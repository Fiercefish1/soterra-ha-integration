# Soterra Home Assistant Integration

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

Smart home device integration for [Soterra](https://soterra.co). Sends entity state changes to the Soterra platform for guest/owner visibility and push notifications.

## Features

- **Zero YAML configuration** — set up entirely through the HA UI
- **Automatic discovery** — sends your device inventory to Soterra on setup
- **Real-time state updates** — pushes state changes as they happen
- **Entity picker** — select exactly which safety devices to monitor
- **Options flow** — add or remove devices at any time

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click the three dots menu → **Custom repositories**
3. Add `https://github.com/Fiercefish1/soterra-ha-integration` as an **Integration**
4. Search for "Soterra" and install
5. Restart Home Assistant

### Manual

1. Copy the `custom_components/soterra` folder into your HA `config/custom_components/` directory
2. Restart Home Assistant

## Setup

1. In Soterra, go to your property → **Smart Home** tab → enable Home Assistant
2. Copy the **Webhook URL**
3. In Home Assistant, go to **Settings → Devices & Services → Add Integration**
4. Search for **Soterra**
5. Paste the webhook URL
6. Select the safety devices you want Soterra to monitor
7. Done — discovery is sent automatically and state changes are monitored from this point

## How It Works

The integration listens for state changes on your selected `binary_sensor` entities (filtered to safety device classes: smoke, carbon_monoxide, gas, heat, moisture). When a state changes:

1. A `state_update` payload is POSTed to your Soterra webhook
2. Soterra updates the device's live status
3. If it's an alarm event (e.g., smoke detected), Soterra waits 30 seconds then sends push notifications to guests and the property owner
4. If the alarm clears within 30 seconds, no notification is sent (avoids false alarms)
5. If the alarm clears after a notification was sent, a follow-up "all clear" notification is sent

## Managing Devices

To add or remove monitored devices after setup:

1. Go to **Settings → Devices & Services → Soterra**
2. Click **Configure**
3. Update your entity selection
4. Save — a new discovery payload is sent to Soterra automatically

## Supported Device Classes

| Device Class | Example |
|---|---|
| `smoke` | Smoke detectors |
| `carbon_monoxide` | CO detectors |
| `gas` | Natural gas / propane sensors |
| `heat` | Heat detectors |
| `moisture` | Water leak sensors |

## Requirements

- Home Assistant 2024.1.0 or later
- A Soterra account with at least one property
- Safety devices configured as `binary_sensor` entities in HA

## Troubleshooting

**"Could not connect to the Soterra webhook"**
- Verify the webhook URL is correct (copy it again from the Soterra app)
- Ensure your HA instance has internet access
- Check that the Soterra integration is enabled for the property

**Devices not appearing in Soterra after setup**
- Go to Settings → Devices & Services → Soterra → Configure
- Save (even without changes) to re-trigger discovery
- Check HA logs for "Soterra" entries

**State changes not pushing**
- Verify the entity is in the monitored list (Configure → check entity selection)
- Check that the entity's *state* is changing, not just attributes
- Check HA logs: `Logger: custom_components.soterra` at debug level

## License

MIT
