"""Color-match drill: light all pods, tap only the target color."""

from __future__ import annotations

import asyncio
import random

from blazepod.drills.base import Drill
from blazepod.manager import PodManager


class ColorMatchDrill(Drill):
    name = "Color Match"

    def __init__(
        self,
        manager: PodManager,
        *,
        rounds: int = 10,
        timeout_s: float = 5.0,
        target_color: tuple[int, int, int] = (0, 255, 0),
        distractor_color: tuple[int, int, int] = (255, 0, 0),
    ) -> None:
        super().__init__(manager)
        self.rounds = rounds
        self.timeout_s = timeout_s
        self.target_color = target_color
        self.distractor_color = distractor_color

    async def _run(self) -> None:
        pods = list(self.manager.pods.values())
        for _ in range(self.rounds):
            target = random.choice(pods)
            tr, tg, tb = self.target_color
            dr, dg, db = self.distractor_color

            await asyncio.gather(*(
                pod.set_color(tr, tg, tb, off_on_tap=True) if pod is target
                else pod.set_color(dr, dg, db, off_on_tap=True)
                for pod in pods
            ))

            result = await self._wait_for_any_lit_tap(timeout=self.timeout_s)
            if result is None:
                self.stats.misses += 1
                self.stats.notes.append(f"timeout (target was {target.address})")
            else:
                src, ev = result
                if src.address == target.address:
                    self.stats.hits += 1
                    self.stats.reaction_times_ms.append(ev.elapsed_ms)
                else:
                    self.stats.misses += 1
            await self.manager.all_off()
