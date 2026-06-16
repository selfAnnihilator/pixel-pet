// Tiny JSON settings store in the app's userData dir.
const fs = require('fs');
const path = require('path');
const { app } = require('electron');

const DEFAULTS = {
  pet: 'cat',
  scale: 4,                // integer pixel scale
  stretchIntervalMin: 30,  // 0 = off
  paused: false,
  pos: null,               // {x, y} window-local anchor, null = default corner
};

let file;
let data;

function load() {
  file = path.join(app.getPath('userData'), 'settings.json');
  try {
    data = { ...DEFAULTS, ...JSON.parse(fs.readFileSync(file, 'utf8')) };
  } catch {
    data = { ...DEFAULTS };
  }
  return data;
}

function get(key) {
  return data[key];
}

function set(key, value) {
  data[key] = value;
  try {
    fs.writeFileSync(file, JSON.stringify(data, null, 2));
  } catch (e) {
    console.error('settings write failed', e);
  }
}

module.exports = { load, get, set, DEFAULTS };
