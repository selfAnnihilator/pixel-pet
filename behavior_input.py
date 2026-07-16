"""Lifecycle-owned evdev delivery for semantic companion activity."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import glob
import os
import select
import struct
import threading
import time
from typing import Callable


@dataclass(frozen=True)
class PointerMotion:
    x: float
    y: float
    at: float
    horizontal_deltas: tuple[float, ...] = ()


@dataclass(frozen=True)
class TypingStep:
    at: float


@dataclass(frozen=True)
class TypingHeld:
    held: bool
    at: float


BehaviorObservation = PointerMotion | TypingStep | TypingHeld


class EvdevBehaviorActivityAdapter:
    """Read evdev once, coalesce pointer motion, and deliver immutable observations."""

    EVENT = struct.Struct("llHHi")
    EV_KEY = 0x01
    EV_REL = 0x02
    REL_X = 0x00
    REL_Y = 0x01
    KEY_DOWN = 1

    def __init__(
        self,
        on_observation: Callable[[BehaviorObservation], None],
        *,
        dispatch: Callable[[Callable[[], bool]], object] | None = None,
        clock: Callable[[], float] = time.monotonic,
        pointer_paths: Callable[[], list[str]] | None = None,
        keyboard_paths: Callable[[], list[str]] | None = None,
    ) -> None:
        self._on_observation = on_observation
        self._dispatch = dispatch or (lambda callback: callback())
        self._clock = clock
        self._pointer_paths = pointer_paths or self._default_pointer_paths
        self._keyboard_paths = keyboard_paths or self._default_keyboard_paths
        self._lock = threading.Lock()
        self._fds: dict[int, str] = {}
        self._held_keys: set[int] = set()
        self._pending: deque[BehaviorObservation] = deque()
        self._pending_pointer: PointerMotion | None = None
        self._delivery_scheduled = False
        self._thread: threading.Thread | None = None
        self._stopping = False
        self._pointer_enabled = False
        self._typing_enabled = False
        self.pointer_available = False
        self.keyboard_available = False
        self._width = self._height = 0
        self._pointer_x = self._pointer_y = 0.0
        self._control_read, self._control_write = os.pipe2(
            os.O_NONBLOCK | os.O_CLOEXEC
        )

    @staticmethod
    def _default_pointer_paths() -> list[str]:
        paths = sorted(set(glob.glob("/dev/input/by-path/*-event-mouse")))
        return paths or sorted(glob.glob("/dev/input/event*"))

    @staticmethod
    def _default_keyboard_paths() -> list[str]:
        return sorted(
            set(
                glob.glob("/dev/input/by-path/*-event-kbd")
                + glob.glob("/dev/input/by-id/*-event-kbd")
            )
        )

    def set_viewport(self, width: int, height: int) -> None:
        with self._lock:
            if self._width == 0:
                self._pointer_x, self._pointer_y = width / 2.0, height / 2.0
            self._width, self._height = width, height
            self._pointer_x = min(max(self._pointer_x, 0.0), float(width or 1))
            self._pointer_y = min(max(self._pointer_y, 0.0), float(height or 1))

    def start(self, *, pointer_enabled: bool, typing_enabled: bool) -> None:
        self.configure(
            pointer_enabled=pointer_enabled,
            typing_enabled=typing_enabled,
        )
        with self._lock:
            if self._thread is not None:
                return
            self._stopping = False
            self._thread = threading.Thread(
                target=self._reader,
                name="pixel-pet-input",
                daemon=True,
            )
            self._thread.start()

    def configure(self, *, pointer_enabled: bool, typing_enabled: bool) -> None:
        release_held = False
        with self._lock:
            self._pointer_enabled = bool(pointer_enabled)
            self._typing_enabled = bool(typing_enabled)
            release_held = bool(self._held_keys) and not self._typing_enabled
            if release_held:
                self._held_keys.clear()
            self._replace_devices_locked()
        if release_held:
            self._queue(TypingHeld(False, self._clock()))
        self._wake_reader()

    def recheck_access(self) -> None:
        self.configure(
            pointer_enabled=self._pointer_enabled,
            typing_enabled=self._typing_enabled,
        )

    def stop(self) -> None:
        with self._lock:
            self._stopping = True
            thread = self._thread
        self._wake_reader()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        with self._lock:
            self._thread = None
            self._close_devices_locked()
            self._pending.clear()
            self._pending_pointer = None

    def close(self) -> None:
        self.stop()
        for fd in (self._control_read, self._control_write):
            try:
                os.close(fd)
            except OSError:
                pass

    def consume_pointer_bytes(self, payload: bytes, *, at: float | None = None) -> None:
        dx = dy = 0
        for offset in range(0, len(payload) - self.EVENT.size + 1, self.EVENT.size):
            _, _, event_type, code, value = self.EVENT.unpack_from(payload, offset)
            if event_type != self.EV_REL:
                continue
            if code == self.REL_X:
                dx += value
            elif code == self.REL_Y:
                dy += value
        if not (dx or dy):
            return
        with self._lock:
            previous_x = self._pointer_x
            self._pointer_x = min(
                max(self._pointer_x + dx, 0.0), float(self._width or 1)
            )
            self._pointer_y = min(
                max(self._pointer_y + dy, 0.0), float(self._height or 1)
            )
            x, y = self._pointer_x, self._pointer_y
            actual_dx = x - previous_x
        self._queue(
            PointerMotion(
                x=x,
                y=y,
                at=self._clock() if at is None else at,
                horizontal_deltas=(actual_dx,) if actual_dx else (),
            )
        )

    def consume_keyboard_bytes(self, payload: bytes, *, at: float | None = None) -> None:
        observed_at = self._clock() if at is None else at
        activities: list[BehaviorObservation] = []
        with self._lock:
            for offset in range(0, len(payload) - self.EVENT.size + 1, self.EVENT.size):
                _, _, event_type, code, value = self.EVENT.unpack_from(payload, offset)
                if event_type != self.EV_KEY:
                    continue
                if value == self.KEY_DOWN and code not in self._held_keys:
                    was_empty = not self._held_keys
                    self._held_keys.add(code)
                    activities.append(TypingStep(observed_at))
                    if was_empty:
                        activities.append(TypingHeld(True, observed_at))
                elif value == 0 and code in self._held_keys:
                    self._held_keys.remove(code)
                    if not self._held_keys:
                        activities.append(TypingHeld(False, observed_at))
        for activity in activities:
            self._queue(activity)

    def _replace_devices_locked(self) -> None:
        self._close_devices_locked()
        pointer_paths = self._pointer_paths()
        keyboard_paths = self._keyboard_paths()
        if self._pointer_enabled:
            pointer_fds = self._open_paths(pointer_paths)
            self._fds.update((fd, "pointer") for fd in pointer_fds)
            self.pointer_available = bool(pointer_fds)
        else:
            self.pointer_available = self._probe_paths(pointer_paths)
        if self._typing_enabled:
            keyboard_fds = self._open_paths(keyboard_paths)
            self._fds.update((fd, "keyboard") for fd in keyboard_fds)
            self.keyboard_available = bool(keyboard_fds)
        else:
            self.keyboard_available = self._probe_paths(keyboard_paths)

    @staticmethod
    def _open_paths(paths: list[str]) -> list[int]:
        fds = []
        opened = set()
        for path in paths:
            try:
                real = os.path.realpath(path)
                if real in opened:
                    continue
                fds.append(os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC))
                opened.add(real)
            except OSError:
                continue
        return fds

    @classmethod
    def _probe_paths(cls, paths: list[str]) -> bool:
        fds = cls._open_paths(paths)
        for fd in fds:
            try:
                os.close(fd)
            except OSError:
                pass
        return bool(fds)

    def _close_devices_locked(self) -> None:
        for fd in self._fds:
            try:
                os.close(fd)
            except OSError:
                pass
        self._fds.clear()

    def _wake_reader(self) -> None:
        try:
            os.write(self._control_write, b"x")
        except OSError:
            pass

    def _reader(self) -> None:
        while True:
            with self._lock:
                if self._stopping:
                    return
                sources = dict(self._fds)
            try:
                ready, _, _ = select.select(
                    [self._control_read, *sources], [], []
                )
            except (OSError, ValueError):
                continue
            if self._control_read in ready:
                try:
                    os.read(self._control_read, 4096)
                except OSError:
                    pass
            for fd in ready:
                kind = sources.get(fd)
                if kind is None:
                    continue
                try:
                    payload = os.read(fd, self.EVENT.size * 64)
                except OSError:
                    continue
                if not payload:
                    continue
                if kind == "pointer":
                    self.consume_pointer_bytes(payload)
                else:
                    self.consume_keyboard_bytes(payload)

    def _queue(self, observation: BehaviorObservation) -> None:
        with self._lock:
            if self._stopping:
                return
            if isinstance(observation, PointerMotion):
                horizontal_deltas = list(observation.horizontal_deltas)
                if self._pending_pointer is not None:
                    horizontal_deltas = list(
                        self._pending_pointer.horizontal_deltas
                    ) + horizontal_deltas
                coalesced: list[float] = []
                for delta in horizontal_deltas:
                    if coalesced and (coalesced[-1] > 0) == (delta > 0):
                        coalesced[-1] += delta
                    else:
                        coalesced.append(delta)
                self._pending_pointer = PointerMotion(
                    x=observation.x,
                    y=observation.y,
                    at=observation.at,
                    horizontal_deltas=tuple(coalesced),
                )
            else:
                self._pending.append(observation)
            if self._delivery_scheduled:
                return
            self._delivery_scheduled = True
        self._dispatch(self._deliver)

    def _deliver(self) -> bool:
        with self._lock:
            observations = list(self._pending)
            self._pending.clear()
            if self._pending_pointer is not None:
                observations.append(self._pending_pointer)
                self._pending_pointer = None
            self._delivery_scheduled = False
        for observation in observations:
            self._on_observation(observation)
        return False
