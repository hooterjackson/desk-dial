'use strict';
/*
 * BS target golden for the "Warm · alive" LED engine (firmware/ALIVE.md revision 2, 11.3):
 * the master's "Browse and Snap" renderVals() (r2.1 BS:1118-1333; R22 BS:1124-1339) ring and button
 * targets. [r2.2] The golden reads the r2.2 prototype: its renderVals() gives the liked heart
 * {c: PINK, a: 0.3, ink: '#A3244A'} (R22 BS:1268, :1295, :1299; ALIVE.md 11.3 [r2.2], M32), which is
 * the value the engine must match; r2.1's PINK 1.0 is retired. The draw()/play() code is the same
 * in both (the r2.1 -> r2.2 diff of renderVals touches only the Up next heart, the footer ink/alpha and
 * the Recently Added meta text), so every other state is unchanged.
 *
 * Runs the logic block of design-reference/design_handoff_nano_d_master_r2.2/prototypes/"Browse and
 * Snap.dc.html" UNMODIFIED in a node `vm` context (the stubs of tests/js/alive_oracle_bs.cjs: DCLogic,
 * React.createRef, window.devicePixelRatio, a fixed Date, throwing timers/document). For every case a
 * fresh component gets a state patch over fresh() and renderVals() is called; the fixture records
 * the design's own targets: this._ring ([[r,g,b], a] per segment, null when unlit or a = 0),
 * this._btns ({c, a}), this._cursor and this._working, plus the knob footer (each button's icon
 * name from BS's I table, its tone and colour).
 *
 * The mapping of each BS state to the v5 frame the v7 host sends (ALIVE.md 11.3; the host rules of
 * PRESENTATION_V5 4.2-4.6, 5.1 and VOC 2.4) is done HERE, next to the state it reads (knob_adapter.py
 * belongs to another package): the layout per mode, the ring (the level value; the selection window
 * first = clamp(index - 10, 0, count - 20) with the raw colours of the transmitted entries read from
 * BS's own ring slots, BS's warm marker [255,190,105] sent as 0 [M26]; Up next with now and, in
 * the Sonos-shuffle regime, card:true at entry count - 1 with colour 0 [M14]; the Seek lap with
 * index = pos and count = D; K1's loading form, style off + activity loading, for a loading list
 * [M31]), activity (pending for Starting..., Queueing..., Jumping...), playing, and the buttons
 * (BS icon -> v5 token, tone -> enabled / lit, the snap colour raw).
 *
 * Usage: node alive_golden_bs.cjs <prototypes dir> [out.json]
 * Output is deterministic; a coverage self-check (ALIVE.md 11.3's BS case list) runs first.
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const [designDir, outPath] = process.argv.slice(2);
if (!designDir) {
  process.stderr.write('usage: node alive_golden_bs.cjs <prototypes dir> [out.json]\n');
  process.exit(2);
}
const html = fs.readFileSync(path.join(designDir, 'Browse and Snap.dc.html'), 'utf8');
const opens = [...html.matchAll(/<script type="text\/x-dc"[^>]*>/g)];
if (opens.length !== 1) throw new Error(`alive_golden_bs: expected one x-dc block, found ${opens.length}`);
const start = opens[0].index + opens[0][0].length;
const logic = html.slice(start, html.indexOf('</script>', start));
const inert = name => () => { throw new Error(`alive_golden_bs: ${name} is not available`); };
class FixedDate { getHours() { return 12; } getMinutes() { return 0; } static now() { return 0; } }
const context = vm.createContext({
  window: { devicePixelRatio: 1 },
  document: new Proxy({}, { get: (t, k) => { throw new Error('alive_golden_bs: document.' + String(k)); } }),
  React: { createRef: () => ({ current: null }) },
  requestAnimationFrame: () => 0, cancelAnimationFrame: () => {},
  setTimeout: inert('setTimeout'), clearTimeout: inert('clearTimeout'), setInterval: inert('setInterval'),
  clearInterval: inert('clearInterval'), performance: { now: inert('performance.now') }, Date: FixedDate
});
vm.runInContext('class DCLogic { constructor(p) { this.props = p; } setState(p) { this.state = Object.assign({}, this.state, p); } forceUpdate() {} }', context);
vm.runInContext(logic, context, { filename: 'Browse and Snap.dc.html' });
const D = vm.runInContext('({ Component, I, HALF, ALB, TR, PL, PL_REAL, WARM, GREEN, AMBER, RED, PINK, isW, queueFor, durOf })', context);

const ICON = new Map(Object.entries(D.I).map(([name, d]) => [d, name]));
// BS icon names -> v5 tokens (PRESENTATION_V5 9.1; VOC 2.4 per mode). Slot 3's skip icon is the
// "next" / "prev" token so that go follows the tone; rect is the snap side of its slot.
function token(name, slot, mode) {
  switch (name) {
    case 'back': case 'play': case 'pause': case 'expand': case 'clock': case 'heart': case 'shuffle': case 'seek':
    case 'prev': case 'win':
      return name;
    case 'note': return 'list';
    case 'list': return 'tracks';
    case 'tracks': return 'next';
    case 'next': return 'playnext';
    case 'queue': return 'playlists';
    case 'check': return 'switch';
    case 'rect': return slot === 1 ? 'snapleft' : 'snapright';
    default: throw new Error(`alive_golden_bs: no v5 token for BS icon ${name} (${mode})`);
  }
}
const RAW = c => (D.isW(c) ? 0 : (c[0] << 16) | (c[1] << 8) | c[2]);   // [M26] the warm marker is 0
// renderVals() returns the footer as {d, fill, col}: col is the tone's LCD ink (BS's `tone` table) or, for
// a button with its own colour (an assigned snap side: tone on), 'rgb(r,g,b)'. [r2.2] The liked heart
// carries its own ink (R22 BS:1268, :1295 `col: f.ink || ...`): '#A3244A' on the filled heart is tone
// `liked` (VOC 1.2 CCButtonTone 7), which the v7 host sends as heart + lit:"on" (VOC 2.3 row 4).
const INK_TONE = { '#E6E6E6': 'nav', '#6ED996': 'go', '#5A5A5A': 'dim', '#FFFFFF': 'on', '#7A7A7A': 'off', transparent: 'none' };
const LIKED_INK = '#A3244A';
function footOf(f) {
  if (f.col.startsWith('rgb(')) return { d: f.d, t: 'on', c: f.col.slice(4, -1).split(',').map(Number) };
  if (f.col === LIKED_INK) {
    if (f.d !== D.I.heart || f.fill !== D.I.heart) throw new Error('alive_golden_bs: the liked ink on a non-heart footer');
    return { d: f.d, t: 'liked', c: null };
  }
  if (!(f.col in INK_TONE)) throw new Error('alive_golden_bs: unknown footer ink ' + f.col);
  return { d: f.d, t: INK_TONE[f.col], c: null };
}

// ---------------------------------------------------------------- cases
const probe = new D.Component({});
const FRESH = probe.fresh();
const WINS = probe.W;
function S(patch) {
  const p = patch || {};
  return Object.assign({}, FRESH, p, { sim: Object.assign({}, FRESH.sim, p.sim || {}) });
}
const CASES = [];
const C = (id, group, state, extra) => CASES.push(Object.assign({ id, group, state: S(state) }, extra || {}));
for (const v of [0, 1, 2, 54, 55, 79, 80, 81, 85, 89, 90, 95, 98, 99, 100]) C(`home-${v}`, 'home', { mode: 'home', vol: v });
C('home-paused', 'home', { mode: 'home', vol: 54, playing: false });
C('home-paused-95', 'home', { mode: 'home', vol: 95, playing: false });
C('home-starting', 'home', { mode: 'home', vol: 54, playing: false, busy: { kind: 'start' } });
for (const i of [0, 9, 10, 12, 23]) C(`recent-${i}`, 'recent', { mode: 'recent', rIdx: i });
C('recent-queueing', 'recent', { mode: 'recent', rIdx: 6, busy: { kind: 'pn', k: 3, n: 10 } });
for (const i of [0, 10, 23]) C(`explore-recent-${i}`, 'explore', { mode: 'explore', src: 'recent', xOpen: true, xIdx: { recent: i, playlists: 0 } });
C('explore-favs-many-3', 'explore', { mode: 'explore', src: 'playlists', xOpen: true, xIdx: { recent: 0, playlists: 3 }, sim: { favs: 'many' } });
C('explore-favs-real-1', 'explore', { mode: 'explore', src: 'playlists', xOpen: true, xIdx: { recent: 0, playlists: 1 } });
C('explore-favs-empty', 'explore', { mode: 'explore', src: 'playlists', xOpen: true, sim: { favs: 'empty' } });
C('explore-loading-list', 'explore', { mode: 'explore', src: 'recent', xOpen: true, sim: { art: 'list' } });
for (const t of [-1, 0, 1]) C(`tracks-${t}`, 'tracks', { mode: 'tracks', tPos: t });
for (const qNow of [4, 7]) {
  const queue = D.queueFor({ kind: 'al', i: 4 }), dur = D.durOf(queue[qNow]);
  for (const pos of [0, 74, dur - 3]) C(`seek-q${qNow}-${pos}`, 'seek', { mode: 'tracks', seek: true, qNow, qSel: qNow, pos });
}
C('seek-jumping', 'seek', { mode: 'tracks', seek: true, pos: 74, seekState: 'jump' });
for (const q of [0, 4, 11]) C(`upnext-fresh-${q}`, 'upnext', { mode: 'queue', qOpen: true, qSel: q });
C('upnext-liked', 'upnext', { mode: 'queue', qOpen: true, qSel: 6, liked: { ['4:' + D.TR[4][6]]: true } });
{
  const base = D.queueFor({ kind: 'al', i: 4 });
  const add = D.TR[2].map((t, k) => ({ t, a: D.ALB[2].a, al: 2, n: k + 1 })).concat(D.TR[5].map((t, k) => ({ t, a: D.ALB[5].a, al: 5, n: k + 1 })));
  const queue = base.concat(add), idx = add.map((_, k) => base.length + k);
  const order = [0, 1, 2, 3, 4].concat(idx, [5, 6, 7, 8, 9, 10, 11]);
  for (const q of [1, 12, 30, 33]) C(`upnext-playnext-${q}`, 'upnext', { mode: 'queue', qOpen: true, queue, qOrder: order, pnIdx: idx, qNow: 4, qSel: q });
}
C('upnext-shuffled', 'upnext', { mode: 'queue', qOpen: true, shuffle: true, qOrder: [0, 1, 2, 3, 4, 9, 6, 11, 5, 8, 10, 7], qSel: 7 });
C('upnext-longshuffle-card', 'upnext', { mode: 'queue', qOpen: true, qSel: 5, sim: { upnext: 'longshuffle' } });
C('upnext-longshuffle-row', 'upnext', { mode: 'queue', qOpen: true, qSel: 2, sim: { upnext: 'longshuffle' } });
C('upnext-loading', 'upnext', { mode: 'queue', qOpen: true, qSel: 4, sim: { upnext: 'loading' } });
C('windows-none', 'windows', { mode: 'windows', wOpen: true, sel: 1 });
C('windows-left', 'windows', { mode: 'windows', wOpen: true, sel: 2, left: 1 });
C('windows-both', 'windows', { mode: 'windows', wOpen: true, sel: 3, left: 1, right: 3 });
C('windows-left-warm-app', 'windows', { mode: 'windows', wOpen: true, sel: 2, left: 3 });
C('pc-off', 'offline', { sim: { pc: 'off' } });

// ---------------------------------------------------------------- the v7 host's frame for a BS state
function selection(inst, ringOut, count, index, rowsFromRing, extra) {
  // The raw colour of each transmitted entry is BS's own (read at its BS slot); window = the host's.
  const first = count <= 20 ? 0 : Math.max(0, Math.min(index - 10, count - 20));
  const width = Math.min(20, count - first);
  const ring = { style: 'selection', value: 0, index, count };
  if (count > 20) ring.first = first;
  ring.colors = [];
  for (let j = first; j < first + width; j++) ring.colors.push(rowsFromRing(j));
  return Object.assign(ring, extra || {});
}

function bsSlotColour(inst, j, c0) {
  const r = inst._ring[(((j - c0) * 3) % 60 + 60) % 60];
  if (!r) throw new Error('no BS colour at entry ' + j);
  return RAW(r.c);
}

function frameOf(inst) {
  const s = inst.state, mode = s.mode;
  if (s.sim.pc === 'off') return null;
  const vals = inst._vals;
  const buttons = vals.foot.map(footOf).map((f, j) => {
    if (f.t === 'none') return { label: '', enabled: false, icon: '' };
    const name = ICON.get(f.d);
    if (!name) throw new Error('unknown BS icon path in ' + mode);
    const b = { label: 'b' + j, enabled: f.t !== 'dim', icon: token(name, j, mode) };
    if (f.t === 'on' || f.t === 'liked') b.lit = 'on';                            // [r2.2] liked = heart + lit on
    if (f.t === 'off') b.lit = 'off';
    if (f.t === 'on' && f.c && name === 'rect' && RAW(f.c)) b.color = RAW(f.c);
    return b;
  });
  const frame = { id: 1, target: 'Hall', value: '', detail: '', status: '', ledStyle: 'color', buttons, activity: 'idle' };
  if (mode === 'home') {
    Object.assign(frame, { mode: 'HOME', layout: 'nowPlaying', value: `${s.vol}%`, confirmedVolume: s.vol,
      ring: { style: 'level', value: s.vol, index: 0, count: 101 } });
    if (s.busy && s.busy.kind === 'start') frame.activity = 'pending';           // Starting... (no playing, M16)
    else frame.playing = !!s.playing;
    return frame;
  }
  if (mode === 'tracks' && s.seek) {
    const D0 = D.durOf(inst.curTrack());
    return Object.assign(frame, { mode: 'TRACKS', layout: 'seek', activity: s.seekState === 'jump' ? 'pending' : 'idle',
      ring: { style: 'lap', value: 0, index: s.pos, count: D0 } });
  }
  if (mode === 'tracks') {
    return Object.assign(frame, { mode: 'TRACKS', layout: 'tracks', ring: { style: 'transport', value: 0, index: s.tPos + 1, count: 3 } });
  }
  if (mode === 'queue') {
    Object.assign(frame, { mode: 'RECENTLY ADDED', layout: 'upnext' });
    if (s.sim.upnext === 'loading') return Object.assign(frame, { activity: 'loading', ring: { style: 'off', value: 0, index: 0, count: 0 } });
    const long = s.sim.upnext === 'longshuffle';
    const rows = long ? s.qNow + 1 : inst.qLen(), qSel = Math.min(s.qSel, inst.qLen() - 1);
    const win = Math.min(20, rows), w0 = Math.max(0, Math.min(rows - win, qSel - 10)), c0 = w0 + Math.floor((win - 1) / 2);
    const count = long ? s.qNow + 2 : rows;
    return Object.assign(frame, { ring: selection(inst, null, count, qSel,
      j => (long && j === count - 1 ? 0 : bsSlotColour(inst, j, c0)), long ? { now: s.qNow, card: true } : { now: s.qNow }) });
  }
  if (mode === 'explore') {
    const L = inst.list(s.src);
    Object.assign(frame, { mode: 'RECENTLY ADDED', layout: 'explorer', page: s.src === 'playlists' ? 1 : 0 });
    if (s.sim.art === 'list') return Object.assign(frame, { activity: 'loading', ring: { style: 'off', value: 0, index: 0, count: 0 } });
    if (!L.length) return Object.assign(frame, { ring: { style: 'off', value: 0, index: 0, count: 0 } });
    const xi = Math.max(0, Math.min(s.xIdx[s.src], L.length - 1));
    const win = Math.min(20, L.length), w0 = Math.max(0, Math.min(L.length - win, xi - 10)), c0 = w0 + Math.floor((win - 1) / 2);
    return Object.assign(frame, { ring: selection(inst, null, L.length, xi, j => bsSlotColour(inst, j, c0)) });
  }
  const items = mode === 'windows' ? WINS : D.ALB, cur = mode === 'windows' ? s.sel : s.rIdx;
  const win = Math.min(20, items.length), w0 = Math.max(0, Math.min(items.length - win, cur - 10)), c0 = w0 + Math.floor((win - 1) / 2);
  Object.assign(frame, mode === 'windows' ? { mode: 'WINDOWS', layout: 'windows' } : { mode: 'RECENTLY ADDED', layout: 'recent' });
  if (s.busy) frame.activity = 'pending';                                          // Queueing... (Play next)
  return Object.assign(frame, { ring: selection(inst, null, items.length, cur, j => bsSlotColour(inst, j, c0)) });
}

const cellOut = r => (r && r.a ? [r.c.slice(), r.a] : null);
const results = CASES.map(def => {
  const inst = new D.Component({});
  inst.timers = [];
  inst.state = def.state;
  inst._vals = inst.renderVals();
  const frame = frameOf(inst);
  const foot = inst._vals.foot.map(footOf).map(f => ({ icon: f.t === 'none' ? '' : ICON.get(f.d), tone: f.t, c: f.c }));
  return {
    id: def.id, group: def.group, mode: def.state.sim.pc === 'off' ? 'offline' : def.state.mode,
    playing: !!def.state.playing, frame,
    ring: inst._ring.map(cellOut), buttons: inst._btns.map(b => [b.c.slice(), b.a]), cursor: inst._cursor,
    working: !!inst._working, foot
  };
});

// Coverage (ALIVE.md 11.3 BS cases).
const ids = new Set(results.map(r => r.id));
const need = ['home-0', 'home-1', 'home-2', 'home-54', 'home-55', 'home-79', 'home-80', 'home-81', 'home-85', 'home-89', 'home-90',
  'home-95', 'home-98', 'home-99', 'home-100', 'recent-0', 'recent-9', 'recent-10', 'recent-12', 'recent-23', 'explore-recent-10',
  'explore-favs-real-1', 'explore-favs-empty', 'explore-loading-list', 'tracks--1', 'tracks-0', 'tracks-1', 'upnext-fresh-0',
  'upnext-fresh-4', 'upnext-fresh-11', 'upnext-playnext-1', 'upnext-playnext-33', 'upnext-shuffled', 'upnext-longshuffle-card',
  'upnext-loading', 'windows-none', 'windows-left', 'windows-both', 'pc-off', 'home-paused', 'home-starting', 'upnext-liked'];
for (const id of need) if (!ids.has(id)) throw new Error('alive_golden_bs: coverage misses ' + id);
if (results.filter(r => r.group === 'seek').length < 6) throw new Error('alive_golden_bs: two durations x three positions');

const out = {
  version: 1,
  about: 'BS target golden (ALIVE.md revision 2, 11.3 [r2.2]): the r2.2 Browse and Snap renderVals() targets (_ring [[r,g,b], a], _btns, ' +
    '_cursor, _working) per state, with the v7 host frame of that state (mapped here). Compared by tests/test_alive_golden_bs.py ' +
    'with alive_targets after the BS remap: [255,190,105] -> WARM, [0,255,98] -> GREEN, [255,131,56] -> AMBER, [255,0,0] -> RED, ' +
    '[255,40,90] on a button -> PINK, any other colour x -> sat(x).',
  generator: 'tests/js/alive_golden_bs.cjs',
  design: 'design-reference/design_handoff_nano_d_master_r2.2/prototypes/Browse and Snap.dc.html (renderVals, logic block unmodified)',
  constants: { WARM: D.WARM, GREEN: D.GREEN, AMBER: D.AMBER, RED: D.RED, PINK: D.PINK },
  cases: results
};
const text = JSON.stringify(out, null, 0).replace(/\{"id":/g, '\n{"id":') + '\n';
process.stderr.write(`alive_golden_bs: ${results.length} cases\n`);
if (outPath) fs.writeFileSync(outPath, text, 'utf8'); else process.stdout.write(text);
