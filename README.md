# Galcon BT Irrigation Controller for Home Assistant

A custom Home Assistant integration for the **Galcon 9001BT** Bluetooth irrigation controller.

![Dashboard Screenshot](docs/screenshot.png)

## Features

- **Open / Close valve** from the HA dashboard
- **Configurable irrigation duration** — default set during setup, adjustable via dashboard slider (0–40 min)
- **Battery level** sensor (read from device)
- **Time remaining** countdown with live 1-second ticks
- **Operation status** sensor (Idle, Connecting, Opening, Closing, Confirmed, Error)
- **Auto-discovery** of Galcon devices via BLE scan (filters by `GL9001A` device name)
- **Timed irrigation** service (`galcon_bt.open_valve_timed`)
- **Last irrigation** sensor with date/time and duration
- **Scheduling** via HA Schedule helper + automation (see below)

## Installation

1. Copy `custom_components/galcon_bt` from this repo into your HA `config/custom_components/` directory.
2. Restart Home Assistant.
3. Go to **Settings → Devices & Services → Add Integration** → search **Galcon BT**.
4. Select your device from the BLE scan list, or enter the MAC address manually.

## Scanning & Battery Life

The Galcon 9001BT is battery-powered. To conserve battery, **BLE scanning is off by default** — no periodic connections are made.

| Mode | Behavior |
|------|----------|
| **Scanning OFF** | Valve open/close commands still work. Battery and status show cached values. |
| **Scanning ON** | Polls the device every 5 minutes for live status, countdown, and battery. |

Turn scanning on when you need live feedback, off when you don't.

## Entities

| Entity | Type | Description |
|--------|------|-------------|
| `switch.<name>_scanning` | Switch | Toggle BLE scanning on/off |
| `valve.<name>_valve` | Valve | Open/close the irrigation valve |
| `number.<name>_duration` | Number | Irrigation duration slider (0–40 min) |
| `sensor.<name>_battery` | Sensor | Battery level (%) — cached |
| `sensor.<name>_time_remaining` | Sensor | Irrigation countdown (MM:SS) |
| `sensor.<name>_last_irrigation` | Sensor | Last irrigation date/time + duration |
| `sensor.<name>_status` | Sensor | Current operation phase |

## Dashboard Card

```yaml
type: vertical-stack
cards:
  - type: entities
    show_header_toggle: false
    entities:
      - entity: switch.galcon_irrigation_scanning
        name: Scan
        icon: mdi:bluetooth-connect
      - entity: valve.galcon_irrigation_valve
        name: Valve
        icon: mdi:sprinkler-variant
      - entity: number.galcon_irrigation_duration
        name: Duration
      - entity: sensor.galcon_irrigation_last_irrigation
        name: Last Irrigation
  - type: glance
    entities:
      - entity: sensor.galcon_irrigation_battery
        name: Battery
      - entity: sensor.galcon_irrigation_time_remaining
        name: Remaining
      - entity: sensor.galcon_irrigation_status
        name: Status

```

## Scheduling Irrigation

The Galcon 9001BT has no on-device schedule accessible over BLE. Use Home Assistant's built-in **Schedule helper** and an automation to run irrigation on a recurring schedule.

### 1. Create a Schedule Helper

Go to **Settings → Devices & Services → Helpers → Create Helper → Schedule** and configure your desired days/times (e.g. every day at 06:00).

Or add to `configuration.yaml`:

```yaml
schedule:
  irrigation_schedule:
    name: Irrigation Schedule
    monday:
      - from: "06:00:00"
        to: "06:01:00"
    tuesday:
      - from: "06:00:00"
        to: "06:01:00"
    wednesday:
      - from: "06:00:00"
        to: "06:01:00"
    thursday:
      - from: "06:00:00"
        to: "06:01:00"
    friday:
      - from: "06:00:00"
        to: "06:01:00"
    saturday:
      - from: "06:00:00"
        to: "06:01:00"
    sunday:
      - from: "06:00:00"
        to: "06:01:00"
```

### 2. Create an Automation

```yaml
automation:
  - alias: "Scheduled Irrigation"
    trigger:
      - platform: state
        entity_id: schedule.irrigation_schedule
        to: "on"
    action:
      - service: switch.turn_on
        target:
          entity_id: switch.galcon_irrigation_scanning
      - delay: "00:00:05"
      - service: valve.open_valve
        target:
          entity_id: valve.galcon_irrigation_valve
```

The valve will run for the duration set on the **Duration** slider. When time expires, the integration automatically marks the valve as closed and disables scanning to conserve battery.

To see the next scheduled run, check **Settings → Automations** or add the schedule entity to your dashboard.
