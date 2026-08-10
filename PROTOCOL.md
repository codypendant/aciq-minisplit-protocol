# Wire protocol

**115200 baud, 8 data bits, no parity, 1 stop bit.** Measured, not assumed —
see [`METHOD.md`](METHOD.md) for how 9600 was ruled out.

Two lines, each one-directional:

| Harness wire | Direction |
|---|---|
| **Red** | mainboard → WiFi module |
| **Black** | WiFi module → mainboard |

Proven from both ends: with the module powered alone on the bench, black is
active and red idle. With the AC powered and no module attached, red is active
and black idle.

## Frame

```
 0    1    2    3     4      5  6    7      8    9    10 ...
+----+----+----+-----+------+------+------+----------+---------
| A5 | 01 | fl | typ | ctr  | 00 00| len  | chk  chk | payload
+----+----+----+-----+------+------+------+----------+---------
```

| Byte | Meaning |
|---|---|
| `0` | Header, always `A5` |
| `1` | Always `01` |
| `2` | Link flag — `00` or `01`. Purpose not established |
| `3` | **Message type**: `21` = report, `23` = acknowledgment |
| `4` | **Counter**, increments per message |
| `5`–`6` | Always `00 00` |
| `7` | **Total frame length**, including this header. Verified against 12, 15, 18, 21, 24, 27, 30, 63, 66, 72, 90 and 93-byte frames |
| `8`–`9` | **Check field**, big-endian. **Unsolved** — see below |
| `10`+ | Payload |

The length byte at offset 7 is what makes the stream parseable. Frame on
`A5` + length, and validate by whether the next frame starts with `A5`.

## The ACK handshake

Every report is acknowledged **~50 ms later**, echoing the counter:

```
AC   A5 01 01 21 99 00 00 18 47 A0 0C 0C 00 02 00 00 0A 8C 02 27 00 00 00 51
MOD  A5 01 01 23 00 99 00 0C 24 4E 80 0C                            +50.1 ms
                    ^^ counter 99 echoed at byte 5
```

ACKs are always 12 bytes and carry no state. The turnaround was 49.3–50.2 ms
across every exchange observed.

**The ACK's last byte echoes the payload type it is acknowledging** — `80 0A`
for a command, `80 0C` for a report, `80 0D` for clock, `80 10` for a clock
request. Each side runs its own independent counter sequence.

### The module supplies the clock

The AC asks for the time and the module answers with it:

```
AC   A5 01 00 21 00 00 00 0C 46 DE | 10 10
MOD  A5 01 00 23 00 00 00 11 8A 19 | 80 10 | 6A 79 69 90 | FB
                                             ^^^^^^^^^^^ unix timestamp
```

Every ~10 minutes. Worth knowing for a replacement module: the AC expects
whatever sits on `CN-16` to be a time source.

### WiFi signal strength

The module's heartbeat ACK carries an `02 64` parameter holding a **signed
32-bit dBm** value:

```
A5 01 00 23 00 00 00 12 F6 62 80 0C | 02 64 FF FF FF DB     = -37 dBm
```

Observed −37 to −43 overnight. **Note the namespace:** this is the `02`
*parameter* `0x64`, unrelated to the AC's *field* `0x64` (input power).

## Commands

A command is **structurally identical to a report** — same type `0x21`, same TLV
records. Only the payload header differs. Real captures:

```
A5 01 01 21 1E 00 00 12 C2 F0 0A 0A 00 13 00 00 01 01    power ON
A5 01 01 21 20 00 00 12 2E 69 0A 0A 00 73 00 00 05 06    fan speed 6
A5 01 01 21 25 00 00 12 50 2F 0A 0A 00 73 00 00 05 01    fan speed 1
A5 01 01 21 26 00 00 12 33 25 0A 0A 00 73 01 00 05 00    fan AUTO
A5 01 01 21 2F 00 00 0F C7 DD 0A 0A 00 13 01             eco mode ON
```

Eco mode is a good worked example of reading a command end to end:

```
MOD  ... 0A 0A 00 13 01           module asks for eco
AC   A5 01 01 23 00 2F 00 0C ...  AC acknowledges, 80 0A
AC   ... 0C 0C 00 DF 01 00 13 01  AC reports the new state
AC   ... 0C 0C 00 C0 00 00 00 2C  compressor target 86% -> 44%
```

Command, acknowledgment, state change and physical effect, all on the wire
within two seconds.

**`0x73` is the fan AUTO flag.** Manual speeds send `73=00`; auto sends `73=01`
*together with* `05=00`. Fan auto is a flag plus a speed, not a speed value —
which is why it first looked like "speed 0".

## Payload

```
frame[10:12]   payload header -- THIS is what distinguishes a command:
                 `0C 0C` = state report    (AC -> module)
                 `0A 0A` = COMMAND         (module -> AC)
                 `0D 0D` = clock broadcast
                 `10 10` = clock REQUEST   (AC asks, module answers)
                 `26 26` = periodic poll
frame[12]      00
frame[13:]     records
```

### Record encoding — widths are schema-dependent

This is the part that bites. **Records are not a uniform stride.**

Most fields are one byte, separated by a single `00`:

```
<id> <val> 00 <id> <val> 00 ... <id> <val>
                                ^^^^^^^^^^^ last record has NO separator
```

A fixed 3-byte stride therefore **drops the final record of every frame** —
which is exactly where the short 15- and 18-byte frames put their data.

Some fields instead carry a 32-bit value:

```
<id> 00 00 <hi> <lo> 00
```

Walking those as 2-byte records splits them and **invents a phantom field**.
Room temperature first appeared as a bogus `0A=D2` for precisely this reason.

Known wide fields: `0x02`, `0x03`, `0x5C`, `0x60`, `0x64`, `0x65`, `0x72`,
`0xC0`.

**The encoding is genuinely ambiguous without a schema.** A narrow record whose
value is zero is byte-identical to the start of a wide field: `0C 00 00 0D 00 00`
is really `0C=0` followed by `0D=0`, but reads as `0C=3328`. Only a known-wide
list resolves it — a parser cannot infer widths from the bytes alone.

Records are always a **multiple of three bytes** (narrow = id/val/separator,
wide = id/00/00/hi/lo/separator), so any scan must step by 3. Stepping by 1
matches `xx 00 00` mid-record and invents fields that do not exist.

**Symptom worth memorising:** a value that publishes as a constant **0** is
usually a wide field being parsed as narrow. Fan percent (`0x72`) did exactly
this until the live log showed `72 00 00 00 19` — the 25 was three bytes further
along than a 1-byte read looks.

Parse wide fields first by scanning for `<id> 00 00 <hi> <lo>`, then walk the
remainder as 2-byte records, skipping 6 bytes whenever a wide id appears.

## Field map

### Confirmed

| Id | Meaning | Encoding | Notes |
|---|---|---|---|
| `0x01` | **Power** | 1 byte | `00` off, `01` on |
| `0x02` | **Setpoint** | centi-°C | Moves in **0.50 °C** steps |
| `0x03` | **Room temperature** | centi-°C | **Emitted unprompted every ~60 s** |
| `0x05` | **Fan speed** | 1 byte | `1`–`7`, **`0` = auto** |
| `0x12` | **Mode** | 1 byte | `00`–`04`. Which is which: unverified |
| `0x13` | **Eco mode** | 1 byte | `0`/`1`. `0xDF` moves in lockstep with it |
| `0x72` | Fan percent | 1 byte | 1 / 25 / 40 / 55 / 70 / 85 / 100, tracks `0x05` |
| `0x5C` | **Indoor coil temperature** | centi-°C | 10–13 °C while cooling; warms to ambient when off |
| `0x0E` | Vertical airflow | 1 byte | 8 positions per the app |
| `0x11` | Horizontal airflow | 1 byte | 9 positions per the app; observed set is exactly `01 02 03 08 09 0A 0B 0C 0D` |
| `0x60` | **Outdoor AIR temperature** | centi-°C | **Only reported while the outdoor unit is energised** — silent across 5 hours of idle |
| `0x64` | **Input power** | 16-bit, W | 620–930 at partial load, 0 when off. The app has a power-usage tracker, so the unit must report this |
| `0xC0` | **Compressor target** | 16-bit, % | Commanded speed. Jumps straight to value on start |
| `0x65` | **Compressor actual** | 16-bit, % | Ramps up to meet `0xC0` |
| `0x41`, `0x42` | Unix timestamps | 32-bit | In `0D 0D` clock frames |

### The unit thinks in Celsius

Setpoint steps are **0.50 °C**, and the trailing °F byte on setpoint frames is a
**rounded display label**, not the real value:

| Displayed | Field `0x02` | Actual |
|---|---|---|
| 81 °F | 2700 | 27.00 °C = 80.6 °F |
| 80 °F | 2650 | 26.50 °C = 79.7 °F |
| 79 °F | 2600 | 26.00 °C = 78.8 °F |

**For control, send centi-°C.** For the observed points,
`centi_c = 2700 + (degF − 81) × 50`. A plain °F→°C conversion lands between
steps.

### Not yet identified

These appear as wide fields with plausible engineering values. **Candidates,
not conclusions.**

| Id | Values seen | Hypothesis |
|---|---|---|
| `0x06` | `40`, `A4` | — |
| `0x13`, `0x15`, `0xDF` | 0/1 toggles | Feature flags |
| `0x38`, `0x3D`, `0x74`, `0x95`, `0xA4`, `0xBD`–`0xBF` | mostly constant | — |

**Outdoor temperature was field `0x60`**, found exactly this way — it is
centi-°C like `0x02` and `0x03`, and it was confirmed by comparing against a
*different* outdoor sensor elsewhere on the same property at the same moment:

| `0x60` | °C | °F | independent sensor |
|---|---|---|---|
| `0x0D48` | 34.00 | 93.2 | — |
| `0x0CE4` | 33.00 | 91.4 | — |
| `0x0C80` | 32.00 | 89.6 | 92.3 °F |

**Open question: outdoor AIR or outdoor COIL?** The absolute value suggests air;
the observed oscillation between 3300 and 3400 suggests coil. The discriminator
is overnight behaviour — **air falls steadily through the night, a coil jumps
with compressor cycles.** Worth an overnight log before trusting the label.

`0xC0` is *not* a temperature: it runs 30–82 and reads exactly 0 whenever the
unit is off. **This unit is a multi-speed DC inverter** — a fixed-speed
compressor would report one running value or zero, whereas the observed
30 / 38 / 40 / 42 / 48 / 66 / 82 is continuous modulation.

### Outdoor air, not outdoor coil — settled

Two independent observations, either of which is sufficient:

- It read **89.6–91.4 °F while the compressor pulled 850 W**. A condensing coil
  under that load sits at 115–130 °F.
- Across a morning it climbed **monotonically with the sun** — 78.8 °F at 07:17
  to 91.4 °F at 10:32 — with no step changes at compressor start or stop. A coil
  would jump with every cycle.

### Target and actual — settled

`0xC0` is the **commanded** compressor speed and `0x65` is the **actual**. A
cold start makes this unambiguous:

```
0xC0 -> 86        target jumps straight to its value
0x65 = 18         actual begins ramping
0x65 = 37 -> 50 -> 64 -> 86     reaches target after ~45 s
0xC0 -> 82        target eases back
0x65 = 82         actual follows
```

**Units are percent, not Hz.** Both cap near 86, the app exposes a 0–100% speed
for the compressor and air handler, and actual chases commanded the way a
servo-tracked percentage does.

Input power tracks the ramp exactly — 130 → 260 → 420 → 660 → 840 → 910 W,
settling near 850 W.

**`0x64` is instantaneous draw, not a function of compressor speed.** Do not try
to model consumption from `0x65`:

| compressor | power |
|---|---|
| 0% | 0 W |
| 15% | 220 W |
| 28% | 630 W |
| 86% | 850 W |

Every cycle ramps 50 → 900 W and then settles, so a given speed maps to
different readings depending on where in the cycle you sample. Integrate the
power field itself; do not derive it.

### Eco mode changes the whole control strategy

Worth knowing before interpreting anyone's capture — a unit in eco behaves like
a different machine:

| | eco off | eco on |
|---|---|---|
| Compressor target | up to 86% | capped **16–28%** |
| Cycle length | continuous pull-down | ~11 min on/off |
| Room swing | tight | **~3 °F** around setpoint |

Eco also **drifts the setpoint upward on its own** — 26.0 °C became 27.0 °C
overnight with nobody touching the remote, and the trailing display byte moved
`0x50` → `0x51` (80 → 81 °F) to match. If you are diffing captures and the
setpoint moved, check eco before assuming a decode error.

**Knowing the unit is an inverter narrows the remaining unknowns**, because a
variable-speed machine reports things a fixed-speed one does not: speed or
frequency, input power, and target-versus-actual pairs. Interpret candidate
fields with that in mind rather than assuming on/off telemetry.


### Thermistors: what is on the bus and what is still missing

The hardware has more temperature sensors than the bus has so far revealed:

| Sensor | Field | Status |
|---|---|---|
| Intake air | `0x03` | **Found.** Reads the room, but is **biased low while running** — see below |
| Outdoor | `0x60` | **Found.** Air or coil still unsettled |
| **Indoor coil** | `0x5C` | **Found** — see below |
| Blower outlet | — | **Not yet seen** |

**Ruling out a candidate:** `0x64` (930 / 890 / 850 / 620) *looks* like an
evaporator coil at 6–9 °C, but it reads **exactly 0 within 38 seconds of
power-off**. A real coil drifts *up* toward room temperature when the compressor
stops — it does not go to zero. It is **input power in watts**, corroborated by
the vendor app exposing a power-usage tracker: the unit has to report power
somewhere, and this is the only field shaped like it. Verify by comparing
against the app's own reading while running.

### `0x03` reads low while the unit runs

This is a wall-mount mini split, so there is **no return duct** — the head unit
draws room air straight through its top grille, and `0x03` is the thermistor in
that intake. It genuinely measures room air, which is why "room temperature" is
a fair label.

But it sits inches from where the unit discharges its own cold supply air, so
while cooling, some output recirculates into the intake and the body of the unit
is cold. The sensor reads **several degrees below true room temperature**:

| state | `0x03` |
|---|---|
| cooling | 78.8 °F |
| everything off | **82.9 °F** |

Nothing warmed by 4 °F in that moment — the bias simply disappeared when the
airflow stopped. **Treat the running value as approximate.** An automation
driven off it will see a step change every time the unit starts or stops.

(Ducted systems have the same problem for a different reason, where the sensor
really is in a return plenum. Do not carry that vocabulary over to a mini split:
there is no return here.)

### The indoor coil was hiding as "blower RPM"

`0x5C` was mislabelled for most of this project because 1400–2300 is a
believable fan speed and the number never looked wrong. It is a **temperature in
centi-°C**:

| when | `0x5C` | °C |
|---|---|---|
| cooling | 1000–1300 | **10–13** — textbook evaporator coil |
| shutdown +35 s | 1500 | 15 |
| +48 s / +75 s | 1700 → 2100 | 17 → 21 |
| settled, unit off | **2600** | **26** — equal to room temp, which read `0x0A28` too |

**A fan goes to zero when it stops. A coil warms to ambient.** The give-away was
the value *climbing* after shutdown and converging on the room temperature.

**But it does not fully equilibrate.** Over five idle hours it pinned at exactly
75.2 °F while room temperature drifted 80.4 → 83.3 °F — an **8 °F offset that
never closes**. So the coil-to-room difference is not a clean measure of cooling
output at rest; the sensor appears to sit on refrigerant piping rather than in
the air path.

Generalising: **a plausible-looking number is not evidence.** Check that a field
behaves correctly at the boundaries — off, minimum, maximum — not just that its
range looks sensible.

**Where to look for the blower-outlet sensor:** the 72-byte frame contains
`BD`, `BE`, `BF` — three
consecutive wide fields sitting at zero, immediately before `C0` (compressor). A
contiguous run of unpopulated slots next to a known sensor field is exactly
where extra thermistors would live.

**How to catch it:** run the listener through a cooling cycle from a warm start
and watch the `Wide Fields` entity, which prints every unclaimed wide field with
a centi-Celsius reading alongside. A coil thermistor has the most violent
signature on this bus — it plunges from room temperature to roughly 5–10 °C
within a couple of minutes of the compressor engaging, then climbs straight back
when it stops. Nothing else moves like that.

## Behaviour worth exploiting

**Power-on dumps complete state.** Switching the unit on emits 66 + 90 + 72-byte
frames back to back, unasked. A freshly booted controller can obtain full state
without needing to request it — useful even now that writing is possible, since
it avoids having to synthesise a state request at all.

Between changes the AC reports sparsely: a room-temperature frame each minute
and short frames when something moves.

## The check field — SOLVED

```
CRC-16/XMODEM
  polynomial   0x1021
  init         0x0000
  bit order    MSB-first
  final XOR    none
  region       the ENTIRE FRAME with bytes 8-9 REMOVED -- not zeroed
```

Verified on **105 frames**: every length from 12 to 90 bytes, both directions,
all five payload types, zero failures. Reference implementation in
[`tools/crc.py`](tools/crc.py).

```python
def crc16(data, init=0x0000):
    c = init
    for b in data:
        c ^= b << 8
        for _ in range(8):
            c = ((c << 1) ^ 0x1021) & 0xFFFF if c & 0x8000 else (c << 1) & 0xFFFF
    return c

def compute(frame):
    return crc16(bytes(frame[0:8]) + bytes(frame[10:]))   # note the hole
```

### Remove the check field. Do not zero it.

This is the whole puzzle, and it cost two days.

Zeroing bytes 8-9 leaves **two extra bytes in the shift register**. The effect
is not a clean failure — it is worse, because it *half* works:

- Bytes **after** the check field still fit CRC-1021 at their positional tail.
- The counter byte, which sits **before** it, fits CRC-1021 at a tail **exactly
  2 shorter** than its position.
- Nothing fits all of them at once.

That produces a very convincing wrong conclusion, and it is the one this
document carried for two days: *"the counter is protected by something
CRC-1021-shaped and the payload is folded in some other way."* There is no
second mechanism. It is one ordinary CRC over a region with a hole in it.

The same mistake also produced a **fake partial solution**. Fitting only the
12-byte ACKs — which differ in exactly one byte — yielded "region `[0:10]`,
init `0x28C8` one direction and `0xD07E` the other". That reproduces every ACK
and is still wrong: with one varying byte the fit only ever modelled the
counter, and the two "inits" were the constant remainder of the bytes the model
was ignoring. **A checksum model that needs a different constant per message
type is not solved; it is overfitted.**

### How it was actually found

Parameter search had already failed across seven polynomials, both bit orders,
both byte orders, and every contiguous span. The move that worked was to stop
guessing parameters and **recover the linear map directly**:

1. Collect ~80 frames of one length. In the 18-byte report family exactly four
   bytes vary — counter, field id, and the two value bytes — so there are 32
   unknown bit contributions plus a constant, against 79 equations.
2. Solve `chk = C ⊕ Σ(contribution of each set bit)` as a **GF(2) linear
   system**. It came out consistent and reproduced all 79 frames exactly. That
   alone proves the check field is linear, which rules out sums, LRCs, and
   anything carrying.
3. Read the polynomial off the solution. Consecutive bits of one byte were
   `2042 → 4084 → 8108 → 1231`: each the previous shifted left, the overflow
   XORing in **0x1021**.
4. Compare each byte's **effective** tail — the `T` for which
   `crc([0x01] + [0x00]*T)` equals its bit-0 contribution — against its
   **positional** tail. Bytes after the check field matched exactly. The counter
   was short by 2. That names the hole and finishes the problem.

| byte | positional tail | effective tail |
|---|---|---|
| `[4]` counter | 13 | **11** |
| `[13]` field id | 4 | 4 |
| `[16]` value hi | 1 | 1 |
| `[17]` value lo | 0 | 0 |

**Generalise this.** When a checksum resists parameter search, recover the
linear map instead. It cannot lie about structure, and it yields both the
polynomial and the region rather than one guess at a time.

### What this unlocks

Receiving never needed it — header, length byte and the ACK counter echo frame
the stream reliably. **Transmitting does**, and this was the last blocker.

The listener now verifies every frame and exposes a **CRC Failures** counter
alongside Frames Rejected. The two mean different things: Rejected counts
implausible length bytes, CRC Failures counts real corruption. Both should stay
at zero.
