// Knob icon masks for 1.0.0-cc5.4 / desktop v7 (PRESENTATION_V5.md section 9; WP9).
//
// The glyphs are the r2.1 design's own paths: an explicit token -> (stroke path, fill paths, sizes)
// table copied from `I` and `HALF` of design_handoff_nano_d_master_r2.1/prototypes/Browse and
// Snap.dc.html (BS:485-495). The legacy tokens home, more and cancel keep their cc5.3 paths, written
// out in the table below, and their masks, unchanged; the old design table is no longer read (section
// 9.2 item 1): --check pins those masks byte for byte. Every run first runs the DRIFT GATE: each r2.1
// path string (and the stroke/size markup it is drawn with) must still occur verbatim in the BS file
// (Knob Face.dc.html for the 26 px markup), or nothing is written.
//
// Strokes by use (24-unit viewBox, round caps and joins): 20 px 2.3 (footer, BS:331), 26 px 2.1 (Home
// idle row, Knob Face.dc.html:42), 16 px 2.3 (Tracks position row, BS:304/306). Fill paths are drawn
// fill="white" stroke="none" (the snap halves; the internal `dotfill` disc, BS:305's 6 px dot; the
// internal [r2.2] `heartfill`, the `heart` path filled for tone `liked`, drawn in #A3244A, P5-R29).
//
// Firmware masks are trimmed per use (section 9.1): 22 x 20 px (21 wire tokens + heartfill) + 5 x 26 px
// + 3 x 16 px = 12,948 B of A8 (r2.1: 12,548 B; before: 48 masks, 21,312 B). A token without a mask at a
// size makes cc_icon() return nullptr. The desktop copies (assets/handoff-icons PNG/SVG, assets/lcd-icons
// @2x/@3x) keep every wire token, and heartfill (the liked look of `heart`), at 16/20/26 so the floating
// knob can draw any of them; dotfill only at 16 px. icons.json there lists the firmware sizes for mirror
// parity.
//
// Output: LVGL 9.0 A8 masks as 3-member lv_image_dsc_t {header, data_size, data}
// (lvgl/src/draw/lv_image_buf.h) in per-size tables, plus white+alpha PNG/SVG copies for the companion.
//
//   node export_handoff_icons.cjs            full export: src/cc_icons.cpp/.h, assets/handoff-icons,
//                                            then (after the 1x fidelity gate) assets/lcd-icons @2x/@3x
//   node export_handoff_icons.cjs --check    regenerate in memory; exit 1 on any byte difference or a
//                                            missing file (gate A6); writes nothing
//   node export_handoff_icons.cjs --png-only [--scales 2,3] [--out <dir>] [--force]
//                                            hi-res PNGs only ({name}-{size}@{k}x.png, default out:
//                                            assets/lcd-icons). It first renders @1x in memory and requires
//                                            its alpha to equal every shipped handoff-icons mask (fidelity
//                                            gate), and it NEVER writes the firmware sources or
//                                            assets/handoff-icons.
// Any other argument is refused, so only a bare run takes the full (firmware) export path.
'use strict';
const fs = require('fs'); const path = require('path');
function loadSharp() {
  // SHARP_MODULE_PATH may point at a sharp install outside this tree; otherwise a normal require.
  const bundled = process.env.SHARP_MODULE_PATH;
  if (bundled) { try { return require(bundled); } catch (e) { /* fall back */ } }
  return require('sharp');
}
const sharp = loadSharp();
const root = path.resolve(__dirname, '..');
const DESIGN = path.join(root, 'app/design-reference');
const BS_FILE = path.join(DESIGN, 'design_handoff_nano_d_master_r2.1/prototypes/Browse and Snap.dc.html');
const KF_FILE = path.join(DESIGN, 'design_handoff_nano_d_master_r2.1/prototypes/Knob Face.dc.html');
const FIRMWARE_SRC = path.join(root, 'firmware/src');
const out = path.join(root, 'app/assets/handoff-icons');
const HIRES_OUT = path.join(root, 'app/assets/lcd-icons');
const STROKE = {16: '2.3', 20: '2.3', 26: '2.1'};
const SIZES = [16, 20, 26];
const HIRES_SCALES = [2, 3];
const ARGS = process.argv.slice(2);
const PNG_ONLY = ARGS.includes('--png-only');
const CHECK_ONLY = ARGS.length === 1 && ARGS[0] === '--check';

// PRESENTATION_V5 section 9.1, in CCIcon order (cc_presentation.h, append only). `id` is the enum
// value; `dotfill` and `heartfill` are internal (never on the wire). `src`: 'bs' = BS I[key] (+ HALF[half]),
// drift-checked; 'legacy' = the cc5.3 path, unchanged and pinned by --check (no design file read);
// 'internal' = drawn here, drift-checked through `drift` (the BS I[key] string it is made of) when set.
// `sizes`: the firmware masks (sizes by use); `desktop`: the desktop copies' sizes (default: every size).
const HEART = 'M20.8 5.6a5.5 5.5 0 0 0-7.8 0L12 6.7l-1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 22l8.8-8.6a5.5 5.5 0 0 0 0-7.8z';
const TOKENS = [
  {token: 'play', id: 1, src: 'bs', key: 'play', stroke: 'M7 4.5v15l12-7.5z', sizes: [20, 26]},
  {token: 'pause', id: 2, src: 'bs', key: 'pause', stroke: 'M8 5v14M16 5v14', sizes: [20, 26]},
  {token: 'list', id: 3, src: 'bs', key: 'note', sizes: [20, 26],
   stroke: 'M9 18V5l12-2v13M9 18a3 3 0 1 1-6 0 3 3 0 0 1 6 0zM21 16a3 3 0 1 1-6 0 3 3 0 0 1 6 0z'},
  {token: 'win', id: 4, src: 'bs', key: 'win', stroke: 'M3 5h18v14H3zM3 9h18', sizes: [20, 26]},
  {token: 'tracks', id: 5, src: 'bs', key: 'list', sizes: [20, 26],
   stroke: 'M8 6h13M8 12h13M8 18h13M3.5 6h.01M3.5 12h.01M3.5 18h.01'},
  {token: 'back', id: 6, src: 'bs', key: 'back', stroke: 'M15 18l-6-6 6-6', sizes: [20]},
  {token: 'home', id: 7, src: 'legacy', key: 'home', stroke: 'M3 10.5 12 3l9 7.5V21h-6v-7H9v7H3z', sizes: [20]},
  {token: 'more', id: 8, src: 'legacy', key: 'more', stroke: 'M12 5v14M5 12h14', sizes: [20]},
  {token: 'prev', id: 9, src: 'bs', key: 'prev', stroke: 'M19 5v14l-9-7zM6 5v14', sizes: [20, 16]},
  {token: 'next', id: 10, src: 'bs', key: 'tracks', stroke: 'M5 5v14l9-7zM18 5v14', sizes: [20, 16]},
  {token: 'switch', id: 11, src: 'bs', key: 'check', stroke: 'M20 6L9 17l-5-5', sizes: [20]},
  {token: 'cancel', id: 12, src: 'legacy', key: 'cancel', stroke: 'M18 6 6 18M6 6l12 12', sizes: [20]},
  {token: 'expand', id: 13, src: 'bs', key: 'expand', stroke: 'M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7', sizes: [20]},
  {token: 'clock', id: 14, src: 'bs', key: 'clock', stroke: 'M12 7v5l3 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0',
   sizes: [20]},
  {token: 'playlists', id: 15, src: 'bs', key: 'queue', sizes: [20],
   stroke: 'M21 15V6M18.5 18a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM12 12H3M16 6H3M12 18H3'},
  {token: 'playnext', id: 16, src: 'bs', key: 'next', stroke: 'M11 12H3M16 6H3M16 18H3M18 9v6M21 12h-6', sizes: [20]},
  {token: 'seek', id: 17, src: 'bs', key: 'seek', stroke: 'M3 12h8.7M17.7 12H21M14.7 9a3 3 0 1 1 0 6 3 3 0 0 1 0-6z',
   sizes: [20]},
  {token: 'shuffle', id: 18, src: 'bs', key: 'shuffle', sizes: [20],
   stroke: 'M2 18h1.4c1.3 0 2.5-.6 3.3-1.7l6.1-8.6c.7-1.1 2-1.7 3.3-1.7H22M18 2l4 4-4 4M2 6h1.9c1.5 0 2.9.9 3.6 2.2M22 18h-5.9c-1.3 0-2.6-.7-3.3-1.8l-.5-.8M18 14l4 4-4 4'},
  {token: 'heart', id: 19, src: 'bs', key: 'heart', stroke: HEART, sizes: [20]},
  {token: 'snapleft', id: 20, src: 'bs', key: 'rect', half: 'left', stroke: 'M3 5h18v14H3z', fill: ['M3 5h9v14H3z'],
   sizes: [20]},
  {token: 'snapright', id: 21, src: 'bs', key: 'rect', half: 'right', stroke: 'M3 5h18v14H3z', fill: ['M12 5h9v14h-9z'],
   sizes: [20]},
  // Tracks position-row centre: BS:305 draws a 6 px disc in the 16 px row; r 4.5 at (12, 12) of 24 units.
  {token: 'dotfill', id: null, src: 'internal', fill: ['M7.5 12a4.5 4.5 0 1 0 9 0 4.5 4.5 0 1 0-9 0z'], sizes: [16],
   desktop: [16]},
  // [r2.2] Tone `liked` (heart + lit "on", P5-R29): the `heart` path as a fill path, footer 20 px, drawn in
  // #A3244A. Same BS `heart:` string as `heart` (R22 BS:1268 `fill: I.heart`), so the same drift needle.
  {token: 'heartfill', id: null, src: 'internal', key: 'heart', drift: HEART, fill: [HEART], sizes: [20]},
];
// The markup the design draws each size with (drift gate): the strokes above follow it.
const STYLE_ANCHORS = [
  [BS_FILE, '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" ' +
            'stroke-linecap="round" stroke-linejoin="round"><path d="{{ f.d }}"></path><path d="{{ f.fill }}" ' +
            'fill="currentColor" stroke="none"></path></svg>', 'footer 20 px, stroke 2.3, fill paths'],
  [BS_FILE, '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="{{ tpc }}" stroke-width="2.3" ' +
            'stroke-linecap="round" stroke-linejoin="round"><path d="M19 5v14l-9-7zM6 5v14"></path></svg>',
   'Tracks row 16 px, stroke 2.3'],
  [BS_FILE, '<div style="width:6px;height:6px;border-radius:50%;background:{{ tdc }}"></div>', 'Tracks row 6 px dot'],
  [KF_FILE, '<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1"',
   'idle row 26 px, stroke 2.1'],
];

function firmwareMasks() {
  const masks = [];
  for (const e of TOKENS) for (const size of e.sizes) masks.push([e, size]);
  return masks;
}

// Desktop copies: every token at every size, unless the entry names its own (dotfill: 16 px only).
function desktopMasks() {
  const masks = [];
  for (const e of TOKENS) for (const size of (e.desktop || SIZES)) masks.push([e, size]);
  return masks;
}

// The design string an entry is drift-checked against: a BS token's stroke, an internal entry's `drift`.
// Legacy tokens (cc5.3 paths) and dotfill have none: the old design table is not read (9.2 item 1).
function driftPath(e) { return e.src === 'bs' ? e.stroke : e.src === 'internal' ? e.drift : undefined; }

function driftGate() {
  const text = fs.readFileSync(BS_FILE, 'utf8');
  const problems = [];
  let checked = 0;
  for (const e of TOKENS) {
    const d = driftPath(e);
    if (!d) continue;
    checked++;
    const needle = `${e.key}: '${d}'`;
    if (!text.includes(needle)) problems.push(`${e.token}: ${needle} not in ${BS_FILE}`);
    if (e.half) {
      const half = `${e.half}: '${e.fill[0]}'`;
      if (!/const HALF = \{[^\n]*\};/.test(text) || !text.match(/const HALF = \{[^\n]*\};/)[0].includes(half))
        problems.push(`${e.token}: HALF ${half} not in ${BS_FILE}`);
    }
  }
  for (const [file, anchor, what] of STYLE_ANCHORS)
    if (!fs.readFileSync(file, 'utf8').includes(anchor)) problems.push(`${what}: markup not found in ${file}`);
  if (problems.length)
    throw new Error('drift gate: the r2.1 design no longer matches the icon table; nothing written:\n  ' +
                    problems.join('\n  '));
  return checked;
}

function iconSvg(e, size, px) {
  let body = '';
  if (e.stroke) body += `<path d="${e.stroke}" fill="none" stroke="white" stroke-width="${STROKE[size]}" ` +
                        'stroke-linecap="round" stroke-linejoin="round"/>';
  for (const d of e.fill || []) body += `<path d="${d}" fill="white" stroke="none"/>`;
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${px}" height="${px}" viewBox="0 0 24 24">${body}</svg>`;
}

async function alphaOf(png) {
  const {data, info} = await sharp(png).ensureAlpha().raw().toBuffer({resolveWithObject: true});
  const alpha = Buffer.alloc(info.width * info.height);
  for (let i = 3, j = 0; i < data.length; i += info.channels, j++) alpha[j] = data[i];
  return {alpha, width: info.width, height: info.height};
}

async function render(e, size, k = 1) {
  const svg = iconSvg(e, size, size * k);
  const png = await sharp(Buffer.from(svg)).png().toBuffer();
  const {alpha, width, height} = await alphaOf(png);
  if (width !== size * k || height !== size * k) throw new Error(`${e.token}-${size}@${k}x: rendered ${width}x${height}`);
  return {svg, png, alpha};
}

function parsePngOnlyArgs(args) {
  const options = {scales: HIRES_SCALES.slice(), out: HIRES_OUT, force: false};
  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    if (arg === '--png-only') continue;
    if (arg === '--force') { options.force = true; continue; }
    if (arg === '--scales' && i + 1 < args.length) {
      options.scales = args[++i].split(',').map(Number);
      if (!options.scales.length || options.scales.some(k => !Number.isInteger(k) || k < 2 || k > 8))
        throw new Error('--scales takes integers 2..8 (the 1x masks are the shipped ones)');
      continue;
    }
    if (arg === '--out' && i + 1 < args.length) { options.out = path.resolve(args[++i]); continue; }
    throw new Error(`unknown argument ${arg}`);
  }
  const guarded = [path.join(root, 'firmware'), out].map(p => path.resolve(p).toLowerCase());
  if (guarded.some(p => options.out.toLowerCase() === p || options.out.toLowerCase().startsWith(p + path.sep)))
    throw new Error('--png-only never writes into the firmware sources or assets/handoff-icons');
  return options;
}

// [r2.2] heartfill (harness `icons`): the heart path filled. The stroked heart's interior (its unlit pixels
// that no 4-connected unlit path joins to the border) must be solid in heartfill, and nothing outside the
// stroked outline may be lit; the fill path is the heart's own string.
function heartfillCheck(heart, fill, size = 20) {
  const e = TOKENS.find(x => x.token === 'heartfill'), h = TOKENS.find(x => x.token === 'heart');
  if (!e || e.stroke || e.fill.length !== 1 || e.fill[0] !== h.stroke) throw new Error('heartfill is not the heart path as a fill');
  const outside = new Uint8Array(size * size), stack = [];
  for (let i = 0; i < size; i++) stack.push([i, 0], [i, size - 1], [0, i], [size - 1, i]);
  while (stack.length) {
    const [x, y] = stack.pop();
    if (x < 0 || y < 0 || x >= size || y >= size) continue;
    const k = y * size + x;
    if (outside[k] || heart[k] !== 0) continue;
    outside[k] = 1;
    stack.push([x + 1, y], [x - 1, y], [x, y + 1], [x, y - 1]);
  }
  let interior = 0;
  for (let k = 0; k < size * size; k++) {
    if (outside[k] && fill[k] > 5) throw new Error(`heartfill-${size}: lit outside the heart outline at ${k % size},${(k / size) | 0}`);
    if (!outside[k] && heart[k] === 0) {
      interior++;
      if (fill[k] < 250) throw new Error(`heartfill-${size}: the heart's interior is not filled at ${k % size},${(k / size) | 0}`);
    }
  }
  if (interior < 20) throw new Error(`heartfill-${size}: the stroked heart has only ${interior} interior pixels`);
  return interior;
}

function cppName(e, size) { return `${e.token}_${size}`; }

function firmwareSources(rendered) {
  const masks = firmwareMasks();
  const bytes = masks.reduce((n, [, size]) => n + size * size, 0);
  const counts = SIZES.map(size => `${masks.filter(([, s]) => s === size).length} x ${size} px`).join(' + ');
  let cpp = '// Generated by harness/export_handoff_icons.cjs. Do not edit by hand.\n' +
    '// A8 masks of the r2.1 design icons (PRESENTATION_V5.md section 9.1; Browse and Snap.dc.html I/HALF),\n' +
    '// trimmed per use: stroke 2.3 @20 px (footer), 2.1 @26 px (idle row), 2.3 @16 px (Tracks row);\n' +
    '// internal fills: dotfill @16 px (Tracks row), heartfill @20 px (r2.2 tone liked, the heart filled).\n' +
    `// Masks: ${counts} = ${bytes} B.\n` +
    '#include "cc_icons.h"\n#include <string.h>\n' +
    '#if LV_BIG_ENDIAN_SYSTEM\n#error "cc_icons.cpp header initialisers assume the little-endian lv_image_header_t field order"\n#endif\n' +
    '// lv_image_header_t (LVGL 9.0, little endian): magic, cf, flags, w, h, stride, reserved_2.\n' +
    '// lv_image_dsc_t: header, data_size, data.\n' +
    'namespace {\n';
  for (const [e, size] of masks) {
    const sym = cppName(e, size);
    const alpha = rendered.get(`${e.token}-${size}`).alpha;
    cpp += `const uint8_t ${sym}_data[] = {${Array.from(alpha).join(',')}};\n`;
    cpp += `const lv_image_dsc_t ${sym} = { {LV_IMAGE_HEADER_MAGIC, LV_COLOR_FORMAT_A8, 0, ${size}, ${size}, ${size}, 0}, ` +
           `${alpha.length}, ${sym}_data };\n`;
  }
  cpp += 'struct IconEntry { const char* name; const lv_image_dsc_t* image; };\n';
  for (const size of SIZES) {
    const rows = masks.filter(([, s]) => s === size).map(([e]) => `{"${e.token}", &${cppName(e, size)}}`);
    cpp += `const IconEntry kIcons${size}[] = {${rows.join(', ')}};\n`;
  }
  cpp += 'const lv_image_dsc_t* find(const IconEntry* table, size_t count, const char* name) {\n' +
         '    for (size_t i = 0; i < count; ++i)\n' +
         '        if (!strcmp(table[i].name, name)) return table[i].image;\n' +
         '    return nullptr;\n' +
         '}\n' +
         '}\n' +
         'const lv_image_dsc_t* cc_icon(const char* name, int size) {\n' +
         '    if (!name || !*name) return nullptr;\n' +
         '    switch (size) {\n';
  for (const size of SIZES)
    cpp += `    case ${size}: return find(kIcons${size}, sizeof(kIcons${size}) / sizeof(kIcons${size}[0]), name);\n`;
  cpp += '    default: return nullptr;\n    }\n}\n';
  const header = '#pragma once\n#include <lvgl.h>\n' +
    '// Design icon masks (A8), generated by harness/export_handoff_icons.cjs.\n' +
    '// Sizes by use (PRESENTATION_V5.md section 9.1): 20 px every wire token and the internal "heartfill"\n' +
    '// (footer; tone liked draws it in #A3244A instead of "heart", P5-R29); 26 px play, pause, list, win,\n' +
    '// tracks (Home idle row); 16 px prev, next and the internal "dotfill" (Tracks row).\n' +
    '// Returns nullptr for an unknown name or a token without a mask at that size (the caller hides it).\n' +
    'const lv_image_dsc_t* cc_icon(const char* name, int size);\n';
  return {cpp, header, bytes};
}

function manifest(bytes) {
  const firmware = {};
  for (const e of TOKENS) firmware[e.token] = e.sizes.slice().sort((a, b) => a - b);
  return JSON.stringify({
    generatedBy: 'harness/export_handoff_icons.cjs',
    contract: 'PRESENTATION_V5.md section 9',
    source: 'design_handoff_nano_d_master_r2.1/prototypes/Browse and Snap.dc.html I/HALF (BS:485-495); ' +
            'home, more, cancel: the cc5.3 paths, unchanged',
    viewBox: 24, strokes: STROKE,
    tokens: TOKENS.map(e => ({token: e.token, id: e.id, design: e.src === 'bs' ? e.key + (e.half ? '+HALF.' + e.half : '') :
                              e.src === 'legacy' ? 'legacy ' + e.key : 'internal' + (e.drift ? ' ' + e.key + ' filled' : ''),
                              fill: !!(e.fill && e.fill.length)})),
    firmwareSizes: firmware,
    firmwareMaskBytes: bytes,
    desktopSizes: 'every wire token and heartfill at 16, 20 and 26 px (dotfill at 16 px); @2x/@3x in assets/lcd-icons',
  }, null, 2) + '\n';
}

const README = 'Knob icon masks of the r2.1 design (PRESENTATION_V5.md section 9): the exact `I`/`HALF` paths of ' +
  'design_handoff_nano_d_master_r2.1 Browse and Snap.dc.html (legacy home, more and cancel keep their cc5.3 ' +
  'paths). White + alpha PNG and SVG at 16, 20 and 26 native pixels on a 24-unit viewBox, ' +
  'round caps and joins; strokes 2.3 at 20 px (footer), 2.1 at 26 px (idle row), 2.3 at 16 px (Tracks row); ' +
  'the snap halves, the internal dotfill disc and the internal heartfill (r2.2: the heart path filled, ' +
  'tone liked, drawn in #A3244A) are filled. The firmware masks (src/cc_icons.cpp) are ' +
  'trimmed per use; icons.json lists their sizes. Generated by harness/export_handoff_icons.cjs ' +
  '(--check verifies every file); not substituted with a system font.\n';

async function buildAll() {
  const tokens = driftGate();
  const rendered = new Map();
  for (const [e, size] of desktopMasks()) rendered.set(`${e.token}-${size}`, await render(e, size));
  // Sizes-by-use self-checks (harness `icons`): every 9.1 token/size exists; snap masks carry their half.
  for (const [e, size] of firmwareMasks()) if (!rendered.has(`${e.token}-${size}`)) throw new Error(`${e.token}-${size} missing`);
  for (const [token, filled, empty] of [['snapleft', 6, 14], ['snapright', 14, 6]]) {
    const a = rendered.get(`${token}-20`).alpha;
    if (a[10 * 20 + filled] < 250 || a[10 * 20 + empty] > 5) throw new Error(`${token}-20: the filled half is not filled`);
  }
  heartfillCheck(rendered.get('heart-20').alpha, rendered.get('heartfill-20').alpha);
  let rejects = false;                     // negative control: the stroked heart must not pass as heartfill
  try { heartfillCheck(rendered.get('heart-20').alpha, rendered.get('heart-20').alpha); } catch (e) { rejects = true; }
  if (!rejects) throw new Error('heartfill self-check accepts the stroked heart');
  const {cpp, header, bytes} = firmwareSources(rendered);
  if (bytes !== 12948) throw new Error(`firmware masks ${bytes} B, section 9.1 says 12,948 B (r2.2: 12,548 + heartfill 400)`);
  const files = new Map();       // absolute path -> Buffer
  files.set(path.join(FIRMWARE_SRC, 'cc_icons.cpp'), Buffer.from(cpp));
  files.set(path.join(FIRMWARE_SRC, 'cc_icons.h'), Buffer.from(header));
  for (const [e, size] of desktopMasks()) {
    const r = rendered.get(`${e.token}-${size}`);
    files.set(path.join(out, `${e.token}-${size}.svg`), Buffer.from(r.svg));
    files.set(path.join(out, `${e.token}-${size}.png`), r.png);
  }
  files.set(path.join(out, 'README.md'), Buffer.from(README));
  files.set(path.join(out, 'icons.json'), Buffer.from(manifest(bytes)));
  // 1x fidelity gate before the hi-res set: the shipped (here: just rendered) mask equals the SVG's.
  for (const [e, size] of desktopMasks()) {
    const again = await alphaOf(await sharp(Buffer.from(iconSvg(e, size, size))).png().toBuffer());
    if (!again.alpha.equals(rendered.get(`${e.token}-${size}`).alpha)) throw new Error(`fidelity gate: ${e.token}-${size}`);
  }
  for (const k of HIRES_SCALES) for (const [e, size] of desktopMasks())
    files.set(path.join(HIRES_OUT, `${e.token}-${size}@${k}x.png`), (await render(e, size, k)).png);
  return {files, tokens, bytes, masks: firmwareMasks().length, desktop: desktopMasks().length};
}

function staleExtras(files) {
  // Files an earlier table produced that this one no longer does (e.g. ok, dot, warn, usb): reported, kept.
  const produced = new Set([...files.keys()].map(p => path.resolve(p).toLowerCase()));
  const extras = [];
  for (const [dir, pattern] of [[out, /^[a-z]+-(16|20|26)\.(png|svg)$/], [HIRES_OUT, /^[a-z]+-(16|20|26)@\dx\.png$/]])
    for (const name of fs.readdirSync(dir))
      if (pattern.test(name) && !produced.has(path.resolve(dir, name).toLowerCase())) extras.push(name);
  return extras;
}

async function main() {
  const {files, tokens, bytes, masks, desktop} = await buildAll();
  const extras = staleExtras(files);
  if (CHECK_ONLY) {
    const stale = [];
    for (const [file, data] of files) if (!fs.existsSync(file) || !fs.readFileSync(file).equals(data)) stale.push(file);
    for (const file of stale) console.log(`STALE ${file}`);
    console.log(`check: drift gate ${tokens} design paths verbatim; ${files.size} files ` +
                (stale.length ? `-- ${stale.length} differ or are missing` : 'up to date') +
                `; firmware ${masks} masks ${bytes} B` +
                (extras.length ? `; ${extras.length} file(s) from an earlier table kept: ${extras.join(', ')}` : ''));
    process.exit(stale.length ? 1 : 0);
  }
  let written = 0;
  for (const [file, data] of files) {
    fs.mkdirSync(path.dirname(file), {recursive: true});
    if (fs.existsSync(file) && fs.readFileSync(file).equals(data)) continue;
    fs.writeFileSync(file, data); written++;
  }
  console.log(`Exported ${masks} firmware masks (${bytes} B) and ${desktop} desktop icons (+ @${HIRES_SCALES.join('x/@')}x); ` +
              `drift gate ${tokens} design paths verbatim; ${written}/${files.size} files written` +
              (extras.length ? `; kept ${extras.length} file(s) from an earlier table: ${extras.join(', ')}` : ''));
}

// Hi-res PNGs only (kept next to the dispatch: this function never names the firmware files).
async function pngOnly(options) {
  driftGate();
  // Fidelity gate: the same rasteriser, paths and strokes reproduce every shipped 1x mask exactly.
  const masks = desktopMasks();
  let same = 0;
  for (const [e, size] of masks) {
    const mine = await render(e, size);
    const shipped = await alphaOf(fs.readFileSync(path.join(out, `${e.token}-${size}.png`)));
    if (shipped.width !== size || shipped.height !== size || !mine.alpha.equals(shipped.alpha))
      throw new Error(`fidelity gate: ${e.token}-${size} at 1x differs from the shipped mask; nothing written`);
    same++;
  }
  fs.mkdirSync(options.out, {recursive: true});
  let written = 0, unchanged = 0;
  for (const k of options.scales) for (const [e, size] of masks) {
    const {png} = await render(e, size, k);
    const target = path.join(options.out, `${e.token}-${size}@${k}x.png`);
    if (fs.existsSync(target)) {
      if (fs.readFileSync(target).equals(png)) { unchanged++; continue; }
      if (!options.force) throw new Error(`${target} exists with other content (use --force)`);
    }
    fs.writeFileSync(target, png); written++;
  }
  console.log(`PNG-only: 1x fidelity ${same}/${masks.length} shipped masks identical; ` +
              `${written} written, ${unchanged} unchanged (@${options.scales.join('x/@')}x) in ${options.out}; ` +
              'firmware sources not touched');
}

if (PNG_ONLY) {
  let options;
  try { options = parsePngOnlyArgs(ARGS); } catch (e) { console.error(String(e.message || e)); process.exit(1); }
  pngOnly(options).catch(e => { console.error(e); process.exit(1); });
} else if (CHECK_ONLY) {
  main().catch(e => { console.error(String(e && e.stack || e)); process.exit(1); });
} else if (ARGS.length) {
  console.error(`unknown arguments ${ARGS.join(' ')}; a bare run is the full export (firmware cc_icons.cpp/.h included), ` +
                '--check verifies it');
  process.exit(1);
} else {
  main().catch(e => { console.error(String(e && e.stack || e)); process.exit(1); });
}
