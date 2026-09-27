'use strict';
/*
 * Button-grammar oracle (CONTROL_CENTER_V5.md section 17, test_cc5_grammar_oracle.py): the design's
 * own footer, BS renderVals() `foot` (icon key and tone per slot), for every state-picker
 * combination that reaches the footer (BS:1352-1365), from the [r2.2] master's
 * "Browse and Snap.dc.html" (the K3 r2.2 amendments are binding; r2.2's footer differs from r2.1
 * only on the liked heart, R22 BS:1268).
 *
 * The logic block (<script type="text/x-dc" data-dc-script>) runs in a node `vm` context with inert
 * stubs (as tests/js/alive_oracle_bs.cjs does): a DCLogic base class, React.createRef(), window,
 * requestAnimationFrame no-ops, a fixed Date (Date.now() = 0, so no knobMeta is live), and timers,
 * performance and document throwing (the oracle never mounts the component). The block is evaluated
 * UNMODIFIED except for ONE mechanical capture patch: `__grammarCapture(foot);` inserted right before
 * `const fx = [46, 89, 131, 174];` (the footer's layout, just after `foot` is final). The anchor must
 * occur exactly once or this script throws.
 *
 * Each case is a state patch over fresh() (plus a `sim` patch), rendered once with renderVals().
 * Recorded per slot: `key` (the BS glyph key: the name in BS's I table whose path is `d`; a `rect`
 * carries its HALF side as `rect-left` / `rect-right`), `tone` (nav / go / dim / on / off / none) and
 * `c` (a colour override, e.g. the snap app colour or r2.2's liked PINK) when the design sets one.
 * The Python test maps the keys to the VOC-N06 meaning tokens and the tones to PRESENTATION_V5 5.2.
 *
 * Usage: node grammar_oracle.cjs <prototypes dir> [out.json]
 * Output is deterministic (no clock, no randomness).
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const [designDir, outPath] = process.argv.slice(2);
if (!designDir) {
  process.stderr.write('usage: node grammar_oracle.cjs <prototypes dir> [out.json]\n');
  process.exit(2);
}
const HTML_PATH = path.join(designDir, 'Browse and Snap.dc.html');
const noop = () => {};
const inert = name => () => { throw new Error(`grammar_oracle: ${name} is not available (the oracle drives renderVals() only)`); };

function replaceOnce(source, anchor, replacement, what) {
  const count = source.split(anchor).length - 1;
  if (count !== 1) throw new Error(`grammar_oracle: ${what} anchor found ${count} time(s), expected exactly once: ${anchor}`);
  const at = source.indexOf(anchor);
  return source.slice(0, at) + replacement + source.slice(at + anchor.length);
}

// ---------------------------------------------------------------- the design's logic class
const html = fs.readFileSync(HTML_PATH, 'utf8');
const opens = [...html.matchAll(/<script type="text\/x-dc"[^>]*>/g)];
if (opens.length !== 1) throw new Error(`grammar_oracle: expected one <script type="text/x-dc"> block, found ${opens.length}`);
const logicStart = opens[0].index + opens[0][0].length;
const logicEnd = html.indexOf('</script>', logicStart);
if (logicEnd < 0) throw new Error('grammar_oracle: logic block is not closed');
const logicSource = html.slice(logicStart, logicEnd);
const logicLine = html.slice(0, logicStart).split('\n').length;

const CAPTURE_ANCHOR = 'const fx = [46, 89, 131, 174];';
const patched = replaceOnce(logicSource, CAPTURE_ANCHOR, '__grammarCapture(foot); ' + CAPTURE_ANCHOR, 'footer layout');

let captured = null;
class FixedDate {
  getHours() { return 12; }
  getMinutes() { return 0; }
  static now() { return 0; }
}
const sandbox = {
  window: { devicePixelRatio: 1 },
  document: new Proxy({}, { get: (t, k) => { throw new Error('grammar_oracle: document.' + String(k) + ' is not available'); } }),
  React: { createRef: () => ({ current: null }) },
  requestAnimationFrame: () => 0,
  cancelAnimationFrame: noop,
  setTimeout: inert('setTimeout'),
  clearTimeout: inert('clearTimeout'),
  setInterval: inert('setInterval'),
  clearInterval: inert('clearInterval'),
  performance: { now: inert('performance.now') },
  ResizeObserver: class { constructor() { throw new Error('grammar_oracle: ResizeObserver'); } },
  Date: FixedDate,
  __grammarCapture: foot => {
    if (captured !== null) throw new Error('grammar_oracle: two footers in one render');
    captured = foot.map(f => Object.assign({}, f));
  }
};
const context = vm.createContext(sandbox);
vm.runInContext(
  'class DCLogic { constructor(props) { this.props = props; } setState(patch) { this.state = Object.assign({}, this.state, typeof patch === "function" ? patch(this.state) : patch); } forceUpdate() {} }',
  context, { filename: 'grammar_oracle-stubs.js' });
vm.runInContext(patched, context, { filename: 'Browse and Snap.dc.html', lineOffset: logicLine - 1 });
const D = vm.runInContext('({ Component, I, HALF, PINK, WARM })', context);

const KEY_OF = new Map(Object.entries(D.I).map(([name, d]) => [d, name]));
const TONES = new Set(['nav', 'go', 'dim', 'on', 'off', 'none']);
function slotOf(f, where) {
  if (!TONES.has(f.t)) throw new Error(`${where}: unknown tone ${f.t}`);
  let key = f.d === '' ? '' : KEY_OF.get(f.d);
  if (key === undefined) throw new Error(`${where}: a glyph outside BS's I table`);
  if (key === 'rect') {
    if (f.fill === D.HALF.left) key = 'rect-left';
    else if (f.fill === D.HALF.right) key = 'rect-right';
    else throw new Error(`${where}: a rect without a HALF side`);
  }
  const out = { key, tone: f.t };
  if (f.c) out.c = Array.from(f.c);
  if (f.fill && f.fill === D.I.heart) out.filled = true;
  return out;
}

// ---------------------------------------------------------------- states
const probe = new D.Component({});
const FRESH = probe.fresh();
const QUEUE0 = FRESH.queue;
const SOURCES = ['queue', 'airplay', 'radio', 'linein', 'none'];

function render(name, patch) {
  const p = patch || {};
  const st = Object.assign({}, FRESH, p, { sim: Object.assign({}, FRESH.sim, p.sim || {}) });
  const inst = new D.Component({});
  inst.state = st;
  captured = null;
  inst.renderVals();
  if (!captured || captured.length !== 4) throw new Error(`${name}: no footer captured`);
  return captured.map((f, i) => slotOf(f, `${name} slot ${i}`));
}

const CASES = [];
function C(name, bs) {
  if (CASES.some(c => c.name === name)) throw new Error('duplicate case ' + name);
  CASES.push({ name, bs, foot: render(name, bs) });
}
const likeKey = tr => tr.al + ':' + tr.t;

// Home: playing / paused, Starting…, every source; the PC-not-connected footer (knob profile).
for (const playing of [true, false]) {
  for (const start of [false, true]) {
    for (const source of SOURCES) {
      C(`home-${playing ? 'playing' : 'paused'}${start ? '-starting' : ''}-${source}`,
        { mode: 'home', playing, busy: start ? { kind: 'start' } : null, sim: { source } });
    }
  }
}
C('home-pc-off', { mode: 'home', sim: { pc: 'off' } });

// Tracks: Previous / Neutral / Next on every source; the busy spans on a queue.
for (const tPos of [-1, 0, 1]) {
  for (const source of SOURCES) C(`tracks-${tPos}-${source}`, { mode: 'tracks', tPos, sim: { source } });
}
for (const busy of [{ kind: 'start' }, { kind: 'pn', k: 1, n: 12 }]) {
  C(`tracks-1-queue-${busy.kind}`, { mode: 'tracks', tPos: 1, busy, sim: { source: 'queue' } });
}

// Seek (a queue only: Seek is refused elsewhere, BS srcWhy): idle, jumping, failed.
for (const seekState of [null, 'jump', 'fail']) {
  C(`seek-${seekState || 'idle'}`, { mode: 'tracks', seek: true, seekState, sim: { source: 'queue' } });
}

// Up next: every queue kind x like state x companion shuffle x focus (now, the next row, the one
// after) x the focused row liked or not.
for (const upnext of ['normal', 'loading', 'foreign', 'longshuffle']) {
  for (const like of ['ok', 'loading', 'expired']) {
    for (const shuffle of upnext === 'longshuffle' ? [false] : [false, true]) {
      for (const qSel of upnext === 'longshuffle' ? [4, 5] : [4, 5, 6]) {
        for (const liked of [false, true]) {
          const tr = QUEUE0[FRESH.qOrder[qSel]];
          C(`upnext-${upnext}-${like}${shuffle ? '-shuffle' : ''}-${qSel}${liked ? '-liked' : ''}`,
            { mode: 'queue', qOpen: true, qIn: true, qSel, shuffle, liked: liked ? { [likeKey(tr)]: true } : {},
              sim: { upnext, like } });
        }
      }
    }
  }
}

// Recently Added: every source x Sonos shuffle x busy (none, Starting…, Play next) x the list loaded
// or loading (art 'list').
for (const source of SOURCES) {
  for (const sonosShuffle of ['off', 'on']) {
    for (const busy of [null, { kind: 'start' }, { kind: 'pn', k: 1, n: 12 }]) {
      for (const art of ['mixed', 'list']) {
        C(`recent-${source}-shuffle_${sonosShuffle}-${busy ? busy.kind : 'idle'}-${art}`,
          { mode: 'recent', rIdx: 0, busy, sim: { source, sonosShuffle, art } });
      }
    }
  }
}

// Music explorer: both tabs x favourites (real, empty, many) x the list loaded or loading.
for (const src of ['recent', 'playlists']) {
  for (const favs of ['real', 'empty', 'many']) {
    for (const art of ['mixed', 'list']) {
      C(`explorer-${src}-${favs}-${art}`, { mode: 'explore', src, xOpen: true, xIn: true, sim: { favs, art } });
    }
  }
}

// Windows: nothing snapped, one side, both sides, a side held by the warm-marker app (ChatGPT).
for (const [label, left, right] of [['none', null, null], ['left', 1, null], ['right', null, 2], ['both', 1, 2],
  ['left-warm', 3, null]]) {
  C(`windows-${label}`, { mode: 'windows', wOpen: true, wIn: true, sel: 1, left, right });
}

// ---------------------------------------------------------------- output
const header = {
  source: 'design-reference/design_handoff_nano_d_master_r2.2/prototypes/Browse and Snap.dc.html (renderVals foot)',
  capture: CAPTURE_ANCHOR,
  constants: { PINK: Array.from(D.PINK), WARM: Array.from(D.WARM) },
  fresh: { playing: FRESH.playing, qNow: FRESH.qNow, qLength: FRESH.qOrder.length, sel: FRESH.sel, rIdx: FRESH.rIdx },
  windows: probe.W.map(w => ({ app: w.app, c: Array.from(w.c) }))
};
const NL = '\n';
const text = '{' + NL + Object.keys(header).map(k => JSON.stringify(k) + ': ' + JSON.stringify(header[k])).join(',' + NL) +
  ',' + NL + '"cases": [' + NL + CASES.map(c => JSON.stringify(c)).join(',' + NL) + NL + ']}' + NL;
if (outPath) fs.writeFileSync(outPath, text, 'utf8'); else process.stdout.write(text);
