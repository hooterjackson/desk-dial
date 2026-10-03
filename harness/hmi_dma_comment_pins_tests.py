"""FW-BUG-018 comment pin: hmi_thread.cpp's 3 ms audio pass cap names the writable DMA depth, not the whole ring.

cc_sound.h counts underruns against CC_SOUND_DMA_WRITABLE ((buffers - 1) x frames, the IDF 4.4 free-buffer queue),
so the loop comment that justifies the 3 ms cap must quote that depth, with numbers matching the header constants.
"""
from pathlib import Path
import re
import sys

root = Path(__file__).resolve().parent
firmware = root.parent / 'firmware'


def const(header: str, name: str) -> int:
    m = re.search(r'constexpr uint32_t ' + name + r' = (\d+)u?;', header)
    if not m:
        raise SystemExit(f'FAIL: {name} not found as a literal in cc_sound.h')
    return int(m.group(1))


def main() -> int:
    fails: list[str] = []
    header = (firmware / 'src' / 'audio' / 'cc_sound.h').read_text(encoding='utf-8')
    buffers = const(header, 'CC_SOUND_DMA_BUFFERS')
    frames = const(header, 'CC_SOUND_DMA_FRAMES')
    ms = (buffers - 1) * frames / 22050 * 1000
    src = (firmware / 'src' / 'hmi_thread.cpp').read_text(encoding='utf-8')
    if '17 ms of DMA' in src:
        fails.append('hmi_thread.cpp: comment still says "17 ms of DMA" (the whole ring, not the writable depth)')
    want = f'so its {ms:.1f} ms of writable DMA ({buffers - 1} x {frames} frames) never runs dry'
    if want not in src:
        fails.append(f'hmi_thread.cpp: 3 ms cap comment lacks: {want}')
    if 'if (audioPlayer.playing() && waitMs > 3) waitMs = 3;' not in src:
        fails.append('hmi_thread.cpp: the 3 ms pass cap while a sound plays is gone')
    for msg in fails:
        print('FAIL:', msg)
    print(f'{"FAIL" if fails else "PASS"}: hmi DMA comment pins, 3 checks, {len(fails)} failures')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
