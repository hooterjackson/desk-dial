"""Static checks of the GitHub Action that imports Karl's app profiles (plan §5c).

The Action may only propose changes: one pull request from the bot branch, for the owner to review.
These checks keep it that way (no merge, no release, no push to main, every action pinned to a commit,
the least permissions), and keep its commands in step with the importer and the index tool.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT.parent / ".github" / "workflows" / "karl-profiles.yml"


def _text():
    return WORKFLOW.read_text(encoding="utf-8")


def _code_lines():
    """The workflow without comments, so a word in a comment can't satisfy or trip a check."""
    return [line.split(" #", 1)[0] for line in _text().splitlines() if not line.lstrip().startswith("#")]


class KarlProfilesActionTests(unittest.TestCase):
    def test_every_action_is_pinned_to_a_full_commit(self):
        uses = [line.split("uses:", 1)[1].strip() for line in _code_lines() if "uses:" in line]
        self.assertEqual(len(uses), 5)              # checkout and setup-python in each job, create-pull-request
        for ref in uses:
            self.assertRegex(ref, r"^[\w.-]+/[\w.-]+@[0-9a-f]{40}$", ref)

    def test_pinned_versions_are_named_in_comments(self):
        for line in _text().splitlines():
            if "uses:" in line:
                self.assertRegex(line, r"# v\d+\.\d+\.\d+$", line)

    @staticmethod
    def _jobs():
        """{job name: its text} (the jobs are two-space keys under `jobs:`)."""
        body = _text().split("\njobs:\n", 1)[1]
        parts = re.split(r"^  ([\w-]+):\n", body, flags=re.M)
        return dict(zip(parts[1::2], parts[2::2]))

    @staticmethod
    def _granted(block):
        match = re.search(r"^\s*permissions:\n((?:\s+[\w-]+: \w+\n)+)", block, re.M)
        return dict(line.strip().split(": ") for line in match.group(1).splitlines()) if match else None

    def test_permissions_are_only_contents_and_pull_requests(self):
        top = _text().split("\njobs:\n", 1)[0] + "\n"
        self.assertEqual(self._granted(top), {"contents": "read"}, "read-only by default")
        jobs = self._jobs()
        self.assertEqual(set(jobs), {"build", "propose"})
        self.assertEqual(self._granted(jobs["build"]), {"contents": "read"})
        self.assertEqual(self._granted(jobs["propose"]), {"contents": "write", "pull-requests": "write"})

    def test_karls_code_never_runs_with_a_write_token(self):
        """S3 review DD-4: the importer builds and runs Karl's C exporter. In a job that also held contents: write,
        that code could rewrite the files of a later action (create-pull-request) and push with its token. It runs
        in the read-only job; the job with the token only unpacks the JSON (names checked) and runs our tools."""
        jobs = self._jobs()
        self.assertIn("import_karl.py", jobs["build"])
        self.assertNotIn("create-pull-request", jobs["build"])
        propose = "\n".join(line.split(" #", 1)[0] for line in jobs["propose"].splitlines()
                            if not line.lstrip().startswith("#"))
        for word in ("import_karl", "gcc", "--compiler", "profile_json_test"):
            self.assertNotIn(word, propose, word)
        self.assertIn("needs: build", propose)
        self.assertIn(r"[a-z0-9_-]{1,11}", propose, "unpacked file names are checked")

    def test_it_never_merges_releases_or_pushes_main(self):
        code = "\n".join(_code_lines()).lower()
        for word in ("auto-merge", "automerge", "gh pr merge", "merge-method", "git push", "release",
                     "gh release", "secrets."):
            self.assertNotIn(word, code, word)
        self.assertIn("branch: bot/karl-profiles", code)
        self.assertNotRegex(code, r"branch:\s*(main|master)\b")

    def test_checkout_does_not_keep_the_token(self):
        self.assertIn("persist-credentials: false", _text())

    def test_triggers_are_schedule_and_manual_only(self):
        on = re.search(r"^on:\n((?:  .*\n|\n)+?)^\S", _text(), re.M).group(1)
        triggers = {line.strip().rstrip(":") for line in on.splitlines() if re.match(r"^  \w", line)}
        self.assertEqual(triggers, {"schedule", "workflow_dispatch"})

    def test_karl_ref_reaches_the_shell_only_through_the_environment(self):
        run_blocks = re.findall(r"run: \|\n((?:\s{10}.+\n)+)", _text())
        self.assertTrue(run_blocks)
        for block in run_blocks:
            self.assertNotIn("${{", block, "inputs must not be expanded into shell code")
        self.assertIn("KARL_REF: ${{ github.event.inputs.ref }}", _text())

    def test_only_profile_data_is_committed(self):
        block = re.search(r"add-paths: \|\n((?:\s{12}.+\n)+)", _text()).group(1)
        paths = [line.strip() for line in block.splitlines()]
        self.assertEqual(paths, ["${{ env.APP }}/profiles/karl/*.json", "${{ env.APP }}/profiles/index.json"])

    def test_the_scripts_it_runs_exist_and_take_its_options(self):
        tools = ROOT / "tools" / "profiles"
        importer = (tools / "import_karl.py").read_text(encoding="utf-8")
        for option in ("--compiler", "--out", "--summary", "--ref"):
            self.assertIn(f'"{option}"', importer, option)
        self.assertIn('"gcc"', importer)
        self.assertTrue((tools / "validate.py").is_file())
        self.assertTrue((tools / "make_index.py").is_file(), "lane DD-C's index tool")

    def test_the_header_credits_karl_and_says_it_never_merges(self):
        head = _text().split("name:", 1)[0]
        self.assertIn("Karl Malota", head)
        self.assertIn("never merges", head)


    def test_the_updater_fetches_the_folder_the_action_writes(self):
        """Desk Dial's optional fetch must read exactly where this Action commits: <APP>/profiles/ on main."""
        import sys
        sys.path.insert(0, str(ROOT))
        from control_center import profile_updates
        app = re.search(r"^  APP: (\S+)$", _text(), re.M).group(1)
        self.assertEqual(profile_updates.INDEX_URL,
                         f"https://raw.githubusercontent.com/hooterjackson/desk-dial/main/{app}/profiles/index.json")

if __name__ == "__main__":
    unittest.main()
