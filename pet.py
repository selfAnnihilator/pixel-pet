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
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gtk, Gdk, GdkPixbuf, GLib, Gtk4LayerShell as LayerShell
import cairo
import json
import os
import random
import shutil
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")
SCALE = int(os.environ.get("PET_SCALE", "4"))
IDLE_SEC = int(os.environ.get("PET_IDLE_SEC", "180"))  # AFK -> sleep after this many seconds

# Behavior tuning.
SIT_MIN, SIT_MAX = 5.0, 12.0      # seconds to hold a sit
WALK_MIN = 2.5                    # keep walking at least this long before settling
MEOW_DUR = 1.0                    # seconds the meow (anim + dialog) stays up
FIDGET_CHANCE = 0.4                # odds a given sit includes a mid-sit fidget
REACT_POOL = ["sit", "react_l", "react_r", "react_land"]  # drop outcome, picked uniformly
SLEEP_POOL = ["flop", "sleep1", "sleep2", "sleep3", "sleep4", "meow_sit2", "meow_lie"]  # AFK pose, picked once per nap


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
    def __init__(self, manifest, pet_name):
        self.manifest = manifest
        self.sheets = {n: Sheet(d) for n, d in manifest["pets"].items()}
        self.name = pet_name if pet_name in self.sheets else manifest["defaultPet"]
        self.sheet = self.sheets[self.name]

        self.gx = 0.0          # ground anchor x (feet, screen px)
        self.gy = 0.0          # ground anchor y (feet, screen px)
        self.facing_left = False
        self.state = "idle"    # animation row currently playing
        self.frame = 0
        self.frame_clock = 0.0
        self.hold = False      # freeze on one frame (sit poses are distinct, not a loop)

        self.action = None     # high-level: walk / sit / groom / sleep
        self.action_start = 0.0
        self.sit_dur = SIT_MAX
        self.tx = self.ty = 0.0   # walk target
        self.afk = False
        self.paused = False    # fullscreen app present: hide + freeze
        self.forced_sleep = False  # right-click: sleep + stop moving until woken
        self._pre_meow_action = None  # action to resume once a meow finishes
        self.dragging = False
        self._drag_dx = self._drag_dy = 0.0
        self._fidgeting = False        # mid-sit head-turn/blink fidget playing
        self._fidget_at = None         # monotonic time the next fidget should start
        self._fidget_end = 0.0
        self._sit_pose_frame = 0       # held idle frame to return to after a fidget
        self.W = self.H = 0
        self._last = time.monotonic()
        self._children = []    # spawned helper procs to reap on exit

    # ---- behavior -------------------------------------------------------
    def set_viewport(self, w, h):
        first = self.W == 0
        self.W, self.H = w, h
        if first:
            self.gx, self.gy = w * 0.7, h * 0.8
            self.enter_action("sit")
        self._clamp()

    def _clamp(self):
        dw, dh = self.sheet.cw * SCALE, self.sheet.ch * SCALE
        self.gx = max(dw / 2, min(self.gx, self.W - dw / 2))
        self.gy = max(dh, min(self.gy, self.H))

    def enter(self, state):
        self.state = state
        self.frame = 0
        self.frame_clock = 0.0
        self.hold = False

    # non-walk action -> animation row (walk picks a directional row, see _walk_state)
    _ANIM = {"sit": "idle", "sleep": "flop",
              "react_l": "react_l", "react_r": "react_r", "react_land": "react_land"}

    def enter_action(self, name):
        self.action = name
        self.action_start = time.monotonic()
        if name == "walk":
            self._pick_target()
            st, self.facing_left = self._walk_state(self.tx - self.gx,
                                                    self.ty - self.gy)
            self.enter(st)
        elif name == "sleep":
            # one random pose per nap; holds/loops until woken (no reroll mid-sleep)
            self.enter(random.choice(SLEEP_POOL))
        else:
            self.enter(self._ANIM[name])
            if name == "sit":
                self.sit_dur = random.uniform(SIT_MIN, SIT_MAX)
                self.frame = self._sit_frame()  # one calm pose, held (no rotating)
                self.hold = True
                self._sit_pose_frame = self.frame
                self._fidgeting = False
                # fidget sprite is a front-facing head-turn; skip it on the
                # back-facing sit pose (frame 1) where no face is visible
                self._fidget_at = (
                    self.action_start + random.uniform(0.3, 0.7) * self.sit_dur
                    if self.frame != 1 and random.random() < FIDGET_CHANCE
                    else None
                )
            elif name in ("react_l", "react_r", "react_land"):
                # hold/loop the reaction for the same dwell a sit would get
                self.sit_dur = random.uniform(SIT_MIN, SIT_MAX)

    def _sit_frame(self):
        # idle row holds several *distinct* poses; only keep the upright sits
        n = len(self.sheet.frames["idle"])
        cands = [i for i in (0, 1, 4, 5) if i < n] or list(range(n))
        return random.choice(cands)

    def _walk_state(self, dx, dy):
        """Pick a directional walk row from the heading. Returns (state, flip_left).

        side = horizontal (row1), front/back = vertical, front-diagonal (row3)
        for sharp down-diagonals. Pets without the directional rows fall back to
        plain 'walk'."""
        left = dx < 0
        adx, ady = abs(dx), abs(dy)
        if "walk_fd" not in self.sheet.frames:
            return "walk", left
        if ady <= 0.4 * adx:                 # ~horizontal -> straight side walk
            return "walk", left
        if adx <= 0.4 * ady:                 # ~vertical
            return ("walk_front" if dy > 0 else "walk_back"), left
        # sharp diagonal: front-3/4 going down, back-3/4 going up
        return ("walk_fd" if dy > 0 else "walk_back"), left

    def _pick_target(self):
        dw, dh = self.sheet.cw * SCALE, self.sheet.ch * SCALE
        xmin, xmax = dw / 2, self.W - dw / 2
        ymin, ymax = dh, self.H
        tx, ty = self.gx, self.gy
        for _ in range(10):  # want a target far enough to enforce a real walk
            tx = random.uniform(xmin, xmax)
            ty = random.uniform(ymin, ymax)
            if ((tx - self.gx) ** 2 + (ty - self.gy) ** 2) ** 0.5 > 250:
                break
        self.tx, self.ty = tx, ty

    def choose_next(self):
        # alternate walk <-> sit (this art pack has no groom animation)
        nxt = "sit" if self.action == "walk" else "walk"
        self.enter_action(nxt)

    def trigger_meow(self):
        """Click reaction: play meow or hiss (never the drop-only 'sad'), then resume prior action."""
        if self.action == "meow" or self.paused:
            return
        self._pre_meow_action = self.action or "sit"
        self.action = "meow"
        self.action_start = time.monotonic()
        self.enter(random.choice(["meow", "react_l", "react_r"]))

    def _exit_meow(self):
        self.enter_action(self._pre_meow_action or "sit")

    def force_sleep(self):
        """Right-click: nap in place (random pose) until woken by a left-click or drag."""
        if self.paused:
            return
        self.forced_sleep = True
        self.enter_action("sleep")

    def wake(self):
        """Left-click or drag while forced-asleep: end the nap, resume normal behavior."""
        self.forced_sleep = False
        self.enter_action("sit")

    def start_drag(self):
        """Mouse-drag begins: freeze normal behavior, switch to the dangle sprite."""
        if self.paused:
            return
        self.forced_sleep = False
        self.action = "drag"
        self.dragging = True
        self.action_start = time.monotonic()
        self.enter("drag")

    def end_drag(self):
        # hand off from the held first half straight into the second half;
        # frame is already sitting at the halfway point, just let it keep going
        self.dragging = False
        self.action = "drop"
        self.frame_clock = 0.0

    def update(self, dt):
        now = time.monotonic()

        # dragging: animate the "drag" row up to its halfway frame and hold there
        # while held; on release (see end_drag) action becomes "drop" and we play
        # out the remaining half once, then always settle into a sit (dwelling at
        # the drop spot for a while) rather than resuming whatever was running
        # before the grab.
        if self.action in ("drag", "drop"):
            a = self.sheet.anim("drag")
            half = max(1, a["frames"] // 2)
            dangle_lo, dangle_hi = half - 1, a["frames"] - half  # middle "dangling" frames
            dur = 1.0 / a["fps"]
            self.frame_clock += dt
            if self.action == "drag":
                while self.frame_clock >= dur:
                    self.frame_clock -= dur
                    if self.frame < dangle_lo:
                        self.frame += 1
                    else:
                        # reached the held pose: loop the dangle frames while grabbed
                        self.frame = self.frame + 1 if self.frame < dangle_hi else dangle_lo
            else:
                cap = a["frames"] - 1
                while self.frame_clock >= dur and self.frame < cap:
                    self.frame_clock -= dur
                    self.frame += 1
                if self.frame >= cap:
                    self.enter_action(random.choice(REACT_POOL))
            return

        a = self.sheet.anim(self.state)
        # advance animation frames
        self.frame_clock += dt
        dur = 1.0 / a["fps"]
        ended = False
        while not self.hold and self.frame_clock >= dur:
            self.frame_clock -= dur
            self.frame += 1
            if self.frame >= a["frames"]:
                if a["loop"]:
                    self.frame = 0
                else:
                    self.frame = a["frames"] - 1
                    ended = True

        # meow reaction takes priority and freezes movement while it plays
        if self.action == "meow":
            if now - self.action_start >= MEOW_DUR:
                self._exit_meow()
            return

        # mode: AFK -> sleep and hold; on wake -> sit
        if self.afk:
            if self.action != "sleep":
                self.enter_action("sleep")
            return
        if self.action == "sleep" and not self.forced_sleep:
            self.enter_action("sit")
            return
        if self.forced_sleep:
            return

        # active behavior with dwell
        if self.action == "walk":
            dx, dy = self.tx - self.gx, self.ty - self.gy
            dist = (dx * dx + dy * dy) ** 0.5
            step = 70 * (SCALE / 4) * dt
            if dist <= step or dist < 2:
                self.gx, self.gy = self.tx, self.ty
                if now - self.action_start >= WALK_MIN:
                    self.enter_action("sit")
            else:
                # heading is constant to a fixed target, so the directional row
                # is stable; only switch state if it actually changed (no stutter)
                st, self.facing_left = self._walk_state(dx, dy)
                if st != self.state:
                    self.enter(st)
                self.gx += step * dx / dist
                self.gy += step * dy / dist
            self._clamp()
        elif self.action == "sit":
            if not self._fidgeting and self._fidget_at and now >= self._fidget_at:
                self._fidgeting = True
                self.enter("fidget")
                fa = self.sheet.anim("fidget")
                self._fidget_end = now + fa["frames"] / fa["fps"]
            elif self._fidgeting and now >= self._fidget_end:
                self._fidgeting = False
                self.enter("idle")
                self.frame = self._sit_pose_frame
                self.hold = True
            if now - self.action_start >= self.sit_dur:
                self.choose_next()
        elif self.action in ("react_l", "react_r", "react_land"):
            if now - self.action_start >= self.sit_dur:
                self.enter_action("sit")

    # ---- rendering ------------------------------------------------------
    def draw(self, cr):
        frames = self.sheet.frames[self.state]
        pb = frames[min(self.frame, len(frames) - 1)]
        cw, ch = self.sheet.cw, self.sheet.ch
        dw, dh = cw * SCALE, ch * SCALE
        dx = round(self.gx - dw / 2)
        dy = round(self.gy - dh)
        flip = self.facing_left and self.sheet.faces_right
        cr.save()
        if flip:
            cr.translate(dx + dw, dy)
            cr.scale(-SCALE, SCALE)
        else:
            cr.translate(dx, dy)
            cr.scale(SCALE, SCALE)
        Gdk.cairo_set_source_pixbuf(cr, pb, 0, 0)
        cr.get_source().set_filter(cairo.FILTER_NEAREST)  # crisp pixels
        cr.paint()
        cr.restore()

        if self.state == "meow":
            self._draw_bubble(cr, dx + dw / 2, dy, "meow~")
        elif self.state in ("react_l", "react_r"):
            self._draw_bubble(cr, dx + dw / 2, dy, "hsss!")

    def _draw_bubble(self, cr, head_x, head_top_y, text):
        """Small speech-bubble sprite drawn on top, since the art pack has none."""
        bw, bh = 13 * SCALE, 9 * SCALE
        gap = max(2, SCALE // 2)
        bx = round(head_x - bw / 2)
        by = round(head_top_y - bh - gap - SCALE)
        tail = 4 * SCALE / 4

        cr.save()
        cr.set_source_rgba(1, 1, 1, 0.95)
        cr.rectangle(bx, by, bw, bh)
        cr.fill()
        cr.move_to(head_x - tail, by + bh)
        cr.line_to(head_x + tail, by + bh)
        cr.line_to(head_x, by + bh + tail)
        cr.close_path()
        cr.fill()

        cr.set_source_rgba(0, 0, 0, 0.85)
        cr.set_line_width(max(1, SCALE / 4))
        cr.rectangle(bx, by, bw, bh)
        cr.stroke()

        cr.select_font_face("monospace", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(12 * SCALE / 4)
        ext = cr.text_extents(text)
        cr.move_to(bx + (bw - ext.width) / 2 - ext.x_bearing,
                   by + (bh - ext.height) / 2 - ext.y_bearing)
        cr.show_text(text)
        cr.restore()


# ---- environment integration (AFK + fullscreen), all best-effort ----------

def start_afk_watch(pet):
    """swayidle -> set pet.afk on IDLE/ACTIVE. No swayidle => pet never sleeps."""
    if not shutil.which("swayidle"):
        print("pet: swayidle not found; AFK sleep disabled", file=sys.stderr)
        return
    try:
        proc = subprocess.Popen(
            ["swayidle", "-w",
             "timeout", str(IDLE_SEC), 'printf "IDLE\\n"',
             "resume", 'printf "ACTIVE\\n"'],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    except OSError as e:
        print(f"pet: swayidle failed: {e}", file=sys.stderr)
        return
    pet._children.append(proc)

    def set_afk(v):
        pet.afk = v
        return False

    def reader():
        for line in proc.stdout:
            s = line.strip()
            if s == "IDLE":
                GLib.idle_add(set_afk, True)
            elif s == "ACTIVE":
                GLib.idle_add(set_afk, False)

    threading.Thread(target=reader, daemon=True).start()


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


def start_fullscreen_watch(pet, win, set_clickthrough):
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
        if fs and not pet.paused:
            pet.paused = True
            win.set_visible(False)
        elif not fs and pet.paused:
            pet.paused = False
            win.present()
            set_clickthrough()
        return True

    GLib.timeout_add_seconds(1, poll)


def main():
    pet_name = "cat"
    if "--pet" in sys.argv:
        i = sys.argv.index("--pet")
        if i + 1 < len(sys.argv):
            pet_name = sys.argv[i + 1]

    with open(os.path.join(ASSETS, "manifest.json")) as f:
        manifest = json.load(f)
    pet = Pet(manifest, pet_name)

    app = Gtk.Application(application_id="com.abhi.pixelpet")

    def on_activate(a):
        win = Gtk.ApplicationWindow(application=a)
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
        css = Gtk.CssProvider()
        css.load_from_data(b"window, drawingarea { background: transparent; }")
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

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

        def update_input_region():
            if pet.W == 0 or pet.paused:
                return
            surface = win.get_surface()
            if surface is None:
                return
            cw, ch = pet.sheet.cw, pet.sheet.ch
            dw, dh = cw * SCALE, ch * SCALE
            dx = round(pet.gx - dw / 2)
            dy = round(pet.gy - dh)
            # tight click area: only the sprite's actual (non-transparent)
            # pixels for the current state/frame, not the whole padded cell
            frames = pet.sheet.bboxes.get(pet.state) or [(0, 0, cw, ch)]
            bx0, by0, bx1, by1 = frames[min(pet.frame, len(frames) - 1)]
            if pet.facing_left and pet.sheet.faces_right:
                bx0, bx1 = cw - bx1, cw - bx0  # mirror to match the flipped draw
            rx = max(0, round(dx + bx0 * SCALE))
            ry = max(0, round(dy + by0 * SCALE))
            rw = min(round((bx1 - bx0) * SCALE), pet.W - rx)
            rh = min(round((by1 - by0) * SCALE), pet.H - ry)
            if rw > 0 and rh > 0:
                rect = cairo.RectangleInt(int(rx), int(ry), int(rw), int(rh))
                surface.set_input_region(cairo.Region(rect))

        # single GestureDrag handles both: a short press-release (no real motion)
        # is treated as a click -> meow; crossing DRAG_THRESH px starts a real drag
        # that follows the cursor and shows the "drag" sprite until release.
        DRAG_THRESH = 6

        def on_drag_begin(gesture, start_x, start_y):
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)

        def on_drag_update(gesture, offset_x, offset_y):
            ok, start_x, start_y = gesture.get_start_point()
            if not ok:
                return
            if not pet.dragging:
                if (offset_x ** 2 + offset_y ** 2) ** 0.5 < DRAG_THRESH:
                    return
                pet.start_drag()
                pet._drag_dx = pet.gx - start_x
                pet._drag_dy = pet.gy - start_y
            pet.gx = start_x + offset_x + pet._drag_dx
            pet.gy = start_y + offset_y + pet._drag_dy
            pet._clamp()
            area.queue_draw()

        def on_drag_end(gesture, offset_x, offset_y):
            if pet.dragging:
                pet.end_drag()
            elif pet.forced_sleep:
                pet.wake()
            else:
                pet.trigger_meow()

        drag = Gtk.GestureDrag.new()
        drag.connect("drag-begin", on_drag_begin)
        drag.connect("drag-update", on_drag_update)
        drag.connect("drag-end", on_drag_end)
        area.add_controller(drag)

        def on_right_click(gesture, n_press, x, y):
            pet.force_sleep()

        right_click = Gtk.GestureClick.new()
        right_click.set_button(Gdk.BUTTON_SECONDARY)
        right_click.connect("released", on_right_click)
        area.add_controller(right_click)

        def tick():
            now = time.monotonic()
            if pet.paused:        # fullscreen app: freeze, skip clock + redraw
                pet._last = now
                return True
            dt = min(0.05, now - pet._last)
            pet._last = now
            pet.update(dt)
            area.queue_draw()
            update_input_region()
            return True

        GLib.timeout_add(1000 // 30, tick)

        win.present()
        set_clickthrough()

        start_afk_watch(pet)
        start_fullscreen_watch(pet, win, set_clickthrough)

    def on_shutdown(a):
        for p in pet._children:
            try:
                p.terminate()
            except OSError:
                pass

    app.connect("activate", on_activate)
    app.connect("shutdown", on_shutdown)
    app.run(None)


if __name__ == "__main__":
    main()
