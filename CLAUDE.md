# Working on this repo

This documents a UART protocol reverse-engineered from an
**ACiQ `ACIQ-K18W-W-32-HP2300`** mini
split. It is **public**, and it exists for a specific reason the owner stated:

> these projects weren't very well documented online, I would like to make this
> information available so other people don't have to go through all the trouble
> that we went through.

Write for **a stranger who owns this hardware and is stuck**, not as personal
notes. That framing decides most style questions.

## Before you commit, run the checks

```
python3 tools/check-docs.py
```

Non-zero exit means something drifted. It verifies that every link and anchor
resolves, that the layout block matches the filesystem both ways, that no
retracted claim has crept back in, that the README entity table covers every
entity the config publishes, that every frame in `captures/` still passes
`tools/crc.py`, and that no literal credential reached the published config.

**When a claim is disproved, add its wording to `RETRACTED` in that script.**
That is what stops it reappearing three files away six weeks later. The list
already carries every claim this project has had to withdraw.

This exists because the field map was corrected carefully every single time and
the prose around it never was. A sweep on 2026-08-11 found the frame table still
calling the checksum "Unsolved", the Quick start recommending the debugging dead
end that had cost an evening, an entity table listing 14 of 30+ entities, and a
roadmap asking for work already finished. None of it needed judgement to catch.

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
- **Mark unverified things unverified**, and leave them unnamed in the decoder
  rather than guessing a label. Two live examples: the `0x32` payload in an
  engaged `0x38` record looked exactly like the manual's GEAR "50 %", and the
  prediction that followed from it was **tested and falsified**; and `0x08` on
  both louver fields is published as `unnamed (0x08)` because it has been seen
  in only one situation. `0x12` used to be the example here — it is now verified
  by pressing each mode in the app, which is what promotion out of this list
  should require.
- **A named field is a claim about hardware.** Say how it was established, not
  just what it is, and prefer the check that could have gone the other way —
  a boundary, a cross-reference against the app's own labels, or an effect you
  can watch the machine perform.

## Things already tried — do not redo them

- **9600 baud / `0xBB` framing / `55 AA`.** Every published TCL and Tuya
  component targets those. This unit is 115200 8N1 with `0xA5`. Ruled out by a
  pulse-width census: 2347/2347 pulses match 115200, 0/2347 match 9600.
- **Guessing CRC parameters.** Seven polynomials, both bit orders, both byte
  orders, every contiguous span — all failed, for two days. See below.
- **Blaming hardware when the tap goes deaf.** The level shifter and a UART
  latch-up were both diagnosed confidently and both were wrong. The cause was
  `ESP_LOGI` per frame inside the read loop starving the UARTs. `rx_buffer_size`
  was already 1024 and is not the fix. Check `RX Bytes AC` / `RX Bytes Module`
  first — they count before framing, so they say whether bytes are arriving at
  all. See `METHOD.md` gotcha 5.
- **Reading button presses off the bus.** The remote batches fast presses and
  transmits only the settled value, so eight quick presses look identical to one
  command. Attribution comes from knowing which button was pressed, never from
  the shape of the traffic. See `METHOD.md` gotcha 6.

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

## A C++ trap this config has hit

The record decoder is one big `switch (fid)`. Several case groups deliberately
share a body — the airflow fields, the phantom wide-field halves. **Appending a
new `case` label to the end of such a group silently enrols every label above it
into your new behaviour.**

That exact mistake shipped once: `case 0x13` (eco mode) was added to the end of
the airflow group, so `0x0E`, `0x11`, `0x0C` and `0x0D` all began publishing eco
mode. The symptom was Eco Mode flapping ON → OFF → ON across the three frames of
a single state dump, because different frames end on different members of the
group. It looked like a protocol mystery and was a missing `break`.

When adding a field, give it its own labelled block, and re-read the group above
the insertion point.

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
