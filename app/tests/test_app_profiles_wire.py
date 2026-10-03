"""The DDAP v1 wire compiler (APP_PROFILES.md; plan sections 1b and 6, S1 DD-A): every bundled profile
compiles, deterministically, within 32768 bytes; the strict reference decoder reads back exactly the
effective model; feature bits, de-duplicated scenes, limits; truncations, bit flips and length lies are
refused with a reason code, never a crash. Headless."""
from pathlib import Path
import base64
import random
import struct
import sys
import unittest
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import app_profiles as ap  # noqa: E402
from control_center import keymap  # noqa: E402
from control_center.app_profiles import ProfileError, WireError, decode_wire, load_pair, read_json  # noqa: E402

PROFILES = Path(__file__).resolve().parents[1] / "profiles"
IDS = ("onshape", "figma", "plasticity", "blender", "autocad")


def bundled(pid):
    return load_pair(PROFILES / "karl" / f"{pid}.json", PROFILES / f"{pid}.windows.json")


def build(doc, overlay=None):
    return ap._build(doc, overlay or {}, source="user", karl_sha256="", rules=None)


def recrc(blob):
    blob = bytearray(blob)
    struct.pack_into("<I", blob, len(blob) - 4, zlib.crc32(bytes(blob[:-4])) & 0xFFFFFFFF)
    return bytes(blob)


class BundledWireTests(unittest.TestCase):
    def test_compiles_deterministically_within_budget(self):
        sizes = {}
        for pid in IDS:
            a, b = bundled(pid).wire(), bundled(pid).wire()
            self.assertEqual(a, b, pid)
            self.assertLessEqual(len(a), ap.WIRE_MAX)
            self.assertEqual(struct.unpack_from("<I", a, 8)[0], len(a))
            self.assertEqual(bundled(pid).wire_crc, zlib.crc32(a[:-4]) & 0xFFFFFFFF)
            sizes[pid] = len(a)
        # Display data only (icons 5.76 KB of each): the plan's estimate was 12-20 KB / ~6 KB.
        for pid in ("onshape", "figma", "plasticity"):
            self.assertTrue(8000 < sizes[pid] < 20000, sizes)
        for pid in ("blender", "autocad"):
            self.assertTrue(5800 < sizes[pid] < 6500, sizes)

    def test_features(self):
        self.assertEqual(bundled("onshape").features, ap.F_SHAPE | ap.F_SHAPE_EXT)               # cube, thick
        self.assertEqual(bundled("figma").features, ap.F_LABEL_VISUAL)
        self.assertEqual(bundled("plasticity").features, ap.F_SHAPE | ap.F_SHAPE_EXT | ap.F_PARAM_CONSTRAINTS)
        self.assertEqual(bundled("blender").features, ap.F_LABEL_VISUAL)

    def test_round_trip_equals_the_model(self):
        for pid in IDS:
            with self.subTest(pid):
                p = bundled(pid)
                d = decode_wire(p.wire())
                k = p.raw_karl
                self.assertEqual((d["id"], d["name"], tuple(d["legend"])), (p.id, p.name, p.legend))
                self.assertEqual(d["visual"], ap.VISUAL.index(k.get("visual", "label")))
                self.assertEqual(d["shape_style"], ap.STYLE.index(k.get("shape_style", "face")))
                self.assertEqual(d["stepped"], int(bool(k.get("shape_stepped"))))
                self.assertEqual(d["plasma"], list(k.get("plasma", [0, 0, 0])))
                self.assertEqual(d["icon24"], base64.b64decode(k["icon24"]))
                self.assertEqual(d["icon48"], base64.b64decode(k["icon48"]))
                for name, slot in zip(ap.SLOTS, d["slots"]):
                    s = p.slots[name]
                    self.assertEqual(slot, {"kind": ap.KIND.index(s.kind), "fx": ap.FX.index(s.fx),
                                            "button": 0xFF if s.button is None or s.kind == "none" else s.button,
                                            "label": s.label})
                if p.search:
                    self.assertEqual(d["search"], {"mod": keymap.display_mods(p.search.mods),
                                                   "key": p.search.key.label})
                self.assertEqual(len(d["scenes"]), len(p.scenes))
                for (base, frames), (wb, wf) in zip(p.scenes, d["scenes"]):
                    self.assertEqual([tuple(e) for e in wb], list(base))
                    self.assertEqual([(ms, [tuple(e) for e in els]) for ms, els in wf], [(ms, list(e)) for ms, e in frames])
                self.assertEqual(len(d["rings"]), len(p.rings))
                for ring, wr in zip(p.rings, d["rings"]):
                    self.assertEqual((wr["name"], wr["tab"], wr["slot"]), (ring.name, ring.tab, ap.SLOTS.index(ring.slot)))
                    for cmd, wc in zip(ring.commands, wr["cmds"]):
                        self.assertEqual(wc["name"], cmd.name)
                        self.assertEqual(wc["flags"], (1 if cmd.kind == "actions" else 0) | (2 if cmd.disabled else 0)
                                         | (4 if cmd.kind == "macro" else 0))
                        if cmd.kind == "keys" and cmd.chord:
                            self.assertEqual((wc["mod"], wc["key"]),
                                             (keymap.display_mods(cmd.chord.mods), cmd.chord.key.label))
                        else:
                            self.assertEqual((wc["mod"], wc["key"]), (0, ""))
                        self.assertEqual(wc["scene"], 0xFF if cmd.scene is None else cmd.scene)
                        if cmd.param is None:
                            self.assertEqual(wc["param"], 0xFF)
                        else:
                            wp = d["params"][wc["param"]]
                            self.assertEqual(wp["label"], cmd.param.label)
                            self.assertEqual(wp["label_neg"], cmd.param.label_neg or "")
                            for got, want in zip(wp["steps"] + [wp["free_step"], wp["min"], wp["max"]],
                                                 cmd.param.steps + (cmd.param.free_step, cmd.param.min, cmd.param.max)):
                                self.assertAlmostEqual(got, want, places=5)
                            self.assertEqual(wp["visual"], ap.PVISUAL.index(cmd.param.visual))
                            self.assertEqual(wp["field"], int(p.param_keys.field))
                            self.assertEqual(wp["flags"], int(cmd.param.deg) | 2 * cmd.param.axes
                                             | 4 * cmd.param.planes | 8 * cmd.param.uniform)

    def test_onshape_keycaps(self):
        d = decode_wire(bundled("onshape").wire())
        model = {c["name"]: (c["mod"], c["key"], c["flags"]) for r in d["rings"] for c in r["cmds"]}
        self.assertEqual(model["EXTRUDE"], (2, "E", 0))                 # SHIFT, the shift arrow
        self.assertEqual(model["CHAMFER"], (0, "", 1))                  # tool search
        self.assertEqual(model["FRONT"], (2, "1", 0))
        self.assertEqual(d["search"], {"mod": 4, "key": "C"})           # Alt+C
        self.assertEqual([s["button"] for s in d["slots"]], [0xFF, 0, 1, 2, 3])
        self.assertEqual([s["label"] for s in d["slots"]], ["ZOOM", "TILT", "ORBIT", "UNDO", "PAN"])
        self.assertEqual(d["legend"], ["TILT", "ORBIT", "WHEEL", "PAN"])

    def test_scenes_are_deduplicated(self):
        p = bundled("plasticity")
        count = sum(1 for r in p.raw_karl["rings"] for c in r["cmds"] if "scene" in c)
        self.assertLessEqual(len(p.scenes), count)
        doc = read_json(PROFILES / "karl" / "figma.json")
        scene = doc["rings"][0]["cmds"][0]["scene"]
        for r in doc["rings"]:
            for c in r["cmds"]:
                c["scene"] = scene
        q = build(doc)
        self.assertEqual(len(q.scenes), 1)
        self.assertEqual({c["scene"] for r in decode_wire(q.wire())["rings"] for c in r["cmds"]}, {0})


def small(**extra):
    doc = {"format": 1, "id": "t", "name": "T", "legend": ["", "", "", ""]}
    doc.update(extra)
    return doc


def scene(n, salt):
    return {"base": [[0, 1, salt % 100, 0, 1, 1, 0, 0, 0]] * n,
            "frames": [{"ms": 100 + salt, "el": [[1, 2, 3, 4, 5, 6, 7, 8, 9]] * n}] * 16}


class LimitWireTests(unittest.TestCase):
    def test_too_big_is_refused(self):
        rings = [{"name": f"R{r}", "tab": "R", "cmds": [{"name": f"C{c}", "scene": scene(48, r * 32 + c)}
                                                       for c in range(4)]} for r in range(2)]
        p = build(small(rings=rings))
        with self.assertRaises(ProfileError) as ctx:
            p.wire()
        self.assertIn("the knob takes 32768", str(ctx.exception))

    def test_too_many_scenes_and_params(self):
        rings = [{"name": f"R{r}", "tab": "R", "cmds": [{"name": f"C{c}", "scene": {"frames": [{"ms": r * 32 + c}]}}
                                                       for c in range(32)]} for r in range(5)]
        with self.assertRaises(ProfileError) as ctx:
            build(small(rings=rings)).wire()
        self.assertIn("scenes", str(ctx.exception))
        rings = [{"name": f"R{r}", "tab": "R", "cmds": [{"name": f"C{c}", "param": {"label": "P", "max": r * 32 + c}}
                                                       for c in range(32)]} for r in range(2)]
        with self.assertRaises(ProfileError) as ctx:
            build(small(rings=rings)).wire()
        self.assertIn("params", str(ctx.exception))

    def test_params_deduplicated_and_start_clamped(self):
        prm = {"label": "P", "start": 50, "min": 0, "max": 10, "steps": [0.1, 1, 10]}
        rings = [{"name": "R", "tab": "R", "cmds": [{"name": f"C{c}", "param": dict(prm)} for c in range(32)]}] * 2
        d = decode_wire(build(small(rings=rings)).wire())
        self.assertEqual(len(d["params"]), 1)
        self.assertEqual(d["params"][0]["start"], 10.0)

    def test_label_visual_zeroes_the_shape(self):
        d = decode_wire(build(small(visual="label", shape="octa", shape_style="grips")).wire())
        self.assertEqual((d["visual"], d["shape"], d["shape_style"]), (0, 0, 1))
        self.assertEqual(d["features"], ap.F_LABEL_VISUAL | ap.F_SHAPE_EXT)
        d = decode_wire(build(small(visual="shape", shape="octa")).wire())
        self.assertEqual((d["visual"], d["shape"], d["features"]), (1, 2, ap.F_SHAPE | ap.F_SHAPE_EXT))
        d = decode_wire(build(small()).wire())
        self.assertEqual((d["icon24"], d["icon48"], d["features"]), (None, None, ap.F_LABEL_VISUAL))

    def test_wire_floats_are_bounded(self):
        prm = {"label": "P", "steps": [1e7, 1, 1], "max": 1e7, "min": -1e7}
        build(small(rings=[{"name": "R", "tab": "R", "cmds": [{"name": "C", "param": prm}]}])).wire()


class DecoderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.blob = bundled("plasticity").wire()

    def code(self, blob, **kw):
        with self.assertRaises(WireError) as ctx:
            decode_wire(blob, **kw)
        return ctx.exception.code

    def test_header_codes(self):
        b = self.blob
        self.assertEqual(self.code(b[:10]), 1)
        self.assertEqual(self.code(b"XDAP" + b[4:]), 2)
        self.assertEqual(self.code(b[:4] + b"\x02" + b[5:]), 3)
        self.assertEqual(self.code(b + b"\0"), 4)
        self.assertEqual(self.code(b[:-1] + bytes([b[-1] ^ 1])), 5)
        self.assertEqual(self.code(b, features_allowed=ap.F_SHAPE), 6)
        lie = bytearray(b)
        struct.pack_into("<I", lie, 8, len(b) + 4)
        self.assertEqual(self.code(recrc(bytes(lie) + b"\0\0\0\0")), 12)   # total covers trailing bytes
        unknown = bytearray(b)
        struct.pack_into("<I", unknown, 12, 32)
        self.assertEqual(self.code(recrc(bytes(unknown))), 6)

    def test_body_codes(self):
        b = bytearray(self.blob)
        b[16] = 12                                                          # id length past 11
        self.assertEqual(self.code(recrc(bytes(b))), 7)
        b = bytearray(self.blob)
        b[17] = ord("A")                                                    # id syntax
        self.assertEqual(self.code(recrc(bytes(b))), 11)

    def test_mutation_fuzz(self):
        """Truncation, bit flips and byte stores (CRC fixed up so the body is reached): a WireError
        with a known code, or a clean decode; nothing else."""
        rng = random.Random(20261003)
        codes = set()
        blobs = [bundled(pid).wire() for pid in ("onshape", "figma", "plasticity")]
        for i in range(3000):
            b = bytearray(blobs[i % 3])
            how = i % 3
            if how == 0:
                cut = rng.randrange(20, len(b) - 4)
                b = b[:cut] + b[-4:]
                struct.pack_into("<I", b, 8, len(b))
            elif how == 1:
                for _ in range(rng.randint(1, 4)):
                    pos = rng.randrange(16, len(b) - 4)
                    b[pos] ^= 1 << rng.randrange(8)
            else:
                b[rng.randrange(16, len(b) - 4)] = rng.choice((0, 0x7F, 0x80, 0xFF, 48, 33))
            try:
                decode_wire(recrc(bytes(b)))
            except WireError as exc:
                self.assertIn(exc.code, (1, 4, 6, 7, 8, 9, 10, 11, 12, 14))
                codes.add(exc.code)
        self.assertTrue({1, 7, 8, 10} <= codes, codes)


if __name__ == "__main__":
    unittest.main()
