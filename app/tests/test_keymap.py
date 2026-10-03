"""keymap (plan section 4a/4b, S1 DD-A): Karl's HID usages as Windows keys by intent, modifier mapping,
the sidecar chord syntax, and send-time layout resolution against recorded VkKeyScanExW tables for US,
UK, DE (QWERTZ) and FR (AZERTY), plus a live check for each layout that is installed. Headless."""
from pathlib import Path
import ctypes
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import app_profiles, keymap  # noqa: E402
from control_center.keymap import Chord, from_hid, from_text, map_mods, parse_chord, resolve, resolve_chord  # noqa: E402

PROFILES = Path(__file__).resolve().parents[1] / "profiles"

# VkKeyScanExW results (low byte VK, high byte shift state: 1 Shift, 2 Ctrl, 4 Alt; 6 = AltGr; -1 = none)
# for the US punctuation Karl's usages mean. Built from the layouts' published key maps; US was checked
# live on the build machine.
HKL = {"us": 0x04090409, "uk": 0x08090809, "de": 0x04070407, "fr": 0x040C040C}
LAYOUTS = {
    "us": {"-": 0xBD, "=": 0xBB, "[": 0xDB, "]": 0xDD, "\\": 0xDC, ";": 0xBA, "'": 0xDE, "`": 0xC0, ",": 0xBC,
           ".": 0xBE, "/": 0xBF},
    # UK: ' is VK_OEM_3, # ~ VK_OEM_7, ` VK_OEM_8, \ VK_OEM_5 (the key left of Z)
    "uk": {"-": 0xBD, "=": 0xBB, "[": 0xDB, "]": 0xDD, "\\": 0xDC, ";": 0xBA, "'": 0xC0, "`": 0xDF, ",": 0xBC,
           ".": 0xBE, "/": 0xBF},
    # DE QWERTZ: - is unshifted (VK_OEM_MINUS); = Shift+0; ; Shift+,; ' Shift+#; / Shift+7; [ ] \ AltGr
    "de": {"-": 0xBD, "=": 0x130, "[": 0x638, "]": 0x639, "\\": 0x6DB, ";": 0x1BC, "'": 0x1BF, ",": 0xBC,
           ".": 0xBE, "/": 0x137},
    # FR AZERTY: - on 6, ' on 4, ; is unshifted (VK_OEM_PERIOD), . Shift+;, / Shift+:, [ ] \ ` AltGr
    "fr": {"-": 0x36, "=": 0xBB, "[": 0x635, "]": 0x6DB, "\\": 0x638, ";": 0xBE, "'": 0x34, "`": 0x637,
           ",": 0xBC, ".": 0x1BE, "/": 0x1BF},
}


def fixture_scan(layout):
    table = LAYOUTS[layout]

    def scan(char, hkl):
        assert hkl == HKL[layout]
        value = table.get(char, -1)
        return value if value < 0x8000 else value - 0x10000
    return scan


class HidTableTests(unittest.TestCase):
    def test_letters_and_digits_are_layout_independent_vks(self):
        self.assertEqual(from_hid(0x04), keymap.KeySpec(0x04, 0x41, None, False, "A"))
        self.assertEqual(from_hid(0x1D).vk, ord("Z"))
        self.assertEqual(from_hid(0x1E).vk, ord("1"))
        self.assertEqual(from_hid(0x27).vk, ord("0"))
        for usage in range(0x04, 0x28):
            self.assertIsNone(from_hid(usage).char)

    def test_punctuation_is_resolved_by_character(self):
        for usage, char in zip((0x2D, 0x2E, 0x2F, 0x30, 0x31, 0x33, 0x34, 0x35, 0x36, 0x37, 0x38), "-=[]\\;'`,./"):
            spec = from_hid(usage)
            self.assertEqual((spec.vk, spec.char, spec.label), (None, char, char))

    def test_fixed_keys_and_extended_flag(self):
        cases = {0x28: (0x0D, False, "ENTER"), 0x29: (0x1B, False, "ESC"), 0x2A: (0x08, False, "BKSP"),
                 0x2B: (0x09, False, "TAB"), 0x2C: (0x20, False, "SPACE"), 0x3A: (0x70, False, "F1"),
                 0x45: (0x7B, False, "F12"), 0x68: (0x7C, False, "F13"), 0x73: (0x87, False, "F24"),
                 0x49: (0x2D, True, "INS"), 0x4A: (0x24, True, "HOME"), 0x4B: (0x21, True, "PGUP"),
                 0x4C: (0x2E, True, "DEL"), 0x4D: (0x23, True, "END"), 0x4E: (0x22, True, "PGDN"),
                 0x4F: (0x27, True, "RIGHT"), 0x50: (0x25, True, "LEFT"), 0x51: (0x28, True, "DOWN"),
                 0x52: (0x26, True, "UP"), 0x54: (0x6F, True, "NUM/"), 0x55: (0x6A, False, "NUM*"),
                 0x56: (0x6D, False, "NUM-"), 0x57: (0x6B, False, "NUM+"), 0x58: (0x0D, True, "NUMENT"),
                 0x59: (0x61, False, "NUM1"), 0x61: (0x69, False, "NUM9"), 0x62: (0x60, False, "NUM0"),
                 0x63: (0x6E, False, "NUM."), 0xE4: (0xA3, True, "RCTRL"), 0xE6: (0xA5, True, "RALT"),
                 0xE0: (0xA2, False, "LCTRL")}
        for usage, (vk, extended, label) in cases.items():
            spec = from_hid(usage)
            self.assertEqual((spec.vk, spec.extended, spec.label), (vk, extended, label), hex(usage))
        for vk in (0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x6F, 0xA3, 0xA5):
            self.assertIn(vk, keymap.EXTENDED_VKS)
        self.assertNotIn(0x0D, keymap.EXTENDED_VKS)        # only the numpad Enter, through its KeySpec

    def test_labels_fit_the_wire(self):
        for usage in range(256):
            try:
                spec = from_hid(usage)
            except ValueError:
                continue
            self.assertLessEqual(len(spec.label), keymap.LABEL_MAX)
            self.assertTrue(all(0x20 <= ord(c) <= 0x7E for c in spec.label))

    def test_unsupported_usages_refuse(self):
        for usage in (0x00, 0x32, 0x39, 0x46, 0x53, 0x64, 0x7F, 0xFF, -1, 300, "4", True):
            with self.assertRaises(ValueError):
                from_hid(usage)


class TextAndChordTests(unittest.TestCase):
    def test_tokens(self):
        self.assertEqual(from_text("z"), from_hid(0x1D))
        self.assertEqual(from_text("Z"), from_hid(0x1D))
        self.assertEqual(from_text("F5"), from_hid(0x3E))
        self.assertEqual(from_text("/"), from_hid(0x38))
        self.assertEqual(from_text("num1"), from_hid(0x59))
        self.assertEqual(from_text("delete"), from_text("DEL"))
        self.assertEqual(from_text("escape"), from_hid(0x29))
        self.assertEqual(from_text("numenter"), from_hid(0x58))
        for bad in ("", "f25", "ctrl", "+", "ab", None, 5):
            with self.assertRaises(ValueError):
                from_text(bad)

    def test_parse_chord(self):
        self.assertEqual(parse_chord("ctrl+alt+t"), Chord(frozenset({"ctrl", "alt"}), from_hid(0x17)))
        self.assertEqual(parse_chord("Shift+="), Chord(frozenset({"shift"}), from_hid(0x2E)))
        self.assertEqual(parse_chord("ctrl+num+"), Chord(frozenset({"ctrl"}), from_hid(0x57)))
        self.assertEqual(parse_chord("win+shift+s").mods, frozenset({"win", "shift"}))
        for bad in ("", "ctrl+", "ctrl+ctrl+z", "cmd+z", "ctrl+alt", "ctrl+zz"):
            with self.assertRaises(ValueError):
                parse_chord(bad)

    def test_chord_text_round_trips(self):
        for text in ("ctrl+alt+t", "shift+/", "ctrl+shift+z", "f5", "alt+num."):
            chord = parse_chord(text)
            self.assertEqual(parse_chord(keymap.chord_text(chord)), chord)
        self.assertEqual(keymap.chord_text(parse_chord("Alt+Ctrl+T")), "ctrl+alt+t")

    def test_map_mods(self):
        self.assertEqual(map_mods(0x08), frozenset({"ctrl"}))                    # Cmd
        self.assertEqual(map_mods(0x80), frozenset({"ctrl"}))                    # right Cmd
        self.assertEqual(map_mods(0x04), frozenset({"alt"}))                     # Option
        self.assertEqual(map_mods(0x0C), frozenset({"ctrl", "alt"}))             # Option+Cmd (Figma WRAP IN FRAME)
        self.assertEqual(map_mods(0x0A), frozenset({"ctrl", "shift"}))
        self.assertEqual(map_mods(0x21), frozenset({"ctrl", "shift"}))           # LCtrl + RShift
        self.assertEqual(map_mods(0x08, gui_to="win"), frozenset({"win"}))
        self.assertEqual(map_mods(0), frozenset())
        for bad in (-1, 256, 1.5, "8"):
            with self.assertRaises(ValueError):
                map_mods(bad)
        self.assertTrue(keymap.karl_mods_collide(0x09))                          # Ctrl+Cmd -> ctrl twice
        self.assertFalse(keymap.karl_mods_collide(0x09, gui_to="win"))
        self.assertFalse(keymap.karl_mods_collide(0x11))                         # left and right Ctrl

    def test_display_mods(self):
        self.assertEqual(keymap.display_mods(frozenset({"ctrl", "shift", "alt", "win"})), 15)
        self.assertEqual(keymap.display_mods(frozenset({"alt"})), 4)


class LayoutTests(unittest.TestCase):
    def check(self, layout, char, mods, want):
        chord = Chord(frozenset(mods), from_text(char))
        self.assertEqual(resolve_chord(chord, HKL[layout], fixture_scan(layout)), want, (layout, char, mods))

    def test_layout_independent_keys_never_call_vk_key_scan(self):
        def boom(char, hkl):
            raise AssertionError("called")
        self.assertEqual(resolve(from_text("z"), HKL["de"], boom), (ord("Z"), frozenset()))
        self.assertEqual(resolve(from_text("num1"), HKL["fr"], boom), (0x61, frozenset()))

    def test_us_and_uk(self):
        for char in "-=[]\\;'`,./":
            self.check("us", char, (), (LAYOUTS["us"][char], frozenset()))
        self.check("uk", "'", (), (0xC0, frozenset()))
        self.check("uk", "/", ("ctrl",), (0xBF, frozenset({"ctrl"})))

    def test_german_qwertz(self):
        self.check("de", "/", (), None)                                 # Shift+7: a plain '/' shortcut refuses
        self.check("de", "/", ("shift",), (0x37, frozenset({"shift"})))  # the chord already holds Shift
        self.check("de", "[", (), None)                                 # AltGr+8
        self.check("de", "[", ("ctrl", "alt"), None)                    # AltGr is never sent, even then
        self.check("de", ".", ("alt",), (0xBE, frozenset({"alt"})))
        self.check("de", "`", (), None)                                 # dead key: not in the table
        self.assertEqual(resolve(from_text("z"), HKL["de"], fixture_scan("de")), (0x5A, frozenset()))  # VK_Z stays Z
        self.assertEqual(resolve(from_text("/"), HKL["de"], fixture_scan("de")), (0x37, frozenset({"shift"})))

    def test_french_azerty(self):
        self.check("fr", "/", (), None)                                 # Shift+: on AZERTY
        self.check("fr", ".", (), None)
        self.check("fr", ";", (), (0xBE, frozenset()))
        self.check("fr", "-", ("ctrl",), (0x36, frozenset({"ctrl"})))
        self.check("fr", "\\", (), None)
        self.check("fr", ",", (), (0xBC, frozenset()))

    def test_plasticity_view_ring_on_each_layout(self):
        """FOCUS '/', ISOLATE '.', UNISOLATE Alt+'.': sent on US / UK, refused where Shift is needed."""
        p = app_profiles.load_pair(PROFILES / "karl" / "plasticity.json", PROFILES / "plasticity.windows.json")
        view = {c.name: c.chord for c in next(r for r in p.rings if r.name == "VIEW").commands}
        for layout, sent in (("us", True), ("uk", True), ("de", True), ("fr", False)):
            for name in ("FOCUS", "ISOLATE", "UNISOLATE"):
                got = resolve_chord(view[name], HKL[layout], fixture_scan(layout))
                if name == "FOCUS" and layout == "de":
                    self.assertIsNone(got)
                else:
                    self.assertEqual(got is not None, sent, (layout, name))

    def test_not_on_layout_and_odd_shift_states(self):
        spec = from_text("/")
        self.assertIsNone(resolve(spec, 1, lambda c, h: -1))
        self.assertIsNone(resolve(spec, 1, lambda c, h: 0x0FBF))       # Hankaku / reserved states
        self.assertIsNone(resolve(spec, 1, lambda c, h: 0x02BF))       # Ctrl alone
        self.assertIsNone(resolve(spec, 1, lambda c, h: 0x04BF))       # Alt alone
        self.assertIsNone(resolve(spec, 1, lambda c, h: 0x0000))


def installed_layouts():
    if sys.platform != "win32":
        return set()
    user32 = ctypes.WinDLL("user32")
    count = user32.GetKeyboardLayoutList(0, None)
    handles = (ctypes.c_void_p * max(count, 1))()
    user32.GetKeyboardLayoutList(count, handles)
    return {(h or 0) & 0xFFFFFFFF for h in handles[:count]}


class LiveLayoutTests(unittest.TestCase):
    """Runs only for layouts already installed (never loads one): the recorded table matches Windows."""

    def test_installed_layouts_match_the_fixtures(self):
        installed = installed_layouts()
        checked = 0
        for name, hkl in HKL.items():
            if hkl not in installed:
                continue
            for char, value in LAYOUTS[name].items():
                live = keymap._default_vk_key_scan(char, hkl) & 0xFFFF
                self.assertEqual(live, value & 0xFFFF, (name, char))
            checked += 1
        if not checked:
            self.skipTest("none of US / UK / DE / FR is installed")


if __name__ == "__main__":
    unittest.main()
