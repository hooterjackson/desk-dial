"""DD-BUG-053: ALIVE r3.1 section 15.8, the button-4 hold (Play next) lands as the GREEN "queue" flash.

The real Controller (r3 fixture, Recently Added) produces the wire frames; AliveLights is fed them the way the
recording does (60 Hz renders, the controller's hold frame applied from its arrival time). At hold maturity
(HOLD4_MS = 1000 ms) the first new feedback seq lands the hold: ok + queued -> "queue", plain ok -> "land". The
bug: the frame's feedback was read before the maturity opened the landing window, so a frame arriving on the very
render of the 1000 ms mark (always in the recording) went down the ordinary moment path: no green. Headless: no
Tk, no ports, no network.
"""
import unittest

from cc5_support import recent_page
from r3_support import R3Fixture
from control_center.alive_lights import AliveLights

PRESS_AT = 2000


def drive(fx, delay_ms, list_screen=True, marker=None):
    """Hold button 4 from PRESS_AT; the controller's hold frame arrives at PRESS_AT + 1000 + delay_ms.

    ``marker`` overrides the frames' holdMarker (None keeps the controller's). Returns the flashes in order."""
    if list_screen:
        fx.press(0)
        fx.press(1)
        fx.complete("recent", recent_page(0, 30))
    fx.c.drain()
    lights = AliveLights(0)
    lights.claim(0)

    def frame_now():
        frame = fx.wire()
        if marker is not None:
            frame = dict(frame, holdMarker=marker)
        return frame

    frame = frame_now()
    hold_at = PRESS_AT + 1000 + delay_ms
    ticks = sorted(set([round(j * 1000 / 60) for j in range(60 * 5)] + [hold_at]))
    flashes, pressed, sent = [], False, False
    for now in ticks:
        if now >= PRESS_AT and not pressed:
            lights.press(PRESS_AT, 3)
            pressed = True
        if now >= hold_at and not sent:
            fx.c.hold(3, fx.c.control_id)        # the runtime's kh -> Controller.hold
            frame = frame_now()
            sent = True
        if now >= PRESS_AT + 1120 and lights._hold4_down is not None:
            lights.key_up(now, 3)
        lights.render(now, frame)
        if lights._flash and (not flashes or flashes[-1] != lights._flash):
            flashes.append(lights._flash)
    return flashes


class PlayNextGreenTest(R3Fixture):
    def test_recording_order_frame_at_the_1000_ms_mark_flashes_queue(self):
        self.assertIn("queue", drive(self, 0))

    def test_frame_20_ms_after_maturity_still_flashes_queue(self):
        self.assertIn("queue", drive(self, 20))

    def test_plain_ok_landing_is_land(self):
        # The launcher hold 4 (the domain swap) answers a plain ok: the landing, at the mark and after it.
        self.assertIn("land", drive(self, 0, list_screen=False))
        self.assertIn("land", drive(self, 20, list_screen=False))

    def test_no_hold_marker_gives_neither(self):
        flashes = drive(self, 0, marker=False)
        self.assertNotIn("queue", flashes)
        self.assertNotIn("land", flashes)


if __name__ == "__main__":
    unittest.main(verbosity=2)
