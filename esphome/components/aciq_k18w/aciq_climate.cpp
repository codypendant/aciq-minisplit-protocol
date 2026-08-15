#include "aciq_climate.h"

#include <cstdlib>
#include <cstring>

#include "esphome/core/log.h"

namespace esphome {
namespace aciq_k18w {

static const char *const TAG = "aciq_k18w.climate";

// The unit advertises its own setpoint bounds on the bus as parameters 0x21
// and 0x22 -- 1600 and 3100 centi-Celsius, seen live as 60.8 F and 87.8 F.
// These are those numbers, not a guess.
static const float MIN_C = 16.0f;
static const float MAX_C = 31.0f;

// Fan modes are CUSTOM because this unit has 7 speeds plus auto, and ESPHome's
// LOW/MEDIUM/HIGH enum cannot express that. "mute" is speed 1 -- the 1 % step,
// which the handheld labels MUTE rather than 1.
// ONE table, used both to advertise the modes and to report them back. The
// protected setter interns against the registered list, so these must be the
// same pointers -- index is the protocol speed, 0 = auto, 1 = mute.
static const char *const FAN_MODES[8] = {"auto", "mute", "2", "3", "4", "5", "6", "7"};
static const char *const FAN_AUTO = FAN_MODES[0];
static const char *const FAN_MUTE = FAN_MODES[1];

climate::ClimateTraits AciqClimate::traits() {
  auto t = climate::ClimateTraits();
  // ESPHome 2026.5 replaced set_supports_current_temperature() /
  // set_supports_action() with a single feature-flag bitmask.
  t.set_feature_flags(climate::CLIMATE_SUPPORTS_CURRENT_TEMPERATURE |
                      climate::CLIMATE_SUPPORTS_ACTION);
  t.set_visual_min_temperature(MIN_C);
  t.set_visual_max_temperature(MAX_C);
  // 1.0, NOT the 0.5 C that the unit's ladder actually moves in.
  //
  // Home Assistant converts min/max between units but passes the STEP through
  // untouched -- 16/31 C came out as 60.8/87.8 F while a 0.5 step stayed 0.5.
  // So the step is effectively in whatever the user's display unit is, and 0.5
  // offered half-degree Fahrenheit stops this unit cannot take. control()
  // rounds to whole degF and the AC reports the rounded value back, so it did
  // self-correct -- but it is better not to offer 80.5 at all.
  t.set_visual_target_temperature_step(1.0f);
  t.set_visual_current_temperature_step(0.1f);
  t.set_supported_modes({
      climate::CLIMATE_MODE_OFF,
      climate::CLIMATE_MODE_HEAT_COOL,  // the unit's "auto", mode raw 0
      climate::CLIMATE_MODE_COOL,       // raw 1
      climate::CLIMATE_MODE_DRY,        // raw 2
      climate::CLIMATE_MODE_FAN_ONLY,   // raw 3
      climate::CLIMATE_MODE_HEAT,       // raw 4
  });
  // NOT set here. As of 2026.5 the traits setter is deprecated (removed in
  // 2026.11) in favour of calling it on the Climate entity -- done in setup().
  return t;
}

void AciqClimate::setup() {
  this->set_supported_custom_fan_modes(FAN_MODES);
  // Seed the fan mode. Without this the underlying enum sits at its zero value
  // and Home Assistant shows "on" until the AC first reports a fan state --
  // and "on" is not even a member of the list advertised above, so it reads as
  // a broken entity rather than an unknown one. Auto is the honest guess: it
  // is this unit's own default, and the first real report overwrites it.
  this->set_custom_fan_mode_(FAN_MODES[0]);
}

void AciqClimate::control(const climate::ClimateCall &call) {
  // Nothing here publishes state. The AC reports what it actually did a moment
  // later and that report is the authority -- this is the whole reason the
  // entity can be honest rather than dead-reckoned like an IR integration.
  if (call.get_mode().has_value()) {
    climate::ClimateMode m = *call.get_mode();
    int raw;
    switch (m) {
      case climate::CLIMATE_MODE_OFF:       raw = -1; break;
      case climate::CLIMATE_MODE_HEAT_COOL: raw = 0;  break;
      case climate::CLIMATE_MODE_COOL:      raw = 1;  break;
      case climate::CLIMATE_MODE_DRY:       raw = 2;  break;
      case climate::CLIMATE_MODE_FAN_ONLY:  raw = 3;  break;
      case climate::CLIMATE_MODE_HEAT:      raw = 4;  break;
      default:
        ESP_LOGW(TAG, "unsupported mode requested, ignoring");
        raw = -2;
        break;
    }
    if (raw != -2) {
      ESP_LOGI(TAG, "control: mode -> %d", raw);
      this->mode_trigger_.trigger(raw);
    }
  }

  if (call.get_target_temperature().has_value()) {
    // Round to whole Fahrenheit here rather than in YAML: degF is the number
    // the unit's ladder and its own display are built on.
    int f = c_to_f_(*call.get_target_temperature());
    ESP_LOGI(TAG, "control: setpoint -> %d F", f);
    this->temp_trigger_.trigger((float) f);
  }

  // ClimateCall returns a StringRef here, not an optional -- test with
  // has_custom_fan_mode() rather than has_value().
  if (call.has_custom_fan_mode()) {
    const char *fm = call.get_custom_fan_mode().c_str();
    int speed;
    if (strcmp(fm, FAN_AUTO) == 0) {
      speed = 0;
    } else if (strcmp(fm, FAN_MUTE) == 0) {
      speed = 1;
    } else {
      speed = atoi(fm);
    }
    ESP_LOGI(TAG, "control: fan -> %d", speed);
    this->fan_trigger_.trigger(speed);
  }
}

void AciqClimate::set_power_state(bool on) {
  this->power_ = on;
  this->have_power_ = true;
  this->republish_();
}

void AciqClimate::set_mode_raw(int raw) {
  this->mode_raw_ = raw;
  this->republish_();
}

void AciqClimate::set_room_temperature_f(float f) {
  this->current_temperature = f_to_c_(f);
  this->republish_();
}

void AciqClimate::set_setpoint_f(float f) {
  this->target_temperature = f_to_c_(f);
  this->republish_();
}

void AciqClimate::set_fan_state(int speed, bool is_auto) {
  this->fan_speed_ = speed;
  this->fan_auto_ = is_auto || speed == 0;
  this->have_fan_ = true;
  this->republish_();
}

void AciqClimate::set_compressor_running(bool running) {
  this->compressor_ = running;
  this->republish_();
}

void AciqClimate::republish_() {
  // Mode. Power off wins over whatever mode the unit last reported -- the AC
  // keeps reporting `cool` while switched off, and showing COOL on a stopped
  // unit reads as "it is running".
  if (this->have_power_ && !this->power_) {
    this->mode = climate::CLIMATE_MODE_OFF;
  } else {
    switch (this->mode_raw_) {
      case 0:  this->mode = climate::CLIMATE_MODE_HEAT_COOL; break;
      case 1:  this->mode = climate::CLIMATE_MODE_COOL;      break;
      case 2:  this->mode = climate::CLIMATE_MODE_DRY;       break;
      case 3:  this->mode = climate::CLIMATE_MODE_FAN_ONLY;  break;
      case 4:  this->mode = climate::CLIMATE_MODE_HEAT;      break;
      default: break;  // never reported yet -- leave whatever we had
    }
  }

  // Action. The compressor flag is the honest signal; do not infer it from the
  // mode, which says what was asked for rather than what is happening.
  if (this->have_power_ && !this->power_) {
    this->action = climate::CLIMATE_ACTION_OFF;
  } else if (this->compressor_) {
    switch (this->mode) {
      case climate::CLIMATE_MODE_HEAT:      this->action = climate::CLIMATE_ACTION_HEATING; break;
      case climate::CLIMATE_MODE_DRY:       this->action = climate::CLIMATE_ACTION_DRYING;  break;
      case climate::CLIMATE_MODE_FAN_ONLY:  this->action = climate::CLIMATE_ACTION_FAN;     break;
      default:                              this->action = climate::CLIMATE_ACTION_COOLING; break;
    }
  } else if (this->mode == climate::CLIMATE_MODE_FAN_ONLY) {
    this->action = climate::CLIMATE_ACTION_FAN;
  } else {
    this->action = climate::CLIMATE_ACTION_IDLE;
  }

  if (this->have_fan_) {
    // custom_fan_mode is private now; the protected setter interns the
    // pointer against the supported list, so these must be the SAME literals
    // registered in setup() -- hence one table used by both.
    if (this->fan_auto_) {
      this->set_custom_fan_mode_(FAN_MODES[0]);
    } else if (this->fan_speed_ >= 1 && this->fan_speed_ <= 7) {
      this->set_custom_fan_mode_(FAN_MODES[this->fan_speed_]);
    }
  }

  this->publish_state();
}

void AciqClimate::dump_config() {
  LOG_CLIMATE("", "ACiQ K18W Climate", this);
  ESP_LOGCONFIG(TAG, "  Setpoint range: %.1f-%.1f C (from the unit's own 0x21/0x22)",
                MIN_C, MAX_C);
  ESP_LOGCONFIG(TAG, "  State is fed from the YAML decoder; control fires triggers.");
}

}  // namespace aciq_k18w
}  // namespace esphome
