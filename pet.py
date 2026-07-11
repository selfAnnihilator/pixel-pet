#!/usr/bin/env python3
"""Pixel Pet — wlr-layer-shell desktop companion.

Unlike the Electron build, this paints the pet directly onto a screen-level
*overlay* layer (gtk4-layer-shell). There is no window, no border, no workspace
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
from process_identity import set_process_name
from sprite_presentation import SpritePresentation
import glob
import json
import os
import select
import shutil
import struct
import subprocess
import sys
import threading
import time

from pet_settings import DEFAULTS, SettingsStore
from pet_controller import PetController

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")
SCALE = int(os.environ.get("PET_SCALE", "4"))

# Mouse-tracking tuning.
MOVE_TIMEOUT = 0.18   # cursor counts as "moving" for this long after last motion event
DEADZONE = 24         # cursor within this many px of the cat center -> look straight

class MouseTracker:
    """Reads relative motion from evdev pointer devices and integrates it into a
    virtual cursor position. Avoids capturing clicks (the overlay stays fully
    click-through); niri exposes no cursor-position API so we read the raw devices.

    Relative deltas are post-acceleration-agnostic: magnitude may drift from the
    real pointer, but direction is what drives the sprite, and clamping at the
    screen edges re-syncs position."""

    _EV_SIZE = struct.calcsize("llHHi")  # input_event: timeval + type + code + value
    _EV_REL = 0x02
    _REL_X, _REL_Y = 0x00, 0x01

    def __init__(self):
        self.vx = self.vy = 0.0
        self.last_motion = 0.0
        self.W = self.H = 0
        self._fds = []
        self.available = False
        self._started = False

    def set_viewport(self, w, h):
        if self.W == 0:
            self.vx, self.vy = w / 2.0, h / 2.0
        self.W, self.H = w, h

    def moving(self):
        return (time.monotonic() - self.last_motion) < MOVE_TIMEOUT

    def _open_devices(self):
        paths = sorted(set(glob.glob("/dev/input/by-path/*-event-mouse")))
        if not paths:
            paths = sorted(glob.glob("/dev/input/event*"))
        for p in paths:
            try:
                self._fds.append(os.open(p, os.O_RDONLY | os.O_NONBLOCK))
            except OSError:
                pass
        return bool(self._fds)

    def start(self):
        if self._started:
            return self.available
        if not self._open_devices():
            print("pet: no readable pointer devices in /dev/input "
                  "(need 'input' group); tracking disabled", file=sys.stderr)
            self.available = False
            return False
        self.available = True
        self._started = True
        threading.Thread(target=self._reader, daemon=True).start()
        return True

    def _reader(self):
        while True:
            ready, _, _ = select.select(self._fds, [], [], 0.5)
            for fd in ready:
                try:
                    buf = os.read(fd, self._EV_SIZE * 64)
                except OSError:
                    continue
                self._consume(buf)

    def _consume(self, buf):
        dx = dy = 0
        n = len(buf) // self._EV_SIZE
        for i in range(n):
            off = i * self._EV_SIZE
            _, _, etype, code, value = struct.unpack_from("llHHi", buf, off)
            if etype != self._EV_REL:
                continue
            if code == self._REL_X:
                dx += value
            elif code == self._REL_Y:
                dy += value
        if dx or dy:
            self.vx = min(max(self.vx + dx, 0.0), float(self.W or 1))
            self.vy = min(max(self.vy + dy, 0.0), float(self.H or 1))
            self.last_motion = time.monotonic()


class KeyboardTracker:
    """Reads global keyboard presses from evdev without taking keyboard focus.

    Every physical keydown counts, including modifiers. Kernel-generated repeat
    events do not create new paw presses: they keep the current held-key pose.
    Devices are restricted to keyboard symlinks so mouse buttons (also reported
    as EV_KEY) cannot trigger typing.
    """

    _EV_SIZE = struct.calcsize("llHHi")
    _EV_KEY = 0x01
    _KEY_DOWN = 1

    def __init__(self):
        self.press_serial = 0
        self.last_press = 0.0
        self.last_release = 0.0
        self.held_keys = set()
        self._fds = []
        self.available = False
        self._started = False

    def any_held(self):
        return bool(self.held_keys)

    def _open_devices(self):
        paths = sorted(set(
            glob.glob("/dev/input/by-path/*-event-kbd")
            + glob.glob("/dev/input/by-id/*-event-kbd")
        ))
        opened = set()
        for path in paths:
            try:
                real = os.path.realpath(path)
                if real in opened:
                    continue
                self._fds.append(os.open(path, os.O_RDONLY | os.O_NONBLOCK))
                opened.add(real)
            except OSError:
                pass
        return bool(self._fds)

    def start(self):
        if self._started:
            return self.available
        if not self._open_devices():
            print("pet: no readable keyboard devices in /dev/input "
                  "(need 'input' group); typing disabled", file=sys.stderr)
            self.available = False
            return False
        self.available = True
        self._started = True
        threading.Thread(target=self._reader, daemon=True).start()
        return True

    def _reader(self):
        while True:
            ready, _, _ = select.select(self._fds, [], [], 0.5)
            for fd in ready:
                try:
                    buf = os.read(fd, self._EV_SIZE * 64)
                except OSError:
                    continue
                self._consume(buf)

    def _consume(self, buf):
        n = len(buf) // self._EV_SIZE
        for i in range(n):
            off = i * self._EV_SIZE
            _, _, etype, code, value = struct.unpack_from("llHHi", buf, off)
            if etype != self._EV_KEY:
                continue
            if value == self._KEY_DOWN and code not in self.held_keys:
                self.held_keys.add(code)
                self.last_press = time.monotonic()
                self.press_serial += 1
            elif value == 0 and code in self.held_keys:
                self.held_keys.remove(code)
                self.last_release = time.monotonic()


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
    def __init__(self, manifest, pet_name, tracker=None, keyboard=None, settings=None):
        self.manifest = manifest
        pet_defs = manifest["pets"]
        self.name = pet_name if pet_name in pet_defs else manifest["defaultPet"]
        self.sheet = Sheet(pet_defs[self.name])
        drag_def = pet_defs.get(self.name + "_drag")
        type_def = pet_defs.get(self.name + "_type")
        pet_def = pet_defs.get(self.name + "_pet")
        self.drag_sheet = Sheet(drag_def) if drag_def is not None else None
        self.type_sheet = Sheet(type_def) if type_def is not None else None
        self.pet_sheet = Sheet(pet_def) if pet_def is not None else None
        self._heart_path = os.path.join(ASSETS, self.name, "heart.png")
        self.heart_pixbuf = None
        self.tracker = tracker
        self.keyboard = keyboard
        settings = settings or DEFAULTS
        self.size_percent = int(settings.get("size_percent", 100))
        pointer_tracking = bool(settings.get("pointer_tracking", True))
        typing_reactions = bool(settings.get("typing_reactions", True))
        petting_reactions = bool(settings.get("petting_reactions", True))
        typing_hold_seconds = float(settings.get("typing_hold_seconds", 2.0))
        user_paused = bool(settings.get("paused", False))
        self._saved_position = settings.get("position")
        self.W = self.H = 0
        self.set_size_percent(self.size_percent)

        self.gx = 0.0          # ground anchor x (feet, screen px)
        self.gy = 0.0          # ground anchor y (feet, screen px)
        self.state = "track"   # animation row currently playing
        self.frame = 0
        self._drag_dx = self._drag_dy = 0.0
        self._seen_key_serial = keyboard.press_serial if keyboard is not None else 0
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
        self.presentation = SpritePresentation()
        self._interaction_target = None

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
        multiplier = self.size_percent / 100.0
        for sheet in (self.sheet, self.drag_sheet, self.type_sheet, self.pet_sheet):
            if sheet is not None:
                sheet.scale = sheet.base_scale * multiplier
        if self.W:
            self._clamp()

    def set_user_paused(self, paused):
        paused = bool(paused)
        if paused:
            self.cancel_typing()
        self.behavior.visibility_changed(
            "user-pause", hidden=paused, at=time.monotonic()
        )

    def set_fullscreen_paused(self, paused):
        paused = bool(paused)
        if paused:
            self.cancel_typing()
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
        if not enabled:
            self.cancel_typing()

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
            self.gx, self.gy = self.W * 0.7, self.H * 0.8
            self._clamp()
            self.behavior.placement_changed(
                x=self.gx / self.W,
                y=self.gy / self.H,
                at=time.monotonic(),
            )

    def normalized_position(self):
        if not self.W or not self.H:
            return None
        x, y = self.behavior.snapshot().position
        return {"x": x, "y": y}

    def _normalized_sprite_point(self, x, y):
        width = self.sheet.cw * self.sheet.scale
        height = self.sheet.ch * self.sheet.scale
        left = self.gx - width / 2.0
        top = self.gy - height
        return (x - left) / width, (y - top) / height

    def begin_pointer_interaction(self, x, y, now):
        normalized_x, normalized_y = self._normalized_sprite_point(x, y)
        target = self.presentation.interaction_target(
            x=normalized_x,
            y=normalized_y,
            petting_enabled=self.behavior.snapshot().petting_reactions,
        )
        self._interaction_target = target
        if target == "petting":
            self.behavior.begin_interaction(
                target="petting",
                x=x,
                y=y,
                now=now,
                petting_width=self.sheet.cw * self.sheet.scale * 0.48,
            )
        else:
            self.cancel_typing()
            self.behavior.set_dragging(True, now=now)
            self._drag_dx = self.gx - x
            self._drag_dy = self.gy - y
        return target

    def move_pointer_interaction(self, x, y, now):
        if self._interaction_target == "petting":
            normalized_x, normalized_y = self._normalized_sprite_point(x, y)
            self.behavior.move_interaction(
                x=x,
                y=y,
                inside_petting=self.presentation.inside_petting(
                    x=normalized_x, y=normalized_y, tolerance=0.04
                ),
                now=now,
            )
        elif self._interaction_target == "drag":
            new_x = x + self._drag_dx
            new_y = y + self._drag_dy
            self.gx, self.gy = new_x, new_y
            self._clamp()
            self.behavior.move_drag(
                x=self.gx / self.W,
                y=self.gy / self.H,
                now=now,
            )

    def end_pointer_interaction(self, now):
        if self._interaction_target == "petting":
            self.behavior.end_interaction(now=now)
        elif self._interaction_target == "drag":
            self.behavior.set_dragging(False, now=now)
        self._interaction_target = None

    def set_viewport(self, w, h):
        self.W, self.H = w, h
        x, y = self.behavior.snapshot().position
        self.gx, self.gy = w * x, h * y
        if self.tracker is not None:
            self.tracker.set_viewport(w, h)
        self._clamp()
        self.behavior.placement_changed(
            x=self.gx / self.W,
            y=self.gy / self.H,
            at=time.monotonic(),
        )

    def _clamp(self):
        s = self.sheet.scale
        dw, dh = self.sheet.cw * s, self.sheet.ch * s
        self.gx = max(dw / 2, min(self.gx, self.W - dw / 2))
        self.gy = max(dh, min(self.gy, self.H))

    def _cat_center(self):
        """Screen-space center of the drawn sprite (origin for the look vector)."""
        dh = self.sheet.ch * self.sheet.scale
        return self.gx, self.gy - dh / 2.0

    def active_sprite(self):
        """Return the sprite selected from the pure Behavior Snapshot."""
        selection = self.presentation.selection_for(self.behavior.snapshot())
        sheets = {
            "base": self.sheet,
            "drag": self.drag_sheet,
            "type": self.type_sheet,
            "pet": self.pet_sheet,
        }
        sheet = sheets.get(selection.sheet) or self.sheet
        self.frame = selection.frame
        return sheet, selection.state

    def cancel_typing(self):
        """Discard keyboard observations already consumed by a higher priority."""
        if self.keyboard is not None:
            self._seen_key_serial = self.keyboard.press_serial

    def _update_typing(self, now):
        """Translate keyboard observation into semantic Behavior Activity."""
        keyboard = self.keyboard
        if keyboard is None or self.type_sheet is None:
            self.cancel_typing()
            return False

        serial = keyboard.press_serial
        if serial != self._seen_key_serial:
            count = serial - self._seen_key_serial
            self._seen_key_serial = serial
            for _ in range(max(0, count)):
                self.behavior.typing_step(at=now)
        self.behavior.typing_held(keyboard.any_held(), at=now)
        snapshot = self.behavior.snapshot()
        return snapshot.activity in ("typing", "typing_hold")

    def update(self, dt, now=None):
        del dt
        now = time.monotonic() if now is None else now
        if self.behavior.snapshot().activity == "dragging":
            self.cancel_typing()
            self.behavior.advance(to=now)
            self.active_sprite()
            return
        self._update_typing(now)
        # Look toward the (virtual) cursor. Straight ahead when idle or when the
        # cursor sits on top of the cat; otherwise pick the matching compass frame.
        t = self.tracker
        if t is None or not t.moving():
            self.behavior.tracking_changed(None, at=now)
        else:
            cx, cy = self._cat_center()
            dx, dy = t.vx - cx, t.vy - cy
            direction = self.presentation.tracking_direction(
                dx=dx, dy=dy, deadzone=DEADZONE
            )
            self.behavior.tracking_changed(direction, at=now)
        self.behavior.advance(to=now)
        self.active_sprite()

    # ---- rendering ------------------------------------------------------
    def draw(self, cr):
        sheet, state = self.active_sprite()
        frames = sheet.frames[state]
        pb = frames[min(self.frame, len(frames) - 1)]
        s = sheet.scale
        dw, dh = sheet.cw * s, sheet.ch * s
        dx = round(self.gx - dw / 2)
        dy = round(self.gy - dh)
        cr.save()
        cr.translate(dx, dy)
        cr.scale(s, s)
        Gdk.cairo_set_source_pixbuf(cr, pb, 0, 0)
        cr.get_source().set_filter(cairo.FILTER_NEAREST)  # crisp pixels
        cr.paint()
        cr.restore()
        self._draw_hearts(cr)

    def _draw_hearts(self, cr):
        if self.heart_pixbuf is None and os.path.exists(self._heart_path):
            try:
                self.heart_pixbuf = GdkPixbuf.Pixbuf.new_from_file(self._heart_path)
            except GLib.Error as error:
                print(f"pet: couldn't load heart sprite: {error}", file=sys.stderr)
        if self.heart_pixbuf is None:
            return
        hearts = self.behavior.snapshot().hearts
        heart_scale = self.size_percent / 100.0
        for heart in hearts:
            progress = heart.progress
            alpha = (
                1.0
                if heart.static or progress < 2 / 3
                else 3 * (1.0 - progress)
            )
            x = self.gx + heart.drift * 4 * progress - 3.5 * heart_scale
            y = (
                self.gy
                - self.sheet.ch * self.sheet.scale * 0.78
                - 18 * progress
                - 3.5 * heart_scale
            )
            cr.save()
            cr.translate(round(x), round(y))
            cr.scale(heart_scale, heart_scale)
            Gdk.cairo_set_source_pixbuf(cr, self.heart_pixbuf, 0, 0)
            cr.get_source().set_filter(cairo.FILTER_NEAREST)
            cr.paint_with_alpha(max(0.0, alpha))
            cr.restore()

# ---- environment integration (fullscreen), best-effort --------------------


def _niri_json(*args):
    try:
        out = subprocess.run(["niri", "msg", "--json", *args],
                             capture_output=True, text=True, timeout=2)
        if out.returncode != 0:
            return None
        return json.loads(out.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _niri_output_size():
    outs = _niri_json("outputs")
    if not isinstance(outs, dict):
        return None
    best = None
    for o in outs.values():
        m = o.get("logical") or {}
        w, h = m.get("width"), m.get("height")
        if w and h and (best is None or w * h > best[0] * best[1]):
            best = (w, h)
    return best


def start_fullscreen_watch(pet, apply_visibility):
    """Poll niri focused window; hide pet when a window fills the output."""
    if not shutil.which("niri"):
        return
    size = _niri_output_size()
    if size is None:
        return

    def poll():
        fw = _niri_json("focused-window")
        fs = False
        if isinstance(fw, dict):
            ws = (fw.get("layout") or {}).get("window_size")
            if isinstance(ws, list) and len(ws) == 2:
                fs = (ws[0], ws[1]) == size
        if fs and not pet.fullscreen_paused:
            pet.set_fullscreen_paused(True)
            apply_visibility()
        elif not fs and pet.fullscreen_paused:
            pet.set_fullscreen_paused(False)
            apply_visibility()
        return True

    GLib.timeout_add_seconds(1, poll)


def main():
    set_process_name("pixel-pet")
    with open(os.path.join(ASSETS, "manifest.json")) as f:
        manifest = json.load(f)
    store = SettingsStore()
    pet_name = store.get("pet")
    tracker = MouseTracker()
    keyboard = KeyboardTracker()
    pet = Pet(manifest, pet_name, tracker, keyboard, store.data)
    tracker.start()
    keyboard.start()

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
    }

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
        if pet.paused:
            win.set_visible(False)
            return
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
            pet.set_viewport(w, h)
            pet.draw(cr)

        area.set_draw_func(draw_func)

        # click-through everywhere except the pet's own bbox: empty input region
        # so the mouse passes to apps beneath, except over the sprite itself.
        # Re-applied whenever the surface is recreated (e.g. after a hide/show).
        def set_clickthrough():
            surface = win.get_surface()
            if surface is not None:
                surface.set_input_region(cairo.Region())
            return False

        state["set_clickthrough"] = set_clickthrough

        def update_input_region():
            # Click-through everywhere except the cat's actual (non-transparent)
            # pixels, so it can be grabbed while the rest of the screen passes
            # clicks through.
            if pet.W == 0 or pet.paused:
                return
            surface = win.get_surface()
            if surface is None:
                return
            sheet, state = pet.active_sprite()
            cw, ch = sheet.cw, sheet.ch
            s = sheet.scale
            dw, dh = cw * s, ch * s
            dx = round(pet.gx - dw / 2)
            dy = round(pet.gy - dh)
            frames = sheet.bboxes.get(state) or [(0, 0, cw, ch)]
            bx0, by0, bx1, by1 = frames[min(pet.frame, len(frames) - 1)]
            rx = max(0, round(dx + bx0 * s))
            ry = max(0, round(dy + by0 * s))
            rw = min(round((bx1 - bx0) * s), pet.W - rx)
            rh = min(round((by1 - by0) * s), pet.H - ry)
            if rw > 0 and rh > 0:
                rect = cairo.RectangleInt(int(rx), int(ry), int(rw), int(rh))
                surface.set_input_region(cairo.Region(rect))

        # Press origin locks the interaction: head rubs pet the cat; body motion
        # drags it with the existing offset-locked positioning behavior.
        def on_drag_begin(gesture, start_x, start_y):
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            pet.begin_pointer_interaction(start_x, start_y, time.monotonic())

        def on_drag_update(gesture, offset_x, offset_y):
            ok, start_x, start_y = gesture.get_start_point()
            if not ok:
                return
            pet.move_pointer_interaction(
                start_x + offset_x,
                start_y + offset_y,
                time.monotonic(),
            )
            area.queue_draw()

        def on_drag_end(gesture, offset_x, offset_y):
            was_drag = pet._interaction_target == "drag"
            pet.end_pointer_interaction(time.monotonic())
            if was_drag:
                pet.cancel_typing()  # discard every key observed during drag
                try:
                    store.update("position", pet.normalized_position())
                except OSError as error:
                    print(f"pet: couldn't save position: {error}", file=sys.stderr)

        drag = Gtk.GestureDrag.new()
        drag.connect("drag-begin", on_drag_begin)
        drag.connect("drag-update", on_drag_update)
        drag.connect("drag-end", on_drag_end)
        area.add_controller(drag)

        def tick():
            now = time.monotonic()
            gtk_settings = Gtk.Settings.get_default()
            if gtk_settings is not None:
                pet.behavior.reduced_motion_changed(
                    not gtk_settings.get_property("gtk-enable-animations"),
                    at=now,
                )
            if pet.paused:        # fullscreen app: freeze, skip clock + redraw
                pet.cancel_typing()  # discard keys pressed while hidden
                pet._last = now
                return True
            dt = min(0.05, now - pet._last)
            pet._last = now
            pet.update(dt)
            area.queue_draw()
            update_input_region()
            return True

        GLib.timeout_add(1000 // 30, tick)

        apply_overlay_visibility()
        start_fullscreen_watch(pet, apply_overlay_visibility)
        return win

    def ensure_controller():
        controller = state["controller"]
        if controller is None:
            controller = PetController(
                app, pet, store, tracker, keyboard,
                os.path.join(HERE, "run-pet.sh"),
                apply_overlay_visibility,
            )
            state["controller"] = controller
        return controller

    def on_activate(_app):
        create_overlay()
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
    app.run(sys.argv)


if __name__ == "__main__":
    main()
