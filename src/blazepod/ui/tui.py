"""Textual TUI for the BlazePod controller.

Screens:
  Scan    -> discover and select pods to connect
  Menu    -> pick a drill
  Run     -> drill in progress with live counters
  Results -> final stats summary
"""

from __future__ import annotations

import asyncio
import logging

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Center, Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Label, ListItem, ListView, Static

from blazepod import PodManager
from blazepod.drills import ALL_DRILLS, Drill, Stats
from blazepod.manager import discover_until
from blazepod.pod import DiscoveredPod


SCAN_TIMEOUT = 45.0  # pods sleep aggressively; long window catches the slow ones


class ScanScreen(Screen):
    BINDINGS = [
        Binding("r", "rescan", "Rescan"),
        Binding("a", "rescan_all", "Rescan (all BLE)"),
        Binding("c", "connect", "Connect"),
        Binding("i", "identify", "Identify (flash)"),
        Binding("q", "app.quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.discovered: list[DiscoveredPod] = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Scanning for pods... tap any sleeping pod to wake it.", id="status")
        yield DataTable(id="pods")
        yield Footer()

    async def on_mount(self) -> None:
        table = self.query_one("#pods", DataTable)
        table.add_columns("Address", "RSSI", "Name", "Mfr Data")
        table.cursor_type = "row"
        self.run_worker(self._scan(accept_all=False), exclusive=True)

    async def _scan(self, *, accept_all: bool) -> None:
        status = self.query_one("#status", Static)
        table = self.query_one("#pods", DataTable)
        table.clear()
        self.discovered = []

        def on_progress(found: list[DiscoveredPod]) -> None:
            self.discovered = found
            self.app.call_from_thread(self._refresh_table, found)
            self.app.call_from_thread(
                status.update,
                f"Found {len(found)} so far... ({'all BLE' if accept_all else 'tap any missing pod'}). "
                f"[b]c[/b]=connect  [b]r[/b]=rescan  [b]i[/b]=identify",
            )

        status.update(f"Scanning up to {SCAN_TIMEOUT:.0f}s — tap any sleeping pod to wake it...")
        self.discovered = await discover_until(
            target=None, max_wait=SCAN_TIMEOUT, accept_all=accept_all, on_progress=on_progress,
        )
        if self.discovered:
            status.update(
                f"Done. {len(self.discovered)} pod(s) found. "
                f"[b]c[/b]=connect  [b]r[/b]=rescan  [b]i[/b]=identify"
            )
        else:
            status.update("No pods found. Wake the pods and press [b]r[/b], or [b]a[/b] to scan all BLE.")

    def _refresh_table(self, found: list[DiscoveredPod]) -> None:
        table = self.query_one("#pods", DataTable)
        existing = set(table.rows.keys())
        for d in found:
            if d.address not in existing:
                table.add_row(d.address, str(d.rssi), d.name or "?", d.mfr_data.hex(), key=d.address)

    def action_rescan(self) -> None:
        self.run_worker(self._scan(accept_all=False), exclusive=True)

    def action_rescan_all(self) -> None:
        self.run_worker(self._scan(accept_all=True), exclusive=True)

    async def action_connect(self) -> None:
        if not self.discovered:
            return
        await self.app.connect_pods(self.discovered)

    async def action_identify(self) -> None:
        if not self.discovered:
            return
        await self.app.identify_pods(self.discovered)


class MenuScreen(Screen):
    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("q", "app.quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label(f"Connected pods: {len(self.app.manager)}", id="connected")
        yield Label("Choose a drill:")
        items = [ListItem(Label(d.name), id=f"d-{i}") for i, d in enumerate(ALL_DRILLS)]
        yield ListView(*items, id="drills")
        yield Footer()

    @on(ListView.Selected)
    async def on_select(self, event: ListView.Selected) -> None:
        item_id = event.item.id or ""
        idx = int(item_id.removeprefix("d-"))
        await self.app.start_drill(ALL_DRILLS[idx])

    async def action_back(self) -> None:
        await self.app.pop_screen()


class RunScreen(Screen):
    BINDINGS = [Binding("escape", "abort", "Abort")]

    def __init__(self, drill: Drill) -> None:
        super().__init__()
        self.drill = drill
        self._task: asyncio.Task | None = None
        self._poll_task: asyncio.Task | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Center(Static(self.drill.name, id="drill-name"))
        yield Label("Hits: 0   Misses: 0", id="counters")
        yield Label("Tap pods as they light up.", id="hint")
        yield Footer()

    async def on_mount(self) -> None:
        self._task = asyncio.create_task(self._run())
        self._poll_task = asyncio.create_task(self._poll())

    async def _run(self) -> None:
        try:
            stats = await self.drill.run()
        except Exception as e:
            logging.exception("drill failed")
            self.app.notify(f"Drill error: {e}", severity="error")
            await self.app.pop_screen()
            return
        finally:
            if self._poll_task:
                self._poll_task.cancel()
        await self.app.show_results(stats)

    async def _poll(self) -> None:
        counters = self.query_one("#counters", Label)
        try:
            while True:
                s = self.drill.stats
                counters.update(f"Hits: {s.hits}   Misses: {s.misses}")
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            pass

    async def action_abort(self) -> None:
        if self._task:
            self._task.cancel()
        if self._poll_task:
            self._poll_task.cancel()
        await self.app.manager.all_off()
        await self.app.pop_screen()


class ResultsScreen(Screen):
    BINDINGS = [
        Binding("enter", "back", "Back to menu"),
        Binding("escape", "back", "Back to menu"),
        Binding("q", "app.quit", "Quit"),
    ]

    def __init__(self, stats: Stats) -> None:
        super().__init__()
        self.stats = stats

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            for line in self.stats.summary_lines():
                yield Label(line)
            yield Label("")
            yield Button("Back to menu", id="back")
        yield Footer()

    @on(Button.Pressed, "#back")
    async def on_back(self) -> None:
        await self.action_back()

    async def action_back(self) -> None:
        # pop Results, pop Run, leaving Menu on top
        await self.app.pop_screen()
        if isinstance(self.app.screen, RunScreen):
            await self.app.pop_screen()


class BlazepodApp(App):
    CSS = """
    Screen { align: center top; }
    DataTable { height: 1fr; }
    #drills { height: auto; max-height: 12; }
    """

    def __init__(self) -> None:
        super().__init__()
        self.manager = PodManager()

    def on_mount(self) -> None:
        self.title = "BlazePod controller"
        self.push_screen(ScanScreen())

    async def connect_pods(self, discovered: list[DiscoveredPod]) -> None:
        self.notify(f"Connecting to {len(discovered)} pod(s)...")
        errors = await self.manager.connect_all(discovered)
        if not self.manager.pods:
            self.notify("No pods connected — see blazepod.log", severity="error")
            return
        if errors:
            for addr, err in errors.items():
                self.notify(f"{addr}: {type(err).__name__}", severity="warning", timeout=5)
        await self.push_screen(MenuScreen())

    async def identify_pods(self, discovered: list[DiscoveredPod]) -> None:
        self.notify(f"Connecting {len(discovered)} pod(s) to identify...")
        temp = PodManager()
        try:
            errors = await temp.connect_all(discovered)
            if not temp.pods:
                self.notify("Could not connect any pod to identify", severity="error")
                return
            if errors:
                self.notify(f"{len(errors)} pod(s) still failing after retries", severity="warning")
            self.notify(f"Flashing {len(temp.pods)} pod(s) red...", timeout=3)
            await temp.identify_each(flashes=3)
            self.notify("Identify complete", timeout=2)
        finally:
            await temp.disconnect_all()

    async def start_drill(self, drill_cls: type[Drill]) -> None:
        drill = drill_cls(self.manager)
        await self.push_screen(RunScreen(drill))

    async def show_results(self, stats: Stats) -> None:
        await self.push_screen(ResultsScreen(stats))

    async def on_unmount(self) -> None:
        await self.manager.disconnect_all()


def main() -> None:
    logging.basicConfig(
        filename="blazepod.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    BlazepodApp().run()


if __name__ == "__main__":
    main()
