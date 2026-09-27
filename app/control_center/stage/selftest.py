"""Headless self-test of the stage engine (DESKTOP_STAGE §6.6, §19.1 P0; [G1] G1-1 ... G1-9).

    .venv\\Scripts\\python.exe -I control_center\\stage\\selftest.py [--json PATH] [--quick]

(By path, from the project folder: under ``-I`` neither the working directory nor the script's folder
is on ``sys.path``, so ``-m control_center.stage.selftest`` cannot find the package; ``-m`` works
without ``-I``. ``picker_selftest.py`` runs this self-test with the scenes and the picker's checks.)

Nothing is shown on screen: devices are created without a target, trees are built and
committed on them, and the only window is the host created hidden off-screen at 1 x 1 (never
shown; ``HostWindow(hidden_only=True)`` refuses to show) to check its styles and its target
slot. No serial port, network, Tk, screen capture or registry access.

Checks (gated unless marked informational):
- env: x64, Windows 11 (22000+), the five compositor exports (P0);
- static scan: H2 (no timers in frame paths), no focus-stealing calls, ShowWindow only with
  SW_HIDE, no NEAREST / HARD modes passed, no Tk / serial imports, no imports of the stage from
  outside the package (no behaviour change);
- curves: H3 (every App A tuple within §4.6.2's bound), H7 and H1 on a fake clock;
- device: created on the monitor's adapter; ``timeFrequency`` == QPF (G1-8); state valid;
- H6 slot matrix: every slot the stage binds returns S_OK on a device without a target, with
  the ``SetClip`` discriminator; no NEAREST / HARD ever passed;
- upload readback (``UpdateSubresource`` at the atlas offset, §4.5);
- hidden hosts: click-eating 0x08200088 and click-through 0x082800A8, never visible, session
  notifications registered and unregistered (a hidden-only host never registers for the console
  display state, so the display being off cannot reach a headless run: RN-R5),
  ``CreateTargetForHwnd`` + ``SetRoot`` + Commit;
- the probe scene built and committed; retarget continuity in DWM's float32 view over a
  20 detents/s script (H7 on the real builder, G1-7);
- the per-detent bench on the 32:9 table at 20 detents/s: wake -> Commit <= 1.5 ms p95, gated
  (G1-4: "H5 gates it"; a target-less device, so it is the Python + COM build cost);
- informational benches (the PC is shared): the 16:9 table and the burst-hog run, the 33-call
  PYFUNCTYPE push under a busy thread (P0: ≤ 0.05 ms p95), statistics reads keeping vs releasing
  the GIL (G1-1), one compositor-clock wait's return code (G1-2; never looped).
"""
from __future__ import annotations

import argparse
import ctypes as C
import json
import os
import re
import statistics
import sys
import threading
import time

if __name__ == "__main__" and not __package__:          # run by path (see the usage above)
    import runpy
    _HERE = os.path.dirname(os.path.abspath(__file__))
    sys.path[:] = [p for p in sys.path if os.path.abspath(p or os.curdir) != _HERE]
    sys.path.insert(0, os.path.dirname(os.path.dirname(_HERE)))
    runpy.run_module("control_center.stage.selftest", run_name="__main__", alter_sys=True)
    sys.exit(0)

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
ROOT = os.path.dirname(PKG)

FRAME_PATH_MODULES = ("animation.py", "blur.py", "capture.py", "clock.py", "com.py", "curves.py", "device.py",
                      "engine.py", "fake.py", "frames.py", "host.py", "layout.py", "motion_table.py", "presenter.py",
                      "probe_scene.py", "surfaces.py", "tree.py", "win32.py", "__init__.py")
IDLE_PATH_ALLOWLIST = ("bench.py", "selftest.py")
# The one sanctioned importer of the stage outside the package: WP10's wiring point (K4 §4.1,
# ``standalone.start_stage``); the same rule as ``stage.scenes.selftest.WIRING_POINTS`` (WP8-R11).
WIRING_POINTS = ("standalone.py",)


class Report:
    def __init__(self, echo=True):
        self.checks = []
        self.data = {}
        self.echo = echo

    def check(self, name, ok, detail=None, gate=True):
        self.checks.append({"name": name, "ok": bool(ok), "gate": gate, "detail": detail})
        if self.echo:
            tag = "PASS" if ok else ("FAIL" if gate else "info")
            text = json.dumps(detail, default=str)[:240] if detail is not None else ""
            print(f"[{tag}] {name}  {text}", flush=True)
        return ok

    @property
    def passed(self):
        return all(c["ok"] for c in self.checks if c["gate"])


# --------------------------------------------------------------------------- static scan
def _strip_strings_and_comments(line):
    line = re.sub(r"(\"\"\"|''').*?\1", "", line)
    line = re.sub(r"\"(\\.|[^\"])*\"|'(\\.|[^'])*'", "''", line)
    return line.split("#", 1)[0]


def static_scan(stage_dir=HERE, pkg_dir=PKG, root=ROOT) -> dict:
    """H2 and the safety rules. Forbidden names are assembled from pieces so this function never
    matches itself."""
    hits = []
    focus = ["SetFore" + "groundWindow", "SetActive" + "Window", "BringWindow" + "ToTop", "SW_" + "SHOW",
             "SW_" + "RESTORE", "SetFo" + "cus("]
    timers = [r"\.after" + r"\(", r"\bSetTim" + r"er\(", r"\bsle" + r"ep\("]
    magic = [r"\b16\.7\b", r"\b8\.3\b", r"\b4\.17\b"]
    imports = ["import " + "tkinter", "from " + "tkinter", "import " + "serial", "import " + "soco",
               "import " + "requests", "import " + "urllib"]
    for name in sorted(os.listdir(stage_dir)):
        if not name.endswith(".py"):
            continue
        in_doc = False
        with open(os.path.join(stage_dir, name), encoding="utf-8") as fh:
            for ln, raw in enumerate(fh, 1):
                if raw.count('"""') % 2 == 1:
                    in_doc = not in_doc
                    continue
                if in_doc:
                    continue
                code = _strip_strings_and_comments(raw)
                for b in focus + imports:
                    if b in code:
                        hits.append(f"{name}:{ln}: {b}")
                if name in FRAME_PATH_MODULES:
                    for pat in timers:
                        if re.search(pat, code):
                            hits.append(f"{name}:{ln}: timer {pat}")
                    for pat in magic:
                        if re.search(pat, code):
                            hits.append(f"{name}:{ln}: hard-coded period {pat}")
                if "ShowWindow(" in code and "SW_HIDE" not in code:
                    hits.append(f"{name}:{ln}: ShowWindow without SW_HIDE")
                for pat in ("NEAREST" + "_NEIGHBOR", "BORDER_MODE" + "_HARD"):
                    if pat in code and "FORBIDDEN" not in code and not re.match(r"\s*DCOMPOSITION_\w+\s*=", code):
                        hits.append(f"{name}:{ln}: {pat} passed")
    outside = []
    for base in (pkg_dir, root):
        for name in sorted(os.listdir(base)):
            p = os.path.join(base, name)
            if not name.endswith(".py") or not os.path.isfile(p):
                continue
            with open(p, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            if re.search(r"(control_center\.stage|from \.stage|from \. import stage)", text):
                outside.append(os.path.relpath(p, root))
    return {"hits": hits, "outside_importers": outside}


# --------------------------------------------------------------------------- curves
def curves_checks(rep: Report):
    from . import curves as CV
    from . import motion_table as MT
    bounds = {"offset": CV.OFFSET_BOUND_PX, "scale": CV.SCALE_BOUND_PX, "opacity": CV.OPACITY_BOUND}
    worst = {}
    ok = True
    segs = {}
    for row in MT.APP_A:
        kind, name = row[2], row[3]
        ext = MT.H3_EXTREMES[kind]
        for _st, dur in MT.legs_of(row):
            r = CV.validate(name, dur / 1000.0, 1.0, 1.0 + ext["travel"], kind, ext["size"], samples=4000)
            err = r["max_err"] * (ext["size"] if kind == "scale" else 1.0)
            worst[kind] = max(worst.get(kind, 0.0), err)
            segs[kind] = max(segs.get(kind, 0), r["segments"])
            ok &= err <= bounds[kind]
    rep.check("curves.h3_every_app_a_tuple_within_bound", ok,
              {"worst": {k: round(v, 5) for k, v in worst.items()}, "max_segments": segs, "tuples": len(MT.APP_A)})
    freq = 10_000_000
    m = CV.tween(0, freq, 0.0, 600.0, 0.42)
    jump = 0.0
    t = 0
    x = 600.0
    for i in range(40):
        t += int(0.05 * freq)
        v = m.value(t)
        x += 600.0 if i % 3 else -600.0
        n = CV.tween(t, freq, v, x, 0.42)
        segs_, end = n.segments()
        jump = max(jump, abs(n.value(t) - v), abs(CV.eval_segments(segs_, end, 0.0) - CV.f32(v)))
        m = n
    rep.check("curves.h7_retarget_continuity_fake_clock", jump <= 1e-3, {"max_jump": jump})
    base = [m.value(int(j * freq / 60)) for j in range(60)]
    same = all(m.value(int(j * freq / 60)) == base[j] for j in range(60))
    rep.check("curves.h1_frame_rate_independent", same)


# --------------------------------------------------------------------------- device checks
def slot_matrix(dev) -> tuple:
    """H6: every slot the stage binds, S_OK on a device without a target. The SetClip
    discriminator: the object overload accepts NULL (removes the clip); the rect overload would
    dereference it, so slot 13 answering S_OK to NULL proves it is the object overload before
    slot 14 is called with a rect."""
    from . import com
    res = {}
    v = dev.create_visual("slot.v", v3=True)
    v2 = dev.create_visual("slot.v2")
    st = dev.create_scale("slot.st")
    st2 = dev.create_scale("slot.st2")
    grp = dev.create_transform_group([st, st2], "slot.group")
    eg = dev.create_effect_group("slot.eg")
    clip = dev.create_rect_clip("slot.clip")
    an = dev.create_animation("slot.anim")
    surf = dev.create_surface(4, 4, True, "slot.surf")
    dev.upload(surf, 4, 4, bytes((1, 2, 3, 255)) * 16, "slot.surf")

    def t(name, obj, *args):
        try:
            hr = com.vfn(obj, name)(obj, *args)
            res[name + ("" if not args else f"({_argname(args)})")] = com.hx(hr) if hr is not None else "void"
        except Exception as exc:
            res[name] = repr(exc)

    t("Animation.Reset", an)
    t("Animation.SetAbsoluteBeginTime", an, int(time.perf_counter() * dev.freq) + dev.freq)
    t("Animation.AddCubic", an, 0.0, 1.0, 2.0, 0.0, 0.0)
    t("Animation.End", an, 0.5, 2.0)
    t("Visual.SetOffsetX", v.ptr, 12.5)
    t("Visual.SetOffsetX.anim", v.ptr, an)
    t("Visual.SetOffsetY", v.ptr, 3.0)
    t("Visual.SetOffsetY.anim", v.ptr, an)
    t("Visual.SetTransform.object", v2.ptr, st)
    t("Visual.SetTransform.object", v2.ptr, grp)
    m = com.D2D_MATRIX_3X2_F(2, 0, 0, 2, 1, 1)
    t("Visual.SetTransform.matrix", v.ptr, C.byref(m))
    t("Visual.SetEffect", v2.ptr, eg)
    t("Visual.SetBitmapInterpolationMode", v.ptr, com.DCOMPOSITION_BITMAP_INTERPOLATION_MODE_LINEAR)
    t("Visual.SetBitmapInterpolationMode", v2.ptr, com.DCOMPOSITION_BITMAP_INTERPOLATION_MODE_INHERIT)
    t("Visual.SetBorderMode", v.ptr, com.DCOMPOSITION_BORDER_MODE_SOFT)
    t("Visual.SetBorderMode", v2.ptr, com.DCOMPOSITION_BORDER_MODE_INHERIT)
    t("Visual.SetClip.object", v.ptr, None)                       # the discriminator (NULL)
    disc_ok = res.get("Visual.SetClip.object(None)") == "0x00000000"
    if disc_ok:
        t("Visual.SetClip.object", v.ptr, clip)
        r = com.D2D_RECT_F(0, 0, 100, 50)
        t("Visual.SetClip.rect", v.ptr, C.byref(r))
        t("Visual.SetClip.object", v.ptr, None)
    t("Visual.SetContent", v.ptr, surf)
    t("Visual.AddVisual", v.ptr, v2.ptr, 0, None)
    t("Visual.RemoveVisual", v.ptr, v2.ptr)
    t("Visual.AddVisual", v.ptr, v2.ptr, 1, None)
    t("Visual.RemoveAllVisuals", v.ptr)
    t("Visual2.SetOpacityMode", v.ptr, com.DCOMPOSITION_OPACITY_MODE_LAYER)
    t("Visual2.SetOpacityMode", v2.ptr, com.DCOMPOSITION_OPACITY_MODE_MULTIPLY)
    t("Visual3.SetOpacity", v.v3, 0.5)
    t("Visual3.SetOpacity.anim", v.v3, an)
    for nm in ("Scale.SetScaleX", "Scale.SetScaleY"):
        t(nm, st, 0.5)
        t(nm + ".anim", st, an)
    t("Scale.SetCenterX", st, 340.0)
    t("Scale.SetCenterY", st, 340.0)
    t("EffectGroup.SetOpacity", eg, 0.5)
    t("EffectGroup.SetOpacity.anim", eg, an)
    t("Device.Commit", dev.dev)
    t("Device.WaitForCommitCompletion", dev.dev)
    fs = com.DCOMPOSITION_FRAME_STATISTICS()
    t("Device.GetFrameStatistics", dev.dev, C.byref(fs))
    ok = all(val in ("0x00000000", "void") for val in res.values()) and disc_ok
    disc = {}
    for name, obj in (("Visual.SetOffsetX.anim", v.ptr), ("Visual3.SetOpacity.anim", v.v3),
                      ("Scale.SetScaleX.anim", st)):
        try:
            disc[name + "(NULL)"] = com.hx(com.vfn(obj, name)(obj, None))
        except Exception as exc:
            disc[name + "(NULL)"] = repr(exc)
    com.vfn(v.ptr, "Visual.SetOffsetX")(v.ptr, 0.0)
    dev.commit()
    for p in (surf, an, clip, eg, grp, st2, st, v2.ptr):
        dev.release(p)
    dev.release(v.v3)
    dev.release(v.ptr)
    return ok, res, disc, disc_ok


def _argname(args):
    a = args[0]
    return "None" if a is None else type(a).__name__ if not isinstance(a, (int, float)) else repr(a)


class SpinHog(threading.Thread):
    def __init__(self):
        super().__init__(name="stage-selftest-hog", daemon=True)
        self.stop = False

    def run(self):
        n = 0
        while not self.stop:
            n += 1


def gil_push_bench(dev) -> dict:
    """P0: a 33-call PYFUNCTYPE setter push under a busy Python thread (≤ 0.05 ms p95)."""
    from . import com
    vis = [dev.create_visual(f"gil{i}", v3=True) for i in range(16)]
    fx = [com.vfn(v.ptr, "Visual.SetOffsetX") for v in vis]
    fo = [com.vfn(v.v3, "Visual3.SetOpacity") for v in vis]
    out = {}
    for label, hog_on in (("no_hog", False), ("hog", True)):
        hog = SpinHog() if hog_on else None
        if hog:
            hog.start()
            time.sleep(0.05)
        ts = []
        try:
            for i in range(400):
                t0 = time.perf_counter()
                for k in range(16):
                    fx[k](vis[k].ptr, float(k * 40 + i % 7))
                    fo[k](vis[k].v3, 0.5 + (i % 50) / 100.0)
                fx[0](vis[0].ptr, 1.0)
                ts.append((time.perf_counter() - t0) * 1000)
        finally:
            if hog:
                hog.stop = True
                hog.join()
        ys = sorted(ts)
        out[label] = {"p50": round(statistics.median(ys), 4), "p95": round(ys[int(0.95 * len(ys)) - 1], 4),
                      "max": round(ys[-1], 4)}
    dev.commit()
    for v in vis:
        dev.release(v.v3)
        dev.release(v.ptr)
    return out


def stats_read_bench(dev) -> dict:
    """G1-1: 24 frames of DCompositionGetStatistics + GetTargetStatistics, and the input path's
    GetFrameStatistics, keeping vs releasing the GIL, under a busy Python thread."""
    from . import com, win32 as W
    out = {}
    fid = C.c_uint64()
    if W.DCompositionGetFrameId_py(com.COMPOSITION_FRAME_ID_COMPLETED, C.byref(fid)) != 0:
        return {"error": "no frame id"}
    cur = fid.value
    tids = (com.COMPOSITION_TARGET_ID * 8)()
    fst, ts, cnt = com.COMPOSITION_FRAME_STATS(), com.COMPOSITION_TARGET_STATS(), C.c_uint()
    fs = com.DCOMPOSITION_FRAME_STATISTICS()
    gfs_py = com.vfn(dev.dev, "Device.GetFrameStatistics")
    gfs_wf = com._proto(com.WF, com.HRESULT, (C.POINTER(com.DCOMPOSITION_FRAME_STATISTICS),))(
        C.c_void_p.from_address(C.c_void_p.from_address(dev.dev).value + 8 * 5).value)
    for style, gs, gt, gf, n in (("py", W.DCompositionGetStatistics_py, W.DCompositionGetTargetStatistics_py,
                                  gfs_py, 20),
                                 ("wf", W.DCompositionGetStatistics_wf, W.DCompositionGetTargetStatistics_wf,
                                  gfs_wf, 5)):
        hog = SpinHog()
        hog.start()
        time.sleep(0.03)
        walk, one = [], []
        try:
            for _ in range(n):
                t0 = time.perf_counter()
                for f in range(cur - 24, cur):
                    if gs(f, C.byref(fst), 8, tids, C.byref(cnt)) == 0 and cnt.value:
                        gt(f, C.byref(tids[0]), C.byref(ts))
                walk.append((time.perf_counter() - t0) * 1000)
                t0 = time.perf_counter()
                gf(dev.dev, C.byref(fs))
                one.append((time.perf_counter() - t0) * 1000)
        finally:
            hog.stop = True
            hog.join()
        out[style] = {"walk24_ms_p50": round(statistics.median(walk), 3), "walk24_ms_max": round(max(walk), 3),
                      "GetFrameStatistics_ms_p50": round(statistics.median(one), 4),
                      "GetFrameStatistics_ms_max": round(max(one), 4)}
    return out


def clock_probe() -> dict:
    """One DCompositionWaitForCompositorClock(0, NULL, 50) call (G1-2): 0x1 is WAIT_OBJECT_0 +
    count = a tick; 0xC01E0006 means the display sleeps. Never looped."""
    from . import win32 as W
    f = W.DCompositionWaitForCompositorClock
    if f is None:
        return {"export": False}
    t0 = time.perf_counter()
    code = f(0, None, 50) & 0xFFFFFFFF
    return {"export": True, "code": hex(code), "ms": round((time.perf_counter() - t0) * 1000, 2),
            "meaning": ("tick" if code == 0 else "display asleep (0xC01E0006)" if code == 0xC01E0006
                        else "timeout" if code == 0x102 else "other")}


def hidden_host_checks(dev) -> dict:
    from . import host as HO
    from . import win32 as W
    out = {}
    for role in (HO.ROLE_CLICK_EATING, HO.ROLE_CLICK_THROUGH):
        events = []
        h = HO.HostWindow(HO.HostInput(role, events.append), hidden_only=True)
        try:
            info = {"ex_style": hex(h.ex_style()), "expected": hex(HO.EX_STYLES[role]),
                    "visible_after_create": h.info["visible_after_create"], "dwm": [hex(x & 0xFFFFFFFF)
                                                                                    for x in h.info["dwm"]]}
            info["notifications"] = h.register_notifications()
            try:
                h.show((0, 0, 10, 10))
                info["show_refused"] = False
            except RuntimeError:
                info["show_refused"] = True
            info["capture_affinity"] = h.exclude_from_capture(True) and h.exclude_from_capture(False)
            if role == HO.ROLE_CLICK_EATING:
                tgt = dev.create_target(h.hwnd)
                root = dev.create_visual("host.root")
                info["set_root"] = dev.set_root(tgt, root.ptr)
                dev.commit()
                dev.set_root(tgt, None)
                dev.commit()
                dev.release(root.ptr)
                dev.release(tgt)
                info["target_ok"] = True
            info["visible_at_end"] = h.visible()
            info["ok"] = (int(info["ex_style"], 16) == HO.EX_STYLES[role] and not info["visible_after_create"]
                          and info["show_refused"] and not info["visible_at_end"]
                          and bool(info["notifications"]["wts"]))
        finally:
            h.destroy()
        info["destroyed"] = h.hwnd is None
        out[role] = info
    return out


def probe_continuity(dev, clock, detents=60) -> dict:
    """G1-7 on the real builder: over a 20 detents/s script on the probe scene, every retarget's
    first AddCubic value (float32, what DWM receives) equals the old twin at t1."""
    from . import curves as CV
    from .bench import _Holder
    from .engine import SceneContext, StageCore
    from .layout import StageLayout
    from .probe_scene import ProbeScene, probe_payload
    from .tree import Tree
    core = StageCore(dev, clock)
    tree = Tree(dev)
    root = tree.root()
    container = tree.visual("scene")
    tree.add(root, container)
    payload = probe_payload(count=25, index=12)
    ctx = SceneContext(_Holder(dev), core, tree, StageLayout((0, 0, 5120, 1440)), "explorer", payload)
    scene = ProbeScene(ctx, payload)
    scene.build(payload, container)
    b = core.batch()
    scene.open(b, payload)
    b.commit()
    worst_f32 = worst_f64 = 0.0
    n = 0
    focus = 12
    for i in range(detents):
        time.sleep(0.05)
        props = [p for c in scene.cards for p in (c.x, c.s, c.o, c.sh)] + [scene.marker]
        before = {id(p): p.func for p in props}
        b = core.batch()
        focus += 1 if (i // 20) % 2 == 0 or (i >= 40 and i % 2 == 0) else -1
        scene.turn(b, max(0, min(24, focus)))
        b.commit()
        for p in props:
            old, new = before[id(p)], p.func
            if new is old or not isinstance(new, (CV.Tween, CV.Motion)) or not isinstance(old, (CV.Tween, CV.Motion)):
                continue
            if new.begin != b.t1:
                continue
            segs, end = new.segments()
            want = old.value(b.t1)
            worst_f64 = max(worst_f64, abs(new.value(b.t1) - want))
            worst_f32 = max(worst_f32, abs(CV.eval_segments(segs, end, 0.0, True) - CV.f32(want)))
            n += 1
    tree.release_all()
    scene.release()
    return {"retargets": n, "max_jump_f64": worst_f64, "max_jump_f32_px": worst_f32,
            "ok": n > 100 and worst_f64 <= 1e-9 and worst_f32 <= 0.01}


# --------------------------------------------------------------------------- main
def run(quick=False, echo=True) -> Report:
    rep = Report(echo)
    sys.setswitchinterval(0.001)
    rep.check("env.x64_python", C.sizeof(C.c_void_p) == 8, {"python": sys.version.split()[0]})
    build = sys.getwindowsversion().build if sys.platform == "win32" else 0
    rep.check("env.windows_11", build >= 22000, {"build": build})
    scan = static_scan()
    rep.check("static.h2_timers_focus_modes_imports", not scan["hits"], scan["hits"][:20])
    unsanctioned = [f for f in scan["outside_importers"] if os.path.basename(f) not in WIRING_POINTS]
    rep.check("static.no_importers_outside_the_package (no behaviour change)", not unsanctioned,
              {"unsanctioned": unsanctioned, "wiring_points": list(WIRING_POINTS)})
    curves_checks(rep)
    from . import clock as CK
    from . import com
    from . import win32 as W
    from .device import NativeDevice
    exports = {k: bool(v) for k, v in W.FLAT_EXPORTS.items()}
    rep.check("api.flat_exports_present (P0)", all(exports.values()), exports)
    mon = W.primary_monitor()
    t0 = time.perf_counter()
    dev = NativeDevice(mon["hmonitor"] if mon else None)
    try:
        info = dict(dev.info)
        info["create_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        rep.data["device"] = info
        rep.check("device.on_monitor_adapter", (info.get("d3d11") or {}).get("path") == "monitor_adapter",
                  info.get("d3d11"))
        rep.check("device.timeFrequency_equals_qpf (G1-8)", info["timeFrequency_equals_qpf"],
                  {"timeFrequency": info["timeFrequency"], "qpf": info["qpf"]})
        rep.check("device.state_valid", dev.check_device_state() and dev.removed_reason() == 0)
        clock = CK.StageClock(dev.time_frequency, dev.qpf, qpc=W.qpc)
        rep.check("clock.begin_mode_absolute", clock.begin_mode == CK.BEGIN_ABSOLUTE, {"mode": clock.begin_mode,
                                                                                      "perf_offset_s": clock.perf_offset_s})
        ok, slots, disc, disc_ok = slot_matrix(dev)
        rep.check("h6.slots_S_OK_without_a_target", ok, slots)
        rep.check("h6.setclip_discriminator (slot 13 is the object overload)", disc_ok)
        rep.check("h6.anim_overloads_refuse_NULL (informational)", all(v != "0x00000000" for v in disc.values()),
                  disc, gate=False)
        import random
        rnd = random.Random(5)
        data = bytes(rnd.randrange(256) for _ in range(37 * 21 * 4))
        s = dev.create_surface(37, 21, False, "readback")
        match = dev.upload(s, 37, 21, data, "readback", verify=True)
        dev.release(s)
        rep.check("upload.readback_at_the_atlas_offset (UpdateSubresource slot)", match is True)
        fs = dev.frame_statistics()
        rate = fs.rateNum / fs.rateDen if fs.rateDen else 0
        rep.check("stats.frame_statistics_rate", rate > 0, {"rate_hz": round(rate, 3)})
        hosts = hidden_host_checks(dev)
        rep.check("host.hidden_roles_styles_notifications_target",
                  all(h.get("ok") for h in hosts.values()) and hosts["click_eating"].get("target_ok"), hosts)
        cont = probe_continuity(dev, clock, detents=20 if quick else 60)
        rep.check("builder.h7_continuity_float32 (G1-7)", cont["ok"], cont)
        rep.data["gil_push"] = gil_push_bench(dev)
        rep.check("bench.pyfunctype_push_33_calls_under_hog_p95<=0.05ms (P0, informational)",
                  rep.data["gil_push"]["hog"]["p95"] <= 0.05, rep.data["gil_push"], gate=False)
        rep.data["stats_reads"] = stats_read_bench(dev)
        rep.check("bench.statistics_reads_keep_the_gil (G1-1, informational)", True, rep.data["stats_reads"],
                  gate=False)
        rep.data["clock_probe"] = clock_probe()
        rep.check("clock.compositor_wait_return (G1-2, informational)", True, rep.data["clock_probe"], gate=False)
    finally:
        n = dev.teardown()
        rep.check("device.teardown_released_everything", dev.alive() == 0, {"released": n})
    from . import bench
    for table in ("32:9",) if quick else ("32:9", "16:9"):
        b = bench.run("native", table, 25, 20.0, "none", detents=10 if quick else 20)
        rep.data[f"bench_{table}"] = b
        # G1-4: "H5 gates it on the 32:9 table at 20 detents/s" (the G1 notes win over §6.6's
        # "reported, not gated"); the 16:9 table is reported.
        rep.check(f"bench.per_detent_wake_to_commit_{table}_p95<=1.5ms (H5{' gate, G1-4' if table == '32:9' else ''})",
                  b["gate_1_5ms_p95"], {k: b[k] for k in ("wake_to_commit_ms", "calls_per_detent",
                                                        "anims_per_detent", "us_per_call", "over_1_5ms")},
                  gate=table == "32:9")
    if not quick:
        b = bench.run("native", "32:9", 25, 20.0, "burst")
        rep.data["bench_32:9_burst"] = b
        rep.check("bench.per_detent_under_burst_hog (informational; §6.3 stress allows 2 P)", True,
                  {k: b[k] for k in ("wake_to_commit_ms", "over_1_5ms")}, gate=False)
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--json", default=None)
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args(argv)
    t0 = time.perf_counter()
    rep = run(quick=a.quick)
    gated = [c for c in rep.checks if c["gate"]]
    summary = {"pass": rep.passed, "gated": len(gated), "gated_passed": sum(1 for c in gated if c["ok"]),
               "informational": len(rep.checks) - len(gated), "seconds": round(time.perf_counter() - t0, 1)}
    print(json.dumps(summary))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump({"summary": summary, "checks": rep.checks, "data": rep.data}, fh, indent=1, default=str)
    return 0 if rep.passed else 1


if __name__ == "__main__":
    sys.exit(main())
