# Working on this repo

This documents a UART protocol reverse-engineered from an **ACiQ K18W** mini
split. It is **public**, and it exists for a specific reason the owner stated:

> these projects weren't very well documented online, I would like to make this
> information available so other people don't have to go through all the trouble
> that we went through.

Write for **a stranger who owns this hardware and is stuck**, not as personal
notes. That framing decides most style questions.

## Non-negotiables

- **No personal information.** No real IPs, MACs, module serials, SSIDs, emails,
  or tokens. Placeholder IPs marked `CHANGE ME` are fine.
- **ESPHome configs use `!secret` for every credential**, including the fallback
  AP password.
- **No vendor firmware, artwork, or manual PDFs.** The companion repo had four
  ACiQ/Midea assets purged from its git history before going public. Do not
  reintroduce that category of content here.
- **GPIO17 stays disconnected** in every published wiring diagram and config
  until transmit is deliberately, separately documented as such. Listen-only is
  a safety property of this build, not an incidental detail.
- **`CN-16` is 5 V logic.** Any wiring guidance must keep the level shifter and
  must keep the yellow=+5V / white=GND warning, because the harness colours do
  not follow convention and transposing them puts 5 V into a GPIO.

## Evidence standards

This repo's value is that its claims are *measured*. Protect that.

- **State how a thing was established**, not just what it is. "Outdoor air, not
  coil — it climbed monotonically with the sun and never jumped at compressor
  start" is worth more than "outdoor air temperature".
- **A plausible range is not evidence.** Field `0x5C` was labelled "blower RPM"
  for two days because 1400–2300 looks like a fan. It is the indoor coil
  thermistor. It was caught only by checking a *boundary*: a fan reads zero when
  it stops, a coil warms to ambient. Check boundaries, not plausibility.
- **A value stuck at a constant is a parse bug until proven otherwise.** Field
  `0x72` published a constant 0 because a wide field was being read as narrow.
- **Mark unverified things unverified.** Mode values `0x12` = 0–4 are exposed as
  a raw integer precisely because which number means "heat" was never confirmed.
  A guess here produces an entity that heats when asked to cool.

## Things already tried — do not redo them

- **9600 baud / `0xBB` framing / `55 AA`.** Every published TCL and Tuya
  component targets those. This unit is 115200 8N1 with `0xA5`. Ruled out by a
  pulse-width census: 2347/2347 pulses match 115200, 0/2347 match 9600.
- **Guessing CRC parameters.** Seven polynomials, both bit orders, both byte
  orders, every contiguous span — all failed, for two days. See below.

## The checksum, and the lesson in it

```
CRC-16/XMODEM — poly 0x1021, init 0x0000, MSB-first, no final XOR
region: the entire frame with bytes 8-9 REMOVED (not zeroed)
```

Every failed attempt **zeroed** the check field. Zeroing leaves two extra bytes
in the shift register, which makes the counter byte appear to fit CRC-1021 at a
tail two shorter than its position while the payload fits nothing at all. That
produces a very convincing wrong conclusion: "the counter is protected by
something CRC-shaped and the payload is folded in some other way."

**What actually solved it:** stop guessing parameters and solve the check field
as a **GF(2) linear system** over the individual bits of the bytes that vary,
across ~80 frames. The solution reproduces every frame exactly, and its per-bit
contributions are visibly a 0x1021 shift register. Then compare each byte's
*effective* tail against its *positional* tail — a constant 2-byte discrepancy
before the check field and none after it names the hole immediately.

Generalise that: **when a checksum resists parameter search, recover the linear
map instead.** It cannot lie about structure.

Use `tools/crc.py` rather than reimplementing.

## Style

- Tables for field maps and comparisons; they are what readers scan for.
- Keep the "dead ends" material. `METHOD.md` exists so nobody repeats two days
  of work, and the wrong turns are the most valuable part of it.
- Say plainly where the project stops. The README's "Where this stops" section
  is a feature — an honest boundary is more useful than an implied capability.
- Cross-link the companion repo, and keep saying the two ACiQ units share
  nothing but a brand. That assumption is the natural one and it is wrong.

## Related

The ducted air handler lives in
[aciq-local-control](https://github.com/codypendant/aciq-local-control) — RS-485
XYE, completely different OEM hardware.
