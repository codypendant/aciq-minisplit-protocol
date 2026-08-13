# ACiQ mini split — local protocol

Reverse-engineered UART protocol for an **ACiQ `ACIQ-K18W-W-32-HP2300`**
wall-mount mini split whose only smart interface is a cloud-bound WiFi dongle,
plus an ESPHome node that decodes the appliance's own bus into Home Assistant —
and, if you want it, replaces the dongle outright for local control with no
cloud.

The unit ships with a **TCL WBR1** WiFi module on the indoor board's `CN-16`
header. It talks to TCL's servers and nothing else — no LAN protocol, no local
API. The bus between that module and the mainboard, however, carries everything:
power, mode, setpoint, room and coil temperatures, outdoor air temperature, fan
speed, louver positions, compressor speed and input power.

This documents that bus.

> **Status: local control works, proven on hardware 2026-08-13.** The dongle was
> removed, the ESP32 took over `CN-16`, and a setpoint command from Home
> Assistant moved the value on the unit's own display. Zero CRC failures.
>
> **Both configurations are supported and documented.** Listen-only keeps the
> dongle and the vendor app and transmits nothing; the takeover replaces the
> dongle and gives you control without cloud. Pick one — they are mutually
> exclusive for a hardware reason. See [Two configurations](#two-configurations).

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
| Checksum | XOR of preceding | 8-bit sum | 8-bit sum | **CRC-16/XMODEM over a region with a hole in it** |
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
| **[`tools/`](tools/)** | Pure-python decoders for Kingst LA1010 CSV and binary exports. No numpy, no dependencies |

## What it gives you

Live Home Assistant sensors, decoded from the appliance's own reporting:

| Entity | Source | Notes |
|---|---|---|
| Room Temperature | field `0x03` | Emitted **unprompted every ~60 s** — this is what makes a real climate entity possible |
| Setpoint | `02 27` param | °F as the remote displays it. The unit thinks in **centi-°C** |
| Power | field `0x01` | |
| Mode | field `0x12` | Named + raw; see [mode values](#mode-values--mapped-and-verified) |
| Fan Speed | field `0x05` | 1–7, and **0 = auto** |
| Fan Percent | field `0x72` | 1 / 25 / 40 / 55 / 70 / 85 / 100 |
| Fan Auto | field `0x73` | |
| Vertical Louver | field `0x11` | Named positions — 3 sweep + 5 fixed. See [Louvers](PROTOCOL.md#louvers) |
| Horizontal Louver | field `0x0E` | Named positions — 4 sweep + 5 fixed |
| Indoor Coil Temperature | field `0x5C` | Evaporator; 10–13 °C while cooling |
| Outdoor Temperature | field `0x60` | Ambient air, confirmed under compressor load |
| Compressor Target | field `0xC0` | Commanded speed, % |
| Compressor Actual | field `0x65` | Ramps to meet the target, % |
| Power Usage | field `0x64` | Watts, quantised to 10. **Updates only ~every 12 min** — see [Input power](PROTOCOL.md#input-power) |
| Eco Mode | field `0x13` | |
| Sleep Mode | field `0x22` | Named + raw — off / standard / the aged / child |
| Display Light | field `0x1E` | The indoor unit's LED display |
| Beep · Health · Drying | `0x25` `0x15` `0x27` | |
| Generator Mode | field `0x2D` | off / LV1 / LV2 / LV3. Only LV1 actually limits |
| Power Limit | field `0x38` | Engaged / released, while the limiter bites |
| Capability List | field `0x39` | Length-prefixed, and **it changes at runtime** |
| Module WiFi Signal | `02 64` param | dBm, reported by the module itself |
| Frames Decoded / Rejected / CRC Failures | — | Health. Rejected and CRC failures should stay at zero |
| RX Bytes AC / Module | — | Raw bytes per tap, counted **before** framing. See [gotcha 5](METHOD.md#5-logging-every-frame-at-info--it-silently-wedges-the-uart) |
| Last Command | `0A 0A` frames | What the **app** asked for. Remote presses never appear here — they arrive over IR and only show as state changes |
| Wide Fields | — | Unclaimed 32-bit fields, with a centi-°C reading alongside so a thermistor is obvious |
| Last Frame · Last Unmapped · Unknown Fields | — | The mapping queue for anything not yet identified |

**The AC reports state on its own.** It does not need to be polled. That single
property is why a read-only node is useful rather than a stepping stone — no
dead reckoning, no drift, and it sees changes made from the remote, the app, or
the unit's own buttons.

### Controls — takeover configuration only

These exist in the config either way, but they **cannot transmit** unless
`Transmit Enabled` is on, and turning that on with the dongle still installed is
the one thing that damages hardware. See [Two configurations](#two-configurations).

| Entity | Sends | Notes |
|---|---|---|
| **Transmit Enabled** | — | The interlock. Every transmit path is gated on it, and the single UART write lives behind it |
| **Set Setpoint** | `0x02` + `p0x27` | **Absolute, in °F.** Prefer this — it needs no prior state |
| **Power On** / **Power Off** | field `0x01` | Absolute, same reason |
| **Set Mode** | field `0x12` | auto / cool / dry / fan / heat. **Untransmitted so far.** Selecting dry also forces a fan speed |
| **Set Fan** | `0x73` + `0x05` | auto / mute / 2–7. **Untransmitted so far** |
| Setpoint Up / Setpoint Down | `0x02` + `p0x27` | **Relative** — they read current state and step it, so they refuse to act when the setpoint is unknown |
| Power Toggle | field `0x01` | Relative, same caveat |
| **Frames Sent** | — | Should be **0** until you deliberately enable transmit |
| **ESP WiFi Signal** | — | Ours, sent to the AC in the module heartbeat. Distinct from Module WiFi Signal, which after takeover is this value echoed back off the wire |

> **Relative controls are a trap after a reboot.** The AC reports only what
> *changes*, so unchanged fields have no value at all until something moves
> them. The relative controls log a warning and send nothing rather than
> computing a command from a missing value — an early build did not, and
> transmitted the clamp floor. **Use the absolute controls**, or press one
> button on the handheld to make the unit report.

## Two configurations

**They are mutually exclusive, and the reason is electrical, not political.**
Harness BLACK is the *module's* transmit output. An ESP32 driving it while the
dongle is still plugged in puts two push-pull outputs on one net, which damages
drivers rather than merely misbehaving. One thing owns that wire.

| | **Listen-only** | **Takeover** |
|---|---|---|
| Stock dongle | stays in `CN-16` | removed |
| ESP32 `GPIO17` | **not connected** | drives harness BLACK |
| Vendor app | keeps working | gone |
| Local telemetry | ~30 entities | ~30 entities |
| Local control | none | **yes, no cloud** |
| Appliance modified | no | no — the dongle plugs back in |

### Listen-only

The transmit pin is physically absent from the wiring — not disabled in
software. The stock dongle stays plugged in and keeps working, including the
app diagnostics the bus does not expose, and Home Assistant still gets the
thirty-odd entities the dongle never surfaces: coil temperature, compressor
commanded vs actual, input power, outdoor air, louver positions, feature flags.

This is a legitimate endpoint, not a stage. If you want the app, stop here.

### Takeover

The dongle comes out and the ESP32 becomes the module. You lose the app and the
self-check it offers. You gain setpoint, power, mode and fan control with
nothing leaving your network.

**Replacing the module means inheriting its obligations, not just its wire.**
The node must ACK every report ~50 ms later, answer the clock request, and send
the periodic RSSI heartbeat. This is not optional politeness: an unacknowledged
mainboard **retries hard** — measured at ~75 frames/min with nothing answering,
against ~3.5/min once the ACKs start. See
[The ACK handshake](PROTOCOL.md#the-ack-handshake).

**It is reversible.** Nothing is cut that the listen-only build did not already
cut; the dongle plugs back into `CN-16`. If you go back, **unwire `GPIO17` or
reflash a listen-only config first** — otherwise the next reboot drives BLACK
against the dongle's own output.

<details>
<summary>The way to have both, if you insist</summary>

The module only transmits ACKs, roughly 50 ms after each AC frame, so the line
is idle most of the time. A series resistor (~1 kΩ) on the ESP's TX limits fault
current to about 3 mA if both ever drive simultaneously, which makes contention
harmless rather than destructive, and you transmit only inside known-idle
windows. This is a real technique, not a bodge — but it adds a failure mode, and
it is not what this repo builds.

</details>

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

**If frames never arrive — or arrive and then stop — read `RX Bytes AC` and
`RX Bytes Module` before touching the wiring.** They count raw bytes *before*
any framing, so they separate faults that otherwise look identical:

| | |
|---|---|
| Bytes rising, frames flat | framing or CRC — the wiring is fine |
| Bytes flat on **one** tap | that tap's wire |
| Bytes flat on **both** | shared supply/ground, or the loop is stalling |

An earlier version of this file said "it is almost always the shifter rails."
That advice cost an evening. The tap on this build went deaf repeatedly and the
cause was **logging every frame at INFO inside the read loop**, which starved
the UARTs — not the shifter, not the buffer size. See
[gotcha 5](METHOD.md#5-logging-every-frame-at-info--it-silently-wedges-the-uart)
before suspecting hardware.

## Mode values — mapped and verified

| raw | mode |
|---|---|
| `0` | auto |
| `1` | cool |
| `2` | dry |
| `3` | fan |
| `4` | heat |

Established by pressing each mode in the app and reading the resulting **command
frame**, not by watching what the unit did. Cool is double-confirmed: it was the
power-on state and the value the closing press returned.

The entity exposes both a named **Mode** and the raw integer. The raw one stays
because the mapping is verified but the number cannot be wrong.

**Caveat worth carrying into a write path:** selecting dry also forces a fan
speed (`12=02` arrives with `05=02`). Setting mode alone may change more than
mode.

### Louvers — and a correction

`0x11` is the **vertical** louver (8 buttons) and `0x0E` is the **horizontal**
one (9). Earlier versions of these documents had that **backwards**, having
inferred the axes from state counts in a capture rather than checking. Both
axes share one encoding — bit 3 clear means sweeping (the app's "Flow"), bit 3
set means parked ("Fix"), and bits 0–2 are a 1-based index. Full table in
[PROTOCOL.md](PROTOCOL.md#louvers).

**Turbo is not a field.** It is a macro: fan to speed 7 / 100 %, fan-auto off,
compressor target raised, both louvers to `0x08`. Everything reverts when it is
switched off.

## Where this stops

**Nothing structural is unsolved any more.** Framing, message types, the ACK
handshake, record encoding, the command format and the checksum are all
documented and verified.

Control is no longer on this list — setpoint was commanded successfully on
2026-08-13. What remains:

- **Only setpoint and the ACK/clock/heartbeat obligations are proven on
  hardware.** `Set Mode` and `Set Fan` are written and shipped but **have never
  been sent**. Both are absolute, so neither depends on knowing current state.
- **The command decoder mis-splits the `02` parameter namespace was fixed;
  the report decoder was not.** The command walk now reads namespaces properly.
  The report walk has the same structural blind spot and is left alone because
  it feeds every working entity — it copes today, but it is an audit waiting to
  happen.
- **After a reboot the node is blind to anything that has not changed since.**
  The AC reports deltas, so unchanged fields have no value at all. Absolute
  controls (`Set Setpoint`, `Power On`/`Power Off`) work regardless; the
  relative buttons refuse to act and say so. **No query frame is known** — if
  one exists, finding it is the single highest-value remaining discovery.
- **A handful of ids remain unidentified** — `0x17`, `0x35`, `0x47`, `0x48`,
  `0x5E`, `0x74`, `0xA4`, `0xC9`, and the wide `0x95`, `0xBD`–`0xBF`. **None of
  them responds to any user-facing control**: a sweep of all 17 louver buttons,
  all four generator levels, Turbo, Mute, I Feel and I Set surfaced only two new
  ids. They are most likely diagnostics or configuration, so pressing buttons is
  not the way to crack them.
- **`0x3D`** appears in the "not yet identified" table but **has never actually
  been observed** on this unit.
- **A blower-outlet thermistor** may exist but has never appeared on the bus.

## Roadmap

**Map TIMER**, the last remote button that has not been identified. Sleep is
done — `0x22`, four named values.

**Establish whether I FEEL does anything on this unit.** It is a generic
multi-model remote, and the manual notes that buttons for functions the indoor
unit lacks simply have no effect. Two attempts produced nothing, but both were
invalidated by the listener stalling mid-test, so this is genuinely untested
rather than negative.

**Work out what LV2 and LV3 do.** Only LV1 engages the power limiter, at both
loads tested.

**Send Set Mode and Set Fan**, the two shipped commands never actually
transmitted.

**Find a state-query frame**, if one exists. The app shows full state the
instant it opens, so *something* asks — but no query has been identified on the
bus. Without it, every reboot leaves unchanged fields unknown until the unit
happens to report them.

**A real `climate` entity.** Deliberately not built yet: the plain buttons and
selects exist so each command shape could be proven one at a time. Because the
AC reports its own settled state, this can be a genuinely verified state machine
rather than the optimistic dead reckoning most IR-based integrations do — it can
show what the unit *did*, not what it was told.

## Repository layout

```
README.md                    this file
PROTOCOL.md                  wire format and field map
METHOD.md                    how it was decoded, and the dead ends
CHANGELOG.md                 what changed, and which claims were corrected
esphome/aciq-listen.yaml     the listener, and the takeover controls
esphome/aciq_tx.h            frame construction: CRC, ACK, clock, commands
captures/reference-frames.txt  annotated real frames, one per message type
tools/check-docs.py          documentation drift checks -- run before committing
tools/crc.py                 checksum: verify, compute, apply
tools/decode_csv.py          Kingst LA1010 CSV -> frames
tools/decode_bin.py          Kingst LA1010 binary -> frames
tools/README.md              analyser settings that work
CLAUDE.md                    conventions and evidence standards for this repo
LICENSE                      MIT
```

## Hardware this was built on

- **ACiQ `ACIQ-K18W-W-32-HP2300`** — 18k BTU single-zone wall-mount heat pump,
  **multi-speed DC inverter** — the compressor and air handler each take a
  0–100% speed. That matters when reading the telemetry: the compressor
  modulates continuously rather than cycling on and off, which is why `0xC0`
  sweeps 30–82 instead of reporting a single running value
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
