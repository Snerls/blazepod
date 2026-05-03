"""Test whether the auth check is per-pod or per-shape.

Connects pod A, writes the auth payload computed from pod B's mfr_data,
holds 25 seconds. If pod A stays connected, the auth check is structural
(any valid-CRC auth works) and we can hardcode one. If it disconnects at
~10s, the auth is bound to this specific pod and we cannot hardcode.
"""

from __future__ import annotations
import asyncio, sys, time
from pathlib import Path
sys.path.insert(0, str((Path(__file__).parent.parent / 'src').resolve()))
from bleak import BleakClient
from blazepod.manager import discover_until
from blazepod.protocol import UART_RX_CHAR_UUID, build_auth_payload


async def main() -> int:
    pods = await discover_until(target=2, max_wait=20.0)
    if len(pods) < 2:
        print(f"need 2 pods, got {len(pods)}")
        return 1
    pod_a, pod_b = pods[0], pods[1]
    print(f"pod A: {pod_a.address}  mfr={pod_a.mfr_data.hex()}")
    print(f"pod B: {pod_b.address}  mfr={pod_b.mfr_data.hex()}")

    # Auth from B
    auth_from_b = build_auth_payload(pod_b.mfr_data)
    print(f"auth derived from B's mfrData: {auth_from_b.hex()}")
    # Auth from A (correct one for A) — kept for second test
    auth_from_a = build_auth_payload(pod_a.mfr_data)
    print(f"auth derived from A's mfrData (correct for A): {auth_from_a.hex()}\n")

    print("=== TEST 1: write B's auth to A, hold 25s ===")
    async with BleakClient(pod_a.device, timeout=15.0) as c:
        t0 = time.monotonic()
        try:
            await c.write_gatt_char(UART_RX_CHAR_UUID, auth_from_b, response=True)
            print(f"  +{time.monotonic()-t0:.1f}s  wrote B's auth to A")
        except Exception as e:
            print(f"  WRITE FAILED: {e}")
            return 2
        for sec in range(13):
            await asyncio.sleep(2)
            if not c.is_connected:
                print(f"  +{time.monotonic()-t0:5.1f}s  DISCONNECTED")
                break
            print(f"  +{time.monotonic()-t0:5.1f}s  still connected")
        result_b = c.is_connected
        print(f"  final: connected={result_b}\n")

    await asyncio.sleep(2)

    print("=== TEST 2: control - write A's correct auth to A, hold 25s ===")
    pods2 = await discover_until(target=1, max_wait=15.0)
    if not pods2:
        print("  control: re-scan failed")
        return 3
    pod_a2 = next((p for p in pods2 if p.address == pod_a.address), pods2[0])
    auth_from_a_fresh = build_auth_payload(pod_a2.mfr_data)
    print(f"  fresh A mfr: {pod_a2.mfr_data.hex()}  auth: {auth_from_a_fresh.hex()}")
    async with BleakClient(pod_a2.device, timeout=15.0) as c:
        t0 = time.monotonic()
        try:
            await c.write_gatt_char(UART_RX_CHAR_UUID, auth_from_a_fresh, response=True)
            print(f"  +{time.monotonic()-t0:.1f}s  wrote A's correct auth")
        except Exception as e:
            print(f"  WRITE FAILED: {e}")
            return 4
        for sec in range(13):
            await asyncio.sleep(2)
            if not c.is_connected:
                print(f"  +{time.monotonic()-t0:5.1f}s  DISCONNECTED")
                break
            print(f"  +{time.monotonic()-t0:5.1f}s  still connected")
        result_a = c.is_connected
        print(f"  final: connected={result_a}\n")

    print("=" * 50)
    print(f"  CROSS-POD auth (B's auth on A): {'SUSTAINED' if result_b else 'KICKED at ~10s'}")
    print(f"  CORRECT-pod auth (A's auth on A): {'SUSTAINED' if result_a else 'KICKED'}")
    if result_b:
        print("\n  >>> Auth is STRUCTURAL — any valid CRC sustains. Hardcoded auth is viable!")
    elif result_a and not result_b:
        print("\n  >>> Auth is per-pod — we need the specific pod's mfrData. Hardcoded auth NOT viable.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
