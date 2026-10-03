/* Nano D haptic spec — contexts, tokens, simulation, audio proxy. Depends on motion-lab.js (window.NanoMotion.lib). */
(function () {
'use strict';
const L = window.NanoMotion.lib, M = window.NanoMotion;
const { T, Ic, footer, crumb, npText, listText, RG, btns, I, C, kel, WARM, WW, GREEN, RED, WHITE, bloom, pr, E } = L;
const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
const lerp = (a, b, p) => a + (b - a) * p;
const UNDO = 'M9 14L4 9l5-5M4 9h11a5 5 0 0 1 0 10h-1', ORBIT = 'M12 3a9 4 0 1 0 0 18 9 4 0 1 0 0-18zM3 12a9 4 0 0 0 18 0', PAN = 'M12 2v20M2 12h20M12 2l-3 3M12 2l3 3M12 22l-3-3M12 22l3-3M2 12l3-3M2 12l3 3M22 12l-3-3M22 12l-3 3', HEART = 'M19 14c1.5-1.5 3-3.2 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.8 0-3 .5-4.5 2-1.5-1.5-2.7-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4 3 5.5l7 7z', SHUF = 'M2 18h1.4c1.3 0 2.5-.6 3.3-1.7l6.1-8.6c.7-1.1 2-1.7 3.3-1.7H22M18 2l4 4-4 4M2 6h1.9c1.5 0 2.9.9 3.6 2.2M22 18h-5.9c-1.3 0-2.6-.7-3.3-1.8l-.5-.8M18 14l4 4-4 4', SEEK = 'M3 12h8.7M17.7 12H21M14.7 9a3 3 0 1 1 0 6 3 3 0 0 1 0-6z';

/* ---------- vocabulary ---------- */
const TOKENS = [
  { id: 'detent.value', kind: 'Feel', intent: 'Stepped continuous values (volume). You feel each step; you never hear it.', params: 'SINE · 36 / turn · Kp 3 V/rad · Kd 0.01 · no click', sound: 'None', reduced: 'VISCOSE Kd 0.02' },
  { id: 'detent.dimmer', kind: 'Feel', intent: 'Light level. Same soft steps as volume but heavier, so your fingers know the knob is on the lights.', params: 'SINE · 36 / turn (2 % each, 1 % below 10 %) · Kp 3 · Kd 0.04 · no click', sound: 'None', reduced: 'VISCOSE Kd 0.05' },
  { id: 'detent.list', kind: 'Feel', intent: 'Choosing an item in a list. Crisp, countable, audible.', params: 'SAW · 20 / turn · Kp 6 · Kd 0.01 · hysteresis 15 % · click pulse on', sound: 'wood tock · amp 30 %', reduced: 'SINE 20 / turn, no pulse, no sound' },
  { id: 'detent.coarse', kind: 'Feel', intent: 'A few big choices (scenes, windows). Each notch is a decision, like a rotary switch.', params: 'SAW · 12 / turn · Kp 11 · Kd 0.02 · click pulse on', sound: 'tick-thud · amp 35 %', reduced: 'SINE 12 / turn, Kp 6, no pulse' },
  { id: 'detent.fine', kind: 'Feel', intent: 'Precision in small units (colour temperature). Many light notches.', params: 'SAW · 36 / turn (firmware max) · Kp 2.5 · Kd 0.01 · fine click (2× pitch)', sound: 'fine click · amp 20 %', reduced: 'SINE 36 / turn, no sound' },
  { id: 'fluid.scrub', kind: 'Feel', intent: 'Scrubbing time or position. No notches, controlled weight.', params: 'VISCOSE · Kp 0 · Kd 0.08', sound: 'None', reduced: 'Same' },
  { id: 'fluid.light', kind: 'Feel', intent: 'Asleep, or turning that should not count yet.', params: 'VISCOSE · Kp 0 · Kd 0.02', sound: 'None', reduced: 'Same' },
  { id: 'free.spin', kind: 'Modifier', intent: 'A fast flick through a long list coasts, then catches again.', params: 'Firmware: zero spring above 30 rad/s (filtered, τ 6.7 ms); pulses disarmed while coasting. Enable only for lists > 20 items.', sound: 'Silent while coasting', reduced: 'Off' },
  { id: 'wall.bounce', kind: 'Boundary', intent: 'Every limit. The knob refuses the next step, pushes back harder the further you go, and springs back to the last item when you let go.', params: 'Firmware end-stop: next detent becomes a spring ramping from 0 to 3 × Kp · no click · no step · releases to the committed detent', sound: 'None', reduced: 'Same (a wall is information)' },
  { id: 'feel.fade', kind: 'Modifier', intent: 'Changing context never drops a notch under your finger.', params: 'Kp ramps 0 → target over 120 ms; grid re-anchored at the current angle', sound: 'None', reduced: 'Same' },
  { id: 'hold.tension', kind: 'Modifier', intent: 'While a button is held for a secondary action, the knob stiffens, so you feel the hold charging without any noise.', params: 'Kd ramps 0.01 → 0.12 over the hold (600 ms for button 1, 1000 ms for button 4); released on landing or let go', sound: 'None', reduced: 'Off' },
  { id: 'nudge.left / nudge.right', kind: 'Event', intent: 'Something moved in a direction (skip, snap left/right).', params: '1 firmware pulse, phase-signed (impact 4 ms @ 100 Hz, tail 20 ms @ 70 Hz)', sound: 'tick-thud · amp 30 %', reduced: 'Unsigned tick' },
  { id: 'confirm.tick', kind: 'Event', intent: 'A light toggle or a small commit (play/pause, shuffle, like, set seek, switch window, undo).', params: '1 firmware pulse at 60 % amplitude', sound: 'wood tock · amp 30 %', reduced: 'Same, 50 %' },
  { id: 'confirm.thump', kind: 'Event', intent: 'Something landed. Reserved for hold landings, Play (replaces queue), Turn on and Scene run.', params: '2 pulses 12 ms apart (reads as one deep hit) + BUTTON_THUMP sound', sound: 'BUTTON_THUMP 110 Hz, 40 ms', reduced: 'confirm.tick' },
  { id: 'refuse.buzz', kind: 'Event', intent: '"No." The action was refused. Rate-limited to once per second.', params: '3 pulses, 30 ms apart, 60 % amplitude', sound: '3 wood tocks · amp 20 %', reduced: 'Single nudge' },
  { id: 'error.buzz', kind: 'Event', intent: 'Something is broken (lights unreachable). Slower and heavier.', params: '3 pulses, 70 ms apart, full amplitude', sound: '3 tick-thuds · amp 30 %', reduced: 'Single nudge' }
];
const PRINCIPLES = [
  ['Clicks for choices, soft steps for values, fluid for time and space.', 'Lists, windows and scenes click (SAW + pulse). Volume, brightness and zoom step softly (SINE, silent). Seek, orbit and pan are fluid (VISCOSE).'],
  ['Every limit bounces.', 'Every bounded list and range ends in the firmware wall: no click, no step, a spring that pushes back harder the further you go and returns the knob to the last item when you let go. The screen stretches with it and settles back on the same spring.'],
  ['You can feel which job the knob has.', 'Volume is light, brightness is heavier (Kd 0.04 vs 0.01), lists click, fine values click higher. Swapping domains changes the feel, not just the screen.'],
  ['One confirmation per action, and thumps are rare.', 'A tap or landed hold gets exactly one event. Thumps only for hold landings, Play (replaces queue), Turn on and Scene run; everything else is a tick.'],
  ['Holds charge silently.', 'While a hold counts down, the knob stiffens (hold.tension). No pulses during a hold; one thump when it lands.'],
  ['Quiet while you move fast, and at your desk.', 'Pulses are disarmed while coasting. Detent sounds default to 20–35 % and only for clicking feels; value feels are always silent.'],
  ['Never change the feel under the finger, and degrade to quiet.', 'Every context change re-anchors the grid and fades Kp in over 120 ms. Reduced haptics: pulses become soft steps, thumps become ticks, buzzes a single nudge; walls stay.']
];

/* ---------- simulation helpers ---------- */
const kf = pts => t => { if (t <= pts[0][0]) return pts[0][1]; for (let i = 1; i < pts.length; i++) { const [t0, a0] = pts[i - 1], [t1, a1] = pts[i]; if (t <= t1) return lerp(a0, a1, E.io((t - t0) / Math.max(1, t1 - t0))); } return pts[pts.length - 1][1]; };
const ALB = ['Promises', 'Night Channel', 'Glass Weather', 'Midnight Arcade', 'Paper Lanterns', 'Lua & Mar', 'Neon Littoral', 'Copper Sun', 'Tidal Glass'];
const ART = ['Harbour Signals', 'Velvet Circuit', 'Lumen Park', 'Air', 'Mira Vale', 'Lua Serena', 'Lumen Park', 'Various artists', 'Oskar Lind Trio'];
const QUEUE = ['La femme d’argent', 'Long Range', 'Afterburn', 'Kelly Watch the Stars', 'Talisman', 'Remember', 'You Make It Easy', 'Ce matin-là', 'Blue Hour Signal', 'Le voyage de Maré'];
const WINS = [['Claude', 'Knob review'], ['Chrome', 'Home Assistant'], ['Slack', '#hall-automation'], ['Terminal', 'pio run'], ['Figma', 'Knob faces'], ['Explorer', 'Downloads'], ['Onshape', 'Nano D enclosure']];
const SCN = [['Focus', '62% · 3200 K'], ['Evening', '48% · 2700 K'], ['Movie', '12% · 2200 K'], ['Reading', '80% · 3500 K'], ['Daylight', '100% · 5000 K']];
const lastAt = (evs, type, t) => { let x = -1e9; for (const e of evs) if (e.t <= t && (!type || e.type === type || (Array.isArray(type) && type.includes(e.type)))) x = e.t; return x; };
function bigVal(h, cap, val, unit, o = {}) { const w = L.tw(String(val), 48), uw = unit ? L.tw(unit, 22) + 4 : 0, cx = 120 + (w - uw) / 2; return [T(h, cap, { y: 52, size: 14, col: C.sec, op: o.op }), T(h, String(val), { x: cx, y: 72, size: 48, anchor: 'end', op: o.op }), T(h, unit, { x: cx + 4, y: 92, size: 22, col: C.sec, anchor: 'start', op: o.op })]; }
const status = (h, txt, col, t, at, dur = 1600) => T(h, txt, { y: 134, size: 12, col, op: at > -1e8 ? pr(t, at, 220) * (1 - pr(t, at + dur, 160, E.in)) : 0, dy: at > -1e8 ? 4 * (1 - L.sp(t, at, L.SP.soft)) : 0 });

/* contexts: sim.phases = [{from, feel, dpt, snap, damp, click, clickType, min, max, i0 (value at phase start), step, gain, free}] */
const fromMotion = (pid, vid, map) => (h, st) => { const p = M.protos.find(x => x.id === pid), v = p.variants.find(x => x.id === vid), [trig, tt] = map(st.t); return v.render({ h, t: Math.max(0, tt), trig, reduced: false, id: (st.id || 'm') + pid }); };
const CTX = [];
const add = (o) => CTX.push(o);

// ---------- HOME ----------
add({ id: 'home-volume', key: st => (st.t > 300 ? { k: 'big', d: 0, s: 'reveal' } : { k: 'text', d: 0 }), group: 'home', title: 'Home · volume', v: 'v1', tokens: ['detent.value', 'wall.bounce'],
  feel: 'Soft (SINE)', dpt: '36 / turn (1 % each)', snap: 'Low', damp: 'Low', click: 'Off', ends: 'wall.bounce at 0 % and 100 %', events: 'None while turning', sound: 'None', pair: 'Volume reveal on the first detent; ring arc follows (LED flow). Arc head brightens against the wall.', reduced: 'fluid.light (no steps), wall stays',
  sim: { dur: 3200, angle: kf([[0, 0], [300, 0], [1500, 60], [1800, 60], [2600, 104], [3000, 92]]), phases: [{ from: 0, feel: 'SINE', dpt: 36, snap: 0.3, damp: 0.1, click: false, min: 0, max: 100, i0: 92, step: 1 }] },
  screen: (h, st) => ({ ring: RG.arc((st.vs ?? st.v) / 100, WARM, 1, 0.08), kids: [st.t > 300 ? bigVal(h, 'Remember', st.v, '%') : npText(h, { lines: ['Remember'] }), footer(h, [{ d: I.music }, { d: I.win }, { d: I.bulb }, { d: I.pause }])] }) });
add({ id: 'home-play', group: 'home', title: 'Tap 4 play / pause (Home and Music)', v: 'v1', tokens: ['confirm.tick'],
  feel: '(unchanged: volume)', dpt: '—', snap: '—', damp: '—', click: '—', ends: '—', events: 'confirm.tick on the press frame', sound: 'wood tock, 0.3 (optional)', pair: 'Motion lab Play ⇄ Pause A (Melt): bars melt into the triangle, then the green arrives; button-4 LED eases to green.', reduced: 'confirm.tick at 50 %',
  sim: { dur: 1600, ev: [[300, 'tick'], [1000, 'tick']] },
  screen: fromMotion('playpause', 'A', t => (t < 1000 ? ['pause', t - 200] : ['resume', t - 900])) });

add({ id: 'home-swap', key: st => (st.t >= 1300 ? (st.t > 1500 ? { k: 'lbig', d: 0, s: 'reveal' } : { k: 'lights', d: 0, s: 'swap' }) : { k: 'music', d: 0 }), group: 'home', title: 'Home · hold 4 swaps volume ⇄ brightness', v: 'v1', tokens: ['hold.tension', 'confirm.thump', 'feel.fade', 'detent.dimmer'],
  feel: 'Soft light → soft heavy', dpt: '36 → 36 / turn (2 % steps)', snap: 'Kp 3', damp: 'Kd 0.01 → 0.04', click: 'Off', ends: 'wall.bounce (1 % and 100 %)', events: 'hold.tension: the knob stiffens over the 1 s hold. confirm.thump on landing; feel.fade re-anchors the grid, and the lights feel is heavier than volume so you can tell by touch.', sound: '110 Hz thud on landing', pair: 'Hold arc on the ring; landing = ring sweep to the Kelvin arc (motion lab: Domain swap A).', reduced: 'confirm.tick on landing',
  sim: { dur: 3000, ev: [[1300, 'thump']], angle: kf([[0, 0], [1500, 0], [2600, 40]]), phases: [{ from: 0, feel: 'SINE', dpt: 36, snap: 0.3, damp: 0.1, click: false, min: 0, max: 100, i0: 34, step: 1 }, { from: 1300, feel: 'SINE', dpt: 36, snap: 0.3, damp: 0.4, click: false, min: 2, max: 100, i0: 62, step: 2, fadeIn: 120 }] },
  screen: (h, st) => { const lt = st.t >= 1300, hold = st.t >= 300 && st.t < 1300; let ring = lt ? RG.arc((st.vs ?? st.v) / 100, kel(3200), st.t > 1500 ? 1 : 0.34, 0) : RG.rest(); if (hold) ring = RG.blend(RG.rest(), RG.arc((st.t - 300) / 1000, WARM, 1, 0), clamp((st.t - 300) / 120));
    return { ring, btns: btns({ 3: hold ? [WARM, 0.34 + 0.56 * (st.t - 300) / 1000] : [WW, 0.34] }), kids: [lt ? (st.t > 1500 ? bigVal(h, 'Hall', st.v, '%') : [T(h, 'LIGHTS', { y: 32, size: 12, col: C.sec }), npText(h, { lines: ['Focus'], artist: 'Hall · 62% · 3200 K' })]) : npText(h, { lines: ['Remember'] }), footer(h, [{ d: I.music }, { d: I.win }, { d: I.bulb }, { d: lt ? I.power : I.pause }])] }; } });

// ---------- MUSIC ----------
add({ id: 'music-list', group: 'music', title: 'Recently Added / Playlists', v: 'v1', tokens: ['detent.list', 'free.spin', 'wall.bounce', 'confirm.tick'],
  feel: 'Detents (SAW)', dpt: '20 / turn', snap: 'Med', damp: 'Low', click: 'On', ends: 'wall.bounce at item 1 and the last item', events: 'Click per item. Button 3 (source) = confirm.tick + feel.fade. Fast flick coasts (free.spin), silent.', sound: 'wood tock per item', pair: 'List rail + ring marker (motion lab: Lists A). Wall: rail stretches 0.15 row.', reduced: 'SINE 20 / turn, click off; no coasting',
  sim: { dur: 3600, angle: kf([[0, 0], [250, -24], [500, -2], [1100, 54], [1300, 54], [1650, 414], [2300, 450], [3000, 486]]), phases: [{ from: 0, feel: 'SAW', dpt: 20, snap: 0.55, damp: 0.15, click: true, min: 0, max: 39, i0: 0, step: 1, free: true }] },
  screen: (h, st) => { const i = Math.round(st.v), A = k => (k < 0 ? '' : ALB[k % 9]); return { ring: RG.marker(40, st.vs ?? st.v, [60, 170, 255]), btns: btns({ 3: [GREEN, 0.68] }), kids: [crumb(h, 'hc' + (st.id || ''), 'MUSIC › ', 'RECENTLY ADDED'), listText(h, { dy: (st.glide || 0) * 10, prev: A(i - 1), cur: A(i), next: A(i + 1), meta: st.coast ? `Coasting · ${i + 1} / 40` : `${i + 1} / 40 · ${ART[i % 9]}` }), footer(h, [{ d: I.back }, { d: I.expand }, { d: I.listMusic }, { d: I.play, col: C.ok }])] }; } });
add({ id: 'music-tracks', group: 'music', title: 'Tracks · browse the queue, 4 jumps', v: 'v1', tokens: ['detent.list', 'wall.bounce', 'nudge.left / nudge.right'],
  feel: 'Detents (SAW)', dpt: '20 / turn', snap: 'Med', damp: 'Low', click: 'On', ends: 'wall.bounce at the first and last track', events: 'Click per row. Tap 4 = nudge in the jump direction (right = later track). At the playing row, 4 = refuse.buzz.', sound: 'wood tock per row; tick-thud on the jump', pair: 'Focus row + queue ring (focus in album colour, playing song warm white).', reduced: 'SINE, click off; nudge → tick',
  sim: { dur: 3600, ev: [[1600, 'bump+']], angle: kf([[0, 0], [200, 0], [1100, 54], [2000, 54], [2900, 160], [3400, 140]]), phases: [{ from: 0, feel: 'SAW', dpt: 20, snap: 0.55, damp: 0.15, click: true, min: 0, max: 9, i0: 2, step: 1 }] },
  screen: (h, st) => { const i = Math.round(st.v), playing = st.t >= 1600 ? i : 2; return { ring: RG.marker(10, st.vs ?? st.v, [60, 170, 255]), btns: btns({ 3: i !== playing ? [GREEN, 0.68] : [WW, 0.12] }), kids: [crumb(h, 'ht', 'MUSIC › ', 'TRACKS'), T(h, QUEUE[i], { y: 60, size: 22 }), T(h, 'Air', { y: 114, size: 14, col: C.sec }), T(h, i === playing ? (st.t >= 1600 ? `Playing ${i + 1} / 10` : 'Turn to browse the queue') : `Skip to ${i + 1} / 10 · 4 plays`, { y: 134, size: 12, col: i === playing && st.t < 1600 ? C.meta : C.succ }), footer(h, [{ d: I.back }, { d: I.expand }, { d: SEEK }, { d: I.play, col: i !== playing ? C.ok : C.dis }])] }; } });
add({ id: 'music-seek', key: st => ({ k: st.t >= 2900 ? 'set' : 'seek', d: 0, s: 'fade' }), group: 'music', title: 'Seek', v: 'v1', tokens: ['fluid.scrub', 'wall.bounce', 'confirm.tick'],
  feel: 'Fluid (VISCOSE)', dpt: 'none', snap: '—', damp: 'Med', click: 'Off', ends: 'wall.bounce at 0:00 and at the end of the song', events: 'None while scrubbing. Button 3 (Set) = confirm.tick. Button 1 (Cancel) = nothing (the position just returns).', sound: 'Tock on Set', pair: 'Big m:ss readout; warm ring arc = position.', reduced: 'Same feel; Set = tick',
  later: 'Later: a soft magnet (SINE well, 1 notch) at the position you started from, so you can find your way back without looking.',
  sim: { dur: 3400, ev: [[2900, 'tick']], angle: kf([[0, 0], [300, 0], [1100, 100], [1500, 100], [2200, -90], [2600, -71]]), phases: [{ from: 0, feel: 'VISCOSE', damp: 0.5, min: 0, max: 252, i0: 64, gain: 0.9 }] },
  screen: (h, st) => { const s = Math.round(st.v), mm = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`, set = st.t >= 2900; return { ring: RG.arc(st.v / 252, WARM, 1, 0), btns: btns({ 2: set ? [GREEN, 0.6] : [WARM, 0.9] }), kids: [bigVal(h, 'Remember', mm, ''), T(h, set ? 'Seek set' : 'of 4:12 · 3 sets · 1 cancels', { y: 134, size: 12, col: set ? C.succ : C.warm }), footer(h, [{ d: I.back }, { d: I.expand }, { d: SEEK, col: C.warm }, { d: I.play, col: C.dis }])] }; } });
add({ id: 'music-upnext', group: 'music', title: 'Up next · like, shuffle', v: 'v1', tokens: ['detent.list', 'confirm.tick', 'wall.bounce'],
  feel: 'Detents (SAW)', dpt: '20 / turn', snap: 'Med', damp: 'Low', click: 'On', ends: 'wall.bounce', events: 'Click per row. Shuffle = confirm.tick. Like = confirm.tick (add-only; liking again = refuse.buzz).', sound: 'wood tock', pair: 'Full-screen queue on the monitor; heart fills pink; LED 3 pink.', reduced: 'SINE, click off',
  later: 'Later: Like as a two-beat "heartbeat" (2 ticks, 120 ms apart).',
  sim: { dur: 3600, ev: [[1500, 'tick'], [2100, 'buzz']], angle: kf([[0, 0], [200, 0], [900, 36], [2400, 36], [3100, 150], [3500, 130]]), phases: [{ from: 0, feel: 'SAW', dpt: 20, snap: 0.55, damp: 0.15, click: true, min: 0, max: 9, i0: 2, step: 1 }] },
  screen: (h, st) => { const i = Math.round(st.v), liked = st.t >= 1500; return { ring: RG.marker(10, st.vs ?? st.v, [60, 170, 255]), btns: btns({ 2: liked ? [[255, 40, 90], 0.3] : [WW, 0.34] }), kids: [crumb(h, 'hu', 'MUSIC › TRACKS › ', 'UP NEXT'), listText(h, { dy: (st.glide || 0) * 10, prev: QUEUE[i - 1] || '', cur: QUEUE[i], next: QUEUE[i + 1] || '', meta: st.t >= 2100 ? 'Unfavourite in Music app' : liked ? 'Liked' : `${i + 1} / 10` }), footer(h, [{ d: I.back }, { d: SHUF }, { d: HEART, col: liked ? '#A3244A' : C.nav, fill: liked ? '#A3244A' : 'none' }, { d: I.play, col: C.ok }])] }; } });
add({ id: 'music-queue', group: 'music', title: 'Hold 4 · Queued / Play next', v: 'v1', tokens: ['hold.tension', 'confirm.thump'],
  feel: '(unchanged: list)', dpt: '—', snap: '—', damp: '—', click: '—', ends: '—', events: 'hold.tension during the 1 s hold (the ring is the timer). confirm.thump on the landing frame.', sound: '110 Hz thud', pair: 'Motion lab Hold-4 A: the icon fills warm with the hold, lands with a small spring and a green ring bloom; "Queued · {title}".', reduced: 'confirm.tick',
  sim: { dur: 2200, ev: [[1300, 'thump']] },
  screen: fromMotion('hold4', 'A', t => ['queue', t - 200]) });

add({ id: 'win-picker', group: 'windows', title: 'Window picker · turn through apps', v: 'v1', tokens: ['detent.coarse', 'wall.bounce'],
  feel: 'Detents (SAW)', dpt: '12 / turn', snap: 'High', damp: 'Low', click: 'On', ends: 'wall.bounce at the first and last window', events: 'Click per window.', sound: 'tick-thud per window', pair: 'Focused card on the monitor; white ring marker.', reduced: 'SINE 12 / turn, snap med, click off',
  sim: { dur: 2800, angle: kf([[0, 0], [200, 0], [1300, 150], [1700, 150], [2300, 172]]), phases: [{ from: 0, feel: 'SAW', dpt: 12, snap: 0.85, damp: 0.2, click: true, clickType: 'thudtick', min: 0, max: 6, i0: 1, step: 1 }] },
  screen: (h, st) => { const i = Math.round(st.v), w = WINS[i]; return { ring: RG.marker(7, st.vs ?? st.v, WHITE, 0.1, WARM), btns: btns({ 3: [GREEN, 0.68] }), kids: [crumb(h, 'hw', '', 'WINDOWS'), T(h, w[1], { y: 60, size: 22 }), T(h, w[0], { y: 114, size: 14, col: C.sec }), T(h, `${i + 1} / 7`, { y: 134, size: 12, col: C.meta }), footer(h, [{ d: I.home }, { d: I.snapL }, { d: I.snapR }, { d: I.check, col: C.ok }])] }; } });
add({ id: 'win-snap', group: 'windows', title: 'Snap left / right · Switch', v: 'v1', tokens: ['nudge.left / nudge.right', 'confirm.tick'],
  feel: '(unchanged: picker)', dpt: '—', snap: '—', damp: '—', click: '—', ends: '—', events: 'Snap left = nudge.left, snap right = nudge.right (the knob "leans" the way the window went). Switch (4) = confirm.tick.', sound: 'tick-thud (left/right panned if stereo)', pair: 'Button 2/3 LED takes the app colour; ring blooms in the app colour.', reduced: 'Unsigned tick; Switch = tick',
  sim: { dur: 2400, ev: [[400, 'bump-'], [1100, 'bump+'], [1800, 'tick']] },
  screen: (h, st) => { const L0 = st.t >= 400, R0 = st.t >= 1100, sw = st.t >= 1800; const c = [217, 119, 87]; return { ring: RG.blend(RG.marker(7, 0, WHITE, 0.1, WARM), RG.fill(c, 0.5), 0.6 * Math.max(bloom(st.t, 400, 140, 500), bloom(st.t, 1100, 140, 500))), btns: btns({ 1: L0 && !R0 ? [c, 1] : [WW, 0.34], 2: R0 ? [c, 1] : [WW, 0.34], 3: [GREEN, 0.68] }), kids: [crumb(h, 'hs', '', 'WINDOWS'), T(h, 'Knob review', { y: 60, size: 22 }), T(h, 'Claude', { y: 114, size: 14, col: C.sec }), T(h, sw ? 'Switched to Claude' : R0 ? 'Snapped right' : L0 ? 'Snapped left' : '1 / 7', { y: 134, size: 12, col: L0 ? C.succ : C.meta }), footer(h, [{ d: I.home }, { d: I.snapL }, { d: I.snapR }, { d: I.check, col: C.ok }])] }; } });

// ---------- LIGHTS ----------
add({ id: 'lights-bri', group: 'lights', title: 'Brightness 1–100 %', v: 'v1', tokens: ['detent.dimmer', 'wall.bounce'],
  feel: 'Soft (SINE), heavier', dpt: '36 / turn · 2 % per step (1 % below 10 %) · 1.4 turns full range', snap: 'Kp 3', damp: 'Kd 0.04 (dimmer weight)', click: 'Off', ends: 'wall.bounce at 1 % and 100 %', events: 'None while turning. Turning from Off lands on 1 % with a confirm.tick.', sound: 'None', pair: 'Big value; Kelvin arc; screen stretches 6 px into the wall and springs back.', reduced: 'VISCOSE Kd 0.05, walls stay',
  later: 'Later: a slightly deeper "landmark" notch at 50 %.',
  sim: { dur: 3300, angle: kf([[0, 0], [300, 0], [1400, 120], [1800, 120], [2500, 222], [3100, 190]]), phases: [{ from: 0, feel: 'SINE', dpt: 36, snap: 0.3, damp: 0.4, click: false, min: 2, max: 100, i0: 62, step: 2 }] },
  screen: (h, st) => ({ ring: RG.arc((st.vs ?? st.v) / 100, kel(3200), 1, 0), kids: [bigVal(h, st.v >= 100 ? 'Brightness · maximum' : 'Brightness', st.v, '%'), footer(h, [{ d: I.home }, { d: I.wand }, { d: I.temp }, { d: I.power }])] }) });
add({ id: 'lights-temp', group: 'lights', title: 'Colour temperature 2200–6500 K', v: 'v1', tokens: ['detent.fine', 'wall.bounce'],
  feel: 'Detents (SAW), fine', dpt: '36 / turn (firmware max) · 100 K each · 1.2 turns', snap: 'Kp 2.5', damp: 'Kd 0.01', click: 'Fine (2× pitch)', ends: 'wall.bounce at 2200 K and 6500 K', events: 'Fine click per 100 K.', sound: 'fine click (high pitch), 0.2 vol', pair: 'Kelvin readout; ring shows the white of the selected temperature with a marker.', reduced: 'SINE 43 / turn, click off',
  later: 'Later: stronger notches at the common whites 2700 / 4000 / 5000 K.',
  sim: { dur: 3400, angle: kf([[0, 0], [300, 0], [1500, 100], [1800, 100], [2700, 350], [3200, 330]]), phases: [{ from: 0, feel: 'SAW', dpt: 36, snap: 0.2, damp: 0.1, click: true, clickType: 'fine', min: 2200, max: 6500, i0: 3200, step: 100 }] },
  screen: (h, st) => ({ ring: RG.arc((st.v - 2200) / 4300, kel(st.v), 1, 0), btns: btns({ 2: [WARM, 0.9] }), kids: [bigVal(h, 'Colour temperature', st.v, 'K'), footer(h, [{ d: I.home }, { d: I.wand }, { d: I.temp, col: C.warm }, { d: I.power }])] }) });
add({ id: 'lights-power', key: st => ({ k: st.t < 400 || st.t >= 1400 ? 'on' : 'off', d: 0, s: 'fade' }), group: 'lights', title: 'All off / Turn on', v: 'v1', tokens: ['confirm.thump'],
  feel: '(unchanged)', dpt: '—', snap: '—', damp: '—', click: '—', ends: '—', events: 'All off = a softer, shorter thump (25 ms). Turn on = full thump (40 ms).', sound: 'Off: 90 Hz thud · On: 110 Hz thud', pair: 'Ring drains to off / fills up from the bottom (motion lab: Lights icons C).', reduced: 'confirm.tick both',
  sim: { dur: 2200, ev: [[400, 'thumpsoft'], [1400, 'thump']] },
  screen: (h, st) => { const on = st.t < 400 || st.t >= 1400; const ring = st.t < 400 ? RG.arc(0.62, kel(3200), 0.34, 0) : st.t < 1400 ? RG.blend(RG.arc(0.62, kel(3200), 0.34, 0), RG.off(), pr(st.t, 400, 500, E.io)) : RG.sweep(RG.off(), RG.arc(0.62, kel(3200), 0.34, 0), pr(st.t, 1400, 520, E.io), RG.bottomUp);
    return { ring, kids: [T(h, 'LIGHTS', { y: 32, size: 12, col: C.sec }), npText(h, { lines: [on ? 'Focus' : 'Lights off'], artist: on ? '62% · 3200 K' : 'Tap 4 to turn on' }), footer(h, [{ d: I.home }, { d: I.wand }, { d: I.temp }, { d: I.power }])] }; } });
add({ id: 'lights-scenes', group: 'lights', title: 'Scenes list · run a scene', v: 'v1', tokens: ['detent.coarse', 'wall.bounce', 'confirm.thump'],
  feel: 'Detents (SAW)', dpt: '12 / turn', snap: 'High', damp: 'Low', click: 'On', ends: 'wall.bounce at the first and last scene', events: 'Click per scene; 4 (Run) = confirm.thump.', sound: 'tick-thud per scene; thud on Run', pair: 'Scene clusters on the ring; green bloom when it runs; wand sparkles.', reduced: 'SINE, click off; Run = tick',
  sim: { dur: 3600, ev: [[3100, 'thump']], angle: kf([[0, 0], [200, 0], [1300, 90], [1600, 90], [2300, 150], [2700, 120]]), phases: [{ from: 0, feel: 'SAW', dpt: 12, snap: 0.85, damp: 0.2, click: true, clickType: 'thudtick', min: 0, max: 4, i0: 0, step: 1 }] },
  screen: (h, st) => { const i = Math.round(st.v), run = st.t >= 3100; let ring = RG.fill(WARM, 0); ring = ring.map((_, k) => { for (let s = 0; s < 5; s++) { const c = s * 12; if (Math.abs(k - c) <= 1) return s === i ? [WARM, 1] : [WARM, 0.18]; } return [WARM, 0]; }); if (run) ring = RG.blend(ring, RG.fill(GREEN, 0.55), bloom(st.t, 3100, 180, 700));
    return { ring, btns: btns({ 1: [WW, 0], 2: [WW, 0], 3: [GREEN, 0.68] }), kids: [crumb(h, 'hn', 'LIGHTS › ', 'SCENES'), listText(h, { dy: (st.glide || 0) * 10, prev: SCN[i - 1] ? SCN[i - 1][0] : '', cur: SCN[i][0], next: SCN[i + 1] ? SCN[i + 1][0] : '', meta: run ? 'Scene running' : `${i + 1} / 5 · ${SCN[i][1]}` }), footer(h, [{ d: I.back }, null, null, { d: I.check, col: C.ok }])] }; } });

// ---------- NAVIGATION ----------
add({ id: 'nav-hold1', key: st => (st.t >= 900 ? { k: 'home', d: 0 } : { k: 'recent', d: 2 }), group: 'nav', title: 'Hold 1 · go Home', v: 'v1', tokens: ['hold.tension', 'confirm.thump', 'feel.fade'],
  feel: 'Current feel → volume', dpt: '—', snap: '—', damp: '—', click: '—', ends: '—', events: 'hold.tension over the 600 ms hold. confirm.thump on landing, then feel.fade to the Home volume feel.', sound: 'Thud on landing', pair: 'Warm hold arc on the ring; Home slides in.', reduced: 'confirm.tick',
  sim: { dur: 1800, ev: [[900, 'thump']] },
  screen: (h, st) => { const hold = st.t >= 300 && st.t < 900, home = st.t >= 900; let ring = RG.marker(9, 3, [60, 170, 255]); if (hold) ring = RG.blend(ring, RG.arc((st.t - 300) / 600, WARM, 1, 0), clamp((st.t - 300) / 80)); if (home) ring = RG.blend(RG.arc(1, WARM, 1, 0), RG.rest(), pr(st.t, 900, 300, E.io));
    return { ring, btns: btns({ 0: hold ? [WARM, 0.9] : [WW, 0.34] }), kids: [home ? [npText(h, { lines: ['Remember'] }), footer(h, [{ d: I.music }, { d: I.win }, { d: I.bulb }, { d: I.pause }])] : [crumb(h, 'h1', 'MUSIC › ', 'RECENTLY ADDED'), listText(h, { dy: (st.glide || 0) * 10, prev: 'Glass Weather', cur: 'Midnight Arcade', next: 'Paper Lanterns', meta: '4 / 9 · Air' }), footer(h, [{ d: I.back }, { d: I.expand }, { d: I.listMusic }, { d: I.play, col: C.ok }])]] }; } });
add({ id: 'nav-change', key: st => (st.t >= 1200 ? { k: 'recent', d: 2 } : st.t > 300 ? { k: 'mbig', d: 1, s: 'reveal' } : { k: 'music', d: 1 }), group: 'nav', title: 'Screen changes (buttons 1–3)', v: 'v1', tokens: ['feel.fade'],
  feel: 'Previous → next context', dpt: 'e.g. 36 → 20 / turn', snap: 'Fades in over 120 ms', damp: '—', click: 'Per context', ends: '—', events: 'No event haptic: the button\'s own mechanical click is the feedback. Only the feel changes, re-anchored under the finger.', sound: 'None', pair: 'Screen push (motion lab: Depth C).', reduced: 'Same',
  sim: { dur: 2800, angle: kf([[0, 0], [300, 0], [1000, 30], [1600, 30], [2600, 72]]), phases: [{ from: 0, feel: 'SINE', dpt: 36, snap: 0.3, damp: 0.1, click: false, min: 0, max: 100, i0: 34, step: 1 }, { from: 1200, feel: 'SAW', dpt: 20, snap: 0.55, damp: 0.15, click: true, min: 0, max: 8, i0: 0, step: 1, fadeIn: 120 }] },
  screen: (h, st) => st.t < 1200 ? { ring: RG.arc((st.vs ?? st.v) / 100, WARM, 1, 0.08), kids: [st.t > 300 ? bigVal(h, 'Remember', st.v, '%') : npText(h, { lines: ['Remember'] }), footer(h, [{ d: I.home }, { d: I.album }, { d: I.list }, { d: I.pause }])] }
    : { ring: RG.marker(9, st.vs ?? st.v, [60, 170, 255]), btns: btns({ 1: st.t < 1320 ? [WW, 0.9] : [WW, 0.34], 3: [GREEN, 0.68] }), kids: [crumb(h, 'hx', 'MUSIC › ', 'RECENTLY ADDED'), listText(h, { dy: (st.glide || 0) * 10, prev: st.v >= 1 ? ALB[Math.round(st.v) - 1] : '', cur: ALB[Math.round(st.v)], next: ALB[Math.round(st.v) + 1], meta: `${Math.round(st.v) + 1} / 9` }), footer(h, [{ d: I.back }, { d: I.expand }, { d: I.listMusic }, { d: I.play, col: C.ok }])] } });
add({ id: 'nav-ends', group: 'nav', title: 'Reaching the end of a list', v: 'v1', tokens: ['wall.bounce'],
  feel: 'Detents + wall', dpt: '20 / turn', snap: 'Med', damp: 'Low', click: 'On until the wall', ends: 'wall.bounce: spring ramps 0 → 3 × Kp, no click, no buzz however often you push; lets go back to the last item', events: 'None at the wall.', sound: 'Silent at the wall', pair: 'The list stretches with the push (6 px max, following the spring, not a timed animation) and settles back with the knob; the end LEDs brighten while you push.', reduced: 'Same wall',
  sim: { dur: 3000, angle: kf([[0, 0], [200, 0], [700, 36], [1100, 50], [1400, 36], [1800, 52], [2100, 36]]), phases: [{ from: 0, feel: 'SAW', dpt: 20, snap: 0.55, damp: 0.15, click: true, min: 0, max: 8, i0: 6, step: 1 }] },
  screen: (h, st) => { const i = Math.round(st.v); return { ring: RG.marker(9, (st.vs ?? st.v) + (st.pen > 0 ? 0.15 * clamp(st.pen / 12) : 0), [60, 170, 255]), btns: btns({ 3: [GREEN, 0.68] }), kids: [crumb(h, 'he', 'MUSIC › ', 'RECENTLY ADDED'), listText(h, { dy: (st.glide || 0) * 10, prev: ALB[i - 1] || '', cur: ALB[i], next: ALB[i + 1] || '', meta: `${i + 1} / 9` }), footer(h, [{ d: I.back }, { d: I.expand }, { d: I.listMusic }, { d: I.play, col: C.ok }])] }; } });
add({ id: 'nav-sleep', key: st => (st.t > 900 ? { k: 'big', d: 0, s: 'reveal' } : st.t >= 300 ? { k: 'awake', d: 0, s: 'wake' } : { k: 'asleep', d: 0 }), group: 'nav', title: 'Sleep and wake', v: 'v1', tokens: ['feel.fade'],
  feel: 'Asleep: fluid.light · awake: context feel', dpt: '— → 36 / turn', snap: '0 → Low over 150 ms', damp: 'Low', click: 'Off while asleep', ends: '—', events: 'The first touch only wakes: no event, no value change. Detents fade in over 150 ms so the second notch is the first that counts.', sound: 'None', pair: 'Backlight up 120 ms; ring to warm rest (motion lab: Sleep A).', reduced: 'Same',
  sim: { dur: 2600, angle: kf([[0, 0], [300, 0], [500, 8], [900, 8], [1800, 40]]), phases: [{ from: 0, feel: 'VISCOSE', damp: 0.15, min: 34, max: 34, i0: 34, gain: 0 }, { from: 700, feel: 'SINE', dpt: 36, snap: 0.3, damp: 0.1, click: false, min: 0, max: 100, i0: 34, step: 1, fadeIn: 150 }] },
  screen: (h, st) => { const awake = st.t >= 300, bl = pr(st.t, 300, 120); return { bl, ring: awake ? RG.blend(RG.fill(WARM, 0.04), st.t > 900 ? RG.arc((st.vs ?? st.v) / 100, WARM, 1, 0.08) : RG.rest(), pr(st.t, 300, 120)) : RG.fill(WARM, 0.04), kids: [st.t > 900 ? bigVal(h, 'Remember', st.v, '%') : npText(h, { lines: ['Remember'] }), T(h, st.t >= 300 && st.t < 900 ? 'First touch: wake only' : '', { y: 134, size: 12, col: C.meta }), footer(h, [{ d: I.music }, { d: I.win }, { d: I.bulb }, { d: I.pause }])] }; } });

// ---------- MOMENTS ----------
const MOM = (id, title, tok, evs, ev, txt, col, ringFx, extra = {}) => add(Object.assign({ id, group: 'moments', title, v: 'v1', tokens: [tok], feel: '(event only)', dpt: '—', snap: '—', damp: '—', click: '—', ends: '—', events: evs,
  sim: { dur: 1600, ev: [[400, ev]] },
  screen: (h, st) => ({ ring: ringFx(st.t), kids: [npText(h, { lines: [extra.title || 'Long Range'], artist: extra.artist || 'Air' }), status(h, txt, col, st.t, 400), footer(h, extra.foot || [{ d: I.home }, { d: I.album }, { d: I.list }, { d: I.pause }])] }) }, extra.meta));
const flashR = (rgb, a = 0.55) => t => RG.blend(RG.rest(), RG.fill(rgb, a), bloom(t, 400, 160, 600));
MOM('m-skip', 'Track change (skip ±1)', 'nudge.left / nudge.right', 'nudge.right for next, nudge.left for previous, on the press frame.', 'bump+', 'Playing 4 / 10', C.succ, t => RG.rest(), { meta: { sound: 'tick-thud', pair: 'Stagger slide of title and artist.', reduced: 'Unsigned tick' } });
MOM('m-start', 'Started (album / playlist)', 'confirm.thump', 'confirm.thump when playback starts from a list.', 'thump', 'Queue replaced', C.succ, flashR(GREEN), { meta: { sound: '110 Hz thud', pair: 'Ring green bloom; Music screen pushes in.', reduced: 'confirm.tick' } });
MOM('m-like', 'Liked', 'confirm.tick', 'confirm.tick. Liking a liked song again is refuse.buzz (add-only).', 'tick', 'Liked', '#FF7AA0', flashR([255, 40, 90], 0.35), { meta: { sound: 'wood tock', pair: 'Heart fills; LED 3 pink.', reduced: 'Tick at 50 %', later: 'Later: two-beat "heartbeat".' } });
MOM('m-shuffle', 'Shuffle on / off', 'confirm.tick', 'confirm.tick.', 'tick', 'Shuffle on', C.warm, t => RG.rest(), { meta: { sound: 'wood tock', pair: 'Shuffle icon and LED 2 warm.', reduced: 'Tick at 50 %' } });
MOM('m-refused', 'Refused (nothing to queue)', 'refuse.buzz', 'refuse.buzz on the press frame; nothing else happens.', 'buzz', 'Nothing loaded · pick in Recent', C.no, t => RG.blend(RG.rest(), RG.over(RG.rest(), [27, 28, 29, 30, 31, 32, 33], RED, 0.7), bloom(t, 400, 120, 480)), { meta: { sound: '3 soft ticks', pair: 'Bottom ring LEDs glow red; reason in the status line.', reduced: 'Single nudge' } });
MOM('m-error', 'Error (lights unreachable)', 'error.buzz', 'error.buzz: slower and heavier than refuse, once.', 'errbuzz', 'Lights unavailable', C.no, t => RG.blend(RG.off(), RG.fill(RED, 0.4), bloom(t, 400, 200, 900)), { title: 'Lights unavailable', artist: 'Hall · 3 lights', foot: [{ d: I.home }, { d: I.wand, col: C.dis }, { d: I.temp, col: C.dis }, { d: I.power, col: C.dis }], meta: { sound: '3 low ticks', pair: 'Whole ring blooms dim red once, then off.', reduced: 'Single nudge' } });
MOM('m-snapped', 'Window snapped', 'nudge.left / nudge.right', 'Signed nudge in the snap direction.', 'bump-', 'Snapped left', C.succ, flashR([217, 119, 87], 0.45), { title: 'Knob review', artist: 'Claude', foot: [{ d: I.home }, { d: I.snapL }, { d: I.snapR }, { d: I.check, col: C.ok }], meta: { sound: 'tick-thud', pair: 'LED 2 in the app colour.', reduced: 'Unsigned tick' } });
MOM('m-queued', 'Queued', 'confirm.thump', 'confirm.thump on the hold-4 landing frame.', 'thump', 'Queued · Midnight Arcade', C.succ, flashR(GREEN), { meta: { sound: '110 Hz thud', pair: 'Green bloom (Hold-4 A).', reduced: 'confirm.tick' } });
MOM('m-swapped', 'Domain swapped', 'confirm.thump', 'confirm.thump + feel.fade to the new domain\'s feel.', 'thump', 'Knob sets brightness', C.warm, t => RG.sweep(RG.rest(), RG.arc(0.62, kel(3200), 0.34, 0), pr(t, 400, 520, E.io), RG.cw), { meta: { sound: '110 Hz thud', pair: 'Ring sweep (Domain swap A).', reduced: 'confirm.tick' } });

// ---------- ONSHAPE ----------
const OS = (h, st, label, val, foot, btn) => ({ ring: RG.arc(clamp(st.v / 400), WHITE, 0.8, 0), btns: btns(btn || {}), kids: [crumb(h, 'ho' + label, 'ONSHAPE › ', label), T(h, val, { y: 60, size: 22 }), T(h, 'Nano D enclosure', { y: 114, size: 14, col: C.sec }), footer(h, foot)] });
const OSF = [{ d: I.home }, { d: ORBIT }, { d: PAN }, { d: UNDO }];
add({ id: 'os-zoom', group: 'onshape', title: 'Onshape · zoom (turn)', v: 'later', tokens: ['detent.value'],
  feel: 'Soft (SINE)', dpt: '24 / turn (each = 10 % zoom)', snap: 'Low', damp: 'Low', click: 'Off', ends: 'None (zoom is unbounded; the CAD app clamps)', events: 'None.', sound: 'None', pair: 'Zoom % on the knob; white arc.', reduced: 'fluid.light',
  sim: { dur: 2600, angle: kf([[0, 0], [300, 0], [1500, 90], [1900, 90], [2500, 60]]), phases: [{ from: 0, feel: 'SINE', dpt: 24, snap: 0.25, damp: 0.1, click: false, min: 10, max: 1000, i0: 140, step: 10 }] },
  screen: (h, st) => OS(h, st, 'ZOOM', `Zoom ${st.v} %`, OSF) });
add({ id: 'os-orbit', key: st => ({ k: st.t < 300 ? 'zoom' : 'orbit', d: 0, s: 'fade' }), group: 'onshape', title: 'Onshape · hold 2 + turn = orbit', v: 'later', tokens: ['fluid.orbit', 'feel.fade', 'free.spin'],
  feel: 'Fluid (VISCOSE), light', dpt: 'none', snap: '—', damp: 'Low', click: 'Off', ends: 'None (orbit wraps)', events: 'Pressing 2 fades from zoom detents to fluid (feel.fade, 120 ms). A flick coasts. Release restores zoom detents under the finger.', sound: 'None', pair: 'Orbit angle on the knob; LED 2 lit while held.', reduced: 'Fluid, no coasting',
  sim: { dur: 3000, angle: kf([[0, 0], [400, 0], [1200, 120], [1500, 300], [2300, 330]]), phases: [{ from: 0, feel: 'SINE', dpt: 24, snap: 0.25, damp: 0.1, click: false, min: 10, max: 1000, i0: 140, step: 10 }, { from: 300, feel: 'VISCOSE', damp: 0.2, min: -1e6, max: 1e6, i0: 0, gain: 1, free: true, fadeIn: 120 }] },
  screen: (h, st) => OS(h, st, 'ORBIT', st.t < 300 ? 'Zoom 140 %' : `Orbit ${Math.round(((st.v % 360) + 360) % 360)}°${st.coast ? ' · coasting' : ''}`, OSF, { 1: st.t >= 300 ? [WW, 0.9] : [WW, 0.34] }) });
add({ id: 'os-pan', key: st => ({ k: st.t < 300 ? 'zoom' : 'pan', d: 0, s: 'fade' }), group: 'onshape', title: 'Onshape · hold 3 + turn = pan', v: 'later', tokens: ['fluid.scrub', 'feel.fade'],
  feel: 'Fluid (VISCOSE), medium', dpt: 'none', snap: '—', damp: 'Med', click: 'Off', ends: 'None', events: 'feel.fade on press and release.', sound: 'None', pair: 'Pan offset on the knob; LED 3 lit while held.', reduced: 'Same',
  sim: { dur: 2600, angle: kf([[0, 0], [400, 0], [1600, 80], [2200, 60]]), phases: [{ from: 0, feel: 'SINE', dpt: 24, snap: 0.25, damp: 0.1, click: false, min: 10, max: 1000, i0: 140, step: 10 }, { from: 300, feel: 'VISCOSE', damp: 0.5, min: -1e6, max: 1e6, i0: 0, gain: 1 }] },
  screen: (h, st) => OS(h, st, 'PAN', st.t < 300 ? 'Zoom 140 %' : `Pan ${Math.round(st.v)} px`, OSF, { 2: st.t >= 300 ? [WW, 0.9] : [WW, 0.34] }) });
add({ id: 'os-undo', group: 'onshape', title: 'Onshape · tap 4 = undo', v: 'later', tokens: ['confirm.tick', 'refuse.buzz'],
  feel: '(unchanged: zoom)', dpt: '—', snap: '—', damp: '—', click: '—', ends: '—', events: 'confirm.tick per undo; refuse.buzz when there is nothing to undo.', sound: 'wood tock / 3 soft ticks', pair: 'Status "Undone · Extrude 2".', reduced: 'Tick / single nudge',
  sim: { dur: 2200, ev: [[400, 'tick'], [1300, 'buzz']] },
  screen: (h, st) => { const r = OS(h, st, 'ZOOM', 'Zoom 140 %', OSF); r.kids.push(T(h, st.t >= 1300 ? 'Nothing to undo' : st.t >= 400 ? 'Undone · Extrude 2' : '', { y: 134, size: 12, col: st.t >= 1300 ? C.no : C.succ })); return r; } });


// ---------- CREATIVE ----------
add({ id: 'idea-heavy-volume', group: 'ideas', title: 'Volume gets heavier as it gets louder', v: 'later', tokens: ['detent.value'],
  feel: 'Soft (SINE), damping rises with value', dpt: '36 / turn', snap: 'Kp 3', damp: 'Kd 0.01 → 0.06 above 80 %', click: 'Off', ends: 'wall.bounce at 100 %', events: 'None.', sound: 'None', pair: 'Arc head warms towards amber-red above 80 %.', reduced: 'Constant Kd',
  why: 'A physical warning before it gets loud, without a sound or a pop-up. One line in the control loop: Kd = lerp(0.01, 0.06, clamp((v − 80) / 20)).',
  sim: { dur: 3200, angle: kf([[0, 0], [300, 0], [2400, 290], [2900, 270]]), phases: [{ from: 0, feel: 'SINE', dpt: 36, snap: 0.3, damp: 0.1, click: false, min: 0, max: 100, i0: 72, step: 1 }] },
  screen: (h, st) => ({ ring: RG.arc((st.vs ?? st.v) / 100, st.v > 80 ? [255, Math.round(190 - (st.v - 80) * 3), 105] : WARM, 1, 0.08), kids: [bigVal(h, st.v > 80 ? 'Remember · heavier' : 'Remember', st.v, '%'), footer(h, [{ d: I.music }, { d: I.win }, { d: I.bulb }, { d: I.pause }])] }) });
add({ id: 'idea-push-off', key: st => ({ k: st.t >= 1900 ? 'off' : 'on', d: 0, s: 'fade' }), group: 'ideas', title: 'Push past 1 % to turn the lights off', v: 'later', tokens: ['wall.bounce', 'hold.tension', 'confirm.thump'],
  feel: 'detent.dimmer', dpt: '36 / turn', snap: 'Kp 3', damp: 'Kd 0.04', click: 'Off', ends: 'Hold the 1 % wall for 600 ms → lights off', events: 'Pushing into the 1 % wall starts a 600 ms charge (bottom LEDs fill). Keep pushing → soft thump, lights off. Let go early → normal wall bounce.', sound: 'Soft thud on off', pair: 'Bottom ring LEDs fill left and right towards 6 o’clock, then the ring drains.', reduced: 'Off (use button 4)',
  why: 'Turning a dimmer all the way down is the most natural way to switch a light off. The wall makes it deliberate: you can’t do it by accident mid-turn.',
  sim: { dur: 3000, ev: [[1900, 'thumpsoft']], angle: kf([[0, 0], [300, 0], [1100, -120], [1300, -126], [1900, -128], [2300, -110]]), phases: [{ from: 0, feel: 'SINE', dpt: 36, snap: 0.3, damp: 0.4, click: false, min: 2, max: 100, i0: 14, step: 2 }] },
  screen: (h, st) => { const off = st.t >= 1900, ch = st.pen > 3 && !off ? clamp((st.t - 1300) / 600) : 0; let ring = off ? RG.blend(RG.arc(0.02, kel(3200), 1, 0), RG.off(), pr(st.t, 1900, 400, E.io)) : RG.arc((st.vs ?? st.v) / 100, kel(3200), 1, 0);
    if (ch > 0) ring = ring.map((sg, i) => { const d = Math.min(Math.abs(i - 30), 60 - Math.abs(i - 30)); return d <= 8 * ch ? [kel(2700), 0.9] : sg; });
    return { ring, kids: [off ? npText(h, { lines: ['Lights off'], artist: 'Tap 4 to turn on' }) : bigVal(h, ch > 0 ? 'Keep pushing to turn off' : 'Brightness', st.v, '%'), footer(h, [{ d: I.home }, { d: I.wand }, { d: I.temp }, { d: I.power }])] }; } });
add({ id: 'idea-hold-temp', key: st => ({ k: st.phase === 1 ? 'temp' : 'bri', d: 0, s: 'reveal' }), group: 'ideas', title: 'Hold 3 + turn = temperature, let go = back to brightness', v: 'later', tokens: ['feel.fade', 'detent.fine', 'detent.dimmer'],
  feel: 'dimmer → fine while held', dpt: '36 → 36 / turn (feel changes)', snap: 'Kp 3 → 2.5', damp: 'Kd 0.04 → 0.01', click: 'Off → fine click', ends: 'wall.bounce on both ranges', events: 'feel.fade on press and on release. No mode to forget: the knob returns to brightness when you let go.', sound: 'Fine clicks only while held', pair: 'LED 3 lit while held; ring shows the Kelvin white.', reduced: 'Same, no clicks',
  why: 'The firmware’s app profiles already change feel while a key is held (Onshape orbit/pan). A spring-loaded mode can’t be left on by mistake, and it frees button 3.',
  sim: { dur: 3000, angle: kf([[0, 0], [300, 0], [900, 60], [1100, 60], [2000, 130], [2300, 130], [2800, 160]]), phases: [{ from: 0, feel: 'SINE', dpt: 36, snap: 0.3, damp: 0.4, click: false, min: 2, max: 100, i0: 62, step: 2 }, { from: 1000, feel: 'SAW', dpt: 36, snap: 0.2, damp: 0.1, click: true, clickType: 'fine', min: 2200, max: 6500, i0: 3200, step: 100, fadeIn: 120 }, { from: 2200, feel: 'SINE', dpt: 36, snap: 0.3, damp: 0.4, click: false, min: 2, max: 100, i0: 74, step: 2, fadeIn: 120 }] },
  screen: (h, st) => { const held = st.phase === 1; return { ring: held ? RG.arc((st.v - 2200) / 4300, kel(st.v), 1, 0) : RG.arc((st.vs ?? st.v) / 100, kel(3200), 1, 0), btns: btns({ 2: held ? [WARM, 0.9] : [WW, 0.34] }), kids: [held ? bigVal(h, 'Colour temperature · hold 3', st.v, 'K') : bigVal(h, 'Brightness', st.v, '%'), footer(h, [{ d: I.home }, { d: I.wand }, { d: I.temp, col: held ? C.warm : C.nav }, { d: I.power }])] }; } });
add({ id: 'idea-seek-magnet', group: 'ideas', title: 'Seek remembers where you started', v: 'later', tokens: ['fluid.scrub', 'wall.bounce'],
  feel: 'Fluid + one magnet notch', dpt: '1 SINE well at the start position', snap: 'Kp 4 in a ±6° window', damp: 'Kd 0.08', click: 'Off', ends: 'wall.bounce at 0:00 and the end', events: 'Passing the start position you feel a soft notch; stop in it to cancel without looking.', sound: 'None', pair: 'A warm tick on the ring marks the start position.', reduced: 'No magnet',
  why: 'You can scrub away and find your way back by touch. Needs a firmware addition: a single SINE well centred on a stored angle, blended with VISCOSE.',
  sim: { dur: 3000, angle: kf([[0, 0], [300, 0], [1100, 90], [1400, 90], [2200, 2], [2800, 0]]), phases: [{ from: 0, feel: 'VISCOSE', damp: 0.5, min: 0, max: 252, i0: 64, gain: 0.9 }] },
  screen: (h, st) => { const s0 = Math.round(st.v), mm = `${Math.floor(s0 / 60)}:${String(s0 % 60).padStart(2, '0')}`, near = Math.abs(st.v - 64) < 4 && st.t > 1500; let ring = RG.arc(st.v / 252, WARM, 1, 0); const mk = Math.round(64 / 252 * 45); ring = ring.map((sg, i) => ((i - 38 + 60) % 60 === mk ? [[255, 255, 255], near ? 1 : 0.6] : sg));
    return { ring, kids: [bigVal(h, 'Remember', mm, ''), T(h, near ? 'Back where you started · 1 cancels' : 'of 4:12 · 3 sets · 1 cancels', { y: 134, size: 12, col: near ? C.succ : C.warm }), footer(h, [{ d: I.back }, { d: I.expand }, { d: SEEK, col: C.warm }, { d: I.play, col: C.dis }])] }; } });
add({ id: 'idea-scene-switch', group: 'ideas', title: 'Scenes feel like a rotary switch', v: 'later', tokens: ['detent.coarse', 'wall.bounce'],
  feel: 'SAW, very strong, spacing = one scene', dpt: 'max(3, scenes) per 180° (5 scenes → 10 / turn)', snap: 'Kp 14', damp: 'Kd 0.03', click: 'On (tick-thud)', ends: 'wall.bounce', events: 'Each scene is a heavy click-stop; Run = thump.', sound: 'tick-thud, 40 %', pair: 'Scene clusters on the ring are spaced to match the notches.', reduced: 'SINE, Kp 8',
  why: 'Few, heavy positions make a scene choice feel like flipping a physical switch, and the notch count tells you how many scenes exist.',
  sim: { dur: 2800, angle: kf([[0, 0], [300, 0], [1600, 108], [2000, 108], [2500, 140], [2800, 128]]), phases: [{ from: 0, feel: 'SAW', dpt: 10, snap: 1, damp: 0.2, click: true, clickType: 'thudtick', min: 0, max: 4, i0: 1, step: 1 }] },
  screen: (h, st) => { const i = Math.round(st.v); const ring = RG.fill(WARM, 0).map((_, k) => { for (let s2 = 0; s2 < 5; s2++) { const c = 38 + s2 * 6; if (Math.abs(((k - c + 60) % 60)) <= 1 || Math.abs(((c - k + 60) % 60)) <= 1) return s2 === i ? [WARM, 1] : [WARM, 0.18]; } return [WARM, 0]; });
    return { ring, btns: btns({ 1: [WW, 0], 2: [WW, 0], 3: [GREEN, 0.68] }), kids: [crumb(h, 'hk', 'LIGHTS › ', 'SCENES'), listText(h, { dy: (st.glide || 0) * 10, prev: SCN[i - 1] ? SCN[i - 1][0] : '', cur: SCN[i][0], next: SCN[i + 1] ? SCN[i + 1][0] : '', meta: `${i + 1} / 5 · ${SCN[i][1]}` }), footer(h, [{ d: I.back }, null, null, { d: I.check, col: C.ok }])] }; } });

CTX.find(c => c.id === 'm-skip').screen = fromMotion('track', 'A', t => ['next', t - 250]);
CTX.find(c => c.id === 'm-skip').pair = 'Motion lab Track change A: old lines lift 3 px and fade together; the new title and artist rise 5 px into place, 30 ms apart.';
/* ---------- simulation ---------- */
const REDUCED_EV = { click: 'soft', fine: 'soft', thudtick: 'soft', thump: 'tick', thumpsoft: 'tick', buzz: 'bump+', errbuzz: 'bump+' };
const CACHE = new Map();
function simulate(ctx, reduced) {
  const key = ctx.id + (reduced ? 'r' : ''); if (CACHE.has(key)) return CACHE.get(key);
  const S = ctx.sim, evs = [], frames = [], ph = S.phases || [];
  let lastN = null, lastPh = -1, prevA = 0, wallOn = false, wallStart = 0, coast = false, anchor = 0;
  for (let t = 0; t <= S.dur; t += 4) {
    const a = S.angle ? S.angle(t) : 0, w = Math.abs(a - prevA) / 0.004; prevA = a;
    let pi = -1; ph.forEach((p, i) => { if (t >= p.from) pi = i; }); const p = ph[pi];
    const f = { t, a, v: 0, pen: 0, wdir: 0, coast: false, phase: pi, snapK: 1 };
    if (p) {
      if (pi !== lastPh) { anchor = a; lastN = 0; if (lastPh >= 0) evs.push({ t, type: 'feel' }); lastPh = pi; }
      const rel = a - anchor, fm = p.fadeIn ? clamp((t - p.from) / p.fadeIn) : 1; f.snapK = fm;
      if (p.free) { if (!coast && w > 720) coast = true; else if (coast && w < 180) coast = false; } else coast = false; f.coast = coast;
      if (p.feel === 'VISCOSE') { let v = p.i0 + rel * (p.gain || 0); if (v > p.max) { f.pen = (v - p.max) / Math.max(1e-6, p.gain); f.wdir = 1; v = p.max; } if (v < p.min) { f.pen = (p.min - v) / Math.max(1e-6, p.gain); f.wdir = -1; v = p.min; } f.v = v; }
      else { const pitch = 360 / p.dpt, n = Math.round(rel / pitch), nMax = (p.max - p.i0) / p.step, nMin = (p.min - p.i0) / p.step, nc = clamp(n, nMin, nMax);
        f.v = Math.round((p.i0 + nc * p.step) * 100) / 100; if (n > nMax) { f.pen = rel - nMax * pitch; f.wdir = 1; } else if (n < nMin) { f.pen = nMin * pitch - rel; f.wdir = -1; }
        if (nc !== lastN && lastN !== null && !coast) { let type = p.click ? (p.clickType || 'click') : 'soft'; if (reduced && REDUCED_EV[type]) type = REDUCED_EV[type]; evs.push({ t, type }); }
        lastN = nc; }
      const inWall = f.pen > pitchOf(p) * 0.25; if (inWall && !wallOn) { wallOn = true; wallStart = t; } if (!inWall && wallOn) { wallOn = false; evs.push({ t: wallStart, t1: t, type: 'wall' }); }
    }
    frames.push(f);
  }
  { const k = 503.6, c = 44.9; let x = null, vel = 0, pp = -1; frames.forEach(f => { if (f.phase !== pp) { x = f.v; vel = 0; pp = f.phase; } const a = k * (f.v - x) - c * vel; vel += a * 0.004; x += vel * 0.004; f.sv = x; f.glide = Math.round(x) - x; }); }
  if (wallOn) evs.push({ t: wallStart, t1: S.dur, type: 'wall' });
  (S.ev || []).forEach(([t, type]) => evs.push({ t, type: reduced && REDUCED_EV[type] ? REDUCED_EV[type] : type }));
  // coasting spans
  let cs = null; frames.forEach(f => { if (f.coast && cs == null) cs = f.t; if (!f.coast && cs != null) { evs.push({ t: cs, t1: f.t, type: 'coast' }); cs = null; } });
  evs.sort((x, y) => x.t - y.t);
  const out = { frames, evs }; CACHE.set(key, out); return out;
}
const pitchOf = p => (p && p.dpt ? 360 / p.dpt : 20);
function stateAt(ctx, reduced, t) { const sim = simulate(ctx, reduced), f = sim.frames[Math.max(0, Math.min(sim.frames.length - 1, Math.round(t / 4)))]; const o = Object.assign({ evs: sim.evs }, f, { t, raw: f.v }); const ph = ctx.sim.phases && ctx.sim.phases[f.phase]; if (f.sv != null && ph) { o.vs = f.sv; if (ph.feel !== 'VISCOSE') { const stp = ph.step || 1; o.v = Math.round(f.sv / stp) * stp; o.glide = (o.v - f.sv) / stp; } } return o; }

/* ---------- visuals ---------- */
const INK = '#201e1d', MUTE = '#9b9797', ACC = '#ec3013', GRID = '#d9d6d5';
function torque(p, th, w, reduced) { if (!p) return 0; const pitch = pitchOf(p);
  const nMax = p.feel === 'VISCOSE' ? Infinity : (p.max - p.i0) / p.step * pitch, nMin = p.feel === 'VISCOSE' ? -Infinity : (p.min - p.i0) / p.step * pitch;
  if (th > nMax + pitch / 2) return -Math.min(1.7, 0.1 + (th - nMax - pitch / 2) / pitch * (p.feel === 'SINE' ? 1.2 : 2));
  if (th < nMin - pitch / 2) return Math.min(1.7, 0.1 + (nMin - pitch / 2 - th) / pitch * (p.feel === 'SINE' ? 1.2 : 2));
  let feel = p.feel; if (reduced && feel === 'SAW') feel = 'SINE';
  if (feel === 'VISCOSE') return -Math.sign(w || 1) * p.damp * (w ? Math.min(1, Math.abs(w) / 300) + 0.15 : 0.5);
  const x = th / pitch, ph = x - Math.round(x), snap = (p.snap || 0.4) * (reduced ? 0.7 : 1);
  return feel === 'SAW' ? -snap * 2 * ph : -snap * Math.sin(2 * Math.PI * ph);
}
function curveEl(h, ctx, st, reduced) {
  const W = 340, H = 150, mid = 75, p = (ctx.sim.phases || [])[st.phase];
  const kids = [h('rect', { key: 'bg', x: 0, y: 0, width: W, height: H, fill: '#fff' }), h('line', { key: 'ax', x1: 0, y1: mid, x2: W, y2: mid, stroke: GRID, strokeWidth: 1 })];
  if (!p) { kids.push(h('text', { key: 'n', x: 12, y: mid - 8, fontSize: 12, fill: MUTE, fontFamily: 'Archivo, sans-serif' }, 'No turning in this moment: event haptics only')); return h('svg', { width: W, height: H, viewBox: `0 0 ${W} ${H}`, style: { display: 'block', border: `2px solid ${INK}` } }, ...kids); }
  const pitch = pitchOf(p), span = p.feel === 'VISCOSE' ? 120 : clamp(pitch * 5, 30, 180), rel = st.a - (anchorOf(ctx, st)), w = angVel(ctx, st.t);
  const pts = []; for (let i = 0; i <= 160; i++) { const th = rel - span / 2 + span * i / 160; const tq = torque(p, th, p.feel === 'VISCOSE' ? w : 0, reduced) * st.snapK; pts.push(`${(i / 160 * W).toFixed(1)},${(mid - tq * 38).toFixed(1)}`); }
  if (p.feel !== 'VISCOSE') for (let k = Math.ceil((rel - span / 2) / pitch); k * pitch <= rel + span / 2; k++) { const x = ((k * pitch - (rel - span / 2)) / span) * W; kids.push(h('line', { key: 'd' + k, x1: x, y1: mid - 6, x2: x, y2: mid + 6, stroke: MUTE, strokeWidth: 1 })); }
  kids.push(h('polyline', { key: 'c', points: pts.join(' '), fill: 'none', stroke: INK, strokeWidth: 2, strokeLinejoin: 'round' }));
  const tq0 = torque(p, rel, p.feel === 'VISCOSE' ? w : 0, reduced) * st.snapK;
  kids.push(h('line', { key: 'cur', x1: W / 2, y1: 8, x2: W / 2, y2: H - 8, stroke: ACC, strokeWidth: 1, strokeDasharray: '3 3' }), h('circle', { key: 'dot', cx: W / 2, cy: mid - tq0 * 38, r: 5, fill: ACC }));
  const label = (p.feel === 'VISCOSE' ? 'VISCOSE · resistance ∝ speed' : `${reduced && p.feel === 'SAW' ? 'SINE (reduced)' : p.feel} · ${p.dpt} / turn · snap ${(p.snap * (reduced ? 0.7 : 1)).toFixed(2)}`) + (st.snapK < 1 ? ' · fading in' : '') + (st.coast ? ' · FREE SPIN' : '') + (st.pen > pitch * 0.25 ? ' · WALL' : '');
  kids.push(h('text', { key: 'l', x: 10, y: 18, fontSize: 11, fill: INK, fontFamily: 'Archivo, sans-serif', fontWeight: 600, letterSpacing: 0.5 }, label.toUpperCase()), h('text', { key: 'y', x: 10, y: H - 10, fontSize: 10, fill: MUTE, fontFamily: 'Archivo, sans-serif' }, 'torque vs knob angle (window follows the knob)'));
  return h('svg', { width: W, height: H, viewBox: `0 0 ${W} ${H}`, style: { display: 'block', border: `2px solid ${INK}` } }, ...kids);
}
const anchorOf = (ctx, st) => { const sim = simulate(ctx, false); const p = ctx.sim.phases[st.phase]; if (!p) return 0; const f = sim.frames[Math.round(p.from / 4)] || sim.frames[0]; return p.from ? f.a : 0; };
const angVel = (ctx, t) => ctx.sim.angle ? (ctx.sim.angle(t + 8) - ctx.sim.angle(t - 8)) / 0.016 : 0;
const GLYPH = { click: [28, 'spike'], fine: [16, 'spike'], thudtick: [24, 'spike'], soft: [9, 'sine'], tick: [18, 'spike'], 'bump+': [24, 'bump'], 'bump-': [-24, 'bump'], thump: [34, 'thump'], thumpsoft: [24, 'thump'], buzz: [20, 'buzz'], errbuzz: [28, 'ebuzz'] };
function waveEl(h, ctx, st, reduced) {
  const W = 340, H = 96, mid = 56, dur = ctx.sim.dur, X = t => t / dur * W, sim = simulate(ctx, reduced), kids = [h('rect', { key: 'bg', x: 0, y: 0, width: W, height: H, fill: '#fff' }), h('line', { key: 'ax', x1: 0, y1: mid, x2: W, y2: mid, stroke: GRID })];
  sim.evs.forEach((e, i) => { const x = X(e.t), past = e.t <= st.t, col = past ? ACC : MUTE;
    if (e.type === 'wall' || e.type === 'coast') { kids.push(h('rect', { key: 'z' + i, x, y: 26, width: Math.max(2, X(e.t1) - x), height: 50, fill: e.type === 'wall' ? 'rgba(32,30,29,0.10)' : 'rgba(236,48,19,0.08)' }), h('text', { key: 'zt' + i, x: x + 3, y: 36, fontSize: 9, fill: MUTE, fontFamily: 'Archivo, sans-serif', fontWeight: 600 }, e.type === 'wall' ? 'WALL' : 'FREE SPIN · SILENT')); return; }
    if (e.type === 'feel') { kids.push(h('line', { key: 'f' + i, x1: x, y1: 20, x2: x, y2: H - 6, stroke: INK, strokeDasharray: '2 3' }), h('text', { key: 'ft' + i, x: x + 3, y: 18, fontSize: 9, fill: INK, fontFamily: 'Archivo, sans-serif', fontWeight: 600 }, 'FEEL CHANGE')); return; }
    const g = GLYPH[e.type]; if (!g) return; const [A, kind] = g; let d;
    if (kind === 'spike') d = `M${x - 1} ${mid}L${x} ${mid - A}L${x + 1.5} ${mid + A * 0.35}L${x + 3} ${mid - A * 0.15}L${x + 4.5} ${mid}`;
    else if (kind === 'sine') d = `M${x - 3} ${mid}Q${x} ${mid - A * 2} ${x + 3} ${mid}`;
    else if (kind === 'bump') d = `M${x - 2} ${mid}L${x} ${mid - A}L${x + 3} ${mid}`;
    else if (kind === 'thump') d = `M${x - 1} ${mid}C${x + 2} ${mid - A * 1.3} ${x + 7} ${mid - A * 1.3} ${x + 10} ${mid}C${x + 12} ${mid + A * 0.3} ${x + 14} ${mid + A * 0.2} ${x + 16} ${mid}`;
    else { const gap = kind === 'ebuzz' ? 7 : 4; d = [0, 1, 2].map(k => `M${x + k * gap - 1} ${mid}L${x + k * gap} ${mid - A}L${x + k * gap + 1.5} ${mid}`).join(''); }
    kids.push(h('path', { key: 'p' + i, d, fill: 'none', stroke: col, strokeWidth: kind === 'thump' ? 2.5 : 1.6, strokeLinejoin: 'round' })); });
  kids.push(h('line', { key: 'ph', x1: X(st.t), y1: 4, x2: X(st.t), y2: H - 4, stroke: INK, strokeWidth: 1.5 }), h('text', { key: 'l', x: 10, y: 14, fontSize: 11, fill: INK, fontFamily: 'Archivo, sans-serif', fontWeight: 600, letterSpacing: 0.5 }, 'PULSES OVER TIME'), h('text', { key: 'r', x: W - 10, y: 14, fontSize: 10, fill: MUTE, fontFamily: 'Archivo, sans-serif', textAnchor: 'end' }, `${(dur / 1000).toFixed(1)} s`));
  return h('svg', { width: W, height: H, viewBox: `0 0 ${W} ${H}`, style: { display: 'block', border: `2px solid ${INK}` } }, ...kids);
}
function wallFx(h, ctx, st, r) { const p = (ctx.sim.phases || [])[st.phase];
  if (p && st.pen > 0 && st.wdir) { const k = st.wdir * (1 - Math.exp(-st.pen / (pitchOf(p) * 0.6))); r = Object.assign({}, r, { kids: [h('g', { transform: `translate(0 ${(-6 * k).toFixed(2)})` }, ...[r.kids].flat(9).filter(Boolean))] });
    if (r.ring) r.ring = r.ring.map((sg, i) => { const kk = (i - 38 + 60) % 60; const end = st.wdir > 0 ? 44 : 0; return kk < 45 && Math.abs(kk - end) <= 2 ? [sg[0], Math.max(sg[1], 0.5 + 0.5 * Math.abs(k))] : sg; }); }
  return r; }
const kEq = (a, b) => (a && b ? a.k === b.k : a === b);
function rawScreen(h, ctx, reduced, t, id) { const st = stateAt(ctx, reduced, Math.max(0, t)); return wallFx(h, ctx, st, ctx.screen(h, Object.assign({ id }, st))); }
function composed(h, ctx, reduced, t, id) {
  const cur = rawScreen(h, ctx, reduced, t, id); if (!ctx.key) return cur;
  const key = tt => ctx.key(stateAt(ctx, reduced, Math.max(0, tt))), kNow = key(t); let tc = -1, kOld = null;
  for (let tt = t; tt > t - 720 && tt > 0; tt -= 8) { const kb = key(tt - 8); if (!kEq(kb, kNow)) { tc = tt; kOld = kb; break; } }
  if (tc < 0) return cur;
  const dt = t - tc, old = rawScreen(h, ctx, reduced, tc - 8, id + 'o'), sty = kNow.s || (kNow.d !== kOld.d ? 'push' : 'fade'), SPs = L.SP, spf = L.sp;
  const G2 = (kids, o) => h('g', o, ...[kids].flat(9).filter(Boolean));
  let oo, no, ring = cur.ring;
  if (sty === 'push') { const dir = Math.sign(kNow.d - kOld.d) || 1; oo = { opacity: 1 - pr(dt, 0, 110, E.in), transform: `translate(${-4 * dir * pr(dt, 0, 160)} 0)` }; no = { opacity: pr(dt, 40, 200), transform: `translate(${8 * dir * (1 - spf(dt, 40, SPs.snap))} 0)` }; ring = RG.blend(old.ring, cur.ring, pr(dt, 0, 300, E.io)); }
  else if (sty === 'swap') { oo = { opacity: 1 - pr(dt, 100, 160, E.in) }; no = { opacity: pr(dt, 200, 240), transform: `translate(0 ${3 * (1 - spf(dt, 200, SPs.soft))})` }; ring = RG.sweep(old.ring, cur.ring, pr(dt, 0, 520, E.io), RG.cw); }
  else if (sty === 'reveal') { oo = { opacity: 1 - pr(dt, 0, 120, E.in), transform: `translate(0 ${-6 * pr(dt, 0, 120, E.in)})` }; no = { opacity: pr(dt, 40, 160), transform: `translate(0 ${6 * (1 - spf(dt, 40, SPs.snap))})` }; ring = RG.blend(old.ring, cur.ring, pr(dt, 0, 200, E.io)); }
  else if (sty === 'wake') { oo = { opacity: 0 }; no = { opacity: pr(dt, 0, 200), transform: `translate(0 ${3 * (1 - spf(dt, 0, SPs.soft))})` }; }
  else { oo = { opacity: 1 - pr(dt, 0, 180, E.in) }; no = { opacity: pr(dt, 60, 220) }; ring = RG.blend(old.ring, cur.ring, pr(dt, 0, 300, E.io)); }
  return Object.assign({}, cur, { ring, kids: [G2(old.kids, oo), G2(cur.kids, no)] });
}
function stageEl(h, ctx, st, id) { const t = st.t, r = composed(h, ctx, false, t, id), rs = [r], ws = [1];
  for (let j = 1; j < 6; j++) { const tt = t - j * 16; if (tt < 0) break; rs.push(composed(h, ctx, false, tt, id)); ws.push(Math.exp(-j * 16 / 50)); }
  const W = ws.reduce((a, b) => a + b, 0), avg = key => { const base = r[key]; if (!base) return base; return base.map((_, i) => { let a = 0, c = [0, 0, 0]; rs.forEach((x, j) => { const v = (x[key] || base)[i]; a += v[1] * ws[j]; c = c.map((q, n) => q + v[0][n] * v[1] * ws[j]); }); return [a > 1e-4 ? c.map(q => Math.round(q / a)) : base[i][0], a / W]; }); };
  return M.device(h, Object.assign({ s: 1, id }, r, { ring: avg('ring'), btns: r.btns ? avg('btns') : r.btns })); }

/* ---------- audio proxy ---------- */
let AC = null, NOISE = null;
function ac() { if (!AC) { AC = new (window.AudioContext || window.webkitAudioContext)(); const b = AC.createBuffer(1, AC.sampleRate * 0.05, AC.sampleRate), d = b.getChannelData(0); for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1; NOISE = b; } if (AC.state === 'suspended') AC.resume(); return AC; }
function env(g, t0, peak, dec) { g.gain.setValueAtTime(0.0001, t0); g.gain.exponentialRampToValueAtTime(peak, t0 + 0.002); g.gain.exponentialRampToValueAtTime(0.0001, t0 + dec); }
function tone(out, t0, f, peak, dec, type = 'sine', f1) { const a = AC, o = a.createOscillator(), g = a.createGain(); o.type = type; o.frequency.setValueAtTime(f, t0); if (f1) o.frequency.exponentialRampToValueAtTime(f1, t0 + dec); env(g, t0, peak, dec); o.connect(g); g.connect(out); o.start(t0); o.stop(t0 + dec + 0.02); }
function noise(out, t0, fc, q, peak, dec) { const a = AC, s = a.createBufferSource(), bp = a.createBiquadFilter(), g = a.createGain(); s.buffer = NOISE; bp.type = 'bandpass'; bp.frequency.value = fc; bp.Q.value = q; env(g, t0, peak, dec); s.connect(bp); bp.connect(g); g.connect(out); s.start(t0); s.stop(t0 + dec + 0.02); }
const VOICE = {
  click: (o, t) => { noise(o, t, 2400, 3, 0.5, 0.012); tone(o, t, 1500, 0.15, 0.018, 'triangle'); },
  fine: (o, t) => { noise(o, t, 5200, 5, 0.25, 0.006); tone(o, t, 3200, 0.06, 0.01, 'sine'); },
  thudtick: (o, t) => { noise(o, t, 1400, 2, 0.4, 0.016); tone(o, t, 260, 0.3, 0.03, 'sine', 180); },
  tick: (o, t) => { noise(o, t, 2000, 3, 0.35, 0.012); tone(o, t, 1200, 0.1, 0.016, 'triangle'); },
  'bump+': (o, t) => { tone(o, t, 240, 0.35, 0.03, 'sine', 170); noise(o, t, 1200, 2, 0.2, 0.01); },
  'bump-': (o, t) => { tone(o, t, 200, 0.35, 0.03, 'sine', 140); noise(o, t, 1000, 2, 0.2, 0.01); },
  thump: (o, t) => { tone(o, t, 110, 0.7, 0.06, 'sine', 70); tone(o, t, 220, 0.15, 0.03); },
  thumpsoft: (o, t) => { tone(o, t, 90, 0.5, 0.04, 'sine', 60); },
  buzz: (o, t) => [0, 0.03, 0.06].forEach(d => tone(o, t + d, 180, 0.3, 0.018, 'square', 150)),
  errbuzz: (o, t) => [0, 0.07, 0.14].forEach(d => tone(o, t + d, 130, 0.35, 0.03, 'square', 100))
};
function playAudio(ctx, reduced, fromT, speed = 1) { const a = ac(), out = a.createGain(); out.gain.value = 0.6; out.connect(a.destination);
  const now = a.currentTime + 0.03, evs = simulate(ctx, reduced).evs;
  evs.forEach(e => { if (e.t < fromT) return; const v = VOICE[e.type]; if (!v) return; if (reduced && (e.type === 'click' || e.type === 'fine' || e.type === 'thudtick')) return; v(out, now + (e.t - fromT) / 1000 / speed); });
  return () => { try { out.gain.setValueAtTime(0, a.currentTime); setTimeout(() => out.disconnect(), 100); } catch (e) {} }; }
function preview(type) { const a = ac(), out = a.createGain(); out.gain.value = 0.6; out.connect(a.destination); (VOICE[type] || VOICE.tick)(out, a.currentTime + 0.02); setTimeout(() => out.disconnect(), 800); }

window.NanoHaptic = { CTX, TOKENS, PRINCIPLES, simulate, stateAt, curveEl, waveEl, stageEl, playAudio, preview,
  groups: [{ id: 'home', label: 'Home', n: '01' }, { id: 'music', label: 'Music', n: '02' }, { id: 'windows', label: 'Windows', n: '03' }, { id: 'lights', label: 'Lights', n: '04' }, { id: 'nav', label: 'Navigation', n: '05' }, { id: 'moments', label: 'Moments', n: '06' }, { id: 'ideas', label: 'Creative', n: '07' }, { id: 'onshape', label: 'Onshape', n: '08' }],
  tokenSound: { 'detent.list': 'click', 'detent.coarse': 'thudtick', 'detent.fine': 'fine', 'nudge.left / nudge.right': 'bump+', 'confirm.tick': 'tick', 'confirm.thump': 'thump', 'refuse.buzz': 'buzz', 'error.buzz': 'errbuzz' } };
})();
