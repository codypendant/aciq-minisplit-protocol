"""Climate platform for the ACiQ K18W mini split.

Schema and to_code follow the same shape as the midea_xye external component
already running on this machine, which is the reference for what this ESPHome
version's codegen API actually accepts.

This component owns no UART. State is pushed in from the decoder lambdas in
aciq-k18w.yaml, and control requests come back out as triggers so the frame is
built and sent by the existing tx_send script -- keeping the Transmit Enabled
interlock and the single write_array() on one path.
"""

from esphome import automation
from esphome.components import climate
import esphome.codegen as cg
import esphome.config_validation as cv

CODEOWNERS = ["@codypendant"]
DEPENDENCIES = ["climate"]

aciq_k18w_ns = cg.esphome_ns.namespace("aciq_k18w")
AciqClimate = aciq_k18w_ns.class_("AciqClimate", climate.Climate, cg.Component)

CONF_ON_SET_MODE = "on_set_mode"
CONF_ON_SET_TEMPERATURE = "on_set_temperature"
CONF_ON_SET_FAN = "on_set_fan"

CONFIG_SCHEMA = cv.All(
    climate.climate_schema(AciqClimate)
    .extend(
        {
            cv.GenerateID(): cv.declare_id(AciqClimate),
            # Each trigger takes ONE argument so the YAML lambda receives a
            # plain `x`. Mode is the raw protocol value, or -1 for "power off".
            cv.Optional(CONF_ON_SET_MODE): automation.validate_automation(
                single=True
            ),
            # Fahrenheit, already rounded to a whole degree in control().
            cv.Optional(CONF_ON_SET_TEMPERATURE): automation.validate_automation(
                single=True
            ),
            # 0 = auto, 1 = mute, 2..7 = the manual speeds.
            cv.Optional(CONF_ON_SET_FAN): automation.validate_automation(
                single=True
            ),
        }
    )
    .extend(cv.COMPONENT_SCHEMA)
)


async def to_code(config):
    var = await climate.new_climate(config)
    await cg.register_component(var, config)
    await climate.register_climate(var, config)

    if CONF_ON_SET_MODE in config:
        await automation.build_automation(
            var.get_mode_trigger(), [(cg.int_, "x")], config[CONF_ON_SET_MODE]
        )
    if CONF_ON_SET_TEMPERATURE in config:
        await automation.build_automation(
            var.get_temperature_trigger(),
            [(cg.float_, "x")],
            config[CONF_ON_SET_TEMPERATURE],
        )
    if CONF_ON_SET_FAN in config:
        await automation.build_automation(
            var.get_fan_trigger(), [(cg.int_, "x")], config[CONF_ON_SET_FAN]
        )
