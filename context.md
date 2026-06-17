# Pixel Pet — Context

> Living status doc. **Update after every successful change.** Last updated: 2026-06-17 (tracking pet: draggable + fullscreen hide, per-pet scale)

## ⚠️ Maintenance rule (read first)
**This file MUST be updated after every successfully implemented change.** On each change:
1. Move the finished item from **To do / open** to **Done** (`[x]`).
2. Add any new follow-ups to **To do / open**.
3. Update **architecture / sprite-sheet / tuning** sections if they changed.
4. Bump the **Last updated** date above.
Do this as part of the change itself — not optional, not later.

## What it is
Pixel-art desktop companion (Comnyang-style cat) that lives on the screen as a
**screen-level overlay** — no window, no border, transparent, click-through,
workspace-independent. Roams in 2D, sits, sleeps when you're away.

## Architecture (current)
- **`pet.py`** — the implementation. GTK4 + PyGObject + Cairo, painting on a
  **wlr-layer-shell** OVERLAY surface (gtk4-layer-shell), anchored to all 4 edges =
  full-output. Click-through everywhere except the pet's own bbox (input region
  shrunk to that rect each tick) so the cat itself is clickable while the rest
  of the screen still passes clicks through. Pixel-art scaled with
  `FILTER_NEAREST`. A single `Gtk.GestureDrag` on the drawing area distinguishes
  click vs drag: press+release under `DRAG_THRESH` (6px) = `pet.trigger_meow()`;
  crossing that threshold = `pet.start_drag()`, which freezes the state machine
  and follows the cursor (offset-locked to where it was grabbed) until release
  (`pet.end_drag()` resumes whatever action was active before, same pattern as
  the meow freeze/resume).
- **`run-pet.sh`** — launcher. Sets `LD_PRELOAD=libgtk4-layer-shell.so` (must load
  before libwayland) then runs `pet.py`.
- **`assets/manifest.json` + `assets/cat/cat.png`** — sprite sheet + metadata.
- Electron build (`src/`, `electron-builder.yml`, etc.) is **dead/superseded** —
  kept for now, pending delete decision.

### Environment
niri 26.04, single output eDP-1 1920x1080, Wayland, Arch/cachyos.
Working dir: `/home/abhi/code/pixel-pet` (now a git repo, initialized 2026-06-16).

### Sprite sheet truth (rows were mislabeled by auto-segmenter)
cat.png 726x308, cell 66x28, 11 rows (most rows 9 cols, row9 `fidget` 11 cols —
sheet had to widen from 594→726 to fit row9's 11 frames; `pet.py` slices
purely from `row`+`frames` per anim, x=`frame*cellW`, no `cols` field used, so
unequal row widths are fine as long as the canvas is wide enough for the
widest row):
- row0 `idle` — 6 **distinct sit poses** (NOT a loop; hold one frame)
- row1 `walk` — side/horizontal walk (8)
- row2 `sleep` — (9) **unused now** — AFK plays `flop` (row8) instead; kept in
  the sheet/manifest in case wanted again
- row3 `walk_fd` — front-diagonal walk, ¾ toward viewer (6)
- row4 `walk_front` — straight-down walk, facing viewer (4)
- row5 `walk_back` — back walk, ¾ away (6)
- row6 `meow` — front-facing meow pose, 3 frames, not a loop (added; sourced from
  `assets/src/Free pack/cat 1.png` "meow stand" row, same gray palette as the rest)
- row7 `drag` — **replaced** the original lavender-sourced 4-frame loop with the
  **PICK UP** row (7 frames) from the gray source pack
  (`assets/src/Free pack/cat 16x16 with text.png` only has rows up through
  "on hind legs" — the PICK UP row itself came from a fuller copy of that same
  labeled reference at `/home/abhi/Documents/cat 16x16 with text.png`,
  458x1800, real alpha background, same gray palette as the rest of the sheet
  — no chroma-key/recolor needed this time). Sequence: sit(small) → sit(tall,
  alert) → dangle×3 (held by scruff, legs/tail hanging) → sit(tall) →
  sit(small). `manifest.json`'s `drag` entry is now `frames: 7` (was 4),
  `loop: false`. Unchanged: `pet.py`'s drag/drop logic caps the held phase at
  `frames // 2` = index 3, which now lands exactly on the middle dangle
  frame — still the right "held" pose, no code change needed, just the
  frame count bump.
  **Looping while held:** while `action == "drag"`, instead of stopping dead
  at the halfway frame, `Pet.update()` now plays forward into the dangle
  range (`dangle_lo..dangle_hi`, computed as `half-1 .. frames-half` — the
  middle 3 frames for a 7-frame anim) then loops within that range for as
  long as the drag continues, instead of holding one static frame. On
  release (`action == "drop"`), playback continues forward from wherever it
  currently is in the loop, through the remaining frames to the end, then
  `enter_action("sit")` as before.
- row8 `flop` — lounging/curled-up pose, 8 near-identical frames, loop (added;
  sourced from the bottom row of a second user-supplied lavender icon sheet,
  same chroma-key treatment as `drag`; now used for AFK instead of the old
  `sleep` row — see Done entry below). Recolored lavender→gray too.
- row9 `fidget` — head-turn/blink while sitting, 11 frames, not a loop (added;
  sourced from a third user-supplied lavender icon sheet — top row of two
  near-duplicate rows, same chroma-key + lavender→gray recolor as `drag`/`flop`)
- row10 `react_l`, row11 `react_r`, row12 `react_land` — **three separate**
  post-drop reactions (initially mis-extracted as one 5-frame sequence —
  corrected after the user pointed out the source sheet actually shows 3
  distinct animations stacked vertically: "hiss(l)" 2 frames, "hiss(r)" 2
  frames, and an unlabeled single-frame pose below them). Sourced from a 4th
  user-supplied checkerboard-bg sheet, chroma-keyed the same way; body/shade
  colors here were *already* near the game's gray palette — mapped exactly
  via a small color table: `96,98,115→98,103,115` (body),
  `66,68,84→65,71,82` (shade), `129,133,152→134,141,155` (lighter shade),
  `23,16,27→18,14,20` (outline), `192,107,155→202,113,159` (ear pink),
  `148,127,125→154,135,126` (nose), `213,207,222→98,103,115` (rare antialias
  blend pixel, mapped to body). Source frames were also notably **bigger**
  than every other row (33-42px wide, 31-36px tall vs. the rest of the
  sheet's ~18-22px cats) — downscaled 0.5x with `Image.NEAREST` after
  recoloring to match the established character size before
  centering/bottom-aligning into the 66x28 cell. `react_l`/`react_r` are
  2-frame one-shots (the mirrored hiss pair), `react_land` is a single
  static frame played once. Sheet grew 308→364px tall (+2 rows) to hold
  them as 3 independent rows instead of one mashed-together row.
  **Re-cropped after a clipping bug:** the first extraction's crop boxes
  for `tl`/`ml` cut off part of the cat (tail/legs got chopped at the
  box's left edge — visually confirmed: alpha touched all 4 edges of the
  crop, a giveaway the real art extends past it). Fixed by re-deriving
  exact boxes via flood-fill connected-component labeling on the alpha
  channel (no scipy available — wrote a small BFS by hand) instead of
  eyeballed coordinates: `tl` x10-52 (was x20-52), `ml` x8-50 (was x20-50);
  `tr`/`mr`/`bl` were already correct. Re-extracted/re-pasted all 5 frames
  with the corrected boxes.
- **Palette note:** `flop`/`fidget` (rows 8-9) source sprites came in a
  lavender/white palette (different from the rest of the gray sheet), making
  the cat visibly flash white. (`drag`/row7 *used to* be lavender-sourced too,
  but was replaced by a gray-palette PICK UP row — see row7 note above — so
  it no longer needs this fix.) Fixed by an exact-RGB recolor pass, mapping
  each lavender color to its gray-palette counterpart:
  `213,207,222→98,103,115` (body), `23,16,27→18,14,20` (outline),
  `180,170,193→65,71,82` (shade), `153,150,156→134,141,155` /
  `137,134,140→114,120,132` (lighter shades, fidget row only),
  `148,127,125→154,135,126` (nose), `192,107,155→202,113,159` /
  `213,142,191→223,148,195` (ear pink, two shades). Reuse this mapping for any
  future lavender-sourced rows. `react`/row10 needed its **own**, different
  mapping table (see row10 note above) — its source's native colors were
  already closer to gray, so exact RGB values differ slightly from this table.
- **No groom animation exists** in this pack.
- Source pack has more unused rows (eat, yawn, wash, itch, hiss, paw attack, on
  hind legs, plus 3 sleep poses each L/R) in `assets/src/Free pack/cat 1.png` if
  more states are wanted later — row/col pixel bands need re-deriving by
  alpha-band detection (no fixed grid; each row's frames are tightly trimmed).

## Done
- [x] **Tracking pet is draggable + hides on fullscreen, per-pet scale.**
      - **Drag:** input region restored to the cat's tight alpha bbox (current frame),
        rest of screen click-through. `Gtk.GestureDrag` past `DRAG_THRESH` (6px) grabs
        the cat, follows the cursor offset-locked until release. While `pet.dragging`,
        `update()` holds the straight frame and skips tracking.
      - **Fullscreen:** `start_fullscreen_watch` re-enabled (niri focused window_size ==
        output logical size → `pet.paused`, window hidden + tick frozen; un-fullscreen →
        reappears, click-through re-applied).
      - **Per-pet scale:** `Sheet.scale = pet_def["scale"]` (fallback `PET_SCALE`); live
        methods (`draw`/`_clamp`/`_cat_center`/input region) use `sheet.scale`. `catbone`
        set to `scale: 2` → 128px (was 256px at default ×4). Tweak in manifest.
- [x] **Mouse-tracking pet (`catbone`)** — new default pet. Cat looks toward the
      cursor. Sprite sheet `assets/catbone/track.png` (576×64 = nine 64×64 frames):
      frame 0 straight, frames 1–8 = compass directions starting at up (N) clockwise
      (N, NE, E, SE, S, SW, W, NW). `MouseTracker` reads relative motion from evdev
      pointer devices (`/dev/input/by-path/*-event-mouse`, needs `input` group),
      integrates it into a virtual cursor clamped to the output (re-syncs at edges),
      and flags "moving" for `MOVE_TIMEOUT` after the last motion. `Pet.update()` maps
      the cat→cursor angle (`atan2(dx,-dy)`, clockwise-from-north, 45° sectors) to a
      frame; straight when idle or cursor within `DEADZONE` of the cat. Surface stays
      fully click-through (no GTK pointer grab) — niri exposes no cursor-position API,
      hence evdev. Recommended `PET_SCALE=2` (64px native). Manifest `defaultPet=catbone`.
- [x] **Stripped to inert shell for new sprite work**: actions/auto-move/AFK/drag/
      right-click all disabled (now superseded by tracking). Old action code left in
      `Pet` (dead) for reference; gestures + AFK/fullscreen watches stay disabled.
- [x] Pivoted Electron → GTK4 layer-shell (true borderless transparent screen overlay).
- [x] Single sprite, click-through, workspace-independent, spans whole output.
- [x] Behavior state machine: walk ↔ sit with dwell (hold poses, no spam).
- [x] Sit holds **one** idle pose (fixed the "rotating while sitting" bug).
- [x] 2D free movement (roams anywhere incl. upward), sprite clamped on-screen.
- [x] AFK → sleep via `swayidle` (threshold `PET_IDLE_SEC`, default 180s); wake → sit.
- [x] Fullscreen app → pet hides + freezes (niri heuristic: focused window_size ==
      output logical size); un-fullscreen → reappears.
- [x] Tick gating (no update/redraw while paused); child procs reaped on exit.
- [x] **Directional walk sprites** by heading: horizontal→side, sharp down-diag→
      `walk_fd`, up→`walk_back`, straight down→`walk_front`. Sprite chosen once per
      walk (stable, no stutter).
- [x] Dropped groom from behavior (no groom asset in pack).
- [x] **Clickable pet → meow.** Surface is click-through everywhere except a
      per-frame-updated input-region rect matching the pet's current bbox
      (`update_input_region()` in `pet.py`, recomputed every tick from
      `gx/gy`). A `Gtk.GestureClick` on that rect calls `pet.trigger_meow()`:
      freezes current action, plays the new `meow` row once, draws a small
      cairo-drawn speech-bubble ("meow~", no bubble asset exists in the pack)
      above the head for `MEOW_DUR` (1s), then resumes whatever it was doing
      (`_exit_meow` → `enter_action(prev)`). Bubble box stays 13x9 cells
      (`bw,bh` in `_draw_meow_bubble`); font bumped to `12 * SCALE / 4` (was 6)
      to read clearly — text is allowed to crowd/overflow the box slightly
      rather than shrinking the bubble.
- [x] **Draggable pet.** `Gtk.GestureDrag` on the drawing area; under
      `DRAG_THRESH` px of motion on release it's a click (meow), past it
      `pet.start_drag()` fires: action freezes to `"drag"`, sprite switches to
      the new `drag` row and position is driven directly from the cursor
      (locked to the grab offset so the cat doesn't jump under the pointer)
      every `drag-update`. Release → `pet.end_drag()` resumes whatever action
      was running before the grab. Sprite for this row came from a
      user-supplied lavender/white sitting-cat image, not the gray source
      pack — see sprite-sheet truth section for the chroma-key note.
      **Split-halfway animation:** the 4-frame `drag` row plays only its first
      half (frame 0→1, the halfway point) while held, then holds there for as
      long as the drag continues — it does **not** loop. On release, action
      becomes `"drop"` (still sprite row `"drag"`) and frames 1→3 play out
      once, then `enter_action(pre_drag_action)` resumes normal behavior.
      Both phases are handled in a dedicated branch at the top of
      `Pet.update()` (`if self.action in ("drag", "drop")`), bypassing the
      generic loop/hold frame-advance used by every other state. `loop` in
      `manifest.json`'s `drag` entry is unused by this path (kept `false` for
      clarity) — frame capping is computed from `frames // 2`, not the
      manifest loop flag. After the drop animation finishes it always
      `enter_action("sit")` (normal `SIT_MIN..SIT_MAX` dwell) at the drop
      spot, regardless of what it was doing before the grab — removed
      `_pre_drag_action` entirely since it's no longer needed.
- [x] **Flop sprite for AFK/sleep.** `Pet._ANIM["sleep"]` now points at the new
      `flop` row instead of the old `sleep` row — `enter_action("sleep")`
      (triggered by the swayidle AFK watcher) plays it as a normal looping
      animation, no special-casing needed. Old `sleep` row/anim left in
      `cat.png`/`manifest.json` untouched, just no longer referenced.
- [x] **Mid-sit fidget.** Each time `enter_action("sit")` runs there's a
      `FIDGET_CHANCE` (0.4) odds of scheduling a fidget at a random point
      30-70% through the sit (`self._fidget_at`) — but only if the chosen sit
      pose isn't idle-row frame 1 (the back-facing pose with no visible face);
      `fidget` is a front-facing head-turn/blink so it's skipped there.
      `update()`'s `sit` branch checks for that time, swaps to the new
      `fidget` row (11-frame head-turn/blink, plays once), then on completion
      (`_fidget_end`, computed from `frames/fps`) reverts to `idle` at the
      same held pose frame (`_sit_pose_frame`) it started from — the overall
      sit dwell (`sit_dur`) is unaffected by the fidget happening.
- [x] **Random react-on-drop (3 distinct reactions + sit).** Three new rows
      (10/11/12, see sprite-sheet truth: `react_l`, `react_r`, `react_land`)
      + matching `_ANIM` entries. On drop completion (frame reaches cap in
      the `drag`/`drop` branch of `update()`), `REACT_POOL =
      ["sit","react_l","react_r","react_land"]` is sampled uniformly via
      `random.choice` — so a drop has a 1-in-4 chance of going straight to
      `sit` and an even 1-in-4 chance each of playing one of the 3 reaction
      clips first. New `elif self.action in ("react_l","react_r",
      "react_land"):` branch just waits for the shared `ended` flag then
      calls `enter_action("sit")` for all three — no bespoke timing code,
      reuses the generic frame-advance/`ended` mechanism already used by
      `sit`/`sleep`. Verified via 200-trial headless sim: all 4 outcomes hit
      roughly evenly, every trial still ends in `sit` with its normal
      `SIT_MIN..SIT_MAX` dwell (sit isn't shortened or skipped by this).
      **Hold/loop while reacting:** `react_l`/`react_r` manifest entries are
      now `loop: true` (were `false`) so the generic frame-advance loops
      their 2 frames continuously for as long as the reaction lasts, instead
      of freezing after one pass. All 3 reactions now get their own dwell —
      `enter_action()` sets `self.sit_dur = random.uniform(SIT_MIN,
      SIT_MAX)` for them too (same field/same range as a real sit, just
      reused) — and `update()`'s `elif self.action in ("react_l","react_r",
      "react_land"):` branch now waits for that dwell to elapse
      (`now - action_start >= self.sit_dur`) before `enter_action("sit")`,
      instead of the old `ended`-flag check (which doesn't fire at all for
      a looping anim, and fired almost instantly for the 1-frame
      `react_land`). Verified via a fake-clock headless test: held duration
      for all 3 falls within 5-12s, matching `sit`'s own dwell range.
- [x] **Hiss dialogue.** Renamed `_draw_meow_bubble` → `_draw_bubble(cr, x, y,
      text)` (now takes the text instead of hardcoding `"meow~"`) so it can
      be reused. `draw()` now also calls it for `react_l`/`react_r` with
      `"hsss!"` — shows for as long as the hiss reaction holds (its
      `sit_dur`-length dwell, not `MEOW_DUR`). `react_land` gets no bubble
      (no dialogue makes sense for a silent pose).
- [x] **Dynamic (tight) click area.** The clickable/draggable hit-region used
      to always be the full 66x28 cell scaled up — way bigger than the
      actual cat, since most rows (especially the small `react_*` ones)
      only fill a fraction of the cell. `Sheet.__init__` now also computes
      `self.bboxes[state][frame]` — a tight `(x0,y0,x1,y1)` alpha bounding
      box per frame, via a new `_alpha_bbox()` helper that reads
      `GdkPixbuf`'s raw pixel buffer directly (no PIL dependency at
      runtime). `update_input_region()` (in `pet.py`'s `on_activate`) now
      builds the input-region rect from that bbox (mirrored when
      `facing_left`) instead of the whole cell, so the click/drag-catching
      area now hugs just the visible sprite pixels for whatever
      state/frame is currently showing, and shrinks/grows with it
      automatically as the animation plays.
- [x] **Click can hiss, never sad.** A simple click used to always play
      `meow`; now `trigger_meow()` calls
      `self.enter(random.choice(["meow", "react_l", "react_r"]))` instead of
      always `self.enter("meow")` — `self.action` stays `"meow"` as the
      shared freeze/resume sentinel (unchanged `MEOW_DUR`/`_exit_meow()`
      timing, resumes whatever the pet was doing before the click), only the
      sprite row varies. `react_land` ("sad") is deliberately excluded from
      this pool — it stays exclusive to the drop-outcome `REACT_POOL`, never
      reachable from a click. `draw()`'s bubble dispatch switched from
      keying off `self.action` (now always `"meow"` regardless of which
      sprite plays) to `self.state`, so "meow~"/"hsss!" still show on the
      right sprite. Verified via a fake-clock headless test: 500 simulated
      clicks produced only `{meow, react_l, react_r}`, never `react_land`.
- [x] **AFK sleep gets a random pose pool.** Was always the same `flop` row.
      Added 6 new sprite rows (13-18 in `cat.png`, now 19 rows /
      726x532) extracted from `assets/src/Free pack/cat 1.png`: `sleep1`-
      `sleep4` (2-frame loops) and `meow_sit2`/`meow_lie` (3-frame loops,
      borrowed from the source pack's meow block — just restful poses, not
      tied to the meow sound/dialogue). Source boxes found via the same
      hand-written BFS alpha-flood-fill technique as the earlier hiss/sad
      clipping fix (no scipy available). Scale confirmed 1:1 against the
      existing sheet (source REST block's first frame bbox 18x18 == cat.png
      idle row's frame bbox 18x18, no resize needed). The source's `(l)`/
      `(r)` row pairs (e.g. `sleep1 (l)` vs `sleep1 (r)`) are exact pixel
      mirrors of each other (confirmed via `ImageChops.difference` on a
      flipped copy → empty bbox) — only the canonical right-facing frames
      were extracted; runtime mirroring on `facing_left` (already used by
      every other state) covers the left-facing case for free, so no `_l`/
      `_r` sprite-row duplication was needed here (unlike `react_l`/
      `react_r`, which use genuinely different art per direction).
      `manifest.json` got 6 new `anims` entries, all `loop: true` so each
      pose loops continuously for as long as the nap lasts. New
      `SLEEP_POOL = ["flop", "sleep1", "sleep2", "sleep3", "sleep4",
      "meow_sit2", "meow_lie"]` (kept the original `flop` in the mix).
      `enter_action()` got a new `elif name == "sleep":` branch ahead of the
      generic `else` branch: `self.enter(random.choice(SLEEP_POOL))` instead
      of the old `self.enter(self._ANIM["sleep"])` (`_ANIM["sleep"] →
      "flop"` entry now unused but harmless, left in place). `self.action`
      still stays `"sleep"` regardless of which pose was rolled, so the
      existing AFK-exit check in `update()` (`if self.action == "sleep":
      enter_action("sit")`) needed no changes — pose is rolled once per nap
      (no reroll while still AFK) and persists till wake, then a fresh nap
      rerolls independently. Verified via headless test: 500 simulated naps
      produced poses only from `SLEEP_POOL`, and all 7 entries were each
      reachable at least once.
- [x] **Right-click forces a nap in place.** New `Gtk.GestureClick` on
      `area`, restricted to `Gdk.BUTTON_SECONDARY`, calls `pet.force_sleep()`
      on `"released"`. `force_sleep()` sets a new `self.forced_sleep = True`
      flag and calls `enter_action("sleep")` (reuses the AFK feature's
      `SLEEP_POOL` random-pose pick directly above — same rule: any of the 7
      poses can come up). Unlike AFK sleep, this doesn't depend on
      `self.afk` at all and must **not** auto-wake when `afk` flickers, so
      the existing AFK-driven wake check in `update()` (`if self.action ==
      "sleep": enter_action("sit")`) gained an `and not self.forced_sleep`
      guard, plus an explicit `if self.forced_sleep: return` right after it
      — this freezes the pet at whatever `gx/gy` it was at (no walk/sit/react
      dispatch runs while the flag is set) while still letting the sleep
      pose's own frame-loop animate normally. Two ways to wake it, both
      already-existing gestures on the same drawing area: a left-click
      (`on_drag_end`'s no-real-motion branch) now checks
      `pet.forced_sleep` first and calls the new `pet.wake()` (clears the
      flag, `enter_action("sit")`) instead of `trigger_meow()`; a real drag
      (`start_drag()`) also clears the flag unconditionally at its top, so
      grabbing a forced-sleeping cat resumes normal drag behavior rather
      than fighting the nap state. Verified via a headless test with a
      `FakeSheet` stub (driving `Pet.update()` directly needs a real
      `self.sheet.anim()`/`.frames` since the generic frame-advance runs
      before any action dispatch): 2000 simulated ticks with a far-away walk
      target left `gx/gy` completely unchanged while forced-asleep, toggling
      `self.afk` on/off mid-nap didn't wake it, and both `wake()` and
      `start_drag()` correctly cleared `forced_sleep` and resumed normal
      action.

## To do / open
- [ ] `assets/src/rest-block-reference.png` — stashed crop of the source pack's
      REST block (alert/stretch/lounge/flopped-curled poses, gray palette,
      untouched, not wired into manifest). Candidate frames for a future
      "held by scruff / flopped" reaction if wanted later.
- [ ] Decide fate of dead Electron files (`src/`, `electron-builder.yml`, …) — delete?
- [ ] Groom: source/add a real groom animation if wanted (none in current pack).
- [ ] README: document behavior model + `PET_IDLE_SEC`, swayidle/niri optional deps.
- [ ] Goldie pet: directional walk rows not mapped (only cat has `walk_fd/front/back`)
      — falls back to side walk. Map if Goldie is to be used.
- [ ] Autostart (niri spawn-at-startup) — not set up.
- [ ] Tune walk speed / sit durations / diagonal thresholds after live observation.

## Tuning knobs
- `PET_SCALE` (env, default 4), `PET_IDLE_SEC` (env, default 180).
- `SIT_MIN/SIT_MAX` (5–12s), `WALK_MIN` (2.5s) in `pet.py`.

## Gotchas
- **Don't** kill via `pkill -f pet.py` / `pgrep -f pet.py` — matches the shell's own
  command line and kills it (exit 144). Use the bracket trick instead:
  `ps aux | grep '[p]et\.py'` (won't self-match) → `kill <PID>`. Or a PID file:
  launch `... & echo $! > /tmp/pet.pid`, kill `kill "$(cat /tmp/pet.pid)"`.
- The agent's sandboxed Bash tool runs in a different process namespace than
  the live desktop session — `ps`/`pgrep` from in there can't see the real
  running pet at all. Process management/restarts must happen in the user's
  own terminal.
- `GtkApplication` is single-instance per `application_id`: launching `pet.py`
  again while one is already running just activates the existing instance and
  exits immediately (code 0, no output) — it does **not** reload new code. Must
  kill the old process first for edits to take effect.
- Theme-parser warnings in the log are the user's GTK theme, harmless.
- `Gdk.cairo_set_source_pixbuf` deprecation warning is harmless (still works).
