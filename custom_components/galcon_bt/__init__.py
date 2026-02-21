"""The Galcon BT Irrigation Controller integration."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback

from .const import (
    CONF_ADDRESS,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    SERVICE_OPEN_TIMED,
)
from .coordinator import GalconCoordinator
from .galcon_device import GalconDevice

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.VALVE, Platform.SWITCH, Platform.SENSOR, Platform.NUMBER]

OPEN_TIMED_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): str,
        vol.Optional("hours", default=0): vol.All(int, vol.Range(min=0, max=23)),
        vol.Optional("minutes", default=0): vol.All(int, vol.Range(min=0, max=59)),
        vol.Optional("seconds", default=0): vol.All(int, vol.Range(min=0, max=59)),
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Galcon BT from a config entry."""
    _LOGGER.info("Setting up Galcon BT integration for %s", entry.data.get(CONF_ADDRESS))
    hass.data.setdefault(DOMAIN, {})

    address = entry.data[CONF_ADDRESS]
    scan_interval = entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)

    device = GalconDevice(address)

    # Try to get BLEDevice from HA's bluetooth scanner for reliable connections
    ble_device = bluetooth.async_ble_device_from_address(hass, address, connectable=True)
    if ble_device:
        device.set_ble_device(ble_device)
        _LOGGER.debug("Found BLEDevice for %s via HA bluetooth scanner", address)
    else:
        _LOGGER.debug("No BLEDevice cached for %s, will use MAC address fallback", address)

    # Listen for future BLE advertisements to keep BLEDevice reference fresh
    @callback
    def _update_ble_device(
        service_info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        """Update the BLEDevice when HA's scanner sees the Galcon device."""
        device.set_ble_device(service_info.device)

    entry.async_on_unload(
        bluetooth.async_register_callback(
            hass,
            _update_ble_device,
            bluetooth.BluetoothCallbackMatcher(address=address),
            bluetooth.BluetoothScanningMode.ACTIVE,
        )
    )

    coordinator = GalconCoordinator(hass, device, scan_interval)

    # Polling starts disabled (battery saver). The user enables it via
    # the "Polling" toggle switch in the UI.  We still need to
    # initialise the coordinator — it will return a synthetic status.
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register custom service for timed watering
    async def handle_open_timed(call: ServiceCall) -> None:
        """Handle the open_valve_timed service call."""
        entity_id = call.data["entity_id"]
        hours = call.data.get("hours", 0)
        minutes = call.data.get("minutes", 0)
        seconds = call.data.get("seconds", 0)

        # Find the coordinator for this entity
        for eid, coord in hass.data[DOMAIN].items():
            if isinstance(coord, GalconCoordinator):
                # We'll let the switch entity handle the actual command
                await coord.async_open_valve(
                    hours=hours, minutes=minutes, seconds=seconds
                )
                _LOGGER.info(
                    "Timed valve open: %s for %02d:%02d:%02d",
                    entity_id,
                    hours,
                    minutes,
                    seconds,
                )
                return

        _LOGGER.error("Could not find Galcon device for entity %s", entity_id)

    if not hass.services.has_service(DOMAIN, SERVICE_OPEN_TIMED):
        hass.services.async_register(
            DOMAIN, SERVICE_OPEN_TIMED, handle_open_timed, schema=OPEN_TIMED_SCHEMA
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

        # Remove service if no more entries
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, SERVICE_OPEN_TIMED)

    return unload_ok
