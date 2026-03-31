"""Constants for the Soterra integration."""

DOMAIN = "soterra"
CONF_WEBHOOK_URL = "webhook_url"
CONF_DEVICES = "devices"  # Selected HA device IDs
CONF_ENTITIES = "entities"  # Legacy — kept for migration

# Safety-related device classes on binary_sensor entities
SAFETY_DEVICE_CLASSES = [
    "smoke",
    "carbon_monoxide",
    "gas",
    "heat",
    "moisture",
]

# Additional entity device classes we include per-device
EXTRA_DEVICE_CLASSES = [
    "battery",       # sensor.* with device_class battery
    "tamper",        # binary_sensor.* with device_class tamper
]

# Timeout for webhook HTTP requests (seconds)
WEBHOOK_TIMEOUT = 20

# How long to wait after setup before sending discovery (seconds)
DISCOVERY_DELAY = 2
