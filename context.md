# Pixel Pet — Context

> Living status doc. **Update after every successful change.** Last updated: 2026-06-16 (click-to-meow, git init)

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
  `FILTER_NEAREST`.
- **`run-pet.sh`** — launcher. Sets `LD_PRELOAD=libgtk4-layer-shell.so` (must load
  before libwayland) then runs `pet.py`.
- **`assets/manifest.json` + `assets/cat/cat.png`** — sprite sheet + metadata.
- Electron build (`src/`, `electron-builder.yml`, etc.) is **dead/superseded** —
  kept for now, pending delete decision.

### Environment
niri 26.04, single output eDP-1 1920x1080, Wayland, Arch/cachyos.
Working dir: `/home/abhi/code/pixel-pet` (now a git repo, initialized 2026-06-16).

### Sprite sheet truth (rows were mislabeled by auto-segmenter)
cat.png 594x196, cell 66x28, 9 cols, 7 rows:
- row0 `idle` — 6 **distinct sit poses** (NOT a loop; hold one frame)
- row1 `walk` — side/horizontal walk (8)
- row2 `sleep` — (9)
- row3 `walk_fd` — front-diagonal walk, ¾ toward viewer (6)
- row4 `walk_front` — straight-down walk, facing viewer (4)
- row5 `walk_back` — back walk, ¾ away (6)
- row6 `meow` — front-facing meow pose, 3 frames, not a loop (added; sourced from
  `assets/src/Free pack/cat 1.png` "meow stand" row, same gray palette as the rest)
- **No groom animation exists** in this pack.
- Source pack has more unused rows (eat, yawn, wash, itch, hiss, paw attack, on
  hind legs, plus 3 sleep poses each L/R) in `assets/src/Free pack/cat 1.png` if
  more states are wanted later — row/col pixel bands need re-deriving by
  alpha-band detection (no fixed grid; each row's frames are tightly trimmed).

## Done
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

## To do / open
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
