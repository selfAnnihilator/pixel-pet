from concurrent.futures import Future
import tempfile
import unittest

from live_settings import LiveSettingsCoordinator
from pet_settings import SettingsStore


class FakeTimers:
    def __init__(self):
        self.next_id = 1
        self.sources = {}

    def schedule(self, delay, callback):
        source = self.next_id
        self.next_id += 1
        self.sources[source] = (delay, callback)
        return source

    def cancel(self, source):
        self.sources.pop(source, None)

    def fire(self):
        source = next(iter(self.sources))
        _delay, callback = self.sources.pop(source)
        callback()


class LiveSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = SettingsStore(path=f"{self.temp.name}/settings.json")
        self.timers = FakeTimers()
        self.dispatched = []
        self.futures = []
        self.applied = []
        self.statuses = []

        def submit(function, snapshot):
            future = Future()
            self.futures.append((future, function, snapshot))
            return future

        self.coordinator = LiveSettingsCoordinator(
            self.store,
            {"size_percent": lambda value: self.applied.append(value)},
            schedule_timeout=self.timers.schedule,
            cancel_timeout=self.timers.cancel,
            dispatch=self.dispatched.append,
            submit=submit,
        )
        self.coordinator.set_listener(
            lambda state, error: self.statuses.append((state, error))
        )

    def tearDown(self):
        self.temp.cleanup()

    def complete_save(self, error=None):
        future, function, snapshot = self.futures.pop(0)
        if error is None:
            function(snapshot)
            future.set_result(None)
        else:
            future.set_exception(error)
        while self.dispatched:
            self.dispatched.pop(0)()

    def test_changes_apply_immediately_and_coalesce_for_250ms(self):
        self.assertEqual(self.coordinator.change("size_percent", 125), 125)
        self.assertEqual(self.coordinator.change("size_percent", 150), 150)

        self.assertEqual(self.applied, [125, 150])
        self.assertEqual(len(self.timers.sources), 1)
        self.assertEqual(next(iter(self.timers.sources.values()))[0], 250)
        self.timers.fire()
        self.complete_save()

        self.assertEqual(self.store.get("size_percent"), 150)
        self.assertEqual(self.statuses[-1], ("saved", None))

    def test_equal_normalized_value_does_not_schedule_write(self):
        self.coordinator.change("size_percent", 101)
        self.coordinator.change("size_percent", 124)

        self.assertEqual(self.applied, [125])
        self.assertEqual(len(self.timers.sources), 1)

    def test_failure_rolls_visible_state_back_to_durable_snapshot(self):
        self.coordinator.change("size_percent", 150)
        self.timers.fire()
        self.complete_save(OSError("disk full"))

        self.assertEqual(self.store.get("size_percent"), 100)
        self.assertEqual(self.applied, [150, 100])
        self.assertEqual(self.statuses[-1][0], "error")

    def test_change_during_inflight_save_persists_latest_generation(self):
        self.coordinator.change("size_percent", 125)
        self.timers.fire()
        self.coordinator.change("size_percent", 150)
        self.timers.fire()

        self.complete_save()
        self.assertEqual(len(self.futures), 1)
        self.complete_save()

        self.assertEqual(SettingsStore(path=self.store.path).get("size_percent"), 150)
        self.assertEqual(self.statuses[-1], ("saved", None))

    def test_flush_persists_pending_change_without_waiting_for_debounce(self):
        self.coordinator.change("size_percent", 175)

        self.coordinator.flush()

        self.assertEqual(SettingsStore(path=self.store.path).get("size_percent"), 175)
        self.assertEqual(self.timers.sources, {})

    def test_close_flushes_pending_change(self):
        self.coordinator.change("size_percent", 200)

        self.coordinator.close()

        self.assertEqual(SettingsStore(path=self.store.path).get("size_percent"), 200)
        self.assertEqual(self.timers.sources, {})


if __name__ == "__main__":
    unittest.main()
