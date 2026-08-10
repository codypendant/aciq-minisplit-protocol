#!/usr/bin/env python3
"""
Decode a Kingst LA1010 CSV transition export into A5 protocol frames.

    python3 decode_csv.py capture.csv [--baud 115200] [--raw]

Expects the default Kingst CSV layout:  Time[s], Channel 0, Channel 1
with CH0 on the AC's transmit line (red) and CH1 on the module's (black).

No dependencies. Pure standard library.
"""
import sys
from collections import Counter

BAUD = 115200

# Skip forward this many bit times after a byte before hunting the next start
# bit. MUST be under 10.0 -- this bus leaves only ~0.4 bit of inter-byte idle,
# so a 10.5 skip eats the next start edge and re-locks mid-byte, producing
# bogus framing errors that look exactly like a hardware fault.
BYTE_SKIP_BITS = 9.6


def load(path):
    rows = []
    for line in open(path):
        line = line.strip()
        if not line or line.lower().startswith("time"):
            continue
        parts = line.split(",")
        if len(parts) < 3:
            continue
        rows.append((float(parts[0]), int(parts[1]), int(parts[2])))
    return rows


def edges(rows, idx):
    seq = [(r[0], r[idx]) for r in rows]
    out = [seq[0]]
    for x in seq[1:]:
        if x[1] != out[-1][1]:
            out.append(x)
    return out


def level_at(cl, t):
    lo, hi = 0, len(cl) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if cl[mid][0] <= t:
            lo = mid
        else:
            hi = mid - 1
    return cl[lo][1]


def decode(cl, baud):
    """Return [(timestamp, byte, stop_ok)]."""
    bit = 1.0 / baud
    out, k = [], 0
    while k < len(cl):
        if cl[k][1] == 0 and level_at(cl, cl[k][0] + bit * 0.5) == 0:
            start = cl[k][0]
            val = 0
            for b in range(8):
                if level_at(cl, start + bit * (1.5 + b)):
                    val |= 1 << b
            stop_ok = bool(level_at(cl, start + bit * 9.5))
            out.append((start, val, stop_ok))
            nxt = start + bit * BYTE_SKIP_BITS
            while k < len(cl) and cl[k][0] < nxt:
                k += 1
            continue
        k += 1
    return out


def bursts(byts, gap=0.002):
    groups, cur = [], []
    for t, v, ok in byts:
        if cur and t - cur[-1][0] > gap:
            groups.append(cur)
            cur = []
        cur.append((t, v, ok))
    if cur:
        groups.append(cur)
    return groups


def baud_census(cl):
    """Sanity-check the bit rate straight off the waveform."""
    w = []
    for i in range(len(cl) - 1):
        d = (cl[i + 1][0] - cl[i][0]) * 1e6
        if d < 5000:
            w.append(d)
    if not w:
        return
    print("  pulse-width census:")
    for baud in (115200, 57600, 38400, 9600):
        bt = 1e6 / baud
        n = sum(1 for x in w
                if any(abs(x - bt * k) < bt * 0.25 for k in range(1, 12)))
        print(f"    {baud:6d} ({bt:6.2f} us/bit): {n:5d}/{len(w)}")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    if not args:
        print(__doc__)
        return 1
    baud = BAUD
    for f in flags:
        if f.startswith("--baud"):
            baud = int(f.split("=")[1])

    rows = load(args[0])
    print(f"{args[0]}: {rows[-1][0]:.2f} s, {len(rows)} transitions\n")

    frames = []
    for idx, tag in ((1, "AC "), (2, "MOD")):
        cl = edges(rows, idx)
        if len(cl) < 3:
            print(f"{tag}: idle, no edges")
            continue
        print(f"{tag}: {len(cl)} edges")
        baud_census(cl)
        byts = decode(cl, baud)
        bad = sum(1 for _, _, ok in byts if not ok)
        print(f"  -> {len(byts)} bytes, {bad} bad stop bits"
              f"{'   <-- check BYTE_SKIP_BITS' if bad else ''}\n")
        for g in bursts(byts):
            frames.append((g[0][0], tag, bytes(v for _, v, _ in g)))

    frames.sort()
    bad_len = sum(1 for _, _, f in frames if len(f) < 8 or f[7] != len(f))
    print(f"{len(frames)} frames, {bad_len} with a length-byte mismatch\n")

    prev = None
    for t, tag, f in frames:
        gap = f"  (+{(t - prev) * 1000:7.1f} ms)" if prev is not None else ""
        kind = "REPORT" if len(f) > 3 and f[3] == 0x21 else \
               "ACK   " if len(f) > 3 and f[3] == 0x23 else "?     "
        print(f"{t:8.4f}s {tag} {kind} [{len(f):2d}] "
              f"{' '.join(f'{x:02X}' for x in f)}{gap}")
        prev = t

    if "--raw" not in flags:
        print("\ndistinct frames:")
        c = Counter(' '.join(f'{x:02X}' for x in f) for _, _, f in frames)
        for h, n in c.most_common():
            print(f"  x{n:<3} {h}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
