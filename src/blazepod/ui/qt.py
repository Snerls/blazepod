"""PyQt6 desktop GUI for the BlazePod controller.

Pages (QStackedWidget): Scan -> Menu -> Run -> Results.
asyncio runs inside the Qt event loop via qasync, so the existing async
PodManager / Drill code is reused as-is.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Type

import qasync
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction, QFont
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from blazepod import PodManager
from blazepod.drills import ALL_DRILLS, CustomDrill, CustomDrillConfig, Drill, Stats
from blazepod.manager import discover_until
from blazepod.pod import DiscoveredPod
from blazepod.ui.config_page import CustomConfigPage


SCAN_TIMEOUT = 45.0


STYLESHEET = """
QMainWindow, QWidget { background-color: #0f1115; color: #e6e6e6; }
QLabel { color: #e6e6e6; }
QPushButton {
    background-color: #1f6feb; color: white; border: 0; border-radius: 8px;
    padding: 12px 18px; font-size: 16px; font-weight: 600;
}
QPushButton:hover { background-color: #388bfd; }
QPushButton:pressed { background-color: #1158c7; }
QPushButton:disabled { background-color: #30363d; color: #8b949e; }
QPushButton#secondary { background-color: #30363d; }
QPushButton#secondary:hover { background-color: #444c56; }
QPushButton#danger { background-color: #da3633; }
QPushButton#danger:hover { background-color: #f85149; }
QListWidget {
    background-color: #161b22; border: 1px solid #30363d; border-radius: 8px;
    padding: 6px; font-size: 14px;
}
QListWidget::item { padding: 8px; border-radius: 4px; }
QListWidget::item:selected { background-color: #1f6feb; color: white; }
QProgressBar {
    background-color: #161b22; border: 1px solid #30363d; border-radius: 6px;
    text-align: center; height: 18px; color: #e6e6e6;
}
QProgressBar::chunk { background-color: #1f6feb; border-radius: 5px; }
"""


def _huge(text: str, size: int = 64, color: str = "#e6e6e6") -> QLabel:
    lbl = QLabel(text)
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    f = QFont()
    f.setPointSize(size)
    f.setBold(True)
    lbl.setFont(f)
    lbl.setStyleSheet(f"color: {color};")
    return lbl


def _h2(text: str) -> QLabel:
    lbl = QLabel(text)
    f = QFont()
    f.setPointSize(20)
    f.setBold(True)
    lbl.setFont(f)
    return lbl


# -------------------- Scan page --------------------


class ScanPage(QWidget):
    def __init__(self, app: "BlazepodWindow") -> None:
        super().__init__()
        self.app = app
        self.discovered: list[DiscoveredPod] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 30, 40, 30)
        layout.setSpacing(14)

        layout.addWidget(_h2("Find your pods"))
        self.status = QLabel("Press Scan. Tap any pod that doesn't show up to wake it.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)

        self.list = QListWidget()
        layout.addWidget(self.list, stretch=1)

        btn_row = QHBoxLayout()
        self.scan_btn = QPushButton("Scan")
        self.scan_btn.clicked.connect(self._on_scan)
        btn_row.addWidget(self.scan_btn)

        self.identify_btn = QPushButton("Identify (flash)")
        self.identify_btn.setObjectName("secondary")
        self.identify_btn.setEnabled(False)
        self.identify_btn.clicked.connect(self._on_identify)
        btn_row.addWidget(self.identify_btn)

        self.connect_btn = QPushButton("Connect all →")
        self.connect_btn.setEnabled(False)
        self.connect_btn.clicked.connect(self._on_connect)
        btn_row.addWidget(self.connect_btn)

        layout.addLayout(btn_row)

    def showEvent(self, e):
        super().showEvent(e)
        # Auto-start the first scan when the page first appears
        if not self.discovered and not self.progress.isVisible():
            QTimer.singleShot(100, self._on_scan)

    def _on_scan(self) -> None:
        asyncio.create_task(self._scan())

    async def _scan(self) -> None:
        self.scan_btn.setEnabled(False)
        self.identify_btn.setEnabled(False)
        self.connect_btn.setEnabled(False)
        self.list.clear()
        self.discovered = []
        self.progress.show()
        self.status.setText(f"Scanning up to {SCAN_TIMEOUT:.0f}s — tap any sleeping pod to wake it...")

        def on_progress(found: list[DiscoveredPod]) -> None:
            self.discovered = found
            self._refresh_list()
            self.status.setText(f"Found {len(found)} so far... ({SCAN_TIMEOUT:.0f}s window)")

        try:
            self.discovered = await discover_until(
                target=None, max_wait=SCAN_TIMEOUT, on_progress=on_progress,
            )
        finally:
            self.progress.hide()
            self.scan_btn.setEnabled(True)

        self._refresh_list()
        if self.discovered:
            self.status.setText(f"Done. Found {len(self.discovered)} pod(s).")
            self.identify_btn.setEnabled(True)
            self.connect_btn.setEnabled(True)
        else:
            self.status.setText("No pods found. Wake them with a tap and press Scan again.")

    def _refresh_list(self) -> None:
        self.list.clear()
        for d in self.discovered:
            QListWidgetItem(f"{d.address}    rssi {d.rssi:>4}    {d.name or '?'}", self.list)

    def _on_identify(self) -> None:
        asyncio.create_task(self._identify())

    async def _identify(self) -> None:
        self.identify_btn.setEnabled(False)
        self.connect_btn.setEnabled(False)
        self.status.setText("Connecting to flash-identify...")
        temp = PodManager()
        try:
            errors = await temp.connect_all(self.discovered)
            if not temp.pods:
                self.status.setText("Could not connect to any pod for identify.")
                return
            self.status.setText(f"Flashing {len(temp.pods)} pod(s) red — watch the room.")
            await temp.identify_each(flashes=3)
            self.status.setText(f"Identify done ({len(temp.pods)} flashed, {len(errors)} unreachable).")
        finally:
            await temp.disconnect_all()
            self.identify_btn.setEnabled(True)
            self.connect_btn.setEnabled(True)

    def _on_connect(self) -> None:
        asyncio.create_task(self._connect())

    async def _connect(self) -> None:
        self.scan_btn.setEnabled(False)
        self.identify_btn.setEnabled(False)
        self.connect_btn.setEnabled(False)
        self.status.setText(f"Connecting to {len(self.discovered)} pod(s)...")
        errors = await self.app.manager.connect_all(self.discovered)
        if not self.app.manager.pods:
            self.status.setText("No pods connected — see blazepod.log")
            self.scan_btn.setEnabled(True)
            self.connect_btn.setEnabled(True)
            return
        if errors:
            QMessageBox.warning(
                self, "Some pods failed",
                f"{len(errors)} pod(s) didn't connect:\n\n" +
                "\n".join(f"  {a}: {type(e).__name__}" for a, e in errors.items()),
            )
        self.app.go_menu()


# -------------------- Menu page --------------------


class MenuPage(QWidget):
    def __init__(self, app: "BlazepodWindow") -> None:
        super().__init__()
        self.app = app

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 30, 40, 30)
        layout.setSpacing(20)

        self.title = _h2("Choose a drill")
        layout.addWidget(self.title)

        self.connected_lbl = QLabel("")
        layout.addWidget(self.connected_lbl)

        for drill_cls in ALL_DRILLS:
            btn = QPushButton(drill_cls.name)
            btn.setMinimumHeight(64)
            btn.clicked.connect(lambda _checked=False, c=drill_cls: self.app.start_drill(c))
            layout.addWidget(btn)

        custom_btn = QPushButton("Custom drill…")
        custom_btn.setMinimumHeight(64)
        custom_btn.setObjectName("secondary")
        custom_btn.clicked.connect(self.app.go_custom_config)
        layout.addWidget(custom_btn)

        layout.addStretch(1)

        bottom = QHBoxLayout()
        back = QPushButton("← Disconnect all")
        back.setObjectName("secondary")
        back.clicked.connect(lambda: asyncio.create_task(self.app.disconnect_and_back()))
        bottom.addWidget(back)
        bottom.addStretch(1)
        layout.addLayout(bottom)

    def refresh(self) -> None:
        self.connected_lbl.setText(f"Connected pods: {len(self.app.manager)}")


# -------------------- Run page --------------------


class RunPage(QWidget):
    def __init__(self, app: "BlazepodWindow") -> None:
        super().__init__()
        self.app = app
        self.drill: Drill | None = None
        self._task: asyncio.Task | None = None
        self._poll: QTimer | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 30, 40, 30)
        layout.setSpacing(16)

        self.title = _h2("")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title)

        layout.addStretch(1)

        counters = QHBoxLayout()
        counters.setSpacing(40)

        hits_box = QVBoxLayout()
        hits_box.addWidget(_huge("0", 96, "#3fb950"), alignment=Qt.AlignmentFlag.AlignCenter)
        hits_lbl = QLabel("HITS")
        hits_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hits_lbl.setStyleSheet("color: #8b949e; font-size: 16px;")
        hits_box.addWidget(hits_lbl)
        counters.addLayout(hits_box)

        misses_box = QVBoxLayout()
        misses_box.addWidget(_huge("0", 96, "#f85149"), alignment=Qt.AlignmentFlag.AlignCenter)
        misses_lbl = QLabel("MISSES")
        misses_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        misses_lbl.setStyleSheet("color: #8b949e; font-size: 16px;")
        misses_box.addWidget(misses_lbl)
        counters.addLayout(misses_box)

        # Keep references to the number labels for live update
        self.hits_num = hits_box.itemAt(0).widget()
        self.misses_num = misses_box.itemAt(0).widget()

        layout.addLayout(counters)

        self.last_lbl = QLabel("")
        self.last_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.last_lbl.setStyleSheet("color: #8b949e; font-size: 18px;")
        layout.addWidget(self.last_lbl)

        layout.addStretch(1)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        self.abort = QPushButton("Abort")
        self.abort.setObjectName("danger")
        self.abort.clicked.connect(self._on_abort)
        bottom.addWidget(self.abort)
        layout.addLayout(bottom)

    def start(self, drill: Drill) -> None:
        self.drill = drill
        self.title.setText(drill.name)
        self.hits_num.setText("0")
        self.misses_num.setText("0")
        self.last_lbl.setText("Tap pods as they light up.")
        self._task = asyncio.create_task(self._run())
        self._poll = QTimer(self)
        self._poll.setInterval(80)
        self._poll.timeout.connect(self._tick)
        self._poll.start()

    async def _run(self) -> None:
        try:
            stats = await self.drill.run()
        except asyncio.CancelledError:
            await self.app.manager.all_off()
            return
        except Exception as e:
            logging.exception("drill failed")
            QMessageBox.critical(self, "Drill error", str(e) or type(e).__name__)
            self.app.go_menu()
            return
        finally:
            if self._poll:
                self._poll.stop()
                self._poll = None
        self.app.show_results(stats)

    def _tick(self) -> None:
        if not self.drill:
            return
        s = self.drill.stats
        self.hits_num.setText(str(s.hits))
        self.misses_num.setText(str(s.misses))
        if s.reaction_times_ms:
            self.last_lbl.setText(f"Last reaction: {s.reaction_times_ms[-1]} ms")

    def _on_abort(self) -> None:
        if self._task:
            self._task.cancel()
        self.app.go_menu()


# -------------------- Results page --------------------


class ResultsPage(QWidget):
    def __init__(self, app: "BlazepodWindow") -> None:
        super().__init__()
        self.app = app
        self.stats: Stats | None = None
        self._last_drill: Type[Drill] | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 30, 40, 30)
        layout.setSpacing(16)

        self.title = _h2("")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title)

        layout.addStretch(1)

        self.big_number = _huge("—", 110, "#1f6feb")
        layout.addWidget(self.big_number)
        self.big_caption = QLabel("")
        self.big_caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.big_caption.setStyleSheet("color: #8b949e; font-size: 18px;")
        layout.addWidget(self.big_caption)

        layout.addStretch(1)

        self.detail = QLabel("")
        self.detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail.setStyleSheet("font-size: 16px; line-height: 1.6;")
        self.detail.setWordWrap(True)
        layout.addWidget(self.detail)

        layout.addStretch(1)

        row = QHBoxLayout()
        back = QPushButton("← Back to menu")
        back.setObjectName("secondary")
        back.clicked.connect(self.app.go_menu)
        row.addWidget(back)
        again = QPushButton("Run again ↻")
        again.clicked.connect(self._on_again)
        row.addWidget(again)
        layout.addLayout(row)

    def show_stats(self, stats: Stats, drill_cls: Type[Drill]) -> None:
        self.stats = stats
        self._last_drill = drill_cls
        self.title.setText(stats.drill_name)

        if stats.reaction_times_ms:
            self.big_number.setText(f"{stats.mean_ms:.0f}")
            self.big_caption.setText("ms — mean reaction time")
        else:
            self.big_number.setText("—")
            self.big_caption.setText("no successful taps")

        parts = [
            f"<b>Hits:</b> {stats.hits}     <b>Misses:</b> {stats.misses}     "
            f"<b>Accuracy:</b> {stats.accuracy:.0%}",
        ]
        if stats.reaction_times_ms:
            parts.append(
                f"<b>Best:</b> {stats.best_ms} ms     <b>Median:</b> {stats.median_ms:.0f} ms     "
                f"<b>Worst:</b> {stats.worst_ms} ms"
            )
        if stats.total_time_ms:
            parts.append(f"<b>Total time:</b> {stats.total_time_ms / 1000:.1f}s")

        if stats.subscores:
            parts.append("<br><b>Per-station:</b>")
            for label, sub in stats.subscores.items():
                line = (
                    f"&nbsp;&nbsp;{label}: hits={sub.hits} misses={sub.misses} "
                    f"acc={sub.accuracy:.0%}"
                )
                if sub.reaction_times_ms:
                    line += f" mean={sub.mean_ms:.0f}ms best={sub.best_ms}ms"
                parts.append(line)
        self.detail.setText("<br>".join(parts))

    def _on_again(self) -> None:
        if self._last_drill is CustomDrill and self.app._current_custom_config is not None:
            self.app._start_custom(self.app._current_custom_config)
        elif self._last_drill:
            self.app.start_drill(self._last_drill)


# -------------------- Main window --------------------


class BlazepodWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("BlazePod controller")
        self.resize(820, 720)
        self.manager = PodManager()
        self._current_drill_cls: Type[Drill] | None = None
        self._current_custom_config: CustomDrillConfig | None = None

        self.stack = QStackedWidget()
        self.scan_page = ScanPage(self)
        self.menu_page = MenuPage(self)
        self.config_page = CustomConfigPage(
            get_pod_count=lambda: len(self.manager),
            on_start=self._start_custom,
            on_back=self.go_menu,
        )
        self.run_page = RunPage(self)
        self.results_page = ResultsPage(self)
        self.stack.addWidget(self.scan_page)
        self.stack.addWidget(self.menu_page)
        self.stack.addWidget(self.config_page)
        self.stack.addWidget(self.run_page)
        self.stack.addWidget(self.results_page)
        self.setCentralWidget(self.stack)

        self.stack.setCurrentWidget(self.scan_page)

    def go_menu(self) -> None:
        self.menu_page.refresh()
        self.stack.setCurrentWidget(self.menu_page)

    def start_drill(self, drill_cls: Type[Drill]) -> None:
        try:
            drill = drill_cls(self.manager)
        except Exception as e:
            QMessageBox.critical(self, "Cannot start drill", str(e))
            return
        self._current_drill_cls = drill_cls
        self._current_custom_config = None
        self.stack.setCurrentWidget(self.run_page)
        self.run_page.start(drill)

    def go_custom_config(self) -> None:
        self.config_page.refresh_for_pod_count()
        self.stack.setCurrentWidget(self.config_page)

    def _start_custom(self, config: CustomDrillConfig) -> None:
        try:
            drill = CustomDrill(self.manager, config)
        except Exception as e:
            QMessageBox.critical(self, "Cannot start custom drill", str(e))
            return
        self._current_drill_cls = CustomDrill
        self._current_custom_config = config
        self.stack.setCurrentWidget(self.run_page)
        self.run_page.start(drill)

    def show_results(self, stats: Stats) -> None:
        self.results_page.show_stats(stats, self._current_drill_cls)
        self.stack.setCurrentWidget(self.results_page)

    async def disconnect_and_back(self) -> None:
        await self.manager.disconnect_all()
        self.scan_page.discovered = []
        self.scan_page.list.clear()
        self.scan_page.connect_btn.setEnabled(False)
        self.scan_page.identify_btn.setEnabled(False)
        self.stack.setCurrentWidget(self.scan_page)


def main() -> None:
    logging.basicConfig(
        filename="blazepod.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    app = QApplication(sys.argv)
    app.setStyleSheet(STYLESHEET)
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    window = BlazepodWindow()
    window.show()

    async def shutdown() -> None:
        await window.manager.disconnect_all()

    app.aboutToQuit.connect(lambda: asyncio.ensure_future(shutdown()))

    with loop:
        loop.run_forever()


if __name__ == "__main__":
    main()
