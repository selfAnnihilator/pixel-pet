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
            "petting_reactions": True,
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
        self.assertEqual(companion.pet_sheet.scale, 2.25)

    def test_petting_reactions_can_be_disabled_live(self):
        companion = self.make_pet()
        self.assertTrue(companion.behavior.snapshot().petting_reactions)
        companion.set_petting_enabled(False)
        self.assertFalse(companion.behavior.snapshot().petting_reactions)

    def test_disabling_petting_cancels_an_active_reaction(self):
        companion = self.make_pet()
        companion.set_viewport(1000, 800)
        companion.begin_pointer_interaction(700, 571, 0.0)
        companion.move_pointer_interaction(715, 571, 0.1)
        companion.move_pointer_interaction(700, 571, 0.2)

        companion.set_petting_enabled(False)
        self.assertEqual(companion.behavior.snapshot().activity, "sitting")

    def test_head_press_arms_petting_while_body_press_starts_drag(self):
        companion = self.make_pet()
        companion.set_viewport(1000, 800)

        self.assertEqual(companion.begin_pointer_interaction(700, 571, 0.0), "petting")
        self.assertNotEqual(companion.behavior.snapshot().activity, "dragging")
        companion.end_pointer_interaction(0.1)

        self.assertEqual(companion.begin_pointer_interaction(700, 616, 0.2), "drag")
        self.assertEqual(companion.behavior.snapshot().activity, "dragging")

    def test_head_rub_drives_petting_pose_without_moving_pet(self):
        companion = self.make_pet()
        companion.set_viewport(1000, 800)
        original_position = (companion.gx, companion.gy)
        companion.begin_pointer_interaction(700, 571, 0.0)
        companion.move_pointer_interaction(715, 571, 0.1)
        companion.move_pointer_interaction(700, 571, 0.2)

        snapshot = companion.behavior.snapshot()
        self.assertEqual(snapshot.pose, "petting")
        self.assertEqual((companion.gx, companion.gy), original_position)

    def test_held_typing_takes_over_when_petting_is_released(self):
        companion = self.make_pet()
        companion.set_viewport(1000, 800)
        companion.begin_pointer_interaction(700, 571, 0.0)
        companion.move_pointer_interaction(715, 571, 0.1)
        companion.move_pointer_interaction(700, 571, 0.2)
        companion.behavior.typing_step(at=0.25)
        companion.behavior.typing_held(True, at=0.25)

        self.assertEqual(companion.behavior.snapshot().activity, "petting")
        companion.end_pointer_interaction(0.3)
        self.assertEqual(companion.behavior.snapshot().activity, "typing")

    def test_petting_hold_stays_above_pointer_tracking_until_expiry(self):
        companion = self.make_pet()
        companion.set_viewport(1000, 800)
        companion.begin_pointer_interaction(700, 571, 0.0)
        companion.move_pointer_interaction(715, 571, 0.1)
        companion.move_pointer_interaction(700, 571, 0.2)
        companion.end_pointer_interaction(0.3)
        companion.tracker.moving = lambda: True

        snapshot = companion.behavior.snapshot()
        self.assertEqual((snapshot.activity, snapshot.variant), ("petting_hold", "relaxed"))

    def test_saved_and_reset_positions(self):
        companion = self.make_pet(position={"x": 0.25, "y": 0.5})
        companion.set_viewport(1000, 800)
        self.assertEqual((companion.gx, companion.gy), (250, 400))
        self.assertEqual(companion.behavior.snapshot().position, (0.25, 0.5))
        companion.reset_position()
        self.assertEqual((companion.gx, companion.gy), (700, 640))
        self.assertEqual(companion.behavior.snapshot().position, (0.7, 0.8))

    def test_behavior_toggles_cancel_active_reactions(self):
        companion = self.make_pet()
        companion.behavior.typing_step(at=0.1)
        companion.behavior.typing_held(True, at=0.1)
        companion.set_typing_enabled(False)
        self.assertEqual(companion.behavior.snapshot().activity, "sitting")
        companion.behavior.tracking_changed("southeast", at=0.2)
        companion.set_pointer_tracking(False)
        self.assertEqual(companion.behavior.snapshot().activity, "sitting")

    def test_keyboard_observation_drives_behavior_snapshot(self):
        companion = self.make_pet(typing_hold_seconds=2.0)
        self.keyboard.press_serial = 1
        self.held.add(30)
        companion.update(0.0, now=0.1)
        self.assertEqual(companion.behavior.snapshot().variant, "left")

        self.keyboard.press_serial = 2
        companion.update(0.0, now=0.2)
        self.assertEqual(companion.behavior.snapshot().variant, "right")

        self.held.clear()
        self.keyboard.last_release = 0.3
        companion.update(0.0, now=0.3)
        self.assertEqual(companion.behavior.snapshot().activity, "typing_hold")

        companion.update(0.0, now=2.3)
        self.assertEqual(companion.behavior.snapshot().activity, "sitting")

    def test_pointer_observation_drives_semantic_tracking_pose(self):
        companion = self.make_pet()
        companion.set_viewport(1000, 800)
        companion.tracker.vx = 700
        companion.tracker.vy = 400
        companion.tracker.moving = lambda: True

        companion.update(0.0, now=0.1)
        snapshot = companion.behavior.snapshot()
        self.assertEqual(
            (snapshot.activity, snapshot.pose, snapshot.variant),
            ("tracking", "tracking", "north"),
        )

        companion.tracker.moving = lambda: False
        companion.update(0.0, now=0.2)
        self.assertEqual(companion.behavior.snapshot().activity, "sitting")

    def test_pause_and_fullscreen_are_independent_hiding_reasons(self):
        companion = self.make_pet()
        companion.set_user_paused(True)
        companion.set_fullscreen_paused(True)
        companion.set_user_paused(False)
        self.assertFalse(companion.behavior.snapshot().visible)

        companion.set_fullscreen_paused(False)
        self.assertTrue(companion.behavior.snapshot().visible)


if __name__ == "__main__":
    unittest.main()
