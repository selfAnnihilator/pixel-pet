// Loads a pet's packed sheet and precomputes the tight opaque bounding box of every cell
// (cells carry transparent padding), so the engine can hit-test and position precisely.

export class PetSprites {
  constructor(petDef, image) {
    this.def = petDef;          // manifest entry: {sheet, cellW, cellH, cols, anims, facesRight}
    this.image = image;
    this.bounds = {};           // bounds[row][col] = {ox, oy, ow, oh} in cell-local px

    const { cellW, cellH, cols } = petDef;
    const rows = Object.keys(petDef.anims).length;
    const cv = document.createElement('canvas');
    cv.width = image.width;
    cv.height = image.height;
    const ctx = cv.getContext('2d');
    ctx.drawImage(image, 0, 0);
    const data = ctx.getImageData(0, 0, image.width, image.height).data;

    for (let r = 0; r < rows; r++) {
      this.bounds[r] = {};
      for (let c = 0; c < cols; c++) {
        const bx = c * cellW, by = r * cellH;
        let minX = cellW, minY = cellH, maxX = -1, maxY = -1;
        for (let y = 0; y < cellH; y++) {
          for (let x = 0; x < cellW; x++) {
            const a = data[((by + y) * image.width + (bx + x)) * 4 + 3];
            if (a > 16) {
              if (x < minX) minX = x;
              if (x > maxX) maxX = x;
              if (y < minY) minY = y;
              if (y > maxY) maxY = y;
            }
          }
        }
        this.bounds[r][c] =
          maxX < 0 ? { ox: 0, oy: 0, ow: 0, oh: 0 }
                   : { ox: minX, oy: minY, ow: maxX - minX + 1, oh: maxY - minY + 1 };
      }
    }
  }

  anim(name) { return this.def.anims[name]; }

  // draw cell (row,col) so the sprite's bottom-center sits at screen (gx, gy)
  draw(ctx, name, frame, gx, gy, scale, flip) {
    const a = this.def.anims[name];
    const { cellW, cellH } = this.def;
    const sx = frame * cellW;
    const sy = a.row * cellH;
    const dw = cellW * scale, dh = cellH * scale;
    const dx = Math.round(gx - dw / 2);
    const dy = Math.round(gy - dh);
    ctx.save();
    if (flip) {
      ctx.translate(dx + dw, dy);
      ctx.scale(-1, 1);
      ctx.drawImage(this.image, sx, sy, cellW, cellH, 0, 0, dw, dh);
    } else {
      ctx.drawImage(this.image, sx, sy, cellW, cellH, dx, dy, dw, dh);
    }
    ctx.restore();
  }

  // tight opaque rect on screen for cell (name,frame) drawn at ground (gx,gy)
  screenRect(name, frame, gx, gy, scale, flip) {
    const a = this.def.anims[name];
    const { cellW, cellH } = this.def;
    const b = this.bounds[a.row][Math.min(frame, this.def.cols - 1)];
    const dw = cellW * scale, dh = cellH * scale;
    const dx = gx - dw / 2;
    const dy = gy - dh;
    const ox = flip ? cellW - (b.ox + b.ow) : b.ox;
    return {
      x: Math.round(dx + ox * scale),
      y: Math.round(dy + b.oy * scale),
      w: Math.round(b.ow * scale),
      h: Math.round(b.oh * scale),
    };
  }
}

export function loadImage(src) {
  return new Promise((res, rej) => {
    const img = new Image();
    img.onload = () => res(img);
    img.onerror = rej;
    img.src = src;
  });
}
