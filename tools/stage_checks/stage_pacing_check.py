"""G1-10 supervised pacing check for the WP7a stage engine (DESKTOP_STAGE "[G1] Spike results" G1-10).

WP7a WROTE THIS SCRIPT BUT NEVER RAN IT. It shows a full-screen overlay: run it only from the main
session, with the user's explicit go-ahead, the user at the PC:

    cd app
    .venv\\Scripts\\python.exe -I ..\\tools\\stage_checks\\stage_pacing_check.py --run --i-have-go-ahead [--no-capture]

``--run`` first runs this file's own headless ``--selftest`` in a child process (hidden host, never
shown; the watchdogs are proven on throw-away children) and starts the on-screen child only when
that passed on the same source. The on-screen child is killed at 60 s whatever happens.

What G1-10 asks: "WP7a's first supervised on-screen check repeats one normal pacing pass, with the
witness, on §2.1's click-eating host (0x08200088) with IDCompositionVisual3::SetOpacity, or else
adopts the spike's proven pair." So the on-screen child (about 12 s of animation):
- shows the stage's **click-eating host** (``control_center.stage.host``, not layered, not
  transparent, WS_EX_NOACTIVATE) over the primary monitor with ``SetWindowPos(SWP_NOACTIVATE |
  SWP_NOOWNERZORDER | SWP_SHOWWINDOW)`` only. It eats every click for those seconds and never takes
  focus; keys stay with the foreground app;
- builds the stage's probe scene (32 numbered synthetic covers, the 32:9 table at k = 2) with
  **Visual3 opacity** and the real builder (``StageCore`` / ``Batch``), over a frost from one desktop
  snapshot taken before showing (kept in memory only; ``--no-capture`` uses the tint-only frost);
- a black witness band at the top: W1, a 16 px square ramping at 560 px/s through the judged
  window, and W2, a 16 px square moving 48 px per detent, retargeted like a card;
- one **normal** condition: 24 detents at 10/s, 24 back at 20/s, 50 reversals at 20/s, 0.5 s idle,
  after a 1 s static baseline; then the close fade and the hide;
- frame statistics harvested every 100 ms on the stage thread through GIL-keeping reads (G1-1),
  counted with running counters on the vblank grid (G1-3), plus the P9 history probe at the end;
- a capture thread strip-captures the two witness rows (our own band only).

Pass (recorded in ``diagnostics\\stage-pacing-<stamp>-onscreen.json``): §6.3's explorer row on the
normal condition (fps >= 0.979 x rate, p95 <= 1.1 P, p99 and max <= 2.02 P); wake -> Commit <= 1.5 ms
p95 (G1-4); the static windows quiet (<= 5 % presents per vblank); W1 and W2 visible and on their
twins; the foreground window unchanged; closed by the script; no host window left.

Safety (the G1 spike's design): the animation closes itself after at most 30 s; a Python watchdog
thread posts an abort at 38 s and hard-exits 3 s later; a native thread-pool timer whose callback IS
kernel32!TerminateProcess kills the process at 44 s even with the GIL held forever; the runner
kills the child at 60 s. The global hotkey **Ctrl+Alt+F12** aborts at once. Primary monitor only.
The script refuses to show anything while the display sleeps or the session is locked. No serial
port, knob, network, Sonos, Apple Music, registry write, Tk or companion start; nothing of the
user's is moved; the desktop snapshot never leaves memory.
"""
from __future__ import annotations

import argparse
import ctypes as C
import ctypes.wintypes as WT
import datetime
import hashlib
import heapq
import json
import os
import subprocess
import sys
import threading
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ND = os.path.normpath(os.path.join(HERE, "..", "..", "app"))
if ND not in sys.path:
    sys.path.insert(0, ND)
DIAG = os.path.join(ND, "diagnostics")

ANIMATION_CAP_S = 30.0
PY_WATCHDOG_S = 38.0
NATIVE_WATCHDOG_S = 44.0
HARD_KILL_S = 60.0
EXIT_OK, EXIT_NATIVE_WD, EXIT_FAILED, EXIT_PY_WD, EXIT_EXCEPTION, EXIT_ABORTED = 0, 1, 2, 3, 4, 5

BAND_H = 56
ROW_A_Y, ROW_B_Y = 6, 32              # tops of the 16 px witness rows (W2 on A, W1 on B)
W1_X0, W2_X0 = 700, 200
WITNESS_SPEED = 560.0                  # px/s = 2.33 px per 240 Hz frame
DWITNESS_STEP = 48
HARVEST_S = 0.100                      # 100 ms (§19.2's P9 fallback), the 250 ms history is probed
SEG_FULL, SEG_DRY = (24, 24, 50), (8, 8, 16)
LEAD_S, IDLE_S, BASELINE_S, REV_TAIL_S = 0.1, 0.5, 1.0, 0.45
N_ITEMS, FOCUS0 = 32, 5
WM_HOTKEY, WM_APP_ABORT = 0x0312, 0x8000 + 0x21
HOTKEY_ID, MOD_ALT, MOD_CONTROL, MOD_NOREPEAT, VK_F12 = 0xB1, 0x1, 0x2, 0x4000, 0x7B
CREATE_NO_WINDOW = 0x08000000

_k32 = C.WinDLL("kernel32", use_last_error=True)
_u32 = C.WinDLL("user32", use_last_error=True)
_winmm = C.WinDLL("winmm")
_k32.CreateTimerQueueTimer.restype = WT.BOOL
_k32.CreateTimerQueueTimer.argtypes = [C.POINTER(C.c_void_p), C.c_void_p, C.c_void_p, C.c_void_p, WT.DWORD, WT.DWORD,
                                       C.c_ulong]
_k32.DeleteTimerQueueTimer.restype = WT.BOOL
_k32.DeleteTimerQueueTimer.argtypes = [C.c_void_p, C.c_void_p, C.c_void_p]
_u32.RegisterHotKey.restype = WT.BOOL
_u32.RegisterHotKey.argtypes = [WT.HWND, C.c_int, WT.UINT, WT.UINT]
_u32.UnregisterHotKey.restype = WT.BOOL
_u32.UnregisterHotKey.argtypes = [WT.HWND, C.c_int]
_u32.FindWindowW.restype = WT.HWND
_u32.FindWindowW.argtypes = [WT.LPCWSTR, WT.LPCWSTR]
_u32.OpenInputDesktop.restype = C.c_void_p
_u32.OpenInputDesktop.argtypes = [WT.DWORD, WT.BOOL, WT.DWORD]
_u32.CloseDesktop.restype = WT.BOOL
_u32.CloseDesktop.argtypes = [C.c_void_p]
_u32.GetUserObjectInformationW.restype = WT.BOOL
_u32.GetUserObjectInformationW.argtypes = [C.c_void_p, C.c_int, C.c_void_p, WT.DWORD, C.POINTER(WT.DWORD)]
_winmm.timeBeginPeriod.restype = WT.UINT
_winmm.timeBeginPeriod.argtypes = [WT.UINT]
_winmm.timeEndPeriod.restype = WT.UINT
_winmm.timeEndPeriod.argtypes = [WT.UINT]
_TERMINATE_PROCESS = C.cast(_k32.TerminateProcess, C.c_void_p).value


def source_hash() -> str:
    h = hashlib.sha256()
    with open(os.path.abspath(__file__), "rb") as fh:
        h.update(fh.read())
    stage = os.path.join(ND, "control_center", "stage")
    for name in sorted(os.listdir(stage)):
        if name.endswith(".py"):
            with open(os.path.join(stage, name), "rb") as fh:
                h.update(name.encode() + b"\0" + fh.read())
    return h.hexdigest()


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, default=str)
    os.replace(tmp, path)


class Log:
    def __init__(self, echo=True):
        self.t0 = time.perf_counter()
        self.lines = []
        self.echo = echo

    def __call__(self, msg):
        line = f"{time.perf_counter() - self.t0:8.3f} {msg}"
        self.lines.append(line)
        if self.echo:
            print(line, flush=True)


# ============================================================================ watchdogs
def arm_native_watchdog(due_ms: int):
    """A GIL-independent kill switch: a thread-pool timer whose callback IS TerminateProcess
    (param = (HANDLE)-1 = this process; the exit code's low byte = the callback's TRUE = 1)."""
    h = C.c_void_p()
    if not _k32.CreateTimerQueueTimer(C.byref(h), None, C.c_void_p(_TERMINATE_PROCESS), C.c_void_p(-1), int(due_ms), 0,
                                      0x8 | 0x20):                  # WT_EXECUTEONLYONCE | WT_EXECUTEINTIMERTHREAD
        raise C.WinError(C.get_last_error())
    return h.value


def disarm_native_watchdog(h) -> bool:
    return bool(h) and bool(_k32.DeleteTimerQueueTimer(None, C.c_void_p(h), C.c_void_p(-1)))


class PyWatchdog(threading.Thread):
    """At the deadline: post an abort to the host, then hard-exit 3 s later."""

    def __init__(self, deadline_s, get_hwnd):
        super().__init__(name="stage-check-watchdog", daemon=True)
        self.deadline = time.perf_counter() + deadline_s
        self.get_hwnd = get_hwnd
        self.done = threading.Event()
        self.fired = False

    def run(self):
        if self.done.wait(max(0.0, self.deadline - time.perf_counter())):
            return
        self.fired = True
        try:
            hwnd = self.get_hwnd()
            if hwnd:
                _u32.PostMessageW(hwnd, WM_APP_ABORT, 0, 0)
        except BaseException:
            pass
        if self.done.wait(3.0):
            return
        os._exit(EXIT_PY_WD)


def watchdog_probe_child(kind):
    t0 = time.perf_counter()
    if kind.startswith("native"):
        arm_native_watchdog(1000)
        print(f"armed {time.perf_counter() - t0:.3f}", flush=True)
        if kind == "native-gil":
            C.PYFUNCTYPE(None, WT.DWORD)(("Sleep", _k32))(10000)        # the GIL held inside C for 10 s
        else:
            time.sleep(10)
        print("survived (watchdog failed)", flush=True)
        return 0
    wd = PyWatchdog(0.5, lambda: 0)
    wd.start()
    print(f"armed {time.perf_counter() - t0:.3f}", flush=True)
    time.sleep(10)
    print("survived (watchdog failed)", flush=True)
    return 0


def watchdog_probes():
    procs = {}
    for kind in ("native-sleep", "native-gil", "python-stuck"):
        procs[kind] = (time.perf_counter(), subprocess.Popen(
            [sys.executable, "-I", os.path.abspath(__file__), "--watchdog-probe", kind], stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, creationflags=CREATE_NO_WINDOW))
    out = {}
    for kind, (t0, p) in procs.items():
        try:
            p.wait(timeout=15)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
        tail = p.stdout.read().decode(errors="replace").strip().splitlines()[-2:]
        out[kind] = {"exit": p.returncode, "low_byte": p.returncode & 0xFF, "elapsed_s": round(time.perf_counter() - t0, 2),
                     "tail": tail}
    ok = (out["native-sleep"]["low_byte"] == EXIT_NATIVE_WD and out["native-sleep"]["elapsed_s"] < 4.0
          and out["native-gil"]["low_byte"] == EXIT_NATIVE_WD and out["native-gil"]["elapsed_s"] < 4.0
          and out["python-stuck"]["exit"] == EXIT_PY_WD and out["python-stuck"]["elapsed_s"] < 7.0
          and not any("survived" in " ".join(v["tail"]) for v in out.values()))
    return ok, out


# ============================================================================ display state
def display_usable():
    """Refuse while the display sleeps (the compositor clock answers 0xC01E0006 at once, G1-2) or
    while the session is locked (the input desktop is not 'Default')."""
    from control_center.stage import win32 as W
    out = {}
    f = W.DCompositionWaitForCompositorClock
    if f is not None:
        codes = [f(0, None, 100) & 0xFFFFFFFF for _ in range(3)]
        out["clock_codes"] = [hex(c) for c in codes]
        out["occluded"] = all(c == 0xC01E0006 for c in codes)
    h = _u32.OpenInputDesktop(0, False, 0x0100)
    name = None
    if h:
        buf = C.create_unicode_buffer(64)
        n = WT.DWORD()
        _u32.GetUserObjectInformationW(h, 2, C.cast(buf, C.c_void_p), 128, C.byref(n))
        name = buf.value
        _u32.CloseDesktop(h)
    out["input_desktop"] = name
    out["usable"] = not out.get("occluded") and name == "Default"
    return out


# ============================================================================ witness capture
class StripGrabber:
    """BitBlt of a 1-px row of the screen into a 32-bit DIB (our own witness band only)."""

    def __init__(self, x, y, w):
        from control_center.stage import win32 as W
        self.W = W
        self.x, self.y, self.w = int(x), int(y), int(w)
        self.screen = W.GetDC(None)
        self.mdc = W.CreateCompatibleDC(self.screen)
        bmi = W.BITMAPINFOHEADER(C.sizeof(W.BITMAPINFOHEADER), self.w, -1, 1, 32, 0, 0, 0, 0, 0, 0)
        self.bits = C.c_void_p()
        self.dib = W.CreateDIBSection(self.screen, C.byref(bmi), 0, C.byref(self.bits), None, 0)
        self.old = W.SelectObject(self.mdc, self.dib)

    def grab(self):
        W = self.W
        if not W.BitBlt(self.mdc, 0, 0, self.w, 1, self.screen, self.x, self.y, W.SRCCOPY | W.CAPTUREBLT):
            return None
        W.GdiFlush()
        return bytes((C.c_ubyte * (self.w * 4)).from_address(self.bits.value))[1::4]      # the G channel

    def close(self):
        W = self.W
        if self.old:
            W.SelectObject(self.mdc, self.old)
        if self.dib:
            W.DeleteObject(self.dib)
        if self.mdc:
            W.DeleteDC(self.mdc)
        W.ReleaseDC(None, self.screen)


class WitnessCapture(threading.Thread):
    def __init__(self, strips, qpc, period_s=0.0015, max_samples=30000):
        super().__init__(name="stage-check-witness", daemon=True)
        self.strips = strips              # [(key, x0, y, w)]
        self.qpc = qpc
        self.period_s = period_s
        self.samples = {k: [] for k, *_ in strips}
        self.stop_ev = threading.Event()
        self.max_samples = max_samples
        self.error = None

    def run(self):
        from control_center.stage import proof as PF
        grabbers = []
        try:
            grabbers = [(k, x0, StripGrabber(x0, y, w)) for k, x0, y, w in self.strips]
            n = 0
            while not self.stop_ev.wait(self.period_s) and n < self.max_samples:
                for key, x0, g in grabbers:
                    ta = self.qpc()
                    row = g.grab()
                    tb = self.qpc()
                    c = PF.run_centroid(row) if row is not None else None
                    self.samples[key].append(((ta + tb) // 2, (tb - ta) // 2,
                                              None if c is None else x0 + c - 7.5))
                n += 1
        except BaseException as exc:
            self.error = repr(exc)
        finally:
            for _k, _x, g in grabbers:
                try:
                    g.close()
                except Exception:
                    pass

    def stop(self):
        self.stop_ev.set()
        self.join(2.0)


# ============================================================================ the check
def check_input(notify, on_abort):
    """The stage's click-eating HostInput plus this script's abort paths (the hotkey and the
    watchdog's posted message)."""
    from control_center.stage import host as HO

    class CheckInput(HO.HostInput):
        def handle(self, msg, wp, lp):
            if msg == WM_HOTKEY:
                on_abort("hotkey")
                return 0
            if msg == WM_APP_ABORT:
                on_abort("py_watchdog")
                return 0
            return super().handle(msg, wp, lp)
    return CheckInput(HO.ROLE_CLICK_EATING, notify)


def numbered_covers(n, cs):
    from PIL import Image, ImageDraw, ImageFont
    import colorsys
    try:
        font = ImageFont.truetype(os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "segoeuib.ttf"),
                                  int(cs * 0.4))
    except OSError:
        font = ImageFont.load_default()
    out = []
    for i in range(n):
        r, g, b = colorsys.hsv_to_rgb((i * 0.618033988749895) % 1.0, 0.6, 0.85)
        img = Image.new("RGB", (cs, cs), (int(r * 255), int(g * 255), int(b * 255)))
        d = ImageDraw.Draw(img)
        txt = f"{i + 1:02d}"
        bb = d.textbbox((0, 0), txt, font=font)
        d.text(((cs - bb[2] + bb[0]) / 2 - bb[0], (cs - bb[3] + bb[1]) / 2 - bb[1]), txt, font=font, fill=(255, 255, 255))
        out.append(img)
    return out


class Check:
    def __init__(self, args, log, onscreen: bool):
        from control_center.stage import win32 as W
        self.W = W
        self.args = args
        self.log = log
        self.onscreen = onscreen
        self.res = {"schema": "nanod.stage-pacing-check/1", "mode": "onscreen" if onscreen else "selftest",
                    "started": datetime.datetime.now().isoformat(timespec="seconds"), "source_sha256": source_hash(),
                    "python": sys.version.split()[0], "checks": [], "errors": []}
        self.abort_reason = None
        self.closed_by = None
        self.queue = []
        self.seq = 0
        self.stop_loop = False
        self.detents = []
        self.phases = []
        self.cur_phase = None
        self.w1_hist = []
        self.w2_hist = []
        self.harvest = None
        self.host = None
        self.dev = None
        self.timer = None
        self.witness = None
        self.native_wd = None
        self.py_wd = None
        self.hotkey = False
        self.torn_down = False
        self.T0 = None
        self.span = None
        self.w1_speed = WITNESS_SPEED

    def check(self, name, ok, detail=None, gate=True):
        self.res["checks"].append({"name": name, "ok": bool(ok), "gate": gate, "detail": detail})
        self.log(f"[{'PASS' if ok else ('FAIL' if gate else 'info')}] {name}  "
                 + (json.dumps(detail, default=str)[:300] if detail is not None else ""))
        return ok

    def abort(self, reason):
        if self.abort_reason is None:
            self.abort_reason = reason
            self.log(f"abort requested: {reason}")

    def notify(self, kind):
        if kind in ("lock", "sleep", "display", "display_off", "endsession"):
            self.abort(kind)

    # ------------------------------------------------------------------ build
    def build(self):
        from control_center.stage import blur as B
        from control_center.stage import clock as CK
        from control_center.stage import curves as CV
        from control_center.stage import frames as FR
        from control_center.stage import host as HO
        from control_center.stage.bench import _Holder
        from control_center.stage.capture import screen_grab
        from control_center.stage.device import NativeDevice
        from control_center.stage.engine import SceneContext, StageCore
        from control_center.stage.layout import StageLayout
        from control_center.stage.probe_scene import ProbeScene, probe_payload
        from control_center.stage.surfaces import opaque_bytes
        from control_center.stage.tree import OPACITY_VISUAL3, Tree
        W = self.W
        W.SetThreadDpiAwarenessContext(W.DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
        W.SetThreadPriority(W.GetCurrentThread(), W.THREAD_PRIORITY_ABOVE_NORMAL)
        mon = W.primary_monitor()
        self.mon = mon
        lay = StageLayout(mon["rect"])
        self.lay = lay
        self.res["monitor"] = {"rect": mon["rect"], "layout": lay.describe()}
        CV.prewarm()
        t0 = time.perf_counter()
        self.dev = dev = NativeDevice(mon["hmonitor"])
        self.res["device"] = {k: v for k, v in dev.info.items() if k != "adapters"}
        self.res["device"]["create_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        if not dev.info["timeFrequency_equals_qpf"]:
            raise RuntimeError("timeFrequency != QPF: this check needs absolute begin times (G1-8)")
        self.clock = clock = CK.StageClock(dev.time_frequency, dev.qpf, qpc=W.qpc)
        key = W.adapter_for_display(mon["device"])
        self.res["target_key"] = list(key) if key else None
        self.harvest = FR.CompositorHarvest(FR.NativeStatsReader(key))
        self.core = core = StageCore(dev, clock, harvest=None)
        capture = None
        if self.onscreen and not self.args.no_capture:
            t0 = time.perf_counter()
            capture = screen_grab(lay.monitor)                      # before the host is shown (§4.9)
            self.res["capture_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        self.host = HO.HostWindow(check_input(self.notify, self.abort), hidden_only=not self.onscreen)
        self.res["host"] = {"ex_style": hex(self.host.ex_style()), "role": HO.ROLE_CLICK_EATING,
                            "visible_after_create": self.host.info["visible_after_create"]}
        self.host.register_notifications()
        if self.onscreen:
            self.hotkey = bool(_u32.RegisterHotKey(self.host.hwnd, HOTKEY_ID, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT,
                                                   VK_F12))
        self.res["hotkey_ctrl_alt_f12"] = self.hotkey
        self.target = dev.create_target(self.host.hwnd)
        self.tree = tree = Tree(dev, OPACITY_VISUAL3)
        root = tree.root()
        self.root, self.root_op = root, tree.opacity(root, 0.0)
        recipe = B.RECIPES["blur.explorer"]
        frost, src = B.frost(capture, recipe, lay.k, (lay.W, lay.H))
        capture = None                                              # the snapshot lives only on the GPU
        self.res["frost"] = src
        w, h, data = opaque_bytes(frost)
        fs = dev.create_surface(w, h, True, "frost")
        dev.upload(fs, w, h, data, "frost")
        fv = tree.visual("frost", content=fs)
        sc, dx, dy = B.frost_placement(recipe)
        tree.matrix(fv, sc, sc, dx, dy)
        tree.add(root, fv)
        container = tree.visual("scene")
        tree.add(root, container)
        payload = probe_payload(count=N_ITEMS, index=FOCUS0, probe_covers=numbered_covers(N_ITEMS, lay.u(340)))
        self.holder = _Holder(dev)
        ctx = SceneContext(self.holder, core, tree, lay, "explorer", payload)
        self.scene = ProbeScene(ctx, payload)
        self.scene.build(payload, container)
        band = tree.visual("band", content=self.holder.solids.get((0, 0, 0), lay.W, BAND_H))
        tree.add(root, band)
        white = self.holder.solids.get((255, 255, 255), 16, 16)
        self.w1v = tree.visual("w1", content=white)
        tree.offset(self.w1v, W1_X0, ROW_B_Y)
        self.w2v = tree.visual("w2", content=white)
        tree.offset(self.w2v, W2_X0, ROW_A_Y)
        tree.add(root, self.w1v)
        tree.add(root, self.w2v)
        self.w1 = tree.offset_x(self.w1v, float(W1_X0))
        self.w2 = tree.offset_x(self.w2v, float(W2_X0))
        self.w1_hist.append((0, self.w1.func))
        self.w2_hist.append((0, self.w2.func))
        dev.set_root(self.target, root.ptr)
        dev.commit()
        dev.wait_commit()
        self.timer = W.CreateWaitableTimerExW(None, None, W.CREATE_WAITABLE_TIMER_HIGH_RESOLUTION, W.TIMER_ALL_ACCESS)

    # ------------------------------------------------------------------ scheduler
    def at(self, due, fn):
        self.seq += 1
        heapq.heappush(self.queue, (int(due), self.seq, fn))

    def loop(self):
        from control_center.stage.host import pump_messages
        W = self.W
        handles = (C.c_void_p * 1)(self.timer)
        while not self.stop_loop:
            if self.abort_reason and not self.closed_by:
                self.instant_close(self.abort_reason)
                break
            now = self.clock.now()
            if self.T0 and (now - self.T0) / self.clock.freq > ANIMATION_CAP_S and not self.closed_by:
                self.instant_close("animation_cap_30s")
                break
            while self.queue and self.queue[0][0] <= now and not self.stop_loop:
                due, _s, fn = heapq.heappop(self.queue)
                fn(due)
                now = self.clock.now()
            if self.stop_loop or not self.queue:
                break
            if pump_messages(W) < 0:
                self.abort("quit")
            if self.abort_reason and not self.closed_by:
                continue                                  # handled at the top of the next turn
            wait = self.queue[0][0] - self.clock.now()
            if wait <= 0:
                continue
            rel = C.c_int64(-max(1, int(wait * 1e7 / self.clock.freq)))
            W.SetWaitableTimer(self.timer, C.byref(rel), 0, None, None, False)
            W.MsgWaitForMultipleObjectsEx(1, handles, 100, W.QS_ALLINPUT, W.MWMO_INPUTAVAILABLE)

    def phase(self, name, kind, witness_span=None):
        def fn(due):
            now = self.clock.now()
            if self.cur_phase is not None:
                self.cur_phase["q1"] = now
                self.phases.append(self.cur_phase)
            self.cur_phase = {"name": name, "kind": kind, "q0": now}
            if witness_span:
                b = self.core.batch()
                b.to(self.w1, W1_X0 + self.w1_speed * witness_span, witness_span * 1000.0, "LINEAR",
                     v_from=float(W1_X0), force=True)
                b.commit()
                self.w1_hist.append((b.t1, self.w1.func))
                self.cur_phase["witness"] = [b.t1, b.t1 + int(witness_span * self.clock.freq)]
        return fn

    def detent(self, step):
        def fn(due):
            t_wake = time.perf_counter()
            w_q = self.clock.now()
            b = self.core.batch(t_wake)
            self.scene.turn(b, self.scene.focus + step)
            k = max(0, self.scene.focus - FOCUS0)
            before = self.w2.func
            b.to(self.w2, float(W2_X0 + k * DWITNESS_STEP), 420, "OUT")
            b.commit()
            done = self.clock.now()
            if self.w2.func is not before:
                self.w2_hist.append((b.t1, self.w2.func))
            self.detents.append({"phase": self.cur_phase["name"] if self.cur_phase else None, "t1": b.t1,
                                 "done": done, "wake_q": w_q, "due": due, "work_ms": b.work_ms, "calls": b.calls,
                                 "anims": b.anims, "commit_ms": b.commit_ms})
        return fn

    def harvest_tick(self, due):
        try:
            self.harvest.harvest(True)
        except Exception as exc:
            self.res["errors"].append("harvest: " + repr(exc))
        self.at(due + int(HARVEST_S * self.clock.freq), self.harvest_tick)

    def close_anim(self, due):
        if self.closed_by:
            return
        b = self.core.batch()
        b.to(self.root_op, 0.0, 340, "OUT", force=True)
        b.commit()
        self.closed_by = "scenario_end"
        self.at(b.t1 + int(0.34 * self.clock.freq) + int(2 * self.core.period), self.finish)

    def finish(self, due):
        if self.cur_phase is not None:
            self.cur_phase["q1"] = self.clock.now()
            self.phases.append(self.cur_phase)
            self.cur_phase = None
        self.host.hide()
        self.stop_loop = True

    def instant_close(self, reason):
        self.log(f"instant close: {reason}")
        self.closed_by = reason
        try:
            self.host.hide()
        finally:
            self.stop_loop = True
            self.queue.clear()

    def schedule(self, T0, seg):
        f = self.clock.freq
        q = lambda s: T0 + int(s * f)           # noqa: E731
        n_a, n_b, n_r = seg
        span = (LEAD_S + 0.1 * n_a) + (LEAD_S + 0.05 * n_b) + (LEAD_S + 0.05 * (n_r - 1) + REV_TAIL_S)
        self.span = span
        self.w1_speed = min(WITNESS_SPEED, (self.lay.W - 400 - W1_X0) / span)
        t = 1.0
        self.at(q(t), self.phase("baseline", "static"))
        t += BASELINE_S
        self.at(q(t), self.phase("a10", "motion", witness_span=span))
        for i in range(n_a):
            self.at(q(t + LEAD_S + 0.1 * i), self.detent(+1))
        t += LEAD_S + 0.1 * n_a
        self.at(q(t), self.phase("b20", "motion"))
        for i in range(n_b):
            self.at(q(t + LEAD_S + 0.05 * i), self.detent(-1))
        t += LEAD_S + 0.05 * n_b
        self.at(q(t), self.phase("rev20", "motion"))
        for i in range(n_r):
            self.at(q(t + LEAD_S + 0.05 * i), self.detent(+1 if i % 2 == 0 else -1))
        t += LEAD_S + 0.05 * (n_r - 1) + REV_TAIL_S
        self.at(q(t), self.phase("idle", "static"))
        t += IDLE_S
        self.at(q(t), self.close_anim)
        self.at(T0, self.harvest_tick)
        return t + 0.34

    # ------------------------------------------------------------------ run
    def run_scenario(self, seg):
        W = self.W
        self.res["foreground_before"] = W.GetForegroundWindow() or 0
        self.harvest.start()
        b = self.core.batch()
        b.to(self.root_op, 1.0, 340, "OUT", v_from=0.0, force=True)
        self.scene.open(b, {})
        b.commit()
        self.T0 = b.t1
        if self.onscreen:
            self.res["boost_on"] = hex((W.DCompositionBoostCompositorClock(True) or 0) & 0xFFFFFFFF) \
                if W.DCompositionBoostCompositorClock else None
            self.res["shown"] = self.host.show(self.lay.monitor)
            self.res["foreground_after_show"] = W.GetForegroundWindow() or 0
            if not self.args.no_witness:
                self.witness = WitnessCapture([("w1", W1_X0 - 10, ROW_B_Y + 8, int(self.lay.W - 400 - W1_X0 + 40)),
                                               ("w2", W2_X0 - 10, ROW_A_Y + 8, 26 * DWITNESS_STEP + 40)], W.qpc)
                self.witness.start()
        fs = self.dev.frame_statistics()
        self.res["rate_hz"] = round(fs.rateNum / fs.rateDen, 4) if fs.rateDen else None
        self.res["planned_s"] = round(self.schedule(self.T0, seg), 2)
        try:
            self.loop()
        finally:
            if self.witness is not None:
                self.witness.stop()
            self.host.hide()
            if self.onscreen and W.DCompositionBoostCompositorClock:
                self.res["boost_off"] = hex((W.DCompositionBoostCompositorClock(False) or 0) & 0xFFFFFFFF)
            self.res["foreground_after"] = W.GetForegroundWindow() or 0
            self.res["closed_by"] = self.closed_by
            self.res["animation_s"] = round((self.clock.now() - self.T0) / self.clock.freq, 3)
            try:
                self.harvest.harvest(True)
            except Exception:
                pass
            self.p9_probe()

    def p9_probe(self):
        """P9 on screen: after the last harvest, is a frame 250, 500 and 1000 ms old still answered?"""
        from control_center.stage import proof as PF
        rd = self.harvest.reader
        last = rd.completed_id()
        if last is None:
            self.res["p9"] = None
            return
        out = {}
        for label, wait in (("250ms", 0.25), ("500ms", 0.25), ("1000ms", 0.5)):
            time.sleep(wait)
            out.update(PF.history_probe(rd.completed_id() or last, rd.frame, [(label, last)]))
        self.res["p9"] = out

    def teardown(self):
        if self.torn_down:
            return
        self.torn_down = True
        info = {}
        for step in ("hide", "hotkey", "notifications", "release", "destroy", "timer"):
            try:
                if step == "hide" and self.host is not None:
                    self.host.hide()
                elif step == "hotkey" and self.hotkey:
                    _u32.UnregisterHotKey(self.host.hwnd, HOTKEY_ID)
                elif step == "notifications" and self.host is not None:
                    self.host.unregister_notifications()
                elif step == "release" and self.dev is not None:
                    try:
                        self.dev.set_root(self.target, None)
                        self.dev.commit()
                    except Exception:
                        pass
                    info["released"] = self.dev.teardown()
                elif step == "destroy" and self.host is not None:
                    self.host.destroy()
                    info["window_destroyed"] = True
                elif step == "timer" and self.timer:
                    self.W.CloseHandle(self.timer)
                    self.timer = None
            except Exception as exc:
                info[step + "_error"] = repr(exc)
        self.res["teardown"] = info

    # ------------------------------------------------------------------ analysis
    def analyze(self):
        from control_center.stage import frames as FR
        from control_center.stage import proof as PF
        P = self.core.period
        freq = self.clock.freq
        frames, unknown = self.harvest.frames, self.harvest.unknown
        self.res["harvest"] = {"frames": len(frames), "unknown_ranges": len(unknown),
                               "unknown_ids": sum(b - a + 1 for a, b in unknown), "harvests": self.harvest.harvests}
        ph = {p["name"]: p for p in self.phases}
        rate = self.res.get("rate_hz") or 240.0
        out = {}
        if all(k in ph for k in ("a10", "b20", "rev20")):
            ws, we = ph["a10"]["q0"], ph["rev20"]["q1"]
            work = [d["work_ms"] for d in self.detents if d["work_ms"] is not None]
            ep = FR.episode_from_frames(frames, unknown, ws, we, P, freq, rate_hz=rate)
            verdict = FR.judge_stage(ep, rate, work)
            out["normal"] = {"episode": ep, "verdict": verdict, "work_ms": FR.summary(work),
                             "calls": FR.summary([d["calls"] for d in self.detents], 1),
                             "commit_ms": FR.summary([d["commit_ms"] for d in self.detents])}
            _ks, cls = PF.pickup_classes(frames, self.detents, P)
            out["normal"]["pickup"] = cls
            statics = [(p["q0"], p["q1"]) for p in self.phases if p["kind"] == "static"]
            out["quiet"] = PF.quiet_ratio(frames, statics, P)
            if self.witness is not None:
                w1_win = [tuple(ph["a10"].get("witness", (ws, we)))]
                out["w1"] = PF.witness_judge(self.witness.samples["w1"], PF.twin_range_fn(self.w1_hist), P,
                                             windows=w1_win)
                out["w2"] = PF.witness_judge(self.witness.samples["w2"], PF.twin_range_fn(self.w2_hist), P,
                                             windows=[(ws, we)])
                out["witness_error"] = self.witness.error
        self.res["analysis"] = out
        return out


def run_selftest(args, log) -> int:
    """Headless: the whole build on the real device with the host hidden (never shown), a scaled
    dry run of the schedule, the analysis on what the hidden run produced, and the watchdogs."""
    from control_center.stage import selftest as ST
    ck = Check(args, log, onscreen=False)
    res = ck.res
    path = os.path.join(DIAG, f"stage-pacing-{args.run_id}.json")
    code = EXIT_FAILED
    try:
        ck.native_wd = arm_native_watchdog(int(NATIVE_WATCHDOG_S * 1000) + 60000)
        scan = ST.static_scan()
        ck.check("stage.static_scan", not scan["hits"], scan["hits"][:10])
        ck.build()
        ck.check("host.click_eating_style_hidden", int(res["host"]["ex_style"], 16) == 0x08200088
                 and not res["host"]["visible_after_create"])
        ck.check("device.timeFrequency_equals_qpf", res["device"]["timeFrequency_equals_qpf"])
        ck.run_scenario(SEG_DRY)
        ck.check("dryrun.closed_by_scenario_end", ck.closed_by == "scenario_end", ck.closed_by)
        ck.check("dryrun.all_detents", len(ck.detents) == sum(SEG_DRY), len(ck.detents))
        ck.check("dryrun.never_visible", not ck.host.visible())
        ck.teardown()
        ck.check("teardown.clean", "release_error" not in res["teardown"] and res["teardown"].get("window_destroyed"),
                 res["teardown"])
        a = ck.analyze()
        ck.check("dryrun.analysis_blocks", "normal" in a and "quiet" in a, list(a))
        ok, wd = watchdog_probes()
        ck.check("watchdogs.native_and_python_kill", ok, wd)
        code = EXIT_OK if all(c["ok"] for c in res["checks"] if c["gate"]) else EXIT_FAILED
    except BaseException as exc:
        res["errors"].append(traceback.format_exc())
        log("EXCEPTION " + repr(exc))
        code = EXIT_EXCEPTION
    finally:
        try:
            ck.teardown()
        except Exception:
            pass
        res["pass"] = code == EXIT_OK
        res["exit_code"] = code
        res["log"] = log.lines[-300:]
        write_json(path, res)
        disarm_native_watchdog(ck.native_wd)
    log(f"selftest {'PASSED' if code == EXIT_OK else 'FAILED'} -> {path}")
    return code


def run_onscreen(args, log) -> int:
    ck = Check(args, log, onscreen=True)
    res = ck.res
    path = os.path.join(DIAG, f"stage-pacing-{args.run_id}.json")
    code = EXIT_FAILED
    period_set = False
    try:
        ck.native_wd = arm_native_watchdog(int(NATIVE_WATCHDOG_S * 1000))
        ck.py_wd = PyWatchdog(PY_WATCHDOG_S, lambda: ck.host.hwnd if ck.host else 0)
        ck.py_wd.start()
        period_set = _winmm.timeBeginPeriod(1) == 0
        sys.setswitchinterval(0.001)
        res["display_state"] = display_usable()
        if not res["display_state"]["usable"]:
            res["refused"] = "display not usable (asleep or locked)"
            log("refusing: " + res["refused"])
            return EXIT_ABORTED
        ck.build()
        ck.run_scenario(SEG_FULL)
        ck.teardown()                                               # the window is gone before the analysis
        a = ck.analyze()
        n = a.get("normal") or {}
        verdict = {"judge_6_3": (n.get("verdict") or {}).get("pass"),
                   "work_p95_le_1_5ms": ((n.get("work_ms") or {}).get("p95") or 99) <= 1.5,
                   "quiet_baseline": (a.get("quiet") or {}).get("quiet"),
                   "w1": (a.get("w1") or {}).get("pass"), "w2": (a.get("w2") or {}).get("pass"),
                   "foreground_unchanged": res.get("foreground_before") == res.get("foreground_after"),
                   "closed_by_script": ck.closed_by == "scenario_end"}
        res["verdict"] = verdict
        res["pass"] = all(v is True for v in verdict.values())
        code = EXIT_OK if ck.closed_by == "scenario_end" else EXIT_ABORTED
    except BaseException as exc:
        res["errors"].append(traceback.format_exc())
        log("EXCEPTION " + repr(exc))
        code = EXIT_EXCEPTION
    finally:
        try:
            ck.teardown()
        except Exception:
            res["errors"].append(traceback.format_exc())
        if ck.py_wd:
            ck.py_wd.done.set()
        if period_set:
            _winmm.timeEndPeriod(1)
        res["exit_code"] = code
        res["log"] = log.lines[-300:]
        destroyed = ck.host is None or bool((res.get("teardown") or {}).get("window_destroyed"))
        try:
            write_json(path, res)
        finally:
            if destroyed:
                disarm_native_watchdog(ck.native_wd)
    log(f"onscreen run finished (exit {code}) -> {path}")
    return code


def run_runner(args, log) -> int:
    """Selftest child first (same source), then one on-screen child with a hard kill."""
    from control_center.stage.host import CLASS_NAME
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    src = source_hash()
    me = os.path.abspath(__file__)
    st_id = f"{stamp}-selftest"
    log("selftest child ...")
    try:
        p = subprocess.run([sys.executable, "-I", me, "--selftest", "--run-id", st_id, "--quiet"],
                           creationflags=CREATE_NO_WINDOW, timeout=180)
        st_rc = p.returncode
    except subprocess.TimeoutExpired:
        st_rc = "timeout"
    st_path = os.path.join(DIAG, f"stage-pacing-{st_id}.json")
    try:
        with open(st_path, encoding="utf-8") as fh:
            st = json.load(fh)
    except OSError:
        st = {}
    if st_rc != 0 or not st.get("pass") or st.get("source_sha256") != src:
        log(f"refusing the on-screen pass: selftest exit {st_rc}, pass {st.get('pass')}, "
            f"same source {st.get('source_sha256') == src}")
        return EXIT_FAILED
    on_id = f"{stamp}-onscreen"
    cmd = [sys.executable, "-I", me, "--child-onscreen", "--i-have-go-ahead", "--run-id", on_id]
    if args.no_capture:
        cmd.append("--no-capture")
    if args.no_witness:
        cmd.append("--no-witness")
    log("on-screen child (Ctrl+Alt+F12 aborts; killed at 60 s) ...")
    t0 = time.perf_counter()
    child = subprocess.Popen(cmd, creationflags=CREATE_NO_WINDOW)
    killed = False
    try:
        rc = child.wait(timeout=HARD_KILL_S)
    except subprocess.TimeoutExpired:
        child.kill()
        rc = child.wait()
        killed = True
    left = bool(_u32.FindWindowW(CLASS_NAME, None))
    summary = {"exit": rc, "killed": killed, "seconds": round(time.perf_counter() - t0, 2), "host_window_left": left}
    path = os.path.join(DIAG, f"stage-pacing-{on_id}.json")
    try:
        with open(path, encoding="utf-8") as fh:
            r = json.load(fh)
        summary.update({"pass": r.get("pass"), "verdict": r.get("verdict"), "closed_by": r.get("closed_by"),
                        "result": path})
    except OSError:
        summary["result"] = None
    write_json(os.path.join(DIAG, f"stage-pacing-{stamp}-summary.json"), summary)
    log(json.dumps(summary, default=str))
    return EXIT_OK if summary.get("pass") and not killed and not left else EXIT_FAILED


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--run", action="store_true", help="the runner: selftest, then one on-screen child")
    g.add_argument("--selftest", action="store_true", help="headless; the host is never shown")
    g.add_argument("--child-onscreen", action="store_true", help=argparse.SUPPRESS)
    g.add_argument("--watchdog-probe", choices=["native-sleep", "native-gil", "python-stuck"], help=argparse.SUPPRESS)
    ap.add_argument("--i-have-go-ahead", action="store_true")
    ap.add_argument("--no-capture", action="store_true", help="tint-only frost instead of a desktop snapshot")
    ap.add_argument("--no-witness", action="store_true", help="skip the witness strip capture")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    if a.watchdog_probe:
        return watchdog_probe_child(a.watchdog_probe)
    a.run_id = a.run_id or datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    log = Log(echo=not a.quiet)
    if a.selftest:
        return run_selftest(a, log)
    if not a.i_have_go_ahead:
        print("refusing: the on-screen pass needs --i-have-go-ahead (the user's explicit OK, given in chat)")
        return EXIT_FAILED
    if a.run:
        return run_runner(a, log)
    return run_onscreen(a, log)


if __name__ == "__main__":
    sys.exit(main())
