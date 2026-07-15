import unittest

from behavior_scheduler import BehaviorAdvanceScheduler
from pet_behavior import PetBehavior


class CountingBehavior(PetBehavior):
    def __init__(self):
        super().__init__()
        self.advance_count = 0
        self.snapshot_count = 0

    def advance(self, *, to):
        self.advance_count += 1
        return super().advance(to=to)

    def snapshot(self):
        self.snapshot_count += 1
        return super().snapshot()


class FakeTimers:
    def __init__(self):
        self.now = 0.0
        self.next_id = 1
        self.sources = {}

    def schedule(self, delay_ms, callback):
        source = self.next_id
        self.next_id += 1
        self.sources[source] = (delay_ms, callback)
        return source

    def cancel(self, source):
        self.sources.pop(source, None)

    def fire(self):
        source = next(iter(self.sources))
        delay_ms, callback = self.sources.pop(source)
        self.now += delay_ms / 1000
        callback()
        return delay_ms


class BehaviorSchedulerTests(unittest.TestCase):
    def make_scheduler(self, behavior=None):
        self.timers = FakeTimers()
        self.snapshots = []
        behavior = behavior or PetBehavior()
        scheduler = BehaviorAdvanceScheduler(
            behavior,
            lambda snapshot, force: self.snapshots.append((snapshot, force)),
            schedule_timeout=self.timers.schedule,
            cancel_timeout=self.timers.cancel,
            clock=lambda: self.timers.now,
        )
        return behavior, scheduler

    def test_sitting_has_no_scheduled_source(self):
        _behavior, scheduler = self.make_scheduler()
        scheduler.start()

        self.assertFalse(scheduler.scheduled)
        self.assertEqual(len(self.snapshots), 1)

    def test_tracking_expires_on_one_exact_deadline(self):
        behavior, scheduler = self.make_scheduler()
        scheduler.start()
        behavior.tracking_changed("north", at=0.0)
        scheduler.activity(at=0.0)

        self.assertEqual(next(iter(self.timers.sources.values()))[0], 180)
        self.timers.fire()

        self.assertEqual(behavior.snapshot().activity, "sitting")
        self.assertFalse(scheduler.scheduled)

    def test_typing_hold_uses_one_deadline(self):
        behavior, scheduler = self.make_scheduler(
            PetBehavior(typing_hold_seconds=2.0)
        )
        scheduler.start()
        behavior.typing_step(at=0.1)
        behavior.typing_held(True, at=0.1)
        behavior.typing_held(False, at=0.2)
        self.timers.now = 0.2
        scheduler.activity(at=0.2)

        self.assertEqual(next(iter(self.timers.sources.values()))[0], 2000)

    def test_moving_hearts_use_thirty_fps(self):
        behavior, scheduler = self.make_scheduler()
        scheduler.start()
        behavior.begin_interaction(
            target="petting", x=100, y=100, now=0.0, petting_width=40
        )
        behavior.move_interaction(x=112, y=100, inside_petting=True, now=0.1)
        behavior.move_interaction(x=100, y=100, inside_petting=True, now=0.2)
        self.timers.now = 0.2
        scheduler.activity(at=0.2)

        self.assertEqual(next(iter(self.timers.sources.values()))[0], 34)

    def test_reduced_motion_heart_has_no_frame_cadence(self):
        behavior, scheduler = self.make_scheduler(PetBehavior(reduced_motion=True))
        scheduler.start()
        behavior.begin_interaction(
            target="petting", x=100, y=100, now=0.0, petting_width=40
        )
        behavior.move_interaction(x=112, y=100, inside_petting=True, now=0.1)
        behavior.move_interaction(x=100, y=100, inside_petting=True, now=0.2)
        self.timers.now = 0.2
        scheduler.activity(at=0.2)

        self.assertFalse(scheduler.scheduled)

    def test_hidden_behavior_cancels_active_source(self):
        behavior, scheduler = self.make_scheduler(PetBehavior(typing_hold_seconds=2.0))
        scheduler.start()
        behavior.typing_step(at=0.1)
        behavior.typing_held(False, at=0.2)
        scheduler.activity(at=0.2)
        behavior.visibility_changed("user-pause", hidden=True, at=0.3)
        scheduler.activity(at=0.3)

        self.assertFalse(scheduler.scheduled)

    def test_delayed_activity_uses_current_clock_for_exact_expiry(self):
        behavior, scheduler = self.make_scheduler()
        scheduler.start()
        behavior.tracking_changed("north", at=1.0)
        self.timers.now = 1.2

        scheduler.activity(at=1.0)

        self.assertEqual(behavior.snapshot().activity, "sitting")
        self.assertFalse(scheduler.scheduled)

    def test_each_scheduler_wake_advances_and_snapshots_once(self):
        behavior = CountingBehavior()
        behavior, scheduler = self.make_scheduler(behavior)
        scheduler.start()
        behavior.tracking_changed("north", at=0.0)
        scheduler.activity(at=0.0)
        behavior.advance_count = 0
        behavior.snapshot_count = 0

        self.timers.fire()

        self.assertEqual(behavior.advance_count, 1)
        self.assertEqual(behavior.snapshot_count, 1)


if __name__ == "__main__":
    unittest.main()
