"""Constants for Eveus EV Charger + Cost."""

from typing import Final

DOMAIN: Final = "evse_charging_cost"

# --- connection -------------------------------------------------------------
CONF_HOST: Final = "host"
CONF_USERNAME: Final = "username"
CONF_PASSWORD: Final = "password"  # noqa: S105
CONF_DEVICE_NAME: Final = "device_name"
CONF_PHASES: Final = "phases"
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_MAX_CURRENT: Final = "max_current"
CONF_REAPPLY: Final = "reapply_current"
CONF_REAPPLY_DELAY: Final = "reapply_delay"

DEFAULT_REAPPLY: Final = True
DEFAULT_REAPPLY_DELAY: Final = 15
MAX_REAPPLY_DELAY: Final = 180
# The charger only tells the car about a new limit when the value changes, so
# the setting is briefly stepped by 1 A and then written back.
NUDGE_PAUSE: Final = 3.0

DEFAULT_DEVICE_NAME: Final = "Eveus"
DEFAULT_SCAN_INTERVAL: Final = 15
MIN_SCAN_INTERVAL: Final = 1
MAX_SCAN_INTERVAL: Final = 300
PHASES: Final = ["1", "3"]
DEFAULT_PHASES: Final = "1"

# --- tariff -----------------------------------------------------------------
CONF_DAY_PRICE: Final = "day_price"
CONF_NIGHT_PRICE: Final = "night_price"
CONF_NIGHT_START: Final = "night_start"
CONF_NIGHT_END: Final = "night_end"
CONF_CURRENCY: Final = "currency"

DEFAULT_DAY_PRICE: Final = 4.32
DEFAULT_NIGHT_PRICE: Final = 2.16
DEFAULT_NIGHT_START: Final = "23:00:00"
DEFAULT_NIGHT_END: Final = "07:00:00"
DEFAULT_CURRENCY: Final = "UAH"

ZONE_DAY: Final = "day"
ZONE_NIGHT: Final = "night"
ZONES: Final = (ZONE_DAY, ZONE_NIGHT)

# --- device -----------------------------------------------------------------
MANUFACTURER: Final = "Energy Star"
MODEL: Final = "Eveus EVSE"

MIN_CURRENT: Final = 6
MAX_CURRENT: Final = 32
DEFAULT_MAX_CURRENT: Final = 16

# States in which a car is plugged in, and the one where energy actually flows.
CONNECTED_STATES: Final = (3, 4, 5)
CHARGING_STATE: Final = 4
# After re-applying, check whether the car actually took the higher current.
VERIFY_DELAY: Final = 60
VERIFY_TOLERANCE_A: Final = 2.0
MAX_REAPPLY_ATTEMPTS: Final = 3
# How long to keep waiting for the cable to be unplugged before re-arming the
# charger anyway, after an "end session" request.
REARM_TIMEOUT: Final = 1800

STATUS_MAP: Final = {
    0: "power_up",
    1: "self_test",
    2: "standby",
    3: "car_connected",
    4: "charging",
    5: "charging_complete",
    6: "disabled",
    7: "error",
}

# --- accounting -------------------------------------------------------------
STORAGE_VERSION: Final = 1
# A single jump bigger than this between two polls is treated as a glitch.
MAX_DELTA_KWH: Final = 50.0
# A drop of the session counter bigger than this means a new session started.
SESSION_RESET_THRESHOLD_KWH: Final = 0.001
