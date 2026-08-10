# ACiQ mini split — local protocol

Reverse-engineered UART protocol for an **ACiQ K18W** wall-mount mini split
whose only smart interface is a cloud-bound WiFi dongle, plus an ESPHome node
that decodes the appliance's own bus into Home Assistant sensors **without
transmitting a single byte**.

The unit ships with a **TCL WBR1** WiFi module on the indoor board's `CN-16`
header. It talks to TCL's servers and nothing else — no LAN protocol, no local
API. The bus between that module and the mainboard, however, carries everything:
power, mode, setpoint, room temperature, fan speed, blower RPM.

This documents that bus.

> **Status: read-only, and honest about it.** The listener decodes live state
> today. Writing to the bus is *not* implemented — the frame checksum is still
> unsolved. See [Where this stops](#where-this-stops).

## The protocol is not the one every guide says it is

Every published TCL air-conditioner project targets **`0xBB` framing at 9600
8E1**. Search results, forum threads, and three separate ESPHome components all
agree on it. The connector name matches. The vendor matches.

**It is not this unit's protocol**, and following that assumption cost an entire
evening.

| | TCL (`tclac`, ESPHome-TCLAC) | Midea (SmartKey) | Tuya WBR1 standard | **This unit** |
|---|---|---|---|---|
| Baud | 9600 | 9600 | — | **115200** |
| Parity | **8E1** | 8N1 | — | **8N1** |
| Header | `0xBB` | `0xAA` | `55 AA` | **`0xA5`** |
| Length | fixed 31 B | length byte | length byte | **length byte, 12–93 B** |
| Checksum | XOR of preceding | 8-bit sum | 8-bit sum | **16-bit, unsolved** |
| Handshake | none | none | none | **counter + explicit ACK** |

The module is **Tuya silicon running TCL firmware** — a Tuya WBR1 (RTL8720CF)
carrying `rtl8720cf_..._tcl_home_...` firmware strings. So the hardware being a
documented Tuya part tells you nothing about the wire format. The firmware
decides, and this firmware speaks something private.

9600 was ruled out by measurement, not opinion: a pulse-width census of the raw
capture found **2347 of 2347 pulses matching a 115200 bit time and 0 of 2347
matching 9600**.

### Prior art: there wasn't any

Searching before and during (August 2026) turned up **no published description
of an `0xA5` @ 115200 air-conditioner protocol**. Not a forum post, not a repo,
not a datasheet. The nearest things that exist all describe different protocols:

- **[adaasch/AC-hack](https://github.com/adaasch/AC-hack)** — TCL/Kesser UART
  notes. The `0xBB` 9600 8E1 family.
- **[sorz2122/tclac](https://github.com/sorz2122/tclac)**,
  **[lNikazzzl/tcl_ac_esphome](https://github.com/lNikazzzl/tcl_ac_esphome)**,
  **[xaxexa/ESPHome-TCLAC](https://github.com/xaxexa/ESPHome-TCLAC)** — working
  components for that family. None apply here.
- **[reneklootwijk/midea-uartsniffer](https://github.com/reneklootwijk/midea-uartsniffer)**
  — Midea SmartKey dongle, `0xAA` @ 9600.
- **[Tuya's own WBR1 MCU serial docs](https://developer.tuya.com/en/docs/iot/wbr1-module-mcu-serial-communication-instructions?id=K9pfdx6h4clku)**
  — `55 AA`. The module is a WBR1 and does **not** use this.

If you found this repo by searching for `A5 01 01 21`, that is why it exists.

## What is in here

| | |
|---|---|
| **[`PROTOCOL.md`](PROTOCOL.md)** | The complete wire format: framing, message types, the ACK handshake, record encoding, and the full field map with units |
| **[`METHOD.md`](METHOD.md)** | How it was decoded, what the dead ends were, and the analyser settings that actually work. Read this before decoding a different unit |
| **[`esphome/aciq-listen.yaml`](esphome/aciq-listen.yaml)** | The listener. Two receive-only taps, no transmit pin connected |
| **[`tools/`](tools/) ** | Pure-python decoders for Kingst LA1010 CSV and binary exports. No numpy, no dependencies |

## What it gives you

Live Home Assistant sensors, decoded from the appliance's own reporting:

| Entity | Source | Notes |
|---|---|---|
| Room Temperature | field `0x03` | Emitted **unprompted every ~60 s** — this is what makes a real climate entity possible |
| Setpoint | trailing byte | °F as the remote displays it |
| Power | field `0x01` | |
| Mode | field `0x12` | Raw 0–4; see [the caveat](#the-mode-names-are-deliberately-not-mapped) |
| Fan Speed | field `0x05` | 1–7, and **0 = auto** |
| Fan Percent | field `0x72` | 1 / 25 / 40 / 55 / 70 / 85 / 100 |
| Blower RPM | field `0x5C` | 1000–2300 observed |
| Outdoor Temperature | field `0x60` | Cross-checked against an independent outdoor sensor |
| Compressor | field `0xC0` | Operating frequency in Hz; 0 when off |
| Frames Decoded / Rejected | — | Health check. Rejected should stay at zero |
| Last Frame / Unknown Fields | — | The mapping queue for anything not yet identified |

**The AC reports state on its own.** It does not need to be polled. That single
property is why a read-only node is useful rather than a stepping stone — no
dead reckoning, no drift, and it sees changes made from the remote, the app, or
the unit's own buttons.

## Why listen-only is the right first build

The transmit pin is **not connected**. Not disabled in software — physically
absent from the wiring.

That is not timidity. This appliance is mounted at ceiling height, the harness
must be cut to tap it, and a malformed frame on a bus you only partly understand
is a genuinely bad idea when the failure mode involves a ladder and a teardown.
A listener also runs for days while you use the unit normally, which is how the
field map got finished — the analyser only ever gave 25- and 62-second windows.

Add control to a parser you already trust. Not before.

## Hardware

**`CN-16` is 5 V logic.** Measured with a meter, and independently reported by
others on the same connector. ESP32 GPIOs are **not** 5 V tolerant. A level
shifter is mandatory — though for receive-only a plain 10k/20k divider per line
is electrically sufficient.

The harness colours **do not follow convention**:

| Wire | Carries | |
|---|---|---|
| **Yellow** | **+5 V** | Not red |
| **White** | **Ground** | Not black |
| **Red** | AC transmits → your RX | |
| **Black** | Module transmits | Tap to watch the app's commands |

Transposing yellow and red puts 5 V straight into a GPIO. **Meter them.**

```
   HARNESS              LEVEL SHIFTER            ESP32
   YELLOW  +5V ───────── HV
   WHITE   GND ───────── GND ─────────────────── GND
                         LV  ─────────────────── 3V3
   RED   (AC TX) ─────── HV1 : LV1 ───────────── GPIO16
   BLACK (mod TX) ────── HV2 : LV2 ───────────── GPIO4
                                                 GPIO17  ── nothing
```

Notes that cost time:

- **The shifter needs both rails.** HV from harness +5 V, LV from the ESP32's
  3V3. Missing either and it passes nothing while looking perfectly healthy.
- **The dongle stays plugged in**, so each tapped line has to continue *and*
  branch — that needs **3-conductor** lever connectors (WAGO 221-413), not the
  2-conductor 221-412.
- **Power the ESP32 from USB** during this work, and never from USB and CN-16
  5 V simultaneously.
- `CN-16` is bare 2.0 mm male pins with a polarising key; DuPont does not fit.
  Cut and reuse the factory harness rather than hunting a mating connector.

## Quick start

1. Wire it as above. Confirm nothing is on GPIO17.
2. Put `wifi_ssid`, `wifi_password` and `ap_fallback_password` in your ESPHome
   `secrets.yaml`.
3. Flash `esphome/aciq-listen.yaml` over USB with the CN-16 5 V lead
   disconnected.
4. Read the boot log for your chip revision. The config sets
   `minimum_chip_revision: "3.1"` — **change it to match your board** or it may
   not boot.
5. Adopt the device in Home Assistant.
6. Watch **Frames Decoded** climb and **Frames Rejected** stay at zero.

If frames never arrive, check the shifter rails first. It is almost always the
shifter rails.

## The mode names are deliberately not mapped

Field `0x12` has exactly five values, `00`–`04`, confirmed by cycling the app
through auto / cool / dry / fan / heat. **Which number is which mode was never
verified**, so the entity exposes the raw integer.

Guessing would produce an entity that looks correct and heats when asked to
cool. Watch your own unit, then map it. It takes a minute and it is your
hardware, not mine.

The same applies to `0x0E` / `0x11`, the two multi-position airflow controls
(8 and 9 positions). They were decoded far enough to prove the record encoding
and then deliberately left alone.

## Where this stops

**The 16-bit check field at bytes 8–9 is unsolved.**

It is not a textbook CRC16. Attacks that failed, so you do not repeat them:

- All standard CRC16 polynomials (`0x1021`, `0x8005`, `0x3D65`, `0xA001`,
  `0x8408`, `0x0589`, `0xC867`), both bit orders, both byte orders.
- Every contiguous span and end-offset, with the check field zeroed and not.
- Solving `init` by GF(2) linear algebra across 16 clean frames from both
  directions simultaneously.

What *is* known, and is the thread worth pulling:

- The field is **linear over GF(2)** with respect to the counter byte —
  `chk(1)^chk(3) == chk(5)^chk(7)` exactly. That is a CRC's signature.
- The counter's contribution matches **CRC-16/CCITT (`0x1021`) exactly**, at a
  tail length placing the region end at `len-2`, verified on a pair of frames
  with byte-identical payloads.
- **Payload changes do not follow the same rule.** No contiguous region
  reproduces them.

So the counter is protected by something CRC-1021-shaped and the payload is
folded in some other way. Someone with fresh eyes may see it immediately.

Receiving does not need it — header, length byte and the ACK counter echo frame
the stream reliably. Transmitting does.

## Roadmap

**Solve the check field.** Everything else waits on it — see
[the state of play](#where-this-stops). More frames with varied payloads is
exactly what that analysis was short of, and the listener now collects them
continuously.

**Settle whether `0x60` is outdoor air or outdoor coil.** It reads plausibly
either way; an overnight log distinguishes them, since air falls steadily and a
coil jumps with compressor cycles.

**Map the mode values** to auto / cool / dry / fan / heat by observation.

**Transmit, then a real climate entity.** Wire black to the ESP32's TX through
the shifter and drive the bus. Command values must be sent in **centi-°C**, not
°F.

**Final hardware:** a 30-pin ESP32 with no headers soldered, mounted inside the
original WiFi dongle's shell so the installation is externally indistinguishable
from stock. The board this was developed on is a header-equipped devkit taped
out of the way — fine for a bench, not for a sealed unit near a blower.

## Repository layout

```
README.md                    this file
PROTOCOL.md                  wire format and field map
METHOD.md                    how it was decoded, and the dead ends
esphome/aciq-listen.yaml     the listener
tools/decode_csv.py          Kingst LA1010 CSV -> frames
tools/decode_bin.py          Kingst LA1010 binary -> frames
tools/README.md              analyser settings that work
```

## Hardware this was built on

- **ACiQ `ACIQ-K18W-W-32-HP2300`** — 18k BTU single-zone wall-mount heat pump,
  **multi-speed DC inverter**. That matters when reading the telemetry: the
  compressor modulates continuously rather than cycling on and off, which is why
  `0xC0` sweeps 30–82 Hz instead of reporting a single running value
- WiFi module: **TCL `WBR1`**, silkscreen `TCLWBR V1.0.0`, RTL8720CF
- Analyser: **Kingst LA1010** (−50 V to +50 V inputs, so it clips straight onto
  5 V logic)
- ESP32 DevKit, 4-channel bidirectional level shifter

ACiQ is a house brand; the mini split and the ducted units are **not** the same
platform. The ducted air handler in the companion project uses an RS-485 XYE
bus and shares nothing with this — different OEM, different bus, different
protocol, same badge on the front.

## Companion project

**[aciq-local-control](https://github.com/codypendant/aciq-local-control)** —
the ducted ACiQ / Midea air handler, brought under local control over its RS-485
**XYE** service bus, with a pixel-matched Lovelace replica of the TL04-1 wall
thermostat.

Same house brand, entirely different hardware underneath. Worth reading if you
have ACiQ equipment and are not sure which of the two you own: if it is a ducted
unit with a wall thermostat, that is the one you want.

## Licence

MIT — see [`LICENSE`](LICENSE). All original work: captures, analysis, code and
documentation. No vendor firmware, artwork or documentation is redistributed
here.
