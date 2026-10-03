'use strict';
/*
 * Target golden for the "Warm · alive" LED engine (firmware/ALIVE.md section 11.2).
 *
 * Runs the NEW design's knob-model.js (design-reference/design_handoff_led_choreography/)
 * unmodified in a node `vm` context with inert window/document shims, exactly like
 * tests/js/knob_golden.cjs does for the older model: NanoModel.COLORS is PRE-POPULATED
 * from tests/fixtures/dominant_reference.json, and the one mechanical source patch is the
 * same export-line patch knob_golden.cjs applies (it exposes the private tint() helper
 * next to the public API; every function body runs as shipped). For every case it dumps
 * view(st, {led:'alive'}) (finishAlive(): ring [c, l, a], buttons {tone, c, l, a},
 * ledSleep, cursor, mode) plus the plain view's lcd + foot, which
 * tests/tools/knob_adapter.py maps to the v4 frame the host would send.
 *
 * The animator flags of ALIVE.md 5.4 are evaluated with the design's OWN expressions,
 * lifted verbatim from the logic block of "Ring Choreography v2.dc.html" (each anchor must
 * occur exactly once or this script throws; the expression text is written to the fixture):
 *   asleep (draw() line 269), heat (273), embers (280), pausedPlay (287), Working comet =
 *   pending (306), tint (308-309), song hand (313), and the SWITCHED colour of detect()
 *   (199, 214-215). ``wash`` is that colour on the variant's own view; ``washRef`` is it on
 *   the reference view (same state awake, no flash, a pending list request shown as ready):
 *   the selected entry's accent of ALIVE.md 6.4.
 * finishAlive's sat() is lifted the same way and run over its whole domain ("sat": the channel
 * table's sha256, the exact .5 roundings and the spread 29/30 threshold), so the 11.2 remap
 * "sat(x) -> sat(x)" is checked on every colour, not only on the accents the cases reach.
 *
 * Cases: every scenarios() and stress() state, the knob_golden.cjs states (LED rows, volume
 * sweep 0..100 confirmed / pending up / pending down, pulses, flashes, lists, tracks, more
 * than 20 windows, disconnected) and a few alive states (Home pausing / starting, the Sonos
 * notice with a stale pending request). Variants per case (patch applied to the state):
 * base; asleep (st.asleep = true); flash ok / err (st.flash = {kind, id: 1}) and err while
 * asleep; external (st.ext = true) and external while asleep on Home with volume ==
 * confirmed. The volume sweep carries base + asleep (+ external on the confirmed rows).
 * Flash variants are not generated while disconnected (no frame reaches the knob).
 * A variant whose tick-1 ring differs (pending / loading / reconnecting pulse LOW) carries
 * "tick1". A case with "alt" {tag, patch} also dumps each variant with that patch applied:
 * the expected value of a listed deviation that the design itself can draw (V4-9.5: the
 * 20-entry window, entries outside it marked closed; D5: no reconnecting pulse = the
 * 'missing' view; D15: the Sonos notice ignores a stale request = volume at confirmed).
 *
 * Usage: node alive_golden.cjs <design dir> <dominant_reference.json> [out.json]
 * Without out.json the JSON goes to stdout. Output is deterministic.
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const [designDir, referencePath, outPath] = process.argv.slice(2);
if (!designDir || !referencePath) {
  process.stderr.write('usage: node alive_golden.cjs <design dir> <dominant_reference.json> [out.json]\n');
  process.exit(2);
}
const MODEL_PATH = path.join(designDir, 'knob-model.js');
const HTML_PATH = path.join(designDir, 'Ring Choreography v2.dc.html');
const reference = JSON.parse(fs.readFileSync(referencePath, 'utf8'));
if (!reference.colors || typeof reference.colors !== 'object') throw new Error('reference has no "colors" map');

function once(text, anchor, what) {
  const count = text.split(anchor).length - 1;
  if (count !== 1) throw new Error(`alive_golden: ${what} anchor found ${count} time(s), expected exactly once: ${anchor}`);
  return text.indexOf(anchor);
}
// Text after `before` (which must occur once) up to the first `after`.
function lift(text, before, after, what) {
  const start = once(text, before, what) + before.length;
  const end = text.indexOf(after, start);
  if (end < 0) throw new Error(`alive_golden: ${what} has no terminator ${after}`);
  return text.slice(start, end).trim();
}
// Text between the last `open` before `inside` (which must occur once) and the first `close`
// at or after it: the condition of the `if (...)` that contains `inside`.
function liftAround(text, inside, open, close, what) {
  const at = once(text, inside, what);
  const start = text.lastIndexOf(open, at);
  const end = text.indexOf(close, at);
  if (start < 0 || end < 0) throw new Error(`alive_golden: ${what} is not inside ${open} ... ${close}`);
  return text.slice(start + open.length, end).trim();
}

// ------------------------------------------------------------------ knob-model.js
const inert = name => () => { throw new Error(`alive_golden: ${name} is not available (no DOM, no network)`); };
const context = vm.createContext({
  window: {},
  document: { createElement: inert('document.createElement'), head: { appendChild: inert('document.head') } },
  Image: class { set src(v) { throw new Error('alive_golden: image load ' + v); } },
  setTimeout: inert('setTimeout'),
  clearTimeout: inert('clearTimeout')
});
const EXPORT_ANCHOR = 'window.NanoModel = { loadColors,';
const modelSource = fs.readFileSync(MODEL_PATH, 'utf8');
once(modelSource, EXPORT_ANCHOR, 'knob-model.js export');
vm.runInContext(modelSource.replace(EXPORT_ANCHOR, 'window.NanoModel = { __tint: tint, loadColors,'),
  context, { filename: 'knob-model.js' });
const M = context.window.NanoModel;
for (const key of Object.keys(reference.colors).sort()) M.COLORS[key] = reference.colors[key];

// finishAlive() constants, read from its source (the Python test pins the remap to them).
const paletteLine = lift(modelSource, "function finishAlive(light0) {", ';', 'finishAlive palette');
const designPalette = {};
for (const m of paletteLine.matchAll(/(\w+) = '(\d+,\d+,\d+)'/g)) designPalette[m[1]] = m[2];
for (const k of ['WARM', 'AG', 'AR', 'AAMB', 'ABLUE']) if (!designPalette[k]) throw new Error('finishAlive palette misses ' + k);
const alphaLine = lift(modelSource, 'const AW = ', ';', 'finishAlive alpha tables');
const AW = JSON.parse(alphaLine.slice(0, alphaLine.indexOf(']') + 1));
const AS = JSON.parse(lift(modelSource, ', AS = ', ';', 'finishAlive resting alphas'));
// view()'s own colours, the inputs of finishAlive's remap (W, G, R).
const viewPalette = {};
for (const m of lift(modelSource, 'const W = ', ';', 'view palette').matchAll(/(\w+)? ?=? ?'(\d+,\d+,\d+)'/g)) viewPalette[m[1] || 'W'] = m[2];
for (const k of ['W', 'G', 'R']) if (!viewPalette[k]) throw new Error('view palette misses ' + k);

// ------------------------------------------------ the design's flag expressions (draw/detect)
const html = fs.readFileSync(HTML_PATH, 'utf8');
const EXPR = {
  asleep: lift(html, 'const asleep = ', ', off = ', 'draw() asleep'),
  heat: lift(html, 'const heat = ', ';', 'draw() heat'),
  embers: liftAround(html, ') ta *= 0.72 + 0.28', 'if (', ') ta *= 0.72', 'draw() embers'),
  pausedPlay: lift(html, 'const pausedPlay = ', ';', 'draw() pausedPlay'),
  pending: liftAround(html, ') comet(t / 1400 * 60, 1, 8, HOT, WARM, 0.5);', 'if (', ') comet(t / 1400', 'draw() Working comet'),
  tintOn: lift(html, 'const tintOn = ', ';', 'draw() tintOn'),
  tintColour: lift(html, 'const tt = tintOn ? ', ' : [0, 0, 0]', 'draw() tint colour'),
  songHand: liftAround(html, "this.s.playing && v.mode === 'home'", 'if (', ') {', 'draw() song hand'),
  colAt: lift(html, 'const colAt = ', ';', 'detect() colAt'),
  washColour: 'colAt(' + lift(html, 'const c = colAt(', ');', 'detect() SWITCHED colour') + ')',
  wash: liftAround(html, ") this.play('wash'", 'if (', ") this.play('wash'", 'detect() SWITCHED test')
};
if (!EXPR.songHand.includes('this.s.playing')) throw new Error('song hand anchor drifted: ' + EXPR.songHand);
if (EXPR.pending !== 'this.M.isPending(this.s)') throw new Error('Working comet anchor drifted: ' + EXPR.pending);
const MODEL_WARM = lift(html, "const MODEL_WARM = '", "'", 'MODEL_WARM');
if (MODEL_WARM !== designPalette.WARM) throw new Error('MODEL_WARM differs from finishAlive WARM');
// Each flag is a function of (v, s): the view, the model state; this = {s, M} as in the component.
const flagFns = vm.runInNewContext(`({
  asleep(v) { return ${EXPR.asleep}; },
  heat(v, asleep) { return ${EXPR.heat}; },
  ember(heat, r) { return !!(${EXPR.embers}); },
  pausedPlay(v, asleep) { return !!(${EXPR.pausedPlay}); },
  pending() { return !!(${EXPR.pending}); },
  tint(v, asleep, MODEL_WARM) { const tintOn = ${EXPR.tintOn}; return tintOn ? ${EXPR.tintColour.replace('rgbN(', '(')} : null; },
  songHand(v, asleep) { return !!(${EXPR.songHand}); },
  wash(pv, MODEL_WARM) { const colAt = ${EXPR.colAt}; const c = ${EXPR.washColour}; return (${EXPR.wash}) ? c : null; }
})`, {});

function flags(st, v) {
  const self = { s: st, M };
  const asleep = flagFns.asleep.call(self, v);
  const heat = flagFns.heat.call(self, v, asleep);
  const embers = [];
  v.ring.forEach((r, i) => { if (r && r.l && flagFns.ember.call(self, heat, r)) embers.push(i); });
  return {
    pending: flagFns.pending.call(self), heat, embers,
    pausedPlay: flagFns.pausedPlay.call(self, v, asleep),
    tint: flagFns.tint.call(self, v, asleep, MODEL_WARM),
    songHand: flagFns.songHand.call(self, v, asleep),
    wash: flagFns.wash.call(self, v, MODEL_WARM)
  };
}

// ------------------------------------------------------------------------ dumps
const plain = o => JSON.parse(JSON.stringify(o));
function merge(t, p) {       // knob-model.js merge(): objects recurse, arrays and scalars assign
  for (const k in p) {
    if (p[k] && typeof p[k] === 'object' && !Array.isArray(p[k]) && t[k] && typeof t[k] === 'object') merge(t[k], p[k]);
    else t[k] = p[k];
  }
  return t;
}
const patched = (st, patch) => merge(plain(st), plain(patch || {}));
const ICON_BY_PATH = {};
for (const k of Object.keys(M.I)) ICON_BY_PATH[M.I[k]] = k;
const iconName = d => (d ? (ICON_BY_PATH[d] || '?') : '');
const aliveRing = ring => ring.map(r => (r && r.l ? [r.c, r.l, r.a] : null));

function lcdOut(lcd) {
  const out = {};
  for (const k of Object.keys(lcd)) {
    if (k === 'center') out.center = lcd.center.map(f => ({ icon: iconName(f.d), w: f.w, tone: f.tone }));
    else if (k === 'pos') out.pos = lcd.pos.map(p => ({ icon: iconName(p.d), c: p.c }));
    else out[k] = lcd[k];
  }
  if (lcd.art) out.artLocal = lcd.art.indexOf('url("assets/covers/') === 0;
  return out;
}

function alive(st) {
  const v = M.view(st, { led: 'alive' });
  if (!v.alive) throw new Error('view(st, {led:"alive"}) did not run finishAlive');
  return {
    view: v,
    out: {
      ring: aliveRing(v.ring),
      buttons: v.buttons.map(b => ({ tone: b.tone, c: b.c, l: b.l, a: b.a })),
      ledSleep: v.ledSleep, cursor: v.cursor, mode: v.mode
    }
  };
}

// The reference view of 6.4's "selected entry's accent": awake, no flash, a pending list
// request drawn as its ready/browsing state (the design draws the pending pulse WARM on Recent).
function referenceState(st) {
  const r = patched(st, { asleep: false, flash: null });
  if (r.recent && r.recent.status === 'pending') r.recent.status = 'ready';
  if (r.win && r.win.status === 'pending') r.win.status = 'browsing';
  return r;
}

function variant(key, st0, patch, alt) {
  const st = patched(st0, patch);
  const a = alive(st);
  const plainView = M.view(st);
  const entry = {
    key, patch: plain(patch),
    lcd: lcdOut(plainView.lcd),
    foot: plainView.foot.map(f => ({ icon: iconName(f.d), w: f.w, tone: f.tone })),
    alive: a.out,
    flags: Object.assign(flags(st, a.view), { washRef: flags(referenceState(st), alive(referenceState(st)).view).wash })
  };
  const t1 = patched(st, { tick: (st.tick || 0) + 1 });
  const ring1 = aliveRing(M.view(t1, { led: 'alive' }).ring);
  if (JSON.stringify(ring1) !== JSON.stringify(entry.alive.ring)) entry.tick1 = ring1;
  if (alt) {
    const sa = patched(st, alt.patch);
    const b = alive(sa);
    entry.altAlive = b.out;
    entry.altFlags = flags(sa, b.view);
    const ringA1 = aliveRing(M.view(patched(sa, { tick: (sa.tick || 0) + 1 }), { led: 'alive' }).ring);
    if (JSON.stringify(ringA1) !== JSON.stringify(entry.altAlive.ring)) entry.altTick1 = ringA1;
  }
  return entry;
}

const cases = [];
const ids = new Set();
function add(group, id, name, note, st, opts) {
  if (ids.has(id)) throw new Error('duplicate case id ' + id);
  ids.add(id);
  opts = opts || {};
  st = plain(st);
  let alt = opts.alt || null;
  if (!alt && st.mode === 'windows' && st.win.order.length > 20) {
    // V4-9.5 expected value: the 20-entry host window (first = clamp(idx-9, 0, n-20)), drawn by
    // the model itself with every entry outside the window marked closed (as knob_golden.cjs).
    const n = st.win.order.length, first = Math.max(0, Math.min(st.win.idx - 9, n - 20));
    const closed = st.win.closed.slice();
    for (let i = 0; i < n; i++) if ((i < first || i >= first + 20) && !closed.includes(i)) closed.push(i);
    alt = { tag: 'V4-9.5', first, patch: { win: { closed } } };
  }
  const connected = st.conn === 'ok';
  const hasFlash = !!st.flash;
  const extOk = connected && st.mode === 'home' && !st.ext && st.vol === st.volConf;
  const sets = [['base', {}], ['asleep', { asleep: true }]];
  if (opts.light) {
    if (opts.ext && extOk) sets.push(['ext', { ext: true }]);
  } else {
    if (connected && !hasFlash) {
      sets.push(['ok', { flash: { kind: 'ok', id: 1 }, flashId: 1 }], ['err', { flash: { kind: 'err', id: 1 }, flashId: 1 }],
        ['err-asleep', { asleep: true, flash: { kind: 'err', id: 1 }, flashId: 1 }]);
    }
    if (extOk) sets.push(['ext', { ext: true }], ['ext-asleep', { ext: true, asleep: true }]);
  }
  const entry = { id, group, name, note: note || '', st, variants: sets.map(([key, patch]) => variant(key, st, patch, alt)) };
  if (alt) entry.alt = alt;
  cases.push(entry);
}
const slug = s => s.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
const R_ = (page, idx, status, extra) => Object.assign({ mode: 'recent', recent: { page, idx, stack: page ? Array(page).fill(10) : [], status: status || 'ready' } }, extra || {});
const flashSt = (patch, kind, id) => Object.assign({}, patch, { flash: { kind, id }, flashId: id });

// 1. Every scenario and stress case, as shipped.
M.scenarios().forEach(x => add('scenario', x.id, x.name, '', x.st, x.st.conn === 'reconnecting' ? { alt: { tag: 'D5', patch: { conn: 'missing' } } } : null));
M.stress().forEach(x => add('stress', 'stress-' + slug(x.name), x.name, x.note, x.st));

// 2. The knob_golden.cjs states (same patches, same ids).
[
  ['led-vol-54', 'Volume · 54 %', { vol: 54, volConf: 54 }],
  ['led-vol-86', 'Volume · 86 %', { vol: 86, volConf: 86, volVis: true }],
  ['led-vol-96', 'Volume · 96 %', { vol: 96, volConf: 96, volVis: true }],
  ['led-recent', 'Recently Added', { mode: 'recent', recent: { idx: 2 } }],
  ['led-win-claude', 'Windows · Claude', { mode: 'windows', win: { idx: 1 } }],
  ['led-win-chrome', 'Windows · Chrome', { mode: 'windows', win: { idx: 2 } }]
].forEach(([id, name, patch]) => add('ledRows', id, name, '', M.mk(patch)));
for (let v = 0; v <= 100; v++) {
  add('sweep', `vol-${v}-eq`, `Volume ${v} %`, 'confirmed', M.mk({ vol: v, volConf: v, volVis: true }), { light: true, ext: true });
  if (v - 9 >= 0) add('sweep', `vol-${v}-up`, `Volume ${v} % (confirmed ${v - 9})`, 'pending increase', M.mk({ vol: v, volConf: v - 9, volVis: true }), { light: true });
  if (v + 9 <= 100) add('sweep', `vol-${v}-down`, `Volume ${v} % (confirmed ${v + 9})`, 'pending decrease', M.mk({ vol: v, volConf: v + 9, volVis: true }), { light: true });
}
[0, 1, 38, 79, 89, 100].forEach(v => add('volume', `vol-${v}-ext`, `Volume ${v} % · changed elsewhere`, 'external endpoint', M.mk({ vol: v, volConf: v, ext: true, volVis: true })));
add('volume', 'vol-1-down-50', 'Volume 1 % (confirmed 100)', 'pending decrease across the whole arc', M.mk({ vol: 1, volConf: 100, volVis: true }));
add('volume', 'home-off-61', 'Volume · Sonos offline at 61 %', 'offline endpoint uses the confirmed value only', M.mk({ sonos: 'off', vol: 61, volConf: 61 }));
add('volume', 'home-off-0', 'Volume · Sonos offline at 0 %', '', M.mk({ sonos: 'off', vol: 0, volConf: 0 }));
add('volume', 'home-none-vol', 'Volume · nothing playing, turning', '', M.mk({ nothing: true, vol: 57, volConf: 57, volVis: true }));
add('volume', 'home-pidle-vol', 'Volume · paused idle, turning', '', M.mk({ playing: false, playReq: false, pIdle: true, vol: 41, volConf: 41, volVis: true }));
add('pending', 'pend-ra-p2', 'Recently Added P2 · playback pending', '', M.mk(R_(1, 5, 'pending')));
add('pending', 'pend-tr-next', 'Tracks · Next skip pending', '', M.mk({ mode: 'tracks', tracks: { pos: 1, status: 'pending' } }));
add('pending', 'pend-tr-prev', 'Tracks · Previous skip pending', '', M.mk({ mode: 'tracks', tracks: { pos: -1, status: 'pending' } }));
add('pending', 'pend-wi-claude', 'Windows · switch to Claude pending', 'D13: pulses in the app colour', M.mk({ mode: 'windows', win: { idx: 1, status: 'pending' } }));
add('pending', 'pend-wi-chrome', 'Windows · switch to Chrome pending', 'D13: pulses in the app colour', M.mk({ mode: 'windows', win: { idx: 2, status: 'pending' } }));
add('pending', 'pend-wi-codex', 'Windows · switch to Codex pending', 'untinted app: warm either way', M.mk({ mode: 'windows', win: { idx: 0, status: 'pending' } }));
add('flash', 'flash-ok-tracks', 'Tracks · skipped, green flash', 'tr-done with its flash', M.mk(flashSt({ mode: 'tracks', qi: 2, tracks: { pos: 0, status: 'done' } }, 'ok', 1)));
add('flash', 'flash-err-ra-part', 'Recently Added · partial, red flash', 'ra-part with its flash', M.mk(flashSt(R_(0, 2, 'partial'), 'err', 2)));
add('flash', 'flash-err-wi-fail', 'Windows · failed, red flash', 'wi-fail with its flash', M.mk(flashSt({ mode: 'windows', win: { idx: 2, status: 'failed' } }, 'err', 3)));
add('flash', 'flash-ok-home', 'Volume · played, green flash', 'Recent play completion lands on Home', M.mk(flashSt({ np: { t: 'Night Channel', a: 'Velvet Circuit' } }, 'ok', 4)));
add('flash', 'flash-ok-home-61', 'Volume 61 % · green flash', 'flash overwrites the odd-v shoulder', M.mk(flashSt({ vol: 61, volConf: 61 }, 'ok', 5)));
add('flash', 'flash-ok-home-0', 'Volume 0 % · green flash', 'cursor-1 is segment 34', M.mk(flashSt({ vol: 0, volConf: 0 }, 'ok', 6)));
add('flash', 'flash-err-home-96', 'Volume 96 % · red flash', 'embers on the red flash too', M.mk(flashSt({ vol: 96, volConf: 96 }, 'err', 7)));
add('flash', 'flash-err-ra-load', 'Recently Added · loading, red flash', 'loading cursor is segment 0', M.mk(flashSt(R_(0, 0, 'loading'), 'err', 8)));
add('flash', 'flash-ok-wi-first', 'Windows · first entry, green flash', '', M.mk(flashSt({ mode: 'windows', win: { idx: 0 } }, 'ok', 9)));
add('flash', 'flash-ok-ra-more', 'Recently Added · More, green flash', '', M.mk(flashSt(R_(0, 10), 'ok', 10)));
add('lists', 'ra-load-p2', 'Recently Added · loading page 2', 'requested page', M.mk(R_(1, 0, 'loading')));
add('lists', 'ra-load-p3', 'Recently Added · loading page 3', 'requested page', M.mk(R_(2, 0, 'loading')));
add('lists', 'ra-more-p2', 'Recently Added P2 · More', '', M.mk(R_(1, 10)));
add('lists', 'ra-na-p2', 'Recently Added P2 · unavailable', '', M.mk(R_(1, 4)));
add('lists', 'ra-item-p2', 'Recently Added P2 · Tidal Glass', 'cover without an accent: warm', M.mk(R_(1, 2)));
add('lists', 'ra-item-p2-glass weather', 'Recently Added P2 · Glass Weather', '', M.mk(R_(1, 5)));
add('lists', 'ra-last-p3', 'Recently Added P3 · last item (no More)', '', M.mk(R_(2, 2)));
add('lists', 'ra-night-drive', 'Recently Added · Night Channel', '', M.mk(R_(0, 2)));
add('lists', 'ra-hounds', 'Recently Added · Paper Lanterns', '', M.mk(R_(0, 9)));
add('lists', 'ra-sonos-off', 'Recently Added · Sonos down', 'landmarks kept, Play dim', M.mk(R_(0, 2, 'ready', { sonos: 'off' })));
add('lists', 'wi-closed-claude', 'Windows · Claude closed', 'closed cursor keeps the app colour', M.mk({ mode: 'windows', win: { idx: 1, closed: [1] } }));
add('lists', 'wi-closed-multi', 'Windows · two closed slots', '', M.mk({ mode: 'windows', win: { idx: 3, closed: [2, 4] } }));
add('lists', 'wi-slack', 'Windows · Slack', '', M.mk({ mode: 'windows', win: { idx: 6 } }));
add('lists', 'wi-discord', 'Windows · Discord (minimized)', 'COLOR_FALLBACK accent', M.mk({ mode: 'windows', win: { idx: 7 } }));
add('lists', 'wi-last', 'Windows · last entry', '', M.mk({ mode: 'windows', win: { idx: 8 } }));
add('tracks', 'tr-prev', 'Tracks · Previous selected', '', M.mk({ mode: 'tracks', tracks: { pos: -1 } }));
add('tracks', 'tr-noprev-neutral', 'Tracks · neutral, no Previous', '', M.mk({ mode: 'tracks', tracks: { pos: 0 }, opt: { noPrev: true } }));
add('tracks', 'tr-noprev-next', 'Tracks · Next, no Previous', '', M.mk({ mode: 'tracks', tracks: { pos: 1 }, opt: { noPrev: true } }));
const winsN = (n, idx, closed) => M.mk({ mode: 'windows', win: { order: Array.from({ length: n }, (_, i) => i % 9), idx, closed: closed || [] } });
[[20, 0], [20, 19], [21, 0], [21, 10], [21, 20], [25, 12], [45, 5], [45, 30], [45, 44], [80, 40], [80, 79]].forEach(([n, i]) =>
  add('windows', `wi-n${n}-i${i}`, `Windows · ${n} windows, entry ${i + 1}`, n > 20 ? 'V4-9.5: 20-entry window' : 'design-exact (count <= 20)', winsN(n, i)));
add('windows', 'wi-n45-i30-closed', 'Windows · 45 windows, closed inside and outside the window', 'V4-9.5', winsN(45, 30, [3, 25, 31]));
add('disconnected', 'disc-reconnecting', 'Knob · reconnecting', 'D5: no reconnecting pulse', M.mk({ conn: 'reconnecting' }), { alt: { tag: 'D5', patch: { conn: 'missing' } } });

// 3. alive states.
add('alive', 'home-pausing', 'Volume · pause requested', 'playReq false, playing true: Play dim, pending', M.mk({ playReq: false }));
add('alive', 'home-starting', 'Volume · play requested', 'playReq true, playing false: Pause dim, pending', M.mk({ playing: false }));
add('alive', 'home-paused-96', 'Volume 96 % · paused', 'paused Play and embers', M.mk({ playing: false, playReq: false, vol: 96, volConf: 96 }));
add('alive', 'home-off-pend', 'Volume · Sonos offline with a stale request', 'D15: the notice draws the confirmed endpoint only; the stale request is not pending',
  M.mk({ sonos: 'off', vol: 61, volConf: 54 }), { alt: { tag: 'D15', patch: { vol: 54 } } });

// ---------------------------------------------------------------- constants
const pages = [0, 1, 2].map(p => M.entries(M.mk({ recent: { page: p } })).map(e => plain(e)));
const tintKeys = new Set(Object.keys(reference.colors));
pages.forEach(es => es.forEach(e => { if (!e.more) tintKeys.add('al:' + e.t); }));
M.WINS.forEach(w => tintKeys.add('app:' + w.app));
const tints = {};
[...tintKeys].sort().forEach(k => { tints[k] = M.__tint(k); });

// ------------------------------------------ sat(): finishAlive's own code over its whole domain
// sat() maps each channel x of a colour with minimum mn and maximum mx on its own, so the
// channel table over every 0 <= mn <= x <= mx <= 255 with mx - mn >= 30 is its whole domain
// (spread < 30 is WARM). The source is lifted verbatim (anchor exactly once) and run as shipped
// in a fresh context whose WARM is finishAlive's. The fixture carries the table's sha256, the
// exact .5 roundings (every 100th as samples) and the spread 29 / 30 threshold.
const SAT_ANCHOR = 'const sat = c => {';
const satStart = once(modelSource, SAT_ANCHOR, 'finishAlive sat()') + 'const sat = '.length;
const satSource = modelSource.slice(satStart, modelSource.indexOf('};', satStart) + 1);
const designSat = vm.runInNewContext('(' + satSource + ')', { WARM: designPalette.WARM });
const satTable = [];
const satHalves = [];
for (let mn = 0; mn <= 255; mn++) {
  for (let mx = mn + 30; mx <= 255; mx++) {
    for (let x = mn; x <= mx; x++) {
      const text = designSat(`${mn},${x},${mx}`);
      if (text === designPalette.WARM) throw new Error(`sat(${mn},${x},${mx}) fell back to WARM`);
      const rgbOut = text.split(',').map(Number);
      satTable.push(rgbOut[1]);
      const q = Math.max(0, x - mn * 0.75) / (mx - mn * 0.75) * 255;   // only picks the .5 samples
      if (q - Math.floor(q) === 0.5) satHalves.push([mn, x, mx, rgbOut]);
    }
  }
}
const satThreshold = { spread29Warm: 0, spread30Warm: 0, colours: 0 };
for (let mn = 0; mn + 30 <= 255; mn++) {
  satThreshold.colours++;
  if (designSat(`${mn},${mn},${mn + 29}`) === designPalette.WARM) satThreshold.spread29Warm++;
  if (designSat(`${mn},${mn},${mn + 30}`) === designPalette.WARM) satThreshold.spread30Warm++;
}
const satReference = {
  source: satSource,
  domain: '0 <= mn <= x <= mx <= 255, mx - mn >= 30; byte = channel x of sat("mn,x,mx"), loops mn, mx, x ascending',
  triples: satTable.length,
  sha256: require('crypto').createHash('sha256').update(Buffer.from(satTable)).digest('hex'),
  exactHalves: satHalves.length,
  halfSamples: satHalves.filter((_, i) => i % 100 === 0),
  threshold: satThreshold
};

const out = {
  about: 'Target golden for the alive LED engine (ALIVE.md 11.2), generated from the design\'s knob-model.js view(st, {led:"alive"}) (finishAlive) by tests/js/alive_golden.cjs, with the animator flags evaluated by the design\'s own draw()/detect() expressions ("flagExpressions"). Ring entries are ["r,g,b", l, a] or null. Compare with tests/test_alive_golden.py (frames via tests/tools/knob_adapter.py).',
  generator: 'tests/js/alive_golden.cjs',
  model: 'design-reference/design_handoff_led_choreography/knob-model.js',
  design: 'design-reference/design_handoff_led_choreography/Ring Choreography v2.dc.html (logic block)',
  colorsSource: 'tests/fixtures/dominant_reference.json',
  designConstants: { palette: designPalette, AW, AS, viewPalette, MODEL_WARM },
  flagExpressions: EXPR,
  constants: { tints, pages, WINS: plain(M.WINS) },
  sat: satReference,
  cases
};
const NL = String.fromCharCode(10);
const block = list => '[' + NL + list.map(x => JSON.stringify(x)).join(',' + NL) + NL + ']';
const text = '{' + NL + Object.keys(out).map(k => JSON.stringify(k) + ': ' +
  (Array.isArray(out[k]) ? block(out[k]) : JSON.stringify(out[k]))).join(',' + NL) + NL + '}' + NL;
if (outPath) fs.writeFileSync(outPath, text, 'utf8'); else process.stdout.write(text);
