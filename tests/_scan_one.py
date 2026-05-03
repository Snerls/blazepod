"""Scan for one pod and emit {address, mfr_hex} as JSON to stdout."""
from __future__ import annotations
import asyncio, json, sys
from pathlib import Path
sys.path.insert(0, str((Path(__file__).parent.parent / 'src').resolve()))
from blazepod.manager import discover_until


async def main() -> int:
    pods = await discover_until(target=1, max_wait=15.0)
    if not pods:
        print(json.dumps({"error": "no pods found"}))
        return 1
    p = pods[0]
    print(json.dumps({"address": p.address, "name": p.name, "mfr_hex": p.mfr_data.hex()}))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
