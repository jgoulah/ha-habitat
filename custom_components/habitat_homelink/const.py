"""Constants for the Habitat HomeLink integration."""

DOMAIN = "habitat_homelink"

# AWS configuration of the Habitat HomeLink app (a white-label Salus iT600 cloud)
AWS_REGION = "us-west-2"
AWS_USER_POOL_ID = "us-west-2_UqKk6Qvs1"
AWS_CLIENT_ID = "ji4tv7q81n7rbbmv1bkmkeb8i"
AWS_IDENTITY_POOL_ID = "us-west-2:ba429fe0-7865-4c71-8715-287b89ec7b5f"
AWS_IOT_ENDPOINT = "asyh9zqgbddbc-ats.iot.us-west-2.amazonaws.com"

# DynamoDB table listing the gateways of an account, keyed by Cognito identity id
DEVICE_LIST_TABLE = "UserToDeviceList"
DEVICE_LIST_KEY = "userid"

# Polling of device shadows (seconds); MQTT pushes changes, polling is a safety net
SCAN_INTERVAL_SECONDS = 60
PUSH_SCAN_INTERVAL_SECONDS = 300
# Things of a gateway change rarely and are re-read less often
METADATA_REFRESH_SECONDS = 3600
# Entities of a device without state data for this long become unavailable
STALE_AFTER_SECONDS = 600
# Commanded state is shown until the device reports it, at most this long
PENDING_TIMEOUT_SECONDS = 60
# Without pushed state changes a command is confirmed by polling after this delay
CONFIRM_REFRESH_DELAY_SECONDS = 10

# Thing models (second-to-last dash-separated part of the thing name)
MODEL_GATEWAY = "SAUPTZ1GW"
MODEL_PTAC_THERMOSTAT = "SAUPTZ1PT868"

# PTAC thermostat shadow properties
PTAC = "ep0:sPTAC868:"
LOCAL_TEMPERATURE = f"{PTAC}LocalTemperature_x100"
HEATING_SETPOINT = f"{PTAC}HeatingSetpoint_x100"
MIN_HEATING_SETPOINT = f"{PTAC}MinHeatingSetpoint_x100"
MAX_HEATING_SETPOINT = f"{PTAC}MaxHeatingSetpoint_x100"
SYSTEM_MODE = f"{PTAC}SystemMode"
FAN_MODE = f"{PTAC}FanMode"
RUNNING_STATE = f"{PTAC}RunningState"
BATTERY_VOLTAGE = f"{PTAC}BatteryVoltage_x10"
FILTER_RUN_DAYS = f"{PTAC}FilterRunDays"
FILTER_DAYS = f"{PTAC}FilterDays"
LOCK_KEY = f"{PTAC}LockKey"
PTAC_ERROR_CODE = f"{PTAC}PTACErrorCode"

SET_HEATING_SETPOINT = f"{PTAC}SetHeatingSetpoint_x100"
SET_SYSTEM_MODE = f"{PTAC}SetSystemMode"
SET_FAN_MODE = f"{PTAC}SetFanMode"
# Asks the thermostat to report its full state; the app sends this value right after connecting
SET_REFRESH = f"{PTAC}SetRefresh"
REFRESH_ON_CONNECT = "040000"

# Zigbee thermostat numbering, confirmed against the app
SYSTEM_MODE_OFF = 0
SYSTEM_MODE_COOL = 3
SYSTEM_MODE_HEAT = 4
SYSTEM_MODE_FAN_ONLY = 7
FAN_MODE_LOW = 1
FAN_MODE_HIGH = 3
FAN_MODE_AUTO = 5
