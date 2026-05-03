"""Qt configuration page for Custom Drill, modeled on the BlazePod 'Custom Activity' screen."""

from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QButtonGroup,
    QColorDialog,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from blazepod.drills import (
    CustomDrillConfig,
    DurationMode,
    LightDelay,
    LightsOut,
    PlayerConfig,
)


def _section_title(text: str) -> QLabel:
    lbl = QLabel(text)
    f = QFont()
    f.setPointSize(14)
    f.setBold(True)
    lbl.setFont(f)
    lbl.setStyleSheet("color: #1f6feb; padding-top: 12px;")
    return lbl


def _hr() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet("color: #30363d; background-color: #30363d; max-height: 1px;")
    return line


def _row(label: str, *widgets: QWidget) -> QWidget:
    w = QWidget()
    hl = QHBoxLayout(w)
    hl.setContentsMargins(0, 0, 0, 0)
    lbl = QLabel(label)
    lbl.setMinimumWidth(140)
    lbl.setStyleSheet("color: #c9d1d9;")
    hl.addWidget(lbl)
    for x in widgets:
        hl.addWidget(x)
    hl.addStretch(1)
    return w


def _radio_group(values: list[tuple[str, object]]) -> tuple[QWidget, QButtonGroup, dict[object, QRadioButton]]:
    container = QWidget()
    hl = QHBoxLayout(container)
    hl.setContentsMargins(0, 0, 0, 0)
    group = QButtonGroup(container)
    by_value: dict[object, QRadioButton] = {}
    for label, value in values:
        rb = QRadioButton(label)
        rb.setStyleSheet("color: #e6e6e6; padding-right: 16px;")
        group.addButton(rb)
        by_value[value] = rb
        hl.addWidget(rb)
    hl.addStretch(1)
    return container, group, by_value


def _spinbox(minimum: int, maximum: int, value: int) -> QSpinBox:
    s = QSpinBox()
    s.setRange(minimum, maximum)
    s.setValue(value)
    s.setMinimumWidth(80)
    return s


def _doublespin(minimum: float, maximum: float, value: float, step: float = 0.1, decimals: int = 1) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(minimum, maximum)
    s.setSingleStep(step)
    s.setDecimals(decimals)
    s.setValue(value)
    s.setMinimumWidth(90)
    return s


class ColorButton(QPushButton):
    """A button whose background = current color; click opens a color picker."""

    def __init__(self, color: tuple[int, int, int]) -> None:
        super().__init__()
        self._color = color
        self.setMinimumSize(36, 28)
        self.setMaximumWidth(60)
        self._refresh()
        self.clicked.connect(self._pick)

    @property
    def color(self) -> tuple[int, int, int]:
        return self._color

    def _refresh(self) -> None:
        r, g, b = self._color
        # invert text so it stays readable on light/dark backgrounds
        text_col = "white" if (r * 0.299 + g * 0.587 + b * 0.114) < 128 else "black"
        self.setStyleSheet(
            f"background-color: rgb({r},{g},{b}); color: {text_col};"
            f"border: 1px solid #30363d; border-radius: 6px; font-weight: 600;"
        )
        self.setText(f"#{r:02X}{g:02X}{b:02X}")

    def _pick(self) -> None:
        c = QColorDialog.getColor(QColor(*self._color), self, "Pick a color")
        if c.isValid():
            self._color = (c.red(), c.green(), c.blue())
            self._refresh()


class PlayerColorsRow(QWidget):
    """A row of color buttons + add/remove for one player."""

    def __init__(self, player: PlayerConfig) -> None:
        super().__init__()
        self.player = player
        self._buttons: list[ColorButton] = []
        self.layout_ = QHBoxLayout(self)
        self.layout_.setContentsMargins(0, 0, 0, 0)
        for c in player.colors:
            self._add_button(c)
        self.add_btn = QPushButton("+")
        self.add_btn.setObjectName("secondary")
        self.add_btn.setMaximumWidth(32)
        self.add_btn.clicked.connect(lambda: self._add_button((255, 255, 255)))
        self.remove_btn = QPushButton("−")
        self.remove_btn.setObjectName("secondary")
        self.remove_btn.setMaximumWidth(32)
        self.remove_btn.clicked.connect(self._remove_button)
        self.layout_.addWidget(self.add_btn)
        self.layout_.addWidget(self.remove_btn)
        self.layout_.addStretch(1)

    def _add_button(self, color: tuple[int, int, int]) -> None:
        btn = ColorButton(color)
        self._buttons.append(btn)
        # insert before the +/- buttons + stretch
        self.layout_.insertWidget(len(self._buttons) - 1, btn)

    def _remove_button(self) -> None:
        if len(self._buttons) <= 1:
            return
        btn = self._buttons.pop()
        btn.setParent(None)
        btn.deleteLater()

    def collect(self) -> list[tuple[int, int, int]]:
        return [b.color for b in self._buttons]


class CustomConfigPage(QWidget):
    """Form for building a CustomDrillConfig. Calls `on_start(config)` on Start."""

    def __init__(
        self,
        get_pod_count: Callable[[], int],
        on_start: Callable[[CustomDrillConfig], None],
        on_back: Callable[[], None],
    ) -> None:
        super().__init__()
        self.get_pod_count = get_pod_count
        self.on_start = on_start
        self.on_back = on_back
        self.config = CustomDrillConfig()

        # Scroll wrapper for small windows
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.addWidget(scroll)

        body = QWidget()
        scroll.setWidget(body)
        v = QVBoxLayout(body)
        v.setContentsMargins(20, 10, 20, 10)
        v.setSpacing(8)

        title = QLabel("Custom Drill")
        tf = QFont()
        tf.setPointSize(20)
        tf.setBold(True)
        title.setFont(tf)
        v.addWidget(title)

        # ----- Setup -----
        v.addWidget(_section_title("Setup"))
        v.addWidget(_hr())

        self.stations_spin = _spinbox(1, 16, self.config.stations)
        v.addWidget(_row("Stations:", self.stations_spin))

        self.pps_spin = _spinbox(1, 16, self.config.pods_per_station)
        self.pod_summary = QLabel("")
        self.pod_summary.setStyleSheet("color: #8b949e;")
        v.addWidget(_row("Pods per station:", self.pps_spin, self.pod_summary))

        self.players_spin = _spinbox(1, 8, len(self.config.players))
        v.addWidget(_row("Players:", self.players_spin))

        self.players_container = QVBoxLayout()
        v.addLayout(self.players_container)
        self.player_rows: list[tuple[QLabel, PlayerColorsRow]] = []

        self.stations_spin.valueChanged.connect(self._refresh_summary)
        self.pps_spin.valueChanged.connect(self._refresh_summary)
        self.players_spin.valueChanged.connect(self._rebuild_players)

        # ----- Behavior -----
        v.addWidget(_section_title("Behavior"))
        v.addWidget(_hr())

        lo_widget, self.lights_out_group, self.lights_out_btns = _radio_group([
            ("Hit", LightsOut.HIT),
            ("Timeout", LightsOut.TIMEOUT),
            ("Hit & timeout", LightsOut.HIT_AND_TIMEOUT),
        ])
        self.lights_out_btns[LightsOut.HIT].setChecked(True)
        v.addWidget(_row("Lights out:", lo_widget))

        self.timeout_spin = _doublespin(0.1, 60.0, self.config.timeout_s, step=0.5)
        v.addWidget(_row("Timeout (s):", self.timeout_spin))

        ld_widget, self.light_delay_group, self.light_delay_btns = _radio_group([
            ("None", LightDelay.NONE),
            ("Fixed", LightDelay.FIXED),
            ("Random", LightDelay.RANDOM),
        ])
        self.light_delay_btns[LightDelay.NONE].setChecked(True)
        v.addWidget(_row("Light delay:", ld_widget))

        self.delay_fixed_spin = _doublespin(0.0, 10.0, self.config.light_delay_fixed_s, step=0.1)
        v.addWidget(_row("Fixed delay (s):", self.delay_fixed_spin))

        self.delay_min_spin = _doublespin(0.0, 10.0, self.config.light_delay_min_s, step=0.1)
        self.delay_max_spin = _doublespin(0.0, 10.0, self.config.light_delay_max_s, step=0.1)
        sep = QLabel(" — ")
        sep.setStyleSheet("color: #8b949e;")
        v.addWidget(_row("Random delay (s):", self.delay_min_spin, sep, self.delay_max_spin))

        # ----- Duration -----
        v.addWidget(_section_title("Duration"))
        v.addWidget(_hr())

        dm_widget, self.duration_mode_group, self.duration_mode_btns = _radio_group([
            ("Time", DurationMode.TIME),
            ("Hit count", DurationMode.HIT_COUNT),
            ("Time & hit count", DurationMode.TIME_AND_HIT_COUNT),
        ])
        self.duration_mode_btns[DurationMode.TIME].setChecked(True)
        v.addWidget(_row("Duration mode:", dm_widget))

        self.duration_time_spin = _doublespin(1.0, 3600.0, self.config.duration_time_s, step=1.0, decimals=0)
        v.addWidget(_row("Time (s):", self.duration_time_spin))

        self.duration_hits_spin = _spinbox(1, 9999, self.config.duration_hit_count)
        v.addWidget(_row("Hit count:", self.duration_hits_spin))

        self.cycles_spin = _spinbox(1, 99, self.config.cycles)
        v.addWidget(_row("Cycles:", self.cycles_spin))

        # Wire up dynamic enable/disable
        self.lights_out_btns[LightsOut.HIT].toggled.connect(self._refresh_enabled)
        self.lights_out_btns[LightsOut.TIMEOUT].toggled.connect(self._refresh_enabled)
        self.lights_out_btns[LightsOut.HIT_AND_TIMEOUT].toggled.connect(self._refresh_enabled)
        for rb in self.light_delay_btns.values():
            rb.toggled.connect(self._refresh_enabled)
        for rb in self.duration_mode_btns.values():
            rb.toggled.connect(self._refresh_enabled)

        # ----- Footer -----
        footer = QHBoxLayout()
        back = QPushButton("← Back")
        back.setObjectName("secondary")
        back.clicked.connect(lambda: self.on_back())
        footer.addWidget(back)
        footer.addStretch(1)
        self.start_btn = QPushButton("Start drill →")
        self.start_btn.clicked.connect(self._on_start_clicked)
        footer.addWidget(self.start_btn)
        v.addLayout(footer)

        self.error_lbl = QLabel("")
        self.error_lbl.setStyleSheet("color: #f85149;")
        v.addWidget(self.error_lbl)

        self._rebuild_players(len(self.config.players))
        self._refresh_summary()
        self._refresh_enabled()

    # ---- Dynamic widgets ----

    def _rebuild_players(self, count: int) -> None:
        # Clear existing player rows
        while self.players_container.count():
            item = self.players_container.takeAt(0)
            if item is None:
                break
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self.player_rows = []

        defaults = [
            (255, 255, 255), (0, 200, 255), (255, 50, 50), (50, 220, 80),
            (255, 200, 0), (255, 0, 200), (180, 100, 255), (255, 120, 0),
        ]
        for i in range(count):
            row_widget = QWidget()
            hl = QHBoxLayout(row_widget)
            hl.setContentsMargins(0, 0, 0, 0)
            label = QLabel(f"Player {i + 1} colors:")
            label.setMinimumWidth(140)
            label.setStyleSheet("color: #c9d1d9;")
            hl.addWidget(label)
            pcr = PlayerColorsRow(PlayerConfig(f"Player {i + 1}", [defaults[i % len(defaults)]]))
            hl.addWidget(pcr)
            self.players_container.addWidget(row_widget)
            self.player_rows.append((label, pcr))
        self._refresh_summary()

    def _refresh_summary(self) -> None:
        total = self.stations_spin.value() * self.pps_spin.value()
        connected = self.get_pod_count()
        suffix = f"({total} pods needed; {connected} connected)"
        color = "#3fb950" if total <= connected else "#f85149"
        self.pod_summary.setText(f"<span style='color: {color};'>{suffix}</span>")

    def _refresh_enabled(self) -> None:
        # Timeout field used only when lights_out involves timeout
        lo = self._current_lights_out()
        self.timeout_spin.setEnabled(lo in (LightsOut.TIMEOUT, LightsOut.HIT_AND_TIMEOUT))

        ld = self._current_light_delay()
        self.delay_fixed_spin.setEnabled(ld == LightDelay.FIXED)
        self.delay_min_spin.setEnabled(ld == LightDelay.RANDOM)
        self.delay_max_spin.setEnabled(ld == LightDelay.RANDOM)

        dm = self._current_duration_mode()
        self.duration_time_spin.setEnabled(dm in (DurationMode.TIME, DurationMode.TIME_AND_HIT_COUNT))
        self.duration_hits_spin.setEnabled(dm in (DurationMode.HIT_COUNT, DurationMode.TIME_AND_HIT_COUNT))

    def _current_lights_out(self) -> LightsOut:
        for v, rb in self.lights_out_btns.items():
            if rb.isChecked():
                return v  # type: ignore[return-value]
        return LightsOut.HIT

    def _current_light_delay(self) -> LightDelay:
        for v, rb in self.light_delay_btns.items():
            if rb.isChecked():
                return v  # type: ignore[return-value]
        return LightDelay.NONE

    def _current_duration_mode(self) -> DurationMode:
        for v, rb in self.duration_mode_btns.items():
            if rb.isChecked():
                return v  # type: ignore[return-value]
        return DurationMode.TIME

    # ---- Submit ----

    def _on_start_clicked(self) -> None:
        cfg = CustomDrillConfig(
            stations=self.stations_spin.value(),
            pods_per_station=self.pps_spin.value(),
            players=[
                PlayerConfig(name=f"Player {i + 1}", colors=row.collect())
                for i, (_, row) in enumerate(self.player_rows)
            ],
            lights_out=self._current_lights_out(),
            timeout_s=self.timeout_spin.value(),
            light_delay=self._current_light_delay(),
            light_delay_fixed_s=self.delay_fixed_spin.value(),
            light_delay_min_s=self.delay_min_spin.value(),
            light_delay_max_s=self.delay_max_spin.value(),
            duration_mode=self._current_duration_mode(),
            duration_time_s=self.duration_time_spin.value(),
            duration_hit_count=self.duration_hits_spin.value(),
            cycles=self.cycles_spin.value(),
        )
        if cfg.total_pods_needed > self.get_pod_count():
            self.error_lbl.setText(
                f"Need {cfg.total_pods_needed} pods, only {self.get_pod_count()} connected."
            )
            return
        self.error_lbl.setText("")
        self.on_start(cfg)

    def refresh_for_pod_count(self) -> None:
        self._refresh_summary()
