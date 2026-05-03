"""Probe: does the BlazePod auth handshake actually validate the secret?

If the pod accepts arbitrary "sea" + 4-byte payloads, we can skip the
advertisement-read entirely and connect from iPhone with a hardcoded payload.
That would unlock the iPhone-only Bluefy path.

Tests one pod with several auth payloads:
  1. Correct mfr-derived auth          (baseline — must work)
  2. "sea" + random 4 bytes            (does any "sea" payload work?)
  3. "sea" + zero 4 bytes              (degenerate case)
  4. Wrong prefix "ABC" + correct CRC  (is the prefix checked?)
  5. No auth write at all              (is auth even required?)

After each, write color RED and check whether it appears (using subsequent
notify behavior as proxy: if pod accepts color, it will register taps).
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str((Path(__file__).parent.parent / 'src').resolve()))

from bleak import BleakClient
from blazepod.manager import discover_until
from blazepod.protocol import (
    AUTH_PREFIX, COLOR_CHAR_UUID, COLOR_SERVICE_UUID,
    UART_RX_CHAR_UUID, UART_SERVICE_UUID,
    build_auth_payload, encode_color,
)


async def try_payload(addr_or_dev, label: str, auth_bytes: bytes | None) -> bool:
    """Connect to pod, optionally write auth, then write red color. Return True if pod responds."""
    print(f"\n--- {label} ---")
    if auth_bytes is not None:
        print(f"  auth bytes: {auth_bytes.hex()} ({len(auth_bytes)}B)")
    else:
        print(f"  auth bytes: <none — skipping auth write>")

    pod_lit = False
    try:
        async with BleakClient(addr_or_dev, timeout=15.0) as client:
            print(f"  connected: {client.is_connected}")
            if auth_bytes is not None:
                try:
                    await client.write_gatt_char(UART_RX_CHAR_UUID, auth_bytes, response=True)
                    print("  auth write: OK")
                except Exception as e:
                    print(f"  auth write FAILED: {type(e).__name__}: {e}")
                    return False
            try:
                # Write red. If pod accepts color writes, it lights up.
                await client.write_gatt_char(COLOR_CHAR_UUID, encode_color(255, 0, 0), response=False)
                print("  color write: OK (no error)")
                await asyncio.sleep(1.5)
                await client.write_gatt_char(COLOR_CHAR_UUID, encode_color(0, 0, 0), response=False)
                pod_lit = True
            except Exception as e:
                print(f"  color write FAILED: {type(e).__name__}: {e}")
                pod_lit = False
        print(f"  result: {'LIT' if pod_lit else 'NO RESPONSE'}")
        return pod_lit
    except Exception as e:
        print(f"  connect/teardown failed: {type(e).__name__}: {e}")
        return False


async def main() -> int:
    pods = await discover_until(target=1, max_wait=20.0)
    if not pods:
        print("no pods found")
        return 1
    p = pods[0]
    print(f"using pod {p.address}  name='{p.name}'  mfr={p.mfr_data.hex()}")
    real_auth = build_auth_payload(p.mfr_data)
    print(f"computed correct auth: {real_auth.hex()}")

    results = {}

    # 1. Baseline — correct auth
    results['1. correct auth'] = await try_payload(p.device, "1. CORRECT auth (baseline)", real_auth)
    await asyncio.sleep(2)

    # 2. "sea" + random 4 bytes
    rand = b"sea" + os.urandom(4)
    results['2. sea + random 4'] = await try_payload(p.device, "2. 'sea' + RANDOM 4 bytes", rand)
    await asyncio.sleep(2)

    # 3. "sea" + zero bytes
    zero = b"sea" + b"\x00\x00\x00\x00"
    results['3. sea + zeros'] = await try_payload(p.device, "3. 'sea' + ZEROS", zero)
    await asyncio.sleep(2)

    # 4. Wrong prefix
    wrong = b"ABC" + real_auth[3:]
    results['4. wrong prefix'] = await try_payload(p.device, "4. WRONG prefix 'ABC' + correct CRC", wrong)
    await asyncio.sleep(2)

    # 5. No auth at all
    results['5. no auth'] = await try_payload(p.device, "5. NO auth write at all", None)

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for k, v in results.items():
        print(f"  {'LIT' if v else 'NO ':3}  {k}")

    if all(results.values()):
        print("\n>>> AUTH IS NOT VALIDATED — any payload (or none) lets us light the pod!")
        print(">>> This unlocks the iPhone Bluefy path: hardcoded auth or no auth needed.")
    elif results['1. correct auth'] and results['2. sea + random 4']:
        print("\n>>> Auth check is LENIENT — any 'sea'-prefixed 7-byte payload works.")
        print(">>> Hardcoded auth from iPhone should work.")
    elif results['1. correct auth']:
        print("\n>>> Auth IS validated — needs the correct mfr-derived payload.")
        print(">>> iPhone-only path remains blocked.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
