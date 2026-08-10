#!/usr/bin/env python3
"""ACiQ K18W mini split frame checksum.

CRC-16/XMODEM: polynomial 0x1021, init 0x0000, MSB-first, no final XOR.

The region is the entire frame with bytes 8-9 -- the check field itself --
*** REMOVED, not zeroed ***. That single distinction is what made this
resist solving; see PROTOCOL.md.

    python3 crc.py A5 01 01 21 D6 00 00 12 E2 BC 0C 0C 00 03 00 00 0A 28
    python3 crc.py < frames.txt          # one frame per line
"""
import sys

POLY = 0x1021


def crc16(data: bytes, init: int = 0x0000) -> int:
    c = init
    for b in data:
        c ^= b << 8
        for _ in range(8):
            c = ((c << 1) ^ POLY) & 0xFFFF if c & 0x8000 else (c << 1) & 0xFFFF
    return c


def region(frame: bytes) -> bytes:
    """The CRC region: whole frame minus the two check bytes."""
    return bytes(frame[0:8]) + bytes(frame[10:])


def compute(frame: bytes) -> int:
    """CRC a frame should carry."""
    return crc16(region(frame))


def verify(frame: bytes) -> bool:
    return compute(frame) == (frame[8] << 8) | frame[9]


def apply(frame: bytearray) -> bytearray:
    """Write the correct CRC into a frame you are building."""
    c = compute(frame)
    frame[8] = c >> 8
    frame[9] = c & 0xFF
    return frame


def _parse(text: str) -> bytes:
    return bytes.fromhex(text.replace(" ", "").replace(":", ""))


def main() -> int:
    args = sys.argv[1:]
    lines = [" ".join(args)] if args else sys.stdin.read().splitlines()
    bad = 0
    for line in lines:
        if not line.strip():
            continue
        f = _parse(line)
        if len(f) < 10:
            print(f"too short: {line}")
            bad += 1
            continue
        want = (f[8] << 8) | f[9]
        got = compute(f)
        ok = got == want
        bad += not ok
        print(f"{'ok  ' if ok else 'BAD '} len={len(f):2d} "
              f"carried={want:04X} computed={got:04X}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
