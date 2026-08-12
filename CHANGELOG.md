# Changelog

## 2026-08-11 (later) — a falsified prediction, and input power vindicated

**A prediction we published as a lead, then killed.** The remote manual's
ECO/GEAR ladder ("up to 75 % / 50 % electrical energy consumption") made
`0x32` = 50 in the `0x38` record look like the GEAR percentage, predicting
`0x38 = 01 4B` (75) for LV2 under load. Tested at **80 % compressor / 900 W**:
**LV2 released the limiter instead.** No payload other than `0x32` has ever been
seen. The earlier "LV2 just needs more load to bite" excuse is also dead — it
was tested at 80 % and failed.

Corrected: **only LV1 engages the limiter**, at either load tested (48 % and
80 %; at 80 % it pulled compressor target to 38 %). What LV2 and LV3 do is
unknown. `0x32` stays unidentified and unlabelled.

**`0x64` IS a function of compressor speed** — this document previously said it
was not. Over 124 pairs with the compressor reading ≤30 s stale, correlation is
+0.69 and the low end is tight: 15 % → 280–300 W, 19 % → 330–350 W, 22 % →
350–370 W, and **exactly 0 W whenever the compressor stops.**

The reason for the earlier wrong call is now documented as a trap:
**`0x64` only updates about every 12 minutes.** Any window shorter than that
contains no update, so power looks frozen and therefore looks decoupled from
load. A 90-second test halved the compressor and `0x64` never moved — that is
the sampling rate, not the physics.

**Also confirmed as composites rather than protocol fields**, joining Turbo:
`MUTE` is simply fan speed 1 (the 1 % step), and `I SET` forces fan to AUTO.
Neither introduces a new field id. The full fan ladder was captured in one
sweep: 1 %, 25 %, 40 %, 55 %, 70 %, 85 %, 100 %, plus 0 = auto.

## 2026-08-11 — the listener kept going deaf, and it was a log call

**If you are building an ESPHome UART sniffer from this repo, read this one.**

The node repeatedly stopped receiving — online over WiFi, globals intact so it
had not crashed, zero rejected frames and zero CRC failures, and no bytes at all
on **both** taps simultaneously. Time-to-deaf was 5, 14, 20, 38 minutes.

**Cause: `ESP_LOGI` per frame, inside the 10 ms lambda that drains both UARTs.**
A ~270-character hex string written to UART0 *and* pushed to every connected API
log client, in the hot path. The loop fell behind, both RX buffers overran, the
ESP32 driver stopped delivering. Both channels share that loop, so they died
together — which is exactly why it looked like a shared-hardware fault, and why
two hardware theories (level shifter, then UART latch-up) were proposed and both
were wrong.

Changing that one call to `ESP_LOGD`:

| | before | after |
|---|---|---|
| time to deaf | 5, 14, 20, 38 min | **9.4 h, zero events** |
| frames | — | 4,221 |
| rejects / CRC failures | — | **0 / 0** |

**`rx_buffer_size` was already 1024 and is not the fix.** That is ~89 ms of
headroom at 115200 — ample until the loop blocks for longer. Do not enlarge it.

**Added**
- Per-channel **raw byte counters**, incremented before any framing. "No frames"
  fits at least four different faults; "no bytes on either channel" narrows it
  at a glance and exonerates the decoder. This is what finally settled it
- A **watchdog** that restarts the node after 120 s of byte-silence, capped at
  3 consecutive attempts. Threshold is evidenced, not guessed: across 9.4 h the
  longest legitimate gap between raw bytes was 60 s, the module heartbeat
- A separate warning path for "bytes arriving but nothing framing" — a CRC or
  alignment fault, which a reboot would *not* fix, so it warns instead
- A **restart button**

**Incidentally validated**: the CRC-16/XMODEM solution was published on the
strength of 105 frames. It has now run 4,221 frames across a continuous 9.4 h
with **zero failures**, and every frame decoded — `Last Unmapped Frame` stayed
empty all night.

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
  mode `0x12`, fan percent `0x72`, ~~blower RPM~~ `0x5C`, airflow
  `0x0E`/`0x11`, clock timestamps `0x41`/`0x42`
  — *`0x5C` was later identified as the **indoor coil thermistor**, and the two
  airflow fields were later found to be swapped; see the entries above*
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
