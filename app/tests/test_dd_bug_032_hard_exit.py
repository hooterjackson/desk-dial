"""DD-BUG-032 (D9): after main() returns, the process flushes its logs and ends with
os._exit(0), so a lane worker still running past Runtime.close()'s bounded join cannot
keep the hidden process alive. No Tk, no ports, no network."""
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import standalone


class HardExitTests(unittest.TestCase):
    def test_normal_return_flushes_logs_then_exits_zero(self):
        order = []
        with patch.object(standalone.logging, 'shutdown', side_effect=lambda: order.append('logs')), \
             patch.object(standalone.os, '_exit', side_effect=lambda code: order.append(('exit', code))):
            standalone.run_and_exit(lambda: order.append('main'))
        self.assertEqual(order, ['main', 'logs', ('exit', 0)])

    def test_failure_is_logged_and_reraised_without_hard_exit(self):
        def boom():
            raise RuntimeError('startup failed')
        with patch.object(standalone.os, '_exit') as hard_exit, \
             patch.object(standalone.logging, 'exception') as logged:
            with self.assertRaises(RuntimeError):
                standalone.run_and_exit(boom)
        hard_exit.assert_not_called()
        logged.assert_called_once_with('Application failed')

    def test_system_exit_keeps_its_code(self):
        def smoke():
            raise SystemExit(3)
        with patch.object(standalone.os, '_exit') as hard_exit:
            with self.assertRaises(SystemExit) as caught:
                standalone.run_and_exit(smoke)
        self.assertEqual(caught.exception.code, 3)
        hard_exit.assert_not_called()

    def test_entry_point_uses_run_and_exit(self):
        source = (ROOT / 'standalone.py').read_text(encoding='utf-8')
        tail = source[source.rindex("if __name__ == '__main__':"):]
        self.assertIn('run_and_exit()', tail)
        # The hard exit comes after main's finally, which closes the mutex.
        main_src = source[source.index('def main():'):source.index('def run_and_exit(')]
        self.assertIn('kernel.CloseHandle(mutex)', main_src)
        self.assertNotIn('os._exit', main_src)


if __name__ == '__main__':
    unittest.main()
