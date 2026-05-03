"""Unit tests for protocol.py.

The auth CRC test cross-checks our port against an independent literal
transcription of main.c from sasodoma/blazepod-hacking. Two ports producing the
same output for the documented example vector gives reasonable confidence the
port is correct.
"""

from __future__ import annotations

import pytest

from blazepod.protocol import (
    AUTH_PREFIX,
    COLOR_OFF,
    TapState,
    build_auth_payload,
    compute_auth_suffix,
    decode_tap,
    encode_color,
)


U32 = 0xFFFFFFFF


def _reference_c_port(offset: int, byte_array: bytes) -> list[int]:
    """Literal line-by-line port of main.c — kept independent from protocol.py."""
    poly = (0xEDB88321 + (offset % 50)) & U32

    crc = 0xFFFFFFFF
    for b in byte_array:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = ((crc >> 1) ^ poly) & U32
            else:
                crc = (crc >> 1) & U32

    crc = (crc ^ 0xFFFFFFFF) & U32
    crc = (crc + ((crc << 3) & U32)) & U32
    crc = (crc ^ (crc >> 11)) & U32
    crc = (crc + ((crc << 15) & U32)) & U32

    return [
        0x73, 0x65, 0x61,
        crc & 0xFF, (crc >> 8) & 0xFF, (crc >> 16) & 0xFF, (crc >> 24) & 0xFF,
    ]


# Documented example from the reference readme:
#   ManufacturerSpecificData: D7-09-5A-01-DE-AD-BE-EF
#   last 5 bytes: 01-DE-AD-BE-EF
#   offset = 0x01, byte_array = {DE, AD, BE, EF}
README_EXAMPLE_MFR_DATA = bytes.fromhex("5A01DEADBEEF")
# Note: Bleak strips the 2-byte company ID (D7-09) before exposing
# manufacturer_data, so this is what we'd actually receive from the BLE stack.


def test_auth_prefix_is_sea():
    assert AUTH_PREFIX == b"sea"


def test_auth_payload_matches_independent_c_port():
    expected = bytes(_reference_c_port(0x01, b"\xDE\xAD\xBE\xEF"))
    actual = build_auth_payload(README_EXAMPLE_MFR_DATA)
    assert actual == expected, f"got {actual.hex()}, expected {expected.hex()}"


def test_auth_payload_starts_with_sea():
    payload = build_auth_payload(README_EXAMPLE_MFR_DATA)
    assert payload[:3] == b"sea"
    assert len(payload) == 7


def test_auth_uses_only_last_five_bytes():
    """Leading bytes of mfr data must not influence the suffix."""
    base = compute_auth_suffix(README_EXAMPLE_MFR_DATA)
    padded = compute_auth_suffix(b"\x00\xAA\xBB" + README_EXAMPLE_MFR_DATA)
    assert base == padded


def test_auth_offset_changes_polynomial():
    """Different offset bytes (mod 50) must produce different suffixes."""
    a = compute_auth_suffix(b"\x01\xDE\xAD\xBE\xEF")
    b = compute_auth_suffix(b"\x02\xDE\xAD\xBE\xEF")
    assert a != b


def test_auth_short_data_raises():
    with pytest.raises(ValueError):
        compute_auth_suffix(b"\x00\x01\x02\x03")  # only 4 bytes


@pytest.mark.parametrize("offset", [0, 1, 25, 49, 50, 99, 200, 255])
def test_auth_matches_c_port_across_offsets(offset):
    body = b"\x12\x34\x56\x78"
    expected = bytes(_reference_c_port(offset, body))
    actual = build_auth_payload(bytes([offset]) + body)
    assert actual == expected


def test_encode_color_g_b_r_order():
    # red = (255, 0, 0) → wire bytes G=0, B=0, R=255
    assert encode_color(255, 0, 0) == b"\x00\x00\xFF"
    # green
    assert encode_color(0, 255, 0) == b"\xFF\x00\x00"
    # blue
    assert encode_color(0, 0, 255) == b"\x00\xFF\x00"


def test_encode_color_off_on_tap_appends_flag():
    assert encode_color(10, 20, 30, off_on_tap=True) == b"\x14\x1E\x0A\x01"


def test_color_off_constant():
    assert COLOR_OFF == b"\x00\x00\x00"


def test_encode_color_validates_range():
    with pytest.raises(ValueError):
        encode_color(-1, 0, 0)
    with pytest.raises(ValueError):
        encode_color(0, 256, 0)


def test_decode_tap_lit_then_off():
    # readme example: lit for 25s (0x61A8 ms), turned off after tap.
    payload = bytes.fromhex("25A861000000000000")[:8]
    ev = decode_tap(payload)
    assert ev.state == TapState.LIT_OFF
    assert ev.elapsed_ms == 0x61A8
    assert ev.hit_lit_pod


def test_decode_tap_off_pod():
    payload = bytes.fromhex("0000000000000000")
    ev = decode_tap(payload)
    assert ev.state == TapState.OFF
    assert ev.elapsed_ms == 0
    assert not ev.hit_lit_pod


def test_decode_tap_lit_stay():
    payload = bytes.fromhex("21E8030000000000")
    ev = decode_tap(payload)
    assert ev.state == TapState.LIT_STAY
    assert ev.elapsed_ms == 1000  # 0x3E8
    assert ev.hit_lit_pod


def test_decode_tap_unknown_state_raises():
    with pytest.raises(ValueError):
        decode_tap(bytes.fromhex("FF00000000000000"))


def test_decode_tap_short_payload_raises():
    with pytest.raises(ValueError):
        decode_tap(b"\x00\x00")
