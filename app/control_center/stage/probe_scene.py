"""A synthetic explorer-like scene on the stage (DESKTOP_STAGE §7.2, §7.3, §7.6): the cards of the
16:9 or 32:9 table with the proven tree shape, used by the headless self-test, the per-detent
bench (H5, G1-4) and the supervised pacing check (G1-10). It is **not** the explorer (WP8
builds that); it exercises the engine the way the explorer will:

- a card container per item (LAYER group opacity, the table opacity), X on the container, the
  rest Y plus the enter rise on the container, and a ``TransformGroup`` of two scales about the
  card centre (the table scale S and the enter scale e, §4.6.6);
- inside: the side and focus shadows as **fixed** 1/4-resolution layers crossfaded when a card
  enters or leaves the centre, the cover, and the shade drawn from **one shared** 680 px solid
  (G1-9);
- z-order ``20 − a`` changed only at a detent (§4.4); the marker translating 420 ms OUT; the
  end bump as one two-leg animation on the cards container (S5-31);
- G1-4 call cutting: equal targets are skipped by the builder, and a card invisible before and
  after a turn jumps (one float call) instead of animating.
"""
from __future__ import annotations

import colorsys

from .presenter import Scene
from .surfaces import box_shadow, opaque_bytes, sprite_bytes

TABLE_16x9 = {"x": (0, 300, 470, 590, 660), "s": (1.00, 0.60, 0.42, 0.30, 0.22), "o": (1, 0.92, 0.55, 0, 0),
              "sh": (0, 0.24, 0.48, 0.60, 0.60)}
TABLE_32x9 = {"x": (0, 300, 500, 680, 850, 1010, 1170, 1330, 1490),
              "s": (1.00, 0.60, 0.46, 0.42, 0.40, 0.40, 0.40, 0.40, 0.40),
              "o": (1, 0.92, 0.84, 0.76, 0.68, 0.60, 0.54, 0.50, 0),
              "sh": (0, 0.24, 0.34, 0.42, 0.48, 0.52, 0.55, 0.58, 0.60)}
SHADE_RGB = (0x0B, 0x0B, 0x0C)


class _Card:
    __slots__ = ("i", "box", "inner", "cover", "shade", "side", "focus", "x", "y", "s", "e", "o", "sh",
                 "side_o", "focus_o", "a")


class ProbeScene(Scene):
    surface = "explorer"

    def __init__(self, ctx, payload):
        super().__init__(ctx, payload)
        lay = ctx.layout
        self.tab = TABLE_32x9 if lay.wide else TABLE_16x9
        self.a_max = len(self.tab["x"]) - 1
        self.n = int(payload.get("count") or len(payload.get("items") or ()) or 25)
        self.focus = max(0, min(self.n - 1, int(payload.get("index") or 0)))
        self.cs = lay.u(340)
        self.cx, self.cy = lay.sx0 + 640 * lay.k, lay.sy0 + 318 * lay.k
        self.rest_y = int(round(self.cy - self.cs / 2))
        self.cards = []
        self.surfaces = []
        self.covers = payload.get("probe_covers")          # optional list of PIL images
        self.play = False
        self.turns = 0
        self.stats = {"anims": [], "calls": []}

    # ------------------------------------------------------------------ geometry
    def slot(self, d):
        a = min(abs(d), self.a_max)
        sg = (d > 0) - (d < 0)
        lay = self.ctx.layout
        x = int(round(self.cx + sg * self.tab["x"][a] * lay.k - self.cs / 2))
        return a, x, self.tab["s"][a], self.tab["o"][a], self.tab["sh"][a]

    def hit_rect(self):
        if self.play:
            return None
        x = int(round(self.cx - self.cs / 2))
        return (x, self.rest_y, x + self.cs, self.rest_y + self.cs)

    # ------------------------------------------------------------------ build
    def _cover(self, i):
        from PIL import Image
        if self.covers:
            img = self.covers[i % len(self.covers)]
            if img.size != (self.cs, self.cs):
                img = img.resize((self.cs, self.cs), Image.LANCZOS)
            return img
        r, g, b = colorsys.hsv_to_rgb((i * 0.618033988749895) % 1.0, 0.55, 0.80)
        return Image.new("RGB", (self.cs, self.cs), (int(r * 255), int(g * 255), int(b * 255)))

    def _upload(self, img, opaque, name):
        dev = self.ctx.device
        w, h, data = opaque_bytes(img) if opaque else sprite_bytes(img)
        s = dev.create_surface(w, h, opaque, name)
        dev.upload(s, w, h, data, name)
        self.surfaces.append(s)
        return s, (w, h)

    def build(self, payload, container):
        ctx, tree, lay = self.ctx, self.ctx.tree, self.ctx.layout
        k, cs = lay.k, self.cs
        shade_s = ctx.solids.get(SHADE_RGB, cs, cs)                            # G1-9: one shared surface
        side_sp = box_shadow(cs, cs, 36 * k, 0.40, offset_y_px=16 * k)         # 0 16px 36px rgba(0,0,0,.40)
        focus_sp = box_shadow(cs, cs, 80 * k, 0.55, offset_y_px=40 * k)        # 0 40px 80px rgba(0,0,0,.55)
        side_s, _ = self._upload(side_sp.image, False, "shadow.side")
        focus_s, _ = self._upload(focus_sp.image, False, "shadow.focus")
        self.cards_box = tree.container("cards", opacity=False)
        tree.add(container, self.cards_box)
        self.cards_x = tree.offset_x(self.cards_box, 0.0)
        for i in range(self.n):
            c = _Card()
            c.i = i
            a, x, s, o, sh = self.slot(i - self.focus)
            c.a = a
            c.box = tree.container(f"card{i}", overlap=True)
            c.inner = tree.visual(f"card{i}.inner")
            sts = tree.scale_group(c.inner, ((cs / 2.0, cs / 2.0), (cs / 2.0, cs / 2.0)))
            c.side = tree.visual(f"card{i}.side", opacity=True, content=side_s)
            tree.matrix(c.side, side_sp.scale, side_sp.scale, side_sp.offset[0], side_sp.offset[1])
            c.focus = tree.visual(f"card{i}.focus", opacity=True, content=focus_s)
            tree.matrix(c.focus, focus_sp.scale, focus_sp.scale, focus_sp.offset[0], focus_sp.offset[1])
            cover_s, _ = self._upload(self._cover(i), True, f"cover{i}")
            c.cover = tree.visual(f"card{i}.cover", content=cover_s)
            c.shade = tree.visual(f"card{i}.shade", opacity=True, content=shade_s)
            for child in (c.side, c.focus, c.cover, c.shade):
                tree.add(c.inner, child)
            tree.add(c.box, c.inner)
            visible = abs(i - self.focus) <= self.a_max
            c.x = tree.offset_x(c.box, float(x))
            c.y = tree.offset_y(c.box, float(self.rest_y + (lay.u(30 * s) if visible else 0)))
            c.s = tree.scale(sts[0], cs, s, name=f"card{i}.S")
            c.e = tree.scale(sts[1], cs, 0.9 if visible else 1.0, name=f"card{i}.e")
            c.o = tree.opacity(c.box, 0.0)
            c.sh = tree.opacity(c.shade, sh)
            c.side_o = tree.opacity(c.side, 0.0 if a == 0 else 1.0)
            c.focus_o = tree.opacity(c.focus, 1.0 if a == 0 else 0.0)
            self.cards.append(c)
        self.cards_order = []
        self._reorder(force=True)
        ms = lay.u(6)
        self.dots_x = int(round(lay.sx0 + (1280 * k - (min(self.n, 82) - 1) * 14 * k - ms) / 2))
        marker_s = ctx.solids.get((255, 255, 255), ms, ms)
        self.marker_v = tree.visual("marker", content=marker_s)
        tree.offset(self.marker_v, self.dots_x, lay.sy0 + 622 * k)
        tree.add(container, self.marker_v)
        self.marker = tree.offset_x(self.marker_v, float(self._marker_x()))

    def _marker_x(self):
        return self.dots_x + int(round(self.focus * 14 * self.ctx.layout.k))

    def _reorder(self, force=False):
        order = sorted(self.cards, key=lambda c: (-min(abs(c.i - self.focus), self.a_max), c.i))
        if not force and [c.i for c in order] == self.cards_order:
            return 0
        self.cards_order = [c.i for c in order]
        tree = self.ctx.tree
        if not self.cards_box.children:
            for c in order:
                tree.add(self.cards_box, c.box)
            return len(order)
        return tree.reorder(self.cards_box, [c.box for c in order])

    # ------------------------------------------------------------------ motion
    def open(self, batch, payload):
        """§7.6 Open: rise +30·S -> 0 and e 0.9 -> 1 over 440 OUT, opacity 0 -> table over 320
        OUT, each delayed 45 ms × a; reduced motion: opacity only, 200 ms OUT (§16)."""
        rm = self.ctx.reduced_motion
        for c in self.cards:
            d = c.i - self.focus
            if abs(d) > self.a_max:
                continue
            a, x, s, o, sh = self.slot(d)
            delay = 0 if rm else 45 * a
            if rm:
                batch.jump(c.y, self.rest_y)
                batch.jump(c.e, 1.0)
                batch.to(c.o, o, 200, "OUT", v_from=0.0, force=True)
                continue
            batch.to(c.y, float(self.rest_y), 440, "OUT", delay_ms=delay)
            batch.to(c.e, 1.0, 440, "OUT", delay_ms=delay)
            batch.to(c.o, o, 320, "OUT", delay_ms=delay, v_from=0.0, force=True)

    def update(self, batch, call, payload):
        if call.endswith("_highlight"):
            bump = int(payload.get("bump") or 0)
            if bump and not self.ctx.reduced_motion:
                k = self.ctx.layout.k
                batch.legs(self.cards_x, [(0, -14 * k * bump, 160, "OUT"), (160, 0.0, 160, "OUT")], v_from=0.0)
            self.turn(batch, int(payload["index"]))

    def position(self, batch, index):
        self.turn(batch, index)

    def turn(self, batch, focus):
        focus = max(0, min(self.n - 1, int(focus)))
        if focus == self.focus or self.play:
            return 0
        n0, a0 = batch.calls, batch.anims
        rm = self.ctx.reduced_motion
        t1 = batch.t1
        old_focus, self.focus = self.focus, focus
        for c in self.cards:
            a, x, s, o, sh = self.slot(c.i - focus)
            was_hidden = c.o.target <= 0.0 and c.o.value(t1) <= 0.0
            if (was_hidden and o <= 0.0) or rm:
                batch.jump(c.x, float(x))                     # invisible before and after: jump (G1-4)
                batch.jump(c.s, s)
                if rm:
                    batch.to(c.o, o, 200, "OUT")
                else:
                    batch.jump(c.o, o)
                batch.jump(c.sh, sh)
            else:
                batch.to(c.x, float(x), 420, "OUT")
                batch.to(c.s, s, 420, "OUT")
                batch.to(c.o, o, 300, "OUT")
                batch.to(c.sh, sh, 320, "OUT")
            if (c.a == 0) != (a == 0):                         # entering or leaving the centre
                batch.to(c.side_o, 0.0 if a == 0 else 1.0, 320, "OUT")
                batch.to(c.focus_o, 1.0 if a == 0 else 0.0, 320, "OUT")
            c.a = a
        if rm:
            batch.jump(self.marker, float(self._marker_x()))
        else:
            batch.to(self.marker, float(self._marker_x()), 420, "OUT")
        tree = self.ctx.tree
        before = tree.calls
        self._reorder()
        batch.calls += tree.calls - before
        self.turns += 1
        self.stats["anims"].append(batch.anims - a0)
        self.stats["calls"].append(batch.calls - n0)
        return batch.calls - n0

    def close(self, batch, payload):
        """Play (§7.6): the centre card grows 1 -> 1.12 over 380 OUT, the others fade over 300 OUT
        (reduced motion: no grow, the others fade over 200 ms)."""
        self.play = True
        rm = self.ctx.reduced_motion
        for c in self.cards:
            if c.i == self.focus:
                if not rm:
                    batch.to(c.e, 1.12, 380, "OUT")
            else:
                batch.to(c.o, 0.0, 200 if rm else 300, "OUT")

    def swapping(self, now_tick):
        return self.play

    def release(self):
        dev = self.ctx.device
        for s in self.surfaces:
            dev.release(s)
        self.surfaces = []


def probe_payload(count=25, index=12, t0=None, control_id=1, reduced_motion=False, **extra):
    """An ``explorer_open`` payload carrying every K4 §2.3 field (synthetic items)."""
    import time
    p = {"t0": time.perf_counter() if t0 is None else t0, "source": "recent", "state": "ready", "index": index,
         "count": count, "items": [{"title": f"Item {i + 1}"} for i in range(count)], "items_first": 0,
         "items_rev": 1, "control_id": control_id, "control_min": 0, "reduced_motion": reduced_motion,
         "foreground_hwnd": 0, "sonos_available": True}
    p.update(extra)
    return p

