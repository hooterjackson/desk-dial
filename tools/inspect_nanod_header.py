from pathlib import Path
import struct
import zlib

data = (Path(__file__).parent / "nanod-flash-read-benchmark.bin").read_bytes()
print("Observed partition entries:")
offset = 0x8000
while data[offset:offset+2] == bytes.fromhex("aa50"):
    magic, kind, subtype, start, size, label, flags = struct.unpack("<HBBII16sI", data[offset:offset+32])
    print(kind, subtype, hex(start), hex(size), label.rstrip(b"\0").decode(), flags)
    offset += 32
print("Observed OTA slots:")
for offset in (0xe000, 0xf000):
    seq, label, state, crc = struct.unpack("<I20sII", data[offset:offset+32])
    print(hex(offset), seq, hex(state), hex(crc), hex(zlib.crc32(struct.pack("<I", seq), 0xffffffff)))
