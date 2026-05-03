"""Discovery, multi-pod connection management, and tap dispatch."""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, Iterable

from bleak import BleakScanner

from blazepod.pod import DiscoveredPod, Pod, TapCallback
from blazepod.protocol import COLOR_SERVICE_UUID, TAP_SERVICE_UUID, TapEvent

log = logging.getLogger(__name__)

# A pod's advertisement carries one of these distinctive service UUIDs.
_POD_SERVICE_UUIDS = {COLOR_SERVICE_UUID.lower(), TAP_SERVICE_UUID.lower()}

# Pods commonly advertise with names like "BlazePod" or "BP-...". Used as a
# fallback when service UUIDs aren't included in the advertisement.
_NAME_PREFIXES = ("blazepod", "bp")


def _looks_like_pod(adv) -> bool:
    if not adv.manufacturer_data:
        return False
    if any(u.lower() in _POD_SERVICE_UUIDS for u in (adv.service_uuids or [])):
        return True
    name = (adv.local_name or "").lower()
    return any(name.startswith(p) for p in _NAME_PREFIXES)


def _pick_mfr_data(adv) -> bytes | None:
    """Return the manufacturer-specific data bytes most likely to be the pod's.

    Bleak's `manufacturer_data` is `{company_id: bytes}`. BlazePods seem to
    publish a single entry; if multiple exist we pick the longest one >=5 bytes.
    """
    candidates = [v for v in adv.manufacturer_data.values() if len(v) >= 5]
    if not candidates:
        return None
    return max(candidates, key=len)


async def discover(timeout: float = 5.0, *, accept_all: bool = False) -> list[DiscoveredPod]:
    """Scan for BlazePods. Returns one DiscoveredPod per unique address.

    If `accept_all` is True, returns every device with usable manufacturer
    data — useful when the standard heuristics miss your firmware revision.
    """
    return await discover_until(target=None, max_wait=timeout, accept_all=accept_all)


async def discover_until(
    target: int | None,
    *,
    max_wait: float = 30.0,
    accept_all: bool = False,
    on_progress: "Callable[[list[DiscoveredPod]], None] | None" = None,
) -> list[DiscoveredPod]:
    """Scan, calling `on_progress` whenever a new pod is found.

    Stops early once `target` unique pods are seen, otherwise runs the full
    `max_wait` window. Pods that sleep aggressively only advertise every few
    seconds, so a longer window catches more of them.
    """
    found: dict[str, DiscoveredPod] = {}
    target_reached = asyncio.Event()
    loop = asyncio.get_running_loop()

    def detection(device, adv):
        if device.address in found:
            return
        if not accept_all and not _looks_like_pod(adv):
            return
        mfr = _pick_mfr_data(adv)
        if mfr is None:
            return
        found[device.address] = DiscoveredPod(
            device=device,
            mfr_data=mfr,
            rssi=adv.rssi,
            name=adv.local_name or device.name or "",
        )
        if on_progress is not None:
            try:
                on_progress(list(found.values()))
            except Exception:
                log.exception("on_progress raised")
        if target is not None and len(found) >= target:
            loop.call_soon_threadsafe(target_reached.set)

    scanner = BleakScanner(detection_callback=detection)
    await scanner.start()
    try:
        if target is None:
            await asyncio.sleep(max_wait)
        else:
            try:
                await asyncio.wait_for(target_reached.wait(), timeout=max_wait)
            except asyncio.TimeoutError:
                pass
    finally:
        await scanner.stop()
    return sorted(found.values(), key=lambda p: -p.rssi)


class PodManager:
    """Owns N connected pods and a single shared tap-event queue."""

    def __init__(self) -> None:
        self.pods: dict[str, Pod] = {}
        self.tap_queue: asyncio.Queue[tuple[Pod, TapEvent]] = asyncio.Queue()
        self._extra_listeners: list[TapCallback] = []

    def __len__(self) -> int:
        return len(self.pods)

    def __iter__(self):
        return iter(self.pods.values())

    async def connect_all(
        self,
        discovered: Iterable[DiscoveredPod],
        *,
        timeout: float = 15.0,
        retries: int = 2,
    ) -> dict[str, Exception]:
        """Connect in parallel, retrying failures. Returns {address: last_error} for pods still failing."""
        async def _one(d: DiscoveredPod) -> Pod | Exception:
            pod = Pod(d, on_tap=self._dispatch_tap)
            try:
                await asyncio.wait_for(pod.connect(), timeout=timeout)
                return pod
            except asyncio.TimeoutError:
                log.warning("connect timeout for %s after %ss", d.address, timeout)
                return TimeoutError(f"connect timeout after {timeout}s")
            except Exception as e:
                # Bleak sometimes raises bare exceptions with empty messages — log the type too.
                log.warning("failed to connect %s: %s (%s)", d.address, e, type(e).__name__)
                return e if str(e) else type(e)(f"{type(e).__name__} (no message)")

        pending: list[DiscoveredPod] = list(discovered)
        last_errors: dict[str, Exception] = {}
        for attempt in range(retries + 1):
            if not pending:
                break
            if attempt > 0:
                log.info("retrying %d pod(s), attempt %d", len(pending), attempt + 1)
                await asyncio.sleep(1.0)
            results = await asyncio.gather(*[_one(d) for d in pending])
            next_pending: list[DiscoveredPod] = []
            for d, r in zip(pending, results):
                if isinstance(r, Pod):
                    self.pods[r.address] = r
                    last_errors.pop(d.address, None)
                else:
                    last_errors[d.address] = r
                    next_pending.append(d)
            pending = next_pending
        return last_errors

    def add_tap_listener(self, cb: TapCallback) -> None:
        self._extra_listeners.append(cb)

    def clear_tap_listeners(self) -> None:
        self._extra_listeners.clear()

    async def all_color(self, r: int, g: int, b: int, *, off_on_tap: bool = False) -> None:
        await asyncio.gather(*(p.set_color(r, g, b, off_on_tap=off_on_tap) for p in self.pods.values()))

    async def all_off(self) -> None:
        await asyncio.gather(*(p.turn_off() for p in self.pods.values()))

    async def identify_each(
        self,
        *,
        r: int = 255, g: int = 0, b: int = 0,
        flashes: int = 3,
        gap_s: float = 0.6,
        on_pod: "Callable[[Pod], None] | None" = None,
    ) -> None:
        """Flash each connected pod in turn so you can tell them apart physically."""
        for pod in self.pods.values():
            if on_pod is not None:
                try:
                    on_pod(pod)
                except Exception:
                    log.exception("on_pod callback raised")
            await pod.flash(r, g, b, count=flashes)
            await asyncio.sleep(gap_s)

    async def disconnect_all(self) -> None:
        await asyncio.gather(*(p.disconnect() for p in self.pods.values()), return_exceptions=True)
        self.pods.clear()

    async def __aenter__(self) -> "PodManager":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        try:
            await self.all_off()
        finally:
            await self.disconnect_all()

    def _dispatch_tap(self, pod: Pod, event: TapEvent) -> None:
        self.tap_queue.put_nowait((pod, event))
        for cb in list(self._extra_listeners):
            res = cb(pod, event)
            if asyncio.iscoroutine(res):
                asyncio.create_task(res)

    async def drain_taps(self) -> None:
        """Discard any queued taps (call before starting a new drill round)."""
        while not self.tap_queue.empty():
            self.tap_queue.get_nowait()
