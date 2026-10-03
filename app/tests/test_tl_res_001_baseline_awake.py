"""TL-RES-001: the knob baseline records the sleep state, flags samples that are not awake and gates step 1
on an awake knob. No port, no knob: the preflight runs against a fake tooling module and a fake knob."""
import importlib.util
import io
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path

WORK = Path(__file__).resolve().parents[2] / "tools"
SPEC = importlib.util.spec_from_file_location("knob_baseline_tl_res_001", WORK / "audit" / "tools" / "knob_baseline.py")
kb = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(kb)


def diag(state, idle=1000, **extra):
    return {"sleepState": state, "idleMs": idle, "core0IdlePct": 50, "focLoopHz": 9000, "bootCount": 3,
            "build": "F", "coredump": {"blank": True}, **extra}


class FakeKnob:
    def __init__(self, states):
        self.states, self.pumped, self.closed = list(states), 0.0, False

    def pump(self, seconds):
        self.pumped += seconds

    def diag(self):
        return diag(self.states.pop(0) if len(self.states) > 1 else self.states[0])

    def request(self, *a, **k):
        return {"capabilities": {}}

    def close(self):
        self.closed = True


def fake_tooling(knob):
    current = types.SimpleNamespace(version=kb.EXPECTED_VERSION, expected_capabilities=lambda: {})
    return types.SimpleNamespace(CURRENT=current, utc_stamp=lambda: "stamp", running_companions=lambda: [],
                                 list_ports=lambda: [types.SimpleNamespace(device="p")], is_app_port=lambda p: True,
                                 RawKnob=lambda *a, **k: knob, lcd_binary=lambda d: "F")


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        self.now += 1.0
        return self.now


class ReportFlagsAsleepSamples(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._baseline, kb.BASELINE = kb.BASELINE, Path(self.tmp.name)
        self.addCleanup(setattr, kb, "BASELINE", self._baseline)

    def test_sleep_state_and_idle_are_recorded(self):
        self.assertIn("sleepState", kb.PREFLIGHT_FIELDS)
        self.assertIn("idleMs", kb.PREFLIGHT_FIELDS)
        self.assertIn("idleMs", kb.STAT_FIELDS)
        self.assertFalse(any("never reached" in n for n in kb.NOT_MEASURED))

    def test_report_flags_asleep_samples(self):
        rows = [{"diag": diag("asleep", 54866317)}, {"diag": diag("asleep", 54867317)}]
        problems = kb.sleep_problems({"native-rest": rows, "claimed-rest": [{"diag": diag("awake")}]})
        self.assertEqual(len(problems), 1)
        self.assertIn("native-rest", problems[0])
        self.assertIn("asleep x2", problems[0])
        stats = kb.state_stats(rows)
        self.assertEqual(stats["sleepState"], {"values": {"asleep": 2}})
        report = {"startedUtc": "s", "passes": 1, "soundStep": False, "notes": {}, "skipped": [],
                  "problems": [f"pass 1 1-native-rest: {p}" for p in problems],
                  "knobVolume": {"value": None, "source": "not requested"}}
        kb.write_md(report, {"sleepState": "asleep", "idleMs": 54866317}, {(1, "native-rest"): stats})
        md = (kb.BASELINE / "knob-baseline.md").read_text(encoding="utf-8")
        cpu = md.split("## CPU, FOC and LCD")[1].split("##")[0]
        self.assertIn("sleepState", cpu.splitlines()[2])
        self.assertIn("| 1 | native-rest | asleep |", cpu)
        self.assertIn("not awake", md.split("## Problems")[1])

    def test_awake_samples_are_not_problems(self):
        self.assertEqual(kb.sleep_problems({"animating": [{"diag": diag("awake")}] * 3}), [])

    def test_asleep_preflight_waits_for_awake_before_step_1(self):
        knob = FakeKnob(["asleep", "asleep", "dim", "awake"])
        said = []
        clock = Clock()
        original = kb.wait_awake
        kb.wait_awake = lambda k, d: original(k, d, clock=clock, say=lambda *a, **k: said.append(a[0]))
        self.addCleanup(setattr, kb, "wait_awake", original)
        with redirect_stdout(io.StringIO()):
            facts, got = kb.preflight(fake_tooling(knob))
        self.assertIs(got, knob)
        self.assertEqual(facts["sleepState"], "asleep")          # what the knob reported first is kept
        self.assertEqual(facts["sleepStateAtStart"], "awake")
        self.assertTrue(facts["wokenByGate"])
        self.assertEqual(len(said), 1)
        self.assertIn("wake", said[0])

    def test_asleep_preflight_refuses_when_it_never_wakes(self):
        knob = FakeKnob(["asleep"])
        clock = Clock()
        original = kb.wait_awake
        kb.wait_awake = lambda k, d: original(k, d, timeout=5, clock=clock, say=lambda *a, **k: None)
        self.addCleanup(setattr, kb, "wait_awake", original)
        with self.assertRaises(kb.Refused) as ctx:
            kb.preflight(fake_tooling(knob))
        self.assertIn("did not wake", str(ctx.exception))
        self.assertTrue(knob.closed)

    def test_awake_preflight_does_not_wait(self):
        knob = FakeKnob(["awake"])
        with redirect_stdout(io.StringIO()):
            facts, _ = kb.preflight(fake_tooling(knob))
        self.assertFalse(facts["wokenByGate"])
        self.assertEqual(knob.pumped, 0.3)


if __name__ == "__main__":
    unittest.main()
