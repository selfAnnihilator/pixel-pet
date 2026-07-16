import unittest

from companion_presentation import CompanionPresentation, SpriteMetrics
from pet_behavior import PetBehavior


class CompanionPresentationTests(unittest.TestCase):
    def setUp(self):
        bounds = {"track": tuple((8, 8, 56, 60) for _ in range(9))}
        self.sheets = {
            "base": SpriteMetrics(64, 64, 1.5, bounds),
            "drag": SpriteMetrics(
                128, 128, 1.5, {"drag": tuple((20, 20, 108, 120) for _ in range(4))}
            ),
            "type": SpriteMetrics(
                128, 128, 0.75, {"type": tuple((16, 16, 112, 120) for _ in range(4))}
            ),
            "pet": SpriteMetrics(
                64, 64, 1.5, {"pet": tuple((8, 8, 56, 60) for _ in range(3))}
            ),
            "hunt": SpriteMetrics(
                64,
                64,
                1.5,
                {
                    "hunt_front": tuple((7, 17, 56, 51) for _ in range(9)),
                    "hunt_transition": tuple((7, 17, 56, 51) for _ in range(5)),
                },
            ),
        }
        self.presentation = CompanionPresentation()

    def test_scale_and_viewport_conversion_policy_is_canonical(self):
        self.assertEqual(
            self.presentation.overlay_scale(base_scale=1.5, size_percent=150),
            2.25,
        )
        anchor = self.presentation.position_to_anchor((0.25, 0.5), (1000, 800))
        self.assertEqual(anchor, (250, 400))
        self.assertEqual(
            self.presentation.anchor_to_position(anchor, (1000, 800)),
            (0.25, 0.5),
        )

    def test_clamp_policy_keeps_sprite_inside_viewport(self):
        self.assertEqual(
            self.presentation.clamp_anchor(
                (0, 0),
                viewport=(1000, 800),
                metrics=self.sheets["base"],
            ),
            (48, 96),
        )

    def test_press_origin_classifies_head_and_body(self):
        behavior = PetBehavior(position=(0.5, 0.5))
        plan = self.presentation.overlay_plan(
            behavior.snapshot(), viewport=(1000, 800), sheets=self.sheets, size_percent=100
        )

        self.assertEqual(
            self.presentation.interaction_target(
                x=plan.sprite.x + plan.sprite.width * 0.5,
                y=plan.sprite.y + plan.sprite.height * 0.28,
                sprite=plan.sprite,
                petting_enabled=True,
            ),
            "petting",
        )
        self.assertEqual(
            self.presentation.interaction_target(
                x=plan.sprite.x + plan.sprite.width * 0.5,
                y=plan.sprite.y + plan.sprite.height * 0.75,
                sprite=plan.sprite,
                petting_enabled=True,
            ),
            "drag",
        )

    def test_disabled_petting_makes_head_draggable(self):
        behavior = PetBehavior(position=(0.5, 0.5))
        plan = self.presentation.overlay_plan(
            behavior.snapshot(), viewport=(1000, 800), sheets=self.sheets, size_percent=100
        )

        self.assertEqual(
            self.presentation.interaction_target(
                x=plan.sprite.x + plan.sprite.width * 0.5,
                y=plan.sprite.y + plan.sprite.height * 0.28,
                sprite=plan.sprite,
                petting_enabled=False,
            ),
            "drag",
        )

    def test_semantic_behavior_snapshot_selects_sprite_frame(self):
        behavior = PetBehavior()
        behavior.typing_step(at=0.1)
        behavior.typing_held(True, at=0.1)
        typing = self.presentation.overlay_plan(
            behavior.snapshot(), viewport=(1000, 800), sheets=self.sheets, size_percent=100
        ).sprite
        self.assertEqual(
            (typing.sheet, typing.state, typing.frame),
            ("type", "type", 1),
        )

        behavior.typing_reactions_changed(False, at=0.2)
        behavior.tracking_changed("northwest", at=0.3)
        tracking = self.presentation.overlay_plan(
            behavior.snapshot(), viewport=(1000, 800), sheets=self.sheets, size_percent=100
        ).sprite
        self.assertEqual(
            (tracking.sheet, tracking.state, tracking.frame),
            ("base", "track", 8),
        )

    def test_pointer_vector_classifies_semantic_tracking_direction(self):
        self.assertEqual(
            self.presentation.tracking_direction(dx=0, dy=-100, deadzone=24),
            "north",
        )
        self.assertEqual(
            self.presentation.tracking_direction(dx=-100, dy=100, deadzone=24),
            "southwest",
        )
        self.assertIsNone(
            self.presentation.tracking_direction(dx=5, dy=5, deadzone=24)
        )

    def test_mouse_hunt_selects_front_sheet_and_gaze_frame(self):
        behavior = PetBehavior()
        behavior.pointer_moved("east", horizontal_delta=1.1, at=0.0)
        behavior.pointer_moved("west", horizontal_delta=-1.1, at=0.1)
        behavior.pointer_moved("east", horizontal_delta=1.1, at=0.2)
        behavior.advance(to=0.4)

        sprite = self.presentation.overlay_plan(
            behavior.snapshot(), viewport=(1000, 800), sheets=self.sheets, size_percent=100
        ).sprite

        self.assertEqual(
            (sprite.sheet, sprite.state, sprite.frame),
            ("hunt", "hunt_front", 3),
        )

    def test_mouse_hunt_selects_front_sprite_for_above_cursor(self):
        behavior = PetBehavior()
        behavior.pointer_moved("east", horizontal_delta=1.1, at=0.0)
        behavior.pointer_moved("west", horizontal_delta=-1.1, at=0.1)
        behavior.pointer_moved("east", horizontal_delta=1.1, at=0.2)
        behavior.advance(to=0.4)
        behavior.pointer_moved("northwest", horizontal_delta=0.0, at=0.41)

        sprite = self.presentation.overlay_plan(
            behavior.snapshot(), viewport=(1000, 800), sheets=self.sheets, size_percent=100
        ).sprite

        self.assertEqual(
            (sprite.sheet, sprite.state, sprite.frame),
            ("hunt", "hunt_front", 8),
        )

    def test_overlay_plan_clamps_active_sprite_and_builds_input_region(self):
        behavior = PetBehavior(position=(0.0, 0.0))
        behavior.set_dragging(True, now=0.0)

        plan = self.presentation.overlay_plan(
            behavior.snapshot(), viewport=(1000, 800), sheets=self.sheets, size_percent=100
        )

        self.assertEqual((plan.sprite.x, plan.sprite.y), (0, 0))
        self.assertEqual(plan.input_region.x, 30)
        self.assertEqual(plan.input_region.y, 30)

    def test_preview_plan_centers_sprite_with_size_policy(self):
        behavior = PetBehavior()

        plan = self.presentation.preview_plan(
            behavior.snapshot(), viewport=(240, 270), sheets=self.sheets, size_percent=100
        )

        self.assertEqual(plan.sprite.width, 140.0)
        self.assertEqual(plan.sprite.height, 140.0)
        self.assertEqual((plan.sprite.x, plan.sprite.y), (50, 65))
        self.assertIsNone(plan.input_region)


if __name__ == "__main__":
    unittest.main()
