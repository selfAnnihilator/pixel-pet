import { PetSprites, loadImage } from './sprites.js';

const ASSETS = '../../assets/';

const AMBIENT = [
  { name: 'idle', weight: 5, min: 4, max: 8 },
  { name: 'groom', weight: 3, min: 3, max: 5 },
  { name: 'sleep', weight: 2, min: 6, max: 14 },
];

class Engine {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.ctx.imageSmoothingEnabled = false;

    this.manifest = null;
    this.sprites = {};      // pet name -> PetSprites
    this.pet = null;        // active PetSprites
    this.petName = 'cat';
    this.scale = 4;
    this.paused = false;

    this.cursor = { x: 0, y: 0 };
    this.gx = 0; this.gy = 0;      // ground anchor (feet) in window-local px
    this.facingLeft = false;

    this.state = 'idle';
    this.frame = 0;
    this.frameClock = 0;
    this.locked = false;           // playing a one-shot (react/stretch) to completion
    this.ambientClock = 0;
    this.dragging = false;
    this.dragOff = { x: 0, y: 0 };

    this.lastHitSend = 0;
    this.bubble = document.getElementById('bubble');
    this.bubbleUntil = 0;

    this._bindPointer();
    window.addEventListener('resize', () => this.resize());
  }

  resize() {
    this.canvas.width = window.innerWidth;
    this.canvas.height = window.innerHeight;
    this.ctx.imageSmoothingEnabled = false;
    this.clampGround();
  }

  // keep the pet's feet inside the full-screen canvas
  clampGround() {
    this.gx = Math.max(0, Math.min(this.gx || 0, this.canvas.width));
    this.gy = Math.max(0, Math.min(this.gy || (this.canvas.height - 4), this.canvas.height - 4));
  }

  async init(data) {
    this.manifest = data.manifest;
    this.scale = data.scale || 4;
    this.paused = !!data.paused;
    this.resize();
    // load all pets up front so switching is instant
    for (const [name, def] of Object.entries(this.manifest.pets)) {
      const img = await loadImage(ASSETS + def.sheet);
      this.sprites[name] = new PetSprites(def, img);
    }
    this.setPet(data.pet || this.manifest.defaultPet, false);

    if (data.pos) { this.gx = data.pos.x; this.gy = data.pos.y; }
    else { this.gx = this.canvas.width - 140; this.gy = this.canvas.height - 4; }
    this.clampGround(); // a stale saved pos must never land off-screen

    this.enter('idle');
    requestAnimationFrame((t) => this.loop(t));
  }

  setPet(name, keepPos = true) {
    if (!this.sprites[name]) return;
    this.petName = name;
    this.pet = this.sprites[name];
    this.frame = 0;
    if (!keepPos) this.enter('idle');
  }

  setScale(s) { this.scale = s; }
  setPaused(p) { this.paused = p; if (!p) this.enter('idle'); }

  enter(state) {
    this.state = state;
    this.frame = 0;
    this.frameClock = 0;
    this.locked = state === 'react' || state === 'stretch';
  }

  pickAmbient() {
    const total = AMBIENT.reduce((s, a) => s + a.weight, 0);
    let r = Math.random() * total;
    let chosen = AMBIENT[0];
    for (const a of AMBIENT) { if ((r -= a.weight) <= 0) { chosen = a; break; } }
    this.ambientClock = chosen.min + Math.random() * (chosen.max - chosen.min);
    if (this.state !== chosen.name) this.enter(chosen.name);
  }

  // external events
  react() { if (!this.paused) this.enter('react'); }
  stretch() {
    if (this.paused) return;
    this.enter('stretch');
    this.showBubble('stretch~ ' + (this.petName === 'cat' ? '🐱' : '🐶'));
  }

  showBubble(text) {
    this.bubble.textContent = text;
    this.bubbleUntil = performance.now() + 4000;
  }

  loop(t) {
    const dt = Math.min(0.05, (t - (this._last || t)) / 1000);
    this._last = t;
    if (!this.paused && !this.dragging) this.update(dt);
    this.render(t);
    requestAnimationFrame((nt) => this.loop(nt));
  }

  update(dt) {
    const anim = this.pet.anim(this.state);
    const dx = this.cursor.x - this.gx;
    const far = Math.abs(dx);

    // advance current animation frames
    this.frameClock += dt;
    const dur = 1 / anim.fps;
    let ended = false;
    while (this.frameClock >= dur) {
      this.frameClock -= dur;
      this.frame++;
      if (this.frame >= anim.frames) {
        if (anim.loop) this.frame = 0;
        else { this.frame = anim.frames - 1; ended = true; }
      }
    }

    if (this.locked) {
      if (ended) { this.locked = false; this.pickAmbient(); }
      return;
    }

    // cursor chase takes priority over ambient
    const FAR_START = 80, FAR_STOP = 16;
    if (far > FAR_START) {
      if (this.state !== 'walk') this.enter('walk');
      this.facingLeft = dx < 0;
      const speed = 70 * (this.scale / 4);
      this.gx += Math.sign(dx) * Math.min(speed * dt, far);
      return;
    }
    if (this.state === 'walk') { this.pickAmbient(); return; }

    // ambient cycling
    this.ambientClock -= dt;
    if (this.ambientClock <= 0) this.pickAmbient();
    else if (ended && this.state !== 'sleep') this.frame = 0; // re-loop one-shot ambient (groom)
  }

  render(t) {
    const ctx = this.ctx;
    ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    const flip = this.facingLeft && this.pet.def.facesRight;
    this.pet.draw(ctx, this.state, this.frame, this.gx, this.gy, this.scale, flip);

    // bubble follows pet
    if (t < this.bubbleUntil) {
      const r = this.pet.screenRect(this.state, this.frame, this.gx, this.gy, this.scale, flip);
      this.bubble.style.display = 'block';
      this.bubble.style.left = (r.x + r.w / 2) + 'px';
      this.bubble.style.top = (r.y - 28) + 'px';
    } else {
      this.bubble.style.display = 'none';
    }

    // report hit region to main (throttled)
    if (t - this.lastHitSend > 80) {
      this.lastHitSend = t;
      const r = this.pet.screenRect(this.state, this.frame, this.gx, this.gy, this.scale, flip);
      window.pet.setHitRegion(r);
    }
  }

  _bindPointer() {
    window.addEventListener('pointerdown', (e) => {
      this.dragging = true;
      this.dragOff = { x: e.clientX - this.gx, y: e.clientY - this.gy };
      this.canvas.style.cursor = 'grabbing';
    });
    window.addEventListener('pointermove', (e) => {
      if (!this.dragging) return;
      this.gx = e.clientX - this.dragOff.x;
      this.gy = e.clientY - this.dragOff.y;
    });
    const drop = () => {
      if (!this.dragging) return;
      this.dragging = false;
      this.canvas.style.cursor = 'grab';
      this.clampGround();
      window.pet.savePos({ x: Math.round(this.gx), y: Math.round(this.gy) });
    };
    window.addEventListener('pointerup', drop);
    window.addEventListener('pointercancel', drop);
  }
}

// --- wire up ---
const engine = new Engine(document.getElementById('stage'));
window.pet.onInit((d) => engine.init(d));
window.pet.onCursor((p) => { engine.cursor = p; });
window.pet.onTyping(() => engine.react());
window.pet.onStretch(() => engine.stretch());
window.pet.onPet((name) => engine.setPet(name, false));
window.pet.onScale((s) => engine.setScale(s));
window.pet.onPaused((p) => engine.setPaused(p));
