// ============================================================================
// aciq_tx.h -- frame construction for the ACiQ K18W bus.
//
// Only used when this node REPLACES the WiFi module. With the stock dongle
// plugged in, nothing here may be called: two push-pull outputs on one net
// damages drivers.
//
// Every outgoing frame is built the same way -- assemble header + payload with
// two placeholder bytes at [8][9], then call finalize(), which writes the
// length byte and the CRC. Do not compute either by hand.
// ============================================================================
#pragma once

#include <cmath>
#include <cstdint>
#include <vector>

namespace aciq {

// CRC-16/XMODEM over the frame with bytes 8-9 REMOVED -- not zeroed. That
// distinction is the whole puzzle; zeroing leaves two extra bytes in the shift
// register and nothing ever matches. Verified on 4221 live frames.
inline uint16_t crc16(const std::vector<uint8_t> &v) {
  uint16_t c = 0x0000;
  for (size_t k = 0; k < v.size(); k++) {
    if (k == 8 || k == 9)
      continue;                       // the hole
    c ^= (uint16_t) v[k] << 8;
    for (int i = 0; i < 8; i++)
      c = (c & 0x8000) ? (uint16_t) ((c << 1) ^ 0x1021) : (uint16_t) (c << 1);
  }
  return c;
}

// Stamp the length byte and the check field. Call last, after the payload is
// complete. Frames must already carry two placeholder bytes at [8][9].
inline void finalize(std::vector<uint8_t> &f) {
  f[7] = (uint8_t) f.size();          // length INCLUDES the 8-byte header
  f[8] = 0x00;
  f[9] = 0x00;
  uint16_t c = crc16(f);
  f[8] = (uint8_t) (c >> 8);          // big-endian
  f[9] = (uint8_t) (c & 0xFF);
}

// ---------------------------------------------------------------------------
// Frames the module is expected to produce. Shapes copied from real captures
// of the stock dongle -- see captures/reference-frames.txt.
// ---------------------------------------------------------------------------

// Plain acknowledgment. 12 bytes. Byte 5 echoes the AC's counter, and the last
// byte echoes the payload type being acknowledged (0x0C report, 0x0A command,
// 0x0D clock). Observed turnaround from the real module: 49.3-50.2 ms.
//
//   MOD  A5 01 01 23 00 99 00 0C 24 4E 80 0C
inline std::vector<uint8_t> ack(uint8_t link, uint8_t counter, uint8_t ptype) {
  std::vector<uint8_t> f = {0xA5, 0x01, link, 0x23, 0x00, counter,
                            0x00, 0x00, 0x00, 0x00, 0x80, ptype};
  finalize(f);
  return f;
}

// Clock answer. 17 bytes. The AC asks with a `10 10` payload roughly every ten
// minutes and expects whatever sits on CN-16 to be a time source -- so once the
// dongle is gone, THIS NODE OWES THE AC THE TIME.
//
//   MOD  A5 01 00 23 00 00 00 11 8A 19 80 10 6A 79 69 90 FB
//                                            \_ unix be _/ ^^ constant
inline std::vector<uint8_t> clock_reply(uint32_t unix_time) {
  std::vector<uint8_t> f = {0xA5, 0x01, 0x00, 0x23, 0x00, 0x00,
                            0x00, 0x00, 0x00, 0x00, 0x80, 0x10,
                            (uint8_t) (unix_time >> 24),
                            (uint8_t) (unix_time >> 16),
                            (uint8_t) (unix_time >> 8),
                            (uint8_t) (unix_time),
                            0xFB};
  finalize(f);
  return f;
}

// Module heartbeat carrying signal strength as a signed 32-bit dBm in the `02`
// parameter namespace. The real dongle sends this about once a minute.
//
//   MOD  A5 01 00 23 00 00 00 12 F6 62 80 0C 02 64 FF FF FF DB   = -37 dBm
inline std::vector<uint8_t> rssi_report(int32_t dbm) {
  std::vector<uint8_t> f = {0xA5, 0x01, 0x00, 0x23, 0x00, 0x00,
                            0x00, 0x00, 0x00, 0x00, 0x80, 0x0C,
                            0x02, 0x64,
                            (uint8_t) (dbm >> 24), (uint8_t) (dbm >> 16),
                            (uint8_t) (dbm >> 8),  (uint8_t) (dbm)};
  finalize(f);
  return f;
}

// ---------------------------------------------------------------------------
// Commands. A command is structurally a REPORT (type 0x21) whose payload
// header is `0A 0A`. Records are <ns> <id> <value...>, appended back to back
// with no trailing separator.
//
//   MOD  A5 01 01 21 2F 00 00 0F C7 DD 0A 0A 00 13 01        eco ON
//   MOD  A5 01 01 21 1E 00 00 12 C2 F0 0A 0A 00 13 00 00 01 01
//                                                 ^^^^^^^^ TWO records
// ---------------------------------------------------------------------------
class Command {
 public:
  explicit Command(uint8_t counter) {
    f_ = {0xA5, 0x01, 0x01, 0x21, counter, 0x00,
          0x00, 0x00, 0x00, 0x00, 0x0A, 0x0A};
  }

  // Narrow field: <00> <id> <value>
  Command &field(uint8_t id, uint8_t value) {
    f_.push_back(0x00);
    f_.push_back(id);
    f_.push_back(value);
    return *this;
  }

  // Wide field: <00> <id> 00 00 <hi> <lo>. Setpoint (0x02) is centi-CELSIUS
  // and moves in 50-count steps -- a plain degF->degC conversion lands between
  // steps and the unit rounds it somewhere you did not ask for.
  Command &wide(uint8_t id, uint16_t value) {
    f_.push_back(0x00);
    f_.push_back(id);
    f_.push_back(0x00);
    f_.push_back(0x00);
    f_.push_back((uint8_t) (value >> 8));
    f_.push_back((uint8_t) (value & 0xFF));
    return *this;
  }

  // Parameter namespace, 4-byte payload: <02> <id> 00 00 00 <value>.
  // 0x27 is the setpoint as the DISPLAY degF label.
  Command &param(uint8_t id, uint8_t value) {
    f_.push_back(0x02);
    f_.push_back(id);
    f_.push_back(0x00);
    f_.push_back(0x00);
    f_.push_back(0x00);
    f_.push_back(value);
    return *this;
  }

  std::vector<uint8_t> build() {
    finalize(f_);
    return f_;
  }

 private:
  std::vector<uint8_t> f_;
};

// Setpoint conversion, from the observed ladder:
//   81 F -> 2700    80 F -> 2650    79 F -> 2600
// i.e. 50 centi-degrees per Fahrenheit step, anchored at 81 F = 2700.
// Clamped to the unit's own advertised limits (params 0x21/0x22 = 1600/3100).
inline uint16_t centi_c_for_degf(int degf) {
  int v = 2700 + (degf - 81) * 50;
  if (v < 1600) v = 1600;
  if (v > 3100) v = 3100;
  return (uint16_t) v;
}

}  // namespace aciq
