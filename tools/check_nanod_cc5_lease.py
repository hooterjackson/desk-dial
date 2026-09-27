"""Host-lease checks of the current release (nanod_cc5_tooling.CURRENT: 1.0.0-cc5.3) over RAW serial
(never DeviceBridge). Quit the companion first.

No speaker, desktop or HID actions (windowsHidEnabled is false). Frames come from the
shared contract fixtures (tests/fixtures/frames_v4.json); covers and icons are the section 5
payloads of nanod_cc5_tooling (design reference assets). Run with the companion's
interpreter: app\\.venv\\Scripts\\python.exe tools\\check_nanod_cc5_lease.py

Cases 1-4 write paced (64 B / 5 ms), as the cc5.2-era companion; cases 2b and 3b write whole
lines, as the v4 companion once artwork2 is negotiated (ARTWORK2.md section 3).
  1. Expiry: after ready, with no frames, the firmware releases with reason
     "lease-expired" about 2 s later (cc4 measured 2.07 s).
  2. Art packets alone do not renew: art lines every ~150 ms and no frames still expire
     about 2 s after ready.
  2b. Media lines alone do not renew (1.0.0-cc5.3): have queries and a cover upload, one media
     line every ~150 ms, unpaced, and no frames still expire about 2 s after ready.
  3. Frames continue during a transfer: 0.5 s heartbeats keep the control claimed across
     art transfers lasting several lease periods; every transfer commits, no error.
  3b. Frames continue during unpaced media transfers (1.0.0-cc5.3): for about 5 s (several lease
     periods) covers and icons are uploaded unpaced, a frame (whole line) naming each one before
     its begin, and INSIDE every upload (after a data ack, before the commit) the latest frame is
     written again: after the upload's first data ack and whenever 0.5 s passed since the last
     frame. An unpaced upload is usually shorter than 0.5 s, so without those frames no frame
     would ever arrive while an upload is open. Each frame must be accepted without ending the
     upload: every upload commits, no error, no media error, no release, and
     framesInsideUploads > 0.
  4. Host lost, then native handback: stopping frames expires the lease (the LCD shows the
     host-lost notice "NANO_D++ / Waiting for PC / Native controls active" - confirm by
     eye); the old control's frames are then answered "Stale control frame"; knob events
     arrive without an id (native) if you turn the knob during --observe-native-seconds;
     a new control is ready again and an intentional release is acknowledged without a
     reason. What the LCD shows is not observable over serial and is recorded as such.
  5. No reboot (1.0.0-cc5.1): {"diag":"?"} at the start and at the end must show the same
     bootCount and a later uptimeMs; a lease expiry is never a reset.
  6. Task liveness (1.0.0-cc5.2): both diag replies show every task age <= 1000 ms and no LED
     transmit failure or forced release (nanod_cc5_tooling.liveness_problems). Every release in
     cases 1-4 is acknowledged normally: a lease expiry with reason "lease-expired", the
     intentional release without a reason, never "forced".
The "artwork2" object records cases 2b and 3b (mediaOnlyDoesNotRenew,
framesDuringMediaTransfers); finalize_nanod_cc5.py requires both.
Evidence: diagnostics/cc5.3-lease-checks.json (an older one is kept as *.superseded-*; the cc5.2
evidence diagnostics/cc5-lease-checks.json is never touched).
"""
import argparse
from pathlib import Path
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nanod_cc5_tooling as t  # noqa: E402

LEASE_WINDOW = (1.5, 3.0)  # seconds after the ready reply; the firmware lease is 2000 ms


def expiry(knob, timeout=5.0):
    """Wait for the lease-expired release; returns (seconds after ready, reason)."""
    reply = knob.wait(lambda m: m.get("released") is True, timeout, "lease expiry release")
    return round(knob.now() - knob.ready_at, 3), reply.get("reason")


def media_only(knob, ident, recent, cursor):
    """Case 2b: media lines alone (have queries, then a cover upload), one every ~150 ms, unpaced."""
    cover_key, cover = cursor.cover()
    knob.enter(t.raw_control(ident, "MIDI SKIPPER", recent["ring"]["count"] - 1, recent["ring"]["index"],
                             {**recent, "artKey": cover_key}))
    released_before = len(knob.released)
    have = {"id": ident, "op": "have", "kind": "cover", "keys": [cover_key]}
    bodies = [have] * 3 + t.media_messages(ident, "cover", cover_key, cover) + [have] * 40
    acks, sent = [], 0
    for body in bodies:
        if len(knob.released) > released_before or knob.now() - knob.ready_at > 6:
            break
        ack, _ = knob.media(body)
        acks.append(ack.get("error", "ok"))
        sent += 1
        knob.pump(0.15)
    if len(knob.released) == released_before:
        seconds, reason = expiry(knob, 3.0)
    else:
        at, reason = knob.released[-1]
        seconds = round(at - knob.ready_at, 3)
    ok_before = acks.count("ok")
    return {"mediaLinesSent": sent, "secondsAfterReady": seconds, "reason": reason, "acks": acks,
            "okAcksBeforeRelease": ok_before, "unpaced": not knob.paced,
            "passed": (reason == "lease-expired" and LEASE_WINDOW[0] <= seconds <= LEASE_WINDOW[1] and ok_before >= 3)}


def last_media_ack(knob):
    """The newest mediaAck the knob sent (stop-and-wait: the answer to the line just acknowledged)."""
    return next((m["mediaAck"] for _, m in reversed(knob.messages) if isinstance(m.get("mediaAck"), dict)), {})


def frames_during_media(knob, ident, recent, windows, cursor, seconds=5.0, period=0.5):
    """Case 3b: frames (whole lines) before and inside unpaced cover and icon uploads for `seconds`.

    A frame names each cover or icon before its begin, as the v4 companion does. Inside every
    upload (media_transfer's `between`, after a data ack and so before the commit) the latest
    frame is written again after the upload's first data ack and whenever `period` s passed since
    the last frame (the companion's heartbeat). RawKnob's own heartbeats run only while it waits
    for a reply, and an unpaced upload is usually shorter than 0.5 s, so these are the frames that
    reach the knob while an upload is open. Each must be accepted without ending the upload: every
    upload still commits, with no error, media error or release; framesInsideUploads counts them.
    """
    errors_before, released_before = len(knob.errors), len(knob.released)
    media_before = len(knob.media_errors)
    knob.enter(t.raw_control(ident, "MIDI SKIPPER", recent["ring"]["count"] - 1, recent["ring"]["index"], recent))
    frames_before, started, transfers = knob.frames_sent, time.monotonic(), []
    inside = {"frames": 0, "dataAcks": 0}

    def between():
        # media_transfer calls this only after an acknowledged line; after a data ack the upload is open.
        if last_media_ack(knob).get("op") != "data":
            return
        inside["dataAcks"] += 1
        if inside["dataAcks"] == 1 or knob.clock() - knob.last_frame_at >= period:
            knob.frame(knob.latest_frame)
            inside["frames"] += 1

    def upload(kind, key, data):
        inside["dataAcks"] = 0
        return t.media_transfer(knob, ident, kind, key, data, between=between)

    while time.monotonic() - started < seconds or not transfers:
        key, cover = cursor.cover()
        knob.frame({**recent, "id": ident, "artKey": key})
        transfers.append(upload("cover", key, cover))
        icon_key, icon = cursor.icon()
        knob.frame({**windows, "id": ident, "iconKey": icon_key})
        transfers.append(upload("icon", icon_key, icon))
        if any(x["error"] for x in transfers[-2:]):
            break
    knob.pump(0.3)
    elapsed = round(time.monotonic() - started, 2)
    record = {"seconds": elapsed, "transfers": len(transfers),
              "committed": sum(1 for x in transfers if x["committed"]), "framesSent": knob.frames_sent - frames_before,
              "framesInsideUploads": inside["frames"],
              "errors": knob.errors[errors_before:], "released": knob.released[released_before:],
              "mediaErrors": knob.media_errors[media_before:], "unpaced": not knob.paced}
    record["passed"] = (not record["errors"] and not record["released"] and not record["mediaErrors"]
                        and all(x["committed"] for x in transfers) and record["framesInsideUploads"] > 0
                        and elapsed >= 4.0)
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--observe-native-seconds", type=float, default=0.0,
                        help="after the host-lost expiry, listen this long while you turn the knob")
    args = parser.parse_args(argv)
    t.console_utf8()
    t.require_companion_quit()
    p = t.CURRENT
    port = t.find_app_port()
    v4, _ = t.fixture_frames()
    home, recent, windows = v4["v4-home-now-playing"], v4["v4-recent-item-colour"], v4["v4-windows-window-rule"]
    run = uuid.uuid4().hex[:6]
    cursor = t.MediaCursor(t.cover_pool(salt=run), t.icon_pool(salt=run)) if p.artwork2 else None
    report = {"startedUtc": t.utc_stamp(), "firmwareVersion": p.version, "port": port, "externalActions": False,
              "leaseWindowSeconds": LEASE_WINDOW, "checks": [], "failures": [],
              "artwork2": {"mediaOnlyDoesNotRenew": False, "framesDuringMediaTransfers": False}}

    def check(name, ok, detail=None):
        report["checks"].append({"check": name, "passed": bool(ok), "detail": detail})
        print(f"{'PASS' if ok else 'FAIL'}  {name}", flush=True)
        if not ok:
            report["failures"].append(name)
        return ok

    knob = t.RawKnob(port)
    try:
        knob.pump(0.3)
        knob.release()
        report["diagStart"] = knob.diag()
        check("diag reports the reboot fields (resetReason, uptimeMs, bootCount)",
              not t.boot_fields_problems(report["diagStart"]), t.boot_fields_problems(report["diagStart"]))
        live = t.liveness_problems(report["diagStart"])
        check(f"start: tasks alive (every age <= {t.LIVENESS_MAX_AGE_MS} ms), no LED transmit failure, "
              "no forced release", not live, live or t.liveness_summary(report["diagStart"]))
        knob.heartbeat_seconds = 0

        # 1. Expiry without frames.
        knob.enter(t.raw_control(201, "BINARIS BEER", 100, 54, home))
        seconds, reason = expiry(knob)
        report["expiry"] = {"secondsAfterReady": seconds, "reason": reason}
        check("lease expires ~2 s after ready without frames",
              reason == "lease-expired" and LEASE_WINDOW[0] <= seconds <= LEASE_WINDOW[1], report["expiry"])

        # 2. Art packets alone do not renew the lease.
        key = f"cc5l{run}"
        knob.enter(t.raw_control(202, "MIDI SKIPPER", recent["ring"]["count"] - 1, recent["ring"]["index"],
                                 {**recent, "artKey": key}))
        released_before = len(knob.released)
        acks, sent = [], 0
        for body in t.art_messages(202, key, t.art_pixels(key)):
            if len(knob.released) > released_before:
                break
            ack, _ = knob.art(body)
            acks.append(ack.get("error", "ok"))
            sent += 1
            knob.pump(0.15)
            if knob.now() - knob.ready_at > 6:
                break
        if len(knob.released) == released_before:
            seconds, reason = expiry(knob, 3.0)
        else:
            at, reason = knob.released[-1]
            seconds = round(at - knob.ready_at, 3)
        report["artOnly"] = {"artLinesSent": sent, "secondsAfterReady": seconds, "reason": reason,
                             "acks": acks, "okAcksBeforeRelease": acks.count("ok")}
        check("art packets alone do not renew the lease",
              reason == "lease-expired" and LEASE_WINDOW[0] <= seconds <= LEASE_WINDOW[1] and acks.count("ok") >= 3,
              {k: report["artOnly"][k] for k in ("artLinesSent", "secondsAfterReady", "okAcksBeforeRelease")})

        # 2b. Media lines alone do not renew the lease (artwork2, unpaced).
        if cursor is not None:
            with t.pacing(knob, False):
                report["mediaOnly"] = media_only(knob, 205, recent, cursor)
            report["artwork2"]["mediaOnlyDoesNotRenew"] = check(
                "media lines alone do not renew the lease (have/begin/data/commit every ~150 ms, unpaced)",
                report["mediaOnly"]["passed"],
                {k: report["mediaOnly"][k] for k in ("mediaLinesSent", "secondsAfterReady", "reason",
                                                     "okAcksBeforeRelease")})

        # 3. Frames continue during transfers.
        knob.heartbeat_seconds = 0.5
        errors_before, released_before = len(knob.errors), len(knob.released)
        knob.enter(t.raw_control(206, "MIDI SKIPPER", recent["ring"]["count"] - 1, recent["ring"]["index"], recent))
        frames_before, started, transfers = knob.frames_sent, time.monotonic(), []
        while time.monotonic() - started < 5.0 or not transfers:
            key = f"cc5m{run}{len(transfers)}"
            knob.frame({**recent, "id": 206, "artKey": key})
            transfers.append(t.art_transfer(knob, 206, key, t.art_pixels(key)))
            if transfers[-1]["error"]:
                break
        knob.pump(0.3)
        report["framesDuringTransfer"] = {
            "seconds": round(time.monotonic() - started, 2), "transfers": len(transfers),
            "committed": sum(1 for x in transfers if x["committed"]), "framesSent": knob.frames_sent - frames_before,
            "errors": knob.errors[errors_before:], "released": knob.released[released_before:]}
        check("frames continue during art transfers (claimed > 2 lease periods, all committed, no error)",
              not knob.errors[errors_before:] and len(knob.released) == released_before
              and all(x["committed"] for x in transfers) and time.monotonic() - started >= 4.0,
              {k: report["framesDuringTransfer"][k] for k in ("seconds", "transfers", "committed", "framesSent")})

        # 3b. Frames continue during unpaced media transfers.
        if cursor is not None:
            with t.pacing(knob, False):
                report["framesDuringMediaTransfer"] = frames_during_media(knob, 207, recent, windows, cursor)
            report["artwork2"]["framesDuringMediaTransfers"] = check(
                "frames continue during unpaced media transfers (frames before and inside the uploads, claimed > 2 "
                "lease periods, covers and icons all committed, no error or media error)",
                report["framesDuringMediaTransfer"]["passed"],
                {k: report["framesDuringMediaTransfer"][k] for k in ("seconds", "transfers", "committed", "framesSent",
                                                                     "framesInsideUploads")})
        live_id = 207 if cursor is not None else 206

        # 4. Host lost, then native handback.
        knob.heartbeat_seconds = 0
        knob.ready_at = knob.now() - (knob.clock() - knob.last_frame_at)  # lease restarts at the last frame
        seconds, reason = expiry(knob)
        errors_before = len(knob.errors)
        knob.send({"frame": {**recent, "id": live_id}})
        stale = knob.wait(lambda m: "error" in m, 1.5, "stale frame after expiry")
        native_before = len(knob.native_events)
        if args.observe_native_seconds > 0:
            print(f"Host-lost notice should be visible. Turn the knob for {args.observe_native_seconds:.0f} s ...",
                  flush=True)
            knob.pump(args.observe_native_seconds)
        native = knob.native_events[native_before:]
        knob.heartbeat_seconds = 0.5
        knob.enter(t.raw_control(208, "BINARIS BEER", 100, 54, home))
        reentry = knob.ready_at is not None
        released = knob.release()
        idle = knob.release()
        report["hostLost"] = {
            "secondsAfterLastFrame": seconds, "reason": reason, "staleFrameReply": stale.get("error"),
            "nativeEventsObserved": len(native), "nativeSample": [m for _, m in native[:5]],
            "nativeObservationSeconds": args.observe_native_seconds,
            "reentryReady": reentry, "intentionalRelease": released, "idleRelease": idle,
            "lcd": "not observable over serial: confirm the host-lost notice and the native screen by eye"}
        check("stopping frames expires the lease ~2 s after the last frame (host-lost)",
              reason == "lease-expired" and LEASE_WINDOW[0] <= seconds <= LEASE_WINDOW[1], seconds)
        check("native handback: frames for the expired control are stale", stale.get("error") == "Stale control frame",
              stale.get("error"))
        if args.observe_native_seconds > 0:
            check("native knob events (no id) while the host-lost notice is shown", len(native) > 0, len(native))
        check("re-entry after expiry is ready; intentional release acknowledged without a reason",
              reentry and released.get("released") is True and "reason" not in released, released)
        report["diagEnd"] = knob.diag()
        reboot = t.reboot_problems(report["diagStart"], report["diagEnd"])
        if reboot:
            print("!!! REBOOT DETECTED during the lease checks: " + "; ".join(reboot), flush=True)
        check("no reboot during the lease checks (same bootCount, uptime moved forward)", not reboot,
              reboot or {k: report["diagEnd"].get(k) for k in t.BOOT_FIELDS})
        live = t.liveness_problems(report["diagEnd"])
        if live:
            print("!!! TASK STALL, LED TRANSMIT FAILURE OR FORCED RELEASE during the lease checks: "
                  + "; ".join(live), flush=True)
        check(f"end: tasks alive (every age <= {t.LIVENESS_MAX_AGE_MS} ms), no LED transmit failure, "
              "no forced release", not live, live or t.liveness_summary(report["diagEnd"]))
        if cursor is None:
            check(f"{p.version} reports artwork2, so the artwork2 lease cases ran", False)
        report["passed"] = not report["failures"]
    except Exception as exc:
        check("run completed", False, f"{type(exc).__name__}: {exc}")
        report["passed"] = False
    finally:
        # Always release, whatever control_id says (enter() may have timed out after the
        # control was sent, or a case may have failed after an expiry): an idle release is
        # answered at once and clears the host-lost notice, so the knob is never left claimed.
        report["finalRelease"] = knob.release_quietly()
        knob.close()
        report["finishedUtc"] = t.utc_stamp()
        report["raw"] = {"errors": knob.errors, "artErrors": knob.art_errors, "mediaErrors": knob.media_errors,
                         "released": knob.released, "linesWritten": dict(knob.lines_written)}
        t.write_json_evidence(p.lease_checks, report)
        print(f"{'PASSED' if report.get('passed') else 'FAILED'}; evidence {p.lease_checks}")
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    sys.exit(main())
