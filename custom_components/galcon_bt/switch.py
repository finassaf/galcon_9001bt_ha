"""Switch platform for Galcon BT irrigation controller."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ADDRESS, CONF_NAME, DEFAULT_NAME, DOMAIN
from .coordinator import GalconCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Galcon BT switch from a config entry."""
    coordinator: GalconCoordinator = hass.data[DOMAIN][entry.entry_id]
    name = entry.data.get(CONF_NAME, DEFAULT_NAME)
    address = entry.data[CONF_ADDRESS]

    async_add_entities(
        [GalconPollingSwitch(coordinator, name, address, entry.entry_id)]
    )


class GalconPollingSwitch(CoordinatorEntity[GalconCoordinator], SwitchEntity):
    """Toggle that enables / disables BLE status scanning.

    When OFF (default) no periodic BLE connections are made, preserving
    the Galcon controller's battery.  Commands (open / close valve) still
    work.  Turn ON when you want live status updates in the dashboard.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: GalconCoordinator,
        name: str,
        address: str,
        entry_id: str,
    ) -> None:
        """Initialize the polling toggle switch."""
        super().__init__(coordinator)
        self._address = address
        self._attr_name = "Scanning"
        self._attr_unique_id = f"galcon_bt_{address.replace(':', '_').lower()}_scanning"
        self._attr_icon = "mdi:bluetooth-connect"

        self._attr_device_info = {
            "identifiers": {(DOMAIN, address)},
            "name": name,
            "manufacturer": "Galcon",
            "model": "9001BT",
            "connections": {("bluetooth", address)},
        }

    @property
    def is_on(self) -> bool:
        """Return True if polling is active."""
        return self.coordinator.polling_enabled

    @property
    def available(self) -> bool:
        """Scanning toggle is always available."""
        return True

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Show scanning diagnostics."""
        attrs: dict[str, Any] = {
            "polling_interval_seconds": self.coordinator._base_interval,
        }
        if self.coordinator.last_successful_poll is not None:
            attrs["last_successful_poll"] = (
                self.coordinator.last_successful_poll.isoformat()
            )
        return attrs

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable BLE scanning."""
        _LOGGER.info("Enabling Galcon BLE scanning for %s", self._address)
        self.coordinator.set_polling(True)
        await self.coordinator.async_request_refresh()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable BLE scanning (battery saver)."""
        _LOGGER.info("Disabling Galcon BLE scanning for %s", self._address)
        self.coordinator.set_polling(False)
        self.async_write_ha_state()
