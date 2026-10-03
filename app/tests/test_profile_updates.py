"""Plan section 5b (S1 DD-C): the optional profile fetch, against a fake urllib opener. Nothing touches the
network. Covered: the one URL, no query, the User-Agent, the size caps, a hash mismatch, an oversize or
truncated download, an invalid profile, desk_dial_min too new, offline, a write that fails half way (the
previous good files stay), the user folder never written, the daily policy and the worker thread."""
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from control_center import app_profiles, profile_updates as pu  # noqa: E402

PROFILES = REPO / "profiles"


class Response:
    def __init__(self, data, status=200, length=None):
        self._data, self.status = io.BytesIO(data), status
        self.headers = {} if length is None else {"Content-Length": str(length)}

    def read(self, n=-1):
        return self._data.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    """url -> bytes, a Response, or an exception instance. Records every request."""

    def __init__(self, files):
        self.files, self.requests = dict(files), []

    def open(self, request, timeout=None):
        self.requests.append((request.full_url, dict(request.header_items()), request.get_method(), timeout))
        value = self.files.get(request.full_url)
        if value is None:
            raise urllib.error.HTTPError(request.full_url, 404, "not found", {}, None)
        if isinstance(value, BaseException):
            raise value
        return value if isinstance(value, Response) else Response(value)


def entry(pid, karl, overlay=None, minimum="2.0.0"):
    out = {"id": pid, "file": f"karl/{pid}.json", "sha256": hashlib.sha256(karl).hexdigest(), "bytes": len(karl),
           "desk_dial_min": minimum}
    if overlay is not None:
        out["overlay"] = {"file": f"{pid}.windows.json", "sha256": hashlib.sha256(overlay).hexdigest(),
                          "bytes": len(overlay)}
    return out


def index(*entries):
    return json.dumps({"format": 1, "profiles": list(entries)}).encode("ascii")


def figma_variant(name="Figma Next"):
    doc = json.loads((PROFILES / "karl" / "figma.json").read_text(encoding="ascii"))
    doc["name"] = name
    return json.dumps(doc).encode("ascii")


class Case(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.updates, self.user = root / "profiles" / "updates", root / "profiles" / "user"
        self.user.mkdir(parents=True)
        (self.user / "keep.txt").write_text("mine")
        self.karl = figma_variant()
        self.overlay = (PROFILES / "figma.windows.json").read_bytes()

    def check(self, files, version="2.0.0"):
        self.opener = FakeOpener(files)
        return pu.run_check(self.updates, PROFILES, version, self.opener, self.user, names={"figma": "Figma"})

    def good_files(self, karl=None, overlay=None, **kw):
        karl = self.karl if karl is None else karl
        overlay = self.overlay if overlay is None else overlay
        return {pu.INDEX_URL: index(entry("figma", karl, overlay, **kw)),
                pu.BASE_URL + "karl/figma.json": karl, pu.BASE_URL + "figma.windows.json": overlay}

    def assert_user_untouched(self):
        self.assertEqual(sorted(p.name for p in self.user.iterdir()), ["keep.txt"])

    def updated_files(self):
        return sorted(p.name for p in self.updates.iterdir()) if self.updates.is_dir() else []


class RequestTests(Case):
    def test_only_the_index_url_and_profile_files_with_a_plain_user_agent(self):
        self.assertEqual(pu.INDEX_URL, "https://raw.githubusercontent.com/hooterjackson/desk-dial/main/app/profiles/index.json")
        result = self.check(self.good_files(), version="2.1.0")
        self.assertTrue(result.ok)
        urls = [r[0] for r in self.opener.requests]
        self.assertEqual(urls, [pu.INDEX_URL, pu.BASE_URL + "karl/figma.json"],
                         "the bundled sidecar is unchanged, so only the Karl file is fetched")
        for url, headers, method, timeout in self.opener.requests:
            self.assertTrue(url.startswith("https://raw.githubusercontent.com/hooterjackson/desk-dial/main/app/profiles/"))
            self.assertNotIn("?", url)
            self.assertEqual(method, "GET")
            self.assertEqual(headers, {"User-agent": "DeskDial/2.1.0"}, "nothing but the User-Agent")
            self.assertEqual(timeout, pu.TIMEOUT_S)

    def test_the_default_opener_verifies_certificates_and_refuses_redirects(self):
        opener = pu.default_opener()
        https = [h for h in opener.handlers if h.__class__.__name__ == "HTTPSHandler"]
        self.assertEqual(len(https), 1)
        context = https[0]._context
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, __import__("ssl").CERT_REQUIRED)
        self.assertTrue(any(isinstance(h, pu._NoRedirect) for h in opener.handlers))

    def test_a_non_https_or_query_url_is_never_fetched(self):
        opener = FakeOpener({})
        for url in ("http://raw.githubusercontent.com/x", "https://x/a?b=1"):
            with self.subTest(url=url), self.assertRaises(pu.UpdateError):
                pu.fetch(url, 10, opener, "2.0.0")
        self.assertEqual(opener.requests, [])

    def test_a_strange_version_never_reaches_the_header(self):
        self.assertEqual(pu.user_agent("2.0.0"), "DeskDial/2.0.0")
        self.assertEqual(pu.user_agent(None), "DeskDial/0")
        self.assertEqual(pu.user_agent("2.0\r\nX: y"), "DeskDial/0")


class CheckTests(Case):
    def test_a_changed_profile_is_switched_in_and_loads(self):
        result = self.check(self.good_files())
        self.assertEqual((result.ok, result.updated, result.kept), (True, ["Figma Next"], []))
        self.assertEqual(result.text, "Updated: Figma Next.")
        self.assertEqual((self.updates / "figma.json").read_bytes(), self.karl)
        self.assertEqual(self.updated_files(), ["figma.json"], "no staging or temporary file stays")
        library = app_profiles.Library(PROFILES, self.updates, self.user)
        self.assertEqual((library.get("figma").name, library.get("figma").source), ("Figma Next", "updates"))
        self.assert_user_untouched()

    def test_an_unchanged_profile_is_not_downloaded(self):
        karl = (PROFILES / "karl" / "figma.json").read_bytes()
        result = self.check(self.good_files(karl=karl))
        self.assertEqual((result.updated, result.kept, result.text), ([], [], "Profiles are up to date."))
        self.assertEqual([r[0] for r in self.opener.requests], [pu.INDEX_URL])
        self.assertEqual(self.updated_files(), [])

    def test_a_changed_sidecar_alone_is_fetched_and_validated_with_the_bundled_karl_file(self):
        karl = (PROFILES / "karl" / "figma.json").read_bytes()
        overlay = json.loads(self.overlay)
        overlay["notes"] = ["updated"]
        overlay = json.dumps(overlay).encode("ascii")
        result = self.check(self.good_files(karl=karl, overlay=overlay))
        self.assertEqual(result.updated, ["FIGMA"], "the name the profile itself carries (Karl's)")
        self.assertEqual(self.updated_files(), ["figma.windows.json"])

    def test_previous_good_file_is_kept_on_every_kind_of_bad_download(self):
        old = figma_variant("Figma Old")
        bad = figma_variant("Figma Nexx")       # same size, other bytes
        broken = json.loads(self.karl)
        broken["rings"] = "not a list"
        broken = json.dumps(broken).encode("ascii")
        oversize = self.karl + b" " * (pu.FILE_MAX + 1 - len(self.karl))
        cases = {
            "hash mismatch": ({**self.good_files(), pu.BASE_URL + "karl/figma.json": bad},
                              "the download didn't match its checksum"),
            "oversize": ({**self.good_files(), pu.BASE_URL + "karl/figma.json": oversize}, "the download was too big"),
            "oversize header": ({**self.good_files(), pu.BASE_URL + "karl/figma.json":
                                 Response(self.karl, length=pu.FILE_MAX + 1)}, "the download was too big"),
            "truncated": ({**self.good_files(), pu.BASE_URL + "karl/figma.json": self.karl[:-10]},
                          "the download was incomplete"),
            "invalid profile": (self.good_files(karl=broken), "the new file didn't pass the profile checks"),
        }
        for name, (files, reason) in cases.items():
            with self.subTest(case=name):
                shutil.rmtree(self.updates, ignore_errors=True)
                self.updates.mkdir(parents=True)
                (self.updates / "figma.json").write_bytes(old)
                result = self.check(files)
                self.assertTrue(result.ok)
                self.assertEqual(result.updated, [])
                self.assertEqual(result.kept, [f"Figma: {reason}. Kept the current version."])
                self.assertEqual((self.updates / "figma.json").read_bytes(), old, "the previous good file stays")
                self.assertEqual(self.updated_files(), ["figma.json"])
                self.assert_user_untouched()

    def test_a_profile_for_a_newer_desk_dial_is_skipped(self):
        result = self.check(self.good_files(minimum="9.0.0"), version="2.0.0")
        self.assertEqual(result.kept, ["Figma: needs Desk Dial 9.0.0 or later."])
        self.assertEqual([r[0] for r in self.opener.requests], [pu.INDEX_URL])
        self.assertEqual(self.updated_files(), [])

    def test_offline_changes_nothing(self):
        for error in (urllib.error.URLError("no route"), TimeoutError("slow"), OSError("reset")):
            with self.subTest(error=type(error).__name__):
                result = self.check({pu.INDEX_URL: error})
                self.assertEqual((result.ok, result.offline), (False, True))
                self.assertEqual(result.text, "Couldn't reach the Desk Dial repo. Your profiles haven't changed.")
                self.assertEqual(self.updated_files(), [])
        result = self.check({pu.INDEX_URL: index(entry("figma", self.karl, self.overlay)),
                             pu.BASE_URL + "karl/figma.json": urllib.error.URLError("dropped")})
        self.assertTrue(result.offline)
        self.assertEqual(self.updated_files(), [])

    def test_a_bad_or_oversize_index_changes_nothing(self):
        bad = [b"[]", b"{\"format\": 2, \"profiles\": []}", b"not json",
               index({**entry("figma", self.karl), "file": "../user/figma.json"}),
               index({**entry("figma", self.karl), "file": "karl/onshape.json"}),
               index({**entry("figma", self.karl), "bytes": pu.FILE_MAX + 1}),
               index({**entry("figma", self.karl), "sha256": "x" * 64}),
               index({**entry("figma", self.karl), "desk_dial_min": "soon"}),
               index(entry("figma", self.karl), entry("figma", self.karl)),
               index({**entry("Figma!", self.karl)}),
               b"{" + b" " * pu.INDEX_MAX + b"}"]
        for data in bad:
            with self.subTest(data=data[:60]):
                result = self.check({pu.INDEX_URL: data})
                self.assertEqual((result.ok, result.offline, result.updated), (False, False, []))
                self.assertEqual(result.text, "The profile list from the Desk Dial repo wasn't usable. "
                                              "Your profiles haven't changed.")
                self.assertEqual(self.updated_files(), [])

    def test_a_write_that_fails_half_way_keeps_both_previous_files(self):
        self.updates.mkdir(parents=True)
        old_karl, old_overlay = figma_variant("Figma Old"), self.overlay
        (self.updates / "figma.json").write_bytes(old_karl)
        (self.updates / "figma.windows.json").write_bytes(old_overlay)
        overlay = json.loads(self.overlay)
        overlay["notes"] = ["new"]
        overlay = json.dumps(overlay).encode("ascii")
        real = os.replace
        calls = []

        def flaky(src, dst):
            calls.append(Path(dst).name)
            if Path(dst).name == "figma.json":
                raise OSError("disk full")
            return real(src, dst)
        with patch.object(pu.os, "replace", flaky):
            result = self.check(self.good_files(overlay=overlay))
        self.assertEqual(result.kept, ["Figma: it couldn't be saved. Kept the current version."])
        self.assertEqual(calls, ["figma.windows.json", "figma.json"], "the sidecar is switched in first")
        self.assertEqual((self.updates / "figma.json").read_bytes(), old_karl)
        self.assertEqual(sorted(p.name for p in self.updates.iterdir()), ["figma.json", "figma.windows.json"],
                         "no temporary file stays")
        library = app_profiles.Library(PROFILES, self.updates, self.user)
        self.assertEqual(library.get("figma").name, "Figma Old", "the old Karl file still loads")

    def test_the_user_folder_is_never_a_target(self):
        opener = FakeOpener(self.good_files())
        result = pu.run_check(self.user, PROFILES, "2.0.0", opener, self.user)
        self.assertFalse(result.ok)
        self.assertEqual(opener.requests, [])
        result = pu.run_check(self.user / "sub", PROFILES, "2.0.0", opener, self.user)
        self.assertFalse(result.ok)
        self.assert_user_untouched()

    def test_messages_never_carry_a_url_or_path(self):
        for files in (self.good_files(), {pu.INDEX_URL: urllib.error.URLError("x")}, {pu.INDEX_URL: b"[]"},
                      {**self.good_files(), pu.BASE_URL + "karl/figma.json": b"{}"}):
            text = self.check(files).text
            self.assertNotIn("http", text)
            self.assertNotIn(str(self.updates), text)


class PolicyTests(unittest.TestCase):
    def test_off_never_runs_and_daily_runs_once_a_day(self):
        now = 1_800_000_000.0
        self.assertFalse(pu.due("off", 0, now))
        self.assertFalse(pu.due("weekly", 0, now))
        self.assertTrue(pu.due("daily", 0, now))
        self.assertFalse(pu.due("daily", now - 3600, now))
        self.assertTrue(pu.due("daily", now - pu.DAY_S, now))
        self.assertTrue(pu.due("daily", now + 3600, now), "a clock set back never blocks the check for good")
        self.assertTrue(pu.due("daily", "yesterday", now))

    def test_settings_values(self):
        self.assertEqual((pu.normal_setting("daily"), pu.normal_setting(True), pu.DEFAULT_SETTING),
                         ("daily", "off", "off"))
        self.assertEqual([pu.normal_last(v) for v in (5, 5.5, -1, float("nan"), True, "1", None)],
                         [5, 5.5, 0, 0, 0, 0, 0])

    def test_versions(self):
        self.assertTrue(pu.version_ok("2.0.0", "2.0.0"))
        self.assertTrue(pu.version_ok("2.0", "2.0.1"))
        self.assertFalse(pu.version_ok("2.1.0", "2.0.9"))
        self.assertTrue(pu.version_ok("2.1.0", None), "a checkout without a version reads everything")
        self.assertFalse(pu.version_ok("later", "2.0.0"))


class WorkerTests(unittest.TestCase):
    def test_the_check_runs_off_the_calling_thread_and_reports_once(self):
        import threading
        seen = []

        def runner(*args):
            seen.append((threading.current_thread().name, args[-1]))
            return pu.CheckResult(updated=["Figma"], finished=1.0)
        updater = pu.ProfileUpdater("u", "b", "2.0.0", "user", opener=object(), runner=runner)
        updater.names = {"figma": "Figma"}
        self.assertTrue(updater.start())
        deadline = time.monotonic() + 5
        result = None
        while result is None and time.monotonic() < deadline:
            result = updater.poll()
            time.sleep(0.01)
        self.assertEqual(result.updated, ["Figma"])
        self.assertIsNone(updater.poll(), "reported once")
        self.assertEqual(seen, [("deskdial-profile-updates", {"figma": "Figma"})])
        self.assertIs(updater.last, result)

    def test_a_second_start_while_busy_is_refused(self):
        import threading
        gate = threading.Event()
        updater = pu.ProfileUpdater("u", runner=lambda *a: (gate.wait(5), pu.CheckResult())[1])
        self.assertTrue(updater.start())
        self.assertFalse(updater.start())
        gate.set()
        updater._thread.join(5)
        self.assertIsNotNone(updater.poll())

    def test_a_failing_runner_still_reports(self):
        updater = pu.ProfileUpdater("u", runner=lambda *a: 1 / 0)
        updater.start()
        updater._thread.join(5)
        self.assertFalse(updater.poll().ok)


class ImportTests(unittest.TestCase):
    def test_importing_the_module_opens_nothing(self):
        source = (REPO / "control_center" / "profile_updates.py").read_text(encoding="utf-8")
        body = source[source.index('"""', 3):]
        self.assertNotIn("urlopen(", body)
        self.assertEqual(source.count("raw.githubusercontent.com"), 1, "one place names the host")


if __name__ == "__main__":
    unittest.main()
