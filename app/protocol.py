"""Nano_D++ JSON framing and input mapping, independent of serial and Windows.

The current firmware emits ``p`` as a uint16 position and numeric ``kd``/``ku``
button indices. The older documented angle and letter formats are accepted too.
"""

from __future__ import annotations

from copy import deepcopy
import json
import math
from typing import Any


def _reject_constant(value: str) -> None:
    raise ValueError("Non-finite JSON number")


class LineDecoder:
    """Incrementally decode newline-delimited JSON objects.

    Boot text and malformed lines are ignored. An oversized line is discarded
    through its newline so its tail can never be mistaken for an input event.
    Partial frame storage is bounded by 64 KiB, even without any newlines.
    """

    MAX_LINE_BYTES = 65_536

    def __init__(self, max_line_bytes: int = MAX_LINE_BYTES) -> None:
        if type(max_line_bytes) is not int or not 1 <= max_line_bytes <= self.MAX_LINE_BYTES:
            raise ValueError("max_line_bytes must be between 1 and 65536")
        self.max_line_bytes = max_line_bytes
        self.reset()

    def reset(self) -> None:
        self._buffer = bytearray()
        self._discarding = False

    def feed(self, data: bytes) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        start = 0
        while start < len(data):
            end = data.find(b"\n", start)
            complete = end != -1
            if not complete:
                end = len(data)
            if not self._discarding:
                if len(self._buffer) + end - start > self.max_line_bytes:
                    self._buffer.clear()
                    self._discarding = True
                else:
                    self._buffer.extend(data[start:end])
            if complete:
                if not self._discarding:
                    message = self._decode_line(bytes(self._buffer))
                    if message is not None:
                        messages.append(message)
                self._buffer.clear()
                self._discarding = False
            start = end + 1
        return messages

    @staticmethod
    def _decode_line(line: bytes) -> dict[str, Any] | None:
        line = line.strip()
        # ZeroOne tolerates this prefix on the initial serial frame.
        if line.startswith(b"undefined"):
            line = line[len(b"undefined"):].lstrip()
        if not line.startswith(b"{"):
            return None
        try:
            value = json.loads(line.decode("utf-8"), parse_constant=_reject_constant)
        except (ValueError, UnicodeError, RecursionError):
            return None
        return value if isinstance(value, dict) else None


def _integer(value: Any, minimum: int, maximum: int) -> bool:
    return type(value) is int and minimum <= value <= maximum


def _key_mask(value: Any) -> int:
    if _integer(value, 0, 3):
        return 1 << value
    if isinstance(value, str) and value and all(char in "ABCD" for char in value):
        return sum(1 << index for index, char in enumerate("ABCD") if char in value)
    return 0


def _state_mask(value: Any) -> int | None:
    if _integer(value, 0, 15):
        return value
    if isinstance(value, str) and len(value) == 4:
        if all(char in (upper, upper.lower()) for char, upper in zip(value, "ABCD")):
            return sum(1 << index for index, char in enumerate(value) if char.isupper())
    return None


class EventMapper:
    """Convert input messages to ``('turn', delta)`` / ``('button', 0..3)``.

    Each connection/profile change should call reset(). The first position only
    establishes a baseline. Discontinuities over 32 steps rebase silently; each
    subsequent action is limited to eight steps. Legacy angles use 24 steps per
    revolution and accumulate fractional steps instead of rounding each frame.
    State-only button messages update deduplication without triggering actions.
    """

    MAX_DELTA = 32
    MAX_EMITTED_TURN = 8

    def __init__(self, angle_steps_per_turn: int = 24) -> None:
        if type(angle_steps_per_turn) is not int or not 1 <= angle_steps_per_turn <= 1024:
            raise ValueError("angle_steps_per_turn must be between 1 and 1024")
        self.angle_steps_per_turn = angle_steps_per_turn
        self.reset()

    def reset(self) -> None:
        self._position: int | None = None
        self._angle: float | None = None
        self._angle_has_turns: bool | None = None
        self._angle_remainder = 0.0
        self._pressed = 0

    def consume(self, message: dict[str, Any]) -> list[tuple[str, int]]:
        if not isinstance(message, dict):
            return []
        actions: list[tuple[str, int]] = []
        if "p" in message:
            delta = self._consume_position(message["p"])
        elif "a" in message:
            delta = self._consume_angle(message)
        else:
            delta = 0
        if delta:
            actions.append(("turn", delta))

        state = _state_mask(message.get("ks"))
        self._pressed &= ~_key_mask(message.get("ku"))
        down = _key_mask(message.get("kd"))
        if state is not None:
            # A contradictory state must not create an artificial press.
            down &= state
        new_presses = down & ~self._pressed
        actions.extend(("button", index) for index in range(4) if new_presses & (1 << index))
        self._pressed |= down
        if state is not None:
            self._pressed = state
        return actions

    def _consume_position(self, position: Any) -> int:
        if not _integer(position, 0, 65_535):
            return 0
        previous = self._position
        self._position = position
        self._angle = None
        self._angle_remainder = 0.0
        if previous is None:
            return 0
        # uint16 rollover is one detent, rather than a 65,535-step jump.
        delta = (position - previous + 32_768) % 65_536 - 32_768
        return self._bounded_delta(delta)

    def _consume_angle(self, message: dict[str, Any]) -> int:
        angle = message["a"]
        if type(angle) not in (int, float) or abs(angle) > math.tau or not math.isfinite(angle):
            return 0
        has_turns = "t" in message
        turns = message.get("t", 0)
        if not _integer(turns, -1_000_000, 1_000_000):
            return 0
        absolute = angle + turns * math.tau
        previous = self._angle
        self._position = None
        self._angle = absolute
        if previous is None or self._angle_has_turns != has_turns:
            self._angle_has_turns = has_turns
            self._angle_remainder = 0.0
            return 0
        difference = absolute - previous
        if not has_turns:
            difference = (difference + math.pi) % math.tau - math.pi
        steps = difference * self.angle_steps_per_turn / math.tau
        if abs(steps) > self.MAX_DELTA:
            self._angle_remainder = 0.0
            return 0
        pending = steps + self._angle_remainder
        # Tiny tolerance handles floating-point representations of a detent.
        delta = math.trunc(pending + math.copysign(1e-10, pending))
        self._angle_remainder = pending - delta
        return self._bounded_delta(delta)

    def _bounded_delta(self, delta: int) -> int:
        if abs(delta) > self.MAX_DELTA:
            return 0
        return max(-self.MAX_EMITTED_TURN, min(self.MAX_EMITTED_TURN, delta))


def demo_updates(original: dict[str, Any]) -> dict[str, Any]:
    """Build an in-memory mapping patch for the already-selected profile.

    No name, motor, haptic, display, LED or persistent-save setting is invented.
    The full existing knob mappings are copied so their haptics remain exact;
    only actions are disabled, leaving the host app to handle input events.
    Send this as the ``updates`` of the original profile, never as a new profile.
    """
    if not isinstance(original, dict):
        raise ValueError("Expected a complete profile object")
    knob = original.get("knob")
    if not isinstance(knob, list) or not 1 <= len(knob) <= 8:
        raise ValueError("Profile must contain one to eight existing knob mappings")
    if any(not isinstance(mapping, dict) or not isinstance(mapping.get("haptic"), dict) for mapping in knob):
        raise ValueError("Every knob mapping must include its original haptic configuration")
    knob = deepcopy(knob)
    for mapping in knob:
        mapping["type"] = "actions"
        for key in ("every", "cw", "ccw"):
            mapping.pop(key, None)
        if "actions" in mapping:
            mapping["actions"] = []
    return {
        "keys": [{"pressed": [], "held": [], "released": []} for _ in range(4)],
        "knob": knob,
    }
