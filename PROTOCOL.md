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

## Payload

```
frame[10:12]   payload header: `0C 0C` normally, `0D 0D` for clock frames
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
| `0x72` | Fan percent | 1 byte | 1 / 25 / 40 / 55 / 70 / 85 / 100, tracks `0x05` |
| `0x5C` | Blower RPM | 16-bit | 1400–2300 observed |
| `0x0E` | Vertical airflow | 1 byte | 8 positions per the app |
| `0x11` | Horizontal airflow | 1 byte | 9 positions per the app; observed set is exactly `01 02 03 08 09 0A 0B 0C 0D` |
| `0x60` | **Outdoor temperature** | centi-°C | Cross-checked against an independent outdoor sensor |
| `0xC0` | **Compressor speed** | 16-bit | 30–82 running, **exactly 0** when off. Units unsettled — see below |
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
| `0x65` | 0–66, **0 when off** | Pairs with `0xC0`. Target vs actual speed, or compressor vs air handler — both are 0–100% settable on this unit |
| `0x64` | 930, 890, 850, 620 | **Input power (W)** — a strong fit for an 18k BTU inverter at partial load, and it falls with compressor frequency rather than sitting at a fixed draw |
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

### Percent or Hz? Not settled

Both readings fit and it is worth not guessing:

- **Percent.** The unit's compressor and air handler each accept a **0–100%
  speed**, and every value observed from `0xC0` and `0x65` is **≤ 100**.
- **Hz.** 30–82 Hz is a textbook inverter operating range.

`0x65` behaves identically — 0–66 running, 0 when off — so the pair is most
likely **target and actual**, or **compressor and air handler**.

**The experiment that settles it:** command a known percentage from the app and
see which field lands on that exact number. A percent field will match the
commanded value; a frequency field will not.

Until then the listener publishes `0xC0` as a percentage, because that is the
better-supported reading, and labels it as unconfirmed.

**Knowing the unit is an inverter narrows the remaining unknowns**, because a
variable-speed machine reports things a fixed-speed one does not: speed or
frequency, input power, and target-versus-actual pairs. Interpret candidate
fields with that in mind rather than assuming on/off telemetry.

## Behaviour worth exploiting

**Power-on dumps complete state.** Switching the unit on emits 66 + 90 + 72-byte
frames back to back, unasked. A freshly booted controller can obtain full state
without needing to request it — which matters because request framing is part of
the unsolved write path.

Between changes the AC reports sparsely: a room-temperature frame each minute
and short frames when something moves.

## The check field

**Unsolved.** Bytes 8–9, big-endian, deterministic — identical frames always
produce identical values.

Ruled out: all standard CRC16 polynomials (`0x1021`, `0x8005`, `0x3D65`,
`0xA001`, `0x8408`, `0x0589`, `0xC867`) in both bit orders and both byte orders,
across every contiguous span and end offset, with the field zeroed and not,
solving `init` by GF(2) linear algebra over 16 clean frames from both
directions.

Established facts for whoever cracks it:

1. The field is **linear over GF(2)** in the counter byte:
   `chk(1)^chk(3) == chk(5)^chk(7) == 0x60E3` exactly. Per-bit deltas for the
   counter are `bit0=B861 bit1=60E3 bit2=C1C6 bit3=93AD bit4=377B`.
2. On two 24-byte frames with **byte-identical payloads** differing only in the
   counter, the delta `00E4` is reproduced **exactly** by CRC-16/CCITT `0x1021`
   with the region ending at `len-2`.
3. **Payload changes do not follow that rule.** After removing the counter's
   contribution the residual matches no single-byte CRC contribution at any
   offset.
4. Frames with identical payloads solve to identical `init`; differing payloads
   do not.

So the counter is covered by something CRC-1021-shaped, and the payload
participates by some other route. Sample frames are in
[`captures/`](captures/).

Receiving does not require it. Transmitting does.
