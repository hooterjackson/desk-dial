"""Protocol regression tests run without hardware or Windows input injection."""

from copy import deepcopy
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from protocol import EventMapper, LineDecoder, demo_updates


class LineDecoderTests(unittest.TestCase):
    def test_noise_fragmentation_and_multiple_frames(self):
        decoder = LineDecoder()
        self.assertEqual(decoder.feed(b'COM thread started\r\nundefined{"p"'), [])
        self.assertEqual(decoder.feed(b':42}\r\n{"kd":0,"ks":1}\n{"p":'), [{"p": 42}, {"kd": 0, "ks": 1}])
        self.assertEqual(decoder.feed(b'43}\n'), [{"p": 43}])

    def test_corrupt_data_recovers_at_next_line(self):
        decoder = LineDecoder()
        data = b'{bad}\n[1,2]\n{"p":NaN}\n{"x":"\xff"}\n{"p":4}\n'
        self.assertEqual(decoder.feed(data), [{"p": 4}])

    def test_utf8_may_be_split_between_bytes(self):
        decoder = LineDecoder()
        encoded = '{"profile":{"name":"Música"}}\n'.encode("utf-8")
        output = []
        for value in encoded:
            output.extend(decoder.feed(bytes([value])))
        self.assertEqual(output, [{"profile": {"name": "Música"}}])

    def test_overlong_frame_drops_its_event_looking_tail(self):
        decoder = LineDecoder(max_line_bytes=20)
        self.assertEqual(decoder.feed(b'x' * 21), [])
        self.assertEqual(decoder.feed(b'{"p":8}\n{"p":9}\n'), [{"p": 9}])

    def test_default_bound_and_reset(self):
        decoder = LineDecoder()
        self.assertEqual(decoder.feed(b'x' * (3 * 65_536)), [])
        self.assertLessEqual(len(decoder._buffer), 65_536)
        decoder.reset()
        self.assertEqual(decoder.feed(b'{"p":7}\n'), [{"p": 7}])


class EventMapperTests(unittest.TestCase):
    def setUp(self):
        self.mapper = EventMapper()

    def test_position_baseline_duplicates_and_direction(self):
        self.assertEqual(self.mapper.consume({"p": 100}), [])
        self.assertEqual(self.mapper.consume({"p": 100}), [])
        self.assertEqual(self.mapper.consume({"p": 102}), [("turn", 2)])
        self.assertEqual(self.mapper.consume({"p": 101}), [("turn", -1)])

    def test_large_discontinuity_rebases_and_limits_action(self):
        self.mapper.consume({"p": 0})
        self.assertEqual(self.mapper.consume({"p": 1000}), [])
        self.assertEqual(self.mapper.consume({"p": 1020}), [("turn", 8)])
        self.assertEqual(self.mapper.consume({"p": 1021}), [("turn", 1)])
        self.assertEqual(self.mapper.consume({"p": 1000}), [("turn", -8)])

    def test_uint16_rollover(self):
        self.mapper.consume({"p": 65_535})
        self.assertEqual(self.mapper.consume({"p": 0}), [("turn", 1)])
        self.assertEqual(self.mapper.consume({"p": 65_535}), [("turn", -1)])

    def test_invalid_position_does_not_poison_baseline(self):
        self.mapper.consume({"p": 2})
        for value in (True, False, -1, 65_536, float("nan"), float("inf"), "4", 4.2, None):
            with self.subTest(value=value):
                self.assertEqual(self.mapper.consume({"p": value}), [])
        self.assertEqual(self.mapper.consume({"p": 3}), [("turn", 1)])

    def test_button_zero_and_repeat_until_release(self):
        self.assertEqual(self.mapper.consume({"kd": 0, "ks": 1}), [("button", 0)])
        self.assertEqual(self.mapper.consume({"kd": 0, "ks": 1}), [])
        self.assertEqual(self.mapper.consume({"ku": 0, "ks": 0}), [])
        self.assertEqual(self.mapper.consume({"kd": 0, "ks": 1}), [("button", 0)])

    def test_state_only_updates_deduplication(self):
        self.assertEqual(self.mapper.consume({"ks": 4}), [])
        self.assertEqual(self.mapper.consume({"kd": 2, "ks": 4}), [])
        self.mapper.consume({"ks": 0})
        self.assertEqual(self.mapper.consume({"kd": 2, "ks": 4}), [("button", 2)])

    def test_legacy_chords_release_and_state(self):
        self.assertEqual(self.mapper.consume({"kd": "AC", "ks": "AbCd"}), [("button", 0), ("button", 2)])
        self.assertEqual(self.mapper.consume({"kd": "AC", "ks": "AbCd"}), [])
        self.assertEqual(self.mapper.consume({"ku": "AC", "kd": "D", "ks": "abcD"}), [("button", 3)])
        self.assertEqual(self.mapper.consume({"kd": "A", "ks": "AbcD"}), [("button", 0)])

    def test_invalid_keys_do_not_trigger(self):
        for value in (True, False, -1, 4, 0.0, None, "E", "A?", "0"):
            with self.subTest(value=value):
                self.assertEqual(self.mapper.consume({"kd": value}), [])
        self.assertEqual(self.mapper.consume({"kd": 0, "ks": 0}), [])

    def test_legacy_angles_accumulate_small_movements(self):
        step = math.tau / 24
        self.assertEqual(self.mapper.consume({"a": 0, "t": 0}), [])
        self.assertEqual(self.mapper.consume({"a": step / 2, "t": 0}), [])
        self.assertEqual(self.mapper.consume({"a": step, "t": 0}), [("turn", 1)])
        self.assertEqual(self.mapper.consume({"a": 0, "t": 0}), [("turn", -1)])

    def test_legacy_angle_wrap_and_discontinuity(self):
        step = math.tau / 24
        self.mapper.consume({"a": math.tau - step / 2})
        self.assertEqual(self.mapper.consume({"a": step / 2}), [("turn", 1)])
        self.mapper.reset()
        self.mapper.consume({"a": 0, "t": 0})
        self.assertEqual(self.mapper.consume({"a": 0, "t": 20}), [])
        self.assertEqual(self.mapper.consume({"a": step, "t": 20}), [("turn", 1)])

    def test_invalid_angles_and_turn_counts_do_not_poison_baseline(self):
        self.mapper.consume({"a": 0, "t": 0})
        for value in (True, "1", float("nan"), float("inf"), math.tau + 1, 10 ** 1000):
            with self.subTest(value=value):
                self.assertEqual(self.mapper.consume({"a": value, "t": 0}), [])
        for value in (True, 0.5, "0", 1_000_001):
            with self.subTest(value=value):
                self.assertEqual(self.mapper.consume({"a": 0, "t": value}), [])
        self.assertEqual(self.mapper.consume({"a": math.tau / 24, "t": 0}), [("turn", 1)])

    def test_reset_clears_position_and_button_state(self):
        self.mapper.consume({"p": 100, "kd": 0})
        self.mapper.reset()
        self.assertEqual(self.mapper.consume({"p": 0, "kd": 0}), [("button", 0)])


class ProfilePatchTests(unittest.TestCase):
    def test_patch_preserves_haptics_and_original_without_aliasing(self):
        original = {
            "name": "Original", "ledBrightness": 50,
            "keys": [{"pressed": [{"type": "next_profile"}]}],
            "knob": [{"type": "midi", "channel": 1, "step": 1,
                      "haptic": {"mode": 1, "detentStrength": 2, "detentCount": 127},
                      "every": {"type": "key"}, "cw": {}, "ccw": {}, "actions": ["old"]}],
        }
        saved = deepcopy(original)
        updates = demo_updates(original)
        self.assertEqual(original, saved)
        self.assertEqual(set(updates), {"keys", "knob"})
        self.assertEqual(updates["keys"], [{"pressed": [], "held": [], "released": []}] * 4)
        self.assertEqual(updates["knob"][0]["haptic"], original["knob"][0]["haptic"])
        self.assertEqual(updates["knob"][0]["type"], "actions")
        self.assertTrue(all(key not in updates["knob"][0] for key in ("every", "cw", "ccw")))
        self.assertEqual(updates["knob"][0]["actions"], [])
        updates["knob"][0]["haptic"]["mode"] = 999
        updates["keys"][0]["pressed"].append("changed")
        self.assertEqual(updates["keys"][1]["pressed"], [])
        self.assertEqual(original, saved)

    def test_unknown_profile_shape_does_not_invent_motor_configuration(self):
        for original in ({}, {"knob": []}, {"knob": [{"type": "midi"}]}, {"knob": [None]}):
            with self.subTest(original=original), self.assertRaises(ValueError):
                demo_updates(original)


if __name__ == "__main__":
    unittest.main()
