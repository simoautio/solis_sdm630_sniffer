"""Integration defaults."""

DOMAIN = "solis_sdm630_sniffer"
CONF_TOPIC = "topic"
CONF_TIMEOUT = "timeout"
DEFAULT_TOPIC = "solis/rs485/raw"
DEFAULT_TIMEOUT = 60
CONF_GRID_IMPORT_SIGN = "grid_import_sign"
DEFAULT_GRID_IMPORT_SIGN = "positive"

CONF_UPDATE_INTERVAL = "update_interval"
DEFAULT_UPDATE_INTERVAL = 30

CONF_LOGGER_HOST = "logger_host"
CONF_LOGGER_PORT = "logger_port"
CONF_LOGGER_UNIT = "logger_unit"
CONF_LOGGER_INTERVAL = "logger_interval"
DEFAULT_LOGGER_PORT = 502
DEFAULT_LOGGER_UNIT = 1
DEFAULT_LOGGER_INTERVAL = 30
CONF_UTILITY_CYCLES = "utility_meter_cycles"
CONF_UTILITY_SOURCES = "utility_meter_sources"

CONF_MODE = "mode"
MODES = ("meter", "logger", "both")
METER_TITLE = "Solis SDM630 Sniffer"
LOGGER_TITLE = "Solis inverter"
