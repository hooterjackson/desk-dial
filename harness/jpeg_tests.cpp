// artwork2 cover JPEG glue checks (1.0.0-cc5.3). Built by jpeg_tests.py with MSVC /W4 /WX together
// with the unchanged firmware unit ../firmware/src/cc_jpeg.cpp, which reaches LVGL's
// TJpgDec R0.03 through tjpgd_shim/ (the ESP32-S3 ROM TJpgDec API). C++11 subset.
//
// argv[1]: a JSON-lines manifest written by jpeg_tests.py, one sample per line:
//   {"name", "path", "validate": bool, "w": int, "h": int, "decode": bool, "out": path or "",
//    "raw": path or ""}
// For every sample: cc_jpeg_validate must return `validate` and report w x h; cc_jpeg_decode_240
// must return `decode`; a decoded image is written to `out` (240*240 uint16 little-endian) for
// jpeg_tests.py's PSNR check against Pillow, and the decoder's own RGB888 output for the same
// file (the esp_rom_tjpgd API called directly, not through cc_jpeg.cpp) to `raw`, so
// jpeg_tests.py can check the glue's placement and rounding bit for bit. The destination has
// guard words after the 240x240 pixels that must never change. Then direct checks: argument
// rejects, oversize data that would otherwise decode, the flat gray image's exact pixels and
// the decode statistics.
//
// 1.0.0-cc5.4 (PRESENTATION_V5 12.5.4 step 2 and 12.5.7's jpeg case; lead ruling R-f): the abort
// hook, for every decodable sample (band_abort_checks):
//   1. a never-aborting callback is polled once per MCU row, top to bottom, at the row's top pixel
//      row and before any pixel of that row is written, and the result is CC_JPEG_OK and
//      byte-identical to the 3-argument decode;
//   2. an abort at EVERY polled row returns CC_JPEG_ABORTED (TJpgDec's JDR_INTR), leaves the rows
//      above it equal to the clean decode and every row from it on (and the guard words)
//      untouched, counts one decode and no error, leaves msLast / msMax alone, and the next clean
//      decode is byte-identical (the decoder is reusable);
//   3. the flag form cc_jpeg_decode_240(jpeg, bytes, dst, &cancel): false (or a null flag) decodes
//      identically, true aborts before the first pixel;
// and the damaged scan with a never-aborting callback is CC_JPEG_FAILED (one decode, one error).
#include "cc_jpeg.h"
#include <ArduinoJson.h>
#include <esp_rom_tjpgd.h>   // tjpgd_shim: the same decoder API cc_jpeg.cpp uses

#include <algorithm>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

namespace {
long long checks = 0;
int failures = 0;
uint32_t decodeCalls = 0, decodeFailures = 0;
int abortSamples = 0, bandAborts = 0;

void require(bool condition, const std::string& message) {
    ++checks;
    if (!condition) {
        ++failures;
        if (failures <= 60) std::printf("FAIL: %s\n", message.c_str());
    }
}

std::string num(long long value) {
    char text[32];
    std::snprintf(text, sizeof(text), "%lld", value);
    return text;
}

std::vector<uint8_t> read_file(const std::string& path) {
    std::ifstream file(path, std::ios::binary);
    return std::vector<uint8_t>((std::istreambuf_iterator<char>(file)), std::istreambuf_iterator<char>());
}

constexpr uint32_t kPixels = 240 * 240;
constexpr uint32_t kGuard = 64;
constexpr uint16_t kSentinel = 0xBEEF;

// Decodes into a guarded buffer; counts the call for the statistics check.
bool decode(const uint8_t* data, uint32_t bytes, std::vector<uint16_t>& pixels, const std::string& name) {
    pixels.assign(kPixels + kGuard, kSentinel);
    const bool ok = cc_jpeg_decode_240(data, bytes, pixels.data());
    ++decodeCalls;
    if (!ok) ++decodeFailures;
    bool guard = true;
    for (uint32_t i = kPixels; i < kPixels + kGuard; ++i) guard = guard && pixels[i] == kSentinel;
    require(guard, name + ": decode wrote past 240x240 pixels");
    return ok;
}

// The decoder's RGB888 output for a whole 240x240 image, independent of cc_jpeg.cpp.
struct Raw {
    const std::vector<uint8_t>* data;
    uint32_t at;
    std::vector<uint8_t> rgb;
};
uint32_t raw_input(esp_rom_tjpgd_dec_t* dec, uint8_t* buffer, uint32_t count) {
    Raw* raw = static_cast<Raw*>(dec->device);
    const uint32_t left = static_cast<uint32_t>(raw->data->size()) - raw->at;
    if (count > left) count = left;
    if (buffer && count) std::memcpy(buffer, raw->data->data() + raw->at, count);
    raw->at += count;
    return count;
}
uint32_t raw_output(esp_rom_tjpgd_dec_t* dec, void* bitmap, esp_rom_tjpgd_rect_t* rect) {
    Raw* raw = static_cast<Raw*>(dec->device);
    const uint8_t* in = static_cast<const uint8_t*>(bitmap);
    for (uint32_t y = rect->top; y <= rect->bottom; ++y)
        for (uint32_t x = rect->left; x <= rect->right; ++x, in += 3)
            if (x < 240 && y < 240) std::memcpy(&raw->rgb[3 * (y * 240 + x)], in, 3);
    return 1;
}
bool raw_decode(const std::vector<uint8_t>& data, const std::string& path) {
    static uint32_t work[2048];
    static esp_rom_tjpgd_dec_t decoder;
    Raw raw = {&data, 0, std::vector<uint8_t>(3 * kPixels, 0)};
    if (esp_rom_tjpgd_prepare(&decoder, raw_input, work, sizeof(work), &raw) != JDR_OK ||
        esp_rom_tjpgd_decomp(&decoder, raw_output, 0) != JDR_OK) return false;
    std::ofstream file(path, std::ios::binary);
    file.write(reinterpret_cast<const char*>(raw.rgb.data()), static_cast<std::streamsize>(raw.rgb.size()));
    return true;
}

// ---- The abort hook (12.5.4 step 2, R-f) ----------------------------------------------------------
struct Poll {
    std::vector<uint16_t> rows;   // rows polled, in order
    size_t abortAt;               // abort at this poll index (SIZE_MAX: never)
    const uint16_t* dst;          // the destination, to check nothing of the polled row is written yet
    bool rowUntouchedAtPoll;
};

bool on_row(void* context, uint16_t row) {
    Poll* poll = static_cast<Poll*>(context);
    // Between MCU rows: nothing at or below `row` has been written yet.
    for (size_t i = static_cast<size_t>(row) * 240; i < kPixels; ++i)
        if (poll->dst[i] != kSentinel) { poll->rowUntouchedAtPoll = false; break; }
    poll->rows.push_back(row);
    return poll->rows.size() - 1 == poll->abortAt;
}

// One call of the callback form, counted for the statistics check.
CCJpegResult decode_polled(const std::vector<uint8_t>& data, std::vector<uint16_t>& out, Poll& poll) {
    out.assign(kPixels + kGuard, kSentinel);
    poll.dst = out.data();
    const CCJpegResult result = cc_jpeg_decode_240(data.empty() ? nullptr : data.data(),
                                                   static_cast<uint32_t>(data.size()), out.data(), on_row, &poll);
    ++decodeCalls;
    if (result == CC_JPEG_FAILED) ++decodeFailures;
    return result;
}

bool untouched_from(const std::vector<uint16_t>& out, size_t first) {
    for (size_t i = first; i < out.size(); ++i)
        if (out[i] != kSentinel) return false;
    return true;
}

// `reference` is the 3-argument decode of `data` (kPixels + guard words).
void band_abort_checks(const std::string& name, const std::vector<uint8_t>& data,
                       const std::vector<uint16_t>& reference) {
    const uint32_t size = static_cast<uint32_t>(data.size());
    const auto same_pixels = [&reference](const std::vector<uint16_t>& out) {
        return std::equal(out.begin(), out.begin() + kPixels, reference.begin());
    };
    std::vector<uint16_t> out;
    // 1. Never abort: every MCU row polled once, in order, before it is written; identical result.
    Poll all = {{}, static_cast<size_t>(-1), nullptr, true};
    require(decode_polled(data, out, all) == CC_JPEG_OK, name + ": a never-aborting callback decodes OK");
    require(same_pixels(out) && untouched_from(out, kPixels),
            name + ": a never-aborting callback is byte-identical to the 3-argument decode");
    require(all.rowUntouchedAtPoll, name + ": each poll comes before any pixel of its row is written");
    require(!all.rows.empty() && all.rows.front() == 0, name + ": the first poll is row 0");
    const uint16_t pitch = all.rows.size() > 1 ? static_cast<uint16_t>(all.rows[1] - all.rows[0]) : 0;
    require(pitch == 8 || pitch == 16, name + ": polls one MCU row apart (8 or 16 px), got " + num(pitch));
    bool regular = pitch != 0;
    for (size_t k = 0; k < all.rows.size(); ++k) regular = regular && all.rows[k] == k * pitch;
    require(regular && all.rows.size() * pitch >= 240 && (all.rows.size() - 1) * pitch < 240,
            name + ": exactly one poll per MCU row, top to bottom (" + num(static_cast<long long>(all.rows.size())) +
                " polls)");
    if (!regular) return;
    // 2. Abort at every band.
    for (size_t k = 0; k < all.rows.size(); ++k) {
        const CCJpegStats before = cc_jpeg_stats();
        Poll poll = {{}, k, nullptr, true};
        const CCJpegResult result = decode_polled(data, out, poll);
        const CCJpegStats after = cc_jpeg_stats();
        ++bandAborts;
        const std::string where = name + " abort at band " + num(static_cast<long long>(k)) + " (row " +
                                  num(all.rows[k]) + ")";
        require(result == CC_JPEG_ABORTED, where + ": CC_JPEG_ABORTED (JDR_INTR)");
        require(poll.rows.size() == k + 1, where + ": no poll after the abort");
        const size_t split = static_cast<size_t>(all.rows[k]) * 240;
        require(std::equal(out.begin(), out.begin() + static_cast<std::ptrdiff_t>(split), reference.begin()),
                where + ": the rows above the abort equal the clean decode");
        require(untouched_from(out, split), where + ": nothing from the abort row on is written (guard words too)");
        require(after.decodes == before.decodes + 1 && after.errors == before.errors,
                where + ": an abort counts one decode and never an error");
        require(after.msLast == before.msLast && after.msMax == before.msMax,
                where + ": an abort is not a decode time (msLast / msMax unchanged)");
        std::vector<uint16_t> again;
        require(decode(data.data(), size, again, where) && same_pixels(again),
                where + ": the next clean decode is byte-identical (the decoder is reusable)");
    }
    // 3. The flag form (K1 12.5.4 step 2: cc_jpeg_decode_240(jpeg, bytes, dst, &cancel)).
    volatile bool cancel = false;
    out.assign(kPixels + kGuard, kSentinel);
    CCJpegResult flagged = cc_jpeg_decode_240(data.data(), size, out.data(), &cancel);
    ++decodeCalls;
    require(flagged == CC_JPEG_OK && same_pixels(out) && untouched_from(out, kPixels),
            name + ": the flag form, false, decodes identically");
    cancel = true;
    out.assign(kPixels + kGuard, kSentinel);
    flagged = cc_jpeg_decode_240(data.data(), size, out.data(), &cancel);
    ++decodeCalls;
    require(flagged == CC_JPEG_ABORTED && untouched_from(out, 0), name + ": the flag form, true, aborts before the first pixel");
    const volatile bool* none = nullptr;
    out.assign(kPixels + kGuard, kSentinel);
    flagged = cc_jpeg_decode_240(data.data(), size, out.data(), none);
    ++decodeCalls;
    require(flagged == CC_JPEG_OK && same_pixels(out), name + ": a null flag never aborts");
    ++abortSamples;
}

void run_sample(JsonObjectConst sample) {
    const std::string name = sample["name"] | "?";
    const std::vector<uint8_t> data = read_file(sample["path"] | "");
    const uint8_t* bytes = data.empty() ? nullptr : data.data();
    const uint32_t size = static_cast<uint32_t>(data.size());
    uint16_t w = 1, h = 1;
    const bool valid = cc_jpeg_validate(bytes, size, &w, &h);
    require(valid == (sample["validate"] | false),
            name + ": cc_jpeg_validate " + (valid ? "accepted" : "rejected") + " (" + num(w) + "x" + num(h) + ")");
    require(w == (sample["w"] | 0) && h == (sample["h"] | 0),
            name + ": reported " + num(w) + "x" + num(h) + ", expected " + num(sample["w"] | 0) + "x" + num(sample["h"] | 0));
    std::vector<uint16_t> pixels;
    const bool decoded = decode(bytes, size, pixels, name);
    require(decoded == (sample["decode"] | false), name + ": cc_jpeg_decode_240 " + (decoded ? "succeeded" : "failed"));
    if (decoded) {
        band_abort_checks(name, data, pixels);
    } else if (valid) {
        // Accepted but undecodable (a damaged scan): FAILED through the hook too, never ABORTED.
        Poll poll = {{}, static_cast<size_t>(-1), nullptr, true};
        std::vector<uint16_t> out;
        const CCJpegStats before = cc_jpeg_stats();
        const CCJpegResult result = decode_polled(data, out, poll);
        const CCJpegStats after = cc_jpeg_stats();
        require(result == CC_JPEG_FAILED, name + ": a damaged scan with a never-aborting callback is FAILED, not aborted");
        require(after.decodes == before.decodes + 1 && after.errors == before.errors + 1,
                name + ": that failure counts one decode and one error");
    }
    const std::string out = sample["out"] | "";
    if (decoded && !out.empty()) {
        std::ofstream file(out, std::ios::binary);
        for (uint32_t i = 0; i < kPixels; ++i) {
            const char le[2] = {static_cast<char>(pixels[i] & 0xFF), static_cast<char>(pixels[i] >> 8)};
            file.write(le, 2);
        }
        const std::string raw = sample["raw"] | "";
        if (!raw.empty()) require(raw_decode(data, raw), name + ": the decoder API alone failed");
    }
}

void direct_checks(const std::vector<uint8_t>& gray, const std::vector<uint8_t>& cover) {
    uint16_t w = 7, h = 7;
    std::vector<uint16_t> pixels;
    require(!cc_jpeg_validate(nullptr, 100, &w, &h) && w == 0 && h == 0, "validate: no data");
    require(!cc_jpeg_validate(gray.data(), 0, &w, &h), "validate: zero bytes");
    require(!cc_jpeg_validate(gray.data(), 3, &w, &h), "validate: three bytes");
    require(cc_jpeg_validate(gray.data(), static_cast<uint32_t>(gray.size()), nullptr, nullptr), "validate: null w/h");
    require(!decode(nullptr, 100, pixels, "null data"), "decode: no data");
    require(!cc_jpeg_decode_240(gray.data(), static_cast<uint32_t>(gray.size()), nullptr), "decode: no destination");
    ++decodeCalls;
    ++decodeFailures;
    // Oversize: the gray cover grown past 32768 bytes by a comment segment after SOI (it still
    // ends with EOI, and the decoder would skip the segment), then to exactly 32768 bytes.
    const auto padded_to = [&gray](size_t total) -> std::vector<uint8_t> {
        const size_t fill = total - gray.size() - 4;   // FF FE, a 2-byte length, `fill` bytes
        std::vector<uint8_t> out(gray.begin(), gray.begin() + 2);
        out.push_back(0xFF);
        out.push_back(0xFE);
        out.push_back(static_cast<uint8_t>((fill + 2) >> 8));
        out.push_back(static_cast<uint8_t>(fill + 2));
        out.insert(out.end(), fill, 0x20);
        out.insert(out.end(), gray.begin() + 2, gray.end());
        return out;
    };
    std::vector<uint8_t> padded = padded_to(32769);
    require(padded.size() == 32769 && padded[padded.size() - 1] == 0xD9, "a 32769-byte cover ending with EOI");
    require(!cc_jpeg_validate(padded.data(), static_cast<uint32_t>(padded.size()), &w, &h), "validate: 32769 bytes");
    require(!decode(padded.data(), static_cast<uint32_t>(padded.size()), pixels, "padded"), "decode: 32769 bytes");
    padded = padded_to(32768);
    require(cc_jpeg_validate(padded.data(), static_cast<uint32_t>(padded.size()), &w, &h) && w == 240 && h == 240,
            "validate: the same cover padded to exactly 32768 bytes");
    require(decode(padded.data(), static_cast<uint32_t>(padded.size()), pixels, "padded-32768"), "decode: 32768 bytes");
    // EOI must be the last two bytes: a valid cover without it, or with one byte after it.
    std::vector<uint8_t> cut(cover.begin(), cover.end() - 2);
    require(!cc_jpeg_validate(cut.data(), static_cast<uint32_t>(cut.size()), &w, &h), "validate: no EOI");
    require(!decode(cut.data(), static_cast<uint32_t>(cut.size()), pixels, "no EOI"), "decode: no EOI");
    std::vector<uint8_t> trailing(cover);
    trailing.push_back(0x00);
    require(!cc_jpeg_validate(trailing.data(), static_cast<uint32_t>(trailing.size()), &w, &h),
            "validate: a byte after EOI");
    // The flat gray image: every pixel is RGB888 (128,128,128) -> RGB565 with rounding.
    const uint16_t gray565 = static_cast<uint16_t>(((128 * 31 + 127) / 255) << 11 | ((128 * 63 + 127) / 255) << 5 |
                                                   ((128 * 31 + 127) / 255));
    require(gray565 == 0x8410, "RGB565 of 128 gray is 0x8410");
    require(decode(gray.data(), static_cast<uint32_t>(gray.size()), pixels, "gray"), "decode: gray");
    uint32_t off = 0;
    for (uint32_t i = 0; i < kPixels; ++i) off += pixels[i] != gray565;
    require(off == 0, "decode: gray pixels, " + num(off) + " differ from 0x8410");
    // A byte flipped in the SOF0 component count: rejected by the pre-scan like the ROM would.
    std::vector<uint8_t> mutated(gray);
    for (size_t i = 2; i + 9 < mutated.size(); ++i)
        if (mutated[i] == 0xFF && mutated[i + 1] == 0xC0) { mutated[i + 9] = 1; break; }
    require(!cc_jpeg_validate(mutated.data(), static_cast<uint32_t>(mutated.size()), &w, &h), "validate: one component");
    // Statistics: every decode call counted, failures counted, durations recorded.
    const CCJpegStats stats = cc_jpeg_stats();
    require(stats.decodes == decodeCalls, "stats: decodes " + num(stats.decodes) + ", calls " + num(decodeCalls));
    require(stats.errors == decodeFailures, "stats: errors " + num(stats.errors) + ", failures " + num(decodeFailures));
    require(stats.msMax >= stats.msLast && stats.msMax < 5000, "stats: msMax " + num(stats.msMax) + " msLast " + num(stats.msLast));
    std::printf("jpeg_tests: stats decodes %u, errors %u, msMax %u, msLast %u (host timing)\n",
                static_cast<unsigned>(stats.decodes), static_cast<unsigned>(stats.errors),
                static_cast<unsigned>(stats.msMax), static_cast<unsigned>(stats.msLast));
}
}  // namespace

int main(int argc, char** argv) {
    if (argc < 4) {
        std::printf("usage: jpeg_tests manifest.jsonl gray.jpg cover.jpg\n");
        return 2;
    }
    std::ifstream manifest(argv[1]);
    std::string line;
    long long samples = 0;
    while (std::getline(manifest, line)) {
        if (line.empty()) continue;
        JsonDocument doc;
        if (deserializeJson(doc, line)) {
            require(false, "manifest line is not JSON");
            continue;
        }
        run_sample(doc.as<JsonObjectConst>());
        ++samples;
    }
    // The abort hook must have run over the design covers and the variants (24 samples today).
    require(abortSamples >= 10, "the abort hook ran over " + num(abortSamples) + " decodable sample(s), expected >= 10");
    // A null destination fails through the callback form too (never aborts, never crashes).
    require(cc_jpeg_decode_240(nullptr, 0, nullptr, on_row, nullptr) == CC_JPEG_FAILED,
            "the callback form: no data and no destination is FAILED");
    ++decodeCalls;
    ++decodeFailures;
    direct_checks(read_file(argv[2]), read_file(argv[3]));
    std::printf("jpeg_tests: abort hook over %d sample(s): %d band abort(s), each CC_JPEG_ABORTED and reusable\n",
                abortSamples, bandAborts);
    std::printf("jpeg_tests: %lld sample(s), %lld check(s), %d failure(s)\n", samples, checks, failures);
    return failures ? 1 : 0;
}
