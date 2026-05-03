"""Find pods. Prints each one as it appears so you know to keep tapping any
missing ones to wake them out of deep sleep.
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from blazepod.manager import discover_until


async def run(target: int | None, max_wait: float, accept_all: bool) -> None:
    seen = 0

    def on_progress(found):
        nonlocal seen
        for p in found[seen:]:
            print(f"  + {p.address}  rssi={p.rssi:>4}  name={p.name!r}  mfr={p.mfr_data.hex()}")
        seen = len(found)

    if target:
        print(f"looking for {target} pod(s) (up to {max_wait:.0f}s)... tap any sleeping pods to wake them")
    else:
        print(f"watching for pods for {max_wait:.0f}s...")

    pods = await discover_until(target=target, max_wait=max_wait, accept_all=accept_all, on_progress=on_progress)

    print(f"\nfound {len(pods)} pod(s)" + (f" (wanted {target})" if target else ""))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("-n", "--count", type=int, default=None, help="stop early once N pods found")
    p.add_argument("--timeout", type=float, default=30.0, help="max scan duration in seconds (default 30)")
    p.add_argument("--all", action="store_true", help="don't filter by BlazePod heuristics")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING)
    asyncio.run(run(args.count, args.timeout, args.all))


if __name__ == "__main__":
    main()
