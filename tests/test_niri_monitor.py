import json
import unittest
from unittest.mock import patch

from niri_monitor import NiriFullscreenMonitor, NiriState


class NiriStateTests(unittest.TestCase):
    def setUp(self):
        self.state = NiriState()
        self.state.apply(
            {
                "OutputsChanged": {
                    "outputs": {
                        "eDP-1": {"logical": {"width": 1920, "height": 1080}},
                        "HDMI-A-1": {"logical": {"width": 2560, "height": 1440}},
                    }
                }
            }
        )
        self.state.apply(
            {
                "WorkspacesChanged": {
                    "workspaces": [
                        {"id": 1, "output": "eDP-1"},
                        {"id": 2, "output": "HDMI-A-1"},
                    ]
                }
            }
        )

    def test_focused_window_is_compared_with_its_own_output(self):
        fullscreen = self.state.apply(
            {
                "WindowsChanged": {
                    "windows": [
                        {
                            "id": 7,
                            "workspace_id": 1,
                            "is_focused": True,
                            "layout": {"window_size": [1920, 1080]},
                        },
                        {
                            "id": 8,
                            "workspace_id": 2,
                            "is_focused": False,
                            "layout": {"window_size": [2560, 1440]},
                        },
                    ]
                }
            }
        )

        self.assertTrue(fullscreen)

    def test_focus_and_layout_changes_recompute_fullscreen(self):
        self.state.apply(
            {
                "WindowsChanged": {
                    "windows": [
                        {
                            "id": 7,
                            "workspace_id": 1,
                            "is_focused": True,
                            "layout": {"window_size": [1920, 1080]},
                        },
                        {
                            "id": 8,
                            "workspace_id": 2,
                            "is_focused": False,
                            "layout": {"window_size": [1200, 900]},
                        },
                    ]
                }
            }
        )

        self.assertFalse(self.state.apply({"WindowFocusChanged": {"id": 8}}))
        self.assertTrue(
            self.state.apply(
                {
                    "WindowOpenedOrChanged": {
                        "window": {
                            "id": 8,
                            "workspace_id": 2,
                            "is_focused": True,
                            "layout": {"window_size": [2560, 1440]},
                        }
                    }
                }
            )
        )

    def test_window_layout_updates_use_visual_tile_size(self):
        self.state.apply(
            {
                "WindowsChanged": {
                    "windows": [
                        {
                            "id": 7,
                            "workspace_id": 1,
                            "is_focused": True,
                            "layout": {
                                "tile_size": [1920.0, 1080.0],
                                "window_size": [1280, 720],
                            },
                        }
                    ]
                }
            }
        )
        self.assertTrue(self.state.is_fullscreen())

        self.assertFalse(
            self.state.apply(
                {
                    "WindowLayoutsChanged": {
                        "changes": [
                            [
                                7,
                                {
                                    "tile_size": [1200.0, 900.0],
                                    "window_size": [1200, 900],
                                },
                            ]
                        ]
                    }
                }
            )
        )

    def test_unknown_event_does_not_change_state(self):
        self.assertIsNone(self.state.apply({"FutureEvent": {"value": 1}}))

    def test_window_without_output_mapping_is_not_guessed_fullscreen(self):
        self.assertFalse(
            self.state.apply(
                {
                    "WindowsChanged": {
                        "windows": [
                            {
                                "id": 9,
                                "workspace_id": 99,
                                "is_focused": True,
                                "layout": {"window_size": [2560, 1440]},
                            }
                        ]
                    }
                }
            )
        )


class NiriMonitorTests(unittest.TestCase):
    class FakeProcess:
        def __init__(self, lines):
            self.stdout = iter(lines)
            self.terminated = False

        def wait(self, timeout=None):
            del timeout
            return 0

        def poll(self):
            return 0

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.terminated = True

    def test_malformed_and_unknown_lines_are_ignored(self):
        emitted = []
        monitor = NiriFullscreenMonitor(
            emitted.append,
            dispatch=lambda callback: callback(),
            schedule_retry=lambda _delay, _callback: 1,
            cancel_retry=lambda _source: None,
        )

        self.assertIsNone(monitor.consume_line("not json"))
        self.assertIsNone(monitor.consume_line(json.dumps({"FutureEvent": {}})))
        self.assertEqual(emitted, [])

    def test_initial_stream_state_emits_only_visibility_changes(self):
        emitted = []
        monitor = NiriFullscreenMonitor(
            emitted.append,
            dispatch=lambda callback: callback(),
            schedule_retry=lambda _delay, _callback: 1,
            cancel_retry=lambda _source: None,
        )
        lines = [
            {"OutputsChanged": {"outputs": {"eDP-1": {"logical": {"width": 1920, "height": 1080}}}}},
            {"WorkspacesChanged": {"workspaces": [{"id": 1, "output": "eDP-1"}]}},
            {"WindowsChanged": {"windows": [{"id": 2, "workspace_id": 1, "is_focused": True, "layout": {"window_size": [1920, 1080]}}]}},
            {"WindowFocusChanged": {"id": 2}},
        ]

        for line in lines:
            monitor.consume_line(json.dumps(line))

        self.assertEqual(emitted, [False, True])

    def test_output_cache_is_loaded_before_real_initial_stream_events(self):
        emitted = []
        process = self.FakeProcess(
            [
                json.dumps(
                    {
                        "WorkspacesChanged": {
                            "workspaces": [{"id": 1, "output": "eDP-1"}]
                        }
                    }
                ),
                json.dumps(
                    {
                        "WindowsChanged": {
                            "windows": [
                                {
                                    "id": 2,
                                    "workspace_id": 1,
                                    "is_focused": True,
                                    "layout": {
                                        "tile_size": [1920.0, 1080.0],
                                        "window_size": [1280, 720],
                                    },
                                }
                            ]
                        }
                    }
                ),
            ]
        )
        monitor = NiriFullscreenMonitor(
            emitted.append,
            dispatch=lambda callback: callback(),
            schedule_retry=lambda _delay, _callback: 1,
            cancel_retry=lambda _source: None,
            popen=lambda *_args, **_kwargs: process,
            load_outputs=lambda: {
                "eDP-1": {"logical": {"width": 1920, "height": 1080}}
            },
        )

        with patch("niri_monitor.shutil.which", return_value="/usr/bin/niri"):
            monitor.start()
            monitor._thread.join(timeout=1.0)

        self.assertEqual(emitted, [False, True, False])
        monitor.stop()

    def test_failed_streams_restart_with_capped_backoff_and_stop_cleanly(self):
        emitted = []
        retries = []
        cancelled = []

        def schedule(delay, callback):
            retries.append((delay, callback))
            return len(retries)

        monitor = NiriFullscreenMonitor(
            emitted.append,
            dispatch=lambda callback: callback(),
            schedule_retry=schedule,
            cancel_retry=cancelled.append,
            popen=lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError()),
            load_outputs=lambda: {},
        )
        monitor._last_fullscreen = True

        with patch("niri_monitor.shutil.which", return_value="/usr/bin/niri"):
            monitor.start()
            monitor._thread.join(timeout=1.0)
            for _ in range(5):
                retries[-1][1]()
                monitor._thread.join(timeout=1.0)

        self.assertEqual(
            [delay for delay, _callback in retries],
            [1000, 2000, 5000, 10000, 30000, 30000],
        )
        self.assertEqual(emitted, [False])

        monitor.stop()
        self.assertEqual(cancelled, [6])


if __name__ == "__main__":
    unittest.main()
