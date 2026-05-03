"""Drill abstract base + shared Stats dataclass."""

from __future__ import annotations

import asyncio
import statistics
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from blazepod.manager import PodManager
from blazepod.pod import Pod
from blazepod.protocol import TapEvent


@dataclass
class Stats:
    """Per-drill results. Reaction times are pod-reported milliseconds."""
    drill_name: str
    reaction_times_ms: list[int] = field(default_factory=list)
    hits: int = 0
    misses: int = 0
    total_time_ms: int = 0  # wall-clock duration of the whole drill
    notes: list[str] = field(default_factory=list)
    # Per-player or per-station breakdowns. Keyed by display label.
    subscores: dict[str, "Stats"] = field(default_factory=dict)

    @property
    def attempts(self) -> int:
        return self.hits + self.misses

    @property
    def accuracy(self) -> float:
        return self.hits / self.attempts if self.attempts else 0.0

    @property
    def mean_ms(self) -> float:
        return statistics.fmean(self.reaction_times_ms) if self.reaction_times_ms else 0.0

    @property
    def median_ms(self) -> float:
        return statistics.median(self.reaction_times_ms) if self.reaction_times_ms else 0.0

    @property
    def best_ms(self) -> int:
        return min(self.reaction_times_ms) if self.reaction_times_ms else 0

    @property
    def worst_ms(self) -> int:
        return max(self.reaction_times_ms) if self.reaction_times_ms else 0

    def summary_lines(self) -> list[str]:
        lines = [
            f"Drill: {self.drill_name}",
            f"Attempts: {self.attempts}  (hits={self.hits}, misses={self.misses}, accuracy={self.accuracy:.0%})",
        ]
        if self.reaction_times_ms:
            lines.append(
                f"Reaction (ms): mean={self.mean_ms:.0f}  median={self.median_ms:.0f}  "
                f"best={self.best_ms}  worst={self.worst_ms}"
            )
        if self.total_time_ms:
            lines.append(f"Total time: {self.total_time_ms / 1000:.2f}s")
        lines.extend(self.notes)
        return lines


class Drill(ABC):
    """A drill consumes taps from manager.tap_queue and lights pods accordingly.

    Subclasses implement `_run`. The base class handles queue draining,
    wall-clock timing, and stats packaging.
    """

    name: str = "drill"

    def __init__(self, manager: PodManager) -> None:
        if not manager.pods:
            raise ValueError("no pods connected")
        self.manager = manager
        self.stats = Stats(drill_name=self.name)

    async def run(self) -> Stats:
        await self.manager.drain_taps()
        loop = asyncio.get_running_loop()
        start = loop.time()
        try:
            await self._run()
        finally:
            self.stats.total_time_ms = int((loop.time() - start) * 1000)
            await self.manager.all_off()
        return self.stats

    @abstractmethod
    async def _run(self) -> None: ...

    async def _wait_for_tap_from(
        self,
        pod: Pod,
        *,
        timeout: float | None = None,
    ) -> TapEvent | None:
        """Wait until the named pod produces a lit-pod tap. Other taps count as misses."""
        loop = asyncio.get_running_loop()
        deadline = (loop.time() + timeout) if timeout else None
        while True:
            remaining = (deadline - loop.time()) if deadline else None
            if remaining is not None and remaining <= 0:
                return None
            try:
                src, ev = await asyncio.wait_for(self.manager.tap_queue.get(), timeout=remaining)
            except asyncio.TimeoutError:
                return None
            if not ev.hit_lit_pod:
                continue
            if src.address != pod.address:
                self.stats.misses += 1
                continue
            return ev

    async def _wait_for_any_lit_tap(
        self,
        *,
        timeout: float | None = None,
    ) -> tuple[Pod, TapEvent] | None:
        loop = asyncio.get_running_loop()
        deadline = (loop.time() + timeout) if timeout else None
        while True:
            remaining = (deadline - loop.time()) if deadline else None
            if remaining is not None and remaining <= 0:
                return None
            try:
                src, ev = await asyncio.wait_for(self.manager.tap_queue.get(), timeout=remaining)
            except asyncio.TimeoutError:
                return None
            if ev.hit_lit_pod:
                return src, ev
