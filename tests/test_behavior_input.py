import os
import struct
import unittest

from behavior_input import (
    EvdevBehaviorActivityAdapter,
    PointerMotion,
    TypingHeld,
    TypingStep,
)


def event(event_type, code, value):
    return struct.pack("llHHi", 0, 0, event_type, code, value)


class BehaviorInputTests(unittest.TestCase):
    def make_adapter(self):
        self.deliveries = []
        self.dispatched = []
        adapter = EvdevBehaviorActivityAdapter(
            self.deliveries.append,
            dispatch=self.dispatched.append,
            pointer_paths=lambda: [],
            keyboard_paths=lambda: [],
        )
        adapter.set_viewport(1000, 800)
        return adapter

    def flush(self):
        while self.dispatched:
            self.dispatched.pop(0)()

    def test_pointer_motion_is_integrated_and_coalesced(self):
        adapter = self.make_adapter()
        adapter.consume_pointer_bytes(
            event(adapter.EV_REL, adapter.REL_X, 5), at=1.0
        )
        adapter.consume_pointer_bytes(
            event(adapter.EV_REL, adapter.REL_Y, -7), at=1.1
        )

        self.flush()

        self.assertEqual(self.deliveries, [PointerMotion(505.0, 393.0, 1.1)])
        adapter.close()

    def test_keyboard_preserves_steps_and_combines_held_state(self):
        adapter = self.make_adapter()
        payload = b"".join(
            [
                event(adapter.EV_KEY, 30, 1),
                event(adapter.EV_KEY, 30, 2),
                event(adapter.EV_KEY, 31, 1),
                event(adapter.EV_KEY, 30, 0),
                event(adapter.EV_KEY, 31, 0),
            ]
        )

        adapter.consume_keyboard_bytes(payload, at=2.0)
        self.flush()

        self.assertEqual(
            self.deliveries,
            [
                TypingStep(2.0),
                TypingHeld(True, 2.0),
                TypingStep(2.0),
                TypingHeld(False, 2.0),
            ],
        )
        adapter.close()

    def test_disabled_observation_keeps_no_device_descriptors(self):
        read_fd, write_fd = os.pipe()
        path = f"/proc/self/fd/{read_fd}"
        adapter = EvdevBehaviorActivityAdapter(
            lambda _observation: None,
            pointer_paths=lambda: [path],
            keyboard_paths=lambda: [],
        )
        adapter.configure(pointer_enabled=False, typing_enabled=False)

        self.assertTrue(adapter.pointer_available)
        self.assertEqual(adapter._fds, {})

        adapter.close()
        os.close(read_fd)
        os.close(write_fd)

    def test_stop_discards_late_observations(self):
        adapter = self.make_adapter()
        adapter.stop()
        adapter.consume_keyboard_bytes(event(adapter.EV_KEY, 30, 1), at=3.0)
        self.flush()

        self.assertEqual(self.deliveries, [])
        adapter.close()


if __name__ == "__main__":
    unittest.main()
