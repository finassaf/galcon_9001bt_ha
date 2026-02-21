"""BLE communication layer for Galcon 9001BT irrigation controller."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import establish_connection

from .const import (
    CMD_CLOSE_VALVE,
    CMD_OPEN_VALVE,
    COMMAND_VERIFY_ATTEMPTS,
    CONNECT_TIMEOUT,
    MAX_RETRIES,
    POST_COMMAND_DELAY,
    STATUS_MANUAL_OPEN_MASK,
    STATUS_VALVE_OPEN_MASK,
    UUID_CONTROL,
    UUID_STATUS,
    UUID_WAKE,
    WAKE_PAYLOAD,
    WAKE_SETTLE_DELAY,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class GalconStatus:
    """Parsed status from the Galcon device."""

    valve_open: bool
    manual_open: bool
    hours_remaining: int
    minutes_remaining: int
    seconds_remaining: int
    raw: bytes
    battery_level: int | None = None  # 0-100%, from byte 5

    @property
    def time_remaining_seconds(self) -> int:
        """Return total remaining time in seconds."""
        return (
            self.hours_remaining * 3600
            + self.minutes_remaining * 60
            + self.seconds_remaining
        )


class GalconDevice:
    """Manages BLE communication with a Galcon 9001BT irrigation controller."""

    def __init__(self, address: str) -> None:
        """Initialize the Galcon BLE device.

        Args:
            address: Bluetooth MAC address of the device (e.g., "AA:BB:CC:DD:EE:FF").
        """
        self.address = address
        self._lock = asyncio.Lock()
        self._ble_device: BLEDevice | None = None

    def set_ble_device(self, ble_device: BLEDevice) -> None:
        """Update the BLEDevice reference (from HA's bluetooth scanner)."""
        self._ble_device = ble_device

    async def _execute(self, callback) -> any:
        """Connect to the device, execute a callback, and disconnect.

        Handles retries on BLE errors. The callback receives the BleakClient.
        Uses bleak-retry-connector when a BLEDevice is available (from HA's
        bluetooth scanner), otherwise falls back to raw BleakClient.
        """
        last_error: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                if self._ble_device is not None:
                    client = await establish_connection(
                        BleakClient,
                        self._ble_device,
                        self.address,
                        max_attempts=2,
                    )
                else:
                    client = BleakClient(
                        self.address, timeout=CONNECT_TIMEOUT
                    )
                    await client.connect()
                try:
                    if not client.is_connected:
                        raise BleakError("Failed to connect")
                    return await callback(client)
                finally:
                    await client.disconnect()
            except (BleakError, asyncio.TimeoutError, OSError) as err:
                last_error = err
                _LOGGER.debug(
                    "Galcon BLE attempt %d/%d failed for %s: %s",
                    attempt,
                    MAX_RETRIES,
                    self.address,
                    err,
                )
                if attempt < MAX_RETRIES:
                    # Exponential-ish backoff — give the BLE device time to wake
                    await asyncio.sleep(2.0 * attempt)

        raise ConnectionError(
            f"Failed to communicate with Galcon device {self.address} "
            f"after {MAX_RETRIES} attempts: {last_error}"
        )

    async def wake_up(self, client: BleakClient) -> None:
        """Send the wake-up command and wait for the device to settle."""
        await client.write_gatt_char(UUID_WAKE, WAKE_PAYLOAD, response=True)
        await asyncio.sleep(WAKE_SETTLE_DELAY)
        _LOGGER.debug("Wake-up sent to %s", self.address)

    async def _read_status_raw(self, client: BleakClient) -> GalconStatus:
        """Read status from an already-connected client (no wake-up)."""
        data = await client.read_gatt_char(UUID_STATUS)
        return self._parse_status(data)

    async def get_status(self) -> GalconStatus:
        """Read and parse the current status from the device."""
        async with self._lock:

            async def _read(client: BleakClient) -> GalconStatus:
                await self.wake_up(client)
                return await self._read_status_raw(client)

            return await self._execute(_read)

    async def _verified_command(
        self,
        client: BleakClient,
        payload: bytes,
        expect_open: bool,
    ) -> GalconStatus | None:
        """Send a command and verify the valve reached the expected state.

        Within a single BLE connection:
          1. Wake the device
          2. Read current status (confirms device is responsive)
          3. Write the command
          4. Wait for the device to process
          5. Read status back and verify
          6. Retry steps 3-5 up to COMMAND_VERIFY_ATTEMPTS times

        Returns the post-command GalconStatus if successful, None otherwise.
        """
        await self.wake_up(client)

        # Pre-read to make sure device is alive
        pre_status = await self._read_status_raw(client)
        _LOGGER.debug(
            "Pre-command status on %s: valve_open=%s",
            self.address,
            pre_status.valve_open,
        )

        # If already in the desired state, no need to send
        if pre_status.valve_open == expect_open:
            _LOGGER.info(
                "Valve on %s already %s, skipping command",
                self.address,
                "open" if expect_open else "closed",
            )
            return pre_status

        for attempt in range(1, COMMAND_VERIFY_ATTEMPTS + 1):
            _LOGGER.debug(
                "Sending %s command to %s (attempt %d/%d)",
                "OPEN" if expect_open else "CLOSE",
                self.address,
                attempt,
                COMMAND_VERIFY_ATTEMPTS,
            )
            await client.write_gatt_char(UUID_CONTROL, payload, response=True)
            await asyncio.sleep(POST_COMMAND_DELAY)

            # Re-wake before reading — the device may have gone back to
            # sleep after processing the command, returning stale data.
            try:
                await client.write_gatt_char(UUID_WAKE, WAKE_PAYLOAD, response=True)
                await asyncio.sleep(0.5)
            except (BleakError, asyncio.TimeoutError, OSError):
                pass  # Best effort; continue to read anyway

            # Read back and verify
            try:
                post_status = await self._read_status_raw(client)
                _LOGGER.debug(
                    "Post-command status on %s: valve_open=%s (expected %s)",
                    self.address,
                    post_status.valve_open,
                    expect_open,
                )

                if post_status.valve_open == expect_open:
                    _LOGGER.info(
                        "Valve %s confirmed on %s (attempt %d)",
                        "OPEN" if expect_open else "CLOSED",
                        self.address,
                        attempt,
                    )
                    return post_status
            except (BleakError, asyncio.TimeoutError, OSError) as err:
                _LOGGER.debug(
                    "Verify read failed on %s: %s", self.address, err
                )

            # Not yet — give it a bit more time before retrying
            await asyncio.sleep(1.0)

        _LOGGER.warning(
            "Valve on %s did not confirm %s after %d attempts",
            self.address,
            "open" if expect_open else "closed",
            COMMAND_VERIFY_ATTEMPTS,
        )
        return False

    async def open_valve(
        self, hours: int = 0, minutes: int = 0, seconds: int = 0
    ) -> GalconStatus | None:
        """Open the irrigation valve with verified write.

        Returns the post-command GalconStatus if available.
        """
        async with self._lock:
            if hours == 0 and minutes == 0 and seconds == 0:
                payload = CMD_OPEN_VALVE
            else:
                payload = bytes(
                    [0x00, 0x03, 0x00, hours & 0xFF, minutes & 0xFF, seconds & 0xFF, 0x00]
                )

            async def _open(client: BleakClient) -> GalconStatus | None:
                result = await self._verified_command(
                    client, payload, expect_open=True
                )
                if not result:
                    _LOGGER.warning(
                        "Valve OPEN on %s sent but not confirmed by readback "
                        "(command likely succeeded — device is slow to update)",
                        self.address,
                    )
                _LOGGER.info(
                    "Valve opened on %s (duration: %02d:%02d:%02d)",
                    self.address,
                    hours,
                    minutes,
                    seconds,
                )
                return result

            return await self._execute(_open)

    async def close_valve(self) -> GalconStatus | None:
        """Close the irrigation valve with verified write.

        Returns the post-command GalconStatus if available.
        """
        async with self._lock:

            async def _close(client: BleakClient) -> GalconStatus | None:
                result = await self._verified_command(
                    client, CMD_CLOSE_VALVE, expect_open=False
                )
                if not result:
                    _LOGGER.warning(
                        "Valve CLOSE on %s sent but not confirmed by readback "
                        "(command likely succeeded — device is slow to update)",
                        self.address,
                    )
                _LOGGER.info("Valve closed on %s", self.address)
                return result

            return await self._execute(_close)

    @staticmethod
    def _parse_status(data: bytes) -> GalconStatus:
        """Parse raw status bytes into a GalconStatus object.

        Status byte layout:
            Byte 0, bit 0: valve open (1) / closed (0)
            Byte 1: manual open flag
            Byte 2: remaining hours
            Byte 3: remaining minutes
            Byte 4: remaining seconds
            Byte 5: battery level (0-100%)
            Byte 6: unknown
        """
        if len(data) < 5:
            _LOGGER.warning("Unexpected status length: %d bytes", len(data))
            return GalconStatus(
                valve_open=False,
                manual_open=False,
                hours_remaining=0,
                minutes_remaining=0,
                seconds_remaining=0,
                raw=data,
            )

        valve_open = bool(data[0] & STATUS_VALVE_OPEN_MASK)
        manual_open = bool(data[1] & STATUS_MANUAL_OPEN_MASK) if len(data) > 1 else False
        hours = data[2] if len(data) > 2 else 0
        minutes = data[3] if len(data) > 3 else 0
        seconds = data[4] if len(data) > 4 else 0
        battery = data[5] if len(data) > 5 else None

        return GalconStatus(
            valve_open=valve_open,
            manual_open=manual_open,
            hours_remaining=hours,
            minutes_remaining=minutes,
            seconds_remaining=seconds,
            raw=data,
            battery_level=battery,
        )
