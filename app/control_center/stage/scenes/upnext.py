"""The Up next scene on the stage (DESKTOP_STAGE §8 with §4.4-§4.6, §4.9, §13, §16; [r2.2] S5-34;
K3 §5.6, §9.7.3, §11).

Tree (bottom to top, §8.1): ambient A / B (0.45), the left column (LAYER; the enter rise and
fade): the big-cover frame (its fixed shadow, the ``#1B1B1D`` base, covers A and B, the inset
line) and the text sprites (caption, title, sub; the shuffle line A / B); the focus plate (its
fixed shadow and the fill with its inset, one opacity); the rows container (the vertical end
bump) with the row containers (MULTIPLY: their children never overlap); the hints (A / B).

A row (§8.2, §8.3): container (offset X = row left + the enter shift, offset Y = the table slot,
table opacity × 0.6 when played) > inner (the table scale about the left-middle point) > the
56 px cover lead, the text sprite (number, title, sub, tag, drawn at scale 1), and the three
[r2.2] heart forms as prepared sprites that only fade: outline (not liked 0.45, not in Apple
Music 0.15), dashed (not known yet 0.30) and filled ``#FF285A`` (liked), whose own scale pops
0.4 -> 1.5 -> 1 (SPR, per leg, S5-31) only on a ``likes`` patch; a ``data`` patch never pops:
the filled form fades in over 200 ms OUT (R22 BS:255) and every other change is instant.

Rows are pooled like the explorer's cards: only |d| <= 4 has a container; a shuffle's new order
is a second row set entering at ``t0`` + 200 while the old set fades out (160 ms IN) at ``t0``.
Rows at or past a smaller count fade out (300 ms OUT, 200 reduced) and are recycled (WP8-R6).
The big cover crossfades A <-> B 120 ms after the last detent (playlist and foreign contexts; an
album context's cover stays still), and the ambient follows the same album 200 ms after it
(§8.4): both debounces run on the art workers (a tick upload on the fast lane), never on the
stage thread. When the real cover replaces its own loading tile it takes the art-ready fade
(240 ms OUT, §7.6, §13.6; WP8-R8), and the ambient is built again from the cover's 64 px copy
(§7.5, §12; WP8-R4). Each row lead (art or placeholder) carries the shared 1 px inset line at 0.12
(§8.2; WP8-R9). The shuffle line follows the shuffle state on every patch (§8.2; WP8-R7). The hints
and shuffle-line variants are resident before the first detent; one missing on the input path
goes through the upload queue (WP8-R10).
"""
from __future__ import annotations

import hashlib

from ... import render_music as RM
from ... import scene_music as SM
from .art import LANE_ART, Job, _PRIO_FAR, _PRIO_FOCUS, _PRIO_NEAR
from .common import AmbientPair, SceneBase, shadow_sprite, static_key

ROW_WINDOW = 10                        # rows prepared around the focus (VOC §8.2 queue_window ±10)
ROW_PX_KEY = "row"
SHUFFLE_MODES = ("off", "companion", "sonos")
HINT_VARIANTS = ((False, False), (False, True), (True, False), (True, True))


def _h(*parts) -> str:
    return hashlib.sha1("\x1f".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:20]


class _Row:
    __slots__ = ("n", "box", "inner", "lead", "text", "hout", "hdash", "hfill_box", "hfill", "x", "y", "S", "o",
                 "out_o", "dash_o", "fill_o", "fill_s", "index", "set", "spec", "keys", "bound", "a", "leaving",
                 "heart", "text_o", "sharp", "sharp_o", "sharp_key", "frame", "frame_on")

    def __init__(self):
        self.index = None
        self.set = 0
        self.spec = None
        self.keys = (None, None)          # text sprite, lead art
        self.bound = [None, None]
        self.a = None
        self.leaving = False
        self.heart = "none"
        self.sharp_key = None
        self.frame_on = False


def row_spec(k, rows, now, count, card, context, likes_known):
    """What row ``k`` draws: (kind, lead, number, title, sub, tag, heart, art plan)."""
    if card is not None and isinstance(count, int) and k == count - 1:
        title, sub = SM.card_texts(card.get("n") if isinstance(card, dict) else None)
        return ("card", "none", "", title, sub, None, "none", None)
    row = rows.get(k)
    if row is None:
        return ("placeholder", "placeholder", "", "", "", None, "none", None)
    lead = SM.row_lead(row, context)
    title, sub = SM.row_texts(row, context)
    number = SM.row_number(row) if lead == "number" else ""
    tag = SM.row_tag(k, now)
    heart = SM.heart_state(row, likes_known)
    plan = SM.row_art_plan(row) if lead == "art" else None
    return ("row", lead, number, title, sub, tag, heart, plan)


def row_keys(k_index, spec, k, lead_px):
    kind, lead, number, title, sub, tag, heart, plan = spec
    tag_id = tag[0] if tag else ""
    ph = k_index if kind == "placeholder" else None
    text_key = (ROW_PX_KEY, _h(kind, lead, number, title, sub, tag_id, ph), round(k, 4))
    art_key = ("art", plan.key, "row", lead_px) if plan is not None else None
    return text_key, art_key


def _row_sprite(spec, k_index, k):
    kind, lead, number, title, sub, tag, heart, plan = spec
    if kind == "placeholder":
        return lambda: RM.row_sprite(k, lead="placeholder", placeholder_k=k_index)
    return lambda: RM.row_sprite(k, lead=lead, number=number, title=title, sub=sub, tag=tag)


def _row_art(art, plan, px):
    def run():
        if plan.kind == "generated":
            g0, g1, _ink = RM.GEN_PALETTE[SM.gen_index(plan.title, plan.artist)]
            return RM.linear_gradient_160(px, g0, g1)
        return art.element(plan, px, units=SM.U_ROW_ART_NEED, need0=px, variant="row")
    return run


def upnext_planner(art, snap):
    """Row sprites and leads for ±10 rows, the big cover (and its loading tile) for the focus ±1
    (or the context album), |d| ascending (§8.6 prefetch, §13.1)."""
    focus, specs, covers, resident, sizes, target = snap
    k, lead_px, big_px = sizes
    uploads, done = target
    jobs = []
    for i, spec in specs:
        d = abs(i - focus)
        text_key, art_key = row_keys(i, spec, k, lead_px)
        base = _PRIO_FOCUS if d == 0 else _PRIO_NEAR if d <= 4 else _PRIO_FAR
        if text_key not in resident:
            jobs.append(Job(text_key, (base, d, 0), _row_sprite(spec, i, k), uploads=uploads, done=done, opaque=False))
        if art_key is not None and art_key not in resident:
            jobs.append(Job(art_key, (base, d, 1), _row_art(art, spec[7], lead_px), uploads=uploads, done=done,
                            lane=LANE_ART))
    for j, plan in enumerate(covers):
        if plan is None:
            continue
        ck, lk = cover_keys(plan, big_px)
        pr = _PRIO_FOCUS if j == 0 else _PRIO_NEAR
        if ck is not None and ck not in resident:
            if lk not in resident:
                jobs.append(Job(lk, (pr, j, 0), (lambda plan=plan: art.loading(plan, big_px, units=SM.U_COVER)),
                                uploads=uploads, done=done))
            jobs.append(Job(ck, (pr, j, 1), (lambda plan=plan: art.element(plan, big_px, units=SM.U_COVER,
                                                                           need0=big_px, variant="cover")),
                            uploads=uploads, done=done, lane=LANE_ART))
        elif ck is None and lk not in resident:
            jobs.append(Job(lk, (pr, j, 0), (lambda plan=plan: art.loading(plan, big_px, units=SM.U_COVER)),
                            uploads=uploads, done=done))
    return jobs


def left_key(title, sub, k):
    return ("left", _h(title, sub), round(k, 4))


def left_text_job(payload, k, target, owner=None):
    """The column text of an upnext_open payload, for the factory's t = 0 prefetch (it is
    released at every close, §4.5, so each open would otherwise draw it in build)."""
    ctx = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    title, sub = str(ctx.get("title") or ""), str(ctx.get("sub") or "")
    uploads, done = target
    return Job(left_key(title, sub, k), (_PRIO_FOCUS, 0, 0), lambda: RM.left_text_sprite(title, sub, k)[0],
               uploads=uploads, done=done, opaque=False, owner=owner)


def cover_keys(plan, px):
    lid = _h(plan.title, plan.artist, plan.bg, plan.ink)
    art = plan.kind not in ("pending", "never")
    return (("art", plan.key, "cover", px) if art else None), ("load", lid, "cover", px)


# --------------------------------------------------------------------------- statics (WP8-R9, WP8-R10)
def _hints_make(hints, k):
    return lambda: RM.hints_sprite(hints, k)[0]


def _shuffle_make(text, on, k):
    return lambda: RM.shuffle_sprite(text, on, k)


def hints_name(variant):
    return f"hints.u.{int(variant[0])}{int(variant[1])}"


def upnext_static_specs(lay, payload=None):
    """(key, make) of Up next's statics at ``lay``'s k: the four hint rows, the three shuffle
    lines, the row lead's inset line, the big cover's inset and the plate. Their CPU bytes are
    rendered at the open's t = 0 on the fast lane (``common.prepare_statics``)."""
    k = lay.k
    specs = [(static_key(hints_name(v), k), _hints_make(SM.upnext_hints(*v), k)) for v in HINT_VARIANTS]
    for mode in SHUFFLE_MODES:
        text, on = SM.shuffle_line(mode)
        specs.append((static_key(f"shuffle.{mode}", k), _shuffle_make(text, on, k)))
    lead, big = SM.upx(lay, SM.U_LEAD_ART), SM.upx(lay, SM.U_COVER)
    specs.append((static_key("row.lead.frame", k), lambda: RM.frame_sprite(lead, max(1, round(k)), SM.INSET_ALPHA)))
    specs.append((static_key("cover.inset", k), lambda: RM.frame_sprite(big, max(1, round(k)), SM.INSET_ALPHA)))
    specs.append((static_key("plate.fill", k), lambda: RM.plate_sprite(k)))
    return specs


class UpNextScene(SceneBase):
    surface = "upnext"

    def __init__(self, ctx, payload, art=None, prepared=None):
        super().__init__(ctx, payload, art, prepared)
        lay = ctx.layout
        self.lay = lay
        self.rm = bool(ctx.reduced_motion)
        self.rows = {}
        self.now = 0
        self.focus = 0
        self.count = 0
        self.card = None
        self.context = {"kind": "foreign", "title": "", "sub": ""}
        self.shuffle = "off"
        self.likes_known = False
        self.loading = False
        self._apply(payload)
        self.set_id = 1
        self.play = False
        self.swap_until = None
        self.pending_index = None
        self.row_pool = []
        self.free = []
        self.bound = {}
        self.key_rows = {}
        self.lead_px = SM.upx(lay, SM.U_LEAD_ART)
        self.big_px = SM.upx(lay, SM.U_COVER)
        self.row_x = float(SM.row_left(lay))
        self.row_h = SM.upx(lay, SM.U_ROW_H)
        self.slot_tab = {}
        for a in range(SM.U_A_MAX + 1):
            for sg in (-1, 0, 1):
                for played in (False, True):
                    s = SM.row_slot(lay, sg * a if a else 0, played)
                    self.slot_tab[(a, sg, played)] = (float(s.y), s.s, s.o)
        self.cover_front = 0
        self.cover_key = None            # the key the front cover layer shows
        self.cover_want = None           # the plan the newest request is for
        self.cover_gen = 0
        self.hints_front = 0
        self.hints_shown = None
        self.shuffle_front = 0
        self.shuffle_shown = None
        self.shuffle_pending = None      # (anchor, delay_ms): the line waits for its sprite (WP8-R10)
        self.hints_pending = None        # (variant, anchor, delay_ms)
        self.context_key = None
        self.stats = {"turn_calls": []}

    # ------------------------------------------------------------------ data
    def _apply(self, payload, merge=False):
        self._spec_cache = {}
        self._keys_cache = {}
        rows = SM.rows_by_index(payload.get("rows"))
        if merge:
            for k, r in rows.items():
                cur = self.rows.get(k)
                self.rows[k] = dict(cur, **r) if isinstance(cur, dict) and set(r) <= {"row", "liked"} else r
        else:
            self.rows = rows
        if "now" in payload:
            self.now = int(payload.get("now") or 0)
        if "count" in payload:
            self.count = int(payload.get("count") or 0)
        if "card" in payload:
            self.card = payload.get("card")
        if isinstance(payload.get("context"), dict):
            self.context = payload["context"]
        if "shuffle" in payload:
            self.shuffle = payload.get("shuffle") or "off"
        if "likes_known" in payload:
            self.likes_known = bool(payload.get("likes_known"))
        if "loading" in payload:
            self.loading = bool(payload.get("loading"))
        if "focus" in payload:
            self.focus = self._clamp(int(payload.get("focus") or 0))

    def _clamp(self, i):
        return max(0, min(max(0, self.count - 1), int(i)))

    def spec(self, k):
        """Row ``k``'s spec, cached until the next patch (``_apply`` clears the cache)."""
        cache = self._spec_cache
        sp = cache.get(k)
        if sp is None:
            sp = cache[k] = row_spec(k, self.rows, self.now, self.count, self.card, self.context, self.likes_known)
        return sp

    def keys(self, k):
        cache = self._keys_cache
        kk = cache.get(k)
        if kk is None:
            kk = cache[k] = row_keys(k, self.spec(k), self.k, self.lead_px)
        return kk

    def in_range(self, i) -> bool:
        return i is not None and 0 <= i < self.count

    def wanted_indices(self):
        if self.count <= 0:
            return []
        lo = max(0, self.focus - SM.U_A_MAX)
        hi = min(self.count - 1, self.focus + SM.U_A_MAX)
        return list(range(lo, hi + 1))

    def focused_liked(self):
        r = self.rows.get(self.focus)
        return bool(r and r.get("liked") and not (self.card is not None and self.focus == self.count - 1))

    def cover_plan(self):
        row = SM.big_cover_row(self.rows, self.focus, self.now, self.context)
        return SM.big_cover_plan(row)

    # ------------------------------------------------------------------ build
    @classmethod
    def ambient_source(cls, payload, art=None):
        from .explorer import ambient_source_of
        rows = SM.rows_by_index(payload.get("rows"))
        row = SM.big_cover_row(rows, int(payload.get("focus") or 0), int(payload.get("now") or 0),
                               payload.get("context"))
        return ambient_source_of(SM.big_cover_plan(row), art)

    @classmethod
    def static_specs(cls, lay, payload=None):
        return upnext_static_specs(lay, payload)

    def build(self, payload, container):
        tree, lay, k = self.tree, self.lay, self.k
        self.container = container
        self.ambient = AmbientPair(self, container, SM.AMBIENT_OPACITY["upnext"])
        plan = self.cover_plan()
        self.ambient.first(getattr(self.ctx, "ambient_image", None), plan.key if plan else "",
                           getattr(self, "first_ambient_src", None))
        # the left column
        lx, ly = SM.stage_x(lay, SM.U_LEFT_X), SM.stage_y(lay, SM.U_LEFT_Y)
        self.left = tree.container("left", overlap=True)
        tree.add(container, self.left)
        tree.offset_x(self.left, float(int(round(lx))))
        self.left_y = tree.offset_y(self.left, float(int(round(ly))))
        self.left_o = tree.opacity(self.left, 0.0)
        big = self.big_px
        sp = shadow_sprite(big, big, 80, 0.55, 40, k)
        self.cover_shadow = tree.visual("cover.shadow", content=self.static("cover.shadow", lambda: _shadow(sp)))
        tree.matrix(self.cover_shadow, sp.scale, sp.scale, sp.offset[0], sp.offset[1])
        tree.add(self.left, self.cover_shadow)
        base = tree.visual("cover.base", content=self.ctx.solids.get(SM.U_COVER_BASE_RGB, big, big))
        tree.add(self.left, base)
        self.covers = []
        for j in range(2):
            v = tree.visual(f"cover.{j}", opacity=True)
            tree.add(self.left, v)
            self.covers.append([v, tree.opacity(v, 0.0), None])
        inset = tree.visual("cover.inset", content=self.static("cover.inset",
                                                             lambda: RM.frame_sprite(big, max(1, round(k)), SM.INSET_ALPHA)))
        lead = self.lead_px
        self.s_lead_frame = self.static("row.lead.frame",
                                        lambda: RM.frame_sprite(lead, max(1, round(k)), SM.INSET_ALPHA))
        tree.add(self.left, inset)
        text_top = (SM.U_TEXT_TOP - SM.U_LEFT_Y) * k
        self.left_text = tree.visual("left.text")
        tree.offset(self.left_text, 0, text_top)
        tree.add(self.left, self.left_text)
        cap = RM.line_normal(13 * k)
        self.shuffle_y = text_top + cap + 6 * k + 30 * k + 6 * k + max(16 * k, RM.line_normal(15 * k)) + 6 * k
        self.shuffles = []
        for j in range(2):
            v = tree.visual(f"shuffle.{j}", opacity=True)
            tree.offset(v, 0, self.shuffle_y)
            tree.add(self.left, v)
            self.shuffles.append((v, tree.opacity(v, 0.0)))
        # the focus plate
        px0, py0, px1, py1 = SM.plate_rect(lay)
        self.plate = tree.container("plate", overlap=True)
        tree.add(container, self.plate)
        tree.offset(self.plate, px0, py0)
        self.plate_o = tree.opacity(self.plate, 0.0)
        psp = shadow_sprite(px1 - px0, py1 - py0, 50, 0.35, 20, k)
        ps = tree.visual("plate.shadow", content=self.static("plate.shadow", lambda: _shadow(psp)))
        tree.matrix(ps, psp.scale, psp.scale, psp.offset[0], psp.offset[1])
        tree.add(self.plate, ps)
        pf = tree.visual("plate.fill", content=self.static("plate.fill", lambda: RM.plate_sprite(k)))
        tree.add(self.plate, pf)
        # rows
        self.rows_box = tree.container("rows", opacity=False)
        tree.add(container, self.rows_box)
        self.rows_y = tree.offset_y(self.rows_box, 0.0)
        ho, hd, hf = RM.heart_sprites(k)
        self.s_hout = self.static("heart.outline", lambda: ho)
        self.s_hdash = self.static("heart.dashed", lambda: hd)
        self.s_hfill = self.static("heart.filled", lambda: hf)
        self.heart_fill_size = hf.size[0]
        for _ in range(2 * SM.U_A_MAX + 1 + 6):
            self.free.append(self._new_row())
        # hints (two)
        hy = int(round(SM.stage_y(lay, SM.HINTS_TOP)))
        self.hints = []
        for j in range(2):
            v = tree.visual(f"hints.{j}", opacity=True)
            tree.add(container, v)
            self.hints.append((v, tree.offset_x(v, 0.0), tree.offset_y(v, float(hy)), tree.opacity(v, 0.0)))
        # every hints and shuffle-line variant resident before the first detent (WP8-R10): the
        # ones the factory's t = 0 already rendered are uploaded now, the rest on first use
        self.upload_statics([(hints_name(v), ()) for v in HINT_VARIANTS]
                            + [(f"shuffle.{m}", ()) for m in SHUFFLE_MODES])
        self._prewarm_open()
        if self.art is not None:
            self.art.forget(("prefetch", "upnext"), running=False)      # its running fetches still serve C1

    def _prewarm_open(self):
        """S2 of the 2026-09-26 frame-drop fixes: the prepared sprites the open binds (the rows' text and
        leads, the big cover or its loading tile, the column text) are uploaded here in build, before
        the engine opens the open's batch, not inside it (the batch's t1 is taken after them). ``open``
        finds them resident; the same surfaces, bound in the same batch."""
        text, on = SM.shuffle_line(self.shuffle)                      # the open's shuffle line and hints
        self.static(f"shuffle.{self.shuffle}", _shuffle_make(text, on, self.k), sync=True)
        variant = (self.shuffle != "off", self.focused_liked())
        self.static(hints_name(variant), _hints_make(SM.upnext_hints(*variant), self.k), sync=True)
        for i in self.wanted_indices():
            for key in self.keys(i):
                if key is not None:
                    self.surface_for(key, sync=True)
        plan = self.cover_plan()
        if plan is not None:
            ck, lk = cover_keys(plan, self.big_px)
            if not (ck and self.surface_for(ck, sync=True)):
                self.surface_for(lk, sync=True)
        title, sub = str(self.context.get("title") or ""), str(self.context.get("sub") or "")
        key = left_key(title, sub, self.k)
        if self.surface_for(key, sync=True) is None:                  # as ``_left_text(sync=True)`` would
            spr, _h2 = RM.left_text_sprite(title, sub, self.k)
            w, h = spr.size
            s = self.dev.create_surface(w, h, False, str(key))
            self.dev.upload(s, w, h, spr.bgra(), str(key))
            self.lru.put(key, s, w * h * 4)

    def _new_row(self):
        tree, k = self.tree, self.k
        n = len(self.row_pool)
        r = _Row()
        r.n = n
        r.box = tree.container(f"row{n}", overlap=False)
        r.inner = tree.visual(f"row{n}.inner")
        st = tree.scale_transform(r.inner, 0.0, self.row_h / 2.0)
        r.lead = tree.visual(f"row{n}.lead")
        tree.offset(r.lead, SM.U_ROW_PAD * k, 16 * k)
        r.text = tree.visual(f"row{n}.text", opacity=True)
        r.sharp = tree.visual(f"row{n}.sharp", opacity=True)
        hx = (SM.U_ROW_W - SM.U_ROW_PAD - SM.U_HEART) * k
        hy = (SM.U_ROW_H - SM.U_HEART) / 2.0 * k
        r.hout = tree.visual(f"row{n}.hout", opacity=True, content=self.s_hout)
        tree.offset(r.hout, hx, hy)
        r.hdash = tree.visual(f"row{n}.hdash", opacity=True, content=self.s_hdash)
        tree.offset(r.hdash, hx, hy)
        r.hfill_box = tree.visual(f"row{n}.hfillbox", opacity=True)
        tree.offset(r.hfill_box, hx, hy)
        hpx = SM.U_HEART * k
        fst = tree.scale_transform(r.hfill_box, hpx / 2.0, hpx / 2.0)
        r.hfill = tree.visual(f"row{n}.hfill", content=self.s_hfill)
        inv = hpx / float(self.heart_fill_size)
        tree.matrix(r.hfill, inv, inv, 0, 0)
        tree.add(r.hfill_box, r.hfill)
        r.frame = tree.visual(f"row{n}.frame")                  # the lead's inset 1 px at 0.12 (§8.2; BS:246)
        tree.offset(r.frame, SM.U_ROW_PAD * k, 16 * k)
        for ch in (r.lead, r.text, r.sharp, r.frame, r.hout, r.hdash, r.hfill_box):
            tree.add(r.inner, ch)
        tree.add(r.box, r.inner)
        tree.add(self.rows_box, r.box, back=True)
        y, s, o = self.slot_tab[(SM.U_A_MAX, 1, False)]
        r.x = tree.offset_x(r.box, self.row_x)
        r.y = tree.offset_y(r.box, y)
        r.S = tree.scale(st, SM.U_ROW_W * k, s, name=f"row{n}.S")
        r.o = tree.opacity(r.box, 0.0)
        r.out_o = tree.opacity(r.hout, 0.0)
        r.dash_o = tree.opacity(r.hdash, 0.0)
        r.fill_o = tree.opacity(r.hfill_box, 0.0)
        r.fill_s = tree.scale(fst, hpx, 1.0, name=f"row{n}.heart")
        r.text_o = tree.opacity(r.text, 1.0)
        r.sharp_o = tree.opacity(r.sharp, 0.0)
        self.row_pool.append(r)
        return r

    # ------------------------------------------------------------------ binding
    def _index_key(self, r, add):
        for key in r.keys:
            if key is None:
                continue
            s = self.key_rows.get(key)
            if add:
                if s is None:
                    s = self.key_rows[key] = set()
                s.add(r)
            elif s is not None:
                s.discard(r)
                if not s:
                    del self.key_rows[key]

    def _contents(self, batch, r, *, sync=False):
        """Set the text and lead contents from the LRU; returns True when the text is shown."""
        shown = False
        for j, v in enumerate((r.text, r.lead)):
            key = r.keys[j]
            s = self.surface_for(key, sync=sync) if key is not None else None
            if s is None and j == 0:
                continue                                # keep the previous text until the new one lands
            if s != r.bound[j]:
                self.set_content(batch, v, s)
                r.bound[j] = s
            if j == 0:
                shown = True
        return shown

    def _frame(self, batch, r):
        """The lead's inset line (§8.2: art and placeholder leads; BS:246 ``showArt = ph || own``)."""
        on = r.spec is not None and r.spec[1] in ("art", "placeholder")
        if on != r.frame_on:
            self.set_content(batch, r.frame, self.s_lead_frame if on else None)
            r.frame_on = on

    def _bind(self, batch, r, i, *, sync=False):
        self._unsharpen(batch, r)
        r.index, r.set, r.leaving = i, self.set_id, False
        r.spec = self.spec(i)
        r.keys = self.keys(i)
        if r.bound[0] is not None:
            self.set_content(batch, r.text, None)
            r.bound[0] = None
        self._index_key(r, True)
        self.bound[(r.set, i)] = r
        self.counters["binds"] += 1
        self._contents(batch, r, sync=sync)
        self._frame(batch, r)

    def _unbind(self, r):
        r.sharp_key = None
        self._index_key(r, False)
        self.bound.pop((r.set, r.index), None)
        r.index, r.spec, r.keys, r.a, r.leaving = None, None, (None, None), None, False
        self.free.append(r)
        self.counters["recycled"] += 1

    def _take_row(self):
        if self.free:
            return self.free.pop()
        self.counters["grown"] += 1
        return self._new_row()

    def _slot(self, k):
        d = k - self.focus
        a = min(abs(d), SM.U_A_MAX)
        return a, self.slot_tab[(a, SM.sign(d), k < self.now)]

    def _heart(self, batch, r, *, pop=False, fade_in=False):
        """The heart forms of the row's state (S5-34 precedence): outline and dashed switch at
        once; the filled form pops on a ``likes`` patch, fades in (200 OUT) on a ``data`` patch."""
        state = r.spec[6] if r.spec else "none"
        out, dash, fill = SM.HEART_LOOKS[state]
        batch.jump(r.out_o, out)
        batch.jump(r.dash_o, dash)
        if fill > 0 and r.heart != "liked":
            if pop and not self.rm:
                batch.to(r.fill_o, 1.0, SM.HEART_OPACITY_MS, "OUT", v_from=0.0, force=True)
                batch.legs(r.fill_s, [(0, 1.5, 380, "SPR"), (420, 1.0, 380, "SPR")], v_from=SM.HEART_FROM)
            elif (pop or fade_in):
                batch.jump(r.fill_s, 1.0)
                batch.to(r.fill_o, 1.0, SM.HEART_OPACITY_MS, "OUT", v_from=0.0, force=True)
            else:
                batch.jump(r.fill_s, 1.0)
                batch.jump(r.fill_o, 1.0)
        elif fill <= 0:
            batch.jump(r.fill_o, 0.0)
            batch.jump(r.fill_s, SM.HEART_FROM)
        r.heart = state

    def _place(self, batch, r, *, enter=False):
        """Jump a freshly bound row to its slot (``enter``: +40·S to the right, opacity 0)."""
        a, (y, s, o) = self._slot(r.index)
        batch.jump(r.y, y)
        batch.jump(r.S, s)
        batch.jump(r.x, self.row_x + (SM.U_ENTER_UNITS * s * self.k if enter and not self.rm else 0.0))
        batch.jump(r.o, 0.0)
        r.a = a
        r.heart = "none"
        self._heart(batch, r)

    def _enter(self, batch, r, anchor, delay_ms):
        a, (y, s, o) = self._slot(r.index)
        if self.rm:
            batch.jump(r.x, self.row_x)
            batch.to(r.o, o, SM.REDUCED_OPACITY_MS, "OUT", v_from=0.0, force=True, anchor=anchor, delay_ms=delay_ms)
            return
        d = delay_ms + SM.U_STAGGER_MS * a
        batch.to(r.x, self.row_x, SM.U_ENTER_MS, "OUT", anchor=anchor, delay_ms=d)
        batch.to(r.o, o, SM.U_ENTER_OPACITY_MS, "OUT", anchor=anchor, delay_ms=d, v_from=0.0, force=True)

    def _revive(self, wanted):
        """Rows of the current set fading out past a smaller count come back when it grows again."""
        out = []
        for i in wanted:
            r = self.bound.get((self.set_id, i))
            if r is not None and r.leaving:
                r.leaving = False
                out.append(r)
        return out

    def _drop_gone(self, batch):
        """Rows of the current set at or past a smaller count (a ``queue_changed`` of an edit made
        elsewhere, K3 §5.6.8) fade out (300 ms OUT; 200 reduced) and are recycled at rest (WP8-R6)."""
        for r in list(self.bound.values()):
            if r.set != self.set_id or r.leaving or self.in_range(r.index):
                continue
            r.leaving = True
            self._unsharpen(batch, r)
            batch.to(r.o, 0.0, SM.REDUCED_OPACITY_MS if self.rm else SM.U_TURN_OPACITY_MS, "OUT")

    def _recycle(self, t):
        for key, r in list(self.bound.items()):
            if (r.set == self.set_id and not r.leaving and abs(r.index - self.focus) <= SM.U_A_MAX
                    and r.index < self.count):
                continue
            if r.o.moving(t) or r.y.moving(t) or r.x.moving(t):
                continue
            if r.set == self.set_id and r.o.value(t) > 0.0:
                continue
            self._unbind(r)

    def _reorder(self, batch):
        cur = self.set_id
        active = sorted(self.bound.values(), key=lambda r: (r.set == cur, -min(abs(r.index - self.focus), 4), r.index))
        order = [r.box for r in self.free] + [r.box for r in active]
        before = self.tree.calls
        if self.rows_box.children != order:
            self.tree.reorder(self.rows_box, order)
        batch.calls += self.tree.calls - before

    # ------------------------------------------------------------------ open
    def open(self, batch, payload):
        """§8.5 Open: the left column rises +20 -> 0 (460 OUT) and fades in (320 OUT); rows enter
        +40·S -> 0 (420 OUT) and fade to the table (300 OUT), 40 ms × a; the plate fades in (320).
        Reduced motion: no offsets, no stagger, opacities 200 ms."""
        k = self.k
        if not self.rm:
            y0 = self.left_y.target
            batch.to(self.left_y, y0, SM.U_LEFT_RISE_MS, "OUT", v_from=y0 + SM.U_LEFT_RISE_UNITS * k, force=True)
        batch.to(self.left_o, 1.0, SM.U_LEFT_OPACITY_MS, "OUT", v_from=0.0, force=True)
        batch.to(self.plate_o, 1.0, SM.U_PLATE_MS, "OUT", v_from=0.0, force=True)
        for i in self.wanted_indices():
            r = self._take_row()
            self._bind(batch, r, i, sync=True)
            self._place(batch, r, enter=True)
            self._enter(batch, r, None, 0.0)
        self._reorder(batch)
        self._cover_now(batch, sync=True)
        plan = self.cover_plan()
        if plan is not None and self.cover_key is not None and self.cover_key[0] == "art":
            self.ambient.refresh_if_first_stale(plan, self.ctx.clock.to_perf(self.ctx.clock.now()))
        self._left_text(batch, sync=True)
        self._shuffle_line(batch, None, 0.0, first=True)
        self._hints(batch, None, 0.0, first=True)
        self._after_change(batch, cover=False)

    # ------------------------------------------------------------------ turns
    def turn(self, batch, focus):
        """§8.5 Turn: rows retarget Y and S (420 OUT) and opacity (300 OUT, × 0.6 when played);
        the big cover follows 120 ms after the last detent (playlist / foreign), the ambient 200 ms."""
        focus = self._clamp(focus)
        if focus == self.focus or self.play:
            return 0
        n0 = batch.calls
        t1 = batch.t1
        self.focus = focus
        cur = self.set_id
        self._unsharpen_all(batch)
        wanted = self.wanted_indices()
        self._revive(wanted)
        self._drop_gone(batch)
        for i in wanted:
            if (cur, i) not in self.bound:
                r = self._take_row()
                self._bind(batch, r, i)
                self._place(batch, r)
                a, (y, s, o) = self._slot(i)
                side = SM.sign(i - focus) or 1
                edge = self.slot_tab[(SM.U_A_MAX, side, i < self.now)]
                batch.jump(r.y, edge[0])
                batch.jump(r.S, edge[1])
        rm = self.rm
        for r in list(self.bound.values()):
            if r.set != cur or r.leaving:
                continue
            self._retarget(batch, r, t1, rm)
        self._recycle(t1)
        self._reorder(batch)
        self._hints(batch, None, 0.0)
        self._after_change(batch, cover=True)
        self.stats["turn_calls"].append(batch.calls - n0)
        return batch.calls - n0

    def _retarget(self, batch, r, t1, rm):
        a, (y, s, o) = self._slot(r.index)
        was_hidden = r.o.target <= 0.0 and r.o.value(t1) <= 0.0
        if (was_hidden and o <= 0.0) or rm:
            batch.jump(r.y, y)
            batch.jump(r.S, s)
            if rm:
                batch.to(r.o, o, SM.REDUCED_OPACITY_MS, "OUT")
            else:
                batch.jump(r.o, o)
        else:
            batch.to(r.y, y, SM.U_TURN_MS, "OUT")
            batch.to(r.S, s, SM.U_TURN_MS, "OUT")
            batch.to(r.o, o, SM.U_TURN_OPACITY_MS, "OUT")
        r.a = a

    # ------------------------------------------------------------------ patches
    def update(self, batch, call, payload):
        if self.play:
            return
        t = batch.t1
        if call == "upnext_highlight":
            idx = payload.get("index")
            if idx is not None and self.swapping(t):
                self.pending_index = int(idx)
                return
            if idx is not None:
                self.turn(batch, int(idx))
            bump = int(payload.get("bump") or 0)
            if bump and not self.rm:
                k = self.k
                batch.legs(self.rows_y, [(0, -SM.BUMP_UNITS * k * bump, SM.BUMP_LEG_MS, "OUT"),
                                         (SM.BUMP_LEG_MS, 0.0, SM.BUMP_LEG_MS, "OUT")], v_from=0.0)
            return
        if call != "upnext_rows":
            return
        reason = payload.get("reason")
        if reason == "shuffle":
            return self._shuffle(batch, payload)
        old_context = dict(self.context)
        payload = dict(payload)
        new_focus = payload.pop("focus", None)
        self._apply(payload, merge=reason != "queue_changed")
        if new_focus is None and self._clamp(self.focus) != self.focus:
            new_focus = self._clamp(self.focus)             # a smaller count: the focus follows (WP8-R6)
        if reason == "likes":
            self._likes(batch, payload)
        self._refresh(batch, reason)
        self._shuffle_line(batch, None, 0.0)                # §8.2: the line follows the state (WP8-R7)
        if self.context != old_context:
            self._left_text(batch)
        if new_focus is not None and self._clamp(int(new_focus)) != self.focus:
            if self.swapping(t):
                self.pending_index = int(new_focus)
            else:
                self.turn(batch, int(new_focus))
        else:
            self._hints(batch, None, 0.0)
            self._after_change(batch, cover=True)

    def _refresh(self, batch, reason):
        """``data`` / ``queue_changed`` / the likes' state: rows whose spec changed get their new
        sprites (instant swaps when ready; a placeholder that got data fades 0 -> table over
        160 ms OUT at rest), heart states set without a pop, new rows bound, rows past the end
        recycled."""
        t = batch.t1
        cur = self.set_id
        wanted = self.wanted_indices()
        revived = self._revive(wanted)
        self._drop_gone(batch)
        for r in list(self.bound.values()):
            if r.set != cur or r.leaving:
                continue
            spec = self.spec(r.index)
            if spec == r.spec:
                continue
            was_placeholder = r.spec is not None and r.spec[0] == "placeholder"
            self._unsharpen(batch, r)
            self._index_key(r, False)
            r.spec = spec
            r.keys = self.keys(r.index)
            self._index_key(r, True)
            shown = self._contents(batch, r)
            if was_placeholder and spec[0] != "placeholder" and reason in ("data", "queue_changed"):
                if shown:
                    a, (y, s, o) = self._slot(r.index)
                    batch.to(r.o, o, SM.U_ROW_DATA_MS, "OUT", v_from=0.0, force=True)
                else:
                    self._mark_fade(r)
            if reason != "likes":
                self._heart(batch, r, fade_in=True)
            self._frame(batch, r)
            self._retarget(batch, r, t, self.rm)
        for i in wanted:
            if (cur, i) not in self.bound:
                r = self._take_row()
                self._bind(batch, r, i)
                self._place(batch, r)
                a, (y, s, o) = self._slot(i)
                batch.to(r.o, o, SM.U_ROW_DATA_MS, "OUT", v_from=0.0, force=True)
        for r in revived:
            self._retarget(batch, r, t, self.rm)
        self._recycle(t)
        self._reorder(batch)

    def _mark_fade(self, r):
        self._fade_on_land = getattr(self, "_fade_on_land", set())
        self._fade_on_land.add(r)

    def _likes(self, batch, payload):
        """A confirmed like (a ``likes`` patch, [r2.2] ``liked: true`` only): the heart pops."""
        for entry in payload.get("rows") or ():
            if not isinstance(entry, dict) or not isinstance(entry.get("row"), int):
                continue
            k = entry["row"] - 1
            r = self.bound.get((self.set_id, k))
            if r is None:
                continue
            r.spec = self.spec(k)
            self._heart(batch, r, pop=True)

    # ------------------------------------------------------------------ the sharpen pass (§8.6, AR-17, S5-27)
    def _unsharpen(self, batch, r):
        """The first turn (or a new binding, a content change) discards the exact-scale sprite."""
        if r.sharp_key is None:
            return
        r.sharp_key = None
        batch.jump(r.sharp_o, 0.0)
        batch.jump(r.text_o, 1.0)

    def _unsharpen_all(self, batch):
        self.sharp_gen = getattr(self, "sharp_gen", 0) + 1
        self._sharp_want = {}
        for r in self.bound.values():
            if r.sharp_key is not None:
                self._unsharpen(batch, r)

    def _schedule_sharpen(self):
        """150 ms after the rows settle (the twins know when), render exact-scale text sprites for
        the visible rows with a != 0 on a worker (a tick first, so a spin schedules nothing)."""
        if self.art is None or self.play:
            return
        end = None
        for r in self.bound.values():
            if r.set != self.set_id:
                continue
            for prop in (r.y, r.S, r.o):
                e = prop.func.end_tick
                if e is not None and (end is None or e > end):
                    end = e
        clock = self.ctx.clock
        at = clock.to_perf(end if end is not None else clock.now()) + SM.SHARPEN_DELAY_MS / 1000.0
        gen = getattr(self, "sharp_gen", 0)
        self._sharp_tick = self.tick_job(("sharpen", gen), at, replace=getattr(self, "_sharp_tick", None))

    def _sharpen_fire(self, batch, gen):
        if gen != getattr(self, "sharp_gen", 0) or self.play or self.swapping(batch.t1):
            return
        t = batch.t1
        k = self.k
        want = {}
        for r in self.bound.values():
            if r.set != self.set_id or r.leaving or r.spec is None or r.spec[0] == "placeholder":
                continue
            a, (y, s, o) = self._slot(r.index)
            if a == 0 or o <= 0.0 or r.o.moving(t) or r.S.moving(t) or r.y.moving(t):
                continue
            key = ("rowsharp", r.keys[0][1], round(k * s, 4))
            want.setdefault(key, set()).add(r)
            if self.lru.get(key) is None:
                self.art.add(self.job(key, (_PRIO_FAR, a, 9), _row_sprite(r.spec, r.index, k * s), owner=self.owner,
                                      opaque=False))
        self._sharp_want = want
        self._sharp_land(batch, [key for key in want if self.lru.get(key) is not None])

    def _sharp_land(self, batch, keys):
        for key in keys:
            rows = getattr(self, "_sharp_want", {}).get(key)
            surface = self.lru.get(key)
            if not rows or surface is None:
                continue
            for r in rows:
                if r.set != self.set_id or r.sharp_key == key:
                    continue
                a, (y, s, o) = self._slot(r.index)
                self.set_content(batch, r.sharp, surface)
                self.set_matrix(batch, r.sharp, 1.0 / s, 1.0 / s, 0.0, 0.0)
                batch.to(r.sharp_o, 1.0, SM.SHARPEN_FADE_MS, "OUT", v_from=0.0, force=True)
                batch.to(r.text_o, 0.0, SM.SHARPEN_FADE_MS, "OUT")
                r.sharp_key = key

    def _shuffle(self, batch, payload):
        """§8.5 Shuffle at ``t0`` (the press, or the verified completion): the rows fade out 160 ms
        IN; the new order (focus = now + 1) enters at ``t0`` + 200 with the 40 ms stagger; the
        shuffle line crossfades (240 EASE) and the hints swap (instant) at +200."""
        t0 = self.ctx.t0_ticks(payload)
        self.sharp_gen = getattr(self, "sharp_gen", 0) + 1
        self._sharp_want = {}
        for r in list(self.bound.values()):
            if r.set == self.set_id and not r.leaving:
                r.leaving = True
                batch.to(r.o, 0.0, SM.REDUCED_OPACITY_MS if self.rm else SM.U_SHUFFLE_EXIT_MS,
                         "OUT" if self.rm else "IN", anchor=t0)
        self.set_id += 1
        self._apply(payload, merge=False)
        self.swap_until = t0 + int(round(SM.U_SHUFFLE_ENTRY_MS * self.ctx.clock.freq / 1000.0))
        for i in self.wanted_indices():
            r = self._take_row()
            self._bind(batch, r, i)
            self._place(batch, r, enter=True)
            self._enter(batch, r, t0, SM.U_SHUFFLE_ENTRY_MS)
        self._reorder(batch)
        self._shuffle_line(batch, t0, SM.U_SHUFFLE_ENTRY_MS)
        self._hints(batch, t0, SM.U_SHUFFLE_ENTRY_MS)
        self.tick_job("swap_end", self.ctx.clock.to_perf(self.swap_until))
        self._after_change(batch, cover=True)

    # ------------------------------------------------------------------ left column, hints
    def _left_text(self, batch, sync=False):
        title = str(self.context.get("title") or "")
        sub = str(self.context.get("sub") or "")
        key = left_key(title, sub, self.k)
        if key == self.context_key:
            return
        s = self.surface_for(key, sync=sync)
        if s is None:
            if sync:
                spr, _h2 = RM.left_text_sprite(title, sub, self.k)
                w, h = spr.size
                s = self.dev.create_surface(w, h, False, str(key))
                self.dev.upload(s, w, h, spr.bgra(), str(key))
                self.lru.put(key, s, w * h * 4)
            else:
                if self.art is not None:
                    k = self.k
                    self.art.add(self.job(key, (_PRIO_FOCUS, 0, 0),
                                          lambda: RM.left_text_sprite(title, sub, k)[0], owner=self.owner,
                                          opaque=False))
                self.context_pending = key
                return
        self.set_content(batch, self.left_text, s)
        self.context_key = key
        self.context_pending = None

    def _shuffle_line(self, batch, anchor, delay_ms, first=False):
        """The shuffle line of the current state (§8.2): a 240 ms EASE crossfade of two sprites
        (at ``anchor`` + ``delay_ms``, or now). Off the open, a sprite that is not resident goes
        through the upload queue and the crossfade runs when it lands (WP8-R10)."""
        text, on = SM.shuffle_line(self.shuffle)
        if (text, on) == self.shuffle_shown:
            self.shuffle_pending = None
            return
        s = self.static(f"shuffle.{self.shuffle}", _shuffle_make(text, on, self.k), sync=first)
        if s is None:
            self.shuffle_pending = (anchor, delay_ms)
            return
        self.shuffle_pending = None
        if first:
            v, op = self.shuffles[self.shuffle_front]
            self.set_content(batch, v, s)
            batch.jump(op, 1.0)
        else:
            j = 1 - self.shuffle_front
            v, op = self.shuffles[j]
            fv, fop = self.shuffles[self.shuffle_front]
            self.set_content(batch, v, s)
            batch.to(op, 1.0, SM.U_SHUFFLE_LINE_MS, "EASE", v_from=0.0, force=True, anchor=anchor, delay_ms=delay_ms)
            batch.to(fop, 0.0, SM.U_SHUFFLE_LINE_MS, "EASE", anchor=anchor, delay_ms=delay_ms)
            self.shuffle_front = j
        self.shuffle_shown = (text, on)

    def _hints(self, batch, anchor, delay_ms, first=False):
        """``[1] Back · [2] Shuffle | Shuffle off · [3] Like | Liked · [4] Play`` ([r2.2]): an
        instant swap when the shuffle state or the focused row's liked state changes."""
        variant = (self.shuffle != "off", self.focused_liked())
        if variant == self.hints_shown:
            self.hints_pending = None
            return
        hints = SM.upnext_hints(*variant)
        name = hints_name(variant)
        s = self.static(name, _hints_make(hints, self.k), sync=first)
        if s is None:                                   # on its way (WP8-R10): swapped when it lands
            self.hints_pending = (variant, anchor, delay_ms)
            return
        self.hints_pending = None
        w, _h2 = self.static_size(name)
        x = float(int(round(SM.stage_x(self.lay, 640) - w / 2.0)))
        if first or anchor is None:
            v, xp, _yp, op = self.hints[self.hints_front]
            self.set_content(batch, v, s)
            batch.jump(xp, x)
            batch.jump(op, 1.0)
        else:
            j = 1 - self.hints_front
            v, xp, _yp, op = self.hints[j]
            fv, fxp, _fyp, fop = self.hints[self.hints_front]
            self.set_content(batch, v, s)
            batch.jump(xp, x)
            batch.jump(op, 1.0, anchor=anchor, delay_ms=delay_ms)
            batch.jump(fop, 0.0, anchor=anchor, delay_ms=delay_ms)
            self.hints_front = j
        self.hints_shown = variant

    # ------------------------------------------------------------------ the big cover
    def _cover_now(self, batch, sync=False):
        """At open: the cover (or its loading tile) on layer A, without a crossfade."""
        plan = self.cover_plan()
        self.cover_want = plan.key if plan else None
        if plan is None:
            return
        ck, lk = cover_keys(plan, self.big_px)
        s = self.surface_for(ck, sync=sync) if ck else None
        key = ck
        if s is None:
            s = self.surface_for(lk, sync=sync)
            key = lk if s is not None else None
        if s is None:
            self.cover_pending = (ck, lk)
            return
        v, op, _ = self.covers[self.cover_front]
        self.set_content(batch, v, s)
        batch.jump(op, 1.0)
        self.covers[self.cover_front][2] = key
        self.cover_key = key
        self.cover_pending = (ck, lk) if key != ck else None

    def _cover_request(self):
        """A focus change: restart the 120 ms debounce (playlist / foreign context; an album
        context's cover stays still, S01:326)."""
        plan = self.cover_plan()
        key = plan.key if plan else None
        if key == self.cover_want:
            return
        self.cover_want = key
        self.cover_gen += 1
        now_s = self.ctx.clock.to_perf(self.ctx.clock.now())
        self.cover_tick = self.tick_job(("cover", self.cover_gen), now_s + SM.U_COVER_DEBOUNCE_MS / 1000.0,
                                        replace=getattr(self, "cover_tick", None))

    def _cover_fire(self, batch):
        plan = self.cover_plan()
        if plan is None or plan.key != self.cover_want:
            return
        ck, lk = cover_keys(plan, self.big_px)
        s = self.surface_for(ck) if ck else None
        key = ck
        if s is None:
            s = self.surface_for(lk)
            key = lk if s is not None else None
        self.cover_pending = (ck, lk) if key != ck else None
        if s is None or key == self.cover_key:
            return
        self._cover_swap(batch, s, key)

    def _cover_ready(self, batch, s, key):
        """§7.6 "Art ready", §13.6 ``art.loading`` (WP8-R8): the real cover over its own loading
        tile, 0 -> 1 over 240 ms OUT, with no dip. The layers keep a fixed order (cover.0 under
        cover.1): above the tile, the cover fades in and the tile is hidden once it has; below
        it, the cover shows at once and the tile fades out, which is the same blend."""
        j = 1 - self.cover_front
        v, op, _ = self.covers[j]
        fv, fop, _ = self.covers[self.cover_front]
        self.set_content(batch, v, s)
        if j > self.cover_front:
            batch.to(op, 1.0, SM.ART_READY_MS, "OUT", v_from=0.0, force=True)
            batch.jump(fop, 0.0, delay_ms=SM.ART_READY_MS)
        else:
            batch.jump(op, 1.0)
            batch.to(fop, 0.0, SM.ART_READY_MS, "OUT")
        self.covers[j][2] = key
        self.cover_front = j
        self.cover_key = key

    def _cover_swap(self, batch, s, key, ms=SM.U_COVER_MS):
        j = 1 - self.cover_front
        v, op, _ = self.covers[j]
        fv, fop, _ = self.covers[self.cover_front]
        self.set_content(batch, v, s)
        batch.to(op, 1.0, ms, "OUT", v_from=0.0, force=True)
        batch.to(fop, 0.0, ms, "OUT")
        self.covers[j][2] = key
        self.cover_front = j
        self.cover_key = key

    # ------------------------------------------------------------------ Play, close
    def close(self, batch, payload):
        """Play (§8.5, S5-7): the focused row grows 1 -> 1.06 (420 OUT), the other rows fade over
        300 OUT, the plate fades over 320 OUT; reduced motion: no grow, 200 ms fades."""
        self.play = True
        t0 = self.ctx.t0_ticks(payload)
        for r in list(self.bound.values()):
            if r.set != self.set_id or r.leaving:
                continue
            if r.index == self.focus:
                if not self.rm:
                    batch.to(r.S, SM.U_PLAY_GROW, SM.U_PLAY_GROW_MS, "OUT", anchor=t0)
            else:
                batch.to(r.o, 0.0, SM.REDUCED_OPACITY_MS if self.rm else SM.PLAY_OTHERS_MS, "OUT", anchor=t0)
        batch.to(self.plate_o, 0.0, SM.REDUCED_OPACITY_MS if self.rm else SM.U_PLAY_PLATE_MS, "OUT", anchor=t0)

    def hit_rect(self):
        return None if self.play else SM.plate_rect(self.lay)

    def swapping(self, now_tick) -> bool:
        return self.play or (self.swap_until is not None and now_tick < self.swap_until)

    def position(self, batch, index):
        if not self.play and not self.swapping(batch.t1):
            self.turn(batch, index)

    # ------------------------------------------------------------------ uploads
    def uploads_ready(self, batch, keys):
        cover_art = False
        for key in keys:
            self.counters["landed"] += 1
            if self.ambient.landed(batch, key):
                continue
            kind = key[0] if isinstance(key, tuple) else None
            if kind == "static":
                self._static_landed(batch, key)
                continue
            if (kind == "art" and len(key) > 2 and key[2] == "cover" and self.ambient.want
                    and key[1] == self.ambient.want):
                cover_art = True                            # the ambient's album: its 64 px copy exists now
            if kind == "tick":
                tag = getattr(self, "tick_tags", {}).pop(key, None)
                if tag == "swap_end" and self.pending_index is not None and not self.swapping(batch.t1):
                    idx, self.pending_index = self.pending_index, None
                    self.turn(batch, idx)
                elif isinstance(tag, tuple) and tag[0] == "cover" and tag[1] == self.cover_gen:
                    self._cover_fire(batch)
                elif isinstance(tag, tuple) and tag[0] == "sharpen":
                    self._sharpen_fire(batch, tag[1])
                continue
            if kind == "rowsharp":
                self._sharp_land(batch, [key])
                continue
            if kind == "left":
                if getattr(self, "context_pending", None) == key:
                    self._left_text(batch)
                continue
            pend = getattr(self, "cover_pending", None)
            if pend is not None and key in pend:
                plan = self.cover_plan()
                if plan is not None and plan.key == self.cover_want and key != self.cover_key:
                    s = self.surface_for(key)
                    if s is not None:
                        if key == pend[0] and self.cover_key == pend[1]:
                            self._cover_ready(batch, s, key)          # over its own loading tile (WP8-R8)
                        else:
                            self._cover_swap(batch, s, key,
                                             SM.ART_READY_MS if self.cover_key is None else SM.U_COVER_MS)
                        self.cover_pending = None if key == pend[0] else pend
            fade = getattr(self, "_fade_on_land", set())
            for r in list(self.key_rows.get(key, ())):
                self._contents(batch, r)
                if r in fade and r.bound[0] is not None:
                    fade.discard(r)
                    a, (y, s, o) = self._slot(r.index)
                    batch.to(r.o, o, SM.U_ROW_DATA_MS, "OUT", v_from=0.0, force=True)
        if cover_art:
            # §7.5, §12 (WP8-R4): the ambient was built from ``art_bg`` (or an older source) while
            # the cover was not cached; build it again from the cover, with the 200 ms debounce
            now_s = self.ctx.clock.to_perf(self.ctx.clock.now())
            self.ambient.refresh(self.cover_plan(), now_s)
        self._pin()

    def _static_landed(self, batch, key):
        """A static posted from the input path landed: show what waited for it."""
        name = key[1] if len(key) > 1 else ""
        if not isinstance(name, str):
            return
        if name.startswith("hints.u.") and self.hints_pending is not None:
            variant, anchor, delay_ms = self.hints_pending
            self._hints(batch, anchor, delay_ms)
        elif name.startswith("shuffle.") and self.shuffle_pending is not None:
            anchor, delay_ms = self.shuffle_pending
            self._shuffle_line(batch, anchor, delay_ms)

    # ------------------------------------------------------------------ art, ambient, pins
    def _after_change(self, batch, *, cover):
        if cover:
            self._cover_request()
        self._schedule_sharpen()
        plan = self.cover_plan()
        now_s = self.ctx.clock.to_perf(self.ctx.clock.now())
        self.ambient.request(plan, now_s)
        self._plan_art()
        self._pin()

    def _plan_art(self):
        """Hand the workers the rows ±10 and the covers, only when something is not resident."""
        if self.art is None or self.count <= 0:
            return
        lo = max(0, self.focus - ROW_WINDOW)
        hi = min(self.count - 1, self.focus + ROW_WINDOW)
        lru = self.lru
        if self.context.get("kind") == "album":
            covers = [self.cover_plan()]
        else:
            covers = [SM.big_cover_plan(self.rows.get(i)) for i in (self.focus, self.focus + 1, self.focus - 1)]
        need = False
        for plan in covers:
            if plan is not None:
                ck, lk = cover_keys(plan, self.big_px)
                if (ck or lk) not in lru:
                    need = True
                    break
        if not need:
            for i in range(lo, hi + 1):
                tk, ak = self.keys(i)
                if tk not in lru or (ak is not None and ak not in lru):
                    need = True
                    break
        if not need:
            return
        order = sorted(range(lo, hi + 1), key=lambda i: (abs(i - self.focus), i))
        specs = [(i, self.spec(i)) for i in order]
        snap = (self.focus, specs, covers, lru, (self.k, self.lead_px, self.big_px), (self.uploads, self.done))
        self.art.plan(self.owner, upnext_planner, snap)

    def _pin(self):
        keys = set(self.key_rows)
        keys.update(r.sharp_key for r in self.bound.values() if r.sharp_key is not None)
        keys.update(layer[2] for layer in self.covers if layer[2] is not None)
        if self.context_key is not None:
            keys.add(self.context_key)
        keys.update(self.ambient.keys())
        self.repin(keys)


def _shadow(sp):
    return RM.Sprite.from_rgba(sp.image)                  # black: premultiplied colour stays 0
