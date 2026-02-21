"""Valve platform for Galcon BT irrigation controller."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.valve import (
    ValveDeviceClass,
    ValveEntity,
    ValveEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ADDRESS, CONF_NAME, DEFAULT_NAME, DOMAIN
from .coordinator import GalconCoordinator
from .galcon_device import GalconStatus

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Galcon BT valve from a config entry."""
    coordinator: GalconCoordinator = hass.data[DOMAIN][entry.entry_id]
    name = entry.data.get(CONF_NAME, DEFAULT_NAME)
    address = entry.data[CONF_ADDRESS]

    async_add_entities([GalconValve(coordinator, name, address, entry.entry_id)])


class GalconValve(CoordinatorEntity[GalconCoordinator], ValveEntity):
    """Representation of a Galcon irrigation valve."""

    _attr_device_class = ValveDeviceClass.WATER
    _attr_supported_features = ValveEntityFeature.OPEN | ValveEntityFeature.CLOSE
    _attr_has_entity_name = True
    _attr_reports_position = False

    def __init__(
        self,
        coordinator: GalconCoordinator,
        name: str,
        address: str,
        entry_id: str,
    ) -> None:
        """Initialize the Galcon valve."""
        super().__init__(coordinator)
        self._address = address
        self._attr_name = "Valve"
        self._attr_unique_id = f"galcon_bt_{address.replace(':', '_').lower()}_valve"

        self._attr_device_info = {
            "identifiers": {(DOMAIN, address)},
            "name": name,
            "manufacturer": "Galcon",
            "model": "9001BT",
            "connections": {("bluetooth", address)},
        }

    @property
    def is_closed(self) -> bool | None:
        """Return True if the valve is closed."""
        status: GalconStatus | None = self.coordinator.data
        if status is None:
            return None
        return not status.valve_open

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        status: GalconStatus | None = self.coordinator.data
        attrs: dict[str, Any] = {
            "bluetooth_address": self._address,
            "consecutive_poll_failures": self.coordinator.consecutive_failures,
        }
        if self.coordinator.last_successful_poll is not None:
            attrs["last_seen"] = self.coordinator.last_successful_poll.isoformat()
        if status is not None:
            attrs["manual_open"] = status.manual_open
            attrs["hours_remaining"] = status.hours_remaining
            attrs["minutes_remaining"] = status.minutes_remaining
            attrs["seconds_remaining"] = status.seconds_remaining
            attrs["time_remaining_total_seconds"] = status.time_remaining_seconds
            attrs["raw_status"] = status.raw.hex()
        return attrs

    @property
    def available(self) -> bool:
        """Return True when polling is enabled."""
        return self.coordinator.polling_enabled

    async def async_open_valve(self, **kwargs: Any) -> None:
        """Open the irrigation valve using the configured duration."""
        duration = self.coordinator.duration_minutes
        hours, remainder = divmod(duration * 60, 3600)
        minutes, seconds = divmod(remainder, 60)
        _LOGGER.info(
            "Opening valve on %s for %d min (%02d:%02d:%02d)",
            self._address,
            duration,
            hours,
            minutes,
            seconds,
        )
        try:
            await self.coordinator.async_open_valve(
                hours=hours, minutes=minutes, seconds=seconds
            )
        except ConnectionError as err:
            _LOGGER.error("Failed to open valve: %s", err)

    async def async_close_valve(self, **kwargs: Any) -> None:
        """Close the irrigation valve."""
        _LOGGER.info("Closing valve on %s", self._address)
        try:
            await self.coordinator.async_close_valve()
        except ConnectionError as err:
            _LOGGER.error("Failed to close valve: %s", err)
