const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('pet', {
  // main -> renderer events
  onInit: (cb) => ipcRenderer.on('init', (_e, d) => cb(d)),
  onCursor: (cb) => ipcRenderer.on('cursor', (_e, p) => cb(p)),
  onTyping: (cb) => ipcRenderer.on('typing', () => cb()),
  onStretch: (cb) => ipcRenderer.on('stretch', () => cb()),
  onPet: (cb) => ipcRenderer.on('pet', (_e, name) => cb(name)),
  onScale: (cb) => ipcRenderer.on('scale', (_e, s) => cb(s)),
  onPaused: (cb) => ipcRenderer.on('paused', (_e, p) => cb(p)),
  // renderer -> main
  setHitRegion: (r) => ipcRenderer.send('hit-region', r),
  savePos: (pos) => ipcRenderer.send('save-pos', pos),
});
