"""The drop classes of the 2026-09-26 on-screen tours, reproduced headlessly and shown fixed (the
frame-drop diagnosis; ``control_center.stage.engine`` module docstring, S1-S3; ``carousel.LoopPacer``, P1).

- **S1** (stage uploads): on the old engine an upload wake revealed what it uploaded with a Commit in
  the same wake, every wake; an upload-carrying Commit blocks until about two frames after the
  previous one (``stage.device`` docstring, measured), so those reveal Commits took 4-8 ms on screen,
  and an upload whose reveal made no call rode the next detent's Commit. Tours E and U on the fake
  rig (the fake device models the spacing: ``FakeDevice.throttled``): only the open's Commit carries
  uploads, no turn / art / switch / shuffle Commit does, and no Commit of the whole tour would wait.
- **S2** (the open): a cold device pays its first upload Commit at creation (``prime``), and an
  open whose upload-carrying Commit would wait for that spacing places t1 after it (no leading gap).
- **S3** (holds): Up next's heart pop holds 1.5 for 40 ms (§4.6.4); DWM composes nothing there
  and the judge counted it as a missed frame (on screen: 184 of 192 frames, 1 missed, 1 double,
  step 9). The episode's change model finds the hold; §6.3's in-motion figures pass.
- **P1** (the picker's 120 lock): the frames that ran an open's setup or the frost's upload reach the
  pacer as one-off frames, and the GPU chrome's detent frames stay out of P5's window.

Headless: the fake device, fake hosts, synchronous capture and art, one fake clock. Nothing is shown.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = Path(__file__).resolve().parent
for path in (ROOT, TESTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from control_center.stage import animation as AN  # noqa: E402
from control_center.stage import fake as F  # noqa: E402
from control_center.stage import frames as FR  # noqa: E402
from control_center.stage import surfaces as SU  # noqa: E402

RATE = 240.0


def _pattern():
    """§6.4's detent pattern: 20 at 10/s, 20 at 20/s, 10 reversals at 20/s (delay s, step)."""
    return [(0.1, +1)] * 20 + [(0.05, +1)] * 20 + [(0.05, +1 if i % 2 == 0 else -1) for i in range(10)]


def explorer_tour(rig):
    """Tour E on the rig (music_tours' script): the spin with K3's window pushes, a source switch
    and back, Play."""
    from control_center.stage.scenes import testing as T
    items = T.explorer_payload(0.0, recent="many", art="mixed", window=False)["items"]
    index, rev = 30, 1
    rig.presenter.explorer_open(T.explorer_payload(rig.now(), index=index, recent="many", art="mixed"))
    rig.settle()
    rig.advance(1200, 50)
    first = max(0, index - 12)
    for delay, step in _pattern():
        rig.advance(delay * 1000.0, 50)
        index = max(0, min(len(items) - 1, index + step))
        p = {"index": index, "control_id": 1, "bump": 0}
        f = max(0, index - 12)
        if f != first:
            first = f
            p.update(items=items[f:index + 17], items_first=f, items_rev=rev)
        rig.presenter.explorer_highlight(p)
        rig.settle()
    rig.advance(600, 50)
    for cid, payload in ((2, T.explorer_payload(rig.now(), source="favourites", index=3, favs="many")),
                         (3, T.explorer_payload(rig.now(), index=index, recent="many", art="mixed"))):
        rev += 1
        sw = {k: payload[k] for k in ("source", "state", "index", "count", "items", "items_first")}
        sw.update(t0=rig.now(), items_rev=rev, control_id=cid)
        rig.presenter.explorer_source(sw)
        rig.settle()
        rig.advance(800, 50)
    rig.presenter.explorer_close({"t0": rig.now(), "reason": "play", "close_at_ms": 380})
    rig.settle()
    rig.advance(1400, 50)


def upnext_tour(rig, like=True):
    """Tour U on the rig: the spin, Shuffle on and off, a Like, Play."""
    from control_center.stage.scenes import testing as T
    now = 20
    p = T.upnext_payload(rig.now(), kind="playlist", rows=60, now=now, art="mixed", liked=(3, 9))
    count = p["count"]
    rig.presenter.upnext_open(p)
    rig.settle()
    rig.advance(1200, 50)
    focus = now
    for delay, step in _pattern():
        rig.advance(delay * 1000.0, 50)
        focus = max(0, min(count - 1, focus + step))
        rig.presenter.upnext_highlight({"index": focus, "control_id": 1, "bump": 0})
        rig.settle()
    rig.advance(800, 50)
    rows = p["rows"]
    shuffled = [dict(r, row=j + 1) for j, r in enumerate(rows[:now + 1] + list(reversed(rows[now + 1:])))]
    base = {"now": now, "count": count, "card": None, "likes_known": True}
    for cid, (new_rows, mode) in enumerate(((shuffled, "companion"), (rows, "off")), 2):
        rig.presenter.upnext_rows(dict(base, t0=rig.now(), reason="shuffle", rows=new_rows, focus=now + 1,
                                       shuffle=mode, control_id=cid))
        rig.settle()
        rig.advance(1000, 50)
    if like:
        rig.presenter.upnext_rows(dict(base, t0=rig.now(), reason="likes", rows=[{"row": now + 2, "liked": True}],
                                       focus=now + 1, shuffle="off"))
        rig.settle()
        rig.advance(1200, 50)
    rig.presenter.upnext_close({"t0": rig.now(), "reason": "play", "close_at_ms": 380})
    rig.settle()
    rig.advance(1400, 50)


def _rig(monitor="32:9"):
    from control_center.stage.scenes import testing as T
    return T.SceneRig(monitor, keep_pixels=False)


class UploadDisciplineTests(unittest.TestCase):
    """S1: no input or reveal Commit carries an upload, and no Commit waits for the spacing."""

    def check_tour(self, rig):
        core_counts = dict(rig.engine.core.commits_with_uploads) if rig.engine.core else {}
        self.assertEqual(core_counts, {"open": 1}, core_counts)          # only the open's own Commit
        self.assertEqual(rig.dev.throttled, [], rig.dev.throttled[:3])  # no Commit waits (the native spacing)
        self.assertEqual(rig.engine.core.upload_commit_waits, 0)
        up = rig.engine.uploads
        self.assertGreater(up.stats["commits"], 10)                    # the tour's art went through upload wakes
        self.assertLessEqual(up.stats["bytes_max"], SU.UPLOAD_BUDGET_BYTES)
        self.assertEqual(rig.dev.violations, [])
        self.assertTrue(all(e["uploads"] == 0 or e["wait_s"] == 0.0 for e in rig.dev.commit_log))

    def test_tour_e_32x9(self):
        rig = _rig("32:9")
        explorer_tour(rig)
        self.check_tour(rig)
        self.assertEqual([k for k, _p in rig.events()], ["opened", "closed"])

    def test_tour_e_16x9(self):
        rig = _rig("16:9")
        explorer_tour(rig)
        self.check_tour(rig)

    def test_tour_u_32x9(self):
        rig = _rig("32:9")
        upnext_tour(rig)
        self.check_tour(rig)
        self.assertEqual([k for k, _p in rig.events()], ["opened", "closed"])

    def test_a_surface_is_bound_only_a_frame_after_its_upload_commit(self):
        """Every content bind of a revealed surface comes at least READY_S after the Commit that
        carried its upload (the picker chrome's rule, now the stage's)."""
        from control_center.stage.scenes import testing as T
        rig = _rig("32:9")
        committed = {}                                          # surface -> the time its upload was committed
        rig.presenter.explorer_open(T.explorer_payload(rig.now(), index=30, recent="many", art="mixed"))
        rig.settle()
        dev = rig.dev
        pending = []
        orig_upload, orig_commit = dev.upload, dev.commit
        binds = []

        def upload(surface, *a, **k):
            pending.append(surface)
            return orig_upload(surface, *a, **k)

        def commit():
            r = orig_commit()
            for s in pending:
                committed[s] = dev.now()
            pending.clear()
            return r
        dev.upload, dev.commit = upload, commit
        orig_apply = dev._apply

        def _apply(name, p, args):
            if name == "Visual.SetContent" and args and args[0] in committed:
                binds.append(dev.now() - committed[args[0]])
            return orig_apply(name, p, args)
        dev._apply = _apply
        rig.advance(1500, 50)
        for idx in range(31, 45):
            rig.presenter.explorer_highlight({"index": idx, "control_id": 1, "bump": 0})
            rig.settle()
            rig.advance(50, 50)
        rig.advance(800, 50)
        self.assertGreater(len(binds), 20)
        self.assertGreaterEqual(min(binds), SU.READY_S - 1e-6, sorted(binds)[:5])


class PrimingFakeDevice(F.FakeDevice):
    """The fake device with ``NativeDevice.prime``'s effect: one upload-carrying Commit at creation."""

    def prime(self):
        s = self.create_surface(8, 8, True, "prime")
        self.upload(s, 8, 8, bytes(256), "prime")
        self.flush()
        self.commit()
        self.release(s)


class OpenTests(unittest.TestCase):
    """S2: the device's first upload Commit at creation; the open's t1 after its Commit can return."""

    def rig(self):
        import test_stage_engine as TE
        r = TE.Rig()
        devs = r.devices

        def factory():
            d = PrimingFakeDevice(r.clk)
            devs.append(d)
            return d
        r.engine.device_factory = factory
        return r

    def test_a_cold_open_right_after_the_prime_keeps_its_first_frame_on_time(self):
        from control_center.stage.probe_scene import probe_payload
        r = self.rig()
        r.presenter.explorer_open(probe_payload(t0=r.clk.perf()))
        r.run()
        dev = r.dev
        self.assertEqual([k for k, _p in r.events()], ["opened"])
        self.assertEqual(dev.upload_commits, 2)                        # the prime's, then the open's
        lo = r.engine.last_open
        self.assertTrue(lo["t1_pushed"])
        self.assertGreater(lo["uploads"], 0)
        wait = dev.throttled[-1]                                        # the open's Commit waits (native) ...
        returns = r.engine.core.clock.from_perf(wait["t"] + wait["wait_s"])
        root = r.engine.root_op.func
        self.assertGreaterEqual(root.begin, returns + int(0.0015 * r.clk.freq) - 1)   # ... and t1 is after that

    def test_a_warm_open_is_not_pushed(self):
        from control_center.stage.probe_scene import probe_payload
        r = self.rig()
        r.presenter.note_touch()                                        # the knob touch warms (and primes)
        r.run()
        r.clk.advance(0.5)
        r.presenter.explorer_open(probe_payload(t0=r.clk.perf()))
        r.run()
        lo = r.engine.last_open
        self.assertFalse(lo["t1_pushed"])                               # no spacing to wait for ...
        self.assertGreaterEqual(lo["t1_lead_ms"], 1000.0 / 240 - 0.01)   # ... and G1-6's largest margin, P
        self.assertLess(lo["t1_lead_ms"], 2 * 1000.0 / 240 + 0.01)
        self.assertEqual(r.dev.throttled, [])


class _Recorder:
    """Every property a committed batch programmed (its function from the batch's t1) and every
    batch t1, for an oracle of what DWM would compose (a frame exactly where a value changes)."""

    def __init__(self):
        self.props = {}                 # id(prop) -> (prop, [(t1, func)])
        self.t1s = []
        self._saved = []
        self._live = {}

    def install(self):
        rec = self
        for name in ("to", "legs", "jump"):
            orig = getattr(AN.Batch, name)

            def wrapped(batch, prop, *a, _orig=orig, **k):
                r = _orig(batch, prop, *a, **k)
                rec._live.setdefault(id(batch), {})[id(prop)] = (prop, prop.func)
                return r
            self._saved.append((name, orig))
            setattr(AN.Batch, name, wrapped)
        orig_commit = AN.Batch.commit

        def commit(batch, _orig=orig_commit):
            r = _orig(batch)
            rec.t1s.append(int(batch.t1))
            for pid, (prop, func) in rec._live.pop(id(batch), {}).items():
                rec.props.setdefault(pid, (prop, []))[1].append((int(batch.t1), func))
            return r
        self._saved.append(("commit", orig_commit))
        AN.Batch.commit = commit
        return self

    def uninstall(self):
        for name, orig in reversed(self._saved):
            setattr(AN.Batch, name, orig)
        self._saved = []

    def changed(self, t, P):
        if any(t - P < t1 <= t for t1 in self.t1s):
            return True
        for _prop, hist in self.props.values():
            f1 = f0 = None
            for t1, func in hist:
                if t1 <= t:
                    f1 = func
                if t1 <= t - P:
                    f0 = func
            if f1 is None:
                continue
            v1 = f1.value(t)
            v0 = (f0 or f1).value(t - P) if f0 is not None else None
            if v0 is None or abs(v1 - v0) > 1e-7:
                return True
        return False


def oracle_frames(rec, start, end, P, drop=()):
    """The frames DWM would compose in [start, end]: one where the picture changes."""
    frames = []
    n = 0
    fid = 1000
    while start + n * P <= end + 1:
        t = int(round(start + n * P))
        if rec.changed(t, P) and n not in drop:
            fid += 1
            frames.append(FR.TargetFrame(fid, t, t, fid, fid, start_time=t - int(P / 2), target_time=t))
        n += 1
    return frames


class HoldTests(unittest.TestCase):
    """S3: a designed hold is not a missed frame (the Up next like, 2026-09-26: 184 of 192)."""

    def heart_episode(self):
        from control_center.stage import clock as CK
        from control_center.stage.engine import StageCore
        from control_center.stage.tree import Tree
        clk = F.FakeClock()
        dev = F.FakeDevice(clk)
        core = StageCore(dev, CK.StageClock(dev.time_frequency, dev.time_frequency, qpc=clk, perf=clk.perf))
        core.read_stats()
        tree = Tree(dev)
        root = tree.root("root")
        box = tree.visual("heart", opacity=True)
        tree.add(root, box)
        fill_o = tree.opacity(box, 0.0)
        st = tree.scale_transform(box, 16.0, 16.0)
        fill_s = tree.scale(st, 32.0, 0.4, name="heart")
        rec = _Recorder().install()
        try:
            b = core.batch()
            b.to(fill_o, 1.0, 200, "OUT", v_from=0.0, force=True)                 # the filled form fades in
            b.legs(fill_s, [(0, 1.5, 380, "SPR"), (420, 1.0, 380, "SPR")], v_from=0.4)   # §4.6.4's heart
            b.commit()
            core.finish(b, "turn")
        finally:
            rec.uninstall()
        ep = core.episodes.finish()
        return core, rec, ep

    def test_the_heart_pops_hold_is_not_a_missed_frame(self):
        core, rec, ep = self.heart_episode()
        P = core.period
        frames = oracle_frames(rec, ep["start"], ep["end"], P)
        raw = FR.episode_from_frames(frames, [], ep["start"], ep["end"], P, core.clock.freq, rate_hz=RATE)
        # the on-screen record, reproduced: 192 vblanks, 8 of them without a frame, one 9 P interval
        self.assertEqual((round(raw["vblanks"]), raw["missed"], raw["double_missed"], raw["step_max"]), (192, 1, 1, 9))
        self.assertIn(raw["frames"], (184, 185))                                # the commit's own vblank counted or not
        self.assertFalse(FR.judge_stage(raw, RATE)["pass"])
        model = FR.ChangeModel(ep["batches"], P)
        got = FR.episode_from_frames(frames, [], ep["start"], ep["end"], P, core.clock.freq, rate_hz=RATE,
                                     changes=model)
        self.assertEqual((got["missed"], got["double_missed"]), (1, 1))            # the raw fields keep §6.2
        self.assertEqual(got["holds"]["intervals"], 1)
        self.assertEqual(got["holds"]["vblanks"], 8)
        self.assertEqual((got["missed_in_motion"], got["double_missed_in_motion"]), (0, 0))
        self.assertGreaterEqual(got["fps_in_motion"], 0.979 * RATE)
        verdict = FR.judge_stage(got, RATE)
        self.assertTrue(verdict["pass"], verdict)
        self.assertEqual(verdict["basis"], "in_motion")

    def test_a_frame_lost_in_motion_is_still_missed(self):
        core, rec, ep = self.heart_episode()
        P = core.period
        frames = oracle_frames(rec, ep["start"], ep["end"], P, drop=(40,))          # inside the first leg
        model = FR.ChangeModel(ep["batches"], P)
        got = FR.episode_from_frames(frames, [], ep["start"], ep["end"], P, core.clock.freq, rate_hz=RATE,
                                     changes=model)
        self.assertEqual(got["missed_in_motion"], 1)                               # a real miss stays a miss
        self.assertEqual(got["holds"]["vblanks"], 8)
        self.assertEqual(got["interval_P_in_motion"]["max"], 2.0)

    def test_the_like_on_the_up_next_scene(self):
        """The scene's own like (the heart forms, the hints, every batch of the episode): the frames
        where something changes are exactly what the model predicts, and the hold is recognised."""
        from control_center.stage.scenes import testing as T
        rig = _rig("32:9")
        now = 20
        p = T.upnext_payload(rig.now(), kind="playlist", rows=60, now=now, art="mixed", liked=(3, 9))
        rig.presenter.upnext_open(p)
        rig.settle()
        rig.advance(2500, 50)
        self.assertFalse(rig.engine.core.episodes.active)
        rec = _Recorder().install()
        try:
            rig.presenter.upnext_rows({"t0": rig.now(), "reason": "likes", "rows": [{"row": now + 2, "liked": True}],
                                       "now": now, "count": p["count"], "card": None, "likes_known": True,
                                       "focus": now, "shuffle": "off"})
            rig.settle()
            eps = rig.engine.core.episodes
            self.assertTrue(eps.active)
            start = eps.start
            ends = []
            orig_finish = AN.Episodes.finish

            def finish(e, _orig=orig_finish):
                r = _orig(e)
                ends.append(r)
                return r
            AN.Episodes.finish = finish
            try:
                rig.advance(1500, 10)
            finally:
                AN.Episodes.finish = orig_finish
        finally:
            rec.uninstall()
        ep = ends[0]
        self.assertEqual(ep["start"], start)
        P = rig.engine.core.period if rig.engine.core else rig.clk.period
        frames = oracle_frames(rec, ep["start"], ep["end"], P)
        model = FR.ChangeModel(ep["batches"], P)
        got = FR.episode_from_frames(frames, [], ep["start"], ep["end"], P, rig.clk.freq, rate_hz=RATE, changes=model)
        self.assertGreaterEqual(got["holds"]["vblanks"], 8)                           # the heart's 40 ms at least
        self.assertEqual(got["missed_in_motion"], 0, got)
        self.assertTrue(FR.judge_stage(got, RATE)["pass"])


class PickerOneOffTests(unittest.TestCase):
    """P1 at the engine: the frames that ran the open's setup and the frost's upload reach the pacer
    as one-off frames; the GPU chrome's detent frames are left out of P5's window."""

    def tearDown(self):
        from control_center import carousel as c
        c.install_gpu_chrome(None)

    def test_the_setup_and_frost_frames_are_one_off(self):
        import test_stage_picker as SP
        from control_center import carousel as c
        calls = []

        class Backend(SP.GpuBackend):
            def frame_done(self, t_wake, work_s, *, oneoff=False, p5=True):
                calls.append((oneoff, p5))
                return 1
        orig = SP.GpuBackend
        SP.GpuBackend = Backend
        try:
            rig = SP.Rig(self)
        finally:
            SP.GpuBackend = orig
        rig.open(count=12, index=4)
        oneoffs = [x for x in calls if x[0]]
        self.assertEqual(len(oneoffs), 2, calls[:6])                  # the setup frame and the frost's frame
        n = len(calls)
        rig.presenter.highlight(5)
        rig.step(0.3)
        after = calls[n:]
        self.assertTrue(after)
        self.assertGreaterEqual(sum(1 for o, p5 in after if not p5), 1)  # the detent's (and a label's) sync frame
        self.assertGreater(sum(1 for o, p5 in after if p5), 10)          # the normal frames feed P5
        self.assertFalse(any(o for o, _p5 in after))
        pacer = c.LoopPacer()
        self.assertFalse(hasattr(pacer, "LOCK_MIN_SAMPLES"))            # the frame-count minimum is gone (E-P1)
        self.assertEqual((pacer.LOCK_MIN_SPAN_S, pacer.LOCK_MIN_OVER), (0.25, 2))

    def _attribution_rig(self, cadence):
        """The picker on the GPU rig with a backend pacer held at ``cadence``; returns the rig."""
        import types
        import test_stage_picker as SP

        class Backend(SP.GpuBackend):
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                self.pacer = types.SimpleNamespace(cadence=cadence, switches=0, period=1 / 240.0, _vblank=None)

            def frame_done(self, t_wake, work_s, *, oneoff=False, p5=True):
                return self.pacer.cadence
        orig = SP.GpuBackend
        SP.GpuBackend = Backend
        try:
            return SP.Rig(self)
        finally:
            SP.GpuBackend = orig

    def test_the_picker_episodes_record_the_lock_and_the_re_registrations(self):
        """The review of the fixes (2026-09-26): the on-screen run's worst displayed episodes were snaps
        at 2 P, which points to the P5 120 lock rather than to the thumbnails' re-registration (still
        on the frame after each detent). So the re-run can settle it, every picker episode records how
        many presents ran at cadence 2 and which frames re-registered (ms from its start, and how
        long), in its record and in ``recent``, which ``picker_snap_checks`` sets against the gaps."""
        rig = self._attribution_rig(cadence=1)
        rig.open(count=12, index=4)
        for index in (5, 6, 7):
            rig.presenter.highlight(index)
            rig.step(0.1)
        rig.step(0.6)
        picker = rig.presenter.metrics()["frames"]["picker"]
        entries = picker["recent"]
        self.assertTrue(entries and all(len(e) == 5 for e in entries), entries[:2])
        turn = [e for e in entries if e[0] == "turn"][-1]
        loop = turn[4]
        self.assertEqual(loop["locked_frames"], 0)
        self.assertEqual(loop["paced_frames"], loop["presents"])
        self.assertGreaterEqual(len(loop["rereg_at_ms"]), 3)           # the frame after each detent
        self.assertTrue(all(0.0 <= at <= (turn[2] - turn[1]) * 1000.0 + 1e-6 for at in loop["rereg_at_ms"]))
        self.assertGreaterEqual(loop["rereg_ms_max"], 0.0)
        record = picker["last"] if picker["last"]["kind"] == "turn" else picker["worst"]
        for key in ("locked_frames", "paced_frames", "rereg_frames", "rereg_ms"):
            self.assertIn(key, record)
        locked = self._attribution_rig(cadence=2)
        locked.open(count=12, index=4)
        locked.presenter.highlight(5)
        locked.step(0.6)
        loop = [e for e in locked.presenter.metrics()["frames"]["picker"]["recent"] if e[0] == "turn"][-1][4]
        self.assertGreater(loop["locked_frames"], 0)
        self.assertEqual(loop["locked_frames"], loop["paced_frames"])


if __name__ == "__main__":
    unittest.main()
