"""K-errata: the phase-2b errata read the same in every contract (the K-errata review, KE-R1…KE-R6).

K1 = firmware/PRESENTATION_V5.md, K3 = CONTROL_CENTER_V5.md, K4 = DESKTOP_STAGE.md,
VOC = firmware/V5_VOCABULARY.md, CAROUSEL = CAROUSEL.md. Each class pins one review fix:

- GroupChangedToneTests (KE-R1; KE-R2, applied to VOC 2026-09-26): lead ruling R-j gives `Speaker group changed`
  the `error` tone. No live line of K1 or K3 still names the `meta` tone for it (the errata history rows and
  K3's handoff table aside), K3 §8's Start row names `error`, E-j and the [P2b] header list §8, and the
  controller sets `error`.
- TwinFadeBoundTests (KE-R5): K1 15.3's `twin_fade` row gives R-b's ≤ 28 only outside R-g's overlap class
  (≤ 36), as 8.5.3 does, and the two bounds are the ones `cc54_report.py` enforces.
- PickerDeviationTests (KE-R3; KE-R4, applied to CAROUSEL 2026-09-26): K4 21.4's WP7b-D6 names the built root fix
  (K3 C5-78) and WP7b-D7 limits "no fly shadow" to the step-1 CPU chrome; §2.3 and §9.5 agree (E-c, E-h);
  the runtime passes `reason` and the GPU chrome has the fly's shadow.
- SummonFrameErratumTests (KE-R6): K4's H9 row and §11.4's Test bullet state R-i's summon rule, E-i names
  §11.4, the header names the phase-2b errata, and every test the new rows cite exists.

A fix another package owns is listed in PENDING_OWNER: its case skips with the handoff while the text still
differs and fails once the owner has applied it, so the entry is removed with the fix (the convention of
`test_kdocs_contract.PENDING_WP5`).

Headless: reads text files and imports the controller module only; no device, port, network, window or Tk.
"""
from __future__ import annotations

import ast
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

WORK = ROOT.parent / "tools"
K1 = WORK.parent / "firmware" / "PRESENTATION_V5.md"
K3 = ROOT / "CONTROL_CENTER_V5.md"
K4 = ROOT / "DESKTOP_STAGE.md"
VOC = WORK.parent / "firmware" / "V5_VOCABULARY.md"
CAROUSEL = ROOT / "CAROUSEL.md"
CC54_REPORT = WORK.parent / "harness" / "cc54_report.py"

# KE-R2 (VOC) and KE-R4 (CAROUSEL) were applied on 2026-09-26 (the lead's phase-3b decision 5, from the
# checked owner patches), so nothing is pending now.
PENDING_OWNER = {}

META_TONE = re.compile(r"`meta`\s+tone")


def read(path):
    return path.read_text(encoding="utf-8")


def section(text, start, end):
    """The text from the line matching `start` up to the next line matching `end` ("" when missing)."""
    m = re.search(start, text, re.M)
    if not m:
        return ""
    rest = text[m.end():]
    e = re.search(end, rest, re.M)
    return text[m.start(): m.end() + (e.start() if e else len(rest))]


def table_row(text, first_cell):
    rows = [line for line in text.splitlines() if line.startswith(f"| {first_cell} |")]
    return rows[0] if len(rows) == 1 else None


def cells(row):
    return [c.strip() for c in re.split(r"(?<!\\)\|", row.strip().strip("|"))]


def unstruck(text):
    return re.sub(r"~~.*?~~", "", text, flags=re.S)


def history_row(line):
    """An errata or ruling-history row (E-x): its "Was" column quotes the superseded text on purpose."""
    return line.startswith("| E-")


def defined_names(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {n.name for n in ast.walk(tree) if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))}


class _Pending:
    def check_owner_fix(self, key, problems):
        if key in PENDING_OWNER:
            if problems:
                self.skipTest(f"{key} pending, {PENDING_OWNER[key]}")
            self.fail(f"{key} is applied now: remove it from PENDING_OWNER in {Path(__file__).name}")
        self.assertEqual(problems, [])


# ---------------------------------------------------------------------------------- KE-R1, KE-R2
@unittest.skipUnless(K1.is_file() and K3.is_file(), "the contracts are not next to the companion")
class GroupChangedToneTests(_Pending, unittest.TestCase):
    """Lead ruling R-j (KD-4): `Speaker group changed` is failure copy in the `error` tone wherever it shows."""

    def test_no_live_k1_or_k3_line_gives_group_changed_the_meta_tone(self):
        k3 = read(K3)
        handoffs = section(k3, r"^## 18\. ", r"^## 19\. ")       # K3's handoff table reports VOC's state
        for path, text, skip in ((K1, read(K1), ""), (K3, k3, handoffs)):
            bad = []
            for n, line in enumerate(text.splitlines(), 1):
                if "group_changed" not in line and "Speaker group changed" not in line:
                    continue
                if history_row(line) or (skip and line in skip):
                    continue
                if META_TONE.search(unstruck(line)):
                    bad.append(n)
            self.assertEqual(bad, [], f"{path.name}: lines naming the `meta` tone for the group copy")

    def test_k3_section_8_start_row_uses_the_error_tone(self):
        sec = section(read(K3), r"^## 8\. ", r"^## 9\. ")
        row = table_row(sec, "**Start** (Recent 4, Explorer 4, Up next 4)")
        self.assertIsNotNone(row, "K3 §8 has one Start row")
        failure = unstruck(cells(row)[-1])
        clause = failure[failure.index("`group_changed`"):]
        clause = clause[:clause.index("§9.10")]
        self.assertIn("`error` tone", clause)
        self.assertIn("R-j", clause)
        self.assertNotRegex(clause, META_TONE)

    def test_k3_errata_list_section_8(self):
        k3 = read(K3)
        header = next(p for p in k3.split("\n\n") if p.startswith("**Phase-2b errata"))
        self.assertIn("wherever it shows (§2.4, §7, §8, §9.10, C5-76)", header)
        ej = table_row(section(k3, r"^## 19\. ", r"^## 20\. "), "E-j")
        self.assertIsNotNone(ej)
        self.assertIn("§8", cells(ej)[-1])

    def test_the_controller_sets_the_error_tone(self):
        from control_center.controller import Controller
        calls = []

        class Stub:
            def _set_transient(self, copy_id, **kw):
                calls.append((copy_id, kw.get("tone")))

        Controller._group_changed_copy(Stub())
        self.assertEqual(calls, [("knob.status.group_changed", "error")])

    @unittest.skipUnless(VOC.is_file(), "the vocabulary is not next to the companion")
    def test_voc_rows_use_the_error_tone(self):
        voc = read(VOC)
        problems = []
        for sec, first in (((r"^### 8\.5 ", r"^## 9\. "), "`group_changed`"),
                           ((r"^## 10\. ", r"^## 11\. "), "`group_changed_ms`")):
            row = table_row(section(voc, *sec), first)
            if row is None:
                problems.append(f"no single {first} row")
                continue
            live = unstruck(row)
            if META_TONE.search(live) or "`error`" not in live:
                problems.append(f"{first} row: not the `error` tone")
        if "R-j" not in unstruck(voc):
            problems.append("no R-j entry")
        self.check_owner_fix("KE-R2", problems)


# ---------------------------------------------------------------------------------- KE-R5
@unittest.skipUnless(K1.is_file(), "the contracts are not next to the companion")
class TwinFadeBoundTests(unittest.TestCase):
    """Lead rulings R-b and R-g: ≤ 28 inside the label ink boxes, ≤ 36 in the volume-reveal overlap class."""

    def row(self):
        row = table_row(section(read(K1), r"^### 15\.3 ", r"^### 15\.4 "), "`twin_fade`")
        self.assertIsNotNone(row, "K1 15.3 has one `twin_fade` row")
        return unstruck(row)

    def test_the_15_3_row_scopes_the_cover_bound(self):
        row = self.row()
        self.assertNotIn("whatever lies under the ink", row)
        self.assertIn("**[erratum R-g]** over the cover (every in-box pixel outside the overlap class below)", row)
        self.assertIn("≤ 28 levels per 8-bit channel", row)
        self.assertIn("≤ 36 levels per 8-bit channel", row)

    def test_no_live_k1_text_claims_one_bound_whatever_lies_under_the_ink(self):
        bad = [n for n, line in enumerate(read(K1).splitlines(), 1)
               if not history_row(line) and "whatever lies under the ink" in unstruck(line)]
        self.assertEqual(bad, [])

    @unittest.skipUnless(CC54_REPORT.is_file(), "the LCD harness is not next to the companion")
    def test_the_bounds_are_the_harness_constants(self):
        src = read(CC54_REPORT)
        limits = {name: int(re.search(rf"^{name} = (\d+)\b", src, re.M).group(1))
                  for name in ("TWIN_FADE_LIMIT", "TWIN_FADE_OVERLAP_LIMIT")}
        self.assertEqual(limits, {"TWIN_FADE_LIMIT": 28, "TWIN_FADE_OVERLAP_LIMIT": 36})
        row = self.row()
        for value in limits.values():
            self.assertIn(f"≤ {value} levels", row)


# ---------------------------------------------------------------------------------- KE-R3, KE-R4
@unittest.skipUnless(K4.is_file(), "the contracts are not next to the companion")
class PickerDeviationTests(_Pending, unittest.TestCase):
    """K3 C5-78 ([P3]) carries the close `reason`; R-h's step 3 draws the fly's shadow (K4 §9.10)."""

    def errata(self):
        return section(read(K4), r"^### 21\.4 ", r"^## 22\. ")

    def test_wp7b_d6_names_the_built_root_fix(self):
        row = table_row(self.errata(), "**WP7b-D6**")
        self.assertIsNotNone(row)
        acceptance = unstruck(cells(row)[-1])
        for stale in ("stopgap", "open work"):
            self.assertNotIn(stale, acceptance)
        self.assertIn("fallback for a payload without `reason`", acceptance)
        self.assertIn("C5-78", acceptance)

    def test_wp7b_d7_holds_for_the_cpu_chrome_only(self):
        row = table_row(self.errata(), "**WP7b-D7**")
        self.assertIsNotNone(row)
        acceptance = unstruck(cells(row)[-1])
        self.assertNotEqual(acceptance.strip(), "accepted, as S5-4")
        self.assertIn("step-1 (CPU) fallback chrome", acceptance)
        self.assertIn("§9.10", acceptance)

    def test_the_body_agrees(self):
        k4 = read(K4)
        payloads = section(k4, r"^### 2\.3 ", r"^### 2\.4 |^## 3\. ")
        row = next(line for line in payloads.splitlines() if "`windows_cancel` adds" in line)
        self.assertRegex(unstruck(row), r"`windows_cancel` adds `origin`, `home`, `complete`[^;]*`reason`")
        fly = table_row(section(k4, r"^### 9\.5 ", r"^### 9\.6 "), "0–460")
        self.assertIsNotNone(fly)
        self.assertNotIn("No fly shadow in v7", unstruck(fly))
        self.assertIn("step 3 draws the fly's shadow (§9.10", unstruck(fly))
        live = [line for line in k4.splitlines() if not history_row(line)]
        self.assertFalse([line for line in live if "stays open work for K3" in unstruck(line)])
        for key in ("E-c", "E-h"):
            self.assertIsNotNone(table_row(self.errata(), key), key)

    def test_the_code_does_what_the_rows_say(self):
        runtime = read(ROOT / "control_center" / "runtime.py")
        branch = runtime[runtime.index('kind == "windows_cancel"'):]
        branch = branch[:branch.index("elif kind ==")]
        self.assertIn('reason=effect.get("reason")', branch)
        self.assertIn('"picker.fly.shadow"', read(ROOT / "control_center" / "stage" / "picker_chrome.py"))

    @unittest.skipUnless(CAROUSEL.is_file(), "CAROUSEL.md is not next to the companion")
    def test_carousel_12_3_records_the_acceptance(self):
        sec = section(read(CAROUSEL), r"^### 12\.3 ", r"^### 12\.4 ")
        problems = []
        if "R-l" not in sec:
            problems.append("§12.3 records no R-l acceptance")
        d6 = next((line for line in sec.splitlines() if line.startswith("- **WP7b-D6")), "")
        live = unstruck(d6)
        if "carries no `reason`" in live or "C5-78" not in live:
            problems.append("WP7b-D6 predates C5-78")
        d7 = unstruck(next((line for line in sec.splitlines() if line.startswith("- **WP7b-D7")), ""))
        if not re.search(r"CPU|step[- ]1", d7):
            problems.append("WP7b-D7 is not limited to the step-1 CPU chrome")
        self.check_owner_fix("KE-R4", problems)


# ---------------------------------------------------------------------------------- KE-R6
@unittest.skipUnless(K4.is_file(), "the contracts are not next to the companion")
class SummonFrameErratumTests(unittest.TestCase):
    """Lead ruling R-i: after a summon by a message the first visible frame is M27's; the twin from +300 ms."""

    RULE = ("[erratum R-i]", "M27 reference", "+300 ms", "E-i")

    def test_h9_and_the_11_4_test_bullet_state_the_summon_rule(self):
        k4 = read(K4)
        h9 = table_row(section(k4, r"^### 6\.6 ", r"^## 7\. "), "H9")
        self.assertIsNotNone(h9)
        bullet = next(line for line in section(k4, r"^### 11\.4 ", r"^### 11\.5 ").splitlines()
                      if line.startswith("- **Test**"))
        for text in (h9, bullet):
            for part in self.RULE:
                self.assertIn(part, unstruck(text))

    def test_the_header_names_the_phase_2b_errata(self):
        k4 = read(K4)
        header = k4[:k4.index("\n## ")]
        para = next((p for p in header.split("\n\n") if p.startswith("**[errata] Phase-2b gate")), "")
        for part in ("2026-09-26", "21.4", "R-i", "R-l", "R-h", "E-i", "E-t", "E-c", "E-h"):
            self.assertIn(part, para)

    def test_e_i_names_11_4_and_the_cited_tests_exist(self):
        errata = section(read(K4), r"^### 21\.4 ", r"^## 22\. ")
        ei = table_row(errata, "E-i")
        self.assertIsNotNone(ei)
        self.assertIn("§11.4", cells(ei)[-1])
        for key in ("E-i", "E-c", "E-h"):
            where = cells(table_row(errata, key))[-1]
            files = re.findall(r"`tests/(\w+\.py)`", where)
            self.assertTrue(files, key)
            after = where[where.index("`tests/"):]
            names = {t for t in re.findall(r"`([^`]+)`", after) if re.fullmatch(r"[A-Za-z_]\w*", t)}
            known = set().union(*(defined_names(ROOT / "tests" / f) for f in files))
            self.assertEqual(names - known, set(), key)


if __name__ == "__main__":
    unittest.main()
