"""Configurable drill — the BlazePod 'Custom Activity' equivalent.

Concepts:
  Station        -- a group of pods running independently (parallel)
  Player         -- owns a station; has one or more colors
  Lights out     -- when a lit pod extinguishes (hit / timeout / either)
  Light delay    -- gap between one pod going out and the next lighting up
  Duration       -- when the drill ends (time / hit count / either)
  Cycles         -- repeat the whole drill N times
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from enum import Enum

from blazepod.drills.base import Drill, Stats
from blazepod.manager import PodManager
from blazepod.pod import Pod
from blazepod.protocol import TapEvent


Color = tuple[int, int, int]  # r, g, b


class LightsOut(str, Enum):
    HIT = "hit"
    TIMEOUT = "timeout"
    HIT_AND_TIMEOUT = "hit_and_timeout"


class LightDelay(str, Enum):
    NONE = "none"
    FIXED = "fixed"
    RANDOM = "random"


class DurationMode(str, Enum):
    TIME = "time"
    HIT_COUNT = "hit_count"
    TIME_AND_HIT_COUNT = "time_and_hit_count"


@dataclass
class PlayerConfig:
    name: str
    colors: list[Color] = field(default_factory=lambda: [(255, 255, 255)])


@dataclass
class CustomDrillConfig:
    # Setup
    stations: int = 1
    pods_per_station: int = 6
    players: list[PlayerConfig] = field(
        default_factory=lambda: [PlayerConfig("Player 1", [(255, 255, 255)])]
    )

    # Lights out behavior
    lights_out: LightsOut = LightsOut.HIT
    timeout_s: float = 3.0  # used when lights_out includes TIMEOUT

    # Inter-target delay
    light_delay: LightDelay = LightDelay.NONE
    light_delay_fixed_s: float = 1.0
    light_delay_min_s: float = 0.5
    light_delay_max_s: float = 2.0

    # End conditions
    duration_mode: DurationMode = DurationMode.TIME
    duration_time_s: float = 60.0
    duration_hit_count: int = 50

    # Repetitions
    cycles: int = 1

    @property
    def total_pods_needed(self) -> int:
        return self.stations * self.pods_per_station


class _StationRuntime:
    """Per-station state: owns its pods and accumulates its own stats."""

    def __init__(self, idx: int, pods: list[Pod], player: PlayerConfig) -> None:
        self.idx = idx
        self.pods = pods
        self.player = player
        self.target: Pod | None = None
        self.queue: asyncio.Queue[tuple[Pod, TapEvent]] = asyncio.Queue()
        self.stats = Stats(drill_name=f"{player.name}")
        self._color_cursor = 0

    def next_color(self) -> Color:
        c = self.player.colors[self._color_cursor % len(self.player.colors)]
        self._color_cursor += 1
        return c


class CustomDrill(Drill):
    name = "Custom"

    def __init__(self, manager: PodManager, config: CustomDrillConfig) -> None:
        super().__init__(manager)
        self.config = config

        all_pods = list(manager.pods.values())
        needed = config.total_pods_needed
        if needed > len(all_pods):
            raise ValueError(
                f"need {needed} pods ({config.stations} stations × {config.pods_per_station}) "
                f"but only {len(all_pods)} connected"
            )
        if not config.players:
            raise ValueError("at least one player required")

        # Slice pods into station buckets in connection order.
        self.stations: list[_StationRuntime] = []
        for s in range(config.stations):
            start = s * config.pods_per_station
            station_pods = all_pods[start:start + config.pods_per_station]
            player = config.players[s % len(config.players)]
            self.stations.append(_StationRuntime(s, station_pods, player))

        # Reverse-lookup: which station owns this pod address
        self._addr_to_station: dict[str, _StationRuntime] = {
            pod.address: st for st in self.stations for pod in st.pods
        }

    async def _run(self) -> None:
        for cycle in range(self.config.cycles):
            if cycle > 0:
                self.stats.notes.append(f"--- cycle {cycle + 1} ---")
            await self._run_one_cycle()

        # Aggregate per-station stats into the parent Stats
        for st in self.stations:
            self.stats.subscores[st.player.name + f" (station {st.idx + 1})"] = st.stats
            self.stats.hits += st.stats.hits
            self.stats.misses += st.stats.misses
            self.stats.reaction_times_ms.extend(st.stats.reaction_times_ms)

    async def _run_one_cycle(self) -> None:
        loop = asyncio.get_running_loop()
        deadline: float | None = None
        if self.config.duration_mode in (DurationMode.TIME, DurationMode.TIME_AND_HIT_COUNT):
            deadline = loop.time() + self.config.duration_time_s
        hit_cap: int | None = None
        if self.config.duration_mode in (DurationMode.HIT_COUNT, DurationMode.TIME_AND_HIT_COUNT):
            hit_cap = self.config.duration_hit_count

        end_event = asyncio.Event()
        total_hits = 0

        def maybe_finish() -> None:
            nonlocal total_hits
            if hit_cap is not None and total_hits >= hit_cap:
                end_event.set()

        # Per-station task
        async def run_station(st: _StationRuntime) -> None:
            nonlocal total_hits
            while not end_event.is_set():
                target = self._pick_target(st)
                st.target = target

                color = st.next_color()
                # Auto-off-on-tap when a hit alone extinguishes the pod
                off_on_tap = self.config.lights_out in (LightsOut.HIT, LightsOut.HIT_AND_TIMEOUT)
                await target.set_color(*color, off_on_tap=off_on_tap)

                hit_event = await self._await_resolution(st, target)
                if hit_event is not None:
                    st.stats.hits += 1
                    st.stats.reaction_times_ms.append(hit_event.elapsed_ms)
                    total_hits += 1
                    maybe_finish()
                else:
                    st.stats.misses += 1
                    # If the pod didn't auto-extinguish on a tap, force it off
                    await target.turn_off()

                st.target = None
                if end_event.is_set():
                    break

                delay = self._compute_delay()
                if delay > 0:
                    try:
                        await asyncio.wait_for(end_event.wait(), timeout=delay)
                    except asyncio.TimeoutError:
                        pass

        # Tap dispatcher: route from manager.tap_queue to the right station
        async def dispatch_taps() -> None:
            while not end_event.is_set():
                try:
                    pod, ev = await asyncio.wait_for(self.manager.tap_queue.get(), timeout=0.2)
                except asyncio.TimeoutError:
                    continue
                if not ev.hit_lit_pod:
                    continue
                st = self._addr_to_station.get(pod.address)
                if st is None:
                    continue
                if st.target is not None and st.target.address == pod.address:
                    st.queue.put_nowait((pod, ev))
                else:
                    # Stray hit on a non-target pod within this station
                    st.stats.misses += 1

        # Deadline watcher
        async def watch_deadline() -> None:
            if deadline is None:
                return
            remaining = deadline - loop.time()
            if remaining > 0:
                try:
                    await asyncio.wait_for(end_event.wait(), timeout=remaining)
                except asyncio.TimeoutError:
                    pass
            end_event.set()

        await self.manager.drain_taps()
        try:
            station_tasks = [asyncio.create_task(run_station(s)) for s in self.stations]
            dispatcher = asyncio.create_task(dispatch_taps())
            watcher = asyncio.create_task(watch_deadline())
            await asyncio.gather(*station_tasks, return_exceptions=True)
            end_event.set()
            dispatcher.cancel()
            watcher.cancel()
            await asyncio.gather(dispatcher, watcher, return_exceptions=True)
        finally:
            await asyncio.gather(*(p.turn_off() for p in self.manager.pods.values()), return_exceptions=True)

    async def _await_resolution(self, st: _StationRuntime, target: Pod) -> TapEvent | None:
        """Wait for a hit or a timeout depending on the lights_out mode."""
        timeout: float | None = (
            self.config.timeout_s
            if self.config.lights_out in (LightsOut.TIMEOUT, LightsOut.HIT_AND_TIMEOUT)
            else None
        )
        if self.config.lights_out == LightsOut.TIMEOUT:
            # Pod stays lit for `timeout` seconds regardless of taps.
            try:
                _, ev = await asyncio.wait_for(st.queue.get(), timeout=timeout)
                # Tap arrived but counts as miss in pure-timeout mode? No — in
                # BlazePod semantics, hits in TIMEOUT mode are still hits, the
                # difference is just that the pod doesn't auto-off on tap.
                # We'll still count it as a hit and return the event.
                return ev
            except asyncio.TimeoutError:
                return None
        try:
            _, ev = await asyncio.wait_for(st.queue.get(), timeout=timeout)
            return ev
        except asyncio.TimeoutError:
            return None

    def _pick_target(self, st: _StationRuntime) -> Pod:
        # Avoid choosing the same pod twice in a row when possible
        if st.target is not None and len(st.pods) > 1:
            choices = [p for p in st.pods if p.address != st.target.address]
        else:
            choices = st.pods
        return random.choice(choices)

    def _compute_delay(self) -> float:
        match self.config.light_delay:
            case LightDelay.NONE:
                return 0.0
            case LightDelay.FIXED:
                return max(0.0, self.config.light_delay_fixed_s)
            case LightDelay.RANDOM:
                lo = max(0.0, self.config.light_delay_min_s)
                hi = max(lo, self.config.light_delay_max_s)
                return random.uniform(lo, hi)
        return 0.0
