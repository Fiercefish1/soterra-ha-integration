"""Constants for the Soterra integration."""

DOMAIN = "soterra"
CONF_WEBHOOK_URL = "webhook_url"
CONF_ENTITIES = "entities"

# Safety-related device classes that Soterra monitors
SAFETY_DEVICE_CLASSES = [
    "smoke",
    "carbon_monoxide",
    "gas",
    "heat",
    "moisture",
]

# Timeout for webhook HTTP requests (seconds)
WEBHOOK_TIMEOUT = 20

# How long to wait after setup before sending discovery (seconds)
DISCOVERY_DELAY = 2
