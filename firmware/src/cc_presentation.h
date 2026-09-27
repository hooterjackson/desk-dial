#pragma once
#include <stdint.h>
#include <string.h>

// Presentation-only wire state (contract v4, PRESENTATION_V4.md, plus the v5 storage of
// PRESENTATION_V5.md section 3.6). Safe to render on a host; no motor dependencies.
// Parsed by cc_frame_parse.cpp.
// C++11 rules (section 10): namespace-scope constexpr only, no odr-used
// static constexpr members, no C++14 features.

// Presentation 5 (PRESENTATION_V5.md section 3.6; VOC section 1.2): every enum below is
// APPEND-ONLY. The v5 values follow the v4 ones and nothing is ever renumbered.
enum CCActivity : uint8_t { CC_IDLE, CC_LOADING, CC_PENDING, CC_ERROR, CC_UNAVAILABLE, CC_OFFLINE };
enum CCLayout : uint8_t {
    CC_LAYOUT_NOW_PLAYING, CC_LAYOUT_VOLUME, CC_LAYOUT_IDLE, CC_LAYOUT_RECENT,
    CC_LAYOUT_TRACKS, CC_LAYOUT_WINDOWS, CC_LAYOUT_NOTICE,
    // v5 (7..9): "seek", "explorer", "upnext".
    CC_LAYOUT_SEEK, CC_LAYOUT_EXPLORER, CC_LAYOUT_UPNEXT
};
enum CCTitleTone : uint8_t { CC_TITLE_INK, CC_TITLE_MUTED };
enum CCLineTone : uint8_t { CC_LINE_META, CC_LINE_SECONDARY, CC_LINE_ERROR, CC_LINE_SUCCESS };
enum CCFeedbackKind : uint8_t { CC_FEEDBACK_OK, CC_FEEDBACK_ERR };
enum CCRingStyle : uint8_t {
    CC_RING_OFF, CC_RING_LEVEL, CC_RING_SELECTION, CC_RING_TRANSPORT,
    CC_RING_LAP   // v5 (4): "lap", the Seek ring (index = target s, count = D s; section 4.3)
};
// Button icon vocabulary (section 3). CC_ICON_NONE is the wire token "".
enum CCIcon : uint8_t {
    CC_ICON_NONE, CC_ICON_PLAY, CC_ICON_PAUSE, CC_ICON_LIST, CC_ICON_WIN, CC_ICON_TRACKS,
    CC_ICON_BACK, CC_ICON_HOME, CC_ICON_MORE, CC_ICON_PREV, CC_ICON_NEXT, CC_ICON_SWITCH,
    CC_ICON_CANCEL,
    // v5 (13..21, PRESENTATION_V5 section 9.1): "expand", "clock", "playlists", "playnext",
    // "seek", "shuffle", "heart", "snapleft", "snapright".
    CC_ICON_EXPAND, CC_ICON_CLOCK, CC_ICON_PLAYLISTS, CC_ICON_PLAYNEXT, CC_ICON_SEEK,
    CC_ICON_SHUFFLE, CC_ICON_HEART, CC_ICON_SNAPLEFT, CC_ICON_SNAPRIGHT
};
// Section 5.9 button tones (v5 section 5.2 appends on / off and, [r2.2], liked; the knob derives
// every tone, none is parsed from the wire).
enum CCButtonTone : uint8_t {
    CC_TONE_NONE, CC_TONE_DIM, CC_TONE_STOP, CC_TONE_GO, CC_TONE_NAV,
    CC_TONE_ON, CC_TONE_OFF,  // v5 (5, 6)
    CC_TONE_LIKED             // [r2.2] (7): heart + lit on, the filled heart in #A3244A (5.2 row 4, P5-R29)
};
// v5 button `lit` (section 5.1): 0 absent, "on", "off".
enum CCButtonLit : uint8_t { CC_LIT_NONE, CC_LIT_ON, CC_LIT_OFF };
// v5 `feedback.moment` (section 6.1): 0 none; kept only with kind ok.
enum CCFeedbackMoment : uint8_t {
    CC_MOMENT_NONE, CC_MOMENT_QUEUED, CC_MOMENT_SHUFFLE, CC_MOMENT_LIKE, CC_MOMENT_UNLIKE,
    CC_MOMENT_SNAP, CC_MOMENT_STARTED
};

// Entries the ring carries at most (section 4 window rule).
constexpr uint16_t CC_RING_WINDOW = 20;
// v5 `lap` ring: 1 <= count <= CC_LAP_COUNT_MAX and index < count, else reject (section 4.3;
// VOC-K1e LAP_COUNT_MAX; the host offers Seek only for D <= 59,999 s).
constexpr uint16_t CC_LAP_COUNT_MAX = 59999;

struct CCButton {
    char label[17] = {};                   // <= 16 B (section 5.1)
    bool enabled = false;
    uint8_t icon = CC_ICON_NONE;
    // True when the wire carried "icon" (every v2+ sender does). False only for
    // legacy frames without icons, whose tone falls back to the label.
    bool iconSent = false;
    // v5 (presentation >= 5): raw app colour, meaningful only with lit on (the assigned snap
    // side; the knob applies sat()). v4 and older senders: legacy, never used for LEDs.
    uint32_t color = 0;
    uint8_t lit = CC_LIT_NONE;             // v5 CCButtonLit (section 5.1)
};

struct CCFrame {
    // Required legacy text (byte capacities = size - 1, section 3).
    char mode[25] = {}, target[65] = {}, value[65] = {}, detail[97] = {}, status[65] = {};
    // Optional text.
    char title[97] = {}, subtitle[97] = {};
    char counter[25] = {};                 // Legacy; v4 renderers ignore it.
    char heading[33] = {}, meta[97] = {};  // v4
    char artKey[65] = {}, volumeCaption[97] = {};
    // 1.0.0-cc5.3 (ARTWORK2.md section 6): the selected Windows entry's app icon, a media key
    // [A-Za-z0-9_-]{0,24}. Only kept on the windows layout; "" otherwise (never rejected).
    char iconKey[25] = {};
    uint8_t layoutId = CC_LAYOUT_NOW_PLAYING;   // Derived from mode when absent (section 2).
    uint8_t restLayout = CC_LAYOUT_NOW_PLAYING; // CC_LAYOUT_NOW_PLAYING or CC_LAYOUT_IDLE.
    uint8_t titleTone = CC_TITLE_INK;
    uint8_t metaTone = CC_LINE_META, statusTone = CC_LINE_META;
    uint8_t page = 0;
    bool artDim = false;
    uint8_t confirmedVolume = 0;           // Defaults to ringValue.
    bool coloredLeds = false;              // ledStyle "color"; "white" by default.
    uint8_t activity = CC_IDLE;
    bool feedbackPresent = false;
    uint8_t feedbackKind = CC_FEEDBACK_OK;
    uint32_t feedbackSeq = 0;              // 1..0x7FFFFFFF when present.
    CCButton buttons[4];
    uint8_t ringStyle = CC_RING_OFF;
    uint8_t ringValue = 0;
    uint16_t ringIndex = 0, ringCount = 0; // Absolute.
    uint16_t ringFirst = 0;                // First transmitted entry (section 4 window rule).
    bool ringExternal = false;
    uint8_t ringColorCount = 0;            // Accents for entries ringFirst + k.
    int32_t ringMoreIndex = -1;
    uint32_t ringColors[20] = {}, ringUnavailable = 0;
    // 1.0.0-cc5.4 "Warm · alive" (ALIVE.md section 3), sent only by a host that negotiated the
    // `alive` capability. Every field is optional; absent keeps these defaults. An invalid value
    // rejects the frame (cc_frame_parse.cpp); a valid one outside its scope is stripped.
    int8_t playing = -1;                   // -1 absent, 0 false, 1 true; kept on Home layouts only
    int8_t feedbackSkip = 0;               // 0 none, -1/1; kept only with feedbackKind ok
    bool clockPresent = false;
    uint16_t clockMinute = 0;              // local minutes since midnight, 0..1439 (latched)
    bool progressPresent = false;
    uint32_t progressPos = 0, progressDur = 0; // ms, 0..86400000, pos <= dur unless dur == 0 (clears)
    bool ledDrivePresent = false;
    uint8_t ledDrive = 0;                  // 1..255 (latched)
    bool ledDitherPresent = false;
    bool ledDither = false;                // latched; absent = off (ALIVE.md 9, the 2026-09-26 ruling)
    // Presentation 5 (PRESENTATION_V5.md section 3.6), sent only to a knob with presentation >= 5
    // (the two LED tuning fields only with `alive`). Defaults = absent. Header only: the parser
    // and the engine read them once their packages land. Laid out so the three words come first
    // and the eight single bytes pack into two words (+20 B per CCFrame, +4 B per CCButton).
    int32_t ringNow = -1;                  // -1 none; -1..count-1, kept only on selection + upnext
                                           // (int32_t: `now` reaches 65,534, section 4.1)
    uint32_t feedbackColor = 0;            // 0..0xFFFFFF raw (0 = warm), only with moment snap/started
    uint32_t ledPink = 0;                  // 0..0xFFFFFF, latched (0 = the built-in PINK; section 7.3)
    bool ringCard = false;                 // entry count-1 is the Sonos card (section 4.4, VOC-K1a)
    uint8_t feedbackMoment = CC_MOMENT_NONE; // CCFeedbackMoment, 0 unless feedbackKind ok
    int8_t feedbackSide = 0;               // -1 left / 1 right, only with moment snap
    bool reducedMotionPresent = false;
    bool reducedMotion = false;            // latched, reset to false at every claim (section 7.1)
    bool ledPinkPresent = false;
    bool ledVolFullPresent = false;
    bool ledVolFull = false;               // latched (section 7.3); unset = false
};

// LCD inks (PRESENTATION_V5.md section 8.3; VOC section 11). Tones and footer colours follow
// section 5.2 (v5; V4's section 5.9 was the presentation-4 subset).
namespace CCInk {
constexpr uint32_t background = 0x000000;
constexpr uint32_t text = 0xF2F2F2;         // ink
constexpr uint32_t context = 0xA6A6A6;      // secondary
constexpr uint32_t muted = 0x5A5A5A;        // disabled footer (= CCFooterInk::dim); not the "muted" title tone
constexpr uint32_t line = 0x242B30;
constexpr uint32_t ice = 0xBDC9D0;
constexpr uint32_t green = 0x6ED996;
constexpr uint32_t red = 0xFF8474;
constexpr uint32_t meta = 0x7C7C7C;        // meta line tone and the "muted" title tone
constexpr uint32_t footer = 0xE6E6E6;       // nav footer
constexpr uint32_t error = 0xFF8474;        // v5 (VOC-R10; V4 drew #FF8A7A)
constexpr uint32_t success = 0x7EE0A2;
constexpr uint32_t tile = 0x444444;         // Windows letter tile (no app accent)
constexpr uint32_t tileInitial = 0xF2F2F2;  // initial on the #444 tile (AW2 section 7)
constexpr uint32_t accentInitial = 0xFFFFFF;  // initial on an app-accent tile (section 5.3)
constexpr uint32_t disabledGlyph = 0x555555;
constexpr uint32_t shadow = 0x000000;       // text-shadow twins (section 8.5.3)
}

// LCD footer / idle-row ink per button tone (section 5.2).
namespace CCFooterInk {
constexpr uint32_t none = 0x000000;         // hidden
constexpr uint32_t dim = 0x5A5A5A;          // v5 (S01:49; V4 #4A4A4A)
constexpr uint32_t stop = 0xFF8474;
constexpr uint32_t go = 0x6ED996;
constexpr uint32_t nav = 0xE6E6E6;
constexpr uint32_t on = 0xFFFFFF;           // lit on (row 6; accent_ink()'s fallback)
constexpr uint32_t off = 0x7A7A7A;          // lit off (row 7)
constexpr uint32_t liked = 0xA3244A;        // [r2.2] row 4: the filled heart (never PINK, never sat())
}

// LED model constants (section 5): palette, drive levels and timing. Separate
// from the LCD inks. Levels scale each channel as (c*level + 127) / 255 before
// the global FastLED brightness cap.
namespace CCLed {
constexpr uint32_t white = 0xFFFFFF;
constexpr uint32_t green = 0x46E178;
constexpr uint32_t red = 0xFF4834;
constexpr uint32_t amber = 0xFF961E;
constexpr uint32_t volumeRed = 0xFF3723;
constexpr uint8_t levels[5] = {0, 15, 46, 102, 204}; // L0..L4
constexpr uint8_t L0 = 0, L1 = 15, L2 = 46, L3 = 102, L4 = 204;
constexpr uint8_t shoulder = 74;            // odd-v volume shoulder (deviation 1)
// easeOutQuint sampled at t = 0..1 in 1/16 steps, x255 (linear between entries).
constexpr uint8_t easeLut[17] = {0, 67, 123, 165, 195, 216, 230, 239, 245, 249, 252, 253, 254, 255, 255, 255, 255};
constexpr uint32_t pulseMs = 260;           // one pending/loading phase
constexpr uint32_t pendingHoldMs = 3000;    // pending pulse holds L1 afterwards
constexpr uint32_t decayMs = 260;           // ring segment decay
constexpr uint32_t buttonFadeMs = 220;
constexpr uint32_t flashOkMs = 650;
constexpr uint32_t flashErrMs = 900;
}

// Host window rule (section 4): first = 0 when count <= 20, otherwise
// clamp(index-9, 0, count-20). Also the parser's derivation for an absent first.
inline uint16_t cc_window_first(uint16_t index, uint16_t count) {
    if (count <= CC_RING_WINDOW) return 0;
    const int32_t first = static_cast<int32_t>(index) - 9;
    const int32_t last = static_cast<int32_t>(count) - static_cast<int32_t>(CC_RING_WINDOW);
    return static_cast<uint16_t>(first < 0 ? 0 : (first > last ? last : first));
}

// Legacy frames without icons: the controller's label -> icon table.
inline uint8_t cc_legacy_icon(const char* label) {
    if (!strcmp(label, "Play")) return CC_ICON_PLAY;
    if (!strcmp(label, "Pause")) return CC_ICON_PAUSE;
    if (!strcmp(label, "Browse")) return CC_ICON_LIST;
    if (!strcmp(label, "Win")) return CC_ICON_WIN;
    if (!strcmp(label, "Tracks")) return CC_ICON_TRACKS;
    if (!strcmp(label, "Back")) return CC_ICON_BACK;
    if (!strcmp(label, "Home")) return CC_ICON_HOME;
    if (!strcmp(label, "More")) return CC_ICON_MORE;
    if (!strcmp(label, "Prev")) return CC_ICON_PREV;
    if (!strcmp(label, "Next") || !strcmp(label, "Skip")) return CC_ICON_NEXT;
    if (!strcmp(label, "Switch")) return CC_ICON_SWITCH;
    if (!strcmp(label, "Cancel")) return CC_ICON_CANCEL;
    return CC_ICON_NONE;
}

// The icon a button presents: the wire icon, or for a legacy frame without
// icons the label mapping. A sent "" stays none (tone none).
inline uint8_t cc_button_icon(const CCButton& button) {
    if (button.icon != CC_ICON_NONE || button.iconSent) return button.icon;
    return cc_legacy_icon(button.label);
}

// Presentation roles follow available actions, never a button's fixed position
// or a legacy sender's color. The controller's enabled flag is authoritative.
inline bool cc_button_available(const CCFrame& frame, uint8_t index) {
    return index < 4 && frame.buttons[index].enabled;
}

// The Home layouts of the section 5.2 go rule (row 9) and of the display's `home` group.
inline bool cc_home_layout(uint8_t layout) {
    return layout == CC_LAYOUT_NOW_PLAYING || layout == CC_LAYOUT_VOLUME || layout == CC_LAYOUT_IDLE ||
           layout == CC_LAYOUT_NOTICE;
}

// PRESENTATION_V5.md section 5.2 (VOC section 2.3): the tone of button `slot`, first match wins.
// The icon is the effective one (cc_button_icon: the wire token, or the label map of a legacy
// frame without icons); `lit` is kept by the parser only from presentation-5 senders.
//   1 icon ""                        none      6 lit on                  on (#FFFFFF)
//   2 !enabled                       dim       7 lit off                 off
//   3 slot 0 . cancel                stop      8 slot 3 . play/prev/next/switch   go
//   4 lit on . heart   [r2.2]        liked     9 Home layout . slot 0 . play      go (paused Play)
//   5 lit on . color != 0            on + accent_ink(color)            10 otherwise nav
inline uint8_t cc_button_tone(const CCFrame& frame, uint8_t slot) {
    if (slot >= 4) return CC_TONE_NONE;
    const CCButton& button = frame.buttons[slot];
    const uint8_t icon = cc_button_icon(button);
    if (icon == CC_ICON_NONE) return CC_TONE_NONE;
    if (!button.enabled) return CC_TONE_DIM;
    if (slot == 0 && icon == CC_ICON_CANCEL) return CC_TONE_STOP;
    if (button.lit == CC_LIT_ON) return icon == CC_ICON_HEART ? CC_TONE_LIKED : CC_TONE_ON;
    if (button.lit == CC_LIT_OFF) return CC_TONE_OFF;
    if (slot == 3 && (icon == CC_ICON_PLAY || icon == CC_ICON_PREV ||
                      icon == CC_ICON_NEXT || icon == CC_ICON_SWITCH)) return CC_TONE_GO;
    if (slot == 0 && icon == CC_ICON_PLAY && cc_home_layout(frame.layoutId)) return CC_TONE_GO;
    return CC_TONE_NAV;
}

// Footer / idle-row ink of a tone (0 = hidden). Tone `on` is #FFFFFF here; a lit button with an app
// colour draws accent_ink(color) instead (cc_button_ink).
inline uint32_t cc_footer_ink(uint8_t tone) {
    switch (tone) {
        case CC_TONE_DIM: return CCFooterInk::dim;
        case CC_TONE_STOP: return CCFooterInk::stop;
        case CC_TONE_GO: return CCFooterInk::go;
        case CC_TONE_NAV: return CCFooterInk::nav;
        case CC_TONE_ON: return CCFooterInk::on;
        case CC_TONE_OFF: return CCFooterInk::off;
        case CC_TONE_LIKED: return CCFooterInk::liked;
        default: return CCFooterInk::none;
    }
}

// ALIVE.md section 2 sat() in exact integers (presentation.sat_rgb, cc_alive's sat): each channel
// round(max(0, x - 0.75 mn) / (mx - 0.75 mn) * 255), half away from zero. False (WARM fallback)
// when max - min < 30.
inline bool cc_sat(uint32_t color, uint32_t& out) {
    const uint32_t r = (color >> 16) & 255u, g = (color >> 8) & 255u, b = color & 255u;
    const uint32_t mx = r > g ? (r > b ? r : b) : (g > b ? g : b);
    const uint32_t mn = r < g ? (r < b ? r : b) : (g < b ? g : b);
    if (mx - mn < 30u) return false;
    const uint32_t den = 4u * mx - 3u * mn;
    const uint32_t ch[3] = {r, g, b};
    out = 0;
    for (uint8_t k = 0; k < 3; ++k) {
        const uint32_t x4 = 4u * ch[k];
        const uint32_t num = 255u * (x4 > 3u * mn ? x4 - 3u * mn : 0u);
        const uint32_t v = (2u * num + den) / (2u * den);
        out = (out << 8) | (v > 255u ? 255u : v);
    }
    return true;
}

// sRGB -> linear light x 1e9, rounded (the relative-luminance test of accent_ink without floats;
// presentation.relative_luminance uses doubles: equal decisions for every 24-bit colour away from
// the 1e-9 neighbourhood of the threshold, checked over the shared vectors by the LCD harness).
constexpr uint32_t CC_LINEAR_1E9[256] = {
    0u, 303527u, 607054u, 910581u, 1214108u, 1517635u, 1821162u, 2124689u, 2428216u, 2731743u,
    3035270u, 3346536u, 3676507u, 4024717u, 4391442u, 4776953u, 5181517u, 5605392u, 6048833u, 6512091u,
    6995410u, 7499032u, 8023193u, 8568126u, 9134059u, 9721217u, 10329823u, 10960094u, 11612245u, 12286488u,
    12983032u, 13702083u, 14443844u, 15208514u, 15996293u, 16807376u, 17641954u, 18500220u, 19382361u, 20288563u,
    21219010u, 22173885u, 23153366u, 24157632u, 25186860u, 26241222u, 27320892u, 28426040u, 29556834u, 30713444u,
    31896033u, 33104767u, 34339807u, 35601315u, 36889450u, 38204372u, 39546235u, 40915197u, 42311411u, 43735029u,
    45186204u, 46665086u, 48171824u, 49706566u, 51269458u, 52860647u, 54480276u, 56128490u, 57805430u, 59511238u,
    61246054u, 63010018u, 64803267u, 66625939u, 68478170u, 70360096u, 72271851u, 74213568u, 76185381u, 78187422u,
    80219820u, 82282707u, 84376212u, 86500462u, 88655586u, 90841711u, 93058963u, 95307467u, 97587347u, 99898728u,
    102241733u, 104616484u, 107023103u, 109461711u, 111932428u, 114435374u, 116970668u, 119538428u, 122138772u, 124771818u,
    127437680u, 130136477u, 132868322u, 135633330u, 138431615u, 141263291u, 144128471u, 147027266u, 149959790u, 152926152u,
    155926464u, 158960835u, 162029376u, 165132195u, 168269400u, 171441101u, 174647404u, 177888416u, 181164244u, 184474995u,
    187820772u, 191201683u, 194617830u, 198069320u, 201556254u, 205078736u, 208636870u, 212230757u, 215860500u, 219526200u,
    223227957u, 226965874u, 230740049u, 234550582u, 238397574u, 242281122u, 246201327u, 250158285u, 254152094u, 258182853u,
    262250658u, 266355605u, 270497791u, 274677312u, 278894263u, 283148740u, 287440838u, 291770650u, 296138271u, 300543794u,
    304987314u, 309468923u, 313988713u, 318546778u, 323143209u, 327778098u, 332451536u, 337163615u, 341914425u, 346704056u,
    351532600u, 356400144u, 361306780u, 366252596u, 371237680u, 376262123u, 381326011u, 386429434u, 391572478u, 396755231u,
    401977780u, 407240212u, 412542613u, 417885071u, 423267670u, 428690497u, 434153636u, 439657174u, 445201195u, 450785783u,
    456411023u, 462077000u, 467783796u, 473531496u, 479320183u, 485149940u, 491020850u, 496932995u, 502886458u, 508881321u,
    514917665u, 520995573u, 527115126u, 533276404u, 539479489u, 545724461u, 552011402u, 558340390u, 564711506u, 571124829u,
    577580440u, 584078418u, 590618841u, 597201788u, 603827339u, 610495571u, 617206562u, 623960392u, 630757136u, 637596874u,
    644479682u, 651405637u, 658374817u, 665387298u, 672443157u, 679542470u, 686685312u, 693871761u, 701101892u, 708375780u,
    715693501u, 723055129u, 730460740u, 737910409u, 745404210u, 752942217u, 760524505u, 768151147u, 775822218u, 783537792u,
    791297940u, 799102738u, 806952258u, 814846572u, 822785754u, 830769877u, 838799012u, 846873232u, 854992608u, 863157213u,
    871367119u, 879622397u, 887923118u, 896269353u, 904661174u, 913098652u, 921581856u, 930110858u, 938685728u, 947306537u,
    955973353u, 964686248u, 973445290u, 982250550u, 991102097u, 1000000000u};

// Relative luminance >= 0.10 (>= 3:1 against black): 2126 R + 7152 G + 722 B of CC_LINEAR_1E9 >= 1e12.
inline bool cc_luminance_ok(uint32_t color) {
    const uint64_t y = 2126ull * CC_LINEAR_1E9[(color >> 16) & 255u] + 7152ull * CC_LINEAR_1E9[(color >> 8) & 255u] +
                       722ull * CC_LINEAR_1E9[color & 255u];
    return y >= 1000000000000ull;
}

// Section 5.3: the LCD ink of an assigned snap side (lit on + color), integer in/out. 0, or a colour
// whose sat() falls back to WARM -> #FFFFFF; else s = sat(c) lifted towards white in eighths,
// m_j = s + ((255 - s) * j + 4) / 8 per channel, j = 0..8: the first m_j with relative luminance
// >= 0.10 (j = 8 is white). Navy 0x000080 -> sat 0x0000FF -> j = 2 -> 0x4040FF.
inline uint32_t cc_accent_ink(uint32_t color) {
    uint32_t s = 0;
    if (color == 0 || !cc_sat(color, s)) return CCFooterInk::on;
    for (uint32_t j = 0; j <= 8u; ++j) {
        uint32_t lifted = 0;
        for (int shift = 16; shift >= 0; shift -= 8) {
            const uint32_t c = (s >> shift) & 255u;
            lifted = (lifted << 8) | (c + ((255u - c) * j + 4u) / 8u);
        }
        if (cc_luminance_ok(lifted)) return lifted;
    }
    return CCFooterInk::on;
}

// LCD footer / idle-row ink of button `index` (section 5.2 rows 1-10): the tone's ink, except tone
// `on` with an app colour, which draws cc_accent_ink(color) (row 5; the heart never reaches it).
inline uint32_t cc_button_ink(const CCFrame& frame, uint8_t index) {
    const uint8_t tone = cc_button_tone(frame, index);
    if (tone == CC_TONE_ON && frame.buttons[index].color != 0) return cc_accent_ink(frame.buttons[index].color);
    return cc_footer_ink(tone);
}

// Section 4.3: the Seek time m:ss ("%u:%02u", minutes unpadded) of `seconds` into out (>= 8 B for
// every lap value, <= 999:59). Integer only; both ports format identically.
inline void cc_mmss(uint32_t seconds, char* out, uint32_t cap) {
    if (!out || cap == 0) return;
    char digits[12];
    uint32_t n = 0, minutes = seconds / 60u;
    do { digits[n++] = static_cast<char>('0' + minutes % 10u); minutes /= 10u; } while (minutes && n < 10u);
    uint32_t k = 0;
    while (n && k + 1 < cap) out[k++] = digits[--n];
    const char tail[3] = {':', static_cast<char>('0' + (seconds % 60u) / 10u), static_cast<char>('0' + seconds % 10u)};
    for (uint32_t i = 0; i < 3 && k + 1 < cap; ++i) out[k++] = tail[i];
    out[k] = '\0';
}

// LCD ink of titleTone / metaTone / statusTone (section 3).
inline uint32_t cc_title_ink(uint8_t tone) {
    return tone == CC_TITLE_MUTED ? CCInk::meta : CCInk::text;
}

inline uint32_t cc_line_ink(uint8_t tone) {
    switch (tone) {
        case CC_LINE_SECONDARY: return CCInk::context;
        case CC_LINE_ERROR: return CCInk::error;
        case CC_LINE_SUCCESS: return CCInk::success;
        default: return CCInk::meta;
    }
}
