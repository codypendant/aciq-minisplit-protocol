# Changelog

## 2026-08-10 — louvers, generator mode, and two parser corrections

**Corrected — read this if you built anything on the previous field map**
- **`0x11` is the VERTICAL louver and `0x0E` is the HORIZONTAL one.** The
  previous version had the axes swapped, and the state counts with them. The
  earlier claim was inferred from counts in a capture; this one comes from
  pressing all 17 buttons in the app's "Precision Air Flow" screen and reading
  the labels off the screen.
- **`0x95`, `0xBD`, `0xBE`, `0xBF` are WIDE fields**, not narrow. Parsing them
  as narrow produced a real record plus a phantom `00=00` for each — six
  non-existent fields in every state dump. Because `3 + 3 == 6` the frame stayed
  aligned, so nothing downstream ever broke and the bug hid indefinitely.
  `0xA4`, which sits in the middle of that run, **is** genuinely narrow.
- `0x0C` / `0x0D` are **not** the per-axis louver companions previously claimed.
  Neither appeared during any of the 17 louver presses.

**Established**
- Louver encoding, both axes: bit 3 clear = sweeping ("Flow"), bit 3 set =
  parked ("Fix"), bits 0–2 = 1-based index. Gap at `05`–`08` is the tell
- All 17 louver positions named against the app's own labels
- **Generator mode = `0x2D`** — `0` off, `1` LV1, `2` LV2, `3` LV3. A compressor
  power limiter. LV1 is the restrictive end, confirmed by watching it pull
  compressor target 48 % → 42 %
- **`0x38` uses the same length-prefixed encoding as `0x39`**, and appears only
  while the limiter is engaged. Tracks engagement, not level
- **Turbo is a composite, not a field** — fan to 7/100 %, fan-auto off,
  compressor target raised, both louvers to `0x08`; all of it reverts on release
- A width discriminator that does not rely on plausibility: walk a record both
  ways and keep the reading that lands on a real next id
- Full state dumps arrive roughly **hourly**; button presses trigger
  single-field reports, not dumps

**Open**
- `0x08` on both louver axes — seen only during Turbo, one observation, left
  deliberately unnamed
- `0x17`, `0x35`, `0x47`, `0x48`, `0x5E`, `0x74`, `0xA4`, `0xC9`, `0x95`,
  `0xBD`–`0xBF` — none respond to any user-facing control
- `0x3D` has never actually been observed
- What `0x32` means in an engaged `0x38` record. Not a percent
- I Feel and I Set produced nothing attributable; needs a re-run at wider spacing

## 2026-08-09 — initial release

Protocol decoded from four logic-analyser captures and a live listener.

**Established**
- 115200 8N1, `0xA5` framing. 9600 ruled out by pulse census (2347/2347 vs 0/2347)
- Frame layout: header, link flag, message type, counter, length byte, check field
- Message types `0x21` report / `0x23` acknowledgment; ACK echoes the counter at ~50 ms
- Payload record encoding, including the 2-byte final record and 32-bit wide fields
- Power `0x01`, setpoint `0x02`, room temperature `0x03`, fan `0x05`,
  mode `0x12`, fan percent `0x72`, blower RPM `0x5C`, airflow `0x0E`/`0x11`,
  clock timestamps `0x41`/`0x42`
- Setpoint and room temperature are centi-degrees **Celsius**; the °F byte is a
  rounded display label
- Power-on emits a complete state dump unasked

**Shipped**
- `esphome/aciq-listen.yaml` — dual receive-only tap, no transmit pin wired
- `tools/` — dependency-free Kingst CSV and binary decoders

**Open**
- The 16-bit check field. Not a standard CRC16; see `PROTOCOL.md`
- Mode value → name mapping (five values confirmed, meanings unverified)
- Outdoor coil temperature, if it is on this bus at all
- Transmit path
