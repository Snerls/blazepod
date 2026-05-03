"""Random-light reaction drill: light one random pod, time the tap, repeat."""

from __future__ import annotations

import random

from blazepod.drills.base import Drill
from blazepod.manager import PodManager


class RandomLightDrill(Drill):
    name = "Random Light"

    def __init__(
        self,
        manager: PodManager,
        *,
        rounds: int = 10,
        timeout_s: float = 5.0,
        color: tuple[int, int, int] = (255, 255, 255),
    ) -> None:
        super().__init__(manager)
        self.rounds = rounds
        self.timeout_s = timeout_s
        self.color = color

    async def _run(self) -> None:
        pods = list(self.manager.pods.values())
        for _ in range(self.rounds):
            target = random.choice(pods)
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
