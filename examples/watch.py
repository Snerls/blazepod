"""Live BLE advertisement monitor.

Prints every advertisement as it arrives, with a timestamp. Use this to figure
out which pods are advertising, when, and what they look like over the air.

Suggested experiments:
  - Run this, then physically tap / press / shake each pod one at a time.
    Pods that wake should appear in the output within a second.
  - Compare mfr_data across pods — if some have a different shape, the
    discovery filter may be excluding them.
  - Watch for pods that briefly appear then go silent (deep-sleep behavior).

Filter modes:
  default       only show advertisements that look like BlazePods
  --all         show every BLE device (lots of noise, useful for debugging)
  --name STR    only show devices whose name contains STR (case-insensitive)
"""

from __future__ import annotations

import argparse
import asyncio
import time
from datetime import datetime

from bleak import BleakScanner

from blazepod.manager import _looks_like_pod, _pick_mfr_data


async def run(timeout: float, accept_all: bool, name_filter: str | None) -> None:
    seen_count: dict[str, int] = {}
    start = time.monotonic()

    def on_detect(device, adv):
        if name_filter:
            n = (adv.local_name or device.name or "")
            if name_filter.lower() not in n.lower():
                return
        elif not accept_all and not _looks_like_pod(adv):
            return

        seen_count[device.address] = seen_count.get(device.address, 0) + 1
        first_time = seen_count[device.address] == 1
        marker = "NEW" if first_time else f"#{seen_count[device.address]}"
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        elapsed = time.monotonic() - start

        mfr = _pick_mfr_data(adv)
        mfr_str = mfr.hex() if mfr else "(none)"
        all_mfr = {hex(k): v.hex() for k, v in adv.manufacturer_data.items()}
        svcs = adv.service_uuids or []

        print(
            f"[{ts}  +{elapsed:6.2f}s  {marker:>4}] "
            f"{device.address}  rssi={adv.rssi:>4}  "
            f"name={(adv.local_name or device.name or '?')!r}"
        )
        print(f"          mfr_data={mfr_str}  all_mfr={all_mfr}")
        if svcs:
            print(f"          services={svcs}")

    scanner = BleakScanner(detection_callback=on_detect)
    print(f"watching for {timeout}s... wake each pod (tap / button) one at a time")
    print("-" * 70)
    await scanner.start()
    try:
        await asyncio.sleep(timeout)
    finally:
        await scanner.stop()

    print("-" * 70)
    print(f"summary: {len(seen_count)} unique device(s)")
    for addr, count in sorted(seen_count.items(), key=lambda kv: -kv[1]):
        print(f"  {addr}  ads={count}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--timeout", type=float, default=30.0, help="seconds to watch (default 30)")
    p.add_argument("--all", action="store_true", help="show every BLE device, not just pods")
    p.add_argument("--name", help="only show devices whose name contains this substring")
    args = p.parse_args()
    asyncio.run(run(args.timeout, args.all, args.name))


if __name__ == "__main__":
    main()
