"""Visual tree helpers and animatable properties (DESKTOP_STAGE §4.4, §4.6.6, §4.7.1).

Rules enforced here (§4.4):
- **Sampling / edges:** the scene root gets LINEAR interpolation and SOFT borders and every other
  visual inherits. NEAREST_NEIGHBOR and HARD are refused (AssertionError), and every mode ever
  passed is recorded in ``Tree.mode_calls`` for the H6 check.
- **Group opacity:** LAYER on the root and on containers whose children overlap; MULTIPLY only
  where children never overlap (``container(..., overlap=False)``).
- **Rest pixel snap:** ``Tree.offset`` rounds rest offsets to whole physical pixels (§0.3).
- **Z-order:** sibling order changes only through ``Tree.reorder`` (at a detent, no animation),
  with ``RemoveVisual`` + ``AddVisual`` against a reference visual for the children that move,
  or one ``RemoveAllVisuals`` + re-add when that is fewer calls.
- **Content swap:** ``Tree.content`` is a plain setter; the builder commits it in the same batch
  as the animation that reveals it (§4.4 last row).

Properties (§4.6.6): ``OffsetX``/``OffsetY`` on a visual, ``Opacity`` through
``IDCompositionVisual3::SetOpacity`` (or the spike's ``IDCompositionEffectGroup`` pair, the G1-10
fallback), a uniform ``Scale`` whose X and Y are bound to the **same** animation object, and
``ScaleX`` alone (the tab underline). Each property owns a pool of two animation objects created
at open, used alternately, so an animation still bound is never modified (§4.6.5 item 4, G1-7);
its ``func`` is the twin (``curves.Const``, ``curves.Tween`` or ``curves.Motion``).
"""
from __future__ import annotations

import ctypes as C

from . import com
from . import curves as CV

LINEAR = com.DCOMPOSITION_BITMAP_INTERPOLATION_MODE_LINEAR
SOFT = com.DCOMPOSITION_BORDER_MODE_SOFT
LAYER = com.DCOMPOSITION_OPACITY_MODE_LAYER
MULTIPLY = com.DCOMPOSITION_OPACITY_MODE_MULTIPLY

OPACITY_VISUAL3, OPACITY_EFFECT_GROUP = "visual3", "effectgroup"


class Visual:
    """A visual in the tree: the device handle, its children bottom to top, its parent."""

    __slots__ = ("ref", "name", "children", "parent", "effect", "transform", "released")

    def __init__(self, ref, name):
        self.ref = ref
        self.name = name
        self.children = []
        self.parent = None
        self.effect = None
        self.transform = None
        self.released = False

    @property
    def ptr(self):
        return self.ref.ptr

    def __repr__(self):
        return f"<Visual {self.name}>"


class Prop:
    """One animatable property: float setters, animation binders, the two-object pool and the
    twin. ``kind`` is 'offset' | 'scale' | 'opacity' (the §4.6.2 bound); ``size`` is the element
    size in px for scales."""

    __slots__ = ("name", "kind", "size", "fset", "fbind", "pool", "pi", "func", "owner")

    def __init__(self, device, name, kind, fset, fbind, size=1.0, initial=0.0, owner=None):
        self.name = name
        self.kind = kind
        self.size = float(size)
        self.fset = tuple(fset)
        self.fbind = tuple(fbind)
        self.pool = (device.create_animation(name + ".a0"), device.create_animation(name + ".a1"))
        self.pi = 0
        self.func = CV.Const(initial)
        self.owner = owner

    def take_animation(self):
        """The pool object not bound now (ping-pong, G1-7)."""
        a = self.pool[self.pi]
        self.pi ^= 1
        return a

    def value(self, t):
        return self.func.value(t)

    @property
    def target(self):
        return self.func.target

    def moving(self, t) -> bool:
        return self.func.moving(t)

    def set_now(self, v) -> int:
        """Float setter(s) outside any batch (tree building). Returns the calls made."""
        hr = 0
        v = float(v)
        for fn, ptr in self.fset:
            hr |= fn(ptr, v)
        if hr < 0:
            com.check(hr, self.name + " set")
        self.func = CV.Const(v)
        return len(self.fset)

    def __repr__(self):
        return f"<Prop {self.name}>"


class Tree:
    """Builds and edits one scene's visuals on a device (NativeDevice or FakeDevice)."""

    def __init__(self, device, opacity_path: str = OPACITY_VISUAL3):
        if opacity_path not in (OPACITY_VISUAL3, OPACITY_EFFECT_GROUP):
            raise ValueError(opacity_path)
        self.dev = device
        self.opacity_path = opacity_path
        self.mode_calls = []
        self.visuals = []
        self.props = []
        self.others = []          # transforms, effect groups created for visuals
        self.calls = 0

    # ------------------------------------------------------------------ modes (H6)
    def set_interp(self, v: Visual, mode: int):
        if mode == com.FORBIDDEN_INTERPOLATION:
            raise AssertionError("NEAREST_NEIGHBOR interpolation is forbidden (AR-8, H6)")
        self.mode_calls.append(("interp", mode))
        self._call("Visual.SetBitmapInterpolationMode", v.ptr, mode)

    def set_border(self, v: Visual, mode: int):
        if mode == com.FORBIDDEN_BORDER:
            raise AssertionError("HARD border mode is forbidden (AR-8, H6)")
        self.mode_calls.append(("border", mode))
        self._call("Visual.SetBorderMode", v.ptr, mode)

    def set_opacity_mode(self, v: Visual, mode: int):
        self.mode_calls.append(("opacity", mode))
        self._call("Visual2.SetOpacityMode", v.ptr, mode)

    def _call(self, name, ptr, *args):
        hr = self.dev.fn(name, ptr)(ptr, *args)
        self.calls += 1
        if hr is not None and hr < 0:
            com.check(hr, name)
        return hr

    # ------------------------------------------------------------------ visuals
    def visual(self, name: str, *, opacity: bool = False, content=None) -> Visual:
        ref = self.dev.create_visual(name, v3=opacity and self.opacity_path == OPACITY_VISUAL3)
        v = Visual(ref, name)
        self.visuals.append(v)
        if opacity and self.opacity_path == OPACITY_EFFECT_GROUP:
            eg = self.dev.create_effect_group(name + ".eg")
            self.others.append(eg)
            self._call("Visual.SetEffect", v.ptr, eg)
            v.effect = eg
        if content is not None:
            self.content(v, content)
        return v

    def root(self, name: str = "root") -> Visual:
        """The scene root: LINEAR + SOFT (every other visual inherits) and LAYER group opacity."""
        v = self.visual(name, opacity=True)
        self.set_interp(v, LINEAR)
        self.set_border(v, SOFT)
        self.set_opacity_mode(v, LAYER)
        return v

    def container(self, name: str, *, opacity: bool = True, overlap: bool = True) -> Visual:
        """A container with group opacity: LAYER where children overlap, MULTIPLY otherwise."""
        v = self.visual(name, opacity=opacity)
        if opacity:
            self.set_opacity_mode(v, LAYER if overlap else MULTIPLY)
        return v

    def content(self, v: Visual, surface):
        self._call("Visual.SetContent", v.ptr, surface or None)

    def offset(self, v: Visual, x: float, y: float, snap: bool = True):
        """Rest offsets in whole physical px (§0.3 rule 12) unless ``snap`` is False."""
        if snap:
            x, y = round(x), round(y)
        self._call("Visual.SetOffsetX", v.ptr, float(x))
        self._call("Visual.SetOffsetY", v.ptr, float(y))

    def matrix(self, v: Visual, sx: float, sy: float, dx: float, dy: float, m12: float = 0.0, m21: float = 0.0):
        m = com.D2D_MATRIX_3X2_F(sx, m12, m21, sy, dx, dy)
        self._call("Visual.SetTransform.matrix", v.ptr, C.byref(m))

    def clip(self, v: Visual, rect):
        """A static rectangular clip (left, top, right, bottom) in the visual's space, or None.
        ``SetClip(object)`` with NULL removes it (the slot the H6 discriminator proves)."""
        if rect is None:
            self._call("Visual.SetClip.object", v.ptr, None)
            return
        r = com.D2D_RECT_F(*(float(x) for x in rect))
        self._call("Visual.SetClip.rect", v.ptr, C.byref(r))

    def scale_transform(self, v: Visual, cx: float, cy: float, name: str = ""):
        """A ScaleTransform about (cx, cy) set as the visual's transform (§0.5 item 2)."""
        st = self.dev.create_scale(name or v.name + ".scale")
        self.others.append(st)
        self._call("Scale.SetCenterX", st, float(cx))
        self._call("Scale.SetCenterY", st, float(cy))
        self._call("Visual.SetTransform.object", v.ptr, st)
        v.transform = st
        return st

    def scale_group(self, v: Visual, centers, name: str = ""):
        """§4.6.6: SetTransform(TransformGroup[ScaleTransform, ScaleTransform, ...]); each scale
        about its own centre (e.g. the table scale S and the enter scale e)."""
        sts = []
        for i, (cx, cy) in enumerate(centers):
            st = self.dev.create_scale(f"{name or v.name}.scale{i}")
            self.others.append(st)
            self._call("Scale.SetCenterX", st, float(cx))
            self._call("Scale.SetCenterY", st, float(cy))
            sts.append(st)
        grp = self.dev.create_transform_group(sts, (name or v.name) + ".group")
        self.others.append(grp)
        self._call("Visual.SetTransform.object", v.ptr, grp)
        v.transform = grp
        return sts

    # ------------------------------------------------------------------ children
    def add(self, parent: Visual, child: Visual, *, above: Visual | None = None, below: Visual | None = None,
            back: bool = False):
        """Add ``child`` in front of all siblings (default), behind all (``back``), or just
        above / below a sibling."""
        kids = parent.children
        if above is not None:
            self._call("Visual.AddVisual", parent.ptr, child.ptr, 1, above.ptr)
            kids.insert(kids.index(above) + 1, child)
        elif below is not None:
            self._call("Visual.AddVisual", parent.ptr, child.ptr, 0, below.ptr)
            kids.insert(kids.index(below), child)
        elif back:
            self._call("Visual.AddVisual", parent.ptr, child.ptr, 1, None)
            kids.insert(0, child)
        else:
            self._call("Visual.AddVisual", parent.ptr, child.ptr, 0, None)
            kids.append(child)
        child.parent = parent

    def remove(self, parent: Visual, child: Visual):
        self._call("Visual.RemoveVisual", parent.ptr, child.ptr)
        parent.children.remove(child)
        child.parent = None

    def reorder(self, parent: Visual, ordered) -> int:
        """Make ``parent``'s children exactly ``ordered`` (bottom to top), with no animation.
        Children that keep their relative order (a longest increasing subsequence) stay; the
        others are removed and re-added next to a reference sibling. Returns the calls made."""
        ordered = list(ordered)
        cur = parent.children
        if cur == ordered:
            return 0
        if set(map(id, cur)) != set(map(id, ordered)) or len(cur) != len(ordered):
            raise ValueError("reorder must keep the same children")
        pos = {id(v): i for i, v in enumerate(ordered)}
        seq = [pos[id(v)] for v in cur]
        keep = _lis_indices(seq)
        stay = {id(cur[i]) for i in keep}
        moves = len(cur) - len(keep)
        n = 0
        if 2 * moves < len(ordered) + 1:
            for v in list(cur):
                if id(v) not in stay:
                    self._call("Visual.RemoveVisual", parent.ptr, v.ptr)
                    cur.remove(v)
                    n += 1
            for i, v in enumerate(ordered):
                if id(v) in stay:
                    continue
                prev = ordered[i - 1] if i > 0 else None
                if prev is not None:
                    self._call("Visual.AddVisual", parent.ptr, v.ptr, 1, prev.ptr)
                    cur.insert(cur.index(prev) + 1, v)
                else:
                    self._call("Visual.AddVisual", parent.ptr, v.ptr, 1, None)
                    cur.insert(0, v)
                n += 1
        else:
            self._call("Visual.RemoveAllVisuals", parent.ptr)
            n += 1
            for v in ordered:
                self._call("Visual.AddVisual", parent.ptr, v.ptr, 0, None)
                n += 1
            parent.children[:] = ordered
        return n

    # ------------------------------------------------------------------ properties
    def offset_x(self, v: Visual, initial: float = 0.0) -> Prop:
        return self._prop(v, "x", "offset", ("Visual.SetOffsetX", v.ptr), ("Visual.SetOffsetX.anim", v.ptr), 1.0,
                          initial)

    def offset_y(self, v: Visual, initial: float = 0.0) -> Prop:
        return self._prop(v, "y", "offset", ("Visual.SetOffsetY", v.ptr), ("Visual.SetOffsetY.anim", v.ptr), 1.0,
                          initial)

    def opacity(self, v: Visual, initial: float = 1.0) -> Prop:
        if v.effect:
            return self._prop(v, "opacity", "opacity", ("EffectGroup.SetOpacity", v.effect),
                              ("EffectGroup.SetOpacity.anim", v.effect), 1.0, initial)
        if not v.ref.v3:
            raise ValueError(f"{v.name}: created without opacity=True")
        return self._prop(v, "opacity", "opacity", ("Visual3.SetOpacity", v.ref.v3),
                          ("Visual3.SetOpacity.anim", v.ref.v3), 1.0, initial)

    def scale(self, st, size: float, initial: float = 1.0, name: str = "scale") -> Prop:
        """Uniform scale: SetScaleX and SetScaleY bound to the same animation (§4.6.6, G1-4)."""
        d = self.dev
        p = Prop(d, name, "scale", ((d.fn("Scale.SetScaleX", st), st), (d.fn("Scale.SetScaleY", st), st)),
                 ((d.fn("Scale.SetScaleX.anim", st), st), (d.fn("Scale.SetScaleY.anim", st), st)), size, initial)
        self.props.append(p)
        if initial is not None:
            self.calls += p.set_now(initial)
        return p

    def scale_x(self, st, size: float, initial: float = 1.0, name: str = "scale_x") -> Prop:
        d = self.dev
        p = Prop(d, name, "scale", ((d.fn("Scale.SetScaleX", st), st),), ((d.fn("Scale.SetScaleX.anim", st), st),),
                 size, initial)
        self.props.append(p)
        if initial is not None:
            self.calls += p.set_now(initial)
        return p

    def _prop(self, v, what, kind, setter, binder, size, initial) -> Prop:
        d = self.dev
        p = Prop(d, f"{v.name}.{what}", kind, ((d.fn(*setter), setter[1]),), ((d.fn(*binder), binder[1]),), size,
                 initial, owner=v)
        self.props.append(p)
        if initial is not None:
            self.calls += p.set_now(initial)
        return p

    # ------------------------------------------------------------------ release
    def release_all(self) -> int:
        """Release every visual, transform, effect and animation this tree created, in reverse
        creation order (the scene's visuals at close, §4.1; surfaces live in their caches)."""
        n = 0
        for p in reversed(self.props):
            for a in p.pool:
                self.dev.release(a)
                n += 1
        for o in reversed(self.others):
            self.dev.release(o)
            n += 1
        for v in reversed(self.visuals):
            if not v.released:
                if v.ref.v3 and v.ref.v3 != v.ref.ptr:
                    self.dev.release(v.ref.v3)
                self.dev.release(v.ref.ptr)
                v.released = True
                n += 1
        self.props.clear()
        self.others.clear()
        self.visuals.clear()
        return n


def _lis_indices(seq):
    """Indices of one longest strictly increasing subsequence of ``seq`` (O(n log n))."""
    import bisect
    tails, tails_i, prev = [], [], [-1] * len(seq)
    for i, x in enumerate(seq):
        j = bisect.bisect_left(tails, x)
        if j == len(tails):
            tails.append(x)
            tails_i.append(i)
        else:
            tails[j] = x
            tails_i[j] = i
        prev[i] = tails_i[j - 1] if j > 0 else -1
    out = []
    k = tails_i[-1] if tails_i else -1
    while k >= 0:
        out.append(k)
        k = prev[k]
    return out[::-1]
