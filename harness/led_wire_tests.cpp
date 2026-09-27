// 1.0.0-cc5.2 LED wire encoder checks. Built by led_wire_tests.py with MSVC /W4 /WX together
// with the unchanged firmware unit ../firmware/src/cc_led_wire.cpp. Written in the
// C++11 subset (the firmware is gnu++11).
//
// Part 1 - timing: the RMT item words must be exactly what FastLED 3.6.0's clockless RMT
// driver produced for the WS2811 chipset (ESP32RMTController's mOne/mZero), recomputed here
// from FastLED's own formulas, not from cc_led_wire.h.
// Part 2 - encoding: MSB first, 8 items per byte, bytes in order, never a partial byte.
// Part 3 - argv[1] (optional) receives pseudo-random frames and their items as JSON lines, so
// led_wire_tests.py can check them against its own independent Python encoder.
// Part 4 (1.0.0-cc5.4, ALIVE.md section 9 step 5) - the wire carries the alive engine's bytes q
// exactly. hmi_thread.cpp writes q into leds/ledsp (cc_ring_address(i, orientation) for the ring,
// kKeyLedPairs for the buttons) and shows with FastLED.setBrightness(255) and
// FastLED.setDither(DISABLE_DITHER). FastLED 3.6.0's output stage (colour adjustment, the
// PixelController's dither and scale8 per byte, the RGB orders) is re-typed below from its
// source; led_wire_tests.py pins every FastLED line used here in .pio/libdeps and the
// hmi_thread.cpp lines this mirrors, so a FastLED or firmware change fails the gate. Checked:
// identity for every byte value, orders and dither phases at brightness 255 with dithering
// disabled; FastLED's binary dither would add up to one count at 255 (why it is disabled rather
// than relied on being gated off below 100 fps); and the real engine (cc_alive.cpp) end to end:
// section 9 output -> the write-out -> FastLED -> cc_led_encode items -> decoded bytes == q, with
// the engine's dither on and, [user 2026-09-26] on its default path (dither off, ALIVE.md 12.7),
// with the F-T floor's bytes included.
#include "cc_led_wire.h"
#include "cc_alive.h"

#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

namespace {
long long checks = 0;
int failures = 0;

void require(bool condition, const std::string& message) {
    ++checks;
    if (!condition) {
        ++failures;
        if (failures <= 40) std::printf("FAIL: %s\n", message.c_str());
    }
}

std::string num(unsigned long long value) {
    char text[32];
    std::snprintf(text, sizeof(text), "%llu", value);
    return text;
}

// ESP32-S3 rmt_item32_t (soc/esp32s3/include/soc/rmt_struct.h), rebuilt for the host.
union HostItem {
    struct {
        unsigned duration0 : 15;
        unsigned level0 : 1;
        unsigned duration1 : 15;
        unsigned level1 : 1;
    } bits;
    unsigned val;
};

// FastLED 3.6.0: C_NS(ns) = (ns * (CLOCKLESS_FREQUENCY / 1000000) + 999) / 1000 CPU cycles
// (CLOCKLESS_FREQUENCY = F_CPU = 240 MHz); WS2811Controller800Khz uses C_NS(320), C_NS(320),
// C_NS(640); ESP_TO_RMT_CYCLES(n) = n / (F_CPU / (APB 80 MHz / DIVIDER 2)).
constexpr unsigned long long kCpuHz = 240000000ULL, kApbHz = 80000000ULL, kDivider = 2;
constexpr unsigned long long cNs(unsigned long long ns) { return (ns * (kCpuHz / 1000000ULL) + 999ULL) / 1000ULL; }
constexpr unsigned long long kRmtPerCpu = kCpuHz / (kApbHz / kDivider);
constexpr unsigned long long kT1 = cNs(320), kT2 = cNs(320), kT3 = cNs(640);

HostItem fastledItem(unsigned long long high, unsigned long long low) {
    HostItem item;
    item.val = 0;
    item.bits.level0 = 1;
    item.bits.duration0 = static_cast<unsigned>(high / kRmtPerCpu) & 0x7FFFu;
    item.bits.level1 = 0;
    item.bits.duration1 = static_cast<unsigned>(low / kRmtPerCpu) & 0x7FFFu;
    return item;
}

void timing() {
    require(kT1 == 77 && kT2 == 77 && kT3 == 154, "FastLED WS2811 cycles T1/T2/T3 = 77/77/154");
    require(kRmtPerCpu == 6, "6 CPU cycles per RMT tick");
    require(CC_LED_RMT_CLK_DIV == kDivider, "RMT clock divider 2 (40 MHz)");
    const HostItem one = fastledItem(kT1 + kT2, kT3), zero = fastledItem(kT1, kT2 + kT3);
    require(CC_LED_ITEM_ONE == one.val, "one item equals FastLED mOne (" + num(one.val) + ")");
    require(CC_LED_ITEM_ZERO == zero.val, "zero item equals FastLED mZero (" + num(zero.val) + ")");
    HostItem mine;
    mine.val = CC_LED_ITEM_ONE;
    require(mine.bits.level0 == 1 && mine.bits.duration0 == 25 && mine.bits.level1 == 0 && mine.bits.duration1 == 25,
            "one = 25 ticks high, 25 low");
    mine.val = CC_LED_ITEM_ZERO;
    require(mine.bits.level0 == 1 && mine.bits.duration0 == 12 && mine.bits.level1 == 0 && mine.bits.duration1 == 38,
            "zero = 12 ticks high, 38 low");
    // 25 ns per tick at 40 MHz.
    const unsigned long long tickPs = 1000000000000ULL / (kApbHz / kDivider);
    require(tickPs == 25000, "25 ns tick");
    require(CC_LED_ONE_HIGH_TICKS * tickPs == 625000 && CC_LED_ONE_LOW_TICKS * tickPs == 625000, "one 625/625 ns");
    require(CC_LED_ZERO_HIGH_TICKS * tickPs == 300000 && CC_LED_ZERO_LOW_TICKS * tickPs == 950000, "zero 300/950 ns");
    require((CC_LED_ONE_HIGH_TICKS + CC_LED_ONE_LOW_TICKS) == (CC_LED_ZERO_HIGH_TICKS + CC_LED_ZERO_LOW_TICKS) &&
            (CC_LED_ONE_HIGH_TICKS + CC_LED_ONE_LOW_TICKS) * tickPs == 1250000, "1.25 us per bit for both values");
    require(cc_led_rmt_item(0x7FFF, 0x7FFF) == 0x7FFFFFFFu, "item layout: level1 (bit 31) is always 0");
    require(cc_led_rmt_item(0, 0) == 0x00008000u, "item layout: level0 is bit 15");
}

std::vector<unsigned> expected(const std::vector<unsigned char>& bytes) {
    std::vector<unsigned> out;
    for (size_t i = 0; i < bytes.size(); ++i)
        for (int bit = 7; bit >= 0; --bit)
            out.push_back(((bytes[i] >> bit) & 1) ? CC_LED_ITEM_ONE : CC_LED_ITEM_ZERO);
    return out;
}

void encoding() {
    const unsigned char samples[] = {0x00, 0xFF, 0xA5, 0x80, 0x01, 0x5A, 0x33};
    for (size_t i = 0; i < sizeof(samples); ++i) {
        uint32_t items[8] = {0};
        const size_t n = cc_led_encode(&samples[i], 1, items, 8);
        require(n == 8, "one byte, 8 items: " + num(samples[i]));
        for (int bit = 0; bit < 8; ++bit) {
            const bool set = ((samples[i] << bit) & 0x80) != 0;
            require(items[bit] == (set ? CC_LED_ITEM_ONE : CC_LED_ITEM_ZERO),
                    "byte " + num(samples[i]) + " bit " + num(static_cast<unsigned>(bit)) + " (MSB first)");
        }
    }
    // A 60-LED ring frame (180 bytes) and the 8 button LEDs (24 bytes).
    const size_t sizes[] = {180, 24};
    for (size_t s = 0; s < 2; ++s) {
        std::vector<unsigned char> bytes(sizes[s]);
        for (size_t i = 0; i < bytes.size(); ++i) bytes[i] = static_cast<unsigned char>((i * 37 + 11) & 0xFF);
        std::vector<uint32_t> items(bytes.size() * 8 + 5, 0xDEADBEEFu);
        const size_t n = cc_led_encode(bytes.data(), bytes.size(), items.data(), bytes.size() * 8);
        require(n == bytes.size() * 8, "frame of " + num(bytes.size()) + " bytes gives " + num(bytes.size() * 8) + " items");
        const std::vector<unsigned> want = expected(bytes);
        bool same = true;
        for (size_t i = 0; i < n; ++i) same = same && items[i] == want[i];
        require(same, "frame of " + num(bytes.size()) + " bytes: items in byte order, MSB first");
        require(items[n] == 0xDEADBEEFu, "nothing written past the frame");
    }
    // Capacity: whole bytes only, never a partial byte; zero-length input.
    unsigned char three[3] = {0xFF, 0x00, 0xFF};
    uint32_t items[24];
    for (size_t i = 0; i < 24; ++i) items[i] = 0xDEADBEEFu;
    require(cc_led_encode(three, 3, items, 23) == 16, "capacity 23 items: two whole bytes (16)");
    require(items[16] == 0xDEADBEEFu, "the third byte is not started");
    require(cc_led_encode(three, 3, items, 7) == 0, "capacity below one byte: nothing");
    require(cc_led_encode(three, 0, items, 24) == 0, "no bytes: nothing");
    require(cc_led_encode(three, 3, items, 24) == 24, "exact capacity: all 24");
}

// xorshift32, deterministic.
uint32_t nextRandom(uint32_t& state) {
    state ^= state << 13;
    state ^= state >> 17;
    state ^= state << 5;
    return state;
}

int dump(const char* path) {
    std::FILE* out = std::fopen(path, "wb");
    if (!out) {
        std::printf("FAIL: cannot write %s\n", path);
        return 1;
    }
    uint32_t state = 0x2545F491u;
    for (int frame = 0; frame < 200; ++frame) {
        const size_t count = 1 + nextRandom(state) % 180;
        std::vector<unsigned char> bytes(count);
        for (size_t i = 0; i < count; ++i) bytes[i] = static_cast<unsigned char>(nextRandom(state) & 0xFF);
        std::vector<uint32_t> items(count * 8);
        const size_t n = cc_led_encode(bytes.data(), count, items.data(), items.size());
        std::fprintf(out, "{\"bytes\":[");
        for (size_t i = 0; i < count; ++i) std::fprintf(out, "%s%u", i ? "," : "", static_cast<unsigned>(bytes[i]));
        std::fprintf(out, "],\"items\":[");
        for (size_t i = 0; i < n; ++i) std::fprintf(out, "%s%lu", i ? "," : "", static_cast<unsigned long>(items[i]));
        std::fprintf(out, "]}\n");
    }
    std::fclose(out);
    return 0;
}
}

// ---------------------------------------------------------------------------------------- Part 4
namespace {
// FastLED 3.6.0's output stage, re-typed from .pio/libdeps/nanofoc_d/FastLED/src (pinned by
// led_wire_tests.py). The ESP32-S3 (Xtensa) is neither __arm__ nor __AVR__, so lib8tion takes its
// "unspecified architecture" branch: SCALE8_C and QADD8_C, with FASTLED_SCALE8_FIXED 1.
namespace fastled {
uint8_t scale8(uint8_t i, uint8_t scale) {            // lib8tion/scale8.h
    return static_cast<uint8_t>((static_cast<uint16_t>(i) * (1 + static_cast<uint16_t>(scale))) >> 8);
}
uint8_t qadd8(uint8_t i, uint8_t j) {                 // lib8tion/math8.h
    unsigned t = static_cast<unsigned>(i) + j;
    if (t > 255) t = 255;
    return static_cast<uint8_t>(t);
}
// color.h UncorrectedColor / UncorrectedTemperature: the CLEDController defaults (the firmware
// never calls setCorrection/setTemperature; led_wire_tests.py checks src/).
const uint8_t kUncorrected[3] = {255, 255, 255};
// controller.h CLEDController::computeAdjustment(scale, colorCorrection, colorTemperature).
void computeAdjustment(uint8_t scale, const uint8_t (&cc)[3], const uint8_t (&ct)[3], uint8_t (&adj)[3]) {
    for (int i = 0; i < 3; ++i) {
        adj[i] = 0;
        if (scale > 0 && cc[i] > 0 && ct[i] > 0) {
            uint32_t work = (static_cast<uint32_t>(cc[i]) + 1) * (static_cast<uint32_t>(ct[i]) + 1) * scale;
            work /= 0x10000L;
            adj[i] = static_cast<uint8_t>(work & 0xFF);
        }
    }
}
// pixeltypes.h EOrder (octal) and controller.h RGB_BYTE(RO, X) = ((RO >> (3 * (2 - X))) & 0x3).
const unsigned kRGB = 0012, kGRB = 0102;
unsigned ro(unsigned order, unsigned slot) { return (order >> (3 * (2 - slot))) & 0x3; }
const uint8_t kDisableDither = 0x00, kBinaryDither = 0x01;   // controller.h
// VIRTUAL_BITS: UPDATES_PER_FULL_DITHER_CYCLE = 400 / 50 = 8 -> (8>1)+(8>2)+(8>4)+(8>8)+... = 3.
const uint8_t kVirtualBits = 3;
uint8_t ditherCounter = 0;                            // init_binary_dithering()'s static R

// PixelController<ORDER> as CCLedController::showPixels() drives it (loadAndScale0/1/2,
// advanceData, stepDithering), for one strip of `count` CRGB (r, g, b) in memory order.
std::vector<uint8_t> showStrip(const std::vector<uint8_t>& rgb, unsigned order, uint8_t brightness,
                               uint8_t ditherMode) {
    uint8_t scale[3], d[3] = {0, 0, 0}, e[3] = {0, 0, 0};
    computeAdjustment(brightness, kUncorrected, kUncorrected, scale);   // getAdjustment(brightness)
    if (ditherMode == kBinaryDither) {                                  // enable_dithering()
        ++ditherCounter;
        ditherCounter &= static_cast<uint8_t>((1 << kVirtualBits) - 1);
        uint8_t q = 0;
        for (int bit = 0; bit < 8; ++bit)
            if (ditherCounter & (1 << bit)) q |= static_cast<uint8_t>(0x80 >> bit);
        q = static_cast<uint8_t>(q + (kVirtualBits < 8 ? (1 << (7 - kVirtualBits)) : 0));   // centre of each range
        for (int i = 0; i < 3; ++i) {
            const uint8_t s = scale[i];
            e[i] = static_cast<uint8_t>(s ? (256 / s) + 1 : 0);
            d[i] = scale8(q, e[i]);
            if (d[i]) --d[i];                                           // FASTLED_SCALE8_FIXED == 1
            if (e[i]) --e[i];
        }
    }
    std::vector<uint8_t> out;
    for (size_t led = 0; led + 3 <= rgb.size(); led += 3) {
        for (unsigned slot = 0; slot < 3; ++slot) {                     // loadAndScale<SLOT>
            const unsigned channel = ro(order, slot);
            uint8_t b = rgb[led + channel];                             // loadByte
            b = b ? qadd8(b, d[channel]) : 0;                           // dither
            out.push_back(scale8(b, scale[channel]));                   // scale
        }
        for (int i = 0; i < 3; ++i) d[i] = static_cast<uint8_t>(e[i] - d[i]);   // stepDithering
    }
    return out;
}
// CFastLED::show(): each controller shows with dithering forced off while m_nFPS < 100.
uint8_t effectiveDither(uint8_t mode, unsigned fps) { return fps < 100 ? kDisableDither : mode; }
}  // namespace fastled

// hmi_thread.cpp's write-out (pinned by led_wire_tests.py): logical ring segment i at
// leds[cc_ring_address(i, orientation)], button slot of raw button i on its LED pair.
const uint8_t kKeyLedPairs[4][2] = {{3, 4}, {2, 5}, {1, 6}, {0, 7}};

// The wire of one frame: FastLED at brightness 255 with DISABLE_DITHER, then cc_led_encode, then
// the items decoded back into bytes (MSB first). Returns ring and button byte streams.
void wireFrame(const uint32_t (&ring)[CC_RING_LEDS], const uint32_t (&buttons)[4], uint8_t orientation,
               const uint8_t (&physicalOf)[4], std::vector<uint8_t>& ringWire, std::vector<uint8_t>& buttonWire) {
    std::vector<uint8_t> leds(CC_RING_LEDS * 3, 0xEE), ledsp(8 * 3, 0xEE);
    for (int i = 0; i < CC_RING_LEDS; ++i) {           // leds[cc_ring_address(i, o)] = CRGB(q)
        const size_t at = static_cast<size_t>(cc_ring_address(i, orientation)) * 3;
        leds[at] = static_cast<uint8_t>((ring[i] >> 16) & 0xFF);
        leds[at + 1] = static_cast<uint8_t>((ring[i] >> 8) & 0xFF);
        leds[at + 2] = static_cast<uint8_t>(ring[i] & 0xFF);
    }
    for (int i = 0; i < 4; ++i) {                      // ledsp[pair] = CRGB(buttons[physical(i)])
        const uint32_t c = buttons[physicalOf[i]];
        for (int k = 0; k < 2; ++k) {
            const size_t at = static_cast<size_t>(kKeyLedPairs[i][k]) * 3;
            ledsp[at] = static_cast<uint8_t>((c >> 16) & 0xFF);
            ledsp[at + 1] = static_cast<uint8_t>((c >> 8) & 0xFF);
            ledsp[at + 2] = static_cast<uint8_t>(c & 0xFF);
        }
    }
    const std::vector<uint8_t>* strips[2] = {&leds, &ledsp};
    const unsigned orders[2] = {fastled::kRGB, fastled::kGRB};   // ringLeds<RGB>, buttonLeds<LED_COL_ORDER = GRB>
    std::vector<uint8_t>* outs[2] = {&ringWire, &buttonWire};
    for (int s = 0; s < 2; ++s) {
        const std::vector<uint8_t> bytes = fastled::showStrip(*strips[s], orders[s], 255, fastled::kDisableDither);
        std::vector<uint32_t> items(bytes.size() * 8);
        const size_t n = cc_led_encode(bytes.data(), bytes.size(), items.data(), items.size());
        outs[s]->assign(n / 8, 0);
        for (size_t i = 0; i < n; ++i)
            if (items[i] == CC_LED_ITEM_ONE) (*outs[s])[i / 8] = static_cast<uint8_t>((*outs[s])[i / 8] | (0x80 >> (i % 8)));
    }
}

// The wire bytes of every LED equal q: ring LED at cc_ring_address(i, o) carries segment i in
// R, G, B order; both LEDs of raw button i carry slot physicalOf[i] in G, R, B order.
bool wireEqualsQ(const uint32_t (&ring)[CC_RING_LEDS], const uint32_t (&buttons)[4], uint8_t orientation,
                 const uint8_t (&physicalOf)[4]) {
    std::vector<uint8_t> ringWire, buttonWire;
    wireFrame(ring, buttons, orientation, physicalOf, ringWire, buttonWire);
    if (ringWire.size() != CC_RING_LEDS * 3 || buttonWire.size() != 8 * 3) return false;
    for (int i = 0; i < CC_RING_LEDS; ++i) {
        const size_t at = static_cast<size_t>(cc_ring_address(i, orientation)) * 3;
        if (ringWire[at] != ((ring[i] >> 16) & 0xFF) || ringWire[at + 1] != ((ring[i] >> 8) & 0xFF) ||
            ringWire[at + 2] != (ring[i] & 0xFF))
            return false;
    }
    for (int i = 0; i < 4; ++i) {
        const uint32_t c = buttons[physicalOf[i]];
        for (int k = 0; k < 2; ++k) {
            const size_t at = static_cast<size_t>(kKeyLedPairs[i][k]) * 3;
            if (buttonWire[at] != ((c >> 8) & 0xFF) || buttonWire[at + 1] != ((c >> 16) & 0xFF) ||
                buttonWire[at + 2] != (c & 0xFF))
                return false;
        }
    }
    return true;
}

void fastledStage() {
    // Brightness 255 with the uncorrected defaults: an adjustment of 255 per channel.
    uint8_t adj[3];
    fastled::computeAdjustment(255, fastled::kUncorrected, fastled::kUncorrected, adj);
    require(adj[0] == 255 && adj[1] == 255 && adj[2] == 255, "getAdjustment(255) == (255, 255, 255)");
    for (int q = 0; q < 256; ++q)
        require(fastled::scale8(static_cast<uint8_t>(q), 255) == q, "scale8(q, 255) == q for q = " + num(static_cast<unsigned>(q)));
    // Identity for every byte value in every slot of both orders, over several shows.
    std::vector<uint8_t> strip(256 * 3);
    for (int k = 0; k < 256; ++k) {
        strip[static_cast<size_t>(k) * 3] = static_cast<uint8_t>(k);
        strip[static_cast<size_t>(k) * 3 + 1] = static_cast<uint8_t>(255 - k);
        strip[static_cast<size_t>(k) * 3 + 2] = static_cast<uint8_t>((k * 7 + 3) & 0xFF);
    }
    const unsigned orders[2] = {fastled::kRGB, fastled::kGRB};
    const char* names[2] = {"RGB", "GRB"};
    bool binaryAdds = false, binaryBounded = true;
    for (int o = 0; o < 2; ++o) {
        for (int show = 0; show < 16; ++show) {
            const std::vector<uint8_t> wire = fastled::showStrip(strip, orders[o], 255, fastled::kDisableDither);
            bool same = wire.size() == strip.size();
            for (size_t led = 0; same && led < 256; ++led)
                for (unsigned slot = 0; slot < 3; ++slot)
                    same = same && wire[led * 3 + slot] == strip[led * 3 + fastled::ro(orders[o], slot)];
            require(same, std::string("DISABLE_DITHER at brightness 255: wire == q, order ") + names[o] + " show " +
                              num(static_cast<unsigned>(show)));
            // FastLED's own gate: BINARY_DITHER stored but m_nFPS < 100 also sends q.
            const std::vector<uint8_t> gated = fastled::showStrip(
                strip, orders[o], 255, fastled::effectiveDither(fastled::kBinaryDither, 60));
            require(gated == wire, std::string("BINARY_DITHER gated off below 100 fps: wire == q, order ") + names[o]);
            // Ungated binary dither at 255 adds 0 or 1 to non-zero bytes: not the identity.
            const std::vector<uint8_t> dithered = fastled::showStrip(strip, orders[o], 255, fastled::kBinaryDither);
            for (size_t led = 0; led < 256; ++led)
                for (unsigned slot = 0; slot < 3; ++slot) {
                    const uint8_t q = strip[led * 3 + fastled::ro(orders[o], slot)];
                    const uint8_t w = dithered[led * 3 + slot];
                    if (w != q) binaryAdds = true;
                    if (q == 0 ? w != 0 : (w < q || w > q + 1)) binaryBounded = false;
                }
        }
    }
    require(binaryAdds, "ungated BINARY_DITHER at 255 is not the identity (why the alive path disables it)");
    require(binaryBounded, "ungated BINARY_DITHER at 255 adds at most one count, never to 0");
}

// xorshift32 in 0..1 (float), deterministic.
float unit(uint32_t& state) { return static_cast<float>(nextRandom(state) % 100001u) / 100000.0f; }

void aliveWire() {
    const uint8_t identity[4] = {0, 1, 2, 3}, swapped[4] = {3, 1, 0, 2};
    // The picks at drive 255, dither off: WARM #FF8424 and AMBER #FF3A0A on the wire. One LED
    // each (the rest dark), so the [D17] power limit does not scale them.
    {
        CCAliveDither residuals;
        std::memset(&residuals, 0, sizeof(residuals));
        uint32_t ring[CC_RING_LEDS], buttons[4];
        CCAliveRingE one;
        CCAliveButtonE dark;
        std::memset(one, 0, sizeof(one));
        std::memset(dark, 0, sizeof(dark));
        for (int c = 0; c < 3; ++c) {
            one[0][c] = CCAliveSpec::warm[c];
            one[1][c] = CCAliveSpec::amber[c];
            dark[0][c] = CCAliveSpec::warm[c];
            dark[1][c] = CCAliveSpec::amber[c];
        }
        cc_alive_output(one, dark, 255, false, residuals, ring, buttons);
        require(ring[0] == 0xFF8424u && ring[1] == 0xFF3A0Au && buttons[0] == 0xFF8424u && buttons[1] == 0xFF3A0Au,
                "section 9 at drive 255, dither off: WARM #FF8424, AMBER #FF3A0A");
        std::vector<uint8_t> ringWire, buttonWire;
        wireFrame(ring, buttons, 0, identity, ringWire, buttonWire);
        const size_t a0 = static_cast<size_t>(cc_ring_address(0, 0)) * 3, a1 = static_cast<size_t>(cc_ring_address(1, 0)) * 3;
        require(ringWire.size() == 180 && ringWire[a0] == 0xFF && ringWire[a0 + 1] == 0x84 && ringWire[a0 + 2] == 0x24 &&
                    ringWire[a1] == 0xFF && ringWire[a1 + 1] == 0x3A && ringWire[a1 + 2] == 0x0A,
                "ring wire (RGB): FF 84 24 and FF 3A 0A");
        // Raw button 0 shows slot 0 on LEDs 3 and 4, raw button 1 slot 1 on LEDs 2 and 5 (GRB).
        require(buttonWire.size() == 24 && buttonWire[9] == 0x84 && buttonWire[10] == 0xFF && buttonWire[11] == 0x24 &&
                    buttonWire[12] == 0x84 && buttonWire[13] == 0xFF && buttonWire[14] == 0x24 &&
                    buttonWire[6] == 0x3A && buttonWire[7] == 0xFF && buttonWire[8] == 0x0A &&
                    buttonWire[15] == 0x3A && buttonWire[16] == 0xFF && buttonWire[17] == 0x0A,
                "button wire (GRB): 84 FF 24 and 3A FF 0A on both LEDs of the pair");
    }
    // Pseudo-random e through section 9 (dither on and off, every drive class, power limit on
    // and off) and the whole write-out, in all four orientations and two button orders.
    uint32_t state = 0x9E3779B9u;
    CCAliveDither residuals;
    std::memset(&residuals, 0, sizeof(residuals));
    int frames = 0;
    bool allSame = true;
    for (int f = 0; f < 400; ++f) {
        CCAliveRingE ringE;
        CCAliveButtonE buttonE;
        const float level = (f % 4 == 0) ? 1.0f : (f % 4 == 1 ? 0.3f : (f % 4 == 2 ? 0.05f : 0.6f));
        for (int i = 0; i < CC_RING_LEDS; ++i)
            for (int c = 0; c < 3; ++c) ringE[i][c] = unit(state) * level;
        for (int j = 0; j < 4; ++j)
            for (int c = 0; c < 3; ++c) buttonE[j][c] = unit(state) * level;
        uint32_t driveValue = 1 + nextRandom(state) % 255u;
        if (f % 5 == 0) driveValue = 255;
        if (f % 5 == 1) driveValue = 150;
        const uint8_t drive = static_cast<uint8_t>(driveValue);
        const bool dither = (f % 3) != 0;
        uint32_t ring[CC_RING_LEDS], buttons[4];
        cc_alive_output(ringE, buttonE, drive, dither, residuals, ring, buttons);
        allSame = allSame && wireEqualsQ(ring, buttons, static_cast<uint8_t>(f & 3), (f & 4) ? swapped : identity);
        ++frames;
    }
    require(allSame, "wire bytes == section 9 bytes q over " + num(static_cast<unsigned>(frames)) +
                         " pseudo-random frames (4 orientations, 2 button orders, dither on/off)");
    // The real engine: power-up (offline marks with the reveal and breath), 3 s of 16 ms frames.
    CCAlive engine;
    engine.reset(0);
    bool engineSame = true, lit = false;
    for (uint32_t t = 0; t <= 3000; t += 16) {
        engine.render(t, nullptr, 0, -1);
        uint32_t ring[CC_RING_LEDS], buttons[4];
        engine.output(150, true, ring, buttons);
        for (int i = 0; i < CC_RING_LEDS; ++i) lit = lit || ring[i] != 0;
        engineSame = engineSame && wireEqualsQ(ring, buttons, static_cast<uint8_t>((t / 16) & 3), identity);
    }
    require(lit, "the offline engine lights its marks within 3 s");
    require(engineSame, "offline engine frames: wire bytes == q (drive 150, dither on)");
    // [user 2026-09-26] (ALIVE.md 9 step 4, 12.7) The engine's default path, as hmi_thread.cpp calls
    // it (ledDither unset: CCAliveSpec::defaultDither, off): the F-T floor keeps the offline marks lit
    // at the dim point of the breath, and those floored bytes reach the wire unchanged too.
    engine.reset(0);
    bool defaultSame = true;
    int floored = 0;
    for (uint32_t t = 0; t <= 6000; t += 16) {
        engine.render(t, nullptr, 0, -1);
        uint32_t ring[CC_RING_LEDS], buttons[4], plain[CC_RING_LEDS], plainButtons[4];
        engine.output(150, CCAliveSpec::defaultDither, ring, buttons);
        CCAliveDither none;
        std::memset(&none, 0, sizeof(none));
        cc_alive_output(engine.ringE(), engine.buttonE(), 150, false, none, plain, plainButtons);   // no floor
        for (int i = 0; i < CC_RING_LEDS; ++i) floored += ring[i] != plain[i] && plain[i] == 0u && ring[i] != 0u;
        defaultSame = defaultSame && wireEqualsQ(ring, buttons, static_cast<uint8_t>((t / 16) & 3), (t & 16) ? swapped : identity);
    }
    require(!CCAliveSpec::defaultDither, "the engine's default is dither off (the 2026-09-26 ruling)");
    require(floored > 100, "the F-T floor lights dark offline marks on the default path (" +
                               num(static_cast<unsigned>(floored)) + " LED-frames)");
    require(defaultSame, "offline engine frames on the default path (dither off, F-T floor): wire bytes == q");
}
}  // namespace

int main(int argc, char** argv) {
    timing();
    encoding();
    fastledStage();
    aliveWire();
    const int dumped = argc > 1 ? dump(argv[1]) : 0;
    std::printf("%s: %lld led-wire check(s), %d failure(s)\n", failures || dumped ? "FAIL" : "PASS", checks, failures);
    return failures || dumped ? 1 : 0;
}
