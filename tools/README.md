# Decoders

Pure standard library. No numpy, no pip, nothing to install.

```
python3 decode_csv.py capture.csv        # preferred
python3 decode_bin.py capture.bin        # if you already have a binary export
```

Both print a per-channel byte count with **bad stop bits**, then every frame in
time order with its direction and message type.

## Analyser settings

| Setting | Value |
|---|---|
| Sample rate | **8 MSa/s** |
| Sample depth | 500 MSa (= 62 s) |
| Channels | **only the two in use** — the rate ceiling depends on active count |
| Threshold | default is fine; the LA1010 takes 5 V directly |
| Export | **CSV** |

CH0 on the AC's transmit line (red), CH1 on the module's (black).

## Two numbers tell you if a capture is good

- **bad stop bits** should be **0**
- **length-byte mismatches** should be **0**

Anything else means the decode is wrong, and the decode is wrong far more often
than the capture is.

## If you see bad stop bits

Check `BYTE_SKIP_BITS` before you touch the hardware. This bus leaves only
**~0.4 bit** of idle between bytes, so a decoder that skips 10.5 bit times after
each byte eats the next start edge and re-locks mid-byte. The value must stay
**under 10.0**; 9.5–9.8 all work.

A 27% bad-stop rate here was diagnosed as signal integrity, blamed on the probe
threshold, and cost a re-capture — before turning out to be exactly this.

**The tell:** dump the run lengths. If every LOW run is a clean integer multiple
of the bit time while HIGH runs come out at 1.39 / 2.39 / 2.41, that is
inter-byte idle, not a distorted signal. Real signal-integrity problems distort
**both** polarities.

## If you see no bytes at all

The waveform decides the baud rate, not the decoder setting. `decode_csv.py`
prints a pulse-width census for exactly this reason — if 115200 does not claim
essentially every pulse, you are not looking at this protocol.
