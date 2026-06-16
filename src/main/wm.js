// Compositor-specific overlay glue.
//
// The portable overlay behaviour (always-on-top, sticky, skip-taskbar) is requested through
// standard EWMH hints in main.js and is honoured by X11 WMs, GNOME, KDE, Xfce, etc. This
// module only handles the compositors that *ignore* those hints for XWayland windows — the
// pure tiling Wayland ones — by driving their IPC instead. Everything here degrades to a
// no-op if the compositor is unknown or its CLI is missing, so the app never depends on it.

const { execFile, spawn } = require('child_process');

let niriProc = null;

function run(cmd, args) {
  return new Promise((resolve) => {
    execFile(cmd, args, { timeout: 4000 }, (err, stdout) => {
      resolve(err ? null : stdout);
    });
  });
}

function detect() {
  if (process.env.HYPRLAND_INSTANCE_SIGNATURE) return 'hyprland';
  if (process.env.NIRI_SOCKET) return 'niri';
  if (process.env.SWAYSOCK) return 'sway';
  return null;
}

// --- niri: no native "show on all workspaces", so we float the window and chase the active
//     workspace over its event stream, re-parenting the pet without stealing focus. ---
async function niriWindowId(title) {
  const out = await run('niri', ['msg', '--json', 'windows']);
  if (!out) return null;
  try {
    const w = JSON.parse(out).find((x) => x.title === title);
    return w ? w.id : null;
  } catch { return null; }
}

async function niriFocusedIdx() {
  const out = await run('niri', ['msg', '--json', 'workspaces']);
  if (!out) return null;
  try {
    const ws = JSON.parse(out).find((x) => x.is_focused);
    return ws ? ws.idx : null;
  } catch { return null; }
}

async function enableNiri(title) {
  // The window can take a moment to map; poll for its id.
  let id = null;
  for (let i = 0; i < 20 && id == null; i++) {
    id = await niriWindowId(title);
    if (id == null) await new Promise((r) => setTimeout(r, 150));
  }
  if (id == null) return; // give up quietly; EWMH hints still apply

  await run('niri', ['msg', 'action', 'move-window-to-floating', '--id', String(id)]);
  // Floated windows land below the top bar; a full-height overlay then spills off the
  // bottom and clips the pet's feet. Pin it to the output's top-left corner.
  await run('niri', ['msg', 'action', 'move-floating-window', '--id', String(id), '-x', '0', '-y', '0']);

  let petIdx = await niriFocusedIdx(); // where the pet currently lives
  const follow = async () => {
    const idx = await niriFocusedIdx();
    if (idx == null || idx === petIdx) return;
    // window id is stable across workspace moves, but re-resolve if it ever vanishes
    let wid = await niriWindowId(title);
    if (wid == null) return;
    await run('niri', [
      'msg', 'action', 'move-window-to-workspace',
      '--window-id', String(wid), '--focus', 'false', String(idx),
    ]);
    petIdx = idx;
  };

  niriProc = spawn('niri', ['msg', '--json', 'event-stream'], { stdio: ['ignore', 'pipe', 'ignore'] });
  let buf = '';
  niriProc.stdout.on('data', (chunk) => {
    buf += chunk;
    let nl;
    while ((nl = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, nl);
      buf = buf.slice(nl + 1);
      if (line.includes('WorkspaceActivated') || line.includes('WorkspacesChanged')) follow();
    }
  });
  niriProc.on('error', () => {}); // niri CLI missing: ignore
}

// --- sway: floating + sticky is native. ---
async function enableSway(title) {
  await run('swaymsg', [`[title="${title}"] floating enable, sticky enable, border none`]);
}

// --- Hyprland: float + pin (pin = visible on every workspace) is native. ---
async function enableHyprland(title) {
  const m = `title:^(${title})$`;
  await run('hyprctl', [
    '--batch',
    `keyword windowrulev2 float,${m} ; ` +
    `keyword windowrulev2 pin,${m} ; ` +
    `keyword windowrulev2 nofocus,${m} ; ` +
    `keyword windowrulev2 noborder,${m}`,
  ]);
}

async function enableStickyOverlay(_win, title) {
  try {
    switch (detect()) {
      case 'niri': return await enableNiri(title);
      case 'sway': return await enableSway(title);
      case 'hyprland': return await enableHyprland(title);
      default: return; // EWMH hints cover everything else
    }
  } catch { /* never let overlay glue crash the app */ }
}

function stop() {
  if (niriProc) { try { niriProc.kill(); } catch {} niriProc = null; }
}

module.exports = { enableStickyOverlay, stop };
