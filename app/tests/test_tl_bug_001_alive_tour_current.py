"""TL-BUG-001: the alive tour checks the knob against the current release (tooling CURRENT), not a pinned
1.0.0-cc5.4, so it starts on the shipped release and names it in its evidence. Fake knob, no port."""
import importlib.util
import json
import sys
import unittest
from pathlib import Path

WORK = Path(__file__).resolve().parents[2] / "tools"
if str(WORK) not in sys.path:
    sys.path.insert(0, str(WORK))
import nanod_cc5_tooling as t  # noqa: E402


def load_tour():
    spec = importlib.util.spec_from_file_location("alive_tour_tl_bug_001", WORK / "nanod_alive_tour.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeKnob:
    def __init__(self, caps):
        self.caps, self.released, self.errors = caps, [], []

    def pump(self, seconds):
        pass

    def release(self):
        self.released.append(True)

    def request(self, message, accept, what=None, **kwargs):
        reply = {"capabilities": self.caps}
        assert accept(reply)
        return reply


def caps(presentation, alive=True):
    out = {"presentation": presentation}
    if alive:
        out[t.presentation().ALIVE_CAPABILITY] = t.alive_capability()
    return out


class AliveTourCurrentRelease(unittest.TestCase):
    def setUp(self):
        self.tour = load_tour()

    def test_open_session_accepts_current_release(self):
        got = self.tour.open_session(FakeKnob(caps(t.CURRENT.presentation)))
        self.assertEqual(got["presentation"], t.CURRENT.presentation)

    def test_open_session_refuses_another_presentation_naming_current(self):
        older = t.CURRENT.presentation - 1
        with self.assertRaises(RuntimeError) as caught:
            self.tour.open_session(FakeKnob(caps(older, alive=False)))
        self.assertIn(f"does not run {t.CURRENT.version}", str(caught.exception))
        self.assertIn("no alive capability", str(caught.exception))

    def test_record_and_evidence_name_the_current_release(self):
        knob = FakeKnob(caps(t.CURRENT.presentation))
        session = self.tour.Tour(knob, knob.caps, lambda frame: [], out=lambda *a: None)
        self.assertEqual(session.record()["firmware"], t.CURRENT.version)
        source = (WORK / "nanod_alive_tour.py").read_text(encoding="utf-8")
        self.assertNotIn('PROFILES["cc5.4"]', source)
        self.assertNotIn("PROFILES['cc5.4']", source)
        self.assertIn("t.CURRENT.prefix", source)

    def test_current_version_matches_the_release_manifests(self):
        found = [b for b in t.CURRENT.pipeline_binaries() if t.CURRENT.binary_profile(b).manifest.is_file()]
        if not found:
            self.skipTest("no manifest of the current release in this tree")
        for b in found:
            manifest = json.loads(t.CURRENT.binary_profile(b).manifest.read_text(encoding="utf-8"))
            self.assertEqual(manifest.get("firmwareVersion"), t.CURRENT.version, b)


if __name__ == "__main__":
    unittest.main()
