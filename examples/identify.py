"""Find pods, connect to all of them, then flash each one red in sequence so
you can map BLE address -> physical pod.

Usage:
  python examples/identify.py -n 6 --timeout 60
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from blazepod import Pod, PodManager
from blazepod.manager import discover_until


async def run(target: int | None, max_wait: float) -> None:
    print(f"scanning for {target or 'all'} pod(s), up to {max_wait:.0f}s...")
    seen = 0

    def on_progress(found):
        nonlocal seen
        for p in found[seen:]:
            print(f"  found {p.address}  rssi={p.rssi:>4}  name={p.name!r}")
        seen = len(found)

    discovered = await discover_until(target=target, max_wait=max_wait, on_progress=on_progress)
    if not discovered:
        print("no pods found")
        return

    print(f"\nconnecting to {len(discovered)} pod(s)...")
    manager = PodManager()
    errors = await manager.connect_all(discovered)
    if errors:
        print(f"  WARNING: {len(errors)} pod(s) failed to connect after retries:")
        for addr, err in errors.items():
            print(f"    {addr}: {type(err).__name__}: {err}")
    print(f"connected: {len(manager)}/{len(discovered)}")

    try:
        print("\nflashing each pod red in turn — watch the room:")
        def announce(pod: Pod) -> None:
            print(f"  -> {pod.address}  ({pod.name})")
        await manager.identify_each(on_pod=announce, flashes=3, gap_s=0.8)
    finally:
        await manager.disconnect_all()
        print("done")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("-n", "--count", type=int, default=None, help="stop scanning once N pods found")
    p.add_argument("--timeout", type=float, default=60.0, help="max scan duration (default 60s)")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)
    asyncio.run(run(args.count, args.timeout))


if __name__ == "__main__":
    main()
