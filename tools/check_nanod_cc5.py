"""Post-flash device checks for the current release (nanod_cc5_tooling.CURRENT: 1.0.0-cc5.4, "Warm · alive"
LEDs + presentation 5, with the artwork2 checks of 1.0.0-cc5.3; see the 1.0.0-cc5.4 part at the end) or,
with --release cc5.3 / cc5.2, for an earlier release, on the application port. Quit the companion first
(Desk Dial, DeskDial.exe, or the older NanoDControlCenter.exe: tooling.require_companion_quit refuses while
either runs).

1.0.0-cc5.4 is staged as the PRESENTATION_V5 12.6 ladder: pass --binary A|B|C|D|E, the binary just installed
(install_nanod_cc5.py --binary; D and E are the fix binaries after A's rollback, every binary stays checkable),
and the run checks that diag reports that binary (tooling.lcd_binary: diag build on D and E, which must agree with
lcdDma, lcdPeriodMs and artAsync; the pipeline alone on A, B and C) before anything else; an image that reports
build is also checked for its LCD data line (diag lcdMosiSig 103, FSPID; 102 is binary A's dark-LCD defect). Its
LCD timing targets are the binary's (12.2 / 12.6; D has A's, E has C's). The evidence keeps the release's name
(diagnostics/cc5.4-device-checks.json, an older one kept as *.superseded-*) and records the binary ("binary":
expected and reported, with build and lcdMosiSig when the image reports them; sections.diag.binary, build and
lcdMosiSig), which finalize_nanod_cc5.py --binary requires.

The cc5.3-era description below still holds for every release with artwork2; the section names and
gates are unchanged.

Simulated data only: no Sonos, Apple Music, Windows or HID actions (windowsHidEnabled is
false in every control). Covers and icons are built from the design reference assets
(design-reference/design_handoff_nano_d_artwork_color/assets) exactly as ARTWORK2.md section 5
says: artwork.prepare_artwork's 240 px composited image, the JPEG quality ladder, and 32x32
RGB565 icons composited onto black. Each run stamps its own sources (tooling.cover_pool salt), so
a rerun on the same boot never finds the covers and icons the knob kept from an earlier run.
Run with the companion's interpreter:
  app\\.venv\\Scripts\\python.exe tools\\check_nanod_cc5.py --turn-seconds 30 --soak-minutes 20

The knob's own screen tells the operator what to do (user ruling 2026-09-26; tooling.KnobPrompter): no audio cue
and no console or chat prompt. The first thing it shows is the display check ("Can you see this? Press Button 4",
section displayCheck, right after the capabilities and the first diag read); nothing else runs until Button 4
confirms it. Then it shows HANDS OFF for the automatic sections, asks for the turning test ("Ready to turn? Press
Button 4 to start", then "Turn back and forth" with the seconds of turning counted live), the 1.0.0-cc5.4 hands-on
steps one at a time, and YOU CAN LEAVE with the time left for the soak. Each step advances only on the device
events that show it was done; a wrong or incomplete action repeats it with the reason on the screen (and an err
flash). The only timeout is --step-timeout (600 s) per wait: reaching it stops the run as "operator did not complete
step N" (exit 4) or, on the display check, "screen not confirmed" (exit 5), recorded as "operatorStop" and never
as a firmware failure (the gates of the steps not run stay false). The console is a log only. The evidence adds
"displayCheck" and "prompts" (every step: shown, retries, done).

Reboot detection runs through the whole run. {"diag":"?"} (resetReason, uptimeMs, bootCount;
read-only) is read at the start and after EVERY section: a changed bootCount or an uptime that
went back is a reboot. A port-list watcher (every 0.2 s) catches a USB re-enumeration, however
short, and Windows' LastArrivalDate for the knob's USB device is compared at the start, after
each DeviceBridge section, before the raw part and at the end (not while a raw control is
claimed: the PowerShell read takes about a second and the lease is 2 s). Any of them FAILS the
run loudly; the script then waits for the knob to come back and reads diag once more
(read-only) so the evidence names the reset reason and where each task was (the
previous-boot breadcrumbs). The DeviceBridge part cannot send diag, so its sections are
checked on the Windows side and the next raw diag covers uptime and bootCount across them.

Task liveness (1.0.0-cc5.2) is checked on every one of those diag replies: each task's age
(hmiAgeMs, lcdAgeMs, comAgeMs, focAgeMs) must be at most 1000 ms, and ledTxTimeouts,
ledWriteErrors and forcedReleases (counted since boot) must be 0. Any of them FAILS the run
loudly ("!!! TASK STALL, LED TRANSMIT FAILURE OR FORCED RELEASE").

Part A, through the companion's DeviceBridge (exactly what the v4 companion sends):
  * inventory (a new backups/control-center-inventory-*.json) with firmware 1.0.0-cc5.3 and
    capabilities presentation 4, artwork (v1) unchanged {... composited "scrim80", available},
    artwork2 equal to control_center/presentation.py ARTWORK2_CAPABILITY, glyphs latin-ext-a
    and diag; saved profiles compared with the pre-flash inventory;
  * four controls (volume, recent, tracks, windows) ready at their positions, then
    decorated v4 frames in both LED styles (white and targeted colour);
  * bridgeArtwork2: DeviceBridge negotiates artwork2 (media_capability), a 240 px JPEG cover
    and an app icon pushed with set_media_wanted become "media-ready", and a new selection
    preempts the previous one. (Only if artwork2 is not negotiated: the cc5.2 v1 bridge art
    section, cold, cached and superseded covers.)
Part B, over RAW serial (never DeviceBridge). Paced 64 B / 5 ms like the cc5.2-era companion
for the v1 sections; whole-line writes (no slicing, no sleeps) like the v4 companion for every
artwork2 section, the stress passes and the soak:
  * start: diag carries the reboot fields, the coredump partition is blank (after a step-down, with
    --binary, the one exception is the failed binary's dump that this binary's step-down base holds:
    the same size, and no crash reset reason; tooling.step_down_coredump, BUILD-cc5.4.md TB-D9), and the serial
    receive queue is in internal RAM (rxQueue "internal", rxQueueBytes 8192); the raw
    capabilities carry artwork (v1) unchanged and artwork2 exactly;
  * v2 (cc4-era companion) frames from tests/fixtures/frames_v4.json are accepted;
  * stale frame (wrong id) and stale control (non-advancing id) are rejected while the
    active control stays claimed;
  * v1 art (paced, as the cc5.2-era companion): begin/data/commit with CRC, cache hit (begin
    answers 28800), CRC mismatch refused at commit, stale id / stale key / mid-transfer
    selection change answered as stale, malformed and oversize art lines answered by one
    artAck "parse";
  * mediaRoundTrip: a cover and an icon, cold (begin 0, every data offset, commit = bytes),
    then begin-hit (no data), and have (true for both, false for a key never sent);
  * mediaPrefetch: three covers the frame does not name are accepted and kept (have), and one
    of them, once a frame names it, is a begin-hit and is decoded by the LCD at once
    (jpegDecodes +1 within 1.5 s, jpegDecodeMsLast <= 200 ms); the same for an icon;
  * mediaPinning: with the frame naming cover P (and a Windows frame naming icon Q), 26 more
    covers and 50 more icons fill the 25- and 49-slot stores past capacity: P and Q and the
    newest others stay (have), the two oldest others are evicted, diag mediaEvictions grows;
  * mediaErrors: every section 4.3 error string reachable without risk (parse of a malformed
    and an oversize line, Unknown media operation, Unknown media kind, Stale media control,
    Invalid media keys, Invalid media key, Media size and CRC required, Invalid media size, No
    matching media upload, Invalid media data, Media chunk bounds, Media offset mismatch, Media
    upload incomplete, Media checksum mismatch, Media decode failed for a progressive, a
    120 px and a non-JPEG payload), each reply compared whole with its section 4.2 shape (the
    id, op, kind and key that parsed validly; offset = the received count when an upload
    matched, else 0; no key or offset on have), the identical-retry rule, and diag mediaErrors
    counting exactly those replies; "Media unavailable" needs a store that failed to allocate
    and is recorded as not reachable;
  * mediaTiming: five cold covers and five cold icons, unpaced: per-line ms, seconds per
    cover; every ack within 1.5 s (the host's ack timeout) and every cover within 1.5 s;
  * coldTransferTiming (v1, paced): one timed cold transfer, then exactly --replay-transfers (3)
    more cold transfers, untouched (the start of the 1.0.0-cc5 run-1 sequence);
  * stress (pass 1, untouched): first the cc5.2 stress itself, paced v1 art as the cc5.2-era
    companion sends it (~300 frame updates interleaved with v1 art transfers: the 1.0.0-cc5
    run-1 sequence after coldTransferTiming's extra cold transfers; its evidence is the
    section's "v1" object), then UNPACED through artwork2: at least ~300 frame updates and
    --stress-seconds (20) of load (layout bases switched every 20 frames including the Windows
    tile with its icon, LED style every 10, a feedback flash every 25), a frame after every
    media ack, a new cover named and uploaded per round, an icon every other round, a have
    query every third (true for the last three covers), a prefetch cover every fourth. For
    both: zero error replies, zero media or art errors, no release, every transfer committed,
    and no knob events (the knob shows HANDS OFF on every stress frame; the per-frame tag moves to the
    note line). It starts after 3 s with no knob event; a knob event during a pass aborts it ("You
    touched the knob") and reruns it, cold transfers first, at most 3 attempts (the last one is gated);
  * stressTurn (pass 2, stress+turn, step "turn"): on "Ready to turn?" Button 4 starts it; once
    turning is seen (3 position events within 1.5 s), --replay-transfers paced v1 cold transfers,
    then the same unpaced media stress, extended until the knob counts --turn-seconds (30) of
    actual turning inside the stress window (tooling.TurnMeter), both ends and both lims. A pause
    over 3 s aborts the attempt ("You stopped for 3 s"), at most --turn-attempts (3), all recorded
    (turnAttempts). The gate is as before on the last attempt: at least 20 claimed position events
    inside the stress-frame window itself and no pause over 3 s in that window; otherwise it is a
    FAIL marked "turning not detected during stress; rerun", never a pass;
  * both stress gates have a floor, like the soak's (TL-BUG-009): each pass (and the untouched pass's v1 part)
    must send at least STRESS_GATE_FRAMES (300) frame updates and an unpaced pass must last at least
    STRESS_GATE_SECONDS (20 s); a shorter run is recorded ("gateFloor") but its gate stays false.
    --stress-frames must be at least 1, and the effective arguments are recorded ("arguments");
  * soak (UNATTENDED): --soak-minutes (default 20) of companion-like traffic with nobody at the
    knob (it shows YOU CAN LEAVE and the time left): a changed frame every second (the countdown
    and the per-frame tag, LED style every 5 s, layout base every 10 s, a
    feedback flash every 7 s) with 0.5 s heartbeats, a release followed by a new control every
    30 s (volume, recent, tracks, external, windows; never released "forced"), and every 10 s
    an artwork slot, unpaced through artwork2: a cover named and uploaded (alternately new and
    the previous one, a begin-hit), an icon, a have query (true for the recent covers) and,
    every other slot, a prefetch cover; every 4th slot is instead a paced v1 art transfer
    (the cc5.2-era companion, for compatibility). A diag checkpoint every 10 s: no reboot, no
    re-enumeration, every task age <= 1000 ms, no LED transmit failure and no forced release.
    The first failure stops the soak;
  * diag: LVGL heap >= 25 % free at its minimum, the internal heap's minimum since boot
    (heapMinFree) >= 40000 B (cc5.2 measured 79692 B; the evidence records the delta),
    LCD/COM/HMI/FOC stacks > 1 KB, no serial reply
    cut short (txStalls 0), JPEG covers decoded (jpegDecodes > 0) with jpegDecodeErrors 0 and
    jpegDecodeMsMax <= 200 ms, media counters recorded.
The "gates" object in the evidence (all must be true for finalize_nanod_cc5.py):
stressUntouched, stressTurn, turningDetected, noRebootOrReenumeration, rebootFieldsReported,
coredumpBlank, rxQueueInternal, diagMargins, taskLiveness, unattendedSoak (the cc5.2 gates) and
artwork2Capability, bridgeArtwork2, v1ArtCompatible, mediaRoundTrip, mediaPrefetch, mediaPinning,
mediaErrorStrings, unpacedTransferTiming, jpegDecode (1.0.0-cc5.3).
Evidence: diagnostics/cc5.3-device-checks.json (an older one is kept as *.superseded-*; the cc5.2
evidence diagnostics/cc5-device-checks.json is never touched).

1.0.0-cc5.4 (CURRENT, the default --release; ALIVE.md revision 2 section 11.9, PRESENTATION_V5.md
sections 11, 12 and 15.4). Everything above runs as for cc5.3, with the presentation-5 capability
(artwork2 negotiates on presentation 5), plus:
  * binary (with --binary): diag build (D, E) and lcdDma / lcdPeriodMs / artAsync identify the binary installed
    (12.6); with build reported, lcdMosiSig is 103 (the LCD data line on FSPID);
  * capabilities: presentation 5 and alive equal to tooling.alive_capability(<the inventory's
    ledMaxBrightness>) (gates presentation5Capability, aliveCapability);
  * ledIdle (untouched Home control): diag ledFps >= 58 and ledShowGapMsMax <= 20 ms;
  * lcdAnimation: the binary (A..E, tooling.lcd_binary); a pass of slides
    over a shown cover (lcdFpsAnimMin >= 55 on A and D, >= 28 on B, C and E; no late refresh during the pass,
    lcdLateRefrs taken as a since-boot or reset-on-read count, told apart by two reads at rest, so the
    earlier sections' cover arrivals never count) and a pass of art show/hide (>= 45 on A and D, >= 28 on
    B, C and E) (gate lcdTimings). Each pass animates without a gap (a screen change every 0.25 s / 0.2 s,
    shorter than the 380 ms slide and the 240 ms art fade it restarts) from 1.2 s before the read that
    resets lcdFpsAnimMin to a measured read 3 s later taken mid-slide, so every whole second measured
    is animated; enterMsMax recorded (<= 250 ms);
  * ledUnderLoad: cover transfers with diag read after each: ledFps >= 45 in every sample (the
    pass rule), >= 55, ledShowGapMsMax and ledLateShows recorded (gate ledFrameRate, with ledIdle);
  * stress: ledRenderUsMax <= 3000 us over each stress pass (gate ledRenderTime); no error reply in
    either pass (gate noErrorReplies); lim events of the stress control at both ends while turning;
  * handsOn (at the knob, right after stress+turn; the knob shows each step, "STEP n OF m", and moves on
    only when its events arrive): "Hold Button 1" -> on the kd "Keep holding…", on the kh "Let go" ->
    exactly one kh 0.45-1.2 s after its kd, with Button 1's bit in ks; "Hold Button 2" (a 2 s countdown)
    -> no kh (gate holdEvents; both count every kh from the kd to 0.6 s after the key-up, so a kh sent at
    or after the release fails them; a key-up too soon is "Too short" and the step again); hold Button 1
    while a new control enters (the delay from tooling.DeferredPlanner, refined by each attempt that did
    not defer) -> the ready line's ks has Button 1's bit and one kh with the new id follows it, counted by
    diag holdDeferred (up to --deferred-attempts 10; gate holdDeferred); a Seek control (20 s song, T_end
    17 s) at its right end: "Push past the end" one push at a time (1 of 5 ...), each ending 1 s after
    its last lim (a second lim in that second is a double: chatter), then "Push and hold" with a 3 s
    countdown, then "Turn to 0:00" and push -> exactly one lim +1 per push, one while held, none outside,
    lim -1 at 0:00 (tooling.EndStopWindows: the windows come from the prompts; gates limitPerPush and,
    with the stress lims, limitEvents; lim_rearm_ms is tuned by hand from these counts and recorded; no
    lim for 10 s asks "Did you push?" on the knob); with --hid-check only (it sends F24 key presses to
    Windows; nothing handles them while the companion is quit): "Press Button 4" on a Home control whose
    slot 4 is `win` -> kd with hid:1, on a Tracks control -> kd without hid (gate hidIconGate; false when
    not run);
  * every ready line carries ks 0..15 (gate readyKeyState, with the held bit of the deferred test);
  * diag: heapMinFree >= 40,960 B, lvglMinFree >= 30 KB, stackArtDec >= 1,024 B on the binaries with artAsync
    (A, D).
Checks the user makes by eye in the same window (PRESENTATION_V5 12.6 check 1 "panel image" and, on binary
A, filming the panel scan; 15.4; ALIVE.md 11.9) are listed in the evidence ("byEye", next to the binary
under test) and are not gated here. Evidence: diagnostics/cc5.4-device-checks.json.
"""
import argparse
import base64
from contextlib import contextmanager
from copy import deepcopy
import hashlib
from pathlib import Path
import queue
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nanod_cc5_tooling as t  # noqa: E402

FATAL_KINDS = ("error", "released", "disconnected")
PROFILE = {"volume": "BINARIS BEER", "recent": "MIDI SKIPPER", "tracks": "MIDI CLACK JONES", "windows": "MIDI SKIPPER"}
STRESS_BASES = ("v4-home-now-playing", "v4-recent-item-colour", "v4-tracks-no-previous",
                "v4-home-volume-external-over-idle")
# The unpaced media stress also switches to the Windows tile, whose frames name the latest icon.
MEDIA_STRESS_BASES = STRESS_BASES + ("v4-windows-window-rule",)
MEDIA_BASES = {"recent": "v4-recent-item-colour", "windows": "v4-windows-window-rule"}
REPLAY_TRANSFERS = 3      # the extra cold transfers of the 1.0.0-cc5 run 1, before its stress
# The stress gates' floor, like the soak's SOAK_GATE_MINUTES (TL-BUG-009): stressUntouched and stressTurn are true only
# when each pass sent at least the default --stress-frames and an unpaced artwork2 pass lasted at least the default
# --stress-seconds. A shorter run (e.g. --stress-frames 10 for a rerun) still runs and is recorded, but never passes.
STRESS_GATE_FRAMES = 300
STRESS_GATE_SECONDS = t.STRESS_MIN_SECONDS
# The failure a Ctrl+C records (TL-BUG-008): the run is written as not completed and not passed, then re-raised.
INTERRUPTED_CHECK = "run completed: interrupted (Ctrl+C) before the end; not a pass"
# The current release's gates (its profile's: the cc5.2 ten, then artwork2's of 1.0.0-cc5.3). A run
# for another profile (--release) reports that profile's gates (1.0.0-cc5.4 adds the ALIVE and
# presentation-5 gates, tooling.ALIVE_DEVICE_GATES and PRESENTATION5_DEVICE_GATES).
GATES = t.CURRENT.gates
# 1.0.0-cc5.4 hands-on (handsOn section).
HOLD_RAW, OTHER_RAW, HID_RAW = 0, 1, 3          # Button 1 holds (buttonOrder[0]); Button 2 never; Button 4 is F24
# Deferred hold: the new control is sent so that the long press falls in the middle of its entry
# (tooling.DeferredPlanner: diag enterMsLast, ~22 ms when unknown); each attempt shifts it by an offset and an attempt
# that did not defer refines the estimate. Calibrated on hardware (1.0.0-cc5.4 binary A, 2026-09-26): the kh
# arrived 0.444-0.506 s (mean 0.476) after the kd reached the PC, not ~0.60 s (kHoldMs 600 runs from the physical
# press), and an entry takes ~22 ms, so the offsets step through that spread in 10-20 ms steps.
HOLD_AFTER_KD_S = t.DEFERRED_KH_ESTIMATE_S
DEFERRED_OFFSETS_S = t.DEFERRED_OFFSETS_S
DEFERRED_ATTEMPTS = 10                           # --deferred-attempts
DEFERRED_AGAIN = "Again · attempt {n} of {of}"    # the next deferred attempt (fits the note line at 10 of 10)
DEFERRED_KH_WAIT_S = 1.5                         # after the new ready line, the kh is awaited this long
LATE_KH_S = 0.6       # after each key-up the check listens this long; a kh in it counts (11.2: at most one per press)
HOLD_SHORT_S = 1.2                               # a key-up this soon after the kd, with no kh: "Too short"
HOLD_NO_KH_S = 1.5                               # held this long with no kh: "Let go" (the firmware sent none)
HOLD2_COUNT = 2                                  # Button 2 is held through a 2 s countdown the tool times
SEEK_DURATION_S, SEEK_MARGIN_S = 20, 3           # the push test's Seek song: D 20 s, T_end = D - 3 (VOC seek_margin_s)
PUSHES, HOLD_WINDOW_S = 5, 3.0                   # five single pushes, then one held for 3 s
PUSH_NUDGE_S = 10.0                              # no event of the Seek control this long: "Did you push?" on the knob
# The turning test and the untouched passes (the knob's screen; tooling.TurnMeter).
TURN_SECONDS = 30.0                              # --turn-seconds: seconds of actual turning inside the stress window
TURN_ATTEMPTS = 3                                # --turn-attempts: a pause over 3 s aborts an attempt
TURN_READY, TURN_START = "Ready to turn?", "Press Button 4 to start"
TURN_SAY, TURN_KEEP = "Turn back and forth", "Keep turning"
UNTOUCHED_ATTEMPTS = 3                           # a touched untouched pass is rerun (the last attempt is gated)
UNTOUCHED_QUIET_S = 3.0                          # no knob event this long before each untouched pass
HANDS_OFF, LEAVE, AUTOMATIC = "HANDS OFF", "YOU CAN LEAVE", "Automatic test"
UNTOUCHED = "Don’t touch the knob"
LED_IDLE_SECONDS = 3.0
LED_LOAD_TRANSFERS = 6
# lcdFpsAnimMin is the lowest whole-second lcdFps while animations run (PRESENTATION_V5 12.3), and LVGL
# refreshes only while something animates: a pass must keep the panel animating WITHOUT A GAP through every
# second it measures. Each screen change restarts contentTx (380 ms, 8.8) and every recent <-> windows change
# retargets artOpa (240 ms), so a change every SLIDE_PERIOD_S / FADE_PERIOD_S (shorter than the tween it
# restarts) animates continuously. ANIM_LEAD_S of it runs before the read that resets lcdFpsAnimMin (no idle
# or partly idle second before the pass counts), ANIM_PASS_S of it (>= 2 whole seconds) before the measured
# read, and the last change is sent right before that read, so it is taken while a slide still runs.
SLIDE_PERIOD_S = 0.25                            # opaque pass: recent <-> tracks (both show the cover)
FADE_PERIOD_S = 0.2                              # blended pass: recent <-> windows (the cover hides and shows)
ANIM_LEAD_S, ANIM_PASS_S = 1.2, 3.0
BY_EYE = ("PRESENTATION_V5 12.6 check 1, panel image (the first check on each binary, before its timing; A failing "
          "it goes straight to C, D failing it goes to E): a static Home cover matches the harness render of the same frame (colours, "
          "byte order, no offset); no torn or stale bands during a slide, a volume reveal or a cover swap; an "
          "orientation change (setRotation) redraws cleanly. Record pass/fail with the binary under test",
          "binaries A and D only (12.6 check 3; D is A's pipeline): film the panel scan (RF3 8.2 step 3) and keep the clip with the evidence",
          "Seek digits: no jitter while turning (tabular m:ss)", "twins legible on light covers; no darkening of "
          "text during a slide (P5-13)", "no visible darkening of text during both volume reveals (R-b: the "
          "twin_fade bound 28 confirmed by eye; R-g: where the volume caption crosses the fading home title, the "
          "overlap class bounded at 36, 35 measured, no visible darkening of the caption)", "headings fit on glass",
          "the offline native line 'Knob controls still work' on one line at -1 px tracking reads cleanly (R-c; "
          "else the 8.10 fallback copy 'Controls still work')",
          "the offline screen after the Desk Dial rename: no heading (K1 8.10), 'Waiting for PC' and the sub-line "
          "'Open Desk Dial' / 'on your PC' on two lines, the name never split (a no-break space; K1 16.8 E-r)", "the Windows art fade (240 ms)",
          "Up next spin without decode stalls (binaries A and D: R5), never a superseded cover",
          "LED tour (tools/nanod_alive_tour.py): every moment, PINK among the ledPink candidates, the volume "
          "body 0.62 vs 1.0 (ledVolFull), paused Play green, Head shake legibility, the wake feel",
          "the End stop feel at 0:00 and T_end; lim_rearm_ms (start 75 ms, 40-150) settled from the per-push counts")
BANNER = "=" * 76
LIVENESS_CHECK = (f"tasks alive (every age <= {t.LIVENESS_MAX_AGE_MS} ms), no LED transmit failure, "
                  "no forced release")
# The soak's controls, cycled on every release + re-enter: (name, profile, fixture base, max, position).
SOAK_CONTROLS = (("volume", "BINARIS BEER", "v4-home-now-playing", 100, 54),
                 ("recent", "MIDI SKIPPER", "v4-recent-item-colour", 10, 2),
                 ("tracks", "MIDI CLACK JONES", "v4-tracks-no-previous", 2, 0),
                 ("external", "BINARIS BEER", "v4-home-volume-external-over-idle", 100, 57),
                 ("windows", "MIDI SKIPPER", "v4-windows-window-rule", 44, 30))
BRIEF = ("kind", "key", "bytes", "beginOffset", "hit", "chunks", "committed", "error", "errorOp", "seconds")


TURN_CHECK =(f"stress+turn: turning detected during the stress (>= {t.TURN_MIN_EVENTS} claimed position events "
              f"inside its frame window, no pause > {t.TURN_MAX_GAP_S:g} s)")


def brief(result):
    return {k: result.get(k) for k in BRIEF if k in result}


def failed_at(result):
    """Where a failed media_transfer/art_transfer stopped: its op and error or, with no error (committed
    False), the commit whose ack did not acknowledge the full size (the soak's failure text)."""
    if result["error"]:
        return f"{result['errorOp']}: {result['error']}"
    return (f"commit: not committed (the commit ack carries no error but its offset is not the full size; "
            f"beginOffset {result['beginOffset']}, {result['chunks']} data lines)")


class Report:
    def __init__(self, port, profile=None):
        self.profile = profile or t.CURRENT
        self.led_max_brightness = None      # the inventory's ledMaxBrightness (alive drive), never in the evidence
        self.data = {"startedUtc": t.utc_stamp(), "firmwareVersion": self.profile.version, "port": port,
                     "externalActions": False, "checks": [], "sections": {}, "failures": [],
                     "gates": {name: False for name in self.profile.gates}}
        self.gates = self.data["gates"]

    def check(self, name, ok, detail=None):
        self.data["checks"].append({"check": name, "passed": bool(ok), **({"detail": detail} if detail is not None else {})})
        print(f"{'PASS' if ok else 'FAIL'}  {name}", flush=True)
        if not ok:
            self.data["failures"].append(name)
        return ok

    @contextmanager
    def section(self, name):
        started = time.monotonic()
        try:
            yield self.data["sections"].setdefault(name, {})
        except t.OperatorStop:
            raise  # the operator did not complete a step: never a firmware failure (main exits 4 or 5)
        except TimeoutError as exc:  # a missing reply: record it and continue with the next section
            self.check(f"{name}: completed", False, f"{type(exc).__name__}: {exc}")
        except (t.PortError, OSError):
            raise  # the port itself failed: stop the run
        except Exception as exc:  # record and continue with the next section
            self.check(f"{name}: completed", False, f"{type(exc).__name__}: {exc}")
        finally:
            self.data["sections"][name]["seconds"] = round(time.monotonic() - started, 2)


class RebootWatch:
    """Reboot and USB re-enumeration detection at the start, after every section and at the end."""

    def __init__(self, report, port, *, arrival=None, port_watch=None, probe=None, poll=None, inherited_coredump=None):
        self.report, self.port = report, port
        # A step-down binary: the failed binary's core dump its step-down base holds (tooling.step_down_coredump).
        self.inherited_coredump = inherited_coredump
        self.arrival_reader = arrival or t.pnp_last_arrival
        self.port_watch = port_watch if port_watch is not None else t.PortWatch()
        self.probe = probe or t.probe_diag
        self.poll = poll or t.poll_ports
        self.data = report.data.setdefault("rebootWatch", {"timeline": [], "detected": [], "postDropDiag": None})
        # 1.0.0-cc5.2: every diag reply is also a liveness checkpoint (tooling.liveness_problems).
        self.live = report.data.setdefault("liveness", {"maxAgeMs": t.LIVENESS_MAX_AGE_MS, "checked": 0,
                                                         "failures": []})
        self.arrival, self.last_diag, self.started = None, None, False
        self.pre_drop = None            # the last diag before the first detection (the post-drop reference)

    def start(self):
        self.arrival = self.arrival_reader()
        self.data["arrivalAtStart"] = self.arrival
        self.port_watch.start()
        self.started = True
        diag = self.probe(self.port)
        self.report.data["diagStart"] = diag
        self._entry("start", diag, [])
        self.last_diag = diag
        fields = t.boot_fields_problems(diag)
        self.report.check("diag reports the reboot fields (resetReason, uptimeMs, bootCount)", not fields,
                          fields or {k: diag.get(k) for k in (*t.BOOT_FIELDS, "rtcResetNames", "rtcRetained")})
        core = t.coredump_problems(diag, self.inherited_coredump)
        kept = bool(self.inherited_coredump) and not core and bool((diag.get("coredump") or {}).get("present"))
        self.report.data["coredumpInherited"] = self.inherited_coredump if kept else None
        self.report.check("no core dump stored in flash (coredump partition blank)"
                          + (", or only the failed binary's dump its step-down base holds" if self.inherited_coredump else ""),
                          not core, core or ({**diag.get("coredump"), "inheritedFromStepDownBase": self.inherited_coredump}
                                             if kept else diag.get("coredump")))
        internal = diag.get("rxQueue") == "internal"
        self.report.check("serial receive queue in internal RAM (rxQueue internal)", internal,
                          {"rxQueue": diag.get("rxQueue"), "rxQueueBytes": diag.get("rxQueueBytes")})
        self.report.gates.update(rebootFieldsReported=not fields, coredumpBlank=not core, rxQueueInternal=internal)
        self.liveness("start", diag)

    def liveness(self, where, diag, quiet=False):
        """Task ages, LED transmit counters and forced releases of one diag reply.

        `quiet` (the soak's 10 s checkpoints) records a healthy reply without a check line;
        a failure is always a FAIL check and a loud banner."""
        problems = t.liveness_problems(diag)
        self.live["checked"] += 1
        if problems:
            self.live["failures"].append({"after": where, "problems": problems, "diag": t.liveness_summary(diag)})
            print(f"{BANNER}\n!!! TASK STALL, LED TRANSMIT FAILURE OR FORCED RELEASE (after {where}):", flush=True)
            for problem in problems:
                print(f"!!!   {problem}", flush=True)
            print(BANNER, flush=True)
        if problems or not quiet:
            self.report.check(f"{LIVENESS_CHECK}: {where}", not problems, problems or t.liveness_summary(diag))
        return not problems

    def checkpoint(self, where, diag=None, pnp=True, quiet=False):
        """Port watch always; uptime and bootCount when a diag reply is given; the PnP arrival
        date only with `pnp` (it runs PowerShell for about a second, so the raw sections, whose
        control is claimed on a 2 s lease with nothing heartbeating meanwhile, skip it: a
        re-enumeration there breaks the port, and the port watch and the next diag see it).
        A diag reply is also a liveness checkpoint. `quiet` records a passing checkpoint in the
        timeline only (the soak's 10 s checkpoints); any problem is still a FAIL check.
        Returns True when both the reboot and the liveness checks passed."""
        problems = t.arrival_problems(self.arrival, self.arrival_reader()) if pnp else []
        for gone in self.port_watch.take():
            seconds = "still gone" if gone.get("seconds") is None else f"{gone['seconds']} s"
            problems.append(f"USB RE-ENUMERATION: the knob's port disappeared at +{gone['from']} s ({seconds})")
        if problems and self.pre_drop is None:
            self.pre_drop = self.last_diag
        if diag is not None:
            reboot = t.reboot_problems(self.last_diag, diag)
            if reboot and self.pre_drop is None:
                self.pre_drop = self.last_diag
            problems += reboot
            self.last_diag = diag
        self._entry(where, diag, problems)
        if problems or not quiet:
            self.report.check(f"no reboot or USB re-enumeration: {where}", not problems, problems or None)
        if problems:
            self.data["detected"].append({"after": where, "problems": problems})
            print(f"{BANNER}\n!!! REBOOT OR USB RE-ENUMERATION DETECTED (after {where}):", flush=True)
            for problem in problems:
                print(f"!!!   {problem}", flush=True)
            print(BANNER, flush=True)
        alive = self.liveness(where, diag, quiet) if diag is not None else True
        return not problems and alive

    def _entry(self, where, diag, problems):
        diag = diag if isinstance(diag, dict) else {}
        self.data["timeline"].append({"after": where, "utc": t.utc_stamp(), "uptimeMs": diag.get("uptimeMs"),
                                      "bootCount": diag.get("bootCount"), "resetReason": diag.get("resetReason"),
                                      "liveness": t.liveness_summary(diag) if diag else None,
                                      "media": t.media_diag_summary(diag) if diag else None,
                                      "problems": problems})

    def finish(self, error=None):
        """End of run: a last read-only diag; after any drop, wait for the knob and record why it reset."""
        if not self.started:
            return
        if self.last_diag is None:          # no baseline diag (older firmware or no reply at the start)
            self.port_watch.stop()
            return
        try:
            dropped = bool(self.data["detected"]) or isinstance(error, OSError)
            if not dropped:
                try:
                    self.checkpoint("end", self.probe(self.port))
                except Exception as exc:
                    self.report.check("no reboot or USB re-enumeration: end", False, f"{type(exc).__name__}: {exc}")
                    self.data["detected"].append({"after": "end", "problems": [f"no diag reply: {exc}"]})
                dropped = bool(self.data["detected"])
            if dropped:
                self.recover()
        finally:
            self.port_watch.stop()
            self.report.gates["noRebootOrReenumeration"] = not self.data["detected"] and not isinstance(error, OSError)
            self.report.gates["taskLiveness"] = self.live["checked"] > 0 and not self.live["failures"]

    def recover(self, timeout=20.0):
        """Read-only: wait for the application port, read diag once, record the reset attribution."""
        print("Waiting up to 20 s for the knob to come back, to read why it reset (read-only diag) ...", flush=True)
        device, _ = self.poll(t.is_app_port, timeout, settle=1.0)
        if device is None:
            self.data["postDropDiag"] = {"error": f"the application port did not come back within {timeout:.0f} s"}
            self.report.check("after the drop: the knob came back and diag was read", False, self.data["postDropDiag"])
            return
        try:
            diag = self.probe(device)
        except Exception as exc:
            self.data["postDropDiag"] = {"port": device, "error": f"{type(exc).__name__}: {exc}"}
            self.report.check("after the drop: the knob came back and diag was read", False, self.data["postDropDiag"])
            return
        summary = {k: diag.get(k) for k in ("resetReason", "resetCode", "rtcResetNames", "bootCount", "rtcRetained",
                                            "uptimeMs", "previous", "coredump")}
        rebooted = t.reboot_problems(self.pre_drop or self.last_diag, diag)
        self.data["postDropDiag"] = {"port": device, "diag": diag, "rebootProblems": rebooted}
        if rebooted:
            print(f"{BANNER}\n!!! The knob RESET. Reset reason: {diag.get('resetReason')} {diag.get('rtcResetNames')}; "
                  f"previous boot: {diag.get('previous')}\n{BANNER}", flush=True)
            self.report.check("after the drop: the knob reset; reset reason recorded (read-only diag)", False, summary)
        else:
            print(f"{BANNER}\n!!! The port failed or re-enumerated, but the knob did not reset (same bootCount, later "
                  f"uptime).\n{BANNER}", flush=True)
            self.report.check("after the drop: the knob did not reset (same bootCount, later uptime); the drop "
                              "itself still fails the run", True, summary)


class Events:
    """Time-stamped DeviceBridge events; error/released/disconnected are fatal while waiting."""

    def __init__(self, bridge):
        self.bridge, self.log, self.t0 = bridge, [], time.monotonic()

    def _next(self, timeout):
        event = self.bridge.events.get(timeout=timeout)
        self.log.append({**{k: v for k, v in event.items() if k != "profiles"},
                         "t": round(time.monotonic() - self.t0, 3)})
        return event

    def wait(self, kind, timeout, match=lambda e: True, fail=lambda e: False):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                event = self._next(0.1)
            except queue.Empty:
                continue
            if event["kind"] in FATAL_KINDS or fail(event):
                raise RuntimeError(f"bridge {event['kind']}: {event.get('message') or event.get('reason') or event}")
            if event["kind"] == kind and match(event):
                return event
        raise TimeoutError(f"no {kind} within {timeout} s")

    def quiet(self, seconds, fail=lambda e: False):
        seen, deadline = [], time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                event = self._next(0.05)
            except queue.Empty:
                continue
            if event["kind"] in FATAL_KINDS or fail(event):
                raise RuntimeError(f"bridge {event['kind']}: {event.get('message') or event.get('reason') or event}")
            seen.append(event["kind"])
        return seen


def companion():
    if str(t.APP) not in sys.path:
        sys.path.insert(0, str(t.APP))
    from control_center import controller, device, runtime, simulation
    return controller, device, runtime, simulation


def before_inventory(profile=None):
    preparation = (profile or t.CURRENT).preparation
    if not preparation.is_file():
        return None
    path = t.BACKUPS / t.load_json(preparation)["beforeInventory"]
    return path if path.is_file() else None


# ---------------------------------------------------------------------------
# Part A: DeviceBridge

def bridge_media(bridge, events, c, controller, simulation, report, out, cursor):
    """artwork2 through the v4 DeviceBridge (ARTWORK2.md section 9): negotiation, a cover and an
    icon pushed with set_media_wanted, and a preempting selection. Returns True when all pass."""
    capability = getattr(bridge, "media_capability", None)
    ok = [report.check("bridge artwork2: DeviceBridge negotiated artwork2 (media_capability equals "
                       "presentation.ARTWORK2_CAPABILITY)", capability == t.artwork2_capability(), capability)]
    if capability is None:
        raise RuntimeError("DeviceBridge did not negotiate artwork2")
    Screen = controller.Screen

    def enter(screen):
        c.screen = screen
        c._enter()
        control = c.control()
        bridge.submit("enter", control)
        events.wait("ready", 5, match=lambda e: e["id"] == control["id"])

    def ready(key, timeout=15):
        started = time.monotonic()
        events.wait("media-ready", timeout, match=lambda e: e.get("key") == key,
                    fail=lambda e: e["kind"] == "media-error" and e.get("key") == key)
        return round(time.monotonic() - started, 3)

    recent = lambda: Screen(mode="recent", pages=[simulation.SimulatedAppleMusic().recent()], status="")  # noqa: E731
    enter(recent())
    key_a, cover_a = cursor.cover()
    bridge.submit("frame", {**c.frame(), "id": c.control_id, "artKey": key_a})
    bridge.set_media_wanted("cover", [(key_a, cover_a)])
    out["coverSeconds"] = cold = ready(key_a)
    ok.append(report.check(f"bridge artwork2: a 240 px JPEG cover ({len(cover_a)} B) becomes media-ready", cold is not None,
                           cold))

    enter(Screen(mode="windows", index=1, windows=simulation.SimulatedWindows().snapshot(), status=""))
    key_i, icon = cursor.icon()
    bridge.submit("frame", {**c.frame(), "id": c.control_id, "iconKey": key_i})
    bridge.set_media_wanted("icon", [(key_i, icon)])
    out["iconSeconds"] = seconds = ready(key_i)
    ok.append(report.check("bridge artwork2: a 32x32 app icon becomes media-ready", seconds is not None, seconds))

    enter(recent())
    (key_b, cover_b), (key_c, cover_c) = cursor.cover(), cursor.cover()
    bridge.submit("frame", {**c.frame(), "id": c.control_id, "artKey": key_b})
    bridge.set_media_wanted("cover", [(key_b, cover_b)])
    bridge.submit("frame", {**c.frame(), "id": c.control_id, "artKey": key_c})
    bridge.set_media_wanted("cover", [(key_c, cover_c), (key_b, cover_b)])
    out["preemptSeconds"] = seconds = ready(key_c)
    ok.append(report.check("bridge artwork2: a new selection's cover becomes ready when it preempts the previous "
                           "one", seconds is not None, seconds))
    bridge.set_media_wanted("cover", [])
    bridge.set_media_wanted("icon", [])
    events.quiet(0.5)
    errors = [e for e in events.log if e["kind"] == "media-error"]
    out["mediaErrors"] = errors[:20]
    ok.append(report.check("bridge artwork2: no media-error event and no error or release", not errors, errors[:5]))
    return all(ok)


def bridge_checks(port, report, watch, profile=None, binary=None):
    p = profile or report.profile
    controller, device, runtime_mod, simulation = companion()
    bridge = device.DeviceBridge(t.BACKUPS)
    events = Events(bridge)
    runtime = None
    try:
        bridge.submit("connect", port)
        connected = events.wait("connected", 35)
        caps = connected["capabilities"]
        inventory_path = Path(connected["backup"])
        inventory = t.load_json(inventory_path)
        report.data.update(inventory=str(inventory_path), capabilities=caps)
        settings = inventory.get("settings", {})
        # FW-PUB-004: the knob reports "<NANO_FIRMWARE_PUBLIC>+<build id>.<binary>" (1.0.0+cc5.7.F), not p.version.
        reported = t.reported_firmware_versions(p, binary)
        report.check(f"inventory: firmware {' or '.join(reported)} ({p.version})",
                     settings.get("firmwareVersion") in reported, settings.get("firmwareVersion"))
        report.check("capability: controlCenter 1, leaseMs 2000", caps.get("controlCenter") == 1 and caps.get("leaseMs") == 2000)
        report.check(f"capability: presentation {p.presentation}", caps.get("presentation") == p.presentation,
                     caps.get("presentation"))
        if p.alive:
            # ALIVE.md 1: drive = min(150, ledMaxBrightness); the inventory names the knob's setting.
            # (kept on the report object for the raw part, not written to the evidence: no settings contents)
            report.led_max_brightness = settings.get("ledMaxBrightness")
            alive = t.alive_capability_problems(caps, report.led_max_brightness)
            report.check("capability: alive {version 1, fps 60, drive min(150, ledMaxBrightness)}", not alive,
                         alive or caps.get(t.presentation().ALIVE_CAPABILITY))
        report.check("capability: glyphs latin-ext-a", caps.get("glyphs") == "latin-ext-a", caps.get("glyphs"))
        report.check("capability: diag 1", caps.get("diag") == 1, caps.get("diag"))
        report.check("capability: artwork 120x120 RGB565_LE, 384 B chunks, 8 entries, available, composited scrim80",
                     caps.get("artwork") == t.EXPECTED_ARTWORK_CAPABILITY, caps.get("artwork"))
        if p.artwork2:
            report.check("capability: artwork2 equals presentation.ARTWORK2_CAPABILITY (240 JPEG covers, 32x32 "
                         "icons, unpaced)", caps.get("artwork2") == t.artwork2_capability(), caps.get("artwork2"))
        legacy = {"hostFrame": 1, "runtimeProfileBounds": 1, "taggedInput": 1, "windowsHidKey": "F24",
                  "buttonOrder": 1, "windowsHidControl": 1}
        report.check("capability: cc4 keys unchanged", all(caps.get(k) == v for k, v in legacy.items()),
                     {k: caps.get(k) for k in legacy})
        previous = before_inventory(p)
        if previous:
            old = t.load_json(previous)
            changed = sorted(k for k in set(old["settings"]) | set(settings) if old["settings"].get(k) != settings.get(k))
            report.data["beforeInventory"] = previous.name
            report.check("saved profiles identical to the pre-flash inventory",
                         old["profiles"] == inventory["profiles"] and len(inventory["profiles"]) == 10,
                         len(inventory["profiles"]))
            report.check("only firmwareVersion changed in settings", changed == ["firmwareVersion"], changed)
        else:
            report.data["beforeInventory"] = f"not available ({p.preparation.name} missing)"
        for name in set(PROFILE.values()):
            if name not in inventory["profiles"]:
                raise RuntimeError(f"profile {name} missing from the inventory")

        c = controller.Controller()
        runtime = runtime_mod.Runtime(c, simulation.SimulatedSonos(), simulation.SimulatedAppleMusic(),
                                      simulation.SimulatedWindows())
        c.state.update(simulation.SimulatedSonos().read_state())
        c.state.update(volume=54, title="Varanda", artist="Ana Ribeira", playback="PLAYING")
        c.state_known = True
        c.windows_hid_enabled = False
        Screen = controller.Screen
        screens = [Screen(status=""),
                   Screen(mode="recent", pages=[simulation.SimulatedAppleMusic().recent()], status=""),
                   Screen(mode="tracks", index=1, status=""),
                   Screen(mode="windows", index=1, windows=simulation.SimulatedWindows().snapshot(), status="")]
        entries = []
        with report.section("fourControls") as out:
            for screen in screens:
                c.screen = screen
                c._enter()
                control = c.control()
                bridge.submit("enter", control)
                ready = events.wait("ready", 5, match=lambda e: e["id"] == control["id"])
                entry = {"mode": screen.mode, "profile": control["profile"], "id": control["id"],
                         "position": ready["position"], "expectedPosition": control["position"],
                         "ready": ready["position"] == control["position"], "styles": {}}
                for style in ("white", "color"):
                    runtime.led_style = style
                    frame = {**c.frame(), "id": c.control_id}
                    wire = device._frame(deepcopy(frame), caps)
                    bridge.submit("frame", frame)
                    colors = wire["ring"].get("colors", [])
                    entry["styles"][style] = {
                        "ledStyle": wire.get("ledStyle"), "layout": wire.get("layout"),
                        "colors": colors, "nonWhiteColors": sum(1 for v in colors if v not in (0, 0xFFFFFF)),
                        "lineBytes": device.frame_line_bytes(wire), "events": events.quiet(0.8)}
                entries.append(entry)
                report.check(f"control {screen.mode}: ready at position {control['position']}", entry["ready"])
            out["entries"] = entries
            report.check("v4 frames in both LED styles accepted (no error, no release)", len(entries) == 4)
            coloured = [e["mode"] for e in entries if e["styles"]["color"]["nonWhiteColors"] > 0]
            report.check("targeted colour: Recent and Windows carry non-white landmarks",
                         {"recent", "windows"} <= set(coloured), coloured)
            report.check("white style: no ring colours sent",
                         all(not e["styles"]["white"]["colors"] for e in entries))
        report.data["fourControls"] = [{k: e[k] for k in ("mode", "profile", "ready", "position")} for e in entries]
        watch.checkpoint("fourControls")

        if getattr(bridge, "media_capability", None) is None:
            # Only when the bridge did not negotiate artwork2: the cc5.2 v1 art through DeviceBridge.
            with report.section("bridgeArtwork") as out:
                run = uuid.uuid4().hex[:6]
                c.screen = Screen(mode="recent", pages=[simulation.SimulatedAppleMusic().recent()], status="")
                runtime.led_style = "color"

                def enter():
                    c._enter()
                    control = c.control()
                    bridge.submit("enter", control)
                    events.wait("ready", 5, match=lambda e: e["id"] == control["id"])

                def show(key):
                    bridge.submit("frame", {**c.frame(), "id": c.control_id, "artKey": key})
                    bridge.submit("artwork", {"id": c.control_id, "key": key, "data": t.art_pixels(key)})

                def ready(key, timeout=30):
                    started = time.monotonic()
                    events.wait("artwork-ready", timeout, match=lambda e: e["key"] == key,
                                fail=lambda e: e["kind"] == "artwork-error" and e.get("key") == key)
                    return round(time.monotonic() - started, 3)

                enter()
                key_a = f"cc5bA{run}"
                show(key_a)
                out["coldSeconds"] = cold = ready(key_a)
                enter()
                show(key_a)
                out["cachedSeconds"] = cached = ready(key_a, 10)
                report.check("bridge art: cold transfer ready", cold > 0, cold)
                report.check("bridge art: cache hit on re-entry is much faster than cold", cached < cold / 3,
                             {"cold": cold, "cached": cached})
                key_b, key_c = f"cc5bB{run}", f"cc5bC{run}"
                show(key_b)
                out["duringStale"] = events.quiet(0.3, fail=lambda e: e["kind"] == "artwork-ready" and e.get("key") == key_b)
                show(key_c)
                out["newSelectionSeconds"] = ready(key_c)
                out["afterNewSelection"] = events.quiet(1.0, fail=lambda e: e["kind"] == "artwork-ready" and e.get("key") == key_b)
                stale_ready = [e for e in events.log if e["kind"] == "artwork-ready" and e.get("key") == key_b]
                report.check("bridge art: superseded cover never becomes ready; new one does; no error or release",
                             not stale_ready)
                out["artworkErrors"] = [e for e in events.log if e["kind"] == "artwork-error"]
            watch.checkpoint("bridgeArtwork")

        with report.section("bridgeArtwork2") as out:
            runtime.led_style = "color"
            # Payloads of this run only (see tooling.cover_pool): never a cover or icon the knob already holds.
            salt = f"bridge{uuid.uuid4().hex[:6]}"
            cursor = t.MediaCursor(t.cover_pool(8, salt), t.icon_pool(4, salt))
            report.gates["bridgeArtwork2"] = bridge_media(bridge, events, c, controller, simulation, report, out, cursor)
        watch.checkpoint("bridgeArtwork2")
    finally:
        if runtime is not None:
            try:
                runtime.shutdown(close_device=False)
            except Exception as exc:
                report.data["runtimeShutdown"] = f"{type(exc).__name__}: {exc}"
        bridge.submit("close")
        bridge._thread.join(timeout=5)
        report.data["bridgeEvents"] = events.log[-200:]
        report.data["portClosed"] = bridge.serial is None
    return caps


# ---------------------------------------------------------------------------
# Part B: raw serial

class Ids:
    def __init__(self, start=101):
        self.value = start

    def __call__(self):
        self.value += 1
        return self.value


def knob_events_between(knob, start, end):
    """Every knob event (claimed or native, turns and presses) seen in [start, end]."""
    return [(ts, e) for ts, e in knob.claimed_events + knob.native_events if start <= ts <= end]


class RawContext:
    """What the raw artwork2 sections share: the knob, its frames, the pools and error marks."""

    def __init__(self, knob, report, v4, next_id, run, cursor, capability):
        self.knob, self.report, self.next_id, self.run = knob, report, next_id, run
        self.cursor, self.capability = cursor, capability
        self.bases = {name: v4[fixture] for name, fixture in MEDIA_BASES.items()}

    def mark(self):
        knob = self.knob
        return len(knob.errors), len(knob.released), len(knob.art_errors), len(knob.media_errors)

    def since(self, mark):
        knob = self.knob
        return knob.errors[mark[0]:], knob.released[mark[1]:], knob.art_errors[mark[2]:], knob.media_errors[mark[3]:]

    def frame(self, layout, cid, **fields):
        return {**self.bases[layout], "id": cid, **fields}

    def enter(self, layout, **fields):
        cid = self.next_id()
        base = self.bases[layout]
        self.knob.enter(t.raw_control(cid, PROFILE[layout], base["ring"]["count"] - 1, base["ring"]["index"],
                                      {**base, **fields}))
        return cid


def require_artwork2(negotiated):
    if not negotiated:
        raise RuntimeError("artwork2 is not negotiated (capability missing or different); section not run")


def wait_decode(knob, before, timeout=1.5):
    """Poll diag until jpegDecodes exceeds `before`: (seconds, diag) or (None, the last diag)."""
    started = knob.now()
    diag = None
    while knob.now() - started < timeout:
        diag = knob.diag()
        value = t.media_counter(diag, "jpegDecodes")
        if value is not None and before is not None and value > before:
            return round(knob.now() - started, 3), diag
        knob.pump(0.1)
    return None, diag


def settled_decodes(knob, timeout=2.0):
    """jpegDecodes once two diag replies 0.3 s apart agree (the LCD finished what it was drawing)."""
    started, last = knob.now(), None
    while knob.now() - started < timeout:
        value = t.media_counter(knob.diag(), "jpegDecodes")
        if value is not None and value == last:
            return value
        last = value
        knob.pump(0.3)
    return last


def media_round_trip(ctx, out):
    knob, report, cap = ctx.knob, ctx.report, ctx.capability
    (cover_key, cover), (icon_key, icon) = ctx.cursor.cover(), ctx.cursor.icon()
    m = ctx.mark()
    cid = ctx.enter("recent", artKey=cover_key)          # the frame names the cover before its media lines
    chunks = -(-len(cover) // cap["chunkBytes"])
    cold = t.media_transfer(knob, cid, "cover", cover_key, cover)
    ok = [report.check(f"media cover round trip: begin at 0, every data offset acknowledged, commit = bytes "
                       f"({len(cover)} B baseline JPEG, {chunks} data lines)",
                       cold["beginOffset"] == 0 and cold["chunks"] == chunks and cold["committed"] and not cold["error"],
                       brief(cold))]
    hit = t.media_transfer(knob, cid, "cover", cover_key, cover)
    ok.append(report.check("media cover begin-hit: begin answers the full size, no data line, commit succeeds",
                           hit["hit"] and hit["chunks"] == 0 and hit["committed"] and not hit["error"], brief(hit)))
    knob.frame(ctx.frame("windows", cid, iconKey=icon_key))
    icold = t.media_transfer(knob, cid, "icon", icon_key, icon)
    ok.append(report.check(f"media icon round trip: begin at 0, one {cap['icon']['bytes']} B data line, commit",
                           icold["beginOffset"] == 0 and icold["chunks"] == 1 and icold["committed"] and not icold["error"],
                           brief(icold)))
    ihit = t.media_transfer(knob, cid, "icon", icon_key, icon)
    ok.append(report.check("media icon begin-hit", ihit["hit"] and ihit["committed"] and not ihit["error"], brief(ihit)))
    missing = f"cc53miss{ctx.run}"
    have_cover = t.media_have(knob, cid, "cover", [cover_key, missing])
    have_icon = t.media_have(knob, cid, "icon", [icon_key, missing])
    ok.append(report.check("media have: true for the committed cover and icon, false for a key never sent",
                           have_cover.get("have") == [True, False] and have_icon.get("have") == [True, False]
                           and "error" not in have_cover and "error" not in have_icon,
                           {"cover": have_cover, "icon": have_icon}))
    knob.pump(0.3)
    errors, released, _, media_errors = ctx.since(m)
    ok.append(report.check("media round trips: no error reply, media error or release", not (errors or released or media_errors),
                           {"errors": errors, "released": released, "mediaErrors": media_errors}))
    out.update(cover=brief(cold), coverHit=brief(hit), icon=brief(icold), iconHit=brief(ihit),
               have={"cover": have_cover, "icon": have_icon})
    knob.release()
    return all(ok)


def media_prefetch(ctx, out):
    knob, report = ctx.knob, ctx.report
    current_key, current = ctx.cursor.cover()
    prefetch = [ctx.cursor.cover() for _ in range(3)]
    m = ctx.mark()
    cid = ctx.enter("recent", artKey=current_key)
    shown_first = t.media_transfer(knob, cid, "cover", current_key, current)
    results = [t.media_transfer(knob, cid, "cover", key, data) for key, data in prefetch]   # the frame still names current
    ok = [report.check("prefetch: three covers the frame does not name are accepted (cold, committed, no error)",
                       shown_first["committed"] and all(r["committed"] and not r["hit"] and not r["error"] for r in results),
                       [brief(r) for r in results])]
    have = t.media_have(knob, cid, "cover", [key for key, _ in prefetch])
    ok.append(report.check("prefetch: have answers true for all three (kept)", have.get("have") == [True] * 3, have))
    before_decodes = settled_decodes(knob)
    before_errors = t.media_counter(knob.diag(), "jpegDecodeErrors")
    target_key, target = prefetch[1]
    knob.frame(ctx.frame("recent", cid, artKey=target_key))          # a frame now names a prefetched cover
    named = t.media_transfer(knob, cid, "cover", target_key, target)
    seconds, diag = wait_decode(knob, before_decodes)
    ok.append(report.check("prefetch: the named prefetched cover is a begin-hit (no upload needed)",
                           named["hit"] and named["committed"] and not named["error"], brief(named)))
    last_ms = t.media_counter(diag, "jpegDecodeMsLast")
    ok.append(report.check(f"prefetch: the LCD decoded it at once (jpegDecodes +1 within 1.5 s, no decode error, "
                           f"jpegDecodeMsLast <= {t.JPEG_DECODE_MAX_MS} ms)",
                           seconds is not None and t.media_counter(diag, "jpegDecodeErrors") == before_errors
                           and last_ms is not None and last_ms <= t.JPEG_DECODE_MAX_MS,
                           {"seconds": seconds, "before": before_decodes, "diag": t.media_diag_summary(diag)}))
    (icon_key, icon), (pre_key, pre_icon) = ctx.cursor.icon(), ctx.cursor.icon()
    knob.frame(ctx.frame("windows", cid, iconKey=icon_key))
    icon_now = t.media_transfer(knob, cid, "icon", icon_key, icon)
    icon_pre = t.media_transfer(knob, cid, "icon", pre_key, pre_icon)                  # not named by any frame
    icon_have = t.media_have(knob, cid, "icon", [pre_key])
    knob.frame(ctx.frame("windows", cid, iconKey=pre_key))
    icon_named = t.media_transfer(knob, cid, "icon", pre_key, pre_icon)
    ok.append(report.check("prefetch: an icon the frame does not name is accepted, kept (have) and a begin-hit once "
                           "a Windows frame names it",
                           icon_now["committed"] and icon_pre["committed"] and not icon_pre["hit"]
                           and icon_have.get("have") == [True] and icon_named["hit"] and icon_named["committed"],
                           {"prefetch": brief(icon_pre), "have": icon_have, "named": brief(icon_named)}))
    knob.pump(0.3)
    errors, released, _, media_errors = ctx.since(m)
    ok.append(report.check("prefetch: no error reply, media error or release", not (errors or released or media_errors),
                           {"errors": errors, "released": released, "mediaErrors": media_errors}))
    out.update(prefetch=[brief(r) for r in results], have=have, named=brief(named), shownSeconds=seconds,
               decodes={"before": before_decodes, "after": t.media_diag_summary(diag)},
               icon={"prefetch": brief(icon_pre), "have": icon_have, "named": brief(icon_named)})
    knob.release()
    return all(ok)


def media_pinning(ctx, out):
    """The frame's (and the displayed) key is never evicted while the store fills past capacity."""
    knob, report, cap = ctx.knob, ctx.report, ctx.capability
    m = ctx.mark()
    evictions_before = t.media_counter(knob.diag(), "mediaEvictions")
    ok, detail = [], {}
    pinned_key, pinned = ctx.cursor.cover()
    cid = ctx.enter("recent", artKey=pinned_key)
    for kind, pin in (("cover", (pinned_key, pinned)), ("icon", ctx.cursor.icon())):
        if kind == "icon":
            knob.frame(ctx.frame("windows", cid, iconKey=pin[0]))
        first = t.media_transfer(knob, cid, kind, pin[0], pin[1])
        others = [ctx.cursor.next(kind) for _ in range(cap[kind]["entries"] + 2)]   # one past the slots, plus one
        results = [t.media_transfer(knob, cid, kind, key, data) for key, data in others]
        keep = [pin[0]] + [key for key, _ in others[-(cap["haveKeys"] - 1):]]
        gone = [key for key, _ in others[:2]]
        have_keep, have_gone = t.media_have(knob, cid, kind, keep), t.media_have(knob, cid, kind, gone)
        uploads_ok = first["committed"] and all(r["committed"] and not r["hit"] and not r["error"] for r in results)
        slots = cap[kind]["entries"] + 1
        ok.append(report.check(f"pinning ({kind}s): the frame's {kind} stays while {len(others)} more fill the "
                               f"{slots}-slot store; the newest {len(keep) - 1} stay and the two oldest are evicted",
                               uploads_ok and have_keep.get("have") == [True] * len(keep)
                               and have_gone.get("have") == [False, False],
                               {"uploads": len(results), "allCommitted": uploads_ok,
                                "pinnedAndNewest": have_keep.get("have"), "oldest": have_gone.get("have")}))
        detail[kind] = {"pinned": brief(first), "uploads": len(results), "allCommittedCold": uploads_ok,
                        "haveKept": have_keep, "haveEvicted": have_gone}
    evictions_after = t.media_counter(knob.diag(), "mediaEvictions")
    grew = None if None in (evictions_before, evictions_after) else evictions_after - evictions_before
    ok.append(report.check("pinning: diag mediaEvictions grew by at least 4 (two covers, two icons)",
                           grew is not None and grew >= 4, {"before": evictions_before, "after": evictions_after}))
    knob.pump(0.3)
    errors, released, _, media_errors = ctx.since(m)
    ok.append(report.check("pinning: no error reply, media error or release", not (errors or released or media_errors),
                           {"errors": errors, "released": released, "mediaErrors": media_errors}))
    out.update(detail, evictions={"before": evictions_before, "after": evictions_after})
    knob.release()
    return all(ok)


def media_error_cases(ctx, out):
    """Every ARTWORK2.md 4.3 error string reachable without risk, in validation order."""
    knob, report, cap = ctx.knob, ctx.report, ctx.capability
    (k1, c1), (k2, c2), (k3, c3) = ctx.cursor.cover(), ctx.cursor.cover(), ctx.cursor.cover()
    icon_key, _icon = ctx.cursor.icon()
    bad = t.bad_cover_payloads()
    chunk = cap["chunkBytes"]
    b64 = lambda data: base64.b64encode(data).decode("ascii")  # noqa: E731
    cid = ctx.enter("recent", artKey=k1)
    errors_before = t.media_counter(knob.diag(), "mediaErrors")
    m = ctx.mark()
    cases, error_acks = [], [0]

    def expect(name, request, error=None, offset=0, drop=()):
        """One case. Its reply must be exactly the ARTWORK2.md 4.2 reply: the request's id, op, kind
        and key, less `drop` (the fields that do not parse validly; a have reply never has a key),
        `offset` unless the op is have (the received count when an upload context matched, else 0),
        and `error`. A raw line (bytes) must get the 4.3 parse reply {"op","error","id","key"}, id
        and key from its 192-byte prefix."""
        if isinstance(request, (bytes, bytearray)):
            ack, _ = knob.media_line(request, what=name)
            wanted = {"op": "parse", "error": "parse", "id": cid, "key": k1}
        else:
            ack, _ = knob.media(request)
            have = request.get("op") == "have"
            wanted = {k: request[k] for k in ("id", "op", "kind", "key")
                      if k in request and k not in drop and not (have and k == "key")}
            if not have:
                wanted["offset"] = offset
            if error:
                wanted["error"] = error
        if "error" in ack:
            error_acks[0] += 1
        cases.append({"case": name, "expected": error or f"offset {offset}", "reply": wanted, "ack": ack,
                      "passed": ack == wanted})
        return ack

    def req(op, kind="cover", key=k1, **fields):
        return {"id": cid, "op": op, "kind": kind, "key": key, **fields}

    # 1. parse: a malformed and an oversize line; id and key come from the 192-byte prefix
    expect("malformed line", f'{{"media":{{"id":{cid},"op":"data","kind":"cover","key":"{k1}","offset":0,"data":"AAAA\n'
           .encode(), "parse")
    expect("oversize line", ('{"media":{"id":%d,"op":"data","kind":"cover","key":"%s","offset":0,"data":"%s"}}\n'
                             % (cid, k1, "A" * 4200)).encode(), "parse")
    # 2-3. op and kind
    expect("op missing", {"id": cid, "kind": "cover", "key": k1}, "Unknown media operation")
    expect("op unknown", req("replace"), "Unknown media operation", drop=("op",))
    expect("kind unknown", {"id": cid, "op": "have", "kind": "poster", "keys": [k1]}, "Unknown media kind",
           drop=("kind",))
    # 4. "Media unavailable" needs a store that failed to allocate: not reachable without risk.
    # 5. stale control
    expect("stale id", {"id": cid - 1, "op": "have", "kind": "cover", "keys": [k1]}, "Stale media control")
    # 6. have
    expect("have without keys", {"id": cid, "op": "have", "kind": "cover"}, "Invalid media keys")
    expect("have keys not an array", {"id": cid, "op": "have", "kind": "cover", "keys": k1}, "Invalid media keys")
    expect("have with no key", {"id": cid, "op": "have", "kind": "cover", "keys": []}, "Invalid media keys")
    expect(f"have with {cap['haveKeys'] + 1} keys", {"id": cid, "op": "have", "kind": "cover",
                                                    "keys": [f"k{n}" for n in range(cap["haveKeys"] + 1)]},
           "Invalid media keys")
    expect("have with a malformed key", {"id": cid, "op": "have", "kind": "cover", "keys": [k1, "bad key!"]},
           "Invalid media keys")
    # 6. begin
    crc1 = t.art_crc(c1)
    expect("begin with a malformed key", req("begin", key="bad key!", bytes=len(c1), crc32=crc1), "Invalid media key",
           drop=("key",))
    expect("begin with a 25-character key", req("begin", key="x" * 25, bytes=len(c1), crc32=crc1), "Invalid media key",
           drop=("key",))
    expect("begin without crc32", req("begin", bytes=len(c1)), "Media size and CRC required")
    expect("begin with a text size", req("begin", bytes=str(len(c1)), crc32=crc1), "Media size and CRC required")
    expect("begin with a negative size", req("begin", bytes=-1, crc32=crc1), "Media size and CRC required")
    expect("cover of 0 bytes", req("begin", bytes=0, crc32=0), "Invalid media size")
    expect("cover over maxBytes", req("begin", bytes=cap["cover"]["maxBytes"] + 1, crc32=crc1), "Invalid media size")
    expect("icon not 2048 bytes", req("begin", kind="icon", key=icon_key, bytes=cap["icon"]["bytes"] - 1, crc32=0),
           "Invalid media size")
    # 6. data (before the first chunk the upload holds 0 bytes, so a matched context's offset is 0 too)
    expect("data with a malformed key", req("data", key="bad key!", offset=0, data=b64(c2[:16])), "Invalid media key",
           drop=("key",))
    expect("data without an upload", req("data", key=k2, offset=0, data=b64(c2[:16])), "No matching media upload")
    expect("begin of a real upload", req("begin", key=k2, bytes=len(c2), crc32=t.art_crc(c2)), offset=0)
    expect("data for another key", req("data", key=k3, offset=0, data=b64(c3[:16])), "No matching media upload")
    expect("data for another kind", req("data", kind="icon", key=k2, offset=0, data=b64(c2[:16])),
           "No matching media upload")
    expect("data not base64", req("data", key=k2, offset=0, data="@@@@"), "Invalid media data")
    expect("data empty", req("data", key=k2, offset=0, data=""), "Invalid media data")
    expect("data over chunkBytes", req("data", key=k2, offset=0, data=b64(c2[:chunk + 1])), "Invalid media data")
    expect("data past the end", req("data", key=k2, offset=len(c2) - 1, data=b64(c2[-4:])), "Media chunk bounds")
    expect("data at the wrong offset", req("data", key=k2, offset=1, data=b64(c2[1:17])), "Media offset mismatch")
    first = min(chunk, len(c2))
    expect("first chunk", req("data", key=k2, offset=0, data=b64(c2[:first])), offset=first)
    expect("identical retry of that chunk (accepted, nothing changes)", req("data", key=k2, offset=0, data=b64(c2[:first])),
           offset=first)
    expect("changed retry of that chunk", req("data", key=k2, offset=0, data=b64(bytes([c2[0] ^ 1]) + c2[1:first])),
           "Media offset mismatch", offset=first)
    expect("data not base64 during the upload", req("data", key=k2, offset=first, data="@@@@"), "Invalid media data",
           offset=first)
    expect("data past the end during the upload", req("data", key=k2, offset=len(c2) - 1, data=b64(c2[-4:])),
           "Media chunk bounds", offset=first)
    # 6. commit
    expect("commit before the last chunk", req("commit", key=k2), "Media upload incomplete", offset=first)
    expect("commit with a malformed key", req("commit", key="bad key!"), "Invalid media key", drop=("key",))
    expect("commit for another key", req("commit", key=k3), "No matching media upload")
    for offset in range(first, len(c2), chunk):
        expect(f"chunk at {offset}", req("data", key=k2, offset=offset, data=b64(c2[offset:offset + chunk])),
               offset=min(len(c2), offset + chunk))
    expect("commit of the complete upload", req("commit", key=k2), offset=len(c2))
    expect("begin-hit of that cover", req("begin", key=k2, bytes=len(c2), crc32=t.art_crc(c2)), offset=len(c2))
    expect("data for a begin-hit context", req("data", key=k2, offset=0, data=b64(c2[:16])), "No matching media upload")
    expect("commit of the begin-hit", req("commit", key=k2), offset=len(c2))
    transfers = {}
    crc = t.media_transfer(knob, cid, "cover", k3, c3, crc=t.art_crc(c3) ^ 1)
    transfers["checksum"] = brief(crc)
    error_acks[0] += 1 if crc["error"] else 0
    cancelled = {"checksum": crc["errorOp"] == "commit" and crc["error"] == "Media checksum mismatch"}
    for name, payload in bad.items():
        key = hashlib.sha256(payload).hexdigest()[:24]
        result = t.media_transfer(knob, cid, "cover", key, payload)
        transfers[name] = brief(result)
        error_acks[0] += 1 if result["error"] else 0
        cancelled[name] = result["errorOp"] == "commit" and result["error"] == "Media decode failed"
    refused = [k3] + [hashlib.sha256(payload).hexdigest()[:24] for payload in bad.values()]
    have = t.media_have(knob, cid, "cover", refused)
    ok = [report.check("media errors: each case answers exactly its ARTWORK2.md 4.3 error string (parse, Unknown media "
                       "operation, Unknown media kind, Stale media control, Invalid media keys, Invalid media key, "
                       "Media size and CRC required, Invalid media size, No matching media upload, Invalid media data, "
                       "Media chunk bounds, Media offset mismatch, Media upload incomplete) with the 4.2 reply shape "
                       "(the id, op, kind and key that parsed validly, offset = the received count when an upload "
                       "matched, else 0) and the identical retry is accepted", all(c["passed"] for c in cases),
                       [c for c in cases if not c["passed"]] or len(cases))]
    ok.append(report.check("media errors: Media checksum mismatch, and Media decode failed for a progressive, a 120 px "
                           "and a non-JPEG payload, each at commit; none of them is kept (have false)",
                           all(cancelled.values()) and have.get("have") == [False] * len(refused),
                           {"cancelled": cancelled, "have": have}))
    knob.release()
    expect("after the release (no session)", {"id": cid, "op": "have", "kind": "cover", "keys": [k1]},
           "Stale media control")
    ok.append(report.check("media errors: after a release every media line is Stale media control", cases[-1]["passed"],
                           cases[-1]["ack"]))
    errors_after = t.media_counter(knob.diag(), "mediaErrors")
    counted = None if None in (errors_before, errors_after) else errors_after - errors_before
    ok.append(report.check(f"media errors: diag mediaErrors counted exactly the {error_acks[0]} error replies",
                           counted == error_acks[0], {"before": errors_before, "after": errors_after}))
    knob.pump(0.3)
    errors, released, _, _ = ctx.since(m)
    ok.append(report.check("media errors: no bare error reply (every media line got a mediaAck) and only the "
                           "intended release", not errors and len(released) == 1,
                           {"errors": errors, "released": released}))
    out.update(cases=cases, transfers=transfers, have=have, errorReplies=error_acks[0],
               mediaErrors={"before": errors_before, "after": errors_after},
               notReachable={"Media unavailable": "needs a media store that failed to allocate (artwork2.available "
                                                  "is true, so both are allocated); not provoked"})
    return all(ok)


def media_timing(ctx, out):
    """Unpaced transfer timing: five cold covers and five cold icons, each named by a frame first."""
    knob, report = ctx.knob, ctx.report
    covers = [ctx.cursor.cover() for _ in range(5)]
    icons = [ctx.cursor.icon() for _ in range(5)]
    m = ctx.mark()
    cid = ctx.enter("recent", artKey=covers[0][0])
    results = []
    for key, data in covers:
        knob.frame(ctx.frame("recent", cid, artKey=key))
        results.append(t.media_transfer(knob, cid, "cover", key, data))
    for key, data in icons:
        knob.frame(ctx.frame("windows", cid, iconKey=key))
        results.append(t.media_transfer(knob, cid, "icon", key, data))
    lines = [s for r in results for s in r["lineSeconds"]]
    cover_seconds = [r["seconds"] for r in results if r["kind"] == "cover"]
    cover_bytes = sum(len(d) for _, d in covers)
    limit = t.presentation().MEDIA_ACK_TIMEOUT_SECONDS
    committed = all(r["committed"] and not r["hit"] and not r["error"] for r in results)
    out.update(perLine=t.summarize_ms(lines), coverSeconds=cover_seconds,
               iconSeconds=[r["seconds"] for r in results if r["kind"] == "icon"],
               coverBytes=[len(d) for _, d in covers],
               coverBytesPerSecond=round(cover_bytes / sum(cover_seconds)) if sum(cover_seconds) else None,
               ackLimitSeconds=limit, coverLimitSeconds=t.COVER_TRANSFER_MAX_SECONDS)
    ok = [report.check("unpaced timing: five cold covers and five cold icons committed", committed,
                       [brief(r) for r in results if not r["committed"] or r["error"]])]
    ok.append(report.check(f"unpaced timing: every media ack within {limit:g} s (the host's ack timeout)",
                           bool(lines) and max(lines) <= limit, out["perLine"]))
    ok.append(report.check(f"unpaced timing: every cover (begin to commit) within {t.COVER_TRANSFER_MAX_SECONDS:g} s "
                           "(a paced 120 px v1 cover took about 5 s)",
                           bool(cover_seconds) and max(cover_seconds) <= t.COVER_TRANSFER_MAX_SECONDS, cover_seconds))
    knob.pump(0.3)
    errors, released, _, media_errors = ctx.since(m)
    ok.append(report.check("unpaced timing: no error reply, media error or release",
                           not (errors or released or media_errors),
                           {"errors": errors, "released": released, "mediaErrors": media_errors}))
    knob.release()
    return all(ok)


# ---------------------------------------------------------------------------
# 1.0.0-cc5.4 (--release cc5.4): LED and LCD timing, hold, End stop and F24 icon-gate sections

def wait_message(knob, predicate, timeout):
    """(time, message) of the first message after now that satisfies `predicate`, within `timeout` s
    (heartbeats continue while waiting), else (None, None)."""
    first, end = len(knob.messages), knob.now() + timeout
    while True:
        for ts, message in knob.messages[first:]:
            if predicate(message):
                return ts, message
        first = len(knob.messages)
        if knob.now() >= end:
            return None, None
        knob.pump(0.02)


def v5_frame(device, live_caps, base, **fields):
    """A fixture base with v5 fields, through the companion's own validation (device._frame)."""
    return device._frame({**deepcopy(base), **fields}, live_caps)


def led_idle(knob, report, next_id, home, out):
    """ALIVE.md 11.9: an untouched Home control; ledFps >= 58 and ledShowGapMsMax <= 20 ms over the
    last LED_IDLE_SECONDS (the first diag read resets the gap)."""
    cid = next_id()
    knob.enter(t.raw_control(cid, PROFILE["volume"], 100, 54, {**home, "title": "LED idle"}))
    knob.pump(0.5)
    out["reset"] = t.led_idle_problems(knob.diag())          # read-and-reset; its values include the entry
    knob.pump(LED_IDLE_SECONDS)
    diag = knob.diag()
    problems = t.led_idle_problems(diag)
    out.update(diag={k: diag.get(k) for k in t.ALIVE_DIAG_FIELDS}, problems=problems, seconds=LED_IDLE_SECONDS)
    report.check(f"LED at idle: ledFps >= {t.ALIVE_LED_FPS_IDLE_MIN}, ledShowGapMsMax <= "
                 f"{t.ALIVE_LED_SHOW_GAP_IDLE_MAX_MS} ms (ALIVE.md 11.9)", not problems, problems or out["diag"])
    knob.release()
    return not problems


def animate(knob, cid, screens, period, seconds):
    """Alternate `screens` every `period` s for about `seconds`, then send one more change and return at
    once, so the caller's diag read is taken while that change's tweens run. Returns the changes sent."""
    changes = max(1, round(seconds / period))
    for n in range(changes):
        knob.frame({**screens[n % 2], "id": cid})
        knob.pump(period)
    knob.frame({**screens[changes % 2], "id": cid})
    return changes + 1


def animation_pass(knob, cid, screens, period):
    """One lcdAnimation pass: ANIM_LEAD_S of continuous animation, the read that resets lcdFpsAnimMin
    (taken mid-animation), ANIM_PASS_S more, then the measured read (also mid-animation). (lead, end, changes)."""
    changes = animate(knob, cid, screens, period, ANIM_LEAD_S)
    lead = knob.diag()
    changes += animate(knob, cid, screens[::-1] if changes % 2 else screens, period, ANIM_PASS_S)
    return lead, knob.diag(), changes


def lcd_animation(ctx, device, live_caps, tracks, out):
    """PRESENTATION_V5 12.2 / 12.6: slides over a shown cover (recent <-> tracks), then art show/hide
    (recent <-> windows). Each pass animates without a gap from before its lcdFpsAnimMin reset to its
    measured read (SLIDE_PERIOD_S / FADE_PERIOD_S above), so every whole second it measures is animated.
    lcdLateRefrs is taken over the opaque pass only (lcd_late_refreshes: since boot or reset on read, told
    apart by two reads at rest), never as the absolute count, which on B and C includes the earlier sections'
    cover arrivals. Releases its control; True when both passes meet the binary's targets."""
    knob, report = ctx.knob, ctx.report
    key, cover = ctx.cursor.cover()
    recent = v5_frame(device, live_caps, ctx.bases["recent"], artKey=key, title="Slides")
    cid = ctx.next_id()
    knob.enter(t.raw_control(cid, PROFILE["recent"], recent["ring"]["count"] - 1, recent["ring"]["index"], recent))
    upload = t.media_transfer(knob, cid, "cover", key, cover)
    knob.pump(0.5)
    first = knob.diag()
    again = knob.diag()                          # back to back at rest: how lcdLateRefrs counts
    semantics = t.late_refresh_semantics(first, again)
    binary = t.lcd_binary(first)
    out.update(binary=binary, pipeline={k: first.get(k) for k in ("lcdDma", "lcdPeriodMs", "artAsync", "lcdSpiHz")},
               coverCommitted=upload["committed"])
    screens = (v5_frame(device, live_caps, tracks, artKey=key, title="Slides"), recent)
    opaque_lead, opaque, slides = animation_pass(knob, cid, screens, SLIDE_PERIOD_S)
    windows = v5_frame(device, live_caps, ctx.bases["windows"], title="Fades")
    blended_lead, blended, fades = animation_pass(knob, cid, (windows, recent), FADE_PERIOD_S)
    late = {"opaque": t.lcd_late_refreshes(semantics, again, opaque_lead, opaque),
            "blended": t.lcd_late_refreshes(semantics, opaque, blended_lead, blended)}
    problems = {"opaque": t.lcd_timing_problems(opaque, binary, "opaque", late["opaque"]),
                "blended": t.lcd_timing_problems(blended, binary, "blended")}
    out.update(opaque=t.lcd_diag_summary(opaque), blended=t.lcd_diag_summary(blended), problems=problems,
               targets=t.LCD_FPS_TARGETS.get(binary),
               cadence={"slidePeriodS": SLIDE_PERIOD_S, "fadePeriodS": FADE_PERIOD_S, "leadS": ANIM_LEAD_S,
                        "measuredS": ANIM_PASS_S, "slides": slides, "fades": fades},
               lateRefreshes={"semantics": semantics or "unknown (0 at rest)",
                              "atRest": [t.diag_int(first, "lcdLateRefrs"), t.diag_int(again, "lcdLateRefrs")],
                              "opaquePass": late["opaque"], "blendedPass": late["blended"]})
    for kind in ("opaque", "blended"):
        report.check(f"LCD {kind} pass (binary {binary}): lcdFpsAnimMin >= "
                     f"{(t.LCD_FPS_TARGETS.get(binary) or {}).get(kind)}"
                     + (", no late refresh during the pass (lcdLateRefrs)" if kind == "opaque" else ""),
                     not problems[kind], problems[kind] or t.lcd_diag_summary(opaque if kind == "opaque" else blended))
    enter = t.diag_int(blended, "enterMsMax")
    out["enterMsMax"] = {"ms": enter, "reportAbove": t.V5_ENTER_MS_MAX,
                         "note": "reported, not gated: above it, investigate before release (12.2)"}
    if enter is not None and enter > t.V5_ENTER_MS_MAX:
        print(f"Note: enterMsMax {enter} ms > {t.V5_ENTER_MS_MAX} ms: investigate before release "
              "(PRESENTATION_V5 12.2)", flush=True)
    knob.release()
    return upload["committed"] and not problems["opaque"] and not problems["blended"]


def led_under_load(ctx, out):
    """ALIVE.md 11.9: cover transfers back to back with diag read after each; the pass rule is ledFps
    >= 45 in every sample (55, ledShowGapMsMax and ledLateShows recorded). Releases its control."""
    knob, report = ctx.knob, ctx.report
    cid = ctx.enter("recent", title="LED load")
    knob.diag()                                                 # reset the per-read maxima
    samples, committed = [], 0
    for _ in range(LED_LOAD_TRANSFERS):
        key, cover = ctx.cursor.cover()
        knob.frame({**ctx.frame("recent", cid), "artKey": key, "title": "LED load"})
        committed += 1 if t.media_transfer(knob, cid, "cover", key, cover)["committed"] else 0
        samples.append(knob.diag())
    summary = t.led_load_summary(samples)
    out.update(summary, transfers=LED_LOAD_TRANSFERS, committed=committed)
    report.check(f"LED under cover transfers: ledFps >= {t.ALIVE_LED_FPS_TRANSFER_MIN} in every sample (target "
                 f"{t.ALIVE_LED_FPS_TRANSFER_TARGET}, recorded)", summary["passed"] and committed == LED_LOAD_TRANSFERS,
                 {k: summary[k] for k in ("ledFpsMin", "targetMet", "ledShowGapMsMax", "ledLateShows", "problems")})
    if summary["passed"] and not summary["targetMet"]:
        print(f"Note: ledFps under load {summary['ledFpsMin']} is between {t.ALIVE_LED_FPS_TRANSFER_MIN} and "
              f"{t.ALIVE_LED_FPS_TRANSFER_TARGET}: tell the user (the case for R7 in a later release, ALIVE.md 11.9)",
              flush=True)
    knob.release()
    return summary["passed"] and committed == LED_LOAD_TRANSFERS


def say(text):
    """A log line (the operator reads the knob, never the console)."""
    print(f"[log] {text}", flush=True)


# ---------------------------------------------------------------------------
# Hands-on steps (user ruling 2026-09-26): every instruction is on the knob's own screen (tooling.KnobPrompter),
# each step advances only on the device events that show it was done, and nothing beeps. The gates, their
# thresholds and their evidence fields are unchanged; the windows now come from the prompts and the events.

def prompt_plan(profile, hid_check=False):
    """The steps the knob will show, in order: the display check, the turning test, and (presentation 5) the
    hold, deferred-hold and End stop steps, plus the two F24 steps with --hid-check."""
    plan = [t.DISPLAY_STEP, "turn"]
    if profile.presentation >= 5:
        plan += ["hold1", "hold2", "deferred", "pushes", "pushhold", "zero"]
        if hid_check:
            plan += ["f24home", "f24tracks"]
    return plan


def kd_of(p, raw, since):
    """Wait for the kd of Button raw+1 on the prompter's control (another button: "That was Button N").
    Returns its time."""
    cid = p.cid

    def check(batch, now):
        for ts, m in batch:
            if m.get("id") == cid and isinstance(m.get("kd"), int):
                if m["kd"] == raw:
                    return ts
                p.retry(f"That was Button {m['kd'] + 1}")
        return None
    return p.wait(check, what=f"Button {raw + 1} pressed", since=since)


def ku_after(p, raw, kd_at, since, what):
    """Wait for the key-up of Button raw+1 after its kd (whatever control it names). Returns its time."""
    def check(batch, now):
        return next((ts for ts, m in batch if m.get("ku") == raw and ts >= kd_at), None)
    return p.wait(check, what=what, since=since)


def hold_button1(p, report, out):
    """Step hold1 (PRESENTATION_V5 11.2): "Hold Button 1" with only Button 1 lit; on its kd "Keep holding…", on the
    kh "Let go", on the ku the check listens LATE_KH_S and counts every kh from the kd (hold_check: exactly one, its
    raw, Button 1's bit in ks, 0.45-1.2 s after the kd). A key-up within HOLD_SHORT_S with no kh is "Too short" and
    the attempt is discarded (a kh in it is still evaluated); held HOLD_NO_KH_S with no kh: "Let go", evaluated (the
    firmware sent none)."""
    knob = p.knob
    p.begin("hold1")
    attempts, note = 0, ""
    while True:
        attempts += 1
        cid = p.screen("Hold Button 1", "Hold until it says Let go", note, "error" if note else None,
                       buttons=t.press_buttons(HOLD_RAW))
        since = p.mark()
        kd_at = kd_of(p, HOLD_RAW, since)
        p.update(progress="Keep holding…", note="", tone=None)

        def matured(batch, now, kd_at=kd_at):
            for ts, m in batch:
                if "kh" in m and ts >= kd_at:
                    return "kh", ts
                if m.get("ku") == HOLD_RAW and ts >= kd_at:
                    return "ku", ts
            return ("none", now) if now - kd_at >= HOLD_NO_KH_S else None
        event, at = p.wait(matured, what="the long press of Button 1", since=since)
        if event == "ku":
            knob.pump(LATE_KH_S)
            if at - kd_at < HOLD_SHORT_S and not t.kh_events(knob.messages, kd_at, knob.now()):
                note = "Too short · hold longer"
                p.retry(note)
                continue
        else:
            p.update(say="Let go", progress="", note="", tone=None)
            ku_after(p, HOLD_RAW, kd_at, since, "Button 1 released")
            knob.pump(LATE_KH_S)                     # a late (wrong) kh would arrive here: it is counted
        problems, khs = t.hold_check(knob.messages, cid, HOLD_RAW, HOLD_RAW, kd_at, knob.now())
        break
    p.done()
    out["button1"] = {"problems": problems, "kh": [m for _, m in khs],
                      "khAfterKdMs": [round((ts - kd_at) * 1000) for ts, _ in khs], "attempts": attempts,
                      "controlId": cid}
    return problems


def hold_button2(p, report, out):
    """Step hold2: "Hold Button 2" (only Button 2 lit); on its kd a countdown the tool times ("Keep holding · 2",
    "1"), then "Let go", the ku and LATE_KH_S of listening: no kh at all (only Button 1 holds). An early key-up is
    "Too short" and a retry; a kh for raw 1 in any attempt is a firmware problem and is recorded."""
    knob = p.knob
    p.begin("hold2")
    attempts, stray, note = 0, [], ""
    while True:
        attempts += 1
        cid = p.screen("Hold Button 2", "Hold until it says Let go", note, "error" if note else None,
                       buttons=t.press_buttons(OTHER_RAW))
        since = p.mark()
        kd_at = kd_of(p, OTHER_RAW, since)
        early = None
        for left in range(HOLD2_COUNT, 0, -1):
            p.update(progress=f"Keep holding · {left}", note="", tone=None)
            tick_at = knob.now()

            def released(batch, now, tick_at=tick_at, kd_at=kd_at):
                ku = next((ts for ts, m in batch if m.get("ku") == OTHER_RAW and ts >= kd_at), None)
                if ku is not None:
                    return ku
                return False if now - tick_at >= 1.0 else None
            early = p.wait(released, what="Button 2 held", since=since) or None
            if early is not None:
                break
        if early is not None:
            knob.pump(LATE_KH_S)
            problems, khs = t.hold_check(knob.messages, cid, OTHER_RAW, HOLD_RAW, kd_at, knob.now())
            stray += problems
            note = "Too short · hold until Let go"
            p.retry(note)
            continue
        p.update(say="Let go", progress="", note="", tone=None)
        ku_after(p, OTHER_RAW, kd_at, since, "Button 2 released")
        knob.pump(LATE_KH_S)
        problems, khs = t.hold_check(knob.messages, cid, OTHER_RAW, HOLD_RAW, kd_at, knob.now())
        break
    p.done()
    problems = stray + problems
    out["button2"] = {"problems": problems, "kh": [m for _, m in khs], "attempts": attempts, "controlId": cid}
    return problems


def hold_tests(p, report, out):
    """PRESENTATION_V5 11.2: a hold of Button 1 sends exactly one kh; Button 2 none (steps hold1 and hold2)."""
    first = hold_button1(p, report, out)
    second = hold_button2(p, report, out)
    report.check("hold Button 1: exactly one kh (its raw, Button 1's bit in ks, 0.45-1.2 s after the kd)",
                 not first, first or out["button1"])
    report.check("hold Button 2: no kh (only Button 1 holds)", not second, second or None)
    return not first and not second


def deferred_hold(p, report, out, attempts_max=DEFERRED_ATTEMPTS):
    """Step deferred (PRESENTATION_V5 11.2 step 5): Button 1 held while a new control enters; the ready line's ks
    has its bit (11.3) and one kh with the new id follows the ready line, counted by diag holdDeferred.

    Each attempt: diag (holdDeferred before, enterMsLast), "Hold Button 1"; on its kd the tool waits the planner's
    delay (tooling.DeferredPlanner, from the hardware kd -> kh 0.444-0.506 s and the ~22 ms entry), enters a new
    control ("Keep holding…"), waits up to DEFERRED_KH_WAIT_S after its ready line for the kh, shows "Let go", and
    counts the kh lines from the kd to LATE_KH_S after the ku. An attempt that did not defer refines the planner
    (the kd -> kh it measured) and the next one starts; a key-up before the ready line or the kh is "Too short" and
    the same attempt again. At most `attempts_max` attempts."""
    knob = p.knob
    p.begin("deferred")
    planner = t.DeferredPlanner()
    attempts, short, note, tone = [], 0, "", None
    while len(attempts) < attempts_max:
        n = len(attempts) + 1
        diag = knob.diag()
        before = t.diag_int(diag, "holdDeferred")
        entry_s = planner.entry(t.diag_int(diag, "enterMsLast"))
        cid = p.screen("Hold Button 1", "Hold until it says Let go", note or f"Attempt {n} of {attempts_max}", tone,
                       buttons=t.press_buttons(HOLD_RAW))
        since = p.mark()
        kd_at = kd_of(p, HOLD_RAW, since)
        delay = planner.next_delay()
        p.update(progress="Keep holding…", note=f"Attempt {n} of {attempts_max}", tone=None)
        start = knob.now()

        def early_up(batch, now, kd_at=kd_at, start=start, delay=delay):
            ku = next((ts for ts, m in batch if m.get("ku") == HOLD_RAW and ts >= kd_at), None)
            if ku is not None:
                return ku
            return False if now - start >= delay else None
        if p.wait(early_up, what="Button 1 held", since=since) is not False:
            short += 1
            planner.repeat()
            note, tone = "Too short · hold until Let go", "error"
            p.retry(note)
            continue
        new = p.enter(None, say="Keep holding…", progress="The screen changed", buttons=t.press_buttons(HOLD_RAW))
        ready, ready_at = knob.ready_replies[-1][1], knob.ready_at

        def matured(batch, now, kd_at=kd_at, ready_at=ready_at):
            for ts, m in batch:
                if "kh" in m and ts >= kd_at:
                    return "kh", ts
                if m.get("ku") == HOLD_RAW and ts >= kd_at:
                    return "ku", ts
            return ("none", now) if now - ready_at >= DEFERRED_KH_WAIT_S else None
        event, at = p.wait(matured, what="the long press of Button 1", since=since)
        if event == "ku":
            knob.pump(LATE_KH_S)
            if not t.kh_events(knob.messages, kd_at, knob.now()):
                short += 1
                planner.repeat()
                note, tone = "Too short · hold until Let go", "error"
                p.retry(note)
                continue
            ku_at = at
        else:
            p.update(say="Let go", progress="", note="", tone=None)
            ku_at = ku_after(p, HOLD_RAW, kd_at, since, "Button 1 released")
            knob.pump(LATE_KH_S)
        after = t.diag_int(knob.diag(), "holdDeferred")
        khs = t.kh_events(knob.messages, kd_at, ku_at + LATE_KH_S)
        record = {"attempt": n, "delayS": round(delay, 3), "entryS": entry_s, "estimateS": round(planner.estimate, 4),
                  "readyKs": ready.get("ks"), "kh": [m for _, m in khs],
                  "khAfterKdMs": [round((ts - kd_at) * 1000) for ts, _ in khs],
                  "khAfterReadyMs": [round((ts - ready_at) * 1000) for ts, _ in khs],
                  "holdDeferred": [before, after], "controlIds": [cid, new]}
        problems = []
        if len(khs) != 1:
            problems.append(f"{len(khs)} kh for one physical press (at most one, exactly one here)")
        if not (type(ready.get("ks")) is int and ready["ks"] & (1 << HOLD_RAW)):
            problems.append(f"ready ks {ready.get('ks')!r} lacks Button 1's bit while it was held (11.3)")
        deferred = (len(khs) == 1 and khs[0][1].get("id") == new and khs[0][0] >= ready_at
                    and None not in (before, after) and after == before + 1)
        if not problems and not deferred:
            problems.append("the long press did not mature while the control was entering (holdDeferred unchanged): "
                            "retrying with another delay")
        record["problems"], record["deferred"] = problems, deferred
        attempts.append(record)
        if deferred and not problems:
            break
        if khs:
            planner.observe(khs[0][0] - kd_at)
        note, tone = DEFERRED_AGAIN.format(n=n + 1, of=attempts_max), None
    p.done()
    out.update(attempts=attempts, planner=planner.record(), tooShort=short, attemptsMax=attempts_max)
    ok = bool(attempts) and attempts[-1].get("deferred") is True and not attempts[-1]["problems"]
    report.check("deferred hold: Button 1 held across a control entry -> the ready line's ks has its bit and "
                 "exactly one kh with the new id follows the ready line (diag holdDeferred +1)", ok, attempts[-1:])
    ks_ok = any(type(a.get("readyKs")) is int and a["readyKs"] & (1 << HOLD_RAW) for a in attempts)
    return ok, ks_ok


class SeekScreen:
    """The End stop test's Seek control: the base frame with the ring following the claimed position (0:17 ...
    0:00 live on the knob)."""

    def __init__(self, p, base, t_end):
        self.p, self.base, self.position, self.cid = p, base, t_end, None
        self.t_end = t_end

    def frame(self):
        return {**self.base, "ring": {**self.base["ring"], "index": self.position}}

    def follow(self, batch):
        moved = False
        for _, m in batch:
            if m.get("id") == self.cid and isinstance(m.get("p"), int) and "ready" not in m:
                position = max(0, min(self.t_end, m["p"]))
                moved, self.position = moved or position != self.position, position
        if moved:
            self.p.update(base=self.frame())
        return moved


def end_stop_push(p, seek, say, note, question, nudges, *, direction=1, hold_s=0.0, key="nudge"):
    """One End stop push, event-gated: `say` / `note` on the Seek control; the first lim `direction` of the control
    (after PUSH_NUDGE_S without any event of it: `question` on the knob, Yes = pushed but nothing seen, a missed End
    stop; No = back to the prompt, the window goes on); with `hold_s`, a countdown while held; then "Let go" or "Let
    it spring back" and PROMPT_QUIET_S without a lim of the control. Every lim after the first is a double (chatter)
    and restarts the quiet. Returns (window start, window end, first lim time or None, doubles)."""
    knob, cid = p.knob, seek.cid
    p.screen(say, note=note, base=seek.frame())
    start, since = knob.now(), p.mark()
    while True:
        state = {"last": knob.now()}

        def first(batch, now, state=state):
            seek.follow(batch)
            for i, (ts, m) in enumerate(batch):
                if m.get("id") != cid:
                    continue
                if m.get("lim") == direction:
                    return ts, m
                if t.is_knob_event(m):
                    state["last"] = ts
            return False if now - state["last"] >= PUSH_NUDGE_S else None
        got = p.wait(first, what=f"lim {direction:+d} ({say})", since=since)
        if got is not False:
            break
        yes = p.ask(f"{key}{len(nudges) + 1}", question, base=seek.frame())
        nudges.append({"question": question, "pushed": yes, "at": round(knob.now() - start, 3)})
        if yes:
            return start, knob.now(), None, []
        p.screen(say, note=note, base=seek.frame())
        since = p.mark()
    first_at, first_msg = got
    after = next(i for i in range(len(knob.messages) - 1, -1, -1) if knob.messages[i][1] is first_msg) + 1
    doubles, last = [], {"at": first_at}

    def lims_since(batch):
        seek.follow(batch)
        for ts, m in batch:
            if m.get("id") == cid and m.get("lim") in (-1, 1):
                doubles.append(ts)
                last["at"] = max(last["at"], ts)
    if hold_s:
        for left in range(int(hold_s), 0, -1):
            p.update(note=f"Keep holding · {left}", tone=None)
            tick = knob.now()

            def holding(batch, now, tick=tick):
                lims_since(batch)
                return True if now - tick >= 1.0 else None
            p.wait(holding, what="the push held", since=after)
            after = len(knob.messages)
        p.update(say="Let go", note="Let it spring back", tone=None)
    else:
        p.update(say="Let it spring back", note="", tone=None)

    def settled(batch, now):
        lims_since(batch)
        return now if now - last["at"] >= t.PROMPT_QUIET_S else None
    end = p.wait(settled, what="the knob to settle", since=after)
    return start, end, first_at, doubles


SEEK_FEEL = "fluid.scrub"           # Desk Dial's Seek feel (controller.Controller.feel)


def push_note(n, again=""):
    """The note of push n of PUSHES on the Seek overlay; the first push of a repeat carries `again` ("Again · ") and
    drops "then" so the line fits the glass (TL-TST-002: "Again · Push 1 of 5, then let go" was cut)."""
    if again and n == 1:
        return f"{again}Push {n} of {PUSHES}, let go"
    return f"Push {n} of {PUSHES}, then let go"


def push_test(p, report, device, live_caps, tracks, out, retries):
    """ALIVE.md ruling Q1 (12.5) and 11.9, steps pushes, pushhold and zero: at the right end of a Seek control, one
    lim +1 per push, one while held, none outside; then 0:00 gives lim -1. Every push is its own prompt ("Push past
    the end (n of 5)" -> the lim -> "Let it spring back" -> PROMPT_QUIET_S without a lim), so the windows run from
    each prompt to its quiet end (tooling.EndStopWindows, grace 0). Returns (per-push ok, both Seek ends seen)."""
    knob = p.knob
    t_end = SEEK_DURATION_S - SEEK_MARGIN_S
    base = v5_frame(device, live_caps, tracks, layout="seek", heading="SEEK", title="End stop test",
                    subtitle="", value="", meta=f"of 0:{SEEK_DURATION_S:02d}",
                    ring={"style": "lap", "value": 0, "index": t_end, "count": SEEK_DURATION_S})
    runs = []
    for attempt in range(1 + max(0, retries)):
        p.begin("pushes")
        again = "Again · " if attempt else ""
        seek = SeekScreen(p, base, t_end)
        # Desk Dial's Seek feel on an r4 knob, so its walls follow the r4 wall law and not the cc5.6 loop; silent
        # (volume 0) like every hands-on step; nothing is added for an older knob (its control line is unchanged).
        seek.cid = p.enter(seek.frame(), PROFILE["tracks"], t_end, t_end, say="End stop test",
                           note=f"{again}{PUSHES} pushes", extra=t.feel_fields(device, live_caps, SEEK_FEEL))
        start = knob.now()
        windows, nudges = t.EndStopWindows(), []
        for n in range(1, PUSHES + 1):
            a, b, first, doubles = end_stop_push(p, seek, "Push past the end", push_note(n, again), "Did you push?",
                                                 nudges, key=f"push{n}.")
            windows.push(a, b, missed=first is None)
            for at in doubles:
                windows.double(n, at)
        p.done()
        p.begin("pushhold")
        a, b, first, doubles = end_stop_push(p, seek, "Push and hold", "Hold it against the end", "Did you push?",
                                             nudges, hold_s=HOLD_WINDOW_S, key="hold.")
        windows.held(a, b)
        for at in doubles:
            windows.double("hold", at)
        p.done()
        p.begin("zero")
        p.screen("Turn to 0:00", note="Then push past it once", base=seek.frame())
        since = p.mark()

        def at_zero(batch, now):
            seek.follow(batch)
            return next((ts for ts, m in batch if m.get("id") == seek.cid and m.get("p") == 0 and "ready" not in m),
                        None)
        zero = p.wait(at_zero, what="the knob at 0:00", since=since)
        _, _, low, _ = end_stop_push(p, seek, "Now push past 0:00", "", "Pushed past 0:00?", nudges, direction=-1,
                                     key="zero.")
        p.done()
        lims = t.limit_events(knob.messages, seek.cid, start, knob.now())
        pushed = windows.evaluate(lims)
        ends = t.limit_problems(lims)
        runs.append({"attempt": attempt + 1, "controlId": seek.cid, "tEnd": t_end, **{k: pushed[k] for k in
                     ("perPush", "held", "stray", "problems")}, "reachedZero": zero is not None,
                     "limAtZero": low is not None, "seekEnds": ends,
                     "lims": [(round(ts - start, 3), d) for ts, d in lims], "windows": windows.record(start),
                     "nudges": nudges})
        if pushed["passed"] and not ends:
            break
    last = runs[-1]
    counts = last["perPush"]
    advice = ("raise lim_rearm_ms (a push fired twice)" if any(c > 1 for c in counts) or last["held"] > 1 else
              "lower lim_rearm_ms or push more slowly (a push was missed)" if any(c == 0 for c in counts) else
              "keep lim_rearm_ms")
    out.update(runs=runs, limRearmMs={"firmware": t.ALIVE_LIM_REARM_MS, "range": [40, 150], "advice": advice,
                                      "note": "tuned by hand from these counts (ALIVE.md 12.5); record the value flashed"})
    report.check("End stop per push (ruling Q1): exactly one lim +1 per push, one while held, none outside",
                 not last["problems"], last["problems"] or {"perPush": counts, "held": last["held"]})
    report.check("Seek End stop: lim +1 at T_end and lim -1 at 0:00", not last["seekEnds"],
                 last["seekEnds"] or None)
    return not last["problems"], not last["seekEnds"]


def hid_gate(p, report, home, tracks, out):
    """PRESENTATION_V5 11.4 (opt-in: F24 reaches Windows), steps f24home and f24tracks: F24 and hid:1 only from a
    Home control whose Button 4 is `win`; Button 4 on Tracks (icon next) sends no F24 and no hid. Each step is
    "Press Button 4" on that control, complete at its key-up; another button is a retry."""
    results = {}
    win = {"label": "Win", "enabled": True, "icon": "win"}
    cases = (("home", "f24home", PROFILE["volume"], home, True),
             ("tracks", "f24tracks", PROFILE["tracks"], tracks, False))
    for name, step, profile, frame, expect_hid in cases:
        buttons = deepcopy(frame["buttons"])
        if expect_hid:
            buttons[HID_RAW] = win
        frame = {**frame, "buttons": buttons}
        p.begin(step)
        p.enter(frame, profile, 100 if expect_hid else frame["ring"]["count"] - 1,
                54 if expect_hid else frame["ring"]["index"], windows_button=HID_RAW, windows_hid=True,
                say="Press Button 4", progress="Once")
        down = p.press_events(HID_RAW)["kd"][1]
        hid = down.get("hid") == 1
        results[name] = {"kd": down, "hid": hid, "expected": expect_hid, "passed": hid == expect_hid}
        p.done()
    out.update(results)
    ok = all(r["passed"] for r in results.values())
    report.check("F24 icon gate: Home Button 4 (win) sends F24 with hid:1; Tracks Button 4 (next) sends neither",
                 ok, results)
    return ok


def hands_on(p, report, device, live_caps, v4, args, out):
    """The at-the-knob section of 1.0.0-cc5.4 (gates holdEvents, holdDeferred, limitPerPush, hidIconGate), right
    after the turning test: every step's instruction is on the knob."""
    home = v5_frame(device, live_caps, v4["v4-home-now-playing"])
    tracks = v5_frame(device, live_caps, v4["v4-tracks-no-previous"])
    say(f"hands-on: {', '.join(p.plan[2:])} (the knob shows each step)")
    results = {"holdEvents": hold_tests(p, report, out.setdefault("hold", {}))}
    results["holdDeferred"], results["heldAtReady"] = deferred_hold(
        p, report, out.setdefault("deferred", {}), getattr(args, "deferred_attempts", DEFERRED_ATTEMPTS))
    results["limitPerPush"], results["seekEnds"] = push_test(p, report, device, live_caps, tracks,
                                                             out.setdefault("endStop", {}),
                                                             getattr(args, "push_retries", 1))
    if getattr(args, "hid_check", False):
        report.data["externalActions"] = "F24 key presses to Windows (--hid-check; nothing handles them while the companion is quit)"
        results["hidIconGate"] = hid_gate(p, report, home, tracks, out.setdefault("f24", {}))
    else:
        results["hidIconGate"] = False
        out["f24"] = {"run": False, "note": "not run: pass --hid-check (it sends F24 to Windows)"}
        report.check("F24 icon gate: not run (pass --hid-check; the gate needs it)", False, out["f24"]["note"])
    say("hands-on done")
    return results


class TurnFeed:
    """Feeds a tooling.TurnMeter from the stress control's claimed positions and lims while run_stress runs, and
    gives run_stress its overlay (the instruction and live progress), its on_start, until and abort. A pause over
    TURN_MAX_GAP_S aborts an attempt ("gap"); on the `final` attempt it does not: the pass runs to its own minimum
    and is no longer extended, so the stress gate is judged on the stress and turningDetected on the turning. The
    safety timeout aborts any attempt ("timeout": an operator stop)."""

    def __init__(self, p, knob, cid, meter, timeout, final=False):
        self.p, self.knob, self.cid, self.meter, self.timeout, self.final = p, knob, cid, meter, timeout, final
        self.cursor, self.started, self.reason, self.gapped = len(knob.messages), knob.now(), None, False

    def pull(self, now=None):
        new = self.knob.messages[self.cursor:]
        self.cursor += len(new)
        mine = [(ts, m) for ts, m in new if m.get("id") == self.cid and "ready" not in m]
        self.meter.update([(ts, m["p"]) for ts, m in mine if isinstance(m.get("p"), int)],
                          [(ts, m["lim"]) for ts, m in mine if m.get("lim") in (-1, 1)],
                          self.knob.now() if now is None else now)
        return self.meter

    def begin(self, now):
        self.pull(now)
        self.meter.begin_window(now)

    def overlay(self, frame, tag):
        self.pull()
        note, tone = self.meter.note(self.knob.now())
        return t.overlay(frame, self.p.heading(), TURN_KEEP, self.meter.progress(), note, tone, tag)

    def complete(self):
        return self.gapped or self.pull().complete(self.knob.now())

    def abort(self):
        now = self.knob.now()
        if self.pull(now).broken(now):
            self.gapped = True
            if not self.final:
                self.reason = "gap"
        if self.reason is None and now - self.started >= self.timeout:
            self.reason = "timeout"
        return self.reason is not None


def touch_watch(knob):
    """abort() of an untouched pass: True once any knob event (claimed of any control, or native) arrived after
    this call."""
    count = len(knob.claimed_events) + len(knob.native_events)
    return lambda: len(knob.claimed_events) + len(knob.native_events) > count


def run_stress(knob, cid, prefix, frames, bases, live_caps, state, device, errors_since, mark, media=None,
               min_seconds=0.0, overlay=None, on_start=None, until=None, abort=None):
    """~`frames` frame updates interleaved with artwork transfers (the check_nanod_cc5 stress).

    Frames cycle through `bases` every 20 frames, switch the LED style every 10 and carry a
    feedback flash every 25 (the 1.0.0-cc5 pattern); one frame follows every acknowledged line.
    Without `media` the transfers are paced v1 art (the cc5.2 stress). With `media` (a
    tooling.MediaCursor) everything is written unpaced through artwork2 and the pass lasts at
    least `min_seconds`: per round a new cover named by the frame and uploaded, an icon every
    other round (Windows frames name the latest), a have query every third round (the last
    three covers must be present) and a prefetch cover every fourth. Frames then keep the v4
    companion's rate, at most one per FRAME_TICK_SECONDS (a frame after an ack that comes sooner
    is skipped; the frame naming a new cover waits for the tick), so at most one frame and one
    media line are in flight.

    Every frame carries a per-frame tag ("Stress <n> <key>"), so a drawn label changes on each one. The knob's
    screen (user ruling 2026-09-26): `overlay(frame, tag)` puts the instruction on each frame (the untouched passes'
    "HANDS OFF", the turning test's live progress) and the tag moves to its note line. `on_start(time)` marks the
    frame window's start, `until()` extends the pass past its minimum until it returns True (the turning test's
    TurnMeter), and `abort()` returning True ends it early ("aborted": a touched untouched pass, a turning pause).
    """
    state["i"], sent = 0, {"n": 0}
    icon = {"key": ""}
    start_t = knob.now()
    last_frame = {"at": None}
    stopped = {"aborted": False}
    if on_start is not None:
        on_start(start_t)

    def next_frame(key):
        i = state["i"]
        frame = deepcopy(bases[(i // 20) % len(bases)])
        tag = f"Stress {i} {key[-4:]}"
        frame.update(id=cid, artKey=key, title=tag, ledStyle="color" if (i // 10) % 2 == 0 else "white")
        frame.pop("feedback", None)
        if i % 25 == 0:
            state["seq"] += 1
            frame["feedback"] = {"kind": "ok" if (i // 25) % 2 == 0 else "err", "seq": state["seq"]}
        state["i"] += 1
        if overlay is not None:
            frame = overlay(frame, tag)
        wire = device._frame(frame, live_caps)
        if media is not None and wire.get("layout") == "windows" and icon["key"]:
            wire["iconKey"] = icon["key"]
        return wire

    def more():
        if stopped["aborted"]:
            return False
        if abort is not None and abort():
            stopped["aborted"] = True
            return False
        return (sent["n"] < frames or (media is not None and knob.now() - start_t < min_seconds)
                or (until is not None and not until()))

    def send_frame(key, force=False):
        if not more():
            return
        if media is not None and last_frame["at"] is not None:
            wait = t.FRAME_TICK_SECONDS - (knob.now() - last_frame["at"])
            if wait > 0:
                if not force:
                    return                   # coalesced into the next tick, as the v4 companion does
                knob.pump(wait)
        knob.frame(next_frame(key))
        last_frame["at"] = knob.now()
        sent["n"] += 1

    m = mark()
    writes_before = len(knob.frame_write_seconds)
    started = time.monotonic()
    transfers, media_stats, committed_keys = [], {"covers": 0, "icons": 0, "prefetch": 0, "have": 0, "haveMisses": 0}, []
    paced_before = knob.paced
    if media is not None:
        knob.paced = False
    try:
        while more():
            if media is None:
                key = f"{prefix}{len(transfers)}"
                send_frame(key)
                transfers.append(t.art_transfer(knob, cid, key, t.art_pixels(key), between=lambda k=key: send_frame(k)))
                if transfers[-1]["error"]:
                    break
                continue
            n = media_stats["covers"]
            key, cover = media.cover()
            send_frame(key, force=True)      # the frame names the new cover before its media lines
            transfers.append(t.media_transfer(knob, cid, "cover", key, cover, between=lambda k=key: send_frame(k)))
            media_stats["covers"] += 1
            if transfers[-1]["error"] or not transfers[-1]["committed"]:
                break
            committed_keys.append(key)
            if n % 2 == 0:
                icon["key"], data = media.icon()
                transfers.append(t.media_transfer(knob, cid, "icon", icon["key"], data,
                                                  between=lambda k=key: send_frame(k)))
                media_stats["icons"] += 1
            if n % 3 == 2:
                ack = t.media_have(knob, cid, "cover", committed_keys[-3:])
                media_stats["have"] += 1
                media_stats["haveMisses"] += sum(1 for v in ack.get("have") or [None] * 3 if v is not True)
                send_frame(key)
            if n % 4 == 3:
                pre_key, pre = media.cover()
                transfers.append(t.media_transfer(knob, cid, "cover", pre_key, pre, between=lambda k=key: send_frame(k)))
                media_stats["prefetch"] += 1
            if any(x["error"] for x in transfers[-3:]):
                break
        knob.pump(1.0)
    finally:
        knob.paced = paced_before
    errors, released, art_errors, media_errors = errors_since(m)
    result = {"framesSent": sent["n"], "transfers": len(transfers),
              "committed": sum(1 for x in transfers if x["committed"]), "seconds": round(time.monotonic() - started, 2),
              "window": [round(start_t, 3), round(knob.now(), 3)],
              "frameWrite": t.summarize_ms(knob.frame_write_seconds[writes_before:]),
              "errors": errors, "released": released, "artErrors": art_errors, "mediaErrors": media_errors}
    if media is None:
        result["perChunk"] = t.summarize_ms([s for x in transfers for s in x["chunkSeconds"]])
    else:
        result.update(unpaced=True, media=media_stats, perLine=t.summarize_ms([s for x in transfers for s in x["lineSeconds"]]))
    result["aborted"] = stopped["aborted"]
    result["passed"] = (sent["n"] >= frames and not errors and not released and not art_errors and not media_errors
                        and all(x["committed"] for x in transfers) and media_stats["haveMisses"] == 0
                        and not stopped["aborted"])
    return result


def stress_floor_problems(result, media=None, what="stress"):
    """Why a stress pass `result` (run_stress) is below the gate's floor: fewer than STRESS_GATE_FRAMES frame updates,
    or, for an unpaced artwork2 pass (`media` set), a frame window shorter than STRESS_GATE_SECONDS. [] when it is not
    (TL-BUG-009)."""
    problems = []
    if result["framesSent"] < STRESS_GATE_FRAMES:
        problems.append(f"{what}: {result['framesSent']} frame updates < {STRESS_GATE_FRAMES} (the gate's floor)")
    if media is not None:
        seconds = result["window"][1] - result["window"][0]
        if seconds < STRESS_GATE_SECONDS:
            problems.append(f"{what}: {seconds:.1f} s of unpaced media stress < {STRESS_GATE_SECONDS:g} s "
                            "(the gate's floor)")
    return problems


def positive_int(text):
    """argparse type: an integer >= 1 (--stress-frames 0 would let a stress pass send nothing; TL-BUG-009)."""
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, not {value}")
    return value


class SoakFailure(RuntimeError):
    """The first thing that went wrong in the soak (it stops there)."""


def run_soak(knob, watch, minutes, next_id, v4, live_caps, device, run, errors_since, mark, media=None, overlay=None):
    """UNATTENDED SOAK: `minutes` of companion-like traffic with nobody at the knob.

    Cycles through SOAK_CONTROLS, one control per ~30 s (release, then a new control with the
    next ID). Inside a cycle: a changed frame every SOAK_FRAME_SECONDS (title; LED style every
    5 s; the next control's layout base every 10 s; a feedback flash every 7 s), RawKnob's
    0.5 s heartbeats in between, and an artwork slot every SOAK_ART_SECONDS. Without `media`
    each slot is a v1 art transfer, alternately a new cover (cold) and the previous one (a
    cache hit). With `media` (1.0.0-cc5.3) the soak writes unpaced through artwork2: each slot
    names and uploads a cover (alternately new and the previous one, a begin-hit), uploads an
    icon (Windows frames name it), asks `have` for the recent covers (all must be present) and,
    every other slot, prefetches a cover no frame names; every SOAK_V1_ART_EVERY-th slot is
    instead a paced v1 art transfer, as the cc5.2-era companion sends it. A diag checkpoint every
    SOAK_CHECKPOINT_SECONDS (watch.checkpoint, quiet when healthy): no reboot or re-enumeration,
    every task age <= 1000 ms, no LED transmit failure, no forced release. After each release,
    with no control claimed, the checkpoint also reads Windows' LastArrivalDate. Error replies,
    art or media errors, unexpected releases and a release acknowledged with reason "forced" fail
    it. The first failure stops the soak (SoakFailure, recorded).

    Every frame carries a tag ("Soak <control> <n>"). With `overlay(frame, tag, seconds_left)` (the knob's screen,
    user ruling 2026-09-26: "YOU CAN LEAVE", the time left) each frame shows it and the tag moves to the note line;
    the countdown changes every second, so a changed frame still goes out every SOAK_FRAME_SECONDS.
    """
    duration = max(0.0, minutes * 60.0)
    started = knob.now()
    end = started + duration
    stats = {"cycles": 0, "controls": [], "framesSent": 0, "changedFrames": 0, "flashes": 0,
             "transfers": {"cold": 0, "cached": 0, "cacheHits": 0, "committed": 0},
             "releases": [], "checkpoints": 0, "knobEvents": 0, "failure": None}
    if media is not None:
        stats["media"] = {"unpaced": True, "coldMisses": 0, "icons": 0, "iconCommits": 0, "prefetch": 0,
                          "prefetchCommits": 0, "have": 0, "haveMisses": 0, "v1Art": 0, "v1Committed": 0}
    frames_before, events_before = knob.frames_sent, len(knob.claimed_events) + len(knob.native_events)
    state = {"seq": 7000, "n": 0, "artKey": "", "coldKeys": 0, "lastKey": "", "iconKey": "", "slot": 0, "recent": []}
    m = mark()
    checkpoints = {"next": started + t.SOAK_CHECKPOINT_SECONDS}

    def fail(what):
        raise SoakFailure(what)

    def watch_errors():
        errors, released, art_errors, media_errors = errors_since(m)
        if errors:
            fail(f"error reply during the soak: {errors[:3]}")
        if art_errors:
            fail(f"art error during the soak: {art_errors[:3]}")
        if media_errors:
            fail(f"media error during the soak: {media_errors[:3]}")
        own = sum(1 for r in stats["releases"] if r.get("acknowledged"))
        if len(released) > own:
            fail(f"unexpected release during the soak: {released[own:][:3]}")

    def checkpoint(where, pnp=False):
        stats["checkpoints"] += 1
        diag = knob.diag()
        if not watch.checkpoint(f"soak {where}", diag, pnp=pnp, quiet=True):
            fail(f"checkpoint {where} failed (reboot, re-enumeration, stalled task, LED transmit failure "
                 "or forced release; see the checks above)")
        elapsed = knob.now() - started
        ages = ", ".join(f"{k[:-5]} {diag.get(k)} ms" for k in t.LIVENESS_AGE_FIELDS)
        print(f"soak {elapsed / 60:5.1f}/{duration / 60:.0f} min: checkpoint {stats['checkpoints']} ok ({ages}; "
              f"frames {knob.frames_sent - frames_before}, transfers {stats['transfers']['committed']}, "
              f"releases {len(stats['releases'])})", flush=True)

    def frame(control, cid, i, base, flash=True):
        """Frame `i` of this control: LED style every 5, a feedback flash every 7th."""
        body = deepcopy(base)
        tag = f"Soak {control[0]} {state['n']}"
        body.update(id=cid, artKey=state["artKey"], title=tag, ledStyle="color" if (i // 5) % 2 == 0 else "white")
        body.pop("feedback", None)
        if flash and i % 7 == 6:
            state["seq"] += 1
            body["feedback"] = {"kind": "ok" if state["seq"] % 2 else "err", "seq": state["seq"]}
            stats["flashes"] += 1
        state["n"] += 1
        if overlay is not None:
            body = overlay(body, tag, max(0.0, end - knob.now()))
        wire = device._frame(body, live_caps)
        if media is not None and wire.get("layout") == "windows" and state["iconKey"]:
            wire["iconKey"] = state["iconKey"]
        return wire

    def v1_art(cid, control, i, cold):
        """One v1 transfer the way the cc5.2-era DeviceBridge does it: the frame names the key, then the cover."""
        cold = cold or not state["lastKey"]
        if cold:
            state["lastKey"] = f"cc5k{run}{state['coldKeys']}"
            state["coldKeys"] += 1
        key = state["artKey"] = state["lastKey"]
        knob.frame(frame(control, cid, i, current["base"], flash=False))
        result = t.art_transfer(knob, cid, key, t.art_pixels(key))
        return key, result, cold

    def art(cid, control, i, cold):
        key, result, cold = v1_art(cid, control, i, cold)
        stats["transfers"]["cold" if cold else "cached"] += 1
        stats["transfers"]["cacheHits"] += 1 if result["cached"] else 0
        stats["transfers"]["committed"] += 1 if result["committed"] else 0
        if result["error"] or not result["committed"]:
            fail(f"artwork transfer {key} failed at {failed_at(result)}")

    def media_slot(cid, control, i, cold):
        """One artwork2 slot (or, every SOAK_V1_ART_EVERY-th, a paced v1 transfer). Returns True when
        the slot was a cover (its cold/cached alternation advances)."""
        slot = state["slot"]
        state["slot"] += 1
        counts = stats["media"]
        if slot % t.SOAK_V1_ART_EVERY == t.SOAK_V1_ART_EVERY - 1:
            with t.pacing(knob, True):
                key, result, _ = v1_art(cid, control, i, True)
            counts["v1Art"] += 1
            counts["v1Committed"] += 1 if result["committed"] else 0
            if result["error"] or not result["committed"]:
                fail(f"v1 art transfer {key} failed at {failed_at(result)}")
            return False
        cold = cold or not state.get("mediaKey")
        if cold:
            state["mediaKey"], state["mediaData"] = media.cover()
        key, data = state["mediaKey"], state["mediaData"]
        state["artKey"] = key
        knob.frame(frame(control, cid, i, current["base"], flash=False))
        result = t.media_transfer(knob, cid, "cover", key, data)
        stats["transfers"]["cold" if cold else "cached"] += 1
        stats["transfers"]["cacheHits"] += 1 if result["hit"] and not cold else 0
        counts["coldMisses"] += 1 if cold and not result["hit"] else 0
        stats["transfers"]["committed"] += 1 if result["committed"] else 0
        if result["error"] or not result["committed"]:
            fail(f"media cover {key} failed at {failed_at(result)}")
        state["recent"] = (state["recent"] + [key])[-3:] if key not in state["recent"] else state["recent"]
        state["iconKey"], icon = media.icon()
        result = t.media_transfer(knob, cid, "icon", state["iconKey"], icon)
        counts["icons"] += 1
        counts["iconCommits"] += 1 if result["committed"] else 0
        if result["error"] or not result["committed"]:
            fail(f"media icon {state['iconKey']} failed at {failed_at(result)}")
        ack = t.media_have(knob, cid, "cover", state["recent"])
        counts["have"] += 1
        misses = sum(1 for v in ack.get("have") or [None] * len(state["recent"]) if v is not True)
        counts["haveMisses"] += misses
        if misses:
            fail(f"have lost a recent cover: {state['recent']} -> {ack}")
        if slot % 2 == 1:
            pre_key, pre = media.cover()
            result = t.media_transfer(knob, cid, "cover", pre_key, pre)
            counts["prefetch"] += 1
            counts["prefetchCommits"] += 1 if result["committed"] else 0
            if result["error"] or not result["committed"]:
                fail(f"prefetch cover {pre_key} failed at {failed_at(result)}")
        return True

    current = {"base": None}
    paced_before = knob.paced
    if media is not None:
        knob.paced = False
    try:
        cycle = 0
        while knob.now() < end:
            control = SOAK_CONTROLS[cycle % len(SOAK_CONTROLS)]
            name, profile, base_name, maximum, position = control
            base = device._frame(deepcopy(v4[base_name]), live_caps)
            other = device._frame(deepcopy(v4[SOAK_CONTROLS[(cycle + 1) % len(SOAK_CONTROLS)][2]]), live_caps)
            current["base"] = base
            cid = next_id()
            state["artKey"] = ""
            knob.enter(t.raw_control(cid, profile, maximum, position, frame(control, cid, 0, base)))
            stats["controls"].append({"id": cid, "control": name, "readyAt": round(knob.now() - started, 3)})
            cycle_end = min(end, knob.now() + t.SOAK_CYCLE_SECONDS)
            next_frame, next_art, i, cold = knob.now() + t.SOAK_FRAME_SECONDS, knob.now() + 2.0, 1, True
            while knob.now() < cycle_end:
                now = knob.now()
                if now >= next_frame:
                    # Layout switch every 10 s: the next control's base, then back.
                    current["base"] = other if (i // 10) % 2 else base
                    knob.frame(frame(control, cid, i, current["base"]))
                    stats["changedFrames"] += 1
                    i += 1
                    next_frame = now + t.SOAK_FRAME_SECONDS
                if now >= next_art:
                    if media is None:
                        art(cid, control, i, cold)
                        cold = not cold
                    elif media_slot(cid, control, i, cold):
                        cold = not cold
                    next_art = knob.now() + t.SOAK_ART_SECONDS
                if knob.now() >= checkpoints["next"]:
                    checkpoint(stats["checkpoints"] + 1)
                    checkpoints["next"] = knob.now() + t.SOAK_CHECKPOINT_SECONDS
                watch_errors()
                knob.pump(0.05)
            # Release this control; the reply must come without reason "forced".
            sent = knob.now()
            reply = knob.release()
            record = {"id": cid, "seconds": round(knob.now() - sent, 3), "reason": reply.get("reason"),
                      "unacked": reply.get("unacked"), "acknowledged": True}
            stats["releases"].append(record)
            forced = t.forced_release_problems(reply)
            if forced:
                fail(forced[0])
            if reply.get("reason"):
                fail(f"release of control {cid} answered with reason {reply.get('reason')!r}")
            watch_errors()
            stats["cycles"] += 1
            cycle += 1
            # No control is claimed now: the checkpoint may also read Windows' LastArrivalDate.
            checkpoint(f"{stats['checkpoints'] + 1} after release {len(stats['releases'])}", pnp=True)
            checkpoints["next"] = knob.now() + t.SOAK_CHECKPOINT_SECONDS
    except (SoakFailure, TimeoutError, RuntimeError) as exc:
        stats["failure"] = f"{type(exc).__name__}: {exc}"
        print(f"{BANNER}\n!!! SOAK STOPPED: {exc}\n{BANNER}", flush=True)
    finally:
        knob.paced = paced_before
        stats["framesSent"] = knob.frames_sent - frames_before
        stats["knobEvents"] = len(knob.claimed_events) + len(knob.native_events) - events_before
        stats["seconds"] = round(knob.now() - started, 1)
    stats["minutes"] = minutes
    stats["completed"] = stats["failure"] is None and knob.now() >= end
    stats["passed"] = stats["completed"] and stats["checkpoints"] > 0 and bool(stats["releases"])
    if media is not None and stats["passed"]:
        stats["passed"] = stats["media"]["v1Art"] > 0 and stats["media"]["icons"] > 0
    return stats


def raw_checks(port, report, caps, args, watch, profile=None):
    p = profile or getattr(report, "profile", None) or t.CURRENT
    v5 = p.presentation >= 5
    _, device, _, _ = companion()
    v4, v2 = t.fixture_frames()
    run = uuid.uuid4().hex[:6]
    next_id = Ids()
    # Built before the port is opened: a payload problem never leaves a control claimed. Salted with
    # this run's id: covers and icons the knob kept from an earlier run on the same boot are never reused.
    cursor = t.MediaCursor(t.cover_pool(salt=run), t.icon_pool(salt=run)) if p.artwork2 else None
    knob = t.RawKnob(port)          # paced, as the cc5.2-era companion; artwork2 sections write whole lines
    prompter = None
    try:
        knob.pump(0.3)
        knob.release()
        live_caps = knob.request({"capabilities": "?"}, lambda m: isinstance(m.get("capabilities"), dict),
                                 what="capabilities")["capabilities"]
        diag_before = knob.diag()
        report.data["diagBefore"] = diag_before
        watch.checkpoint("DeviceBridge part (uptime and bootCount across it)", diag_before)
        capability = t.artwork2_capability() if p.artwork2 else None
        negotiated = (bool(p.artwork2) and live_caps.get("presentation") == p.presentation
                      and live_caps.get("artwork2") == capability)
        if p.artwork2:
            same_v1 = live_caps.get("artwork") == t.EXPECTED_ARTWORK_CAPABILITY
            rx_ok = (diag_before.get("rxQueueBytes") == capability["rxBytes"] and diag_before.get("rxQueue") == "internal")
            report.check(f"raw capabilities: artwork2 equals presentation.ARTWORK2_CAPABILITY, presentation "
                         f"{p.presentation}", negotiated,
                         {"presentation": live_caps.get("presentation"), "artwork2": live_caps.get("artwork2")})
            report.check("raw capabilities: artwork (v1) byte-identical to cc5.2's", same_v1, live_caps.get("artwork"))
            report.check(f"diag: receive queue {capability['rxBytes']} B in internal RAM (rxQueueBytes, rxQueue)", rx_ok,
                         {k: diag_before.get(k) for k in ("rxQueue", "rxQueueBytes")})
            report.gates["artwork2Capability"] = negotiated and same_v1 and rx_ok
        if v5:
            presentation = t.presentation_capability_problems(live_caps, p)
            report.check(f"raw capabilities: presentation {p.presentation} (PRESENTATION_V5 1)", not presentation,
                         presentation or live_caps.get("presentation"))
            report.gates["presentation5Capability"] = not presentation
        if v5:
            expected, reported = getattr(args, "binary", None), t.lcd_binary(diag_before)
            report.data["binary"] = {"expected": expected, "reported": reported,
                                     "pipeline": {k: diag_before.get(k) for k in ("lcdDma", "lcdPeriodMs", "artAsync")}}
            # A numbered image (the fix binaries D and E) names itself and reports its LCD data line.
            report.data["binary"].update({k: diag_before.get(k) for k in ("build", "lcdMosiSig") if k in diag_before})
            if expected:
                report.check(f"diag identifies binary {expected} (lcdDma, lcdPeriodMs, artAsync; PRESENTATION_V5 12.6)",
                             reported == expected, report.data["binary"])
            if "build" in diag_before:
                mosi = t.lcd_mosi_problems(diag_before)
                report.check(f"diag: lcdMosiSig {t.LCD_MOSI_SIGNAL}, the LCD data line on FSPID ({t.LCD_MOSI_BROKEN_SIGNAL} "
                             "is binary A's dark-LCD defect)", not mosi, mosi or diag_before.get("lcdMosiSig"))
        if p.alive:
            alive = t.alive_capability_problems(live_caps, getattr(report, "led_max_brightness", None))
            report.check("raw capabilities: alive equals tooling.alive_capability(ledMaxBrightness)", not alive,
                         alive or live_caps.get(t.presentation().ALIVE_CAPABILITY))
            report.gates["aliveCapability"] = not alive
        ctx = RawContext(knob, report, v4, next_id, run, cursor, capability)

        def errors_since(mark):
            return ctx.since(mark)

        def mark():
            return ctx.mark()

        # The knob's own screen tells the operator what to do (user ruling 2026-09-26); the first thing it shows is
        # the display check, and nothing else runs until Button 4 confirms the screen is seen.
        prompter = t.KnobPrompter(knob, next_id, plan=prompt_plan(p, getattr(args, "hid_check", False)),
                                  finish=lambda frame: device._frame(frame, live_caps),
                                  timeout=getattr(args, "step_timeout", t.PROMPT_STEP_TIMEOUT_S),
                                  log=lambda text: print(text, flush=True))
        with report.section("displayCheck") as out:
            out.update(prompter.confirm_display())
            report.data["displayCheck"] = dict(prompter.display)
            prompter.hands_off(HANDS_OFF, AUTOMATIC, "About 12 min", "The knob will call you", dwell=2.0)
        watch.checkpoint("displayCheck", knob.diag(), pnp=False)

        with report.section("legacyV2Frames") as out:
            names = sorted(v2)
            cid = next_id()
            knob.enter(t.raw_control(cid, PROFILE["recent"], 2, 0, v2[names[0]]))
            m = mark()
            cases = []
            for name in names:
                knob.frame({**v2[name], "id": cid})
                cases.append({"case": name, "replies": [r for r in knob.pump(0.25) if "error" in r or "released" in r]})
            knob.pump(0.5)
            errors, released, _, _ = errors_since(m)
            out.update(cases=cases, errors=errors, released=released)
            report.check(f"v2 legacy frames accepted ({len(names)} recorded cc4-companion frames)",
                         not errors and not released and len(names) >= 10, len(names))
        watch.checkpoint("legacyV2Frames", knob.diag(), pnp=False)

        with report.section("staleFrameAndControl") as out:
            frame = v4["v4-home-now-playing"]
            m = mark()
            knob.send({"frame": {**frame, "id": cid + 1000}})
            wrong = knob.wait(lambda r: "error" in r, 1.5, "stale frame error")
            knob.send({"frame": {**frame, "id": cid - 1}})
            older = knob.wait(lambda r: "error" in r, 1.5, "stale frame error")
            out["staleFrameReplies"] = [wrong["error"], older["error"]]
            replies = []
            for stale_id in (cid, cid - 1):
                knob.send({"control": t.raw_control(stale_id, PROFILE["recent"], 2, 0, frame)})
                reply = knob.wait(lambda r: "error" in r or r.get("ready") == stale_id, 2, "stale control reply")
                replies.append(reply.get("error", reply))
            out["staleControlReplies"] = replies
            knob.frame({**frame, "id": cid})
            knob.pump(0.6)
            errors, released, _, _ = errors_since(m)
            report.check("stale frame (wrong id) rejected as stale",
                         out["staleFrameReplies"] == ["Stale control frame"] * 2, out["staleFrameReplies"])
            report.check("stale control (non-advancing id) rejected",
                         all(isinstance(r, str) and r.startswith("Control ID must advance") for r in replies), replies)
            report.check("active control kept after stale cases (exactly 4 expected errors, no release)",
                         len(errors) == 4 and not released, {"errors": errors, "released": released})
            knob.release()
        watch.checkpoint("staleFrameAndControl", knob.diag(), pnp=False)

        led = {"idle": False, "load": False}               # 1.0.0-cc5.4 ledFrameRate: idle and under load
        if p.alive:
            with report.section("ledIdle") as out:
                led["idle"] = led_idle(knob, report, next_id, device._frame(deepcopy(v4["v4-home-now-playing"]),
                                                                            live_caps), out)
            watch.checkpoint("ledIdle", knob.diag(), pnp=False)

        recent = v4["v4-recent-item-colour"]
        v1_results = []
        with report.section("rawArtwork") as out:
            cid = next_id()
            key_r = f"cc5r{run}"
            knob.enter(t.raw_control(cid, PROFILE["recent"], recent["ring"]["count"] - 1, recent["ring"]["index"],
                                     {**recent, "artKey": key_r}))
            pixels = t.art_pixels(key_r)
            cold = t.art_transfer(knob, cid, key_r, pixels)
            v1_results.append(report.check(
                "art begin/data/commit round trip (CRC checked at commit)",
                cold["beginOffset"] == 0 and cold["chunks"] == t.ART_BYTES // t.ART_CHUNK
                and cold["committed"] and not cold["error"], {k: cold[k] for k in ("beginOffset", "chunks", "committed", "error")}))
            cached = t.art_transfer(knob, cid, key_r, pixels)
            v1_results.append(report.check("art cache hit: begin answers 28800 and commit succeeds",
                                           cached["cached"] and cached["committed"] and not cached["error"],
                                           {k: cached[k] for k in ("beginOffset", "committed", "error")}))
            key_x = f"cc5x{run}"
            knob.frame({**recent, "id": cid, "artKey": key_x})
            data_x = t.art_pixels(key_x)
            bad = t.art_transfer(knob, cid, key_x, data_x, crc=t.art_crc(data_x) ^ 1)
            again, _ = knob.art(t.art_messages(cid, key_x, data_x)[0])
            v1_results.append(report.check("CRC mismatch refused at commit and not cached",
                                           bad.get("errorOp") == "commit" and "checksum" in (bad["error"] or "").lower()
                                           and again.get("offset") == 0 and "error" not in again,
                                           {"commit": bad["error"], "rebegin": again}))
            stale_id, _ = knob.art({**t.art_messages(cid - 1, key_x, data_x)[0]})
            stale_key, _ = knob.art({**t.art_messages(cid, f"cc5n{run}", data_x)[0]})
            v1_results.append(report.check("stale art id and stale art key answered as stale",
                                           stale_id.get("error") == "Stale artwork selection"
                                           and stale_key.get("error") == "Stale artwork selection",
                                           [stale_id.get("error"), stale_key.get("error")]))
            key_c, key_d = f"cc5c{run}", f"cc5d{run}"
            knob.frame({**recent, "id": cid, "artKey": key_c})
            data_c = t.art_pixels(key_c)
            partial = t.art_transfer(knob, cid, key_c, data_c, stop_after_chunks=5)
            knob.frame({**recent, "id": cid, "artKey": key_d})
            chunk6 = t.art_messages(cid, key_c, data_c)[1 + partial["chunks"]]
            late, _ = knob.art(chunk6)
            v1_results.append(report.check("selection change mid-transfer: the old cover's next chunk is stale",
                                           late.get("error") == "Stale artwork selection", late))
            fresh = t.art_transfer(knob, cid, key_d, t.art_pixels(key_d))
            v1_results.append(report.check("new selection's cover completes after the stale discard",
                                           fresh["committed"] and not fresh["error"], fresh["error"]))
            m = mark()
            knob.send_line(('{"art":{"id":%d,"key":"%s","op":"data","offset":0,"data":"AAAA\n' % (cid, key_d)).encode())
            parse = knob.wait(lambda r: isinstance(r.get("artAck"), dict) and r["artAck"].get("op") == "parse", 2, "parse artAck")
            knob.send_line(('{"art":{"id":%d,"key":"%s","op":"data","offset":0,"data":"%s"}}\n'
                            % (cid, key_d, "A" * 4200)).encode())
            oversize = knob.wait(lambda r: isinstance(r.get("artAck"), dict) and r["artAck"].get("op") == "parse", 2, "oversize artAck")
            knob.pump(0.5)
            errors, released, _, _ = errors_since(m)
            parses = [r for _, r in knob.messages if isinstance(r.get("artAck"), dict) and r["artAck"].get("op") == "parse"]
            out.update(parseAck=parse["artAck"], oversizeAck=oversize["artAck"], paced=knob.paced)
            expect = {"id": cid, "key": key_d, "op": "parse", "error": "parse"}
            v1_results.append(report.check(
                "malformed and oversize art lines: one artAck parse each (id/key recovered), no bare error",
                {k: parse["artAck"].get(k) for k in expect} == expect
                and {k: oversize["artAck"].get(k) for k in expect} == expect
                and len(parses) == 2 and not errors and not released,
                {"errors": errors, "parseAcks": len(parses)}))
            knob.frame({**recent, "id": cid, "artKey": key_d})
            m = mark()
            knob.pump(0.6)
            v1_results.append(report.check("control still claimed after the art error cases", not any(errors_since(m)[:2])))
            out["v1Compatible"] = all(v1_results) and len(v1_results) == 8
        watch.checkpoint("rawArtwork", knob.diag(), pnp=False)

        with report.section("mediaRoundTrip") as out, t.pacing(knob, False):
            require_artwork2(negotiated)
            report.gates["mediaRoundTrip"] = media_round_trip(ctx, out)
        watch.checkpoint("mediaRoundTrip", knob.diag(), pnp=False)

        with report.section("mediaPrefetch") as out, t.pacing(knob, False):
            require_artwork2(negotiated)
            report.gates["mediaPrefetch"] = media_prefetch(ctx, out)
        watch.checkpoint("mediaPrefetch", knob.diag(), pnp=False)

        with report.section("mediaPinning") as out, t.pacing(knob, False):
            require_artwork2(negotiated)
            report.gates["mediaPinning"] = media_pinning(ctx, out)
        watch.checkpoint("mediaPinning", knob.diag(), pnp=False)

        with report.section("mediaErrors") as out, t.pacing(knob, False):
            require_artwork2(negotiated)
            report.gates["mediaErrorStrings"] = media_error_cases(ctx, out)
        watch.checkpoint("mediaErrors", knob.diag(), pnp=False)

        with report.section("mediaTiming") as out, t.pacing(knob, False):
            require_artwork2(negotiated)
            report.gates["unpacedTransferTiming"] = media_timing(ctx, out)
        watch.checkpoint("mediaTiming", knob.diag(), pnp=False)

        if v5:
            with report.section("lcdAnimation") as out, t.pacing(knob, False):
                require_artwork2(negotiated)
                report.gates["lcdTimings"] = lcd_animation(ctx, device, live_caps, v4["v4-tracks-no-previous"], out)
            watch.checkpoint("lcdAnimation", knob.diag(), pnp=False)
        if p.alive:
            with report.section("ledUnderLoad") as out, t.pacing(knob, False):
                require_artwork2(negotiated)
                led["load"] = led_under_load(ctx, out)
            watch.checkpoint("ledUnderLoad", knob.diag(), pnp=False)
            report.gates["ledFrameRate"] = led["idle"] and led["load"]

        def timed_transfer(key, windows, dress=None):
            frame = {**recent, "id": cid, "artKey": key}
            knob.frame(dress(frame) if dress is not None else frame)
            start = knob.now()
            result = t.art_transfer(knob, cid, key, t.art_pixels(key))
            windows.append((start, knob.now()))
            return result

        with report.section("coldTransferTiming") as out:
            # A new control (the artwork2 sections released theirs); the stress passes keep it.
            cid = next_id()
            knob.enter(t.raw_control(cid, PROFILE["recent"], recent["ring"]["count"] - 1, recent["ring"]["index"],
                                     {**recent, "artKey": ""}))
            windows = []
            first = timed_transfer(f"cc5t{run}", windows)
            out["perChunk"] = t.summarize_ms(first["chunkSeconds"])
            out["transferSeconds"] = first["seconds"]
            out["bytesPerSecond"] = round(t.ART_BYTES / first["seconds"]) if first["seconds"] else None
            out["paced"] = knob.paced
            # The rest of the 1.0.0-cc5 run-1 sequence: three more cold transfers, untouched
            # (that run's "--turn-seconds 10" produced exactly these; the knob was not turned).
            extra = [timed_transfer(f"cc5t{run}{n}", windows) for n in range(args.replay_transfers)]
            out["extraTransfers"] = len(extra)
            out["extraCommitted"] = sum(1 for x in extra if x["committed"])
            touched = knob_events_between(knob, windows[0][0], windows[-1][1])
            out["knobEvents"] = {"count": len(touched), "note": "untouched: the run-1 sequence had no knob events"}
            first_ok = report.check("cold transfer committed with per-chunk timing recorded", first["committed"],
                                    out["perChunk"])
            extra_ok = report.check(f"{args.replay_transfers} more cold transfers committed (the 1.0.0-cc5 run-1 cache fill)",
                                    out["extraCommitted"] == args.replay_transfers, out["extraCommitted"])
            report.gates["v1ArtCompatible"] = all(v1_results) and len(v1_results) == 8 and first_ok and extra_ok
        watch.checkpoint("coldTransferTiming", knob.diag(), pnp=False)

        media = cursor if negotiated else None
        base_names = MEDIA_STRESS_BASES if media is not None else STRESS_BASES
        bases = [device._frame(deepcopy(v4[name]), live_caps) for name in base_names]
        stress_state = {"i": 0, "seq": 1000}
        stress_seconds = args.stress_seconds if media is not None else 0.0
        recent_base = device._frame(deepcopy(recent), live_caps)       # the stress control's own screen

        def hands_off_frame(frame, tag="", note="", tone=None):
            """The untouched passes on the knob: HANDS OFF, whatever layout the stress frame has."""
            return t.overlay(frame, HANDS_OFF, AUTOMATIC, UNTOUCHED, note, tone, tag=tag)

        with report.section("stress") as out:
            say(f"stress pass 1 of 2 (untouched: the 1.0.0-cc5 run-1 sequence, paced v1 art"
                f"{', then unpaced through artwork2' if media is not None else ''}); the knob shows HANDS OFF")
            attempts, v1 = [], None
            for attempt in range(1, UNTOUCHED_ATTEMPTS + 1):
                final = attempt == UNTOUCHED_ATTEMPTS
                record = {"attempt": attempt}
                if attempt > 1:
                    # A touched pass is rerun as the run-1 sequence: its cold transfers first, then the passes.
                    again = "You touched the knob"
                    rewindows = []
                    replay = [timed_transfer(f"cc5t{run}r{attempt}{n}", rewindows,
                                             dress=lambda f: prompter.dressed(hands_off_frame(f, note=again,
                                                                                              tone="error")))
                              for n in range(args.replay_transfers)]
                    record["replayCommitted"] = sum(1 for x in replay if x["committed"])
                prompter.screen(AUTOMATIC, UNTOUCHED, heading=HANDS_OFF, base=recent_base)
                record["eventsBeforeQuiet"] = prompter.quiet(UNTOUCHED_QUIET_S, what="the knob left alone")
                touched_since = None if final else touch_watch(knob)
                if media is not None:
                    # The cc5.2-era companion (desktop v3) keeps sending paced v1 art to cc5.3 (ARTWORK2.md
                    # section 2), and cc5.3 changed the COM loop under it (8192-byte receive queue, 1-tick
                    # idle): so the untouched pass first replays the cc5.2 stress itself, paced v1 art
                    # interleaved with frames (the 1.0.0-cc5 run-1 sequence after coldTransferTiming's
                    # three extra cold transfers), then the unpaced artwork2 stress.
                    v1_bases = [device._frame(deepcopy(v4[name]), live_caps) for name in STRESS_BASES]
                    v1 = run_stress(knob, cid, f"cc5p{run}{attempt}", args.stress_frames, v1_bases, live_caps,
                                    stress_state, device, errors_since, mark, overlay=hands_off_frame,
                                    abort=touched_since)
                    record["v1Aborted"] = v1["aborted"]
                result = None
                if v1 is None or not v1["aborted"]:
                    result = run_stress(knob, cid, f"cc5s{run}{attempt}", args.stress_frames, bases, live_caps,
                                        stress_state, device, errors_since, mark, media=media,
                                        min_seconds=stress_seconds, overlay=hands_off_frame, abort=touched_since)
                    record["aborted"] = result["aborted"]
                attempts.append(record)
                if result is not None and not result["aborted"]:
                    break
                prompter.retry("You touched the knob")
                knob.pump(t.PROMPT_DONE_S)
            out["attempts"] = attempts
            v1_ok = True
            if v1 is not None:
                v1_touched = knob_events_between(knob, *v1["window"])
                out["v1"] = dict(v1, run1Replay=True, knobEvents=len(v1_touched),
                                 precededBy=f"{args.replay_transfers} extra cold transfers (coldTransferTiming)")
                v1_ok = (report.check(f"stress (untouched, paced v1 art: the 1.0.0-cc5 run-1 sequence as the cc5.2-era "
                                      f"companion sends it): {v1['framesSent']} frame updates interleaved with "
                                      f"{v1['transfers']} art transfers, zero error replies, no release", v1["passed"],
                                      {k: v1[k] for k in ("framesSent", "transfers", "committed")})
                         & report.check("stress (untouched, paced v1 art): no knob events (a touched knob is a "
                                        "rerun, not a pass)", not v1_touched, len(v1_touched)))
            touched = knob_events_between(knob, *result["window"])
            # run1Replay: this pass (v1 art without artwork2) or its "v1" part replays the run-1 sequence.
            out.update(result, run1Replay=media is None, knobEvents=len(touched))
            if media is None:
                out["precededBy"] = f"{args.replay_transfers} extra cold transfers (coldTransferTiming)"
            label = "unpaced artwork2 media" if media is not None else "the 1.0.0-cc5 run-1 sequence"
            report.check(f"stress (untouched, {label}): {result['framesSent']} frame updates "
                         f"interleaved with {result['transfers']} {'media' if media is not None else 'art'} transfers, "
                         "zero error replies, no release", result["passed"],
                         {k: result[k] for k in ("framesSent", "transfers", "committed")})
            report.check(f"stress (untouched, {label}): no knob events (a touched knob is a rerun, not a pass)",
                         not touched, len(touched))
            floor = stress_floor_problems(result, media, "untouched") + (
                stress_floor_problems(v1, None, "untouched, paced v1 art") if v1 is not None else [])
            out["gateFloor"] = {"frames": STRESS_GATE_FRAMES,
                                "seconds": STRESS_GATE_SECONDS if media is not None else None, "problems": floor}
            report.gates["stressUntouched"] = result["passed"] and not touched and v1_ok and not floor
            if floor:
                print(f"Note: the stressUntouched gate needs a full-length pass: {'; '.join(floor)}.", flush=True)
        render = {}                                         # 1.0.0-cc5.4: ledRenderUsMax over each stress pass
        stress_diag = knob.diag()                           # (the checkpoint before the pass read and reset it)
        if p.alive:
            render["stress"] = t.led_render_problems(stress_diag)
            report.data["sections"].setdefault("stress", {})["ledRenderUsMax"] = t.diag_int(stress_diag, "ledRenderUsMax")
            report.check(f"LED render during the untouched stress: ledRenderUsMax <= {t.ALIVE_LED_RENDER_US_MAX} us",
                         not render["stress"], render["stress"] or t.diag_int(stress_diag, "ledRenderUsMax"))
        watch.checkpoint("stress", stress_diag, pnp=False)

        with report.section("stressTurn") as out:
            say(f"stress pass 2 of 2 (stress+turn): the knob asks for {args.turn_seconds:g} s of turning, both ends")
            prompter.begin("turn")
            prompter.press(3, TURN_READY, TURN_START, base=recent_base, buttons=t.press_buttons(3), attention=True)
            maximum = recent["ring"]["count"] - 1
            turn_attempts, again = [], None
            limit = max(1, getattr(args, "turn_attempts", TURN_ATTEMPTS))
            for attempt in range(1, limit + 1):
                meter = t.TurnMeter(maximum, args.turn_seconds, need_lims=bool(p.alive))
                prompter.screen(TURN_SAY, "Start turning now", base=recent_base)
                if again:
                    prompter.retry(again)
                feed = TurnFeed(prompter, knob, cid, meter, prompter.timeout, final=attempt == limit)
                prompter.wait(lambda batch, now, feed=feed: True if feed.pull(now).started(now) else None,
                              what="turning (3 position events within 1.5 s)")
                feed.started = start = knob.now()
                windows = []
                extra = [timed_transfer(f"cc5u{run}{attempt}{n}", windows,
                                        dress=lambda f, feed=feed: prompter.dressed(feed.overlay(f, "")))
                         for n in range(args.replay_transfers)]
                result = run_stress(knob, cid, f"cc5v{run}{attempt}", args.stress_frames, bases, live_caps,
                                    stress_state, device, errors_since, mark, media=media, min_seconds=stress_seconds,
                                    overlay=feed.overlay, on_start=feed.begin, until=feed.complete, abort=feed.abort)
                end = knob.now()
                turn_attempts.append({"attempt": attempt, "stopped": feed.reason, "gap": feed.gapped,
                                      "window": result["window"], "passed": result["passed"], "meter": meter.record()})
                out["turnAttempts"] = turn_attempts
                if feed.reason == "timeout":
                    raise prompter.stop("the turning test completed", end - feed.started)
                if feed.reason == "gap":
                    again = f"You stopped for {t.TURN_MAX_GAP_S:g} s"
                    continue
                break
            prompter.done()
            times = t.claimed_positions(knob.claimed_events, cid, start, end)
            # The gate counts only events inside the stress-frame window: turning only during
            # the cold transfers before it (or for part of it) must not pass.
            in_stress, gap_stress = t.turning_in_window(times, result["window"])
            during = [ts for ts in times if any(a <= ts <= b for a, b in windows)]
            gap, gap_during = t.max_gap(times), t.max_gap(during)
            turning = t.turning_problems(times, result["window"])
            passed = result["passed"] and all(x["committed"] for x in extra)
            out.update(result, extraTransfers=len(extra), extraCommitted=sum(1 for x in extra if x["committed"]),
                       turnSeconds=args.turn_seconds, sectionSeconds=round(end - start, 2), turnAttempts=turn_attempts,
                       knobEvents={"count": len(times), "required": t.TURN_MIN_EVENTS,
                                   "duringStress": len(in_stress), "stressWindow": result["window"],
                                   "maxGapDuringStressMs": round(gap_stress * 1000, 1),
                                   "maxGapAllowedMs": round(t.TURN_MAX_GAP_S * 1000, 1),
                                   "maxGapMs": round(gap * 1000, 1) if gap is not None else None,
                                   "duringTransfers": len(during),
                                   "maxGapDuringTransfersMs": round(gap_during * 1000, 1) if gap_during is not None else None})
            report.check(f"stress+turn: {args.replay_transfers} cold transfers then {result['framesSent']} frame updates "
                         f"interleaved with {result['transfers']} {'media' if media is not None else 'art'} transfers "
                         "while turning, zero error replies, no release", passed,
                         {k: result[k] for k in ("framesSent", "transfers", "committed")})
            report.check(TURN_CHECK, not turning, turning or out["knobEvents"])
            floor = stress_floor_problems(result, media, "stress+turn")
            out["gateFloor"] = {"frames": STRESS_GATE_FRAMES,
                                "seconds": STRESS_GATE_SECONDS if media is not None else None, "problems": floor}
            report.gates["stressTurn"] = passed and not floor
            if floor:
                print(f"Note: the stressTurn gate needs a full-length pass: {'; '.join(floor)}.", flush=True)
            report.gates["turningDetected"] = not turning
            if p.alive:
                # ALIVE.md 11.9: turning back and forth across the stress control's range reaches both ends.
                lims = t.limit_events(knob.messages, cid, start, end)
                out["lims"] = {"events": [(round(ts, 3), d) for ts, d in lims], "problems": t.limit_problems(lims)}
                report.check("stress+turn: lim events at both ends of the range (-1 and +1), >= 150 ms apart",
                             not out["lims"]["problems"], out["lims"]["problems"] or len(lims))
        turn_diag = knob.diag()
        if p.alive:
            render["stressTurn"] = t.led_render_problems(turn_diag)
            report.data["sections"].setdefault("stressTurn", {})["ledRenderUsMax"] = t.diag_int(turn_diag, "ledRenderUsMax")
            report.check(f"LED render during stress+turn: ledRenderUsMax <= {t.ALIVE_LED_RENDER_US_MAX} us",
                         not render["stressTurn"], render["stressTurn"] or t.diag_int(turn_diag, "ledRenderUsMax"))
            report.gates["ledRenderTime"] = set(render) == {"stress", "stressTurn"} and not any(render.values())
            sections = report.data["sections"]
            quiet = [(name, part.get("errors"), part.get("released")) for name, part in
                     (("stress", sections.get("stress", {})), ("stress v1", sections.get("stress", {}).get("v1", {})),
                      ("stressTurn", sections.get("stressTurn", {})))]
            clean = all(errors == [] and released == [] for _, errors, released in quiet)
            report.check("no error reply and no release in either stress pass (ALIVE.md 11.9)", clean,
                         None if clean else quiet)
            report.gates["noErrorReplies"] = clean
        watch.checkpoint("stressTurn", turn_diag, pnp=False)

        if v5:
            with report.section("handsOn") as out:
                results = hands_on(prompter, report, device, live_caps, v4, args, out)
                stress_lims = report.data["sections"].get("stressTurn", {}).get("lims", {})
                report.gates.update(holdEvents=results["holdEvents"], holdDeferred=results["holdDeferred"],
                                    limitPerPush=results["limitPerPush"], hidIconGate=results["hidIconGate"],
                                    limitEvents=results["seekEnds"] and bool(stress_lims)
                                    and not stress_lims.get("problems"))
                ready = t.ready_key_state_problems([r for _, r in knob.ready_replies])
                if not results["heldAtReady"]:
                    ready.append("no ready line showed Button 1 held (the deferred hold test)")
                out["readyKeyState"] = {"readyLines": len(knob.ready_replies), "problems": ready}
                report.check("every ready line carries ks 0..15, with the held Button 1 bit when it was held "
                             "(PRESENTATION_V5 11.3)", not ready, ready or len(knob.ready_replies))
                report.gates["readyKeyState"] = not ready
            watch.checkpoint("handsOn", knob.diag(), pnp=False)

        with report.section("soak") as out:
            minutes = args.soak_minutes
            released = knob.release()            # the last hands-on control; the soak brings its own
            out["stressReleased"] = released
            forced = t.forced_release_problems(released)
            report.check("stress control released normally before the soak (no forced release)", not forced,
                         forced or released)
            say(f"unattended soak: {minutes:g} min of companion-like traffic (frames, heartbeats, "
                f"{'artwork2 covers, icons, have and prefetch, unpaced, with paced v1 art' if media is not None else 'artwork'}, "
                "layout and LED-style switches, flashes, a release and a new control every "
                f"{t.SOAK_CYCLE_SECONDS:g} s) with a diag checkpoint every {t.SOAK_CHECKPOINT_SECONDS:g} s; the knob "
                "shows YOU CAN LEAVE and the time left")
            prompter.hands_off(LEAVE, AUTOMATIC, f"About {minutes:g} min", "Nothing to do", dwell=t.PROMPT_DONE_S)

            def soak_overlay(frame, tag, left):
                left = int(left)
                return t.overlay(frame, LEAVE, AUTOMATIC, f"{left // 60}:{left % 60:02d} left", tag=tag)
            result = run_soak(knob, watch, minutes, next_id, v4, live_caps, device, run, errors_since, mark,
                              media=media, overlay=soak_overlay)
            out.update(result)
            detail = {k: result[k] for k in ("minutes", "seconds", "cycles", "checkpoints", "framesSent",
                                             "transfers", "knobEvents", "failure")}
            if "media" in result:
                detail["media"] = result["media"]
            if minutes <= 0:
                report.check("unattended soak: skipped (--soak-minutes 0); the unattendedSoak gate needs "
                             f"at least {t.SOAK_GATE_MINUTES:g} min", False, detail)
            else:
                report.check(f"unattended soak: {minutes:g} min completed with no hang, reboot, re-enumeration, "
                             "error, forced release or LED transmit failure", result["passed"], detail)
            report.gates["unattendedSoak"] = (result["passed"] and not forced
                                              and minutes >= t.SOAK_GATE_MINUTES)
            if result["passed"] and minutes < t.SOAK_GATE_MINUTES:
                print(f"Note: a {minutes:g} min soak passed, but the unattendedSoak gate needs "
                      f"{t.SOAK_GATE_MINUTES:g} min.", flush=True)
        watch.checkpoint("soak", knob.diag(), pnp=False)

        with report.section("diag") as out:
            diag = knob.diag()
            margins = t.diag_margins(diag, profile=p)
            out.update(after=diag, margins=margins, media=t.media_diag_summary(diag))
            if p.presentation >= 5:
                out.update(lcd=t.lcd_diag_summary(diag), binary=t.lcd_binary(diag), byEye=list(BY_EYE),
                           led={k: diag.get(k) for k in t.ALIVE_DIAG_FIELDS})
                out.update({k: diag.get(k) for k in ("build", "lcdMosiSig") if k in diag})
                report.check(f"diag: lvglMinFree >= {p.lvgl_min_free} B, heapMinFree >= {p.heap_min_free} B, stacks "
                             f"(LCD, COM, HMI, FOC) > 1 KB, stackArtDec >= {t.V5_STACK_ART_DEC_MIN_BYTES} B on the "
                             "binaries with artAsync (A, D) (PRESENTATION_V5 12.2)", margins["passed"], margins["checks"])
            else:
                report.check(f"diag: LVGL heap >= 25 % free at minimum, internal heap minimum (heapMinFree) >= "
                             f"{t.HEAP_MIN_FREE_BYTES} B, stacks (LCD, COM, HMI, FOC) > 1 KB",
                             margins["passed"], margins["checks"])
            report.check("diag: no serial reply cut short (txStalls 0)", diag.get("txStalls") == 0,
                         {k: diag.get(k) for k in ("txStalls", "txDroppedBytes")})
            report.gates["diagMargins"] = margins["passed"]
            if p.artwork2:
                jpeg = t.jpeg_decode_problems(diag)
                report.check(f"diag: JPEG covers decoded (jpegDecodes > 0), jpegDecodeErrors 0, jpegDecodeMsMax <= "
                             f"{t.JPEG_DECODE_MAX_MS} ms", not jpeg, jpeg or t.media_diag_summary(diag))
                commits = t.media_counter(diag, "mediaCommits")
                report.check("diag: media commits counted (mediaCommits > 0)", bool(commits), commits)
                report.gates["jpegDecode"] = not jpeg and bool(commits)
        watch.checkpoint("diag", knob.diag(), pnp=False)
        knob.release()
    except t.OperatorStop as stop:
        # The operator did not complete a step (or the screen was never confirmed): never a firmware failure. The
        # remaining hands-on steps and the soak are skipped; their gates stay false.
        report.data["operatorStop"] = stop.record()
        say(f"stopped: {stop.reason} (step {stop.step} of {stop.of}, {stop.name}); not a firmware failure")
        raise
    finally:
        # Always release, even when enter() timed out after sending the control or a lease
        # already expired: an idle release is answered at once and clears the host-lost notice.
        if prompter is not None:
            report.data["prompts"] = prompter.evidence()
        report.data["finalRelease"] = knob.release_quietly()
        report.data["raw"] = {"messages": len(knob.messages), "errors": knob.errors, "artErrors": knob.art_errors,
                              "mediaErrors": knob.media_errors[:50], "released": knob.released,
                              "nativeEvents": len(knob.native_events), "claimedEvents": len(knob.claimed_events),
                              "linesWritten": dict(knob.lines_written)}
        knob.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--turn-seconds", type=float, default=TURN_SECONDS,
                        help="seconds of actual turning the turning test needs (counted on the knob's screen only while "
                             f"position events arrive inside the stress window; default {TURN_SECONDS:g}); the stress "
                             "runs until they, both ends and both lims are reached")
    parser.add_argument("--turn-attempts", type=int, default=TURN_ATTEMPTS,
                        help=f"turning attempts (a pause over {t.TURN_MAX_GAP_S:g} s aborts one; default {TURN_ATTEMPTS})")
    parser.add_argument("--deferred-attempts", type=int, default=DEFERRED_ATTEMPTS,
                        help=f"1.0.0-cc5.4: deferred-hold attempts at most (default {DEFERRED_ATTEMPTS})")
    parser.add_argument("--step-timeout", type=float, default=t.PROMPT_STEP_TIMEOUT_S,
                        help="safety timeout of each wait for the operator; reaching it stops the run as \"operator did "
                             "not complete step N\" (exit 4) or \"screen not confirmed\" (exit 5), never a firmware "
                             f"failure (default {t.PROMPT_STEP_TIMEOUT_S:g} s)")
    parser.add_argument("--stress-frames", type=positive_int, default=STRESS_GATE_FRAMES,
                        help=f"frame updates in each stress pass (at least 1; the stress gates need at least "
                             f"{STRESS_GATE_FRAMES})")
    parser.add_argument("--stress-seconds", type=float, default=t.STRESS_MIN_SECONDS,
                        help="minimum length of each unpaced media stress pass (default "
                             f"{t.STRESS_MIN_SECONDS:g} s; unpaced transfers are fast)")
    parser.add_argument("--replay-transfers", type=int, default=REPLAY_TRANSFERS,
                        help="cold transfers before each stress pass (the 1.0.0-cc5 run-1 sequence had 3)")
    parser.add_argument("--soak-minutes", type=float, default=t.SOAK_DEFAULT_MINUTES,
                        help=f"length of the unattended soak after stress+turn (default {t.SOAK_DEFAULT_MINUTES:g}; "
                             f"the unattendedSoak gate needs at least {t.SOAK_GATE_MINUTES:g})")
    current = next(tag for tag, profile in t.PROFILES.items() if profile is t.CURRENT)
    parser.add_argument("--release", choices=sorted(t.PROFILES), default=current,
                        help=f"the release on the knob (default {current}, tooling.CURRENT); cc5.4 adds the ALIVE and "
                             "presentation-5 checks and the hands-on section")
    parser.add_argument("--hid-check", action="store_true",
                        help="1.0.0-cc5.4: run the F24 icon-gate test (sends F24 key presses to Windows; the "
                             "hidIconGate gate is false without it)")
    parser.add_argument("--push-retries", type=int, default=1,
                        help="1.0.0-cc5.4: how often the End stop push test may be repeated when it fails (default 1)")
    ladder = sorted({b for q in t.PROFILES.values() for b in q.pipeline_binaries()})
    parser.add_argument("--binary", choices=ladder or None, default=None,
                        help="1.0.0-cc5.4: the PRESENTATION_V5 12.6 binary just installed (A..E; D and E are the fix "
                             "binaries); the run checks that diag reports it, and finalize_nanod_cc5.py --binary "
                             "requires it")
    args = parser.parse_args(argv)
    profile = t.PROFILES[args.release]
    if args.binary and args.binary not in profile.pipeline_binaries():
        parser.error(f"--binary applies only to a release built as the 12.6 ladder, not {profile.version}")
    t.console_utf8()
    t.require_companion_quit()
    port = t.find_app_port()
    report = Report(port, profile)
    # The effective arguments that shaped this run (stress length, soak length, ...), so the evidence shows them.
    report.data["arguments"] = {k: v for k, v in sorted(vars(args).items())
                                if v is None or isinstance(v, (bool, int, float, str))}
    # After a step-down whose failed binary left a core dump, only that dump (held by this binary's step-down base)
    # may be present at the start; any other dump fails coredumpBlank (tooling.coredump_problems, TB-D9).
    watch = RebootWatch(report, port, inherited_coredump=t.step_down_coredump(profile, args.binary) if args.binary else None)
    error = stop = interrupted = None
    try:
        watch.start()
        caps = bridge_checks(port, report, watch, profile, args.binary)
        time.sleep(0.5)  # let Windows release the port before the raw session
        raw_checks(port, report, caps, args, watch, profile)
    except t.OperatorStop as exc:
        stop = exc              # recorded by raw_checks ("operatorStop", "prompts"); nothing added to "failures"
        report.data["operatorStop"] = exc.record()
    except KeyboardInterrupt as exc:
        # Ctrl+C (TL-BUG-008): an interrupted run is recorded as not completed and not passed, then re-raised below
        # once the record is written; it never prints PASSED.
        interrupted = exc
        report.check(INTERRUPTED_CHECK, False, "KeyboardInterrupt")
    except Exception as exc:
        error = exc
        report.check("run completed", False, f"{type(exc).__name__}: {exc}")
    finally:
        try:
            watch.finish(error)
        except KeyboardInterrupt as exc:     # a second Ctrl+C while the watch finishes: still write the record
            if interrupted is None:
                interrupted = exc
                report.check(INTERRUPTED_CHECK, False, "KeyboardInterrupt (reboot watch)")
        except Exception as exc:
            report.check("reboot watch finished", False, f"{type(exc).__name__}: {exc}")
        report.data["completed"] = stop is None and interrupted is None
        report.data["interrupted"] = interrupted is not None
        # Every gate is a hard gate (finalize_nanod_cc5.REQUIRED_GATES is the profile's gates): a run with a false
        # gate is not a pass even with no failed check (TL-BUG-008).
        gates_false = [name for name, value in report.gates.items() if value is not True]
        report.data["gatesFalse"] = gates_false
        report.data["passed"] = (not report.data["failures"] and stop is None and interrupted is None
                                 and not gates_false)
        report.data["finishedUtc"] = t.utc_stamp()
        t.write_json_evidence(profile.device_checks, report.data)
        if stop is not None:
            verdict = f"NOT COMPLETED ({stop.reason}: step {stop.step} of {stop.of}, {stop.name}; not a firmware failure)"
        elif interrupted is not None:
            verdict = "INTERRUPTED (Ctrl+C; not completed, not passed)"
        elif report.data["passed"]:
            verdict = "PASSED"
        elif not report.data["failures"]:
            verdict = f"FAILED (gates not passed: {', '.join(gates_false)})"
        else:
            verdict = "FAILED"
        print(f"{verdict}; gates {report.gates}; evidence {profile.device_checks}", flush=True)
    if interrupted is not None:
        raise interrupted
    if stop is not None:
        return stop.exit_code
    return 0 if report.data["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
