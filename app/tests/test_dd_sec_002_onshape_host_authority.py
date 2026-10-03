"""DD-SEC-002: the address-bar host, not the title, decides whether a browser window is Onshape.

A page titled "... | Onshape" (the marketing site, or any page that sets its own title) used to enter Onshape
mode without the host being read; the deny-list (NOT_ONSHAPE_HOSTS) never ran. And the "address bar" was the
window's first Edit, which in a window without an omnibox is a text field of the page itself."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from control_center import onshape as O  # noqa: E402
from control_center import browser_url  # noqa: E402


def windows_with(title, host):
    w = O.OnshapeWindows.__new__(O.OnshapeWindows)
    w._exes = {}
    w.exe = lambda pid: "chrome.exe"
    w.pid = lambda hwnd: 7

    class U:
        @staticmethod
        def GetWindowTextW(hwnd, buffer, size):
            buffer.value = title
    w.u = U()
    w.address_host = lambda hwnd: host
    return w


class HostAuthorityTests(unittest.TestCase):
    def test_title_alone_never_makes_a_marketing_or_spoofed_page_onshape(self):
        title = "Pricing | Onshape - Google Chrome"
        for host, expected in (("www.onshape.com", False), ("evil.example", False), ("learn.onshape.com", False),
                               ("", False), ("cad.onshape.com", True), ("acme.onshape.com", True)):
            with self.subTest(host=host):
                self.assertIs(windows_with(title, host).is_onshape(1), expected)

    def test_an_onshape_document_title_without_onshape_still_matches_by_host(self):
        self.assertTrue(windows_with("Bracket | Part Studio 1 - Google Chrome", "cad.onshape.com").is_onshape(1))

    def test_the_title_is_the_fallback_only_when_the_host_is_unreadable(self):
        self.assertTrue(windows_with("Bracket | Onshape - Google Chrome", None).is_onshape(1))
        self.assertFalse(windows_with("Inbox - Gmail - Google Chrome", None).is_onshape(1))


class FakeTree:
    """Elements are ints; parents / classes / documents are dicts."""

    def __init__(self, classes, parents, documents=(), fail=False):
        self.classes, self.parents, self.documents, self.fail = classes, parents, set(documents), fail
        self.released = []

    def class_name(self, element):
        if self.fail:
            raise OSError("uia")
        return self.classes.get(element, "")

    def parent(self, element):
        return self.parents.get(element)

    def is_document(self, element):
        return element in self.documents

    def release(self, element):
        self.released.append(element)


class AddressBarTests(unittest.TestCase):
    def test_the_omnibox_is_the_address_bar(self):
        self.assertTrue(browser_url.is_address_bar(FakeTree({5: "OmniboxViewViews"}, {}), 5))

    def test_a_text_field_inside_the_page_is_not(self):
        tree = FakeTree({5: "", 4: "", 3: ""}, {5: 4, 4: 3, 3: 1}, documents=(3,))
        self.assertFalse(browser_url.is_address_bar(tree, 5))
        self.assertEqual(sorted(tree.released), [3, 4], "every ancestor read is released, never the edit")

    def test_an_unrecorded_class_outside_any_document_is_accepted(self):
        self.assertTrue(browser_url.is_address_bar(FakeTree({5: "SomeEdit"}, {5: 4, 4: 1}), 5))

    def test_a_uia_failure_is_not_an_address_bar(self):
        self.assertFalse(browser_url.is_address_bar(FakeTree({}, {}, fail=True), 5))


if __name__ == "__main__":
    unittest.main()
