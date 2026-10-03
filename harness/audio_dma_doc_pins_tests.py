"""FW-BUG-018 doc pin: HAPTICS.md Sound > Writer states the underrun rule against the writable DMA depth.

cc_sound.h counts an underrun when a write takes CC_SOUND_DMA_WRITABLE frames ((buffers - 1) x frames: the IDF 4.4
free-buffer queue holds buf_cnt - 1), so the doc must say the same, with numbers that match the header constants.
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
    if 'acceptedFrames >= CC_SOUND_DMA_WRITABLE' not in header:
        fails.append('cc_sound.h: cc_sound_underrun does not count against CC_SOUND_DMA_WRITABLE')
    writable = (buffers - 1) * frames
    ms = writable / 22050 * 1000
    doc = re.sub(r'\s+', ' ', (firmware / 'HAPTICS.md').read_text(encoding='utf-8'))
    if 'finds the whole DMA free' in doc:
        fails.append('HAPTICS.md: Writer still says "the whole DMA free"')
    want = (f'a sound already playing that finds the whole writable DMA free ({buffers - 1} of the {buffers} buffers, '
            f'{writable} frames / {ms:.1f} ms: the IDF 4.4 free-buffer queue holds buf_cnt-1)')
    if want not in doc:
        fails.append(f'HAPTICS.md: Writer lacks: {want}')
    for msg in fails:
        print('FAIL:', msg)
    print(f'{"FAIL" if fails else "PASS"}: audio DMA doc pins, 3 checks, {len(fails)} failures')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
