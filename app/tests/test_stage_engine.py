"""The stage engine with the fake device, a fake host and a synchronous capture (DESKTOP_STAGE
§2.3, §2.4, §3, §4.1-§4.3, §4.9, §5.3, §15). Headless: no window, no GPU, no screen capture."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from control_center.stage import clock as CK  # noqa: E402
from control_center.stage import com  # noqa: E402
from control_center.stage import fake as F  # noqa: E402
from control_center.stage import host as HO  # noqa: E402
from control_center.stage import presenter as PR  # noqa: E402
from control_center.stage.device import COLD, LOST, WARM, DevicePolicy  # noqa: E402
from control_center.stage.engine import StageEngine  # noqa: E402
from control_center.stage.probe_scene import ProbeScene, probe_payload  # noqa: E402

MONITOR = (0, 0, 5120, 1440)


class Rig:
    def __init__(self, *, capture_grab="gradient", defer=False, device_fails=0, scenes=None, monitor=MONITOR,
                 dpi_on_show=None, **engine_kw):
        self.clk = F.FakeClock()
        self.devices = []
        self.fail_creates = device_fails
        self.mailbox = PR.Mailbox()
        self.captures = []
        self.logs = []
        self.order = []                                   # "device" / "capture" as they happen

        def device_factory():
            self.order.append("device")
            if self.fail_creates > 0:
                self.fail_creates -= 1
                raise OSError("no device")
            d = F.FakeDevice(self.clk)
            self.devices.append(d)
            return d

        def capture_factory(cb):
            c = F.SyncCapture(cb, grab=capture_grab, defer=defer)
            submit = c.submit
            c.submit = lambda job: self.order.append("capture") or submit(job)
            self.captures.append(c)
            return c
        self.engine = StageEngine(
            self.mailbox, {"explorer": ProbeScene} if scenes is None else scenes,
            device_factory=device_factory, host_factory=lambda h: F.FakeHost(h, dpi_on_show=dpi_on_show),
            clock_factory=lambda d: CK.StageClock(d.time_frequency, d.time_frequency, qpc=self.clk, perf=self.clk.perf),
            monitor_for=lambda hwnd: monitor, capture_factory=capture_factory, log=self.logs.append,
            monotonic=self.clk.perf, **engine_kw)
        self.engine.start()
        self.presenter = PR.StagePresenter(self.engine_facade())

    def engine_facade(self):
        eng = self.engine

        class Facade:
            mailbox = self.mailbox

            def metrics(self):
                return eng.metrics()

            def close(self, timeout):
                return True
        return Facade()

    @property
    def dev(self):
        return self.devices[-1]

    @property
    def host(self):
        return self.engine.host

    def run(self):
        return self.engine.process()

    def events(self):
        """The events, with each payload's ``t0`` checked and removed."""
        out = []
        for kind, payload in self.mailbox.take_events():
            payload = dict(payload)
            t0 = payload.pop("t0")
            assert isinstance(t0, float) and t0 > 0, (kind, t0)
            out.append((kind, payload))
        return out

    def open(self, **kw):
        self.presenter.explorer_open(probe_payload(t0=self.clk.perf(), **kw))
        self.run()
        return self.events()


class OpenSequenceTests(unittest.TestCase):
    def test_open_sequence(self):
        r = Rig()
        r.presenter.set_capture_exclusions([0x111, 0x222])
        ev = r.open()
        self.assertEqual(ev, [("opened", {"surface": "explorer"})])
        self.assertTrue(r.host.shown)
        self.assertEqual(r.host.log[-1], ("show", MONITOR))
        job = r.captures[0].jobs[0]
        self.assertEqual(job.exclude, (0x111, 0x222))
        self.assertEqual(job.rect, MONITOR)
        self.assertEqual(r.captures[0].affinity_calls, [((0x111, 0x222), True), ((0x111, 0x222), False)])
        frost = [o for o in r.dev.objects.values() if o["kind"] == "surface" and o["name"] == "frost"]
        self.assertEqual(frost[0]["size"], (642, 182))                 # 640 x 180 + one reduced px each side
        root = r.engine.root
        a = r.dev.animation_of(root.ref.v3, "opacity")
        self.assertEqual(a["segs"][0][1], 0.0)                         # root 0 -> 1
        self.assertEqual(a["end"], (0.34, 1.0))
        self.assertEqual(r.dev.commits, 1)                             # one commit for the whole open
        self.assertEqual(r.engine.last_open["frost"], "snapshot")
        self.assertEqual(r.dev.violations, [])
        self.assertEqual(r.host.input.hit_rect, (2220, 296, 2900, 976))   # the centre card's rest rect

    def test_capture_failure_opens_on_tint_only(self):
        r = Rig(capture_grab=None)
        self.assertEqual(r.open(), [("opened", {"surface": "explorer"})])
        self.assertEqual(r.engine.last_open["frost"], "tint_only")

    def test_capture_timeout_then_late_result_dropped(self):
        r = Rig(defer=True)
        r.presenter.explorer_open(probe_payload(t0=r.clk.perf()))
        wake = r.run()
        self.assertAlmostEqual(wake, 0.5, places=3)
        self.assertEqual(r.events(), [])
        r.clk.advance(0.5)
        r.run()
        self.assertEqual(r.events(), [("opened", {"surface": "explorer"})])
        self.assertEqual(r.engine.last_open["frost"], "tint_only")
        self.assertEqual(r.engine.counters["capture_timeouts"], 1)
        r.captures[0].release_pending()
        r.run()
        self.assertEqual(r.events(), [])
        self.assertEqual(r.dev.violations, [])

    def test_busy_and_device_refusals(self):
        r = Rig()
        r.open()
        r.presenter.explorer_open(probe_payload(t0=r.clk.perf()))
        r.run()
        self.assertEqual(r.events(), [("refused", {"surface": "explorer", "reason": "busy"})])
        r.presenter.upnext_open({"t0": 0, "rows": [], "now": 0, "focus": 0, "count": 0, "card": None,
                                 "context": {}, "shuffle": "off", "likes_known": False, "loading": True,
                                 "control_id": 2, "control_min": 0, "reduced_motion": False, "foreground_hwnd": 0})
        r.run()
        self.assertEqual(r.events(), [("refused", {"surface": "upnext", "reason": "busy"})])

    def test_no_scene_or_no_device_is_refused_device(self):
        r = Rig(scenes={})
        self.assertEqual(r.open(), [("refused", {"surface": "explorer", "reason": "device"})])
        r2 = Rig(device_fails=5)
        self.assertEqual(r2.open(), [("refused", {"surface": "explorer", "reason": "device"})])

    def test_touch_warms_the_device(self):
        r = Rig()
        self.assertEqual(r.devices, [])
        r.presenter.note_touch()
        r.run()
        self.assertEqual(len(r.devices), 1)
        self.assertEqual(r.engine.policy.state, WARM)


class TurnAndFastPathTests(unittest.TestCase):
    def test_highlight_is_one_commit_and_equal_index_none(self):
        r = Rig()
        r.open(index=12)
        c0 = r.dev.commits
        r.clk.advance(0.05)
        r.presenter.explorer_highlight({"index": 13, "control_id": 1})
        r.run()
        self.assertEqual(r.dev.commits, c0 + 1)
        r.presenter.explorer_highlight({"index": 13, "control_id": 1})
        r.run()
        self.assertEqual(r.dev.commits, c0 + 1)

    def test_highlights_coalesce_in_the_mailbox(self):
        r = Rig()
        r.open(index=12)
        c0 = r.dev.commits
        r.presenter.explorer_highlight({"index": 13, "control_id": 1, "bump": 1})
        r.presenter.explorer_highlight({"index": 14, "control_id": 1})
        self.assertEqual(r.mailbox.coalesced, 1)
        r.run()
        self.assertEqual(r.dev.commits, c0 + 1)
        self.assertEqual(r.engine.scene.focus, 14)

    def test_fast_path_positions(self):
        r = Rig()
        r.open(index=12, control_id=7)
        r.presenter.position(7, 15)
        r.presenter.position(6, 3)                           # an older control id: discarded
        r.run()
        self.assertEqual(r.engine.scene.focus, 15)
        self.assertEqual(r.engine.counters["positions_applied"], 1)
        self.assertEqual(r.engine.counters["positions_discarded"], 1)

    def test_positions_held_back_during_play(self):
        r = Rig()
        r.open(index=12, control_id=7)
        r.presenter.explorer_close({"t0": r.clk.perf(), "reason": "play", "close_at_ms": 380})
        r.run()
        r.presenter.position(7, 16)
        r.run()
        self.assertEqual(r.engine.scene.focus, 12)
        self.assertEqual(r.engine.counters["positions_applied"], 0)

    def test_reduced_motion_latched_at_open(self):
        r = Rig()
        r.open(reduced_motion=True)
        self.assertTrue(r.engine.ctx.reduced_motion)
        self.assertTrue(r.engine.core.reduced_motion)


class CloseTests(unittest.TestCase):
    def test_animated_back_close(self):
        r = Rig()
        r.open()
        alive_open = r.dev.alive()
        r.clk.advance(1.0)
        r.run()
        r.presenter.explorer_close({"t0": r.clk.perf(), "reason": "back", "close_at_ms": 0})
        wake = r.run()
        self.assertTrue(r.host.shown)
        self.assertEqual(r.events(), [])
        self.assertIsNotNone(wake)
        self.assertLess(wake, 0.36)
        self.assertEqual(r.host.input.hit_rect, None)
        r.clk.advance(0.36)
        r.run()
        self.assertFalse(r.host.shown)
        self.assertEqual(r.events(), [("closed", {"surface": "explorer", "reason": "back"})])
        self.assertLess(r.dev.alive(), alive_open)
        self.assertIsNone(r.dev.obj(r.engine.target)["root"])
        self.assertEqual(r.dev.violations, [])
        self.assertEqual(r.engine.policy.state, WARM)

    def test_play_close_root_fade_anchored_at_t0_plus_380(self):
        r = Rig()
        r.open()
        r.clk.advance(1.0)                                    # the open fade has ended
        r.run()
        root = r.engine.root
        t0_perf = r.clk.perf()
        r.clk.advance(0.02)                                   # the post arrives 20 ms after the press
        r.presenter.explorer_close({"t0": t0_perf, "reason": "play", "close_at_ms": 380})
        r.run()
        m = r.engine.root_op.func
        self.assertEqual(m.start_tick, r.engine.core.clock.from_perf(t0_perf) + int(0.38 * r.clk.freq))
        a = r.dev.animation_of(root.ref.v3, "opacity")
        self.assertEqual(a["segs"][0][1:], (1.0, 0.0, 0.0, 0.0))       # held at 1 until t0 + 380
        r.clk.advance(0.8)
        r.run()
        self.assertEqual(r.events(), [("closed", {"surface": "explorer", "reason": "play"})])

    def test_instant_close_reasons(self):
        for reason in ("idle", "lock", "sleep", "disconnect", "group", "foreground", "source"):
            r = Rig()
            r.open()
            r.presenter.explorer_close({"t0": r.clk.perf(), "reason": reason, "close_at_ms": 0})
            r.run()
            self.assertFalse(r.host.shown, reason)
            self.assertEqual(r.events(), [("closed", {"surface": "explorer", "reason": reason})], reason)

    def test_close_while_capturing(self):
        r = Rig(defer=True)
        r.presenter.explorer_open(probe_payload(t0=r.clk.perf()))
        r.run()
        r.presenter.explorer_close({"t0": r.clk.perf(), "reason": "back", "close_at_ms": 0})
        r.run()
        self.assertEqual(r.events(), [("closed", {"surface": "explorer", "reason": "back"})])
        r.captures[0].release_pending()
        r.run()
        self.assertEqual(r.events(), [])
        self.assertFalse(r.host.shown)


class SystemTests(unittest.TestCase):
    def test_notifications_become_events(self):
        r = Rig()
        h = r.host.input.handle
        h(HO.WM_WTSSESSION_CHANGE, HO.WTS_SESSION_LOCK, 0)
        h(HO.WM_POWERBROADCAST, HO.PBT_APMSUSPEND, 0)
        h(HO.WM_SETTINGCHANGE, HO.SPI_SETCLIENTAREAANIMATION, 0)
        r.run()
        self.assertEqual(r.events(), [("system", {"kind": "lock"}), ("system", {"kind": "sleep"}),
                                      ("system", {"kind": "motion"})])

    def test_display_change_closes_instantly(self):
        r = Rig()
        r.open()
        r.host.input.handle(HO.WM_DISPLAYCHANGE, 32, 0)
        r.run()
        self.assertEqual(r.events(), [("system", {"kind": "display"}),
                                      ("closed", {"surface": "explorer", "reason": "display"})])
        self.assertFalse(r.host.shown)

    def test_display_off_stops_the_harvest_flag(self):
        r = Rig()
        r.open()
        r.host.input.power_setting = lambda lp: (True, 0)
        r.host.input.handle(HO.WM_POWERBROADCAST, HO.PBT_POWERSETTINGCHANGE, 1)
        r.run()
        self.assertFalse(r.engine.core.display_on)
        self.assertEqual(r.events(), [("system", {"kind": "sleep"})])

    def test_click_action_only_inside_the_rest_rect(self):
        r = Rig()
        r.open()
        h = r.host.input.handle
        inside, outside = HO.make_lparam(2500, 600), HO.make_lparam(100, 100)
        h(HO.WM_LBUTTONDOWN, 1, inside)
        h(HO.WM_LBUTTONUP, 0, inside)
        h(HO.WM_LBUTTONDOWN, 1, outside)
        h(HO.WM_LBUTTONUP, 0, inside)
        h(HO.WM_RBUTTONDOWN, 2, inside)
        h(HO.WM_RBUTTONUP, 0, inside)
        self.assertEqual(h(HO.WM_MOUSEWHEEL, 120 << 16, inside), 0)
        import time
        before = time.perf_counter()
        r.run()
        raw = r.mailbox.take_events()
        self.assertEqual([(k, {x: v for x, v in p.items() if x != "t0"}) for k, p in raw],
                         [("click_action", {"surface": "explorer"})])
        self.assertLessEqual(raw[0][1]["t0"], before)         # stamped when the button-up was handled

    def test_endsession_stops_without_event(self):
        r = Rig()
        r.open()
        r.host.input.handle(HO.WM_ENDSESSION, 1, 0)
        r.run()
        self.assertTrue(r.engine.stopped)
        self.assertFalse(r.host.shown)
        self.assertEqual(r.events(), [])


class DeviceLossTests(unittest.TestCase):
    def test_lost_device_closes_releases_and_recreates(self):
        r = Rig()
        r.open()
        first = r.dev
        first.fail_next("Commit", com.DXGI_ERROR_DEVICE_REMOVED)
        r.clk.advance(0.05)
        r.presenter.explorer_highlight({"index": 13, "control_id": 1})
        r.run()
        self.assertEqual(r.events(), [("closed", {"surface": "explorer", "reason": "device"})])
        self.assertIsNone(r.engine.device)
        self.assertEqual(first.alive(), 0)                          # every object released
        self.assertEqual(r.engine.policy.state, LOST)
        self.assertTrue(any("GetDeviceRemovedReason" in m for m in r.logs))
        r.run()                                                     # recreate at once
        self.assertEqual(len(r.devices), 2)
        self.assertEqual(r.engine.policy.state, WARM)
        self.assertEqual(r.open(), [("opened", {"surface": "explorer"})])

    def test_failed_build_is_refused_device(self):
        r = Rig()
        r.presenter.note_touch()
        r.run()
        r.dev.fail_next("CreateSurface", com.DXGI_ERROR_DEVICE_REMOVED)
        self.assertEqual(r.open(), [("refused", {"surface": "explorer", "reason": "device"})])


class ArtScene(ProbeScene):
    """A probe scene whose late art arrives through the upload queue (a worker's post)."""

    def build(self, payload, container):
        super().build(payload, container)
        tree = self.ctx.tree
        self.art = tree.visual("late.art", opacity=True)
        tree.add(container, self.art)
        self.art_o = tree.opacity(self.art, 0.0)
        self.revealed = []
        import threading
        th = threading.Thread(target=lambda: self.ctx.uploads.put("late", 4, 4, b"\x7f" * 64, opaque=True))
        th.start()
        th.join()

    def uploads_ready(self, batch, keys):
        self.revealed.extend(keys)
        batch.call(self.ctx.device.fn("Visual.SetContent", self.art.ptr), self.art.ptr, 0x51)
        batch.to(self.art_o, 1.0, 240, "OUT")                   # art ready: 0 -> 1 over 240 OUT (§7.6)


class UploadTests(unittest.TestCase):
    def test_late_upload_is_revealed_a_frame_after_its_own_commit(self):
        """S1 (the 2026-09-26 frame-drop fixes): an upload wake commits its uploads at once in their
        own Commit, paced two frames and 1 ms after the previous upload-carrying Commit (here the
        open's, which carried the frost); the scene's reveal (content + the fade, one batch, §4.4)
        comes a frame later as a bind-only Commit. No Commit of the model would wait."""
        from control_center.stage import surfaces as SU
        r = Rig(scenes={"explorer": ArtScene})
        r.open()
        self.assertEqual(r.engine.scene.revealed, [])
        self.assertEqual(r.dev.commits, 1)                           # the open's Commit only
        wake = r.run()
        self.assertAlmostEqual(wake, r.engine.core.upload_gap_s(), places=4)
        r.clk.advance(wake)
        r.run()                                                      # the upload wake
        self.assertEqual(r.dev.commits, 2)
        self.assertEqual(r.dev.commit_log[-1]["uploads"], 1)
        self.assertEqual(r.engine.scene.revealed, [])
        r.clk.advance(SU.READY_S)
        r.run()                                                      # a frame later: the reveal
        self.assertEqual(r.engine.scene.revealed, ["late"])
        self.assertEqual(r.dev.commits, 3)
        self.assertEqual(r.dev.commit_log[-1]["uploads"], 0)
        self.assertIsNotNone(r.dev.animation_of(r.engine.scene.art.ref.v3, "opacity"))
        self.assertEqual(r.dev.obj(r.engine.scene.art.ptr)["props"]["content"], 0x51)
        self.assertEqual(len(r.engine.uploads), 0)
        self.assertEqual(r.engine.uploads.stats["uploads"], 1)
        self.assertEqual(r.dev.throttled, [])
        self.assertEqual(r.engine.core.commits_with_uploads, {"open": 1})


class PolicyTests(unittest.TestCase):
    def test_release_after_600_s_without_a_scene(self):
        p = DevicePolicy()
        p.created(0.0)
        self.assertFalse(p.release_due(599.0))
        self.assertTrue(p.release_due(600.0))
        p.scene_opened(601.0)
        self.assertFalse(p.release_due(2000.0))
        p.scene_closed(2000.0)
        self.assertEqual(p.next_wake(), 2600.0)
        p.released(2600.0)
        self.assertEqual(p.state, COLD)
        self.assertTrue(p.want_warm(2601.0))

    def test_recreate_at_most_twice_one_second_apart(self):
        p = DevicePolicy()
        p.created(0.0)
        p.lost(10.0)
        self.assertTrue(p.recreate_due(10.0))
        p.create_failed(10.0)
        self.assertFalse(p.recreate_due(10.5))
        self.assertTrue(p.recreate_due(11.0))
        p.create_failed(11.0)
        self.assertEqual(p.state, COLD)                             # stay cold; the next open tries again
        self.assertFalse(p.recreate_due(20.0))
        self.assertTrue(p.want_warm(20.0))

    def test_engine_idle_release(self):
        r = Rig()
        r.open()
        r.presenter.explorer_close({"t0": r.clk.perf(), "reason": "idle", "close_at_ms": 0})
        wake = r.run()
        self.assertAlmostEqual(wake, 600.0, delta=1.0)
        r.clk.advance(600.0)
        r.run()
        self.assertIsNone(r.engine.device)
        self.assertEqual(r.engine.policy.state, COLD)
        self.assertEqual(r.dev.alive(), 0)


class PresenterTests(unittest.TestCase):
    def test_validation(self):
        with self.assertRaises(PR.PayloadError):
            PR.validate("explorer_open", {"t0": 1})
        with self.assertRaises(PR.PayloadError):
            PR.validate("upnext_rows", {"t0": 1, "reason": "unlike", "rows": [], "now": 0, "focus": 0, "count": 0,
                                        "card": None, "shuffle": "off", "likes_known": True})
        with self.assertRaises(PR.PayloadError):
            PR.validate("explorer_close", {"t0": 1, "reason": "whatever", "close_at_ms": 0})
        PR.validate("explorer_open", probe_payload())

    def test_highlight_merge_keeps_the_newest_nonzero_bump(self):
        """WP7a-R10: K3 always sends ``bump`` (K3 §11.1), so a waiting ±1 must survive a 0."""
        mb = PR.Mailbox()
        mb.post("explorer_highlight", {"index": 24, "control_id": 1, "bump": 1})
        mb.post("explorer_highlight", {"index": 24, "control_id": 1, "bump": 0, "items": ["x"], "items_rev": 3})
        mb.post("upnext_highlight", {"index": 5, "control_id": 2, "bump": -1})
        mb.post("upnext_highlight", {"index": 4, "control_id": 2, "bump": 0})
        mb.post("explorer_highlight", {"index": 1, "control_id": 1, "bump": 1})
        mb.post("explorer_highlight", {"index": 0, "control_id": 1, "bump": -1})
        items, _pos, _touch = mb.take()
        got = [(c, p["index"], p["bump"]) for c, p, _t in items]
        self.assertEqual(got, [("explorer_highlight", 24, 1), ("upnext_highlight", 4, -1),
                               ("explorer_highlight", 0, -1)])
        self.assertEqual(items[0][1]["items"], ["x"])
        self.assertEqual(PR.merge_highlight({"index": 3, "bump": 0}, {"index": 4, "bump": 0})["bump"], 0)
        self.assertEqual(PR.merge_highlight({"index": 3}, {"index": 4})["index"], 4)
        self.assertNotIn("bump", PR.merge_highlight({"index": 3}, {"index": 4}))

    def test_pump_hands_every_event_to_the_sink(self):
        r = Rig()
        r.presenter.explorer_open(probe_payload(t0=r.clk.perf()))
        r.run()
        r.mailbox.push_event("system", {"kind": "motion"})
        got = []
        self.assertEqual(r.presenter.pump(got.append), 2)
        self.assertEqual(got[0][0], "opened")
        self.assertEqual(got[1], ("system", {"kind": "motion"}))

    def test_metrics_shape(self):
        r = Rig()
        r.open()
        m = r.presenter.metrics()
        for key in ("state", "device", "policy", "counters", "last_open", "frames", "uploads", "begin_mode"):
            self.assertIn(key, m)
        self.assertEqual(m["state"], "open")
        self.assertEqual(m["begin_mode"], "absolute")


class RecordingScene(ProbeScene):
    """A probe scene that also records every update it is given (to check order and payloads)."""

    def __init__(self, ctx, payload):
        super().__init__(ctx, payload)
        self.updates = []

    def update(self, batch, call, payload):
        self.updates.append((call, {k: v for k, v in payload.items() if k != "t0"}))
        super().update(batch, call, payload)


def _source_payload(t0, **kw):
    p = {"t0": t0, "source": "favourites", "state": "ready", "index": 3, "count": 9,
         "items": [{"title": f"Fav {i + 1}"} for i in range(9)], "items_first": 0, "items_rev": 7}
    p.update(kw)
    return p


class CaptureWindowTests(unittest.TestCase):
    """WP7a-R1: updates posted while an open is still capturing are applied in the open's batch
    (K3 §5.3.1 re-enters the knob at once; K3 §11.1 sends a patch once), never dropped."""

    def test_highlight_and_position_during_capture_reach_the_scene(self):
        r = Rig(defer=True)
        r.presenter.explorer_open(probe_payload(t0=r.clk.perf(), index=12, control_id=1))
        r.run()
        self.assertEqual(r.engine.metrics()["state"], "capturing")
        r.presenter.explorer_highlight({"index": 13, "control_id": 1, "bump": 0})
        r.presenter.position(1, 13)
        r.run()
        self.assertEqual(r.events(), [])
        r.captures[0].release_pending()
        r.run()
        self.assertEqual(r.events(), [("opened", {"surface": "explorer"})])
        self.assertEqual(r.engine.scene.focus, 13)                   # the controller's row is the one shown
        self.assertEqual(r.engine.counters["positions_discarded"], 0)
        self.assertEqual(r.engine.counters["positions_applied"], 1)
        self.assertEqual(r.engine.last_open["buffered"], {"calls": 1, "positions": 1, "positions_discarded": 0})
        self.assertEqual(r.dev.commits, 1)                           # one Commit: the open and its catch-up
        self.assertEqual(r.dev.violations, [])
        r.clk.advance(0.05)
        r.run()
        self.assertEqual(r.engine.scene.focus, 13)

    def test_highlight_in_the_same_drain_as_the_open(self):
        r = Rig()
        r.presenter.explorer_open(probe_payload(t0=r.clk.perf(), index=12))
        r.presenter.explorer_highlight({"index": 14, "control_id": 1, "bump": 0})
        r.run()
        self.assertEqual(r.events(), [("opened", {"surface": "explorer"})])
        self.assertEqual(r.engine.scene.focus, 14)

    def test_state_patch_during_a_capture_timeout(self):
        r = Rig(defer=True, scenes={"explorer": RecordingScene})
        r.presenter.explorer_open(probe_payload(t0=r.clk.perf(), index=12, state="loading"))
        r.run()
        r.clk.advance(0.2)
        r.presenter.explorer_highlight({"index": 10, "control_id": 1, "bump": 0, "state": "ready", "count": 25})
        r.run()
        r.clk.advance(0.3)                                           # the 500 ms timeout: tint-only frost
        r.run()
        self.assertEqual(r.events(), [("opened", {"surface": "explorer"})])
        self.assertEqual(r.engine.last_open["frost"], "tint_only")
        self.assertEqual(r.engine.scene.updates,
                         [("explorer_highlight", {"index": 10, "control_id": 1, "bump": 0, "state": "ready",
                                                  "count": 25})])
        self.assertEqual(r.engine.scene.focus, 10)

    def test_calls_keep_order_and_highlights_coalesce(self):
        r = Rig(defer=True, scenes={"explorer": RecordingScene})
        t0 = r.clk.perf()
        r.presenter.explorer_open(probe_payload(t0=t0, index=24, control_id=1))
        r.run()
        r.presenter.explorer_highlight({"index": 24, "control_id": 1, "bump": 1})           # a lim at the end
        r.run()
        r.presenter.explorer_highlight({"index": 23, "control_id": 1, "bump": 0, "items_rev": 2})
        r.run()
        r.presenter.explorer_source(_source_payload(t0, control_id=2))
        r.run()
        r.presenter.explorer_highlight({"index": 4, "control_id": 2, "bump": 0})
        r.run()
        r.captures[0].release_pending()
        r.run()
        calls = r.engine.scene.updates
        self.assertEqual([c for c, _p in calls], ["explorer_highlight", "explorer_source", "explorer_highlight"])
        self.assertEqual(calls[0][1], {"index": 23, "control_id": 1, "bump": 1, "items_rev": 2})   # bump kept
        self.assertEqual(calls[2][1]["index"], 4)
        self.assertEqual(r.engine.control_id, 2)                     # the newest control id wins
        self.assertEqual(r.engine.ctx.control_id, 2)
        self.assertEqual(r.engine.counters["buffered_calls"], 4)

    def test_positions_of_an_older_control_are_discarded(self):
        r = Rig(defer=True)
        t0 = r.clk.perf()
        r.presenter.explorer_open(probe_payload(t0=t0, index=12, control_id=1))
        r.run()
        r.presenter.explorer_source(_source_payload(t0, control_id=2))
        r.presenter.position(1, 20)                                  # the old source's bounds
        r.presenter.position(2, 5)
        r.run()
        r.captures[0].release_pending()
        r.run()
        self.assertEqual(r.engine.scene.focus, 5)
        self.assertEqual(r.engine.counters["positions_discarded"], 1)
        self.assertEqual(r.engine.counters["positions_applied"], 1)

    def test_close_while_capturing_drops_what_was_buffered(self):
        r = Rig(defer=True)
        r.presenter.explorer_open(probe_payload(t0=r.clk.perf(), index=12))
        r.run()
        r.presenter.explorer_highlight({"index": 13, "control_id": 1, "bump": 0})
        r.presenter.explorer_close({"t0": r.clk.perf(), "reason": "back", "close_at_ms": 0})
        r.run()
        self.assertEqual(r.events(), [("closed", {"surface": "explorer", "reason": "back"})])
        r.captures[0].release_pending()
        r.run()
        self.assertEqual(r.events(), [])
        self.assertIsNone(r.engine.scene)

    def test_end_bump_survives_a_turn_back_in_the_mailbox(self):
        """WP7a-R10 end to end: lim(+1) and the turn back coalesce, and the end bump still plays."""
        r = Rig()
        r.open(index=24, count=25)
        r.clk.advance(1.0)
        r.run()
        r.presenter.explorer_highlight({"index": 24, "control_id": 1, "bump": 1})
        r.presenter.explorer_highlight({"index": 23, "control_id": 1, "bump": 0})
        self.assertEqual(r.mailbox.coalesced, 1)
        r.run()
        m = r.engine.scene.cards_x.func
        self.assertEqual(len(m.legs), 2)                              # the two-leg end bump (S5-31)
        self.assertEqual(r.engine.scene.focus, 23)


class ColdOpenTests(unittest.TestCase):
    """WP7a-R4: §4.9 t = 0 (the capture runs while a cold device is created) and no curve
    prewarm inside a device creation or an open."""

    def test_capture_is_submitted_before_the_cold_device(self):
        r = Rig(defer=True)
        r.presenter.explorer_open(probe_payload(t0=r.clk.perf()))
        r.run()
        self.assertEqual(r.order, ["capture", "device"])
        r.captures[0].release_pending()
        r.run()
        self.assertEqual(r.events(), [("opened", {"surface": "explorer"})])
        self.assertTrue(r.engine.last_open["cold"])
        self.assertIn("device_ms", r.engine.last_open)
        self.assertIsNotNone(r.engine.last_open["open_ms"])

    def test_warm_open_is_not_cold(self):
        r = Rig()
        r.presenter.note_touch()
        r.run()
        r.open()
        self.assertFalse(r.engine.last_open["cold"])
        self.assertEqual(r.order, ["device", "capture"])

    def test_failed_device_drops_the_capture(self):
        r = Rig(defer=True, device_fails=5)
        r.presenter.explorer_open(probe_payload(t0=r.clk.perf()))
        r.run()
        self.assertEqual(r.events(), [("refused", {"surface": "explorer", "reason": "device"})])
        self.assertIsNone(r.engine.pending)
        r.captures[0].release_pending()                              # its late result opens nothing
        r.run()
        self.assertEqual(r.events(), [])
        self.assertIsNone(r.engine.scene)

    def test_device_creation_and_open_never_prewarm(self):
        from control_center.stage import curves as CV
        calls = []
        saved = CV.prewarm, CV.Prewarmer.step
        CV.prewarm = lambda *a, **k: calls.append("prewarm") or 0
        CV.Prewarmer.step = lambda self, *a, **k: calls.append("step") or False
        try:
            r = Rig()
            r.presenter.note_touch()
            r.run()
            r.open()
        finally:
            CV.prewarm, CV.Prewarmer.step = saved
        self.assertEqual(calls, [])

    def test_prewarm_runs_in_idle_wakes_only(self):
        class Pre:
            def __init__(self, n):
                self.left, self.built, self.steps = n, 0, 0

            @property
            def done(self):
                return self.left <= 0

            def step(self, budget_s=None):
                self.steps += 1
                self.left -= 1
                self.built += 1
                return self.left > 0

        pre = Pre(3)
        r = Rig(defer=True, prewarmer=pre)
        self.assertEqual(r.run(), 0.0)                                # idle: one step, then at once again
        self.assertEqual(pre.steps, 1)
        r.presenter.explorer_open(probe_payload(t0=r.clk.perf()))
        wake = r.run()
        self.assertEqual(pre.steps, 1)                                # never while an open waits for its frost
        self.assertAlmostEqual(wake, 0.5, places=3)
        r.captures[0].release_pending()
        r.run()                                                       # the open: an episode runs
        self.assertEqual(pre.steps, 1)
        r.clk.advance(1.0)
        r.run()                                                       # the episode ended: idle again
        self.assertEqual(pre.steps, 2)
        self.assertNotEqual(r.run(), 0.0)                             # the last step: no more immediate wakes
        self.assertTrue(pre.done)
        self.assertEqual(r.engine.metrics()["prewarm"], {"done": True, "built": 3, "steps": 3})


class HostDpiTests(unittest.TestCase):
    """WP7a-R5: the host's own move onto a monitor of another DPI is not a display change."""

    MON = {"rect": MONITOR, "device": None, "dpi": 144}

    def test_own_show_on_another_dpi_keeps_the_scene_open(self):
        r = Rig(monitor=self.MON, dpi_on_show=144)
        self.assertEqual(r.open(), [("opened", {"surface": "explorer"})])
        r.clk.advance(0.1)
        r.run()
        self.assertEqual(r.events(), [])
        self.assertEqual(r.engine.phase, "open")
        self.assertEqual(r.host.input.dpi_ignored, 1)
        self.assertEqual(r.host.input.expected_dpi, 144)

    def test_own_show_without_a_known_monitor_dpi(self):
        r = Rig(dpi_on_show=120)                                      # monitor_for gives no DPI
        r.open()
        r.run()
        self.assertEqual(r.events(), [])
        self.assertEqual(r.engine.phase, "open")

    def test_late_delivery_of_the_scene_dpi_is_ignored(self):
        r = Rig(monitor=self.MON)
        r.open()
        r.host.input.handle(HO.WM_DPICHANGED, (144 << 16) | 144, 0)
        r.run()
        self.assertEqual(r.events(), [])
        self.assertEqual(r.engine.phase, "open")

    def test_a_real_dpi_change_still_closes(self):
        r = Rig(monitor=self.MON, dpi_on_show=144)
        r.open()
        r.host.input.handle(HO.WM_DPICHANGED, (96 << 16) | 96, 0)    # the user changed the scale
        r.run()
        self.assertEqual(r.events(), [("system", {"kind": "display"}),
                                      ("closed", {"surface": "explorer", "reason": "display"})])
        self.assertIsNone(r.host.input.expected_dpi)


class FrameStatsExportTests(unittest.TestCase):
    """WP7a-R6 and R9: §6.2 ``cpu_pct_one_core`` per episode, the FPS HUD, no unbounded history."""

    def test_episode_records_the_stage_threads_cpu_share(self):
        cpu = [5.0]
        r = Rig(cpu_seconds=lambda: cpu[0])
        r.open()
        cpu[0] += 0.1                                                  # 100 ms of CPU ...
        r.clk.advance(1.0)                                             # ... over 1 s of episode
        r.run()
        last = r.presenter.metrics()["frames"]["explorer"]["last"]
        self.assertEqual(last["kind"], "open")
        self.assertAlmostEqual(last["cpu_pct_one_core"], 10.0, places=1)
        self.assertAlmostEqual(last["cpu_ms"], 100.0, places=1)

    def test_cpu_share_is_none_without_a_sampler(self):
        r = Rig()
        r.open()
        r.clk.advance(1.0)
        r.run()
        self.assertIsNone(r.presenter.metrics()["frames"]["explorer"]["last"]["cpu_pct_one_core"])

    def test_the_core_keeps_no_history(self):
        r = Rig()
        for _ in range(3):
            r.open()
            r.clk.advance(1.0)
            r.run()
            r.presenter.explorer_close({"t0": r.clk.perf(), "reason": "idle", "close_at_ms": 0})
            r.run()
            r.events()
        self.assertFalse(hasattr(r.engine.core, "records"))
        self.assertEqual(r.presenter.metrics()["frames"]["explorer"]["totals"]["open"]["episodes"], 3)

    def test_fps_hud(self):
        from control_center.stage.engine import hud_enabled
        self.assertTrue(hud_enabled({"NANOD_FPS_HUD": "1"}))
        self.assertFalse(hud_enabled({"NANOD_FPS_HUD": "0"}))
        self.assertFalse(hud_enabled({}))
        r = Rig(fps_hud=True)
        r.open()
        hud = r.engine.hud
        self.assertIsNotNone(hud)
        surf = r.dev.obj(hud["surface"])
        self.assertEqual(surf["uploads"], 1)                          # drawn with the open, one Commit
        self.assertEqual(r.dev.commits, 1)
        self.assertEqual(r.dev.obj(hud["visual"].ptr)["props"]["content"], hud["surface"])
        self.assertIn(hud["visual"].ptr, r.dev.obj(r.engine.root.ptr)["children"])
        self.assertLessEqual(r.run(), 0.25)
        r.clk.advance(0.25)
        r.run()
        self.assertEqual(surf["uploads"], 2)                          # 4 times a second, never per frame
        self.assertEqual(r.dev.commits, 2)
        r.clk.advance(0.1)
        r.run()
        self.assertEqual(surf["uploads"], 2)
        s = hud["surface"]
        r.presenter.explorer_close({"t0": r.clk.perf(), "reason": "idle", "close_at_ms": 0})
        r.run()
        self.assertTrue(r.dev.obj(s)["released"])
        self.assertIsNone(r.engine.hud)
        self.assertEqual(r.dev.violations, [])

    def test_no_hud_by_default(self):
        r = Rig()
        r.open()
        self.assertIsNone(r.engine.hud)
        self.assertFalse(any(o["kind"] == "surface" and o["name"] == "hud" for o in r.dev.objects.values()))


class DelayedInstantScene(ProbeScene):
    """A scene whose highlight schedules an instant change at t0 + 190 (§7.6 S5-10), the way a
    source switch or a state change moves the dots and marker."""

    def update(self, batch, call, payload):
        t0 = self.ctx.t0_ticks(payload)
        batch.to(self.marker, float(self._marker_x() + 140), 0, anchor=t0, delay_ms=190)
        batch.jump(self.cards_x, 0.0, anchor=t0, delay_ms=190)


class DelayedInstantTests(unittest.TestCase):
    def test_a_delayed_instant_change_does_not_close_the_scene(self):
        """WP7a-R3: before the fix this raised ZeroDivisionError and closed with ``device``."""
        r = Rig(scenes={"explorer": DelayedInstantScene})
        r.open()
        r.clk.advance(1.0)
        r.run()
        t0 = r.clk.perf()
        r.presenter.explorer_highlight({"index": 13, "control_id": 1, "bump": 0, "t0": t0})
        r.run()
        self.assertEqual(r.events(), [])
        self.assertEqual(r.engine.phase, "open")
        m = r.engine.scene.marker.func
        start = r.engine.core.clock.from_perf(t0) + int(0.19 * r.clk.freq)
        self.assertEqual(m.end_tick, start)
        self.assertEqual(m.value(start - 1), float(r.engine.scene._marker_x()))
        self.assertEqual(m.value(start), float(r.engine.scene._marker_x() + 140))
        self.assertEqual(r.dev.violations, [])


def _wait_for(pred, timeout=10.0):
    import time
    end = time.perf_counter() + timeout
    while time.perf_counter() < end:
        r = pred()
        if r:
            return r
        time.sleep(0.01)
    return pred()


@unittest.skipUnless(sys.platform == "win32", "Windows only")
class StageThreadTests(unittest.TestCase):
    """The real ``NanoD-stage`` thread and device, headless: the host is hidden-only (it refuses to
    show, so an open is built and committed, then answered with refused(device)) and the capture
    uses a synthetic grab (the screen is never read)."""

    def test_thread_touch_open_close(self):
        from unittest import mock
        from PIL import Image
        from control_center.stage.engine import StageThread
        logs = []
        # Hermetic (review finding RN-R5): the real host registers for GUID_CONSOLE_DISPLAY_STATE and
        # Windows answers at once with the current value. With this PC's display off that becomes
        # display_off + sleep, an event this test never caused, so the display state is pinned to "on".
        display_on = lambda lp: (True, 1)  # noqa: E731
        pinned = mock.patch.object(HO, "read_power_setting", display_on)
        pinned.start()
        self.addCleanup(pinned.stop)
        th = StageThread({"explorer": ProbeScene}, log=logs.append, host_hidden_only=True,
                         capture_grab=lambda rect: Image.new("RGB", (int(rect[2]), int(rect[3])), (40, 50, 60)))
        pres = PR.StagePresenter(th)
        try:
            self.assertIsNone(th.disabled)
            self.assertIs(th.engine.input.power_setting, display_on)    # the real host reads the pinned state
            self.assertEqual(th._thread.name, "NanoD-stage")
            pres.note_touch()
            m = _wait_for(lambda: pres.metrics().get("device"))
            self.assertTrue(m)
            self.assertEqual(pres.metrics()["begin_mode"], "absolute")
            pres.explorer_open(probe_payload(count=9, index=4))
            ev = _wait_for(lambda: pres.take_events(), 15.0)
            self.assertEqual([(k, {x: v for x, v in p.items() if x != "t0"}) for k, p in ev],
                             [("refused", {"surface": "explorer", "reason": "device"})])
            m = pres.metrics()
            self.assertEqual(m["state"], "idle")
            self.assertEqual(m["policy"], "warm")
            self.assertTrue(any("hidden-only" in s for s in logs), logs)
            self.assertIsNotNone(th.engine.cpu_seconds)                 # §6.2: both stage threads sampled
            self.assertEqual(len(th._cpu.handles), 2)
            self.assertIsNotNone(m["prewarm"])                          # WP7a-R4: warmed in idle wakes
            self.assertTrue(_wait_for(lambda: (pres.metrics().get("prewarm") or {}).get("done"), 15.0))
        finally:
            self.assertTrue(pres.close(5.0))

    def test_a_sleeping_display_never_reaches_a_hidden_only_host(self):
        """RN-R5, the stage owner's fix: a hidden-only host does not register for
        GUID_CONSOLE_DISPLAY_STATE, so the answer Windows sends at registration cannot become
        display_off + sleep. The display state reader is pinned to "off" for every message: with the
        registration this run would see a sleep; without it the open is refused(device) as in the
        self-test's end-to-end check, whatever the PC's display is doing."""
        from unittest import mock
        from PIL import Image
        from control_center.stage.engine import StageThread
        logs = []
        read = mock.Mock(return_value=(True, 0))
        pinned = mock.patch.object(HO, "read_power_setting", read)
        pinned.start()
        self.addCleanup(pinned.stop)
        th = StageThread({"explorer": ProbeScene}, log=logs.append, host_hidden_only=True,
                         capture_grab=lambda rect: Image.new("RGB", (int(rect[2]), int(rect[3])), (40, 50, 60)))
        pres = PR.StagePresenter(th)
        try:
            self.assertIsNone(th.disabled)
            self.assertTrue(_wait_for(lambda: th.engine.host is not None))
            self.assertTrue(th.engine.host.notifications["wts"])
            self.assertIsNone(th.engine.host.notifications["power"])
            pres.note_touch()
            self.assertTrue(_wait_for(lambda: pres.metrics().get("device")))
            pres.explorer_open(probe_payload(count=9, index=4))
            ev = _wait_for(lambda: pres.take_events(), 15.0)
            self.assertEqual([(k, {x: v for x, v in p.items() if x != "t0"}) for k, p in ev],
                             [("refused", {"surface": "explorer", "reason": "device"})])
            read.assert_not_called()
        finally:
            self.assertTrue(pres.close(5.0))

    def test_thread_cpu_times(self):
        import threading
        import time
        from control_center.stage import win32 as W
        tc = W.ThreadCpu([threading.get_native_id(), None, 0])
        try:
            self.assertEqual(len(tc.handles), 1)
            a = tc.seconds()
            end = time.perf_counter() + 0.25
            n = 0
            while time.perf_counter() < end:
                n += 1
            self.assertGreater(tc.seconds() - a, 0.05)
        finally:
            tc.close()
        self.assertEqual(tc.handles, [])

    def test_disabled_thread_refuses_every_open(self):
        from control_center.stage.engine import StageThread
        th = StageThread({"explorer": ProbeScene}, _fail_start=True)
        pres = PR.StagePresenter(th)
        self.assertIn("start failure", th.disabled)
        self.assertFalse(pres.explorer_open(probe_payload()))
        ev = pres.take_events()
        self.assertIn("t0", ev[0][1])
        self.assertEqual([(k, {x: v for x, v in p.items() if x != "t0"}) for k, p in ev],
                         [("refused", {"surface": "explorer", "reason": "device"})])
        self.assertEqual(pres.metrics()["state"], "disabled")
        pres.close(1.0)


if __name__ == "__main__":
    unittest.main()
