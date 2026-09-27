"""The stage self-test extended with the picker's GPU chrome (step 3: DESKTOP_STAGE §6.6, §9.9, §22 Q2;
lead ruling R-h; CAROUSEL.md §12.4).

    .venv\\Scripts\\python.exe -I control_center\\stage\\picker_selftest.py [--json PATH] [--quick] [--picker-only]

(by path, as ``picker_bench``: ``-m`` cannot find the package under ``-I``.)

Runs the stage self-test with the music scenes (``stage.scenes.selftest``: the environment, H2/H3/H6/H7,
the device, the hidden hosts, the scene benches) unless ``--picker-only``, then the picker's checks:

- static: the picker's stage modules have no timers in the chrome's frame path, no focus-stealing
  call and pass no NEAREST / HARD mode; ``carousel.py``, ``carousel_render.py`` and ``windows.py`` never
  name the stage package (the wiring point hands the factory over, K4 §4.1);
- the wiring (WP7c-D11, closed by the lead's decision of 2026-09-26): ``standalone.main`` installs the
  chrome once, right before ControlCenterApp builds the WindowsAdapter, and ``ui.FastPath`` warms the
  picker with the stage at a knob touch (read from the source; neither file is imported);
- H6 for the slots step 3 adds, on a device without a target: ``IDCompositionRectangleClip``'s eight
  setters S_OK, each animation overload refusing NULL (the discriminator that proves the order), and
  ``ID3D11DeviceContext::Flush`` after an upload;
- the knob touch's device in two halves (WP7c-R6): ``D3D11CreateDevice`` on a worker thread, the
  DirectComposition half adopted on this one, a Commit, the teardown; a half never adopted released;
- end to end on the native device (no target, nothing composed): the production ``CarouselEngine``
  with its GPU chrome on both tables, warmed by a knob touch (its worker's half adopted: one device),
  through an open, turns, a snap with the tray and the fly, and the exit, on hidden carousel windows'
  real DWM thumbnails: no fallback, no device loss, every chrome object released at the close;
- the H5 benches of ``picker_bench`` (real time, real COM and DWM calls): the per-frame Python work on
  normal frames <= 1.5 ms p95 at 32:9 (the lead's target, R-h) and on detent frames <= 3.0 ms p95 (K4
  §6.3 "Picker (W), step 3"), gated on 32:9; 16:9 reported; and a 32:9 session with 30 windows whose
  card pool grows in quiet frames only (no slot made inside a sync, K4 §4.7.1, WP7c-R4), gated.

Nothing is shown: the carousel's windows are created hidden and never shown, the chrome has no target,
and the screen is never read. No serial port, network, Tk or registry access.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

if __name__ == "__main__" and not __package__:          # run by path (see the usage above)
    import os
    import runpy
    _HERE = os.path.dirname(os.path.abspath(__file__))
    sys.path[:] = [p for p in sys.path if os.path.abspath(p or os.curdir) != _HERE]
    sys.path.insert(0, os.path.dirname(os.path.dirname(_HERE)))
    runpy.run_module("control_center.stage.picker_selftest", run_name="__main__", alter_sys=True)
    sys.exit(0)

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
PICKER_MODULES = ("picker_chrome.py", "picker_device.py", "picker_testing.py", "picker_bench.py",
                  "picker_selftest.py")
FRAME_PATH = ("picker_chrome.py",)
CAROUSEL_MODULES = ("carousel.py", "carousel_render.py", "windows.py")


def static_checks():
    """(hits, carousel modules that name the stage package)."""
    from .selftest import _strip_strings_and_comments
    hits = []
    bad = ["NEAREST" + "_NEIGHBOR", "BORDER_MODE" + "_HARD", "SetFore" + "groundWindow", "SW_" + "SHOW",
           "SW_" + "RESTORE", "SetActive" + "Window", "BringWindow" + "ToTop", "import " + "tkinter",
           "import " + "serial"]
    timers = (r"\.after" + r"\(", r"\bSetTim" + r"er\(", r"\bsle" + r"ep\(")
    for name in PICKER_MODULES:
        path = os.path.join(HERE, name)
        in_doc = False
        with open(path, encoding="utf-8") as fh:
            for ln, raw in enumerate(fh, 1):
                if raw.count('"""') % 2 == 1:
                    in_doc = not in_doc
                    continue
                if in_doc:
                    continue
                code = _strip_strings_and_comments(raw)
                for b in bad:
                    if b in code:
                        hits.append(f"{name}:{ln}: {b}")
                if name in FRAME_PATH:
                    for pat in timers:
                        if re.search(pat, code):
                            hits.append(f"{name}:{ln}: timer")
    named = []
    for name in CAROUSEL_MODULES:
        with open(os.path.join(PKG, name), encoding="utf-8") as fh:
            if re.search(r"(control_center\.stage|from \.stage|from \. import stage)", fh.read()):
                named.append(name)
    return hits, named


def wiring_checks():
    """WP7c-D11 closed (the lead's decision of 2026-09-26): the wiring point's ``main`` installs the chrome
    once, right before ControlCenterApp (whose runtime builds the WindowsAdapter, and so the presenter
    that reads the factory), and the input fast path warms the picker together with the stage (one
    limiter), with the tick handing it the runtime's picker. Reads the two files' source; imports
    neither (no Tk, no serial). (ok, details)"""
    import ast
    root = os.path.dirname(PKG)
    out = {}
    with open(os.path.join(root, "standalone.py"), encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    main = funcs.get("main")
    calls = [getattr(c.func, "id", None) or getattr(c.func, "attr", None)
             for c in ast.walk(main) if isinstance(c, ast.Call)] if main else []
    at = calls.index("install_picker_chrome") if "install_picker_chrome" in calls else -1
    out["main_installs_once"] = calls.count("install_picker_chrome") == 1
    out["right_before_the_app"] = 0 <= at < len(calls) - 1 and calls[at + 1] == "ControlCenterApp"
    install = funcs.get("install_picker_chrome")
    out["install_calls_picker_chrome_install"] = bool(install) and "picker_chrome.install" in ast.unparse(install)
    with open(os.path.join(PKG, "ui.py"), encoding="utf-8") as fh:
        ui_src = fh.read()
    fast = next((n for n in ast.parse(ui_src).body if isinstance(n, ast.ClassDef) and n.name == "FastPath"), None)
    warm = next((f for f in fast.body if isinstance(f, ast.FunctionDef) and f.name == "_warm"), None) if fast else None
    warm_src = ast.unparse(warm) if warm else ""
    out["fast_path_warms_the_stage_and_the_picker"] = "for target in (stage, windows)" in warm_src \
        and "note_touch()" in warm_src and "FAST_TOUCH_SECONDS" in warm_src
    out["the_tick_hands_over_the_runtimes_picker"] = "fast.windows = warmer" in ui_src
    return all(out.values()), out


def clip_slots(dev):
    """H6: every RectangleClip setter S_OK on a device without a target; the animation overloads
    refuse NULL (E_INVALIDARG), which proves that the later-declared overload comes first."""
    from . import com
    from . import picker_chrome as PC
    out = {}
    ok = True
    clip = dev.create_rect_clip("selftest.clip")
    anim = dev.create_animation("selftest.anim")
    try:
        fr, _fb, fc, fe = dev.animation_fns()
        fr(anim)
        fc(anim, 0.0, 1.0, 0.0, 0.0, 0.0)
        fe(anim, 0.05, 1.0)
        for side in ("Left", "Top", "Right", "Bottom"):
            name = "Clip.Set" + side
            hr = PC.clip_fn(dev, name, clip)(clip, 7.5)
            null = PC.clip_fn(dev, name + ".anim", clip)(clip, None)
            bound = PC.clip_fn(dev, name + ".anim", clip)(clip, anim)
            out[name] = com.hx(hr)
            out[name + ".anim(NULL)"] = com.hx(null)
            out[name + ".anim"] = com.hx(bound)
            ok = ok and hr == 0 and (null & 0xFFFFFFFF) == 0x80070057 and bound == 0
        v = dev.create_visual("selftest.v")
        out["Visual.SetClip.object(clip)"] = com.hx(dev.fn("Visual.SetClip.object", v.ptr)(v.ptr, clip))
        dev.commit()
    finally:
        dev.release(anim)
        dev.release(clip)
    return ok, out


def context_flush(dev):
    """An upload through Surfaces (BeginDraw, UpdateSubresource, EndDraw, then the context's Flush)."""
    from PIL import Image
    from .. import carousel_render as R
    from . import picker_chrome as PC
    s = PC.Surfaces(dev)
    sp = R.Sprite.solid(Image.new("L", (33, 17), 180), (40, 80, 120))
    t = time.perf_counter()
    surface, size = s.sprite(sp, "selftest")
    ms = round((time.perf_counter() - t) * 1000, 3)
    ok = bool(surface) and size == (33, 17) and s._ctx_flush is not None
    s.release()
    dev.commit()
    return ok, {"upload_and_flush_ms": ms}


def two_halves():
    """WP7c-R6: the slow half of the chrome's device on a worker thread, the rest here."""
    import threading
    from . import picker_device as PD
    from . import win32 as W
    mon = W.primary_monitor()
    hmon = mon["hmonitor"] if mon else None
    got = {}

    def worker():
        t = time.perf_counter()
        try:
            got["half"] = PD.prepare(hmon)
        except Exception as exc:
            got["error"] = repr(exc)
        got["prepare_ms"] = round((time.perf_counter() - t) * 1000, 2)
    th = threading.Thread(target=worker, name="NanoD-chrome-warm")
    th.start()
    th.join(10.0)
    out = {k: v for k, v in got.items() if k != "half"}
    if "half" not in got:
        return False, out
    t = time.perf_counter()
    dev = PD.adopt(got["half"])
    out["adopt_ms"] = round((time.perf_counter() - t) * 1000, 2)
    try:
        v = dev.create_visual("selftest.halves.v")
        s = dev.create_surface(4, 4, False, "selftest.halves.s")
        dev.upload(s, 4, 4, bytes(64), "selftest.halves.s")
        out["set_content"] = dev.fn("Visual.SetContent", v.ptr)(v.ptr, s)
        dev.commit()
        out["prepared_on"] = dev.info.get("prepared_on")
        out["timeFrequency_equals_qpf"] = dev.info.get("timeFrequency_equals_qpf")
        out["state_ok"] = dev.check_device_state()
    finally:
        out["released"] = dev.teardown()
    out["discard_released"] = PD.discard(PD.prepare(hmon))
    ok = (out.get("set_content") == 0 and out.get("prepared_on") == "NanoD-chrome-warm" and out.get("state_ok")
          and out["released"] > 4 and out["discard_released"] == 2)
    return ok, out


def end_to_end(ratio):
    """The engine with its GPU chrome on the native device (no target) and real DWM thumbnails of hidden
    windows, warmed by a knob touch: an open, turns, a snap and the exit; then the close releases every
    chrome object."""
    from . import picker_bench as B
    from . import picker_testing as PT
    dwm = B.DwmThumbs()
    rig = PT.Rig(ratio, "native", dwm=dwm, labels="threaded", clock=PT.RealClock())
    out = {}
    try:
        rig.chrome.prewarm_step(None)
        rig.presenter.note_touch()                        # the worker makes the D3D11 half (WP7c-R6)
        rig.step(0)
        deadline = time.perf_counter() + 5.0
        while rig.chrome.warming and time.perf_counter() < deadline:
            rig.step(0.01)
        out["warm_adopted"] = rig.chrome.counters["warm_adopted"]
        out["warm_ms"] = rig.chrome.counters["warm_ms"]
        rig.open(count=10, index=3, settle=0.4)
        for index in (4, 5, 6, 5):
            rig.presenter.highlight(index)
            rig.step(0.08)
        rig.snap_side(5, "left")
        rig.step(0.5)
        rig.presenter.play_cancel_exit()
        rig.step(0.4)
        m = rig.presenter.metrics()
        g = m.get("gpu") or {}
        out = {"chrome": m.get("chrome"), "gpu_sessions": m.get("gpu_sessions"), "fallbacks": m.get("gpu_fallbacks"),
               "syncs": g.get("syncs"), "device_lost": g.get("device_lost"), "failures": g.get("failures"),
               "last_error": g.get("last_error"), "late_uploads": g.get("late_uploads"),
               "device_create_ms": g.get("device_create_ms"), "device_creates": g.get("device_creates"),
               "dwm_register_failures": dwm.fail, "warm_adopted": out.get("warm_adopted"),
               "warm_ms": out.get("warm_ms")}
        dev = rig.chrome.dev
    finally:
        rig.close()
        dwm.close()
    out["released"] = rig.chrome.dev is None
    out["ok"] = (out.get("chrome") == "gpu" and out.get("gpu_sessions") == 1 and not out.get("fallbacks")
                 and not out.get("device_lost") and not out.get("failures") and (out.get("syncs") or 0) > 5
                 and out["released"] and dev is not None and out.get("warm_adopted") == 1
                 and out.get("device_creates") == 1)
    return out


def picker_checks(rep, quick=False):
    hits, named = static_checks()
    rep.check("picker.static_timers_modes_focus_imports", not hits, hits[:20])
    rep.check("picker.carousel_modules_never_name_the_stage (K4 4.1)", not named, named)
    ok, wiring = wiring_checks()
    rep.check("picker.wired_in_the_app (installed before the WindowsAdapter, warmed by the fast path; WP7c-D11)",
              ok, wiring)
    from . import win32 as W
    from .device import NativeDevice
    mon = W.primary_monitor()
    dev = NativeDevice(mon["hmonitor"] if mon else None)
    try:
        ok, slots = clip_slots(dev)
        rep.check("picker.h6_rectangle_clip_slots_and_discriminator", ok, slots)
        ok, flush = context_flush(dev)
        rep.check("picker.h6_context_flush_after_an_upload", ok, flush)
    finally:
        dev.teardown()
    ok, halves = two_halves()
    rep.check("picker.device_in_two_halves_d3d11_on_a_worker (WP7c-R6)", ok, halves)
    for ratio in ("32:9",) if quick else ("32:9", "16:9"):
        e2e = end_to_end(ratio)
        rep.data[f"picker_end_to_end_{ratio}"] = e2e
        rep.check(f"picker.end_to_end_{ratio}_gpu_chrome_open_turns_snap_exit_close", e2e["ok"], e2e)
    from . import picker_bench as B
    for ratio in ("32:9",) if quick else ("32:9", "16:9"):
        b = B.run(ratio, "native", dwm=True, reps=1 if quick else 2, echo=False)
        rep.data[f"picker_bench_{ratio}"] = {k: v for k, v in b.items() if k != "runs"}
        gate = ratio == "32:9"
        rep.check(f"picker.bench_{ratio}_normal_frame_python_work_p95<=1.5ms (R-h{', gated' if gate else ''})",
                  b["gate_normal_1_5ms_p95"], {"normal_ms": b["normal_ms"], "range": b["normal_p95_range"],
                                               "frames": b["frames"]}, gate=gate)
        rep.check(f"picker.bench_{ratio}_detent_frame_python_work_p95<=3.0ms (K4 6.3 step 3{', gated' if gate else ''})",
                  b["gate_detent_3ms_p95"], {"detent_ms": b["detent_ms"], "sync_ms": b["sync_ms"],
                                             "range": b["detent_p95_range"], "detents": b["detents"]}, gate=gate)
    b = B.run("32:9", "native", dwm=True, reps=1, echo=False, count=30)
    rep.data["picker_bench_32:9_30_windows"] = {k: v for k, v in b.items() if k != "runs"}
    rep.check("picker.bench_32:9_30_windows_pool_grows_in_quiet_frames_only (K4 4.7.1, WP7c-R4)",
              b["slots_grown_in_sync"] == 0 and b["slots"] > 14 and not b["failures"],
              {"slots": b["slots"], "slots_grown_in_sync": b["slots_grown_in_sync"], "normal_ms": b["normal_ms"],
               "detent_ms": b["detent_ms"]})
    return rep


def run(quick=False, echo=True, picker_only=False):
    if picker_only:
        from .selftest import Report
        rep = Report(echo)
        sys.setswitchinterval(0.001)
    else:
        from .scenes import selftest as scenes
        rep = scenes.run(quick=quick, echo=echo)
    return picker_checks(rep, quick)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--json", default=None)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--picker-only", action="store_true")
    a = ap.parse_args(argv)
    t0 = time.perf_counter()
    rep = run(quick=a.quick, picker_only=a.picker_only)
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
