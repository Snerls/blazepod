"""Connect ONE pod via Python (real mfr-derived auth) and hold it for 30s.

Compares against tests/hold_one.mjs which uses static "sea\\0\\0\\0\\0" and
disconnects at ~10s. If Python stays connected, the auth IS validated and we
need the real mfrData. If Python ALSO drops at 10s, something else is wrong.
"""
from __future__ import annotations
import asyncio, sys, time
from pathlib import Path
sys.path.insert(0, str((Path(__file__).parent.parent / 'src').resolve()))
from blazepod import Pod
from blazepod.manager import discover_until


async def main() -> int:
    pods = await discover_until(target=1, max_wait=20.0)
    if not pods: return 1
    p = pods[0]
    print(f"using {p.address}  mfr={p.mfr_data.hex()}")

    pod = Pod(p)
    t0 = time.monotonic()
    await pod.connect()
    print(f"connected at +{time.monotonic()-t0:.1f}s")

    disconnected_at = None
    pod._client._backend._on_disconnected_callback = lambda *_: setattr(__import__('builtins'), '__discon__', time.monotonic() - t0)

    for i in range(15):
        await asyncio.sleep(2)
        is_conn = pod.is_connected
        elapsed = time.monotonic() - t0
        print(f"  +{elapsed:5.1f}s  isConnected={is_conn}")
        if not is_conn:
            print("  DROPPED")
            break
        # also write a no-op color so we keep some activity
        try:
            await pod.set_color(0, 60, 0)
            await asyncio.sleep(0.05)
            await pod.turn_off()
        except Exception as e:
            print(f"  write failed: {type(e).__name__}: {e}")
            break

    try: await pod.disconnect()
    except Exception: pass
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
