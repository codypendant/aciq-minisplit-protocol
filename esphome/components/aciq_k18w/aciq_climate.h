// ============================================================================
// A climate entity for the ACiQ K18W mini split.
//
// This component deliberately does NOT touch the UART. All decoding and all
// transmitting stays in aciq-k18w.yaml, where it has been proven on hardware;
// this class is only the HA-facing climate surface.
//
//   state  ->  the YAML decoder calls the set_*() methods below
//   control->  HA's request fires a trigger, and YAML builds the frame with
//              aciq_tx.h and sends it through the tx_send script
//
// That keeps the `Transmit Enabled` interlock and the single write_array() in
// one place. A climate component with its own private path to the wire would
// bypass both.
//
// *** UNITS: ESPHome climate is ALWAYS CELSIUS over the API. *** Home Assistant
// converts for display. The setters here take Fahrenheit because that is what
// the bus reports and what the unit's own display shows, and convert on the way
// in. The unit's centi-Celsius ladder is NOT a true conversion of Fahrenheit --
// it moves 50 counts per degF anchored at 81 F = 2700 -- so degF is the
// authoritative number and Celsius is derived, never the other way round.
// ============================================================================
#pragma once

#include <cmath>
#include <string>

#include "esphome/core/component.h"
#include "esphome/core/automation.h"
#include "esphome/components/climate/climate.h"

namespace esphome {
namespace aciq_k18w {

class AciqClimate : public climate::Climate, public Component {
 public:
  void setup() override;
  void dump_config() override;
  float get_setup_priority() const override { return setup_priority::DATA; }

  climate::ClimateTraits traits() override;
  void control(const climate::ClimateCall &call) override;

  // Triggers fired by control(). Single-argument on purpose: a one-arg
  // ESPHome trigger hands the lambda a plain `x`, which keeps the YAML
  // readable and avoids depending on multi-arg parameter naming.
  Trigger<int> *get_mode_trigger() { return &mode_trigger_; }      // -1 = off
  Trigger<float> *get_temperature_trigger() { return &temp_trigger_; }  // degF
  Trigger<int> *get_fan_trigger() { return &fan_trigger_; }        // 0 = auto

  // ---- fed by the decoder in aciq-k18w.yaml -------------------------------
  // Every one of these can arrive late or never: the AC reports only what
  // CHANGES, so after a reboot an untouched field has no value at all. Each
  // setter tracks whether it has ever been told, and publishes only what is
  // actually known.
  void set_power_state(bool on);
  void set_mode_raw(int raw);
  void set_room_temperature_f(float f);
  void set_setpoint_f(float f);
  void set_fan_state(int speed, bool is_auto);
  void set_compressor_running(bool running);

 protected:
  void republish_();
  static float f_to_c_(float f) { return (f - 32.0f) * 5.0f / 9.0f; }
  static int c_to_f_(float c) { return (int) lroundf(c * 9.0f / 5.0f + 32.0f); }

  Trigger<int> mode_trigger_;
  Trigger<float> temp_trigger_;
  Trigger<int> fan_trigger_;

  bool power_{false};
  bool have_power_{false};
  int mode_raw_{-1};
  bool compressor_{false};
  int fan_speed_{0};
  bool fan_auto_{true};
  bool have_fan_{false};
};

}  // namespace aciq_k18w
}  // namespace esphome
