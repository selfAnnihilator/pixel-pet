#!/usr/bin/env python3
"""Pixel Pet — wlr-layer-shell desktop companion.

This paints the pet directly onto a screen-level *overlay* layer
(gtk4-layer-shell). There is no border or workspace
membership: the surface spans the whole output and floats above everything, so
the pet is "an independent part of the screen" and ignores workspace switches.

Needs: GTK4, python-gobject, gtk4-layer-shell. Wayland (wlroots: niri/sway/Hyprland).
"""
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Adw, Gio, Gtk, Gdk, GdkPixbuf, GLib, Gtk4LayerShell as LayerShell
import cairo

from pet_behavior import PetBehavior
from behavior_input import (
    EvdevBehaviorActivityAdapter,
    PointerMotion,
    TypingHeld,
    TypingStep,
)
from behavior_scheduler import BehaviorAdvanceScheduler
from companion_presentation import CompanionPresentation, SpriteMetrics
from niri_monitor import NiriFullscreenMonitor
from live_settings import LiveSettingsCoordinator
from process_identity import set_process_name
import json
import os
import sys
import time

from pet_settings import DEFAULTS, SettingsStore
from pet_controller import PetController

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")
SCALE = int(os.environ.get("PET_SCALE", "4"))

# Mouse-tracking tuning.
DEADZONE = 24         # cursor within this many px of the cat center -> look straight

def _alpha_bbox(pixbuf):
    """Tight (x0, y0, x1, y1) box around the non-transparent pixels of a cell,
    in cell-local pixel coords (x1/y1 exclusive). Falls back to the full cell
    if there's no alpha channel."""
    w, h = pixbuf.get_width(), pixbuf.get_height()
    if not pixbuf.get_has_alpha():
        return (0, 0, w, h)
    stride = pixbuf.get_rowstride()
    n_ch = pixbuf.get_n_channels()
    data = pixbuf.get_pixels()
    min_x, min_y, max_x, max_y = w, h, -1, -1
    for y in range(h):
        row_off = y * stride
        for x in range(w):
            if data[row_off + x * n_ch + 3] > 10:
                if x < min_x: min_x = x
                if x > max_x: max_x = x
                if y < min_y: min_y = y
                if y > max_y: max_y = y
    if max_x < 0:
        return (0, 0, w, h)
    return (min_x, min_y, max_x + 1, max_y + 1)


class Sheet:
    """Slices a packed sprite sheet into per-(state,frame) pixbufs."""

    def __init__(self, pet_def):
        self.defn = pet_def
        self.faces_right = pet_def.get("facesRight", True)
        path = os.path.join(ASSETS, pet_def["sheet"])
        full = GdkPixbuf.Pixbuf.new_from_file(path)
        cw, ch = pet_def["cellW"], pet_def["cellH"]
        self.cw, self.ch = cw, ch
        self.base_scale = float(pet_def.get("scale", SCALE))
        self.scale = self.base_scale
        self.frames = {}  # state -> [pixbuf, ...]
        self.bboxes = {}  # state -> [(x0,y0,x1,y1), ...] tight alpha box per frame
        for state, a in pet_def["anims"].items():
            row = a["row"]
            self.frames[state] = [
                full.new_subpixbuf(c * cw, row * ch, cw, ch) for c in range(a["frames"])
            ]
            self.bboxes[state] = [_alpha_bbox(pb) for pb in self.frames[state]]

    def anim(self, state):
        return self.defn["anims"][state]


class Pet:
    def __init__(self, manifest, pet_name, settings=None):
        self.manifest = manifest
        pet_defs = manifest["pets"]
        self.name = pet_name if pet_name in pet_defs else manifest["defaultPet"]
        self.sheet = Sheet(pet_defs[self.name])
        drag_def = pet_defs.get(self.name + "_drag")
        type_def = pet_defs.get(self.name + "_type")
        pet_def = pet_defs.get(self.name + "_pet")
        hunt_def = pet_defs.get(self.name + "_hunt")
        self.drag_sheet = Sheet(drag_def) if drag_def is not None else None
        self.type_sheet = Sheet(type_def) if type_def is not None else None
        self.pet_sheet = Sheet(pet_def) if pet_def is not None else None
        self.hunt_sheet = Sheet(hunt_def) if hunt_def is not None else None
        self._heart_path = os.path.join(ASSETS, self.name, "heart.png")
        self.heart_pixbuf = None
        settings = settings or DEFAULTS
        self.presentation = CompanionPresentation()
        self.size_percent = int(settings.get("size_percent", 100))
        pointer_tracking = bool(settings.get("pointer_tracking", True))
        typing_reactions = bool(settings.get("typing_reactions", True))
        petting_reactions = bool(settings.get("petting_reactions", True))
        typing_hold_seconds = float(settings.get("typing_hold_seconds", 2.0))
        user_paused = bool(settings.get("paused", False))
        self._saved_position = settings.get("position")
        self.W = self.H = 0
        self._presentation_metrics = None
        self.set_size_percent(self.size_percent)

        self.gx = 0.0          # ground anchor x (feet, screen px)
        self.gy = 0.0          # ground anchor y (feet, screen px)
        self.state = "track"   # animation row currently playing
        self.frame = 0
        self._drag_dx = self._drag_dy = 0.0
        self._last = time.monotonic()
        saved = self._saved_position if isinstance(self._saved_position, dict) else {}
        initial_position = (saved.get("x", 0.7), saved.get("y", 0.8))
        self.behavior = PetBehavior(
            typing_hold_seconds=typing_hold_seconds,
            position=initial_position,
            typing_reactions=typing_reactions,
            petting_reactions=petting_reactions,
            tracking_enabled=pointer_tracking,
        )
        self.behavior.visibility_changed(
            "user-pause", hidden=user_paused, at=time.monotonic()
        )
        self._interaction_target = None
        self._last_pointer_x = None

    # ---- behavior -------------------------------------------------------
    @property
    def paused(self):
        return not self.behavior.snapshot().visible

    @property
    def user_paused(self):
        return "user-pause" in self.behavior.snapshot().hiding_reasons

    @property
    def fullscreen_paused(self):
        return "fullscreen" in self.behavior.snapshot().hiding_reasons

    def set_size_percent(self, percent):
        self.size_percent = max(75, min(200, int(percent)))
        for sheet in (
            self.sheet,
            self.drag_sheet,
            self.type_sheet,
            self.pet_sheet,
            self.hunt_sheet,
        ):
            if sheet is not None:
                sheet.scale = self.presentation.overlay_scale(
                    base_scale=sheet.base_scale,
                    size_percent=self.size_percent,
                )
        self._presentation_metrics = None
        if self.W:
            self._clamp()

    def set_user_paused(self, paused):
        paused = bool(paused)
        self.behavior.visibility_changed(
            "user-pause", hidden=paused, at=time.monotonic()
        )

    def set_fullscreen_paused(self, paused):
        paused = bool(paused)
        self.behavior.visibility_changed(
            "fullscreen", hidden=paused, at=time.monotonic()
        )

    def set_pointer_tracking(self, enabled):
        self.behavior.tracking_enabled_changed(
            bool(enabled), at=time.monotonic()
        )

    def set_typing_enabled(self, enabled):
        self.behavior.typing_reactions_changed(
            bool(enabled), at=time.monotonic()
        )

    def set_petting_enabled(self, enabled):
        self.behavior.petting_reactions_changed(
            bool(enabled), at=time.monotonic()
        )

    def set_typing_hold(self, seconds):
        self.behavior.typing_hold_changed(
            seconds, at=time.monotonic()
        )

    def reset_position(self):
        self._saved_position = None
        if self.W:
            self.gx, self.gy = self.presentation.position_to_anchor(
                (0.7, 0.8), (self.W, self.H)
            )
            self._clamp()
            x, y = self.presentation.anchor_to_position(
                (self.gx, self.gy), (self.W, self.H)
            )
            self.behavior.placement_changed(
                x=x,
                y=y,
                at=time.monotonic(),
            )

    def set_normalized_position(self, position):
        if position is None:
            self.reset_position()
            return
        x = max(0.0, min(1.0, float(position["x"])))
        y = max(0.0, min(1.0, float(position["y"])))
        if self.W and self.H:
            self.gx, self.gy = self.presentation.position_to_anchor(
                (x, y), (self.W, self.H)
            )
            self._clamp()
            x, y = self.presentation.anchor_to_position(
                (self.gx, self.gy), (self.W, self.H)
            )
        self.behavior.placement_changed(x=x, y=y, at=time.monotonic())

    def normalized_position(self):
        if not self.W or not self.H:
            return None
        x, y = self.behavior.snapshot().position
        return {"x": x, "y": y}

    def begin_pointer_interaction(self, x, y, now):
        plan = self.overlay_plan()
        target = self.presentation.interaction_target(
            x=x,
            y=y,
            sprite=plan.sprite,
            petting_enabled=self.behavior.snapshot().petting_reactions,
        )
        self._interaction_target = target
        if target == "petting":
            self.behavior.begin_interaction(
                target="petting",
                x=x,
                y=y,
                now=now,
                petting_width=plan.sprite.width * 0.48,
            )
        else:
            self.behavior.set_dragging(True, now=now)
            self._drag_dx = self.gx - x
            self._drag_dy = self.gy - y
        return target

    def move_pointer_interaction(self, x, y, now):
        if self._interaction_target == "petting":
            plan = self.overlay_plan()
            self.behavior.move_interaction(
                x=x,
                y=y,
                inside_petting=self.presentation.inside_petting_point(
                    x=x,
                    y=y,
                    sprite=plan.sprite,
                    tolerance=0.04,
                ),
                now=now,
            )
        elif self._interaction_target == "drag":
            new_x = x + self._drag_dx
            new_y = y + self._drag_dy
            self.gx, self.gy = new_x, new_y
            self._clamp()
            normalized_x, normalized_y = self.presentation.anchor_to_position(
                (self.gx, self.gy), (self.W, self.H)
            )
            self.behavior.move_drag(
                x=normalized_x,
                y=normalized_y,
                now=now,
            )

    def end_pointer_interaction(self, now):
        if self._interaction_target == "petting":
            self.behavior.end_interaction(now=now)
        elif self._interaction_target == "drag":
            self.behavior.set_dragging(False, now=now)
        self._interaction_target = None

    def set_viewport(self, w, h):
        if self.W == w and self.H == h:
            return
        self.W, self.H = w, h
        x, y = self.behavior.snapshot().position
        self.gx, self.gy = self.presentation.position_to_anchor((x, y), (w, h))
        self._clamp()
        x, y = self.presentation.anchor_to_position((self.gx, self.gy), (w, h))
        self.behavior.placement_changed(
            x=x,
            y=y,
            at=time.monotonic(),
        )

    def _clamp(self):
        self.gx, self.gy = self.presentation.clamp_anchor(
            (self.gx, self.gy),
            viewport=(self.W, self.H),
            metrics=self.presentation_metrics()["base"],
        )

    def _cat_center(self):
        """Screen-space center of the drawn sprite (origin for the look vector)."""
        return self.presentation.sprite_center(self.overlay_plan().sprite)

    def _sheet_map(self):
        return {
            "base": self.sheet,
            "drag": self.drag_sheet,
            "type": self.type_sheet,
            "pet": self.pet_sheet,
            "hunt": self.hunt_sheet,
        }

    def sheet_for(self, name):
        return self._sheet_map().get(name) or self.sheet

    def presentation_metrics(self):
        if self._presentation_metrics is not None:
            return self._presentation_metrics
        metrics = {}
        for name, sheet in self._sheet_map().items():
            if sheet is None:
                continue
            bounds = {
                state: tuple(tuple(box) for box in boxes)
                for state, boxes in sheet.bboxes.items()
            }
            metrics[name] = SpriteMetrics(
                cell_width=sheet.cw,
                cell_height=sheet.ch,
                scale=sheet.scale,
                bounds=bounds,
            )
        self._presentation_metrics = metrics
        return metrics

    def overlay_plan(self, snapshot=None):
        snapshot = self.behavior.snapshot() if snapshot is None else snapshot
        return self.presentation.overlay_plan(
            snapshot,
            viewport=(self.W, self.H),
            sheets=self.presentation_metrics(),
            size_percent=self.size_percent,
        )

    def preview_plan(self, width, height, snapshot=None):
        snapshot = self.behavior.snapshot() if snapshot is None else snapshot
        return self.presentation.preview_plan(
            snapshot,
            viewport=(width, height),
            sheets=self.presentation_metrics(),
            size_percent=self.size_percent,
        )

    def active_sprite(self):
        """Return the sprite selected from the pure Behavior Snapshot."""
        sheet_name, state, frame = self.presentation.selection_for(
            self.behavior.snapshot()
        )
        sheet = self.sheet_for(sheet_name)
        self.frame = frame
        return sheet, state

    def observe_pointer(self, x, y, at, horizontal_deltas=()):
        cx, cy = self._cat_center()
        direction = self.presentation.tracking_direction(
            dx=x - cx,
            dy=y - cy,
            deadzone=DEADZONE,
        )
        bounds = self.sheet.bboxes["track"][0]
        visible_width = max(1, bounds[2] - bounds[0]) * self.sheet.scale
        fallback_delta = (
            0.0 if self._last_pointer_x is None else x - self._last_pointer_x
        )
        self._last_pointer_x = x
        deltas = tuple(horizontal_deltas) or (fallback_delta,)
        for index, delta in enumerate(deltas):
            sample_direction = direction
            if index < len(deltas) - 1:
                sample_direction = "east" if delta > 0 else "west"
            self.behavior.pointer_moved(
                sample_direction,
                horizontal_delta=delta / visible_width,
                at=at,
            )

    def observe_typing_step(self, at):
        if self.type_sheet is not None:
            self.behavior.typing_step(at=at)

    def observe_typing_held(self, held, at):
        if self.type_sheet is not None:
            self.behavior.typing_held(held, at=at)

    def update(self, dt, now=None):
        del dt
        now = time.monotonic() if now is None else now
        if self.behavior.snapshot().activity == "dragging":
            self.behavior.advance(to=now)
            self.active_sprite()
            return
        self.behavior.advance(to=now)
        self.active_sprite()

    # ---- rendering ------------------------------------------------------
    def draw(self, cr, snapshot=None):
        plan = self.overlay_plan(snapshot)
        self.draw_plan(cr, plan)

    def draw_plan(self, cr, plan):
        sprite = plan.sprite
        sheet = self.sheet_for(sprite.sheet)
        frames = sheet.frames[sprite.state]
        pb = frames[min(sprite.frame, len(frames) - 1)]
        cr.save()
        cr.translate(sprite.x, sprite.y)
        cr.scale(sprite.scale, sprite.scale)
        Gdk.cairo_set_source_pixbuf(cr, pb, 0, 0)
        cr.get_source().set_filter(cairo.FILTER_NEAREST)  # crisp pixels
        cr.paint()
        cr.restore()
        self._draw_hearts(cr, plan.hearts)

    def _draw_hearts(self, cr, hearts):
        if self.heart_pixbuf is None and os.path.exists(self._heart_path):
            try:
                self.heart_pixbuf = GdkPixbuf.Pixbuf.new_from_file(self._heart_path)
            except GLib.Error as error:
                print(f"pet: couldn't load heart sprite: {error}", file=sys.stderr)
        if self.heart_pixbuf is None:
            return
        for heart in hearts:
            cr.save()
            cr.translate(heart.x, heart.y)
            cr.scale(heart.scale, heart.scale)
            Gdk.cairo_set_source_pixbuf(cr, self.heart_pixbuf, 0, 0)
            cr.get_source().set_filter(cairo.FILTER_NEAREST)
            cr.paint_with_alpha(heart.alpha)
            cr.restore()

def main():
    set_process_name("pixel-pet")
    with open(os.path.join(ASSETS, "manifest.json")) as f:
        manifest = json.load(f)
    store = SettingsStore()
    pet_name = store.get("pet")
    pet = Pet(manifest, pet_name, store.data)

    app = Adw.Application(
        application_id="com.abhi.pixelpet",
        flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
    )
    state = {
        "overlay": None,
        "area": None,
        "set_clickthrough": None,
        "controller": None,
        "show_controller": True,
        "input_started": False,
        "fullscreen_started": False,
        "snapshot": pet.behavior.snapshot(),
        "overlay_plan": None,
    }

    def update_input_region(plan):
        win = state["overlay"]
        if win is None or not state["snapshot"].visible or plan.input_region is None:
            return
        surface = win.get_surface()
        if surface is None:
            return
        region = plan.input_region
        rect = cairo.RectangleInt(
            region.x, region.y, region.width, region.height
        )
        surface.set_input_region(cairo.Region(rect))

    def present_snapshot(snapshot, force):
        state["snapshot"] = snapshot
        if pet.W and pet.H:
            plan = pet.overlay_plan(snapshot)
            previous_plan = state["overlay_plan"]
            if force or plan != previous_plan:
                state["overlay_plan"] = plan
                area = state["area"]
                if area is not None and snapshot.visible:
                    area.queue_draw()
                if (
                    force
                    or previous_plan is None
                    or plan.input_region != previous_plan.input_region
                ):
                    update_input_region(plan)
        controller = state["controller"]
        if controller is not None:
            controller.refresh_snapshot(snapshot, force=force)
        apply_overlay_visibility()

    scheduler = BehaviorAdvanceScheduler(
        pet.behavior,
        present_snapshot,
        schedule_timeout=lambda delay, callback: GLib.timeout_add(delay, callback),
        cancel_timeout=lambda source: GLib.source_remove(source),
    )

    def on_fullscreen_changed(fullscreen):
        now = time.monotonic()
        pet.set_fullscreen_paused(fullscreen)
        scheduler.activity(at=now)

    fullscreen_monitor = NiriFullscreenMonitor(
        on_fullscreen_changed,
        dispatch=lambda callback: GLib.idle_add(callback),
        schedule_retry=lambda delay, callback: GLib.timeout_add(delay, callback),
        cancel_retry=lambda source: GLib.source_remove(source),
    )

    def on_observation(observation):
        if isinstance(observation, PointerMotion):
            pet.observe_pointer(
                observation.x,
                observation.y,
                observation.at,
                observation.horizontal_deltas,
            )
        elif isinstance(observation, TypingStep):
            pet.observe_typing_step(observation.at)
        elif isinstance(observation, TypingHeld):
            pet.observe_typing_held(observation.held, observation.at)
        scheduler.activity(at=observation.at)

    activity_input = EvdevBehaviorActivityAdapter(
        on_observation,
        dispatch=lambda callback: GLib.idle_add(callback),
    )
    activity_input.configure(
        pointer_enabled=store.get("pointer_tracking"),
        typing_enabled=store.get("typing_reactions"),
    )

    def apply_pointer_tracking(enabled):
        pet.set_pointer_tracking(enabled)
        activity_input.configure(
            pointer_enabled=enabled,
            typing_enabled=store.get("typing_reactions"),
        )

    def apply_typing_reactions(enabled):
        pet.set_typing_enabled(enabled)
        activity_input.configure(
            pointer_enabled=store.get("pointer_tracking"),
            typing_enabled=enabled,
        )

    live_settings = LiveSettingsCoordinator(
        store,
        {
            "size_percent": pet.set_size_percent,
            "pointer_tracking": apply_pointer_tracking,
            "typing_reactions": apply_typing_reactions,
            "petting_reactions": pet.set_petting_enabled,
            "typing_hold_seconds": pet.set_typing_hold,
            "paused": pet.set_user_paused,
            "position": pet.set_normalized_position,
        },
        schedule_timeout=lambda delay, callback: GLib.timeout_add(delay, callback),
        cancel_timeout=lambda source: GLib.source_remove(source),
        dispatch=lambda callback: GLib.idle_add(callback),
        on_applied=scheduler.invalidate,
    )

    def install_css(_app):
        GLib.set_application_name("Pixel Pet")
        provider = Gtk.CssProvider()
        provider.load_from_data(b"""
            @define-color accent_bg_color #d47a47;
            @define-color accent_color #9a4b27;
            .preview-pane { background-color: alpha(@accent_bg_color, 0.045); }
            .pet-status { color: @accent_color; font-weight: 600; }
            .paused-status { color: @insensitive_fg_color; }
            .main-separator { background-color: @borders; }
            .destructive-action { color: @error_color; }
        """)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def apply_overlay_visibility():
        win = state["overlay"]
        if win is None:
            return
        if not state["snapshot"].visible:
            if win.get_visible():
                win.set_visible(False)
            return
        if not win.get_visible():
            win.present()
            set_clickthrough = state["set_clickthrough"]
            if set_clickthrough is not None:
                GLib.idle_add(set_clickthrough)

    def create_overlay():
        if state["overlay"] is not None:
            return state["overlay"]
        win = Gtk.ApplicationWindow(application=app)
        state["overlay"] = win
        LayerShell.init_for_window(win)
        LayerShell.set_layer(win, LayerShell.Layer.OVERLAY)      # above everything
        LayerShell.set_namespace(win, "pixelpet")
        for edge in (LayerShell.Edge.TOP, LayerShell.Edge.BOTTOM,
                     LayerShell.Edge.LEFT, LayerShell.Edge.RIGHT):
            LayerShell.set_anchor(win, edge, True)               # span whole output
        LayerShell.set_exclusive_zone(win, -1)                   # don't reserve space
        LayerShell.set_keyboard_mode(win, LayerShell.KeyboardMode.NONE)

        area = Gtk.DrawingArea()
        state["area"] = area
        area.set_hexpand(True)
        area.set_vexpand(True)
        win.set_child(area)

        # transparent surface
        overlay_css = Gtk.CssProvider()
        overlay_css.load_from_data(
            b"window.pixel-pet-overlay, window.pixel-pet-overlay drawingarea "
            b"{ background: transparent; }"
        )
        win.add_css_class("pixel-pet-overlay")
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), overlay_css,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        def draw_func(area, cr, w, h):
            activity_input.set_viewport(w, h)
            viewport_changed = pet.W != w or pet.H != h
            pet.set_viewport(w, h)
            if viewport_changed:
                scheduler.invalidate()
            plan = state["overlay_plan"]
            if plan is None:
                plan = pet.overlay_plan(state["snapshot"])
                state["overlay_plan"] = plan
            pet.draw_plan(cr, plan)

        area.set_draw_func(draw_func)

        # click-through everywhere except the pet's own bbox: empty input region
        # so the mouse passes to apps beneath, except over the sprite itself.
        # Re-applied whenever the surface is recreated (e.g. after a hide/show).
        def set_clickthrough():
            surface = win.get_surface()
            if surface is not None:
                surface.set_input_region(cairo.Region())
                plan = state["overlay_plan"]
                if plan is not None:
                    update_input_region(plan)
            return False

        state["set_clickthrough"] = set_clickthrough

        # Press origin locks the interaction: head rubs pet the cat; body motion
        # drags it with the existing offset-locked positioning behavior.
        def on_drag_begin(gesture, start_x, start_y):
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            now = time.monotonic()
            pet.begin_pointer_interaction(start_x, start_y, now)
            scheduler.activity(at=now)

        def on_drag_update(gesture, offset_x, offset_y):
            ok, start_x, start_y = gesture.get_start_point()
            if not ok:
                return
            now = time.monotonic()
            pet.move_pointer_interaction(
                start_x + offset_x,
                start_y + offset_y,
                now,
            )
            scheduler.activity(at=now)

        def on_drag_end(gesture, offset_x, offset_y):
            was_drag = pet._interaction_target == "drag"
            now = time.monotonic()
            pet.end_pointer_interaction(now)
            scheduler.activity(at=now)
            if was_drag:
                try:
                    live_settings.change("position", pet.normalized_position())
                except OSError as error:
                    print(f"pet: couldn't save position: {error}", file=sys.stderr)

        drag = Gtk.GestureDrag.new()
        drag.connect("drag-begin", on_drag_begin)
        drag.connect("drag-update", on_drag_update)
        drag.connect("drag-end", on_drag_end)
        area.add_controller(drag)

        def sync_reduced_motion(*_args):
            now = time.monotonic()
            gtk_settings = Gtk.Settings.get_default()
            if gtk_settings is not None:
                pet.behavior.reduced_motion_changed(
                    not gtk_settings.get_property("gtk-enable-animations"),
                    at=now,
                )
                scheduler.activity(at=now)
            return False

        gtk_settings = Gtk.Settings.get_default()
        if gtk_settings is not None:
            gtk_settings.connect(
                "notify::gtk-enable-animations", sync_reduced_motion
            )
            sync_reduced_motion()

        apply_overlay_visibility()
        return win

    def ensure_controller():
        controller = state["controller"]
        if controller is None:
            controller = PetController(
                app, pet, store, live_settings, activity_input,
                os.path.join(HERE, "run-pet.sh"),
                apply_overlay_visibility,
                scheduler.invalidate,
            )
            state["controller"] = controller
        return controller

    def on_activate(_app):
        create_overlay()
        if not scheduler.running:
            scheduler.start()
        if not state["input_started"]:
            activity_input.start(
                pointer_enabled=store.get("pointer_tracking"),
                typing_enabled=store.get("typing_reactions"),
            )
            state["input_started"] = True
        if not state["fullscreen_started"]:
            fullscreen_monitor.start()
            state["fullscreen_started"] = True
        if state["show_controller"]:
            ensure_controller().present()

    def on_command_line(_app, command_line):
        args = command_line.get_arguments()[1:]
        state["show_controller"] = "--background" not in args
        app.activate()
        return 0

    app.connect("startup", install_css)
    app.connect("activate", on_activate)
    app.connect("command-line", on_command_line)
    def on_shutdown(_app):
        fullscreen_monitor.stop()
        try:
            live_settings.close()
        except OSError as error:
            print(f"pet: couldn't flush settings: {error}", file=sys.stderr)
        activity_input.close()
        scheduler.stop()

    app.connect("shutdown", on_shutdown)
    app.run(sys.argv)


if __name__ == "__main__":
    main()
