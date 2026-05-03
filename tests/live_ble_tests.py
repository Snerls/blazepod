"""Live BLE smoke tests against real BlazePods.

Run as: python tests/live_ble_tests.py <name>
where name is one of: auth | stability | warm | stress | all

These exercise the protocol against actual hardware. The Python implementation
and the JS web-app implementation share the same wire protocol — verifying
behavior here covers both.
"""

from __future__ import annotations

import asyncio
import statistics
import sys
import time
from typing import Awaitable, Callable

# Make `blazepod` importable when running this file directly
sys.path.insert(0, str((__import__('pathlib').Path(__file__).parent.parent / 'src').resolve()))

from blazepod import Pod, PodManager  # noqa: E402
from blazepod.manager import discover_until  # noqa: E402
from blazepod.protocol import build_auth_payload  # noqa: E402

SCAN_TIMEOUT = 30.0  # generous so we catch slow-advertising pods


def _hr(label: str) -> None:
    print(f"\n{'=' * 70}\n {label}\n{'=' * 70}")


def _ok(msg: str) -> None: print(f"  PASS  {msg}")
def _fail(msg: str) -> None: print(f"  FAIL  {msg}")


# ---------------------------------------------------------------------------

async def test_auth() -> bool:
    """Smoke test: every discovered pod accepts our auth handshake and lights up."""
    _hr("AUTH HANDSHAKE — connect each pod, light it green, disconnect")
    discovered = await discover_until(target=None, max_wait=SCAN_TIMEOUT)
    if not discovered:
        _fail("no pods discovered — wake them and retry")
        return False
    print(f"  found {len(discovered)} pod(s)")

    ok = 0
    for d in discovered:
        try:
            pod = Pod(d)
            await pod.connect()
            await pod.set_color(0, 200, 0)
            await asyncio.sleep(0.4)
            await pod.turn_off()
            await pod.disconnect()
            _ok(f"{d.address}  ({d.name})")
            ok += 1
        except Exception as e:
            _fail(f"{d.address}: {type(e).__name__}: {e}")
    print(f"\n  {ok}/{len(discovered)} authenticated successfully")
    return ok == len(discovered)


# ---------------------------------------------------------------------------

async def test_stability() -> bool:
    """Verify mfrData is identical across two scans of the same pod.

    This is the premise of the localStorage mfrData cache in the web app:
    if the pod's manufacturer-specific advertisement data ever changes, the
    cached auth secret becomes invalid. If this test passes, the cache is safe.
    """
    _hr("MFR-DATA STABILITY — scan twice, compare")

    print("  scan 1...")
    a = await discover_until(target=None, max_wait=SCAN_TIMEOUT)
    if not a:
        _fail("no pods on first scan")
        return False
    print(f"    found {len(a)}")

    print("  waiting 5s for pods to potentially shift state...")
    await asyncio.sleep(5)

    print("  scan 2...")
    b = await discover_until(target=None, max_wait=SCAN_TIMEOUT)
    print(f"    found {len(b)}")

    by_addr_a = {p.address: p.mfr_data for p in a}
    by_addr_b = {p.address: p.mfr_data for p in b}

    common = sorted(set(by_addr_a) & set(by_addr_b))
    if not common:
        _fail("no pods seen in both scans")
        return False

    all_ok = True
    for addr in common:
        if by_addr_a[addr] == by_addr_b[addr]:
            _ok(f"{addr}  mfr={by_addr_a[addr].hex()}  (stable)")
        else:
            _fail(f"{addr}  CHANGED  a={by_addr_a[addr].hex()}  b={by_addr_b[addr].hex()}")
            all_ok = False

    only_a = sorted(set(by_addr_a) - set(by_addr_b))
    only_b = sorted(set(by_addr_b) - set(by_addr_a))
    if only_a: print(f"  (only in scan 1: {only_a})")
    if only_b: print(f"  (only in scan 2: {only_b})")

    return all_ok


# ---------------------------------------------------------------------------

async def test_warm() -> bool:
    """Time a connect → disconnect → reconnect cycle.

    The reconnect uses the SAME BLEDevice object (no rescan) — this is the
    Python equivalent of the web app's flow where mfrData is cached and
    `device.gatt.connect()` is called against the previously-paired device.
    """
    _hr("WARM RECONNECT — disconnect + immediate reconnect, no rescan")
    discovered = await discover_until(target=None, max_wait=SCAN_TIMEOUT)
    if not discovered:
        _fail("no pods")
        return False

    target = discovered[0]
    print(f"  using {target.address} ({target.name})")

    pod = Pod(target)
    t0 = time.perf_counter()
    await pod.connect()
    cold_ms = (time.perf_counter() - t0) * 1000
    print(f"  cold connect: {cold_ms:.0f} ms")

    await pod.disconnect()
    print("  disconnected, reconnecting immediately (same BLEDevice)...")

    pod2 = Pod(target)  # re-use the BLEDevice; mfr_data stays cached on it
    t0 = time.perf_counter()
    try:
        await pod2.connect()
        warm_ms = (time.perf_counter() - t0) * 1000
        print(f"  warm reconnect: {warm_ms:.0f} ms")
        await pod2.disconnect()
        if warm_ms < cold_ms * 1.2:
            _ok(f"warm reconnect not slower than cold ({warm_ms:.0f} vs {cold_ms:.0f} ms)")
            return True
        else:
            _fail(f"warm reconnect was slower ({warm_ms:.0f} vs {cold_ms:.0f} ms)")
            return False
    except Exception as e:
        _fail(f"warm reconnect failed: {type(e).__name__}: {e}")
        return False


# ---------------------------------------------------------------------------

async def test_stress() -> bool:
    """Connect all pods in parallel, disconnect, repeat 3x — adapter churn check."""
    _hr("STRESS — connect all + disconnect, 3 cycles")
    discovered = await discover_until(target=None, max_wait=SCAN_TIMEOUT)
    if len(discovered) < 2:
        _fail("need at least 2 pods")
        return False
    print(f"  using {len(discovered)} pods")

    timings = []
    for cycle in range(3):
        manager = PodManager()
        t0 = time.perf_counter()
        errors = await manager.connect_all(discovered)
        connect_ms = (time.perf_counter() - t0) * 1000
        connected = len(manager)
        timings.append(connect_ms)
        print(f"  cycle {cycle + 1}: {connected}/{len(discovered)} in {connect_ms:.0f} ms ({len(errors)} failed)")
        await manager.disconnect_all()
        await asyncio.sleep(0.5)

    avg = statistics.fmean(timings)
    if all(t < 30000 for t in timings):
        _ok(f"all cycles under 30s (avg {avg:.0f} ms)")
        return True
    _fail(f"some cycles too slow: {timings}")
    return False


# ---------------------------------------------------------------------------

TESTS: dict[str, Callable[[], Awaitable[bool]]] = {
    "auth":      test_auth,
    "stability": test_stability,
    "warm":      test_warm,
    "stress":    test_stress,
}


async def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in TESTS and sys.argv[1] != "all":
        print(__doc__)
        print(f"available tests: {', '.join(TESTS)} | all")
        return 2

    selected = list(TESTS.values()) if sys.argv[1] == "all" else [TESTS[sys.argv[1]]]
    results: list[tuple[str, bool]] = []
    for fn in selected:
        try:
            ok = await fn()
        except Exception as e:
            print(f"  FAIL  {fn.__name__}: unhandled {type(e).__name__}: {e}")
            ok = False
        results.append((fn.__name__, ok))

    print(f"\n{'=' * 70}")
    for name, ok in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    return 0 if all(ok for _, ok in results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
