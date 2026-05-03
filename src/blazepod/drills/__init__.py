from blazepod.drills.base import Drill, Stats
from blazepod.drills.color_match import ColorMatchDrill
from blazepod.drills.custom import (
    CustomDrill,
    CustomDrillConfig,
    DurationMode,
    LightDelay,
    LightsOut,
    PlayerConfig,
)
from blazepod.drills.random_light import RandomLightDrill
from blazepod.drills.sequence import SequenceDrill

ALL_DRILLS: list[type[Drill]] = [RandomLightDrill, SequenceDrill, ColorMatchDrill]

__all__ = [
    "Drill", "Stats", "ALL_DRILLS",
    "RandomLightDrill", "SequenceDrill", "ColorMatchDrill",
    "CustomDrill", "CustomDrillConfig", "PlayerConfig",
    "LightsOut", "LightDelay", "DurationMode",
]
