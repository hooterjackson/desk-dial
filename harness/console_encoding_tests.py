"""HN-BUG-002: harness gates must survive a cp1252 console / redirected stdout.

Runs font_tests.py with PYTHONIOENCODING=cp1252 (and UTF-8 mode off), skipping the toolchain and node checks, and
requires the same exit code and final 'font_tests: ...' verdict a PYTHONUTF8=1 run gives, with no UnicodeEncodeError.

    python console_encoding_tests.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def run_font_tests(**env_overrides: str) -> tuple[int, str]:
    env = dict(os.environ, **env_overrides)
    proc = subprocess.run([sys.executable, str(HERE / 'font_tests.py'), '--no-toolchain', '--no-node'],
                          cwd=HERE, env=env, capture_output=True)
    return proc.returncode, (proc.stdout + proc.stderr).decode('utf-8', errors='replace')


def verdict(out: str) -> str:
    lines = [line.strip() for line in out.splitlines() if line.strip()]
    return lines[-1] if lines else ''


def run_font_tests_cp1252() -> list[str]:
    """The cp1252 run must reach the same verdict as the UTF-8 run (whatever the fonts' own state is)."""
    rc_utf8, out_utf8 = run_font_tests(PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    rc_cp, out_cp = run_font_tests(PYTHONUTF8='0', PYTHONIOENCODING='cp1252')
    failures = []
    if 'UnicodeEncodeError' in out_cp:
        failures.append('font_tests.py raised UnicodeEncodeError on a cp1252 stdout:\n' + out_cp[-1200:])
    if not verdict(out_cp).startswith('font_tests: '):
        failures.append(f'font_tests.py did not reach its verdict on a cp1252 stdout: {verdict(out_cp)!r}')
    if (rc_cp, verdict(out_cp)) != (rc_utf8, verdict(out_utf8)):
        failures.append(f'cp1252 run ({rc_cp}, {verdict(out_cp)!r}) differs from the UTF-8 run '
                        f'({rc_utf8}, {verdict(out_utf8)!r})')
    print(f'font_tests.py verdict: UTF-8 ({rc_utf8}, {verdict(out_utf8)!r}); cp1252 ({rc_cp}, {verdict(out_cp)!r})')
    return failures


def main() -> int:
    sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')
    failures = run_font_tests_cp1252()
    for failure in failures:
        print(f'FAIL {failure}')
    print('console_encoding_tests: ' + ('FAIL' if failures else 'PASS'))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
