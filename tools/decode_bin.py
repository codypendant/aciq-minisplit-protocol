#!/usr/bin/env python3
"""
Decode a Kingst LA1010 *binary* export into A5 protocol frames.

    python3 decode_bin.py capture.bin [--rate 8000000]

Prefer the CSV export. This bus is idle >99% of the time, so a CSV of
transitions is a few thousand lines where the same capture as binary is ~1 GB
and carries no extra information that matters.

Binary format (no header):
    2 bytes per sample, little-endian
    CH0 = bit 0, CH1 = bit 1
    idle = 0x0003

The sample rate is NOT stored in the file. If --rate is omitted it is inferred
from the shortest run against a 115200 bit time (8.68 us).

Handles a gigabyte without numpy by skipping constant 64K-sample blocks.
"""
import os
import sys

BAUD = 115200
BLOCK = 65536
BYTE_SKIP_BITS = 9.6      # see decode_csv.py -- must stay under 10.0


def transitions(path):
    """Sparse edge list as [(sample_index, value)]."""
    out, last, idx = [], None, 0
    with open(path, "rb") as fh:
        while True:
            raw = fh.read(BLOCK * 2)
            if not raw:
                break
            lo = raw[0::2]                       # low byte holds both channels
            # Whole block unchanged? skip it without touching Python per byte.
            if last is not None and lo[0] == last and lo.count(lo[0]) == len(lo):
                idx += len(lo)
                continue
            for i, v in enumerate(lo):
                if v != last:
                    out.append((idx + i, v))
                    last = v
            idx += len(lo)
    return out, idx


def infer_rate(trans):
    runs = sorted(trans[i + 1][0] - trans[i][0] for i in range(len(trans) - 1))
    if not runs:
        return None
    shortest = runs[0]
    raw = shortest / (1.0 / BAUD)
    for cand in (2e6, 4e6, 8e6, 10e6, 16e6, 20e6, 25e6, 50e6, 100e6):
        if abs(shortest / cand * 1e6 - 1e6 / BAUD) < 1.0:
            return cand
    return round(raw)


def channel(trans, bit):
    out = []
    for idx, v in trans:
        b = (v >> bit) & 1
        if not out or out[-1][1] != b:
            out.append((idx, b))
    return out


def level_at(cl, i):
    lo, hi = 0, len(cl) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if cl[mid][0] <= i:
            lo = mid
        else:
            hi = mid - 1
    return cl[lo][1]


def decode(cl, spb):
    out, k = [], 0
    while k < len(cl):
        if cl[k][1] == 0 and level_at(cl, cl[k][0] + spb * 0.5) == 0:
            st = cl[k][0]
            val = 0
            for b in range(8):
                if level_at(cl, st + spb * (1.5 + b)):
                    val |= 1 << b
            ok = bool(level_at(cl, st + spb * 9.5))
            out.append((st, val, ok))
            nxt = st + spb * BYTE_SKIP_BITS
            while k < len(cl) and cl[k][0] < nxt:
                k += 1
            continue
        k += 1
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    if not args:
        print(__doc__)
        return 1

    path = args[0]
    print(f"{path}: {os.path.getsize(path):,} bytes")
    trans, nsamp = transitions(path)
    print(f"{nsamp:,} samples, {len(trans):,} transitions")

    rate = None
    for f in flags:
        if f.startswith("--rate"):
            rate = float(f.split("=")[1])
    if rate is None:
        rate = infer_rate(trans)
        print(f"inferred sample rate: {rate/1e6:.0f} MSa/s "
              f"({nsamp/rate:.1f} s capture)")
    spb = rate / BAUD

    frames = []
    for bit, tag in ((0, "AC "), (1, "MOD")):
        cl = channel(trans, bit)
        if len(cl) < 3:
            print(f"{tag}: idle")
            continue
        byts = decode(cl, spb)
        bad = sum(1 for _, _, ok in byts if not ok)
        print(f"{tag}: {len(cl)} edges -> {len(byts)} bytes, {bad} bad stop")
        cur = []
        for s, v, ok in byts:
            if cur and s - cur[-1][0] > 0.002 * rate:
                frames.append((cur[0][0], tag, bytes(x for _, x in cur)))
                cur = []
            cur.append((s, v))
        if cur:
            frames.append((cur[0][0], tag, bytes(x for _, x in cur)))

    frames.sort()
    bad_len = sum(1 for _, _, f in frames if len(f) < 8 or f[7] != len(f))
    print(f"\n{len(frames)} frames, {bad_len} length-byte mismatches\n")
    for s, tag, f in frames:
        kind = "REPORT" if len(f) > 3 and f[3] == 0x21 else \
               "ACK   " if len(f) > 3 and f[3] == 0x23 else "?     "
        print(f"{s/rate:8.4f}s {tag} {kind} [{len(f):2d}] "
              f"{' '.join(f'{x:02X}' for x in f)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
