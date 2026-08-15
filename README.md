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
> There is a full Home Assistant **`climate` entity** as of 2026-08-15, and it is
> fed from decoded bus frames rather than from the commands it sent — so it shows
> what the unit *did*. See [A verified climate
> entity](#a-verified-climate-entity).
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
| **[`esphome/aciq-k18w.yaml`](esphome/aciq-k18w.yaml)** | The node. Two receive taps, plus the takeover controls behind a transmit interlock that is off on every boot |
| **[`esphome/aciq-k18w-listen.yaml`](esphome/aciq-k18w-listen.yaml)** | The listen-only build, kept deliberately. **Contains no transmit code at all** — not gated, absent. Use it for mapping, and as the rollback |
| **[`esphome/aciq_tx.h`](esphome/aciq_tx.h)** | Frame construction — CRC, length, ACK, clock reply, RSSI heartbeat, commands. Never hand-compute a length or a checksum |
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
| **Thermostat** | all of the below | The HA `climate` entity, from the external component in `esphome/components/aciq_k18w/`. It **reports what the bus reported**, not what it asked for — see [A verified climate entity](#a-verified-climate-entity) |
| **Transmit Enabled** | — | The interlock. Every transmit path is gated on it, and the single UART write lives behind it |
| **Set Setpoint** | `0x02` + `p0x27` | **Absolute, in °F.** Prefer this — it needs no prior state |
| **Power On** / **Power Off** | field `0x01` | Absolute, same reason |
| **Set Mode** | field `0x12` | auto / cool / dry / fan / heat. Proven: cool → auto. Selecting dry also forces a fan speed |
| **Set Fan** | `0x73` + `0x05` | auto / mute / 2–7. Proven: auto |
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
| Flash | `aciq-k18w-listen.yaml` | `aciq-k18w.yaml` |
| Stock dongle | stays in `CN-16` | removed |
| ESP32 `GPIO17` | **not connected** | drives harness BLACK |
| Vendor app | keeps working | gone |
| Local telemetry | ~30 entities | ~30 entities |
| Local control | none | **yes, no cloud** |
| Appliance modified | no | no — the dongle plugs back in |

**Both builds are kept on purpose.** `aciq-k18w-listen.yaml` is not an old
version left lying around — it contains **no transmit code at all**, not merely
disabled transmit. It cannot drive the bus however it is wired or clicked, which
is what makes it the right build for the work described in
[Continuing the mapping](#continuing-the-mapping), and the honest rollback.

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

### Listen-only wiring

```
   HARNESS              LEVEL SHIFTER            ESP32
   YELLOW  +5V ───────── HV
   WHITE   GND ───────── GND ─────────────────── GND
                         LV  ─────────────────── 3V3
   RED   (AC TX) ─────── HV1 : LV1 ───────────── GPIO16
   BLACK (mod TX) ────── HV2 : LV2 ───────────── GPIO4
                                                 GPIO17  ── nothing
```

The dongle stays in `CN-16`, so each tapped line has to continue *and* branch —
that needs **3-conductor** lever connectors (WAGO 221-413), not the 2-conductor
221-412.

### Takeover wiring

One added wire: `GPIO17` through a **spare channel of the same shifter** onto
harness BLACK. Two channels then sit on BLACK, one sensing and one driving —
that is fine, because one is an input and one is an output, and once the dongle
is gone nothing else drives that line at all. BLACK is the module→AC direction;
the mainboard only listens on it.

```
   HARNESS              LEVEL SHIFTER            ESP32
   YELLOW  +5V ───────── HV
                         └────────────────────── VIN     ← see power, below
   WHITE   GND ───────── GND ─────────────────── GND
                         LV  ─────────────────── 3V3
   RED   (AC TX) ─────── HV1 : LV1 ───────────── GPIO16
   BLACK (mod TX) ────── HV2 : LV2 ───────────── GPIO4
   BLACK (driven)  ───── HV3 : LV3 ───────────── GPIO17  ← the only new wire
```

**Order matters, and one ordering damages hardware:**

1. **Flash first.** `Transmit Enabled` is off on every boot and is not restored
   from flash, so the firmware is safe to run with the dongle still installed.
   Confirm **`Frames Sent` = 0** before touching any wiring. If it is not zero,
   stop — the interlock is not working.
2. Wire `GPIO17`. Still safe: the switch is off.
3. **Detach the dongle — check which end.** The requirement is that the
   mainboard and the ESP32 stay joined and the dongle does not. If your tap is
   spliced downstream of `CN-16` (which 3-conductor lever nuts imply), pulling
   the plug at `CN-16` disconnects *you* as well — open the **dongle's**
   conductor on each of the four lever nuts instead. Either way the test is the
   same: `Frames Decoded` must keep climbing.
4. Only now turn `Transmit Enabled` on, and send nothing at first. If the ACK is
   accepted, the AC's frame rate falls from ~75/min to ~3/min — see
   [The ACK handshake](PROTOCOL.md#the-ack-handshake). **Do not read that off
   `Frames Decoded`**: once you transmit, your own frames echo back on the
   module tap and are counted too, so it settles around double the AC's rate.
   Watch `RX Bytes AC` and `RX Bytes Module` separately instead.

Keeping `GPIO4` on BLACK afterwards is deliberate: every frame you send comes
straight back in and is decoded as a module frame, so the log proves your own
transmissions are well-formed. Free verification, no extra parts.

> **If TX is garbage but RX is clean, suspect the shifter, not the firmware.**
> BSS138-style auto-direction boards drive LOW hard and rely on a pull-up for
> the HIGH transition; at 115200 that rise time is marginal. The fix is a
> push-pull buffer (74AHCT125), not more debugging. It did **not** bite on this
> build — two channels on BLACK put ~5 kΩ to +5 V instead of 10 kΩ, which helps
> — but it is the first thing to check.

### Both configurations

- **The shifter needs both rails.** HV from harness +5 V, LV from the ESP32's
  3V3. Missing either and it passes nothing while looking perfectly healthy.
  Note that HV is a *reference*, not a power tap — it is required even when the
  board runs from USB.
- **Power.** USB during bring-up, or harness +5 V to **VIN** — never `3V3`, and
  **never both at once**; back-feeding destroys boards and USB ports. Running
  from `CN-16` means pulling the 5 V lead before every USB flash. A
  **470–1000 µF bulk cap** at the board is worth fitting for WiFi current
  spikes; if the rail sags the ESP32 reboots, which shows up as **Frames
  Decoded restarting from zero** rather than freezing.
- `CN-16` is bare 2.0 mm male pins with a polarising key; DuPont does not fit.
  Cut and reuse the factory harness rather than hunting a mating connector.

## Quick start

**Start here whichever configuration you want** — the takeover is the same node
with one more wire, added *after* this works. Do not wire `GPIO17` yet.

1. Wire the [listen-only](#listen-only-wiring) taps. Nothing on `GPIO17`.
2. Put `wifi_ssid`, `wifi_password` and `ap_fallback_password` in your ESPHome
   `secrets.yaml`.
3. Flash `esphome/aciq-k18w.yaml` over USB with the CN-16 5 V lead
   disconnected.
4. Read the boot log for your chip revision. The config sets
   `minimum_chip_revision: "3.1"` — **change it to match your board** or it may
   not boot.
5. Adopt the device in Home Assistant.
6. Watch **Frames Decoded** climb, **Frames Rejected** stay at zero, and
   **`Frames Sent` stay at zero**. The control entities appear either way; they
   cannot transmit until you deliberately enable them.

That is a complete, useful install. If you also want control, continue to
[Takeover wiring](#takeover-wiring) — and read it in order, because one of the
orderings damages hardware.

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

Control is no longer on this list. **Every command this build ships was proven
on hardware on 2026-08-13** — setpoint, mode, fan, and power both ways, plus the
ACK, clock and heartbeat obligations, with zero CRC failures throughout. What
remains:

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

### Continuing the mapping

**Do this on `aciq-k18w-listen.yaml`, with the dongle back in `CN-16`.** That is
not a downgrade — it is the configuration the entire field map was built in, and
the reason is that **the app is a command generator you do not have to write.**

With the dongle installed and the phone app paired, every button you press in
the app produces a real, correct, vendor-authored `0A 0A` command frame on
harness BLACK. You tap `GPIO4` and read it. No transmitting, no risk of a
malformed frame reaching the mainboard, and no guessing at encodings — the app
shows you what a legitimate command looks like, labelled by the screen you
pressed it on.

That is how `0x12` (mode), the louvers, generator mode and sleep were all
mapped: press one control, read one frame, match it to the label the app itself
uses. Once the takeover is wired, that source disappears — you are the module,
and nothing else generates commands for you to study.

Watch **`Last Unmapped Frame`** and **`Unknown Fields`**; they are the work
queue. Two hard-won rules from [`METHOD.md`](METHOD.md):

- **Press the same button six times, ~5 s apart.** Whatever increments is the
  value; whatever stays constant is the field id. Boundaries guessed from a
  single capture have been wrong repeatedly.
- **Never attribute a frame from its shape alone.** The remote batches fast
  presses and transmits only the settled value, so eight quick presses look
  identical to one command. Attribution comes from knowing which button you
  pressed.

Nine ids remain, listed in [Where this stops](#where-this-stops) — but be warned
that **none of them responded to any user-facing control**, so they are probably
diagnostics or configuration rather than buttons nobody has pressed yet.

**Find a state-query frame**, if one exists. The app shows full state the
instant it opens, so *something* asks — but no query has been identified on the
bus. Without it, every reboot leaves unchanged fields unknown until the unit
happens to report them.

Do not spend an evening on the obvious shortcut: **re-sending `01=01` to an
already-on unit does not trigger the power-on state dump.** Tested and
falsified — the dump belongs to the transition, not to the command. See
[gotcha 8](METHOD.md#8-re-sending-a-command-the-unit-already-satisfies-does-not-refresh-state).

## A verified climate entity

**Built and running since 2026-08-15** — this section used to say "deliberately
not built yet", and that is no longer true. The plain buttons and selects came
first so each command shape could be proven one at a time; the `climate` entity
sits on top of the shapes that were proven.

It lives in [`esphome/components/aciq_k18w/`](esphome/components/aciq_k18w) as a
local external component, wired in with:

```yaml
external_components:
  - source:
      type: local
      path: components
    components: [aciq_k18w]
```

**What makes it different from most AC integrations:** every attribute it
publishes is fed from a decoded bus frame — `set_setpoint_f`,
`set_room_temperature_f`, `set_mode_raw`, `set_fan_state`, `set_power_state`,
`set_compressor_running` are all called from the record decoder, not from the
command path. So the entity shows **what the unit did**, not what it was told.
IR-based integrations cannot do this: with no return path they must dead-reckon,
and they drift the moment anyone touches the handheld.

Round-tripped on hardware 2026-08-15: a setpoint change sent from Home Assistant
appeared on the wire as `02=2600 p27=4F`, the mainboard accepted it, and the
value that came back in the AC's own next report is what the entity displays.

## Repository layout

```
README.md                    this file
PROTOCOL.md                  wire format and field map
METHOD.md                    how it was decoded, and the dead ends
CHANGELOG.md                 what changed, and which claims were corrected
esphome/aciq-k18w.yaml       the node: decoder, and the takeover controls
esphome/aciq-k18w-listen.yaml  listen-only build -- no transmit code at all
esphome/aciq_tx.h            frame construction: CRC, ACK, clock, commands
esphome/components/aciq_k18w/__init__.py     external component: package marker
esphome/components/aciq_k18w/climate.py      external component: config schema
esphome/components/aciq_k18w/aciq_climate.h  the climate entity, declarations
esphome/components/aciq_k18w/aciq_climate.cpp  climate state machine, fed by the bus
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
