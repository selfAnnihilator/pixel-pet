"""State model for user-driven pet behavior."""

from dataclasses import dataclass


@dataclass(frozen=True)
class HeartSnapshot:
    progress: float
    drift: int
    static: bool


@dataclass(frozen=True)
class _Heart:
    born_at: float
    drift: int


@dataclass(frozen=True)
class BehaviorSnapshot:
    activity: str
    pose: str
    variant: str
    position: tuple[float, float]
    visible: bool
    hiding_reasons: tuple[str, ...]
    petting_reactions: bool
    hearts: tuple[HeartSnapshot, ...]


@dataclass(frozen=True)
class BehaviorSchedule:
    next_at: float | None
    frame_interval: float | None


class PetBehavior:
    """Translate semantic input activity into renderable pet state."""

    def __init__(
        self,
        *,
        reduced_motion: bool = False,
        position: tuple[float, float] = (0.0, 0.0),
        typing_hold_seconds: float = 2.0,
        typing_reactions: bool = True,
        petting_reactions: bool = True,
        tracking_enabled: bool = True,
        tracking_hold_seconds: float = 0.18,
    ) -> None:
        self._reduced_motion = reduced_motion
        self._position = position
        self._petting_variant = "relaxed"
        self._hearts: list[_Heart] = []
        self._heart_serial = 0
        self._target: str | None = None
        self._last_x = 0.0
        self._direction = 0
        self._segment_travel = 0.0
        self._stroke_threshold = 0.0
        self._petting_active = False
        self._inside_petting = False
        self._last_heart_at: float | None = None
        self._emission_paused_at: float | None = None
        self._petting_hold_until: float | None = None
        self._typing_active = False
        self._typing_variant = "ready"
        self._typing_hold_seconds = typing_hold_seconds
        self._typing_reactions = typing_reactions
        self._petting_reactions = petting_reactions
        self._tracking_enabled = tracking_enabled
        self._tracking_hold_seconds = tracking_hold_seconds
        self._tracking_expires_at: float | None = None
        self._typing_hold_until: float | None = None
        self._next_typing_variant = "left"
        self._tracking_direction: str | None = None
        self._hunt_phase: str | None = None
        self._hunt_crouch = 0.0
        self._hunt_hold_until: float | None = None
        self._hunt_gaze = "forward"
        self._shake_direction = 0
        self._shake_travel = 0.0
        self._shake_reversals = 0
        self._shake_started_at: float | None = None
        self._hidden = False
        self._hiding_reasons: set[str] = set()
        self._dragging = False
        self._drag_wobble_sequence = ("middle", "left", "middle", "right")
        self._drag_wobble_index = 0
        self._drag_wobble_clock = 0.0
        self._drag_moved_at: float | None = None
        self._advanced_to = 0.0

    def begin_interaction(
        self,
        *,
        target: str,
        x: float,
        y: float,
        now: float,
        petting_width: float,
    ) -> None:
        del y, now
        if target == "petting" and not self._petting_reactions:
            return
        self._target = target
        self._last_x = x
        self._direction = 0
        self._segment_travel = 0.0
        self._stroke_threshold = petting_width * 0.25
        self._inside_petting = target == "petting"

    def move_interaction(
        self,
        *,
        x: float,
        y: float,
        inside_petting: bool,
        now: float,
    ) -> None:
        del y
        was_inside = self._inside_petting
        self._inside_petting = inside_petting
        if not inside_petting:
            if was_inside and self._petting_active:
                self._emission_paused_at = now
            self._last_x = x
            return
        if not was_inside:
            if self._emission_paused_at is not None and self._last_heart_at is not None:
                self._last_heart_at += now - self._emission_paused_at
                self._emission_paused_at = None
            self._last_x = x
            return
        delta = x - self._last_x
        self._last_x = x
        if self._target != "petting" or delta == 0:
            return

        direction = 1 if delta > 0 else -1
        if self._direction == 0:
            self._direction = direction
            self._segment_travel = abs(delta)
            return

        if direction == self._direction:
            self._segment_travel += abs(delta)
            return

        if self._segment_travel >= self._stroke_threshold:
            self._petting_variant = (
                "relaxed"
                if self._reduced_motion
                else ("left" if direction < 0 else "right")
            )
            if not self._petting_active:
                self._petting_active = True
                self._cancel_hunt()
                self._hearts.append(self._new_heart(now))
                self._last_heart_at = now

        self._direction = direction
        self._segment_travel = abs(delta)

    def end_interaction(self, *, now: float) -> None:
        self._target = None
        self._inside_petting = False
        if self._petting_active:
            self._petting_active = False
            self._petting_hold_until = now + 0.6
            self._petting_variant = "relaxed"

    def typing_step(self, *, at: float) -> None:
        if not self._typing_reactions or self._hidden or self._dragging:
            return
        if not self._petting_active and self._petting_hold_until is not None:
            self._petting_hold_until = None
            self._petting_variant = "relaxed"
            if self._reduced_motion:
                self._hearts.clear()
        self._cancel_hunt()
        self._tracking_direction = None
        self._tracking_expires_at = None
        self._reset_shake()
        self._typing_active = True
        self._typing_hold_until = None
        self._typing_variant = self._next_typing_variant
        self._next_typing_variant = (
            "right" if self._typing_variant == "left" else "left"
        )

    def typing_held(self, held: bool, *, at: float) -> None:
        if not self._typing_reactions or self._hidden or self._dragging:
            return
        if held:
            return
        if self._typing_active:
            self._typing_active = False
            self._typing_variant = "ready"
            self._typing_hold_until = at + self._typing_hold_seconds

    def typing_reactions_changed(self, enabled: bool, *, at: float) -> None:
        del at
        self._typing_reactions = bool(enabled)
        if not enabled:
            self._typing_active = False
            self._typing_hold_until = None
            self._typing_variant = "ready"

    def tracking_changed(self, direction: str | None, *, at: float) -> None:
        if (
            not self._tracking_enabled
            or self._reduced_motion
            or self._hidden
            or self._dragging
        ):
            return
        self._tracking_direction = direction
        self._tracking_expires_at = (
            at + self._tracking_hold_seconds if direction is not None else None
        )

    def pointer_moved(
        self,
        direction: str | None,
        *,
        horizontal_delta: float,
        at: float,
    ) -> None:
        """Observe pointer gaze and horizontal travel measured in cat widths."""
        self.tracking_changed(direction, at=at)
        if self._hunt_phase is not None:
            self._hunt_gaze = direction or "forward"
        if not self._can_hunt():
            self._reset_shake()
            return

        delta = float(horizontal_delta)
        if abs(delta) < 1e-6:
            return
        move_direction = 1 if delta > 0 else -1
        if (
            self._shake_started_at is not None
            and at - self._shake_started_at > 0.3
        ):
            self._reset_shake()
        if self._shake_direction == 0:
            self._shake_direction = move_direction
            self._shake_travel = abs(delta)
            self._shake_started_at = at
            return
        if move_direction == self._shake_direction:
            self._shake_travel += abs(delta)
            return

        completed_leg = self._shake_travel
        self._shake_direction = move_direction
        self._shake_travel = abs(delta)
        if completed_leg < 1.0:
            self._shake_reversals = 0
            self._shake_started_at = at
            return

        self._shake_reversals += 1
        if self._shake_reversals < 2:
            return
        self._activate_hunt(direction=direction, at=at)
        self._shake_reversals = 0
        self._shake_started_at = at

    def tracking_enabled_changed(self, enabled: bool, *, at: float) -> None:
        del at
        self._tracking_enabled = bool(enabled)
        if not enabled:
            self._tracking_direction = None
            self._tracking_expires_at = None
            self._cancel_hunt()
            self._reset_shake()

    def _set_reduced_motion(self, enabled: bool) -> None:
        self._reduced_motion = bool(enabled)
        if self._reduced_motion:
            self._tracking_direction = None
            self._tracking_expires_at = None
            self._cancel_hunt()
            self._reset_shake()
        if self._reduced_motion and self._petting_active:
            self._petting_variant = "relaxed"
            self._hearts = self._hearts[:1]

    def reduced_motion_changed(self, enabled: bool, *, at: float) -> None:
        del at
        self._set_reduced_motion(enabled)

    def petting_reactions_changed(self, enabled: bool, *, at: float) -> None:
        del at
        self._petting_reactions = bool(enabled)
        if not enabled:
            self._cancel_petting()

    def typing_hold_changed(self, seconds: float, *, at: float) -> None:
        self._typing_hold_seconds = max(0.0, min(5.0, float(seconds)))
        if self._typing_hold_until is not None:
            self._typing_hold_until = at + self._typing_hold_seconds

    def _cancel_petting(self) -> None:
        self._target = None
        self._petting_active = False
        self._petting_hold_until = None
        self._inside_petting = False
        self._emission_paused_at = None
        self._petting_variant = "relaxed"
        self._hearts.clear()

    def visibility_changed(self, reason: str, *, hidden: bool, at: float) -> None:
        del at
        was_hidden = bool(self._hiding_reasons)
        if hidden:
            self._hiding_reasons.add(reason)
        else:
            self._hiding_reasons.discard(reason)
        self._hidden = bool(self._hiding_reasons)
        if self._hidden and not was_hidden:
            self._target = None
            self._petting_active = False
            self._petting_hold_until = None
            self._typing_active = False
            self._typing_hold_until = None
            self._typing_variant = "ready"
            self._tracking_direction = None
            self._tracking_expires_at = None
            self._cancel_hunt()
            self._reset_shake()
            self._inside_petting = False
            self._petting_variant = "relaxed"
            self._hearts.clear()

    def set_dragging(self, dragging: bool, *, now: float) -> None:
        self._dragging = bool(dragging)
        if dragging:
            self._target = None
            self._petting_active = False
            self._petting_hold_until = None
            self._typing_active = False
            self._typing_hold_until = None
            self._typing_variant = "ready"
            self._tracking_direction = None
            self._tracking_expires_at = None
            self._cancel_hunt()
            self._reset_shake()
            self._inside_petting = False
            self._petting_variant = "relaxed"
            self._hearts.clear()
            self._drag_wobble_index = 0
            self._drag_wobble_clock = 0.0
            self._drag_moved_at = None
            self._advanced_to = max(self._advanced_to, now)

    def placement_changed(self, *, x: float, y: float, at: float) -> None:
        del at
        self._set_position(x=x, y=y)

    def _set_position(self, *, x: float, y: float) -> None:
        self._position = (
            max(0.0, min(1.0, x)),
            max(0.0, min(1.0, y)),
        )

    def move_drag(self, *, x: float, y: float, now: float) -> None:
        if self._dragging:
            self._set_position(x=x, y=y)
            self._drag_moved_at = now

    def advance(self, *, to: float) -> None:
        self._advance_timed_state(to)

    def schedule(self) -> BehaviorSchedule:
        if self._hidden:
            return BehaviorSchedule(next_at=None, frame_interval=None)
        deadlines = [
            deadline
            for deadline in (
                self._typing_hold_until,
                self._petting_hold_until,
                self._tracking_expires_at,
                self._hunt_hold_until,
            )
            if deadline is not None
        ]
        if self._petting_active and self._inside_petting and not self._reduced_motion:
            if self._last_heart_at is not None:
                deadlines.append(self._last_heart_at + 0.3)
        if not self._reduced_motion:
            deadlines.extend(heart.born_at + 0.9 for heart in self._hearts)
        moving_drag = (
            self._dragging
            and self._drag_moved_at is not None
            and self._advanced_to - self._drag_moved_at <= 0.12
        )
        moving_hearts = bool(self._hearts) and not self._reduced_motion
        moving_hunt = self._hunt_phase in ("enter", "exit")
        return BehaviorSchedule(
            next_at=min(deadlines) if deadlines else None,
            frame_interval=(1 / 30)
            if moving_drag or moving_hearts or moving_hunt
            else None,
        )

    def _can_hunt(self) -> bool:
        return (
            self._tracking_enabled
            and not self._reduced_motion
            and not self._hidden
            and not self._dragging
            and not self._typing_active
            and not self._petting_active
            and self._petting_hold_until is None
        )

    def _activate_hunt(self, *, direction: str | None, at: float) -> None:
        if self._hunt_phase is None:
            self._hunt_phase = "enter"
            self._hunt_crouch = 0.0
        elif self._hunt_phase == "exit":
            self._hunt_phase = "enter"
        self._hunt_gaze = direction or "forward"
        self._hunt_hold_until = at + 0.4

    def _reset_shake(self) -> None:
        self._shake_direction = 0
        self._shake_travel = 0.0
        self._shake_reversals = 0
        self._shake_started_at = None

    def _cancel_hunt(self) -> None:
        self._hunt_phase = None
        self._hunt_crouch = 0.0
        self._hunt_hold_until = None
        self._hunt_gaze = "forward"

    def _new_heart(self, born_at: float) -> _Heart:
        heart = _Heart(born_at=born_at, drift=(self._heart_serial % 3) - 1)
        self._heart_serial += 1
        return heart

    def _advance_timed_state(self, now: float) -> None:
        elapsed = max(0.0, now - self._advanced_to)
        if self._hunt_phase == "enter":
            self._hunt_crouch = min(1.0, self._hunt_crouch + elapsed / 0.2)
            if self._hunt_crouch >= 1.0:
                self._hunt_phase = "active"
        elif self._hunt_phase == "exit":
            self._hunt_crouch = max(0.0, self._hunt_crouch - elapsed / 0.2)
            if self._hunt_crouch <= 0.0:
                self._cancel_hunt()
        if (
            self._hunt_phase == "active"
            and self._hunt_hold_until is not None
            and now >= self._hunt_hold_until
        ):
            self._hunt_phase = "exit"
            self._hunt_hold_until = None
        if self._dragging:
            moving = (
                self._drag_moved_at is not None
                and now - self._drag_moved_at <= 0.12
            )
            if moving:
                self._drag_wobble_clock += elapsed
                while self._drag_wobble_clock >= 0.125:
                    self._drag_wobble_clock -= 0.125
                    self._drag_wobble_index = (
                        self._drag_wobble_index + 1
                    ) % len(self._drag_wobble_sequence)
            else:
                self._drag_wobble_index = 0
                self._drag_wobble_clock = 0.0
        if self._typing_hold_until is not None and now >= self._typing_hold_until:
            self._typing_hold_until = None
        if self._tracking_expires_at is not None and now >= self._tracking_expires_at:
            self._tracking_expires_at = None
            self._tracking_direction = None
        if not self._reduced_motion:
            self._hearts = [
                heart for heart in self._hearts if now - heart.born_at < 0.9
            ]
        if self._petting_hold_until is not None and now >= self._petting_hold_until:
            self._petting_hold_until = None
            self._petting_variant = "relaxed"
            if self._reduced_motion:
                self._hearts.clear()
        if (
            self._petting_active
            and self._inside_petting
            and not self._reduced_motion
            and self._last_heart_at is not None
        ):
            while now - self._last_heart_at >= 0.3 - 1e-9:
                self._last_heart_at += 0.3
                self._hearts.append(self._new_heart(self._last_heart_at))
                self._hearts = self._hearts[-3:]
        self._advanced_to = max(self._advanced_to, now)

    def snapshot(self) -> BehaviorSnapshot:
        pose = (
            "petting"
            if self._petting_active or self._petting_hold_until is not None
            else "sitting"
        )
        variant = self._petting_variant if pose == "petting" else "forward"
        if self._typing_active and not self._petting_active:
            pose = "typing"
            variant = self._typing_variant
        if self._hidden:
            activity = "hidden"
            pose = "hidden"
            variant = "forward"
        elif self._dragging:
            activity = "dragging"
            pose = "dragging"
            variant = self._drag_wobble_sequence[self._drag_wobble_index]
        elif self._petting_active:
            activity = "petting"
        elif self._typing_active:
            activity = "typing"
        elif self._petting_hold_until is not None:
            activity = "petting_hold"
        elif self._hunt_phase is not None:
            activity = (
                "mouse_hunt" if self._hunt_phase == "active" else "mouse_hunt_transition"
            )
            pose = "hunting"
            if self._hunt_phase == "enter":
                variant = f"transition_{round(self._hunt_crouch * 2)}"
            elif self._hunt_phase == "exit":
                variant = f"transition_{2 + round((1.0 - self._hunt_crouch) * 2)}"
            else:
                variant = f"front_{self._hunt_gaze}"
        elif self._tracking_direction is not None:
            activity = "tracking"
            pose = "tracking"
            variant = self._tracking_direction
        elif self._typing_hold_until is not None:
            activity = "typing_hold"
            pose = "typing"
            variant = "ready"
        else:
            activity = "sitting"
            variant = "forward"
        return BehaviorSnapshot(
            activity=activity,
            pose=pose,
            variant=variant,
            position=self._position,
            visible=not self._hidden,
            hiding_reasons=tuple(sorted(self._hiding_reasons)),
            petting_reactions=self._petting_reactions,
            hearts=tuple(
                HeartSnapshot(
                    progress=(
                        0.0
                        if self._reduced_motion
                        else min(1.0, max(0.0, self._advanced_to - heart.born_at) / 0.9)
                    ),
                    drift=heart.drift,
                    static=self._reduced_motion,
                )
                for heart in self._hearts
            ),
        )
