# Changelog

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
