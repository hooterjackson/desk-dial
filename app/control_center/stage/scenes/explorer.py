"""The Music explorer scene on the stage (DESKTOP_STAGE §7 with §4.4-§4.6, §4.9, §13, §16, §18;
[G1] G1-4, G1-7, G1-9; K3 §5.3, §11).

Tree (bottom to top, §7.1): ambient A / B, the two tabs (a container each: the tab sprite and its
underline bar, scaled about its centre), the cards box (carries the end bump), the card
containers (z = 20 − a, reordered only at a detent), the label (two visuals, so a source switch
can fade one out while the other waits for +190 ms), the state block (two), the dot rows (two)
and the marker, the hints.

A card (§7.3): container (LAYER, table opacity) > inner (TransformGroup: the table scale S and
the enter scale e, about the card centre) > side shadow, focus shadow (fixed 1/4-resolution
layers, crossfaded 320 ms), base (the shared ``#232325`` solid: never a blank card), the loading
tiles (L1 x 2 and L0), the art group (LAYER; opacity 0 -> 1 over 240 ms when the art is ready)
holding L1 (170·k px, x 2) and L0 (340·k px, faded 0 <-> 1 across |d| = 1 <-> 2 on the turn curve,
S5-28), the shared inset line and the shade (the shared 680 px solid, G1-9).

Cards are pooled: only items with |d| <= a_max have a container (§7.2); a card leaving the
range animates to the a_max slot and is recycled once its twin is at rest; a card coming into
range is bound at the a_max slot on its side at opacity 0 and animates in (CSS parity). Every
retarget starts from the twin at t1 (G1-7); equal targets cost nothing and a card invisible
before and after a turn jumps (G1-4).

Timed legs (§0.6, §2.3): the source switch and the state changes are committed at their trigger
with holds anchored to ``t0`` (the tabs at the press; the old cards' 170 ms IN exit; the new set,
label, block and dots at +190 ms), so no timer runs. A tick upload (``SceneBase.tick_job``)
wakes the scene at +190 ms only to apply a turn that was recorded during the swap. Only the turn
waits: a highlight's data inside the 190 ms (new descriptors, a new count) is applied at once to
the entering set, its label and its dots (WP8-R5).

A smaller count (K3 §11.1 ``explorer_highlight``) fades the cards at or past it out (300 ms OUT,
200 reduced) and recycles them; the dots show the true count (§7.2, §7.4; WP8-R6).

The block and dot-row sprites that are missing on the input path go through the upload queue
(``SceneBase.static(sync=False)``) and are swapped in when they land (WP8-R10).
"""
from __future__ import annotations

import hashlib

from ... import render_music as RM
from ... import scene_music as SM
from ..tree import _lis_indices
from .art import LANE_ART, Job, _PRIO_FAR, _PRIO_FOCUS, _PRIO_NEAR
from .common import AmbientPair, SceneBase, program_legs, set_value, shadow_sprite, static_key

LABEL_PREFETCH = 3                      # ±3 around the focus (RF0 §2.1)


class _All(set):
    """Every index changed (a new ``items_rev``)."""

    def __contains__(self, item):
        return True

    def __bool__(self):
        return True


ALL = _All()
_UNSET = object()


def _h(*parts) -> str:
    return hashlib.sha1("\x1f".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:20]


class _Card:
    __slots__ = ("n", "box", "inner", "side", "focus", "base", "load1", "load0", "art", "l1", "l0", "inset",
                 "shade", "x", "y", "S", "e", "o", "side_o", "focus_o", "ready_o", "l0_o", "sh", "index", "set",
                 "plan", "keys", "bound", "a", "leaving", "z")

    def __init__(self):
        self.index = None
        self.set = 0
        self.plan = None
        self.keys = (None, None, None, None)      # l1, l0, load1, load0
        self.bound = [None, None, None, None]     # surfaces bound to l1, l0, load1, load0
        self.a = None
        self.leaving = False
        self.z = False                            # in ``ExplorerScene._z`` (its stacking place is known)


def _by_index(c):
    return c.index


def card_keys(plan, l1px, l0px):
    if plan is None:
        return (None, None, None, None)
    lid = _h(plan.title, plan.artist, plan.bg, plan.ink)
    art = plan.kind not in ("pending", "never")
    return (("art", plan.key, "card", l1px) if art else None, ("art", plan.key, "card", l0px) if art else None,
            ("load", lid, l1px), ("load", lid, l0px))


def label_key(texts, k):
    return ("label", _h(*texts), round(k, 4))


# --------------------------------------------------------------------------- the planner (worker side)
def explorer_planner(art, snap):
    """The jobs of one snapshot (§7.7, §13.4): |d| ascending, the direction of travel first;
    L1 for the whole preload window, L0 (with L1 from the same decode) for the L0 set, loading
    tiles where the art is not resident yet, the labels ±3."""
    focus, direction, order, plans, l0set, labels, resident, sizes, target, units = snap
    l1px, l0px, k = sizes
    uploads, done = target
    jobs = []
    dirn = SM.sign(direction) or 1
    for i in order:
        plan = plans.get(i)
        if plan is None:
            continue
        d = i - focus
        ad = abs(d)
        side = 0 if SM.sign(d) in (0, dirn) else 1
        l1k, l0k, ld1, ld0 = card_keys(plan, l1px, l0px)
        need0 = i in l0set
        have1 = l1k is not None and l1k in resident
        have0 = l0k is not None and l0k in resident
        if l1k is not None and have1 and (not need0 or have0):
            continue
        base = _PRIO_NEAR if ad <= 2 else _PRIO_FAR
        if not have1 and ld1 not in resident:
            jobs.append(Job(ld1, (base, ad, side, 0), _loading(art, plan, l1px, units), uploads=uploads, done=done))
        if need0 and not have0 and not have1 and ld0 not in resident:
            jobs.append(Job(ld0, (base, ad, side, 1), _loading(art, plan, l0px, units), uploads=uploads, done=done))
        if l1k is None:
            continue
        if need0 and not have0:
            jobs.append(Job(l0k, (base, ad, side, 2),
                            _pair(art, plan, l0px, l1px if not have1 else None, units, k, uploads, done, l1k),
                            uploads=uploads, done=done, lane=LANE_ART))
        elif not have1:
            jobs.append(Job(l1k, (base, ad, side, 3), _element(art, plan, l1px, l0px, units, k), uploads=uploads,
                            done=done, lane=LANE_ART))
    for i, texts in labels:
        key = label_key(texts, k)
        if key in resident:
            continue
        pr = _PRIO_FOCUS if i == focus else _PRIO_NEAR
        jobs.append(Job(key, (pr, abs(i - focus), 0, 0), _label(texts, k), uploads=uploads, done=done, opaque=False))
    return jobs


def _loading(art, plan, px, units):
    return lambda: art.loading(plan, px, units=units)


def _element(art, plan, px, need0, units, k):
    """An L1-only job (§7.7, §13.1): the rung for L1's own need (340 at k = 2: the 600 rung), the
    §13.5 decision on the item's largest need (L0's), WP8-R3."""
    return lambda: art.element(plan, px, units=units, need0=need0, k=k, src_need=px)


def _pair(art, plan, l0px, l1px, units, k, uploads, done, l1key):
    """L0 from the 1200 rung and, when missing, L1 from the same image (§13.4: reduce, 0.3 ms)."""
    def run():
        img = art.element(plan, l0px, units=units, need0=l0px, k=k)
        if img is not None and l1px:
            small = img.resize((l1px, l1px), RM.Image.Resampling.BOX) if l0px != 2 * l1px else img.reduce(2)
            art.note_size(l1key, l1px, l1px)
            uploads.put(l1key, l1px, l1px, RM.opaque_bgra(small), opaque=True, done=done, priority=0)
            art.c2_put((plan.key, "card", l1px), small)
        return img
    return run


def _label(texts, k):
    return lambda: RM.label_sprite(texts[0], texts[1], texts[2], k)


# --------------------------------------------------------------------------- statics (WP8-R10)
def _block_make(state, source, k):
    glyph, title, help_text = SM.state_block(state, source)
    return lambda: RM.state_block_sprite(glyph, title, help_text, k)


def _dots_make(dots, k):
    return lambda: RM.dots_sprite(dots, k)


def dots_variants(count):
    """Every dot-row sprite a list of ``count`` items can show (S5-9: one row up to 82 items;
    beyond, the three end-fade combinations)."""
    if not isinstance(count, int) or count <= 0:
        return []
    out = {}
    for i in (0, min(count - 1, SM.DOTS_HALF + 1), count - 1):
        d = SM.dots_window(count, i)
        out[d.key] = d
    return list(out.values())


def explorer_static_specs(lay, payload=None):
    """(key, make) of the explorer's statics at ``lay``'s k: the hints, the tabs, the card inset,
    every state block of both tabs, and the dot rows of the payload's count. Their CPU bytes are
    rendered at the open's t = 0 on the fast lane (``common.prepare_statics``)."""
    k = lay.k
    specs = [(static_key("hints", k), lambda: RM.hints_sprite(SM.EXPLORER_HINTS, k)[0])]
    for src in SM.SOURCES:
        specs.append((static_key(f"tab.{src}", k), lambda src=src: RM.tab_sprite(src, k)[0]))
        for st in SM.BLOCK_STATES:
            if SM.state_block(st, src) is not None:
                specs.append((static_key(f"block.{st}.{src}", k), _block_make(st, src, k)))
    cs = SM.card_size(lay)
    specs.append((static_key("card.inset", k), lambda: RM.frame_sprite(cs, max(1, round(k)), SM.INSET_ALPHA)))
    for d in dots_variants((payload or {}).get("count")):
        specs.append((static_key("dots", k, d.key), _dots_make(d, k)))
    return specs


# --------------------------------------------------------------------------- the scene
class ExplorerScene(SceneBase):
    surface = "explorer"

    def __init__(self, ctx, payload, art=None, prepared=None):
        super().__init__(ctx, payload, art, prepared)
        lay = ctx.layout
        self.lay = lay
        self.table = SM.explorer_table(lay.wide)
        self.a_max = self.table.a_max
        self.cs = SM.card_size(lay)
        self.l1px = SM.upx(lay, SM.L1_UNITS)
        self.rest_y = SM.card_rest_y(lay)
        self.rm = bool(ctx.reduced_motion)
        self.source = payload.get("source") if payload.get("source") in SM.SOURCES else "recent"
        self.state = payload.get("state") or "ready"
        self.count = payload.get("count")
        self.items = {}
        self.plans = {}
        self.texts = {}
        self.lkeys = {}                       # index -> its label's upload key (``texts`` hashed once)
        self.keys_cache = {}
        self._ok = {}                         # index -> (L0 verified, label verified): resident
        self._pins_dirty = True
        self.items_rev = None
        self._merge(payload)
        self.focus = self._clamp(int(payload.get("index") or 0))
        self.direction = 0
        self.play = False
        self.swap_until = None
        self.pending_index = None
        self.set_id = 1
        self.cards = []
        self.free = []
        self.bound = {}                       # (set, index) -> card
        self._z = []                          # bound cards in their stacking order, bottom to top (``_reorder``)
        self._gone = set()                    # current-set cards fading out past a smaller count (``_drop_gone``)
        self._gone_count = _UNSET             # the count ``_drop_gone`` last checked the cards against ...
        self._gone_set = None                 # ... in this card set
        self.key_cards = {}                   # upload key -> set(cards)
        self.label_front = 0
        self.label_shown = None
        self.label_pending = None             # (key, index, start tick or None)
        self.dots_front = 0
        self.dots_shown = None
        self._dots_at = None                  # ((count, focus), Dots) of the last detent (``_marker``)
        self.dots_pending = None              # (visual index, Dots) whose row sprite is on its way
        self.block_front = 0
        self.block_shown = None
        self.block_pending = None             # (anchor, delay_ms, fade, state, source) waiting for its sprite
        # the §7.2 slots, per a and side: (x, S, O, shade)
        self.slot_tab = [[None, None, None] for _ in range(self.a_max + 1)]
        for a in range(self.a_max + 1):
            for sg in (-1, 0, 1):
                s = SM.card_slot(lay, self.table, sg * a if a else 0)
                self.slot_tab[a][sg + 1] = (float(s.x), s.s, s.o, s.sh)
        self.stats = {"turn_calls": [], "turn_anims": []}

    # ------------------------------------------------------------------ data
    def _clamp(self, i):
        if isinstance(self.count, int) and self.count > 0:
            return max(0, min(self.count - 1, i))
        return max(0, i)

    def _merge(self, payload):
        """Descriptors of the preload window (K3 §11.1): replaced on a new ``items_rev``,
        merged while it is unchanged. Returns the indices whose descriptor changed (``ALL`` on
        a replace)."""
        items = payload.get("items")
        if items is None:
            return set()
        first = int(payload.get("items_first") or 0)
        rev = payload.get("items_rev")
        changed = set()
        if rev != self.items_rev:
            self.items, self.plans, self.texts, self.lkeys, self.items_rev = {}, {}, {}, {}, rev
            self._ok = {}
            changed = ALL
        known = self.items
        if changed is ALL:
            for j, desc in enumerate(items):
                if desc is not None:
                    known[first + j] = desc
        else:
            for j, desc in enumerate(items):
                i = first + j
                if desc is None or i in known:
                    continue                          # same items_rev: K3 re-sends the same descriptor
                known[i] = desc
                self.plans.pop(i, None)
                self.texts.pop(i, None)
                self.lkeys.pop(i, None)
                changed.add(i)
        if len(known) > 160:
            keep = {i for i in known if abs(i - first) <= 80}
            self.items = {i: v for i, v in known.items() if i in keep}
            self.plans = {i: v for i, v in self.plans.items() if i in keep}
            self.texts = {i: v for i, v in self.texts.items() if i in keep}
            self.lkeys = {i: v for i, v in self.lkeys.items() if i in keep}
        return changed

    def plan_of(self, i):
        if self.state == "loading":
            return None                                   # art.list_loading: neutral cards (S01:300)
        p = self.plans.get(i)
        if p is None and i in self.items:
            p = self.plans[i] = SM.explorer_plan(self.items[i], self.source)
        return p

    def has_cards(self, state=None) -> bool:
        return (state or self.state) not in SM.BLOCK_STATES

    def in_range(self, i) -> bool:
        """``i`` is an item of the list (below ``count`` when it is known)."""
        n = self.count if isinstance(self.count, int) else None
        return i is not None and i >= 0 and (n is None or i < n)

    def wanted_indices(self):
        if not self.has_cards():
            return []
        n = self.count if isinstance(self.count, int) else None
        if n == 0:
            return []
        lo = max(0, self.focus - self.a_max)
        hi = self.focus + self.a_max
        if n is not None:
            hi = min(hi, n - 1)
        return list(range(lo, hi + 1))

    def item_texts(self, i):
        t = self.texts.get(i)
        if t is None:
            t = self.texts[i] = SM.explorer_label(self.items.get(i), self.source)
        return t

    def label_key_of(self, i):
        """``label_key(item_texts(i), k)``, hashed once per descriptor (R-k)."""
        key = self.lkeys.get(i)
        if key is None:
            key = self.lkeys[i] = label_key(self.item_texts(i), self.k)
        return key

    # ------------------------------------------------------------------ build
    @classmethod
    def ambient_source(cls, payload, art=None):
        """The first ambient layer's source (§4.9): the focused item's 64 px copy, its GEN
        gradient, or ``art_bg``; None in a block state or while loading."""
        if payload.get("state") in SM.BLOCK_STATES or payload.get("state") == "loading":
            return None
        idx = int(payload.get("index") or 0) - int(payload.get("items_first") or 0)
        items = payload.get("items") or []
        if not (0 <= idx < len(items)):
            return None
        plan = SM.explorer_plan(items[idx], payload.get("source"))
        return ambient_source_of(plan, art)

    @classmethod
    def static_specs(cls, lay, payload=None):
        return explorer_static_specs(lay, payload)

    def build(self, payload, container):
        tree, lay, k = self.tree, self.lay, self.k
        self.container = container
        cs = self.cs
        # ambient (layers 2-3)
        self.ambient = AmbientPair(self, container, SM.AMBIENT_OPACITY["explorer"])
        plan0 = self.plan_of(self.focus) if self.has_cards() and self.state != "loading" else None
        self.ambient.first(getattr(self.ctx, "ambient_image", None), plan0.key if plan0 else "",
                           getattr(self, "first_ambient_src", None))
        # statics
        self.s_base = self.ctx.solids.get(SM.LIST_LOADING_RGB, cs, cs)
        self.s_shade = self.ctx.solids.get(SM.SHADE_RGB, cs, cs)
        self.s_inset = self.static("card.inset", lambda: RM.frame_sprite(cs, max(1, round(k)), SM.INSET_ALPHA))
        side_sp = shadow_sprite(cs, cs, SM.SHADOW_SIDE[1], SM.SHADOW_SIDE[2], SM.SHADOW_SIDE[0], k)
        focus_sp = shadow_sprite(cs, cs, SM.SHADOW_FOCUS[1], SM.SHADOW_FOCUS[2], SM.SHADOW_FOCUS[0], k)
        self.side_sp, self.focus_sp = side_sp, focus_sp
        self.s_side = self.static("card.shadow.side", lambda: _shadow(side_sp))
        self.s_focus = self.static("card.shadow.focus", lambda: _shadow(focus_sp))
        # tabs
        self._build_tabs(container)
        # cards
        self.cards_box = tree.container("cards", opacity=False)
        tree.add(container, self.cards_box)
        self.cards_x = tree.offset_x(self.cards_box, 0.0)
        pool = 2 * self.a_max + 1 + 12
        for _ in range(pool):
            self.free.append(self._new_card())
        # label (two), block (two), dots (two) + marker, hints
        lx, ly = int(round(SM.stage_x(lay, SM.LABEL_LEFT))), int(round(SM.stage_y(lay, SM.LABEL_TOP)))
        self.labels = [self.sprite_visual(container, f"label.{j}", None, lx, ly, opacity=0.0) for j in range(2)]
        bx, by = int(round(SM.stage_x(lay, SM.BLOCK_LEFT))), int(round(SM.stage_y(lay, SM.BLOCK_TOP)))
        self.blocks = [self.sprite_visual(container, f"block.{j}", None, bx, by, opacity=0.0) for j in range(2)]
        dy = int(round(SM.stage_y(lay, SM.DOTS_TOP)))
        self.dots = []
        for j in range(2):
            v = tree.visual(f"dots.{j}", opacity=True)
            tree.add(container, v)
            self.dots.append((v, tree.offset_x(v, 0.0), tree.offset_y(v, float(dy)), tree.opacity(v, 0.0)))
        mpx = SM.upx(lay, SM.DOT_UNITS)
        self.marker_v = tree.visual("marker", opacity=True, content=self.ctx.solids.get((255, 255, 255), mpx, mpx))
        tree.add(container, self.marker_v)
        self.marker_x = tree.offset_x(self.marker_v, 0.0)
        tree.offset_y(self.marker_v, float(dy))
        self.marker_o = tree.opacity(self.marker_v, 0.0)
        hs = self.static("hints", lambda: RM.hints_sprite(SM.EXPLORER_HINTS, k)[0])
        hw, _hh = self.static_size("hints")
        self.hints_v, _ = self.sprite_visual(container, "hints", hs, int(round(SM.stage_x(lay, 640) - hw / 2.0)),
                                             int(round(SM.stage_y(lay, SM.HINTS_TOP))))
        # the dot rows a detent can reach, resident before the first detent (WP8-R10)
        for d in dots_variants(self.count):
            self.static("dots", _dots_make(d, k), extra=d.key)
        self._prewarm_open()
        if self.art is not None:
            self.art.forget(("prefetch", "explorer"), running=False)      # its running fetches still serve C1

    def _prewarm_open(self):
        """S2 of the 2026-09-26 frame-drop fixes: the prepared sprites the open binds (the cards of the
        range, the focus's label) are uploaded here in build, before the engine opens the open's batch,
        not inside it: the batch's t1 is then taken after them (hidden-host probe: the explorer's open
        batch spent about 3 ms uploading them past its t1). ``open`` finds them resident; the same
        surfaces, bound in the same batch."""
        if not self.has_cards():
            self._block_surface(self.state, sync=True)                # the open shows the state's block
            return
        for i in self.wanted_indices():
            plan = self.plan_of(i)
            if plan is None:
                continue
            for key in self._keys_of(i, plan):
                if key is not None:
                    self.surface_for(key, sync=True)
        if self.state != "loading" and self.focus in self.items:
            self.surface_for(self.label_key_of(self.focus), sync=True)

    def _build_tabs(self, container):
        tree, lay, k = self.tree, self.lay, self.k
        sizes = {}
        surf = {}
        for src in SM.SOURCES:
            surf[src] = self.static(f"tab.{src}", lambda src=src: RM.tab_sprite(src, k)[0])
            sizes[src] = self.static_size(f"tab.{src}")
        lh = max(18 * k, RM.line_normal(17 * k))
        total = sizes["recent"][0] + 36 * k + sizes["favourites"][0]
        x = SM.stage_x(lay, 640) - total / 2.0
        top = SM.stage_y(lay, SM.TABS_TOP)
        self.tabs = {}
        for src in SM.SOURCES:
            w = sizes[src][0]
            box = tree.container(f"tab.{src}", overlap=False)
            tree.add(container, box)
            tree.offset(box, x, top)
            on = src == self.source
            op = tree.opacity(box, 1.0 if on else 0.55)
            sv = tree.visual(f"tab.{src}.sprite", content=surf[src])
            tree.add(box, sv)
            bar_w, bar_h = int(round(w)), max(1, int(round(2 * k)))
            bar = tree.visual(f"tab.{src}.bar", content=self.ctx.solids.get((255, 255, 255), bar_w, bar_h))
            tree.offset(bar, 0, round(lh + 10 * k))
            st = tree.scale_transform(bar, bar_w / 2.0, bar_h / 2.0)
            sx = tree.scale_x(st, bar_w, 1.0 if on else 0.0, name=f"tab.{src}.sx")
            tree.add(box, bar)
            self.tabs[src] = (op, sx)
            x += w + 36 * k

    def _new_card(self):
        tree, cs = self.tree, self.cs
        n = len(self.cards)
        c = _Card()
        c.n = n
        c.box = tree.container(f"card{n}", overlap=True)
        c.inner = tree.visual(f"card{n}.inner")
        sts = tree.scale_group(c.inner, ((cs / 2.0, cs / 2.0), (cs / 2.0, cs / 2.0)))
        c.side = tree.visual(f"card{n}.side", opacity=True, content=self.s_side)
        tree.matrix(c.side, self.side_sp.scale, self.side_sp.scale, self.side_sp.offset[0], self.side_sp.offset[1])
        c.focus = tree.visual(f"card{n}.focus", opacity=True, content=self.s_focus)
        tree.matrix(c.focus, self.focus_sp.scale, self.focus_sp.scale, self.focus_sp.offset[0], self.focus_sp.offset[1])
        c.base = tree.visual(f"card{n}.base", content=self.s_base)
        r = cs / float(self.l1px)
        c.load1 = tree.visual(f"card{n}.load1")
        tree.matrix(c.load1, r, r, 0, 0)
        c.load0 = tree.visual(f"card{n}.load0")
        c.art = tree.container(f"card{n}.art", overlap=True)
        c.l1 = tree.visual(f"card{n}.l1")
        tree.matrix(c.l1, r, r, 0, 0)
        c.l0 = tree.visual(f"card{n}.l0", opacity=True)
        tree.add(c.art, c.l1)
        tree.add(c.art, c.l0)
        c.inset = tree.visual(f"card{n}.inset", content=self.s_inset)
        c.shade = tree.visual(f"card{n}.shade", opacity=True, content=self.s_shade)
        for ch in (c.side, c.focus, c.base, c.load1, c.load0, c.art, c.inset, c.shade):
            tree.add(c.inner, ch)
        tree.add(c.box, c.inner)
        tree.add(self.cards_box, c.box, back=True)
        x, s, o, sh = self.slot_tab[self.a_max][2]
        c.x = tree.offset_x(c.box, x)
        c.y = tree.offset_y(c.box, float(self.rest_y))
        c.S = tree.scale(sts[0], cs, s, name=f"card{n}.S")
        c.e = tree.scale(sts[1], cs, 1.0, name=f"card{n}.e")
        c.o = tree.opacity(c.box, 0.0)
        c.side_o = tree.opacity(c.side, 1.0)
        c.focus_o = tree.opacity(c.focus, 0.0)
        c.ready_o = tree.opacity(c.art, 0.0)
        c.l0_o = tree.opacity(c.l0, 0.0)
        c.sh = tree.opacity(c.shade, sh)
        self.cards.append(c)
        return c

    # ------------------------------------------------------------------ binding
    def _index_key(self, c, add):
        for key in c.keys:
            if key is None:
                continue
            s = self.key_cards.get(key)
            if add:
                if s is None:
                    s = self.key_cards[key] = set()
                s.add(c)
            elif s is not None:
                s.discard(c)
                if not s:
                    del self.key_cards[key]

    def _bind(self, batch, c, i, *, sync=False):
        """Bind a pooled card to item ``i`` of the current set: contents from the LRU (with
        ``sync`` at build, prepared sprites are uploaded now)."""
        c.index, c.set, c.leaving = i, self.set_id, False
        c.plan = self.plan_of(i)
        c.keys = self._keys_of(i, c.plan) if c.plan is not None else (None, None, None, None)
        self._index_key(c, True)
        self.bound[(c.set, i)] = c
        self.counters["binds"] += 1
        ready = self._apply_contents(batch, c, sync=sync)
        return ready

    def _apply_contents(self, batch, c, *, sync=False):
        """Set the four content slots from the surfaces of ``c.keys``; returns (art ready,
        L0 ready)."""
        targets = (c.l1, c.l0, c.load1, c.load0)
        ready = ready0 = False
        for j in range(4):
            key = c.keys[j]
            s = self.surface_for(key, sync=sync) if key is not None else None
            if s != c.bound[j]:
                if batch is None:
                    self.content_now(targets[j], s)
                else:
                    self.set_content(batch, targets[j], s)
                c.bound[j] = s
            if s is not None and j < 2:
                ready = True
                ready0 = ready0 or j == 1
        return ready, ready0

    def _rebind(self, batch, c):
        """The card's descriptor changed (playlist meta, a page): new keys, contents in place."""
        plan = self.plan_of(c.index)
        if plan == c.plan:
            return
        self._index_key(c, False)
        c.plan = plan
        c.keys = self._keys_of(c.index, plan) if plan is not None else (None, None, None, None)
        self._index_key(c, True)
        ready, ready0 = self._apply_contents(batch, c)
        set_value(batch, c.ready_o, 1.0 if ready else 0.0)
        set_value(batch, c.l0_o, 1.0 if (ready0 and c.a is not None and c.a <= 1) else 0.0)

    def _unbind(self, c):
        self._index_key(c, False)
        self.bound.pop((c.set, c.index), None)
        if c.z:
            self._z.remove(c)
            c.z = False
        self._gone.discard(c)
        c.index, c.plan, c.keys, c.a, c.leaving = None, None, (None, None, None, None), None, False
        self.free.append(c)
        self.counters["recycled"] += 1

    def _take_card(self):
        if self.free:
            return self.free.pop()
        self.counters["grown"] += 1
        return self._new_card()

    def _recycle(self, t):
        """Cards out of range, past the count (fading out) or of an old set go back to the pool
        once their twins are at rest."""
        cur, focus, a_max, cards = self.set_id, self.focus, self.a_max, self.has_cards()
        gone = None
        for c in self.bound.values():
            if c.set == cur and not c.leaving and cards and -a_max <= c.index - focus <= a_max:
                continue
            if c.o.moving(t) or c.x.moving(t) or c.y.moving(t):
                continue
            if c.set == cur and c.o.value(t) > 0.0:
                continue
            if gone is None:
                gone = []
            gone.append(c)
        if gone:
            for c in gone:
                self._unbind(c)

    def _revive(self, wanted):
        """Cards of the current set fading out past a smaller count come back when the count grows
        again (the retarget or the entry brings their opacity back). Returns them."""
        out = []
        if not self._gone:
            return out                                  # nothing fades past a smaller count
        cur = self.set_id
        for i in wanted:
            c = self.bound.get((cur, i))
            if c is not None and c.leaving:
                c.leaving = False
                self._gone.discard(c)
                out.append(c)
        return out

    def _drop_gone(self, batch):
        """§7.2, §7.4 (WP8-R6): cards of the current set at or past a smaller ``count`` fade out
        (300 ms OUT; 200 under reduced motion) and are recycled once at rest."""
        if self.count == self._gone_count and self._gone_set == self.set_id:
            return                                      # cards are bound in range: only a new count drops any
        self._gone_count, self._gone_set = self.count, self.set_id
        for c in list(self.bound.values()):
            if c.set != self.set_id or c.leaving or self.in_range(c.index):
                continue
            c.leaving = True
            self._gone.add(c)
            batch.to(c.o, 0.0, SM.REDUCED_OPACITY_MS if self.rm else SM.TURN_OPACITY_MS, "OUT")

    def _in_swap(self, t) -> bool:
        """Inside a source switch's or a state change's 190 ms (the new set has not entered)."""
        return not self.play and self.swap_until is not None and t < self.swap_until

    def _slot(self, d):
        a = min(abs(d), self.a_max)
        return a, self.slot_tab[a][SM.sign(d) + 1]

    def _place_hidden(self, batch, c, d, *, rise=False):
        """Jump a freshly bound card to its slot (``rise``: the enter pose, +30·S and x 0.9) at
        opacity 0."""
        a, (x, s, o, sh) = self._slot(d)
        sv = set_value                                  # R-k: a property already there costs no call
        sv(batch, c.x, x)
        sv(batch, c.S, s)
        sv(batch, c.o, 0.0)
        sv(batch, c.sh, sh)
        sv(batch, c.y, self.rest_y + (SM.card_rise_px(self.lay, s) if rise and not self.rm else 0.0))
        sv(batch, c.e, SM.ENTER_SCALE if rise and not self.rm else 1.0)
        sv(batch, c.side_o, 0.0 if a == 0 else 1.0)
        sv(batch, c.focus_o, 1.0 if a == 0 else 0.0)
        ready, ready0 = (c.bound[0] is not None or c.bound[1] is not None), c.bound[1] is not None
        sv(batch, c.ready_o, 1.0 if ready else 0.0)
        sv(batch, c.l0_o, 1.0 if (a <= 1 and ready0) else 0.0)
        c.a = a

    # ------------------------------------------------------------------ open
    def open(self, batch, payload):
        """§7.6 Open: rise +30·S -> 0 and e 0.9 -> 1 over 440 OUT, opacity 0 -> table over 320 OUT,
        each delayed 45 ms × a; reduced motion: opacity only, 200 ms OUT (§16). Tabs, label, dots,
        hints or the state block show with the root fade."""
        for i in self.wanted_indices():
            c = self._take_card()
            self._bind(batch, c, i, sync=True)
            self._place_hidden(batch, c, i - self.focus, rise=True)
            self._enter(batch, c, None, 0.0)
        self._reorder(batch)
        if self.has_cards():
            self._show_label(batch, self.focus, anchor=None, delay=0.0, sync=True, fade=False)
            self._show_dots(batch, None, 0.0, instant_front=True, sync=True)
            c = self.bound.get((self.set_id, self.focus))
            if c is not None and (c.bound[0] is not None or c.bound[1] is not None) and self.state != "loading":
                self.ambient.refresh_if_first_stale(c.plan, self.ctx.clock.to_perf(self.ctx.clock.now()))
        else:
            self._show_block(batch, None, 0.0, fade=False, sync=True)
        self._after_change(batch, focus_changed=True)

    def _enter(self, batch, c, anchor, delay_ms):
        """The open / source-switch entry of one card (stagger 45 ms × a from ``delay_ms``)."""
        a, (x, s, o, sh) = self._slot(c.index - self.focus)
        if self.rm:
            batch.jump(c.y, float(self.rest_y))
            batch.jump(c.e, 1.0)
            batch.to(c.o, o, SM.REDUCED_OPACITY_MS, "OUT", v_from=0.0, force=True, anchor=anchor, delay_ms=delay_ms)
            return
        d = delay_ms + SM.STAGGER_MS * a
        batch.to(c.y, float(self.rest_y), SM.ENTER_MS, "OUT", anchor=anchor, delay_ms=d)
        batch.to(c.e, 1.0, SM.ENTER_MS, "OUT", anchor=anchor, delay_ms=d)
        batch.to(c.o, o, SM.ENTER_OPACITY_MS, "OUT", anchor=anchor, delay_ms=d, v_from=0.0, force=True)

    def _exit(self, batch, c, anchor):
        """A source switch / state change exit (170 ms IN): rise 0 -> +30·S, scale -> 0.9·S,
        opacity -> 0; reduced motion: the opacity only, 200 ms OUT."""
        c.leaving = True
        if self.rm:
            batch.to(c.o, 0.0, SM.REDUCED_OPACITY_MS, "OUT", anchor=anchor)
            return
        s = c.S.target
        batch.to(c.y, self.rest_y + SM.card_rise_px(self.lay, s), SM.EXIT_MS, "IN", anchor=anchor)
        batch.to(c.e, SM.ENTER_SCALE, SM.EXIT_MS, "IN", anchor=anchor)
        batch.to(c.o, 0.0, SM.EXIT_MS, "IN", anchor=anchor)

    # ------------------------------------------------------------------ turns
    def turn(self, batch, focus, changed=()):
        """A detent (§7.6 Turn): every bound card of the current set retargets X, S (420 OUT),
        opacity (300 OUT), shade (320 OUT), the shadow crossfade (320) and the L0 level (420);
        cards entering the range are bound at the a_max slot; the marker translates (420 OUT);
        the label swaps at once (S5-24); the z-order changes at the detent (§4.4).

        R-k: the cards' legs are collected and programmed in one ``program_legs`` loop (the
        builder's arithmetic, one pass), properties already where they belong cost no call."""
        focus = self._clamp(int(focus))
        if focus == self.focus or self.play or not self.has_cards():
            return 0
        n0, a0 = batch.calls, batch.anims
        t1 = batch.t1
        self.direction = SM.sign(focus - self.focus)
        self.focus = focus
        wanted = self.wanted_indices()
        cur = self.set_id
        bound = self.bound
        self._revive(wanted)
        if changed:
            for c in list(bound.values()):
                if c.set == cur and not c.leaving and c.index in changed:
                    self._rebind(batch, c)
        self._drop_gone(batch)
        for i in wanted:
            if (cur, i) not in bound:
                c = self._take_card()
                self._bind(batch, c, i)
                side = SM.sign(i - focus) or self.direction
                self._place_hidden(batch, c, side * (self.a_max + 1))
        rm = self.rm
        legs = []
        retarget = self._retarget
        slot_tab, a_max = self.slot_tab, self.a_max
        for c in bound.values():
            if c.set != cur or c.leaving:
                continue
            d = c.index - focus
            a = d if d >= 0 else -d
            if a >= a_max and c.a == a_max:               # beyond the range: the a_max slot, usually reached
                x, s, o, sh = slot_tab[a_max][(d > 0) - (d < 0) + 1]
                if c.x.func.target == x and c.S.func.target == s and c.o.func.target == o and c.sh.func.target == sh:
                    continue
            retarget(batch, c, t1, rm, legs)
        self._marker(batch, jump=rm, legs=legs)
        program_legs(batch, legs)
        self._recycle(t1)
        self._reorder(batch)
        self._show_label(batch, focus, anchor=None, delay=0.0)
        self._after_change(batch, focus_changed=True)
        self.stats["turn_calls"].append(batch.calls - n0)
        self.stats["turn_anims"].append(batch.anims - a0)
        return batch.calls - n0

    def _retarget(self, batch, c, t1, rm, legs=None):
        """One card to its slot: X, S (420), opacity (300), shade (320) on the OUT curve, the
        shadow crossfade (320) when it enters or leaves the centre, L0 (420) across |d| = 1 <-> 2.
        With ``legs`` the curves are appended as ``(prop, target, ms)`` for the caller's
        ``program_legs`` (the property reads here all happen before any is programmed, as each
        card only reads its own); without, they are programmed now."""
        d = c.index - self.focus
        a = d if d >= 0 else -d
        if a > self.a_max:
            a = self.a_max
        x, s, o, sh = self.slot_tab[a][(d > 0) - (d < 0) + 1]
        fo = c.o.func
        if a == c.a and c.x.func.target == x and c.S.func.target == s and fo.target == o and c.sh.func.target == sh:
            return                                              # at (or heading to) its slot: no call (G1-4)
        out = [] if legs is None else legs
        if rm or (o <= 0.0 and fo.target <= 0.0 and fo.value(t1) <= 0.0):
            set_value(batch, c.x, x)                            # invisible before and after: jump (G1-4)
            set_value(batch, c.S, s)
            if rm:
                out.append((c.o, o, SM.REDUCED_OPACITY_MS))
                out.append((c.sh, sh, SM.SHADE_MS))
            else:
                set_value(batch, c.o, o)
                set_value(batch, c.sh, sh)
        else:
            out.append((c.x, x, SM.TURN_MS))
            out.append((c.S, s, SM.TURN_MS))
            out.append((c.o, o, SM.TURN_OPACITY_MS))
            out.append((c.sh, sh, SM.SHADE_MS))
        if (c.a == 0) != (a == 0):
            out.append((c.side_o, 0.0 if a == 0 else 1.0, SM.SHADOW_MS))
            out.append((c.focus_o, 1.0 if a == 0 else 0.0, SM.SHADOW_MS))
        want0 = 1.0 if (a <= 1 and c.bound[1] is not None) else 0.0
        if c.l0_o.func.target != want0:
            out.append((c.l0_o, want0, SM.REDUCED_OPACITY_MS if rm else SM.L0_MS))
        c.a = a
        if legs is None:
            program_legs(batch, out)

    def _reorder(self, batch):
        """z = 20 − a (BS:1183), with the cards of one side kept in index order: bottom to top, an
        old set, the cards left of the focus by ascending index, the cards right of it by
        descending index, the focus. Every pair of neighbours stacks as z = 20 − a does (cards of
        equal a sit on opposite sides and never overlap). Free cards are invisible and stay where
        they are; only bound cards out of order move (a longest increasing subsequence stays),
        so a detent costs one or two moves (G1-4).

        ``_z`` keeps the bound cards in their stacking order (R-k: no scan of the container's
        children per detent); a card bound since the last reorder is first placed into it by
        its position among the children (``_adopt``), so the moves are the same as a full scan's."""
        cur, f = self.set_id, self.focus
        old, left, right, top = [], [], [], []
        for c in self.bound.values():
            if c.set != cur:
                old.append(c)
            elif c.index < f:
                left.append(c)
            elif c.index > f:
                right.append(c)
            else:
                top.append(c)
        left.sort(key=_by_index)
        right.sort(key=_by_index, reverse=True)
        want = old + left + right + top
        z = self._z
        if len(z) != len(want):
            self._adopt(want)
            z = self._z
        if z == want:
            return
        pos = {c: j for j, c in enumerate(want)}
        cur_seq = [pos[c] for c in z]
        keep = {cur_seq[j] for j in _lis_indices(cur_seq)}
        tree = self.tree
        before = tree.calls
        box = self.cards_box
        for j, c in enumerate(want):
            if j in keep:
                continue
            tree.remove(box, c.box)
            if j == 0:
                tree.add(box, c.box, back=True)
            else:
                tree.add(box, c.box, above=want[j - 1].box)
            keep.add(j)
        self._z = want
        if batch is not None:
            batch.calls += tree.calls - before

    def _adopt(self, cards):
        """Place the cards of ``cards`` not yet in ``_z`` at their position among the container's
        children (a bisection over ``_z``, which is in the children's order)."""
        idx = self.cards_box.children.index
        z = self._z
        for c in cards:
            if c.z:
                continue
            p = idx(c.box)
            lo, hi = 0, len(z)
            while lo < hi:
                mid = (lo + hi) >> 1
                if idx(z[mid].box) < p:
                    lo = mid + 1
                else:
                    hi = mid
            z.insert(lo, c)
            c.z = True

    # ------------------------------------------------------------------ label, dots, block
    def _show_label(self, batch, i, *, anchor, delay, sync=False, fade=True):
        """The label of item ``i``: swap now if its sprite exists (else keep the previous one and
        swap on landing, S5-24); then opacity 0 -> 1 over 160 OUT (from ``anchor`` + ``delay``)."""
        if not self.has_cards() or self.state == "loading" or i not in self.items:
            return
        key = self.label_key_of(i)
        start = None if anchor is None else anchor + int(round(delay * self.ctx.clock.freq / 1000.0))
        if key == self.label_shown and start is None:
            self.label_pending = None
            return
        s = self.surface_for(key, sync=sync)
        if s is None:
            self.label_pending = (key, i, start)
            return
        self.label_pending = None
        v, op = self.labels[self.label_front]
        self.set_content(batch, v, s)
        if not fade:
            batch.jump(op, 1.0)
        elif start is None:
            batch.to(op, 1.0, SM.LABEL_FADE_MS, "OUT", v_from=0.0, force=True)
        else:
            batch.to(op, 1.0, SM.LABEL_FADE_MS, "OUT", v_from=0.0, force=True, anchor=start)
        self.label_shown = key

    def _hide_label(self, batch, anchor):
        v, op = self.labels[self.label_front]
        batch.to(op, 0.0, SM.LABEL_FADE_MS, "OUT", anchor=anchor)
        self.label_front = 1 - self.label_front
        self.label_shown = None
        self.label_pending = None

    def _dots_visible(self) -> bool:
        return self.has_cards() and self.state != "loading" and isinstance(self.count, int) and self.count > 0

    def _dots_surface(self, dots, sync=False):
        """The row sprite of ``dots``: resident, or (``sync``: build and open only) made now;
        on the input path a miss goes through the upload queue (WP8-R10) and returns None."""
        return self.static("dots", _dots_make(dots, self.k), extra=dots.key, sync=sync)

    def _dots_content(self, batch, j, dots, sync=False) -> bool:
        """Put the row of ``dots`` on dot visual ``j`` (content and x); False while its sprite
        is on its way (``dots_pending``: set when it lands)."""
        s = self._dots_surface(dots, sync)
        if s is None:
            self.dots_pending = (j, dots)
            return False
        v, xp, _yp, _op = self.dots[j]
        self.set_content(batch, v, s)
        batch.jump(xp, float(int(round(SM.stage_x(self.lay, SM.dots_left_units(dots.count))))))
        if self.dots_pending is not None and self.dots_pending[0] == j:
            self.dots_pending = None
        return True

    def _show_dots(self, batch, anchor, delay_ms, *, instant_front=False, sync=False):
        """The dot row and marker for the current count and focus: the new row on the back visual,
        swapped in at ``anchor`` + ``delay_ms`` (instant, S5-10), or now."""
        show = self._dots_visible()
        dots = SM.dots_window(self.count if show else 0, self.focus)
        if instant_front:
            j = self.dots_front
        else:
            j = 1 - self.dots_front
        v, xp, _yp, op = self.dots[j]
        ov, oxp, _oyp, oop = self.dots[1 - j]
        self.dots_pending = None
        if show:
            self._dots_content(batch, j, dots, sync)
        if instant_front:
            batch.jump(op, 1.0 if show else 0.0)
            batch.jump(self.marker_o, 1.0 if show else 0.0)
            if show:
                batch.jump(self.marker_x, float(SM.marker_x(self.lay, dots)))
        else:
            batch.jump(op, 1.0 if show else 0.0, anchor=anchor, delay_ms=delay_ms)
            batch.jump(oop, 0.0, anchor=anchor, delay_ms=delay_ms)
            batch.jump(self.marker_o, 1.0 if show else 0.0, anchor=anchor, delay_ms=delay_ms)
            if show:
                batch.jump(self.marker_x, float(SM.marker_x(self.lay, dots)), anchor=anchor, delay_ms=delay_ms)
            self.dots_front = j
        self.dots_shown = dots.key if show else None

    def _dots_in_swap(self, batch):
        """A count or focus change inside a switch's 190 ms: the entering row (the front dot
        visual, hidden until ``swap_until``) and the marker's +190 position follow it (WP8-R5)."""
        show = self._dots_visible()
        dots = SM.dots_window(self.count if show else 0, self.focus)
        j = self.dots_front
        v, xp, _yp, op = self.dots[j]
        anchor = self.swap_until
        self.dots_pending = None
        if show:
            self._dots_content(batch, j, dots)
            batch.jump(self.marker_x, float(SM.marker_x(self.lay, dots)), anchor=anchor)
        batch.jump(op, 1.0 if show else 0.0, anchor=anchor)
        batch.jump(self.marker_o, 1.0 if show else 0.0, anchor=anchor)
        self.dots_shown = dots.key if show else None

    def _dots_landed(self, batch):
        p = self.dots_pending
        if p is None:
            return
        j, dots = p
        if dots.key != self.dots_shown:
            self.dots_pending = None                    # superseded
            return
        if self._dots_content(batch, j, dots) and j == self.dots_front and not self._in_swap(batch.t1):
            batch.jump(self.dots[j][3], 1.0)

    def _marker(self, batch, jump=False, legs=None):
        """At a detent: the row sprite swaps when its window's key changes (instant); the marker
        translates to the focused dot (420 OUT, no width animation). A row that became hidden (no
        items) hides with its marker; one that became visible shows with it. With ``legs`` the
        translation is appended for the caller's ``program_legs`` (R-k)."""
        if not self._dots_visible():
            if self.dots_shown is not None:
                batch.jump(self.dots[self.dots_front][3], 0.0)
                batch.jump(self.marker_o, 0.0)
                self.dots_shown = None
                self.dots_pending = None
            return
        at = (self.count, self.focus)
        cached = self._dots_at
        if cached is not None and cached[0] == at:
            dots = cached[1]
        else:
            dots = SM.dots_window(self.count, self.focus)
            self._dots_at = (at, dots)
        if self.dots_shown is None:
            self._show_dots(batch, None, 0.0, instant_front=True)
            return
        if dots.key != self.dots_shown:
            j = self.dots_front
            if self._dots_content(batch, j, dots):
                batch.jump(self.dots[j][3], 1.0)
            self.dots_shown = dots.key
        x = float(SM.marker_x(self.lay, dots))
        if jump:
            batch.jump(self.marker_x, x)
        elif legs is not None:
            legs.append((self.marker_x, x, SM.MARKER_MS))
        else:
            batch.to(self.marker_x, x, SM.MARKER_MS, "OUT")

    def _block_surface(self, state, sync=False):
        if SM.state_block(state, self.source) is None:
            return None
        return self.static(f"block.{state}.{self.source}", _block_make(state, self.source, self.k), sync=sync)

    def _show_block(self, batch, anchor, delay_ms, *, fade=True, sync=False):
        """The state's block (§7.4, S5-33): at ``anchor`` + ``delay_ms`` (fade 160 OUT) or now. A
        block sprite that is not resident on the input path is posted to the upload queue and
        shown, on the same anchor, when it lands (WP8-R10)."""
        if SM.state_block(self.state, self.source) is None:
            return
        s = self._block_surface(self.state, sync)
        if s is None:
            self.block_pending = (anchor, delay_ms, fade, self.state, self.source)
            return
        self.block_pending = None
        j = self.block_front if not fade else 1 - self.block_front
        v, op = self.blocks[j]
        self.set_content(batch, v, s)
        if fade:
            batch.to(op, 1.0, SM.BLOCK_FADE_MS, "OUT", v_from=0.0, force=True, anchor=anchor, delay_ms=delay_ms)
        else:
            batch.jump(op, 1.0)
        self.block_front = j
        self.block_shown = (self.state, self.source)

    def _hide_block(self, batch, anchor):
        self.block_pending = None
        if self.block_shown is None:
            return
        v, op = self.blocks[self.block_front]
        batch.to(op, 0.0, SM.BLOCK_FADE_MS, "OUT", anchor=anchor)
        self.block_front = 1 - self.block_front
        self.block_shown = None

    def _static_landed(self, batch, key):
        """A static posted from the input path landed: show what waited for it."""
        name = key[1] if len(key) > 1 else ""
        if name == "dots":
            self._dots_landed(batch)
        elif isinstance(name, str) and name.startswith("block."):
            p = self.block_pending
            if p is not None and p[3] == self.state and p[4] == self.source:
                self._show_block(batch, p[0], p[1], fade=p[2])

    # ------------------------------------------------------------------ updates
    def update(self, batch, call, payload):
        if call == "explorer_source":
            return self._switch(batch, payload)
        if call != "explorer_highlight" or self.play:
            return
        t = batch.t1
        changed = self._merge(payload)
        if "count" in payload:
            if payload.get("count") != self.count:
                changed = ALL if changed is ALL else (changed | {-1})
            self.count = payload.get("count")
        new_state = payload.get("state", self.state) if "state" in payload else self.state
        if new_state != self.state:
            self._state_change(batch, new_state, t)
            changed = set()
        index = payload.get("index")
        if index is not None and self.swapping(t):
            self.pending_index = int(index)             # §7.6: the turn is recorded, not shown ...
            if changed:
                self._data(batch, changed)              # ... but the data applies now (WP8-R5)
            return
        if index is not None and self._clamp(int(index)) != self.focus:
            self.turn(batch, int(index), changed)
        elif changed:
            self._data(batch, changed)
        bump = int(payload.get("bump") or 0)
        if bump and not self.rm and self.has_cards():
            k = self.k
            batch.legs(self.cards_x, [(0, -SM.BUMP_UNITS * k * bump, SM.BUMP_LEG_MS, "OUT"),
                                      (SM.BUMP_LEG_MS, 0.0, SM.BUMP_LEG_MS, "OUT")], v_from=0.0)

    def position(self, batch, index):
        if not self.play and not self.swapping(batch.t1):
            self.turn(batch, index)

    def _data(self, batch, changed=ALL):
        """Descriptors changed with the index unchanged (a page, playlist meta, a count): rebind
        the changed cards in place, fade out the cards past a smaller count (WP8-R6), bind new
        in-range items, redraw the dots and the label. Inside a switch's or a state change's
        190 ms the same applies to the entering set: a new card joins the entry (+190 and its
        stagger) and the new label and dots keep their +190 swap (§7.6; WP8-R5)."""
        t = batch.t1
        cur = self.set_id
        swap = self._in_swap(t)
        wanted = self.wanted_indices()
        revived = self._revive(wanted)
        for c in list(self.bound.values()):
            if c.set == cur and not c.leaving and c.index in changed:
                self._rebind(batch, c)
        self._drop_gone(batch)
        for i in wanted:
            if (cur, i) not in self.bound:
                c = self._take_card()
                self._bind(batch, c, i)
                if swap:
                    self._place_hidden(batch, c, i - self.focus, rise=True)
                    self._enter(batch, c, self.swap_until, 0.0)
                    continue
                a, (x, s, o, sh) = self._slot(i - self.focus)
                self._place_hidden(batch, c, i - self.focus)
                batch.to(c.o, o, SM.REDUCED_OPACITY_MS if self.rm else SM.TURN_OPACITY_MS, "OUT", v_from=0.0,
                         force=True)
        for c in revived:
            if swap:
                self._enter(batch, c, self.swap_until, 0.0)
            else:
                self._retarget(batch, c, t, self.rm)
        self._recycle(t)
        self._reorder(batch)
        if swap:
            self._dots_in_swap(batch)
            self._show_label(batch, self.focus, anchor=self.swap_until, delay=0.0)
        else:
            self._marker(batch, jump=True)
            self._show_label(batch, self.focus, anchor=None, delay=0.0)
        self._after_change(batch, focus_changed=False)

    def _state_change(self, batch, new_state, t):
        """§7.6 / S5-33: into a block (the cards exit 170 IN, the block fades in at +190), out of a
        block (the block fades out 160, the cards enter with the stagger at +190), block to block
        (fade out, fade in at +190), loading <-> ready (a data update: no exit, no entry)."""
        old_state = self.state
        was_cards, now_cards = self.has_cards(old_state), self.has_cards(new_state)
        self.state = new_state
        self.focus = self._clamp(self.focus)
        if was_cards and now_cards:
            self._data(batch)                           # the dots show (or hide) with it (``_marker``)
            return
        self.swap_until = t + int(round(SM.SWITCH_ENTRY_MS * self.ctx.clock.freq / 1000.0))
        if was_cards:
            for c in list(self.bound.values()):
                if c.set == self.set_id:
                    self._exit(batch, c, t)
            self.set_id += 1
            if self.label_shown is not None:
                self._hide_label(batch, t)
        else:
            self._hide_block(batch, t)
        if now_cards:
            self._enter_set(batch, t)
        else:
            self._show_block(batch, t, SM.SWITCH_ENTRY_MS)
            self._show_dots(batch, t, SM.SWITCH_ENTRY_MS)
        self.tick_job("swap_end", self.ctx.clock.to_perf(self.swap_until))
        self._after_change(batch, focus_changed=True)

    def _enter_set(self, batch, t0):
        """The new set at +190 ms with the open stagger, its label and dots at +190 (§7.6)."""
        for i in self.wanted_indices():
            c = self._take_card()
            self._bind(batch, c, i)
            self._place_hidden(batch, c, i - self.focus, rise=True)
            self._enter(batch, c, t0, SM.SWITCH_ENTRY_MS)
        self._reorder(batch)
        self._show_label(batch, self.focus, anchor=t0, delay=SM.SWITCH_ENTRY_MS)
        self._show_dots(batch, t0, SM.SWITCH_ENTRY_MS)

    def _switch(self, batch, payload):
        """§7.6 Source switch (Button 2/3) at K3's ``t0``: the tabs (240 / 320 OUT) and the old
        cards' exit (170 IN) at the press; the old label and block fade (160 OUT); the new source
        enters at ``t0`` + 190 at the ``index`` K3 sent, with the stagger; dots and marker are
        replaced at +190 with no slide (S5-10)."""
        if self.play:
            return
        t0 = self.ctx.t0_ticks(payload)
        src = payload.get("source") if payload.get("source") in SM.SOURCES else self.source
        rm = self.rm
        for s, (op, sx) in self.tabs.items():
            on = s == src
            batch.to(op, 1.0 if on else 0.55, SM.TAB_LABEL_MS, "OUT", anchor=t0)
            if rm:
                batch.jump(sx, 1.0 if on else 0.0)
            else:
                batch.to(sx, 1.0 if on else 0.0, SM.TAB_UNDERLINE_MS, "OUT", anchor=t0)
        if self.has_cards():
            for c in list(self.bound.values()):
                if c.set == self.set_id:
                    self._exit(batch, c, t0)
        if self.label_shown is not None or self.label_pending is not None:
            self._hide_label(batch, t0)
        self._hide_block(batch, t0)
        self.set_id += 1
        self.source = src
        self.state = payload.get("state") or "ready"
        self.count = payload.get("count")
        self.items_rev = object()                     # force a replace
        self._merge(payload)
        self.focus = self._clamp(int(payload.get("index") or 0))
        self.direction = 0
        self.dots_shown = None
        self.swap_until = t0 + int(round(SM.SWITCH_ENTRY_MS * self.ctx.clock.freq / 1000.0))
        self.pending_index = None
        if self.has_cards():
            self._enter_set(batch, t0)
        else:
            self._show_block(batch, t0, SM.SWITCH_ENTRY_MS)
            self._show_dots(batch, t0, SM.SWITCH_ENTRY_MS)
        self.tick_job("swap_end", self.ctx.clock.to_perf(self.swap_until))
        self._after_change(batch, focus_changed=True)

    # ------------------------------------------------------------------ Play and close
    def close(self, batch, payload):
        """Play (§7.6): the centre card grows 1 -> 1.12 over 380 OUT, the others fade over 300 OUT
        (reduced motion: no grow, 200 ms), anchored to ``t0``; the engine fades the root at
        ``t0`` + 380. The labels, tabs and dots stay (BS:1040-1045)."""
        self.play = True
        t0 = self.ctx.t0_ticks(payload)
        for c in list(self.bound.values()):
            if c.set != self.set_id or c.leaving:
                continue
            if c.index == self.focus:
                if not self.rm:
                    batch.to(c.e, SM.PLAY_GROW, SM.PLAY_GROW_MS, "OUT", anchor=t0)
            else:
                batch.to(c.o, 0.0, SM.REDUCED_OPACITY_MS if self.rm else SM.PLAY_OTHERS_MS, "OUT", anchor=t0)

    def hit_rect(self):
        if self.play or not self.has_cards() or self.state == "loading" or not self.count:
            return None
        return SM.card_hit_rect(self.lay)

    def swapping(self, now_tick) -> bool:
        return self.play or (self.swap_until is not None and now_tick < self.swap_until)

    # ------------------------------------------------------------------ uploads
    def uploads_ready(self, batch, keys):
        """Content that became ready: an art level fades in over the loading tile (240 OUT; a late
        L0 over L1 at |d| <= 1), a waiting label swaps (160), the ambient crossfades (600), a tick
        applies a turn recorded during a swap."""
        focus_art = False
        touched = {}
        for key in keys:
            self.counters["landed"] += 1
            if self.ambient.landed(batch, key):
                continue
            kind = key[0] if isinstance(key, tuple) else None
            if kind == "tick":
                tag = getattr(self, "tick_tags", {}).pop(key, None)
                if tag == "swap_end" and self.pending_index is not None and not self.swapping(batch.t1):
                    idx, self.pending_index = self.pending_index, None
                    self.turn(batch, idx)
                continue
            if kind == "label":
                p = self.label_pending
                if p is not None and p[0] == key:
                    self._show_label(batch, p[1], anchor=p[2], delay=0.0)
                continue
            if kind == "static":
                self._static_landed(batch, key)
                continue
            for c in self.key_cards.get(key, ()):
                if c not in touched:
                    touched[c] = (c.bound[0] is not None or c.bound[1] is not None, c.bound[1] is not None)
        for c, (ready_before, ready0_before) in touched.items():
            if c.index is None:
                continue
            ready, ready0 = self._apply_contents(batch, c)
            if ready and not ready_before and c.ready_o.target < 1.0:
                batch.to(c.ready_o, 1.0, SM.ART_READY_MS, "OUT", v_from=0.0, force=True)
            if ready0 and not ready0_before and c.a is not None and c.a <= 1 and c.l0_o.target < 1.0:
                if ready_before:
                    batch.to(c.l0_o, 1.0, SM.ART_READY_MS, "OUT")
                else:
                    batch.jump(c.l0_o, 1.0)
            if ready and not ready_before and c.index == self.focus and c.set == self.set_id:
                focus_art = True
        if focus_art:
            self.ambient.want = None                    # re-request: the thumbnail exists now
            self._request_ambient()
        self._pin()

    # ------------------------------------------------------------------ art, ambient, pins
    def _after_change(self, batch, *, focus_changed):
        if focus_changed:
            self._request_ambient()
        self._plan_art()
        self._pins_dirty = True

    def _request_ambient(self):
        plan = None
        if self.has_cards() and self.state != "loading":
            plan = self.plan_of(self.focus)
        now_s = self.ctx.clock.to_perf(self.ctx.clock.now())
        self.ambient.request(plan, now_s)

    def _plan_art(self):
        """Hand the art workers a snapshot of the preload window, only when something in it is
        not resident (a warm cache plans nothing, so no worker competes for the GIL, G1-5).
        Indices already verified resident (``_ok``: with their L0 and label needs) are not
        re-checked, so a warm detent costs a few dict lookups. ``resident`` in the snapshot is the
        LRU view itself: a worker's membership test is one dict lookup."""
        if self.art is None or not self.has_cards() or self.state == "loading":
            return
        n = self.count if isinstance(self.count, int) else None
        focus = self.focus
        lo, hi = SM.preload_window(focus, n, self.lay.wide, self.direction)
        if n is None:
            hi = min(hi, max(self.items) if self.items else lo - 1)
        l0set = SM.l0_indices(focus, n, self.direction)
        l0s = set(l0set)
        lru, ok, items = self.lru, self._ok, self.items
        loading = self.state == "loading"
        need = False
        ok_get = ok.get
        lab_lo, lab_hi = (focus - LABEL_PREFETCH, focus + LABEL_PREFETCH) if not loading else (1, 0)
        for i in range(lo, hi + 1):
            got = ok_get(i)
            if got is not None and (got[0] or i not in l0s) and (got[1] or i < lab_lo or i > lab_hi):
                continue                                  # verified resident with what it needs now
            if i not in items:
                continue
            want0 = i in l0s
            wantl = not loading and abs(i - focus) <= LABEL_PREFETCH
            plan = self.plan_of(i)
            if plan is None:
                continue
            keys = self._keys_of(i, plan)
            have1 = keys[0] is not None and keys[0] in lru
            have0 = have1 and (not want0 or keys[1] in lru)
            havel = not wantl or self.label_key_of(i) in lru
            if have1 and have0 and havel:
                ok[i] = (want0, wantl)
            else:
                ok.pop(i, None)
                need = True
        if not need:
            return
        order = SM.build_order(focus, lo, hi, self.direction)
        plans = {i: self.plan_of(i) for i in order if i in items}
        labels = [(i, self.item_texts(i)) for i in range(focus - LABEL_PREFETCH, focus + LABEL_PREFETCH + 1)
                  if i in items] if not loading else []
        snap = (focus, self.direction, order, plans, frozenset(l0set), labels, lru, (self.l1px, self.cs, self.k),
                (self.uploads, self.done), SM.CARD_UNITS)
        self.art.plan(self.owner, explorer_planner, snap)

    def _keys_of(self, i, plan):
        k = self.keys_cache.get(i)
        if k is None or k[0] is not plan:
            k = self.keys_cache[i] = (plan, card_keys(plan, self.l1px, self.cs))
        return k[1]

    def _pin(self):
        """Pin what is bound, the label(s) and the ambient layers. Pins matter only when an
        upload lands (an eviction happens on ``put``), so detents only mark them dirty and
        ``done`` / ``uploads_ready`` refresh them first."""
        self._pins_dirty = False
        keys = set(self.key_cards)
        if self.label_shown is not None:
            keys.add(self.label_shown)
        if self.label_pending is not None:
            keys.add(self.label_pending[0])
        keys.update(self.ambient.keys())
        self.repin(keys)

    def done(self, surface, key):
        if self._pins_dirty and not self.closed:
            self._pin()
        super().done(surface, key)


def _shadow(sp):
    """A ``surfaces.box_shadow`` image (straight RGBA of black) as a premultiplied sprite."""
    return RM.Sprite.from_rgba(sp.image)                  # black: premultiplied colour stays 0


def ambient_source_of(plan, art=None):
    """The ambient's first source (§12): a cached 64 px copy, the GEN gradient, or ``art_bg``."""
    if plan is None:
        return None
    if art is not None:
        th = art.thumb(plan.key)
        if th is not None:
            return th
    if plan.kind == "generated":
        g0, g1, _ink = RM.GEN_PALETTE[SM.gen_index(plan.title, plan.artist)]
        return RM.linear_gradient_160(64, g0, g1)
    return int(plan.bg) or SM.LOADING_EMPTY_BG
