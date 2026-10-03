#include "cc_alive.h"
#include <math.h>
#include <string.h>

// "Warm · alive" LED engine (ALIVE.md revision 2). Each part names the design source it
// ports: Ring Choreography v2.dc.html (RC; logic class draw() 267-396, detect() 198-222,
// play() 226-237), knob-model.js (finishAlive() 496-516) and, for the r2 recipes and targets,
// Browse and Snap.dc.html (BS; draw() 597-695, play() 578-586, renderVals() 1232-1333).
// float32 throughout (ESP32-S3 single-precision FPU): f-suffixed literals and
// the float libm entry points only.

namespace {
using namespace CCAliveSpec;

constexpr int kRing = CC_RING_LEDS;
constexpr float kPi = 3.14159265f;
constexpr float kTau = 6.28318531f;
constexpr float kResidue = 1.0f / 1024.0f;   // animating(): damping residue threshold
constexpr uint32_t kSeqMax = 0x7FFFFFFF;     // feedback.seq is 1..0x7FFFFFFF
constexpr uint32_t kDayMs = 86400000u;
constexpr int kVolumeStart = 35;             // k = 0 of the volume arc (fill, drain, boot, 5.1.2)
constexpr int kVolumeSteps = 50;             // seg(50) = 25, the upper bound mark
constexpr int kListPitch = 3;                // 3 segments per list entry (5.1.1)
constexpr int kWindow = CC_RING_WINDOW;      // 20 transmitted entries
constexpr int kTracksPrev[2] = {52, 53}, kTracksNeutral = 0, kTracksNext[2] = {7, 8};

// [D17][R5] The power budget is the warmth test's proven load, exactly: 68 LEDs at the
// user's WARM pick #FF8424 (255 + 132 + 36) at brightness 150 of 255.
static_assert(68 * (255 + 132 + 36) * 150 == 16920 * 255, "B = 68 * (255 + 132 + 36) * 150 / 255 = 16920");
static_assert(powerBudget == 16920.0f, "powerBudget is B = 16920 exactly");
static_assert(CC_RING_LEDS + 4 * buttonLedsPerSlot == 68, "B covers the 60 ring + 8 button LEDs");
static_assert(CC_FX_TYPES == 17, "durations[] / foreground[] cover every effect type");
static_assert(CC_ALIVE_CLASS_F == 13, "the alpha tables cover every class");
static_assert(sizeof(alphaAwakeWarm) / sizeof(alphaAwakeWarm[0]) == CC_ALIVE_CLASS_W + 1, "alpha table size");
static_assert(sizeof(alphaAwakeSemantic) / sizeof(alphaAwakeSemantic[0]) == CC_ALIVE_CLASS_W + 1, "alpha table size");
static_assert(sizeof(alphaResting) / sizeof(alphaResting[0]) == CC_ALIVE_CLASS_W + 1, "alpha table size");
static_assert(arcStart + arcLength - 60 == 23, "the r3 arc ends at 22; 23..37 stay free");

// sRGB EOTF at e = i/256, i = 0..256 (section 9, [D3]); linear interpolation
// between entries stays within 6e-6 of the formula (alive_tests checks 1e-4).
constexpr float kEotf[257] = {
    0.0f, 0.00030234133f, 0.00060468266f, 0.000907024019f, 0.00120936532f, 0.00151170662f,
    0.00181404804f, 0.00211638934f, 0.00241873064f, 0.00272107194f, 0.00302341324f, 0.00333276158f,
    0.00366063463f, 0.00400659069f, 0.0043709036f, 0.00475384202f, 0.00515566859f, 0.0055766399f,
    0.0060170088f, 0.00647702208f, 0.00695692282f, 0.00745694898f, 0.00797733571f, 0.0085183112f,
    0.00908010453f, 0.00966293644f, 0.0102670267f, 0.0108925914f, 0.0115398439f, 0.0122089926f,
    0.0129002454f, 0.0136138061f, 0.014349875f, 0.0151086506f, 0.0158903282f, 0.0166951027f,
    0.0175231658f, 0.018374702f, 0.0192499012f, 0.0201489478f, 0.0210720226f, 0.0220193062f,
    0.0229909755f, 0.0239872076f, 0.0250081774f, 0.0260540564f, 0.0271250159f, 0.0282212235f,
    0.0293428488f, 0.0304900557f, 0.031663008f, 0.0328618698f, 0.0340868011f, 0.0353379622f,
    0.0366155095f, 0.0379196033f, 0.0392503925f, 0.0406080373f, 0.0419926867f, 0.0434044898f,
    0.0448436067f, 0.0463101752f, 0.0478043482f, 0.0493262708f, 0.0508760884f, 0.0524539463f,
    0.054059986f, 0.0556943528f, 0.0573571846f, 0.0590486191f, 0.0607688017f, 0.0625178665f,
    0.0642959476f, 0.0661031827f, 0.0679397136f, 0.0698056668f, 0.0717011765f, 0.0736263767f,
    0.0755814016f, 0.0775663704f, 0.0795814246f, 0.0816266909f, 0.083702296f, 0.0858083665f,
    0.0879450217f, 0.090112403f, 0.0923106223f, 0.0945398137f, 0.0968000889f, 0.099091582f,
    0.101414405f, 0.103768691f, 0.106154546f, 0.108572103f, 0.111021474f, 0.113502778f,
    0.116016135f, 0.118561663f, 0.121139474f, 0.123749681f, 0.126392409f, 0.129067779f,
    0.131775886f, 0.13451685f, 0.137290791f, 0.140097812f, 0.142938033f, 0.145811558f,
    0.148718506f, 0.151658982f, 0.154633105f, 0.157640964f, 0.160682678f, 0.163758352f,
    0.166868106f, 0.170012042f, 0.173190251f, 0.176402852f, 0.179649964f, 0.182931662f,
    0.186248064f, 0.18959929f, 0.192985415f, 0.196406573f, 0.199862838f, 0.203354329f,
    0.206881136f, 0.210443377f, 0.214041144f, 0.217674524f, 0.221343651f, 0.225048587f,
    0.228789449f, 0.232566342f, 0.236379355f, 0.240228593f, 0.244114146f, 0.248036116f,
    0.25199461f, 0.255989701f, 0.260021478f, 0.264090091f, 0.26819557f, 0.272338063f,
    0.27651763f, 0.28073436f, 0.284988374f, 0.289279789f, 0.293608636f, 0.297975034f,
    0.302379072f, 0.306820869f, 0.311300486f, 0.315818012f, 0.320373565f, 0.324967206f,
    0.329599053f, 0.334269196f, 0.338977695f, 0.343724668f, 0.348510206f, 0.353334367f,
    0.358197242f, 0.363098979f, 0.368039578f, 0.373019189f, 0.3780379f, 0.383095771f,
    0.388192892f, 0.393329352f, 0.398505241f, 0.403720647f, 0.408975661f, 0.414270341f,
    0.419604808f, 0.42497912f, 0.430393398f, 0.43584767f, 0.441342086f, 0.446876675f,
    0.452451527f, 0.458066761f, 0.463722408f, 0.469418615f, 0.475155413f, 0.480932921f,
    0.486751169f, 0.492610306f, 0.498510361f, 0.504451394f, 0.510433614f, 0.516456962f,
    0.522521555f, 0.528627515f, 0.534774899f, 0.540963769f, 0.547194183f, 0.55346632f,
    0.55978018f, 0.566135824f, 0.572533369f, 0.578972936f, 0.585454524f, 0.591978252f,
    0.59854418f, 0.605152369f, 0.611802936f, 0.618495941f, 0.625231504f, 0.632009625f,
    0.638830423f, 0.645694017f, 0.652600408f, 0.659549654f, 0.666541934f, 0.673577249f,
    0.680655658f, 0.687777281f, 0.694942236f, 0.702150464f, 0.709402204f, 0.716697395f,
    0.724036157f, 0.73141855f, 0.738844693f, 0.746314645f, 0.753828466f, 0.761386216f,
    0.768988013f, 0.776633859f, 0.784323871f, 0.79205817f, 0.799836755f, 0.807659686f,
    0.815527081f, 0.823439002f, 0.831395507f, 0.839396715f, 0.847442627f, 0.855533361f,
    0.863668978f, 0.871849597f, 0.880075157f, 0.888345838f, 0.896661699f, 0.9050228f,
    0.913429141f, 0.921880901f, 0.930378139f, 0.938920856f, 0.94750911f, 0.956143081f,
    0.964822769f, 0.973548234f, 0.982319534f, 0.991136789f, 1.0f
};

// ---- design helpers (Ring Choreography v2 lines 99-105 = BS 459-465), float32 --------
float cl(float x) { return x < 0.0f ? 0.0f : (x > 1.0f ? 1.0f : x); }
float eo(float u) {
    const float v = 1.0f - cl(u);
    return 1.0f - v * v * v;
}
float eio(float u) {
    u = cl(u);
    if (u < 0.5f) return 4.0f * u * u * u;
    const float v = -2.0f * u + 2.0f;
    return 1.0f - v * v * v / 2.0f;
}
float gs(float x, float w) { return expf(-x * x / (2.0f * w * w)); }
float bump(float ms, float a, float b) { return ms < a || ms > b ? 0.0f : sinf(kPi * (ms - a) / (b - a)); }
float fmax2(float a, float b) { return a > b ? a : b; }
float fmin2(float a, float b) { return a < b ? a : b; }
int iabs(int x) { return x < 0 ? -x : x; }
int isign(int x) { return x > 0 ? 1 : (x < 0 ? -1 : 0); }
int iclamp(int x, int lo, int hi) { return x < lo ? lo : (x > hi ? hi : x); }
// md / cd on integers: C++11 % truncates toward zero, exactly like the JS remainder.
int mdi(int i) { return ((i % kRing) + kRing) % kRing; }
int cdi(int i, int j) { return ((((i - j) % kRing) + 90) % kRing) - 30; }
// Integer-modulo phase in [0, 1) [D11].
float phase(uint32_t t, uint32_t period) { return static_cast<float>(t % period) / static_cast<float>(period); }
float decay(float dt, float tau) { return 1.0f - expf(-dt / tau); }

float channel(uint32_t rgb, int shift) { return static_cast<float>((rgb >> shift) & 255u) / 255.0f; }
void unpack(uint32_t rgb, float (&c)[3]) {
    c[0] = channel(rgb, 16);
    c[1] = channel(rgb, 8);
    c[2] = channel(rgb, 0);
}
void copy3(const float (&src)[3], float (&dst)[3]) {
    dst[0] = src[0];
    dst[1] = src[1];
    dst[2] = src[2];
}

// The colour a target draws with (0..1): the palette's for the palette roles [R5],
// rgb / 255 for ACCENT (the sat() colour; also the oracles' explicit colours).
void cellColour(const CCAliveCell& cell, const CCAlivePalette& p, float (&c)[3]) {
    switch (cell.role) {
        case CC_ALIVE_ROLE_WARM: copy3(p.warm, c); break;
        case CC_ALIVE_ROLE_GREEN: copy3(p.green, c); break;
        case CC_ALIVE_ROLE_RED: copy3(p.red, c); break;
        case CC_ALIVE_ROLE_AMBER: copy3(p.amber, c); break;
        case CC_ALIVE_ROLE_BLUE: copy3(p.blue, c); break;
        case CC_ALIVE_ROLE_PINK: copy3(p.pink, c); break;
        default: unpack(cell.rgb, c); break;
    }
}

// Tone map soft knee (design line 371).
void tone(float (&e)[3]) {
    const float mx = fmax2(fmax2(e[0], e[1]), e[2]);
    if (mx <= toneKnee) return;
    const float k = (toneKnee + toneRange * (1.0f - expf(-(mx - toneKnee) / toneRange))) / mx;
    e[0] *= k;
    e[1] *= k;
    e[2] *= k;
}

CCAliveCell dark() {
    CCAliveCell c;
    c.rgb = 0;
    c.alpha = 0.0f;
    c.cls = CC_ALIVE_CLASS_NONE;
    c.role = CC_ALIVE_ROLE_NONE;
    c.volRed = false;
    return c;
}

CCAliveCell lit(uint32_t rgb, uint8_t role, uint8_t cls, float alpha) {
    CCAliveCell c;
    c.rgb = rgb;
    c.alpha = alpha;
    c.cls = cls;
    c.role = role;
    c.volRed = false;
    return c;
}

// put(i, ...) overwrites ring[i mod 60] (P4 5.1); the alpha is assigned afterwards (5.2).
void put(CCAliveTargets& out, int i, uint8_t role, uint8_t cls, uint32_t rgb = 0) {
    out.ring[mdi(i)] = lit(role == CC_ALIVE_ROLE_ACCENT ? rgb : 0u, role, cls, 0.0f);
}

// 5.1.1 The transmitted window as the parser kept it (P4 section 4): a present first that
// contains the host frame's index, else V4's derivation (colours and mask only when it is 0).
struct ListInfo {
    int first, width, colorCount, more;
    uint32_t mask;
};

ListInfo list_info(const CCFrame& f, int index) {
    const int count = f.ringCount, given = f.ringFirst;
    ListInfo li;
    li.first = given;
    bool relative = true;
    if (!(given <= index && index < given + kWindow && (count > kWindow || given == 0))) {
        li.first = cc_window_first(static_cast<uint16_t>(index), f.ringCount);
        relative = false;
    }
    li.width = count - li.first;
    if (li.width > kWindow) li.width = kWindow;
    if (li.width < 0) li.width = 0;
    li.colorCount = relative ? f.ringColorCount : 0;
    if (li.colorCount > li.width) li.colorCount = 0;
    for (int k = 0; k < li.colorCount; ++k)
        if (f.ringColors[k] > 0xFFFFFFu) li.colorCount = 0;
    li.mask = relative && f.ringUnavailable < (1u << li.width) ? f.ringUnavailable : 0u;
    li.more = f.ringMoreIndex >= -1 && f.ringMoreIndex <= count - 1 ? static_cast<int>(f.ringMoreIndex) : -1;
    return li;
}

// 5.1.1 acc(j): 0 = WARM (white LEDs, More, colour absent or 0, a sat() fallback), else the
// sat() colour (role ACCENT; sat() never returns 0: its max channel is 255).
uint32_t list_accent(const CCFrame& f, const ListInfo& li, int more, int j) {
    const int k = j - li.first;
    if (!f.coloredLeds || j == more || k < 0 || k >= li.colorCount || f.ringColors[k] == 0) return 0;
    bool accent = false;
    const uint32_t s = cc_alive_sat(f.ringColors[k], accent);
    return accent ? s : 0u;
}

uint8_t pulse_class(uint32_t pendingMs) {           // 5.1.8
    if (pendingMs >= CCLed::pendingHoldMs) return CC_ALIVE_CLASS_1;
    return ((pendingMs / CCLed::pulseMs) & 1u) ? CC_ALIVE_CLASS_1 : CC_ALIVE_CLASS_3;
}

// [M2] col(k, x): RED if x >= 90 and k >= 45; AMBER if x >= 80 and k >= 40; else WARM.
uint8_t volume_role(int k, int x, bool colour) {
    if (!colour) return CC_ALIVE_ROLE_WARM;
    if (x >= 90 && k >= 45) return CC_ALIVE_ROLE_RED;
    if (x >= 80 && k >= 40) return CC_ALIVE_ROLE_AMBER;
    return CC_ALIVE_ROLE_WARM;
}

// 5.1.2 [M1, M2, M13] with the displayed value v. Returns the cursor.
int draw_volume(const CCFrame& f, int v, CCAliveTargets& out) {
    const int c = f.confirmedVolume <= 100 ? f.confirmedVolume : (f.ringValue <= 100 ? f.ringValue : 0);
    const bool colour = f.coloredLeds;
    if (f.activity == CC_OFFLINE) {                  // [D15] the confirmed endpoint only (M13 placement)
        put(out, kVolumeStart + c / 2, CC_ALIVE_ROLE_WARM, CC_ALIVE_CLASS_1);
        return mdi(kVolumeStart + c / 2);
    }
    const int e = v / 2, n = (v + 1) / 2, nc = (c + 1) / 2;
    put(out, kVolumeStart, CC_ALIVE_ROLE_WARM, CC_ALIVE_CLASS_1);                 // 1. bounds
    put(out, kVolumeStart + kVolumeSteps, CC_ALIVE_ROLE_WARM, CC_ALIVE_CLASS_1);
    for (int k = 0; k <= n; ++k)                                                  // 2. body
        put(out, kVolumeStart + k, volume_role(k, v, colour), k <= nc ? CC_ALIVE_CLASS_2 : CC_ALIVE_CLASS_1);
    for (int k = n + 1; k <= nc; ++k)                                             // 3. pending decrease
        put(out, kVolumeStart + k, volume_role(k, c, colour), CC_ALIVE_CLASS_1);
    if (v & 1)                                                                    // 4. [M13] half-step
        put(out, kVolumeStart + e + 1, volume_role(e + 1, v, colour), CC_ALIVE_CLASS_S);
    put(out, kVolumeStart + e, volume_role(e, v, colour),                         // 5. endpoint
        f.ringExternal ? CC_ALIVE_CLASS_4 : CC_ALIVE_CLASS_3);
    return mdi(kVolumeStart + e);
}

// 5.1.1, 5.1.3 (lists) and 5.1.4 (Up next). `localIndex` >= 0: the local position, which the window
// re-centres on [M15] (the frame keeps the host's index and window). `out` null: only the selected
// accent. Returns the cursor; *selected = acc(index) (0 = WARM or none) when non-null.
int draw_selection(const CCFrame& f, int32_t localIndex, uint32_t pendingMs, CCAliveTargets* out,
                   uint32_t* selected) {
    if (selected) *selected = 0;
    const int count = f.ringCount;
    if (f.activity == CC_LOADING || count == 0) return 0;          // [M31] the comet only
    const int hostIndex = f.ringIndex;
    const int index = localIndex >= 0 ? static_cast<int>(localIndex) : hostIndex;
    if (!(hostIndex < count) || !(index < count)) return 0;         // the parsers reject this
    const bool upnext = f.layoutId == CC_LAYOUT_UPNEXT;
    const ListInfo li = list_info(f, hostIndex);
    const int more = upnext ? -1 : li.more;
    const uint32_t mask = upnext ? 0u : li.mask;                   // K1 strips it on upnext (P5-R24)
    const int now = upnext && f.ringNow >= -1 && f.ringNow < count ? static_cast<int>(f.ringNow) : -1;
    const bool card = upnext && f.ringCard && count >= 2;
    int winFirst = li.first, winWidth = li.width;
    if (localIndex >= 0 && count > kWindow) {                      // [M15] re-centre on the local index
        winFirst = iclamp(index - 10, 0, count - kWindow);
        winWidth = kWindow;
    }
    const int c0 = winFirst + (winWidth - 1) / 2;                  // [M9]
    const int cursor = mdi((index - c0) * kListPitch);
    const bool cursorCard = card && index == count - 1;
    const bool cursorSent = index >= li.first && index < li.first + li.width;
    const uint32_t cursorAccent = cursorSent && !cursorCard ? list_accent(f, li, more, index) : 0u;
    if (selected) *selected = cursorAccent;
    if (!out) return cursor;
    for (int j = winFirst; j < winFirst + winWidth; ++j) {         // landmarks; unavailable = a gap
        const int k = j - li.first;
        if (k < 0 || k >= li.width || (card && j == count - 1) || ((mask >> k) & 1u)) continue;
        const uint32_t rgb = list_accent(f, li, more, j);
        const uint8_t cls = upnext ? (j < now ? CC_ALIVE_CLASS_P : (j == now ? CC_ALIVE_CLASS_N : CC_ALIVE_CLASS_Q))
                                   : CC_ALIVE_CLASS_1;
        put(*out, (j - c0) * kListPitch, rgb ? CC_ALIVE_ROLE_ACCENT : CC_ALIVE_ROLE_WARM, cls, rgb);
    }
    if (cursorCard) return cursor;                                 // [M14] the card: no cursor cell
    uint8_t cls = CC_ALIVE_CLASS_3;                                // [M15] untransmitted: WARM class 3
    if (cursorSent && index != more && ((mask >> (index - li.first)) & 1u)) cls = CC_ALIVE_CLASS_Q;   // [M3]
    if (f.activity == CC_PENDING) cls = pulse_class(pendingMs);    // 5.1.8 in its colour [M3][D13]
    put(*out, cursor, cursorAccent ? CC_ALIVE_ROLE_ACCENT : CC_ALIVE_ROLE_WARM, cls, cursorAccent);
    return cursor;
}

// 5.1.5 (P4 5.4, always WARM): index 0 Prev (cursor 52, [M4]), 1 Neutral, 2 Next; bit0 = no Prev.
int draw_transport(const CCFrame& f, int index, uint32_t pendingMs, CCAliveTargets& out) {
    if (f.ringCount != 3 || index < 0 || index > 2) return 0;
    const bool noPrev = ((f.ringUnavailable <= 7u ? f.ringUnavailable : 0u) & 1u) != 0;
    if (!noPrev)
        for (int i : kTracksPrev) put(out, i, CC_ALIVE_ROLE_WARM, CC_ALIVE_CLASS_1);
    put(out, kTracksNeutral, CC_ALIVE_ROLE_WARM, CC_ALIVE_CLASS_1);
    for (int i : kTracksNext) put(out, i, CC_ALIVE_ROLE_WARM, CC_ALIVE_CLASS_1);
    const int* pair = kTracksPrev;
    int cells = 2, cursor = kTracksPrev[0];
    if (index == 0) {
        if (!noPrev)
            for (int i : kTracksPrev) put(out, i, CC_ALIVE_ROLE_WARM, CC_ALIVE_CLASS_3);
    } else if (index == 2) {
        pair = kTracksNext;
        cursor = kTracksNext[1];
        for (int i : kTracksNext) put(out, i, CC_ALIVE_ROLE_WARM, CC_ALIVE_CLASS_3);
    } else {
        pair = &kTracksNeutral;
        cells = 1;
        cursor = kTracksNeutral;
        put(out, kTracksNeutral, CC_ALIVE_ROLE_WARM, CC_ALIVE_CLASS_2);
    }
    if (f.activity == CC_PENDING)                                  // the selected cells pulse
        for (int k = 0; k < cells; ++k) put(out, pair[k], CC_ALIVE_ROLE_WARM, pulse_class(pendingMs));
    return cursor;
}

// 5.1.6 [r2] the Seek lap: played 0.62, every 5th unplayed 0.30, head 1.0, all WARM, no pulse.
int draw_lap(const CCFrame& f, CCAliveTargets& out) {
    const uint32_t t = f.ringIndex, d = f.ringCount ? f.ringCount : 1u;
    uint32_t head = t * 60u / d;
    if (head > 59u) head = 59u;
    const int h = static_cast<int>(head);
    for (int k = 0; k < kRing; ++k) {
        if (k < h) put(out, k, CC_ALIVE_ROLE_WARM, CC_ALIVE_CLASS_2);
        else if (k > h && k % lapTick == 0) put(out, k, CC_ALIVE_ROLE_WARM, CC_ALIVE_CLASS_1);
    }
    put(out, h, CC_ALIVE_ROLE_WARM, CC_ALIVE_CLASS_3);
    return h;
}

// [r3] 15.2 the Lights arc: segment of arc position k (0..44).
int arc_segment(int k) { return mdi(arcStart + k); }

// [r3] 15.2 bri: the arc filled to n = round(45 v / 100) segments in the Kelvin colour (ACCENT, never sat()),
// class 3 (1.0) while turning (layout lightsbig) else L (0.34); the rest OFF ([user 2026-09-29]; class T unused). Cursor: the last filled
// segment (arc position 0 when n == 0).
int draw_bri(const CCFrame& f, int v, bool turning, CCAliveTargets& out) {
    const uint32_t rgb = cc_kelvin_rgb(f.ringKelvin);
    const int n = (v * arcLength + 50) / 100;
    // [user 2026-09-29] (ALIVE.md 15.2) the unfilled arc is OFF: no track (0.08 drifted to olive on the LEDs).
    for (int k = 0; k < n && k < arcLength; ++k)
        put(out, arc_segment(k), CC_ALIVE_ROLE_ACCENT, turning ? CC_ALIVE_CLASS_3 : CC_ALIVE_CLASS_L, rgb);
    return arc_segment(n > 0 ? n - 1 : 0);
}

// [r3] 15.2 ctemp: the whole arc in the selected Kelvin colour; marker m = round(44 value / 100) class 3 (1.0),
// below it class 3 while turning else F (0.50), above it OFF ([user 2026-09-29]; class R unused). Cursor: the marker.
int draw_ctemp(const CCFrame& f, bool turning, CCAliveTargets& out) {
    const uint32_t rgb = cc_kelvin_rgb(f.ringKelvin);
    const int v = f.ringValue <= 100 ? f.ringValue : 100;
    const int m = (v * (arcLength - 1) + 50) / 100;
    // [user 2026-09-29] (ALIVE.md 15.2) the remainder above the marker is OFF (0.12 drifted to olive).
    for (int k = 0; k <= m; ++k)
        put(out, arc_segment(k), CC_ALIVE_ROLE_ACCENT,
            k == m || turning ? CC_ALIVE_CLASS_3 : CC_ALIVE_CLASS_F, rgb);
    return arc_segment(m);
}

// [r3] 15.2 clusters: N (1..20) clusters of 3 segments around centres round(60 s / N) of the whole ring (wrapping
// at 0), WARM; the selected one class 3 (1.0) drawn last, the others O (0.18). Cursor: the selected centre.
int draw_clusters(const CCFrame& f, int index, CCAliveTargets& out) {
    const int n = f.ringCount;
    if (n < 1 || n > CC_CLUSTERS_MAX || index < 0 || index >= n) return 0;
    int selected = 0;
    for (int c = 0; c < n; ++c) {
        const int centre = (120 * c + n) / (2 * n);
        if (c == index) {
            selected = centre;
            continue;
        }
        for (int k = -1; k <= 1; ++k) put(out, centre + k, CC_ALIVE_ROLE_WARM, CC_ALIVE_CLASS_O);
    }
    for (int k = -1; k <= 1; ++k) put(out, selected + k, CC_ALIVE_ROLE_WARM, CC_ALIVE_CLASS_3);
    return mdi(selected);
}

// [r3] 15.7 marker: a white marker +-1 (ACCENT class 3) at pos = round(44 index / max(1, count - 1)) (half up);
// the rest of the arc is OFF ([user 2026-10-03], like the Lights arcs and the queue ring: no sub-floor dim
// segments; the design's rest class M, WARM 0.10, is not drawn; CC_ALIVE_CLASS_M stays in the enum, unused).
// Cursor: the marker's centre.
int draw_marker(const CCFrame& f, int index, CCAliveTargets& out) {
    const int n = f.ringCount;
    if (n < 1 || index < 0 || index >= n) return 0;
    const int span = n - 1 > 1 ? n - 1 : 1;
    const int pos = (2 * index * (arcLength - 1) + span) / (2 * span);
    for (int k = pos - 1; k <= pos + 1; ++k)
        if (k >= 0 && k < arcLength) put(out, arc_segment(k), CC_ALIVE_ROLE_ACCENT, CC_ALIVE_CLASS_3, markerRgb);
    return arc_segment(pos);
}

// [r3.1] 15.9 queue (the whole-queue Tracks and Up next; r3.1 prototype R.queue): row j sits at arc position
// round(44 j / max(1, count - 1)). The playing row (`now`) is one warm-white segment (queueNowRgb, class W 0.60),
// the focus (the local index while turning) +-1 in its row's album colour (sat(); WARM without one) at class 3,
// over it. The rest of the arc is OFF ([user 2026-09-29]: no sub-floor dim segments; the design's 0.10).
int draw_queue(const CCFrame& f, int index, CCAliveTargets& out) {
    const int n = f.ringCount;
    if (n < 1 || index < 0 || index >= n || !(f.ringIndex < n)) return 0;
    const int span = n - 1 > 1 ? n - 1 : 1;
    const int pos = (2 * index * (arcLength - 1) + span) / (2 * span);
    if (f.ringNow >= 0 && f.ringNow < n) {
        const int now = static_cast<int>(f.ringNow);
        put(out, arc_segment((2 * now * (arcLength - 1) + span) / (2 * span)), CC_ALIVE_ROLE_ACCENT,
            CC_ALIVE_CLASS_W, queueNowRgb);
    }
    const ListInfo li = list_info(f, f.ringIndex);
    const uint32_t acc = list_accent(f, li, -1, index);
    for (int k = pos - 1; k <= pos + 1; ++k)
        if (k >= 0 && k < arcLength)
            put(out, arc_segment(k), acc ? CC_ALIVE_ROLE_ACCENT : CC_ALIVE_ROLE_WARM, CC_ALIVE_CLASS_3, acc);
    return arc_segment(pos);
}

// 5.2: the alpha of a lit (role, class) target.
float ring_alpha(uint8_t role, uint8_t cls, bool asleep, bool volFull) {
    if (asleep) return alphaResting[cls];
    if (role == CC_ALIVE_ROLE_WARM) return alphaAwakeWarm[cls];
    if (volFull && (cls == CC_ALIVE_CLASS_2 || cls == CC_ALIVE_CLASS_S)) return alphaVolFull;
    return alphaAwakeSemantic[cls];
}

// 5.3 [r2][M18]: the tone of button `j` (first match wins). pausedPlay is set by row 9.
CCAliveCell button_target(const CCFrame& f, uint8_t j, uint8_t family, bool& pausedPlay) {
    const CCButton& b = f.buttons[j];
    const uint8_t icon = cc_button_icon(b);
    if (icon == CC_ICON_NONE) return dark();                                            // 1
    if (!b.enabled) return lit(0, CC_ALIVE_ROLE_WARM, CC_ALIVE_CLASS_1, buttonDim);     // 2
    if (j == 0 && icon == CC_ICON_CANCEL) return lit(0, CC_ALIVE_ROLE_RED, CC_ALIVE_CLASS_2, buttonStop);   // 3
    if (b.lit == CC_LIT_ON) {
        // 4 [r2.2][M32] tone `liked`: PINK 0.30, never sat() [M25]; rests WARM 0.04 below.
        if (icon == CC_ICON_HEART) return lit(0, CC_ALIVE_ROLE_PINK, CC_ALIVE_CLASS_1, buttonLiked);
        bool accent = false;
        const uint32_t s = b.color && f.coloredLeds ? cc_alive_sat(b.color & 0xFFFFFFu, accent) : 0u;
        if (accent) return lit(s, CC_ALIVE_ROLE_ACCENT, CC_ALIVE_CLASS_3, buttonOn);   // 5 VOC-D02
        // 6; [r3] (15.4, 15.7) the active mode at 0.90 in LIGHTS and on every r3 screen (a crumb).
        return lit(0, CC_ALIVE_ROLE_WARM, CC_ALIVE_CLASS_3,
                   family == CC_ALIVE_LIGHTS || f.crumb != CC_CRUMB_NONE ? buttonActive : buttonOn);
    }
    if (b.lit == CC_LIT_OFF) return lit(0, CC_ALIVE_ROLE_WARM, CC_ALIVE_CLASS_1, buttonOff);   // 7
    if (j == 3 && (icon == CC_ICON_PLAY || icon == CC_ICON_PREV || icon == CC_ICON_NEXT || icon == CC_ICON_SWITCH))
        return lit(0, CC_ALIVE_ROLE_GREEN, CC_ALIVE_CLASS_3, buttonGo);                 // 8
    if (family == CC_ALIVE_HOME && j == 0 && icon == CC_ICON_PLAY) {                    // 9 [M8]
        pausedPlay = true;
        return lit(0, CC_ALIVE_ROLE_GREEN, CC_ALIVE_CLASS_3, buttonGo);
    }
    return lit(0, CC_ALIVE_ROLE_WARM, CC_ALIVE_CLASS_2, buttonNav);                     // 10
}

void flash_put(CCAliveTargets& out, int i, uint8_t role, float alpha) {
    out.ring[mdi(i)] = lit(0, role, CC_ALIVE_CLASS_4, alpha);
}
} // namespace

// ------------------------------------------------------------------ helpers
CCAliveEffect cc_alive_effect(uint8_t type, uint32_t t0) {
    CCAliveEffect e;
    memset(&e, 0, sizeof(e));
    e.type = type;
    e.t0 = t0;
    return e;
}

float cc_alive_js_round(float x) { return floorf(x + 0.5f); }

int cc_alive_md(float i) { return mdi(static_cast<int>(cc_alive_js_round(i))); }

float cc_alive_cd(float i, float j) { return fmodf(fmodf(i - j, 60.0f) + 90.0f, 60.0f) - 30.0f; }

uint32_t cc_alive_sat(uint32_t rgb, bool& accent) {
    const int c[3] = {static_cast<int>((rgb >> 16) & 255u), static_cast<int>((rgb >> 8) & 255u),
                      static_cast<int>(rgb & 255u)};
    int mx = c[0], mn = c[0];
    for (int k = 1; k < 3; ++k) {
        if (c[k] > mx) mx = c[k];
        if (c[k] < mn) mn = c[k];
    }
    if (mx - mn < satMinSpread) {                         // the WARM fallback: a role, not a value
        accent = false;
        return 0;
    }
    // round(max(0, x - 0.75 mn) / (mx - 0.75 mn) * 255), half away from zero, in
    // exact integers (x4): (2 * 255 * num + den) / (2 * den).
    const int den = 4 * mx - 3 * mn;
    uint32_t out = 0;
    for (int k = 0; k < 3; ++k) {
        int num = 4 * c[k] - 3 * mn;
        if (num < 0) num = 0;
        out = (out << 8) | static_cast<uint32_t>((2 * 255 * num + den) / (2 * den));
    }
    accent = true;
    return out;
}

uint8_t cc_alive_family(const CCFrame& f) {
    switch (f.layoutId) {                                 // [r2] 5.4, VOC 1.1: every layout explicitly
        case CC_LAYOUT_NOW_PLAYING:
        case CC_LAYOUT_VOLUME:
        case CC_LAYOUT_IDLE:
        case CC_LAYOUT_NOTICE: return CC_ALIVE_HOME;
        case CC_LAYOUT_RECENT: return CC_ALIVE_RECENT;
        case CC_LAYOUT_EXPLORER: return CC_ALIVE_EXPLORER;
        case CC_LAYOUT_TRACKS:
        case CC_LAYOUT_SEEK: return CC_ALIVE_TRACKS;
        case CC_LAYOUT_UPNEXT: return CC_ALIVE_UPNEXT;
        case CC_LAYOUT_WINDOWS: return CC_ALIVE_WINDOWS;
        case CC_LAYOUT_LIGHTS:
        case CC_LAYOUT_LIGHTSBIG:
        case CC_LAYOUT_SCENES: return CC_ALIVE_LIGHTS;   // [r3] 15.1
        default: return CC_ALIVE_HOME;                    // unreachable: the parser rejects other tokens
    }
}

uint8_t cc_alive_displayed_volume(const CCFrame& f, int32_t localValue) {
    if (localValue >= 0) return static_cast<uint8_t>(localValue <= 100 ? localValue : 100);
    return f.ringValue <= 100 ? f.ringValue : 0;
}

bool cc_alive_pending(const CCFrame& f, int32_t localValue) {
    if (f.activity == CC_PENDING || f.activity == CC_LOADING) return true;
    // [R1] activity offline (the Home Sonos-off notice, [D15]) is never pending: its ring draws
    // only the confirmed endpoint, so a stale request there never runs the Working comet.
    if (cc_alive_family(f) != CC_ALIVE_HOME || f.ringStyle != CC_RING_LEVEL || f.activity == CC_OFFLINE) return false;
    const uint8_t v = cc_alive_displayed_volume(f, localValue);
    const uint8_t c = f.confirmedVolume <= 100 ? f.confirmedVolume : cc_alive_displayed_volume(f);
    return v != c;
}

bool cc_alive_local(const CCFrame& frame, int32_t localPos, int32_t localMax, int32_t& value, int32_t& index) {
    value = index = -1;
    if (localMax < 0) return false;
    const int32_t pos = localPos < 0 ? 0 : (localPos > localMax ? localMax : localPos);
    switch (frame.ringStyle) {
        case CC_RING_LEVEL:
            if (localMax == 100 && frame.layoutId != CC_LAYOUT_NOTICE && frame.activity != CC_OFFLINE) value = pos;
            return value >= 0;
        case CC_RING_SELECTION:
            if (frame.ringCount >= 1 && localMax == static_cast<int32_t>(frame.ringCount) - 1 &&
                frame.activity != CC_PENDING && frame.activity != CC_LOADING) index = pos;
            return index >= 0;
        case CC_RING_TRANSPORT:
            if (localMax == 2 && frame.activity != CC_PENDING) index = pos;
            return index >= 0;
        case CC_RING_BRI:                                 // [r3] 15.6: the brightness profile
            // DD-DES-003: two frames. Off: 0..100, 0 = off. On: 0..99 = 1..100 % (the wall at the 1 % floor).
            if (localMax == 100) value = pos;
            else if (localMax == 99) value = pos + 1;
            return value >= 0;
        case CC_RING_CLUSTERS:                            // [r3] 15.6: the scenes list (max count - 1)
        case CC_RING_MARKER:                              // [r3] 15.7: the r3 Windows list (max count - 1)
        case CC_RING_QUEUE:                               // [r3.1] 15.9: the queue (max count - 1)
            if (frame.ringCount >= 1 && localMax == static_cast<int32_t>(frame.ringCount) - 1 &&
                frame.activity != CC_PENDING && frame.activity != CC_LOADING) index = pos;
            return index >= 0;
        default:                                          // off, [M11] never the lap, [r3] never ctemp
            return false;
    }
}

bool cc_alive_apply_local(const CCFrame& frame, int32_t localPos, int32_t localMax, CCFrame& out) {
    out = frame;
    int32_t value = -1, index = -1;
    if (!cc_alive_local(frame, localPos, localMax, value, index)) return false;
    if (value >= 0) out.ringValue = static_cast<uint8_t>(value);   // level and [r3] bri
    if (index >= 0) out.ringIndex = static_cast<uint16_t>(index);
    return true;
}

uint32_t cc_alive_selected_color(const CCFrame& f, int32_t localIndex) {
    if (f.ringStyle != CC_RING_SELECTION) return 0;
    uint32_t selected = 0;
    draw_selection(f, localIndex, 0, nullptr, &selected);
    return selected;
}

float cc_alive_tod_brightness(float hour) {
    if (!(hour > 0.0f)) hour = 0.0f;
    if (hour > 24.0f) hour = 24.0f;
    int i = 0;                                   // design warmAt(): while (i < 6 && h > H[i + 1]) i++
    while (i < 6 && hour > todHours[i + 1]) ++i;
    const float k = cl((hour - todHours[i]) / (todHours[i + 1] - todHours[i]));
    return todFactors[i] + (todFactors[i + 1] - todFactors[i]) * k;
}

CCAlivePalette cc_alive_palette() {
    CCAlivePalette p;
    copy3(CCAliveSpec::warm, p.warm);
    copy3(CCAliveSpec::hot, p.hot);
    copy3(CCAliveSpec::green, p.green);
    copy3(CCAliveSpec::red, p.red);
    copy3(CCAliveSpec::amber, p.amber);
    copy3(CCAliveSpec::blue, p.blue);
    copy3(CCAliveSpec::pink, p.pink);
    return p;
}

void cc_alive_pink(uint32_t ledPink, float (&out)[3]) {
    if (!(ledPink & 0xFFFFFFu)) {
        copy3(CCAliveSpec::pink, out);
        return;
    }
    for (int q = 0; q < 3; ++q) {                         // the sRGB OETF (section 2 derivation)
        const float c = channel(ledPink, 16 - 8 * q);
        out[q] = c <= 0.0031308f ? 12.92f * c : 1.055f * powf(c, 1.0f / 2.4f) - 0.055f;
    }
}

uint32_t cc_alive_xorshift32(uint32_t x) {
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    return x;
}

// float(x >> 8) is exact (24 bits); * 60 rounds once; * 2^-24 is exact: the correctly rounded
// float of 60 (x >> 8) / 2^24, i.e. the contract's double evaluation stored as float32.
float cc_alive_scatter_seed(uint32_t x) {
    return static_cast<float>(x >> 8) * 60.0f * (1.0f / 16777216.0f);
}

// ------------------------------------------------------------------ targets
// Sections 5.1-5.4 (revision 2: the alive geometry drawn directly).
void cc_alive_targets(const CCFrame* frame, const CCAliveTargetState& state, CCAliveTargets& out) {
    for (int i = 0; i < kRing; ++i) out.ring[i] = dark();
    for (int j = 0; j < 4; ++j) out.buttons[j] = dark();
    out.family = CC_ALIVE_OFFLINE;
    out.style = CC_RING_OFF;
    out.cursor = 0;
    out.asleep = false;
    out.offline = state.offline;
    out.pending = out.heat = out.pausedPlay = out.tintOn = false;
    out.tint[0] = out.tint[1] = out.tint[2] = 0.0f;
    out.songProg = -1.0f;
    out.todB = 1.0f;
    if (state.offline) {                                  // 5.2 offline override; buttons off
        for (int i = 0; i < kRing; i += offlinePitch)
            out.ring[i] = lit(0, CC_ALIVE_ROLE_AMBER, CC_ALIVE_CLASS_1, alphaOffline);
        return;
    }
    if (!frame) return;
    const CCFrame& f = *frame;
    const bool asleep = state.asleep;
    out.family = cc_alive_family(f);
    out.style = f.ringStyle;
    out.asleep = asleep;
    out.pending = cc_alive_pending(f, state.localValue);
    const uint8_t volume = cc_alive_displayed_volume(f, state.localValue);
    int cursor = 0;
    switch (f.ringStyle) {                                // 5.1
        case CC_RING_LEVEL: cursor = draw_volume(f, volume, out); break;
        case CC_RING_SELECTION: cursor = draw_selection(f, state.localIndex, state.pendingMs, &out, nullptr); break;
        case CC_RING_TRANSPORT:
            cursor = draw_transport(f, state.localIndex >= 0 ? static_cast<int>(state.localIndex) : f.ringIndex,
                                    state.pendingMs, out);
            break;
        case CC_RING_LAP: cursor = draw_lap(f, out); break;
        // [r3] 15.2: turning = the lightsbig reveal (the host shows it while the knob turns, 1.4 s after).
        case CC_RING_BRI:
            cursor = draw_bri(f, state.localValue >= 0 ? static_cast<int>(state.localValue <= 100 ? state.localValue : 100)
                                                       : (f.ringValue <= 100 ? f.ringValue : 100),
                              f.layoutId == CC_LAYOUT_LIGHTSBIG, out);
            break;
        case CC_RING_CTEMP: cursor = draw_ctemp(f, f.layoutId == CC_LAYOUT_LIGHTSBIG, out); break;
        case CC_RING_CLUSTERS:
            cursor = draw_clusters(f, state.localIndex >= 0 ? static_cast<int>(state.localIndex) : f.ringIndex, out);
            break;
        case CC_RING_MARKER:                              // [r3] 15.7
            cursor = draw_marker(f, state.localIndex >= 0 ? static_cast<int>(state.localIndex) : f.ringIndex, out);
            break;
        case CC_RING_QUEUE:                               // [r3.1] 15.9
            cursor = draw_queue(f, state.localIndex >= 0 ? static_cast<int>(state.localIndex) : f.ringIndex, out);
            break;
        default: break;                                   // 5.1.7 off: dark, cursor 0
    }
    out.cursor = static_cast<uint8_t>(cursor);
    for (int i = 0; i < kRing; ++i) {                     // 5.2 alphas; resting: WARM
        CCAliveCell& c = out.ring[i];
        if (c.cls == CC_ALIVE_CLASS_NONE) continue;
        if (asleep) c = lit(0, CC_ALIVE_ROLE_WARM, c.cls, alphaResting[c.cls]);
        else c.alpha = ring_alpha(c.role, c.cls, false, state.volFull);
    }
    // 5.2 overrides, in order.
    if (!asleep && out.family == CC_ALIVE_HOME && f.ringExternal)
        for (int k = -1; k <= 1; ++k) flash_put(out, cursor + k, CC_ALIVE_ROLE_BLUE, alphaOverride);
    if (state.flash == CC_FLASH_OK || state.flash == CC_FLASH_ERR) {
        const bool ok = state.flash == CC_FLASH_OK;
        for (int k = -2; k <= 2; ++k)
            flash_put(out, cursor + k, ok ? CC_ALIVE_ROLE_GREEN : CC_ALIVE_ROLE_RED,
                      iabs(k) == 2 ? alphaFlashEdge : alphaOverride);
    } else if (state.flash == CC_FLASH_WASH) {            // [r3] 15.5 LIGHTS ok: the whole ring GREEN 0.68
        for (int i = 0; i < kRing; ++i) flash_put(out, i, CC_ALIVE_ROLE_GREEN, lightsWashAlpha);
    } else if (state.flash == CC_FLASH_REFUSED) {         // [r3] 15.7 / r4 3.4 the deny glow: bottom 255,60,40 0.9
        for (int i = refusedFirst; i <= refusedLast; ++i)
            out.ring[i] = lit(refusedRgb, CC_ALIVE_ROLE_ACCENT, CC_ALIVE_CLASS_4, refusedAlpha);
    } else if (state.flash == CC_FLASH_HOME) {            // [r3] 15.7 the matured hold: the ring WARM 0.68
        for (int i = 0; i < kRing; ++i) flash_put(out, i, CC_ALIVE_ROLE_WARM, homeFlashAlpha);
    } else if (state.flash == CC_FLASH_LAND) {            // r4 M12: the landing is the engine's sweep, no wash
    } else if (state.flash == CC_FLASH_QUEUE) {           // [r3.1] 15.8 the queue landing: the ring GREEN 0.68
        for (int i = 0; i < kRing; ++i) flash_put(out, i, CC_ALIVE_ROLE_GREEN, landFlashAlpha);
    }
    if (state.holdFill > 0) {                            // [r3] 15.7 the hold-1 progress ring replaces the ring
        for (int i = 0; i < kRing; ++i) out.ring[i] = dark();
        for (int k = 0; k < state.holdFill && k < arcLength; ++k)
            flash_put(out, arc_segment(k), CC_ALIVE_ROLE_WARM, 1.0f);
    }
    for (int i = 0; i < kRing; ++i)
        out.ring[i].volRed = out.ring[i].cls != CC_ALIVE_CLASS_NONE && out.ring[i].role == CC_ALIVE_ROLE_RED;
    out.heat = out.family == CC_ALIVE_HOME && !asleep && f.ringStyle == CC_RING_LEVEL && volume >= 90;
    // 5.3 buttons [M18].
    bool pausedPlay = false;
    for (uint8_t j = 0; j < 4; ++j) {
        CCAliveCell b = button_target(f, j, out.family, pausedPlay);
        if (asleep && b.cls != CC_ALIVE_CLASS_NONE)
            b = lit(0, CC_ALIVE_ROLE_WARM, b.cls, b.alpha >= buttonRestSplit ? buttonRestHigh : buttonRestLow);
        out.buttons[j] = b;
    }
    out.pausedPlay = pausedPlay && !asleep;
    // 5.4 tint: the cursor's accent while browsing a list family, awake. [R2] Only an ACCENT
    // cursor tints: a sat() that fell back to WARM, a flash, the Up next card (no cell) give none.
    // FW-BUG-024: no tint while a flash override owns the ring (the deny glow's cells are ACCENT).
    const CCAliveCell& at = out.ring[cursor];
    const bool flashFree = state.flash == CC_FLASH_NONE || state.flash == CC_FLASH_LAND;
    const bool list = out.family == CC_ALIVE_RECENT || out.family == CC_ALIVE_EXPLORER ||
                      out.family == CC_ALIVE_UPNEXT || out.family == CC_ALIVE_WINDOWS;
    if (list && flashFree && !asleep && f.ringStyle != CC_RING_MARKER && f.ringStyle != CC_RING_QUEUE && at.cls != CC_ALIVE_CLASS_NONE &&
        at.role == CC_ALIVE_ROLE_ACCENT) {                // [r3] 15.7: never the white marker; [r3.1] nor the queue
        out.tintOn = true;
        unpack(at.rgb, out.tint);
    }
}

// ------------------------------------------------------------------ animator
CCAliveAnimator::CCAliveAnimator() : reducedMotion_(false) {
    reset();
}

void CCAliveAnimator::reset() {
    for (int i = 0; i < kRing; ++i) {
        cur_[i].r = 1.0f;
        cur_[i].g = 0.64f;
        cur_[i].b = 0.33f;
        cur_[i].a = 0.0f;
    }
    for (int j = 0; j < 4; ++j) bcur_[j] = cur_[0];
    tint_[0] = tint_[1] = tint_[2] = 0.0f;
    memset(fx_, 0, sizeof(fx_));
    count_ = 0;
    evictions_ = 0;
    memset(snap_, 0, sizeof(snap_));
    memset(bsnap_, 0, sizeof(bsnap_));
    memset(m_, 0, sizeof(m_));
    memset(bm_, 0, sizeof(bm_));
    memset(o_, 0, sizeof(o_));
    memset(ob_, 0, sizeof(ob_));
    animating_ = false;
}

void CCAliveAnimator::remove(uint8_t index) {
    for (uint8_t k = index; k + 1 < count_; ++k) fx_[k] = fx_[k + 1];
    --count_;
}

// A snapshot slot no queued 'down' holds. play() evicts before it pushes, so at
// most queueCapacity - 1 effects are queued here and a free slot always exists:
// every down keeps its own snapshot until it ends, as the design's e.snap does.
uint8_t CCAliveAnimator::freeSnapshot() const {
    bool used[queueCapacity] = {};
    for (uint8_t k = 0; k < count_; ++k)
        if (fx_[k].type == CC_FX_DOWN && fx_[k].snap < queueCapacity) used[fx_[k].snap] = true;
    for (uint8_t s = 0; s < queueCapacity; ++s)
        if (!used[s]) return s;
    return 0;                                             // unreachable (count_ < queueCapacity)
}

// play() (RC lines 226-237; BS 578-586 for the reduced-motion drop) plus the [D12] queue cap.
bool CCAliveAnimator::play(const CCAliveEffect& effect) {
    if (effect.type >= CC_FX_TYPES) return false;
    if (reducedMotion_ && (effect.type == CC_FX_WAKE || effect.type == CC_FX_TICK || effect.type == CC_FX_SWEEP ||
                           effect.type == CC_FX_SCATTER || effect.type == CC_FX_REVEAL))
        return false;                                     // [r2][M17] 6.5: not queued, kills nothing
    CCAliveEffect e = effect;
    e.killed = false;
    e.kill = 0;
    if (foreground[e.type]) {
        for (uint8_t k = 0; k < count_; ++k)
            if (foreground[fx_[k].type] && !fx_[k].killed) {
                fx_[k].killed = true;
                fx_[k].kill = e.t0;
            }
    } else if (e.type == CC_FX_WAKE || e.type == CC_FX_REVEAL || e.type == CC_FX_BOUND) {
        for (uint8_t k = count_; k-- > 0;)
            if (fx_[k].type == e.type) remove(k);
    }
    if (count_ >= queueCapacity) {                        // oldest killed, tick, press, else oldest
        int victim = -1;
        for (uint8_t k = 0; k < count_ && victim < 0; ++k) if (fx_[k].killed) victim = k;
        for (uint8_t k = 0; k < count_ && victim < 0; ++k) if (fx_[k].type == CC_FX_TICK) victim = k;
        for (uint8_t k = 0; k < count_ && victim < 0; ++k) if (fx_[k].type == CC_FX_PRESS) victim = k;
        remove(static_cast<uint8_t>(victim < 0 ? 0 : victim));
        ++evictions_;
    }
    if (e.type == CC_FX_DOWN) {                           // snap = cur * a (design line 231)
        e.snap = freeSnapshot();
        for (int i = 0; i < kRing; ++i) {
            snap_[e.snap][i][0] = cur_[i].r * cur_[i].a;
            snap_[e.snap][i][1] = cur_[i].g * cur_[i].a;
            snap_[e.snap][i][2] = cur_[i].b * cur_[i].a;
        }
        for (int j = 0; j < 4; ++j) {
            bsnap_[e.snap][j][0] = bcur_[j].r * bcur_[j].a;
            bsnap_[e.snap][j][1] = bcur_[j].g * bcur_[j].a;
            bsnap_[e.snap][j][2] = bcur_[j].b * bcur_[j].a;
        }
    }
    fx_[count_++] = e;
    return true;
}

// add(): ignores a <= 0.001 (design line 301).
void CCAliveAnimator::add(int i, const float* c, float a) {
    if (a <= 0.001f) return;
    float* o = o_[mdi(i)];
    o[0] += c[0] * a;
    o[1] += c[1] * a;
    o[2] += c[2] * a;
}

void CCAliveAnimator::addAt(float i, const float* c, float a) {
    if (a <= 0.001f) return;
    float* o = o_[cc_alive_md(i)];
    o[0] += c[0] * a;
    o[1] += c[1] * a;
    o[2] += c[2] * a;
}

// addG(): floor(pos - 3w) .. ceil(pos + 3w) (line 302). a <= 0.001 skips every
// splat (gs <= 1), so the exponentials are not evaluated then.
void CCAliveAnimator::addG(float pos, float w, const float* c, float a) {
    if (a <= 0.001f) return;
    const int lo = static_cast<int>(floorf(pos - 3.0f * w)), hi = static_cast<int>(ceilf(pos + 3.0f * w));
    for (int k = lo; k <= hi; ++k) add(k, c, a * gs(static_cast<float>(k) - pos, w));
}

void CCAliveAnimator::addB(int j, const float* c, float a) {
    if (j < 0 || j > 3) return;
    float* o = ob_[j];
    o[0] += c[0] * a;
    o[1] += c[1] * a;
    o[2] += c[2] * a;
}

// comet(): gaussian w 0.7, alpha a * (1 - k/(len+1))^1.7 (line 304).
void CCAliveAnimator::comet(float head, float dir, int len, const float* c0, const float* c1, float a) {
    for (int k = 0; k <= len; ++k)
        addG(head - dir * static_cast<float>(k), 0.7f, k ? c1 : c0,
             a * powf(1.0f - static_cast<float>(k) / static_cast<float>(len + 1), 1.7f));
}

// One effect of the draw() filter/switch (RC lines 318-360; BS 640-660). false = drop it.
bool CCAliveAnimator::draw(CCAliveEffect& e, uint32_t t, const CCAlivePalette& p, float& duck) {
    const float ms = static_cast<float>(static_cast<int32_t>(t - e.t0));
    const float dur = static_cast<float>(durations[e.type]);
    const float u = ms / dur;
    if (u > 1.0f) return false;
    float amp = 1.0f;
    if (e.killed) {
        amp = 1.0f - static_cast<float>(static_cast<int32_t>(t - e.kill)) / killFadeMs;
        if (amp <= 0.0f) return false;
    }
    const float at = e.at;
    const bool atInt = at == floorf(at) && at > -1.0e6f && at < 1.0e6f;
    const int atI = atInt ? static_cast<int>(at) : 0;
    const float* warmC = p.warm;
    const float* hotC = p.hot;
    if (foreground[e.type] && e.type != CC_FX_BOOT && e.type != CC_FX_DOWN)
        duck = fmax2(duck, duckDepth * sinf(kPi * u) * amp);
    switch (e.type) {
        case CC_FX_BOOT: {
            if (ms < 1000.0f)
                comet(60.0f * eio(ms / 900.0f), 1.0f, 14, hotC, warmC,
                      0.95f * (ms < 900.0f ? 1.0f : 1.0f - (ms - 900.0f) / 100.0f) * amp);
            const float b = bump(ms, 850.0f, 1450.0f);
            if (b != 0.0f)
                for (int i = 0; i < kRing; ++i) add(i, warmC, 0.22f * b * amp);
            for (int i = 0; i < kRing; ++i) {
                const float o = e.home ? static_cast<float>(mdi(i - kVolumeStart))
                                       : static_cast<float>(iabs(cdi(i, 0)) * 2);
                m_[i] *= cl((ms - 1250.0f - o * 11.0f) / 160.0f);
            }
            for (int j = 0; j < 4; ++j) {
                const float s0 = 1850.0f + static_cast<float>(j) * 100.0f;
                bm_[j] *= cl((ms - s0) / 200.0f);
                addB(j, hotC, 0.45f * bump(ms, s0, s0 + 240.0f));
            }
            break;                                        // the LCD fade is omitted [D6]
        }
        case CC_FX_DOWN: {                                // [M19] RC's recipe (S02 section 7)
            const uint8_t slot = e.snap < queueCapacity ? e.snap : 0;   // always its own (play())
            const float (&sn)[CC_RING_LEDS][3] = snap_[slot];
            for (int i = 0; i < kRing; ++i) {
                const int o = cc_alive_md(static_cast<float>(i) - at);
                const float st = 80.0f + static_cast<float>(60 - o) * 10.0f;
                m_[i] *= static_cast<float>(i) == at ? 0.0f
                         : cl((ms - 1250.0f - static_cast<float>(iabs(cdi(i, 0))) * 12.0f) / 200.0f);
                if (o == 0) {
                    add(i, sn[i], (1.0f - cl((ms - 700.0f) / 500.0f)) * amp);
                    add(i, warmC, 0.35f * bump(ms, 500.0f, 1250.0f) * amp);
                } else {
                    add(i, sn[i], (1.0f - cl((ms - st) / 110.0f)) * amp);
                }
            }
            for (int j = 0; j < 4; ++j) {
                bm_[j] = 0.0f;
                addB(j, bsnap_[slot][j],
                     1.0f - cl((ms - 120.0f - static_cast<float>(3 - j) * 80.0f) / 160.0f));
            }
            break;
        }
        case CC_FX_WAKE: {
            const float d = eo(u) * 30.0f;
            for (int i = 0; i < kRing; ++i) {
                const float x = atInt ? static_cast<float>(iabs(cdi(i, atI))) : fabsf(cc_alive_cd(static_cast<float>(i), at));
                add(i, hotC, 0.32f * (1.0f - u) * gs(x - d, 3.0f) * amp);
            }
            break;
        }
        case CC_FX_TICK: {
            addAt(at, hotC, 0.45f * (1.0f - u) * (1.0f - u) * amp);
            for (int k = 1; k <= e.len; ++k) {
                const float q = 1.0f - static_cast<float>(k) / static_cast<float>(e.len + 1);
                addAt(at - static_cast<float>(e.dir * k), warmC, 0.38f * q * sqrtf(q) * (1.0f - u) * amp);
            }
            break;
        }
        case CC_FX_BOUND: {
            addAt(at, e.c, 0.8f * (1.0f - u) * (1.0f - u) * amp);
            for (int k = 1; k <= 4; ++k) {
                const float a0 = static_cast<float>((4 - k) * 30);
                addAt(at - static_cast<float>(e.dir * k), e.c,
                      0.5f * (1.0f - static_cast<float>(k) / 5.0f) * bump(ms, a0, a0 + 260.0f) * amp);
            }
            break;
        }
        case CC_FX_PENDING:
            comet(ms / 1400.0f * 60.0f + at, 1.0f, 8, hotC, warmC,
                  0.5f * fmin2(1.0f, fmin2(ms / 200.0f, (dur - ms) / 200.0f)));
            break;
        case CC_FX_BLOOM: {                               // RC:349 / BS:656: the colour is e.c
            const float d = eo(u / 0.8f) * 30.0f;
            const float trail = 1.0f - u;
            for (int i = 0; i < kRing; ++i) {
                const float x = atInt ? static_cast<float>(iabs(cdi(i, atI))) : fabsf(cc_alive_cd(static_cast<float>(i), at));
                add(i, e.c, 0.9f * (1.0f - u * 0.5f) * gs(x - d, 1.5f) * amp);
                if (x < d) add(i, e.c, 0.16f * trail * sqrtf(trail) * amp);
            }
            float spark[3];                               // mix(c, white, 0.3)
            for (int q = 0; q < 3; ++q) spark[q] = e.c[q] + (1.0f - e.c[q]) * 0.3f;
            addG(at + 30.0f, 1.0f, spark, 0.8f * bump(ms, 560.0f, 900.0f) * amp);
            break;
        }
        case CC_FX_HALF: {                                // BS:655 [M23]
            const float fade = ms < halfHoldMs ? 1.0f : 1.0f - eo((ms - halfHoldMs) / halfFadeMs);
            const int elapsed = static_cast<int>(ms);
            const int reach = (elapsed < halfGrowMs ? elapsed : halfGrowMs) + 10;
            for (int k = 1; k < 30; ++k)
                if (20 * iabs(k - 15) <= reach) add(e.side < 0 ? kRing - k : k, e.c, 0.75f * fade * amp);
            addB(e.side < 0 ? 1 : 2, e.c, 0.6f * fade);   // without amp (A02 F18)
            break;
        }
        case CC_FX_SCATTER: {                             // BS:657 [M5]
            for (int k = 0; k < 9; ++k) {
                const float pos = fmodf(e.seed + static_cast<float>(scatterOrder[k] * 60) / 9.0f, 60.0f);
                const float st = static_cast<float>(k) * scatterStepMs;
                addG(pos, 0.8f, hotC, 0.8f * bump(ms, st, st + scatterBumpMs) * amp);
            }
            break;
        }
        case CC_FX_FAIL: {                                // RC:350 / BS:658, stationary under reduced motion
            const float pos = reducedMotion_ ? at : at + 1.6f * sinf(ms / 1000.0f * kTau * 3.2f) * (1.0f - eo(u));
            addG(pos, 0.9f, p.red, 0.95f * (1.0f - u * u) * amp);
            const float dim = 1.0f - 0.6f * sinf(kPi * u);
            for (int k = -3; k <= 3; ++k) m_[cc_alive_md(at + static_cast<float>(k))] *= dim;
            break;
        }
        case CC_FX_SWEEP: {
            const float dir = static_cast<float>(e.dir);
            comet(at + dir * 60.0f * eo(u), dir, 10, hotC, warmC, 0.85f * (1.0f - u * u * u) * amp);
            break;
        }
        case CC_FX_FILL: {
            const float n = static_cast<float>(e.n), f = u * 1.15f * (n + 1.0f);
            for (int k = 0; k <= e.n; ++k) m_[mdi(kVolumeStart + k)] *= cl((f - static_cast<float>(k)) / 2.5f);
            addG(static_cast<float>(kVolumeStart) + fmin2(n, f), 0.9f, hotC,
                 0.75f * (1.0f - cl((u - 0.85f) / 0.15f)) * amp);
            break;
        }
        case CC_FX_DRAIN: {
            const float n = static_cast<float>(e.n), pos = n - eio(u) * (n + 6.0f);
            for (int k = 0; k <= e.n; ++k)
                m_[mdi(kVolumeStart + k)] *= 1.0f - 0.8f * gs(static_cast<float>(k) - pos, 3.5f) * amp;
            break;
        }
        case CC_FX_SHIMMER: {
            const float dl = cc_alive_cd(e.to, e.from), pos = e.from + dl * eio(u / 0.7f);
            addG(pos, 1.2f, p.blue, 0.9f * (u < 0.7f ? 1.0f : 1.0f - (u - 0.7f) / 0.3f) * amp);
            addG(e.to, 1.4f, p.blue, 0.5f * bump(ms, 600.0f, 1000.0f) * amp);
            break;
        }
        case CC_FX_WASH: {
            const float d = eo(ms / 420.0f) * 31.0f;
            const float fade = ms < 520.0f ? 1.0f : 1.0f - eo((ms - 520.0f) / 580.0f);
            const float edge = 1.0f - cl(ms / 420.0f);
            const float base = 1.0f - 0.55f * fade * amp;
            for (int i = 0; i < kRing; ++i) {
                const float x = atInt ? static_cast<float>(iabs(cdi(i, atI))) : fabsf(cc_alive_cd(static_cast<float>(i), at));
                if (x <= d) add(i, e.c, 0.65f * fade * amp);
                add(i, e.c, 0.45f * gs(x - d, 1.5f) * edge * amp);
                m_[i] *= base;
            }
            addB(3, e.c, 0.55f * fade * amp);
            break;
        }
        case CC_FX_REVEAL:
            for (int i = 0; i < kRing; ++i)
                m_[i] *= cl((ms - static_cast<float>(iabs(cdi(i, 0))) * 8.0f) / 130.0f);
            break;
        case CC_FX_PRESS:
            addB(e.n, hotC, 0.6f * (1.0f - u) * (1.0f - u));
            break;
        default:
            break;
    }
    return true;
}

// draw(t, dt) (design lines 267-396) up to e.
void CCAliveAnimator::step(uint32_t t, uint32_t dt, const CCAliveTargets& tg, const CCAlivePalette& pal,
                           CCAliveRingE& ring, CCAliveButtonE& buttons) {
    const bool asleep = tg.asleep, off = tg.offline;
    // [user 2026-09-26] resting is steady (no breath) and time of day never dims it below restTodMin.
    const float restK = asleep ? fmax2(tg.todB, restTodMin) : 1.0f;
    const float br = off ? 0.6f + 0.4f * sinf(kTau * phase(t, offlineBreathMs)) : 1.0f;
    const float fdt = static_cast<float>(dt);
    const float kAsleepUp = decay(fdt, tauRingAsleepUp), kAsleepDown = decay(fdt, tauRingAsleepDown);
    const float kCursorUp = decay(fdt, tauRingCursorUp), kUp = decay(fdt, tauRingUp), kDown = decay(fdt, tauRingDown);
    const float kButtonUp = decay(fdt, tauButtonUp), kButtonDown = decay(fdt, tauButtonDown);
    const float kButtonAsleepUp = decay(fdt, tauButtonAsleepUp), kButtonAsleepDown = decay(fdt, tauButtonAsleepDown);
    const float kColour = decay(fdt, tauColour), kSnap = decay(fdt, tauColourSnap), kTint = decay(fdt, tauTint);
    float residue = 0.0f;
    bool embers = false;

    // 8.2 ring damping (lines 274-286).
    for (int i = 0; i < kRing; ++i) {
        const CCAliveCell& r = tg.ring[i];
        Light& c = cur_[i];
        const bool litCell = r.cls != CC_ALIVE_CLASS_NONE;
        float ta = 0.0f, tc[3] = {0.0f, 0.0f, 0.0f};
        if (litCell) {
            cellColour(r, pal, tc);
            ta = r.alpha * br * restK;
            if (tg.heat && r.volRed) {
                embers = true;
                ta *= 0.72f + 0.28f * (0.5f + 0.5f * sinf(kTau * phase(t, heatPeriodMs[i]) +
                                                          static_cast<float>(i) * 1.9f));
            }
        }
        const bool up = ta > c.a;
        const float k = asleep ? (up ? kAsleepUp : kAsleepDown) : (up ? (ta >= cursorTargetAt ? kCursorUp : kUp) : kDown);
        c.a += (ta - c.a) * k;
        residue = fmax2(residue, fabsf(ta - c.a));
        if (litCell) {
            const float kc = c.a < colourSnapBelow ? kSnap : kColour;
            c.r += (tc[0] - c.r) * kc;
            c.g += (tc[1] - c.g) * kc;
            c.b += (tc[2] - c.b) * kc;
            residue = fmax2(residue, c.a * fmax2(fmax2(fabsf(tc[0] - c.r), fabsf(tc[1] - c.g)), fabsf(tc[2] - c.b)));
        }
    }
    // Buttons (lines 287-296).
    const bool pausedPlay = tg.pausedPlay && !asleep && tg.family == CC_ALIVE_HOME;
    for (int j = 0; j < 4; ++j) {
        const CCAliveCell& b = tg.buttons[j];
        Light& c = bcur_[j];
        const bool litButton = b.cls != CC_ALIVE_CLASS_NONE;
        float ta = litButton ? b.alpha * restK : 0.0f;
        if (asleep) ta *= br;
        if (j == 0 && pausedPlay) ta *= 0.55f + 0.45f * (0.5f + 0.5f * cosf(kTau * phase(t, pausedPlayMs)));
        const bool up = ta > c.a;
        const float k = asleep ? (up ? kButtonAsleepUp : kButtonAsleepDown) : (up ? kButtonUp : kButtonDown);
        c.a += (ta - c.a) * k;
        residue = fmax2(residue, fabsf(ta - c.a));
        if (litButton) {
            float tc[3];
            cellColour(b, pal, tc);
            c.r += (tc[0] - c.r) * kColour;
            c.g += (tc[1] - c.g) * kColour;
            c.b += (tc[2] - c.b) * kColour;
            residue = fmax2(residue, c.a * fmax2(fmax2(fabsf(tc[0] - c.r), fabsf(tc[1] - c.g)), fabsf(tc[2] - c.b)));
        }
    }

    for (int i = 0; i < kRing; ++i) {
        m_[i] = 1.0f;
        o_[i][0] = o_[i][1] = o_[i][2] = 0.0f;
    }
    for (int j = 0; j < 4; ++j) {
        bm_[j] = 1.0f;
        ob_[j][0] = ob_[j][1] = ob_[j][2] = 0.0f;
    }
    float duck = 0.0f;

    // 8.4 layers before the effects: Working comet, ambient tint, song hand.
    if (tg.pending) comet(60.0f * phase(t, workingLapMs), 1.0f, 8, pal.hot, pal.warm, 0.5f);
    float tintMax = 0.0f;
    for (int q = 0; q < 3; ++q) {
        tint_[q] += ((tg.tintOn ? tg.tint[q] : 0.0f) - tint_[q]) * kTint;
        tintMax = fmax2(tintMax, fabsf(tint_[q]));
    }
    for (int i = 0; i < kRing; ++i)
        if (tg.ring[i].cls == CC_ALIVE_CLASS_NONE) add(i, tint_, 0.06f);
    if (tg.songProg >= 0.0f && !asleep) addG(tg.songProg * 60.0f, 0.75f, pal.hot, 0.26f * tg.todB);   // [user 2026-09-26] none at rest

    // Effects, in queue order (lines 318-360).
    uint8_t kept = 0;
    for (uint8_t k = 0; k < count_; ++k) {
        CCAliveEffect& e = fx_[k];
        if (draw(e, t, pal, duck)) {
            if (kept != k) fx_[kept] = e;
            ++kept;
        }
    }
    count_ = kept;

    // 8.5 compose + tone map (lines 370-395).
    const float bk = 1.0f - duck;
    for (int i = 0; i < kRing; ++i) {
        const Light& c = cur_[i];
        const float k = c.a * m_[i] * bk;
        float e[3] = {c.r * k + o_[i][0], c.g * k + o_[i][1], c.b * k + o_[i][2]};
        tone(e);
        ring[i][0] = e[0];
        ring[i][1] = e[1];
        ring[i][2] = e[2];
    }
    for (int j = 0; j < 4; ++j) {
        const Light& c = bcur_[j];
        const float k = c.a * bm_[j];
        float e[3] = {c.r * k + ob_[j][0], c.g * k + ob_[j][1], c.b * k + ob_[j][2]};
        tone(e);
        buttons[j][0] = e[0];
        buttons[j][1] = e[1];
        buttons[j][2] = e[2];
    }
    animating_ = count_ > 0 || residue > kResidue || tg.pending || tg.tintOn || tintMax > kResidue ||
                 tg.songProg >= 0.0f || asleep || off || pausedPlay || embers;
}

// ------------------------------------------------------------------ output
float cc_alive_eotf(float e) {
    if (!(e > 0.0f)) return 0.0f;                        // also NaN
    if (e >= 1.0f) return 1.0f;
    const float x = e * 256.0f;
    int i = static_cast<int>(x);
    if (i > 255) i = 255;
    const float f = x - static_cast<float>(i);
    return kEotf[i] + (kEotf[i + 1] - kEotf[i]) * f;
}

uint8_t cc_alive_drive(bool latched, uint8_t ledDrive, uint8_t ledMaxBrightness) {
    const uint8_t want = latched ? ledDrive : defaultDrive;
    return want < ledMaxBrightness ? want : ledMaxBrightness;
}

namespace {
uint32_t quantise(float v, float& residual, bool dither) {
    float x = v;
    if (dither) x += residual;
    float q = floorf(x + 0.5f);
    if (q < 0.0f) q = 0.0f;
    if (q > 255.0f) q = 255.0f;
    residual = dither ? x - q : 0.0f;
    return static_cast<uint32_t>(q);
}

// One LED: v = eotf(e) * scale per channel, quantised; `lit` = its design target is lit.
uint32_t pixel(const float (&e)[3], float scale, float (&residual)[3], bool dither, bool lit) {
    const float v[3] = {cc_alive_eotf(e[0]) * scale, cc_alive_eotf(e[1]) * scale, cc_alive_eotf(e[2]) * scale};
    uint32_t q[3];
    for (int c = 0; c < 3; ++c) q[c] = quantise(v[c], residual[c], dither);
    // [user 2026-09-26] F-T floor (section 9 step 4, dither off only; channel rule amended the same
    // day, 12.7): a lit target whose plain rounding is dark shows one count on its dominant channel,
    // q_c = (v_c >= m) with m = max_c v_c (a tie lights every tied channel), the rest 0. That is the
    // byte plain rounding shows just above m = 0.5, so a breath passes through the floor without a
    // jump (no channel lights under the floor that is dark just above it).
    if (!dither && lit && (q[0] | q[1] | q[2]) == 0u) {
        const float m = v[0] > v[1] ? (v[0] > v[2] ? v[0] : v[2]) : (v[1] > v[2] ? v[1] : v[2]);
        if (m > 0.0f)
            for (int c = 0; c < 3; ++c) q[c] = v[c] >= m ? 1u : 0u;
    }
    return (q[0] << 16) | (q[1] << 8) | q[2];
}
} // namespace

void cc_alive_lit(const CCAliveTargets& targets, uint64_t& ringLit, uint8_t& buttonLit) {
    ringLit = 0;
    buttonLit = 0;
    for (int i = 0; i < kRing; ++i)
        if (targets.ring[i].cls != CC_ALIVE_CLASS_NONE && targets.ring[i].alpha > 0.0f)
            ringLit |= static_cast<uint64_t>(1) << i;
    for (int j = 0; j < 4; ++j)
        if (targets.buttons[j].cls != CC_ALIVE_CLASS_NONE && targets.buttons[j].alpha > 0.0f)
            buttonLit = static_cast<uint8_t>(buttonLit | (1u << j));
}

void cc_alive_output(const CCAliveRingE& ringE, const CCAliveButtonE& buttonE, uint8_t drive, bool dither,
                     CCAliveDither& residuals, uint32_t (&ring)[CC_RING_LEDS], uint32_t (&buttons)[4],
                     uint64_t ringLit, uint8_t buttonLit) {
    const float d = static_cast<float>(drive);
    float sum = 0.0f;                                     // [D17] S over 60 ring + 8 button LEDs
    for (int i = 0; i < kRing; ++i)
        sum += (cc_alive_eotf(ringE[i][0]) + cc_alive_eotf(ringE[i][1]) + cc_alive_eotf(ringE[i][2])) * d;
    for (int j = 0; j < 4; ++j)
        sum += static_cast<float>(buttonLedsPerSlot) *
               (cc_alive_eotf(buttonE[j][0]) + cc_alive_eotf(buttonE[j][1]) + cc_alive_eotf(buttonE[j][2])) * d;
    const float scale = sum > powerBudget ? d * (powerBudget / sum) : d;
    for (int i = 0; i < kRing; ++i)
        ring[i] = pixel(ringE[i], scale, residuals.ring[i], dither, ((ringLit >> i) & 1u) != 0u);
    for (int j = 0; j < 4; ++j)
        buttons[j] = pixel(buttonE[j], scale, residuals.buttons[j], dither, ((buttonLit >> j) & 1u) != 0u);
}

// ------------------------------------------------------------------ engine
CCAlive::CCAlive() {
    reset(0);
}

void CCAlive::reset(uint32_t now) {
    memset(eased_, 0, sizeof(eased_));
    memset(easedB_, 0, sizeof(easedB_));
    memset(prevE_, 0, sizeof(prevE_));
    memset(prevEB_, 0, sizeof(prevEB_));
    easeResidue_ = 0.0f;
    wallOn_ = sweepOn_ = false;
    wallAt_ = sweepAt_ = now;
    wallSeg_ = 0;
    animator_.reset();
    animator_.setReducedMotion(false);
    palette_ = cc_alive_palette();
    memset(&targets_, 0, sizeof(targets_));
    targets_.family = CC_ALIVE_OFFLINE;
    targets_.offline = true;
    targets_.songProg = -1.0f;
    targets_.todB = 1.0f;
    memset(ringE_, 0, sizeof(ringE_));
    memset(buttonE_, 0, sizeof(buttonE_));
    memset(&dither_, 0, sizeof(dither_));
    memset(presses_, 0, sizeof(presses_));
    memset(detents_, 0, sizeof(detents_));
    memset(limits_, 0, sizeof(limits_));
    pressCount_ = detentCount_ = limitCount_ = 0;
    lastRender_ = now;
    firstRender_ = true;
    claimed_ = bootPending_ = seeding_ = stateAsleep_ = prevAsleep_ = false;
    sleepAt_ = now;
    flash_ = CC_FLASH_NONE;
    feedbackKind_ = CC_FEEDBACK_OK;
    feedbackMoment_ = CC_MOMENT_NONE;
    feedbackEvent_ = colorMode_ = false;
    feedbackSkip_ = feedbackSide_ = 0;
    feedbackColor_ = 0;
    holdMs_ = 0;
    lastSeq_ = flashStart_ = holdStart_ = pendingStart_ = 0;
    pendingOn_ = false;
    prevFamily_ = CC_ALIVE_OFFLINE;
    prevStyle_ = CC_RING_OFF;
    prevCursor_ = 0;
    prevAccent_ = 0;
    prevExternal_ = false;
    prevPlaying_ = -1;
    vel_ = 0.0f;
    lastRot_ = 0;
    hasRot_ = false;
    hasClock_ = volFull_ = false;
    clockMinute_ = 0;
    clockAt_ = 0;
    progPos_ = progDur_ = progAt_ = 0;
    homePlaying_ = -1;
    rng_ = rngSeed;
    holdDown_ = holdMatured_ = feedbackRefused_ = false;
    holdAt_ = 0;
    hold4Down_ = hold4Matured_ = false;
    hold4At_ = 0;
    landingOpen_ = false;
    landingAt_ = 0;
    playAt(CC_FX_REVEAL, now, 0.0f);                      // 8.1: power-up is offline + reveal
}

void CCAlive::claim(uint32_t now) {
    if (claimed_) return;
    claimed_ = true;
    bootPending_ = true;                                  // boot on the first rendered frame
    seeding_ = true;                                      // ... which only seeds 6.4
    stateAsleep_ = false;                                 // claim counts as an input
    sleepAt_ = now + sleepInputMs;
    flash_ = CC_FLASH_NONE;
    holdMs_ = 0;
    lastSeq_ = 0;
    pendingOn_ = false;
    pressCount_ = detentCount_ = limitCount_ = 0;
    vel_ = 0.0f;
    hasRot_ = false;
    holdDown_ = holdMatured_ = false;
    hold4Down_ = hold4Matured_ = false;
    landingOpen_ = false;
}

void CCAlive::release(uint32_t now) {
    if (!claimed_) return;
    claimed_ = false;
    bootPending_ = seeding_ = false;
    stateAsleep_ = false;
    flash_ = CC_FLASH_NONE;
    holdMs_ = 0;
    pressCount_ = detentCount_ = limitCount_ = 0;
    holdDown_ = holdMatured_ = false;
    hold4Down_ = hold4Matured_ = false;
    landingOpen_ = false;
    wallOn_ = sweepOn_ = false;
    playAt(CC_FX_DOWN, now, static_cast<float>(prevCursor_));   // snapshots the damped state now
}

void CCAlive::detent(uint32_t now, int32_t delta) {
    if (!claimed_ || delta == 0) return;
    if (detentCount_ < 8) {
        detents_[detentCount_].now = now;
        detents_[detentCount_].value = delta;
        ++detentCount_;
    } else {                                              // more than 8 per frame: merge into the last
        detents_[7].now = now;
        detents_[7].value += delta;
    }
}

void CCAlive::limit(uint32_t now, int8_t dir) {
    if (!claimed_ || dir == 0 || limitCount_ >= 4) return;
    limits_[limitCount_].now = now;
    limits_[limitCount_].value = dir > 0 ? 1 : -1;
    ++limitCount_;
}

void CCAlive::press(uint32_t now, uint8_t slot) {
    if (!claimed_ || slot > 3) return;
    if (slot == 0) {                                      // [r3] 15.7: the hold-1 progress ring starts here
        holdDown_ = true;
        holdMatured_ = false;
        holdAt_ = now;
    }
    if (slot == 3) {                                      // [r3.1] the button-4 hold ring starts here
        hold4Down_ = true;
        hold4Matured_ = false;
        hold4At_ = now;
    }
    if (pressCount_ >= 8) return;
    presses_[pressCount_].now = now;
    presses_[pressCount_].value = slot;
    ++pressCount_;
}

void CCAlive::keyUp(uint32_t /*now*/, uint8_t slot) {
    if (slot == 0) holdDown_ = holdMatured_ = false;
    if (slot == 3) hold4Down_ = hold4Matured_ = false;
}

void CCAlive::setClock(uint32_t now, uint16_t minute) {
    hasClock_ = true;
    clockMinute_ = static_cast<uint16_t>(minute % 1440u);
    clockAt_ = now;
}

void CCAlive::setProgress(uint32_t now, uint32_t pos, uint32_t dur) {
    if (dur == 0) {
        progPos_ = progDur_ = 0;
        return;
    }
    progPos_ = pos < dur ? pos : dur;
    progDur_ = dur;
    progAt_ = now;
}

void CCAlive::setReducedMotion(uint32_t /*now*/, bool on) {
    animator_.setReducedMotion(on);
}

void CCAlive::setTuning(uint32_t /*now*/, uint32_t pinkLed, bool volFull) {
    cc_alive_pink(pinkLed, palette_.pink);
    volFull_ = volFull;
}

float CCAlive::todB(uint32_t now) const {
    if (!hasClock_) return 1.0f;
    const uint32_t elapsed = (now - clockAt_) % kDayMs;
    const uint32_t ms = (static_cast<uint32_t>(clockMinute_) * 60000u + elapsed) % kDayMs;
    return cc_alive_tod_brightness(static_cast<float>(ms) / 3600000.0f);
}

void CCAlive::playAt(uint8_t type, uint32_t now, float at) {
    CCAliveEffect e = cc_alive_effect(type, now);
    e.at = at;
    animator_.play(e);
}

void CCAlive::wakeInput(uint32_t sleepAt) {
    stateAsleep_ = false;
    sleepAt_ = sleepAt;
}

// The v4 seq rules (PreviewLights._feedback): a new valid seq is one 6.4 event; the first frame
// after claim only seeds. [r2] A flash row (a, b, i, j) starts its flash window and ends a running
// moment hold; a moment row (c-h) starts its [M22] hold and ends a running flash ([M7]: no flash
// with a moment); unlike ends both.
void CCAlive::feedback(const CCFrame& f, uint32_t now, const CCAliveFrameExtra& extra) {
    const bool valid = f.feedbackPresent && (f.feedbackKind == CC_FEEDBACK_OK || f.feedbackKind == CC_FEEDBACK_ERR) &&
                       f.feedbackSeq >= 1 && f.feedbackSeq <= kSeqMax;
    if (seeding_) {
        if (valid) lastSeq_ = f.feedbackSeq;
        return;
    }
    if (!valid || f.feedbackSeq == lastSeq_) return;
    lastSeq_ = f.feedbackSeq;
    const bool ok = f.feedbackKind == CC_FEEDBACK_OK;
    feedbackEvent_ = true;
    feedbackKind_ = f.feedbackKind;
    feedbackSkip_ = static_cast<int8_t>(ok && (extra.skip == 1 || extra.skip == -1) ? extra.skip : 0);
    feedbackMoment_ = ok && f.feedbackMoment <= CC_MOMENT_STARTED ? f.feedbackMoment
                                                                  : static_cast<uint8_t>(CC_MOMENT_NONE);
    feedbackSide_ = static_cast<int8_t>(feedbackMoment_ == CC_MOMENT_SNAP ? (f.feedbackSide == -1 ? -1 : 1) : 0);
    feedbackColor_ = feedbackMoment_ == CC_MOMENT_SNAP || feedbackMoment_ == CC_MOMENT_STARTED
                     ? (f.feedbackColor & 0xFFFFFFu) : 0u;
    colorMode_ = f.coloredLeds;
    feedbackRefused_ = !ok && f.feedbackMoment == CC_MOMENT_REFUSED;   // [r3] 15.7: an unavailable press
    // [r3.1] 15.8: the first new seq after a button-4 hold matured closes its landing window; within 1500 ms a
    // plain ok lands as CC_FLASH_LAND and ok + queued as CC_FLASH_QUEUE (no sweep, no moment hold).
    if (landingOpen_) {
        const bool open = static_cast<uint32_t>(now - landingAt_) < landingWindowMs;
        landingOpen_ = false;
        if (open && ok && !feedbackSkip_ &&
            (feedbackMoment_ == CC_MOMENT_NONE || feedbackMoment_ == CC_MOMENT_QUEUED)) {
            flash_ = feedbackMoment_ == CC_MOMENT_QUEUED ? CC_FLASH_QUEUE : CC_FLASH_LAND;
            flashStart_ = now;
            holdMs_ = 0;
            // r4 M12: the domain swap sweeps from 12 o'clock; FW-DES-002: under reduced motion (r4 7) every LED
            // eases at once (a blend, no sweep).
            if (flash_ == CC_FLASH_LAND && !animator_.reducedMotion()) {
                sweepOn_ = true;
                sweepAt_ = now;
            }
            return;
        }
    }
    if (!ok || feedbackSkip_ || feedbackMoment_ == CC_MOMENT_NONE) {
        flash_ = ok ? CC_FLASH_OK : feedbackRefused_ ? CC_FLASH_REFUSED : CC_FLASH_ERR;   // rows a, b, i, j
        // [r3] 15.5: a plain ok (no skip, no moment) in the LIGHTS family is the 700 ms green wash.
        if (ok && !feedbackSkip_ && cc_alive_family(f) == CC_ALIVE_LIGHTS) flash_ = CC_FLASH_WASH;
        flashStart_ = now;
        holdMs_ = 0;
        return;
    }
    flash_ = CC_FLASH_NONE;                               // rows c-h
    holdStart_ = now;
    bool accent = false;
    switch (feedbackMoment_) {
        case CC_MOMENT_QUEUED: holdMs_ = holdQueuedMs; break;
        case CC_MOMENT_SHUFFLE: holdMs_ = holdShuffleMs; break;
        case CC_MOMENT_LIKE: holdMs_ = holdLikeMs; break;
        case CC_MOMENT_SNAP: holdMs_ = holdSnapMs; break;
        case CC_MOMENT_STARTED:
            if (feedbackColor_ && colorMode_) cc_alive_sat(feedbackColor_, accent);
            holdMs_ = accent ? holdStartedWashMs : holdStartedBloomMs;
            break;
        default: holdMs_ = 0; break;                      // unlike
    }
}

// 6.4 rows a-j (first match). Returns true when the row was h (started) [M16].
bool CCAlive::feedbackEffect(uint32_t now, float at) {
    CCAliveEffect e = cc_alive_effect(CC_FX_BLOOM, now);
    e.at = at;
    bool accent = false;
    if (feedbackKind_ == CC_FEEDBACK_ERR) {                                   // a
        if (!feedbackRefused_) playAt(CC_FX_FAIL, now, at);                   // [r3] 15.7: no shake
        return false;
    }
    if (flash_ == CC_FLASH_WASH) return false;            // [r3] 15.5: the wash is a target override
    if (flash_ == CC_FLASH_LAND || flash_ == CC_FLASH_QUEUE) return false;   // [r3.1] 15.8: the landings too
    if (feedbackSkip_ != 0) {                                                 // b [M21]
        e.type = CC_FX_SWEEP;
        e.at = static_cast<float>(prevCursor_);
        e.dir = feedbackSkip_;
        animator_.play(e);
        return false;
    }
    switch (feedbackMoment_) {
        case CC_MOMENT_QUEUED:                                                // c
            e.type = CC_FX_SWEEP;
            e.at = 0.0f;
            e.dir = 1;
            animator_.play(e);
            return false;
        case CC_MOMENT_SHUFFLE:                                               // d [M5]
            rng_ = cc_alive_xorshift32(rng_);                     // drawn also when rm drops it
            e.type = CC_FX_SCATTER;
            e.seed = cc_alive_scatter_seed(rng_);
            animator_.play(e);
            return false;
        case CC_MOMENT_LIKE:                                                  // e [M25]
            copy3(palette_.pink, e.c);
            animator_.play(e);
            return false;
        case CC_MOMENT_UNLIKE:                                                // f
            return false;
        case CC_MOMENT_SNAP: {                                                // g
            const uint32_t s = feedbackColor_ && colorMode_ ? cc_alive_sat(feedbackColor_, accent) : 0u;
            e.type = CC_FX_HALF;
            e.side = feedbackSide_;
            if (accent) unpack(s, e.c);
            else copy3(palette_.warm, e.c);
            animator_.play(e);
            return false;
        }
        case CC_MOMENT_STARTED: {                                             // h [M16]
            const uint32_t s = feedbackColor_ && colorMode_ ? cc_alive_sat(feedbackColor_, accent) : 0u;
            if (accent) {
                e.type = CC_FX_WASH;
                unpack(s, e.c);
            } else {
                copy3(palette_.green, e.c);
            }
            animator_.play(e);
            return true;
        }
        default:
            break;
    }
    const bool list = prevFamily_ == CC_ALIVE_RECENT || prevFamily_ == CC_ALIVE_EXPLORER ||
                      prevFamily_ == CC_ALIVE_UPNEXT || prevFamily_ == CC_ALIVE_WINDOWS;
    if (list && prevAccent_ != 0) {                                           // i [D7][M10]
        e.type = CC_FX_WASH;
        e.at = static_cast<float>(prevCursor_);
        unpack(prevAccent_, e.c);
    } else {                                                                  // j
        copy3(palette_.green, e.c);
    }
    animator_.play(e);
    return false;
}

// 5.1.8 the pending onset of a selection / transport ring (revision 2 has no loading pulse).
uint32_t CCAlive::onsets(const CCFrame& f, uint32_t now) {
    const bool pending = f.activity == CC_PENDING &&
                         (f.ringStyle == CC_RING_SELECTION || f.ringStyle == CC_RING_TRANSPORT);
    if (pending && !pendingOn_) pendingStart_ = now;
    pendingOn_ = pending;
    return pending ? static_cast<uint32_t>(now - pendingStart_) : 0u;
}

// 8.4 song hand latch [R3]: extrapolation runs while the last Home frame says
// playing:true and freezes when a Home frame stops saying so; an absent playing
// (-1) counts as not playing, exactly like false.
void CCAlive::song(uint32_t now, int8_t playing) {
    const bool wasRunning = homePlaying_ == 1, running = playing == 1;
    if (wasRunning && !running && progDur_ > 0) {
        const uint32_t pos = progPos_ + static_cast<uint32_t>(now - progAt_);
        progPos_ = pos < progPos_ || pos > progDur_ ? progDur_ : pos;
        progAt_ = now;
    }
    if (!wasRunning && running) progAt_ = now;
    homePlaying_ = playing;
}

// 6.2 bound colour: the cursor target's (WARM -> WARM; a dark cursor: WARM).
void CCAlive::cursorColour(float (&c)[3]) const {
    const CCAliveCell& cell = targets_.ring[targets_.cursor];
    if (cell.cls != CC_ALIVE_CLASS_NONE) cellColour(cell, palette_, c);
    else copy3(palette_.warm, c);
}

void CCAlive::render(uint32_t now, const CCFrame* frame, int32_t localPos, int32_t localMax) {
    CCAliveFrameExtra extra;
    extra.playing = -1;
    extra.skip = 0;
    render(now, frame, localPos, localMax, extra);
}

void CCAlive::render(uint32_t now, const CCFrame* frame, int32_t localPos, int32_t localMax,
                     const CCAliveFrameExtra& extra) {
    uint32_t dt = 0;                                      // section 4 frame gaps
    uint32_t easeDt = 0;                                  // r4: the easer integrates the real gap (<= 1 s)
    if (!firstRender_) {
        dt = static_cast<uint32_t>(now - lastRender_);
        easeDt = dt > 1000u ? 1000u : dt;
        if (dt > maxFrameGapMs) dt = maxFrameGapMs;
    }
    firstRender_ = false;
    lastRender_ = now;

    const bool live = claimed_ && frame != nullptr;
    uint8_t family = CC_ALIVE_OFFLINE;
    bool pending = false, extEvent = false;
    int8_t playing = -1;
    uint32_t pendingMs = 0;
    int32_t localValue = -1, localIndex = -1;
    feedbackEvent_ = false;
    if (live) {
        // 6.3 (LEDs only), read in place: no frame copy (a CCFrame is 1,124 B).
        cc_alive_local(*frame, localPos, localMax, localValue, localIndex);
        family = cc_alive_family(*frame);
        pending = cc_alive_pending(*frame, localValue);
        playing = static_cast<int8_t>(family == CC_ALIVE_HOME && extra.playing >= 0 ? (extra.playing ? 1 : 0) : -1);
        pendingMs = onsets(*frame, now);
        // DD-BUG-053 [r3.1] 15.8: a button-4 hold that matures on this render opens its landing window BEFORE the
        // frame's feedback is read, so a host frame landing on the same render as the 1000 ms mark (ok + queued)
        // lands as CC_FLASH_QUEUE, not as an ordinary moment. Same guards as the maturity block below (not the app
        // canvas, holdMarker, hold 1 not running); that block keeps the fill and the 600 ms wait. App profiles: app.id
        // is a char array, so `app.id == 0` compiled as an always-false pointer test and closed this path silently.
        if (hold4Down_ && !hold4Matured_ && frame->holdMarker && !cc_app_present(frame->app) &&
            !(holdDown_ && frame->crumb != CC_CRUMB_NONE) && static_cast<uint32_t>(now - hold4At_) >= hold4RingMs) {
            hold4Matured_ = true;
            landingOpen_ = true;
            landingAt_ = now;
        }
        feedback(*frame, now, extra);
        extEvent = !seeding_ && prevFamily_ == CC_ALIVE_HOME && family == CC_ALIVE_HOME && !prevExternal_ &&
                   frame->ringExternal;
        if (family == CC_ALIVE_HOME) song(now, playing);
    }
    // [r3] 15.7 the hold-1 progress ring on a frame with a crumb (never the launcher Home): the fill from 12 %
    // of the 600 ms hold, then (once) the WARM home flash when it matures.
    int16_t holdFill = 0;
    // 1.0.0-cc5.6 (A2): never on the app canvas (a frame with `app`): there 1 is ZOOM and 4 PAN, and Desk Dial's
    // Home is all four buttons held 1 s (ONSHAPE.md) -- no hold-1 / hold-4 ring, flash or landing.
    const bool appCanvas = live && cc_app_present(frame->app);
    const bool hold1 = live && !appCanvas && holdDown_ && frame->crumb != CC_CRUMB_NONE;
    if (hold1) {
        hold4Down_ = false;                               // [r3.1] hold 1 wins: a held button 4 is dropped
        const uint32_t held = now - holdAt_;
        if (held >= holdRingMs) {
            if (!holdMatured_) {
                holdMatured_ = true;
                flash_ = CC_FLASH_HOME;
                flashStart_ = now;
            }
        } else if (held * 100u >= holdRingMs * holdShowPct) {
            holdFill = static_cast<int16_t>((held * arcLength + holdRingMs / 2u) / holdRingMs);
        }
    }
    // [r3.1] ALIVE.md 15.8 the button-4 hold ring while slot 3 is held on a frame with holdMarker (any screen,
    // the launcher too): the fill from 15 % of the 1000 ms hold; at maturity the full arc waits (<= 600 ms) for
    // the host's landing feedback (feedback()). While the hold-1 ring runs (button 1 also held on a crumb
    // screen) hold 1 wins: that button-4 press draws nothing more (it is dropped above), until its next press.
    if (landingOpen_ && static_cast<uint32_t>(now - landingAt_) >= landingWindowMs) landingOpen_ = false;
    if (live && !appCanvas && hold4Down_ && frame->holdMarker) {
        const uint32_t held = now - hold4At_;
        if (held >= hold4RingMs) {
            if (!hold4Matured_) {                         // [r3.1] 15.8: the landing is the host's (feedback)
                hold4Matured_ = true;
                landingOpen_ = true;
                landingAt_ = now;
            }
            if (landingOpen_ && static_cast<uint32_t>(now - landingAt_) < landingWaitMs) holdFill = arcLength;
        } else if (held * 100u >= hold4RingMs * hold4ShowPct) {
            holdFill = static_cast<int16_t>((held * arcLength + hold4RingMs / 2u) / hold4RingMs);
        }
    }
    // The flash window (ok 650 ms, err 900 ms) and the [M22] moment hold are time-based: they
    // also end on a claimed render without a frame.
    if (flash_ != CC_FLASH_NONE) {
        const uint32_t duration = flash_ == CC_FLASH_OK ? CCLed::flashOkMs
                                  : flash_ == CC_FLASH_WASH ? lightsWashMs
                                  : flash_ == CC_FLASH_REFUSED ? refusedFlashMs
                                  : flash_ == CC_FLASH_HOME ? homeFlashMs
                                  : flash_ == CC_FLASH_LAND ? landFlashMs
                                  : flash_ == CC_FLASH_QUEUE ? queueFlashMs : CCLed::flashErrMs;
        if (static_cast<uint32_t>(now - flashStart_) >= duration) flash_ = CC_FLASH_NONE;
    }
    if (holdMs_ && static_cast<uint32_t>(now - holdStart_) >= holdMs_) holdMs_ = 0;
    const bool holding = flash_ != CC_FLASH_NONE || holdMs_ != 0;
    // 6.1: inputs wake and push the sleep deadline; then the sleep timer.
    if (claimed_) {
        for (uint8_t k = 0; k < pressCount_; ++k) wakeInput(presses_[k].now + sleepInputMs);
        for (uint8_t k = 0; k < detentCount_; ++k) wakeInput(detents_[k].now + sleepInputMs);
        for (uint8_t k = 0; k < limitCount_; ++k) wakeInput(limits_[k].now + sleepInputMs);
        if (extEvent) wakeInput(now + sleepExternalMs);
        if (!stateAsleep_ && static_cast<int32_t>(now - sleepAt_) >= 0) {
            if (pending || holding) sleepAt_ = now + sleepRecheckMs;
            else stateAsleep_ = true;
        }
    }
    const bool sleeping = claimed_ && stateAsleep_ && !pending && !holding;

    CCAliveTargetState state;
    state.offline = !claimed_;
    state.asleep = sleeping;
    state.flash = flash_;
    state.pendingMs = pendingMs;
    state.localValue = localValue;
    state.localIndex = localIndex;
    state.volFull = volFull_;
    state.holdFill = holdFill;
    cc_alive_targets(live ? frame : nullptr, state, targets_);
    targets_.todB = todB(now);
    // 8.4 song hand [R3]: resting on Home, the last Home frame said playing:true (absent is not
    // playing), progress latched with dur > 0.
    if (live && sleeping && family == CC_ALIVE_HOME && homePlaying_ == 1 && progDur_ > 0) {
        const uint32_t pos = progPos_ + static_cast<uint32_t>(now - progAt_);
        const float prog = pos < progPos_ ? 1.0f : static_cast<float>(pos) / static_cast<float>(progDur_);
        targets_.songProg = cl(prog);
    }
    const uint8_t seg = targets_.cursor;
    const float at = static_cast<float>(seg);

    // Events, in the section 4 order.
    if (live) {
        if (bootPending_) {                               // 6.4.5 claim: boot, home = this frame's family
            CCAliveEffect e = cc_alive_effect(CC_FX_BOOT, now);
            e.at = at;
            e.home = family == CC_ALIVE_HOME;
            animator_.play(e);
            bootPending_ = false;
        }
        for (uint8_t k = 0; k < pressCount_; ++k) {       // 1. presses
            CCAliveEffect e = cc_alive_effect(CC_FX_PRESS, now);
            e.at = at;
            e.n = static_cast<int16_t>(presses_[k].value);
            animator_.play(e);
        }
        if (prevAsleep_ && !sleeping) playAt(CC_FX_WAKE, now, at);   // 2. wake
        for (uint8_t k = 0; k < detentCount_; ++k) {      // 3. tick (6.2)
            const Input& d = detents_[k];
            uint32_t dtR = hasRot_ ? static_cast<uint32_t>(d.now - lastRot_) : velocityGapMs + 1u;
            if (dtR < velocityMinMs) dtR = velocityMinMs;
            lastRot_ = d.now;
            hasRot_ = true;
            const float magnitude = static_cast<float>(d.value < 0 ? -d.value : d.value);
            vel_ = dtR > velocityGapMs ? 0.0f
                   : vel_ * 0.55f + 0.45f * (1000.0f * magnitude / static_cast<float>(dtR));
            int dir = seeding_ ? 0 : isign(cdi(seg, prevCursor_));
            if (dir == 0) dir = d.value > 0 ? 1 : -1;
            CCAliveEffect e = cc_alive_effect(CC_FX_TICK, now);
            e.at = at;
            e.dir = static_cast<int8_t>(dir);
            // [D19] len = round(x + 1e-4), x = clamp((vel - 4)/14) * 7: exact ties round up in
            // float32 here and float64 on the desktop alike.
            e.len = static_cast<int16_t>(cc_alive_js_round(cl((vel_ - 4.0f) / 14.0f) * 7.0f + tickTieBias));
            animator_.play(e);
        }
        for (uint8_t k = 0; k < limitCount_; ++k) {       // 3. bound (6.2), no tick [D4]
            wallOn_ = true;                               // r4 3.3: the end LEDs glow (r4Layer)
            wallAt_ = limits_[k].now;
            wallSeg_ = seg;
            CCAliveEffect e = cc_alive_effect(CC_FX_BOUND, now);
            e.at = at;
            e.dir = static_cast<int8_t>(limits_[k].value);
            cursorColour(e.c);
            animator_.play(e);
        }
        if (!seeding_) {                                  // 4. frame-derived events (6.4)
            const uint8_t style = frame->ringStyle;
            const bool lapSwitch = family == CC_ALIVE_TRACKS && style != prevStyle_ &&
                                   ((style == CC_RING_TRANSPORT && prevStyle_ == CC_RING_LAP) ||
                                    (style == CC_RING_LAP && prevStyle_ == CC_RING_TRANSPORT));
            if (family != prevFamily_ || lapSwitch) playAt(CC_FX_REVEAL, now, at);   // MODE [r2]
            const bool started = feedbackEvent_ && feedbackEffect(now, at);
            if (!started && prevFamily_ == CC_ALIVE_HOME && family == CC_ALIVE_HOME && prevPlaying_ >= 0 &&
                playing >= 0 && playing != prevPlaying_) {                            // PLAY/PAUSE [D8][M16]
                CCAliveEffect e = cc_alive_effect(playing ? CC_FX_FILL : CC_FX_DRAIN, now);
                e.at = at;
                e.n = static_cast<int16_t>((cc_alive_displayed_volume(*frame, localValue) + 1) / 2);
                animator_.play(e);
            }
            if (extEvent) {                                                           // EXT
                CCAliveEffect e = cc_alive_effect(CC_FX_SHIMMER, now);
                e.at = at;
                e.from = static_cast<float>(prevCursor_);
                e.to = at;
                animator_.play(e);
            }
        }
        // 6.4 memory of this frame.
        prevFamily_ = family;
        prevStyle_ = frame->ringStyle;
        prevCursor_ = seg;
        prevAccent_ = frame->ringStyle == CC_RING_SELECTION ? cc_alive_selected_color(*frame, localIndex) : 0u;
        prevExternal_ = frame->ringExternal;
        prevPlaying_ = playing;
        seeding_ = false;
    }
    pressCount_ = detentCount_ = limitCount_ = 0;
    prevAsleep_ = sleeping;
    animator_.step(now, dt, targets_, palette_, ringE_, buttonE_);
    r4Layer(now, easeDt);
}

// r4 (ALIVE.md 16): the wall glow blended over the animator's e, then the 50 ms output easer (with the M12 sweep's
// per-LED start). ringE_ / buttonE_ become what the LEDs show. dt: the real gap since the last render (<= 1 s, not
// the animator's 50 ms cap), so a render after a gap (a hidden mirror) lands where a continuous one would.
void CCAlive::r4Layer(uint32_t now, uint32_t dt) {
    if (wallOn_) {
        const float t = static_cast<float>(static_cast<uint32_t>(now - wallAt_));
        float g = 0.0f;
        if (t < glowRiseMs) g = eo(t / glowRiseMs);
        else if (t < glowRiseMs + glowFallMs) g = 1.0f - eio((t - glowRiseMs) / glowFallMs);
        else wallOn_ = false;
        if (g > 0.0f) {
            float c[3];
            unpack(wallGlowRgb, c);
            for (int q = 0; q < 3; ++q) c[q] *= wallGlowAlpha;
            tone(c);
            for (int k = -wallGlowHalf; k <= wallGlowHalf; ++k) {
                float* e = ringE_[mdi(static_cast<int>(wallSeg_) + k)];
                for (int q = 0; q < 3; ++q) e[q] += (c[q] - e[q]) * g;
            }
        }
    }
    const uint32_t sweepMs = static_cast<uint32_t>(now - sweepAt_);
    if (sweepOn_ && sweepMs >= landFlashMs) sweepOn_ = false;
    // First-order hold: the animator's e is taken to move linearly across the frame, and the 50 ms easer is
    // integrated exactly over it (s1 = x1 + (s0 - x0) a - (x1 - x0) b, a = e^-dt/tau, b = tau / dt (1 - a)), so a
    // smooth effect curve eases the same at 60 or 360 Hz; a step is spread over the frame it arrives in.
    const float fdt = static_cast<float>(dt);
    const float a = dt ? expf(-fdt / easeTauMs) : 1.0f;
    const float b = dt ? easeTauMs / fdt * (1.0f - a) : 1.0f;
    float residue = 0.0f;
    for (int i = 0; i < kRing; ++i) {
        float* shown = eased_[i];
        float* prev = prevE_[i];
        const bool held = sweepOn_ && static_cast<float>(sweepMs) < sweepStepMs * static_cast<float>(i);
        for (int q = 0; q < 3; ++q) {
            const float x1 = ringE_[i][q];
            if (!held && dt) shown[q] = x1 + (shown[q] - prev[q]) * a - (x1 - prev[q]) * b;
            // A tail below easeSnap lands on the target (float32 and the float64 twin agree; no 1e-40 tails).
            if (fabsf(x1 - shown[q]) < easeSnap) shown[q] = x1;
            prev[q] = x1;
            residue = fmax2(residue, fabsf(x1 - shown[q]));
            ringE_[i][q] = shown[q];
        }
    }
    for (int j = 0; j < 4; ++j)
        for (int q = 0; q < 3; ++q) {
            const float x1 = buttonE_[j][q];
            float& shown = easedB_[j][q];
            if (dt) shown = x1 + (shown - prevEB_[j][q]) * a - (x1 - prevEB_[j][q]) * b;
            if (fabsf(x1 - shown) < easeSnap) shown = x1;
            prevEB_[j][q] = x1;
            residue = fmax2(residue, fabsf(x1 - shown));
            buttonE_[j][q] = shown;
        }
    easeResidue_ = residue;
}

void CCAlive::output(uint8_t drive, bool dither, uint32_t (&ring)[CC_RING_LEDS], uint32_t (&buttons)[4]) {
    uint64_t ringLit = 0;
    uint8_t buttonLit = 0;
    cc_alive_lit(targets_, ringLit, buttonLit);
    cc_alive_output(ringE_, buttonE_, drive, dither, dither_, ring, buttons, ringLit, buttonLit);
}

// ------------------------------------------------------------------ local input (firmware HMI)
void CCAliveKnob::reset() {
    id_ = pushAt_ = fireAt_ = 0;
    pos_ = max_ = 0;
    valid_ = pushing_ = pushSeen_ = fired_ = false;
}

// [Q1] (ALIVE.md 12.5): see cc_alive.h.
CCAliveKnobEvents CCAliveKnob::sample(uint32_t now, uint32_t id, uint16_t pos, bool pushing, uint16_t max) {
    CCAliveKnobEvents events;
    events.delta = 0;
    events.limit = 0;
    if (!id) {
        reset();
        return events;
    }
    if (id == id_) {                                      // the same ready control: compare
        events.delta = static_cast<int32_t>(pos) - static_cast<int32_t>(pos_);
        if (pushing && !pushing_) {                       // the rising edge of a push
            const bool rearmed = !pushSeen_ || static_cast<uint32_t>(now - pushAt_) >= CCAliveSpec::limRearmMs;
            const bool spaced = !fired_ || static_cast<uint32_t>(now - fireAt_) >= CCAliveSpec::limGapMs;
            const int8_t dir = static_cast<int8_t>(pos == 0 ? -1 : (pos >= max ? 1 : 0));
            if (rearmed && spaced && dir) {
                events.limit = dir;
                fired_ = true;
                fireAt_ = now;
            }
        }
    } else {                                              // a new control only seeds: a fresh detector
        pushSeen_ = fired_ = false;
    }
    if (pushing) {
        pushSeen_ = true;
        pushAt_ = now;
    }
    id_ = id;
    pos_ = pos;
    max_ = max;
    pushing_ = pushing;
    valid_ = true;
    return events;
}
