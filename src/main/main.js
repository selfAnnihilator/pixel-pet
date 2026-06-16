// Force the X11/XWayland backend: on a native Wayland session, transparent always-on-top
// overlays and global input hooks are unreliable. Must run before app is ready.
const { app } = require('electron');
app.commandLine.appendSwitch('ozone-platform-hint', 'x11');
// Without an ARGB visual the transparent overlay renders as a solid black box on
// Linux/XWayland. This forces Chromium to pick a 32-bit visual so only the sprite shows.
app.commandLine.appendSwitch('enable-transparent-visuals');

const path = require('path');
const { BrowserWindow, Tray, Menu, ipcMain, screen, nativeImage } = require('electron');
const settings = require('./settings');
const keyhook = require('./keyhook');
const wm = require('./wm');

const WIN_TITLE = 'PixelPet'; // stable identity for compositor-IPC matching

let win = null;
let tray = null;
let manifest = null;
let workArea = { x: 0, y: 0, width: 0, height: 0 };

// pet's opaque bounding box in window-local px, reported by the renderer
let hitRegion = { x: 0, y: 0, w: 0, h: 0 };
let ignoring = true;

let cursorTimer = null;
let stretchTimer = null;

function loadManifest() {
  manifest = require(path.join(__dirname, '..', '..', 'assets', 'manifest.json'));
}

function createWindow() {
  const display = screen.getPrimaryDisplay();
  // Cover the *full* output (bounds, not workArea) so the pet can roam over panels and apps.
  workArea = display.bounds;
  win = new BrowserWindow({
    x: workArea.x,
    y: workArea.y,
    width: workArea.width,
    height: workArea.height,
    title: WIN_TITLE,
    transparent: true,
    backgroundColor: '#00000000', // fully transparent; avoids black fill on XWayland
    frame: false,
    resizable: false,
    movable: false,
    focusable: false,        // never steal focus from the user's apps
    skipTaskbar: true,
    alwaysOnTop: true,
    hasShadow: false,
    webPreferences: {
      preload: path.join(__dirname, '..', 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  win.setAlwaysOnTop(true, 'screen-saver');               // _NET_WM_STATE_ABOVE
  win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true }); // _NET_WM_STATE_STICKY
  win.setIgnoreMouseEvents(true, { forward: true });
  win.on('page-title-updated', (e) => e.preventDefault()); // keep WIN_TITLE for IPC matching
  win.loadFile(path.join(__dirname, '..', 'renderer', 'index.html'));

  win.webContents.on('did-finish-load', () => {
    win.webContents.send('init', {
      manifest,
      pet: settings.get('pet'),
      scale: settings.get('scale'),
      paused: settings.get('paused'),
      pos: settings.get('pos'),
    });
    startCursorLoop();
    scheduleStretch();
    wm.enableStickyOverlay(win, WIN_TITLE); // float + all-workspace on tiling Wayland WMs
  });
}

// Poll the global cursor: feed it to the renderer (so the pet can chase it) and toggle
// click-through so the window only intercepts the mouse when it's over the sprite.
function startCursorLoop() {
  if (cursorTimer) clearInterval(cursorTimer);
  cursorTimer = setInterval(() => {
    if (!win || win.isDestroyed()) return;
    const p = screen.getCursorScreenPoint();
    const lx = p.x - workArea.x;
    const ly = p.y - workArea.y;
    win.webContents.send('cursor', { x: lx, y: ly });

    const over =
      lx >= hitRegion.x && lx <= hitRegion.x + hitRegion.w &&
      ly >= hitRegion.y && ly <= hitRegion.y + hitRegion.h;
    if (over === ignoring) {
      ignoring = !over;
      win.setIgnoreMouseEvents(ignoring, { forward: true });
    }
  }, 1000 / 30);
}

function scheduleStretch() {
  if (stretchTimer) clearInterval(stretchTimer);
  const min = settings.get('stretchIntervalMin');
  if (!min || settings.get('paused')) return;
  stretchTimer = setInterval(() => {
    if (win && !win.isDestroyed() && !settings.get('paused')) {
      win.webContents.send('stretch');
    }
  }, min * 60 * 1000);
}

function buildTray() {
  const pet = settings.get('pet');
  const iconPath = path.join(__dirname, '..', '..', 'assets', manifest.pets[pet].icon);
  const icon = nativeImage.createFromPath(iconPath).resize({ width: 22, height: 22 });
  tray = new Tray(icon);
  tray.setToolTip('Pixel Pet');
  refreshTrayMenu();
}

function refreshTrayMenu() {
  const curPet = settings.get('pet');
  const curScale = settings.get('scale');
  const paused = settings.get('paused');
  const petItems = Object.keys(manifest.pets).map((name) => ({
    label: name === 'cat' ? 'Cat' : name === 'goldie' ? 'Goldie (puppy)' : name,
    type: 'radio',
    checked: name === curPet,
    click: () => switchPet(name),
  }));
  const scaleItems = [3, 4, 5, 6].map((s) => ({
    label: `${s}×`,
    type: 'radio',
    checked: s === curScale,
    click: () => { settings.set('scale', s); win.webContents.send('scale', s); },
  }));
  const stretchItems = [0, 15, 30, 60].map((m) => ({
    label: m === 0 ? 'Off' : `${m} min`,
    type: 'radio',
    checked: m === settings.get('stretchIntervalMin'),
    click: () => { settings.set('stretchIntervalMin', m); scheduleStretch(); },
  }));
  const menu = Menu.buildFromTemplate([
    { label: 'Pet', submenu: petItems },
    { label: 'Size', submenu: scaleItems },
    { label: 'Stretch break', submenu: stretchItems },
    { type: 'separator' },
    {
      label: paused ? 'Resume' : 'Pause',
      click: () => {
        const p = !settings.get('paused');
        settings.set('paused', p);
        win.webContents.send('paused', p);
        scheduleStretch();
        refreshTrayMenu();
      },
    },
    { label: 'Stretch now', click: () => win.webContents.send('stretch') },
    { type: 'separator' },
    { label: 'Quit', click: () => app.quit() },
  ]);
  tray.setContextMenu(menu);
}

function switchPet(name) {
  settings.set('pet', name);
  win.webContents.send('pet', name);
  const iconPath = path.join(__dirname, '..', '..', 'assets', manifest.pets[name].icon);
  tray.setImage(nativeImage.createFromPath(iconPath).resize({ width: 22, height: 22 }));
  refreshTrayMenu();
}

// --- IPC from renderer ---
ipcMain.on('hit-region', (_e, r) => { hitRegion = r; });
ipcMain.on('save-pos', (_e, pos) => settings.set('pos', pos));

app.whenReady().then(() => {
  settings.load();
  loadManifest();
  createWindow();
  buildTray();
  keyhook.start(() => {
    if (win && !win.isDestroyed() && !settings.get('paused')) win.webContents.send('typing');
  });
});

app.on('window-all-closed', (e) => { e.preventDefault(); }); // tray app: keep running
app.on('before-quit', () => { keyhook.stop(); wm.stop(); });
