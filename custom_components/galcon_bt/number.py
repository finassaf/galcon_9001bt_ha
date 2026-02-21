"""Number platform for Galcon BT — irrigation duration slider."""

from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_ADDRESS, CONF_DURATION, CONF_NAME, DEFAULT_DURATION, DEFAULT_NAME, DOMAIN
from .coordinator import GalconCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Galcon BT duration number entity."""
    coordinator: GalconCoordinator = hass.data[DOMAIN][entry.entry_id]
    name = entry.data.get(CONF_NAME, DEFAULT_NAME)
    address = entry.data[CONF_ADDRESS]
    default_duration = entry.data.get(CONF_DURATION, DEFAULT_DURATION)

    async_add_entities([GalconDurationNumber(coordinator, name, address, default_duration)])


class GalconDurationNumber(NumberEntity):
    """Number entity to set irrigation duration in minutes."""

    _attr_has_entity_name = True
    _attr_native_min_value = 0
    _attr_native_max_value = 40
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_mode = NumberMode.SLIDER
    _attr_icon = "mdi:timer-cog-outline"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: GalconCoordinator,
        name: str,
        address: str,
        default_duration: int,
    ) -> None:
        """Initialize the duration number entity."""
        self._coordinator = coordinator
        self._address = address
        self._attr_name = "Duration"
        self._attr_unique_id = f"galcon_bt_{address.replace(':', '_').lower()}_duration"
        self._attr_native_value = float(default_duration)

        # Store initial value on coordinator so valve can read it
        self._coordinator.duration_minutes = default_duration

        self._attr_device_info = {
            "identifiers": {(DOMAIN, address)},
            "name": name,
            "manufacturer": "Galcon",
            "model": "9001BT",
            "connections": {("bluetooth", address)},
        }

    @property
    def available(self) -> bool:
        """Always available — it's a configuration setting."""
        return True

    async def async_set_native_value(self, value: float) -> None:
        """Update the irrigation duration."""
        self._attr_native_value = value
        self._coordinator.duration_minutes = int(value)
        _LOGGER.info("Galcon %s: irrigation duration set to %d minutes", self._address, int(value))
        self.async_write_ha_state()
