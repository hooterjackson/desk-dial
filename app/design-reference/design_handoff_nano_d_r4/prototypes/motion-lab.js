/* Nano D motion lab — prototype library. Every prototype is a pure function of time t (ms), so play, scrub and loop are exact. */
(function () {
'use strict';
const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
const lerp = (a, b, p) => a + (b - a) * p;
function bez(x1, y1, x2, y2) {
  const cx = 3 * x1, bx = 3 * (x2 - x1) - cx, ax = 1 - cx - bx, cy = 3 * y1, by = 3 * (y2 - y1) - cy, ay = 1 - cy - by;
  const sx = t => ((ax * t + bx) * t + cx) * t, sy = t => ((ay * t + by) * t + cy) * t, dx = t => (3 * ax * t + 2 * bx) * t + cx;
  const f = x => { if (x <= 0) return 0; if (x >= 1) return 1; let t = x; for (let i = 0; i < 8; i++) { const d = dx(t); if (Math.abs(d) < 1e-6) break; t -= (sx(t) - x) / d; } return sy(clamp(t)); };
  f.css = `cubic-bezier(${x1}, ${y1}, ${x2}, ${y2})`; return f;
}
const E = { out: bez(.22, 1, .36, 1), in: bez(.4, 0, 1, 1), io: bez(.65, 0, .35, 1), spr: bez(.34, 1.45, .64, 1), lin: Object.assign(x => clamp(x), { css: 'linear' }) };
function spring(k, c, m = 1) {
  const w0 = Math.sqrt(k / m), z = c / (2 * Math.sqrt(k * m));
  const f = ms => { const t = ms / 1000; if (t <= 0) return 0;
    if (z < 1) { const wd = w0 * Math.sqrt(1 - z * z); return 1 - Math.exp(-z * w0 * t) * (Math.cos(wd * t) + (z * w0 / wd) * Math.sin(wd * t)); }
    return 1 - Math.exp(-w0 * t) * (1 + w0 * t); };
  f.k = k; f.c = c; f.m = m;
  let st = 3000; for (let ms = 0; ms < 3000; ms += 4) { let ok = true; for (let j = 0; j <= 160; j += 8) if (Math.abs(1 - f(ms + j)) > 0.004) { ok = false; break; } if (ok) { st = ms; break; } }
  f.settle = st; f.css = `spring(k ${k}, c ${c}, m ${m}) · settles ≈ ${st} ms`; return f;
}
const ap = (r, z) => { const k = +Math.pow(2 * Math.PI / r, 2).toFixed(1), c = +(4 * Math.PI * z / r).toFixed(1), f = spring(k, c); f.css = `spring(response ${r} s, damping ${z}) · k ${k}, c ${c} · settles ≈ ${f.settle} ms`; return f; };
const SP = { snap: ap(0.3, 0.9), soft: ap(0.45, 1), pop: ap(0.38, 0.72), bouncy: ap(0.4, 0.82), crit: ap(0.28, 1), roll: ap(0.3, 0.88), list: ap(0.28, 0.92) };
const pr = (t, s, d, e = E.out) => e(clamp((t - s) / d));
const bloom = (t, s, rise = 140, fall = 560) => (t < s ? 0 : t < s + rise ? E.out((t - s) / rise) : 1 - E.io(clamp((t - s - rise) / fall)));
const sp = (t, s, f) => (t <= s ? 0 : f(t - s));
const FM = new Map();
function follow(tg, t, f, delay = 0, key) { if (!key) { let x = tg(-1), v = 0; for (let s = 0; s <= t; s += 4) { const a = f.k * (tg(s - delay) - x) - f.c * v; v += a * 0.004; x += v * 0.004; } return x; }
  const kk = key + '|' + f.k + '|' + delay; let arr = FM.get(kk); if (!arr) { arr = new Float32Array(3001); let x = tg(-1), v = 0; for (let i = 0; i <= 3000; i++) { const s = i * 4, a = f.k * (tg(s - delay) - x) - f.c * v; v += a * 0.004; x += v * 0.004; arr[i] = x; } FM.set(kk, arr); }
  return arr[Math.max(0, Math.min(3000, Math.round(t / 4)))]; }

const C = { ink: '#F2F2F2', sec: '#A6A6A6', meta: '#7C7C7C', dis: '#5A5A5A', nav: '#E6E6E6', ok: '#6ED996', warm: '#FFBE69', no: '#FF8474', succ: '#7EE0A2' };
const WARM = [255, 190, 105], WW = [255, 232, 205], GREEN = [110, 217, 150], RED = [255, 60, 40], WHITE = [240, 240, 240];
const hx = s => [1, 3, 5].map(i => parseInt(s.slice(i, i + 2), 16));
const mixRGB = (a, b, p) => a.map((x, i) => Math.round(lerp(x, b[i], clamp(p))));
const mixHex = (a, b, p) => `rgb(${mixRGB(hx(a), hx(b), p).join(',')})`;
const segC = (rgb, a) => `rgb(${rgb.map(x => Math.round(31 + (x - 31) * clamp(a))).join(',')})`;
const kel = K => { const t = K / 100, cl = x => Math.round(clamp(x, 0, 255));
  return [cl(t <= 66 ? 255 : 329.7 * Math.pow(t - 60, -0.1332)), cl(t <= 66 ? 99.47 * Math.log(t) - 161.12 : 288.12 * Math.pow(t - 60, -0.0755)), cl(t >= 66 ? 255 : 138.52 * Math.log(t - 10) - 305.04)]; };
const kelHex = K => '#' + kel(K).map(x => x.toString(16).padStart(2, '0')).join('');

const N = 60;
const RG = {
  fill: (rgb, a) => Array.from({ length: N }, () => [rgb, a]),
  rest: () => RG.fill(WARM, 0.12), off: () => RG.fill(WARM, 0),
  k: i => { const k = (i - 38 + N) % N; return k < 45 ? k : -1; },
  arc: (p, rgb, hi = 1, lo = 0) => Array.from({ length: N }, (_, i) => { const k = RG.k(i); if (k < 0) return [rgb, 0]; const f = clamp(p * 45 - k); return [rgb, lo + (hi - lo) * f]; }),
  comet: (p, rgb) => Array.from({ length: N }, (_, i) => { const k = RG.k(i); if (k < 0) return [rgb, 0]; const head = p * 45, d = head - k; return [rgb, d < 0 ? 0 : d < 1.5 ? 1 : 0.62]; }),
  marker: (n, pos, rgb, base = 0.1, baseRgb) => { const m = pos * 44 / Math.max(1, n - 1); return Array.from({ length: N }, (_, i) => { const k = RG.k(i); if (k < 0) return [rgb, 0]; const d = Math.abs(k - m); return d < 2.4 ? [d < 1.2 ? rgb : mixRGB(rgb, baseRgb || rgb, (d - 1.2) / 1.2), lerp(1, base, E.io(clamp((d - 0.3) / 2.1)))] : [baseRgb || rgb, base]; }); },
  blend: (A, B, p) => A.map((a, i) => [mixRGB(a[0], B[i][0], p), lerp(a[1], B[i][1], clamp(p))]),
  sweep: (A, B, p, order) => A.map((a, i) => { const o = order(i), w = E.io(clamp((p - o) / 0.12)); return [mixRGB(a[0], B[i][0], w), lerp(a[1], B[i][1], w)]; }),
  over: (A, idx, rgb, a) => A.map((s, i) => (idx.includes(i) ? [rgb, Math.max(s[1] * 0.3, a)] : s)),
  cw: i => i / N, bottomUp: i => Math.min(Math.abs(i - 30), N - Math.abs(i - 30)) / 30
};
const BOT = [27, 28, 29, 30, 31, 32, 33];
const btns = (o = {}) => [0, 1, 2, 3].map(i => o[i] || [WW, 0.34]);

const FONT = 'Montserrat, sans-serif';
let cvx; const tw = (s, size, w = 500) => { cvx = cvx || document.createElement('canvas').getContext('2d'); cvx.font = `${w} ${size}px ${FONT}`; return cvx.measureText(s).width; };
function device(h, o) {
  const { s = 1, ring, btns: b = btns(), kids = [], haptic = 0, id, top = null, bl = 1, sr = 120 } = o;
  const oy = top ? 96 : 0, cx = 150, cy = 150 + oy;
  const segs = ring.map(([rgb, a], i) => h('rect', { key: i, x: -2, y: -5, width: 4, height: 10, rx: 1, fill: segC(rgb, a), transform: `translate(${cx} ${cy}) rotate(${i * 6}) translate(0 -138)` }));
  const bs = b.map(([rgb, a], i) => { const x = 46 + i * 56; return h('g', { key: i },
    h('rect', { x, y: oy + 302, width: 40, height: 34, fill: '#202020', stroke: '#2c2c2c', strokeWidth: 1 }),
    h('rect', { x, y: oy + 333, width: 40, height: 3, fill: segC(rgb, Math.max(a, 0.14)) }),
    h('rect', { x: x + 4, y: oy + 338, width: 32, height: 6, fill: `rgba(${rgb.join(',')},${(clamp(a) * 0.5).toFixed(2)})`, opacity: 0.6 }),
    h('text', { x: x + 20, y: oy + 323, fontSize: 11, fill: '#6a6a6a', textAnchor: 'middle', fontFamily: FONT, fontWeight: 600 }, String(i + 1))); });
  return h('svg', { width: 300 * s, height: (352 + oy) * s, viewBox: `0 0 300 ${352 + oy}`, style: { display: 'block', background: '#141414' } },
    h('defs', null, h('clipPath', { id: 'sc' + id }, h('circle', { cx, cy, r: Math.max(0.1, sr) }))),
    top, h('g', null, segs),
    h('circle', { cx, cy, r: 126, fill: '#0a0a0a', stroke: '#262626', strokeWidth: 1 }),
    h('circle', { cx, cy, r: 120, fill: '#000' }),
    h('g', { clipPath: `url(#sc${id})` }, h('g', { transform: `translate(30 ${30 + oy})`, opacity: bl }, ...kids.flat(9).filter(Boolean))),
    h('g', null, bs));
}
const G = (h, kids, o = {}) => h('g', o, ...[kids].flat(9).filter(Boolean));
const tf = (dx = 0, dy = 0, s = 1) => `translate(${dx} ${dy}) translate(120 120) scale(${s}) translate(-120 -120)`;
function T(h, str, o = {}) {
  const { x = 120, y = 0, size = 14, col = C.ink, op = 1, anchor = 'middle', w = 500, dx = 0, dy = 0, ls = 0, filter, clip } = o;
  if (str == null || str === '' || op <= 0.001) return null;
  return h('text', { x: x + dx, y: y + dy + size * 0.95, fontSize: size, fill: col, opacity: clamp(op), textAnchor: anchor, fontFamily: FONT, fontWeight: w, letterSpacing: ls, filter, clipPath: clip, style: { fontVariantNumeric: 'tabular-nums' } }, str);
}
function icoG(h, cx, cy, size, o, kids) { const { op = 1, sx = 1, sy = 1, dx = 0, dy = 0, rot = 0 } = o || {}; const k = size / 24; if (op <= 0.001) return null;
  return h('g', { opacity: clamp(op), transform: `translate(${cx + dx} ${cy + dy}) rotate(${rot}) scale(${sx * k} ${sy * k}) translate(-12 -12)` }, ...[kids].flat(9).filter(Boolean)); }
function pth(h, d, o = {}) { const { col = C.nav, sw = 2.3, op = 1, dash, fill = 'none' } = o; if (op <= 0.001) return null;
  const p = { d, fill, stroke: col, strokeWidth: sw, strokeLinecap: 'round', strokeLinejoin: 'round', opacity: op };
  if (dash != null) { p.pathLength = 1; p.strokeDasharray = '1 1'; p.strokeDashoffset = 1 - clamp(dash); } return h('path', p); }
const Ic = (h, d, cx, cy, size, o = {}) => icoG(h, cx, cy, size, o, pth(h, d, { col: o.col || C.nav, sw: o.sw || (size >= 26 ? 2.1 : 2.3), fill: o.fill }));

const I = {
  play: 'M6 3l14 9-14 9V3z', pause: 'M6 4h4v16H6zM14 4h4v16h-4z',
  music: 'M9 18V5l12-2v13M9 18a3 3 0 1 1-6 0 3 3 0 0 1 6 0zM21 16a3 3 0 1 1-6 0 3 3 0 0 1 6 0z', win: 'M3 4h18v16H3zM3 9h18',
  bulb: 'M9 18h6M10 22h4M15.1 14c.2-1 .7-1.7 1.4-2.5A4.7 4.7 0 0 0 18 8 6 6 0 0 0 6 8c0 1 .2 2.2 1.5 3.5A4.6 4.6 0 0 1 8.9 14',
  back: 'M15 18l-6-6 6-6', home: 'M3 10l9-7 9 7v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1zM9 21v-8h6v8',
  temp: 'M14 4v10.5a4 4 0 1 1-4 0V4a2 2 0 0 1 4 0z', power: 'M12 2v10M18.4 6.6a9 9 0 1 1-12.8 0', stem: 'M12 2v10', parc: 'M18.4 6.6a9 9 0 1 1-12.8 0',
  list: 'M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01', check: 'M20 6L9 17l-5-5',
  expand: 'M8 3H5a2 2 0 0 0-2 2v3M21 8V5a2 2 0 0 0-2-2h-3M3 16v3a2 2 0 0 0 2 2h3M16 21h3a2 2 0 0 0 2-2v-3',
  listMusic: 'M21 15V6M18.5 18a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM12 12H3M16 6H3M12 18H3', album: 'M3 3h18v18H3zM12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10zM12 11.5v1',
  snapL: 'M3 5h18v14H3zM12 5v14M5.5 8v8M8.5 8v8', snapR: 'M3 5h18v14H3zM12 5v14M15.5 8v8M18.5 8v8',
  wandStick: 'M21.6 2.6l-1.2-1.2a1.2 1.2 0 0 0-1.7 0L2.4 17.7a1.2 1.2 0 0 0 0 1.7l1.2 1.2a1.2 1.2 0 0 0 1.7 0L21.6 4.3a1.2 1.2 0 0 0 0-1.7zM14 7l3 3',
  wand: 'M21.6 2.6l-1.2-1.2a1.2 1.2 0 0 0-1.7 0L2.4 17.7a1.2 1.2 0 0 0 0 1.7l1.2 1.2a1.2 1.2 0 0 0 1.7 0L21.6 4.3a1.2 1.2 0 0 0 0-1.7zM14 7l3 3M5 6v4M19 14v4M10 2v2M7 8H3M21 16h-4M11 3H9'
};
const SPARK = [[5, 8, 'M5 6v4M3 8h4'], [19, 16, 'M19 14v4M17 16h4'], [10, 3, 'M10 2v2M9 3h2']];
const FX = [56, 99, 141, 184], FY = 164, IX = [51, 97, 143, 189], IY = 113;
const footer = (h, items) => G(h, items.map((it, i) => it && Ic(h, it.d, FX[i], FY, 20, it)));
const ARC = 'M 26 120 A 94 94 0 0 1 214 120', ARCLEN = Math.PI * 94;
const CRUMB_MAX = 190, crumbW = s => tw(s, 12) + s.length * 0.96;
function fitCrumb(anc, cur) { const parts = anc.split(' › ').map(x => x.trim()).filter(Boolean); let out = parts.length > 1 ? '… › ' + parts[parts.length - 1] + ' › ' : anc;
  if (crumbW(out + cur) <= CRUMB_MAX) return out; return crumbW('‹ ' + cur) <= CRUMB_MAX ? '‹ ' : ''; }
function fitText(s, size, maxW, w = 500) { if (!s || tw(s, size, w) <= maxW) return s; let t = s; while (t.length > 1 && tw(t + '…', size, w) > maxW) t = t.slice(0, -1); return t.trimEnd() + '…'; }
function crumb(h, pid, anc, cur, o = {}) { const { op = 1, rot = 0, dy = 0 } = o; if (op <= 0.001) return null; anc = fitCrumb(anc, cur);
  return h('g', { opacity: clamp(op), transform: `translate(0 ${dy}) rotate(${rot} 120 120)` }, h('path', { id: pid, d: ARC, fill: 'none' }),
    h('text', { fontFamily: FONT, fontSize: 12, fontWeight: 500, letterSpacing: 0.96 }, h('textPath', { href: '#' + pid, startOffset: '50%', textAnchor: 'middle' }, h('tspan', { fill: C.meta }, anc), h('tspan', { fill: C.nav }, cur)))); }
function npText(h, o = {}) { const { lines = ['Long Range'], artist = 'Air', op = 1, dx = 0, dy = 0, s = 1 } = o; if (op <= 0.001) return null;
  return h('g', { opacity: clamp(op), transform: tf(dx, dy, s) }, ...lines.map((l, i) => T(h, l, { y: 60 + i * 26, size: 22 })), T(h, artist, { y: 114, size: 14, col: C.sec })); }
function listText(h, o = {}) { const { prev = '', cur = '', next = '', meta = '', op = 1, dx = 0, dy = 0, s = 1 } = o; if (op <= 0.001) return null;
  return h('g', { opacity: clamp(op), transform: tf(dx, dy, s) }, T(h, fitText(prev, 14, 104), { y: 56, size: 14, col: C.meta }), T(h, fitText(cur, 22, 160), { y: 78, size: 22 }), T(h, fitText(next, 14, 150), { y: 108, size: 14, col: C.meta }), T(h, fitText(meta, 12, 176), { y: 134, size: 12, col: C.meta })); }
const COV = { moon: 'assets/covers/moon-safari.png', helig: 'assets/covers/glass weather-album-.png', blue: 'assets/covers/kind-of-blue.jpg', night: 'assets/covers/night-drive-velvet circuit-album-.jpg', lines: 'assets/covers/blue-lines.jpg', promises: 'assets/covers/promises-floating-points-pharoah-sanders.png' };
function art(h, href, op, o = {}) { const { dx = 0, dy = 0, s = 1 } = o; if (op <= 0.001) return null;
  return h('image', { href, x: 0, y: 0, width: 240, height: 240, preserveAspectRatio: 'xMidYMid slice', opacity: clamp(op), transform: tf(dx, dy, s) }); }
function mosaic(h, hrefs, ops, o = {}) { const { dx = 0, dy = 0, s = 1 } = o;
  return h('g', { transform: tf(dx, dy, s) }, ...hrefs.map((hr, k) => ops[k] > 0.001 ? h('image', { key: k, href: hr, x: (k % 2) * 120, y: k < 2 ? 0 : 120, width: 120, height: 120, preserveAspectRatio: 'xMidYMid slice', opacity: clamp(ops[k]) }) : null)); }
function scrim(h, gid, op = 1) { if (op <= 0.001) return [];
  return [h('linearGradient', { id: gid, x1: 0, y1: 0, x2: 0, y2: 1 }, h('stop', { offset: '0', stopColor: '#000', stopOpacity: 0.6 }), h('stop', { offset: '0.45', stopColor: '#000', stopOpacity: 0.72 }), h('stop', { offset: '0.62', stopColor: '#000', stopOpacity: 0.92 }), h('stop', { offset: '0.7', stopColor: '#000', stopOpacity: 1 })),
    h('rect', { x: 0, y: 0, width: 240, height: 240, fill: `url(#${gid})`, opacity: clamp(op) })]; }
const lastEv = (ev, t, v0) => { let v = v0, at = -1e9, prev = v0; for (const [tt, vv] of ev) if (tt <= t) { prev = v; v = vv; at = tt; } return { v, at, prev }; };
const tgOf = (ev, v0) => s => lastEv(ev, s, v0).v;
const hapticAt = (ticks, t) => { let m = 0; for (const x of ticks) { const d = t - (Array.isArray(x) ? x[0] : x), w = Array.isArray(x) ? x[1] : 1; if (d >= 0 && d < 90) m = Math.max(m, w * (1 - d / 90)); } return m; };
const K = ctx => { const rd = ctx.reduced; return { rd, D: v => (rd ? 0 : v), S: (t, s, f, d = 160) => (rd ? pr(t, s, d) : sp(t, s, f)) }; };
const RDX = 'Opacity crossfade 160 ms, E.out. No translate, scale, rotation or overshoot.';

const P = [];
const spec = (anim, timing, ease, frames, fps, haptic, reduced = RDX) => ({ anim, timing, ease, frames, fps, haptic, reduced });

/* ============ 1. ICONOGRAPHY ============ */
const PQ = [[[6, 4], [10, 4], [10, 20], [6, 20]], [[14, 4], [18, 4], [18, 20], [14, 20]]];
const PL = [[[6, 4], [13, 8.33], [13, 15.67], [6, 20]], [[13, 8.33], [20, 12], [20, 12], [13, 15.67]]];
function morphPP(h, m, col) {
  const q = [0, 1].map(j => PQ[j].map((p, i) => [lerp(p[0], PL[j][i][0], m), lerp(p[1], PL[j][i][1], m)]));
  const L = (a, b) => `M${a[0].toFixed(2)} ${a[1].toFixed(2)}L${b[0].toFixed(2)} ${b[1].toFixed(2)}`;
  return [pth(h, L(q[0][0], q[0][1]) + L(q[0][2], q[0][3]) + L(q[0][3], q[0][0]) + L(q[1][0], q[1][1]) + L(q[1][1], q[1][2]) + L(q[1][2], q[1][3]), { col }), pth(h, L(q[0][1], q[0][2]) + L(q[1][3], q[1][0]), { col, op: 1 - m })];
}
function ppR(c, v) {
  const { h, t, trig } = c, { rd } = K(c), T0 = 100, toPlay = trig === 'pause';
  let g = toPlay ? pr(t, T0 + 150, 200) : 1 - pr(t, T0, 140);
  if (v === 'today') g = (t >= T0) === toPlay ? 1 : 0;
  const col = mixHex(C.nav, C.ok, g); let icon;
  if (v === 'today') icon = Ic(h, (t >= T0) === toPlay ? I.play : I.pause, FX[3], FY, 20, { col });
  else if (rd) { const q = pr(t, T0, 160), po = toPlay ? q : 1 - q; icon = [Ic(h, I.pause, FX[3], FY, 20, { col, op: 1 - po }), Ic(h, I.play, FX[3], FY, 20, { col, op: po })]; }
  else if (v === 'A') { const s = sp(t, T0, SP.snap), m = clamp(toPlay ? s : 1 - s), pop = 0.94 + 0.06 * sp(t, T0, SP.pop); icon = icoG(h, FX[3], FY, 20, { sx: pop, sy: pop }, morphPP(h, m, col)); }
  else if (v === 'B') { const s = sp(t, T0, SP.pop), m = clamp(toPlay ? s : 1 - s); icon = icoG(h, FX[3], FY, 20, { rot: -8 * Math.sin(Math.PI * clamp(s)) }, morphPP(h, m, col)); }
  else { const from = toPlay ? I.pause : I.play, to = toPlay ? I.play : I.pause, o = pr(t, T0, 100, E.in), n = sp(t, T0 + 60, SP.snap);
    icon = [Ic(h, from, FX[3], FY, 20, { col, op: t < T0 ? 1 : 1 - o, dy: -2 * o }), t >= T0 ? Ic(h, to, FX[3], FY, 20, { col, op: pr(t, T0 + 40, 140), dy: 2 * (1 - n) }) : null]; }
  const mo = v === 'today' ? ((t >= T0) === toPlay ? 1 : 0) : toPlay ? pr(t, T0, 160) : 1 - pr(t, T0, 120);
  const b = btns({ 3: [mixRGB(WW, GREEN, g), lerp(0.34, 0.68, g)] }); b[3] = [b[3][0], b[3][1] + (0.9 - b[3][1]) * 0.5 * bloom(t, T0, 90, 420)];
  return { ring: RG.rest(), btns: b, kids: [npText(h, {}), T(h, 'Paused', { y: 134, size: 12, col: C.sec, op: mo }), footer(h, [{ d: I.home }, { d: I.album }, { d: I.list }]), icon] };
}
P.push({ id: 'playpause', area: 'icons', title: 'Play ⇄ Pause morph', brief: 'Button 4 on Home and Music. The bars become the triangle; the paused green arrives only after the shape has settled, so the two changes read separately.',
  triggers: [{ id: 'pause', label: 'Tap 4 · pause', dur: 1100, hap: [100] }, { id: 'resume', label: 'Tap 4 · resume', dur: 1100, hap: [100] }],
  today: { name: 'Today', cost: 'Cheap', spec: spec('Glyph swaps on the tap frame; colour and LED switch at once.', '0 ms', '—', '2 glyphs', '—', 'Button click only', 'Same as today'), render: c => ppR(c, 'today') },
  variants: [
    { id: 'A', name: 'Melt', rec: true, cost: 'Medium', spec: spec('Each bar\'s 4 corners interpolate to one half of the triangle; the inner seam fades. Glyph dips to 0.94 on the tap and springs back with a ≈ 4 % overshoot as the morph lands. Stroke colour → #6ED996 after the shape lands; button-4 LED warm white → green.', 'Morph starts on the tap frame, ≈ 220 ms. Green 150 ms delay + 200 ms.', 'Morph ' + SP.snap.css + '. Green E.out ' + E.out.css, '12-frame strip × 2 directions at 20 px (≈ 0.4 KB/frame, ≈ 10 KB). Colour via LVGL recolor, not baked.', '30 fps is enough; 60 fps optional.', 'Motor click on the tap frame (t = 0).'), render: c => ppR(c, 'A') },
    { id: 'B', name: 'Twist-merge', cost: 'Medium', spec: spec('Same corner morph with an 8° turn that unwinds by the end.', '≈ 300 ms from the tap frame.', SP.pop.css, '12-frame strip × 2 directions (≈ 10 KB).', '30 fps', 'Click at t = 0.'), render: c => ppR(c, 'B') },
    { id: 'C', name: 'Slide swap', cost: 'Cheap', spec: spec('Old glyph fades out drifting 2 px up; new glyph fades in from 2 px below.', 'Out 100 ms; in from 40 ms, 140 ms fade.', 'Out E.in; in ' + SP.snap.css, 'None (2 glyphs).', '30 fps', 'Click at t = 0.'), render: c => ppR(c, 'C') }
  ] });

function pressR(c, v) {
  const { h, t, trig } = c, { rd } = K(c);
  const taps = trig === 'seq' ? [[100, 0], [500, 1], [900, 2], [1300, 3]] : [[100, 1]];
  const icons = [I.home, I.album, I.list, I.pause], kids = [npText(h, {})], b = btns();
  icons.forEach((d, i) => { const tp = taps.filter(x => x[1] === i && x[0] <= t).map(x => x[0]).pop(); const o = { d, col: C.nav };
    if (tp != null) { const dt = t - tp; b[i] = [WW, 0.34 + 0.4 * bloom(dt, 0, 90, 420)];
      if (v === 'today') {}
      else if (rd) o.op = 0.6 + 0.4 * pr(dt, 0, 160);
      else if (v === 'A') { const disp = 1 - SP.pop(dt); o.sy = 1 - 0.1 * disp; o.sx = 1 + 0.06 * disp; }
      else if (v === 'B') { o.sx = o.sy = 0.9 + 0.1 * SP.pop(dt); }
      else if (v === 'C') { const r = 10 + 8 * pr(dt, 0, 420), a = 0.16 * bloom(dt, 0, 90, 360); if (a > 0.01) kids.push(h('circle', { cx: FX[i], cy: FY, r, fill: '#FFE8CD', opacity: a })); }
      else { const s = SP.snap(dt); o.dy = 1.5 * (1 - s); o.op = 0.72 + 0.28 * s; } }
    kids.push(Ic(h, o.d, FX[i], FY, 20, o)); });
  return { ring: RG.rest(), btns: b, kids };
}
P.push({ id: 'press', area: 'icons', title: 'Press feedback on footer icons', brief: 'Every footer icon (Home, Recent, Tracks, Win, Lights, Scenes, Temp, Power) answers its own button. The action fires on the press; the icon only acknowledges it.',
  triggers: [{ id: 'seq', label: 'Tap 1 → 4 in turn', dur: 1800, hap: [100, 500, 900, 1300] }, { id: 'one', label: 'Tap 2', dur: 900, hap: [100] }],
  today: { name: 'Today', cost: 'Cheap', spec: spec('No icon response; button LED jumps to full for the press.', '—', '—', '—', '—', 'Button click', 'Same'), render: c => pressR(c, 'today') },
  variants: [
    { id: 'A', name: 'Squash bounce', cost: 'Medium', spec: spec('Squash on the press frame (scaleY 0.92, scaleX 1.05), springs back with ≈ 2 % stretch.', '≈ 300 ms.', SP.pop.css, '8-frame strip per icon; 8 icons × 8 × 0.4 KB ≈ 26 KB (26 px: 45 KB).', '30 fps OK.', 'Click at t = 0, the frame of maximum squash.'), render: c => pressR(c, 'A') },
    { id: 'B', name: 'Spring pop', cost: 'Medium', spec: spec('Scale 0.9 on press → springs to 1 with ≈ 1 % overshoot.', '≈ 350 ms.', SP.pop.css, '10-frame strip per icon (≈ 32 KB for 8 icons).', '60 fps shows the overshoot best.', 'Click at t = 0.'), render: c => pressR(c, 'B') },
    { id: 'C', name: 'Ink ripple', cost: 'Medium', spec: spec('Warm-white disc at 18 % grows r 10 → 18 behind the icon and fades out.', '360 ms.', 'Radius and alpha E.out.', '10-frame 44 px ripple strip shared by all slots (≈ 19 KB).', '30 fps', 'Click at t = 0.'), render: c => pressR(c, 'C') },
    { id: 'D', name: 'Nudge', rec: true, cost: 'Cheap', spec: spec('Icon drops 1.5 px and dims to 72 % on press, settles back.', '≈ 300 ms.', SP.snap.css, 'None.', '30 fps', 'Click at t = 0, icon at its lowest.'), render: c => pressR(c, 'D') }
  ] });

function lightsIconR(c, v) {
  const { h, t, trig } = c, { rd } = K(c), T0 = 100, dt = t - T0;
  const onBefore = trig !== 'on', onAfter = trig !== 'off', on = t >= T0 ? onAfter : onBefore, flip = trig === 'on' || trig === 'off';
  const kids = [T(h, 'LIGHTS', { y: 32, size: 12, col: C.sec, ls: 0.96 })];
  const K0 = 2700, K1 = trig === 'temp' ? 5000 : 2700;
  const kp = trig === 'temp' ? (v === 'A' && !rd ? sp(t, T0, SP.soft) : v === 'B' || rd ? pr(t, T0, 300) : t >= T0 ? 1 : 0) : 0;
  const Kv = trig === 'temp' ? lerp(K0, K1, kp) : 2700;
  let amt = on ? 1 : 0; if (flip && t >= T0) { const q = v === 'today' ? 1 : v === 'C' ? pr(dt, 0, 80) : pr(dt, 0, 220); amt = trig === 'on' ? q : 1 - q; }
  // bulb
  const bcol = mixHex(C.nav, C.warm, amt), bk = [];
  if (v === 'A' && !rd) { let r = 8 * amt, go = 0.28 * amt; if (trig === 'on' && t >= T0) { r = 3 + 5 * SP.soft(dt); go = 0.28 + 0.1 * (1 - pr(dt, 200, 400)); } bk.push(h('circle', { cx: 12, cy: 8.5, r: Math.max(0, r), fill: C.warm, opacity: go }));
    [-150, -90, -30].forEach((a, i) => { const rr = a * Math.PI / 180, x1 = 12 + 10.5 * Math.cos(rr), y1 = 8.5 + 10.5 * Math.sin(rr), x2 = 12 + 13.5 * Math.cos(rr), y2 = 8.5 + 13.5 * Math.sin(rr);
      const dsh = trig === 'on' ? (t < T0 ? 0 : pr(dt, 120 + i * 50, 200)) : trig === 'off' ? (t < T0 ? 1 : 1 - pr(dt, 0, 120)) : on ? 1 : 0; bk.push(pth(h, `M${x1} ${y1}L${x2} ${y2}`, { col: C.warm, dash: dsh, op: dsh > 0 ? 1 : 0 })); }); }
  else { bk.push(h('circle', { cx: 12, cy: 8.5, r: 8, fill: C.warm, opacity: 0.28 * amt }));
    if (v !== 'C') [-150, -90, -30].forEach((a, i) => { const rr = a * Math.PI / 180; const ro = trig === 'on' && t >= T0 && v !== 'today' && !rd ? pr(dt, 60 + i * 40, 140) : amt; bk.push(pth(h, `M${12 + 10.5 * Math.cos(rr)} ${8.5 + 10.5 * Math.sin(rr)}L${12 + 13.5 * Math.cos(rr)} ${8.5 + 13.5 * Math.sin(rr)}`, { col: C.warm, op: ro })); }); }
  bk.push(pth(h, I.bulb, { col: bcol, sw: 2.1 })); kids.push(icoG(h, IX[0], IY, 26, {}, bk));
  // power
  let dash = 1, pcol = on ? C.nav : C.dis, sdy = 0;
  if (flip && t >= T0 && v !== 'today') { if (v === 'A' && !rd) { dash = dt < 140 ? 1 - pr(dt, 0, 140, E.in) : pr(dt, 140, 360); pcol = dt < 140 ? (onBefore ? C.nav : C.dis) : (onAfter ? C.nav : C.dis); sdy = 0; }
    else if (v === 'B' && !rd) { pcol = mixHex(onBefore ? C.nav : C.dis, onAfter ? C.nav : C.dis, pr(dt, 0, 160)); sdy = 0; }
    else pcol = mixHex(onBefore ? C.nav : C.dis, onAfter ? C.nav : C.dis, pr(dt, 0, v === 'C' ? 80 : 160)); }
  kids.push(icoG(h, IX[1], IY, 26, { dy: sdy * 26 / 24 }, [pth(h, I.stem, { col: pcol, sw: 2.1 }), pth(h, I.parc, { col: pcol, sw: 2.1, dash })]));
  // thermo
  const L = (Kv - 2200) / 4300, mcol = on ? kelHex(Kv) : C.dis;
  kids.push(icoG(h, IX[2], IY, 26, {}, [h('rect', { x: 11.1, y: 15 - L * 9, width: 1.8, height: 2 + L * 9, rx: 0.9, fill: mcol }), h('circle', { cx: 12, cy: 17.5, r: 2.3, fill: mcol }), pth(h, I.temp, { col: C.nav, sw: 2.1 })]));
  // wand
  const wk = []; let wrot = 0, bump = 0;
  if (trig === 'scene' && t >= T0) { bump = bloom(dt, 0, 160, 700); if (v === 'A' && !rd) wrot = -6 * Math.sin(Math.PI * clamp(dt / 300)) * (1 - clamp(dt / 600)) - 1.5 * Math.sin(Math.PI * clamp((dt - 300) / 300)) * (dt > 300 ? 1 : 0); }
  const wcol = v === 'today' ? C.nav : mixHex(C.nav, C.succ, bump);
  wk.push(pth(h, I.wandStick, { col: wcol, sw: 2.1 }));
  SPARK.forEach(([x, y, d], i) => { let s = 1, rot = 0, op = 1;
    if (trig === 'scene' && t >= T0 && v !== 'today') { if (v === 'A' && !rd) { s = 0.7 + 0.3 * sp(t, T0 + 40 + i * 40, SP.pop); } else if (v === 'B' || rd) op = 1 - 0.55 * bloom(dt, i * 40, 180, 420); }
    wk.push(h('g', { transform: `translate(${x} ${y}) rotate(${rot}) scale(${s}) translate(${-x} ${-y})` }, pth(h, d, { col: trig === 'scene' && t >= T0 && v !== 'today' ? mixHex(C.nav, C.succ, bump) : C.nav, sw: 2.1, op }))); });
  kids.push(icoG(h, IX[3], IY, 26, { rot: wrot }, wk));
  ['Lights', 'Power', 'Temp', 'Scenes'].forEach((l, i) => kids.push(T(h, l, { x: IX[i], y: 134, size: 12, col: C.nav })));
  const st = { on: 'Lights on', off: 'Lights off', temp: `${Math.round(Kv / 100) * 100} K`, scene: 'Scene running' }[trig];
  kids.push(T(h, st, { y: 158, size: 12, col: trig === 'scene' ? C.succ : C.sec, op: trig === 'temp' ? 1 : pr(t, T0, 160) }));
  const onRing = RG.arc(0.62, kel(Kv), 0.34, 0); let ring = on ? onRing : RG.off();
  if (v === 'C' && !rd && t >= T0) { if (flip) ring = RG.sweep(trig === 'on' ? RG.off() : onRing, trig === 'on' ? onRing : RG.off(), pr(dt, 0, 520, E.io), RG.bottomUp);
    else if (trig === 'temp') ring = RG.sweep(RG.arc(0.62, kel(K0), 0.34, 0), RG.arc(0.62, kel(K1), 0.34, 0), pr(dt, 0, 520, E.io), RG.cw);
    else { const p = pr(dt, 0, 700, E.io); ring = RG.blend(RG.blend(onRing, RG.comet(p, GREEN), 1 - pr(dt, 600, 400, E.io)), RG.fill(GREEN, 0.5), 0.6 * bloom(t, T0 + 560, 160, 600)); } }
  else if (t >= T0) { if (flip && v !== 'today') ring = RG.blend(trig === 'on' ? RG.off() : onRing, trig === 'on' ? onRing : RG.off(), pr(dt, 0, 300)); if (trig === 'scene') ring = v === 'today' ? RG.blend(RG.fill(GREEN, 0.68), onRing, pr(dt, 0, 450, E.lin)) : RG.blend(onRing, RG.fill(GREEN, 0.55), bloom(t, T0, 180, 700)); }
  return { ring, kids };
}
P.push({ id: 'lightsicons', area: 'icons', title: 'Bulb, Power, Thermo, Wand', brief: 'The four Lights icons at the 26 px idle size. Each one shows the thing it changed: the filament glows, the power stroke draws round, mercury fills to the new temperature, the wand sparkles when a scene runs.',
  triggers: [{ id: 'on', label: 'Lights on', dur: 1300, hap: [100] }, { id: 'off', label: 'Lights off', dur: 1200, hap: [100] }, { id: 'temp', label: '2700 → 5000 K', dur: 1400, hap: [100] }, { id: 'scene', label: 'Scene runs', dur: 1400, hap: [100] }],
  today: { name: 'Today', cost: 'Cheap', spec: spec('Icons are static; state is only shown on the ring and in text.', '—', '—', '—', '—', 'Button click', 'Same'), render: c => lightsIconR(c, 'today') },
  variants: [
    { id: 'A', name: 'Expressive', rec: true, cost: 'Medium', spec: spec('Bulb: glow disc grows r 3 → 8, 3 rays draw in (stroke dash) 50 ms apart, stroke → warm. Power: arc undraws 140 ms and redraws 360 ms in the new colour. Thermo: mercury height and Kelvin colour ease to the new level. Wand: rocks 6° and back, the 3 sparkles grow from 70 % 40 ms apart with a small overshoot, green tint blooms 160 / 700 ms.', 'Bulb 450 ms · Power 500 ms · Thermo ≈ 450 ms · Wand 700 ms.', `Glow ${SP.soft.css}; rays E.out 200 ms; power E.in/E.out; mercury ${SP.soft.css}; wand ${SP.pop.css}.`, 'Bulb on/off 14 + 8 frames, Power 16, Wand 14 (26 px ≈ 0.7 KB each → ≈ 36 KB). Thermo needs none: mercury is a live 2 px rect object.', '30 fps', 'Click on the tap frame; none on the sparkle.'), render: c => lightsIconR(c, 'A') },
    { id: 'B', name: 'Quiet', cost: 'Cheap', spec: spec('Colour and opacity only: glow disc and rays fade in (40 ms apart), power recolours, mercury eases, sparkles dim and return once.', '160–360 ms.', 'E.out', 'None. Rays and sparkles are separate small objects.', '30 fps', 'Click on the tap frame.'), render: c => lightsIconR(c, 'B') },
    { id: 'C', name: 'Ring leads', cost: 'Cheap', spec: spec('Icons recolour in 80 ms; the ring does the storytelling: on = fills up from the bottom on both sides, off = drains, temperature = new colour sweeps clockwise, scene = green comet runs once round and blooms softly as it finishes.', 'Ring 520–1400 ms.', 'E.io ' + E.io.css, 'None.', 'LED task runs at 60 fps independently.', 'Click on the tap frame; soft tick when the scene comet completes.'), render: c => lightsIconR(c, 'C') }
  ] });

function idleR(c, v) {
  const { h, t, trig } = c, { rd } = K(c), kids = [];
  const icons = [[I.music, 'Music', C.nav], [I.win, 'Win', C.nav], [I.bulb, 'Lights', C.nav], [I.play, 'Play', C.dis]];
  let s0 = trig === 'wake' ? 100 : trig === 'stop' ? (v === 'today' ? 500 : 420) : -1e6, ring = RG.rest();
  if (trig === 'wake') ring = RG.blend(RG.off(), RG.rest(), pr(t, 100, 200));
  if (trig === 'stop') { const q = pr(t, 300, 150, E.in); kids.push(npText(h, { lines: ['Remember'], op: 1 - q, dy: rd ? 0 : -8 * q }), footer(h, [{ d: I.music, op: 1 - q }, { d: I.win, op: 1 - q }, { d: I.bulb, op: 1 - q }, { d: I.pause, op: 1 - q }]), T(h, 'Queue ended', { y: 134, size: 12, col: C.sec, op: pr(t, 120, 140) * (1 - q) })); }
  const order = v === 'B' ? [0, 0, 0, 0] : [0, 1, 2, 3].map(i => i * (v === 'today' ? 45 : 24));
  icons.forEach(([d, l, col], i) => { const st = s0 + order[i]; let op, dx = 0, dy = 0;
    if (v === 'today') { op = pr(t, st, 300); dy = 14 * (1 - E.spr(clamp((t - st) / 460))); }
    else if (rd) op = pr(t, st, 200);
    else if (v === 'A') { op = pr(t, st, 240); dy = 6 * (1 - sp(t, st, SP.soft)); }
    else if (v === 'B') { op = pr(t, st, 200); dx = 0.25 * (120 - IX[i]) * (1 - sp(t, st, SP.soft)); }
    else { op = pr(t, st, 220); dy = -6 * (1 - sp(t, st, SP.pop)); }
    kids.push(Ic(h, d, IX[i], IY, 26, { col, op, dx, dy }));
    const lo = op;
    kids.push(T(h, l, { x: IX[i] + dx, y: 134, dy: v === 'today' || v === 'A' ? dy * 0.6 : dy, size: 12, col, op: lo })); });
  return { ring, kids };
}
P.push({ id: 'idle', area: 'icons', title: 'Idle icon row', brief: 'Shown only when nothing is loaded (r3.1 §4). The row arrives when the knob wakes or the queue ends, then rests with a barely-there breath.',
  triggers: [{ id: 'wake', label: 'Knob wakes', dur: 1500 }, { id: 'stop', label: 'Queue ends', dur: 1800 }, { id: 'breathe', label: 'At rest (loop)', dur: 4000 }],
  today: { name: 'Today', cost: 'Cheap', spec: spec('Fade 300 ms + 14 px rise with an overshooting bezier, 45 ms stagger, 200 ms delay.', '300 / 460 ms.', E.spr.css, '—', '30 fps', '—', 'Same'), render: c => idleR(c, 'today') },
  variants: [
    { id: 'A', name: 'Stagger rise', rec: true, cost: 'Cheap', spec: spec('Icons and labels rise 6 px together with a critically damped spring, 24 ms apart. At rest the row is still: no breathing.', 'Stagger 24 ms; each ≈ 450 ms.', SP.soft.css, 'None.', '30 fps', 'None.'), render: c => idleR(c, 'A') },
    { id: 'B', name: 'Fan from centre', cost: 'Cheap', spec: spec('All four icons open outwards from 25 % closer to the centre, at once.', '≈ 450 ms.', SP.soft.css, 'None.', '30 fps', 'None.'), render: c => idleR(c, 'B') },
    { id: 'C', name: 'Drop in', cost: 'Cheap', spec: spec('Icons settle down from 4 px above, 24 ms apart, with a ≈ 2 % overshoot.', '≈ 400 ms.', SP.pop.css, 'None.', '30 fps', 'None.'), render: c => idleR(c, 'C') }
  ] });

function holdR(c, v) {
  const { h, t, trig } = c, { rd } = K(c), P0 = 100, LAND = 1100, REL = 700, early = trig === 'early', q = trig === 'queue';
  const end = early ? REL : LAND, holding = t >= P0 && t < end, landed = !early && t >= LAND;
  const hp = t < P0 ? 0 : clamp((Math.min(t, end) - P0) / 1000);
  const kids = [];
  if (q) kids.push(crumb(h, c.id + 'a', 'MUSIC › ', 'RECENTLY ADDED'), listText(h, { prev: 'Night Channel', cur: 'Midnight Arcade', next: 'Paper Lanterns', meta: '4 / 9 · Air' }));
  else { const x = landed ? (v === 'today' ? 1 : pr(t, LAND, 200)) : 0; kids.push(npText(h, { lines: ['Remember'], op: 1 - x }), T(h, 'LIGHTS', { y: 32, size: 12, col: C.sec, ls: 0.96, op: x }), npText(h, { lines: ['Focus'], artist: 'Hall · 62% · 3200 K', op: x })); }
  kids.push(T(h, 'Queued · Midnight Arcade', { y: 134, size: 12, col: C.succ, op: q && landed ? pr(t, LAND, 160) : 0 }));
  kids.push(footer(h, q ? [{ d: I.back }, { d: I.expand }, { d: I.listMusic }] : [{ d: I.music }, { d: I.win }, { d: I.bulb }]));
  const g0 = q ? I.play : I.pause, g1 = q ? I.play : I.power, c0 = q ? C.ok : C.nav, glyph = landed ? g1 : g0, gcol = landed ? (q ? C.ok : C.nav) : c0;
  let o = { col: gcol };
  if (v === 'today') {}
  else if (rd) { o.op = holding ? 1 - 0.3 * hp : 1; }
  else if (v === 'A') {
    if (holding || (early && t < REL + 200)) { const f = holding ? hp : 0.6 * (1 - pr(t, REL, 160)), id = c.id + 'f';
      kids.push(icoG(h, FX[3], FY, 20, {}, [pth(h, glyph, { col: gcol, op: 0.5 }), h('clipPath', { id }, h('rect', { x: -2, y: 22 - 20 * f, width: 28, height: 26 })), h('g', { clipPath: `url(#${id})` }, pth(h, glyph, { col: C.warm }))])); o = null; }
    else if (landed) { const s = 0.94 + 0.06 * sp(t, LAND, SP.pop); o.sx = o.sy = s; } }
  else if (v === 'B') { if (holding) o.sx = o.sy = 1 - 0.1 * E.io(hp); else if (landed) o.sx = o.sy = 0.9 + 0.1 * sp(t, LAND, SP.pop); else if (early && t >= REL) { const s0 = 1 - 0.1 * E.io(0.6); o.sx = o.sy = s0 + (1 - s0) * sp(t, REL, SP.snap); } }
  else { if (holding) { o.dy = 1.5 * E.io(hp); o.op = 1 - 0.25 * hp; } else if (landed) o.dy = 1.5 * (1 - sp(t, LAND, SP.snap)); else if (early && t >= REL) o.dy = 1.5 * E.io(0.6) * (1 - sp(t, REL, SP.snap)); }
  if (o) kids.push(Ic(h, glyph, FX[3], FY, 20, o));
  let ring = RG.rest();
  if (holding) ring = v === 'today' ? (hp > 0.15 ? RG.arc(hp, WARM, 1, 0.12 * (1 - hp)) : RG.rest()) : RG.blend(RG.rest(), RG.arc(hp, WARM, 1, 0), clamp(hp / 0.12));
  if (early && t >= REL) ring = v === 'today' ? RG.rest() : RG.blend(RG.arc(0.6, WARM, 1, 0.05), RG.rest(), pr(t, REL, 160, E.in));
  if (landed) { const fin = q ? RG.rest() : RG.arc(0.62, kel(3200), 0.34, 0), col = q ? GREEN : kel(3200), dur = q ? 600 : 450;
    ring = v === 'today' ? RG.blend(RG.fill(col, 0.68), fin, pr(t, LAND, dur, E.lin)) : RG.blend(RG.blend(RG.arc(1, WARM, 1, 0), fin, pr(t, LAND, 260, E.io)), RG.fill(col, 0.55), 0.7 * bloom(t, LAND, 140, dur)); if (v === 'C' && !rd) ring = RG.blend(ring, RG.over(ring, BOT, WARM, 1), bloom(t, LAND, 120, 480)); }
  const b = btns(); if (holding) b[3] = [WARM, 0.34 + 0.56 * hp]; if (landed) b[3] = [mixRGB(WARM, q ? GREEN : WW, pr(t, LAND, 300, E.io)), lerp(0.9, q ? 0.68 : 0.34, pr(t, LAND, 500, E.io))];
  return { ring, btns: b, kids };
}
P.push({ id: 'hold4', area: 'icons', title: 'Hold-4 progress and landing', brief: 'Hold 4 for 1.0 s. The ring arc is the timer (unchanged); the icon shows the pressure building and pops when the secondary action lands.',
  triggers: [{ id: 'swap', label: 'Hold 4 → swap to lights', dur: 1900, hap: [100, [1100, 1.4]] }, { id: 'queue', label: 'Hold 4 → Queued', dur: 1900, hap: [100, [1100, 1.4]] }, { id: 'early', label: 'Release at 0.6 s', dur: 1300, hap: [100] }],
  today: { name: 'Today', cost: 'Cheap', spec: spec('Warm ring arc fills over 1.0 s (from 15 %); glyph swaps on landing; ring wash 450–600 ms. Early release: arc disappears.', '1000 ms hold.', 'Linear fill', '—', 'LED 60 fps', 'Click on press; none on landing.', 'Same'), render: c => holdR(c, 'today') },
  variants: [
    { id: 'A', name: 'Fill-up + pop', rec: true, cost: 'Medium', spec: spec('Icon dims to 45 % and a warm copy fills it bottom-to-top with the hold. On landing it springs from 0.94 up to 1 with a ≈ 4 % overshoot, in its new form, while the ring blooms in the outcome colour. Early release drains the fill in 160 ms.', 'Fill = hold time; pop ≈ 300 ms.', 'Fill linear; pop ' + SP.pop.css, '12-frame fill strip + 6-frame swell per glyph (Pause, Play, Power ≈ 15 KB).', '30 fps; fill can step at 12 fps.', 'Strong click on the landing frame.'), render: c => holdR(c, 'A') },
    { id: 'B', name: 'Compress', cost: 'Costly', spec: spec('Icon eases down to 0.9 as pressure builds, springs back to 1 on landing.', 'Hold 1000 ms; release ≈ 350 ms.', 'E.io; release ' + SP.pop.css, 'Live scale is costly; as a strip it becomes Medium (10 frames).', '60 fps for the release.', 'Click on landing.'), render: c => holdR(c, 'B') },
    { id: 'C', name: 'Press-in', cost: 'Cheap', spec: spec('Icon sinks 1.5 px and dims to 75 % during the hold; settles back on landing while the 7 bottom ring LEDs bloom warm (120 ms up, 480 ms down).', 'Landing ≈ 600 ms.', SP.snap.css, 'None.', '30 fps', 'Click on landing, same frame as the ring pop.'), render: c => holdR(c, 'C') }
  ] });

function domainIconR(c, v) {
  const { h, t, trig } = c, { rd } = K(c), T0 = 100, toL = trig === 'toLights', dt = t - T0;
  const x = t < T0 ? 0 : v === 'today' ? 1 : pr(t, T0, 220); const lx = toL ? x : 1 - x;
  const kids = [npText(h, { lines: ['Remember'], op: 1 - lx }), T(h, 'LIGHTS', { y: 32, size: 12, col: C.sec, ls: 0.96, op: lx }), npText(h, { lines: ['Focus'], artist: 'Hall · 62% · 3200 K', op: lx }), footer(h, [{ d: I.music }, { d: I.win }, { d: I.bulb }])];
  const from = toL ? I.pause : I.power, to = toL ? I.power : I.pause;
  if (v === 'today') kids.push(Ic(h, t >= T0 ? to : from, FX[3], FY, 20));
  else if (rd) { const q = pr(t, T0, 160); kids.push(Ic(h, from, FX[3], FY, 20, { op: 1 - q }), Ic(h, to, FX[3], FY, 20, { op: q })); }
  else if (v === 'A') { const s = clamp(sp(t, T0, SP.snap)), m = toL ? s : 1 - s; const r = (x, y, w, hh) => `M${x} ${y}h${w}v${hh}h${-w}z`;
    kids.push(icoG(h, FX[3], FY, 20, {}, [pth(h, r(lerp(6, 11, m), lerp(4, 2, m), lerp(4, 2, m), lerp(16, 10, m)), { op: 1 - pr(m, 0.8, 0.2, E.lin) }), pth(h, I.stem, { op: pr(m, 0.8, 0.2, E.lin) }),
      pth(h, r(lerp(14, 12, m), lerp(4, 11, m), lerp(4, 0.01, m), lerp(16, 2, m)), { op: 1 - m }), pth(h, I.parc, { dash: m, op: pr(m, 0.05, 0.25, E.lin) })])); }
  else if (v === 'B') { const half = 110; if (t < T0 || dt < half) kids.push(Ic(h, from, FX[3], FY, 20, { sx: t < T0 ? 1 : Math.max(0.02, 1 - E.in(dt / half)) })); else kids.push(Ic(h, to, FX[3], FY, 20, { sx: Math.max(0.02, sp(t, T0 + half, SP.pop)) })); }
  else { const o = pr(t, T0, 100, E.in), n = sp(t, T0 + 60, SP.snap); kids.push(Ic(h, from, FX[3], FY, 20, { op: t < T0 ? 1 : 1 - o, dy: -2 * o }), t >= T0 ? Ic(h, to, FX[3], FY, 20, { op: pr(t, T0 + 40, 140), dy: 2 * (1 - n) }) : null); }
  const LR = RG.arc(0.62, kel(3200), 0.34, 0), ring = RG.blend(RG.rest(), LR, v === 'today' ? lx : lerp(toL ? 0 : 1, toL ? 1 : 0, pr(t, T0, 300)));
  return { ring, kids };
}
P.push({ id: 'domainicon', area: 'icons', title: 'Domain icon morph: Pause ⇄ Power', brief: 'When hold 4 swaps Home to Lights, button 4 changes job. The glyph should show that one thing became another, not that one was replaced.',
  triggers: [{ id: 'toLights', label: 'Swap to Lights', dur: 1000, hap: [[100, 1.4]] }, { id: 'toMusic', label: 'Swap to Music', dur: 1000, hap: [[100, 1.4]] }],
  today: { name: 'Today', cost: 'Cheap', spec: spec('Glyph swaps on the landing frame.', '0 ms', '—', '—', '—', 'Hold-landing click', 'Same'), render: c => domainIconR(c, 'today') },
  variants: [
    { id: 'A', name: 'Bar → stem', rec: true, cost: 'Medium', spec: spec('Left bar narrows and lifts into the power stem; right bar collapses; the power arc draws around from its ends.', '≈ 260 ms.', SP.snap.css, '12-frame strip each direction at 20 px (≈ 10 KB).', '30 fps', 'Landing click at t = 0.'), render: c => domainIconR(c, 'A') },
    { id: 'B', name: 'Flip', cost: 'Costly', spec: spec('Glyph flips edge-on (scaleX 1 → 0) and the new glyph flips out with overshoot.', '110 + 220 ms.', 'E.in then ' + SP.pop.css, 'Live scale costly; 10-frame strip makes it Medium.', '60 fps', 'Landing click at the edge-on frame (t = 110 ms).'), render: c => domainIconR(c, 'B') },
    { id: 'C', name: 'Slide swap', cost: 'Cheap', spec: spec('Old glyph fades drifting 2 px up, new one fades in from 2 px below.', '100 ms out, in from 40 ms, 140 ms fade.', 'E.in / ' + SP.snap.css, 'None.', '30 fps', 'Landing click at t = 0.'), render: c => domainIconR(c, 'C') }
  ] });

/* ============ 2. TEXT & NUMBERS ============ */
const DIG = {
  slow: { v0: 34, ev: [[100, 35], [500, 36], [900, 37]], cap: 'Volume', unit: '%' },
  fast: { v0: 34, ev: Array.from({ length: 18 }, (_, i) => [100 + i * 30, 35 + i]), cap: 'Volume', unit: '%' },
  hundred: { v0: 97, ev: [[100, 98], [450, 99], [800, 100]], cap: 'Volume', unit: '%' },
  kelvin: { v0: 32, ev: [[100, 33], [450, 34], [800, 35]], cap: 'Colour temperature', unit: 'K', suffix: '00', kel: true }
};
function digitsR(c, v) {
  const { h, t, trig } = c, { rd } = K(c), d = DIG[trig], tg = tgOf(d.ev, d.v0), cur = lastEv(d.ev, t, d.v0);
  const DW = 30, DH = 58, BY = 72, kids = [T(h, d.cap, { y: 52, size: 14, col: C.sec })], id = c.id + 'n';
  const cols = []; let cw;
  const colsFromPos = pos => { const out = []; for (let k = 0; k < 4; k++) { const p = pos[k]; if (p == null) break; out.push(p); } return out; };
  const glyphsRoll = (p, lead) => { const fl = Math.floor(p), f = p - fl, d0 = ((fl % 10) + 10) % 10, d1 = (d0 + 1) % 10; return [{ ch: d0, dy: -f * DH, op: lead && fl <= 0 ? 0 : 1 }, { ch: d1, dy: (1 - f) * DH, op: 1 }]; };
  if (v === 'today' || (rd && v !== 'C')) { const s = String(cur.v); s.split('').reverse().forEach((ch, k) => cols.push([{ ch, dy: 0, op: 1 }])); cw = s.length; }
  else if (v === 'A' || v === 'B') {
    const pos = [];
    for (let k = 0; k < 4; k++) { const P10 = Math.pow(10, k);
      if (v === 'A') { const x = follow(tg, t, SP.crit, 0, 'dA' + trig); if (k === 0) pos.push(x); else { const base = Math.floor(x / P10), rem = x - base * P10; pos.push(base + clamp(rem - (P10 - 1))); } }
      else pos.push(follow(s => Math.floor(tg(s) / P10), t, SP.roll, k * 30, 'dB' + trig + k)); }
    let lead = 0; pos.forEach((p, k) => { if (k === 0 || p > 0.001) lead = k; });
    for (let k = 0; k <= lead; k++) cols.push(glyphsRoll(pos[k], k > 0 && k === lead));
    cw = lead + (lead > 0 ? clamp(pos[lead]) : 1);
  } else {
    const s = String(cur.v), n = s.length; cw = n;
    for (let k = 0; k < n; k++) { const P10 = Math.pow(10, k), dn = Math.floor(cur.v / P10) % 10; let lastT = -1e9, od = dn;
      let pv = d.v0; for (const [tt, vv] of d.ev) { if (tt > t) break; const a = Math.floor(pv / P10) % 10, b = Math.floor(vv / P10) % 10; if (a !== b || (pv < P10) !== (vv < P10)) { lastT = tt; od = pv < P10 ? -1 : a; } pv = vv; }
      const q = pr(t, lastT, 140); cols.push(q < 1 ? [od >= 0 ? { ch: od, dy: rd ? 0 : -6 * q, op: 1 - q } : null, { ch: dn, dy: rd ? 0 : 6 * (1 - q), op: q }].filter(Boolean) : [{ ch: dn, dy: 0, op: 1 }]); } }
  const suffix = d.suffix || '', uw = tw(d.unit, 22) + 4, W = (cw + suffix.length) * DW + uw, left = 120 - W / 2;
  kids.push(h('clipPath', { id }, h('rect', { x: 0, y: BY + 4, width: 240, height: 44 })));
  const g = [];
  cols.forEach((glyphs, k) => { const cx = left + (cw - 1 - k + 0.5) * DW; glyphs.forEach(gl => g.push(T(h, String(gl.ch), { x: cx, y: BY + 2, size: 48, dy: gl.dy, op: gl.op, ls: -0.5 }))); });
  suffix.split('').forEach((ch, j) => g.push(T(h, ch, { x: left + (cw + j + 0.5) * DW, y: BY + 2, size: 48 })));
  kids.push(h('g', { clipPath: `url(#${id})` }, ...g.filter(Boolean)));
  kids.push(T(h, d.unit, { x: left + (cw + suffix.length) * DW + 4, y: BY + 22, size: 22, col: C.sec, anchor: 'start' }));
  const shown = v === 'A' && !rd ? follow(tg, t, SP.crit, 0, 'dA' + trig) : cur.v;
  const ring = d.kel ? RG.arc((shown * 100 - 2200) / 4300, kel(shown * 100), 1, 0) : RG.arc(shown / 100, WARM, 1, 0.08);
  return { ring, kids };
}
P.push({ id: 'digits', area: 'text', title: 'Rolling digits', brief: 'Volume, brightness and Kelvin in the 48 px big-value layout. Digits sit in fixed 30 px tabular columns; only the leading column can appear, and the block recentres smoothly instead of jumping.',
  triggers: [{ id: 'slow', label: '3 slow detents', dur: 1500, hap: [100, 500, 900] }, { id: 'fast', label: 'Fast spin +18', dur: 1300, hap: DIG.fast.ev.map(e => e[0]) }, { id: 'hundred', label: '99 → 100', dur: 1500, hap: [100, 450, 800] }, { id: 'kelvin', label: '3200 → 3500 K', dur: 1500, hap: [100, 450, 800] }],
  today: { name: 'Today', cost: 'Cheap', spec: spec('Label text replaced on each detent.', '0 ms', '—', '—', '—', 'Detent', 'Same'), render: c => digitsR(c, 'today') },
  variants: [
    { id: 'A', name: 'Odometer', rec: true, cost: 'Cheap', spec: spec('A single value follows the knob with a critically damped spring; the ones column rolls continuously and each higher column rolls only while the column below passes 9 → 0, like a mechanical counter. On a fast spin the value glides through the numbers and catches up; nothing queues.', 'Settles ≈ 300 ms after the last detent.', SP.crit.css, 'None: each column is a clipped container holding 2 digit labels moved by y. Font: pre-rendered 48 px tabular digits 0–9.', '60 fps matters for the fast spin; 30 fps is fine for slow detents.', 'Detent click at the moment the target changes, not when the roll finishes.'), render: c => digitsR(c, 'A') },
    { id: 'B', name: 'Slot machine', cost: 'Cheap', spec: spec('Each column springs to its own new digit; tens start 30 ms after ones, hundreds 60 ms, so a carry ripples leftwards.', '≈ 350 ms per column.', SP.roll.css + ' · column delay 30 ms', 'None (same clipped columns).', '60 fps', 'Detent click at t = 0 of each detent.'), render: c => digitsR(c, 'B') },
    { id: 'C', name: 'Tick', cost: 'Cheap', spec: spec('Only digits that changed move: old digit leaves 6 px up and fades, new arrives from 6 px below.', '140 ms.', 'E.out ' + E.out.css, 'None.', '30 fps', 'Detent click at t = 0.', 'Opacity-only digit crossfade 140 ms.'), render: c => digitsR(c, 'C') }
  ] });

const TR = { next: { a: [['Long Range'], 'Air'], b: [['So What'], 'Oskar Lind Trio'] }, long: { a: [['Remember'], 'Air'], b: [['Kelly Watch', 'the Stars'], 'Air'] } };
function trackR(c, v) {
  const { h, t, trig } = c, { rd } = K(c), T0 = 150, d = TR[trig], kids = [], dt = t - T0;
  const lines = (L, artist, f) => [...L.map((l, i) => f(l, { y: 60 + i * 26, size: 22 }, i)), f(artist, { y: 114, size: 14, col: C.sec }, L.length)];
  if (v === 'today' || t < T0) kids.push(...lines(t < T0 ? d.a[0] : d.b[0], t < T0 ? d.a[1] : d.b[1], (s, o) => T(h, s, o)));
  else if (rd) { const q = pr(t, T0, 160); kids.push(...lines(d.a[0], d.a[1], (s, o) => T(h, s, Object.assign(o, { op: 1 - q }))), ...lines(d.b[0], d.b[1], (s, o) => T(h, s, Object.assign(o, { op: q })))); }
  else if (v === 'A') { kids.push(...lines(d.a[0], d.a[1], (s, o, i) => { const q = pr(t, T0, 120, E.in); return T(h, s, Object.assign(o, { op: 1 - q, dy: -3 * q })); }));
    kids.push(...lines(d.b[0], d.b[1], (s, o, i) => { const st = T0 + 80 + i * 30; return T(h, s, Object.assign(o, { op: pr(t, st, 220), dy: 5 * (1 - sp(t, st, SP.soft)) })); })); }
  else if (v === 'B') { let n = 0; const mk = (s, o, i, out) => { const id = c.id + 'w' + (out ? 'o' : 'i') + i; const st = out ? T0 + i * 30 : T0 + 120 + i * 60; const p = out ? pr(t, st, 140, E.in) : pr(t, st, 240); n++;
      const x = out ? 25 + 190 * p : 25, w = out ? 190 * (1 - p) : 190 * p; return [h('clipPath', { id }, h('rect', { x, y: o.y - 4, width: Math.max(0, w), height: o.size + 12 })), T(h, s, Object.assign(o, { clip: `url(#${id})` }))]; };
    kids.push(...lines(d.a[0], d.a[1], (s, o, i) => mk(s, o, i, true)), ...lines(d.b[0], d.b[1], (s, o, i) => mk(s, o, i, false))); }
  else { const fo = c.id + 'bo', fi = c.id + 'bi', qo = pr(t, T0, 160), qi = pr(t, T0 + 100, 260);
    kids.push(h('filter', { id: fo, x: '-20%', y: '-50%', width: '140%', height: '200%' }, h('feGaussianBlur', { stdDeviation: 6 * qo })), h('filter', { id: fi, x: '-20%', y: '-50%', width: '140%', height: '200%' }, h('feGaussianBlur', { stdDeviation: 6 * (1 - qi) })));
    kids.push(...lines(d.a[0], d.a[1], (s, o) => T(h, s, Object.assign(o, { op: 1 - qo, filter: `url(#${fo})` }))), ...lines(d.b[0], d.b[1], (s, o) => T(h, s, Object.assign(o, { op: qi, filter: `url(#${fi})` })))); }
  kids.push(footer(h, [{ d: I.home }, { d: I.album }, { d: I.list }, { d: I.pause }]));
  return { ring: RG.rest(), kids };
}
P.push({ id: 'track', area: 'text', title: 'Track change', brief: 'Title and artist on Home and Music when the song changes. The old text clears first; the new text arrives line by line so the eye reads title, then artist.',
  triggers: [{ id: 'next', label: 'Next track', dur: 1200 }, { id: 'long', label: '→ two-line title', dur: 1200 }],
  today: { name: 'Today', cost: 'Cheap', spec: spec('Text replaced on the frame the metadata arrives.', '0 ms', '—', '—', '—', 'None', 'Same'), render: c => trackR(c, 'today') },
  variants: [
    { id: 'A', name: 'Stagger slide', rec: true, cost: 'Cheap', spec: spec('Old lines fade together drifting 3 px up. New lines rise 5 px into place, 30 ms apart, from 80 ms.', 'Out 120 ms · in ≈ 500 ms total.', 'Out E.in · in ' + SP.soft.css, 'None.', '30 fps', 'None (not user-initiated).'), render: c => trackR(c, 'A') },
    { id: 'B', name: 'Line wipe', cost: 'Cheap', spec: spec('Each line is revealed left-to-right by its container\'s width (object clip, no mask); old lines wipe out to the right first.', 'Out 140 ms · in 240 ms per line, 60 ms stagger.', 'E.in / E.out', 'None. Uses the label container\'s own clip area.', '30 fps', 'None.'), render: c => trackR(c, 'B') },
    { id: 'C', name: 'Blur settle', cost: 'Costly', spec: spec('New text comes into focus from a 6 px blur while the old text blurs out.', '160 / 260 ms.', 'E.out', 'Not pre-renderable for dynamic text; per-frame blur of each label.', '30 fps at best on device.', 'None.'), render: c => trackR(c, 'C') }
  ] });

function longR(c, v) {
  const { h, t } = c, { rd } = K(c), title = 'Copper Sun Sessions', kids = [], id = c.id + 'm', gid = c.id + 'g';
  const mode = rd && v === 'A' ? 'B' : v;
  if (mode === 'today') kids.push(T(h, 'Copper Sun ou', { y: 60, size: 22 }), T(h, 'Panis et Circen…', { y: 86, size: 22 }));
  else if (mode === 'A') { const W = tw(title, 22), gap = 48, speed = 0.05, hold = 1500, cyc = (W + gap) / speed; const run = Math.max(0, t - hold), off = run >= cyc ? 0 : run * speed;
    kids.push(h('clipPath', { id }, h('rect', { x: 30, y: 60, width: 180, height: 30 })), h('g', { clipPath: `url(#${id})` }, T(h, title, { x: 30 - off, y: 64, size: 22, anchor: 'start' }), T(h, title, { x: 30 - off + W + gap, y: 64, size: 22, anchor: 'start' })));
    kids.push(h('linearGradient', { id: gid + 'l', x1: 0, x2: 1 }, h('stop', { offset: 0, stopColor: '#000' }), h('stop', { offset: 1, stopColor: '#000', stopOpacity: 0 })), h('linearGradient', { id: gid + 'r', x1: 0, x2: 1 }, h('stop', { offset: 0, stopColor: '#000', stopOpacity: 0 }), h('stop', { offset: 1, stopColor: '#000' })));
    if (off > 0) kids.push(h('rect', { x: 30, y: 60, width: 16, height: 30, fill: `url(#${gid}l)` })); kids.push(h('rect', { x: 194, y: 60, width: 16, height: 30, fill: `url(#${gid}r)`, opacity: run >= cyc - 300 ? 1 - pr(t, hold + cyc - 300, 300) : 1 })); }
  else if (mode === 'B') { kids.push(T(h, 'Copper Sun ou', { y: 60, size: 22 }), h('clipPath', { id }, h('rect', { x: 35, y: 84, width: 170, height: 30 })), h('g', { clipPath: `url(#${id})` }, T(h, 'Panis et Circencis', { x: 35, y: 86, size: 22, anchor: 'start' })),
    h('linearGradient', { id: gid, x1: 0, x2: 1 }, h('stop', { offset: 0, stopColor: '#000', stopOpacity: 0 }), h('stop', { offset: 1, stopColor: '#000' })), h('rect', { x: 181, y: 84, width: 26, height: 30, fill: `url(#${gid})` })); }
  else { const ph = Math.floor(t / 3000) % 2, q = pr(t % 3000, 0, 300), a = ph === 0 ? [['Copper Sun ou', 'Panis et'], ['Circencis', '']] : [['Circencis', ''], ['Copper Sun ou', 'Panis et']];
    const [nw, ol] = a; const fade = t < 300 ? 1 : q; if (t >= 300) ol.forEach((l, i) => kids.push(T(h, l, { y: 60 + i * 26, size: 22, op: 1 - fade })));
    nw.forEach((l, i) => kids.push(T(h, l, { y: 60 + i * 26, size: 22, op: fade }))); kids.push(T(h, `${ph + 1} / 2`, { y: 134, size: 12, col: C.meta })); }
  kids.push(T(h, 'Various artists', { y: 114, size: 14, col: C.sec }), footer(h, [{ d: I.home }, { d: I.album }, { d: I.list }, { d: I.pause }]));
  return { ring: RG.rest(), kids };
}
P.push({ id: 'longtitle', area: 'text', title: 'Long titles', brief: 'Titles longer than two lines at 22 px. The knob is glanced at, not read, so the question is how much motion a long title may cost.',
  triggers: [{ id: 'play', label: 'Long title arrives', dur: 12000 }],
  today: { name: 'Today', cost: 'Cheap', spec: spec('2-line clamp with an ellipsis.', '—', '—', '—', '—', 'None', 'Same'), render: c => longR(c, 'today') },
  variants: [
    { id: 'A', name: 'Marquee', cost: 'Cheap', spec: spec('Single line. Holds 1.5 s, then scrolls left at 50 px/s with a 48 px gap and loops once, then rests at the start. 16 px black fade bitmaps at both edges.', 'Hold 1500 ms · ≈ 9.5 s scroll.', 'Linear', 'Two 16 × 30 px fade bitmaps (≈ 1 KB).', '30 fps (1.7 px per frame).', 'None.', 'No scrolling: falls back to B (fade-truncate).'), render: c => longR(c, 'A') },
    { id: 'B', name: 'Fade-truncate', rec: true, cost: 'Cheap', spec: spec('Two balanced lines, no motion. Line 2 runs under a 26 px fade instead of an ellipsis.', 'Static.', '—', 'One 26 × 30 px fade bitmap.', '—', 'None.', 'Same'), render: c => longR(c, 'B') },
    { id: 'C', name: 'Pages', cost: 'Cheap', spec: spec('Title split into 2-line pages that crossfade every 3 s; page count in the meta line.', '300 ms crossfade every 3000 ms.', 'E.out', 'None.', '30 fps', 'None.'), render: c => longR(c, 'C') }
  ] });

const ST = { paused: ['Paused', C.sec], queued: ['Queued · Midnight Arcade', C.succ], knob: ['Knob sets brightness', C.warm] };
function statusR(c, v) {
  const { h, t, trig } = c, { rd } = K(c), [txt, col] = ST[trig], IN = 100, OUT = 2000, kids = [npText(h, {})];
  let op = 0, dx = 0, dy = 0;
  if (v === 'today') op = t >= IN && t < OUT ? 1 : 0;
  else if (rd) op = pr(t, IN, 160) * (1 - pr(t, OUT, 160));
  else if (v === 'A') { op = pr(t, IN, 220) * (1 - pr(t, OUT, 160, E.in)); dy = 4 * (1 - sp(t, IN, SP.soft)); }
  else if (v === 'B') { op = pr(t, IN, 180) * (1 - pr(t, OUT, 140)); dx = 0.2 * (FX[3] - 120) * (1 - sp(t, IN, SP.soft)); }
  else op = pr(t, IN, 120) * (1 - pr(t, OUT, 160));
  kids.push(T(h, txt, { y: 134, size: 12, col, op, dx, dy }), footer(h, [{ d: I.home }, { d: I.album }, { d: I.list }, { d: trig === 'paused' ? I.play : I.pause, col: trig === 'paused' ? C.ok : C.nav }]));
  let ring = RG.rest(); const lrgb = trig === 'queued' ? GREEN : trig === 'knob' ? WARM : WW;
  if (v === 'C' && !rd) ring = RG.blend(ring, RG.over(ring, [28, 29, 30, 31, 32], lrgb, 0.8), bloom(t, IN, 160, 600));
  return { ring, kids };
}
P.push({ id: 'status', area: 'text', title: 'Status lines', brief: 'The 12 px meta line under the artist. It should arrive with intent, hold long enough to read, and leave without drawing the eye back.',
  triggers: [{ id: 'paused', label: 'Paused', dur: 2500, hap: [100] }, { id: 'queued', label: 'Queued · {title}', dur: 2500, hap: [[100, 1.4]] }, { id: 'knob', label: 'Knob sets brightness', dur: 2500, hap: [[100, 1.4]] }],
  today: { name: 'Today', cost: 'Cheap', spec: spec('Appears and disappears on the frame.', 'Hold 1.4–2.2 s (copy-dependent).', '—', '—', '—', '—', 'Same'), render: c => statusR(c, 'today') },
  variants: [
    { id: 'A', name: 'Rise · hold · sink', rec: true, cost: 'Cheap', spec: spec('Enters rising 4 px with a critically damped settle; exits with a plain fade.', 'In 220 ms (settle ≈ 450) · hold · out 160 ms.', 'In ' + SP.soft.css + ' · out E.in', 'None.', '30 fps', 'The status is a result: no click of its own.'), render: c => statusR(c, 'A') },
    { id: 'B', name: 'From the button', cost: 'Cheap', spec: spec('Drifts in 13 px from the side of the footer slot that caused it (button 4 → from the right); fades out in place.', 'In ≈ 450 ms · out 140 ms.', SP.soft.css, 'None.', '30 fps', '—'), render: c => statusR(c, 'B') },
    { id: 'C', name: 'Ring tick', cost: 'Cheap', spec: spec('Plain fade on screen, while the 5 LEDs at the bottom of the ring bloom in the status colour (160 ms up, 600 ms down).', 'In 120 · out 160 ms.', 'E.out', 'None.', 'LED 60 fps.', '—'), render: c => statusR(c, 'C') }
  ] });

function crumbR(c, v) {
  const { h, t, trig } = c, { rd } = K(c), T0 = 100, deep = trig === 'deeper', dir = deep ? 1 : -1;
  const A = deep ? ['', 'MUSIC'] : ['MUSIC › ', 'TRACKS'], B = deep ? ['MUSIC › ', 'TRACKS'] : ['', 'MUSIC'], kids = [];
  const x = t < T0 ? 0 : v === 'today' ? pr(t, T0, 150) : pr(t, T0, 200);
  kids.push(listText(h, { prev: '2 · Long Range', cur: '3 · Afterburn', next: '4 · Kelly Watch the Stars', meta: 'Turn to browse the queue', op: deep ? x : 1 - x }), npText(h, { lines: ['Afterburn'], op: deep ? 1 - x : x }));
  if (v === 'today') kids.push(crumb(h, c.id + 'a', A[0], A[1], { op: 1 - pr(t, T0, 150) }), crumb(h, c.id + 'b', B[0], B[1], { op: pr(t, T0, 150) }));
  else if (rd) kids.push(crumb(h, c.id + 'a', A[0], A[1], { op: 1 - pr(t, T0, 160) }), crumb(h, c.id + 'b', B[0], B[1], { op: pr(t, T0, 160) }));
  else if (v === 'A') { const o = pr(t, T0, 140, E.in); kids.push(crumb(h, c.id + 'a', A[0], A[1], { op: 1 - o, dy: -3 * dir * o }), crumb(h, c.id + 'b', B[0], B[1], { op: pr(t, T0 + 60, 160), dy: 3 * dir * (1 - sp(t, T0 + 60, SP.snap)) })); }
  else if (v === 'B') { const o = pr(t, T0, 160, E.in); kids.push(crumb(h, c.id + 'a', A[0], A[1], { op: 1 - o, rot: -5 * dir * o }), crumb(h, c.id + 'b', B[0], B[1], { op: pr(t, T0 + 40, 180), rot: 5 * dir * (1 - sp(t, T0 + 40, SP.soft)) })); }
  else { const pid = c.id + 'p'; kids.push(h('path', { id: pid, d: ARC, fill: 'none' }));
    const cw = ch => tw(ch, 12) + 0.96, lay = s => { const W = s.split('').reduce((a, ch) => a + cw(ch), 0); let x0 = ARCLEN / 2 - W / 2; return s.split('').map(ch => { const o = x0; x0 += cw(ch); return o; }); };
    const full = (deep ? B : A).join(''), short = 'MUSIC', Lf = lay(full), Ls = lay(short), m = deep ? sp(t, T0, SP.snap) : 1 - sp(t, T0, SP.snap);
    full.split('').forEach((ch, i) => { let off, op, col;
      if (i < 5) { off = lerp(Ls[i], Lf[i], m); op = 1; col = mixHex(C.nav, C.meta, clamp(m)); }
      else { const st = deep ? T0 + 60 + (i - 5) * 8 : T0; const q = deep ? sp(t, st, SP.snap) : 1 - pr(t, T0 + (full.length - i) * 10, 120, E.in); off = Lf[i] + 4 * (1 - clamp(q)); op = deep ? pr(t, st, 140) : q; col = C.nav; }
      if (op > 0.01) kids.push(h('text', { key: i, fontFamily: FONT, fontSize: 12, fontWeight: 500, fill: col, opacity: clamp(op) }, h('textPath', { href: '#' + pid, startOffset: off }, ch))); }); }
  kids.push(footer(h, [{ d: deep ? I.home : I.back, op: 1 }, { d: I.expand }, { d: I.list }, { d: I.play, col: C.ok }]));
  return { ring: RG.rest(), kids };
}
P.push({ id: 'crumb', area: 'text', title: 'Arc breadcrumb', brief: 'The pre-rendered crumb along the top arc. Depth should be felt: deeper pushes outwards, back pulls in.',
  triggers: [{ id: 'deeper', label: 'MUSIC → MUSIC › TRACKS', dur: 1000, hap: [100] }, { id: 'back', label: 'Back to MUSIC', dur: 1000, hap: [100] }],
  today: { name: 'Today', cost: 'Cheap', spec: spec('Crumb crossfades 150 ms.', '150 ms', 'ease', '1 bitmap per path', '30 fps', '—', 'Same'), render: c => crumbR(c, 'today') },
  variants: [
    { id: 'A', name: 'Radial crossfade', rec: true, cost: 'Cheap', spec: spec('Deeper: old crumb fades moving 3 px outwards, new one arrives from 3 px inside. Back: mirrored.', 'Out 140 ms · in 160 ms from 60 ms.', SP.snap.css, '1 A8 bitmap per crumb path (≈ 190 × 20 px, 3.8 KB), as today.', '30 fps', 'Button click only.'), render: c => crumbR(c, 'A') },
    { id: 'B', name: 'Slide along the arc', cost: 'Medium', spec: spec('Old crumb turns 5° away round the arc and fades; new one turns in from the other side (deeper = from the right).', '≈ 450 ms.', SP.soft.css, 'Rotation is costly live; 8 pre-rotated frames per crumb (≈ 30 KB each) make it Medium. Flash budget grows with the number of paths (≈ 12).', '30 fps', '—'), render: c => crumbR(c, 'B') },
    { id: 'C', name: 'Letters settle', cost: 'Costly', spec: spec('Shared prefix stays: MUSIC slides left along the arc and dims to grey; "› TRACKS" letters arrive 8 ms apart, each sliding 4 px along the path. Back reverses.', '≈ 400 ms.', SP.snap.css + ' per letter', 'Per-glyph placement on the arc every frame (vector text on a curve).', '60 fps', '—'), render: c => crumbR(c, 'C') }
  ] });

function bigR(c, v) {
  const { h, t, trig } = c, { rd } = K(c);
  const S0 = trig === 'stop' ? -1 : 100, E0 = trig === 'start' ? 1e9 : trig === 'stop' ? 100 : 2150;
  const ev = trig === 'cycle' ? [[300, 63], [450, 64], [600, 65], [750, 66]] : [], val = lastEv(ev, t, 62).v;
  let tx = 1, big = 0; const kids = [], R = {};
  const bIn = t >= S0 && S0 >= 0, bOut = t >= E0;
  if (v === 'today') { const inq = bIn ? pr(t, S0 + 50, 180) : trig === 'stop' ? 1 : 0, outq = bOut ? pr(t, E0, 170, E.in) : 0; big = inq * (1 - outq); R.bdy = 6 * (1 - E.spr(clamp((t - S0 - 50) / 340))); tx = bIn && !bOut ? 1 - pr(t, S0, 150, E.in) : bOut ? pr(t, E0 + 90, 320) : trig === 'stop' ? 0 : 1; R.cap = big; R.unit = big; R.tdy = bIn && !bOut ? -8 * pr(t, S0, 190, E.in) : bOut ? -8 * (1 - pr(t, E0 + 90, 420)) : 0; }
  else if (rd || v === 'C') { const d = v === 'C' && !rd ? 80 : 0, inq = bIn ? pr(t, S0 + d, 160) : trig === 'stop' ? 1 : 0, outq = bOut ? pr(t, E0, 160) : 0; big = inq * (1 - outq); R.cap = big; R.unit = big; R.bdy = 0; R.tdy = 0; tx = bIn && !bOut ? 1 - pr(t, S0, 120) : bOut ? pr(t, E0 + 60, 200) : trig === 'stop' ? 0 : 1; }
  else if (v === 'A') { const inq = t => (bIn ? t : trig === 'stop' ? 1 : 0);
    R.cap = inq(pr(t, S0, 120)) * (1 - (bOut ? pr(t, E0 + 30, 100) : 0)); big = inq(pr(t, S0 + 40, 160)) * (1 - (bOut ? pr(t, E0, 120) : 0)); R.unit = inq(pr(t, S0 + 70, 160)) * (1 - (bOut ? pr(t, E0, 100) : 0));
    R.bdy = bOut ? 4 * pr(t, E0, 120) : 6 * (1 - sp(t, S0 + 40, SP.snap)); tx = bIn && !bOut ? 1 - pr(t, S0, 120, E.in) : bOut ? pr(t, E0 + 80, 200) : trig === 'stop' ? 0 : 1; R.tdy = bIn && !bOut ? -6 * pr(t, S0, 120, E.in) : bOut ? -6 * (1 - sp(t, E0 + 80, SP.soft)) : 0; }
  else { const m = bIn && !bOut ? sp(t, S0, SP.snap) : bOut ? 1 - sp(t, E0, SP.snap) : trig === 'stop' ? 1 : 0, mm = clamp(m);
    kids.push(T(h, String(val), { x: lerp(96, 112, mm), y: lerp(114, 72, m), size: lerp(14, 48, m), op: 1, anchor: 'middle' }));
    R.cap = pr(mm, 0.5, 0.5, E.lin); R.unit = R.cap; tx = 1 - pr(mm, 0, 0.4, E.lin); R.bdy = 0; R.tdy = 0; big = -1; }
  kids.push(T(h, 'LIGHTS', { y: 32, size: 12, col: C.sec, ls: 0.96 }));
  kids.push(G(h, [T(h, 'Focus', { y: 60, size: 22 }), v === 'B' && !rd ? T(h, '· 3200 K', { x: 132, y: 114, size: 14, col: C.sec }) : T(h, `${val}% · 3200 K`, { y: 114, size: 14, col: C.sec })], { opacity: clamp(tx), transform: `translate(0 ${R.tdy})` }));
  kids.push(T(h, 'Brightness', { y: 52, size: 14, col: C.sec, op: R.cap }));
  const bcx = 120 + (tw(String(val), 48) - tw('%', 22) - 4) / 2;
  if (big >= 0) kids.push(T(h, String(val), { x: bcx, y: 72, dy: R.bdy, size: 48, anchor: 'end', op: big }), T(h, '%', { x: bcx + 4, y: 92, dy: R.bdy, size: 22, col: C.sec, anchor: 'start', op: R.unit }));
  else kids.push(T(h, '%', { x: bcx + 4, y: 92, size: 22, col: C.sec, anchor: 'start', op: R.unit }));
  kids.push(footer(h, [{ d: I.home }, { d: I.wand }, { d: I.temp }, { d: I.power }]));
  const bigAmt = clamp(R.cap || 0); let hi = lerp(0.34, 1, bigAmt);
  if (v === 'C' && !rd) hi = bIn && !bOut ? lerp(0.34, 1, pr(t, S0, 100)) : bOut ? lerp(1, 0.34, pr(t, E0, 300)) : trig === 'stop' ? 1 : 0.34;
  return { ring: RG.arc(val / 100, kel(3200), hi, 0), kids };
}
P.push({ id: 'bigvalue', area: 'text', title: 'Big value reveal', brief: 'Turning in Lights (or volume on Home) swaps the text layout for the 48 px value; 1.4 s after the last detent it swaps back.',
  triggers: [{ id: 'start', label: 'Turning starts', dur: 900, hap: [100] }, { id: 'stop', label: 'Turning stops', dur: 900 }, { id: 'cycle', label: 'Full cycle', dur: 2700, hap: [100, 300, 450, 600, 750] }],
  today: { name: 'Today', cost: 'Cheap', spec: spec('Text: fade 150 ms + 8 px lift. Value: fade 180 ms (50 ms delay) + 6 px rise on an overshooting bezier. Exit: value 170 ms; text back after 90 ms, 320 ms.', '≈ 400 ms each way.', E.spr.css, '—', '30 fps', 'Detent', 'Same'), render: c => bigR(c, 'today') },
  variants: [
    { id: 'A', name: 'Choreographed', rec: true, cost: 'Cheap', spec: spec('Caption first, number 40 ms later rising 6 px, unit 70 ms later; the old text lifts away. Exit is quicker and reversed: number and unit first, caption 30 ms after, text settles back from above.', 'In ≈ 350 ms · out ≈ 300 ms.', 'In ' + SP.snap.css + ' · text back ' + SP.soft.css, 'None.', '30 fps', 'First detent click at t = 0: the value appears under the finger.'), render: c => bigR(c, 'A') },
    { id: 'B', name: 'Grow from the sub line', cost: 'Costly', spec: spec('The "62%" in the sub line travels up and grows into the 48 px number (shared element); caption and unit fade in behind it.', '≈ 330 ms.', SP.snap.css, 'Per-frame text scaling from 14 → 48 px.', '60 fps', 'Click at t = 0.'), render: c => bigR(c, 'B') },
    { id: 'C', name: 'Ring leads', cost: 'Cheap', spec: spec('The ring arc brightens to full first (100 ms); the value fades in 80 ms later without moving. Exit: ring dims over 300 ms while the value fades.', 'In 240 ms · out 300 ms.', 'E.out', 'None.', 'LED 60 fps; screen 30 fps.', 'Click with the ring brightening.'), render: c => bigR(c, 'C') }
  ] });

/* ============ 3. SCREENS ============ */
const ALB = ['Promises', 'Night Channel', 'Glass Weather', 'Midnight Arcade', 'Paper Lanterns', 'Lua & Mar', 'Neon Littoral', 'Copper Sun', 'Tidal Glass'];
const ART = ['Harbour Signals', 'Velvet Circuit', 'Lumen Park', 'Air', 'Mira Vale', 'Lua Serena', 'Lumen Park', 'Various artists', 'Oskar Lind Trio'];
const LISTEV = { slow: { i0: 2, ev: [[100, 3], [500, 4], [900, 5]] }, fast: { i0: 1, ev: Array.from({ length: 6 }, (_, i) => [100 + i * 35, 2 + i]) }, end: { i0: 7, ev: [[100, 8]], block: [400, 650] } };
function listPos(trig, t, f) { const d = LISTEV[trig], tg = tgOf(d.ev, d.i0); const tgr = s => { let v = tg(s); for (const b of d.block || []) if (s >= b && s < b + 80) v = 8.15; return v; }; return f ? follow(tgr, t, f, 0, 'L' + trig) : tg(t); }
function listR(c, v) {
  const { h, t, trig } = c, { rd } = K(c), d = LISTEV[trig], kids = [crumb(h, c.id + 'c', 'MUSIC › ', 'RECENTLY ADDED')];
  const idx = listPos(trig, t), row = 26, CY = 89;
  let pos = v === 'A' || v === 'B' ? listPos(trig, t, SP.list) : idx; if (rd) pos = idx;
  if (v === 'today' || rd) kids.push(listText(h, { prev: idx > 0 ? ALB[idx - 1] : '', cur: ALB[idx], next: idx < 8 ? ALB[idx + 1] : '', op: 1 }));
  else if (v === 'A') { for (let i = 0; i < 9; i++) { const dd = i - pos, ad = Math.abs(dd); if (ad > 2) continue; const op = ad < 0.6 ? 0 : clamp(ad < 1 ? (ad - 0.6) / 0.4 : 1) * clamp((1.9 - ad) / 0.5); kids.push(T(h, ALB[i], { y: CY + dd * row - 7 + (dd > 0 ? 4 : 0), size: 14, col: C.meta, op })); }
    const fi = Math.round(clamp(pos, 0, 8)); let tc = -1e9, prevI = fi; for (let s = 0; s <= t; s += 8) { const r = Math.round(clamp(listPos(trig, s, spring(520, 30)), 0, 8)); if (r !== prevI && s > 0) { tc = s; } prevI = r; }
    const q = pr(t, tc, 160); kids.push(T(h, ALB[fi], { y: 78, size: 22, op: q })); }
  else if (v === 'B') { for (let i = 0; i < 9; i++) { const dd = i - pos, ad = Math.abs(dd); if (ad > 2) continue; const m = Math.min(1, ad), size = 22 - 8 * m; kids.push(T(h, ALB[i], { y: CY + dd * row + Math.sign(dd) * 4 * m - size * 0.62, size, col: mixHex(C.ink, C.meta, m), op: clamp((1.9 - ad) / 0.5) })); } }
  else { const ev = lastEv(d.ev, t, d.i0), q = pr(t, ev.at, 200), dir = Math.sign(ev.v - ev.prev) || 1; kids.push(listText(h, { prev: idx > 0 ? ALB[idx - 1] : '', cur: ALB[idx], next: idx < 8 ? ALB[idx + 1] : '', op: 0.55 + 0.45 * q, dy: 6 * dir * (1 - q) })); }
  const fi = Math.round(clamp(pos, 0, 8)); kids.push(T(h, `${fi + 1} / 9 · ${ART[fi]}`, { y: 134, size: 12, col: C.meta }), footer(h, [{ d: I.back }, { d: I.expand }, { d: I.listMusic }, { d: I.play, col: C.ok }]));
  let ring = RG.marker(9, clamp(pos, 0, 8.3), [60, 170, 255]);
  if (v === 'C' && d.block) { const g = Math.max(...d.block.map(b => bloom(t, b, 120, 480))); if (g > 0) ring = RG.blend(ring, RG.over(ring, BOT, RED, 0.7), g); }
  return { ring, btns: btns({ 3: [GREEN, 0.68] }), kids };
}
const listHap = (trig, v) => { const d = LISTEV[trig], tk = d.ev.map(e => e[0]); if (d.block) (v === 'A' || v === 'B' ? d.block.map(b => [b + 60, 1.5]) : v === 'C' ? d.block.map(b => [b, 1.2]) : []).forEach(x => tk.push(x)); return tk; };
P.push({ id: 'lists', area: 'screens', title: 'Lists', brief: 'Recently Added, Playlists, the Tracks queue and Scenes share one list. Each detent moves one row; a fast spin retargets the same motion instead of stacking steps.',
  triggers: [{ id: 'slow', label: '3 slow detents', dur: 1500 }, { id: 'fast', label: 'Fast spin +6', dur: 1200 }, { id: 'end', label: 'Turn past the end', dur: 1300 }],
  hap: listHap,
  today: { name: 'Today', cost: 'Cheap', spec: spec('Labels replaced per detent; marker jumps; nothing at the end.', '0 ms', '—', '—', '—', 'Detent; end stop is the motor\'s bound.', 'Same'), render: c => listR(c, 'today') },
  variants: [
    { id: 'A', name: 'Rail + focus', rec: true, cost: 'Cheap', spec: spec('The 14 px neighbours ride a rail that follows the knob with a slightly underdamped spring (overshoot ≈ 4 %). The 22 px focus title crossfades in place each time the rail crosses a row. Past the end the rail stretches 0.15 row and returns. Ring marker uses the same spring.', 'Row settles ≈ 300 ms; focus crossfade 160 ms.', SP.list.css + ' · focus E.out', 'None: position of 14 px labels + one 22 px label.', '60 fps during spins, 30 fps otherwise.', 'Detent click as the target changes; end-stop bump at the stretch peak (+60 ms).'), render: c => listR(c, 'A') },
    { id: 'B', name: 'Lens', cost: 'Costly', spec: spec('Continuous list; each row\'s size (14 → 22 px) and brightness follow its distance from the centre, like a magnifier.', 'Same spring as A.', SP.list.css, 'Per-frame font scaling of every visible row.', '60 fps', 'As A.'), render: c => listR(c, 'B') },
    { id: 'C', name: 'Step', cost: 'Cheap', spec: spec('Discrete: per detent the three rows slide 6 px in the turn direction and brighten from 55 %. No inertia. Past the end: rows stay, bottom ring LEDs glow red (120 ms up, 480 ms down).', '200 ms.', 'E.out', 'None.', '30 fps', 'Detent click; end stop = motor bound + red glow starting on the same frame.'), render: c => listR(c, 'C') }
  ] });

const ARTS = { a: { href: COV.moon, c: [60, 170, 255], t: 'Remember', ar: 'Air' }, b: { href: COV.helig, c: [255, 120, 30], t: 'Pray for Rain', ar: 'Lumen Park' } };
function artR(c, v) {
  const { h, t, trig } = c, { rd } = K(c), T0 = 100, kids = [], A = ARTS.a, B = ARTS.b, gid = c.id + 's';
  const paused = trig === 'pause' ? t >= T0 : trig === 'resume' ? t < T0 : false;
  const dimOf = () => { if (trig === 'arrive') return 0.8; const q = v === 'today' ? pr(t, T0, 300, E.io) : pr(t, T0, trig === 'pause' ? 420 : 300, E.io); return trig === 'pause' ? lerp(0.8, 0.45, q) : lerp(0.45, 0.8, q); };
  const psc = () => { if (v !== 'B' || rd || trig === 'arrive') return 1; const q = sp(t, T0, SP.soft); return trig === 'pause' ? lerp(1, 0.98, q) : lerp(0.98, 1, q); };
  if (trig === 'arrive') {
    if (v === 'today') kids.push(art(h, t < T0 ? A.href : B.href, 0.8));
    else if (rd) kids.push(art(h, A.href, 0.8 * (1 - pr(t, T0, 200))), art(h, B.href, 0.8 * pr(t, T0, 240)));
    else if (v === 'A') { kids.push(art(h, A.href, 0.8 * (1 - pr(t, T0, 200)))); const f = pr(t, T0, 180) * (1 - pr(t, T0 + 260, 360, E.io)); if (f > 0) kids.push(h('rect', { x: 0, y: 0, width: 240, height: 240, fill: `rgb(${B.c.join(',')})`, opacity: 0.35 * f })); kids.push(art(h, B.href, 0.8 * pr(t, T0 + 100, 320))); }
    else if (v === 'B') kids.push(art(h, A.href, 0.8 * (1 - pr(t, T0, 240))), art(h, B.href, 0.8 * pr(t, T0, 300), { s: lerp(1.03, 1, sp(t, T0, SP.soft)) }));
    else kids.push(art(h, A.href, 0.8 * (1 - pr(t, T0, 200))), art(h, B.href, 0.8 * pr(t, T0, 320), { dy: 4 * (1 - pr(t, T0, 320)) }));
  } else kids.push(art(h, A.href, dimOf(), { s: psc() }));
  kids.push(...scrim(h, gid));
  const tq = trig === 'arrive' ? (v === 'today' ? (t >= T0 ? 1 : 0) : pr(t, T0, 200)) : 0;
  kids.push(npText(h, { lines: [A.t], artist: A.ar, op: 1 - tq }), npText(h, { lines: [B.t], artist: B.ar, op: tq }));
  kids.push(T(h, 'Paused', { y: 134, size: 12, col: C.sec, op: trig === 'pause' ? pr(t, T0, 160) : trig === 'resume' ? 1 - pr(t, T0, 120) : 0 }));
  kids.push(footer(h, [{ d: I.home }, { d: I.album }, { d: I.list }, { d: paused ? I.play : I.pause, col: paused ? C.ok : C.nav }]));
  return { ring: RG.rest(), btns: btns({ 3: paused ? [GREEN, 0.68] : [WW, 0.34] }), kids };
}
P.push({ id: 'artwork', area: 'screens', title: 'Artwork', brief: 'The cover behind Now Playing (r2.2 scrim, black ≥ 70 %). How a new cover arrives, and how pausing dims it without a hard cut.',
  triggers: [{ id: 'arrive', label: 'New cover', dur: 1300 }, { id: 'pause', label: 'Pause', dur: 1100, hap: [100] }, { id: 'resume', label: 'Resume', dur: 1100, hap: [100] }],
  today: { name: 'Today', cost: 'Cheap', spec: spec('Cover swaps on the frame; pause dims 0.8 → 0.45 over 300 ms.', '300 ms', 'ease', '—', '30 fps', 'Button click', 'Same'), render: c => artR(c, 'today') },
  variants: [
    { id: 'A', name: 'Colour bleed', rec: true, cost: 'Cheap', spec: spec('A flat fill in the new album\'s dominant colour rises to 35 %, the cover fades in over it, then the fill dissolves. Pause: 420 ms dim to 45 %.', 'Fill 180 ms · cover 320 ms from 100 ms · fill out 360 ms from 260 ms.', 'E.out · pause E.io ' + E.io.css, 'None. Full-screen opacity blends redraw the whole 240 × 240 area (≈ 115 KB/frame): keep each blend ≤ 300 ms and at 30 fps.', '30 fps', 'Pause click at t = 0.'), render: c => artR(c, 'A') },
    { id: 'B', name: 'Scale settle', cost: 'Costly', spec: spec('New cover fades in while settling from 103 % to 100 %; pause eases it to 98 % as it dims.', '≈ 450 ms.', SP.soft.css, 'Per-frame scaling of a full-screen image: not viable on the S3 without a second full buffer.', '—', 'Pause click at t = 0.'), render: c => artR(c, 'B') },
    { id: 'C', name: 'Rise', cost: 'Cheap', spec: spec('New cover rises 4 px as it fades in. Pause: same dim as A.', '320 ms.', 'E.out', 'None (image position + opacity; full-screen redraw as A).', '30 fps', '—'), render: c => artR(c, 'C') }
  ] });

const RINGEV = { slow: { v0: 52, ev: Array.from({ length: 10 }, (_, i) => [100 + i * 100, 53 + i]), cap: 'Brightness', kel: true }, fast: { v0: 20, ev: Array.from({ length: 24 }, (_, i) => [100 + i * 16, 21 + i]), cap: 'Volume' }, scene: { v0: 62, ev: [[100, 12]], cap: 'Brightness', kel: true } };
function ringR(c, v) {
  const { h, t, trig } = c, { rd } = K(c), d = RINGEV[trig], tg = tgOf(d.ev, d.v0), cur = lastEv(d.ev, t, d.v0);
  let num = cur.v, rv = cur.v;
  if (v === 'A' && !rd) { num = rv = follow(tg, t, SP.crit, 0, 'rA' + trig); }
  else if (v === 'B' && !rd) { rv = follow(tg, t, SP.crit, 60, 'rB' + trig); }
  const rgb = d.kel ? kel(3200) : WARM; let ring = RG.arc(rv / 100, rgb, v === 'A' && !rd ? 0.8 : 1, d.kel ? 0 : 0.08);
  if (v === 'A' && !rd) { const hk = Math.floor(rv / 100 * 45); ring = ring.map((s, i) => { const k = RG.k(i); return k >= 0 && k >= hk - 1 && k <= hk ? [rgb, 1] : s; }); }
  if (v === 'C' && !rd) { const g = Math.max(0, ...d.ev.map(e => bloom(t, e[0], 80, 520))), hk = Math.round(cur.v / 100 * 45) - 1; ring = ring.map((s, i) => { const k = RG.k(i); return k >= 0 && Math.abs(k - hk) <= 1 ? [mixRGB(s[0], [255, 250, 240], 0.3 * g), lerp(s[1], 1, g * (k === hk ? 1 : 0.5))] : s; }); }
  const n = String(Math.round(num)), rcx = 120 + (tw(n, 48) - tw('%', 22) - 4) / 2;
  const kids = [T(h, d.cap, { y: 52, size: 14, col: C.sec }), T(h, n, { x: rcx, y: 72, size: 48, anchor: 'end' }), T(h, '%', { x: rcx + 4, y: 92, size: 22, col: C.sec, anchor: 'start' }), footer(h, trig === 'fast' ? [{ d: I.music }, { d: I.win }, { d: I.bulb }, { d: I.pause }] : [{ d: I.home }, { d: I.wand }, { d: I.temp }, { d: I.power }])];
  return { ring, kids };
}
P.push({ id: 'ring', area: 'screens', title: 'LED ring with the screen', brief: 'The ring and the number should feel like one gauge. Same start frame, same easing, so a change flows between them.',
  triggers: [{ id: 'slow', label: 'Brightness +10', dur: 1500, hap: RINGEV.slow.ev.map(e => e[0]) }, { id: 'fast', label: 'Volume fast spin', dur: 1100, hap: RINGEV.fast.ev.map(e => e[0]) }, { id: 'scene', label: 'Scene: 62 → 12 %', dur: 1100, hap: [[100, 1.4]] }],
  today: { name: 'Today', cost: 'Cheap', spec: spec('Number and arc both jump on each detent / state change.', '0 ms', '—', '—', 'LED 60 fps', 'Detent', 'Same'), render: c => ringR(c, 'today') },
  variants: [
    { id: 'A', name: 'Flow', rec: true, cost: 'Cheap', spec: spec('Number and arc share one critically damped value. The arc head (2 LEDs) is at full, the body at 80 %, so the fill reads as flowing. Big jumps (a scene) glide instead of snapping.', 'Settles ≈ 300 ms after the last change.', SP.crit.css, 'None (the number rounds the shared value each frame).', 'LED 60 fps; screen 30 fps.', 'Detent click when the target changes.'), render: c => ringR(c, 'A') },
    { id: 'B', name: 'Echo', cost: 'Cheap', spec: spec('The number is immediate; the ring follows 60 ms later and eases in, as if the change pours from the screen into the ring.', '60 ms lag + ≈ 200 ms.', SP.crit.css + ' · delay 60 ms', 'None.', 'LED 60 fps', 'Click with the number (t = 0).'), render: c => ringR(c, 'B') },
    { id: 'C', name: 'Detent glow', cost: 'Cheap', spec: spec('Values step per detent, but the 3 LEDs at the arc head glow brighter while you turn (80 ms up, 520 ms down), so turning feels warm rather than clicky.', 'Glow 80 / 520 ms.', 'E.out up · E.io down', 'None.', 'LED 60 fps', 'Click on the detent.'), render: c => ringR(c, 'C') }
  ] });

function hapR(c, v) { return listR(Object.assign({}, c, { trig: c.trig }), 'A'); }
P.push({ id: 'haptics', area: 'screens', title: 'Haptic pairing', brief: 'Which frame the motor click lands on. The ring around the knob in the stage pulses where the motor fires; ticks on the scrubber show the same.',
  triggers: [{ id: 'fast', label: 'Fast spin', dur: 1200 }, { id: 'end', label: 'Turn past the end', dur: 1300 }],
  hap: (trig, v) => { const d = LISTEV[trig], tk = d.ev.map(e => e[0]); if (v === 'today') return tk; if (d.block) d.block.forEach(b => tk.push([b + 60, 1.5])); if (v === 'B') tk.push([(d.ev[d.ev.length - 1][0]) + 260, 0.6]); return tk; },
  today: { name: 'Today', cost: 'Cheap', spec: spec('Motor detents only; the end is a motor bound with no screen response.', '—', '—', '—', '—', 'Detents from the motor profile.', 'Same'), render: c => hapR(c, 'today') },
  variants: [
    { id: 'A', name: 'Detent-locked', rec: true, cost: 'Cheap', spec: spec('Screen motion starts on the detent frame. At the end stop the motor bump fires at the rail\'s stretch peak (≈ 60 ms after the blocked detent).', '—', 'List A spring', 'None.', '60 fps while spinning', 'Detents: BINARIS / MIDI SKIPPER profiles. End: one stronger bump at +60 ms.'), render: c => hapR(c, 'A') },
    { id: 'B', name: '+ landing tick', cost: 'Cheap', spec: spec('As A, plus one soft tick when a fast spin finishes settling (≈ 260 ms after the last detent), confirming where you landed.', '—', 'List A spring', 'None.', '60 fps while spinning', 'Needs a 3rd, softer motor waveform.'), render: c => hapR(c, 'B') }
  ] });

/* ============ 4. TRANSITIONS ============ */
function scr(h, id, name, o = {}) { const { op = 1, dx = 0, dy = 0, s = 1, noFoot = false, footOp = 1 } = o; if (op <= 0.001) return null; const k = [];
  if (name === 'home') k.push(npText(h, { lines: ['Remember'], artist: 'Air' }));
  if (name === 'music') k.push(crumb(h, id + 'c', '', 'MUSIC'), npText(h, { lines: ['Remember'], artist: 'Air' }));
  if (name === 'recent') k.push(crumb(h, id + 'c', 'MUSIC › ', 'RECENTLY ADDED'), listText(h, { prev: 'Glass Weather', cur: 'Midnight Arcade', next: 'Paper Lanterns', meta: '4 / 9 · Air' }));
  if (name === 'explorer') k.push(crumb(h, id + 'c', 'MUSIC › RECENT › ', 'ON SCREEN'), listText(h, { prev: 'Glass Weather', cur: 'Midnight Arcade', next: 'Paper Lanterns', meta: '4 / 9' }));
  if (name === 'lights') k.push(crumb(h, id + 'c', '', 'LIGHTS'), npText(h, { lines: ['Focus'], artist: 'Hall · 62% · 3200 K' }));
  if (name === 'playlists') k.push(crumb(h, id + 'c', 'MUSIC › ', 'PLAYLISTS'), listText(h, { prev: '', cur: 'Late Night', next: 'Sunday Morning', meta: '1 / 4 · 38 songs' }));
  if (name === 'recent1') k.push(crumb(h, id + 'c', 'MUSIC › ', 'RECENTLY ADDED'), listText(h, { prev: '', cur: 'Promises', next: 'Night Channel', meta: '1 / 9 · Harbour Signals' }));
  if (name === 'windows') k.push(crumb(h, id + 'c', '', 'WINDOWS'), npText(h, { lines: ['Nano D · IA r3'], artist: 'Figma' }), T(h, '2 / 7', { y: 134, size: 12, col: C.meta }));
  if (!noFoot) k.push(G(h, footer(h, FOOT[name]), { opacity: footOp }));
  return h('g', { opacity: clamp(op), transform: tf(dx, dy, s) }, ...k.flat(9).filter(Boolean)); }
const FOOT = { home: [{ d: I.music }, { d: I.win }, { d: I.bulb }, { d: I.pause }], music: [{ d: I.home }, { d: I.album }, { d: I.list }, { d: I.pause }], recent: [{ d: I.back }, { d: I.expand }, { d: I.listMusic }, { d: I.play, col: C.ok }], recent1: [{ d: I.back }, { d: I.expand }, { d: I.listMusic }, { d: I.play, col: C.ok }], playlists: [{ d: I.back }, { d: I.expand }, { d: I.listMusic, col: C.warm }, { d: I.play, col: C.ok }], explorer: [{ d: I.back }, { d: I.album, col: C.warm }, { d: I.listMusic }, { d: I.play, col: C.ok }], lights: [{ d: I.music }, { d: I.win }, { d: I.bulb }, { d: I.power }], windows: [{ d: I.home }, { d: I.snapL }, { d: I.snapR }, { d: I.check, col: C.ok }] };
const ARTOP = { home: 0.8, music: 0.8, recent: 0.7, explorer: 0.7 };
function depthR(c, v) {
  const { h, t, trig } = c, { rd } = K(c), L = ['home', 'music', 'recent', 'explorer'], deep = trig === 'deeper', times = [100, 800, 1500];
  let k = 0; times.forEach((x, i) => { if (t >= x) k = i + 1; });
  const at = k ? times[k - 1] : 0, dt = t - at, dir = deep ? 1 : -1;
  const idx = j => (deep ? j : 3 - j), cur = L[idx(k)], prev = k ? L[idx(k - 1)] : null, kids = [], gid = c.id + 's';
  const artOpNew = ARTOP[cur], artOpOld = prev ? ARTOP[prev] : artOpNew;
  const trans = prev && dt < 600;
  if (v === 'C' && !rd) kids.push(art(h, COV.moon, trans ? lerp(artOpOld, artOpNew, pr(dt, 0, 300)) : artOpNew));
  else kids.push(art(h, COV.moon, trans ? (v === 'today' ? artOpNew : lerp(artOpOld, artOpNew, pr(dt, 0, 300))) : artOpNew));
  kids.push(...scrim(h, gid));
  if (!trans) kids.push(scr(h, c.id + 'n', cur));
  else if (v === 'today') kids.push(scr(h, c.id + 'n', cur, { op: pr(dt, 0, 220), dx: 20 * dir * (1 - pr(dt, 0, 380)) }));
  else if (rd) kids.push(scr(h, c.id + 'o', prev, { op: 1 - pr(dt, 0, 120) }), scr(h, c.id + 'n', cur, { op: pr(dt, 0, 160) }));
  else if (v === 'A') kids.push(scr(h, c.id + 'o', prev, { op: 1 - pr(dt, 0, 120, E.in), dx: -5 * dir * pr(dt, 0, 200) }), scr(h, c.id + 'n', cur, { op: pr(dt, 30, 200), dx: 14 * dir * (1 - sp(dt, 30, SP.snap)) }));
  else if (v === 'B') kids.push(scr(h, c.id + 'o', prev, { op: 1 - pr(dt, 0, 160, E.in), s: deep ? lerp(1, 1.04, pr(dt, 0, 220)) : lerp(1, 0.97, pr(dt, 0, 220)) }), scr(h, c.id + 'n', cur, { op: pr(dt, 40, 200), s: deep ? lerp(0.97, 1, sp(dt, 40, SP.soft)) : lerp(1.03, 1, sp(dt, 40, SP.soft)) }));
  else { const fo = pr(dt, 0, 140); kids.push(scr(h, c.id + 'o', prev, { op: 1 - pr(dt, 0, 110, E.in), dx: -4 * dir * pr(dt, 0, 160), noFoot: true }), scr(h, c.id + 'n', cur, { op: pr(dt, 40, 200), dx: 8 * dir * (1 - sp(dt, 40, SP.snap)), noFoot: true }), footer(h, FOOT[prev].map(f => Object.assign({}, f, { op: 1 - fo }))), footer(h, FOOT[cur].map(f => Object.assign({}, f, { op: fo })))); }
  const rOf = n => (n === 'recent' || n === 'explorer' ? RG.marker(9, 3, [60, 170, 255]) : RG.rest());
  const ring = trans ? RG.blend(rOf(prev), rOf(cur), v === 'today' ? 1 : pr(dt, 0, 300)) : rOf(cur);
  return { ring, btns: btns({ 3: cur === 'recent' || cur === 'explorer' ? [GREEN, 0.68] : [WW, 0.34] }), kids };
}
P.push({ id: 'depth', area: 'transitions', title: 'Home → Music → Recently Added → Explorer', brief: 'Depth navigation with buttons 1 (out) and 2 (in). Going in should feel like going forward; going out should feel like stepping back to where you were.',
  triggers: [{ id: 'deeper', label: 'In ×3 (1 · 2 · 2)', dur: 2200, hap: [100, 800, 1500] }, { id: 'back', label: 'Out ×3 (1 · 1 · 1)', dur: 2200, hap: [100, 800, 1500] }],
  today: { name: 'Today', cost: 'Cheap', spec: spec('Old content disappears; new content slides 20 px in the depth direction and fades.', 'Opacity 220 ms · transform 380 ms.', E.out.css, '—', '30 fps', 'Button click', 'Same'), render: c => depthR(c, 'today') },
  variants: [
    { id: 'A', name: 'Push / pop', cost: 'Cheap', spec: spec('Parallax push: new screen enters 14 px from the depth side, old screen drifts 5 px the other way while fading. Art crossfades underneath.', 'Old 120/200 ms · new ≈ 330 ms from 30 ms.', SP.snap.css, 'None.', '30 fps', 'Click at t = 0.'), render: c => depthR(c, 'A') },
    { id: 'B', name: 'Zoom through', cost: 'Costly', spec: spec('In: the current screen grows to 104 % and fades as the next settles up from 97 %. Out: reversed.', '≈ 400 ms.', SP.soft.css, 'Per-frame scaling of whole screens.', '60 fps', 'Click at t = 0.'), render: c => depthR(c, 'B') },
    { id: 'C', name: 'Anchored art', rec: true, cost: 'Cheap', spec: spec('The cover never leaves (only its dim changes), so the album is the shared element. Text layer does a short 8 px push; footer icons crossfade in place per slot, so the buttons never move under your fingers.', 'Text ≈ 260 ms · footer 140 ms.', SP.snap.css, 'None. Art layer is not redrawn except for the dim change.', '30 fps', 'Click at t = 0.'), render: c => depthR(c, 'C') }
  ] });

function swapR(c, v) {
  const { h, t, trig } = c, { rd } = K(c), T0 = 100, toL = trig === 'toLights', dt = t - T0, gid = c.id + 's';
  const from = toL ? 'home' : 'lights', to = toL ? 'lights' : 'home', MR = RG.rest(), LR = RG.arc(0.62, kel(3200), 0.34, 0), R0 = toL ? MR : LR, R1 = toL ? LR : MR;
  const kids = [], artOp = x => (toL ? 0.8 * (1 - x) : 0.8 * x);
  let ring = t < T0 ? R0 : R1;
  if (t < T0) { kids.push(art(h, COV.moon, toL ? 0.8 : 0), ...scrim(h, gid, toL ? 1 : 0), scr(h, c.id + 'o', from)); }
  else if (v === 'today') { kids.push(art(h, COV.moon, artOp(1)), ...scrim(h, gid, toL ? 0 : 1), scr(h, c.id + 'n', to, { op: pr(dt, 0, 220), dx: 20 * (toL ? 1 : -1) * (1 - pr(dt, 0, 380)) })); ring = RG.blend(RG.fill(toL ? kel(3200) : WARM, 0.68), R1, pr(dt, 0, 450, E.lin)); }
  else if (rd) { const q = pr(dt, 0, 200); kids.push(art(h, COV.moon, artOp(q)), ...scrim(h, gid, toL ? 1 - q : q), scr(h, c.id + 'o', from, { op: 1 - q }), scr(h, c.id + 'n', to, { op: q })); ring = RG.blend(R0, R1, pr(dt, 0, 300)); }
  else if (v === 'A') { const p = pr(dt, 0, 520, E.io), q = pr(dt, 0, 300); ring = RG.sweep(R0, R1, p, RG.cw); kids.push(art(h, COV.moon, artOp(q)), ...scrim(h, gid, toL ? 1 - q : q), scr(h, c.id + 'o', from, { op: 1 - pr(dt, 100, 160, E.in) }), scr(h, c.id + 'n', to, { op: pr(dt, 200, 240), dy: 3 * (1 - sp(dt, 200, SP.soft)) })); }
  else if (v === 'B') { const p = pr(dt, 0, 480, E.io), q = pr(dt, 0, 300); ring = RG.sweep(R0, R1, p, RG.bottomUp); const d = toL ? 1 : -1; kids.push(art(h, COV.moon, artOp(q)), ...scrim(h, gid, toL ? 1 - q : q), scr(h, c.id + 'o', from, { op: 1 - pr(dt, 0, 160, E.in), dy: -6 * d * pr(dt, 0, 200) }), scr(h, c.id + 'n', to, { op: pr(dt, 100, 220), dy: 10 * d * (1 - sp(dt, 100, SP.snap)) })); }
  else { const a = pr(dt, 0, 200, E.in), b = pr(dt, 200, 320); ring = dt < 200 ? RG.blend(R0, RG.off(), a) : (toL ? RG.arc(0.62 * b, kel(3200), 0.34 + 0.66 * (1 - b), 0) : RG.blend(RG.off(), R1, b)); kids.push(art(h, COV.moon, artOp(pr(dt, 0, 300))), ...scrim(h, gid, toL ? 1 - pr(dt, 0, 300) : pr(dt, 0, 300)), scr(h, c.id + 'o', from, { op: 1 - a, s: lerp(1, 0.96, a) }), scr(h, c.id + 'n', to, { op: pr(dt, 200, 240), s: lerp(1.03, 1, sp(dt, 200, SP.soft)) })); }
  return { ring, btns: btns({ 3: [mixRGB(WW, toL ? kel(3200) : WARM, bloom(t, T0, 160, 600)), 0.34 + 0.46 * bloom(t, T0, 160, 600)] }), kids };
}
P.push({ id: 'domainswap', area: 'transitions', title: 'Home ⇄ Lights domain swap', brief: 'Hold 4 lands and the knob changes job. This is the one transition that should feel special: the ring is the gauge, so the ring changes first and the screen follows.',
  triggers: [{ id: 'toLights', label: 'Hold 4 lands → Lights', dur: 1200, hap: [[100, 1.4]] }, { id: 'toMusic', label: 'Hold 4 lands → Music', dur: 1200, hap: [[100, 1.4]] }],
  today: { name: 'Today', cost: 'Cheap', spec: spec('Ring wash in the new domain colour 450 ms; content slides 20 px + fades.', '450 ms', 'linear / E.out', '—', 'LED 60 fps', 'Landing click', 'Same'), render: c => swapR(c, 'today') },
  variants: [
    { id: 'A', name: 'Ring sweep', rec: true, cost: 'Cheap', spec: spec('The new domain\'s ring sweeps clockwise from 12 o\'clock with a soft leading edge; the screen crossfades as the sweep passes halfway (old out from 100 ms, new in from 200 ms with a 3 px settle). Art fades with it.', 'Sweep 520 ms · screen 100–440 ms.', 'Sweep E.io ' + E.io.css + ' · text ' + SP.soft.css, 'None.', 'LED 60 fps · screen 30 fps', 'Landing click at t = 0, the sweep starts on it.'), render: c => swapR(c, 'A') },
    { id: 'B', name: 'Roll', cost: 'Cheap', spec: spec('Content rolls vertically (old drifts 6 px up and out, new rises 10 px from below) while the ring fills up from 6 o\'clock on both sides, meeting at the top.', 'Out 200 ms · in ≈ 330 ms · ring 480 ms.', SP.snap.css + ' · ring E.io', 'None.', '30 fps (60 better for 24 px travel).', 'Landing click at t = 0.'), render: c => swapR(c, 'B') },
    { id: 'C', name: 'Iris', cost: 'Costly', spec: spec('Old content contracts to 96 % while the ring drains to black; then the new ring blooms and the new content settles in from 103 %.', '200 + ≈ 400 ms.', 'E.in / ' + SP.soft.css, 'Per-frame scaling of full screen content.', '60 fps', 'Landing click; soft tick at the dark midpoint (200 ms).'), render: c => swapR(c, 'C') }
  ] });

function srcR(c, v) {
  const { h, t, trig } = c, { rd } = K(c), T0 = 100, toP = trig === 'toPl', dt = t - T0, gid = c.id + 's';
  const from = toP ? 'recent1' : 'playlists', to = toP ? 'playlists' : 'recent1', kids = [];
  const MO = [COV.night, COV.helig, COV.lines, COV.moon], artFrom = (op, o) => (toP ? art(h, COV.promises, op, o) : mosaic(h, MO, [op, op, op, op], o)), artTo = (op, o, ops) => (toP ? mosaic(h, MO, ops || [op, op, op, op], o) : art(h, COV.promises, op, o));
  if (t < T0) kids.push(artFrom(0.7), ...scrim(h, gid), scr(h, c.id + 'o', from));
  else if (v === 'today') kids.push(artTo(0.7), ...scrim(h, gid), scr(h, c.id + 'n', to));
  else if (rd) { const q = pr(dt, 0, 200); kids.push(artFrom(0.7 * (1 - q)), artTo(0.7 * q), ...scrim(h, gid), scr(h, c.id + 'o', from, { op: 1 - q, noFoot: true }), scr(h, c.id + 'n', to, { op: q, noFoot: true }), footer(h, FOOT[to])); }
  else if (v === 'A') { const d = toP ? 1 : -1, q = pr(dt, 0, 240); kids.push(artFrom(0.7 * (1 - q)), artTo(0.7 * q), ...scrim(h, gid), scr(h, c.id + 'o', from, { op: 1 - pr(dt, 0, 160, E.in), dx: -6 * d * pr(dt, 0, 200), noFoot: true }), scr(h, c.id + 'n', to, { op: pr(dt, 40, 200), dx: 14 * d * (1 - sp(dt, 40, SP.snap)), noFoot: true }), footer(h, FOOT[to])); }
  else if (v === 'B') { const q = pr(dt, 0, 200), tiles = [0, 1, 2, 3].map(k => 0.7 * pr(dt, 60 + k * 24, 220)); kids.push(artFrom(0.7 * (1 - q)), toP ? artTo(0, {}, tiles) : artTo(0.7 * pr(dt, 60, 200)), ...scrim(h, gid), scr(h, c.id + 'o', from, { op: 1 - pr(dt, 0, 140, E.in), dy: 5 * pr(dt, 0, 180, E.in), noFoot: true }), scr(h, c.id + 'n', to, { op: pr(dt, 60, 220), dy: -5 * (1 - sp(dt, 60, SP.soft)), noFoot: true }), footer(h, FOOT[to])); }
  else { const q = pr(dt, 0, 240); kids.push(artFrom(0.7 * (1 - q), { s: lerp(1, 0.98, q) }), artTo(0.7 * q, { s: lerp(1.02, 1, sp(dt, 0, SP.soft)) }), ...scrim(h, gid), scr(h, c.id + 'o', from, { op: 1 - q, s: lerp(1, 0.98, q), noFoot: true }), scr(h, c.id + 'n', to, { op: q, s: lerp(1.02, 1, sp(dt, 0, SP.soft)), noFoot: true }), footer(h, FOOT[to])); }
  const pl = t >= T0 ? toP : !toP;
  return { ring: RG.marker(pl ? 4 : 9, 0, pl ? [255, 40, 90] : [120, 150, 190]), btns: btns({ 2: pl ? [WARM, 0.9] : [WW, 0.34], 3: [GREEN, 0.68] }), kids };
}
P.push({ id: 'source', area: 'transitions', title: 'Recently Added ⇄ Favourite playlists', brief: 'Button 3 switches the list source at the same depth. It should read as a sideways change, not going deeper.',
  triggers: [{ id: 'toPl', label: 'Tap 3 → Playlists', dur: 1000, hap: [100] }, { id: 'toRec', label: 'Tap 3 → Recent', dur: 1000, hap: [100] }],
  today: { name: 'Today', cost: 'Cheap', spec: spec('Instant swap (same screen key).', '0 ms', '—', '—', '—', 'Click', 'Same'), render: c => srcR(c, 'today') },
  variants: [
    { id: 'A', name: 'Carousel', cost: 'Cheap', spec: spec('Lists slide sideways 14 px (to Playlists = leftwards), art crossfades. Footer stays put.', '≈ 300 ms.', SP.snap.css, 'None.', '30 fps', 'Click at t = 0.'), render: c => srcR(c, 'A') },
    { id: 'B', name: 'Shuffle', rec: true, cost: 'Cheap', spec: spec('The current list drops 5 px as it fades; the new one settles down from 5 px above. Playlist mosaic tiles fade in 24 ms apart.', 'Out 140 ms · in ≈ 500 ms · tiles 60–350 ms.', SP.soft.css, 'None (4 tile images, opacity only).', '30 fps', 'Click at t = 0.'), render: c => srcR(c, 'B') },
    { id: 'C', name: 'Depth crossfade', cost: 'Costly', spec: spec('Old list and art recede to 98 %, the new ones come forward from 102 %.', '≈ 350 ms.', SP.soft.css, 'Per-frame scaling of full-screen art.', '60 fps', 'Click at t = 0.'), render: c => srcR(c, 'C') }
  ] });

function sleepR(c, v) {
  const { h, t, trig } = c, { rd } = K(c), T0 = 100, kids = [], gid = c.id + 's', sleep = trig === 'sleep';
  let bl = 1, ring = RG.rest(), sr = 120;
  const content = (o = {}) => [art(h, COV.moon, 0.45), ...scrim(h, gid), scr(h, c.id + 'n', 'home', o), T(h, 'Paused', { y: 134, size: 12, col: C.sec, op: o.op == null ? 1 : o.op })];
  const breath = x => [WARM, 0.04 + 0.03 * (0.5 - 0.5 * Math.cos(2 * Math.PI * x / 3000))];
  if (sleep) {
    if (v === 'today') { bl = t >= T0 ? 0 : 1; ring = t >= T0 ? RG.off() : RG.rest(); }
    else if (rd) { bl = 1 - pr(t, T0, 400); ring = RG.blend(RG.rest(), RG.off(), pr(t, T0, 400)); }
    else if (v === 'A') { bl = 1 - pr(t, T0, 700, E.io); ring = t < T0 + 700 ? RG.blend(RG.rest(), RG.fill(WARM, 0.04), pr(t, T0, 700, E.io)) : RG.fill(...breath(t - T0 - 700)); }
    else if (v === 'B') { sr = 120 * (1 - pr(t, T0, 500, E.in)); ring = RG.blend(RG.rest(), RG.off(), pr(t, T0, 500)); }
    else { bl = 1 - pr(t, T0, 220, E.io); ring = t < T0 + 300 ? RG.rest() : RG.blend(RG.rest(), RG.off(), pr(t, T0 + 300, 900, E.io)); }
    kids.push(...content());
  } else {
    const W2 = 900, rev = t >= W2 ? pr(t, W2, 160) * (1 - pr(t, W2 + 1400, 160)) : 0;
    if (t < T0) { bl = 0; ring = v === 'A' ? RG.fill(...breath(t)) : RG.off(); kids.push(...content()); }
    else if (v === 'today') kids.push(...content());
    else if (rd) { bl = pr(t, T0, 200); ring = RG.blend(RG.off(), RG.rest(), pr(t, T0, 200)); kids.push(...content()); }
    else if (v === 'A') { bl = pr(t, T0, 120); ring = RG.blend(RG.fill(WARM, 0.05), RG.rest(), pr(t, T0, 120)); const st = i => T0 + 60 + i * 30;
      kids.push(art(h, COV.moon, 0.45 * pr(t, T0, 200)), ...scrim(h, gid), npText(h, { lines: ['Remember'], op: pr(t, st(0), 240), dy: 3 * (1 - sp(t, st(0), SP.soft)) }), T(h, 'Paused', { y: 134, size: 12, col: C.sec, op: pr(t, st(2), 180) * (1 - rev) }), footer(h, FOOT.home.map((f, i) => Object.assign({}, f, { op: pr(t, st(3), 240), dy: 0 })))); }
    else if (v === 'B') { sr = 120 * sp(t, T0, SP.soft); ring = RG.blend(RG.off(), RG.rest(), pr(t, T0, 300)); kids.push(...content()); }
    else { ring = RG.blend(RG.blend(RG.off(), RG.rest(), pr(t, T0, 200)), RG.fill(WARM, 0.4), bloom(t, T0, 180, 500)); bl = pr(t, T0, 140); kids.push(...content()); }
    if (rev > 0) { kids.push(h('rect', { x: 0, y: 40, width: 240, height: 100, fill: '#000', opacity: rev }), T(h, 'Remember', { y: 52, size: 14, col: C.sec, op: rev }), T(h, '35', { x: 131, y: 72, size: 48, anchor: 'end', op: rev }), T(h, '%', { x: 135, y: 92, size: 22, col: C.sec, anchor: 'start', op: rev })); ring = RG.blend(ring, RG.arc(0.35, WARM, 1, 0.08), rev); }
    kids.push(T(h, t >= T0 && t < 800 ? 'First touch: wake only' : '', { y: 190, size: 11, col: C.meta, op: t >= T0 && t < 800 ? 1 : 0 }));
  }
  return { ring, kids, bl, sr };
}
P.push({ id: 'sleep', area: 'transitions', title: 'Sleep and wake', brief: 'After the idle timeout the knob goes dark. The first touch only wakes it; the volume doesn\'t change until the second detent (shown at 0.9 s).',
  triggers: [{ id: 'sleep', label: 'Idle → sleep', dur: 2600 }, { id: 'wake', label: 'First touch → wake', dur: 2300, hap: [[100, 0.5], 900] }],
  today: { name: 'Today', cost: 'Cheap', spec: spec('Screen and ring cut off / on.', '0 ms', '—', '—', '—', 'Detent (and volume may change on the first touch)', 'Same'), render: c => sleepR(c, 'today') },
  variants: [
    { id: 'A', name: 'Breathe down', rec: true, cost: 'Cheap', spec: spec('Sleep: backlight fades out over 700 ms while the ring dims to 4 % and then breathes 4–7 % on a 3 s cycle. Wake: backlight + ring up in 120 ms, title rises 3 px into place; status and footer fade in behind it.', 'Sleep 700 ms · wake ≈ 350 ms.', 'E.io · content ' + SP.soft.css, 'None. Backlight is PWM, free; the screen isn\'t redrawn while dimming.', '30 fps; the breath can run at 10 fps.', 'First touch: a soft wake tick, no detent value. Detents resume on the next click.'), render: c => sleepR(c, 'A') },
    { id: 'B', name: 'Iris', cost: 'Costly', spec: spec('The picture closes into the centre like an aperture; wake reopens it with a soft spring.', '500 / ≈ 450 ms.', 'E.in / ' + SP.soft.css, 'Animated circular clip (a mask) over the whole screen.', '60 fps', 'As A.'), render: c => sleepR(c, 'B') },
    { id: 'C', name: 'Afterglow', cost: 'Cheap', spec: spec('Screen fades in 220 ms; the ring holds for 300 ms then cools over 900 ms like a filament. Wake: screen fades up in 140 ms while the ring blooms to 40 % and settles to rest.', 'Sleep 1200 ms · wake 680 ms.', 'E.io', 'None.', 'LED 60 fps', 'As A.'), render: c => sleepR(c, 'C') }
  ] });

function winR(c, v) {
  const { h, t, trig } = c, { rd } = K(c), T0 = 100, open = trig === 'open', dt = t - T0, kids = [];
  const on = t < T0 ? !open : open, from = open ? 'home' : 'windows', to = open ? 'windows' : 'home';
  let pOp = on ? 1 : 0, cardDx = i => 0, cardDy = i => 0, cardOp = i => pOp;
  if (t >= T0) {
    if (v === 'today') { pOp = open ? pr(dt, 0, 280) : 1 - pr(dt, 0, 280); }
    else if (rd || v === 'C') { pOp = open ? pr(dt, 0, 200) : 1 - pr(dt, 0, 200); }
    else if (v === 'A') { pOp = open ? pr(dt, 40, 240) : 1 - pr(dt, 0, 200); if (open) { cardDx = i => -12 * (1 - sp(dt, 40 + i * 20, SP.snap)); cardOp = i => pr(dt, 40 + i * 20, 200); } }
    else { pOp = open ? pr(dt, 0, 240) : 1 - pr(dt, 0, 200); if (open) { cardDy = i => 8 * (1 - sp(dt, 60 + i * 20, SP.snap)); cardOp = i => pr(dt, 60 + i * 20, 200); } else cardDy = i => -4 * pr(dt, 0, 200); } }
  const cards = [0, 1, 2, 3, 4].map(i => { const x = 70 + i * 34 - (i === 1 ? 4 : 0), w = i === 1 ? 44 : 28, hh = i === 1 ? 28 : 20; return h('rect', { key: i, x: x + cardDx(i), y: 48 - hh / 2 + cardDy(i), width: w, height: hh, fill: ['#3a3935', '#f1f3f4', '#3f0e40', '#0c0c0c', '#2c2c2c'][i], stroke: i === 1 ? '#fff' : 'rgba(255,255,255,.2)', strokeWidth: i === 1 ? 1.5 : 0.5, opacity: clamp(i === 1 ? cardOp(i) : cardOp(i) * 0.85) }); });
  const top = h('g', null, h('rect', { x: 0, y: 6, width: 300, height: 84, fill: '#0e1a2b' }), h('rect', { x: 4, y: 10, width: 144, height: 70, fill: '#262624' }), h('rect', { x: 152, y: 10, width: 144, height: 70, fill: '#f1f3f4' }), h('rect', { x: 0, y: 82, width: 300, height: 8, fill: '#202020' }),
    h('rect', { x: 0, y: 6, width: 300, height: 84, fill: 'rgba(10,10,12,0.62)', opacity: clamp(pOp) }), ...cards, h('text', { x: 6, y: 20, fontSize: 8, fill: '#9B9797', fontFamily: 'Archivo, sans-serif' }, 'MONITOR · 32:9'));
  if (t < T0) kids.push(scr(h, c.id + 'o', from));
  else if (v === 'today') kids.push(scr(h, c.id + 'n', to, { op: pr(dt, 0, 220), dx: 20 * (open ? 1 : -1) * (1 - pr(dt, 0, 380)) }));
  else if (rd || v === 'C') { const q = pr(dt, 0, 200); kids.push(scr(h, c.id + 'o', from, { op: 1 - q }), scr(h, c.id + 'n', to, { op: q })); }
  else if (v === 'A') { const d = open ? 1 : -1; kids.push(scr(h, c.id + 'o', from, { op: 1 - pr(dt, 0, 140, E.in), dx: -5 * d * pr(dt, 0, 200) }), scr(h, c.id + 'n', to, { op: pr(dt, 40, 200), dx: 12 * d * (1 - sp(dt, 40, SP.snap)) })); }
  else { kids.push(scr(h, c.id + 'o', from, { op: 1 - pr(dt, 0, 160, E.in), dy: (open ? -6 : 6) * pr(dt, 0, 200) }), scr(h, c.id + 'n', to, { op: pr(dt, 60, 200), dy: (open ? 8 : -8) * (1 - sp(dt, 60, SP.snap)) })); }
  const R1 = RG.marker(7, 1, WHITE, 0.1, WARM), ring = RG.blend(RG.rest(), R1, t < T0 ? (open ? 0 : 1) : open ? pr(dt, 40, 240) : 1 - pr(dt, 0, 200));
  return { ring, kids, top, btns: btns({ 3: on ? [GREEN, 0.68] : [WW, 0.34] }) };
}
P.push({ id: 'windows', area: 'transitions', title: 'Window picker opens from the knob', brief: 'Tap 2 on Home opens the picker on the 32:9 monitor. The knob and the monitor should move as one gesture, so the eye follows from the hand to the screen.',
  triggers: [{ id: 'open', label: 'Tap 2 · open', dur: 1100, hap: [100] }, { id: 'close', label: 'Tap 1 · close', dur: 900, hap: [100] }],
  today: { name: 'Today', cost: 'Cheap', spec: spec('Knob: 20 px slide + fade. Monitor overlay fades in 280 ms, independently.', '220 / 380 / 280 ms', E.out.css, '—', '30 fps', 'Click', 'Same'), render: c => winR(c, 'today') },
  variants: [
    { id: 'A', name: 'Hand-off', rec: true, cost: 'Cheap', spec: spec('Knob content pushes sideways 12 px; 40 ms later the monitor scrim fades in and the window cards slide 12 px in from the left, 20 ms apart. The ring marker appears with the focused card.', 'Knob ≈ 260 ms · monitor 40–400 ms.', SP.snap.css, 'Knob: none. Monitor: companion GPU, free.', 'Knob 30 fps · monitor 60 fps', 'Click at t = 0.'), render: c => winR(c, 'A') },
    { id: 'B', name: 'Up to the screen', cost: 'Cheap', spec: spec('Knob content lifts 6 px up and out, towards the monitor; the cards rise 8 px into place on the monitor 60 ms later. Close drops everything back down.', '≈ 350 ms.', SP.snap.css, 'None.', 'Knob 30 fps · monitor 60 fps', 'Click at t = 0.'), render: c => winR(c, 'B') },
    { id: 'C', name: 'Crossfade', cost: 'Cheap', spec: spec('Both sides fade 200 ms together, no movement. The calm baseline.', '200 ms.', 'E.out', 'None.', '30 fps', 'Click at t = 0.'), render: c => winR(c, 'C') }
  ] });

const LED_TAU = 50, LED_N = 7;
function ledSmooth(fn) { return ctx => { const cur = fn(ctx), ws = [], rs = [];
  for (let j = 0; j < LED_N; j++) { const tt = Math.max(0, ctx.t - j * 16); const r = j === 0 ? cur : fn(Object.assign({}, ctx, { t: tt })); ws.push(Math.exp(-j * 16 / LED_TAU)); rs.push(r); }
  const W = ws.reduce((a, b) => a + b, 0);
  const avg = key => { const base = rs[0][key]; if (!base) return base; return base.map((_, i) => { let a = 0, c = [0, 0, 0]; rs.forEach((r, j) => { const x = (r[key] || base)[i]; a += x[1] * ws[j]; c = c.map((v, q) => v + x[0][q] * x[1] * ws[j]); }); const A = a / W; return [a > 0.0001 ? c.map(v => Math.round(v / a)) : base[i][0], A]; }); };
  return Object.assign({}, cur, { ring: avg('ring'), btns: cur.btns ? avg('btns') : cur.btns }); }; }
P.forEach(p => p.variants.forEach(v => { v.render = ledSmooth(v.render); }));

window.NanoMotion = {
  lib: { fitText, fitCrumb, T, Ic, icoG, pth, G, footer, crumb, npText, listText, RG, btns, I, C, kel, kelHex, mixHex, mixRGB, WARM, WW, GREEN, RED, WHITE, art, scrim, bloom, pr, sp, E, SP, FX, FY, IX, IY, tw, COV },
  protos: P, device, hapticAt,
  areas: [{ id: 'icons', label: 'Iconography', n: '01' }, { id: 'text', label: 'Text & numbers', n: '02' }, { id: 'screens', label: 'Screens', n: '03' }, { id: 'transitions', label: 'Transitions', n: '04' }],
  springs: Object.entries(SP).map(([k, f]) => ({ name: k, css: f.css })), beziers: Object.entries(E).map(([k, f]) => ({ name: k, css: f.css }))
};
})();
