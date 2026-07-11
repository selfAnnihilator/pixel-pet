"""Geometry that maps Catbone sprite coordinates to semantic interactions."""

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class SpriteSelection:
    sheet: str
    state: str
    frame: int


class SpritePresentation:
    """Normalized interaction geometry shared by every tracking pose."""

    HEAD_CENTER = (0.5, 0.28)
    HEAD_RADIUS = (0.24, 0.22)
    TRACK_FRAMES = {
        "north": 1,
        "northeast": 2,
        "east": 3,
        "southeast": 4,
        "south": 5,
        "southwest": 6,
        "west": 7,
        "northwest": 8,
    }
    TRACK_DIRECTIONS = tuple(TRACK_FRAMES)

    def inside_petting(self, *, x: float, y: float, tolerance: float = 0.0) -> bool:
        center_x, center_y = self.HEAD_CENTER
        radius_x, radius_y = self.HEAD_RADIUS
        radius_x += tolerance
        radius_y += tolerance
        return (
            ((x - center_x) / radius_x) ** 2
            + ((y - center_y) / radius_y) ** 2
            <= 1.0
        )

    def interaction_target(
        self, *, x: float, y: float, petting_enabled: bool
    ) -> str:
        if petting_enabled and self.inside_petting(x=x, y=y):
            return "petting"
        return "drag"

    def selection_for(self, snapshot) -> SpriteSelection:
        if snapshot.pose == "dragging":
            frame = {"left": 1, "middle": 2, "right": 3}[snapshot.variant]
            return SpriteSelection("drag", "drag", frame)
        if snapshot.pose == "petting":
            frame = {"relaxed": 0, "left": 1, "right": 2}[snapshot.variant]
            return SpriteSelection("pet", "pet", frame)
        if snapshot.pose == "typing":
            frame = {"ready": 0, "left": 1, "right": 3}[snapshot.variant]
            return SpriteSelection("type", "type", frame)
        if snapshot.pose == "tracking":
            return SpriteSelection(
                "base", "track", self.TRACK_FRAMES[snapshot.variant]
            )
        return SpriteSelection("base", "track", 0)

    def tracking_direction(
        self, *, dx: float, dy: float, deadzone: float
    ) -> str | None:
        if (dx * dx + dy * dy) ** 0.5 <= deadzone:
            return None
        angle = math.degrees(math.atan2(dx, -dy)) % 360.0
        sector = int((angle + 22.5) // 45) % 8
        return self.TRACK_DIRECTIONS[sector]
