"""Sensor platform for Galcon BT irrigation controller — operation status."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ADDRESS, CONF_NAME, DEFAULT_NAME, DOMAIN
from .coordinator import GalconCoordinator, OperationState
from .galcon_device import GalconStatus

_LOGGER = logging.getLogger(__name__)

import datetime as dt

# Map operation states to mdi icons for visual feedback
STATE_ICONS: dict[OperationState, str] = {
    OperationState.IDLE: "mdi:sleep",
    OperationState.CONNECTING: "mdi:bluetooth-connect",
    OperationState.OPENING: "mdi:valve-open",
    OperationState.CLOSING: "mdi:valve-closed",
    OperationState.VERIFYING: "mdi:check-circle-outline",
    OperationState.CONFIRMED: "mdi:check-bold",
    OperationState.ERROR: "mdi:alert-circle",
    OperationState.SCANNING: "mdi:bluetooth-audio",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Galcon BT operation status sensor."""
    coordinator: GalconCoordinator = hass.data[DOMAIN][entry.entry_id]
    name = entry.data.get(CONF_NAME, DEFAULT_NAME)
    address = entry.data[CONF_ADDRESS]

    async_add_entities([
        GalconOperationSensor(coordinator, name, address),
        GalconTimeRemainingSensor(coordinator, name, address),
        GalconBatterySensor(coordinator, name, address),
    ])


class GalconOperationSensor(SensorEntity):
    """Sensor showing the current BLE operation phase.

    Values: Idle, Connecting..., Opening..., Closing..., Verifying...,
    Confirmed, Error, Scanning...
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: GalconCoordinator,
        name: str,
        address: str,
    ) -> None:
        """Initialize the operation status sensor."""
        self._coordinator = coordinator
        self._address = address
        self._attr_name = "Status"
        self._attr_unique_id = f"galcon_bt_{address.replace(':', '_').lower()}_status"
        self._attr_icon = STATE_ICONS[OperationState.IDLE]

        self._attr_device_info = {
            "identifiers": {(DOMAIN, address)},
            "name": name,
            "manufacturer": "Galcon",
            "model": "9001BT",
            "connections": {("bluetooth", address)},
        }

    @property
    def native_value(self) -> str:
        """Return the current operation state as a string."""
        return str(self._coordinator.operation_state)

    @property
    def icon(self) -> str:
        """Return an icon matching the current operation phase."""
        return STATE_ICONS.get(
            self._coordinator.operation_state, "mdi:help-circle-outline"
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional diagnostic attributes."""
        attrs: dict[str, Any] = {
            "scanning_enabled": self._coordinator.polling_enabled,
            "consecutive_failures": self._coordinator.consecutive_failures,
        }
        if self._coordinator.last_successful_poll is not None:
            attrs["last_seen"] = self._coordinator.last_successful_poll.isoformat()
        return attrs

    @property
    def available(self) -> bool:
        """Status sensor is always available."""
        return True

    async def async_added_to_hass(self) -> None:
        """Register for operation state change callbacks."""
        await super().async_added_to_hass()

        @callback
        def _on_state_change() -> None:
            """Push a state update when the operation phase changes."""
            self.async_write_ha_state()

        self._coordinator.register_state_listener(_on_state_change)


class GalconTimeRemainingSensor(CoordinatorEntity[GalconCoordinator], SensorEntity):
    """Sensor showing irrigation time remaining as a live countdown.

    When the valve is open and time is reported by the device, this sensor
    interpolates a local countdown (ticking every second) between BLE polls
    so the dashboard shows a smooth "stopwatch" experience.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:timer-outline"

    def __init__(
        self,
        coordinator: GalconCoordinator,
        name: str,
        address: str,
    ) -> None:
        """Initialize the time remaining sensor."""
        super().__init__(coordinator)
        self._address = address
        self._attr_name = "Time Remaining"
        self._attr_unique_id = (
            f"galcon_bt_{address.replace(':', '_').lower()}_time_remaining"
        )
        self._attr_device_info = {
            "identifiers": {(DOMAIN, address)},
            "name": name,
            "manufacturer": "Galcon",
            "model": "9001BT",
            "connections": {("bluetooth", address)},
        }

        # Local countdown state
        self._end_time: datetime | None = None
        self._unsub_timer: callback | None = None

    # ---- helpers ----

    def _remaining_seconds(self) -> int:
        """Seconds left according to local countdown."""
        if self._end_time is None:
            return 0
        remaining = (self._end_time - datetime.now(timezone.utc)).total_seconds()
        return max(0, int(remaining))

    @staticmethod
    def _format_time(total_seconds: int) -> str:
        """Format seconds as HH:MM:SS or MM:SS."""
        if total_seconds <= 0:
            return "00:00"
        h, remainder = divmod(total_seconds, 3600)
        m, s = divmod(remainder, 60)
        if h > 0:
            return f"{h:d}:{m:02d}:{s:02d}"
        return f"{m:d}:{s:02d}"

    # ---- HA entity interface ----

    @property
    def native_value(self) -> str:
        """Return formatted time remaining."""
        return self._format_time(self._remaining_seconds())

    @property
    def icon(self) -> str:
        """Show timer icon when counting, check when done."""
        if self._remaining_seconds() > 0:
            return "mdi:timer-sand"
        return "mdi:timer-outline"

    @property
    def available(self) -> bool:
        """Always available so the user sees 00:00 when idle."""
        return True

    @callback
    def _handle_coordinator_update(self) -> None:
        """Sync local countdown when a fresh BLE status arrives."""
        status: GalconStatus | None = self.coordinator.data
        if status is not None and status.valve_open and status.time_remaining_seconds > 0:
            # Set / refresh the projected end time from device data
            self._end_time = datetime.now(timezone.utc) + dt.timedelta(
                seconds=status.time_remaining_seconds
            )
            self._ensure_timer()
        elif status is not None and not status.valve_open:
            # Valve closed — clear countdown
            self._end_time = None
            self._cancel_timer()
        super()._handle_coordinator_update()

    @callback
    def _tick(self, _now: datetime) -> None:
        """Called every second to update the displayed countdown."""
        if self._remaining_seconds() <= 0:
            self._end_time = None
            self._cancel_timer()
            # Irrigation finished — update valve status and disable scanning
            self.coordinator.async_irrigation_ended()
        self.async_write_ha_state()

    def _ensure_timer(self) -> None:
        """Start the 1-second tick if not already running."""
        if self._unsub_timer is None:
            self._unsub_timer = async_track_time_interval(
                self.hass, self._tick, dt.timedelta(seconds=1)
            )

    def _cancel_timer(self) -> None:
        """Stop the 1-second tick."""
        if self._unsub_timer is not None:
            self._unsub_timer()
            self._unsub_timer = None

    async def async_will_remove_from_hass(self) -> None:
        """Clean up timer on removal."""
        self._cancel_timer()
        await super().async_will_remove_from_hass()


class GalconBatterySensor(CoordinatorEntity[GalconCoordinator], SensorEntity):
    """Sensor showing the Galcon device battery level.

    The battery value is cached so it remains visible even when
    scanning is turned off.
    """

    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: GalconCoordinator,
        name: str,
        address: str,
    ) -> None:
        """Initialize the battery sensor."""
        super().__init__(coordinator)
        self._address = address
        self._attr_name = "Battery"
        self._attr_unique_id = (
            f"galcon_bt_{address.replace(':', '_').lower()}_battery"
        )
        self._attr_device_info = {
            "identifiers": {(DOMAIN, address)},
            "name": name,
            "manufacturer": "Galcon",
            "model": "9001BT",
            "connections": {("bluetooth", address)},
        }
        self._cached_battery: int | None = None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Cache battery level from fresh poll data."""
        status: GalconStatus | None = self.coordinator.data
        if status is not None and status.battery_level is not None:
            self._cached_battery = status.battery_level
        super()._handle_coordinator_update()

    @property
    def native_value(self) -> int | None:
        """Return the cached battery level (0-100%)."""
        return self._cached_battery

    @property
    def available(self) -> bool:
        """Available once we have at least one battery reading."""
        return self._cached_battery is not None
