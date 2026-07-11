import unittest

from pet_behavior import PetBehavior
from sprite_presentation import SpritePresentation


class SpritePresentationTests(unittest.TestCase):
    def test_press_origin_classifies_head_and_body(self):
        presentation = SpritePresentation()

        self.assertEqual(
            presentation.interaction_target(x=0.5, y=0.28, petting_enabled=True),
            "petting",
        )
        self.assertEqual(
            presentation.interaction_target(x=0.5, y=0.75, petting_enabled=True),
            "drag",
        )

    def test_disabled_petting_makes_head_draggable(self):
        presentation = SpritePresentation()

        self.assertEqual(
            presentation.interaction_target(x=0.5, y=0.28, petting_enabled=False),
            "drag",
        )

    def test_semantic_behavior_snapshot_selects_sprite_frame(self):
        presentation = SpritePresentation()
        behavior = PetBehavior()
        behavior.typing_step(at=0.1)
        behavior.typing_held(True, at=0.1)
        typing = presentation.selection_for(behavior.snapshot())
        self.assertEqual(
            (typing.sheet, typing.state, typing.frame),
            ("type", "type", 1),
        )

        behavior.typing_reactions_changed(False, at=0.2)
        behavior.tracking_changed("northwest", at=0.3)
        tracking = presentation.selection_for(behavior.snapshot())
        self.assertEqual(
            (tracking.sheet, tracking.state, tracking.frame),
            ("base", "track", 8),
        )

    def test_pointer_vector_classifies_semantic_tracking_direction(self):
        presentation = SpritePresentation()
        self.assertEqual(
            presentation.tracking_direction(dx=0, dy=-100, deadzone=24),
            "north",
        )
        self.assertEqual(
            presentation.tracking_direction(dx=-100, dy=100, deadzone=24),
            "southwest",
        )
        self.assertIsNone(
            presentation.tracking_direction(dx=5, dy=5, deadzone=24)
        )


if __name__ == "__main__":
    unittest.main()
