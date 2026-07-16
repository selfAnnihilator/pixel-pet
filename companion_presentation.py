"""Pure presentation planning for the desktop companion and Pet Preview."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping


@dataclass(frozen=True)
class SpriteMetrics:
    cell_width: int
    cell_height: int
    scale: float
    bounds: Mapping[str, tuple[tuple[int, int, int, int], ...]]


@dataclass(frozen=True)
class SpriteDraw:
    sheet: str
    state: str
    frame: int
    x: int
    y: int
    width: float
    height: float
    scale: float


@dataclass(frozen=True)
class HeartDraw:
    x: int
    y: int
    scale: float
    alpha: float


@dataclass(frozen=True)
class InputRegion:
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class PresentationPlan:
    sprite: SpriteDraw
    input_region: InputRegion | None
    hearts: tuple[HeartDraw, ...]


class CompanionPresentation:
    """Convert one Behavior Snapshot into pure rendering instructions."""

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

    @staticmethod
    def overlay_scale(*, base_scale: float, size_percent: int) -> float:
        return base_scale * max(75, min(200, int(size_percent))) / 100.0

    @staticmethod
    def position_to_anchor(
        position: tuple[float, float], viewport: tuple[int, int]
    ) -> tuple[float, float]:
        width, height = viewport
        return width * position[0], height * position[1]

    @staticmethod
    def anchor_to_position(
        anchor: tuple[float, float], viewport: tuple[int, int]
    ) -> tuple[float, float]:
        width, height = viewport
        return anchor[0] / max(1, width), anchor[1] / max(1, height)

    def clamp_anchor(
        self,
        anchor: tuple[float, float],
        *,
        viewport: tuple[int, int],
        metrics: SpriteMetrics,
    ) -> tuple[float, float]:
        width, height = viewport
        draw_width = metrics.cell_width * metrics.scale
        draw_height = metrics.cell_height * metrics.scale
        return (
            self._clamp(anchor[0], draw_width / 2, width - draw_width / 2),
            self._clamp(anchor[1], draw_height, height),
        )

    def selection_for(self, snapshot) -> tuple[str, str, int]:
        if snapshot.pose == "dragging":
            return "drag", "drag", {"left": 1, "middle": 2, "right": 3}[snapshot.variant]
        if snapshot.pose == "petting":
            return "pet", "pet", {"relaxed": 0, "left": 1, "right": 2}[snapshot.variant]
        if snapshot.pose == "typing":
            return "type", "type", {"ready": 0, "left": 1, "right": 3}[snapshot.variant]
        if snapshot.pose == "tracking":
            return "base", "track", self.TRACK_FRAMES[snapshot.variant]
        if snapshot.pose == "hunting":
            if snapshot.variant.startswith("transition_"):
                return "hunt", "hunt_transition", int(snapshot.variant.rsplit("_", 1)[1])
            bend, gaze = snapshot.variant.split("_", 1)
            gaze_frame = 0 if gaze == "forward" else self.TRACK_FRAMES[gaze]
            return "hunt", f"hunt_{bend}", gaze_frame
        return "base", "track", 0

    def overlay_plan(
        self,
        snapshot,
        *,
        viewport: tuple[int, int],
        sheets: Mapping[str, SpriteMetrics],
        size_percent: int,
    ) -> PresentationPlan:
        width, height = viewport
        sheet_name, state, frame = self.selection_for(snapshot)
        metrics = sheets.get(sheet_name) or sheets["base"]
        frame = self._bounded_frame(metrics, state, frame)
        draw_width = metrics.cell_width * metrics.scale
        draw_height = metrics.cell_height * metrics.scale
        anchor_x, anchor_y = self.clamp_anchor(
            self.position_to_anchor(snapshot.position, viewport),
            viewport=viewport,
            metrics=metrics,
        )
        sprite = SpriteDraw(
            sheet=sheet_name if sheet_name in sheets else "base",
            state=state,
            frame=frame,
            x=round(anchor_x - draw_width / 2),
            y=round(anchor_y - draw_height),
            width=draw_width,
            height=draw_height,
            scale=metrics.scale,
        )
        region = self._input_region(sprite, metrics, width, height)
        base = sheets["base"]
        hearts = self._overlay_hearts(
            snapshot,
            anchor_x=anchor_x,
            anchor_y=anchor_y,
            base=base,
            size_percent=size_percent,
        )
        return PresentationPlan(sprite=sprite, input_region=region, hearts=hearts)

    def preview_plan(
        self,
        snapshot,
        *,
        viewport: tuple[int, int],
        sheets: Mapping[str, SpriteMetrics],
        size_percent: int,
        padding: int = 20,
    ) -> PresentationPlan:
        width, height = viewport
        sheet_name, state, frame = self.selection_for(snapshot)
        metrics = sheets.get(sheet_name) or sheets["base"]
        frame = self._bounded_frame(metrics, state, frame)
        bounds = metrics.bounds[state][frame]
        opaque_width = max(1, bounds[2] - bounds[0])
        desired_width = 105 * size_percent / 100.0
        available_width = max(1, width - padding * 2)
        available_height = max(1, height - padding * 2)
        scale = max(
            0.5,
            min(
                desired_width / opaque_width,
                available_width / metrics.cell_width,
                available_height / metrics.cell_height,
            ),
        )
        draw_width = metrics.cell_width * scale
        draw_height = metrics.cell_height * scale
        sprite = SpriteDraw(
            sheet=sheet_name if sheet_name in sheets else "base",
            state=state,
            frame=frame,
            x=round((width - draw_width) / 2),
            y=round((height - draw_height) / 2),
            width=draw_width,
            height=draw_height,
            scale=scale,
        )
        return PresentationPlan(sprite=sprite, input_region=None, hearts=())

    def interaction_target(
        self,
        *,
        x: float,
        y: float,
        sprite: SpriteDraw,
        petting_enabled: bool,
    ) -> str:
        nx, ny = self.normalized_sprite_point(x=x, y=y, sprite=sprite)
        if petting_enabled and self.inside_petting(x=nx, y=ny):
            return "petting"
        return "drag"

    def inside_petting_point(
        self,
        *,
        x: float,
        y: float,
        sprite: SpriteDraw,
        tolerance: float = 0.0,
    ) -> bool:
        nx, ny = self.normalized_sprite_point(x=x, y=y, sprite=sprite)
        return self.inside_petting(x=nx, y=ny, tolerance=tolerance)

    def normalized_sprite_point(
        self, *, x: float, y: float, sprite: SpriteDraw
    ) -> tuple[float, float]:
        return (
            (x - sprite.x) / max(1.0, sprite.width),
            (y - sprite.y) / max(1.0, sprite.height),
        )

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

    def tracking_direction(
        self, *, dx: float, dy: float, deadzone: float
    ) -> str | None:
        if math.hypot(dx, dy) <= deadzone:
            return None
        angle = math.degrees(math.atan2(dx, -dy)) % 360.0
        sector = int((angle + 22.5) // 45) % 8
        return self.TRACK_DIRECTIONS[sector]

    @staticmethod
    def sprite_center(sprite: SpriteDraw) -> tuple[float, float]:
        return sprite.x + sprite.width / 2.0, sprite.y + sprite.height / 2.0

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        if high < low:
            return (low + high) / 2
        return max(low, min(value, high))

    @staticmethod
    def _bounded_frame(metrics: SpriteMetrics, state: str, frame: int) -> int:
        frames = metrics.bounds[state]
        return max(0, min(frame, len(frames) - 1))

    @staticmethod
    def _input_region(
        sprite: SpriteDraw,
        metrics: SpriteMetrics,
        viewport_width: int,
        viewport_height: int,
    ) -> InputRegion | None:
        bx0, by0, bx1, by1 = metrics.bounds[sprite.state][sprite.frame]
        x = max(0, round(sprite.x + bx0 * sprite.scale))
        y = max(0, round(sprite.y + by0 * sprite.scale))
        width = min(round((bx1 - bx0) * sprite.scale), viewport_width - x)
        height = min(round((by1 - by0) * sprite.scale), viewport_height - y)
        if width <= 0 or height <= 0:
            return None
        return InputRegion(x=x, y=y, width=width, height=height)

    @staticmethod
    def _overlay_hearts(
        snapshot,
        *,
        anchor_x: float,
        anchor_y: float,
        base: SpriteMetrics,
        size_percent: int,
    ) -> tuple[HeartDraw, ...]:
        heart_scale = size_percent / 100.0
        draws = []
        for heart in snapshot.hearts:
            progress = heart.progress
            alpha = 1.0 if heart.static or progress < 2 / 3 else 3 * (1.0 - progress)
            draws.append(
                HeartDraw(
                    x=round(anchor_x + heart.drift * 4 * progress - 3.5 * heart_scale),
                    y=round(
                        anchor_y
                        - base.cell_height * base.scale * 0.78
                        - 18 * progress
                        - 3.5 * heart_scale
                    ),
                    scale=heart_scale,
                    alpha=max(0.0, alpha),
                )
            )
        return tuple(draws)
