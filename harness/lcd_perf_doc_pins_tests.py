"""Display-perf doc pins: PRESENTATION_V5.md 12.3 must describe lcdRefrUsMax / lcdRefrUsAvg as the firmware computes
them. Python stdlib only; no device, no USB.

FW-PERF-010: lcdRefrUsAvg / lcdRefrUsMax were since boot; lcd_thread.cpp now sums one perfWindow() second in a
CCRefrWindow (cc_lcd_logic.h) and publishes its mean and max when the window closes (0, 0 without a refresh). The 12.3
row must say they cover the refreshes of the last full second, windowed like lcdFps, and are 0 when none reached the
panel; the source must still publish them from perfWindow() through cc_refr_window_close().

Usage: python lcd_perf_doc_pins_tests.py
Exit status is non-zero on any failure.
"""
from __future__ import annotations

from pathlib import Path
import re
import sys

firmware = Path(__file__).resolve().parent.parent / 'firmware'
failures: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(('ok   ' if ok else 'FAIL ') + msg)
    if not ok:
        failures.append(msg)


def code(text: str) -> str:
    text = re.sub(r'/\*.*?\*/', ' ', text, flags=re.S)
    text = re.sub(r'//[^\n]*', ' ', text)
    return re.sub(r'\s+', ' ', text)


doc = (firmware / 'PRESENTATION_V5.md').read_text(encoding='utf-8')
sec = doc.split('### 12.3', 1)[1].split('\n### ', 1)[0] if '### 12.3' in doc else ''
check(bool(sec), 'PRESENTATION_V5.md has section 12.3')
rows = [ln for ln in sec.splitlines() if ln.startswith('| `lcdRefrUsMax`')]
check(len(rows) == 1, '12.3 has one lcdRefrUsMax / lcdRefrUsAvg row')
row = rows[0] if rows else ''
check('`lcdRefrUsAvg`' in row, 'the row names lcdRefrUsAvg')
check('over the refreshes of the last full second' in row, 'the row says: over the refreshes of the last full second')
check('windowed like `lcdFps`' in row, 'the row says: windowed like lcdFps')
check('0 when none reached the panel' in row, 'the row says: 0 when none reached the panel')
check('since boot' not in row, 'the row does not say since boot')

lcd = code((firmware / 'src' / 'lcd_thread.cpp').read_text(encoding='utf-8'))
logic = code((firmware / 'src' / 'cc_lcd_logic.h').read_text(encoding='utf-8'))
check('cc_refr_window_close' in logic and 'w.count ? ' in logic,
      'cc_lcd_logic.h: cc_refr_window_close gives 0 for an empty window')
m = re.search(r'void perfWindow\(uint32_t nowMs\) \{(.*?)\n?void ', lcd + ' void ', flags=re.S)
pw = m.group(1) if m else ''
check('cc_refr_window_close(winRefr' in pw, 'perfWindow() closes the refresh window')
check('perf.lcdRefrUsAvg = refrAvg' in pw and 'perf.lcdRefrUsMax = refrMax' in pw,
      'perfWindow() publishes lcdRefrUsAvg / lcdRefrUsMax from the window')
check(lcd.count('perf.lcdRefrUsMax =') == 1 and lcd.count('perf.lcdRefrUsAvg =') == 1,
      'lcdRefrUsAvg / lcdRefrUsMax are written only by perfWindow()')

print(f'{len(failures)} failure(s)')
sys.exit(1 if failures else 0)
