'use strict';
/*
 * Second design oracle for the "Warm · alive" LED animator: the r2.1 master's "Browse and Snap"
 * draw() (firmware/ALIVE.md revision 2, section 11.2, gate A2).
 *
 * Runs the logic block (<script type="text/x-dc" data-dc-script>) of
 * design-reference/design_handoff_nano_d_master_r2.1/prototypes/"Browse and Snap.dc.html" in a node
 * `vm` context with inert stubs: a DCLogic base class (props; setState shallow-merges into
 * this.state), React.createRef() -> {current: null}, window = {devicePixelRatio: 1},
 * requestAnimationFrame / cancelAnimationFrame no-ops, setTimeout / setInterval / performance.now /
 * document throwing (the oracle never mounts the component), a fixed Date (the case's hour, so
 * warmAt(h).b is the case's todB and Date.now() is 0) and a fake 2D canvas whose every method is a
 * no-op (roundRect, fillRect, arc, ...). The block is evaluated UNMODIFIED except for ONE mechanical
 * capture patch (CAPTURE_PATCH): a call recording the tone-mapped `e` inserted right after `e` is
 * computed in the two compose loops (the ring loop, BS:673-681, and the button loop, BS:683-694).
 * Each anchor must occur exactly once or this script throws. [user 2026-09-26] Besides it, RULING_PATCH
 * applies the user's LED ruling (ALIVE.md 12.8) to draw(): HOT == WARM, every resting level 0.34 (buttons
 * 0.34 / 0.26), a steady rest floored at todB 0.80 and no song hand at rest. Nothing else of the design changes.
 *
 * Targets are the design's own: every scripted view is a state patch applied to this.state (over
 * fresh()), then renderVals() (BS:1118-1333) sets this._ring / this._btns / this._cursor /
 * this._working exactly as the prototype does (BS's constant arrays, so r.c === RED and isW()
 * work); this.asleep is the step's asleep. Effects are pushed with the design's own play(type,
 * params) (BS:578-586) at this.vt = the effect's t0, with explicit params (at, dir, len, c, side,
 * seed; fill/drain n comes from state.vol as play() does), then this.vt = t and draw(t, dt).
 *
 * The fixture view per step carries what draw() reads, each computed with draw()'s own expressions
 * (BS:599-637): per lit segment {c, warm, volRed, a} with a = the target alpha before the breath
 * (asleep: the resting level of BS:609 as patched by RULING_PATCH, else r.a) and warm = asleep || isW(r.c);
 * buttons the same with BS:620's resting rule (patched); asleep = this.asleep && !off; offline = off && !native (the
 * offline breath, BS:612); pending = this._working; heat (BS:602), pausedPlay (BS:617), tint
 * (BS:634), songProg (BS:638) and rm (reduced motion: play()'s drop list, fail's stationary pos).
 *
 * Not compared against BS (ALIVE.md 11.2), tagged in "notTested": down (M19: RC's recipe is the
 * spec), boot / pending / shimmer (not in BS), BS's colour damping of an unlit button (BS:624-625:
 * the port damps lit targets only; a none-tone button is null here and no case lights one before
 * it goes dark), the bound colour fallback (BS:648 `e.c || WM`: the port always passes a colour),
 * the S resting level (D10; a targets-level difference, the golden's).
 *
 * Output: tests/fixtures/alive_oracle_bs.json, the RC oracle's format (tests/js/alive_oracle.cjs)
 * plus: designConstants WARM/HOT/GREEN/RED/AMBER/PINK (0..1, the port's palette for this test),
 * RED/AMBER/PINK/WARM8 as BS's 0..255 arrays, rmDrop (play()'s reduced-motion list); views carry
 * "rm"; effects carry "side" (-1 left / +1 right) and "seed"; an effect play() dropped under
 * reduced motion is recorded with "dropped": true (the ports must drop it too). Expect values are
 * rounded to 1e-5. No case exceeds the 8-effect cap (BS has no cap; the port's is D12).
 * [user 2026-09-26] Every step also carries expect.bytes, as in alive_oracle.cjs: the section 9
 * output of the rounded e at drive 150, dither off, with the F-T floor on the LEDs whose target is
 * lit in the step's persistent view (referenceOutput(), identical in both oracles).
 *
 * Usage: node alive_oracle_bs.cjs <prototypes dir> [out.json]
 * Output is deterministic (no clock, no randomness: every scatter seed is explicit); a coverage
 * self-check runs before anything is written and throws if ALIVE.md 11.2's list is incomplete.
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const [designDir, outPath] = process.argv.slice(2);
if (!designDir) {
  process.stderr.write('usage: node alive_oracle_bs.cjs <prototypes dir> [out.json]\n');
  process.exit(2);
}
const HTML_PATH = path.join(designDir, 'Browse and Snap.dc.html');
const noop = () => {};
const inert = name => () => { throw new Error(`alive_oracle_bs: ${name} is not available (the oracle drives renderVals()/play()/draw() only)`); };

function replaceOnce(source, anchor, replacement, what) {
  const count = source.split(anchor).length - 1;
  if (count !== 1) throw new Error(`alive_oracle_bs: ${what} anchor found ${count} time(s), expected exactly once: ${anchor}`);
  const at = source.indexOf(anchor);
  return source.slice(0, at) + replacement + source.slice(at + anchor.length);
}

// ---------------------------------------------------------------- the design's logic class
const html = fs.readFileSync(HTML_PATH, 'utf8');
const opens = [...html.matchAll(/<script type="text\/x-dc"[^>]*>/g)];
if (opens.length !== 1) throw new Error(`alive_oracle_bs: expected one <script type="text/x-dc"> block, found ${opens.length}`);
const logicStart = opens[0].index + opens[0][0].length;
const logicEnd = html.indexOf('</script>', logicStart);
if (logicEnd < 0) throw new Error('alive_oracle_bs: logic block is not closed');
const logicSource = html.slice(logicStart, logicEnd);
const logicLine = html.slice(0, logicStart).split('\n').length;

// The ONE source patch: record the tone-mapped e of each ring segment / button.
const CAPTURE_PATCH = [
  { loop: 'ring', anchor: 'x.save(); x.rotate(i * 6 * Math.PI / 180);', insert: '__aliveCapture(0, i, e); ' },
  { loop: 'buttons', anchor: 'const bx = 61 + j * 70, by = 398 + (this.state.press === j ? 2 : 0);', insert: '__aliveCapture(1, j, e); ' }
];
let patched = logicSource;
for (const p of CAPTURE_PATCH) patched = replaceOnce(patched, p.anchor, p.insert + p.anchor, `${p.loop} compose loop`);
// [user 2026-09-26] The user's LED ruling (ALIVE.md 12.8), the only behavioural patch: literal anchors in
// draw(), each exactly once. HOT == WARM (scatter sparks, the Working comet and the song hand in the same warm
// white); resting is one steady dim warm white: every lit segment rests at 0.34 (alphaResting), buttons at 0.34
// (awake >= 0.5) / 0.26 (buttonRestHigh / Low), no rest breath and time of day never below 0.80 (restTodMin);
// no song-progress hand at rest (BS draws it only at rest, so it is never drawn). fixtureView() below reads
// the same levels.
const REST_RING = 0.34, REST_BUTTON_HIGH = 0.34, REST_BUTTON_LOW = 0.26, REST_TOD_MIN = 0.80;
const RULING_PATCH = [
  { what: 'HOT == WARM', anchor: 'HOT = mix3(WM, [1, 1, 1], 0.5);', replace: 'HOT = WM;' },
  { what: 'steady rest, time-of-day floor', anchor: 'const br = asleep ? (1 + 0.4 * Math.sin(t / 5200 * TAU)) * tod.b : 1;',
    replace: `const br = asleep ? Math.max(tod.b, ${REST_TOD_MIN.toFixed(2)}) : 1;` },
  { what: 'ring resting level', anchor: 'ta = asleep ? (r.a >= 0.99 ? 0.16 : r.a >= 0.5 ? 0.1 : 0.05) * br : r.a;',
    replace: `ta = asleep ? ${REST_RING} * br : r.a;` },
  { what: 'button resting levels', anchor: 'let ta = asleep ? (b.a >= 0.5 ? 0.12 : 0.04) * br : b.a;',
    replace: `let ta = asleep ? (b.a >= 0.5 ? ${REST_BUTTON_HIGH} : ${REST_BUTTON_LOW}) * br : b.a;` },
  { what: 'no song hand at rest', anchor: "if (asleep && s.playing && s.mode === 'home') addG(",
    replace: "if (false && asleep && s.playing && s.mode === 'home') addG(" }
];
for (const p of RULING_PATCH) patched = replaceOnce(patched, p.anchor, p.replace, `ruling (${p.what})`);

let sink = null;
const clock = { hour: 12, minute: 0 };
class FixedDate {
  getHours() { return clock.hour; }
  getMinutes() { return clock.minute; }
  static now() { return 0; }
}
const sandbox = {
  window: { devicePixelRatio: 1 },
  document: new Proxy({}, { get: (t, k) => { throw new Error('alive_oracle_bs: document.' + String(k) + ' is not available'); } }),
  React: { createRef: () => ({ current: null }) },
  requestAnimationFrame: () => 0,
  cancelAnimationFrame: noop,
  setTimeout: inert('setTimeout'),
  clearTimeout: inert('clearTimeout'),
  setInterval: inert('setInterval'),
  clearInterval: inert('clearInterval'),
  performance: { now: inert('performance.now') },
  ResizeObserver: class { constructor() { throw new Error('alive_oracle_bs: ResizeObserver'); } },
  Date: FixedDate,
  __aliveCapture: (kind, index, e) => {
    if (!sink) throw new Error('alive_oracle_bs: capture outside draw()');
    sink[kind][index] = [e[0], e[1], e[2]];
  }
};
const designContext = vm.createContext(sandbox);
vm.runInContext(
  'class DCLogic { constructor(props) { this.props = props; } setState(patch) { this.state = Object.assign({}, this.state, typeof patch === "function" ? patch(this.state) : patch); } forceUpdate() {} }',
  designContext, { filename: 'alive_oracle_bs-stubs.js' });
vm.runInContext(patched, designContext, { filename: 'Browse and Snap.dc.html', lineOffset: logicLine - 1 });
const D = vm.runInContext('({ Component, warmAt, mix3, cl, cd, md, TAU, DUR, FG, WARM, GREEN, AMBER, RED, PINK, isW })', designContext);

function fakeCanvas() {
  const store = Object.create(null);
  const context2d = new Proxy(store, {
    get: (target, key) => (key in target ? target[key] : noop),
    set: (target, key, value) => { target[key] = value; return true; }
  });
  return { width: 0, height: 0, getContext: () => context2d };
}

const ints = c => {
  if (!Array.isArray(c) || c.length !== 3 || c.some(x => !Number.isInteger(x) || x < 0 || x > 255)) throw new Error('bad colour ' + JSON.stringify(c));
  return c.slice();
};
const FAMILY = { home: 'home', recent: 'recent', explore: 'explorer', tracks: 'tracks', queue: 'upnext', windows: 'windows' };

// The fixture view at time t: draw()'s own expressions on the instance (BS:599-638).
function fixtureView(inst, t) {
  const s = inst.state, off = s.sim.pc === 'off', asleep = inst.asleep && !off;
  const ring = inst._ring.map(r => (r && r.a ? {
    c: ints(r.c), warm: asleep || D.isW(r.c), volRed: r.c === D.RED,
    a: asleep ? REST_RING : r.a                     // [user 2026-09-26] (RULING_PATCH)
  } : null));
  const buttons = inst._btns.map((b, j) => {
    if (!b) throw new Error('renderVals gave no button ' + j);
    if (!b.a) {
      if (asleep) throw new Error('a none-tone button while asleep glows at the low resting level in BS; no case may have one');
      return null;                                   // notTested: BS damps an unlit button's colour
    }
    return { c: ints(b.c), warm: asleep || D.isW(b.c), a: asleep ? (b.a >= 0.5 ? REST_BUTTON_HIGH : REST_BUTTON_LOW) : b.a };
  });
  const listMode = ['recent', 'explore', 'queue', 'windows'].includes(s.mode);
  const cr = inst._ring[inst._cursor];
  const tint = listMode && !asleep && cr && !D.isW(cr.c) ? cr.c.map(x => x / 255) : null;
  return {
    ring, buttons, asleep, offline: off && !s.native, pending: !!inst._working,
    family: off ? 'offline' : FAMILY[s.mode], cursor: inst._cursor, vol: s.vol, playing: s.playing,
    heat: s.mode === 'home' && !asleep && s.vol >= 90,
    pausedPlay: s.mode === 'home' && !s.playing && !asleep,
    tint, songProg: asleep && s.playing && s.mode === 'home' ? ((t / 1000 + 50) % 214) / 214 : null,
    rm: !!s.rm
  };
}

// ---------------------------------------------------------------- views
const probe = new D.Component({});
const FRESH = probe.fresh();
const WINS = probe.W;
function view(patch, extra) {
  const p = patch || {};
  const st = Object.assign({}, FRESH, p, { sim: Object.assign({}, FRESH.sim, p.sim || {}) });
  return Object.assign({ st, asleep: false }, extra || {});
}
const ASLEEP = { asleep: true };
const HOME = view({ mode: 'home', vol: 54 });
const HOME_PAUSED = view({ mode: 'home', vol: 54, playing: false });
const HOME81 = view({ mode: 'home', vol: 81 });
const HOME95 = view({ mode: 'home', vol: 95 });
const RECENT = rIdx => view({ mode: 'recent', rIdx });
const EXPLORE = (src, idx, extra) => view(Object.assign({ mode: 'explore', src, xOpen: true, xIdx: { recent: src === 'recent' ? idx : 0, playlists: src === 'playlists' ? idx : 0 } }, extra || {}));
const QUEUE = (qSel, extra) => view(Object.assign({ mode: 'queue', qOpen: true, qSel }, extra || {}));
const WINDOWS = (sel, extra) => view(Object.assign({ mode: 'windows', wOpen: true, sel }, extra || {}));
const TRACKS = tPos => view({ mode: 'tracks', tPos });
const SEEK = (pos, extra) => view(Object.assign({ mode: 'tracks', seek: true, pos }, extra || {}));
const OFFLINE = view({ sim: { pc: 'off' } });
const rm = v => Object.assign({}, v, { st: Object.assign({}, v.st, { rm: true }) });
const asleep = v => Object.assign({}, v, ASLEEP);

// ---------------------------------------------------------------- cases
const CASES = [];
const C = def => CASES.push(def);
const W_CLAUDE = WINS[1].c, W_SLACK = WINS[2].c;

// half-wash: left and right, sampled at 0, 10, 30, 270, 290, 300 and through the fade; killed.
C({ name: 'half-left', hour: 20, note: 'Windows: snap left (Claude): the half grows from 45 over 31..59, holds, fades 380..900; Button 2 tint without amp.',
  end: 300 + 900 + 30, coarse: [[0, 300, [50]]], hits: [300, 310, 330, 570, 590, 600, 680, 750, 800, 900, 1000, 1100, 1200],
  events: [[0, { view: WINDOWS(1) }], [300, { fx: [['half', { side: 'left', c: W_CLAUDE }]] }]] });
C({ name: 'half-right', hour: 13, note: 'Windows: snap right (Slack colour): segments 1..29 from 15, Button 3 tint.',
  end: 300 + 900 + 30, coarse: [[0, 300, [50]]], hits: [300, 310, 330, 570, 590, 600, 680, 750, 800, 900, 1000, 1100, 1200],
  events: [[0, { view: WINDOWS(2) }], [300, { fx: [['half', { side: 'right', c: W_SLACK }]] }]] });
C({ name: 'half-kill-growing', hour: 20, note: 'A half killed at 120 ms (still growing) by a green bloom: the ring part fades over 120 ms, the button tint stays (no amp) until the kill fade ends.',
  end: 420 + 900 + 30, coarse: [[0, 300, [50]]],
  events: [[0, { view: WINDOWS(1) }], [300, { fx: [['half', { side: 'left', c: W_CLAUDE }]] }], [420, { fx: [['bloom', {}]] }]] });
C({ name: 'half-kill-fading', hour: 8, note: 'A right half killed at 600 ms (fading) by a wash.',
  end: 900 + 1100 + 30, coarse: [[0, 300, [50]]],
  events: [[0, { view: WINDOWS(3) }], [300, { fx: [['half', { side: 'right', c: WINS[5].c }]] }], [900, { fx: [['wash', { c: WINS[5].c }]] }]] });

// bloom: green (BS default) and pink (Like), with their sparks.
C({ name: 'bloom-green', hour: 20, note: 'Home 54 %: green bloom (e.c absent: [0,255,98]) and its white-mixed spark at +30.',
  end: 300 + 900 + 30, coarse: [[0, 300, [50]]],
  events: [[0, { view: HOME }], [300, { fx: [['bloom', {}]] }]] });
C({ name: 'bloom-pink', hour: 22.5, note: 'Up next: Like -> bloom in PINK [255,40,90] from the cursor; spark mix(PINK, white, 0.3).',
  end: 300 + 900 + 30, coarse: [[0, 300, [50]]],
  events: [[0, { view: QUEUE(4) }], [300, { fx: [['bloom', { c: D.PINK }]] }]] });

// scatter at the contract's seeds, and killed.
for (const [k, seed] of [0.37, 13.21, 29.9, 47.53, 59.99].entries()) {
  C({ name: `scatter-${String(seed).replace('.', '_')}`, hour: [20, 13, 3.25, 8, 17.5][k], note: `Up next shuffle: nine HOT sparks spread by ORD from seed ${seed}, 55 ms apart, 260 ms each.`,
    end: 300 + 700 + 30, coarse: [[0, 300, [50]]],
    events: [[0, { view: QUEUE(5 + k) }], [300, { fx: [['scatter', { seed }]] }]] });
}
C({ name: 'scatter-kill', hour: 20, note: 'A scatter killed at 330 ms by a pink bloom (Like right after Shuffle).',
  end: 630 + 900 + 30, coarse: [[0, 300, [50]]],
  events: [[0, { view: QUEUE(3) }], [300, { fx: [['scatter', { seed: 29.9 }]] }], [630, { fx: [['bloom', { c: D.PINK }]] }]] });

// sweep from 0 (Play next done), fail with rm off and on.
C({ name: 'sweep-queued', hour: 20, note: 'Recently Added: Play next done -> one clockwise lap from 12 o\'clock (at 0, dir +1).',
  end: 300 + 640 + 30, coarse: [[0, 300, [50]]],
  events: [[0, { view: RECENT(6) }], [300, { fx: [['sweep', { dir: 1, at: 0 }]] }]] });
C({ name: 'fail-motion', hour: 20, note: 'Windows snap failed: the Head shake (1.6 segments at 3.2 Hz) and the base dim.',
  end: 300 + 700 + 30, coarse: [[0, 300, [50]]],
  events: [[0, { view: WINDOWS(2) }], [300, { fx: [['fail', {}]] }]] });
C({ name: 'fail-reduced', hour: 20, note: 'The same with reduced motion: fail is stationary (pos = at).',
  end: 300 + 700 + 30, coarse: [[0, 300, [50]]],
  events: [[0, { view: rm(WINDOWS(2)) }], [300, { fx: [['fail', {}]] }]] });

// tint in explore and queue (families explorer, upnext); list landmarks.
C({ name: 'tint-explore', hour: 20, note: 'Music explorer, Recently Added tab: tint glides in, follows the cursor, then the Favourite playlists tab.',
  end: 2200, pattern: [33, 17],
  events: [[0, { view: EXPLORE('recent', 1) }], [500, { view: EXPLORE('recent', 2) }], [1000, { view: EXPLORE('playlists', 0) }], [1600, { view: HOME }]] });
C({ name: 'tint-queue', hour: 13, note: 'Up next (foreign queue, mixed albums): played 0.14 / now 0.70 / upcoming 0.45 landmarks; the tint follows the focus.',
  end: 2000, pattern: [33, 17],
  events: [[0, { view: QUEUE(4, { sim: { upnext: 'foreign' } }) }], [600, { view: QUEUE(7, { sim: { upnext: 'foreign' } }) }], [1200, { view: QUEUE(2, { sim: { upnext: 'foreign' } }) }]] });

// resting levels: ring 0.14, 0.45, 0.62, 0.70, 1.0; buttons 0.14, 0.30, 0.70, 1.0 ([user 2026-09-26] all rest at 0.34 / 0.26).
C({ name: 'rest-queue', hour: 23, note: 'Up next resting at night: every level (0.14 / 0.45 / 0.70 / 1.0) rests at 0.34 in warm; buttons 0.70 / 0.30 / 0.70 / 1.0 rest at 0.34 / 0.26 / 0.34 / 0.34 (user 2026-09-26).',
  end: 400 + 5400, pattern: [50], coarse: [[0, 400, [50]]],
  events: [[0, { view: QUEUE(4) }], [400, { view: asleep(QUEUE(4)) }]] });
C({ name: 'rest-home', hour: 21, note: 'Home 81 % playing falls asleep: body 0.62, bounds 0.30, half-step 0.81 endpoint 1.0, all resting at 0.34; no song hand at rest (user 2026-09-26).',
  end: 400 + 5400, pattern: [50], coarse: [[0, 400, [50]]],
  events: [[0, { view: HOME81 }], [400, { view: asleep(HOME81) }]] });
C({ name: 'rest-explore-buttons', hour: 6, note: 'Explorer at rest: the on tab 1.0 -> 0.34, the off tab 0.30 -> 0.26 (user 2026-09-26); wake again.',
  end: 5200, pattern: [50],
  events: [[0, { view: EXPLORE('recent', 3) }], [300, { view: asleep(EXPLORE('recent', 3)) }], [4200, { view: EXPLORE('recent', 3), fx: [['wake', {}]] }]] });
C({ name: 'rest-dim-button', hour: 12, note: 'Up next while the queue is loading: dim buttons (0.14) rest at 0.26 (user 2026-09-26); the Working comet.',
  end: 3000, pattern: [50],
  events: [[0, { view: QUEUE(4, { sim: { upnext: 'loading' } }) }], [600, { view: asleep(QUEUE(4, { sim: { upnext: 'loading' } })) }]] });

// paused-Play breath, offline breath, heat, the seek lap with the comet.
C({ name: 'paused-play', hour: 20, note: 'Home paused: Button 1 green breathes on 2.6 s (awake).',
  end: 3000, pattern: [50, 33, 17], events: [[0, { view: HOME_PAUSED }]] });
C({ name: 'offline-breath', hour: 20, note: 'PC not connected: 12 amber marks at 0.12 breathing on 2.6 s.',
  end: 3000, pattern: [50, 50, 33, 17], events: [[0, { view: OFFLINE }]] });
C({ name: 'heat-home95', hour: 13, note: 'Home 95 %: red segments 45.. glow with the ember cycles.',
  end: 1300, pattern: [33, 17], events: [[0, { view: HOME95 }]] });
C({ name: 'seek-lap-jumping', hour: 20, note: 'Seek at 1:14 of the track: played 0.62, ticks 0.30, head 1.0; Jumping... runs the Working comet.',
  end: 2000, pattern: [33, 17],
  events: [[0, { view: SEEK(74) }], [300, { view: SEEK(74, { seekState: 'jump' }) }], [1500, { view: SEEK(74) }]] });

// queue at capacity with half and scatter (8 effects, no eviction).
C({ name: 'queue-capacity-half-scatter', hour: 20, note: 'Windows: a half, a scatter, 3 presses, a tick, a bound and a reveal within 70 ms: exactly 8 queued.',
  end: 370 + 900 + 30, coarse: [[0, 300, [50]]],
  events: [[0, { view: WINDOWS(1) }], [300, { fx: [['half', { side: 'right', c: W_CLAUDE }]] }], [310, { fx: [['press', { n: 1 }]] }],
    [320, { fx: [['scatter', { seed: 13.21 }]] }], [330, { fx: [['press', { n: 2 }]] }], [340, { fx: [['tick', { dir: 1, len: 3 }]] }],
    [350, { fx: [['press', { n: 3 }]] }], [360, { fx: [['bound', { dir: 1, c: [W_CLAUDE[0] / 255, W_CLAUDE[1] / 255, W_CLAUDE[2] / 255] }]] }],
    [370, { fx: [['reveal', {}]] }]] });

// wash (BS copy) for parity; the RC recipes BS keeps.
C({ name: 'wash-switch', hour: 20, note: 'Windows Switch to Claude: wash in its colour from the cursor, Button 4 tint.',
  end: 300 + 1100 + 30, coarse: [[0, 300, [50]]],
  events: [[0, { view: WINDOWS(1) }], [300, { view: HOME, fx: [['wash', { c: W_CLAUDE, at: 51 }], ['reveal', {}]] }]] });
C({ name: 'rc-recipes', hour: 13, note: 'The recipes BS keeps from RC: tick (len 5), bound, press, fill and drain on Home.',
  end: 1800, coarse: [[0, 200, [50]]],
  events: [[0, { view: HOME }], [200, { fx: [['tick', { dir: 1, len: 5 }], ['press', { n: 0 }]] }], [320, { fx: [['bound', { dir: -1, c: [1, 190 / 255, 105 / 255] }]] }],
    [500, { view: HOME_PAUSED, fx: [['drain', {}]] }], [1000, { view: HOME, fx: [['fill', {}]] }]] });

// reduced motion: wake, tick, sweep, scatter and reveal are dropped; colour moments stay.
C({ name: 'reduced-motion-drops', hour: 20, note: 'Reduced motion: wake, tick, sweep, scatter and reveal never queue (and kill nothing); the half, the pink bloom and the stationary fail stay.',
  end: 1400, coarse: [[0, 300, [50]]],
  events: [[0, { view: rm(QUEUE(4)) }], [300, { fx: [['half', { side: 'left', c: W_SLACK }], ['wake', {}], ['tick', { dir: 1, len: 2 }], ['sweep', { dir: 1, at: 0 }], ['scatter', { seed: 47.53 }], ['reveal', {}]] }],
    [500, { fx: [['bloom', { c: D.PINK }]] }], [700, { fx: [['fail', {}]] }]] });

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
const DEFAULT_PATTERN = [16, 17, 17];
const r5 = x => Math.round(x * 1e5) / 1e5;

function timeline(def) {
  const t0 = def.t0 || 0, end = def.end;
  const must = new Set([t0, end].concat(def.hits || []));
  for (const [T, ev] of def.events) {
    must.add(T);
    for (const f of ev.fx || []) {
      const dur = D.DUR[f[0]];
      for (const x of [Math.round(dur / 2), dur, dur + 1]) must.add(T + x);
      if (D.FG.includes(f[0])) for (const x of [60, 120]) must.add(T + x);
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

function effectRecord(e, type, t0) {
  const rec = { type, t0, at: e.at };
  if (!Number.isFinite(e.at)) throw new Error('effect at ' + e.at);
  if (type === 'tick') { rec.dir = e.dir; rec.len = e.len; }
  if (type === 'bound') { rec.dir = e.dir; rec.c = e.c.slice(); }
  if (type === 'sweep') rec.dir = e.dir;
  if (type === 'fill' || type === 'drain' || type === 'press') rec.n = e.n;
  if (type === 'wash' || type === 'half') rec.c = e.c.map(x => x / 255);
  if (type === 'bloom') rec.c = (e.c || [0, 255, 98]).map(x => x / 255);
  if (type === 'half') rec.side = e.side === 'left' ? -1 : 1;
  if (type === 'scatter') rec.seed = e.seed;
  return rec;
}

function runCase(def) {
  const hour = def.hour, tod = D.warmAt(hour);
  clock.hour = Math.floor(hour);
  clock.minute = Math.round((hour - clock.hour) * 60);
  const inst = new D.Component({});
  inst.cvRef.current = fakeCanvas();
  inst.timers = [];
  const events = new Map();
  for (const [T, ev] of def.events) {
    if (events.has(T)) throw new Error(`${def.name}: two events at ${T}`);
    events.set(T, ev);
  }
  const times = timeline(def);
  for (const T of events.keys()) if (!times.includes(T)) throw new Error(`${def.name}: event at ${T} outside the timeline`);
  const steps = [], trace = [];
  let lastView = null, prevT = null, have = false;
  for (const t of times) {
    const dt = prevT == null ? 0 : t - prevT;
    if (!Number.isInteger(dt) || dt < 0 || dt > 50) throw new Error(`${def.name}: dt ${dt} at ${t}`);
    const ev = events.get(t) || {};
    if (ev.view) {
      inst.state = Object.assign({}, ev.view.st);
      inst.asleep = !!ev.view.asleep;
      inst.renderVals();
      have = true;
    }
    if (!have) throw new Error(`${def.name}: no view at the first step`);
    const step = { t, dt };
    const fv = fixtureView(inst, t), fvJson = JSON.stringify(fv);
    if (fvJson !== lastView) { step.view = fv; lastView = fvJson; }
    step.effects = [];
    for (const f of ev.fx || []) {
      const [type, params] = f;
      const count = inst.fx.length;
      inst.vt = t;
      inst.play(type, Object.assign({}, params));
      const e = inst.fx[inst.fx.length - 1];
      if (inst.fx.length === count || !e || e.type !== type || e.t0 !== t) {
        if (!inst.state.rm) throw new Error(`${def.name}: play(${type}) pushed nothing without reduced motion`);
        const at = params.at != null ? params.at : inst._cursor;
        step.effects.push({ type, t0: t, at, dropped: true });
        continue;
      }
      step.effects.push(effectRecord(e, type, t));
    }
    if (inst.fx.length > 8) throw new Error(`${def.name}: ${inst.fx.length} effects queued at ${t} (the port caps at 8)`);
    const before = inst.fx.slice();
    inst.vt = t;
    sink = [new Array(60), new Array(4)];
    inst.draw(t, dt);
    const captured = sink;
    sink = null;
    for (let i = 0; i < 60; i++) if (!captured[0][i]) throw new Error(`${def.name}: ring ${i} not captured at ${t}`);
    for (let j = 0; j < 4; j++) if (!captured[1][j]) throw new Error(`${def.name}: button ${j} not captured at ${t}`);
    step.expect = { ring: captured[0].map(e => e.map(r5)), buttons: captured[1].map(e => e.map(r5)) };
    step.expect.bytes = referenceOutput(step.expect.ring, step.expect.buttons, fv.ring.map(litOf), fv.buttons.map(litOf),
      OUTPUT_DRIVE);
    steps.push(step);
    trace.push({ t, fv: JSON.parse(lastView), before, after: inst.fx.slice() });
    prevT = t;
  }
  return { out: { name: def.name, note: def.note, hour, todB: tod.b, steps }, trace };
}

// ---------------------------------------------------------------- coverage self-check (ALIVE.md 11.2)
function coverage(results) {
  const problems = [];
  const need = (ok, what) => { if (!ok) problems.push(what); };
  const halfMs = { '-1': new Set(), '1': new Set() };
  let halfKilledGrowing = false, halfKilledFading = false, halfButtonAfterKill = false;
  const blooms = new Set(), seeds = new Set();
  let scatterKilled = false, sweepFromZero = false, failRm = new Set(), capacity = false, wash = false, drops = new Set();
  const tintFamilies = new Set(), ringRest = new Set(), buttonRest = new Set();
  let paused = 0, offline = 0;
  for (const { out, trace } of results) {
    for (const s of trace) {
      const fv = s.fv, t = s.t;
      for (const e of s.before) {
        const ms = t - e.t0;
        if (e.type === 'half') {
          const side = e.side === 'left' ? '-1' : '1';
          if (e.kill == null) halfMs[side].add(ms);
          else if (t > e.kill) {
            if (e.kill - e.t0 < 270) halfKilledGrowing = true; else if (e.kill - e.t0 > 380) halfKilledFading = true;
            if (t - e.kill >= 60) halfButtonAfterKill = true;
          }
        }
        if (e.type === 'bloom' && ms > 560 && ms < 900) blooms.add(JSON.stringify(e.c || null));
        if (e.type === 'scatter') { seeds.add(e.seed); if (e.kill != null && t > e.kill) scatterKilled = true; }
        if (e.type === 'sweep' && e.at === 0 && e.dir === 1) sweepFromZero = true;
        if (e.type === 'fail' && ms > 50 && ms < 600) failRm.add(!!fv.rm);
        if (e.type === 'wash') wash = true;
      }
      if (s.before.length === 8 && s.before.some(e => e.type === 'half') && s.before.some(e => e.type === 'scatter')) capacity = true;
      if (fv.tint) tintFamilies.add(fv.family);
      if (fv.asleep) {
        for (const r of fv.ring) if (r) ringRest.add(r.a);
        for (const b of fv.buttons) if (b) buttonRest.add(b.a);
      }
      if (fv.pausedPlay) paused++;
      if (fv.offline) offline++;
    }
    for (const step of out.steps) for (const e of step.effects) if (e.dropped) drops.add(e.type);
  }
  for (const side of ['-1', '1']) for (const ms of [0, 10, 30, 270, 290, 300, 380, 500, 600, 700, 800, 900])
    need(halfMs[side].has(ms), `half side ${side} sampled at ${ms} ms`);
  need(halfKilledGrowing && halfKilledFading, 'half killed while growing and while fading');
  need(halfButtonAfterKill, 'the half button tint (no amp) sampled after its kill');
  need(blooms.has('null') && blooms.has(JSON.stringify(D.PINK)), 'bloom GREEN (default) and PINK with their sparks');
  for (const seed of [0.37, 13.21, 29.9, 47.53, 59.99]) need(seeds.has(seed), 'scatter seed ' + seed);
  need(scatterKilled, 'scatter killed');
  need(sweepFromZero, 'sweep at 0 with dir +1');
  need(failRm.has(true) && failRm.has(false), 'fail with rm false and true');
  need(tintFamilies.has('explorer') && tintFamilies.has('upnext'), 'tint in explore and queue');
  for (const a of [REST_RING]) need(ringRest.has(a), 'ring resting level ' + a);          // [user 2026-09-26]
  for (const a of [REST_BUTTON_HIGH, REST_BUTTON_LOW]) need(buttonRest.has(a), 'button resting level ' + a);
  need(paused > 50, 'the paused-Play breath');
  need(offline > 50, 'the offline breath');
  need(capacity, 'the queue at capacity with half and scatter');
  need(wash, 'wash');
  for (const type of ['wake', 'tick', 'sweep', 'scatter', 'reveal']) need(drops.has(type), `reduced motion drops ${type}`);
  // [user 2026-09-26] section 9 bytes on every step; the F-T floor changes only dark target-lit LEDs.
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
  if (problems.length) throw new Error('alive_oracle_bs: coverage incomplete:\n  ' + [...new Set(problems)].join('\n  '));
  return { seeds: [...seeds].sort((a, b) => a - b).join(' '), tint: [...tintFamilies].sort().join(' '), floored };
}

const names = new Set();
for (const def of CASES) { if (names.has(def.name)) throw new Error('duplicate case ' + def.name); names.add(def.name); }
// The awake alphas renderVals() produces for the rings and buttons the cases reach.
const results = CASES.map(runCase);
const cov = coverage(results);

const WM = D.warmAt(12).c;
const header = {
  version: 1,
  tolerance: 0.002,
  about: 'Second design oracle for the alive LED animator (ALIVE.md revision 2, 11.2), generated by tests/js/alive_oracle_bs.cjs from the logic ' +
    'block of the r2.1 "Browse and Snap.dc.html" (run unmodified except the capture patch and the user-ruling patch); targets from its own renderVals(). Per case: fresh ' +
    'animator; per step: apply "view" when present (it replaces every persistent input, including rm), push "effects" in order with their own ' +
    't0 and params ("dropped": the port must drop it under reduced motion), then step at t with dt; compare the tone-mapped e of the 60 ' +
    'segments and 4 buttons with "expect" (rounded to 1e-5) within "tolerance". View colours are design space 0..255; warm:true takes ' +
    'designConstants.WARM. The palette of this test is designConstants WARM/HOT/GREEN/RED/AMBER/PINK. ' +
    '[user 2026-09-26] expect.bytes: the section 9 output of the rounded expect e (64 x 0xRRGGBB, ring then buttons) under "output" ' +
    '(drive 150, dither off, the F-T floor on the LEDs whose persistent view entry is non-null with a > 0).',
  generator: 'tests/js/alive_oracle_bs.cjs',
  design: 'design-reference/design_handoff_nano_d_master_r2.1/prototypes/Browse and Snap.dc.html (logic block)',
  capturePatch: CAPTURE_PATCH.map(p => ({ loop: p.loop, anchor: p.anchor, inserted: p.insert.trim() })),
  rulingPatch: RULING_PATCH.map(p => ({ ruling: 'ALIVE.md 12.8 (user, 2026-09-26)', what: p.what, anchor: p.anchor, replaced: p.replace })),
  output: { drive: OUTPUT_DRIVE, dither: false, floor: 'F-T', floorChannels: 'dominant', powerBudget: OUTPUT_BUDGET,
    byteTolerance: 1,
    ruling: 'ALIVE.md 12.7 (user, 2026-09-26): dither off by default; F-T floor on target-lit LEDs, one count on the ' +
      'dominant channel (channel rule amended 2026-09-26)' },
  designConstants: {
    WARM: WM.slice(), HOT: WM.slice(), GREEN: D.GREEN.map(x => x / 255), RED: D.RED.map(x => x / 255),
    AMBER: D.AMBER.map(x => x / 255), PINK: D.PINK.map(x => x / 255),
    WARM8: D.WARM.slice(), GREEN8: D.GREEN.slice(), RED8: D.RED.slice(), AMBER8: D.AMBER.slice(), PINK8: D.PINK.slice(),
    curInit: [probe.cur[0].r, probe.cur[0].g, probe.cur[0].b, probe.cur[0].a],
    bcurInit: [probe.bcur[0].r, probe.bcur[0].g, probe.bcur[0].b, probe.bcur[0].a],
    tintInit: probe.tint.slice(), DUR: Object.assign({}, D.DUR), FG: D.FG.slice(),
    rmDrop: ['wake', 'sweep', 'scatter', 'reveal', 'tick'],
    notTested: ['down (M19)', 'boot', 'pending', 'shimmer', 'unlit button colour damping (BS:624-625)',
      'bound colour fallback (BS:648)', 'S resting level (D10)']
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
process.stderr.write(`alive_oracle_bs: ${results.length} cases, ${stepCount} steps, ${text.length} bytes; seeds ${cov.seeds}; tint in ${cov.tint}\n`);
process.stderr.write(`alive_oracle_bs: section 9 bytes on every step (drive 150, dither off); F-T floor lit ${cov.floored} LED-step(s)\n`);
if (outPath) fs.writeFileSync(outPath, text, 'utf8'); else process.stdout.write(text);
