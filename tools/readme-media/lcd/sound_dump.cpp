// sound-dump: the knob firmware's click bank (src/audio/cc_sound.h, header-only, compiled unchanged with
// /I <firmware>/src) rendered once, exactly as audio.cpp does at boot, and written out for the README media.
//
//   sound-dump <out-dir>
//
// Writes wood.raw, fine.raw, thud.raw, thump.raw (int16 little-endian mono at CC_SOUND_RATE), the same four as
// 16-bit mono .wav files (so a human can listen), and bank.json {rate, lengths, names, peaks}. No device, no network.
#include "audio/cc_sound.h"

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <string>

namespace {

struct Entry {
    const char* file;
    const char* name;
    uint8_t sound;
};
const Entry ENTRIES[4] = {
    {"wood", "tock", CC_SOUND_WOOD},
    {"fine", "fine click", CC_SOUND_FINE},
    {"thud", "thud", CC_SOUND_THUD},
    {"thump", "thump", CC_SOUND_THUMP},
};

void put16(FILE* f, uint32_t v) { const unsigned char b[2] = {static_cast<unsigned char>(v & 0xFF), static_cast<unsigned char>((v >> 8) & 0xFF)}; std::fwrite(b, 1, 2, f); }
void put32(FILE* f, uint32_t v) { put16(f, v & 0xFFFF); put16(f, v >> 16); }

bool writeRaw(const std::string& path, const int16_t* data, uint16_t n) {
    FILE* f = std::fopen(path.c_str(), "wb");
    if (!f) return false;
    for (uint16_t i = 0; i < n; ++i) put16(f, static_cast<uint16_t>(data[i]));
    std::fclose(f);
    return true;
}

// A canonical 44-byte PCM WAV header: mono, 16-bit, CC_SOUND_RATE.
bool writeWav(const std::string& path, const int16_t* data, uint16_t n) {
    FILE* f = std::fopen(path.c_str(), "wb");
    if (!f) return false;
    const uint32_t bytes = static_cast<uint32_t>(n) * 2u;
    std::fwrite("RIFF", 1, 4, f); put32(f, 36u + bytes); std::fwrite("WAVE", 1, 4, f);
    std::fwrite("fmt ", 1, 4, f); put32(f, 16); put16(f, 1); put16(f, 1);
    put32(f, CC_SOUND_RATE); put32(f, CC_SOUND_RATE * 2u); put16(f, 2); put16(f, 16);
    std::fwrite("data", 1, 4, f); put32(f, bytes);
    for (uint16_t i = 0; i < n; ++i) put16(f, static_cast<uint16_t>(data[i]));
    std::fclose(f);
    return true;
}

}  // namespace

int main(int argc, char** argv) {
    if (argc != 2) {
        std::fprintf(stderr, "usage: sound-dump <out-dir>\n");
        return 2;
    }
    const std::string dir = std::string(argv[1]) + "/";
    static int16_t memory[CC_SOUND_BANK_SAMPLES];
    CCSoundBank bank;
    bank.render(memory);
    std::string lengths, names, peaks;
    for (int i = 0; i < 4; ++i) {
        uint16_t len = 0;
        const int16_t* data = bank.data(ENTRIES[i].sound, len);
        if (!data || !len) { std::fprintf(stderr, "bank has no %s\n", ENTRIES[i].file); return 1; }
        int peak = 0;
        for (uint16_t k = 0; k < len; ++k) { const int a = std::abs(static_cast<int>(data[k])); if (a > peak) peak = a; }
        if (!writeRaw(dir + ENTRIES[i].file + ".raw", data, len) || !writeWav(dir + ENTRIES[i].file + ".wav", data, len)) {
            std::fprintf(stderr, "cannot write into %s\n", argv[1]);
            return 1;
        }
        const std::string sep = i ? ", " : "";
        lengths += sep + "\"" + ENTRIES[i].file + "\": " + std::to_string(len);
        names += sep + "\"" + ENTRIES[i].file + "\": \"" + ENTRIES[i].name + "\"";
        peaks += sep + "\"" + ENTRIES[i].file + "\": " + std::to_string(peak);
        std::printf("%-5s %-10s %4u samples (%.1f ms) peak %5d  -> %s.raw / %s.wav\n", ENTRIES[i].file, ENTRIES[i].name, len,
                    1000.0 * len / CC_SOUND_RATE, peak, ENTRIES[i].file, ENTRIES[i].file);
    }
    FILE* j = std::fopen((dir + "bank.json").c_str(), "wb");
    if (!j) { std::fprintf(stderr, "cannot write bank.json\n"); return 1; }
    std::fprintf(j, "{\"rate\": %u, \"format\": \"int16 LE mono\", \"clip\": %d, \"lengths\": {%s}, \"names\": {%s}, \"peaks\": {%s}}\n",
                 static_cast<unsigned>(CC_SOUND_RATE), static_cast<int>(CC_SOUND_CLIP), lengths.c_str(), names.c_str(), peaks.c_str());
    std::fclose(j);
    std::printf("bank.json: rate %u, %u samples in all\n", static_cast<unsigned>(CC_SOUND_RATE), static_cast<unsigned>(CC_SOUND_BANK_SAMPLES));
    return 0;
}
