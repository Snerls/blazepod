"""During the 10-second pre-disconnect window, observe EVERY notification the
pod sends. Hypothesis: the pod transmits its expected auth payload (or a
challenge derivable to one) via Nordic UART TX or another characteristic.

For each candidate, we connect, subscribe to all notify chars, write fake
static auth, then log everything received until disconnect or 12s elapse.
"""

from __future__ import annotations
import asyncio, sys, time
from pathlib import Path
sys.path.insert(0, str((Path(__file__).parent.parent / 'src').resolve()))
from bleak import BleakClient
from blazepod.manager import discover_until
from blazepod.protocol import UART_RX_CHAR_UUID

UART_TX_CHAR_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
DFU_CHAR_UUID    = "8e400001-f315-4f60-9fb8-838830daea50"
TAP_CHAR_UUID    = "50c9727e-4cb8-4c84-b745-0e58a0280cd6"


async def main() -> int:
    pods = await discover_until(target=1, max_wait=20.0)
    if not pods: return 1
    p = pods[0]
    print(f"using {p.address}  mfr={p.mfr_data.hex()}\n")

    # Connect WITHOUT writing real auth, subscribe to every notify-capable
    # characteristic, then write fake static auth and log all events.
    async with BleakClient(p.device, timeout=15.0) as client:
        notifs: list[tuple[float, str, bytes]] = []
        t0 = time.monotonic()

        def make_handler(label):
            def h(_sender, data):
                notifs.append((time.monotonic() - t0, label, bytes(data)))
                print(f"  +{time.monotonic() - t0:5.2f}s  {label:8s}  {bytes(data).hex()}  ({len(data)}B)")
            return h

        # Subscribe to every notify-capable char we know about
        targets = [
            ("UART_TX", UART_TX_CHAR_UUID),
            ("DFU",     DFU_CHAR_UUID),
            ("TAP",     TAP_CHAR_UUID),
        ]
        for label, uuid in targets:
            try:
                await client.start_notify(uuid, make_handler(label))
                print(f"subscribed to {label} ({uuid})")
            except Exception as e:
                print(f"  could not subscribe to {label}: {type(e).__name__}: {e}")
        print()

        # Write fake auth
        fake = b"sea\x00\x00\x00\x00"
        print(f"writing FAKE auth: {fake.hex()}")
        try:
            await client.write_gatt_char(UART_RX_CHAR_UUID, fake, response=True)
            print("  fake auth written\n")
        except Exception as e:
            print(f"  fake auth write failed: {type(e).__name__}: {e}\n")

        # Listen for 12 seconds (covers the 10s disconnect window)
        for sec in range(12):
            await asyncio.sleep(1)
            if not client.is_connected:
                print(f"\n  >>> DISCONNECTED at +{sec+1}s")
                break

        print(f"\nfinal: connected={client.is_connected}  notifications received={len(notifs)}")
        if notifs:
            print("by characteristic:")
            for label in ['UART_TX', 'DFU', 'TAP']:
                hits = [n for n in notifs if n[1] == label]
                print(f"  {label}: {len(hits)} event(s)")

        # Try unsubscribing cleanly
        for _, uuid in targets:
            try: await client.stop_notify(uuid)
            except Exception: pass

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
