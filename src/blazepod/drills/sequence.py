"""Sequence drill: tap pods in the order they light up."""

from __future__ import annotations

import random

from blazepod.drills.base import Drill
from blazepod.manager import PodManager


class SequenceDrill(Drill):
    name = "Sequence"

    def __init__(
        self,
        manager: PodManager,
        *,
        length: int = 8,
        timeout_s: float = 5.0,
        color: tuple[int, int, int] = (0, 0, 255),
    ) -> None:
        super().__init__(manager)
        self.length = length
        self.timeout_s = timeout_s
        self.color = color

    async def _run(self) -> None:
        pods = list(self.manager.pods.values())
        sequence = [random.choice(pods) for _ in range(self.length)]
        for target in sequence:
            r, g, b = self.color
            await target.set_color(r, g, b, off_on_tap=True)
            ev = await self._wait_for_tap_from(target, timeout=self.timeout_s)
            if ev is None:
                self.stats.misses += 1
                await target.turn_off()
                self.stats.notes.append(f"timeout on {target.address}")
            else:
                self.stats.hits += 1
                self.stats.reaction_times_ms.append(ev.elapsed_ms)
