"""BlazePod BLE wire protocol.

Reverse-engineered by https://github.com/sasodoma/blazepod-hacking — this module
ports the C reference (main.c) verbatim and exposes typed encode/decode helpers.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

UART_SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
UART_RX_CHAR_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"

COLOR_SERVICE_UUID = "50c97bfa-4cb8-4c84-b745-0e58a0280cd6"
COLOR_CHAR_UUID = "50c912a2-4cb8-4c84-b745-0e58a0280cd6"

TAP_SERVICE_UUID = "50c928bd-4cb8-4c84-b745-0e58a0280cd6"
TAP_CHAR_UUID = "50c9727e-4cb8-4c84-b745-0e58a0280cd6"

AUTH_PREFIX = bytes([0x73, 0x65, 0x61])  # "sea"

_U32_MASK = 0xFFFFFFFF


class TapState(IntEnum):
    OFF = 0x00       # tap on a pod that was off
    LIT_STAY = 0x21  # tap on a lit pod that stayed lit
    LIT_OFF = 0x25   # tap on a lit pod that turned off


@dataclass(frozen=True, slots=True)
class TapEvent:
    state: TapState
    elapsed_ms: int  # since the pod was last lit; 0 when state == OFF
    raw: bytes       # full 8-byte payload (last 3 bytes are unknown)

    @property
    def hit_lit_pod(self) -> bool:
        return self.state in (TapState.LIT_STAY, TapState.LIT_OFF)


def compute_auth_suffix(mfr_data: bytes) -> bytes:
    """Compute the 4-byte auth suffix from a pod's manufacturer-specific data.

    `mfr_data` is the value bytes of the manufacturer-specific advertisement
    record (i.e. what Bleak puts in `AdvertisementData.manufacturer_data[id]`),
    NOT including the 2-byte company ID.

    Per the reference (sasodoma/blazepod-hacking/main.c):
      - take the last 5 bytes of mfr_data
      - first byte = `offset`, remaining 4 = `byte_array`
      - poly = 0xEDB88321 + (offset % 50)
      - standard CRC32 (init 0xFFFFFFFF, final XOR 0xFFFFFFFF) over byte_array
      - mix: c+=c<<3; c^=c>>11; c+=c<<15
      - emit as little-endian u32
    """
    if len(mfr_data) < 5:
        raise ValueError(f"manufacturer data too short: {len(mfr_data)} bytes, need >= 5")

    tail = mfr_data[-5:]
    offset = tail[0]
    byte_array = tail[1:]

    poly = (0xEDB88321 + (offset % 50)) & _U32_MASK

    crc = 0xFFFFFFFF
    for b in byte_array:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = ((crc >> 1) ^ poly) & _U32_MASK
            else:
                crc = (crc >> 1) & _U32_MASK

    crc ^= 0xFFFFFFFF
    crc &= _U32_MASK

    crc = (crc + ((crc << 3) & _U32_MASK)) & _U32_MASK
    crc = (crc ^ (crc >> 11)) & _U32_MASK
    crc = (crc + ((crc << 15) & _U32_MASK)) & _U32_MASK

    return crc.to_bytes(4, "little")


def build_auth_payload(mfr_data: bytes) -> bytes:
    """Full 7-byte auth payload to write to the UART RX characteristic."""
    return AUTH_PREFIX + compute_auth_suffix(mfr_data)


def encode_color(r: int, g: int, b: int, *, off_on_tap: bool = False) -> bytes:
    """Encode an RGB color for the color characteristic.

    BlazePod expects channels in **G B R** order (not RGB). The optional 4th
    byte 0x01 makes the pod auto-extinguish when tapped.
    """
    for name, v in (("r", r), ("g", g), ("b", b)):
        if not 0 <= v <= 255:
            raise ValueError(f"{name} out of range 0..255: {v}")
    payload = bytes([g, b, r])
    if off_on_tap:
        payload += b"\x01"
    return payload


COLOR_OFF = encode_color(0, 0, 0)


def decode_tap(payload: bytes) -> TapEvent:
    """Decode an 8-byte tap notification payload."""
    if len(payload) < 5:
        raise ValueError(f"tap payload too short: {len(payload)} bytes")
    state_byte = payload[0]
    try:
        state = TapState(state_byte)
    except ValueError as e:
        raise ValueError(f"unknown tap state byte 0x{state_byte:02X}") from e
    elapsed_ms = int.from_bytes(payload[1:5], "little")
    return TapEvent(state=state, elapsed_ms=elapsed_ms, raw=bytes(payload))
