'use strict';
/*
 * Golden LED/LCD fixtures from the design's knob-model.js (cc5 Stage 5).
 *
 * Runs design-reference/.../knob-model.js unmodified in a node `vm` context
 * with inert window/document shims (nothing is fetched, no image is loaded,
 * no timer runs). NanoModel.COLORS is PRE-POPULATED from
 * tests/fixtures/dominant_reference.json ("colors", NanoModel.COLORS form:
 * {"al:<title>"|"app:<app>": "r,g,b"|null}) exactly as loadColors() would have
 * filled it in the browser, so the model's tint() sees the same accents the
 * Python adapter feeds to control_center.preview_lights.
 *
 * Dumped per case: the model state, view(st) and view(st,{led:'color'}) ring +
 * buttons, and the white view's lcd + foot (icon names recovered from the path
 * table I). Pulse cases also carry the tick-1 rings; cases with more than 20
 * windows also carry the "windowed" rings (contract deviation 5: entries
 * outside the 20-entry window are drawn as gaps by marking them closed in the
 * model, so every slot keeps the model's own formula). Sequences replay the
 * model's own step() with its fx timers for the Stage 6 animation checks.
 * Scenario notes are the per-scenario ring notes (RING object literal) of
 * "Nano_D Control Center.dc.html" next to the model; stress notes are the model's.
 *
 * Usage: node knob_golden.cjs <knob-model.js> <dominant_reference.json> [out.json]
 * Without out.json the JSON goes to stdout. Output is deterministic.
 */
const fs = require('fs');
const vm = require('vm');

const [modelPath, referencePath, outPath] = process.argv.slice(2);
if (!modelPath || !referencePath) {
  process.stderr.write('usage: node knob_golden.cjs <knob-model.js> <dominant_reference.json> [out.json]\n');
  process.exit(2);
}
const reference = JSON.parse(fs.readFileSync(referencePath, 'utf8'));
if (!reference.colors || typeof reference.colors !== 'object') throw new Error('reference has no "colors" map');

const inert = name => () => { throw new Error(`knob_golden: ${name} is not available (no DOM, no network)`); };
const context = vm.createContext({
  window: {},
  document: { createElement: inert('document.createElement'), head: { appendChild: inert('document.head') } },
  Image: class { set src(v) { throw new Error('knob_golden: image load ' + v); } },
  setTimeout: inert('setTimeout'),
  clearTimeout: inert('clearTimeout')
});

// Expose private pure helpers next to the public API. Every function body is
// evaluated exactly as shipped in the design.
const anchor = 'window.NanoModel = { loadColors,';
const source = fs.readFileSync(modelPath, 'utf8');
if (source.split(anchor).length !== 2) throw new Error('knob-model.js export anchor not found exactly once');
vm.runInContext(source.replace(anchor,
  'window.NanoModel = { __tint: tint, __volColor: volColor, __cover: cover, loadColors,'),
  context, { filename: 'knob-model.js' });
const M = context.window.NanoModel;

// Pre-populate COLORS (nulls included: tint() then falls back to COLOR_FALLBACK or null).
for (const key of Object.keys(reference.colors).sort()) M.COLORS[key] = reference.colors[key];

const plain = o => JSON.parse(JSON.stringify(o));
const ICON_BY_PATH = {};
for (const k of Object.keys(M.I)) ICON_BY_PATH[M.I[k]] = k;
const iconName = d => (d ? (ICON_BY_PATH[d] || '?') : '');
const ringOut = ring => ring.map(r => (r ? [r.c, r.l] : null));
const buttonsOut = bs => bs.map(b => ({ w: b.w, tone: b.tone, c: b.c, l: b.l }));

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

function views(st, opts) {
  const w = M.view(st, Object.assign({}, opts || {}));
  const c = M.view(st, Object.assign({}, opts || {}, { led: 'color' }));
  return {
    white: { ring: ringOut(w.ring), buttons: buttonsOut(w.buttons), lcd: lcdOut(w.lcd),
      foot: w.foot.map(f => ({ icon: iconName(f.d), w: f.w, tone: f.tone })),
      mode: w.mode, screenKey: w.screenKey, depth: w.depth },
    color: { ring: ringOut(c.ring), buttons: buttonsOut(c.buttons) }
  };
}
const ringsOnly = st => ({ white: ringOut(M.view(st).ring), color: ringOut(M.view(st, { led: 'color' }).ring) });

const cases = [];
const ids = new Set();
function add(group, id, name, note, st, extra) {
  if (ids.has(id)) throw new Error('duplicate case id ' + id);
  ids.add(id);
  st = plain(st);
  const entry = { id, group, name, note: note || '', st, views: views(st) };
  const t1 = plain(st); t1.tick = 1;
  const tick1 = ringsOnly(t1);
  if (JSON.stringify(tick1) !== JSON.stringify({ white: entry.views.white.ring, color: entry.views.color.ring })) entry.tick1 = tick1;
  if (st.mode === 'windows' && st.win.order.length > 20) {
    // Deviation 5 expected value: the 20-entry host window (first = clamp(idx-9, 0, n-20)),
    // drawn by the model itself with every entry outside the window marked closed.
    const n = st.win.order.length, first = Math.max(0, Math.min(st.win.idx - 9, n - 20));
    const sw = plain(st);
    for (let i = 0; i < n; i++) if ((i < first || i >= first + 20) && !sw.win.closed.includes(i)) sw.win.closed.push(i);
    entry.windowed = Object.assign({ first }, ringsOnly(sw));
  }
  Object.assign(entry, extra || {});
  cases.push(entry);
}
const slug = s => s.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
const R_ = (page, idx, status, extra) => Object.assign({ mode: 'recent', recent: { page, idx, stack: page ? Array(page).fill(10) : [], status: status || 'ready' } }, extra || {});
const flashSt = (patch, kind, id) => Object.assign({}, patch, { flash: { kind, id }, flashId: id });

// Scenario notes: the RING object literal of "Nano_D Control Center.dc.html" (next to the model).
function ringNotes() {
  const page = require('path').join(require('path').dirname(modelPath), 'Nano_D Control Center.dc.html');
  if (!fs.existsSync(page)) return {};
  const html = fs.readFileSync(page, 'utf8');
  const start = html.indexOf('const RING = {');
  if (start < 0) return {};
  const end = html.indexOf('};', start);
  return vm.runInNewContext('(' + html.slice(start + 'const RING = '.length, end + 1) + ')', {});
}
const RING_NOTES = ringNotes();

// 1. Every scenario and stress case, as shipped.
M.scenarios().forEach(x => add('scenario', x.id, x.name, RING_NOTES[x.id] || '', x.st));
M.stress().forEach(x => add('stress', 'stress-' + slug(x.name), x.name, x.note, x.st));

// 2. Section 00b ledRows (Nano_D Control Center.dc.html, same states and notes).
[
  ['led-vol-54', 'Volume · 54 %', { vol: 54, volConf: 54 }, 'No change: white below 80 %.'],
  ['led-vol-86', 'Volume · 86 %', { vol: 86, volConf: 86, volVis: true }, 'Segments past 80 % turn amber.'],
  ['led-vol-96', 'Volume · 96 %', { vol: 96, volConf: 96, volVis: true }, 'Last 10 % red; endpoint takes the colour.'],
  ['led-recent', 'Recently Added', { mode: 'recent', recent: { idx: 2 } }, 'Each landmark takes its cover’s dominant colour; cursor brightest.'],
  ['led-win-claude', 'Windows · Claude', { mode: 'windows', win: { idx: 1 } }, 'Each detent takes its app icon’s colour.'],
  ['led-win-chrome', 'Windows · Chrome', { mode: 'windows', win: { idx: 2 } }, 'Monochrome icons (Terminal, ChatGPT) stay white.']
].forEach(([id, name, patch, note]) => add('ledRows', id, name, note, M.mk(patch)));

// 3. Volume sweep 0..100: confirmed equal, pending up (confirmed 9 below), pending down (9 above).
for (let v = 0; v <= 100; v++) {
  add('sweep', `vol-${v}-eq`, `Volume ${v} %`, 'confirmed', M.mk({ vol: v, volConf: v, volVis: true }));
  if (v - 9 >= 0) add('sweep', `vol-${v}-up`, `Volume ${v} % (confirmed ${v - 9})`, 'pending increase', M.mk({ vol: v, volConf: v - 9, volVis: true }));
  if (v + 9 <= 100) add('sweep', `vol-${v}-down`, `Volume ${v} % (confirmed ${v + 9})`, 'pending decrease', M.mk({ vol: v, volConf: v + 9, volVis: true }));
}
[0, 1, 38, 79, 89, 100].forEach(v => add('volume', `vol-${v}-ext`, `Volume ${v} % · changed elsewhere`, 'external endpoint L4', M.mk({ vol: v, volConf: v, ext: true, volVis: true })));
add('volume', 'vol-1-down-50', 'Volume 1 % (confirmed 100)', 'pending decrease across the whole arc', M.mk({ vol: 1, volConf: 100, volVis: true }));
add('volume', 'home-off-61', 'Volume · Sonos offline at 61 %', 'offline endpoint uses the confirmed value only', M.mk({ sonos: 'off', vol: 61, volConf: 61 }));
add('volume', 'home-off-0', 'Volume · Sonos offline at 0 %', '', M.mk({ sonos: 'off', vol: 0, volConf: 0 }));
add('volume', 'home-none-vol', 'Volume · nothing playing, turning', '', M.mk({ nothing: true, vol: 57, volConf: 57, volVis: true }));
add('volume', 'home-pidle-vol', 'Volume · paused idle, turning', '', M.mk({ playing: false, playReq: false, pIdle: true, vol: 41, volConf: 41, volVis: true }));

// 4. Pending pulses (tick 0 HIGH, tick 1 LOW).
add('pending', 'pend-ra-p2', 'Recently Added P2 · playback pending', '', M.mk(R_(1, 5, 'pending')));
add('pending', 'pend-tr-next', 'Tracks · Next skip pending', '', M.mk({ mode: 'tracks', tracks: { pos: 1, status: 'pending' } }));
add('pending', 'pend-tr-prev', 'Tracks · Previous skip pending', '', M.mk({ mode: 'tracks', tracks: { pos: -1, status: 'pending' } }));
add('pending', 'pend-wi-claude', 'Windows · switch to Claude pending', 'deviation 3: white pulse', M.mk({ mode: 'windows', win: { idx: 1, status: 'pending' } }));
add('pending', 'pend-wi-chrome', 'Windows · switch to Chrome pending', 'deviation 3: white pulse', M.mk({ mode: 'windows', win: { idx: 2, status: 'pending' } }));
add('pending', 'pend-wi-codex', 'Windows · switch to Codex pending', 'untinted app: white either way', M.mk({ mode: 'windows', win: { idx: 0, status: 'pending' } }));

// 5. Flashes (feedback seq = the model's flashId).
add('flash', 'flash-ok-tracks', 'Tracks · skipped, green flash', 'tr-done with its flash', M.mk(flashSt({ mode: 'tracks', qi: 2, tracks: { pos: 0, status: 'done' } }, 'ok', 1)));
add('flash', 'flash-err-ra-part', 'Recently Added · partial, red flash', 'ra-part with its flash', M.mk(flashSt(R_(0, 2, 'partial'), 'err', 2)));
add('flash', 'flash-err-wi-fail', 'Windows · failed, red flash', 'wi-fail with its flash', M.mk(flashSt({ mode: 'windows', win: { idx: 2, status: 'failed' } }, 'err', 3)));
add('flash', 'flash-ok-home', 'Volume · played, green flash', 'Recent play completion lands on Home', M.mk(flashSt({ np: { t: 'Night Channel', a: 'Velvet Circuit' } }, 'ok', 4)));
add('flash', 'flash-ok-home-61', 'Volume 61 % · green flash', 'flash overwrites the odd-v shoulder', M.mk(flashSt({ vol: 61, volConf: 61 }, 'ok', 5)));
add('flash', 'flash-ok-home-0', 'Volume 0 % · green flash', 'cursor-1 is segment 34', M.mk(flashSt({ vol: 0, volConf: 0 }, 'ok', 6)));
add('flash', 'flash-err-home-96', 'Volume 96 % · red flash', 'color mode: flash colours are fixed', M.mk(flashSt({ vol: 96, volConf: 96 }, 'err', 7)));
add('flash', 'flash-err-ra-load', 'Recently Added · loading, red flash', 'loading cursor is segment 0', M.mk(flashSt(R_(0, 0, 'loading'), 'err', 8)));
add('flash', 'flash-ok-wi-first', 'Windows · first entry, green flash', '', M.mk(flashSt({ mode: 'windows', win: { idx: 0 } }, 'ok', 9)));
add('flash', 'flash-ok-ra-more', 'Recently Added · More, green flash', '', M.mk(flashSt(R_(0, 10), 'ok', 10)));

// 6. Loading, More, unavailable, closed, Sonos down.
add('lists', 'ra-load-p2', 'Recently Added · loading page 2', 'requested page', M.mk(R_(1, 0, 'loading')));
add('lists', 'ra-load-p3', 'Recently Added · loading page 3', 'requested page', M.mk(R_(2, 0, 'loading')));
add('lists', 'ra-more-p2', 'Recently Added P2 · More', '', M.mk(R_(1, 10)));
add('lists', 'ra-na-p2', 'Recently Added P2 · unavailable', 'Música do Porto', M.mk(R_(1, 4)));
add('lists', 'ra-item-p2', 'Recently Added P2 · Tidal Glass', 'cover without an accent: white', M.mk(R_(1, 2)));
add('lists', 'ra-item-p2-glass weather', 'Recently Added P2 · Glass Weather', '', M.mk(R_(1, 5)));
add('lists', 'ra-last-p3', 'Recently Added P3 · last item (no More)', '', M.mk(R_(2, 2)));
add('lists', 'ra-night-drive', 'Recently Added · Night Channel', '', M.mk(R_(0, 2)));
add('lists', 'ra-hounds', 'Recently Added · Paper Lanterns', '', M.mk(R_(0, 9)));
add('lists', 'ra-sonos-off', 'Recently Added · Sonos down', 'landmarks kept, Play dim', M.mk(R_(0, 2, 'ready', { sonos: 'off' })));
add('lists', 'wi-closed-claude', 'Windows · Claude closed', 'Windows unavailable cursor keeps the app colour', M.mk({ mode: 'windows', win: { idx: 1, closed: [1] } }));
add('lists', 'wi-closed-multi', 'Windows · two closed slots', '', M.mk({ mode: 'windows', win: { idx: 3, closed: [2, 4] } }));
add('lists', 'wi-slack', 'Windows · Slack', '', M.mk({ mode: 'windows', win: { idx: 6 } }));
add('lists', 'wi-discord', 'Windows · Discord (minimized)', 'COLOR_FALLBACK accent', M.mk({ mode: 'windows', win: { idx: 7 } }));
add('lists', 'wi-last', 'Windows · last entry', '', M.mk({ mode: 'windows', win: { idx: 8 } }));

// 7. Tracks, including no Previous.
add('tracks', 'tr-prev', 'Tracks · Previous selected', '', M.mk({ mode: 'tracks', tracks: { pos: -1 } }));
add('tracks', 'tr-noprev-neutral', 'Tracks · neutral, no Previous', '', M.mk({ mode: 'tracks', tracks: { pos: 0 }, opt: { noPrev: true } }));
add('tracks', 'tr-noprev-next', 'Tracks · Next, no Previous', '', M.mk({ mode: 'tracks', tracks: { pos: 1 }, opt: { noPrev: true } }));

// 8. More than 20 windows (deviation 5) and the exact 20 boundary.
const winsN = (n, idx, closed) => M.mk({ mode: 'windows', win: { order: Array.from({ length: n }, (_, i) => i % 9), idx, closed: closed || [] } });
[[20, 0], [20, 19], [21, 0], [21, 10], [21, 20], [25, 12], [45, 5], [45, 30], [45, 44], [80, 40], [80, 79]].forEach(([n, i]) =>
  add('windows', `wi-n${n}-i${i}`, `Windows · ${n} windows, entry ${i + 1}`, n > 20 ? 'deviation 5: 20-entry window' : 'design-exact (count <= 20)', winsN(n, i)));
add('windows', 'wi-n45-i30-closed', 'Windows · 45 windows, closed inside and outside the window', 'deviation 5', winsN(45, 30, [3, 25, 31]));

// 9. Disconnected (deviation 8: firmware hands back to the native UI; no frame).
add('disconnected', 'disc-reconnecting', 'Knob · reconnecting', 'deviation 8', M.mk({ conn: 'reconnecting' }));

// ---------------------------------------------------------------- sequences
// Replays the model's own step() with its fx timers (a deterministic event queue).
function sequence(id, name, note, st0, script, horizon) {
  let s = plain(st0), queue = [], order = 0;
  script.forEach(([t, act]) => queue.push({ t, act, order: order++, user: true }));
  const steps = [{ t: 0, act: null, user: false, st: plain(s), view: views(s), cmd: null }];
  const end = Math.max(0, ...script.map(x => x[0])) + (horizon || 0);
  while (queue.length) {
    queue.sort((a, b) => a.t - b.t || a.order - b.order);
    const ev = queue.shift();
    if (ev.t > end) break;
    const r = M.step(s, ev.act);
    r.fx.forEach(f => queue.push({ t: ev.t + f.ms, act: f.act, order: order++, user: false }));
    const changed = JSON.stringify(r.s) !== JSON.stringify(s);
    s = r.s;
    if (changed || ev.user) steps.push({ t: ev.t, act: plain(ev.act), user: ev.user, st: plain(s), view: views(s), cmd: r.cmd || null });
  }
  return { id, name, note, steps };
}
const sequences = [
  sequence('volume-reveal-hide', 'Volume reveal and hide', 'One detent: reveal, pending, Sonos ack at 380 ms, hide at 1400 ms.',
    M.mk({}), [[0, { t: 'rot', d: 1 }]], 3000),
  sequence('idle-entry-exit', 'Paused idle entry and exit', 'Pause, ack at 420 ms, idle 4 s later; a turn reveals volume over idle; Play exits idle.',
    M.mk({}), [[0, { t: 'btn', n: 1 }], [5000, { t: 'rot', d: 1 }], [8000, { t: 'btn', n: 1 }]], 2000),
  sequence('screen-deeper-back', 'Screen change deeper and back', 'Home → Recent (deeper, +20 px) → More → page 2 (deeper) → Back (−20 px) → Back to Home (−20 px) → Windows (deeper) → Cancel (back).',
    M.mk({}), [[0, { t: 'btn', n: 2 }], [1000, { t: 'rot', d: 10 }], [1200, { t: 'btn', n: 4 }], [2500, { t: 'btn', n: 1 }], [3000, { t: 'btn', n: 1 }],
      [3500, { t: 'btn', n: 3 }], [4000, { t: 'btn', n: 1 }]], 1000),
  sequence('heartbeat-identical', 'Heartbeat with an identical frame', 'The same Home state re-sent 1 s later: no animation, no text re-set.',
    M.mk({}), [[1000, { t: 'volAck', seq: -1 }]], 0),
  sequence('external-volume', 'External volume re-enter', 'Volume changed on Sonos: reveal with L4 endpoint, hide at 2600 ms, external cleared at 6000 ms.',
    M.mk({}), [[0, { t: 'external' }]], 7000),
  sequence('tracks-skip-recentre', 'Tracks skip and re-centre', 'Tracks → Next → skip (pending) → done at 650 ms: back at neutral with a green flash, no slide.',
    M.mk({}), [[0, { t: 'btn', n: 4 }], [500, { t: 'rot', d: 1 }], [1000, { t: 'btn', n: 4 }]], 2000)
];
// The heartbeat sequence needs two identical steps; the stale volAck changes nothing, so record it.
sequences.forEach(q => { if (q.id === 'heartbeat-identical' && q.steps.length !== 2) throw new Error('heartbeat step missing'); });

// ---------------------------------------------------------------- constants
const pages = [0, 1, 2].map(p => M.entries(M.mk({ recent: { page: p } })).map(e => plain(e)));
const tintKeys = new Set(Object.keys(reference.colors));
pages.forEach(es => es.forEach(e => { if (!e.more) tintKeys.add('al:' + e.t); }));
M.WINS.forEach(w => tintKeys.add('app:' + w.app));
const tints = {};
[...tintKeys].sort().forEach(k => { tints[k] = M.__tint(k); });
const volColors = {};
['white', 'color'].forEach(led => { volColors[led] = Array.from({ length: 51 }, (_, k) => M.__volColor(k / 50, undefined, led)); });

const out = {
  about: 'Golden LED/LCD fixture generated from knob-model.js by tests/js/knob_golden.cjs. Ring entries are [\"r,g,b\", l] (l = model level 0..4) or null; buttons carry the model tone and light. Compare with tests/test_cc_led_model.py.',
  generator: 'tests/js/knob_golden.cjs',
  model: 'design-reference/design_handoff_nano_d_artwork_color/knob-model.js',
  colorsSource: 'tests/fixtures/dominant_reference.json',
  constants: { tints, volColors, pages, WINS: plain(M.WINS), QUEUE: plain(M.QUEUE), APPIC: plain(M.APPIC) },
  cases,
  sequences
};
// One case / sequence per line: compact, deterministic and diff-friendly.
const NL = String.fromCharCode(10);
const block = list => '[' + NL + list.map(x => JSON.stringify(x)).join(',' + NL) + NL + ']';
const text = '{' + NL + Object.keys(out).map(k => JSON.stringify(k) + ': ' +
  (Array.isArray(out[k]) ? block(out[k]) : JSON.stringify(out[k]))).join(',' + NL) + NL + '}' + NL;
if (outPath) fs.writeFileSync(outPath, text, 'utf8'); else process.stdout.write(text);
