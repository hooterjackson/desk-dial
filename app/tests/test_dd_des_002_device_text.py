"""DD-DES-002: the knob's text adaptation gives ONE "?" per unsupported source character.

NFKD used to split a Hangul syllable into its jamo and expand an Arabic ligature into many letters before
the "?" substitution, so 5 Hangul syllables showed 14 "?" and U+FDFA 18; an emoji with its skin tone,
variation selector or ZWJ partners showed several. Now each source character (an emoji sequence or a flag
pair counted once) is either kept, transliterated when every part of its compatibility form is a glyph, or
one "?". Invisible marks (combining marks, format characters, variation selectors) are dropped. Both the
ASCII (cc4) and the latin-ext-a (presentation >= 4) paths. No port, window or network.
"""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center.device import _device_text, _lcd_text  # noqa: E402

LATIN = {"presentation": 5, "glyphs": "latin-ext-a"}
ASCII = {"presentation": 3}


class DeviceTextTests(unittest.TestCase):
    def both(self, text):
        return _device_text(text, ASCII, 96), _device_text(text, LATIN, 96)

    def test_device_text_unsupported_scripts(self):
        self.assertEqual(self.both("\ud55c\uad6d\uc5b4\ub178\ub798"), ("?????", "?????"))   # 5 Hangul syllables
        self.assertEqual(self.both("\ufdfa"), ("?", "?"))                                   # one ligature
        self.assertEqual(self.both("\u6771\u4eac"), ("??", "??"))
        self.assertEqual(self.both("\u0395\u03bb\u03bb\u03ac\u03b4\u03b1"), ("??????", "??????"))
        self.assertEqual(self.both("\u041c\u0438\u0440"), ("???", "???"))

    def test_emoji_sequences_count_once(self):
        self.assertEqual(self.both("\U0001F525 Mix"), ("? Mix", "? Mix"))
        self.assertEqual(self.both("\U0001F44D\U0001F3FD ok"), ("? ok", "? ok"))              # skin tone
        self.assertEqual(self.both("\u2764\ufe0f Love"), ("? Love", "? Love"))               # VS16
        family = "\U0001F468\u200d\U0001F469\u200d\U0001F467"
        self.assertEqual(self.both(family + " Mix"), ("? Mix", "? Mix"))                     # ZWJ sequence
        self.assertEqual(self.both("\U0001F1E7\U0001F1F7\U0001F1EF\U0001F1F5"), ("??", "??"))  # two flags
        self.assertEqual(self.both("1\ufe0f\u20e3 Top"), ("1 Top", "1 Top"))                 # keycap

    def test_transliteration_is_kept_when_every_part_is_a_glyph(self):
        self.assertEqual(_device_text("Linn\u00e9a Holm \u00b7 \u201cJ\u00f3ga\u201d", ASCII, 96), 'Linnea Holm / "Tide Song"')
        self.assertEqual(_device_text("Linn\u00e9a Holm", LATIN, 96), "Linn\u00e9a Holm")
        self.assertEqual(self.both("\ufb01ne \uff21 \u2122"), ("fine A TM", "fine A TM"))
        self.assertEqual(_device_text("\u00bd time", ASCII, 96), "1/2 time")
        self.assertEqual(_device_text("\u00bd time", LATIN, 96), "\u00bd time")
        self.assertEqual(_device_text("Stra\u00dfe \u00c6nima", ASCII, 96), "Strasse AEnima")
        self.assertEqual(_device_text("e\u0301", ASCII, 96), "e")

    def test_controls_and_invisible_characters(self):
        self.assertEqual(_lcd_text("a\x7fb\x85c"), "a?b?c")
        self.assertEqual(self.both("a\u200bb\u200ec"), ("abc", "abc"))      # zero-width space, LRM: dropped
        self.assertEqual(_device_text("co\u00adop", ASCII, 96), "coop")       # soft hyphen (no ASCII glyph)

    def test_a_long_unsupported_title_no_longer_floods_the_capacity(self):
        title = "\ud55c" * 40
        self.assertEqual(_device_text(title, LATIN, 96), "?" * 40)


if __name__ == "__main__":
    unittest.main()
