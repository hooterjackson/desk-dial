"""DD-RES-018: status.json is written atomically (temp + os.replace), compact, and only when it
changed or every STATUS_REFRESH_S for liveness. No Tk, no ports, no network."""
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import standalone
from standalone import StatusWriter, STATUS_REFRESH_S


def payload(t, mode='VOLUME', pad=200):
    return {'mode': mode, 'connected': True, 'time': t, 'blob': ['x' * 40] * pad}


class StatusWriterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'status.json'
        self.replaced = []

        def replace(src, dst):
            self.replaced.append((Path(src).name, Path(dst).name))
            os.replace(src, dst)
        self.writer = StatusWriter(self.path, replace=replace, sleep=lambda s: None)

    def tearDown(self):
        self.tmp.cleanup()

    def test_status_written_atomically_and_only_on_change(self):
        w = self.writer
        self.assertTrue(w.write(payload(0.0), now=0.0))
        # Unchanged state (only `time` moves): no write inside the refresh window.
        for tick in range(1, int(STATUS_REFRESH_S)):
            self.assertFalse(w.write(payload(float(tick)), now=float(tick)))
        self.assertEqual(w.writes, 1)
        # The refresh window elapsed: written again so readers see a fresh `time`.
        self.assertTrue(w.write(payload(STATUS_REFRESH_S), now=STATUS_REFRESH_S))
        # A state change is written on the very next call.
        self.assertTrue(w.write(payload(STATUS_REFRESH_S + 1, mode='LIGHTS'), now=STATUS_REFRESH_S + 1))
        self.assertEqual(w.writes, 3)
        self.assertEqual(len(self.replaced), 3)
        for src, dst in self.replaced:
            self.assertEqual(dst, 'status.json')
            self.assertNotEqual(src, 'status.json')
        doc = json.loads(self.path.read_text(encoding='utf-8'))
        self.assertEqual(doc['mode'], 'LIGHTS')
        self.assertNotIn('\n', self.path.read_text(encoding='utf-8'), 'compact JSON')
        self.assertEqual([p.name for p in Path(self.tmp.name).iterdir()], ['status.json'], 'no temp left')

    def test_refresh_keeps_status_fresh_for_the_check_scripts(self):
        # tools/check_desktop_v7.py calls status.json fresh within 5 s; one 1 s tick of slack.
        self.assertLessEqual(STATUS_REFRESH_S + standalone.MAINTAIN_MS / 1000.0, 5.0)

    def test_locked_target_retries_then_raises_and_leaves_no_temp(self):
        calls = []

        def locked(src, dst):
            calls.append(1)
            raise PermissionError('in use')
        w = StatusWriter(self.path, replace=locked, sleep=lambda s: None)
        with self.assertRaises(PermissionError):
            w.write(payload(0.0), now=0.0)
        self.assertEqual(len(calls), standalone.STATUS_REPLACE_TRIES)
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])
        # Not remembered as written: the next tick tries again.
        self.assertEqual(w.writes, 0)
        w.replace = os.replace
        self.assertTrue(w.write(payload(0.5), now=0.5))

    def test_transient_lock_is_retried(self):
        state = {'n': 0}

        def flaky(src, dst):
            state['n'] += 1
            if state['n'] == 1:
                raise PermissionError('reader holds it')
            os.replace(src, dst)
        w = StatusWriter(self.path, replace=flaky, sleep=lambda s: None)
        self.assertTrue(w.write(payload(0.0), now=0.0))
        self.assertEqual(json.loads(self.path.read_text(encoding='utf-8'))['mode'], 'VOLUME')

    def test_concurrent_reader_never_sees_invalid_json(self):
        w = StatusWriter(self.path, refresh_s=0.0)
        w.write(payload(0.0), now=0.0)
        stop = threading.Event()
        bad, good = [], [0]

        def reader():
            while not stop.is_set():
                try:
                    text = self.path.read_text(encoding='utf-8')
                except (PermissionError, FileNotFoundError):
                    continue   # Windows: the swap moment; never a partial document
                try:
                    json.loads(text)
                    good[0] += 1
                except ValueError:
                    bad.append(len(text))
        t = threading.Thread(target=reader)
        t.start()
        try:
            for i in range(300):
                try:
                    w.write(payload(float(i), mode='M%d' % i), now=float(i))
                except PermissionError:
                    pass   # the reader held it through every retry; the next tick writes
        finally:
            stop.set()
            t.join()
        self.assertEqual(bad, [])
        self.assertGreater(good[0], 0)


class MaintainTickUsesWriterTests(unittest.TestCase):
    """Source pin: the app's 1 s maintain tick must go through the atomic StatusWriter."""

    def test_maintain_once_writes_status_through_status_writer(self):
        import inspect
        src = inspect.getsource(standalone.main)
        self.assertIn('status_writer.write(status)', src)
        self.assertIn("StatusWriter(logs/'status.json')", src)
        compact = src.replace(' ', '')
        self.assertNotIn('write_text(json.dumps(status', compact)
        self.assertNotIn("open(logs/'status.json'", compact)


if __name__ == '__main__':
    unittest.main()
