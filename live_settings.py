"""Immediate Live Setting application with coalesced durable persistence."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from copy import deepcopy
from typing import Callable, Mapping

from pet_settings import normalize


class LiveSettingsCoordinator:
    """Own desired settings, durable settings, persistence, and rollback."""

    def __init__(
        self,
        store,
        appliers: Mapping[str, Callable[[object], None]],
        *,
        schedule_timeout: Callable[[int, Callable[[], bool]], object],
        cancel_timeout: Callable[[object], None],
        dispatch: Callable[[Callable[[], bool]], object],
        on_applied: Callable[[], None] = lambda: None,
        debounce_ms: int = 250,
        submit: Callable[[Callable, object], Future] | None = None,
    ) -> None:
        self.store = store
        self._appliers = dict(appliers)
        self._schedule_timeout = schedule_timeout
        self._cancel_timeout = cancel_timeout
        self._dispatch = dispatch
        self._on_applied = on_applied
        self._debounce_ms = debounce_ms
        self._executor = None if submit is not None else ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="pixel-pet-settings"
        )
        self._submit = submit or self._executor.submit
        self._desired = deepcopy(store.data)
        self._durable = deepcopy(store.data)
        self._generation = 0
        self._timer = None
        self._future: Future | None = None
        self._future_generation: int | None = None
        self._save_queued = False
        self._listener: Callable[[str, Exception | None], None] | None = None
        self._closed = False

    @property
    def desired(self):
        return deepcopy(self._desired)

    def set_listener(
        self, listener: Callable[[str, Exception | None], None] | None
    ) -> None:
        self._listener = listener

    def change(self, key, value):
        if self._closed:
            raise RuntimeError("Live Settings coordinator is closed")
        candidate = self.store.prepare(key, value)
        normalized = candidate[key]
        if candidate == self._desired:
            return normalized
        previous = deepcopy(self._desired)
        self._desired = deepcopy(candidate)
        self.store.adopt(candidate)
        applier = self._appliers.get(key)
        try:
            if applier is not None:
                applier(normalized)
        except Exception:
            self._desired = previous
            self.store.adopt(previous)
            self._apply_snapshot(previous)
            raise
        self._on_applied()
        self._generation += 1
        self._arm_save()
        self._notify("saving")
        return normalized

    def replace(self, snapshot) -> None:
        normalized = normalize(snapshot)
        if normalized == self._desired:
            return
        self._desired = deepcopy(normalized)
        self.store.adopt(normalized)
        self._apply_snapshot(normalized)
        self._generation += 1
        self._arm_save()
        self._notify("saving")

    def accept_durable(self, snapshot) -> None:
        self._cancel_timer()
        self.store.adopt(snapshot)
        self._desired = deepcopy(self.store.data)
        self._durable = deepcopy(self.store.data)
        self._generation += 1
        self._notify("saved")

    def flush(self) -> None:
        self._cancel_timer()
        future = self._future
        if future is not None:
            try:
                future.result()
            except Exception as error:
                self._future = None
                self._rollback(error)
                raise
            self._durable = deepcopy(
                self._desired
                if self._future_generation == self._generation
                else self._durable
            )
            self._future = None
            self._future_generation = None
        if self._desired != self._durable:
            try:
                self.store.persist_snapshot(self._desired)
            except Exception as error:
                self._rollback(error)
                raise
            self._durable = deepcopy(self._desired)
        self.store.first_run = False
        self._save_queued = False
        self._notify("saved")

    def close(self) -> None:
        if self._closed:
            return
        try:
            self.flush()
        finally:
            self._closed = True
            if self._executor is not None:
                self._executor.shutdown(wait=True, cancel_futures=False)

    def _arm_save(self) -> None:
        self._cancel_timer()
        self._timer = self._schedule_timeout(
            self._debounce_ms, self._begin_save
        )

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._cancel_timeout(self._timer)
            self._timer = None

    def _begin_save(self) -> bool:
        self._timer = None
        if self._future is not None:
            self._save_queued = True
            return False
        snapshot = deepcopy(self._desired)
        generation = self._generation
        future = self._submit(self.store.persist_snapshot, snapshot)
        self._future = future
        self._future_generation = generation
        future.add_done_callback(
            lambda completed: self._dispatch(
                lambda: self._finish_save(completed, generation, snapshot)
            )
        )
        return False

    def _finish_save(self, future, generation, snapshot) -> bool:
        if future is not self._future:
            return False
        self._future = None
        self._future_generation = None
        try:
            future.result()
        except Exception as error:
            self._rollback(error)
            return False
        self._durable = deepcopy(snapshot)
        self.store.first_run = False
        if generation != self._generation or self._save_queued:
            self._save_queued = False
            self._begin_save()
        else:
            self._notify("saved")
        return False

    def _rollback(self, error: Exception) -> None:
        self._cancel_timer()
        self._future = None
        self._future_generation = None
        self._save_queued = False
        self._desired = deepcopy(self._durable)
        self.store.adopt(self._durable)
        self._apply_snapshot(self._durable)
        self._generation += 1
        self._notify("error", error)

    def _apply_snapshot(self, snapshot) -> None:
        for key, applier in self._appliers.items():
            applier(snapshot[key])
        self._on_applied()

    def _notify(self, state: str, error: Exception | None = None) -> None:
        if self._listener is not None:
            self._listener(state, error)
