/* Nano_D++ prototype model: state machine + view derivation. Pure functions; timers are returned as fx. */
(function () {
  if (window.NanoModel && window.NanoModel.ART) return;
  const I = {
    back: 'M19 12H5M12 19l-7-7 7-7',
    cancel: 'M18 6 6 18M6 6l12 12',
    home: 'M3 10.5 12 3l9 7.5V21h-6v-7H9v7H3z',
    list: 'M8 6h13M8 12h13M8 18h13M3 6h1M3 12h1M3 18h1',
    win: 'M3 8h13v12H3zM8 8V4h13v12h-5',
    tracks: 'M10 6 4 12l6 6zM14 6l6 6-6 6zM2 6v12M22 6v12',
    play: 'M7 4l13 8-13 8z',
    pause: 'M8 5v14M16 5v14',
    prev: 'M19 5 9 12l10 7zM5 5v14',
    next: 'M5 5l10 7-10 7zM19 5v14',
    more: 'M12 5v14M5 12h14',
    switch: 'M4 7h16M16 3l4 4-4 4M20 17H4M8 13l-4 4 4 4',
    ok: 'M20 6 9 17l-5-5',
    dot: 'M9 12a3 3 0 1 0 6 0a3 3 0 1 0-6 0',
    warn: 'M12 3 2 21h20zM12 10v5M12 18v.5',
    usb: 'M12 3v15M12 18a2 2 0 1 0 0 4a2 2 0 1 0 0-4M8 7l4-4 4 4M7 11v2l5 3M17 9v3l-5 3'
  };
  const LV = { back: 'LV_SYMBOL_LEFT', cancel: 'LV_SYMBOL_CLOSE', home: 'LV_SYMBOL_HOME', list: 'LV_SYMBOL_LIST', win: 'LV_SYMBOL_COPY', tracks: 'LV_SYMBOL_PREV + LV_SYMBOL_NEXT', play: 'LV_SYMBOL_PLAY', pause: 'LV_SYMBOL_PAUSE', prev: 'LV_SYMBOL_PREV', next: 'LV_SYMBOL_NEXT', more: 'LV_SYMBOL_PLUS', switch: 'LV_SYMBOL_SHUFFLE (closest)', ok: 'LV_SYMBOL_OK', dot: 'LV_SYMBOL_BULLET', warn: 'LV_SYMBOL_WARNING', usb: 'LV_SYMBOL_USB' };

  const QUEUE = [
    { t: 'Águas de Março', a: 'Elis Regina & Tom Jobim', al: 'Elis & Tom' },
    { t: 'Cloudbusting', a: 'Kate Bush', al: 'Hounds of Love' },
    { t: 'Unfinished Sympathy', a: 'Massive Attack', al: 'Blue Lines' },
    { t: 'So What', a: 'Miles Davis', al: 'Kind of Blue' }
  ];
  const LOCAL = {
    'Hounds of Love': 'hounds-of-love.png', 'Blue Lines': 'blue-lines.jpg', 'Night Drive': 'night-drive-chromatics-album-.jpg',
    'Tropicália ou Panis et Circencis': 'tropic-lia-ou-panis-et-circencis.jpg', 'Kind of Blue': 'kind-of-blue.jpg',
    'Moon Safari': 'moon-safari.png', 'Elis & Tom': 'elis-tom.jpg', 'Promises': 'promises-floating-points-pharoah-sanders.png',
    'Heligoland': 'heligoland-album-.png'
  };
  const P = (t, a, k, x) => Object.assign({ t, a, k }, x || {});
  const PAGES = [
    [P('Colombina – Single', 'Mari Froes', 'Single'),
     P('Tropicália ou Panis et Circencis', 'Caetano Veloso, Gilberto Gil, Os Mutantes & Gal Costa', 'Album'),
     P('Night Drive', 'Chromatics', 'Album'),
     P('Jazz Is Dead 023', 'Adrian Younge & Ali Shaheed Muhammad', 'Album'),
     P('Promises', 'Floating Points, Pharoah Sanders & LSO', 'Album'),
     P('Vespertine (Live at Royal Opera House)', 'Björk', 'Album', { na: true }),
     P('Deep Focus', 'Apple Music', 'Playlist'),
     P('Minuano (Six Eight)', 'Pat Metheny Group', 'Single'),
     P('Blue Lines', 'Massive Attack', 'Album'),
     P('Hounds of Love', 'Kate Bush', 'Album')],
    [P('Djesse Vol. 4', 'Jacob Collier', 'Album'),
     P('Glória', 'Sílvia Pérez Cruz', 'Single'),
     P('Kind of Blue', 'Miles Davis', 'Album'),
     P('Ágætis byrjun', 'Sigur Rós', 'Album'),
     P('Música de Brinquedo', 'Pato Fu', 'Album', { na: true }),
     P('Heligoland', 'Massive Attack', 'Album'),
     P('Clube da Esquina', 'Milton Nascimento & Lô Borges', 'Album'),
     P('Late Night Tales', 'Khruangbin', 'Album'),
     P('Moon Safari', 'Air', 'Album'),
     P('Coding Mix', 'Apple Music', 'Playlist')],
    [P('Elis & Tom', 'Elis Regina & Antônio Carlos Jobim', 'Album'),
     P('Sea Change', 'Beck', 'Album'),
     P('Selected Ambient Works 85–92', 'Aphex Twin', 'Album')]
  ];
  const APPIC = { Codex: 'chatgpt.png', ChatGPT: 'chatgpt.png', Claude: 'claude.png', Chrome: 'chrome.png', Terminal: 'term.png', Slack: 'slack.png' };
  const WINS = [
    { app: 'Codex', title: 'Nano_D++ control center', hint: 'Display 1', th: 'code' },
    { app: 'Claude', title: 'Model training review', hint: 'Display 1', th: 'doc' },
    { app: 'Chrome', title: 'LVGL docs — lv_label', hint: 'Work profile · Display 1', th: 'web' },
    { app: 'Chrome', title: 'LVGL docs — lv_label', hint: 'Personal profile · Display 2', th: 'web' },
    { app: 'Terminal', title: 'pwsh — ~/nano-d', hint: 'Display 1', th: 'term' },
    { app: 'Terminal', title: 'pwsh — ~/nano-d', hint: 'Minimized', th: null, min: true },
    { app: 'Slack', title: '#firmware — Nano', hint: 'Display 2', th: 'chat' },
    { app: 'Discord', title: 'Nano builders', hint: 'Minimized', th: null, min: true },
    { app: 'ChatGPT', title: 'Sonos group volume', hint: 'Display 2', th: 'doc' }
  ];
  const HAP = {
    home: { profile: 'BINARIS BEER', det: 67 },
    recent: { profile: 'MIDI SKIPPER', det: 20 },
    tracks: { profile: 'MIDI CLACK JONES', det: 8 },
    windows: { profile: 'MIDI SKIPPER', det: 20 }
  };

  const clone = o => JSON.parse(JSON.stringify(o));
  const ART = {};
  function jsonp(url) {
    return new Promise((res, rej) => {
      const cb = '__nanoArt' + Math.random().toString(36).slice(2);
      const sc = document.createElement('script');
      const tm = setTimeout(() => { done(); rej('timeout'); }, 7000);
      function done() { clearTimeout(tm); delete window[cb]; sc.remove(); }
      window[cb] = d => { done(); res(d); };
      sc.onerror = () => { done(); rej('err'); };
      sc.src = url + '&callback=' + cb;
      document.head.appendChild(sc);
    });
  }
  const termOf = (t, a) => (a.split(/,| & /)[0] + ' ' + t.replace(/\s[–-]\sSingle$/, '')).slice(0, 90);
  const BYTERM = {};
  async function fetchArt(t, a) {
    if (ART[t] !== undefined) return;
    const term = termOf(t, a);
    if (BYTERM[term] !== undefined) { ART[t] = BYTERM[term]; return; }
    ART[t] = null;
    const q = encodeURIComponent(term);
    for (const ent of ['album', 'song']) {
      for (let attempt = 0; attempt < 2; attempt++) {
        try {
          const d = await jsonp(`https://itunes.apple.com/search?term=${q}&media=music&entity=${ent}&limit=1&country=us`);
          const r = d && d.results && d.results[0];
          if (r && r.artworkUrl100) { ART[t] = BYTERM[term] = r.artworkUrl100.replace('100x100bb', '480x480bb'); return; }
          break;
        } catch (e) { await new Promise(r => setTimeout(r, 1200)); }
      }
    }
    BYTERM[term] = null;
  }
  async function loadAllArt(cb) {
    const first = [QUEUE[1], PAGES[0][0], PAGES[0][2], PAGES[0][1], PAGES[0][9], QUEUE[2]];
    const items = first.concat(QUEUE, ...PAGES).filter((x, i, arr) => arr.indexOf(x) === i);
    for (let i = 0; i < items.length; i++) {
      const x = items[i], had = !!ART[x.t];
      await fetchArt(x.t, x.a);
      if (!had && ART[x.t]) cb();
      await new Promise(r => setTimeout(r, 300));
    }
  }
  const COVERS = [
    ['#c9542f', '#e9c46a', '#1d3557'], ['#2a6f6b', '#d8cfc0', '#11151c'], ['#7a4e9a', '#f2b5a0', '#191919'],
    ['#e0b43a', '#3a3a3a', '#b8412c'], ['#335c81', '#9fb7c9', '#f4efe6'], ['#5e7d3a', '#e8dcc2', '#2b2b2b'],
    ['#a33b4f', '#161616', '#e6d3b3'], ['#3f3f46', '#d97a3a', '#e7e5e4']
  ];
  function cover(t) {
    if (!t) return null;
    if (LOCAL[t]) return `url("assets/covers/${LOCAL[t]}") center / cover no-repeat`;
    if (ART[t]) return `url("${ART[t]}") center / cover no-repeat`;
    let h = 0; for (let i = 0; i < t.length; i++) h = (h * 31 + t.charCodeAt(i)) >>> 0;
    const c = COVERS[h % COVERS.length], v = (h >> 4) % 3;
    const g = v === 0 ? `linear-gradient(90deg, ${c[0]} 0 55%, ${c[1]} 55% 100%)`
      : v === 1 ? `radial-gradient(circle at 62% 40%, ${c[1]} 0 22%, transparent 22.5%), linear-gradient(${c[0]}, ${c[0]})`
      : `linear-gradient(180deg, ${c[2]} 0 38%, ${c[0]} 38% 72%, ${c[1]} 72% 100%)`;
    return g;
  }
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

  function init() {
    return {
      conn: 'ok', sonos: 'ok', room: 'Den', qi: 1, np: null,
      vol: 54, volConf: 54, volSeq: 0, ext: false, volVis: false, volHideSeq: 0,
      playing: true, playReq: true, playSeq: 0,
      mode: 'home',
      recent: { page: 0, idx: 0, stack: [], status: 'ready' },
      tracks: { pos: 0, status: 'idle' },
      mru: [0, 1, 2, 3, 4, 5, 6, 7, 8],
      win: { order: [0, 1, 2, 3, 4, 5, 6, 7, 8], idx: 1, closed: [], status: 'browsing', ret: 'home' },
      flash: null, flashId: 0, tick: 0,
      opt: { auth: false, empty: false, fail: false, noPrev: false }
    };
  }
  function merge(t, p) { for (const k in p) { if (p[k] && typeof p[k] === 'object' && !Array.isArray(p[k]) && t[k] && typeof t[k] === 'object') merge(t[k], p[k]); else t[k] = p[k]; } return t; }
  function mk(patch) { return merge(init(), clone(patch || {})); }

  function entries(s) {
    const e = (PAGES[s.recent.page] || []).slice();
    if (s.recent.page < PAGES.length - 1) e.push({ more: true });
    return e;
  }
  const nowPlaying = s => s.nothing ? null : (s.np || QUEUE[s.qi]);

  function step(s0, a) {
    const s = clone(s0), fx = []; let cmd = null;
    const later = (ms, act) => fx.push({ ms, act });
    const flash = kind => { s.flashId++; s.flash = { kind, id: s.flashId }; later(kind === 'err' ? 900 : 650, { t: 'flashEnd', id: s.flashId }); };
    const off = s.conn !== 'ok';
    if (off && (a.t === 'rot' || a.t === 'btn')) return { s: s0, fx, cmd };
    if (a.t === 'rot' || a.t === 'btn' || a.t === 'external') { s.asleep = false; s.wakeSeq = (s.wakeSeq || 0) + 1; later(a.t === 'external' ? 3200 : 5000, { t: 'sleep', seq: s.wakeSeq }); }

    const openRecent = () => {
      s.mode = 'recent'; s.recent = { page: 0, idx: 0, stack: [], status: s.opt.auth ? 'auth' : 'loading' };
      if (!s.opt.auth) later(650, { t: 'loaded' });
    };
    const openWin = () => {
      if (s.mode === 'windows') return;
      s.win = { order: s.mru.slice(), idx: 1, closed: [], status: 'browsing', ret: s.mode };
      s.mode = 'windows'; cmd = 'Companion · show picker overlay (list frozen, 9 windows)';
    };

    switch (a.t) {
      case 'rot': {
        const d = a.d;
        if (s.mode === 'home') {
          if (s.sonos !== 'ok') break;
          s.volVis = true; s.volHideSeq++; later(1400, { t: 'volHide', seq: s.volHideSeq });
          const nv = clamp(s.vol + d, 0, 100);
          if (nv !== s.vol) { s.vol = nv; s.ext = false; s.volSeq++; later(380, { t: 'volAck', seq: s.volSeq }); cmd = `Sonos · Den group volume → ${nv}`; }
        } else if (s.mode === 'recent') {
          const r = s.recent; if (!['ready', 'partial'].includes(r.status)) break;
          r.idx = clamp(r.idx + d, 0, entries(s).length - 1); r.status = 'ready';
        } else if (s.mode === 'tracks') {
          const t = s.tracks; if (t.status === 'pending') break;
          t.pos = clamp(t.pos + d, -1, 1); t.status = 'idle';
        } else if (s.mode === 'windows') {
          const w = s.win; if (w.status === 'pending') break;
          w.idx = clamp(w.idx + d, 0, w.order.length - 1); w.status = 'browsing';
          cmd = `Overlay · highlight ${WINS[w.order[w.idx]].app} (no activation)`;
        }
        break;
      }
      case 'btn': {
        const n = a.n;
        if (s.mode === 'home') {
          if (n === 1 && s.sonos === 'ok' && !s.nothing && s.playReq === s.playing) {
            s.playReq = !s.playing; s.playSeq++; s.pIdle = false; s.pIdleSeq = (s.pIdleSeq || 0) + 1; later(420, { t: 'playAck', seq: s.playSeq });
            cmd = `Sonos · Den ${s.playReq ? 'play' : 'pause'}`;
          }
          else if (n === 2) openRecent();
          else if (n === 3) openWin();
          else if (n === 4 && s.sonos === 'ok' && !s.nothing) { s.mode = 'tracks'; s.tracks = { pos: 0, status: 'idle' }; }
        } else if (s.mode === 'recent') {
          const r = s.recent;
          if (n === 1) {
            if (r.status === 'pending') break;
            if (r.stack.length) { r.page--; r.idx = r.stack.pop(); r.status = 'ready'; } else s.mode = 'home';
          } else if (n === 2) s.mode = 'home';
          else if (n === 3) openWin();
          else if (n === 4) {
            if (!['ready', 'partial'].includes(r.status)) break;
            const e = entries(s)[r.idx];
            if (e.more) { r.stack.push(r.idx); r.page++; r.idx = 0; r.status = 'loading'; later(550, { t: 'loaded' }); cmd = `Apple Music · fetch Recently Added page ${r.page + 1}`; }
            else if (!e.na && s.sonos === 'ok') { r.status = 'pending'; later(1200, { t: 'playDone' }); cmd = `Sonos · replace Den queue with “${e.t}”, play`; }
          }
        } else if (s.mode === 'tracks') {
          const t = s.tracks;
          if (n === 1 || n === 2) { if (t.status !== 'pending') s.mode = 'home'; else if (n === 2) s.mode = 'home'; }
          else if (n === 3) openWin();
          else if (n === 4) {
            if (t.pos === 0 || t.status === 'pending' || (t.pos === -1 && s.opt.noPrev)) break;
            t.status = 'pending'; later(650, { t: 'skipDone', dir: t.pos });
            cmd = `Sonos · ${t.pos > 0 ? 'next' : 'previous'} (one command)`;
          }
        } else if (s.mode === 'windows') {
          const w = s.win;
          if (n === 1) { if (w.status !== 'pending') { s.mode = w.ret; cmd = 'Overlay · dismissed, focus restored to Codex'; } }
          else if (n === 2) { s.mode = 'home'; cmd = 'Overlay · dismissed, focus restored'; }
          else if (n === 4) {
            if (w.closed.includes(w.idx) || w.status === 'pending') break;
            w.status = 'pending'; later(450, { t: 'switchDone' });
            const x = WINS[w.order[w.idx]]; cmd = `Win32 · activate ${x.app} “${x.title}”, verify foreground`;
          }
        }
        break;
      }
      case 'playAck':
        if (a.seq !== s.playSeq) break;
        if (s.opt.fail) { s.playReq = s.playing; flash('err'); cmd = 'Sonos · transport command failed'; }
        else { s.playing = s.playReq; cmd = `Sonos · transport ${s.playing ? 'PLAYING' : 'PAUSED'} confirmed`; if (!s.playing) { s.pIdleSeq = (s.pIdleSeq || 0) + 1; later(4000, { t: 'pIdle', seq: s.pIdleSeq }); } }
        break;
      case 'pIdle':
        if (a.seq === s.pIdleSeq && !s.playing && !s.playReq && s.mode === 'home') s.pIdle = true;
        break;
      case 'volHide':
        if (a.seq !== s.volHideSeq) break;
        if (s.vol !== s.volConf) later(400, { t: 'volHide', seq: s.volHideSeq }); else s.volVis = false;
        break;
      case 'volAck': if (a.seq === s.volSeq && s.sonos === 'ok') s.volConf = s.vol; break;
      case 'loaded':
        if (s.mode === 'recent' && s.recent.status === 'loading') s.recent.status = (s.opt.empty && s.recent.page === 0) ? 'empty' : 'ready';
        break;
      case 'playDone': {
        const r = s.recent; if (r.status !== 'pending') break;
        if (s.opt.fail) { r.status = 'partial'; flash('err'); cmd = 'Sonos · queue replaced, play() failed'; }
        else { const e = entries(s)[r.idx]; s.np = { t: e.t, a: e.a }; s.nothing = false; s.pIdle = false; s.playing = s.playReq = true; s.mode = s.mode === 'recent' ? 'home' : s.mode; flash('ok'); cmd = 'Sonos · transport PLAYING confirmed'; }
        break;
      }
      case 'skipDone': {
        const t = s.tracks; if (t.status !== 'pending') break;
        s.qi = clamp(s.qi + a.dir, 0, QUEUE.length - 1); s.np = null; t.pos = 0; t.status = 'done'; flash('ok');
        cmd = `Sonos · now playing “${QUEUE[s.qi].t}” (reported)`;
        break;
      }
      case 'switchDone': {
        const w = s.win; if (w.status !== 'pending') break;
        if (s.opt.fail) { w.status = 'failed'; flash('err'); cmd = 'Win32 · foreground check failed'; }
        else { const id = w.order[w.idx]; s.mru = [id].concat(s.mru.filter(x => x !== id)); s.mode = 'home'; flash('ok'); cmd = 'Win32 · foreground verified'; }
        break;
      }
      case 'sleep':
        if (a.seq != null && a.seq !== s.wakeSeq) break;
        if (isPending(s) || s.flash) later(1000, { t: 'sleep', seq: s.wakeSeq }); else s.asleep = true;
        break;
      case 'flashEnd': if (s.flash && s.flash.id === a.id) s.flash = null; break;
      case 'external': s.vol = s.volConf = 38; s.ext = true; s.volSeq++; s.volVis = true; s.volHideSeq++; later(2600, { t: 'volHide', seq: s.volHideSeq }); later(6000, { t: 'extClear', seq: s.volSeq }); cmd = 'Sonos event · volume 38 (changed elsewhere)'; break;
      case 'extClear': if (a.seq === s.volSeq) s.ext = false; break;
      case 'sonos': s.sonos = s.sonos === 'ok' ? 'off' : 'ok'; if (s.sonos === 'ok') s.vol = s.volConf; cmd = s.sonos === 'ok' ? 'Sonos · Den reachable, state refreshed' : 'Sonos · Den unreachable'; break;
      case 'closeWin':
        if (s.mode === 'windows' && !s.win.closed.includes(s.win.idx)) { s.win.closed.push(s.win.idx); cmd = 'Win32 · highlighted window closed (slot kept)'; }
        break;
      case 'unplug': s.conn = 'missing'; later(1600, { t: 'reconnecting' }); cmd = 'USB · device removed'; break;
      case 'reconnecting': s.conn = 'reconnecting'; later(1600, { t: 'reconnected' }); break;
      case 'reconnected': {
        const keep = { mru: s.mru, qi: s.qi, np: s.np, opt: s.opt, sonos: s.sonos, volConf: s.volConf };
        const f = init(); Object.assign(f, keep); f.vol = keep.volConf; cmd = 'USB · reconnected, fresh state read, Volume';
        return { s: f, fx, cmd };
      }
      case 'nothing': s.nothing = !s.nothing; if (s.mode === 'tracks' && s.nothing) s.mode = 'home'; cmd = s.nothing ? 'Sonos · Den queue empty, transport STOPPED' : 'Sonos · Den playing'; break;
      case 'opt': s.opt[a.k] = !s.opt[a.k]; if (a.k === 'auth' && s.mode === 'recent') s.recent.status = s.opt.auth ? 'auth' : 'ready'; break;
    }
    return { s, fx, cmd };
  }

  const isPending = s => s.conn === 'reconnecting' || (s.mode === 'recent' && ['pending', 'loading'].includes(s.recent.status)) || (s.mode === 'tracks' && s.tracks.status === 'pending') || (s.mode === 'windows' && s.win.status === 'pending') || (s.mode === 'home' && (s.vol !== s.volConf || s.playReq !== s.playing));

  /* ---------- view ---------- */
  const W = '255,255,255', G = '70,225,120', R = '255,72,52';
  const COL = { nav: '#E6E6E6', go: '#6ED996', stop: '#FF8474', dim: '#4A4A4A', none: 'transparent' };
  const F = (g, w, tone) => ({ d: I[g] || '', w: w || '', tone: tone || 'none' });
  const NONE = F('', '', 'none');
  const T1 = '#F2F2F2', T2 = '#A6A6A6', T3 = '#7C7C7C', TD = '#555555', TERR = '#FF8A7A', TOK = '#7EE0A2';
  const VOL0 = 35, VOLN = 50; // arc: 7 o'clock → 5 o'clock clockwise, 2 % per segment
  const vseg = v => (VOL0 + Math.round(v / 2)) % 60;
  const mod = i => ((i % 60) + 60) % 60;

  const COLORS = {};
  const COLOR_FALLBACK = { 'app:Discord': '88,101,242' };
  function dominant(img) {
    const c = document.createElement('canvas'); c.width = c.height = 24;
    const x = c.getContext('2d'); x.drawImage(img, 0, 0, 24, 24);
    const d = x.getImageData(0, 0, 24, 24).data, bins = {}; let best = null;
    for (let i = 0; i < d.length; i += 4) {
      if (d[i + 3] < 128) continue;
      const r = d[i], g = d[i + 1], b = d[i + 2], mx = Math.max(r, g, b), mn = Math.min(r, g, b), s = mx ? (mx - mn) / mx : 0;
      if (mx < 50 || s < 0.3) continue;
      const key = ((r >> 5) << 6) | ((g >> 5) << 3) | (b >> 5), w = s * (mx / 255);
      const e = bins[key] || (bins[key] = { w: 0, r: 0, g: 0, b: 0 });
      e.w += w; e.r += r * w; e.g += g * w; e.b += b * w;
    }
    for (const k in bins) if (!best || bins[k].w > best.w) best = bins[k];
    if (!best || best.w < 4) return null;
    let r = best.r / best.w, g = best.g / best.w, b = best.b / best.w; const mx = Math.max(r, g, b);
    return [r, g, b].map(v => Math.round(v / mx * 255)).join(',');
  }
  function loadColors(cb) {
    const jobs = Object.entries(LOCAL).map(([k, f]) => ['al:' + k, 'assets/covers/' + f])
      .concat(Object.entries(APPIC).map(([k, f]) => ['app:' + k, 'assets/apps/' + f]));
    let left = jobs.length;
    jobs.forEach(([k, src]) => {
      const im = new Image();
      im.onload = () => { try { COLORS[k] = dominant(im); } catch (e) { } if (--left === 0) cb(); };
      im.onerror = () => { if (--left === 0) cb(); };
      im.src = src;
    });
  }
  const tint = k => COLORS[k] || COLOR_FALLBACK[k] || null;
  function volColor(pos, style, led) {
    if ((led === 'color' || led === 'alive') && style !== 'gradient') return pos >= 0.9 ? '255,55,35' : pos >= 0.8 ? '255,150,30' : W;
    if (style !== 'gradient') return W;
    const h = 130 - pos * 125; // green → red, sRGB approx
    const t = pos; return `${Math.round(70 + t * 185)},${Math.round(225 - t * 150)},${Math.round(120 - t * 70)}`;
  }

  function view(s, o) {
    o = o || {};
    const ring = Array(60).fill(null);
    const set = (i, c, l) => { ring[mod(i)] = { c, l }; };
    let lcd = { layout: 'list', label: '', title: '', sub: '', meta: '', big: '', st: '', tc: T1, mc: T3, sc: T3, pos: [] };
    let foot = [NONE, NONE, NONE, NONE];
    let cursor = 0, hap = null, actions = '';
    const pulse = s.tick % 2 === 0;
    const np = nowPlaying(s);

    if (s.conn !== 'ok') {
      lcd = Object.assign(lcd, { label: 'NANO_D++', title: s.conn === 'missing' ? 'Waiting for PC' : 'Reconnecting…', sub: 'Resumes at Volume', meta: 'Old turns are discarded', mc: T3 });
      if (s.conn === 'reconnecting') set(0, W, pulse ? 2 : 1); else set(0, W, 1);
      hap = { profile: 'Held (last profile)', det: null, bounds: 'Input ignored until reconnected', pos: '—' };
      actions = 'None. Reconnection reads fresh state and opens Volume.';
      return finish();
    }

    if (s.mode === 'home') {
      hap = Object.assign({}, HAP.home, { bounds: '0 – 100 %', pos: `${s.vol} %`, entry: 'Current volume' });
      if (s.sonos !== 'ok') {
        lcd = Object.assign(lcd, { label: '', title: 'Sonos unavailable', sub: 'Looking for Sonos…', meta: 'Windows still works', tc: T1 });
        set(vseg(s.volConf), W, 1); cursor = vseg(s.volConf);
        foot = [F('pause', 'Pause', 'dim'), F('list', 'Browse', 'nav'), F('win', 'Win', 'nav'), F('tracks', 'Tracks', 'dim')];
        hap.pos = 'No target'; actions = 'Browse, Windows. Play/pause, volume and Tracks wait for Sonos.';
      } else {
        const pending = s.vol !== s.volConf;
        lcd = Object.assign(lcd, { layout: 'home', label: '', title: np ? np.t : 'Nothing playing', sub: np ? np.a : '', big: String(s.vol), volVis: !!s.volVis, art: np ? cover(np.al || np.t) : null });
        const tp = s.playReq !== s.playing;
        lcd.st = s.volVis ? (pending ? 'Setting…' : s.ext ? 'Changed on Sonos' : s.vol === 0 ? 'Minimum' : s.vol === 100 ? 'Maximum' : '')
          : (tp ? (s.playReq ? 'Starting…' : 'Pausing…') : !s.playing ? 'Paused' : '');
        lcd.sc = pending || tp ? T3 : (s.ext || !s.playing) ? T2 : T3;
        const e = vseg(s.vol), c = vseg(s.volConf), n = Math.round(s.vol / 2), nc = Math.round(s.volConf / 2);
        set(VOL0, W, 1); set(VOL0 + VOLN, W, 1);
        for (let k = 0; k <= n; k++) set(VOL0 + k, volColor(k / VOLN, o.volStyle, o.led), k <= nc ? 2 : 1);
        set(e, volColor(n / VOLN, o.volStyle, o.led), s.ext ? 4 : 3);
        cursor = e;
        foot = [s.playReq ? F('pause', 'Pause', tp ? 'dim' : 'nav') : F('play', 'Play', tp ? 'dim' : 'nav'), F('list', 'Browse', 'nav'), F('win', 'Win', 'nav'), F('tracks', 'Tracks', 'nav')];
        actions = `Turn: volume (live). 1 ${s.playing ? 'Pause' : 'Play'} · 2 Browse · 3 Windows · 4 Tracks.`;
        lcd.center = foot.map(f => Object.assign({}, f, { col: COL[f.tone] }));
        lcd.volCap = np ? (!s.playing && !s.playReq ? `Paused · ${np.t}` : np.t) : 'Nothing playing';
        if (!np) {
          lcd.layout = 'idle'; lcd.st = s.volVis ? lcd.st : '';
          foot = [F('play', 'Play', 'dim'), F('list', 'Browse', 'nav'), F('win', 'Win', 'nav'), F('tracks', 'Tracks', 'dim')];
          lcd.center = foot.map(f => Object.assign({}, f, { col: COL[f.tone] }));
          actions = 'Nothing playing. Turn: volume. 2 Browse · 3 Windows. Play and Tracks need a queue.';
        } else if (s.pIdle && !s.playing) {
          lcd.layout = 'idle'; lcd.st = s.volVis ? lcd.st : '';
          lcd.center = foot.map(f => Object.assign({}, f, { col: COL[f.tone] }));
          actions = 'Paused (idle view). 1 Play resumes · 2 Browse · 3 Windows · 4 Tracks. Turn: volume.';
        }
      }
    } else if (s.mode === 'recent') {
      const r = s.recent, es = entries(s), n = es.length;
      hap = Object.assign({}, HAP.recent, { bounds: `1 – ${n} on page ${r.page + 1}`, pos: `${r.idx + 1} / ${n}`, entry: r.stack.length ? 'Restored' : 'Item 1' });
      lcd.label = r.page ? `RECENTLY ADDED · P${r.page + 1}` : 'RECENTLY ADDED';
      foot = [F('back', 'Back', 'nav'), F('home', 'Home', 'nav'), F('win', 'Win', 'nav'), F('play', 'Play', 'dim')];
      const c0 = Math.floor((n - 1) / 2);
      const slot = i => (i - c0) * 3;
      if (r.status === 'loading') {
        Object.assign(lcd, { title: 'Loading…', sub: r.page ? `Page ${r.page + 1}` : 'Apple Music', meta: '' });
        set(0, W, pulse ? 2 : 1); cursor = 0; hap.pos = '—'; actions = 'Back, Home, Windows. Nothing plays.';
      } else if (r.status === 'empty') {
        Object.assign(lcd, { title: 'Nothing recently added', sub: 'Apple Music library', meta: '' });
        hap.bounds = 'No items'; hap.pos = '—'; actions = 'Back, Home, Windows.';
      } else if (r.status === 'auth') {
        Object.assign(lcd, { title: 'Apple Music sign-in expired', sub: 'Renew on your PC', meta: 'Windows still works', mc: T2 });
        hap.bounds = 'No items'; hap.pos = '—'; actions = 'Back, Home, Windows. Renew in companion app.';
      } else {
        const ac = e => ((o.led === 'color' || o.led === 'alive') && !e.more && tint('al:' + e.t)) || W;
        es.forEach((e, i) => { if (!e.na) set(slot(i), ac(e), 1); });
        if (es[n - 1].more) set(slot(n - 1) + 1, W, 1);
        const e = es[r.idx]; cursor = slot(r.idx);
        const posTxt = `${r.idx + 1}/${n}`;
        if (e.more) {
          Object.assign(lcd, { title: 'More', sub: 'Next 10 items', meta: `${posTxt} · Loads, doesn’t play` });
          foot[3] = F('more', 'More', 'nav'); set(cursor, W, 3); set(cursor + 1, W, 3);
          actions = '4 More loads page ' + (r.page + 2) + '. Back returns here.';
        } else if (e.na) {
          Object.assign(lcd, { title: e.t, sub: e.a, meta: `${posTxt} · Not available`, tc: T3, art: cover(e.t) });
          set(cursor, W, 2); actions = 'Play disabled. Turn to another item.';
        } else {
          Object.assign(lcd, { title: e.t, sub: e.a, meta: `${posTxt} · Replaces queue`, art: cover(e.t) });
          foot[3] = F('play', 'Play', s.sonos === 'ok' ? 'go' : 'dim'); set(cursor, ac(e), 3);
          actions = '4 Play: whole ' + e.k.toLowerCase() + ' on Den, replaces queue.';
          if (s.sonos !== 'ok') { lcd.meta = `${posTxt} · Sonos unavailable`; actions = 'Play disabled until Den returns.'; }
        }
        if (r.status === 'pending') {
          lcd.meta = 'Starting…'; lcd.mc = T2;
          foot[0] = F('back', 'Back', 'dim'); foot[3] = F('play', 'Play', 'dim');
          set(cursor, W, pulse ? 3 : 1); actions = 'Sent. Cannot be undone; Home leaves playback running.';
        }
        if (r.status === 'partial') { lcd.meta = 'Queue replaced · didn’t start'; lcd.mc = TERR; actions = '4 Play retries. Queue already replaced.'; }
      }
    } else if (s.mode === 'tracks') {
      const t = s.tracks;
      hap = Object.assign({}, HAP.tracks, { bounds: 'Prev · Neutral · Next', pos: ['Previous', 'Neutral', 'Next'][t.pos + 1], entry: 'Neutral' });
      lcd.layout = 'tracks'; lcd.label = 'TRACKS';
      const noPrev = s.opt.noPrev;
      lcd.title = t.pos === 1 ? 'Next track' : t.pos === -1 ? (noPrev ? 'Previous unavailable' : 'Previous track') : 'Turn to choose';
      lcd.tc = t.pos === -1 && noPrev ? T3 : T1;
      lcd.sub = np ? `Now: ${np.t}` : 'Nothing playing';
      lcd.art = np ? cover(np.al || np.t) : null;
      lcd.meta = t.status === 'pending' ? 'Skipping…' : t.status === 'done' ? 'Skipped · back at neutral' : t.pos === 0 ? 'One press, one skip' : 'Press once to skip';
      lcd.mc = t.status === 'done' ? TOK : t.status === 'pending' ? T2 : T3;
      lcd.pos = [
        { d: I.prev, c: noPrev ? TD : t.pos === -1 ? T1 : T3 },
        { d: I.dot, c: t.pos === 0 ? T1 : T3 },
        { d: I.next, c: t.pos === 1 ? T1 : T3 }
      ];
      if (!noPrev) { set(52, W, 1); set(53, W, 1); }
      set(0, W, 1); set(7, W, 1); set(8, W, 1);
      if (t.pos === -1) { cursor = 52; if (!noPrev) { set(52, W, 3); set(53, W, 3); } }
      else if (t.pos === 1) { cursor = 8; set(7, W, 3); set(8, W, 3); }
      else { cursor = 0; set(0, W, 2); }
      const can = t.pos !== 0 && !(t.pos === -1 && noPrev) && t.status !== 'pending';
      foot = [F('back', 'Back', 'nav'), F('home', 'Home', 'nav'), F('win', 'Win', 'nav'),
        t.pos === 1 ? F('next', 'Next', can ? 'go' : 'dim') : t.pos === -1 ? F('prev', 'Prev', can ? 'go' : 'dim') : F('next', 'Skip', 'dim')];
      if (t.status === 'pending') { const k = t.pos === 1 ? [7, 8] : [52, 53]; k.forEach(i => set(i, W, pulse ? 3 : 1)); }
      actions = can ? `4 ${t.pos > 0 ? 'Next' : 'Previous'}: one skip, returns to Neutral.` : 'Turn to Previous or Next.';
    } else if (s.mode === 'windows') {
      const w = s.win, n = w.order.length, x = WINS[w.order[w.idx]], closed = w.closed.includes(w.idx);
      hap = Object.assign({}, HAP.windows, { bounds: `1 – ${n} (frozen)`, pos: `${w.idx + 1} / ${n}`, entry: 'Most recent other window (2)' });
      lcd.label = '';
      const cur = w.idx === 0;
      Object.assign(lcd, { layout: 'win', title: x.title, sub: x.app, meta: '', icon: APPIC[x.app] ? `assets/apps/${APPIC[x.app]}` : '', iconL: x.app[0], iconOp: closed ? 0.35 : 1 });
      if (closed) { lcd.tc = T3; lcd.meta = 'Closed · can’t switch'; }
      if (w.status === 'pending') { lcd.meta = 'Switching…'; lcd.mc = T2; }
      if (w.status === 'failed') { lcd.meta = 'Didn’t come forward · retry'; lcd.mc = TERR; }
      const c0 = Math.floor((n - 1) / 2);
      const wc = id => ((o.led === 'color' || o.led === 'alive') && tint('app:' + WINS[id].app)) || W;
      w.order.forEach((id, i) => { if (!w.closed.includes(i)) set((i - c0) * 3, wc(id), 1); });
      cursor = (w.idx - c0) * 3; set(cursor, wc(w.order[w.idx]), closed ? 2 : (w.status === 'pending' ? (pulse ? 3 : 1) : 3));
      foot = [F('cancel', 'Cancel', w.status === 'pending' ? 'dim' : 'stop'), F('home', 'Home', 'nav'), F('win', 'Win', 'nav'), F('switch', 'Switch', closed || w.status === 'pending' ? 'dim' : 'go')];
      actions = closed ? 'Switch disabled on closed slot. Turn, Cancel or Home.' : '4 Switch activates and verifies. 1 Cancel restores focus.';
    }
    return finish();

    function finishAlive(light0) {
      const WARM = '255,164,84', AG = '0,255,98', AR = '255,24,0', AAMB = '255,118,0', ABLUE = '40,140,255';
      const asleep = !!s.asleep && !s.flash && !isPending(s) && s.conn === 'ok';
      const sat = c => { const v = c.split(',').map(Number), mx = Math.max(...v), mn = Math.min(...v); if (mx - mn < 30) return WARM; return v.map(x => Math.round(Math.max(0, x - mn * 0.75) / (mx - mn * 0.75) * 255)).join(','); };
      const remap = c => c === W ? WARM : c === G ? AG : c === R || c === '255,55,35' ? AR : c === '255,150,30' ? AAMB : sat(c);
      const AW = [0, 0.3, 0.62, 1, 1], AS = [0, 0.05, 0.1, 0.16, 0.16];
      for (let i = 0; i < 60; i++) {
        const e = ring[i]; if (!e || !e.l) continue;
        const c = remap(e.c), act = c !== WARM;
        ring[i] = asleep ? { c: WARM, l: e.l, a: AS[e.l] } : { c, l: e.l, a: act ? (e.l >= 2 ? 1 : 0.45) : AW[e.l] };
      }
      if (s.conn === 'ok' && s.mode === 'home' && s.ext && !asleep) [-1, 0, 1].forEach(k => set(cursor + k, ABLUE, 4) || (ring[mod(cursor + k)].a = 1));
      if (s.flash) { const c = s.flash.kind === 'ok' ? AG : AR; [-2, -1, 0, 1, 2].forEach(k => { set(cursor + k, c, 4); ring[mod(cursor + k)].a = Math.abs(k) === 2 ? 0.5 : 1; }); }
      if (s.conn !== 'ok') { for (let i = 0; i < 60; i += 5) ring[i] = { c: AAMB, l: 1, a: s.conn === 'reconnecting' ? (pulse ? 0.5 : 0.15) : 0.12 }; }
      if (s.mode === 'home' && s.conn === 'ok' && !s.playReq && !s.playing && !s.nothing) foot[0] = Object.assign({}, foot[0], { tone: foot[0].tone === 'dim' ? 'dim' : 'go' });
      const buttons = foot.map(f => { const b = light0(f), c = remap(b.c), act = c !== WARM; return { w: f.w, tone: f.tone, c: asleep && b.l ? WARM : c, l: b.l, a: !b.l ? 0 : asleep ? (f.tone === 'dim' ? 0.04 : 0.12) : act ? 1 : (f.tone === 'dim' ? 0.14 : 0.7) }; });
      if (s.conn !== 'ok') buttons.forEach(b => { b.l = 0; b.a = 0; });
      const md = s.conn !== 'ok' ? 'offline' : s.mode;
      const depth = md === 'recent' ? 1 + s.recent.page : md === 'tracks' ? 1 : md === 'windows' ? 5 : 0;
      return { lcd, foot: foot.map(f => Object.assign({}, f, { col: COL[f.tone] })), ring, buttons, hap, actions, mode: md, screenKey: md + (md === 'recent' ? s.recent.page : ''), depth, ledSleep: asleep, alive: true, cursor: mod(cursor) };
    }
    function finish() {
      if (s.flash) {
        const c = s.flash.kind === 'ok' ? G : R, l = s.flash.kind === 'ok' ? 4 : 3;
        [-1, 0, 1].forEach(k => set(cursor + k, c, l));
      }
      const alive = o.led === 'alive';
      const light0 = f => f.tone === 'nav' ? { c: W, l: 2 } : f.tone === 'go' ? { c: G, l: 3 } : f.tone === 'stop' ? { c: R, l: 2 } : f.tone === 'dim' ? { c: W, l: 1 } : { c: W, l: 0 };
      if (alive) return finishAlive(light0);
      const light = f => f.tone === 'nav' ? { c: W, l: 2 } : f.tone === 'go' ? { c: G, l: 3 } : f.tone === 'stop' ? { c: R, l: 2 } : f.tone === 'dim' ? { c: W, l: 1 } : { c: W, l: 0 };
      const buttons = foot.map(f => Object.assign({ w: f.w, tone: f.tone }, light(f)));
      if (s.conn !== 'ok') buttons.forEach(b => { b.l = 0; });
      const md = s.conn !== 'ok' ? 'offline' : s.mode;
      const depth = md === 'recent' ? 1 + s.recent.page : md === 'tracks' ? 1 : md === 'windows' ? 5 : 0;
      return { lcd, foot: foot.map(f => Object.assign({}, f, { col: COL[f.tone] })), ring, buttons, hap, actions, mode: md, screenKey: md + (md === 'recent' ? s.recent.page : ''), depth };
    }
  }

  function scenarios() {
    const R_ = (page, idx, status) => ({ mode: 'recent', recent: { page, idx, stack: page ? [10] : [], status: status || 'ready' } });
    return [
      { id: 'home', name: 'Volume · idle', st: mk({}) },
      { id: 'home-pidle', name: 'Volume · paused, idle view', st: mk({ playing: false, playReq: false, pIdle: true }) },
      { id: 'home-none', name: 'Volume · nothing playing', st: mk({ nothing: true }) },
      { id: 'home-turn', name: 'Volume · turning', st: mk({ vol: 55, volConf: 55, volVis: true }) },
      { id: 'home-pend', name: 'Volume · request pending', st: mk({ vol: 61, volConf: 54, volVis: true }) },
      { id: 'home-paused', name: 'Volume · paused', st: mk({ playing: false, playReq: false }) },
      { id: 'home-ext', name: 'Volume · changed elsewhere', st: mk({ vol: 38, volConf: 38, ext: true, volVis: true }) },
      { id: 'home-off', name: 'Volume · Sonos offline', st: mk({ sonos: 'off' }) },
      { id: 'ra-load', name: 'Recently Added · loading', st: mk(R_(0, 0, 'loading')) },
      { id: 'ra-item', name: 'Recently Added · item', st: mk(R_(0, 2)) },
      { id: 'ra-more', name: 'Recently Added · More', st: mk(R_(0, 10)) },
      { id: 'ra-na', name: 'Recently Added · unavailable', st: mk(R_(0, 5)) },
      { id: 'ra-pend', name: 'Recently Added · playback pending', st: mk(R_(0, 2, 'pending')) },
      { id: 'ra-part', name: 'Recently Added · partial failure', st: mk(R_(0, 2, 'partial')) },
      { id: 'ra-auth', name: 'Recently Added · sign-in expired', st: mk(R_(0, 0, 'auth')) },
      { id: 'ra-empty', name: 'Recently Added · empty', st: mk(R_(0, 0, 'empty')) },
      { id: 'tr-neu', name: 'Tracks · neutral', st: mk({ mode: 'tracks' }) },
      { id: 'tr-next', name: 'Tracks · Next selected', st: mk({ mode: 'tracks', tracks: { pos: 1 } }) },
      { id: 'tr-done', name: 'Tracks · skipped, recentred', st: mk({ mode: 'tracks', qi: 2, tracks: { pos: 0, status: 'done' } }) },
      { id: 'tr-noprev', name: 'Tracks · Previous unsupported', st: mk({ mode: 'tracks', tracks: { pos: -1 }, opt: { noPrev: true } }) },
      { id: 'wi-brw', name: 'Windows · browsing', st: mk({ mode: 'windows' }) },
      { id: 'wi-closed', name: 'Windows · closed slot', st: mk({ mode: 'windows', win: { idx: 4, closed: [4] } }) },
      { id: 'wi-fail', name: 'Windows · switch failed', st: mk({ mode: 'windows', win: { idx: 2, status: 'failed' } }) },
      { id: 'disc', name: 'Knob · PC disconnected', st: mk({ conn: 'missing' }) }
    ];
  }

  function stress() {
    return [
      { name: 'Long accented title, Volume', note: 'Single line, ellipsis at 170 px. Artist keeps its own line.', st: mk({ np: { t: 'Tropicália ou Panis et Circencis', a: 'Caetano Veloso, Gilberto Gil, Os Mutantes & Gal Costa' } }) },
      { name: 'Long accented title, browsing', note: 'Two lines at 22 px, then ellipsis. Never shrinks.', st: mk({ mode: 'recent', recent: { idx: 1 } }) },
      { name: '0 %', note: 'Only the start mark lit. “Minimum” explains the bound.', st: mk({ vol: 0, volConf: 0, volVis: true }) },
      { name: '100 %', note: 'Arc meets the end mark. No red, no warning.', st: mk({ vol: 100, volConf: 100, volVis: true }) },
      { name: 'Duplicate Chrome · first', note: 'Knob shows app + title only. Identical windows are told apart by the desktop overlay highlight.', st: mk({ mode: 'windows', win: { idx: 2 } }) },
      { name: 'Duplicate Chrome · second', note: 'Same text; ring cursor one detent further, overlay highlight moves.', st: mk({ mode: 'windows', win: { idx: 3 } }) },
      { name: 'Minimized terminal', note: 'Minimized windows are candidates; the overlay marks them.', st: mk({ mode: 'windows', win: { idx: 5 } }) },
      { name: 'Play', note: 'Green button, play glyph, consequence stated.', st: mk({ mode: 'recent', recent: { idx: 9 } }) },
      { name: 'More', note: 'White button, plus glyph, “doesn’t play”.', st: mk({ mode: 'recent', recent: { idx: 10 } }) },
      { name: 'Closed window', note: 'Slot kept, ring gap, Switch disabled.', st: mk({ mode: 'windows', win: { idx: 4, closed: [4] } }) },
      { name: 'Playback pending', note: 'Back disabled: the command is already out.', st: mk({ mode: 'recent', recent: { idx: 2, status: 'pending' } }) },
      { name: 'Partial playback failure', note: 'Says what happened. Play retries.', st: mk({ mode: 'recent', recent: { idx: 2, status: 'partial' } }) },
      { name: 'Disabled Previous', note: 'Position still reachable; action greyed.', st: mk({ mode: 'tracks', tracks: { pos: -1 }, opt: { noPrev: true } }) },
      { name: 'Disconnected', note: 'All buttons dark. Resumes at Volume.', st: mk({ conn: 'missing' }) }
    ];
  }

  window.NanoModel = { loadColors, COLORS, init, mk, step, view, isPending, scenarios, stress, entries, cover, APPIC, loadAllArt, ART, WINS, HAP, I, LV, QUEUE, nowPlaying };
})();
