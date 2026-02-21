"""Config flow for Galcon BT irrigation controller."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from bleak import BleakScanner

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.data_entry_flow import FlowResult

from .const import (
    BLE_SCAN_TIMEOUT,
    CONF_ADDRESS,
    CONF_DURATION,
    DEFAULT_DURATION,
    DEFAULT_NAME,
    DEVICE_NAME_FILTER,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class GalconBTConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Galcon BT."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovered_devices: dict[str, str] = {}  # address -> name

    async def _scan_for_galcon_devices(self) -> dict[str, str]:
        """Scan BLE for devices whose name contains DEVICE_NAME_FILTER.

        Returns a dict of {address: name} for matching devices.
        """
        devices: dict[str, str] = {}
        try:
            discovered = await BleakScanner.discover(
                timeout=BLE_SCAN_TIMEOUT,
                return_adv=False,
            )
            for d in discovered:
                bt_name = d.name or ""
                if DEVICE_NAME_FILTER.upper() in bt_name.upper():
                    addr = d.address.upper()
                    devices[addr] = bt_name
                    _LOGGER.debug("Found Galcon device: %s (%s)", bt_name, addr)
        except Exception as err:
            _LOGGER.error("BLE scan failed: %s", err)
        return devices

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 1: Scan for devices and show a picker."""
        errors: dict[str, str] = {}

        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            device_name = self._discovered_devices.get(address, "")
            default_name = device_name if device_name else DEFAULT_NAME
            name = user_input.get(CONF_NAME, default_name)

            await self.async_set_unique_id(address)
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=name,
                data={
                    CONF_ADDRESS: address,
                    CONF_NAME: name,
                    CONF_DURATION: user_input.get(CONF_DURATION, DEFAULT_DURATION),
                },
            )

        # Scan for devices
        self._discovered_devices = await self._scan_for_galcon_devices()

        if not self._discovered_devices:
            # No devices found — fall back to manual entry
            return await self.async_step_manual()

        # Build dropdown options: "NAME (AA:BB:CC:DD:EE:FF)"
        device_options = {
            addr: f"{name} ({addr})" for addr, name in self._discovered_devices.items()
        }

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): vol.In(device_options),
                    vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
                    vol.Optional(CONF_DURATION, default=DEFAULT_DURATION): vol.All(
                        int, vol.Range(min=1, max=120)
                    ),
                }
            ),
            errors=errors,
            description_placeholders={
                "count": str(len(self._discovered_devices)),
            },
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Fallback: manual MAC address entry when no devices found."""
        errors: dict[str, str] = {}

        if user_input is not None:
            address = user_input[CONF_ADDRESS].strip().upper()

            import re
            if not re.match(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$", address):
                errors[CONF_ADDRESS] = "invalid_address"
            else:
                await self.async_set_unique_id(address)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=user_input.get(CONF_NAME, DEFAULT_NAME),
                    data={
                        CONF_ADDRESS: address,
                        CONF_NAME: user_input.get(CONF_NAME, DEFAULT_NAME),
                        CONF_DURATION: user_input.get(CONF_DURATION, DEFAULT_DURATION),
                    },
                )

        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): str,
                    vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
                    vol.Optional(CONF_DURATION, default=DEFAULT_DURATION): vol.All(
                        int, vol.Range(min=1, max=120)
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_bluetooth(
        self, discovery_info: Any
    ) -> FlowResult:
        """Handle Bluetooth discovery."""
        address = discovery_info.address.upper()
        await self.async_set_unique_id(address)
        self._abort_if_unique_id_configured()

        self.context["title_placeholders"] = {
            "name": discovery_info.name or DEFAULT_NAME,
            "address": address,
        }

        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm Bluetooth discovery."""
        if user_input is not None:
            return self.async_create_entry(
                title=user_input.get(CONF_NAME, DEFAULT_NAME),
                data={
                    CONF_ADDRESS: self.unique_id,
                    CONF_NAME: user_input.get(CONF_NAME, DEFAULT_NAME),
                    CONF_DURATION: user_input.get(CONF_DURATION, DEFAULT_DURATION),
                },
            )

        return self.async_show_form(
            step_id="bluetooth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
                    vol.Optional(CONF_DURATION, default=DEFAULT_DURATION): vol.All(
                        int, vol.Range(min=1, max=120)
                    ),
                }
            ),
            description_placeholders={
                "address": self.unique_id,
            },
        )
