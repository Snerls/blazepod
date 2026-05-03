"""Probe BlazePod GATT services for any readable characteristic that could
substitute for manufacturerData (which iOS hides from JavaScript).

For each pod found, prints:
  - mfr_data captured from BLE advertisement (the input we want to replace)
  - Every primary service and characteristic
  - For each readable characteristic: its raw bytes + ASCII interpretation
  - Highlights anything containing the same bytes as mfr_data
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str((Path(__file__).parent.parent / 'src').resolve()))

from bleak import BleakClient

from blazepod.manager import discover_until


def _ascii(b: bytes) -> str:
    return ''.join(chr(c) if 32 <= c < 127 else '.' for c in b)


def _matches_mfr(value: bytes, mfr: bytes) -> str:
    """Return a tag if `value` contains any meaningful slice of mfr."""
    tags = []
    if value == mfr:                 tags.append('FULL MATCH')
    if value == mfr[-5:]:            tags.append('matches last-5')
    if value == mfr[-4:]:            tags.append('matches last-4 (CRC body)')
    if mfr in value:                 tags.append('mfr is substring')
    if mfr[-5:] in value:            tags.append('last-5 is substring')
    if mfr[-4:] in value:            tags.append('last-4 is substring')
    if value[::-1] == mfr:           tags.append('matches reversed')
    if value[::-1] == mfr[-5:]:      tags.append('matches reversed last-5')
    return ('  ** ' + ' / '.join(tags) + ' **') if tags else ''


async def probe(pod_addr: str, mfr: bytes, ble_device) -> None:
    print(f"\n{'#' * 70}\n# {pod_addr}  mfr={mfr.hex()}\n{'#' * 70}")
    async with BleakClient(ble_device) as client:
        for service in client.services:
            print(f"\n[svc] {service.uuid}  '{service.description}'")
            for char in service.characteristics:
                props = ','.join(char.properties)
                line = f"  [chr] {char.uuid}  '{char.description}'  ({props})"
                if 'read' in char.properties:
                    try:
                        val = bytes(await client.read_gatt_char(char.uuid))
                        match_tag = _matches_mfr(val, mfr)
                        print(f"{line}{match_tag}")
                        print(f"        bytes: {val.hex()}  ({len(val)}B)")
                        print(f"        ascii: {_ascii(val)!r}")
                    except Exception as e:
                        print(f"{line}\n        READ FAILED: {type(e).__name__}: {e}")
                else:
                    print(line)


async def main() -> int:
    print("scanning for pods (up to 30s)...")
    pods = await discover_until(target=None, max_wait=30.0)
    if not pods:
        print("no pods found")
        return 1
    print(f"found {len(pods)}, probing each in turn")
    for p in pods[:3]:  # cap at 3 so we don't hammer the BLE adapter
        try:
            await probe(p.address, p.mfr_data, p.device)
        except Exception as e:
            print(f"\n!! probe of {p.address} failed: {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
