"""FW-BUG-035 device-side check: out-of-range register commands are refused, never aliased.

The knob range-checks {"R":"<reg>[=<value>]"}: the register must be 0..255 and the recalibrate value (register 129)
0 or 1. Before the fix, 385 aliased to 129 and 257 read as 1, so both started a motor-moving recalibration.

register_number_out_of_range_is_refused(link) drives a raw serial link (write(bytes), read(n) -> bytes) to an
UNCLAIMED knob (the knob refuses every R while a control is claimed):
  1. {"R":"385=1"} and {"R":"129=257"} each get an {"error":...} line, no {"r":...} line, and no recalibration
     (no {"calibrating":true} line; the knob announces every run, whatever started it).
  2. {"R":"129=1"} still starts a recalibration: r129=0, then calibrating, then calibrated.
The motor moves in step 2 (hands off the knob). Returns a report dict; raises AssertionError on a failure.
"""
import json
import time

REFUSED_COMMANDS = ("385=1", "129=257")
ACCEPTED_COMMAND = "129=1"
ACCEPTED_REPLY = "r129=0"


class LineReader:
    """Newline-delimited JSON lines from a raw link; non-JSON lines are skipped."""

    def __init__(self, link, clock=time.monotonic):
        self.link = link
        self.clock = clock
        self._buffer = b""

    def lines(self, seconds):
        """Every JSON object line the knob sends within `seconds`."""
        deadline = self.clock() + seconds
        found = []
        while self.clock() < deadline:
            found.extend(self._drain(self.link.read(256) or b""))
        return found

    def until(self, predicate, seconds):
        """Lines up to and including the first one matching `predicate`; None when it never came."""
        deadline = self.clock() + seconds
        seen = []
        while self.clock() < deadline:
            for message in self._drain(self.link.read(256) or b""):
                seen.append(message)
                if predicate(message):
                    return seen
        return None

    def _drain(self, data):
        self._buffer += data
        out = []
        while b"\n" in self._buffer:
            raw, self._buffer = self._buffer.split(b"\n", 1)
            try:
                message = json.loads(raw.decode("utf-8", "replace").strip() or "null")
            except ValueError:
                continue
            if isinstance(message, dict):
                out.append(message)
        return out


def _send(link, command):
    link.write((json.dumps({"R": command}) + "\n").encode("utf-8"))


def register_number_out_of_range_is_refused(link, clock=time.monotonic, settle=1.5, calibrate_timeout=30.0):
    reader = LineReader(link, clock)
    reader.lines(0.2)   # drop anything already queued
    report = {"refused": {}, "accepted": None}
    for command in REFUSED_COMMANDS:
        _send(link, command)
        lines = reader.lines(settle)
        errors = [m for m in lines if "error" in m]
        replies = [m for m in lines if "r" in m]
        calibrating = [m for m in lines if m.get("calibrating") is True or "calibrated" in m]
        report["refused"][command] = dict(error=bool(errors), r=bool(replies), calibrating=bool(calibrating))
        assert errors, f'R "{command}": no error reply'
        assert not replies, f'R "{command}": answered as a register ({replies[0]["r"]!r}), not refused'
        assert not calibrating, f'R "{command}": started a recalibration'
    _send(link, ACCEPTED_COMMAND)
    seen = reader.until(lambda m: "calibrated" in m, calibrate_timeout)
    assert seen is not None, f'R "{ACCEPTED_COMMAND}": no calibrated line within {calibrate_timeout:.0f} s'
    replies = [m["r"] for m in seen if "r" in m]
    assert ACCEPTED_REPLY in replies, f'R "{ACCEPTED_COMMAND}": expected {ACCEPTED_REPLY}, got {replies!r}'
    assert any(m.get("calibrating") is True for m in seen), f'R "{ACCEPTED_COMMAND}": no calibrating line'
    assert not any("error" in m for m in seen), f'R "{ACCEPTED_COMMAND}": answered with an error'
    result = next(m["calibrated"] for m in seen if "calibrated" in m)
    report["accepted"] = dict(r=ACCEPTED_REPLY, calibrated=result)
    return report
