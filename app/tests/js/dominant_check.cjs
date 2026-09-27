'use strict';
/*
 * Cross-check for control_center.artwork.dominant_rgb against knob-model.js.
 *
 * Loads the design's knob-model.js in a node `vm` context with a stub DOM: the
 * canvas stub's getImageData() returns the 24x24 RGBA bytes Pillow produced
 * (control_center.artwork.dominant_sample), so both implementations bin the
 * very same pixels. Nothing is fetched and no file is written.
 *
 * Usage: node dominant_check.cjs <knob-model.js> <input.json>
 *   input.json = {
 *     "assets":  { "assets/covers/x.jpg": "<base64 24*24*4 RGBA>", ... },
 *     "samples": { "<name>": "<base64 24*24*4 RGBA>", ... }
 *   }
 * stdout (JSON) = {
 *   "colors":  NanoModel.COLORS after the real loadColors() ran over "assets"
 *              ({"al:<title>"|"app:<name>": "r,g,b"|null}),
 *   "sources": {"<COLORS key>": "<asset src>"},
 *   "samples": {"<name>": "r,g,b"|null}   (dominant() on each synthetic sample)
 * }
 */
const fs = require('fs');
const vm = require('vm');

const SIDE = 24;
const BYTES = SIDE * SIDE * 4;
const [modelPath, inputPath] = process.argv.slice(2);
if (!modelPath || !inputPath) {
  process.stderr.write('usage: node dominant_check.cjs <knob-model.js> <input.json>\n');
  process.exit(2);
}
const input = JSON.parse(fs.readFileSync(inputPath, 'utf8'));
const pixels = new Map();
for (const group of ['assets', 'samples']) {
  for (const [name, b64] of Object.entries(input[group] || {})) {
    const bytes = Buffer.from(b64, 'base64');
    if (bytes.length !== BYTES) throw new Error(`sample ${name} has ${bytes.length} bytes, expected ${BYTES}`);
    pixels.set(name, bytes);
  }
}

function stubCanvas() {
  let drawn = null;
  const ctx = {
    drawImage(img, x, y, w, h) {
      if (x !== 0 || y !== 0 || w !== SIDE || h !== SIDE) throw new Error('unexpected drawImage geometry');
      drawn = img;
    },
    getImageData(x, y, w, h) {
      if (x !== 0 || y !== 0 || w !== SIDE || h !== SIDE) throw new Error('unexpected getImageData geometry');
      const bytes = drawn && pixels.get(drawn.src);
      if (!bytes) throw new Error('no Pillow sample for ' + (drawn && drawn.src));
      return { width: SIDE, height: SIDE, data: new Uint8ClampedArray(bytes) };
    }
  };
  return {
    width: 0,
    height: 0,
    getContext(kind) {
      if (kind !== '2d') throw new Error('unexpected context ' + kind);
      return ctx;
    }
  };
}

const loads = [];
class StubImage {
  constructor() { this.onload = null; this.onerror = null; this._src = ''; }
  set src(value) { this._src = String(value); loads.push(this); }
  get src() { return this._src; }
}

const context = vm.createContext({
  window: {},
  document: {
    createElement(tag) {
      if (tag !== 'canvas') throw new Error('unexpected element ' + tag);
      return stubCanvas();
    }
  },
  Image: StubImage
});

// Expose the private dominant() next to the public API for synthetic samples.
// The function body itself is evaluated exactly as shipped in the design.
const anchor = 'window.NanoModel = { loadColors,';
const source = fs.readFileSync(modelPath, 'utf8');
if (source.split(anchor).length !== 2) throw new Error('knob-model.js export anchor not found exactly once');
vm.runInContext(source.replace(anchor, 'window.NanoModel = { __dominant: dominant, loadColors,'),
  context, { filename: 'knob-model.js' });
const model = context.window.NanoModel;

// Real loadColors(): every Image load is answered after loadColors returns, as a
// browser would, and the COLORS key each load produced is recorded.
let completed = false;
model.loadColors(() => { completed = true; });
const sources = {};
for (const image of loads) {
  const before = new Set(Object.keys(model.COLORS));
  if (pixels.has(image.src)) image.onload(); else image.onerror();
  for (const key of Object.keys(model.COLORS)) if (!before.has(key)) sources[key] = image.src;
}
if (!completed) throw new Error('loadColors() did not complete');

const samples = {};
for (const name of Object.keys(input.samples || {})) samples[name] = model.__dominant({ src: name });

const colors = {};
for (const [key, value] of Object.entries(model.COLORS)) colors[key] = value;
process.stdout.write(JSON.stringify({ colors, sources, samples }));
