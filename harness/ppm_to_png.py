"""Lossless conversion of this harness's RGB PPM output, using only stdlib."""
from pathlib import Path
import struct
import sys
import zlib


def chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))


def convert(path: Path) -> Path:
    magic, dimensions, maximum, data = path.read_bytes().split(b'\n', 3)
    if magic != b'P6' or maximum != b'255':
        raise ValueError('Expected binary RGB PPM with maximum255')
    width, height = map(int, dimensions.split())
    if len(data) != width * height * 3:
        raise ValueError('PPM pixel data length does not match dimensions')
    scanlines = b''.join(b'\0' + data[y * width * 3:(y + 1) * width * 3] for y in range(height))
    png = b'\x89PNG\r\n\x1a\n'
    png += chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
    png += chunk(b'IDAT', zlib.compress(scanlines, 9))
    png += chunk(b'IEND', b'')
    target = path.with_suffix('.png')
    target.write_bytes(png)
    return target


if __name__ == '__main__':
    directory = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / 'rendered'
    for path in sorted(directory.glob('*.ppm')):
        print(convert(path))
