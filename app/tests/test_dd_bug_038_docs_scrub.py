"""DD-BUG-038 (docs side): the Desk Dial README and the design-reference prototypes (*.dc.html)
carry no personal room or household name and no private-network IP address.

The names are matched by SHA-256 of each lower-cased word (camelCase, snake_case and kebab-case
are split first), so this test does not itself spell them. Text files only: no Tk, no network."""
from pathlib import Path
import hashlib
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
# sha256 of the lower-cased personal room name and household name that must not appear.
BANNED = {
    "8a8a1a9fe8565d64c5b8b27cb1f9c3dcb2ff7632bc715b805df124d668e3c9e3",
    "ab1cb712f2dca756105160805501f4d6d8657d93d40b16eee4ecb5fd048d26eb",
}
PRIVATE_IP = re.compile(r"\b(?:10|127|192\.168|172\.(?:1[6-9]|2\d|3[01]))(?:\.\d{1,3}){2,3}\b")
WORD = re.compile(r"[A-Za-z]+")


def _words(text):
    for token in WORD.findall(text):
        # split camelCase / PascalCase; ALLCAPS stays one word
        for part in re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+", token):
            yield part.lower()


def _docs():
    yield ROOT / "README.md"
    yield from sorted((ROOT / "design-reference").rglob("*.dc.html"))


class DocsScrubTests(unittest.TestCase):
    def test_docs_exist(self):
        docs = list(_docs())
        self.assertTrue((ROOT / "README.md").is_file())
        self.assertGreater(len(docs), 5)

    def test_no_personal_room_or_household_name(self):
        for path in _docs():
            text = path.read_text(encoding="utf-8")
            with self.subTest(file=path.name):
                hits = sorted({w for w in _words(text)
                               if hashlib.sha256(w.encode()).hexdigest() in BANNED})
                self.assertEqual(hits, [], f"{path.relative_to(ROOT)} still names a personal place")

    def test_no_private_ip_address(self):
        for path in _docs():
            text = path.read_text(encoding="utf-8")
            with self.subTest(file=path.name):
                self.assertIsNone(PRIVATE_IP.search(text), str(path.relative_to(ROOT)))

    def test_word_splitter_catches_identifiers(self):
        self.assertEqual(list(_words("fooBar BAZ qux_quux")), ["foo", "bar", "baz", "qux", "quux"])


if __name__ == "__main__":
    unittest.main()
