"""Lifecycle-aware driver for explicit Pet Behavior Advancement."""

from __future__ import annotations

import math
import time
from typing import Callable


class BehaviorAdvanceScheduler:
    """Advance Pet Behavior only for activity, deadlines, or active motion."""

    def __init__(
        self,
        behavior,
        on_snapshot: Callable[[object, bool], None],
        *,
        schedule_timeout: Callable[[int, Callable[[], bool]], object],
        cancel_timeout: Callable[[object], None],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.behavior = behavior
        self._on_snapshot = on_snapshot
        self._schedule_timeout = schedule_timeout
        self._cancel_timeout = cancel_timeout
        self._clock = clock
        self._source = None
        self._last_snapshot = None
        self._running = False

    @property
    def scheduled(self) -> bool:
        return self._source is not None

    @property
    def running(self) -> bool:
        return self._running

    def start(self) -> None:
        self._running = True
        self.refresh(force=True)

    def stop(self) -> None:
        self._running = False
        self._cancel_source()

    def activity(self, *, at: float | None = None) -> None:
        self.refresh(at=at, force=False)

    def invalidate(self, *, at: float | None = None) -> None:
        self.refresh(at=at, force=True)

    def refresh(self, *, at: float | None = None, force: bool = False) -> None:
        if not self._running:
            return
        clock_now = self._clock()
        now = clock_now if at is None else max(clock_now, at)
        self.behavior.advance(to=now)
        snapshot = self.behavior.snapshot()
        if force or snapshot != self._last_snapshot:
            self._last_snapshot = snapshot
            self._on_snapshot(snapshot, force)
        self._reschedule(now)

    def _reschedule(self, now: float) -> None:
        self._cancel_source()
        schedule = self.behavior.schedule()
        candidates = []
        if schedule.next_at is not None:
            candidates.append(schedule.next_at)
        if schedule.frame_interval is not None:
            candidates.append(now + schedule.frame_interval)
        if not candidates:
            return
        delay_ms = max(1, math.ceil((min(candidates) - now) * 1000))
        self._source = self._schedule_timeout(delay_ms, self._wake)

    def _wake(self) -> bool:
        self._source = None
        self.refresh()
        return False

    def _cancel_source(self) -> None:
        if self._source is None:
            return
        self._cancel_timeout(self._source)
        self._source = None
