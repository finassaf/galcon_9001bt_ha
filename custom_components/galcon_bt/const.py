"""Constants for the Galcon BT irrigation controller integration."""

DOMAIN = "galcon_bt"

# BLE Characteristic UUIDs (Galcon 9001BT)
UUID_WAKE = "e8680201-9c4b-11e4-b5f7-0002a5d5c51b"
UUID_STATUS = "e8680102-9c4b-11e4-b5f7-0002a5d5c51b"
UUID_CONTROL = "e8680103-9c4b-11e4-b5f7-0002a5d5c51b"
UUID_PIN = "e8680401-9c4b-11e4-b5f7-0002a5d5c51b"

# Config keys
CONF_ADDRESS = "address"
CONF_NAME = "name"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_DURATION = "duration"

# Defaults
DEFAULT_NAME = "Galcon Irrigation"
DEFAULT_SCAN_INTERVAL = 300  # 5 minutes
DEFAULT_DURATION = 20  # minutes

# BLE device name filter — the Galcon 9001BT advertises with this prefix
DEVICE_NAME_FILTER = "GL9001A"
BLE_SCAN_TIMEOUT = 10.0  # seconds to scan for devices during setup

# Connection
MAX_RETRIES = 3
CONNECT_TIMEOUT = 30.0  # seconds (Galcon BLE is slow to wake)
COMMAND_VERIFY_ATTEMPTS = 3  # write+verify cycles per connection
WAKE_SETTLE_DELAY = 1.0  # seconds after wake-up before first command
POST_COMMAND_DELAY = 1.5  # seconds after write before reading status back

# Availability: mark unavailable only after this many consecutive poll failures.
# BLE devices sleep and frequently miss polls — this prevents constant gray-out.
MAX_CONSECUTIVE_FAILURES = 5

# Control byte constants
CMD_CLOSE_VALVE = b"\x01\x00\x00\x00\x00\x00\x00"
CMD_OPEN_VALVE = b"\x00\x01\x00\x00\x00\x00\x00"
WAKE_PAYLOAD = b"\x01\x02"

# Status byte masks
STATUS_VALVE_OPEN_MASK = 0x01
STATUS_MANUAL_OPEN_MASK = 0x01  # Byte 1

# Service names
SERVICE_OPEN_TIMED = "open_valve_timed"
