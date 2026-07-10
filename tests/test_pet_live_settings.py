import json
import unittest
from types import SimpleNamespace

import pet


class PetLiveSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open("assets/manifest.json", encoding="utf-8") as handle:
            cls.manifest = json.load(handle)

    def setUp(self):
        self.real_sheet = pet.Sheet

        def fake_sheet(definition):
            return SimpleNamespace(
                defn=definition,
                frames={
                    name: [None] * animation["frames"]
                    for name, animation in definition["anims"].items()
                },
                bboxes={},
                cw=definition["cellW"],
                ch=definition["cellH"],
                base_scale=definition.get("scale", 1),
                scale=definition.get("scale", 1),
            )

        pet.Sheet = fake_sheet
        self.mouse = SimpleNamespace(
            last_motion=0.0,
            vx=0.0,
            vy=0.0,
            moving=lambda: False,
            set_viewport=lambda _w, _h: None,
        )
        self.held = set()
        self.keyboard = SimpleNamespace(
            press_serial=0,
            last_press=0.0,
            last_release=0.0,
            any_held=lambda: bool(self.held),
        )

    def tearDown(self):
        pet.Sheet = self.real_sheet

    def make_pet(self, **overrides):
        settings = {
            "size_percent": 100,
            "pointer_tracking": True,
            "typing_reactions": True,
            "typing_hold_seconds": 2.0,
            "paused": False,
            "position": None,
        }
        settings.update(overrides)
        return pet.Pet(
            self.manifest, "catbone", self.mouse, self.keyboard, settings
        )

    def test_size_multiplier_stays_coupled_across_companion_sheets(self):
        companion = self.make_pet(size_percent=150)
        self.assertEqual(companion.sheet.scale, 2.25)
        self.assertEqual(companion.drag_sheet.scale, 2.25)
        self.assertEqual(companion.type_sheet.scale, 1.125)

    def test_saved_and_reset_positions(self):
        companion = self.make_pet(position={"x": 0.25, "y": 0.5})
        companion.set_viewport(1000, 800)
        self.assertEqual((companion.gx, companion.gy), (250, 400))
        companion.reset_position()
        self.assertEqual((companion.gx, companion.gy), (700, 640))

    def test_behavior_toggles_cancel_active_reactions(self):
        companion = self.make_pet()
        companion._typing_visible = True
        companion.set_typing_enabled(False)
        self.assertFalse(companion._typing_visible)
        companion.frame = 4
        companion.set_pointer_tracking(False)
        self.assertEqual(companion.frame, 0)


if __name__ == "__main__":
    unittest.main()
