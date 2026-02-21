"""DataUpdateCoordinator for Galcon BT irrigation controller."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from enum import StrEnum

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, MAX_CONSECUTIVE_FAILURES
from .galcon_device import GalconDevice, GalconStatus

_LOGGER = logging.getLogger(__name__)


class OperationState(StrEnum):
    """Visual states for the Galcon device operation."""

    IDLE = "Idle"
    CONNECTING = "Connecting..."
    OPENING = "Opening..."
    CLOSING = "Closing..."
    VERIFYING = "Verifying..."
    CONFIRMED = "Confirmed"
    ERROR = "Error"
    SCANNING = "Scanning..."


class GalconCoordinator(DataUpdateCoordinator[GalconStatus]):
    """Coordinator that polls status from the Galcon device periodically."""

    def __init__(
        self, hass: HomeAssistant, device: GalconDevice, scan_interval: int | None = None
    ) -> None:
        """Initialize the coordinator."""
        self.device = device
        self.consecutive_failures: int = 0
        self.last_successful_poll: datetime | None = None
        self._last_known_status: GalconStatus | None = None
        self.polling_enabled: bool = False
        self._base_interval = scan_interval or DEFAULT_SCAN_INTERVAL
        self.duration_minutes: int = 20  # overridden by NumberEntity on setup

        # Last irrigation tracking
        self.last_irrigation_start: datetime | None = None
        self.last_irrigation_duration_min: int | None = None
        self._current_irrigation_start: datetime | None = None
        self._current_irrigation_duration: int = 0

        # Operation state tracking for UI feedback
        self.operation_state: OperationState = OperationState.IDLE
        self._state_listeners: list = []

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{device.address}",
            update_interval=timedelta(seconds=self._base_interval),
        )

    def register_state_listener(self, listener) -> None:
        """Register a callback to be called when operation_state changes."""
        self._state_listeners.append(listener)

    def _set_operation_state(self, state: OperationState) -> None:
        """Update operation state and notify listeners (sensor entities)."""
        self.operation_state = state
        for listener in self._state_listeners:
            listener()

    @property
    def reachable(self) -> bool:
        """Return True unless we exceeded the consecutive-failure threshold."""
        return self.consecutive_failures < MAX_CONSECUTIVE_FAILURES

    def set_polling(self, enabled: bool) -> None:
        """Enable or disable periodic BLE polling."""
        self.polling_enabled = enabled
        if enabled:
            self.consecutive_failures = 0
            self.update_interval = timedelta(seconds=self._base_interval)
            _LOGGER.info("Galcon %s: scanning ENABLED", self.device.address)
        else:
            self.update_interval = timedelta(hours=24)
            self._set_operation_state(OperationState.IDLE)
            _LOGGER.info("Galcon %s: scanning DISABLED", self.device.address)

    async def _async_update_data(self) -> GalconStatus:
        """Fetch status from the Galcon device."""
        if not self.polling_enabled:
            if self._last_known_status is not None:
                return self._last_known_status
            synthetic = GalconStatus(
                valve_open=False,
                manual_open=False,
                hours_remaining=0,
                minutes_remaining=0,
                seconds_remaining=0,
                raw=b"",
            )
            self._last_known_status = synthetic
            return synthetic

        self._set_operation_state(OperationState.SCANNING)
        try:
            status = await self.device.get_status()
            self.consecutive_failures = 0
            self.last_successful_poll = dt_util.utcnow()
            self._last_known_status = status
            self._set_operation_state(OperationState.IDLE)
            _LOGGER.info(
                "Galcon %s status: valve_open=%s, manual=%s, remaining=%02d:%02d:%02d",
                self.device.address,
                status.valve_open,
                status.manual_open,
                status.hours_remaining,
                status.minutes_remaining,
                status.seconds_remaining,
            )
            return status
        except (ConnectionError, Exception) as err:
            self.consecutive_failures += 1
            self._set_operation_state(OperationState.IDLE)
            _LOGGER.info(
                "Galcon %s poll failed (%d/%d consecutive): %s",
                self.device.address,
                self.consecutive_failures,
                MAX_CONSECUTIVE_FAILURES,
                err,
            )
            if self._last_known_status is not None:
                return self._last_known_status
            raise UpdateFailed(
                f"Cannot reach Galcon device (no cached state): {err}"
            ) from err

    def _record_irrigation_start(self, duration_minutes: int) -> None:
        """Record the start of an irrigation session."""
        self._current_irrigation_start = dt_util.now()
        self._current_irrigation_duration = duration_minutes

    def _record_irrigation_end(self) -> None:
        """Finalize the last irrigation record."""
        if self._current_irrigation_start is not None:
            self.last_irrigation_start = self._current_irrigation_start
            self.last_irrigation_duration_min = self._current_irrigation_duration
            self._current_irrigation_start = None
            _LOGGER.info(
                "Galcon %s: irrigation recorded — %s for %d min",
                self.device.address,
                self.last_irrigation_start.strftime("%Y-%m-%d %H:%M"),
                self.last_irrigation_duration_min,
            )

    async def async_open_valve(
        self, hours: int = 0, minutes: int = 0, seconds: int = 0
    ) -> None:
        """Open the valve with operation state feedback."""
        self._set_operation_state(OperationState.CONNECTING)
        try:
            self._set_operation_state(OperationState.OPENING)
            real_status = await self.device.open_valve(
                hours=hours, minutes=minutes, seconds=seconds
            )
            self._set_operation_state(OperationState.CONFIRMED)
            if real_status:
                # Use the actual device-reported status (has real time remaining)
                self._last_known_status = real_status
            else:
                # Fallback synthetic — command sent but not confirmed
                self._last_known_status = GalconStatus(
                    valve_open=True,
                    manual_open=True,
                    hours_remaining=hours,
                    minutes_remaining=minutes,
                    seconds_remaining=seconds,
                    raw=self._last_known_status.raw if self._last_known_status else b"",
                    battery_level=self._last_known_status.battery_level if self._last_known_status else None,
                )
            self._record_irrigation_start(hours * 60 + minutes + (1 if seconds else 0))
            self.async_set_updated_data(self._last_known_status)
        except (ConnectionError, Exception):
            self._set_operation_state(OperationState.ERROR)
            raise

    async def async_close_valve(self) -> None:
        """Close the valve with operation state feedback."""
        self._set_operation_state(OperationState.CONNECTING)
        try:
            self._set_operation_state(OperationState.CLOSING)
            real_status = await self.device.close_valve()
            self._set_operation_state(OperationState.CONFIRMED)
            self._record_irrigation_end()
            if real_status:
                self._last_known_status = real_status
            else:
                self._last_known_status = GalconStatus(
                    valve_open=False,
                    manual_open=False,
                    hours_remaining=0,
                    minutes_remaining=0,
                    seconds_remaining=0,
                    raw=self._last_known_status.raw if self._last_known_status else b"",
                    battery_level=self._last_known_status.battery_level if self._last_known_status else None,
                )
            self.async_set_updated_data(self._last_known_status)
        except (ConnectionError, Exception):
            self._set_operation_state(OperationState.ERROR)
            raise

    def async_irrigation_ended(self) -> None:
        """Called when the local countdown reaches zero.

        Updates cached status to valve-closed and disables scanning
        to conserve battery.
        """
        _LOGGER.info(
            "Galcon %s: irrigation timer expired — marking valve closed and disabling scanning",
            self.device.address,
        )
        self._record_irrigation_end()
        self._last_known_status = GalconStatus(
            valve_open=False,
            manual_open=False,
            hours_remaining=0,
            minutes_remaining=0,
            seconds_remaining=0,
            raw=self._last_known_status.raw if self._last_known_status else b"",
            battery_level=self._last_known_status.battery_level if self._last_known_status else None,
        )
        self.async_set_updated_data(self._last_known_status)
        self.set_polling(False)
