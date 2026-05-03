"""Smoke test: connect to one pod, cycle red/green/blue, print every tap.

Treat this as the canonical regression test for the protocol layer — if it
breaks, blame protocol.py before suspecting Bleak or the firmware.
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from blazepod import Pod, TapEvent, discover


async def on_tap(pod: Pod, event: TapEvent) -> None:
    print(f"  TAP {pod.address} state={event.state.name} elapsed_ms={event.elapsed_ms}")


COLOR_CYCLE = [
    ("red",   (255, 0, 0)),
    ("green", (0, 255, 0)),
    ("blue",  (0, 0, 255)),
    ("white", (255, 255, 255)),
]


async def run(timeout: float, rounds: int, hold_s: float) -> None:
    print(f"scanning for {timeout}s...")
    pods = await discover(timeout=timeout)
    if not pods:
        print("no pods found — try `python examples/scan.py --all` to debug")
        return
    target = pods[0]
    print(f"using {target.address} (rssi={target.rssi}, name={target.name!r})")
    print(f"  mfr_data={target.mfr_data.hex()}")

    async with Pod(target, on_tap=on_tap) as pod:
        print("connected — cycling colors. tap the pod to see notifications.")
        for _ in range(rounds):
            for label, (r, g, b) in COLOR_CYCLE:
                print(f"setting {label}")
                await pod.set_color(r, g, b)
                await asyncio.sleep(hold_s)
        await pod.turn_off()
        print("done")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--hold", type=float, default=1.0, help="seconds per color")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)
    asyncio.run(run(args.timeout, args.rounds, args.hold))


if __name__ == "__main__":
    main()
