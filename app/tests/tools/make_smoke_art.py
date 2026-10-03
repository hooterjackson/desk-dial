"""The frozen smoke test's artwork (standalone.SMOKE_ART): a generated, synthetic 120 x 120 RGB565 little-endian
wire image (28,800 bytes), so the release bundle ships no real album cover (audit finding C12-05). A diagonal
colour gradient with a light disc and a dark band, from arithmetic only (no input files, no randomness): the
output is the same bytes on every run. tests/test_bundle_contents.py checks the committed file against it.

Usage (cwd = app): .venv/Scripts/python.exe tests/tools/make_smoke_art.py
"""
from pathlib import Path
import struct

SIZE = 120
OUT = Path(__file__).resolve().parents[2] / "assets" / "smoke" / "smoke-art-120.rgb565"


def smoke_art(size=SIZE):
    data = bytearray()
    for y in range(size):
        for x in range(size):
            r = 40 + (x * 200) // (size - 1)
            g = 30 + ((x + y) * 160) // (2 * (size - 1))
            b = 220 - (y * 180) // (size - 1)
            dx, dy = x - size * 2 // 3, y - size // 3
            if dx * dx + dy * dy <= (size // 6) ** 2:              # a light disc
                r, g, b = 240, 236, 220
            if size * 3 // 4 <= y < size * 3 // 4 + size // 10:   # a dark band
                r, g, b = r // 4, g // 4, b // 4
            data += struct.pack("<H", (r >> 3) << 11 | (g >> 2) << 5 | b >> 3)
    return bytes(data)


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(smoke_art())
    print(f"{OUT} ({OUT.stat().st_size} bytes)")
