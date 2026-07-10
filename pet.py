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
import glob
import json
import math
import os
import random
import select
import shutil
import struct
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

# Mouse-tracking tuning.
MOVE_TIMEOUT = 0.18   # cursor counts as "moving" for this long after last motion event
DEADZONE = 24         # cursor within this many px of the cat center -> look straight
# Frame layout of the tracking sheet: 0=straight, then 8 compass directions
# starting at up (N) and going clockwise. Index by 45deg sector.
TRACK_DIR_FRAMES = [1, 2, 3, 4, 5, 6, 7, 8]  # N, NE, E, SE, S, SW, W, NW

# Drag/wobble tuning. The drag sheet frames are 0=sit, 1=wobble-left,
# 2=no-wobble/middle, 3=wobble-right. While held we ping-pong middle<->sides;
# starting at index 0 of the sequence (frame 2) means "no wobble at first".
WOBBLE_SEQ = [2, 1, 2, 3]   # middle, left, middle, right (loops)
WOBBLE_FPS = 8
WOBBLE_MOVE_TIMEOUT = 0.12  # wobble only while the held cat is still being moved

# Keyboard typing tuning. Each physical keydown alternates the pressed paw; the
# pose remains pressed while any key stays held, then frame 0 gets a quiet hold.
TYPING_HOLD_DUR = 2.0


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
        if not self._open_devices():
            print("pet: no readable pointer devices in /dev/input "
                  "(need 'input' group); tracking disabled", file=sys.stderr)
            return
        threading.Thread(target=self._reader, daemon=True).start()

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
        if not self._open_devices():
            print("pet: no readable keyboard devices in /dev/input "
                  "(need 'input' group); typing disabled", file=sys.stderr)
            return
        threading.Thread(target=self._reader, daemon=True).start()

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
        self.scale = float(pet_def.get("scale", SCALE))  # per-pet on-screen pixel scale
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
    def __init__(self, manifest, pet_name, tracker=None, keyboard=None):
        self.manifest = manifest
        pet_defs = manifest["pets"]
        self.name = pet_name if pet_name in pet_defs else manifest["defaultPet"]
        self.sheet = Sheet(pet_defs[self.name])
        drag_def = pet_defs.get(self.name + "_drag")
        type_def = pet_defs.get(self.name + "_type")
        self.drag_sheet = Sheet(drag_def) if drag_def is not None else None
        self.type_sheet = Sheet(type_def) if type_def is not None else None
        self.tracker = tracker
        self.keyboard = keyboard

        self.gx = 0.0          # ground anchor x (feet, screen px)
        self.gy = 0.0          # ground anchor y (feet, screen px)
        self.facing_left = False
        self.state = "track"   # animation row currently playing
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
        self._wob_clock = 0.0          # wobble frame timer while dragging
        self._wob_i = 0                # index into WOBBLE_SEQ
        self._drag_moved_at = 0.0      # last time the held cat actually moved
        self._typing_visible = False   # typing sheet currently wins arbitration
        self._typing_until = 0.0       # end of the post-release Typing Hold
        self._typing_frame = 0
        self._type_next_left = True
        self._seen_key_serial = keyboard.press_serial if keyboard is not None else 0
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
        if self.tracker is not None:
            self.tracker.set_viewport(w, h)
        self._clamp()

    def _clamp(self):
        s = self.sheet.scale
        dw, dh = self.sheet.cw * s, self.sheet.ch * s
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

    def _cat_center(self):
        """Screen-space center of the drawn sprite (origin for the look vector)."""
        dh = self.sheet.ch * self.sheet.scale
        return self.gx, self.gy - dh / 2.0

    def _active(self):
        """(sheet, state) currently being shown: the held-pose sheet while
        dragging, then the typing companion sheet, otherwise normal tracking."""
        if self.dragging and self.drag_sheet is not None:
            return self.drag_sheet, "drag"
        if self._typing_visible and self.type_sheet is not None:
            return self.type_sheet, "type"
        return self.sheet, self.state

    def cancel_typing(self):
        """Consume pending typing state so it cannot reappear after an override."""
        if self.keyboard is not None:
            self._seen_key_serial = self.keyboard.press_serial
        self._typing_visible = False
        self._typing_until = 0.0
        self._typing_frame = 0

    def _update_typing(self, now):
        """Apply key events and return True while typing owns the visible sprite."""
        keyboard = self.keyboard
        if keyboard is None or self.type_sheet is None:
            self._typing_visible = False
            return False

        serial = keyboard.press_serial
        if serial != self._seen_key_serial:
            count = serial - self._seen_key_serial
            self._seen_key_serial = serial
            for _ in range(max(0, count)):
                self._typing_frame = 1 if self._type_next_left else 3
                self._type_next_left = not self._type_next_left
            self._typing_until = 0.0
            self._typing_visible = True

        if not self._typing_visible:
            return False

        # Any held key freezes the current paw-down pose. A new physical keydown
        # changes paws above; kernel repeats leave this frame untouched.
        if keyboard.any_held():
            self.frame = self._typing_frame
            return True

        # Final key release ends the press immediately and starts Typing Hold.
        if self._typing_frame != 0:
            self._typing_frame = 0
            self._typing_until = keyboard.last_release + TYPING_HOLD_DUR

        if now >= self._typing_until:
            self._typing_visible = False
            self._typing_frame = 0
            return False

        # Pointer activity newer than the final release consumes Typing Hold.
        if (self.tracker is not None
                and self.tracker.last_motion > keyboard.last_release):
            self.cancel_typing()
            return False

        self.frame = 0
        return True

    def update(self, dt):
        # Being dragged: play the wobble. Start on the no-wobble frame, then
        # ping-pong middle<->left<->right for the whole duration of the hold.
        if self.dragging:
            self.cancel_typing()
            if self.drag_sheet is None:
                self.frame = 0
                return
            moving = (time.monotonic() - self._drag_moved_at) < WOBBLE_MOVE_TIMEOUT
            if not moving:
                # held still: settle on the no-wobble frame, ready to wobble
                # again from the middle on the next move
                self._wob_i = 0
                self._wob_clock = 0.0
                self.frame = WOBBLE_SEQ[0]
                return
            self._wob_clock += dt
            step = 1.0 / WOBBLE_FPS
            while self._wob_clock >= step:
                self._wob_clock -= step
                self._wob_i = (self._wob_i + 1) % len(WOBBLE_SEQ)
            self.frame = WOBBLE_SEQ[self._wob_i]
            return
        now = time.monotonic()
        if self._update_typing(now):
            return
        # Look toward the (virtual) cursor. Straight ahead when idle or when the
        # cursor sits on top of the cat; otherwise pick the matching compass frame.
        t = self.tracker
        if t is None or not t.moving():
            self.frame = 0
            return
        cx, cy = self._cat_center()
        dx, dy = t.vx - cx, t.vy - cy
        if (dx * dx + dy * dy) ** 0.5 <= DEADZONE:
            self.frame = 0
            return
        # angle measured clockwise from up (north); 0=N, 90=E, 180=S, 270=W
        ang = math.degrees(math.atan2(dx, -dy)) % 360.0
        sector = int((ang + 22.5) // 45) % 8
        self.frame = TRACK_DIR_FRAMES[sector]

    # ---- rendering ------------------------------------------------------
    def draw(self, cr):
        sheet, state = self._active()
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
            pet.cancel_typing()
            pet.paused = True
            win.set_visible(False)
        elif not fs and pet.paused:
            pet.paused = False
            win.present()
            set_clickthrough()
        return True

    GLib.timeout_add_seconds(1, poll)


def main():
    pet_name = None
    if "--pet" in sys.argv:
        i = sys.argv.index("--pet")
        if i + 1 < len(sys.argv):
            pet_name = sys.argv[i + 1]

    with open(os.path.join(ASSETS, "manifest.json")) as f:
        manifest = json.load(f)
    if pet_name is None:
        pet_name = manifest["defaultPet"]
    tracker = MouseTracker()
    keyboard = KeyboardTracker()
    pet = Pet(manifest, pet_name, tracker, keyboard)
    tracker.start()
    keyboard.start()

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
            # Click-through everywhere except the cat's actual (non-transparent)
            # pixels, so it can be grabbed while the rest of the screen passes
            # clicks through.
            if pet.W == 0 or pet.paused:
                return
            surface = win.get_surface()
            if surface is None:
                return
            sheet, state = pet._active()
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

        # GestureDrag on the cat's input region: press + move past DRAG_THRESH px
        # grabs the cat and it follows the cursor (offset-locked to the grab point)
        # until release. A plain click (no real motion) does nothing.
        def on_drag_begin(gesture, start_x, start_y):
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            # Pressing the cat picks it up immediately: show the held no-wobble
            # stand right away, even before any movement.
            pet.cancel_typing()
            pet.dragging = True
            pet._wob_i = 0          # start each grab on the no-wobble frame
            pet._wob_clock = 0.0
            pet._drag_moved_at = 0.0
            pet._drag_dx = pet.gx - start_x
            pet._drag_dy = pet.gy - start_y

        def on_drag_update(gesture, offset_x, offset_y):
            ok, start_x, start_y = gesture.get_start_point()
            if not ok:
                return
            nx = start_x + offset_x + pet._drag_dx
            ny = start_y + offset_y + pet._drag_dy
            if nx != pet.gx or ny != pet.gy:
                pet._drag_moved_at = time.monotonic()
            pet.gx, pet.gy = nx, ny
            pet._clamp()
            area.queue_draw()

        def on_drag_end(gesture, offset_x, offset_y):
            pet.cancel_typing()  # discard every key observed during this drag
            pet.dragging = False

        drag = Gtk.GestureDrag.new()
        drag.connect("drag-begin", on_drag_begin)
        drag.connect("drag-update", on_drag_update)
        drag.connect("drag-end", on_drag_end)
        area.add_controller(drag)

        def tick():
            now = time.monotonic()
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

        win.present()
        set_clickthrough()

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
