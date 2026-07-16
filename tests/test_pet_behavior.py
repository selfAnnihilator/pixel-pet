import unittest

from pet_behavior import PetBehavior


class PetBehaviorTests(unittest.TestCase):
    @staticmethod
    def trigger_mouse_hunt(behavior, *, start=0.0):
        behavior.pointer_moved("east", horizontal_delta=1.1, at=start)
        behavior.pointer_moved("west", horizontal_delta=-1.1, at=start + 0.1)
        behavior.pointer_moved("east", horizontal_delta=1.1, at=start + 0.2)

    def test_snapshot_is_pure_and_only_advance_changes_timed_state(self):
        behavior = PetBehavior()
        behavior.begin_interaction(
            target="petting", x=100, y=100, now=0.0, petting_width=40,
        )
        behavior.move_interaction(x=112, y=100, inside_petting=True, now=0.1)
        behavior.move_interaction(x=100, y=100, inside_petting=True, now=0.2)

        first = behavior.snapshot()
        second = behavior.snapshot()
        self.assertEqual(first, second)
        self.assertEqual(len(second.hearts), 1)

        behavior.advance(to=0.5)
        self.assertEqual(len(behavior.snapshot().hearts), 2)

    def test_typing_activity_alternates_paws_and_enters_typing_hold(self):
        behavior = PetBehavior(typing_hold_seconds=2.0)

        behavior.typing_step(at=0.1)
        behavior.typing_held(True, at=0.1)
        self.assertEqual(behavior.snapshot().variant, "left")

        behavior.typing_step(at=0.2)
        self.assertEqual(behavior.snapshot().variant, "right")

        behavior.typing_held(False, at=0.3)
        held = behavior.snapshot()
        self.assertEqual((held.activity, held.pose), ("typing_hold", "typing"))
        self.assertEqual(held.variant, "ready")

        behavior.advance(to=2.3)
        self.assertEqual(behavior.snapshot().activity, "sitting")

    def test_disabling_typing_reactions_consumes_typing_state(self):
        behavior = PetBehavior()
        behavior.typing_step(at=0.1)
        behavior.typing_held(True, at=0.1)
        self.assertEqual(behavior.snapshot().activity, "typing")

        behavior.typing_reactions_changed(False, at=0.2)
        self.assertEqual(behavior.snapshot().activity, "sitting")
        behavior.typing_step(at=0.3)
        self.assertEqual(behavior.snapshot().activity, "sitting")

    def test_typing_activity_discards_earlier_tracking_instead_of_queueing_it(self):
        behavior = PetBehavior(typing_hold_seconds=2.0)
        behavior.tracking_changed("northwest", at=0.1)
        tracking = behavior.snapshot()
        self.assertEqual(
            (tracking.activity, tracking.pose, tracking.variant),
            ("tracking", "tracking", "northwest"),
        )

        behavior.typing_step(at=0.2)
        behavior.typing_held(True, at=0.2)
        self.assertEqual(behavior.snapshot().activity, "typing")

        behavior.typing_held(False, at=0.3)
        self.assertEqual(behavior.snapshot().activity, "typing_hold")

    def test_tracking_pose_expires_after_pointer_activity_window(self):
        behavior = PetBehavior(tracking_hold_seconds=0.18)
        behavior.tracking_changed("east", at=1.0)

        behavior.advance(to=1.179)
        self.assertEqual(behavior.snapshot().activity, "tracking")
        behavior.advance(to=1.18)
        self.assertEqual(behavior.snapshot().activity, "sitting")

    def test_disabling_tracking_consumes_tracking_pose(self):
        behavior = PetBehavior()
        behavior.tracking_changed("east", at=0.1)
        behavior.tracking_enabled_changed(False, at=0.2)
        self.assertEqual(behavior.snapshot().activity, "sitting")

        behavior.tracking_changed("west", at=0.3)
        self.assertEqual(behavior.snapshot().activity, "sitting")

    def test_two_fast_full_width_reversals_trigger_mouse_hunt(self):
        behavior = PetBehavior(position=(0.4, 0.7))
        self.trigger_mouse_hunt(behavior)

        entering = behavior.snapshot()
        self.assertEqual(
            (entering.activity, entering.pose, entering.variant),
            ("mouse_hunt_transition", "hunting", "transition_0"),
        )
        self.assertEqual(entering.position, (0.4, 0.7))
        behavior.advance(to=0.4)
        hunting = behavior.snapshot()
        self.assertEqual(hunting.activity, "mouse_hunt")
        self.assertEqual(hunting.pose, "hunting")
        self.assertTrue(hunting.variant.endswith("_east"))
        self.assertEqual(hunting.position, (0.4, 0.7))

    def test_mouse_hunt_rejects_short_or_slow_shakes(self):
        short = PetBehavior()
        short.pointer_moved("east", horizontal_delta=0.8, at=0.0)
        short.pointer_moved("west", horizontal_delta=-0.8, at=0.1)
        short.pointer_moved("east", horizontal_delta=0.8, at=0.2)
        self.assertNotEqual(short.snapshot().activity, "mouse_hunt_transition")

        slow = PetBehavior()
        slow.pointer_moved("east", horizontal_delta=1.1, at=0.0)
        slow.pointer_moved("west", horizontal_delta=-1.1, at=0.2)
        slow.pointer_moved("east", horizontal_delta=1.1, at=0.31)
        self.assertNotEqual(slow.snapshot().activity, "mouse_hunt_transition")

    def test_mouse_hunt_gaze_tracks_vertically_without_moving_anchor(self):
        behavior = PetBehavior(position=(0.25, 0.75))
        self.trigger_mouse_hunt(behavior)
        behavior.advance(to=0.4)
        behavior.pointer_moved("north", horizontal_delta=0.0, at=0.41)

        snapshot = behavior.snapshot()
        self.assertEqual(snapshot.variant, "front_north")
        self.assertEqual(snapshot.position, (0.25, 0.75))

    def test_mouse_hunt_uses_its_front_model_for_every_gaze(self):
        behavior = PetBehavior()
        self.trigger_mouse_hunt(behavior)
        behavior.advance(to=0.4)

        for direction in (
            "north",
            "northeast",
            "east",
            "southeast",
            "south",
            "southwest",
            "west",
            "northwest",
        ):
            behavior.pointer_moved(direction, horizontal_delta=0.0, at=0.41)
            self.assertEqual(behavior.snapshot().variant, f"front_{direction}")

    def test_mouse_hunt_tracks_with_iris_frames_without_a_body_sway_timer(self):
        behavior = PetBehavior()
        self.trigger_mouse_hunt(behavior)
        behavior.advance(to=0.4)

        behavior.pointer_moved("west", horizontal_delta=0.0, at=0.41)
        self.assertEqual(behavior.snapshot().variant, "front_west")
        behavior.pointer_moved("east", horizontal_delta=0.0, at=0.42)
        self.assertEqual(behavior.snapshot().variant, "front_east")
        self.assertIsNone(behavior.schedule().frame_interval)

    def test_mouse_hunt_holds_then_rises_and_can_reverse_rise(self):
        behavior = PetBehavior()
        self.trigger_mouse_hunt(behavior)
        behavior.advance(to=0.601)
        self.assertEqual(behavior.snapshot().variant, "transition_2")
        behavior.advance(to=0.7)
        self.assertEqual(behavior.snapshot().activity, "mouse_hunt_transition")

        behavior.pointer_moved("west", horizontal_delta=-1.1, at=0.71)
        behavior.pointer_moved("east", horizontal_delta=1.1, at=0.76)
        behavior.pointer_moved("west", horizontal_delta=-1.1, at=0.81)
        self.assertEqual(behavior.snapshot().variant, "transition_1")

        behavior.advance(to=1.01)
        self.assertEqual(behavior.snapshot().activity, "mouse_hunt")

    def test_reduced_motion_suppresses_tracking_and_mouse_hunt(self):
        behavior = PetBehavior(reduced_motion=True)
        self.trigger_mouse_hunt(behavior)
        self.assertEqual(behavior.snapshot().activity, "sitting")

        behavior.reduced_motion_changed(False, at=0.3)
        self.trigger_mouse_hunt(behavior, start=0.4)
        self.assertEqual(behavior.snapshot().activity, "mouse_hunt_transition")
        behavior.reduced_motion_changed(True, at=0.7)
        self.assertEqual(behavior.snapshot().activity, "sitting")

    def test_typing_interrupts_mouse_hunt_instead_of_queueing_it(self):
        behavior = PetBehavior()
        self.trigger_mouse_hunt(behavior)
        behavior.typing_step(at=0.25)
        self.assertEqual(behavior.snapshot().activity, "typing")
        behavior.typing_held(False, at=0.3)
        self.assertEqual(behavior.snapshot().activity, "typing_hold")

    def test_deliberate_head_rub_activates_petting_pose(self):
        behavior = PetBehavior()

        behavior.begin_interaction(
            target="petting",
            x=100,
            y=100,
            now=0.0,
            petting_width=40,
        )
        behavior.move_interaction(x=112, y=100, inside_petting=True, now=0.1)
        behavior.move_interaction(x=100, y=100, inside_petting=True, now=0.2)

        snapshot = behavior.snapshot()
        self.assertEqual(snapshot.pose, "petting")
        self.assertEqual(snapshot.variant, "left")
        self.assertEqual(len(snapshot.hearts), 1)

    def test_head_press_released_before_a_stroke_has_no_reaction(self):
        behavior = PetBehavior()
        behavior.begin_interaction(
            target="petting", x=100, y=100, now=0.0, petting_width=40,
        )
        behavior.move_interaction(x=103, y=100, inside_petting=True, now=0.1)
        behavior.end_interaction(now=0.2)

        snapshot = behavior.snapshot()
        self.assertEqual(snapshot.pose, "sitting")
        self.assertEqual(snapshot.variant, "forward")
        self.assertEqual(snapshot.hearts, ())

    def test_active_petting_emits_at_most_three_hearts_every_300ms(self):
        behavior = PetBehavior()
        behavior.begin_interaction(
            target="petting", x=100, y=100, now=0.0, petting_width=40,
        )
        behavior.move_interaction(x=112, y=100, inside_petting=True, now=0.1)
        behavior.move_interaction(x=100, y=100, inside_petting=True, now=0.2)

        behavior.advance(to=0.49)
        self.assertEqual(len(behavior.snapshot().hearts), 1)
        behavior.advance(to=0.50)
        self.assertEqual(len(behavior.snapshot().hearts), 2)
        behavior.advance(to=0.80)
        self.assertEqual(len(behavior.snapshot().hearts), 3)
        behavior.advance(to=1.10)
        self.assertEqual(len(behavior.snapshot().hearts), 3)

    def test_heart_snapshot_exposes_progress_without_internal_clock(self):
        behavior = PetBehavior()
        behavior.begin_interaction(
            target="petting", x=100, y=100, now=0.0, petting_width=40,
        )
        behavior.move_interaction(x=112, y=100, inside_petting=True, now=0.1)
        behavior.move_interaction(x=100, y=100, inside_petting=True, now=0.2)
        behavior.advance(to=0.65)

        heart = behavior.snapshot().hearts[0]
        self.assertAlmostEqual(heart.progress, 0.5)
        self.assertIn(heart.drift, (-1, 0, 1))
        self.assertFalse(heart.static)
        self.assertFalse(hasattr(heart, "born_at"))

    def test_releasing_active_petting_holds_relaxed_pose_for_600ms(self):
        behavior = PetBehavior()
        behavior.begin_interaction(
            target="petting", x=100, y=100, now=0.0, petting_width=40,
        )
        behavior.move_interaction(x=112, y=100, inside_petting=True, now=0.1)
        behavior.move_interaction(x=100, y=100, inside_petting=True, now=0.2)
        behavior.end_interaction(now=0.3)

        behavior.advance(to=0.89)
        held = behavior.snapshot()
        self.assertEqual((held.pose, held.variant), ("petting", "relaxed"))
        self.assertEqual(len(held.hearts), 1)

        behavior.advance(to=0.90)
        settled = behavior.snapshot()
        self.assertEqual((settled.pose, settled.variant), ("sitting", "forward"))

    def test_held_typing_appears_immediately_after_petting_release(self):
        behavior = PetBehavior()
        behavior.begin_interaction(
            target="petting", x=100, y=100, now=0.0, petting_width=40,
        )
        behavior.move_interaction(x=112, y=100, inside_petting=True, now=0.1)
        behavior.move_interaction(x=100, y=100, inside_petting=True, now=0.2)
        behavior.typing_step(at=0.24)
        behavior.typing_step(at=0.25)
        behavior.typing_held(True, at=0.25)
        self.assertEqual(behavior.snapshot().pose, "petting")

        behavior.end_interaction(now=0.3)
        snapshot = behavior.snapshot()
        self.assertEqual((snapshot.pose, snapshot.variant), ("typing", "right"))

    def test_typing_activity_consumes_petting_hold_permanently(self):
        behavior = PetBehavior()
        behavior.begin_interaction(
            target="petting", x=100, y=100, now=0.0, petting_width=40,
        )
        behavior.move_interaction(x=112, y=100, inside_petting=True, now=0.1)
        behavior.move_interaction(x=100, y=100, inside_petting=True, now=0.2)
        behavior.end_interaction(now=0.3)
        self.assertEqual(behavior.snapshot().activity, "petting_hold")

        behavior.typing_step(at=0.4)
        behavior.typing_held(True, at=0.4)
        behavior.typing_held(False, at=0.5)
        self.assertEqual(behavior.snapshot().activity, "typing_hold")

    def test_reduced_motion_uses_relaxed_pose_and_one_static_heart(self):
        behavior = PetBehavior(reduced_motion=True)
        behavior.begin_interaction(
            target="petting", x=100, y=100, now=0.0, petting_width=40,
        )
        behavior.move_interaction(x=112, y=100, inside_petting=True, now=0.1)
        behavior.move_interaction(x=100, y=100, inside_petting=True, now=0.2)

        behavior.advance(to=1.0)
        snapshot = behavior.snapshot()
        self.assertEqual((snapshot.pose, snapshot.variant), ("petting", "relaxed"))
        self.assertEqual(len(snapshot.hearts), 1)

    def test_hiding_discards_active_reactions_instead_of_queueing_them(self):
        behavior = PetBehavior()
        behavior.begin_interaction(
            target="petting", x=100, y=100, now=0.0, petting_width=40,
        )
        behavior.move_interaction(x=112, y=100, inside_petting=True, now=0.1)
        behavior.move_interaction(x=100, y=100, inside_petting=True, now=0.2)

        behavior.visibility_changed("user-pause", hidden=True, at=0.25)
        hidden = behavior.snapshot()
        self.assertEqual(hidden.activity, "hidden")
        self.assertEqual(hidden.hearts, ())

        behavior.visibility_changed("user-pause", hidden=False, at=0.3)
        self.assertEqual(behavior.snapshot().activity, "sitting")

    def test_hiding_reasons_compose_without_revealing_pet_early(self):
        behavior = PetBehavior()
        behavior.visibility_changed("user-pause", hidden=True, at=0.1)
        self.assertFalse(behavior.snapshot().visible)

        behavior.visibility_changed("fullscreen", hidden=True, at=0.2)
        behavior.visibility_changed("user-pause", hidden=False, at=0.3)
        still_hidden = behavior.snapshot()
        self.assertFalse(still_hidden.visible)
        self.assertEqual(still_hidden.activity, "hidden")

        behavior.visibility_changed("fullscreen", hidden=False, at=0.4)
        self.assertTrue(behavior.snapshot().visible)

    def test_hiding_discards_tracking_and_typing_hold(self):
        behavior = PetBehavior()
        behavior.tracking_changed("east", at=0.1)
        behavior.typing_step(at=0.2)
        behavior.typing_held(True, at=0.2)
        behavior.typing_held(False, at=0.3)

        behavior.visibility_changed("fullscreen", hidden=True, at=0.4)
        behavior.visibility_changed("fullscreen", hidden=False, at=0.5)
        self.assertEqual(behavior.snapshot().activity, "sitting")

    def test_drag_discards_lower_priority_reactions(self):
        behavior = PetBehavior()
        behavior.begin_interaction(
            target="petting", x=100, y=100, now=0.0, petting_width=40,
        )
        behavior.move_interaction(x=112, y=100, inside_petting=True, now=0.1)
        behavior.move_interaction(x=100, y=100, inside_petting=True, now=0.2)
        behavior.end_interaction(now=0.3)

        behavior.set_dragging(True, now=0.4)
        self.assertEqual(behavior.snapshot().activity, "dragging")
        behavior.typing_step(at=0.45)
        behavior.typing_held(True, at=0.45)
        behavior.set_dragging(False, now=0.5)
        self.assertEqual(behavior.snapshot().activity, "sitting")

    def test_motion_outside_head_does_not_count_toward_a_stroke(self):
        behavior = PetBehavior()
        behavior.begin_interaction(
            target="petting", x=100, y=100, now=0.0, petting_width=40,
        )
        behavior.move_interaction(x=106, y=100, inside_petting=True, now=0.1)
        behavior.move_interaction(x=130, y=100, inside_petting=False, now=0.2)
        behavior.move_interaction(x=100, y=100, inside_petting=True, now=0.3)
        behavior.move_interaction(x=101, y=100, inside_petting=True, now=0.4)

        snapshot = behavior.snapshot()
        self.assertEqual(snapshot.activity, "sitting")
        self.assertEqual(snapshot.hearts, ())

    def test_leaving_head_pauses_heart_emission_without_catchup(self):
        behavior = PetBehavior()
        behavior.begin_interaction(
            target="petting", x=100, y=100, now=0.0, petting_width=40,
        )
        behavior.move_interaction(x=112, y=100, inside_petting=True, now=0.1)
        behavior.move_interaction(x=100, y=100, inside_petting=True, now=0.2)
        behavior.move_interaction(x=80, y=100, inside_petting=False, now=0.25)
        behavior.advance(to=0.8)
        self.assertEqual(len(behavior.snapshot().hearts), 1)

        behavior.move_interaction(x=100, y=100, inside_petting=True, now=0.8)
        self.assertEqual(len(behavior.snapshot().hearts), 1)

    def test_drag_owns_normalized_placement_and_semantic_wobble(self):
        behavior = PetBehavior(position=(0.3, 0.5))
        self.assertEqual(behavior.snapshot().position, (0.3, 0.5))

        behavior.set_dragging(True, now=0.0)
        self.assertEqual(behavior.snapshot().variant, "middle")
        behavior.move_drag(x=0.4, y=0.6, now=0.1)
        behavior.advance(to=0.1)
        behavior.move_drag(x=0.5, y=0.6, now=0.2)
        behavior.advance(to=0.2)
        moved = behavior.snapshot()
        self.assertEqual(moved.position, (0.5, 0.6))
        self.assertEqual(moved.variant, "left")

        behavior.advance(to=0.33)
        self.assertEqual(behavior.snapshot().variant, "middle")


if __name__ == "__main__":
    unittest.main()
