"""app_profiles validation (plan sections 1a and 6, S1 DD-A): Karl's own refusal cases from
tools/profile_json_test/test.c, every limit of profile_json.c / app_profiles_valid(), and hostile files
(oversize, deep nesting, non-ASCII, duplicate keys, NaN, huge numbers, wrong types). Headless."""
from pathlib import Path
import copy
import json
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import app_profiles as ap  # noqa: E402
from control_center.app_profiles import ProfileError, read_json, validate_karl  # noqa: E402

KARL = Path(__file__).resolve().parents[1] / "profiles" / "karl"
L4 = ["", "", "", ""]


def base(**extra):
    doc = {"format": 1, "id": "x", "name": "X", "legend": list(L4)}
    doc.update(extra)
    return doc


def ring(*cmds, **extra):
    r = {"name": "R", "tab": "R", "cmds": list(cmds) or [{"name": "C"}]}
    r.update(extra)
    return r


def el(*fields):
    return list(fields) if fields else [0, 0, 0, 0, 0, 0, 0, 0, 0]


class KarlTestCTests(unittest.TestCase):
    """The refuse() and accept cases of Karl's test.c, verbatim JSON."""

    def refused(self, text):
        try:
            doc = read_json(text.encode(), "t.json")
        except ProfileError as exc:
            return exc.problems
        problems = validate_karl(doc)
        self.assertTrue(problems, text)
        return problems

    def test_karl_refusals(self):
        cases = {
            "not json": '{"format":1,',
            "wrong format": '{"format":9,"id":"x","name":"X","legend":["","","",""]}',
            "bad id": '{"format":1,"id":"Bad Id","name":"X","legend":["","","",""]}',
            "no legend": '{"format":1,"id":"x","name":"X"}',
            "unknown kind": '{"format":1,"id":"x","name":"X","legend":["","","",""],"slots":{"knob":{"kind":"fly"}}}',
            "wheel, no rings": '{"format":1,"id":"x","name":"X","legend":["","","",""],"slots":{"f3":{"kind":"commands"}}}',
            "bad element": '{"format":1,"id":"x","name":"X","legend":["","","",""],"rings":[{"name":"A","tab":"A",'
                           '"cmds":[{"name":"C","scene":{"frames":[{"ms":1,"el":[[99,0,0,0,0,0,0,0,0]]}]}}]}]}',
            "short icon": '{"format":1,"id":"x","name":"X","legend":["","","",""],"icon48":"AAAA"}',
            "unknown macro": '{"format":1,"id":"x","name":"X","legend":["","","",""],"slots":{"f1":{"kind":"tap",'
                             '"macro":"NOPE"}}}',
            "two same names": '{"format":1,"id":"x","name":"X","legend":["","","",""],"macros":[{"name":"A",'
                              '"steps":[]},{"name":"A","steps":[]}]}',
            "non-ascii text": '{"format":1,"id":"x","name":"X","legend":["","","",""],"macros":[{"name":"A",'
                              '"steps":[{"text":"\\u00e9"}]}]}',
            "non-ascii raw": '{"format":1,"id":"x","name":"X","legend":["","","",""],"macros":[{"name":"A",'
                             '"steps":[{"text":"é"}]}]}',
            "long wait": '{"format":1,"id":"x","name":"X","legend":["","","",""],"macros":[{"name":"A",'
                         '"steps":[{"wait":99999}]}]}',
            "macro cmd, none": '{"format":1,"id":"x","name":"X","legend":["","","",""],"rings":[{"name":"R",'
                               '"tab":"R","cmds":[{"name":"C","kind":"macro"}]}]}',
        }
        for what, text in cases.items():
            with self.subTest(what):
                self.refused(text)

    def test_karl_accepts(self):
        minimal = ('{"format":1,"id":"mine","name":"MINE","legend":["A","B","C","MENU"],'
                   '"slots":{"knob":{"kind":"wheel","sign":1}}}')
        self.assertEqual(validate_karl(read_json(minimal.encode())), [])
        macros = ('{"format":1,"id":"mac","name":"MAC","legend":["A","B","C","MENU"],'
                  '"macros":[{"name":"HI","steps":[{"key":[8,4]},{"wait":250},{"text":"Hello, {World}!"}]},'
                  '{"name":"BYE","steps":[{"text":"bye"}]}],'
                  '"slots":{"f1":{"kind":"tap","macro":"BYE"},"f2":{"kind":"wheel","sign":1,"tap_macro":"HI"},'
                  '"f3":{"kind":"commands"}},'
                  '"rings":[{"name":"R","tab":"R","slot":"f1","cmds":[{"name":"SAY HI","kind":"macro","macro":"HI"}]}]}')
        doc = read_json(macros.encode())
        self.assertEqual(validate_karl(doc), [])
        p = ap._build(doc, {}, source="user", karl_sha256="", rules=None)
        self.assertEqual([s.kind for s in p.macros["HI"]], ["key", "wait", "text"])
        self.assertEqual(p.macros["HI"][1].ms, 250)
        self.assertEqual(p.macros["HI"][2].text, "Hello, {World}!")
        self.assertEqual(p.macros["HI"][0].chord, ap.keymap.parse_chord("ctrl+a"))
        self.assertEqual((p.slots["f1"].macro, p.slots["f2"].tap_macro), ("BYE", "HI"))
        self.assertEqual(p.rings[0].commands[0].macro, "HI")
        self.assertEqual(p.rings[0].commands[0].kind, "macro")
        blob = p.wire()
        self.assertEqual(ap.decode_wire(blob)["rings"][0]["cmds"][0]["flags"], ap.CMD_MACRO)

    def test_karl_exports_are_valid(self):
        for path in sorted(p for p in KARL.glob("*.json") if p.name != "SOURCE.json"):
            with self.subTest(path.name):
                self.assertEqual(validate_karl(read_json(path)), [])


class LimitTests(unittest.TestCase):
    def bad(self, doc, fragment):
        problems = validate_karl(doc)
        self.assertTrue(any(fragment in p for p in problems), (fragment, problems))

    def ok(self, doc):
        self.assertEqual(validate_karl(doc), [])

    def test_strings(self):
        self.ok(base(id="a" * 11, name="N" * 15, legend=["L" * 7] * 4))
        self.bad(base(id="a" * 12), "id")
        self.bad(base(id=""), "id")
        self.bad(base(id="Ab"), "id: a-z")
        self.bad(base(name="N" * 16), "name: 1..15 characters")
        self.bad(base(name=""), "name")
        self.bad(base(legend=["L" * 8, "", "", ""]), "legend[0]: up to 7 characters")
        self.bad(base(legend=["", "", ""]), "legend: 4 texts")
        self.bad(base(legend=["\x01", "", "", ""]), "legend[0]: plain ASCII")
        self.bad(base(legend=[1, "", "", ""]), "legend[0]: text")
        self.bad(base(name=5), "name: text")
        del_id = base()
        del del_id["id"]
        self.bad(del_id, "id: missing")
        self.ok(base(rings=[ring({"name": "C" * 23})]))
        self.bad(base(rings=[ring({"name": "C" * 24})]), "rings[0].cmds[0].name: 1..23 characters")
        self.bad(base(rings=[ring(tab="T" * 7)]), "rings[0].tab")
        self.bad(base(rings=[ring(name="")]), "rings[0].name")
        self.bad(base(search={"open": [4, 6]}, rings=[ring({"name": "C", "kind": "actions", "phrase": "p" * 61})]),
                 "phrase: up to 60 characters")
        self.bad(base(slots={"knob": {"label": "L" * 24}}), "slots.knob.label")

    def test_counts(self):
        self.ok(base(rings=[ring() for _ in range(8)]))
        self.bad(base(rings=[ring() for _ in range(9)]), "rings: a list of up to 8")
        self.ok(base(rings=[ring(*({"name": "C"} for _ in range(32)))]))
        self.bad(base(rings=[ring(*({"name": "C"} for _ in range(33)))]), "cmds: a list of up to 32")
        self.bad(base(rings=[{"name": "R", "tab": "R", "cmds": []}]), "at least one command")
        self.bad(base(rings=[{"name": "R", "tab": "R"}]), "at least one command")
        scene = {"base": [el()] * 48, "frames": [{"ms": 60000, "el": [el()] * 48}] * 16}
        self.ok(base(rings=[ring({"name": "C", "scene": scene})]))
        self.bad(base(rings=[ring({"name": "C", "scene": {"base": [el()] * 49}})]), "base: a list of up to 48")
        self.bad(base(rings=[ring({"name": "C", "scene": {"frames": [{"ms": 1}] * 17}})]), "frames: a list of up to 16")
        self.bad(base(rings=[ring({"name": "C", "scene": {"frames": [{"ms": 60001}]}})]), "ms: a whole number")
        self.ok(base(macros=[{"name": f"M{i}", "steps": [{"wait": 1}] * 64} for i in range(16)]))
        self.bad(base(macros=[{"name": f"M{i}"} for i in range(17)]), "macros: a list of up to 16")
        self.bad(base(macros=[{"name": "M", "steps": [{"wait": 1}] * 65}]), "steps: a list of up to 64")
        self.bad(base(macros=[{"name": "M" * 16}]), "macros[0].name")
        self.bad(base(macros=[{"name": "M", "steps": [{"text": "t" * 121}]}]), "text: up to 120")
        self.bad(base(macros=[{"name": "M", "steps": [{"bogus": 1}]}]), "each is a key, a text or a wait")
        self.bad(base(macros=[{"name": "M", "steps": [5]}]), "each is a key, a text or a wait")

    def test_elements(self):
        lo, hi = list(ap.EL_LO), list(ap.EL_HI)
        self.ok(base(rings=[ring({"name": "C", "scene": {"base": [lo, hi]}})]))
        for j in range(9):
            for v in (lo[j] - 1, hi[j] + 1):
                e = list(lo)
                e[j] = v
                self.bad(base(rings=[ring({"name": "C", "scene": {"base": [e]}})]), f"base[0][{j}]")
        self.bad(base(rings=[ring({"name": "C", "scene": {"base": [[0] * 8]}})]), "elements are 9 numbers")
        self.bad(base(rings=[ring({"name": "C", "scene": {"base": [[0.5] + [0] * 8]}})]), "base[0][0]")
        self.bad(base(rings=[ring({"name": "C", "scene": 5})]), "scene: an object")

    def test_enums_and_numbers(self):
        self.bad(base(visual="cube"), "visual: unknown value")
        self.bad(base(shape="sphere"), "shape: unknown value")
        self.bad(base(shape_style="x"), "shape_style")
        self.bad(base(shape_stepped=1), "shape_stepped: true or false")
        self.bad(base(plasma=[0, 0]), "plasma: 3 colours")
        self.bad(base(plasma=[0, 0, 0x1000000]), "plasma[2]")
        self.bad(base(plasma=[0, 0, 1.5]), "plasma[2]")
        self.ok(base(plasma=[0, 0xFFFFFF, 1]))
        self.bad(base(slots={"knob": {"feel": "rough"}}), "slots.knob.feel")
        self.bad(base(slots={"knob": {"fx": "spin"}}), "slots.knob.fx")
        self.bad(base(slots={"knob": {"detents": 37}}), "slots.knob.detents: a whole number 0..36")
        self.bad(base(slots={"knob": {"buttons": 32}}), "slots.knob.buttons")
        self.bad(base(slots={"knob": {"modifier": 256}}), "slots.knob.modifier")
        self.bad(base(slots={"knob": {"sign": 2}}), "slots.knob.sign")
        self.bad(base(slots={"knob": {"px_per_rad": 2001}}), "px_per_rad")
        self.bad(base(slots={"knob": {"px_per_rad": -1}}), "px_per_rad")
        self.bad(base(slots={"knob": {"cw": [0, 256]}}), "slots.knob.cw: [modifier, keycode] 0..255")
        self.bad(base(slots={"knob": {"cw": [0]}}), "slots.knob.cw: [modifier, keycode]")
        self.bad(base(slots={"knob": 5}), "slots.knob: an object")
        self.bad(base(slots=[]), "slots: an object")
        self.bad(base(format=1.5), "format")
        self.ok(base(format=1.0))
        self.bad(base(rings=[ring(slot="f5")]), "rings[0].slot")
        self.bad(base(rings=[ring({"name": "C", "kind": "shell"})]), "kind: unknown value")
        self.bad(base(search={"open_wait": 256}), "search.open_wait")
        self.bad(base(param_keys={"axis": [[0, 1]]}), "param_keys.axis: 3 keys")
        self.bad(base(param_keys={"step_mod": [0, 0, 256]}), "param_keys.step_mod[2]")
        self.bad(base(param_keys={"scroll_sign": 5}), "scroll_sign")
        self.bad(base(param_keys={"field": "yes"}), "param_keys.field")

    def test_params(self):
        good = {"label": "DEPTH", "steps": [0.01, 0.1, 1], "start": 1, "min": 0, "max": 10, "decimals": 2,
                "visual": "extrude", "modes": 15, "axis_default": 3}
        self.ok(base(rings=[ring({"name": "C", "param": good})]))
        for change, fragment in (({"label": ""}, "label"), ({"steps": [1, 2]}, "steps: 3 numbers"),
                                 ({"steps": [1, 2, "3"]}, "steps"), ({"min": 11}, "min above max"),
                                 ({"decimals": 5}, "decimals"), ({"visual": "spin"}, "visual"),
                                 ({"modes": 16}, "modes"), ({"axis_default": 4}, "axis_default"),
                                 ({"deg": 1}, "deg"), ({"start": 2e7}, "start"), ({"label_neg": "N" * 24}, "label_neg"),
                                 ({"enter": [0, 300]}, "enter")):
            p = dict(good, **change)
            self.bad(base(rings=[ring({"name": "C", "param": p})]), fragment)
        no_label = dict(good)
        del no_label["label"]
        self.bad(base(rings=[ring({"name": "C", "param": no_label})]), "label: missing")

    def test_app_profiles_valid_rules(self):
        """app_profiles.c: a search command needs a phrase and a search key; a wheel needs rings."""
        self.bad(base(rings=[ring({"name": "C", "kind": "actions", "phrase": "x"})]), "no search.open key")
        self.bad(base(search={"open": [4, 6]}, rings=[ring({"name": "C", "kind": "actions"})]), "needs its phrase")
        self.ok(base(search={"open": [4, 6]}, rings=[ring({"name": "C", "kind": "actions", "phrase": "x"})]))
        self.bad(base(slots={"f2": {"kind": "commands"}}), "needs rings")
        self.ok(base(slots={"f2": {"kind": "commands"}}, rings=[ring()]))

    def test_unknown_karl_keys_are_ignored_like_karl(self):
        self.ok(base(future_field={"x": 1}, slots={"f9": {"kind": "fly"}}))


class HostileTests(unittest.TestCase):
    def refuse(self, data, fragment):
        with self.assertRaises(ProfileError) as ctx:
            read_json(data, "h.json")
        self.assertTrue(any(fragment in p for p in ctx.exception.problems), ctx.exception.problems)

    def test_size(self):
        doc = base(name="X")
        text = json.dumps(doc)
        padded = text[:-1] + "," + '"pad":"' + "a" * (ap.FILE_MAX - len(text)) + '"}'
        self.refuse(padded.encode(), "bigger than 128 KB")

    def test_size_on_disk(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "big.json"
            path.write_bytes(b" " * (ap.FILE_MAX + 1))
            with self.assertRaises(ProfileError):
                read_json(path, "big.json")
            with self.assertRaises(ProfileError):
                ap.load_pair(path)

    def test_nesting(self):
        self.refuse(b'{"a":' + b"[" * 40 + b"]" * 40 + b"}", "nested deeper than 32")
        self.refuse(b"[" * 100000, "nested deeper")
        read_json(b'{"a":' + b"[" * 30 + b"]" * 30 + b"}")
        read_json(b'{"a":"' + b"[" * 100 + b'"}')               # brackets inside a string don't count

    def test_non_ascii_and_controls(self):
        self.refuse('{"name":"café"}'.encode("utf-8"), "not plain ASCII")
        self.refuse(b'{"name":"a\x00b"}', "not plain ASCII")
        self.refuse(b"\xef\xbb\xbf{}", "not plain ASCII")       # a UTF-8 BOM
        read_json(b'{\r\n\t"a": 1\n}')

    def test_numbers(self):
        self.refuse(b'{"a": NaN}', "NaN")
        self.refuse(b'{"a": Infinity}', "Infinity")
        self.refuse(b'{"a": -Infinity}', "Infinity")
        self.refuse(b'{"a": 1e400}', "too large")
        self.refuse(b'{"a": ' + b"9" * 5000 + b"}", "too large")
        self.refuse(b'{"a": ' + b"9" * 19 + b"}", "too large")
        doc = read_json(b'{"a": 1e300}')
        problems = validate_karl(dict(base(rings=[ring({"name": "C", "param": {"label": "L", "max": doc["a"]}})])))
        self.assertTrue(any("max" in p for p in problems))

    def test_duplicate_keys_and_shapes(self):
        self.refuse(b'{"id":"a","id":"b"}', "appears twice")
        self.refuse(b"[]", "not a JSON object")
        self.refuse(b'"x"', "not a JSON object")
        self.refuse(b"", "not valid JSON")
        self.assertEqual(validate_karl([]), ["not a JSON object"])

    def test_wrong_types_everywhere(self):
        """Every field of a real export swapped for a wrong type is refused, never a crash."""
        doc = read_json(KARL / "plasticity.json")
        doc.pop("icon48"), doc.pop("icon24")
        for r in doc["rings"]:
            for i, cmd in enumerate(r["cmds"]):
                if i and "scene" in cmd:
                    cmd["scene"] = {"frames": [{"ms": 1, "el": [[0] * 9]}]}     # one full scene is enough
        weird = (None, True, "x", 1.5, [], {}, -1, 10 ** 9)

        def paths(node, prefix=()):
            yield prefix
            if isinstance(node, dict):
                for k, v in node.items():
                    yield from paths(v, prefix + (k,))
            elif isinstance(node, list) and len(node) < 12:
                for i, v in enumerate(node):
                    yield from paths(v, prefix + (i,))
        count = 0
        for path in list(paths(doc))[1:]:
            for value in weird:
                bad = copy.deepcopy(doc)
                node = bad
                for k in path[:-1]:
                    node = node[k]
                node[path[-1]] = value
                problems = validate_karl(bad)
                if not problems:
                    ap._build(bad, {}, source="bundled", karl_sha256="", rules=None).wire()
                count += 1
        self.assertGreater(count, 800)


if __name__ == "__main__":
    unittest.main()
