# How this was decoded

Written down because the mistakes cost far more time than the successes, and
most of them are the kind anyone would make on the next appliance.

## We guessed the protocol wrong three times before measuring it

This is the whole story in one section, because it is the part most likely to
save someone else a weekend.

**Guess 1 — TCL.** The module is TCL-branded, the connector is `CN-16`, and
three separate ESPHome components exist for "TCL air conditioners" on that exact
connector. All of them use **`0xBB` framing at 9600 8E1**. A config was written
around `sorz2122/tclac` and would have been flashed if parts had arrived sooner.
It could never have worked.

**Guess 2 — Midea.** ACiQ is a house brand and predominantly Midea-sourced; the
ducted air handler in the companion project *is* Midea underneath. So the Midea
`0xAA` @ 9600 SmartKey protocol was the natural second guess. Also wrong — house
brands buy different lines from different OEMs, and one unit being Midea says
nothing about the next.

**Guess 3 — Tuya.** The module turned out to be a **Tuya WBR1** (RTL8720CF), and
Tuya publishes a documented MCU serial protocol for that exact part: **`55 AA`**.
Wrong again. The module is Tuya *silicon* running *TCL* firmware
(`rtl8720cf_..._tcl_home_...`). **The hardware vendor does not determine the wire
format — the firmware does.**

**What it actually is:** `0xA5` framing at **115200 8N1**, matching none of the
three, and matching nothing published anywhere.

### The baud rate: we spent an evening at 9600

Every guess above assumed **9600**. The real rate is **115200** — a factor of
twelve out.

Worse, the correct answer had already been measured and thrown away. An ESP32's
RMT peripheral reported **~8 µs** bit times, repeatedly. That was dismissed as
contact bounce, because the published projects said 104 µs and prior art felt
more trustworthy than a jittery hand-held probe. The analyser later showed
**8.5 µs**, which is 115200 exactly.

Parity compounded it. The TCL projects specify **8E1**, and an 8N1 receiver
reading an 8E1 line produces convincing garbage rather than obvious failure —
roughly half the bytes become framing errors and the rest arrive corrupted.
Chasing that convinced us the wiring was bad when the wiring was fine.

Settling it took a census of the raw waveform rather than another opinion:

| | pulses matching |
|---|---|
| 115200 (8.68 µs) | **2347 / 2347** |
| 9600 (104 µs) | **0 / 2347** |

Decoding the same capture three ways made it final:

| Decode | Bytes | Framing errors |
|---|---|---|
| **115200 8N1** | 499 | **0** |
| 9600 8E1 | 39 | **38** |
| 9600 8N1 | 76 | 37 |

**A decoder setting cannot reveal traffic that is not in the waveform.**
Re-decoding an existing capture at a different baud is always wasted effort —
measure the pulse widths instead.

## Analyser settings that work

**Kingst LA1010.** Its inputs are rated **−50 V to +50 V** with an adjustable
threshold, so it clips directly onto 5 V logic with no shifter.

| Setting | Value | Why |
|---|---|---|
| Sample rate | **8 MSa/s** | 69 samples per bit at 115200 — ample. 20 MSa/s works but halves your capture window for no benefit |
| Sample depth | 500 MSa | 62 s at 8 MSa/s |
| Channels | **only the two you need** | The rate ceiling depends on active channel count |
| Export | **CSV** | See below |

**Export CSV, not binary.** CSV stores *transitions*; binary stores every
sample. This bus is idle >99% of the time, so a 62-second CSV is a few thousand
lines while the same capture as binary is **1 GB**. The binary carries no
additional information that matters.

If you do end up with a binary: it is **2 bytes per sample, little-endian, CH0 =
bit 0, CH1 = bit 1**, idle `0x0003`, no header. The sample rate is *not* in the
file — derive it from the shortest run against a known bit time.
[`tools/decode_bin.py`](tools/decode_bin.py) handles it without numpy by
skipping constant 64 K blocks.

## The mistakes

### 1. Trusting prior art over measurement

An ESP32's RMT peripheral measured **~8 µs** bit times repeatedly. That was
dismissed as contact bounce, because published projects for "the same"
connector said 9600 8E1 (104 µs). The analyser later showed **8.5 µs = 115200**.

The measurement was right the whole time. The prior art described different
hardware that happened to share a connector name.

**When your own hardware and a web source disagree, verify the source applies to
your device before believing it over your instrument.**

Ruling 9600 out properly took a pulse-width census rather than an argument:

| | pulses matching |
|---|---|
| 115200 (8.68 µs) | **2347 / 2347** |
| 9600 (104 µs) | **0 / 2347** |

### 2. Probing a cut harness with nothing powered

Early captures at the unit produced silence, which read as a wiring failure. The
harness had been cut, so the module was never powered *and* connected at the
same time — and **the AC does not talk unless something is on the bus**.

Two useful captures came out of separating the halves deliberately:

- Module alone on the bench → black active, red idle
- AC alone, no module → red active, black idle

That pair is what proved the direction of each wire, which no amount of staring
at silkscreen would have settled. `CN-16`'s "TX"/"RX" labels are named from the
cable side, the opposite of what was assumed.

### 3. A decoder bug that looked exactly like a hardware fault

A capture came back with **27% bad stop bits** where every previous one had
zero. The obvious conclusions — signal integrity, threshold too low, sample rate
too coarse — were all wrong, and acting on them wasted a re-capture.

The real cause: the decoder skipped **10.5 bit times** after each byte before
hunting the next start bit. This unit leaves only **~0.4 bit of idle between
bytes**, so the next start edge arrives at ~10.4 and the decoder ate it, then
re-locked mid-byte.

**The tell was in the run lengths.** Every LOW run was a clean integer multiple
of the bit time (1.00, 2.00, 9.01) while HIGH runs came out 1.39, 2.39, 2.41.

> Perfect lows plus long highs means inter-byte idle, not a distorted signal.
> A real signal-integrity problem distorts **both** polarities.

Fix: skip **9.5–9.8** bit times, not 10.5. Anything in that range gives zero bad
stops; 10.0 and above starts failing.

### 4. A uniform record stride

The payload looks like fixed 3-byte records and mostly parses that way — which
hides two bugs at once. The last record of every frame is 2 bytes (no trailing
separator), and some fields are 32-bit. Both were invisible until short frames
turned up carrying nothing but their final record.

### 5. Logging every frame at INFO — it silently wedges the UART

The listener node kept **going deaf**: it stayed online over WiFi, pinged with
0% loss, kept its globals (so it had not crashed or rebooted), reported **zero
rejected frames and zero CRC failures** — and received nothing at all, on
**both** taps at once. Time-to-deaf was 5, 14, 20, 38 minutes.

Two hardware diagnoses were proposed and both were wrong: first the level
shifter, then a UART peripheral latch-up. Neither survived contact with the
evidence.

**The cause was one log call.** The 10 ms lambda that drains both UARTs was also
doing `ESP_LOGI` per frame with a hex string up to ~270 characters. At INFO that
goes to UART0 *and* to every connected API log client, from inside the hot path.
The loop fell behind, both RX buffers overran, and the ESP32 driver stopped
delivering. Both channels are serviced by the same loop, so they died together —
which is precisely what made it look like shared hardware.

Changing that single call to `ESP_LOGD`:

| | before | after |
|---|---|---|
| time to deaf | 5, 14, 20, 38 min | **9.4 h, zero events** |
| frames | — | 4,221 |
| rejects / CRC failures | — | **0 / 0** |

**`rx_buffer_size` was already 1024 — the buffer was never the problem.** 1024
bytes is ~89 ms of headroom at 115200 baud, which is ample right up until the
loop blocks for longer than that. Enlarging it does nothing.

> **For any ESPHome UART sniffer: do not log per-frame at INFO inside the read
> loop.** Log at DEBUG and publish the frame to a `text_sensor` instead, then
> raise `logger: level: DEBUG` only while actively mapping — and expect the
> stalls to come back while it is raised.

**What finally settled it was instrumentation, not reasoning:** a raw byte
counter per channel, incremented *before* any framing logic. "No frames" is
consistent with at least four different faults; "no bytes on either channel"
narrows it immediately, and it proves the decoder is not at fault. Those
counters cost nothing and should have existed from the start.

## What actually worked

### Cross-checking field widths against the app's own UI

The single highest-leverage step. Before decoding anything, the app was opened
and its controls counted:

- Fan: 7 speeds + auto
- Vertical airflow: 8 positions
- Horizontal airflow: 9 positions
- Modes: 5
- Power: separate buttons

Then it is just arithmetic. A field taking exactly **9** distinct values is the
horizontal airflow control, and no argument is required. That match is what
confirmed the record encoding was right, which in turn made mode findable.

It also prevents the opposite error: an early listener clamped fan speed to 1–6
and would have silently discarded the top speed and auto.

### One control at a time, and write down what you pressed

Six presses of one button, five seconds apart, beats sixty presses of everything.
The 50 ms ACK means each press produces a cleanly separated exchange pair.

Fields that change on their own are equally informative — **room temperature
identified itself** as the only value drifting while nothing was touched.

### Letting the appliance report rather than asking it

The AC broadcasts unprompted. Everything here was learned without transmitting a
byte, which meant no risk to a ceiling-mounted appliance at any point.

## Sequence that got from nothing to a field map

1. Capture with **only the module** powered → its polls, and which wire it drives
2. Capture with **only the AC** powered → its broadcasts, and the other wire
3. Rejoin the harness, capture **both** → the request/response handshake
4. Press one control repeatedly, note it, capture → one field per run
5. Cross-check the value counts against the app
6. Flash a listener and let it run → the slow-moving fields fall out on their own

Steps 1 and 2 are the ones people skip, and they are the ones that make the rest
unambiguous.
