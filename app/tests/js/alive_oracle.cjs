'use strict';
/*
 * Design oracle for the "Warm · alive" LED animator (firmware/ALIVE.md section 11.1).
 *
 * Runs the logic block (<script type="text/x-dc">) of the design's
 * "Ring Choreography v2.dc.html" in a node `vm` context with inert stubs:
 *   - DCLogic base class (stores props; setState shallow-merges into this.state),
 *   - React.createRef() -> {current: null}, window = {}, document = {},
 *   - requestAnimationFrame / cancelAnimationFrame no-ops,
 *   - setTimeout / setInterval / performance.now throw (the oracle never mounts
 *     the component and never calls dispatch()/detect()),
 *   - a fake canvas whose getContext('2d') is a no-op 2d context (every method is
 *     a harmless no-op, every property accepts writes).
 * The block is evaluated UNMODIFIED except for ONE mechanical capture patch
 * (CAPTURE_PATCH below): a call that records the tone-mapped `e` is inserted
 * right after `e` is computed in the two compose loops (ring loop, file line
 * 377, right after line 376; button loop, file line 387, right after line 386).
 * Each anchor is a literal string that must occur exactly once or this script
 * throws. [user 2026-09-26] Besides it, RULING_PATCH applies the user's LED ruling
 * (ALIVE.md 12.8) to draw(): HOT == WARM, a steady rest floored at todB 0.80 and no
 * song hand at rest. Nothing else of the design is changed.
 *
 * knob-model.js (same design dir) is loaded unmodified in a second vm context,
 * with NanoModel.COLORS pre-populated from tests/fixtures/dominant_reference.json
 * exactly as tests/js/knob_golden.cjs does. It is used ONLY to build realistic
 * views: every scripted view is NanoModel.view(NanoModel.mk(patch), {led:'alive'})
 * (finishAlive targets). The component itself never sees NanoModel: its this.M is
 * a stub whose isPending() returns the step's `pending` flag, this.s is
 * {vol, playing, conn: offline ? 'missing' : 'ok'} and this.v is rebuilt from the
 * fixture view in the design's string colour format ({c:'r,g,b', l:1, a} per lit
 * segment/button, null when unlit; warm segments are MODEL_WARM '255,164,84').
 * hour() returns case.hour (state.hour), props = {breathe:true, glow:1, speed:1}.
 *
 * Drive, per case: a fresh component instance; per step: apply the view (when
 * present), then for each effect set this.vt = effect.t0 and call
 * this.play(type, params, true) with the params the design's detect()/demo()
 * pass (fill/drain n comes from this.s.vol, boot home from this.v.mode, down
 * snapshots this.cur), then this.vt = t and this.draw(t, dt); expect = the
 * captured e. The effect records in the fixture are read back from the pushed
 * effect object (what the design actually stored).
 *
 * Output: tests/fixtures/alive_oracle.json (format: see the "about" field and the
 * orchestration contract). Expect values are rounded to 1e-5 (max rounding error
 * 5e-6, far below the 2e-3 tolerance); inputs are written at full precision.
 *
 * [user 2026-09-26] Every step also carries expect.bytes: the knob's section 9 output of that
 * step's (rounded) e at drive 150 with dither off, the default since the user's ruling, and the
 * F-T brightness floor on the LEDs whose target is lit in the step's persistent view (entry
 * non-null, a > 0): referenceOutput() below, float64 in control_center/alive_lights.py
 * reference_output()'s operation order, so the Python twin reproduces every byte and the C++
 * output stage matches within 1 (ALIVE.md 9 step 4, 11.1, 12.7). The design draws e only; the
 * bytes are this oracle's reading of the contract, not the design's.
 * Cases marked "designUncapped": true push more than 8 effects (the design has
 * no queue cap, ALIVE.md D12 caps at 8); their steps also carry "queue" (effects
 * in the design queue after this step's pushes, before draw) and "live" (after
 * draw) so a capped port can compare only while queue <= 8.
 *
 * Usage: node alive_oracle.cjs <design dir> [out.json]
 * Without out.json the JSON goes to stdout. Output is deterministic (no clock,
 * no randomness); a coverage self-check runs before anything is written and
 * throws if ALIVE.md 11.1 coverage is incomplete.
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const [designDir, outPath] = process.argv.slice(2);
if (!designDir) {
  process.stderr.write('usage: node alive_oracle.cjs <design dir> [out.json]\n');
  process.exit(2);
}
const HTML_PATH = path.join(designDir, 'Ring Choreography v2.dc.html');
const MODEL_PATH = path.join(designDir, 'knob-model.js');
const REFERENCE_PATH = path.join(__dirname, '..', 'fixtures', 'dominant_reference.json');

const noop = () => {};
const inert = name => () => { throw new Error(`alive_oracle: ${name} is not available (the oracle drives draw()/play() only)`); };

// ---------------------------------------------------------------- the design's logic class
function replaceOnce(source, anchor, replacement, what) {
  const count = source.split(anchor).length - 1;
  if (count !== 1) throw new Error(`alive_oracle: ${what} anchor found ${count} time(s), expected exactly once: ${anchor}`);
  const at = source.indexOf(anchor);
  return source.slice(0, at) + replacement + source.slice(at + anchor.length);
}

const html = fs.readFileSync(HTML_PATH, 'utf8');
const opens = [...html.matchAll(/<script type="text\/x-dc"[^>]*>/g)];
if (opens.length !== 1) throw new Error(`alive_oracle: expected one <script type="text/x-dc"> block, found ${opens.length}`);
const logicStart = opens[0].index + opens[0][0].length;
const logicEnd = html.indexOf('</script>', logicStart);
if (logicEnd < 0) throw new Error('alive_oracle: logic block is not closed');
const logicSource = html.slice(logicStart, logicEnd);
const logicLine = html.slice(0, logicStart).split('\n').length; // file line of the opening tag

// The ONE source patch: record the tone-mapped e of each ring segment / button.
const CAPTURE_PATCH = [
  { loop: 'ring', anchor: 'x.save(); x.rotate(i * 6 * Math.PI / 180);', insert: '__aliveCapture(0, i, e); ' },
  { loop: 'buttons', anchor: 'const bx = 61 + j * 70, by = 398;', insert: '__aliveCapture(1, j, e); ' }
];
let patched = logicSource;
for (const p of CAPTURE_PATCH) patched = replaceOnce(patched, p.anchor, p.insert + p.anchor, `${p.loop} compose loop`);
// [user 2026-09-26] The user's LED ruling (ALIVE.md 12.8), the only behavioural patch: literal anchors in
// draw(), each exactly once, so the oracle draws the knob's contract rather than the design's original
// rest: HOT == WARM (the Working comet and the song hand in the same warm white), a steady rest (no rest
// breath; time of day never dims resting below 0.80, restTodMin) and no song-progress hand at rest (the
// design draws the hand only at rest, so it is never drawn). The views keep the design's own targets.
const RULING_PATCH = [
  { what: 'HOT == WARM', anchor: 'HOT = mix(WARM, [1, 1, 1], 0.5);', replace: 'HOT = WARM;' },
  { what: 'rest time-of-day floor', anchor: 'const restK = asleep ? tod.b : 1;', replace: 'const restK = asleep ? Math.max(tod.b, 0.80) : 1;' },
  { what: 'no rest breath', anchor: 'const br = asleep && (this.props.breathe ?? true) ? 1 + 0.4 * Math.sin(t / 5200 * TAU) : off ?', replace: 'const br = off ?' },
  { what: 'no song hand at rest', anchor: "if (asleep && this.s.playing && v.mode === 'home' && this.s.conn === 'ok') {",
    replace: "if (false && asleep && this.s.playing && v.mode === 'home' && this.s.conn === 'ok') {" }
];
for (const p of RULING_PATCH) patched = replaceOnce(patched, p.anchor, p.replace, `ruling (${p.what})`);

let sink = null; // [ring[60], buttons[4]] for the draw in progress
const sandbox = {
  window: {},
  document: {},
  React: { createRef: () => ({ current: null }) },
  requestAnimationFrame: () => 0,
  cancelAnimationFrame: noop,
  setTimeout: inert('setTimeout'),
  clearTimeout: inert('clearTimeout'),
  setInterval: inert('setInterval'),
  clearInterval: inert('clearInterval'),
  performance: { now: inert('performance.now') },
  __aliveCapture: (kind, index, e) => {
    if (!sink) throw new Error('alive_oracle: capture outside draw()');
    sink[kind][index] = [e[0], e[1], e[2]];
  }
};
const designContext = vm.createContext(sandbox);
vm.runInContext(
  'class DCLogic { constructor(props) { this.props = props; } setState(patch) { this.state = Object.assign({}, this.state, patch); } }',
  designContext, { filename: 'alive_oracle-stubs.js' });
vm.runInContext(patched, designContext, { filename: 'Ring Choreography v2.dc.html', lineOffset: logicLine - 1 });
const D = vm.runInContext('({ Component, warmAt, mix, rgbN, cl, cd, md, TAU, MODEL_WARM, DUR, FG, GRN, RED, BLUE })', designContext);
const MODEL_WARM = D.MODEL_WARM;
const DESIGN_RED = '255,24,0'; // draw() line 280: the heat embers test r.c === '255,24,0'
const DESIGN_GREEN = '0,255,98'; // draw() line 287: pausedPlay tests buttons[0].c === '0,255,98'

function fakeCanvas() {
  const store = Object.create(null);
  const context2d = new Proxy(store, {
    get: (target, key) => (key in target ? target[key] : noop),
    set: (target, key, value) => { target[key] = value; return true; }
  });
  return { width: 0, height: 0, getContext: () => context2d };
}

// ---------------------------------------------------------------- knob-model.js (views only)
const modelContext = vm.createContext({
  window: {},
  document: { createElement: inert('document.createElement'), head: { appendChild: inert('document.head') } },
  Image: class { set src(v) { throw new Error('alive_oracle: image load ' + v); } },
  setTimeout: inert('setTimeout'),
  clearTimeout: inert('clearTimeout')
});
vm.runInContext(fs.readFileSync(MODEL_PATH, 'utf8'), modelContext, { filename: 'knob-model.js' });
const M = modelContext.window.NanoModel;
const reference = JSON.parse(fs.readFileSync(REFERENCE_PATH, 'utf8'));
if (!reference.colors || typeof reference.colors !== 'object') throw new Error('reference has no "colors" map');
for (const key of Object.keys(reference.colors).sort()) M.COLORS[key] = reference.colors[key];

// A view source: finishAlive targets + the flags' raw inputs, from one model state.
function src(patch) {
  const s = M.mk(patch);
  const v = M.view(s, { led: 'alive' });
  if (!v.alive) throw new Error('knob-model view() did not run finishAlive');
  const lit = (x, what) => {
    if (typeof x.a !== 'number' || !(x.a > 0)) throw new Error(`lit ${what} without a positive alpha`);
    return { c: x.c, a: x.a };
  };
  return {
    ring: v.ring.map((r, i) => (r && r.l ? lit(r, 'segment ' + i) : null)),
    buttons: v.buttons.map((b, j) => (b.l ? lit(b, 'button ' + j) : null)),
    asleep: !!v.ledSleep,
    offline: s.conn !== 'ok',
    pending: !!M.isPending(s),
    family: v.mode,
    cursor: v.cursor,
    vol: s.vol,
    playing: !!s.playing
  };
}

const ints = c => {
  const v = c.split(',').map(Number);
  if (v.length !== 3 || v.some(x => !Number.isInteger(x) || x < 0 || x > 255)) throw new Error('bad colour ' + c);
  return v;
};

// The fixture view at time t: targets + every flag the animator needs, each
// computed with the very expression draw() uses (line numbers of the design file).
function fixtureView(sv, t) {
  const home = sv.family === 'home';
  const cur = sv.ring[sv.cursor];
  return {
    ring: sv.ring.map(r => (r ? { c: ints(r.c), warm: r.c === MODEL_WARM, volRed: r.c === DESIGN_RED, a: r.a } : null)),
    buttons: sv.buttons.map(b => (b ? { c: ints(b.c), warm: b.c === MODEL_WARM, a: b.a } : null)),
    asleep: sv.asleep,
    offline: sv.offline,
    pending: sv.pending,
    family: sv.family,
    cursor: sv.cursor,
    vol: sv.vol,
    playing: sv.playing,
    heat: home && !sv.asleep && sv.vol >= 90, // line 273
    pausedPlay: home && !sv.asleep && !!sv.buttons[0] && sv.buttons[0].c === DESIGN_GREEN, // line 287
    tint: (sv.family === 'windows' || sv.family === 'recent') && !sv.asleep && cur && cur.c !== MODEL_WARM ? D.rgbN(cur.c) : null, // 308-309
    songProg: sv.asleep && sv.playing && home && !sv.offline ? ((t / 1000 + 50) % 214) / 214 : null // 313-314
  };
}

// this.v / this.s exactly as the fixture describes them (the fixture fully determines the inputs).
function designView(fv) {
  const colour = x => (x.warm ? MODEL_WARM : x.c.join(','));
  return {
    ring: fv.ring.map(r => (r ? { c: colour(r), l: 1, a: r.a } : null)),
    buttons: fv.buttons.map(b => (b ? { c: colour(b), l: 1, a: b.a } : null)),
    ledSleep: fv.asleep,
    mode: fv.family,
    cursor: fv.cursor
  };
}

// ---------------------------------------------------------------- case table helpers
const PAUSED = { playing: false, playReq: false };
const ASLEEP = { asleep: true };
const OK = id => ({ flash: { kind: 'ok', id }, flashId: id });
const ERR = id => ({ flash: { kind: 'err', id }, flashId: id });
const NIGHT_DRIVE = { np: { t: 'Night Channel', a: 'Velvet Circuit' } };
const home = (vol, ...extra) => src(Object.assign({ vol, volConf: vol }, ...extra));
const recent = (idx, status, ...extra) => src(Object.assign({ mode: 'recent', recent: { page: 0, idx, stack: [], status: status || 'ready' } }, ...extra));
const tracks = (pos, status, ...extra) => src(Object.assign({ mode: 'tracks', tracks: { pos, status: status || 'idle' } }, ...extra));
const windows = (idx, status, ...extra) => src(Object.assign({ mode: 'windows', win: { idx, status: status || 'browsing' } }, ...extra));
const offline = () => src({ conn: 'missing' });
const reconnecting = tick => src({ conn: 'reconnecting', tick });
const COLOF = Object.freeze({ marker: 'bound colour' }); // detect() line 208: colOf(colAt(nv, nv.cursor))

// detect() lines 213-216 for an ok flash: wash with the previous cursor colour, else bloom.
function flashOkFx(pv, nv) {
  const c = (pv.ring[pv.cursor] && pv.ring[pv.cursor].c) || MODEL_WARM;
  if ((pv.family === 'windows' || pv.family === 'recent') && c !== MODEL_WARM) return ['wash', { at: pv.cursor, c: D.rgbN(c) }];
  return ['bloom', { at: nv.cursor }];
}
// detect() lines 206-209: velocity and tail length, with virtual ms for performance.now().
function spinLens(times) {
  let vel = 0, last = -Infinity;
  return times.map(now => {
    const dtR = Math.max(16, now - last); last = now;
    vel = dtR > 400 ? 0 : vel * 0.55 + (1000 / dtR) * 0.45;
    return Math.round(D.cl((vel - 4) / 14) * 7);
  });
}
const tickDir = (to, from, d) => Math.sign(D.cd(to, from)) || d; // detect() line 209

const CASES = [];
function C(def) { CASES.push(def); }

// ---------------------------------------------------------------- the cases
// Views used repeatedly.
const H54 = home(54), H54P = home(54, PAUSED), H70 = home(70), H85 = home(85), H95 = home(95), H100 = home(100);
const W1 = windows(1), W2 = windows(2);
if (H54.cursor !== 2 || H70.cursor !== 10 || H95.cursor !== 23 || H100.cursor !== 25 || W1.cursor !== 51 || W2.cursor !== 54) throw new Error('unexpected model cursor');
const WASH_CLAUDE = flashOkFx(W1, H54);
if (WASH_CLAUDE[0] !== 'wash') throw new Error('Claude window should wash');

// 1. Every effect, isolated, sampled across its duration.
C({ name: 'fx-boot-home', hour: 20, note: 'Coming online (reconnect): offline marks, then the fresh Home 54 % view and boot (home: order md(i-35)).',
  end: 300 + 2800 + 40, coarse: [[0, 300, [50]], [1300, 3140, [33, 17]]],
  events: [[0, { view: offline() }], [300, { view: H54, fx: [['boot', {}]] }]] });
C({ name: 'fx-boot-nonhome', hour: 8, note: 'Boot replayed on Windows (Claude highlighted): e.home false, order 2|cd(i,0)|.',
  end: 250 + 2800 + 40, pattern: [50, 33, 17],
  events: [[0, { view: W1 }], [250, { fx: [['boot', {}]] }]] });
C({ name: 'fx-down', hour: 17.75, note: 'Going offline from a settled Home 54 %: snapshot drains into the cursor, amber marks fade in.',
  end: 400 + 1800 + 40, coarse: [[0, 400, [50]]],
  events: [[0, { view: H54 }], [400, { view: offline(), fx: [['down', { at: H54.cursor }]] }]] });
C({ name: 'fx-wake', hour: 23, note: 'Resting Home 54 % paused (night), then awake: wake front from the cursor; ring rises from rest.',
  end: 1500 + 520 + 40, coarse: [[0, 1500, [50]]],
  events: [[0, { view: home(54, PAUSED, ASLEEP) }], [1500, { view: H54P, fx: [['wake', { at: H54P.cursor }]] }]] });
{
  const a = tracks(0), b = tracks(1);
  C({ name: 'fx-tick-len0', hour: 13, note: 'Tracks: turn from Neutral to Next, single detent (len 0).',
    end: 300 + 180 + 40, coarse: [[0, 300, [50]]],
    events: [[0, { view: a }], [300, { view: b, fx: [['tick', { at: b.cursor, dir: tickDir(b.cursor, a.cursor, 1), len: 0 }]] }]] });
}
C({ name: 'fx-tick-len7', hour: 20, note: 'Windows: fast turn back from Chrome to Claude (dir -1, len 7 tail).',
  end: 300 + 180 + 40, coarse: [[0, 300, [50]]],
  events: [[0, { view: W2 }], [300, { view: W1, fx: [['tick', { at: W1.cursor, dir: tickDir(W1.cursor, W2.cursor, -1), len: 7 }]] }]] });
{
  const h0 = home(0);
  C({ name: 'fx-bound-min-warm', hour: 20, note: 'Home 0 %: pushing down at the bound (warm cursor colour, dir -1).',
    end: 300 + 460 + 40, coarse: [[0, 300, [50]]],
    events: [[0, { view: h0 }], [300, { fx: [['bound', { at: h0.cursor, c: COLOF, dir: -1 }]] }]] });
}
C({ name: 'fx-bound-max-red', hour: 13, note: 'Home 100 % (heat on): pushing up at the bound (red cursor colour, dir +1).',
  end: 300 + 460 + 40, coarse: [[0, 300, [50]]],
  events: [[0, { view: H100 }], [300, { fx: [['bound', { at: H100.cursor, c: COLOF, dir: 1 }]] }]] });
C({ name: 'fx-bloom', hour: 20, note: 'Home 54 % ok flash (cursor +-2 green) with bloom; flash ends at 650 ms.',
  end: 300 + 900 + 40, coarse: [[0, 300, [50]]],
  events: [[0, { view: H54 }], [300, { view: home(54, OK(1)), fx: [['bloom', { at: H54.cursor }]] }], [950, { view: H54 }]] });
C({ name: 'fx-fail', hour: 20, note: 'Windows switch to Chrome failed: err flash (red) and the head shake.',
  end: 300 + 700 + 40, coarse: [[0, 300, [50]]],
  events: [[0, { view: W2 }], [300, { view: windows(2, 'failed', ERR(1)), fx: [['fail', { at: W2.cursor }]] }]] });
C({ name: 'fx-sweep-next', hour: 20, note: 'Tracks Next skipped: back at neutral with ok flash; sweep clockwise.',
  end: 300 + 640 + 40, coarse: [[0, 300, [50]]],
  events: [[0, { view: tracks(1) }], [300, { view: tracks(0, 'done', OK(1), { qi: 2 }), fx: [['sweep', { at: 0, dir: 1 }]] }],
    [950, { view: tracks(0, 'done', { qi: 2 }) }]] });
C({ name: 'fx-sweep-prev', hour: 3.25, note: 'Tracks Previous skipped (night): sweep anticlockwise.',
  end: 300 + 640 + 40, coarse: [[0, 300, [50]]],
  events: [[0, { view: tracks(-1) }], [300, { view: tracks(0, 'done', OK(1), { qi: 0 }), fx: [['sweep', { at: 0, dir: -1 }]] }]] });
C({ name: 'fx-fill', hour: 20, note: 'Home 54 % paused (green Play breathing), play confirmed: fill n = round(54/2) = 27.',
  end: 400 + 760 + 40, coarse: [[0, 400, [50]]],
  events: [[0, { view: H54P }], [400, { view: H54, fx: [['fill', {}]] }]] });
C({ name: 'fx-drain', hour: 13, note: 'Home 85 % playing (amber top), pause confirmed: drain n = round(85/2) = 43; Play turns green.',
  end: 400 + 860 + 40, coarse: [[0, 400, [50]]],
  events: [[0, { view: H85 }], [400, { view: home(85, PAUSED), fx: [['drain', {}]] }]] });
{
  const e38 = home(38, { ext: true });
  C({ name: 'fx-shimmer', hour: 20, note: 'Volume changed on Sonos 54 -> 38 %: blue cursor +-1, shimmer from the old cursor to the new.',
    end: 300 + 1000 + 40, coarse: [[0, 300, [50]]],
    events: [[0, { view: H54 }], [300, { view: e38, fx: [['shimmer', { from: H54.cursor, to: e38.cursor }]] }]] });
}
C({ name: 'fx-wash', hour: 20, note: 'Windows switch to Claude confirmed: Home with ok flash; wash in the Claude accent from the old cursor.',
  end: 300 + 1100 + 40, coarse: [[0, 300, [50]]],
  events: [[0, { view: W1 }], [300, { view: home(54, OK(1)), fx: [WASH_CLAUDE] }], [950, { view: H54 }]] });
C({ name: 'fx-reveal', hour: 13, note: 'Mode change Home -> Tracks: landmarks unfold from the top.',
  end: 300 + 450 + 40, coarse: [[0, 300, [50]]],
  events: [[0, { view: H54 }], [300, { view: tracks(0), fx: [['reveal', {}]] }]] });
C({ name: 'fx-press-slots', hour: 20, note: 'Home 54 %: presses on slots 0..3, staggered 70 ms (slot 2 registered 8 ms before its frame).',
  end: 510 + 220 + 40, coarse: [[0, 300, [50]]],
  events: [[0, { view: H54 }], [300, { fx: [['press', { n: 0 }]] }], [370, { fx: [['press', { n: 1 }]] }],
    [440, { fx: [['press', { n: 2 }, 432]] }], [510, { fx: [['press', { n: 3 }]] }]] });

// 2. A kill case for every foreground type (a second FG effect starts mid-way).
C({ name: 'kill-boot-by-down', hour: 20, note: 'Boot (Home) unplugged again at 1400 ms: boot fades over 120 ms while down drains.',
  end: 1600 + 400, coarse: [[0, 200, [50]], [200, 1500, [33]]],
  events: [[0, { view: offline() }], [200, { view: H54, fx: [['boot', {}]] }], [1600, { view: offline(), fx: [['down', { at: H54.cursor }]] }]] });
C({ name: 'kill-down-by-boot', hour: 20, note: 'Down replugged at 900 ms: down fades over 120 ms while boot starts.',
  end: 1200 + 400, coarse: [[0, 300, [50]]],
  events: [[0, { view: H54 }], [300, { view: offline(), fx: [['down', { at: H54.cursor }]] }], [1200, { view: H54, fx: [['boot', {}]] }]] });
C({ name: 'kill-bloom-by-sweep', hour: 13, note: 'Tracks: bloom at 0, a sweep 450 ms later kills it.',
  end: 750 + 300, coarse: [[0, 300, [50]]],
  events: [[0, { view: tracks(1) }], [300, { view: tracks(0, 'done', OK(1), { qi: 2 }), fx: [['bloom', { at: 0 }]] }],
    [750, { fx: [['sweep', { at: 0, dir: 1 }]] }]] });
C({ name: 'kill-fail-by-bloom', hour: 20, note: 'Home: transport failed (err flash, fail), retry confirmed 350 ms later (ok flash, bloom).',
  end: 650 + 300, coarse: [[0, 300, [50]]],
  events: [[0, { view: H54 }], [300, { view: home(54, ERR(1)), fx: [['fail', { at: H54.cursor }]] }],
    [650, { view: home(54, OK(2)), fx: [['bloom', { at: H54.cursor }]] }]] });
C({ name: 'kill-sweep-by-sweep', hour: 20, note: 'Two Next skips 320 ms apart: the first sweep fades, the second runs to its end.',
  end: 620 + 640 + 40, coarse: [[0, 300, [50]]],
  events: [[0, { view: tracks(1) }], [300, { view: tracks(0, 'done', OK(1), { qi: 2 }), fx: [['sweep', { at: 0, dir: 1 }]] }],
    [620, { view: tracks(0, 'done', OK(2), { qi: 3 }), fx: [['sweep', { at: 0, dir: 1 }]] }]] });
C({ name: 'kill-fill-by-drain', hour: 13, note: 'Play confirmed then pause confirmed 380 ms later: fill fades, drain runs.',
  end: 680 + 300, coarse: [[0, 300, [50]]],
  events: [[0, { view: H54P }], [300, { view: H54, fx: [['fill', {}]] }], [680, { view: H54P, fx: [['drain', {}]] }]] });
C({ name: 'kill-drain-by-fill', hour: 8, note: 'Pause confirmed at 85 % then play confirmed 430 ms later: drain fades, fill runs.',
  end: 730 + 300, coarse: [[0, 300, [50]]],
  events: [[0, { view: H85 }], [300, { view: home(85, PAUSED), fx: [['drain', {}]] }], [730, { view: H85, fx: [['fill', {}]] }]] });
{
  const e38 = home(38, { ext: true }), e30 = home(30, { ext: true });
  C({ name: 'kill-shimmer-by-shimmer', hour: 20, note: 'Two external volume changes (54 -> 38 -> 30 %) 500 ms apart.',
    end: 800 + 600, coarse: [[0, 300, [50]]],
    events: [[0, { view: H54 }], [300, { view: e38, fx: [['shimmer', { from: H54.cursor, to: e38.cursor }]] }],
      [800, { view: e30, fx: [['shimmer', { from: e38.cursor, to: e30.cursor }]] }]] });
}
C({ name: 'kill-wash-by-bloom', hour: 20, note: 'Claude wash, then an unrelated ok (bloom) 550 ms later kills it.',
  end: 850 + 300, coarse: [[0, 300, [50]]],
  events: [[0, { view: W1 }], [300, { view: home(54, OK(1)), fx: [WASH_CLAUDE] }],
    [850, { view: home(54, OK(2)), fx: [['bloom', { at: H54.cursor }]] }]] });

// 3. Duck with two overlapping FG effects; tone map above the knee.
C({ name: 'duck-two-fg', hour: 13, note: 'Home 70 %: bloom at u 0.5 (duck 0.35) killed by fail; duck = max(killed bloom, rising fail).',
  end: 750 + 450, coarse: [[0, 300, [50]]],
  events: [[0, { view: H70 }], [300, { view: home(70, OK(1)), fx: [['bloom', { at: H70.cursor }]] }],
    [750, { view: home(70, ERR(2)), fx: [['fail', { at: H70.cursor }]] }]] });
C({ name: 'tone-overlap-bright', hour: 13, note: 'Home 95 % (heat): bloom, len-7 tick, bound, press and wake on the bright red cursor at once.',
  end: 300 + 900 + 40, coarse: [[0, 300, [50]]],
  events: [[0, { view: H95 }], [300, { fx: [['bloom', { at: H95.cursor }], ['tick', { at: H95.cursor, dir: 1, len: 7 }],
    ['bound', { at: H95.cursor, c: COLOF, dir: 1 }], ['press', { n: 0 }], ['wake', { at: H95.cursor }]] }]] });

// 4. Damping in every tau branch, colour snap and colour glide.
C({ name: 'damp-rise-awake-home', hour: 20, note: 'Dark start, awake Home 54 %: cursor rises tau 10, arc tau 55, buttons tau 40; colour from the initial cur colour.',
  end: 450, events: [[0, { view: H54 }]] });
C({ name: 'damp-fall-awake-volume', hour: 13, note: 'Home 70 % -> 40 %: the arc above 40 % falls with tau 140 (colour frozen), new cursor rises tau 10.',
  end: 400 + 700, coarse: [[0, 400, [50]]], events: [[0, { view: H70 }], [400, { view: home(40) }]] });
C({ name: 'damp-awake-home-to-tracks', hour: 20, note: 'Home 70 % -> Tracks: arc falls tau 140, Tracks landmarks rise tau 55, Skip button falls tau 160.',
  end: 400 + 600, coarse: [[0, 400, [50]]], events: [[0, { view: H70 }], [400, { view: tracks(0) }]] });
C({ name: 'damp-sleep-home', hour: 23, note: 'Home 54 % paused falls asleep (night): ring and buttons fall tau 700 toward the steady rest levels (user 2026-09-26: no rest breath).',
  end: 400 + 2400, pattern: [33, 50], events: [[0, { view: H54P }], [400, { view: home(54, PAUSED, ASLEEP) }]] });
C({ name: 'damp-asleep-rise-dark', hour: 3.25, note: 'Dark start while resting (nothing playing, 03:15): rise tau 400, buttons tau 400, colour snap below a 0.02.',
  end: 1600, coarse: [[300, 1600, [50]]], events: [[0, { view: home(54, ASLEEP, PAUSED, { nothing: true }) }]] });
C({ name: 'damp-wake-glide-windows', hour: 20, note: 'Windows resting (all warm) wakes: app colours glide in at tau 70, cursor tau 10, buttons tau 40 with Cancel/Switch colours.',
  end: 1800, coarse: [[0, 1200, [50]]], events: [[0, { view: windows(1, 'browsing', ASLEEP) }], [1200, { view: W1 }]] });
C({ name: 'damp-colour-snap', hour: 20, note: 'Ok flash paints 0..4 green; after it ends 3,4 decay below 0.02; volume 58 % relights them warm in a 1 ms frame (snap k = 1 - e^-1).',
  end: 2200, coarse: [[0, 300, [50]], [1000, 1850, [50]]], hits: [1899],
  events: [[0, { view: H54 }], [300, { view: home(54, OK(1)) }], [950, { view: H54 }], [1900, { view: home(58) }]] });

// 5. Breath: resting and offline, each over more than a full period.
C({ name: 'breath-rest-home-night', hour: 23, note: 'Resting Home 54 % paused idle at 23:00 (todB 0.617, floored at 0.80 by the user 2026-09-26 ruling): steady rest (no breath) over more than 5200 ms.',
  end: 6400, pattern: [50], events: [[0, { view: home(54, PAUSED, ASLEEP, { pIdle: true }) }]] });
C({ name: 'breath-offline', hour: 20, note: 'Waiting for PC: 12 amber marks at 0.12 with the offline breath over more than 2600 ms.',
  end: 3000, pattern: [50, 50, 33, 17], events: [[0, { view: offline() }]] });
C({ name: 'breath-rest-windows-day', hour: 13, note: 'Resting Windows at 13:00 (todB 1): all warm, steady rest (user 2026-09-26: no breath).',
  end: 2000, pattern: [33], events: [[0, { view: windows(1, 'browsing', ASLEEP) }]] });

// 6. Heat.
C({ name: 'heat-home95', hour: 20, note: 'Home 95 % awake: red segments (45..48) glow with independent ember cycles for 1.6 s.',
  end: 1300, events: [[0, { view: H95 }]] });
C({ name: 'heat-home100-paused-then-sleep', hour: 13, note: 'Home 100 % paused (Play breathing green) with heat from t = 2 s; falls asleep at 3.3 s (heat off).',
  t0: 2000, end: 3900, pattern: [33, 17],
  events: [[2000, { view: home(100, PAUSED) }], [3300, { view: home(100, PAUSED, ASLEEP) }]] });

// 7. Ambient tint.
C({ name: 'tint-windows-glide', hour: 20, note: 'Windows: tint appears (Claude), glides to Chrome, disappears on Codex (warm), residue decays on Home.',
  end: 2300, pattern: [33, 17],
  events: [[0, { view: W1 }], [600, { view: W2 }], [1200, { view: windows(0) }], [1800, { view: H54 }]] });
C({ name: 'tint-recent-sleep', hour: 13, note: 'Recently Added: Tropicalia tint, glide to Night Channel, then resting (tint off).',
  end: 1600, pattern: [33, 17], events: [[0, { view: recent(1) }], [500, { view: recent(2) }], [1000, { view: recent(2, 'ready', ASLEEP) }]] });

// 8. Song hand at several progress values (design fake progress; the view is re-sent every step).
// [user 2026-09-26] No song-progress hand at rest (RULING_PATCH): these cases now check that it stays dark.
C({ name: 'song-hand-p023', hour: 23, note: 'Resting Home 54 % playing at 23:00, progress ~0.234.', end: 500, pattern: [50, 33, 17],
  events: [[0, { view: home(54, ASLEEP) }]] });
C({ name: 'song-hand-p051', hour: 20, note: 'Resting Home 54 % playing, progress ~0.514.', t0: 60000, end: 60500, pattern: [50, 33, 17],
  events: [[60000, { view: home(54, ASLEEP) }]] });
C({ name: 'song-hand-p079', hour: 3.25, note: 'Resting Home 85 % playing at 03:15, progress ~0.794.', t0: 120000, end: 120500, pattern: [50, 33, 17],
  events: [[120000, { view: home(85, ASLEEP) }]] });
C({ name: 'song-hand-wrap', hour: 13, note: 'Resting Home 54 % playing, progress 0.9986 -> 0 -> 0.0014: the hand crosses 12 o\'clock.',
  t0: 163700, end: 164300, pattern: [50, 33, 17], events: [[163700, { view: home(54, ASLEEP) }]] });

// 9. Working comet.
{
  const ev = [];
  for (let k = 0; k <= 5; k++) ev.push([700 + 260 * k, { view: recent(2, 'pending', { tick: k }) }]);
  C({ name: 'pending-recent-lap', hour: 20, note: 'Recently Added playback pending: comet laps from head 30 while the cursor pulses every 260 ms.',
    t0: 700, end: 2200, events: ev });
}
C({ name: 'pending-home-volume', hour: 13, note: 'Home 61 % requested, 54 % confirmed: comet over a lap from t = 1300 (head wraps past 60).',
  t0: 1300, end: 2800, pattern: [33, 17], events: [[1300, { view: home(61, { volConf: 54 }) }]] });

// 10. Queue: exactly at capacity (ports compare fully) and beyond (design uncapped).
C({ name: 'queue-at-capacity', hour: 20, note: 'Windows: 4 presses, 3 ticks and a bound within 70 ms: exactly 8 effects queued, never more.',
  end: 370 + 460 + 40, coarse: [[0, 300, [50]]],
  events: [[0, { view: W1 }], [300, { fx: [['press', { n: 0 }]] }], [310, { fx: [['press', { n: 1 }]] }],
    [320, { fx: [['tick', { at: W1.cursor, dir: 1, len: 0 }]] }], [330, { fx: [['tick', { at: W1.cursor, dir: 1, len: 2 }]] }],
    [340, { fx: [['press', { n: 2 }]] }], [350, { fx: [['tick', { at: W1.cursor, dir: 1, len: 4 }]] }],
    [360, { fx: [['press', { n: 3 }]] }], [370, { fx: [['bound', { at: W1.cursor, c: COLOF, dir: 1 }]] }]] });
{
  const times = [], ev = [[0, { view: recent(0) }]];
  for (let i = 1; i <= 10; i++) times.push(300 + (i - 1) * 18);
  const lens = spinLens(times.concat([480, 498]));
  let prev = recent(0);
  for (let i = 1; i <= 10; i++) {
    const v = recent(i);
    ev.push([times[i - 1], { view: v, fx: [['tick', { at: v.cursor, dir: tickDir(v.cursor, prev.cursor, 1), len: lens[i - 1] }]] }]);
    prev = v;
  }
  // Two more detents at the end of the list: the cursor does not move, so the design bounds.
  ev.push([480, { fx: [['bound', { at: prev.cursor, c: COLOF, dir: 1 }]] }]);
  ev.push([498, { fx: [['bound', { at: prev.cursor, c: COLOF, dir: 1 }]] }]);
  C({ name: 'queue-spin-uncapped', hour: 20, designUncapped: true,
    note: 'Recently Added spun from item 1 to More in 162 ms (18 ms/detent, tail grows to 7): 10 ticks live at once, then bounds.',
    end: 498 + 460 + 40, coarse: [[0, 300, [50]]], events: ev });
}
C({ name: 'queue-mixed-uncapped', hour: 13, designUncapped: true,
  note: 'Home 54 %: 7 presses, bloom killed by fail killed by sweep, then shimmer: killed effects stay queued (> 8 in the design).',
  end: 440 + 660, coarse: [[0, 300, [50]]],
  events: [[0, { view: H54 }], [300, { fx: [['press', { n: 0 }], ['press', { n: 1 }]] }],
    [320, { view: home(54, OK(1)), fx: [['bloom', { at: H54.cursor }]] }], [340, { fx: [['press', { n: 2 }]] }],
    [360, { view: home(54, ERR(2)), fx: [['fail', { at: H54.cursor }]] }], [380, { fx: [['press', { n: 3 }], ['press', { n: 0 }]] }],
    [400, { fx: [['sweep', { at: H54.cursor, dir: 1 }]] }], [420, { fx: [['press', { n: 1 }], ['press', { n: 2 }]] }],
    [440, { view: home(38, { ext: true }), fx: [['shimmer', { from: H54.cursor, to: home(38).cursor }]] }]] });

// 11. Replacement of wake / reveal / bound (same type replaces the running one).
C({ name: 'replace-wake-reveal-bound', hour: 20, note: 'Wake + reveal, bound, then wake, reveal and bound again mid-way: each replaces its predecessor.',
  end: 1060 + 520 + 40, coarse: [[0, 800, [50]]],
  events: [[0, { view: home(54, PAUSED, ASLEEP) }], [800, { view: H54P, fx: [['wake', { at: H54P.cursor }], ['reveal', {}]] }],
    [950, { fx: [['bound', { at: H54P.cursor, c: COLOF, dir: 1 }]] }],
    [1060, { fx: [['wake', { at: H54P.cursor }], ['reveal', {}], ['bound', { at: H54P.cursor, c: COLOF, dir: 1 }]] }]] });

// 12. Realistic sequences (event mapping as detect() does it, in its order).
{
  const ev = [[0, { view: H54 }], [300, { view: offline(), fx: [['down', { at: H54.cursor }]] }]];
  for (let k = 0; k <= 6; k++) ev.push([1900 + 260 * k, { view: reconnecting(k) }]);
  ev.push([3500, { view: H54, fx: [['boot', {}]] }]);
  C({ name: 'seq-unplug-replug', hour: 20, note: 'Unplug (down), reconnecting after 1.6 s (pulsing marks, Working comet), reconnected at 3.5 s (boot).',
    end: 3500 + 2800 + 40, pattern: [33, 33, 50], coarse: [[0, 300, [50]]], events: ev });
}
{
  const t0v = tracks(0), t1v = tracks(1), done = tracks(0, 'done', OK(1), { qi: 2 });
  C({ name: 'seq-tracks-skip', hour: 13, note: 'Home -> Tracks (press 4, reveal), turn to Next (tick), press 4 (pending pulse), skip done: bloom then sweep at the same instant.',
    end: 1950 + 900 + 40, coarse: [[0, 300, [50]], [1300, 1940, [33, 17]]],
    events: [[0, { view: H54 }], [300, { view: t0v, fx: [['press', { n: 3 }], ['reveal', {}]] }],
      [800, { view: t1v, fx: [['tick', { at: t1v.cursor, dir: tickDir(t1v.cursor, t0v.cursor, 1), len: 0 }]] }],
      [1300, { view: tracks(1, 'pending', { tick: 0 }), fx: [['press', { n: 3 }]] }],
      [1560, { view: tracks(1, 'pending', { tick: 1 }) }], [1820, { view: tracks(1, 'pending', { tick: 2 }) }],
      [1950, { view: done, fx: [flashOkFx(tracks(1, 'pending', { tick: 2 }), done), ['sweep', { at: done.cursor, dir: 1 }]] }],
      [2600, { view: tracks(0, 'done', { qi: 2 }) }]] });
}
{
  const r0 = recent(0), r1 = recent(1), r2 = recent(2), last = recent(2, 'pending', { tick: 4 });
  const played = home(54, NIGHT_DRIVE, OK(1));
  const lens = spinLens([1200, 1400]);
  const ev = [[0, { view: H54 }], [300, { view: recent(0, 'loading', { tick: 0 }), fx: [['press', { n: 1 }], ['reveal', {}]] }],
    [560, { view: recent(0, 'loading', { tick: 1 }) }], [950, { view: r0 }],
    [1200, { view: r1, fx: [['tick', { at: r1.cursor, dir: tickDir(r1.cursor, r0.cursor, 1), len: lens[0] }]] }],
    [1400, { view: r2, fx: [['tick', { at: r2.cursor, dir: tickDir(r2.cursor, r1.cursor, 1), len: lens[1] }]] }],
    [1700, { view: recent(2, 'pending', { tick: 0 }), fx: [['press', { n: 3 }]] }]];
  for (let k = 1; k <= 4; k++) ev.push([1700 + 260 * k, { view: recent(2, 'pending', { tick: k }) }]);
  ev.push([2900, { view: played, fx: [['reveal', {}], flashOkFx(last, played)] }]);
  ev.push([3550, { view: home(54, NIGHT_DRIVE) }]);
  C({ name: 'seq-recent-play', hour: 20, note: 'Home -> Recently Added (loading comet), turn to Night Channel, Play (pending pulse draws the cursor warm), started: reveal + bloom (design, see ALIVE D7).',
    end: 2900 + 1100 + 40, coarse: [[0, 300, [50]], [950, 2890, [33, 17]], [3450, 4040, [33, 17]]], events: ev });
}
{
  const pend1 = windows(2, 'pending', { tick: 1 }), done = home(54, OK(1));
  const ev = [[0, { view: H54 }], [300, { view: W1, fx: [['press', { n: 2 }], ['reveal', {}]] }],
    [700, { view: W2, fx: [['tick', { at: W2.cursor, dir: tickDir(W2.cursor, W1.cursor, 1), len: 0 }]] }],
    [1000, { view: windows(2, 'pending', { tick: 0 }), fx: [['press', { n: 3 }]] }], [1260, { view: pend1 }],
    [1450, { view: done, fx: [['reveal', {}], flashOkFx(pend1, done)] }], [2100, { view: H54 }]];
  C({ name: 'seq-windows-switch', hour: 20, note: 'Home -> Windows (press 3, reveal), turn to Chrome, Switch (pending pulse in the app colour), switched: reveal + Chrome wash.',
    end: 1450 + 1100 + 40, coarse: [[0, 300, [50]], [1000, 1440, [33, 17]], [2100, 2590, [33, 17]]], events: ev });
}
{
  const h55 = home(55, { volConf: 54 }), h56 = home(56, { volConf: 54 }), h57 = home(57, { volConf: 54 });
  const lens = spinLens([994, 1060, 1120]);
  C({ name: 'seq-wake-turn-home', hour: 23, note: 'Resting Home playing (song hand), first detent at 994 ms wakes (wake + tick), 2nd detent keeps the cursor (bound), 3rd ticks; volume acked at 1500.',
    end: 1800, coarse: [[0, 1000, [50]]], hits: [993],
    events: [[0, { view: home(54, ASLEEP) }],
      [1000, { view: h55, fx: [['wake', { at: h55.cursor }, 994], ['tick', { at: h55.cursor, dir: tickDir(h55.cursor, H54.cursor, 1), len: lens[0] }, 994]] }],
      [1060, { view: h56, fx: [['bound', { at: h56.cursor, c: COLOF, dir: 1 }]] }],
      [1120, { view: h57, fx: [['tick', { at: h57.cursor, dir: tickDir(h57.cursor, h56.cursor, 1), len: lens[2] }]] }],
      [1500, { view: home(57) }]] });
}

// ---------------------------------------------------------------- section 9 output (knob bytes)
// BEGIN referenceOutput (kept identical in alive_oracle.cjs and alive_oracle_bs.cjs; the tests compare them)
// [user 2026-09-26] ALIVE.md section 9 with dither off (the default) and rule F-T: transfer (sRGB
// EOTF, e clamped to 0..1), drive, the [D17] power limit over 60 ring + 8 button LEDs (B = 16920),
// round half up and clamp; then an LED whose target is lit (ringLit[i] / buttonLit[j]) and whose
// plain rounding is dark while m = max(v) > 0 shows one count on its dominant channel (v_c == m; a
// tie lights every tied channel), the rest 0: the byte plain rounding shows just above m = 0.5
// (12.7, channel rule amended 2026-09-26). Float64 in the operation order of
// alive_lights.reference_output().
// Returns 64 x 0xRRGGBB, ring 0..59 then button slots 0..3.
const OUTPUT_DRIVE = 150, OUTPUT_BUDGET = 16920, OUTPUT_BUTTON_LEDS = 2;
function outputEotf(e) {
  const x = e < 0 ? 0 : e > 1 ? 1 : e;
  return x <= 0.04045 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4);
}
function referenceOutput(ring, buttons, ringLit, buttonLit, drive) {
  const linRing = ring.map(c => c.map(outputEotf)), linButtons = buttons.map(c => c.map(outputEotf));
  let total = 0;
  for (const c of linRing) total += (c[0] + c[1] + c[2]) * drive;
  for (const c of linButtons) total += OUTPUT_BUTTON_LEDS * (c[0] + c[1] + c[2]) * drive;
  const scale = total > OUTPUT_BUDGET ? drive * (OUTPUT_BUDGET / total) : drive;
  const pixel = (c, lit) => {
    const v = c.map(x => x * scale);
    let q = v.map(x => Math.min(255, Math.max(0, Math.floor(x + 0.5))));
    if (lit && q[0] === 0 && q[1] === 0 && q[2] === 0) {
      const m = Math.max(v[0], v[1], v[2]);
      if (m > 0) q = v.map(x => (x >= m ? 1 : 0));
    }
    return q[0] * 65536 + q[1] * 256 + q[2];
  };
  return linRing.map((c, i) => pixel(c, ringLit[i])).concat(linButtons.map((c, j) => pixel(c, buttonLit[j])));
}
const litOf = entry => entry !== null && entry !== undefined && entry.a > 0;
// END referenceOutput

// ---------------------------------------------------------------- driver
const USED = {
  boot: ['home'], down: ['at'], wake: ['at'], tick: ['at', 'dir', 'len'], bound: ['at', 'c', 'dir'],
  bloom: ['at'], fail: ['at'], sweep: ['at', 'dir'], fill: ['n'], drain: ['n'], shimmer: ['from', 'to'],
  wash: ['at', 'c'], reveal: [], press: ['n']
};
const MAX_QUEUE = 8;
const DEFAULT_PATTERN = [16, 17, 17]; // ~60 fps frame gaps
const r5 = x => Math.round(x * 1e5) / 1e5;

function timeline(def) {
  const t0 = def.t0 || 0, end = def.end;
  const must = new Set([t0, end].concat(def.hits || []));
  for (const [T, ev] of def.events) {
    must.add(T);
    for (const f of ev.fx || []) {
      const start = f[2] != null ? f[2] : T, dur = D.DUR[f[0]];
      if (start < T) must.add(start - 1); // no frame between the effect's t0 and its own frame
      for (const x of [Math.round(dur / 2), dur, dur + 1]) must.add(start + x); // u = 0.5, u = 1, just past the end
      if (D.FG.includes(f[0])) for (const x of [60, 120]) must.add(start + x); // kill fade of the running FG effects (amp 0.5, amp 0)
    }
  }
  const hits = [...must].filter(x => x >= t0 && x <= end).sort((a, b) => a - b);
  const counters = new Map();
  const patternAt = t => {
    for (const [from, to, p] of def.coarse || []) if (t >= from && t < to) return p;
    return def.pattern || DEFAULT_PATTERN;
  };
  const times = [t0];
  let t = t0;
  while (t < end) {
    const p = patternAt(t), k = counters.get(p) || 0;
    counters.set(p, k + 1);
    let dt = p[k % p.length];
    const next = hits.find(x => x > t);
    if (next !== undefined && t + dt > next) dt = next - t;
    t += dt;
    times.push(t);
  }
  return times;
}

function runCase(def) {
  const hour = def.hour, tod = D.warmAt(hour);
  const warm = tod.c.slice(), hot = tod.c.slice();   // [user 2026-09-26] HOT == WARM (RULING_PATCH)
  const inst = new D.Component({ breathe: true, glow: 1, speed: 1 });
  inst.state = Object.assign({}, inst.state, { hour });
  inst.cvRef.current = fakeCanvas();
  let pending = false;
  inst.M = { isPending: () => pending };

  const events = new Map();
  for (const [T, ev] of def.events) {
    if (events.has(T)) throw new Error(`${def.name}: two events at ${T}`);
    events.set(T, ev);
  }
  const times = timeline(def);
  for (const T of events.keys()) if (!times.includes(T)) throw new Error(`${def.name}: event at ${T} outside the timeline`);

  const steps = [], trace = [];
  let source = null, lastView = null, prevT = null;
  for (const t of times) {
    const dt = prevT == null ? 0 : t - prevT;
    if (!Number.isInteger(dt) || dt < 0 || dt > 50) throw new Error(`${def.name}: dt ${dt} at ${t}`);
    const ev = events.get(t) || {};
    if (ev.view) source = ev.view;
    if (!source) throw new Error(`${def.name}: no view at the first step`);
    const step = { t, dt };
    const fv = fixtureView(source, t), fvJson = JSON.stringify(fv);
    if (fvJson !== lastView) {
      step.view = fv;
      lastView = fvJson;
      inst.v = designView(fv);
      inst.s = { vol: fv.vol, playing: fv.playing, conn: fv.offline ? 'missing' : 'ok' };
      pending = fv.pending;
    }
    step.effects = [];
    for (const f of ev.fx || []) {
      const [type, params0, explicitT0] = f;
      const t0 = explicitT0 != null ? explicitT0 : t;
      if (!(t0 <= t) || (prevT != null && !(t0 > prevT)) || (prevT == null && t0 !== t)) throw new Error(`${def.name}: effect ${type} t0 ${t0} not in (${prevT}, ${t}]`);
      const params = Object.assign({}, params0);
      if (params.c === COLOF) params.c = inst.colOf((inst.v.ring[params.at] && inst.v.ring[params.at].c) || MODEL_WARM);
      const count = inst.fx.length;
      inst.vt = t0;
      inst.play(type, params, true);
      const e = inst.fx[inst.fx.length - 1];
      if (!e || e.type !== type || e.t0 !== t0 || inst.fx.length > count + 1) throw new Error(`${def.name}: play(${type}) did not push one effect`);
      const rec = { type, t0 };
      for (const k of USED[type]) {
        const val = e[k];
        if (k === 'c') { if (!Array.isArray(val) || val.length !== 3) throw new Error(`${def.name}: ${type}.c`); rec.c = val.slice(); }
        else if (k === 'home') { if (typeof val !== 'boolean') throw new Error(`${def.name}: ${type}.home`); rec.home = val; }
        else { if (!Number.isInteger(val)) throw new Error(`${def.name}: ${type}.${k} = ${val}`); rec[k] = val; }
      }
      step.effects.push(rec);
    }
    const queue = inst.fx.length;
    if (!def.designUncapped && queue > MAX_QUEUE) throw new Error(`${def.name}: ${queue} effects queued at ${t} (mark the case designUncapped)`);
    const before = { fx: inst.fx.slice(), cur: inst.cur.map(c => Object.assign({}, c)), bcur: inst.bcur.map(c => Object.assign({}, c)) };
    inst.vt = t;
    sink = [new Array(60), new Array(4)];
    inst.draw(t, dt);
    const captured = sink;
    sink = null;
    for (let i = 0; i < 60; i++) if (!captured[0][i]) throw new Error(`${def.name}: ring ${i} not captured at ${t}`);
    for (let j = 0; j < 4; j++) if (!captured[1][j]) throw new Error(`${def.name}: button ${j} not captured at ${t}`);
    if (def.designUncapped) { step.queue = queue; step.live = inst.fx.length; }
    step.expect = { ring: captured[0].map(e => e.map(r5)), buttons: captured[1].map(e => e.map(r5)) };
    step.expect.bytes = referenceOutput(step.expect.ring, step.expect.buttons, fv.ring.map(litOf), fv.buttons.map(litOf),
      OUTPUT_DRIVE);
    steps.push(step);
    trace.push({ t, dt, fv: JSON.parse(lastView), before, after: { fx: inst.fx.slice(), cur: inst.cur.map(c => Object.assign({}, c)), bcur: inst.bcur.map(c => Object.assign({}, c)) }, raw: captured });
    prevT = t;
  }
  const out = { name: def.name, note: def.note, hour, warm, hot, todB: tod.b };
  if (def.designUncapped) out.designUncapped = true;
  out.steps = steps;
  return { out, trace, tod };
}

// ---------------------------------------------------------------- coverage self-check (ALIVE.md 11.1)
function coverage(results) {
  const problems = [];
  const need = (ok, what) => { if (!ok) problems.push(what); };
  // Effect samples, per effect instance (keyed by the design's effect object).
  const samples = new Map();
  const variant = e => e.type === 'boot' ? `boot-${e.home ? 'home' : 'nonhome'}` : e.type === 'tick' ? `tick-len${e.len}`
    : e.type === 'sweep' ? `sweep-${e.dir > 0 ? 'next' : 'prev'}` : e.type === 'press' ? `press-${e.n}` : e.type;
  const branch = new Set();
  let snap = 0, glide = 0, heatSpan = 0, pendingSpan = 0, restSpan = 0, offSpan = 0, duckTwo = 0, knee = 0, knee2 = 0;
  const songBins = new Set();
  let tintCase = false;
  for (const { out, trace, tod } of results) {
    let heatStart = null, pendStart = null, restStart = null, offStart = null;
    const tints = [];
    for (const s of trace) {
      const fv = s.fv, t = s.t;
      for (const e of s.before.fx) {
        const ms = t - e.t0, u = ms / e.dur;
        if (!samples.has(e)) samples.set(e, { variant: variant(e), type: e.type, n: 0, u0: false, uHalf: false, u1: false, past: false, fades: 0, killedOut: false });
        const k = samples.get(e);
        const amp = e.kill != null ? 1 - (t - e.kill) / 120 : 1;
        if (u > 1) { if (u <= 1 + 25 / e.dur && e.kill == null) k.past = true; continue; }
        if (amp <= 0) { k.killedOut = true; continue; }
        k.n++;
        if (u <= 0.02) k.u0 = true;
        if (Math.abs(u - 0.5) <= 0.03) k.uHalf = true;
        if (u >= 0.98) k.u1 = true;
        if (e.kill != null && t > e.kill) k.fades++;
      }
      const duckers = s.before.fx.filter(e => D.FG.includes(e.type) && e.type !== 'boot' && e.type !== 'down').filter(e => {
        const u = (t - e.t0) / e.dur, amp = e.kill != null ? 1 - (t - e.kill) / 120 : 1;
        return u > 0 && u <= 1 && amp > 0 && Math.sin(Math.PI * u) * amp > 0.05;
      });
      if (duckers.length >= 2) duckTwo++;
      for (const e of s.raw[0].concat(s.raw[1])) {
        const mx = Math.max(e[0], e[1], e[2]);
        if (mx >= 0.97) knee++;
        if (mx >= 0.995) knee2++;
      }
      // Damping branches: the ta draw() computes (lines 271-283, 288-293).
      // [user 2026-09-26] steady rest floored at todB 0.80, breath only offline (RULING_PATCH).
      const asleep = fv.asleep, off = fv.family === 'offline', restK = asleep ? Math.max(tod.b, 0.80) : 1;
      const br = off ? 0.6 + 0.4 * Math.sin(t / 2600 * D.TAU) : 1;
      for (let i = 0; i < 60; i++) {
        const r = fv.ring[i], c0 = s.before.cur[i], c1 = s.after.cur[i];
        let ta = 0;
        if (r) {
          ta = r.a * br * restK;
          if (fv.heat && r.volRed) ta *= 0.72 + 0.28 * (0.5 + 0.5 * Math.sin(t / (380 + (i * 97) % 260) + i * 1.9));
        }
        if (s.dt === 0 || Math.abs(ta - c0.a) < 1e-4) continue;
        const up = ta > c0.a;
        branch.add(`ring-${asleep ? (up ? 'asleep-400' : 'asleep-700') : up ? (ta >= 0.9 ? 'awake-10' : 'awake-55') : 'awake-140'}`);
        if (r) {
          const tc = r.warm ? out.warm : r.c.map(x => x / 255);
          const diff = Math.max(Math.abs(tc[0] - c0.r), Math.abs(tc[1] - c0.g), Math.abs(tc[2] - c0.b));
          if (diff > 0.02 && c1.a < 0.02) snap++;
          if (diff > 0.05 && c1.a >= 0.02 && c0.a >= 0.02) glide++;
        }
      }
      for (let j = 0; j < 4; j++) {
        const b = fv.buttons[j], c0 = s.before.bcur[j];
        let ta = b ? b.a * restK : 0;
        if (asleep) ta *= br;
        if (j === 0 && fv.pausedPlay) ta *= 0.55 + 0.45 * (0.5 + 0.5 * Math.cos(t / 2600 * D.TAU));
        if (s.dt === 0 || Math.abs(ta - c0.a) < 1e-4) continue;
        const up = ta > c0.a;
        branch.add(`button-${asleep ? (up ? 'asleep-400' : 'asleep-700') : up ? 'awake-40' : 'awake-160'}`);
      }
      // Continuous layers.
      if (fv.heat) { if (heatStart == null) heatStart = t; heatSpan = Math.max(heatSpan, t - heatStart); } else heatStart = null;
      if (fv.pending) { if (pendStart == null) pendStart = t; pendingSpan = Math.max(pendingSpan, t - pendStart); } else pendStart = null;
      if (asleep) { if (restStart == null) restStart = t; restSpan = Math.max(restSpan, t - restStart); } else restStart = null;
      if (off) { if (offStart == null) offStart = t; offSpan = Math.max(offSpan, t - offStart); } else offStart = null;
      if (fv.songProg != null) songBins.add(Math.floor(fv.songProg * 10));
      const last = tints[tints.length - 1], cur = fv.tint ? fv.tint.join(',') : 'none';
      if (last !== cur) tints.push(cur);
    }
    // Appearing (the smoothed tint starts at 0 in every case), gliding (two tint colours), disappearing (none after them).
    const colours = tints.filter(x => x !== 'none');
    if (new Set(colours).size >= 2 && tints.lastIndexOf('none') > tints.indexOf(colours[1])) tintCase = true;
  }
  const variants = ['boot-home', 'boot-nonhome', 'down', 'wake', 'tick-len0', 'tick-len7', 'bound', 'bloom', 'fail', 'sweep-next', 'sweep-prev',
    'fill', 'drain', 'shimmer', 'wash', 'reveal', 'press-0', 'press-1', 'press-2', 'press-3'];
  const all = [...samples.values()];
  for (const v of variants) {
    need(all.some(k => k.variant === v && k.n >= 8 && k.u0 && k.uHalf && k.u1 && k.past), `effect ${v} sampled >= 8 times with u ~0, ~0.5, ~1 and just past the end`);
  }
  for (const type of D.FG) need(all.some(k => k.type === type && k.fades >= 5 && k.killedOut), `kill of ${type}: fade sampled >= 5 times and removed at amp <= 0`);
  for (const b of ['ring-asleep-400', 'ring-asleep-700', 'ring-awake-10', 'ring-awake-55', 'ring-awake-140',
    'button-asleep-400', 'button-asleep-700', 'button-awake-40', 'button-awake-160']) need(branch.has(b), `damping branch ${b}`);
  need(snap > 0, 'colour snap below a 0.02');
  need(glide > 0, 'colour change at a lit segment');
  need(restSpan >= 5200, 'steady rest over more than the former 5200 ms breath period');
  need(offSpan >= 2600, 'offline breath over a full period');
  need(heatSpan > 1000, 'heat over more than 1 s');
  need(tintCase, 'tint appearing, gliding and disappearing');
  need(songBins.size >= 4, 'song progress at several values (the hand is not drawn at rest, user 2026-09-26)');
  need(pendingSpan >= 1400, 'Working comet over a lap');
  need(duckTwo > 0, 'duck with two FG effects');
  need(knee > 0 && knee2 > 0, 'tone map above the knee');
  need(results.some(r => r.out.designUncapped && r.out.steps.some(s => s.queue > MAX_QUEUE)), 'queue beyond capacity');
  need(results.some(r => !r.out.designUncapped && r.trace.some(s => s.before.fx.length === MAX_QUEUE)), 'queue exactly at capacity');
  // [user 2026-09-26] section 9 bytes on every step; the F-T floor lights target-lit LEDs that plain
  // rounding leaves dark (the resting and offline marks) and never an unlit one.
  let floored = 0, flooredUnlit = 0;
  for (const { out } of results) {
    let view = null;
    for (const s of out.steps) {
      if (s.view) view = s.view;
      need(Array.isArray(s.expect.bytes) && s.expect.bytes.length === 64, 'expect.bytes on every step');
      const plain = referenceOutput(s.expect.ring, s.expect.buttons, [], [], OUTPUT_DRIVE);
      for (let k = 0; k < 64; k++) {
        if (plain[k] === s.expect.bytes[k]) continue;
        floored++;
        if (!litOf(k < 60 ? view.ring[k] : view.buttons[k - 60]) || plain[k] !== 0) flooredUnlit++;
        if (s.expect.bytes[k] & 0xFEFEFE) flooredUnlit++;           // one count per channel at most
      }
    }
  }
  need(floored > 0, 'the F-T floor lights a target-lit LED that plain rounding leaves dark');
  need(flooredUnlit === 0, 'the F-T floor changes only dark target-lit LEDs, to at most one count per channel');
  if (problems.length) throw new Error('alive_oracle: coverage incomplete:\n  ' + [...new Set(problems)].join('\n  '));
  const perVariant = new Map();
  for (const k of all) perVariant.set(k.variant, (perVariant.get(k.variant) || 0) + k.n);
  return { variants: [...perVariant.entries()].map(([k, n]) => `${k}:${n}`).join(' '), branches: [...branch].sort().join(' '), snap, glide, songBins: songBins.size, floored };
}

// ---------------------------------------------------------------- run and write
const names = new Set();
for (const def of CASES) { if (names.has(def.name)) throw new Error('duplicate case ' + def.name); names.add(def.name); }
const results = CASES.map(runCase);
const cov = coverage(results);

const probe = new D.Component({ breathe: true, glow: 1, speed: 1 });
const header = {
  version: 1,
  tolerance: 0.002,
  about: 'Design oracle for the alive LED animator (ALIVE.md 11.1), generated by tests/js/alive_oracle.cjs from the logic block of ' +
    '"Ring Choreography v2.dc.html" (run unmodified except the capture patch and the user-ruling patch) with views from knob-model.js view(st, {led:"alive"}). ' +
    'Per case: fresh animator; per step: apply "view" when present (it replaces every persistent input), push "effects" in order with their ' +
    'own t0 and params used verbatim ("down" snapshots the animator state at push time), then step at t with dt; compare the tone-mapped ' +
    'e of the 60 segments and 4 buttons with "expect" (rounded to 1e-5) within "tolerance". View colours are design space 0..255; ' +
    'warm:true takes case.warm. "designConstants" are the literal effect colours and initial state of draw(); a port must use them in this test. ' +
    '[user 2026-09-26] expect.bytes: the section 9 output of the rounded expect e (64 x 0xRRGGBB, ring then buttons) under "output" ' +
    '(drive 150, dither off, the F-T floor on the LEDs whose persistent view entry is non-null with a > 0).',
  generator: 'tests/js/alive_oracle.cjs',
  design: 'design-reference/design_handoff_led_choreography/Ring Choreography v2.dc.html (logic block) + knob-model.js',
  colorsSource: 'tests/fixtures/dominant_reference.json',
  capturePatch: CAPTURE_PATCH.map(p => ({ loop: p.loop, anchor: p.anchor, inserted: p.insert.trim() })),
  rulingPatch: RULING_PATCH.map(p => ({ ruling: 'ALIVE.md 12.8 (user, 2026-09-26)', what: p.what, anchor: p.anchor, replaced: p.replace })),
  output: { drive: OUTPUT_DRIVE, dither: false, floor: 'F-T', floorChannels: 'dominant', powerBudget: OUTPUT_BUDGET,
    byteTolerance: 1,
    ruling: 'ALIVE.md 12.7 (user, 2026-09-26): dither off by default; F-T floor on target-lit LEDs, one count on the ' +
      'dominant channel (channel rule amended 2026-09-26)' },
  designConstants: {
    GRN: D.GRN.slice(), RED: D.RED.slice(), BLUE: D.BLUE.slice(), bloomSpark: D.mix(D.GRN, [1, 1, 1], 0.3),
    curInit: [probe.cur[0].r, probe.cur[0].g, probe.cur[0].b, probe.cur[0].a],
    bcurInit: [probe.bcur[0].r, probe.bcur[0].g, probe.bcur[0].b, probe.bcur[0].a],
    tintInit: probe.tint.slice(), DUR: Object.assign({}, D.DUR), FG: D.FG.slice(), MODEL_WARM, heatRed: DESIGN_RED, pausedPlayGreen: DESIGN_GREEN
  }
};

const NL = '\n';
const caseText = c => {
  const head = Object.assign({}, c);
  delete head.steps;
  const h = JSON.stringify(head);
  return h.slice(0, -1) + ',"steps":[' + NL + c.steps.map(s => JSON.stringify(s)).join(',' + NL) + NL + ']}';
};
const text = '{' + NL + Object.keys(header).map(k => JSON.stringify(k) + ': ' + JSON.stringify(header[k])).join(',' + NL) +
  ',' + NL + '"cases": [' + NL + results.map(r => caseText(r.out)).join(',' + NL) + NL + ']' + NL + '}' + NL;

const stepCount = results.reduce((n, r) => n + r.out.steps.length, 0);
process.stderr.write(`alive_oracle: ${results.length} cases, ${stepCount} steps, ${text.length} bytes\n`);
process.stderr.write(`alive_oracle: effect samples ${cov.variants}\n`);
process.stderr.write(`alive_oracle: damping ${cov.branches}; snap ${cov.snap}, glide ${cov.glide}, song bins ${cov.songBins}\n`);
process.stderr.write(`alive_oracle: section 9 bytes on every step (drive 150, dither off); F-T floor lit ${cov.floored} LED-step(s)\n`);
if (outPath) fs.writeFileSync(outPath, text, 'utf8'); else process.stdout.write(text);
