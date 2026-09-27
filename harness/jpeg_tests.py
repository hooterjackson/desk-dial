"""artwork2 cover JPEG glue checks (1.0.0-cc5.3, ARTWORK2.md sections 4.3, 5, 7 and 10). Python +
Pillow + MSVC; the xtensa toolchain for the firmware syntax check. No device, no USB, no PlatformIO.

1. Encodes the design covers (design_handoff_nano_d_artwork_color/assets/covers) with the host
   encoder itself: control_center.artwork.prepare_artwork2 (read-only import), whose JPEG is
   ARTWORK2.md section 5's (EXIF-transposed, crop-fitted to 240 with LANCZOS, 0.8 opacity plus
   the readability scrim, baseline, 4:2:0, optimize=True, the first quality of 85, 80, 75, 70,
   65, 60 that fits 32768 bytes). This script's own replica of section 5 is reported next to
   it (and used only when the companion cannot be imported). Plus accepted variants
   (4:4:4, 4:2:2, a comment segment, EXIF, restart markers, the hand-written gray JPEG of the
   store traces) and rejects: progressive, oversize, other sizes, grayscale, CMYK, leading
   garbage, truncated headers, not a JPEG, empty, a missing EOI, a byte after EOI and a cover
   cut inside its scan (no EOI); and a cover cut inside its scan with EOI appended (the
   headers and EOI validate, the decode fails: the one edge the commit check leaves to the
   LCD, which the payload CRC-32 confines to host bugs).
2. Checks the ROM TJpgDec R0.01b work area each accepted sample needs (its alloc_pool sizes,
   from the marker segments) against cc_jpeg.cpp's 4096-byte area.
3. Compiles jpeg_tests.cpp with the unchanged src/cc_jpeg.cpp through tjpgd_shim/ and LVGL's
   TJpgDec R0.03 (MSVC /W4 /WX) and runs it: validate/decode results, reported sizes, guarded
   destinations, argument and oversize rejects, exact gray pixels and the decode statistics. It
   also saves the decoder's own RGB888 output of each decoded sample (the esp_rom_tjpgd API
   called directly). 1.0.0-cc5.4 (PRESENTATION_V5 12.5.4 step 2 and 12.5.7's jpeg case, lead
   ruling R-f): the abort hook over every decodable sample -- polled once per MCU row, top to
   bottom, before the row is written; an abort at EVERY band returns CC_JPEG_ABORTED (JDR_INTR)
   with the rows above it equal to a clean decode, nothing from it on written, one decode and no
   error counted, and the next clean decode byte-identical (the decoder is reusable); the
   `&cancel` flag form; the damaged scan FAILED through the hook, never ABORTED.
4. Pixels. Implementation checks, for every decoded sample:
   a. glue: cc_jpeg_decode_240's RGB565 equals r5 = (r*31 + 127)//255, g6 = (g*63 + 127)//255,
      b5 = (b*31 + 127)//255 of the decoder's RGB888 at the same position, bit for bit;
   b. decoder: its RGB888 is within PSNR >= 40 dB of Pillow's RGB888 decode of the same file.
   Then the ARTWORK2.md section 10 JPEG figure, which applies to the design covers encoded by
   the host encoder (the cover-* samples; the variants are not host-encoder output), under the
   rule named by SECTION10_RULE (or --section10-rule). It states the contract's text exactly;
   when the lead amends section 10, this constant changes in the same change. The lead ratified
   'decoder-rgb888' on 2026-09-24, together with the user who owns the knob: ARTWORK2.md section
   10 now states it, so it is the default.
   - 'as-written' (the original cc5.3-start wording, superseded): the RGB565 result against Pillow's decode after RGB565
     rounding (both expanded to 8 bits), >= 40 dB for every design cover. NOT met with Pillow
     12.3: cover-heligoland-album measures 39.40 dB although (a) is exact and (b) is 43.14 dB.
     Rounding both sides to RGB565 turns the decoders' +-1 differences (TJpgDec floors its IDCT
     and replicates chroma, as the ROM's R0.01b does; libjpeg rounds and interpolates) into
     whole RGB565 steps, and section 7 fixes the conversion, so the firmware cannot change it.
   - 'decoder-rgb888' (amendment A, the rule in force): (a) and (b) for the design covers.
   - 'rgb565-vs-rgb888' (candidate amendment B, the other reading of the sentence): the RGB565
     result (expanded to 8 bits) against Pillow's unrounded RGB888, >= 40 dB for every design
     cover (worst 40.08 dB with Pillow 12.3: a 0.08 dB margin).
   Reported only (candidate amendment C, a host encoder change): the same design covers encoded
   at 4:4:4 (subsampling=0, allowed by section 5's payload rule) meet 'as-written' (worst 40.71
   dB with Pillow 12.3) at about 10-35 % more bytes; their decode time on the knob is unmeasured.
5. Syntax-checks src/cc_jpeg.cpp with the firmware's own compile line against the real
   esp_rom_tjpgd.h (compile_commands.json, -fsyntax-only).

Writes only under build/jpeg-tests. Exit status: 0 when every check and the section 10 rule in
force pass; 1 when an implementation check fails (rejects, sizes, work area, glue, decoder,
syntax); 2 when every implementation check passes but the section 10 rule in force does not (a
contract decision for the lead, never a PASS: see CONTROL_CENTER.md "Validation boundaries").
"""
from __future__ import annotations

import argparse
from io import BytesIO
import json
import math
from pathlib import Path
import random
import subprocess
import sys
import time

from PIL import Image, ImageOps

root = Path(__file__).resolve().parent
companion = root.parent / 'app'
covers_dir = companion / 'design-reference' / 'design_handoff_nano_d_artwork_color' / 'assets' / 'covers'
out_dir = root / 'build' / 'jpeg-tests'

sys.path.insert(0, str(root))
sys.path.insert(0, str(companion))
import media_tests  # noqa: E402  (this directory: MSVC and xtensa helpers, gray_jpeg)
from control_center import presentation  # noqa: E402  (read-only: the artwork2 constants)

SIZE = presentation.COVER_SIZE
MAX_BYTES = presentation.COVER_MAX_BYTES
QUALITIES = presentation.COVER_JPEG_QUALITIES
WORK_BYTES = 4096            # cc_jpeg.cpp kWorkWords * 4
MIN_PSNR = 40.0              # decoder vs Pillow (4b), and the ARTWORK2.md section 10 figure
# The ARTWORK2.md section 10 JPEG rule in force: the contract's text, exactly (docstring, 4).
SECTION10_RULE = 'decoder-rgb888'
SECTION10_RULES = {
    'as-written': 'RGB565 result vs Pillow decode after RGB565 rounding >= 40 dB, every design cover',
    'decoder-rgb888': 'glue bit-exact and decoder RGB888 vs Pillow RGB888 >= 40 dB, every design cover',
    'rgb565-vs-rgb888': 'RGB565 result vs Pillow RGB888 (no reference rounding) >= 40 dB, every design cover',
}
EXIT_FAIL, EXIT_SECTION10 = 1, 2


def scrim_rows():
    """The v1 composite's per-row tables (0.8 opacity plus the scrim), from the companion."""
    try:
        from control_center import artwork  # read-only
        return artwork._scrim_rows()
    except Exception:  # noqa: BLE001  (a companion mid-edit: the documented stops instead)
        stops = ((0, .35), (108, .55), (149, .90), (168, 1.0), (239, 1.0))

        def factor(y):
            for (y0, a0), (y1, a1) in zip(stops, stops[1:]):
                if y0 <= y <= y1:
                    return .8 * (1 - (a0 + (a1 - a0) * (y - y0) / (y1 - y0)))
            raise ValueError(y)
        return tuple(bytes(round(v * factor(y)) for v in range(256)) for y in range(SIZE))


def composite(path: Path) -> Image.Image:
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert('RGB')
    cropped = ImageOps.fit(image, (SIZE, SIZE), method=Image.Resampling.LANCZOS)
    rgb, row, tables = cropped.tobytes(), SIZE * 3, scrim_rows()
    return Image.frombytes('RGB', (SIZE, SIZE),
                           b''.join(rgb[y * row:(y + 1) * row].translate(tables[y]) for y in range(SIZE)))


def encode(image: Image.Image, **options) -> bytes:
    out = BytesIO()
    image.save(out, format='JPEG', **options)
    return out.getvalue()


def host_jpeg(image: Image.Image, subsampling: int = 2) -> tuple[bytes, int]:
    """This script's replica of ARTWORK2.md section 5: the first ladder quality that fits
    (subsampling 2 is 4:2:0, the contract's host encoder; 0 is 4:4:4, candidate amendment C)."""
    for quality in QUALITIES:
        data = encode(image, quality=quality, subsampling=subsampling, optimize=True, progressive=False)
        if len(data) <= MAX_BYTES:
            return data, quality
    raise SystemExit('FAIL: no ladder quality fits 32768 bytes')


def host_encoder():
    """The desktop v4 host's own encoder, control_center.artwork.prepare_artwork2 (read-only),
    or None when the companion cannot be imported."""
    try:
        from control_center import artwork  # read-only
        return artwork.prepare_artwork2
    except Exception:  # noqa: BLE001  (a companion mid-edit: the replica instead, reported)
        return None


def rgb565_reference(data: bytes) -> list:
    with Image.open(BytesIO(data)) as image:
        rgb = image.convert('RGB').tobytes()
    return [(((rgb[i] * 31 + 127) // 255) << 11) | (((rgb[i + 1] * 63 + 127) // 255) << 5)
            | ((rgb[i + 2] * 31 + 127) // 255) for i in range(0, len(rgb), 3)]


def expand(value: int) -> tuple:
    r, g, b = value >> 11, (value >> 5) & 63, value & 31
    return (r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)


def psnr(actual: list, expected: list) -> float:
    error = 0
    for a, e in zip(actual, expected):
        for x, y in zip(expand(a), expand(e)):
            error += (x - y) ** 2
    mse = error / (3 * len(expected))
    return math.inf if mse == 0 else 10 * math.log10(255 ** 2 / mse)


def rom_pool_bytes(data: bytes) -> int:
    """Work area TJpgDec R0.01b (the ESP32-S3 ROM) allocates in jd_prepare for this JPEG."""
    def align(n):
        return (n + 3) & ~3
    need, at, blocks = align(512), 2, 0                 # stream input buffer (JD_SZBUF)
    while at + 4 <= len(data):
        marker, length = data[at + 1], int.from_bytes(data[at + 2:at + 4], 'big')
        body = data[at + 4:at + 2 + length]
        if marker == 0xC0:
            y = body[7]
            blocks = (y >> 4) * (y & 15)
        elif marker == 0xC4:
            i = 0
            while i + 17 <= len(body):
                count = sum(body[i + 1:i + 17])
                need += align(16) + align(count * 2) + align(count)
                i += 17 + count
        elif marker == 0xDB:
            i = 0
            while i < len(body):
                need += align(64 * 4)
                i += 65 if body[i] >> 4 == 0 else 129
        elif marker == 0xDA:
            return need + align(max(blocks * 64 * 2 + 64, 256)) + align((blocks + 2) * 64)
        at += 2 + length
    return need


def samples(build: Path) -> tuple[list, dict]:
    """(manifest entries, extra files) for the runner."""
    entries, notes = [], {}

    def add(name, data: bytes, validate, size=(0, 0), decode=None, psnr_check=False):
        path = build / f'{name}.jpg'
        path.write_bytes(data)
        decode = validate if decode is None else decode
        entry = {'name': name, 'path': str(path), 'validate': validate, 'w': size[0], 'h': size[1],
                 'decode': decode, 'out': str(build / f'{name}.rgb565') if decode else '',
                 'raw': str(build / f'{name}.rgb888') if decode else ''}
        entries.append(entry)
        if decode and psnr_check:
            notes[name] = data
        return path

    covers = sorted(p for p in covers_dir.iterdir() if p.suffix.lower() in ('.jpg', '.jpeg', '.png'))
    if not covers:
        raise SystemExit(f'FAIL: no design covers in {covers_dir}')
    prepare = host_encoder()
    if prepare is None:
        print('  NOTE: control_center.artwork is not importable: the design covers use this script\'s '
              'section 5 replica instead of the host encoder')
    first = None
    for path in covers:
        image = composite(path)
        replica, quality = host_jpeg(image)
        data, source = replica, 'section 5 replica'
        if prepare is not None:
            data = prepare(path.read_bytes()).jpeg
            if data is None:
                raise SystemExit(f'FAIL: the host encoder made no artwork2 cover for {path.name}')
            source = 'host encoder' + (f' (= replica, q{quality})' if data == replica
                                       else ' (differs from the section 5 replica)')
        name = 'cover-' + path.stem.strip('-')
        add(name, data, True, (SIZE, SIZE), psnr_check=True)
        print(f'  {name}: {source}, {len(data)} bytes, ROM work area {rom_pool_bytes(data)} B')
        # Candidate amendment C (reported only): the same composite encoded at 4:4:4.
        full, full_quality = host_jpeg(image, subsampling=0)
        add('option-c-444-' + path.stem.strip('-'), full, True, (SIZE, SIZE), psnr_check=True)
        notes['__bytes__' + name] = (len(data), len(full), full_quality)
        if first is None:
            first = (image, data)
    image, cover = first
    notes['__cover__'] = cover
    # Accepted variants.
    add('variant-444', encode(image, quality=75, subsampling=0, optimize=True), True, (SIZE, SIZE), psnr_check=True)
    add('variant-422', encode(image, quality=75, subsampling=1, optimize=True), True, (SIZE, SIZE), psnr_check=True)
    add('variant-comment', encode(image, quality=80, subsampling=2, comment=b'artwork2 sample'), True, (SIZE, SIZE),
        psnr_check=True)
    exif = Image.Exif()
    exif[0x0131] = 'jpeg_tests'
    add('variant-exif', encode(image, quality=80, subsampling=2, exif=exif.tobytes()), True, (SIZE, SIZE),
        psnr_check=True)
    try:
        restart = encode(image, quality=80, subsampling=2, restart_marker_blocks=4)
        if b'\xFF\xDD' in restart:
            add('variant-restart', restart, True, (SIZE, SIZE), psnr_check=True)
    except TypeError:
        pass   # Pillow without restart marker options
    gray = media_tests.gray_jpeg(SIZE, SIZE)
    notes['__gray__'] = gray
    add('variant-gray-hand-written', gray, True, (SIZE, SIZE), psnr_check=True)
    # Rejects.
    add('reject-progressive', encode(image, quality=80, subsampling=2, progressive=True), False)
    noise = Image.frombytes('RGB', (SIZE, SIZE), random.Random(5).randbytes(SIZE * SIZE * 3))
    big = encode(noise, quality=95, subsampling=0)
    assert len(big) > MAX_BYTES, len(big)
    add('reject-oversize', big, False)
    for w, h in ((239, 240), (240, 239), (480, 480), (120, 120), (16, 16)):
        add(f'reject-size-{w}x{h}', encode(image.resize((w, h)), quality=80, subsampling=2), False, (w, h))
    add('reject-grayscale', encode(image.convert('L'), quality=80), False)
    add('reject-cmyk', encode(image.convert('CMYK'), quality=80), False)
    add('reject-leading-garbage', b'\x00' + cover, False)
    sof = cover.index(b'\xFF\xC0')
    add('reject-truncated-header', cover[:sof + 6], False)
    add('reject-not-jpeg', b'\x89PNG\r\n\x1a\n' + bytes(64), False)
    add('reject-empty', b'', False)
    add('reject-soi-only', b'\xFF\xD8\xFF\xD9', False)
    add('reject-missing-eoi', cover[:-2], False)                 # refused before the ROM prepare: 0x0
    add('reject-byte-after-eoi', cover + b'\x00', False)
    sos = cover.index(b'\xFF\xDA')
    add('reject-truncated-scan', cover[:sos + 200], False)
    add('decode-fails-truncated-scan-with-eoi', cover[:sos + 200] + b'\xFF\xD9', True, (SIZE, SIZE), decode=False)
    return entries, notes


class Pixels:
    """Section 4's figures for one decoded sample."""

    def __init__(self, name: str, mismatches: int, pixels: int, decoder: float, rounded: float, unrounded: float):
        self.name, self.mismatches, self.pixels = name, mismatches, pixels
        self.decoder, self.rounded, self.unrounded = decoder, rounded, unrounded

    def implementation_ok(self) -> bool:
        """4a and 4b: the glue bit-exact, a full image, the decoder within 40 dB of Pillow."""
        return not self.mismatches and self.pixels == SIZE * SIZE and self.decoder >= MIN_PSNR

    def figure(self, rule: str) -> float:
        """The PSNR a section 10 rule (SECTION10_RULES) compares with 40 dB."""
        return {'as-written': self.rounded, 'decoder-rgb888': self.decoder, 'rgb565-vs-rgb888': self.unrounded}[rule]

    def meets(self, rule: str) -> bool:
        """One design cover under a section 10 rule ('decoder-rgb888' also needs the exact glue)."""
        if rule == 'decoder-rgb888':
            return self.implementation_ok()
        return self.figure(rule) >= MIN_PSNR


def measure(entry: dict, data: bytes) -> Pixels:
    raw = Path(entry['out']).read_bytes()
    actual = [raw[i] | raw[i + 1] << 8 for i in range(0, len(raw), 2)]
    rgb = Path(entry['raw']).read_bytes()
    glue = [(((rgb[i] * 31 + 127) // 255) << 11) | (((rgb[i + 1] * 63 + 127) // 255) << 5)
            | ((rgb[i + 2] * 31 + 127) // 255) for i in range(0, len(rgb), 3)]
    mismatches = sum(a != g for a, g in zip(actual, glue)) + abs(len(actual) - len(glue))
    with Image.open(BytesIO(data)) as image:
        pillow = image.convert('RGB').tobytes()

    def db(error: float) -> float:
        return math.inf if error == 0 else 10 * math.log10(255 ** 2 / error)
    decoder = db(sum((a - b) ** 2 for a, b in zip(rgb, pillow)) / len(pillow))
    knob = [channel for pixel in actual for channel in expand(pixel)]
    unrounded = db(sum((a - b) ** 2 for a, b in zip(knob, pillow)) / len(pillow))
    return Pixels(entry['name'], mismatches, len(actual), decoder, psnr(actual, rgb565_reference(data)), unrounded)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--section10-rule', choices=sorted(SECTION10_RULES), default=SECTION10_RULE,
                        help=f'the ARTWORK2.md section 10 JPEG rule to gate on (default: {SECTION10_RULE!r}, the '
                             'contract as it stands; the others are the candidate amendments)')
    args = parser.parse_args()
    rule = args.section10_rule
    sys.stdout.reconfigure(line_buffering=True)   # keep our lines in order with the tools' output
    started = time.time()
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f'jpeg_tests: Pillow {Image.__version__ if hasattr(Image, "__version__") else "?"}; '
          f'covers from {covers_dir.relative_to(companion)}', flush=True)
    entries, notes = samples(out_dir)
    # 2. ROM work area.
    worst = max(rom_pool_bytes(Path(e['path']).read_bytes()) for e in entries if e['validate'])
    print(f'jpeg_tests: ROM TJpgDec R0.01b work area, worst accepted sample: {worst} of {WORK_BYTES} bytes')
    if worst > WORK_BYTES:
        print('FAIL: an accepted sample needs more than the ROM work area')
        return EXIT_FAIL
    manifest = out_dir / 'manifest.jsonl'
    manifest.write_text(''.join(json.dumps(e) + '\n' for e in entries), encoding='utf-8')
    (out_dir / 'gray.jpg').write_bytes(notes['__gray__'])
    (out_dir / 'cover.jpg').write_bytes(notes['__cover__'])
    # 3. The C++ runner.
    exe = media_tests.compile_runner(out_dir, root / 'jpeg_tests.cpp', 'jpeg_tests.exe')
    if subprocess.run([str(exe), str(manifest), str(out_dir / 'gray.jpg'), str(out_dir / 'cover.jpg')]).returncode:
        return EXIT_FAIL
    # 4. Pixels: the implementation checks on every decoded sample, then the section 10 figure.
    rows = [measure(entry, notes[entry['name']]) for entry in entries if entry['name'] in notes]
    for row in rows:
        mark = 'ok' if row.implementation_ok() else 'FAIL'
        if row.name.startswith('cover-') and row.implementation_ok() and not row.meets(rule):
            mark = 'BELOW-SECTION-10'
        print(f'  {mark} {row.name}: glue {row.mismatches} pixel mismatch(es); decoder vs Pillow {row.decoder:.2f} dB; '
              f'RGB565 vs Pillow + RGB565 rounding {row.rounded:.2f} dB; RGB565 vs Pillow RGB888 {row.unrounded:.2f} dB')
    design = [row for row in rows if row.name.startswith('cover-')]
    option_c = [row for row in rows if row.name.startswith('option-c-444-')]
    if not design or len(option_c) != len(design):
        print('FAIL: no design cover was decoded')
        return EXIT_FAIL
    print(f'jpeg_tests: ARTWORK2.md section 10 JPEG figure over the {len(design)} design covers encoded by the host '
          f'encoder, per rule:')
    for name, text in SECTION10_RULES.items():
        below = [f'{row.name} ({row.figure(name):.2f} dB)' for row in design if not row.meets(name)]
        state = 'met' if not below else 'NOT MET: ' + ', '.join(below)
        print(f'  {"*" if name == rule else " "} {name}: {text}: {state}')
    growth = [notes['__bytes__' + row.name] for row in design]
    increase = [full / host - 1 for host, full, _ in growth]
    print(f'  (report only) candidate amendment C, the host encoder at 4:4:4: worst RGB565 vs Pillow + RGB565 '
          f'rounding {min(row.rounded for row in option_c):.2f} dB, quality '
          f'{"/".join(str(q) for q in sorted({q for _, _, q in growth}))}, '
          f'{min(increase) * 100:.0f}-{max(increase) * 100:.0f} % more bytes than 4:2:0 '
          f'(largest {max(full for _, full, _ in growth)} B); decode time on the knob unmeasured')
    failed = [row.name for row in rows if not row.implementation_ok()]
    if failed:
        print(f'FAIL: glue mismatches, a short image or the decoder below {MIN_PSNR:.0f} dB against Pillow: '
              + ', '.join(failed))
        return EXIT_FAIL
    # 5. The firmware compile line against the real ROM header.
    if not media_tests.firmware_syntax(['cc_jpeg.cpp']):
        return EXIT_FAIL
    accepted = sum(1 for e in entries if e['validate'])
    summary = (f'{len(entries)} sample(s) ({accepted} accepted, {len(entries) - accepted} rejected); glue exact; '
               f'worst decoder PSNR {min(row.decoder for row in rows):.2f} dB; worst ROM work area {worst} B '
               f'[{time.time() - started:.1f} s]')
    below = [row for row in design if not row.meets(rule)]
    if below:
        print(f'SECTION 10 NOT MET (rule {rule!r}: {SECTION10_RULES[rule]}): '
              + ', '.join(f'{row.name} {row.rounded:.2f} dB rounded / {row.unrounded:.2f} dB unrounded reference'
                          for row in below)
              + '. Every implementation check passed; the shortfall is TJpgDec arithmetic, which the firmware cannot '
                'change. A contract decision for the lead (CONTROL_CENTER.md "Validation boundaries"): amend '
                'ARTWORK2.md section 10 (A, B) or the host encoder (C), and set SECTION10_RULE to match. '
                f'Exit {EXIT_SECTION10}; this is not a PASS. ' + summary)
        return EXIT_SECTION10
    print(f'PASS: ARTWORK2.md section 10 rule {rule!r} met; ' + summary)
    return 0


if __name__ == '__main__':
    sys.exit(main())
