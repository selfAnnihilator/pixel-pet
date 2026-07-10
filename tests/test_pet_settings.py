import os
import tempfile
import unittest

import pet_settings


class SettingsStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous_config = os.environ.get("XDG_CONFIG_HOME")
        os.environ["XDG_CONFIG_HOME"] = self.temp.name

    def tearDown(self):
        if self.previous_config is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = self.previous_config
        self.temp.cleanup()

    def test_normalizes_and_persists_live_settings(self):
        store = pet_settings.SettingsStore()
        self.assertTrue(store.first_run)
        self.assertEqual(store.update("size_percent", 138), 150)
        self.assertEqual(store.update("typing_hold_seconds", 9), 5)
        self.assertEqual(
            store.update("position", {"x": 1.2, "y": -0.2}),
            {"x": 1.0, "y": 0.0},
        )
        self.assertEqual(pet_settings.SettingsStore().data, store.data)

    def test_failed_write_rolls_back_memory(self):
        store = pet_settings.SettingsStore()
        store.save()
        previous = dict(store.data)
        store.path = "/proc/pixel-pet/settings.json"
        with self.assertRaises(OSError):
            store.update("size_percent", 200)
        self.assertEqual(store.data, previous)

    def test_autostart_entry_is_owned_and_reversible(self):
        pet_settings.set_launch_at_login(True, "/tmp/Pixel Pet/run-pet.sh")
        with open(pet_settings.autostart_path(), encoding="utf-8") as handle:
            entry = handle.read()
        self.assertIn('Exec="/tmp/Pixel Pet/run-pet.sh" --background', entry)
        pet_settings.set_launch_at_login(False, "ignored")
        self.assertFalse(os.path.exists(pet_settings.autostart_path()))


if __name__ == "__main__":
    unittest.main()
