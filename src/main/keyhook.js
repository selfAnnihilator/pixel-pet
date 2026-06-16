// Global keyboard listener via uiohook-napi. Works on X11 + Windows. On a pure-Wayland
// session the hook may fail to capture events — we swallow the error so the pet still runs
// (just without keystroke reactions).
let uIOhook;
try {
  ({ uIOhook } = require('uiohook-napi'));
} catch (e) {
  console.warn('uiohook-napi unavailable; keystroke reactions disabled:', e.message);
}

let started = false;

// onType: called (debounced) whenever the user is typing.
function start(onType) {
  if (!uIOhook || started) return;
  let last = 0;
  try {
    uIOhook.on('keydown', () => {
      const now = Date.now();
      if (now - last > 120) {
        last = now;
        onType();
      }
    });
    uIOhook.start();
    started = true;
    console.log('global keyhook started');
  } catch (e) {
    console.warn('keyhook start failed (Wayland?):', e.message);
  }
}

function stop() {
  if (uIOhook && started) {
    try { uIOhook.stop(); } catch {}
    started = false;
  }
}

module.exports = { start, stop };
