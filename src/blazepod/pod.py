"""Single-pod BLE client wrapping a BleakClient with the BlazePod handshake."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from bleak import BleakClient
from bleak.backends.device import BLEDevice

from blazepod.protocol import (
    COLOR_CHAR_UUID,
    COLOR_OFF,
    TAP_CHAR_UUID,
    UART_RX_CHAR_UUID,
    TapEvent,
    build_auth_payload,
    decode_tap,
    encode_color,
)

log = logging.getLogger(__name__)

TapCallback = Callable[["Pod", TapEvent], Awaitable[None] | None]


@dataclass
class DiscoveredPod:
    """A pod found during a BLE scan, with the data needed to authenticate."""
    device: BLEDevice
    mfr_data: bytes  # value from AdvertisementData.manufacturer_data
    rssi: int = 0
    name: str = ""

    @property
    def address(self) -> str:
        return self.device.address


class Pod:
    """A connected (or connectable) BlazePod."""

    def __init__(self, discovered: DiscoveredPod, on_tap: TapCallback | None = None) -> None:
        self._discovered = discovered
        self._client = BleakClient(discovered.device)
        self._on_tap = on_tap
        self._tap_listeners: list[TapCallback] = []
        if on_tap is not None:
            self._tap_listeners.append(on_tap)

    @property
    def address(self) -> str:
        return self._discovered.address

    @property
    def name(self) -> str:
        return self._discovered.name or self._discovered.device.name or self.address

    @property
    def is_connected(self) -> bool:
        return self._client.is_connected

    def add_tap_listener(self, cb: TapCallback) -> None:
        self._tap_listeners.append(cb)

    def clear_tap_listeners(self) -> None:
        self._tap_listeners.clear()

    async def connect(self) -> None:
        """Connect, send the auth handshake, and subscribe to tap notifications."""
        log.info("connecting to %s", self.address)
        await self._client.connect()
        try:
            payload = build_auth_payload(self._discovered.mfr_data)
            log.debug("auth payload for %s: %s", self.address, payload.hex())
            await self._client.write_gatt_char(UART_RX_CHAR_UUID, payload, response=True)
            await self._client.start_notify(TAP_CHAR_UUID, self._handle_notify)
        except Exception:
            await self._client.disconnect()
            raise

    async def set_color(self, r: int, g: int, b: int, *, off_on_tap: bool = False) -> None:
        await self._client.write_gatt_char(
            COLOR_CHAR_UUID,
            encode_color(r, g, b, off_on_tap=off_on_tap),
            response=False,
        )

    async def turn_off(self) -> None:
        await self._client.write_gatt_char(COLOR_CHAR_UUID, COLOR_OFF, response=False)

    async def flash(
        self,
        r: int = 255, g: int = 0, b: int = 0,
        *,
        count: int = 3,
        on_s: float = 0.25,
        off_s: float = 0.2,
    ) -> None:
        """Pulse the pod a given color N times — useful for identifying which pod is which."""
        for i in range(count):
            await self.set_color(r, g, b)
            await asyncio.sleep(on_s)
            await self.turn_off()
            if i < count - 1:
                await asyncio.sleep(off_s)

    async def disconnect(self) -> None:
        if self._client.is_connected:
            try:
                await self._client.stop_notify(TAP_CHAR_UUID)
            except Exception:
                pass
            await self._client.disconnect()

    async def __aenter__(self) -> "Pod":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.disconnect()

    def _handle_notify(self, _sender, data: bytearray) -> None:
        try:
            event = decode_tap(bytes(data))
        except ValueError as e:
            log.warning("bad tap payload from %s: %s (%s)", self.address, bytes(data).hex(), e)
            return
        for cb in list(self._tap_listeners):
            result = cb(self, event)
            if asyncio.iscoroutine(result):
                asyncio.create_task(result)
