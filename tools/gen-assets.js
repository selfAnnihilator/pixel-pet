// gen-assets.js — turn the artist's raw sprite sheets into normalized, engine-ready
// sheets + a manifest. Runs at dev time (`npm run gen:assets`).
//
// The raw sheets have no frame-tag metadata (the .aseprite files are a single flattened
// canvas), so we auto-segment: blank horizontal rows split the sheet into animation
// "strips", blank vertical columns split each strip into frames. We then tight-crop every
// frame and repack the animations we want into a uniform grid (rows = animations,
// cols = frames), bottom-center anchored so every pose stands on the same ground line.
//
// Add your own pet: drop its sheet, find its strips with the same blank-gap layout, and
// add an entry to PETS below (strip index per animation). Re-run `npm run gen:assets`.

const fs = require('fs');
const path = require('path');
const AdmZip = require('adm-zip');
const { PNG } = require('pngjs');
const os = require('os');

const ROOT = path.join(__dirname, '..');
const SRC = path.join(ROOT, 'assets', 'src');
const DOCS = path.join(os.homedir(), 'Documents');

// --- 0. Ensure source art is extracted -------------------------------------------------
function ensureSources() {
  const need = [
    [path.join(SRC, 'Free pack', 'cat 1.png'), 'Free pack.zip'],
    [path.join(SRC, 'Goldie pack_v02', 'Goldie_v02.png'), 'Goldie pack_v1.1.zip'],
  ];
  fs.mkdirSync(SRC, { recursive: true });
  for (const [file, zip] of need) {
    if (fs.existsSync(file)) continue;
    const zp = path.join(DOCS, zip);
    if (!fs.existsSync(zp)) throw new Error(`Missing art zip: ${zp}`);
    console.log(`extracting ${zip}`);
    new AdmZip(zp).extractAllTo(SRC, true);
  }
}

// --- pixel helpers ---------------------------------------------------------------------
function loadPNG(file) {
  return PNG.sync.read(fs.readFileSync(file));
}
function alphaAt(img, x, y) {
  return img.data[(img.width * y + x) * 4 + 3];
}
const A = 16; // alpha threshold

function rowEmpty(img, y) {
  for (let x = 0; x < img.width; x++) if (alphaAt(img, x, y) > A) return false;
  return true;
}
// horizontal strips = runs of non-empty rows
function strips(img) {
  const out = [];
  let y = 0;
  while (y < img.height) {
    if (!rowEmpty(img, y)) {
      const a = y;
      while (y < img.height && !rowEmpty(img, y)) y++;
      out.push([a, y]);
    } else y++;
  }
  return out;
}
// frames within a strip = runs of non-empty columns, each tight-cropped vertically
function frames(img, y0, y1) {
  const colEmpty = (x) => {
    for (let y = y0; y < y1; y++) if (alphaAt(img, x, y) > A) return false;
    return true;
  };
  const spans = [];
  let x = 0;
  while (x < img.width) {
    if (!colEmpty(x)) {
      const a = x;
      while (x < img.width && !colEmpty(x)) x++;
      spans.push([a, x]);
    } else x++;
  }
  // tight vertical crop per frame
  return spans.map(([sx, ex]) => {
    let top = y1, bot = y0;
    for (let y = y0; y < y1; y++)
      for (let xx = sx; xx < ex; xx++)
        if (alphaAt(img, xx, y) > A) { if (y < top) top = y; if (y >= bot) bot = y + 1; }
    return { sx, sy: top, sw: ex - sx, sh: Math.max(1, bot - top) };
  });
}

function blit(src, dst, box, dx, dy) {
  for (let y = 0; y < box.sh; y++)
    for (let x = 0; x < box.sw; x++) {
      const si = (src.width * (box.sy + y) + (box.sx + x)) * 4;
      const di = (dst.width * (dy + y) + (dx + x)) * 4;
      const a = src.data[si + 3];
      if (a <= A) continue;
      dst.data[di] = src.data[si];
      dst.data[di + 1] = src.data[si + 1];
      dst.data[di + 2] = src.data[si + 2];
      dst.data[di + 3] = a;
    }
}

// --- pet definitions: which strip is which animation ----------------------------------
// facesRight: art in `walk` already faces right; engine flips horizontally to face left.
const PETS = {
  cat: {
    sheet: ['Free pack', 'cat 1.png'],
    out: ['cat', 'cat.png'],
    anims: {
      idle:    { strip: 0, fps: 4,  loop: true },
      walk:    { strip: 6, fps: 10, loop: true },
      sleep:   { strip: 3, fps: 4,  loop: false },
      stretch: { strip: 9, fps: 8,  loop: false },
      react:   { strip: 4, fps: 12, loop: false },
      groom:   { strip: 10, fps: 6, loop: false },
    },
  },
  goldie: {
    sheet: ['Goldie pack_v02', 'Goldie_v02.png'],
    out: ['puppy', 'goldie.png'],
    anims: {
      idle:    { strip: 3, fps: 3, loop: true },
      walk:    { strip: 6, fps: 8, loop: true },
      sleep:   { strip: 2, fps: 4, loop: false },
      stretch: { strip: 0, fps: 8, loop: false },
      react:   { strip: 4, fps: 10, loop: false },
      groom:   { strip: 2, fps: 4, loop: false },
    },
  },
};

function buildPet(name, def) {
  const img = loadPNG(path.join(SRC, ...def.sheet));
  const S = strips(img);
  // extract frames for each animation
  const extracted = {};
  let cellW = 0, cellH = 0, maxFrames = 0;
  for (const [anim, cfg] of Object.entries(def.anims)) {
    const [y0, y1] = S[cfg.strip];
    const fr = frames(img, y0, y1);
    extracted[anim] = fr;
    maxFrames = Math.max(maxFrames, fr.length);
    for (const b of fr) { cellW = Math.max(cellW, b.sw); cellH = Math.max(cellH, b.sh); }
  }
  cellW += 2; cellH += 2; // 1px breathing room
  const animList = Object.keys(def.anims);
  const out = new PNG({ width: maxFrames * cellW, height: animList.length * cellH });
  out.data.fill(0);

  const manifestAnims = {};
  animList.forEach((anim, row) => {
    const fr = extracted[anim];
    fr.forEach((box, col) => {
      const dx = col * cellW + Math.floor((cellW - box.sw) / 2); // center
      const dy = row * cellH + (cellH - box.sh) - 1;             // bottom anchor
      blit(img, out, box, dx, dy);
    });
    manifestAnims[anim] = { row, frames: fr.length, fps: def.anims[anim].fps, loop: def.anims[anim].loop };
  });

  const outPath = path.join(ROOT, 'assets', ...def.out);
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  fs.writeFileSync(outPath, PNG.sync.write(out));

  // tray icon: idle frame 0, centered on a 32x32 transparent canvas
  const iconBox = extracted.idle[0];
  const icon = new PNG({ width: 32, height: 32 });
  icon.data.fill(0);
  blit(img, icon, iconBox,
    Math.floor((32 - iconBox.sw) / 2),
    Math.floor((32 - iconBox.sh) / 2));
  const iconRel = [path.dirname(path.posix.join(...def.out)), 'icon.png'];
  fs.writeFileSync(path.join(ROOT, 'assets', ...iconRel), PNG.sync.write(icon));

  console.log(`${name}: ${animList.length} anims, cell ${cellW}x${cellH}, ${maxFrames} cols -> ${path.relative(ROOT, outPath)}`);
  return {
    sheet: path.posix.join(...def.out),
    icon: path.posix.join(...iconRel),
    cellW, cellH, cols: maxFrames,
    facesRight: true,
    anims: manifestAnims,
  };
}

function main() {
  ensureSources();
  const manifest = { pets: {}, defaultPet: 'cat' };
  for (const [name, def] of Object.entries(PETS)) {
    manifest.pets[name] = buildPet(name, def);
  }
  const mp = path.join(ROOT, 'assets', 'manifest.json');
  fs.writeFileSync(mp, JSON.stringify(manifest, null, 2));
  console.log('wrote', path.relative(ROOT, mp));
}

main();
