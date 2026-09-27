#include "cc_display.h"
#include "cc_icons.h"
#include "fonts/cc_fonts.h"
#include <stdio.h>
#include <string.h>

#ifndef CC_TEXT_TWINS
#define CC_TEXT_TWINS 1
#endif
#ifndef CC_DISPLAY_FULL_LAYERS
#define CC_DISPLAY_FULL_LAYERS 0
#endif

// cc5.4 LCD renderer: presentation 5 (PRESENTATION_V5.md section 8; r2.1 S01 section 3 and App A,
// the Browse and Snap knob markup BS:279-335 and renderVals BS:1232-1297; [r2.2] tone `liked`).
//
// Tree (created once, never rebuilt; section 8.2):
//   screen (black)
//   `- stage            no animation (V4's stage fade is gone, RF3 R2b)
//      |- art           240 px cover; never translates; fades only on show/hide (240 ms)
//      |- content       translate_x +-20 and opacity of a screen change; bounded y 28..163
//      |  |- heading (+twin)
//      |  |- home       track{title, artist} volume{caption, digits, percent} status idle[4]
//      |  |- list       recent, explorer, upnext, notice: title, sub, meta
//      |  |- tracks     title, prev/dotfill/next, sub, meta
//      |  |- seek       caption, 48 px tabular time, 14 px line
//      |  |- windows    tile{letter, 32 px app icon}, app, title, meta
//      |  `- offline    title, sub (firmware-local "Waiting for PC", section 8.10)
//      `- footer[4]     20 px icons; never slides or fades on a screen change
//
// Every animated layer is bounded to its content box (section 8.2 R2); the harness compiles the
// same unit with CC_DISPLAY_FULL_LAYERS=1 and proves identical pixels (`v5_bounded`). Twelve labels
// carry a text-shadow twin (section 8.5.3): a black copy at text_opa 204, one pixel lower, created
// first so it draws below its label. Motion is translate and opacity only (no transforms, no
// opa_layered: the LVGL heap is 64 KB). SPR overshoot drives translate only; opacity uses the
// OUT/IN curves and is clamped to 0..255.
//
// Artwork (ARTWORK2.md section 7; section 8.4): the art image shows the front of two 240 px
// buffers; a new key is decoded (JPEG) or upscaled (v1) into the back buffer and the two swap
// (instant over a visible cover; 240 ms fades only on show/hide). With the R5 hooks
// (CCDisplayMedia::requestCover/pollCover/cancelCover, section 12.5) the decode runs in another
// task: the render posts it and keeps the previous cover until a later render consumes the result.

namespace {

// ---------------------------------------------------------------- geometry --
constexpr int32_t SAFE_R = 104;          // optical safe circle around (120,120)
constexpr int32_t HEADING_R = 112;       // headings may reach r112 (section 8.3; the bezel hides r112..120)
constexpr int32_t CENTER = 120;

struct Box { int16_t x, y, w, h; };
// Label boxes, absolute {x, y = LVGL label top, w, h} (section 8.5.1). y puts the baseline on the
// design's CSS baseline: y = round(CSS top + CSS baseline offset) - ascent.
constexpr Box HEADING = {51, 31, 138, CC_FONT_12_LINE_HEIGHT};
constexpr Box HOME_TITLE = {35, 61, 170, 2 * CC_FONT_22_LINE_HEIGHT + 2};
constexpr Box HOME_ARTIST = {35, 115, 170, CC_FONT_14_LINE_HEIGHT};
constexpr Box STATUS = {40, 133, 160, CC_FONT_12_LINE_HEIGHT};
constexpr Box VOL_CAPTION = {35, 53, 170, CC_FONT_14_LINE_HEIGHT};
constexpr int16_t DIGITS_Y = 73;         // 48 px digits: baseline 116
constexpr int16_t PERCENT_Y = 96;        // 22 px '%': baseline 116
constexpr int16_t DIGIT_GAP = 2;
constexpr Box LIST_TITLE = {35, 53, 170, 2 * CC_FONT_22_LINE_HEIGHT + 2};
constexpr Box LIST_SUB = {35, 107, 170, CC_FONT_14_LINE_HEIGHT};
constexpr Box LIST_META = {35, 126, 170, CC_FONT_12_LINE_HEIGHT};
constexpr Box TRACKS_TITLE = {35, 55, 170, CC_FONT_22_LINE_HEIGHT};
constexpr Box TRACKS_SUB = {35, 111, 170, CC_FONT_14_LINE_HEIGHT};
constexpr Box TRACKS_META = {35, 129, 170, CC_FONT_12_LINE_HEIGHT};
constexpr int16_t TRACKS_POS_X[3] = {72, 112, 152};
constexpr int16_t TRACKS_POS_Y = 88;
constexpr Box SEEK_CAPTION = {35, 53, 170, CC_FONT_14_LINE_HEIGHT};
constexpr Box SEEK_TIME = {0, 73, 240, CC_FONT_48T_LINE_HEIGHT};
constexpr Box SEEK_LINE = {35, 129, 170, CC_FONT_14_LINE_HEIGHT};
constexpr Box TILE = {104, 42, 32, 32};
// 16 px initial on the tile's CSS 16/16 line, centred in the 32 px tile: line top 42 + 8 = 50,
// baseline 50 + 13.74 = 64 (label top 42 + 7, ascent 15).
constexpr int16_t TILE_LETTER_Y = 7;
constexpr Box WIN_APP = {35, 81, 170, CC_FONT_14_LINE_HEIGHT};
constexpr Box WIN_TITLE = {35, 99, 170, 2 * CC_FONT_16_LINE_HEIGHT + 2};
constexpr Box WIN_META = {35, 139, 170, CC_FONT_12_LINE_HEIGHT};
constexpr Box OFF_TITLE = {35, 71, 170, CC_FONT_22_LINE_HEIGHT};
constexpr Box OFF_SUB = {35, 105, 170, 2 * CC_FONT_14_LINE_HEIGHT + 2};
constexpr int16_t FOOTER_CX[4] = {56, 99, 141, 184};
constexpr int16_t FOOTER_Y = 154;
constexpr int16_t FOOTER_ICON = 20;
constexpr int16_t IDLE_CX[4] = {51, 97, 143, 189};
constexpr int16_t IDLE_Y = 100;
constexpr int16_t IDLE_ICON = 26;
constexpr int16_t IDLE_COLUMN_W = 60;
constexpr int16_t IDLE_WORD_DY = 33;     // words at y 133 (CSS top 134, 12/14)
constexpr int16_t POS_ICON = 16;
constexpr int16_t LINE_SPACE = 2;        // two-line labels: 22/26, 16/20 and 14/18 pitches
constexpr int8_t HEADING_TRACKING = 1;   // 0.04 em is not representable: 1 px (P5-1)
constexpr int8_t DIGITS_TRACKING = -1;   // letter-spacing -0.02em at 48 px (volume and Seek)
constexpr uint8_t TILE_CLOSED_OPA = 89;  // 0.35
constexpr uint8_t ART_DIM_OPA = 112;     // 0.35 / 0.8 over pre-composited pixels
constexpr int32_t SLIDE_PX = 20;
constexpr uint8_t TWIN_OPA = 204;        // text shadow 0 1px 0 at 80 % (section 8.5.3)

// Layer boxes (absolute). Bounded (section 8.2 R2): each animated layer covers only what it draws
// at every point of its motion. content: the heading row (y 31) to the idle row's +14 px start
// (148 + 14 = 162). home: the content box (it holds the translating track/volume/idle layers).
#if CC_DISPLAY_FULL_LAYERS
constexpr Box FULL = {0, 0, 240, 240};
constexpr Box CONTENT_BOX = FULL, TRACK_BOX = FULL, VOLUME_BOX = FULL, LIST_BOX = FULL, TRACKS_BOX = FULL,
              SEEK_BOX = FULL, WINDOWS_BOX = FULL, OFFLINE_BOX = FULL, FOOTER_BOX = FULL, HOME_BOX = FULL;
#else
constexpr Box CONTENT_BOX = {0, 28, 240, 136};
constexpr Box HOME_BOX = CONTENT_BOX;
constexpr Box TRACK_BOX = {35, 61, 170, 71};     // title, artist and their twins: rows 61..131
constexpr Box VOLUME_BOX = {0, 53, 240, 74};     // caption, digits, percent and twins: rows 53..126
constexpr Box LIST_BOX = {35, 53, 170, 88};      // rows 53..140
constexpr Box TRACKS_BOX = {35, 55, 170, 89};    // rows 55..143
constexpr Box SEEK_BOX = {0, 53, 240, 92};       // rows 53..144
constexpr Box WINDOWS_BOX = {35, 42, 170, 112};  // rows 42..153
constexpr Box OFFLINE_BOX = {35, 71, 170, 68};   // rows 71..138
constexpr Box FOOTER_BOX = {44, 152, 152, 24};   // icons x 46..193, rows 154..173
#endif

// Firmware-local copy (section 8.10; VOC knob.title.offline, knob.sub.offline(_native)).
const char OFFLINE_TITLE[] = "Waiting for PC";
// Desk Dial (the rename, rename-desk-dial.md C1): "Desk Dial" is held together by a no-break space
// (U+00A0, UTF-8 C2 A0; cc_font_14 draws it 4 px wide, like a space). fitTwoLines breaks only at
// ASCII spaces, so the two balanced lines are "Open Desk Dial" / "on your PC", never "Open Desk" /
// "Dial on your PC" (5.2, 11.5). The literal is split because "\xA0Dial" would read \xA0D as one
// hex escape.
const char OFFLINE_SUB[] = "Open Desk\xC2\xA0" "Dial on your PC";
const char OFFLINE_NATIVE[] = "Knob controls still work";
// K1 8.10 erratum (lead ruling R-c): the native sub-line is one line, and with the knob font it is
// 171 px (LVGL sums whole-pixel kerned advances; 167.5 px in the design's metrics) against the
// 170 px line. Rather than wrap it or change the approved words, it is drawn at -1 px tracking
// (148 px) whenever it does not fit at 0; the two-line "Open Desk Dial on your PC" keeps 0.
constexpr int8_t OFFLINE_NATIVE_TRACKING = -1;

// ------------------------------------------------------------------ motion --
enum Ease : uint8_t { EASE_OUT, EASE_IN, EASE_SPR };
struct Curve { int16_t x1, y1, x2, y2; };
constexpr Curve CURVES[3] = {
    {static_cast<int16_t>(LV_BEZIER_VAL_FLOAT(0.22)), static_cast<int16_t>(LV_BEZIER_VAL_FLOAT(1.0)),
     static_cast<int16_t>(LV_BEZIER_VAL_FLOAT(0.36)), static_cast<int16_t>(LV_BEZIER_VAL_FLOAT(1.0))},
    {static_cast<int16_t>(LV_BEZIER_VAL_FLOAT(0.4)), static_cast<int16_t>(LV_BEZIER_VAL_FLOAT(0.0)),
     static_cast<int16_t>(LV_BEZIER_VAL_FLOAT(1.0)), static_cast<int16_t>(LV_BEZIER_VAL_FLOAT(1.0))},
    {static_cast<int16_t>(LV_BEZIER_VAL_FLOAT(0.34)), static_cast<int16_t>(LV_BEZIER_VAL_FLOAT(1.45)),
     static_cast<int16_t>(LV_BEZIER_VAL_FLOAT(0.64)), static_cast<int16_t>(LV_BEZIER_VAL_FLOAT(1.0))},
};

// Section 8.8 durations (VOC-K1d) not already named above.
constexpr uint32_t ART_FADE_MS = 240;
constexpr uint32_t INK_FADE_MS = 160;
constexpr uint32_t LINE_FADE_MS = 160;
constexpr uint32_t CONTENT_FADE_MS = 220;
constexpr uint32_t CONTENT_SLIDE_MS = 380;

// Wire icon tokens by CCIcon value (section 9.1; append-only, VOC section 1.2).
const char* const ICON_NAMES[] = {"", "play", "pause", "list", "win", "tracks", "back", "home", "more",
                                  "prev", "next", "switch", "cancel", "expand", "clock", "playlists",
                                  "playnext", "seek", "shuffle", "heart", "snapleft", "snapright"};
constexpr uint8_t ICON_COUNT = sizeof(ICON_NAMES) / sizeof(ICON_NAMES[0]);
// Internal masks: the Tracks position-row centre and, [r2.2], the liked heart (tone liked).
const char DOT_GLYPH[] = "dotfill";
const char LIKED_GLYPH[] = "heartfill";

// Display groups (section 8.7; VOC section 1.2 plus VOC-K1b offline).
enum Group : uint8_t {
    GROUP_HOME, GROUP_RECENT, GROUP_TRACKS, GROUP_WINDOWS, GROUP_EXPLORER, GROUP_UPNEXT, GROUP_OFFLINE
};

// ------------------------------------------------------------------- state --
constexpr size_t SRC_CAP = 100;          // wire text <= 96 bytes + NUL
constexpr size_t TEXT_CAP = 112;         // fitted: line1 '\n' line2 U+2026 NUL

struct Layer {
    lv_obj_t* obj;
    int16_t x, y;                        // absolute origin
};

struct Label {
    lv_obj_t* obj;
    lv_obj_t* twin;                      // text-shadow twin, or nullptr
    const lv_font_t* font;
    int16_t x, y, w;                     // absolute rest box (safe-circle fitting)
    int16_t centerX;                     // absolute horizontal centre of the text
    int16_t radius;                      // fitting radius: 104, or 112 for the heading
    int8_t tracking;                     // letter space applied
    uint8_t lines;                       // 1 or 2
    bool inkSet;
    uint32_t ink;                        // target ink
    uint32_t shownInk;                   // ink on screen (differs during an ink crossfade)
    uint32_t fadeFrom;
    char src[SRC_CAP];                   // source text of the current fit
};

struct Icon {
    lv_obj_t* obj;
    const lv_image_dsc_t* src;           // glyph shown, nullptr = hidden
    int16_t size;
    bool inkSet;
    uint32_t ink, shownInk, fadeFrom;
};

enum Prop : uint8_t { PROP_OPA, PROP_TX, PROP_TY };
struct Tween {
    lv_obj_t* obj;
    uint8_t prop;
    bool set;
    int32_t target;
};

struct View {
    bool rendered;
    uint8_t group, page, layout;
    bool homeish;
    bool row;                            // the idle row was shown (idle base, no volume reveal)
    bool footerShown;                    // footer target 255
};

lv_obj_t* screen = nullptr;
lv_obj_t* stage = nullptr;
lv_obj_t* art = nullptr;
Layer content, homeLayer, trackLayer, volumeLayer, listLayer, tracksLayer, seekLayer, windowsLayer,
    offlineLayer, footerLayer;
lv_obj_t* idleColumn[4] = {};
lv_obj_t* tile = nullptr;

Label heading, homeTitle, homeArtist, status, volumeCaption, digits, percent;
Label idleWord[4];
Label listTitle, listSub, listMeta;
Label tracksTitle, tracksSub, tracksMeta;
Label seekCaption, seekTime, seekLine;
Label tileLetter, winApp, winTitle, winMeta;
Label offTitle, offSub;
Icon idleIcon[4], footerIcon[4], positionIcon[3];

Tween trackOpa, trackTy, volumeOpa, volumeTy, statusOpa, footerOpa, artOpa, contentTx, contentOpa;
Tween idleOpa[4], idleTy[4];
Tween listMetaOpa, tracksMetaOpa, winMetaOpa, offSubOpa;

View view = {};
CCDisplayStats stats = {};
bool changed = false;                    // this render changed something
bool animated = false;                   // this render started an animation
int32_t digitsWidth = -1, percentWidth = -1;
uint8_t tileOpa = 255;
uint32_t tileBg = CCInk::tile;
bool reducedMotion = false;              // latched (section 7.1): reset by release/offline (claims)

// Offline layer (section 8.10).
bool offline = false;
bool offlineNative = false;
bool offlinePinsHeld = false;
uint32_t offlineAt = 0;

// Caller-owned 240x240 RGB565 artwork buffers (PSRAM on the device). The art image shows
// artBuffer[artFront]; a new cover is written into the other one (when there are two) and they
// swap. artKeyOf[i] names the pixels of buffer i ("" while it holds none, or partly written ones,
// or while the R5 decoder owns it).
uint8_t* artBuffer[2] = {nullptr, nullptr};
lv_image_dsc_t artDsc[2];
char artKeyOf[2][sizeof(CCFrame::artKey)] = {};
uint8_t artFront = 0;
char artFailedKey[sizeof(CCFrame::artKey)] = {};   // decode failed: no art until the key changes
uint8_t artImageOpa = 255;

// R5 (section 12.5.2): the one decode in flight and whether this renderer cancelled it.
struct Decode {
    bool inFlight;
    bool cancelled;
    char key[sizeof(CCFrame::artKey)];
};
Decode decode = {};

// artwork2 app icon on the Windows tile: 32x32 RGB565 (the wire's little endian bytes are the
// native layout), static like the tile it belongs to.
alignas(4) uint8_t iconPixels[CC_ICON_BYTES];
lv_image_dsc_t iconDsc;
lv_obj_t* tileIcon = nullptr;
char iconLoadedKey[sizeof(CCFrame::iconKey)] = {};  // pixels in iconPixels
bool tileIconShown = false;

// artwork2 store lookups (cc_display_set_media) and whether this renderer holds the store's
// display pin of each kind (CCDisplayMediaKind).
CCDisplayMedia media = {};
bool mediaHeld[2] = {false, false};

char scratch[TEXT_CAP + 8];              // measuring buffer (LVGL runs on one thread)

// -------------------------------------------------------------- utilities --
void copyText(char* out, size_t cap, const char* text) {
    size_t n = strlen(text);
    if (n >= cap) n = cap - 1;
    memcpy(out, text, n);
    out[n] = '\0';
}

// Next code point of valid UTF-8 (the frame parser validated it); advances i.
uint32_t utf8Next(const char* s, size_t& i) {
    const uint8_t c = static_cast<uint8_t>(s[i]);
    size_t n = 1;
    uint32_t cp = c;
    if (c >= 0xF0) { n = 4; cp = c & 0x07u; }
    else if (c >= 0xE0) { n = 3; cp = c & 0x0Fu; }
    else if (c >= 0xC0) { n = 2; cp = c & 0x1Fu; }
    for (size_t k = 1; k < n; ++k) {
        const uint8_t next = static_cast<uint8_t>(s[i + k]);
        if ((next & 0xC0u) != 0x80u) { i += k; return 0xFFFD; }
        cp = (cp << 6) | (next & 0x3Fu);
    }
    i += n;
    return cp;
}

int32_t isqrt(int32_t v) {
    int32_t r = 0;
    while ((r + 1) * (r + 1) <= v) ++r;
    return r;
}

// Half-width of the radius-r circle's chord over pixel rows [top, bottom].
int32_t safeHalf(int32_t top, int32_t bottom, int32_t radius) {
    int32_t half = CENTER;
    for (int32_t y = top; y <= bottom; ++y) {
        const int32_t d = y < CENTER ? CENTER - y : y + 1 - CENTER;
        const int32_t h = d >= radius ? 0 : isqrt(radius * radius - d * d);
        if (h < half) half = h;
    }
    return half;
}

int32_t ascentOf(const lv_font_t* font) { return font->line_height - font->base_line; }

// Ink rows of a text relative to its line top (every glyph, fallback included).
void inkRows(const char* text, const lv_font_t* font, int32_t& top, int32_t& bottom) {
    const int32_t ascent = ascentOf(font);
    top = ascent;
    bottom = ascent - 1;
    for (size_t i = 0; text[i];) {
        const uint32_t letter = utf8Next(text, i);
        lv_font_glyph_dsc_t g;
        if (!lv_font_get_glyph_dsc(font, &g, letter, 0) || g.box_h == 0 || g.box_w == 0) continue;
        const int32_t glyphTop = ascent - g.box_h - g.ofs_y;
        const int32_t glyphBottom = ascent - g.ofs_y - 1;
        if (glyphTop < top) top = glyphTop;
        if (glyphBottom > bottom) bottom = glyphBottom;
    }
}

int32_t widthOf(const char* text, size_t length, const lv_font_t* font, int32_t tracking) {
    if (length >= sizeof(scratch)) length = sizeof(scratch) - 1;
    memcpy(scratch, text, length);
    scratch[length] = '\0';
    return lv_text_get_width(scratch, static_cast<uint32_t>(length), font, tracking);
}

int32_t widthOf(const char* text, const lv_font_t* font, int32_t tracking) {
    return widthOf(text, strlen(text), font, tracking);
}

const char ELLIPSIS[] = "\xE2\x80\xA6";  // U+2026, in every cc_font_<N>

size_t trimRight(const char* text, size_t length) {
    while (length && text[length - 1] == ' ') --length;
    return length;
}

// Width of text[0:length] (trailing spaces trimmed) followed by an ellipsis.
int32_t ellipsizedWidth(const char* text, size_t length, const lv_font_t* font, int32_t tracking) {
    char buffer[TEXT_CAP];
    length = trimRight(text, length);
    if (length > TEXT_CAP - sizeof(ELLIPSIS)) length = TEXT_CAP - sizeof(ELLIPSIS);
    memcpy(buffer, text, length);
    memcpy(buffer + length, ELLIPSIS, sizeof(ELLIPSIS));
    return widthOf(buffer, length + sizeof(ELLIPSIS) - 1, font, tracking);
}

// Appends text (<= maxWidth) to out: whole, or cut at a code point with U+2026 (CSS
// text-overflow: ellipsis). forceEllipsis marks a clamped line whose remainder was dropped: the
// U+2026 is appended even when the text fits.
void appendLine(char* out, size_t cap, const char* text, const lv_font_t* font, int32_t tracking,
                int32_t maxWidth, bool forceEllipsis = false) {
    const size_t used = strlen(out);
    const size_t length = strlen(text);
    if (!forceEllipsis && widthOf(text, length, font, tracking) <= maxWidth) {
        copyText(out + used, cap - used, text);
        return;
    }
    // bounds[k]: byte offset where code point k starts; a prefix of k code points ends at
    // bounds[k] (or at length when k == count). Static: LVGL runs on one thread and this keeps
    // the LCD task stack free.
    static size_t bounds[TEXT_CAP];
    size_t count = 0;
    for (size_t i = 0; text[i] && count < TEXT_CAP;) { bounds[count++] = i; utf8Next(text, i); }
    // Largest kept prefix (in code points) whose ellipsized width fits.
    size_t lo = 0, hi = count, keep = 0;
    while (lo < hi) {
        const size_t mid = (lo + hi + 1) / 2;
        const size_t prefix = mid < count ? bounds[mid] : length;
        if (ellipsizedWidth(text, prefix, font, tracking) <= maxWidth) {
            keep = mid;
            lo = mid;
        } else {
            hi = mid - 1;
        }
    }
    size_t cut = trimRight(text, keep < count ? bounds[keep] : length);
    if (used + sizeof(ELLIPSIS) > cap) return;
    if (used + cut + sizeof(ELLIPSIS) > cap) cut = cap - used - sizeof(ELLIPSIS);
    memcpy(out + used, text, cut);
    memcpy(out + used + cut, ELLIPSIS, sizeof(ELLIPSIS));
}

// Longest code-point prefix of text that fits maxWidth (no ellipsis).
size_t fittingPrefix(const char* text, const lv_font_t* font, int32_t tracking, int32_t maxWidth) {
    size_t end = 0;
    for (size_t i = 0; text[i];) {
        size_t next = i;
        utf8Next(text, next);
        if (widthOf(text, next, font, tracking) > maxWidth) break;
        end = i = next;
    }
    return end;
}

// The last line of a paragraph: the whole text when it fits; otherwise it is clamped
// (-webkit-line-clamp) to the whole words that fit together with U+2026, and characters are cut
// only when no whole word fits.
void appendLastLine(char* out, size_t cap, const char* text, const lv_font_t* font, int32_t tracking,
                    int32_t maxWidth) {
    if (widthOf(text, font, tracking) <= maxWidth) {
        appendLine(out, cap, text, font, tracking, maxWidth);
        return;
    }
    size_t words = 0;
    for (size_t i = 1; text[i]; ++i) {
        if (text[i] != ' ') continue;
        const size_t end = trimRight(text, i);
        if (end == 0) continue;
        if (ellipsizedWidth(text, end, font, tracking) > maxWidth) break;
        words = end;
    }
    if (words == 0) {
        appendLine(out, cap, text, font, tracking, maxWidth, true);
        return;
    }
    char kept[TEXT_CAP];
    memcpy(kept, text, words);
    kept[words] = '\0';
    appendLine(out, cap, kept, font, tracking, maxWidth, true);
}

// Preferred break points inside an over-wide word: after a separator of file names and paths
// ("CLAUDE_CODE_" / "HANDOFF.md", "cc5-stage6-" / "lcd-...").
bool isWordSeparator(char c) { return c == '-' || c == '_' || c == '/' || c == '\\' || c == '.'; }

// Balanced two-line split (line 1 = text[0:end1], line 2 = text[start2:]).
struct Split {
    size_t end1, start2;
    int32_t score;                          // the wider line; lower is better
    bool found;
};

void consider(Split& best, size_t end1, size_t start2, int32_t w1, int32_t w2) {
    const int32_t score = w1 > w2 ? w1 : w2;
    if (!best.found || score <= best.score) {   // ties keep the longer first line
        best.end1 = end1;
        best.start2 = start2;
        best.score = score;
        best.found = true;
    }
}

// Two lines, CSS "text-wrap: balance" + line-clamp 2. U+2026 appears only when the whole text
// cannot be shown in the two lines:
// 1. a split at a space where both lines fit, minimising the wider line;
// 2. otherwise a split inside a word wider than a line (overflow-wrap), again balanced,
//    preferring a break after - _ / \ . over any code point;
// 3. otherwise the text does not fit: a full first line (the words that fit, or the first word
//    cut by characters) and a clamped second line.
void fitTwoLines(char* out, size_t cap, const char* text, const lv_font_t* font, int32_t tracking,
                 int32_t width1, int32_t width2) {
    out[0] = '\0';
    const size_t length = strlen(text);
    if (widthOf(text, length, font, tracking) <= width1) { copyText(out, cap, text); return; }
    Split best = {0, 0, 0, false};
    size_t greedyEnd1 = 0, greedyStart2 = 0;
    for (size_t i = 1; i < length; ++i) {
        if (text[i] != ' ') continue;
        const size_t end1 = trimRight(text, i);
        size_t start2 = i;
        while (text[start2] == ' ') ++start2;
        if (end1 == 0 || text[start2] == '\0') continue;
        const int32_t w1 = widthOf(text, end1, font, tracking);
        if (w1 > width1) break;                      // later splits only widen line 1
        greedyEnd1 = end1;
        greedyStart2 = start2;
        const int32_t w2 = widthOf(text + start2, length - start2, font, tracking);
        if (w2 <= width2) consider(best, end1, start2, w1, w2);
    }
    if (!best.found) {
        const int32_t narrow = width1 < width2 ? width1 : width2;
        Split separated = {0, 0, 0, false};
        bool stop = false;
        for (size_t start = 0; start < length && !stop;) {
            while (start < length && text[start] == ' ') ++start;
            size_t end = start;
            while (end < length && text[end] != ' ') ++end;
            if (end > start && widthOf(text + start, end - start, font, tracking) > narrow) {
                size_t p = start;
                utf8Next(text, p);
                while (p < end) {
                    const int32_t w1 = widthOf(text, p, font, tracking);
                    if (w1 > width1) { stop = true; break; }
                    const int32_t w2 = widthOf(text + p, length - p, font, tracking);
                    if (w2 <= width2) {
                        consider(best, p, p, w1, w2);
                        if (isWordSeparator(text[p - 1])) consider(separated, p, p, w1, w2);
                    }
                    utf8Next(text, p);
                }
            }
            start = end;
        }
        if (separated.found) best = separated;
    }
    size_t end1, start2;
    if (best.found) {
        end1 = best.end1;
        start2 = best.start2;
    } else if (greedyEnd1) {
        end1 = greedyEnd1;
        start2 = greedyStart2;
    } else {
        // The first word alone is wider than line 1: cut it by characters.
        end1 = fittingPrefix(text, font, tracking, width1);
        if (end1 == 0) { size_t one = 0; utf8Next(text, one); end1 = one; }
        start2 = end1;
        while (text[start2] == ' ') ++start2;
    }
    char line1[TEXT_CAP];
    if (end1 >= sizeof(line1)) end1 = sizeof(line1) - 1;
    memcpy(line1, text, end1);
    line1[end1] = '\0';
    copyText(out, cap, line1);
    const char* rest = text + start2;
    if (*rest) {
        const size_t used = strlen(out);
        if (used + 1 < cap) { out[used] = '\n'; out[used + 1] = '\0'; }
        appendLastLine(out, cap, rest, font, tracking, width2);   // whole when it fits (steps 1-2)
    }
}

// Usable width of a label's line k: design width clamped to the chord of the label's own radius
// (104; 112 for headings) over the ink rows of that line.
int32_t lineWidth(const Label& l, uint8_t k, int32_t inkTop, int32_t inkBottom) {
    const int32_t pitch = l.font->line_height + LINE_SPACE;
    const int32_t top = l.y + k * pitch;
    const int32_t half = safeHalf(top + inkTop, top + inkBottom, l.radius);
    const int32_t offset = l.centerX > CENTER ? l.centerX - CENTER : CENTER - l.centerX;
    int32_t width = 2 * (half - offset);
    if (width < 0) width = 0;
    return width < l.w ? width : l.w;
}

void markChanged() { changed = true; }

void setVisible(lv_obj_t* obj, bool visible) {
    if (lv_obj_has_flag(obj, LV_OBJ_FLAG_HIDDEN) != !visible) {
        if (visible) lv_obj_remove_flag(obj, LV_OBJ_FLAG_HIDDEN);
        else lv_obj_add_flag(obj, LV_OBJ_FLAG_HIDDEN);
        markChanged();
    }
}

void setLabelVisible(Label& l, bool visible) {
    setVisible(l.obj, visible);
    if (l.twin) setVisible(l.twin, visible);
}

// visible false keeps the text set but hides the label (the tile letter under an app icon), so
// a later return costs no text set. The label's own LVGL copy is the comparison (LONG_CLIP never
// rewrites it).
void applyText(Label& l, const char* text, bool visible = true) {
    if (strcmp(lv_label_get_text(l.obj), text) != 0) {
        lv_label_set_text(l.obj, text);
        if (l.twin) lv_label_set_text(l.twin, text);
        ++stats.textSets;
        markChanged();
    }
    setLabelVisible(l, visible && text[0] != '\0');
}

uint32_t mixInk(uint32_t from, uint32_t to, int32_t v) {
    if (v <= 0) return from;
    if (v >= 255) return to;
    uint32_t out = 0;
    for (int shift = 16; shift >= 0; shift -= 8) {
        const uint32_t a = (from >> shift) & 255u, b = (to >> shift) & 255u;
        const uint32_t c = (a * static_cast<uint32_t>(255 - v) + b * static_cast<uint32_t>(v) + 127u) / 255u;
        out |= c << shift;
    }
    return out;
}

void execLabelInk(void* var, int32_t v) {
    Label* l = static_cast<Label*>(var);
    l->shownInk = mixInk(l->fadeFrom, l->ink, v);
    lv_obj_set_style_text_color(l->obj, lv_color_hex(l->shownInk), 0);
}

void execIconInk(void* var, int32_t v) {
    Icon* ic = static_cast<Icon*>(var);
    ic->shownInk = mixInk(ic->fadeFrom, ic->ink, v);
    lv_obj_set_style_image_recolor(ic->obj, lv_color_hex(ic->shownInk), 0);
}

void startAnim(void* var, lv_anim_exec_xcb_t exec, int32_t from, int32_t to, uint32_t duration, uint32_t delay,
               uint8_t ease) {
    const Curve& curve = CURVES[ease];
    lv_anim_t a;
    lv_anim_init(&a);
    lv_anim_set_var(&a, var);
    lv_anim_set_exec_cb(&a, exec);
    lv_anim_set_values(&a, from, to);
    lv_anim_set_duration(&a, duration);
    lv_anim_set_delay(&a, delay);
    lv_anim_set_path_cb(&a, lv_anim_path_custom_bezier3);
    lv_anim_set_bezier3_param(&a, curve.x1, curve.y1, curve.x2, curve.y2);
    lv_anim_start(&a);
    ++stats.animations;
    animated = true;
    markChanged();
}

// Instant ink (text lines; the twin keeps its black).
void applyInk(Label& l, uint32_t ink) {
    if (lv_anim_delete(&l, execLabelInk)) markChanged();
    if (!l.inkSet || l.ink != ink || l.shownInk != ink) {
        l.ink = l.shownInk = ink;
        l.inkSet = true;
        lv_obj_set_style_text_color(l.obj, lv_color_hex(ink), 0);
        markChanged();
    }
}

// Section 5.2 ink crossfade (idle words): 160 ms OUT, per 8-bit channel, from the ink shown.
void fadeLabelInk(Label& l, uint32_t ink, bool fade) {
    if (l.inkSet && l.ink == ink) return;
    if (!fade || !l.inkSet) {
        applyInk(l, ink);
        return;
    }
    lv_anim_delete(&l, execLabelInk);
    l.fadeFrom = l.shownInk;
    l.ink = ink;
    ++stats.inkFades;
    startAnim(&l, execLabelInk, 0, 255, INK_FADE_MS, 0, EASE_OUT);
}

void setIconInk(Icon& ic, uint32_t ink, bool fade) {
    if (ic.inkSet && ic.ink == ink) return;
    const bool running = lv_anim_delete(&ic, execIconInk);
    if (!fade || !ic.inkSet || ic.shownInk == ink) {
        ic.ink = ic.shownInk = ink;
        ic.inkSet = true;
        lv_obj_set_style_image_recolor(ic.obj, lv_color_hex(ink), 0);
        markChanged();
        return;
    }
    (void)running;
    ic.fadeFrom = ic.shownInk;
    ic.ink = ink;
    ++stats.inkFades;
    startAnim(&ic, execIconInk, 0, 255, INK_FADE_MS, 0, EASE_OUT);
}

void applyTracking(Label& l, int8_t tracking) {
    if (l.tracking != tracking) {
        l.tracking = tracking;
        lv_obj_set_style_text_letter_space(l.obj, tracking, 0);
        if (l.twin) lv_obj_set_style_text_letter_space(l.twin, tracking, 0);
        markChanged();
    }
}

// Fits and shows text unless the source is unchanged since the last fit. True when the source
// text changed (a meta or status line then fades in at rest, section 8.5.4).
bool showText(Label& l, const char* text) {
    if (strcmp(l.src, text) == 0) {
        setLabelVisible(l, lv_label_get_text(l.obj)[0] != '\0');
        return false;
    }
    copyText(l.src, sizeof(l.src), text);
    char fitted[TEXT_CAP] = {};
    if (text[0]) {
        int32_t inkTop, inkBottom;
        inkRows(text, l.font, inkTop, inkBottom);
        const int32_t width1 = lineWidth(l, 0, inkTop, inkBottom);
        if (l.lines > 1) fitTwoLines(fitted, sizeof(fitted), text, l.font, l.tracking, width1,
                                     lineWidth(l, 1, inkTop, inkBottom));
        else appendLine(fitted, sizeof(fitted), text, l.font, l.tracking, width1);
    }
    applyText(l, fitted);
    return true;
}

// Section 8.10 offline sub-line (K1 erratum, lead ruling R-c): the native line is one line, so when
// it does not fit its line at 0 tracking it takes OFFLINE_NATIVE_TRACKING before the fit (the
// words stay whole: no wrap, no ellipsis); every other sub-line is fitted at 0.
void showOfflineSub(const char* text, bool native) {
    int8_t tracking = 0;
    if (native) {
        int32_t inkTop, inkBottom;
        inkRows(text, offSub.font, inkTop, inkBottom);
        if (widthOf(text, offSub.font, 0) > lineWidth(offSub, 0, inkTop, inkBottom))
            tracking = OFFLINE_NATIVE_TRACKING;
    }
    if (offSub.tracking != tracking) {
        applyTracking(offSub, tracking);
        offSub.src[0] = '\0';                // refit at the new tracking
    }
    showText(offSub, text);
}

// Section 8.5.2: 12 px caps at 1 px tracking in {51, 31, 138}, fitted against min(138, the r112
// chord of its ink rows). Every v5 heading fits as is; a legacy heading drops the tracking, then
// "RECENTLY ADDED · P{n}" shortens to "RECENT · P{n}", and only then is it ellipsized.
void showHeading(Label& l, const char* text) {
    if (strcmp(l.src, text) == 0) {
        setLabelVisible(l, lv_label_get_text(l.obj)[0] != '\0');
        return;
    }
    copyText(l.src, sizeof(l.src), text);
    char fitted[TEXT_CAP] = {};
    int8_t tracking = HEADING_TRACKING;
    if (text[0]) {
        int32_t inkTop, inkBottom;
        inkRows(text, l.font, inkTop, inkBottom);
        const int32_t width = lineWidth(l, 0, inkTop, inkBottom);
        static const char RECENT_LONG[] = "RECENTLY ADDED \xC2\xB7 P";
        static const char RECENT_SHORT[] = "RECENT \xC2\xB7 P";
        if (widthOf(text, l.font, HEADING_TRACKING) <= width) {
            copyText(fitted, sizeof(fitted), text);
        } else if (widthOf(text, l.font, 0) <= width) {
            copyText(fitted, sizeof(fitted), text);
            tracking = 0;
        } else if (strncmp(text, RECENT_LONG, sizeof(RECENT_LONG) - 1) == 0) {
            char shorter[TEXT_CAP];
            snprintf(shorter, sizeof(shorter), "%s%s", RECENT_SHORT, text + sizeof(RECENT_LONG) - 1);
            if (widthOf(shorter, l.font, HEADING_TRACKING) > width) {
                tracking = 0;
                appendLine(fitted, sizeof(fitted), shorter, l.font, 0, width);
            } else {
                copyText(fitted, sizeof(fitted), shorter);
            }
        } else {
            tracking = 0;
            appendLine(fitted, sizeof(fitted), text, l.font, 0, width);
        }
    }
    applyTracking(l, tracking);
    applyText(l, fitted);
}

// ------------------------------------------------------------------ tweens --
void execOpa(void* obj, int32_t v) {
    if (v < 0) v = 0;
    if (v > 255) v = 255;
    lv_obj_set_style_opa(static_cast<lv_obj_t*>(obj), static_cast<lv_opa_t>(v), 0);
}
void execTx(void* obj, int32_t v) { lv_obj_set_style_translate_x(static_cast<lv_obj_t*>(obj), v, 0); }
void execTy(void* obj, int32_t v) { lv_obj_set_style_translate_y(static_cast<lv_obj_t*>(obj), v, 0); }

lv_anim_exec_xcb_t execOf(uint8_t prop) {
    return prop == PROP_OPA ? execOpa : prop == PROP_TX ? execTx : execTy;
}

int32_t currentValue(const Tween& t) {
    if (t.prop == PROP_OPA) return lv_obj_get_style_opa(t.obj, 0);
    if (t.prop == PROP_TX) return lv_obj_get_style_translate_x(t.obj, 0);
    return lv_obj_get_style_translate_y(t.obj, 0);
}

void initTween(Tween& t, lv_obj_t* obj, uint8_t prop, int32_t target) {
    t.obj = obj;
    t.prop = prop;
    t.set = false;
    t.target = target;
}

// CSS-transition semantics: when the target changes, move from the current value to the new
// target with the new state's timing; an unchanged target (heartbeat) does nothing. snap applies
// the target at once (and ends a running transition).
void tween(Tween& t, int32_t target, uint32_t duration, uint32_t delay, uint8_t ease, bool snap) {
    if (t.set && t.target == target && !snap) return;
    t.set = true;
    t.target = target;
    lv_anim_exec_xcb_t exec = execOf(t.prop);
    const bool running = lv_anim_get(t.obj, exec) != nullptr;
    if (running) { lv_anim_delete(t.obj, exec); markChanged(); }
    const int32_t current = currentValue(t);
    if (current == target) return;
    if (snap || duration == 0) {
        exec(t.obj, target);
        markChanged();
        return;
    }
    startAnim(t.obj, exec, current, target, duration, delay, ease);
}

// A fresh transition that starts from an explicit value (screen change, text at rest).
void tweenFrom(Tween& t, int32_t from, int32_t target, uint32_t duration, uint32_t delay, uint8_t ease) {
    lv_anim_exec_xcb_t exec = execOf(t.prop);
    lv_anim_delete(t.obj, exec);
    t.set = true;
    t.target = target;
    exec(t.obj, from);
    markChanged();
    if (from != target) startAnim(t.obj, exec, from, target, duration, delay, ease);
}

// Section 8.5.4: a meta or status line whose text changed at rest snaps to 0 and fades in over
// 160 ms OUT; otherwise (a screen change, a layer that just appeared) it is at 255 at once.
void fadeLine(const Label& l, Tween& t, bool textChanged, bool atRest) {
    if (textChanged && atRest && l.src[0]) {
        tweenFrom(t, 0, 255, LINE_FADE_MS, 0, EASE_OUT);
        ++stats.lineFades;
    } else if (textChanged || !atRest) {
        tween(t, 255, 0, 0, EASE_OUT, true);
    }
}

// ---------------------------------------------------------------- creation --
void tag(lv_obj_t* obj, const char* role) { lv_obj_set_user_data(obj, const_cast<char*>(role)); }

lv_obj_t* makeBox(lv_obj_t* parent, int32_t x, int32_t y, int32_t w, int32_t h, const char* role) {
    lv_obj_t* obj = lv_obj_create(parent);
    lv_obj_remove_style_all(obj);
    lv_obj_set_pos(obj, x, y);
    lv_obj_set_size(obj, w, h);
    lv_obj_remove_flag(obj, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_remove_flag(obj, LV_OBJ_FLAG_CLICKABLE);
    tag(obj, role);
    return obj;
}

// A layer at absolute box b inside parent (absolute origin parentX/Y).
void makeLayer(Layer& layer, lv_obj_t* parent, int16_t parentX, int16_t parentY, const Box& b, const char* role) {
    layer.obj = makeBox(parent, b.x - parentX, b.y - parentY, b.w, b.h, role);
    layer.x = b.x;
    layer.y = b.y;
}

void makeLayer(Layer& layer, const Layer& parent, const Box& b, const char* role) {
    makeLayer(layer, parent.obj, parent.x, parent.y, b, role);
}

lv_obj_t* newLabel(lv_obj_t* parent, int32_t x, int32_t y, const Box& box, const lv_font_t* font,
                   lv_text_align_t align, const char* role) {
    lv_obj_t* obj = lv_label_create(parent);
    lv_obj_remove_style_all(obj);
    lv_obj_set_pos(obj, x, y);
    lv_obj_set_size(obj, box.w, box.h);
    lv_obj_set_style_text_font(obj, font, 0);
    lv_obj_set_style_text_align(obj, align, 0);
    lv_obj_set_style_text_line_space(obj, LINE_SPACE, 0);
    // Fitting happens before LVGL (U+2026 placed by showText); CLIP never rewrites the text, so the
    // label's own copy is the heartbeat comparison.
    lv_label_set_long_mode(obj, LV_LABEL_LONG_CLIP);
    lv_label_set_text(obj, "");
    lv_obj_add_flag(obj, LV_OBJ_FLAG_HIDDEN);
    tag(obj, role);
    return obj;
}

// box: absolute. twinRole non-null: a text-shadow twin (section 8.5.3) is created first (below).
void makeLabel(Label& l, const Layer& parent, const Box& box, const lv_font_t* font, uint8_t lines,
               lv_text_align_t align, const char* role, const char* twinRole = nullptr,
               int16_t radius = SAFE_R, int8_t tracking = 0) {
    memset(&l, 0, sizeof(l));
    l.font = font;
    l.x = box.x;
    l.y = box.y;
    l.w = box.w;
    l.centerX = static_cast<int16_t>(box.x + box.w / 2);
    l.radius = radius;
    l.lines = lines;
    l.tracking = tracking;
    const int32_t x = box.x - parent.x, y = box.y - parent.y;
#if CC_TEXT_TWINS
    if (twinRole) {
        l.twin = newLabel(parent.obj, x, y + 1, box, font, align, twinRole);
        lv_obj_set_style_text_color(l.twin, lv_color_hex(CCInk::shadow), 0);
        lv_obj_set_style_text_opa(l.twin, TWIN_OPA, 0);
        if (tracking) lv_obj_set_style_text_letter_space(l.twin, tracking, 0);
    }
#else
    (void)twinRole;
#endif
    l.obj = newLabel(parent.obj, x, y, box, font, align, role);
    if (tracking) lv_obj_set_style_text_letter_space(l.obj, tracking, 0);
}

void makeIcon(Icon& icon, const Layer& parent, int32_t x, int32_t y, int16_t size, const char* role) {
    memset(&icon, 0, sizeof(icon));
    icon.obj = lv_image_create(parent.obj);
    icon.size = size;
    lv_obj_remove_style_all(icon.obj);
    lv_obj_set_pos(icon.obj, x - parent.x, y - parent.y);
    lv_obj_set_size(icon.obj, size, size);
    lv_obj_set_style_image_recolor_opa(icon.obj, LV_OPA_COVER, 0);
    lv_obj_add_flag(icon.obj, LV_OBJ_FLAG_HIDDEN);
    tag(icon.obj, role);
}

// A8 mask recoloured to ink (the sw renderer draws A8 in the recolor colour). dsc nullptr hides
// the icon. A glyph change is instant; with `fade`, an ink change of an icon that stays shown
// crossfades from the ink on screen (section 5.2).
void showIcon(Icon& ic, const lv_image_dsc_t* dsc, uint32_t ink, bool fade) {
    const bool wasShown = ic.src != nullptr;
    if (dsc != ic.src) {
        ic.src = dsc;
        if (dsc) lv_image_set_src(ic.obj, dsc);
        markChanged();
    }
    if (dsc) setIconInk(ic, ink, fade && wasShown);
    setVisible(ic.obj, dsc != nullptr);
}

// The glyph a button draws: tone liked is the filled heart ([r2.2], section 5.2 row 4 / 9.1), any
// other tone the token's own mask; nullptr hides (tone none, or no mask at this size).
const lv_image_dsc_t* buttonGlyph(const CCFrame& f, uint8_t slot, uint8_t tone, int size) {
    if (tone == CC_TONE_NONE) return nullptr;
    if (tone == CC_TONE_LIKED) return cc_icon(LIKED_GLYPH, size);
    uint8_t icon = cc_button_icon(f.buttons[slot]);
    if (icon >= ICON_COUNT) icon = CC_ICON_NONE;
    return icon == CC_ICON_NONE ? nullptr : cc_icon(ICON_NAMES[icon], size);
}

// ------------------------------------------------------------------- media --
// ARTWORK2.md 4.4 "Display adoption": the store pins the slot the LCD draws (adopt) and is told
// when the LCD draws no media of a kind (release).
void releaseMedia(uint8_t kind) {
    if (!mediaHeld[kind]) return;
    mediaHeld[kind] = false;
    if (media.release) media.release(kind);
}

// The committed payload for key, pinned as displayed; a miss (or no key) releases the kind's
// pin. Cheap and idempotent: the store touches a slot only when its displayed slot changes.
bool adoptMedia(uint8_t kind, const char* key, const uint8_t** data, uint32_t* bytes) {
    *data = nullptr;
    *bytes = 0;
    if (media.adopt && key[0] && strlen(key) <= CC_DISPLAY_MEDIA_KEY_MAX && media.adopt(kind, key, data, bytes)) {
        mediaHeld[kind] = true;
        if (*data && *bytes) return true;
    }
    releaseMedia(kind);
    *data = nullptr;
    *bytes = 0;
    return false;
}

bool asyncArt() { return media.requestCover && media.pollCover && media.cancelCover && artBuffer[1]; }

void cancelDecode(bool cancel) {
    if (!decode.inFlight || decode.cancelled == cancel) return;
    decode.cancelled = cancel;
    media.cancelCover(cancel);
}

// ------------------------------------------------------------------ render --
uint8_t groupOf(uint8_t layout) {
    switch (layout) {
        case CC_LAYOUT_RECENT: return GROUP_RECENT;
        case CC_LAYOUT_TRACKS:
        case CC_LAYOUT_SEEK: return GROUP_TRACKS;           // entering/leaving Seek never slides
        case CC_LAYOUT_WINDOWS: return GROUP_WINDOWS;
        case CC_LAYOUT_EXPLORER: return GROUP_EXPLORER;
        case CC_LAYOUT_UPNEXT: return GROUP_UPNEXT;
        default: return GROUP_HOME;
    }
}

// Section 8.7: home 0, recent 1 + page', tracks 1, windows 5, explorer 30 + page', upnext 30.
int32_t depthOf(uint8_t group, uint8_t page) {
    switch (group) {
        case GROUP_TRACKS: return 1;
        case GROUP_RECENT: return 1 + page;
        case GROUP_WINDOWS: return 5;
        case GROUP_EXPLORER: return 30 + page;
        case GROUP_UPNEXT: return 30;
        default: return 0;
    }
}

void renderHome(const CCFrame& f, bool volume, bool idle, bool snap, bool statusAtRest, bool inkFade) {
    const bool away = volume || idle;
    showText(homeTitle, f.title);
    applyInk(homeTitle, CCInk::text);
    showText(homeArtist, f.subtitle);
    applyInk(homeArtist, CCInk::context);
    // Reduced motion (section 8.9): opacity only, every translate target 0 and snapped.
    const int32_t trackLift = reducedMotion ? 0 : volume ? -8 : -10;
    tween(trackOpa, away ? 0 : 255, away ? 150 : 320, away ? 0 : 90, away ? EASE_IN : EASE_OUT, snap);
    tween(trackTy, away ? trackLift : 0, away ? 190 : 420, away ? 0 : 90, away ? EASE_IN : EASE_OUT,
          snap || reducedMotion);

    showText(volumeCaption, f.volumeCaption[0] ? f.volumeCaption : f.title);
    applyInk(volumeCaption, CCInk::context);
    // 48 px digits (value without its '%') and a 22 px '%' on one baseline, centred.
    char number[8] = {};
    size_t n = 0;
    for (const char* c = f.value; *c && *c != '%' && n + 1 < sizeof(number); ++c)
        if ((*c >= '0' && *c <= '9') || *c == '-') number[n++] = *c;
    applyText(digits, number);
    applyText(percent, n ? "%" : "");
    const int32_t wd = n ? widthOf(number, digits.font, DIGITS_TRACKING) : 0;
    const int32_t wp = n ? widthOf("%", percent.font, 0) : 0;
    if (wd != digitsWidth || wp != percentWidth) {
        digitsWidth = wd;
        percentWidth = wp;
        const int32_t left = CENTER - (wd + DIGIT_GAP + wp + 1) / 2 - volumeLayer.x;
        const int32_t dy = DIGITS_Y - volumeLayer.y, py = PERCENT_Y - volumeLayer.y;
        lv_obj_set_pos(digits.obj, left, dy);
        lv_obj_set_width(digits.obj, wd + 2);
        lv_obj_set_pos(percent.obj, left + wd + DIGIT_GAP, py);
        lv_obj_set_width(percent.obj, wp + 2);
        if (digits.twin) {
            lv_obj_set_pos(digits.twin, left, dy + 1);
            lv_obj_set_width(digits.twin, wd + 2);
        }
        if (percent.twin) {
            lv_obj_set_pos(percent.twin, left + wd + DIGIT_GAP, py + 1);
            lv_obj_set_width(percent.twin, wp + 2);
        }
        markChanged();
    }
    tween(volumeOpa, volume ? 255 : 0, volume ? 180 : 170, volume ? 50 : 0, volume ? EASE_OUT : EASE_IN, snap);
    // A hidden layer keeps its offset under reduced motion (no invisible retarget, so a frame that
    // only latches reducedMotion stays inert); the reveal then snaps it to 0 (opacity only).
    tween(volumeTy, volume ? 0 : reducedMotion ? volumeTy.target : 6, volume ? 340 : 190, volume ? 50 : 0,
          volume ? EASE_SPR : EASE_IN, snap || reducedMotion);

    const bool statusChanged = showText(status, f.status);
    applyInk(status, cc_line_ink(f.statusTone));
    const bool row = idle && !volume;
    if (row) tween(statusOpa, 0, 240, 0, EASE_OUT, snap);          // the idle hide wins
    else if (statusChanged && statusAtRest && status.src[0]) {
        tweenFrom(statusOpa, 0, 255, LINE_FADE_MS, 0, EASE_OUT);
        ++stats.lineFades;
    } else {
        tween(statusOpa, 255, 240, 0, EASE_OUT, snap);
    }

    for (uint8_t i = 0; i < 4; ++i) {
        const uint8_t tone = cc_button_tone(f, i);
        const uint32_t ink = cc_button_ink(f, i);
        showIcon(idleIcon[i], buttonGlyph(f, i, tone, IDLE_ICON), ink, inkFade);
        showText(idleWord[i], tone != CC_TONE_NONE ? f.buttons[i].label : "");
        fadeLabelInk(idleWord[i], ink, inkFade);
        const uint32_t stagger = 200u + 45u * i;
        tween(idleOpa[i], row ? 255 : 0, row ? 300 : 140, row ? stagger : 0, row ? EASE_OUT : EASE_IN, snap);
        tween(idleTy[i], row ? 0 : reducedMotion ? idleTy[i].target : 14, row ? 460 : 160, row ? stagger : 0,
              row ? EASE_SPR : EASE_IN, snap || reducedMotion);
    }
}

void renderList(const CCFrame& f, bool metaAtRest) {
    showText(listTitle, f.title);
    applyInk(listTitle, cc_title_ink(f.titleTone));
    showText(listSub, f.subtitle);
    applyInk(listSub, CCInk::context);
    // Lists draw meta (metaTone); the status line is Home-only.
    const bool metaChanged = showText(listMeta, f.meta);
    applyInk(listMeta, cc_line_ink(f.metaTone));
    fadeLine(listMeta, listMetaOpa, metaChanged, metaAtRest);
}

void renderTracks(const CCFrame& f, bool metaAtRest) {
    showText(tracksTitle, f.title);
    applyInk(tracksTitle, cc_title_ink(f.titleTone));
    const uint16_t selected = f.ringIndex <= 2 ? f.ringIndex : 1;
    const bool noPrevious = (f.ringUnavailable & 1u) != 0;
    static const char* const names[3] = {"prev", DOT_GLYPH, "next"};
    for (uint16_t i = 0; i < 3; ++i) {
        uint32_t ink = selected == i ? CCInk::text : CCInk::meta;
        if (i == 0 && noPrevious) ink = CCInk::disabledGlyph;
        showIcon(positionIcon[i], cc_icon(names[i], POS_ICON), ink, false);
    }
    showText(tracksSub, f.subtitle);
    applyInk(tracksSub, CCInk::context);
    const bool metaChanged = showText(tracksMeta, f.meta);
    applyInk(tracksMeta, cc_line_ink(f.metaTone));
    fadeLine(tracksMeta, tracksMetaOpa, metaChanged, metaAtRest);
}

// Section 8.6.8: the 14 px caption is the song (`title`), the 48 px tabular time mmss(ring.index)
// of a lap ring (redrawn per frame, never animated), the 14 px line the `meta` (#A6A6A6 for tone
// meta, P5-R2). None of them fades (section 8.5.4).
void renderSeek(const CCFrame& f) {
    showText(seekCaption, f.title);
    applyInk(seekCaption, CCInk::context);
    char time[12] = {};
    if (f.ringStyle == CC_RING_LAP) cc_mmss(f.ringIndex, time, sizeof(time));
    showText(seekTime, time);
    applyInk(seekTime, CCInk::text);
    showText(seekLine, f.meta);
    applyInk(seekLine, f.metaTone == CC_LINE_META ? CCInk::context : cc_line_ink(f.metaTone));
}

bool selectedUnavailable(const CCFrame& f) {
    if (f.ringIndex < f.ringFirst) return false;
    const uint32_t k = static_cast<uint32_t>(f.ringIndex - f.ringFirst);
    return k < CC_RING_WINDOW && ((f.ringUnavailable >> k) & 1u) != 0;
}

// ARTWORK2.md section 7 icons: the selected window's 32x32 icon fills the tile (transparent tile
// background, letter hidden) when the store has iconKey. It is copied into the tile buffer only
// when the key changes and appears at once (no fade). Otherwise the letter tile is drawn.
bool renderTileIcon(const CCFrame& f) {
    const uint8_t* data = nullptr;
    uint32_t bytes = 0;
    bool shown = adoptMedia(CC_DISPLAY_MEDIA_ICON, f.iconKey, &data, &bytes);
    if (shown && bytes != CC_ICON_BYTES) {
        releaseMedia(CC_DISPLAY_MEDIA_ICON);
        shown = false;
    }
    if (shown && strcmp(iconLoadedKey, f.iconKey) != 0) {
        memcpy(iconPixels, data, CC_ICON_BYTES);
        copyText(iconLoadedKey, sizeof(iconLoadedKey), f.iconKey);
        lv_obj_invalidate(tileIcon);
        ++stats.iconLoads;
        markChanged();
    }
    setVisible(tileIcon, shown);
    if (shown != tileIconShown) {
        tileIconShown = shown;
        lv_obj_set_style_bg_opa(tile, static_cast<lv_opa_t>(shown ? LV_OPA_TRANSP : LV_OPA_COVER), 0);
        markChanged();
    }
    return shown;
}

void renderWindows(const CCFrame& f, bool metaAtRest) {
    const bool icon = renderTileIcon(f);
    // Letter tile: the subtitle's first code point, upper-cased when it is ASCII a-z (other code
    // points as-is; lcd_preview.py does the same).
    char letter[5] = {};
    size_t end = 0;
    if (f.subtitle[0]) utf8Next(f.subtitle, end);
    memcpy(letter, f.subtitle, end < sizeof(letter) ? end : sizeof(letter) - 1);
    if (end == 1 && letter[0] >= 'a' && letter[0] <= 'z') letter[0] = static_cast<char>(letter[0] - 'a' + 'A');
    // Section 5.3 tile fallback: sat() of the selected entry's accent with a #FFFFFF initial, else
    // V4's #444 tile with a #F2F2F2 initial.
    uint32_t bg = CCInk::tile, initial = CCInk::tileInitial, accent = 0, s = 0;
    if (f.ringIndex >= f.ringFirst && static_cast<uint32_t>(f.ringIndex - f.ringFirst) < f.ringColorCount)
        accent = f.ringColors[f.ringIndex - f.ringFirst];
    if (accent != 0 && cc_sat(accent, s)) {
        bg = s;
        initial = CCInk::accentInitial;
    }
    if (bg != tileBg) {
        tileBg = bg;
        lv_obj_set_style_bg_color(tile, lv_color_hex(bg), 0);
        markChanged();
    }
    applyText(tileLetter, letter, !icon);
    applyInk(tileLetter, initial);
    setVisible(tile, icon || f.subtitle[0] != '\0');
    // The closed entry dims the whole tile group (icon or letter) to 0.35.
    const uint8_t opa = selectedUnavailable(f) ? TILE_CLOSED_OPA : 255;
    if (opa != tileOpa) {
        tileOpa = opa;
        lv_obj_set_style_opa(tile, opa, 0);
        markChanged();
    }
    showText(winApp, f.subtitle);
    applyInk(winApp, CCInk::context);
    showText(winTitle, f.title);
    applyInk(winTitle, cc_title_ink(f.titleTone));
    const bool metaChanged = showText(winMeta, f.meta);
    applyInk(winMeta, cc_line_ink(f.metaTone));
    fadeLine(winMeta, winMetaOpa, metaChanged, metaAtRest);
}

void renderFooter(const CCFrame& f, bool hidden, bool snap, bool inkFade) {
    for (uint8_t i = 0; i < 4; ++i) {
        const uint8_t tone = cc_button_tone(f, i);
        showIcon(footerIcon[i], buttonGlyph(f, i, tone, FOOTER_ICON), cc_button_ink(f, i), inkFade);
    }
    tween(footerOpa, hidden ? 0 : 255, hidden ? 160 : 280, hidden ? 0 : 140, hidden ? EASE_IN : EASE_OUT, snap);
}

// Bilinear 2x (weights 9/3/3/1 over 16): 120 px RGB565 LE -> 240 px native RGB565.
void upscaleArt(const uint8_t* src, uint8_t* dst) {
    for (int32_t y = 0; y < 240; ++y) {
        const int32_t sy = y >> 1;
        const int32_t fy = (y & 1) ? (sy < 119 ? sy + 1 : sy) : (sy > 0 ? sy - 1 : sy);
        for (int32_t x = 0; x < 240; ++x) {
            const int32_t sx = x >> 1;
            const int32_t fx = (x & 1) ? (sx < 119 ? sx + 1 : sx) : (sx > 0 ? sx - 1 : sx);
            const uint8_t* p[4] = {src + 2 * (sy * 120 + sx), src + 2 * (sy * 120 + fx),
                                   src + 2 * (fy * 120 + sx), src + 2 * (fy * 120 + fx)};
            static const uint32_t weight[4] = {9, 3, 3, 1};
            uint32_t r = 8, g = 8, b = 8;
            for (int k = 0; k < 4; ++k) {
                const uint32_t v = static_cast<uint32_t>(p[k][0]) | (static_cast<uint32_t>(p[k][1]) << 8);
                r += weight[k] * ((v >> 11) & 31u);
                g += weight[k] * ((v >> 5) & 63u);
                b += weight[k] * (v & 31u);
            }
            const uint16_t out = static_cast<uint16_t>(((r >> 4) << 11) | ((g >> 4) << 5) | (b >> 4));
            memcpy(dst + 2 * (y * 240 + x), &out, sizeof(out));
        }
    }
}

// Re-points the image at buffer i (now the front).
void showBuffer(uint8_t i) {
    if (i != artFront) {
        artFront = i;
        lv_image_set_src(art, &artDsc[artFront]);  // re-points and invalidates the image
    } else {
        lv_obj_invalidate(art);
    }
    markChanged();
}

// Synchronous load (binaries B/C, one buffer, v1 covers): key's pixels into the front buffer --
// the back buffer when it still holds them, else the JPEG decoded into the back buffer, else the
// v1 cover upscaled into it; then front and back swap. With one buffer the shown buffer is
// written in place. False when there are no pixels for key, or when the decode failed (then
// artFailedKey is set and the store's pin released).
bool loadArt(const char* key, const uint8_t* jpeg, uint32_t jpegBytes, const uint8_t* artwork120) {
    const uint8_t back = artBuffer[1] ? static_cast<uint8_t>(1 - artFront) : artFront;
    if (back != artFront && strcmp(artKeyOf[back], key) == 0) {
        ++stats.artReuses;                       // e.g. Recent: back to the previous item
    } else if (jpeg && media.decodeCover) {
        artKeyOf[back][0] = '\0';                // partly written until the decode succeeds
        ++stats.artDecodes;
        if (!media.decodeCover(jpeg, jpegBytes, reinterpret_cast<uint16_t*>(artBuffer[back]))) {
            ++stats.artDecodeErrors;
            copyText(artFailedKey, sizeof(artFailedKey), key);
            releaseMedia(CC_DISPLAY_MEDIA_COVER);
            return false;
        }
        copyText(artKeyOf[back], sizeof(artKeyOf[back]), key);
    } else if (artwork120) {
        artKeyOf[back][0] = '\0';
        upscaleArt(artwork120, artBuffer[back]);
        ++stats.artUpscales;
        copyText(artKeyOf[back], sizeof(artKeyOf[back]), key);
    } else {
        return false;
    }
    showBuffer(back);
    return true;
}

// What the art layer can show for this frame (prepareArt -> renderArt).
enum ArtPixels : uint8_t {
    ART_OFF = 0,   // no art wanted: a layout without art, no key, no buffer (fades out, 240 ms)
    ART_MISSING,   // the key has no pixels in any store yet (hidden at once; shows when they arrive)
    ART_FAILED,    // the key's decode failed (hidden at once, no retry until the key changes)
    ART_PENDING,   // R5: the key is decoding (or waits behind another decode): nothing changes
    ART_READY      // the front buffer holds the key's pixels
};

// R5 step 5 (section 12.5.4): consume a finished decode. Only an `ok` for the frame's current key
// is swapped in; stale and aborted results are discarded; a failure of the current key hides it.
void consumeDecode(const CCFrame& f, bool wantArt) {
    if (!decode.inFlight) return;
    char key[sizeof(CCFrame::artKey)] = {};
    uint8_t result = CC_DECODE_FAILED;
    if (!media.pollCover(key, sizeof(key), &result)) return;
    decode.inFlight = false;
    decode.cancelled = false;
    const bool current = wantArt && strcmp(key, f.artKey) == 0;
    const uint8_t back = static_cast<uint8_t>(1 - artFront);
    if (result == CC_DECODE_OK && current) {
        copyText(artKeyOf[back], sizeof(artKeyOf[back]), key);
        showBuffer(back);
    } else if (result == CC_DECODE_OK) {
        ++stats.artDecodeStale;                  // artKeyOf[back] stays ""
    } else if (result == CC_DECODE_ABORTED) {
        ++stats.artDecodeAborts;
    } else {
        ++stats.artDecodeErrors;
        if (current) {
            copyText(artFailedKey, sizeof(artFailedKey), key);
            releaseMedia(CC_DISPLAY_MEDIA_COVER);
        }
    }
}

// Section 8.4 lookups: the artwork2 store before the v1 cover; a failed decode shows no art for
// that key until the frame's artKey changes (no retry loop). Runs first in cc_display_render(),
// before any animation of the render starts: a synchronous decode (up to about 150 ms on the
// knob) after a screen-change tween would cut that much off the slide (LVGL times an animation
// from lv_anim_start()). With R5 the render never decodes: it posts the request (step 1).
uint8_t prepareArt(const CCFrame& f, const uint8_t* artwork120, bool wantArt) {
    const bool async = asyncArt();
    if (async) consumeDecode(f, wantArt);
    if (artFailedKey[0] && strcmp(artFailedKey, f.artKey) != 0) artFailedKey[0] = '\0';
    if (!artBuffer[0] || !wantArt || !f.artKey[0]) {
        if (async) cancelDecode(true);           // step 6: no art wanted, nothing posted after it
        releaseMedia(CC_DISPLAY_MEDIA_COVER);
        return ART_OFF;
    }
    if (artFailedKey[0]) {
        if (async) cancelDecode(true);
        releaseMedia(CC_DISPLAY_MEDIA_COVER);
        return ART_FAILED;
    }
    // The store pins the cover while it is drawn, loaded or not.
    const uint8_t* jpeg = nullptr;
    uint32_t jpegBytes = 0;
    if (media.decodeCover || async) adoptMedia(CC_DISPLAY_MEDIA_COVER, f.artKey, &jpeg, &jpegBytes);
    // Pixels already in the front buffer are shown as they are, whether or not a store still holds
    // the key: keys are content hashes, so they are exact.
    if (strcmp(artKeyOf[artFront], f.artKey) == 0) {
        if (async && decode.inFlight) cancelDecode(strcmp(decode.key, f.artKey) != 0);
        return ART_READY;
    }
    if (!async) {
        if (loadArt(f.artKey, jpeg, jpegBytes, artwork120)) return ART_READY;
        return artFailedKey[0] ? ART_FAILED : ART_MISSING;
    }
    if (decode.inFlight) {
        // Step 4: the running key is the frame's again (a spin back) -> it continues; another key
        // waits as the frame's current key (newest wins: nothing is queued) and is posted when the
        // running decode's result has been consumed.
        const bool same = strcmp(decode.key, f.artKey) == 0;
        cancelDecode(!same);
        return same || jpeg || artwork120 ? ART_PENDING : ART_MISSING;
    }
    const uint8_t back = static_cast<uint8_t>(1 - artFront);
    if (strcmp(artKeyOf[back], f.artKey) == 0) {
        ++stats.artReuses;
        showBuffer(back);
        return ART_READY;
    }
    if (jpeg) {
        // Step 1: post; the back buffer belongs to the decoder until its result is consumed.
        artKeyOf[back][0] = '\0';
        if (media.requestCover(f.artKey, jpeg, jpegBytes, reinterpret_cast<uint16_t*>(artBuffer[back]))) {
            decode.inFlight = true;
            decode.cancelled = false;
            copyText(decode.key, sizeof(decode.key), f.artKey);
            ++stats.artDecodeRequests;
            return ART_PENDING;
        }
    }
    if (loadArt(f.artKey, jpeg, jpegBytes, artwork120)) return ART_READY;   // v1 upscale (or a refused post)
    return artFailedKey[0] ? ART_FAILED : ART_MISSING;
}

void artHideNow() {
    if (lv_anim_delete(art, execOpa)) markChanged();
    artOpa.set = true;
    artOpa.target = 0;
    if (lv_obj_get_style_opa(art, 0) != 0) {
        execOpa(art, 0);
        markChanged();
    }
    setVisible(art, false);
}

// Section 8.4 motion: a key change over a visible cover swaps instantly (prepareArt re-pointed the
// image; the opacity target stays 255); show and hide fade over 240 ms OUT; a key without pixels
// (or whose decode failed) hides at once and never shows the previous cover; a pending decode
// keeps whatever is shown. snap: the first render after the host screen appears.
void renderArt(const CCFrame& f, uint8_t pixels, bool snap) {
    switch (pixels) {
        case ART_OFF:
            tween(artOpa, 0, ART_FADE_MS, 0, EASE_OUT, snap);
            return;
        case ART_MISSING:
        case ART_FAILED:
            artHideNow();
            return;
        case ART_PENDING:
            return;
        default:
            break;
    }
    const uint8_t imageOpa = f.artDim ? ART_DIM_OPA : 255;
    if (imageOpa != artImageOpa) {
        artImageOpa = imageOpa;
        lv_obj_set_style_image_opa(art, imageOpa, 0);
        markChanged();
    }
    setVisible(art, true);
    tween(artOpa, 255, ART_FADE_MS, 0, EASE_OUT, snap);
}

// An RGB565 image descriptor over caller or static pixels.
void describeImage(lv_image_dsc_t& dsc, const uint8_t* pixels, uint32_t side) {
    memset(&dsc, 0, sizeof(dsc));
    dsc.header.magic = LV_IMAGE_HEADER_MAGIC;
    dsc.header.cf = LV_COLOR_FORMAT_RGB565;
    dsc.header.w = side;
    dsc.header.h = side;
    dsc.header.stride = 2 * side;
    dsc.data_size = 2 * side * side;
    dsc.data = pixels;
}

void describeArt(uint8_t i) {
    describeImage(artDsc[i], artBuffer[i], 240);
    artKeyOf[i][0] = '\0';
}

// Points the art image at the front buffer (cleared to black).
void attachArt() {
    for (uint8_t i = 0; i < 2; ++i)
        if (artBuffer[i]) describeArt(i);
    artFront = 0;
    memset(artBuffer[0], 0, CC_ART240_BYTES);
    lv_image_set_src(art, &artDsc[0]);
}

// Shows exactly one content layer (the offline layer included).
void showLayers(uint8_t layout, bool homeish, bool off) {
    setVisible(homeLayer.obj, !off && homeish);
    setVisible(listLayer.obj, !off && (layout == CC_LAYOUT_RECENT || layout == CC_LAYOUT_NOTICE ||
                                       layout == CC_LAYOUT_EXPLORER || layout == CC_LAYOUT_UPNEXT));
    setVisible(tracksLayer.obj, !off && layout == CC_LAYOUT_TRACKS);
    setVisible(seekLayer.obj, !off && layout == CC_LAYOUT_SEEK);
    setVisible(windowsLayer.obj, !off && layout == CC_LAYOUT_WINDOWS);
    setVisible(offlineLayer.obj, off);
}

bool layerVisible(const Layer& layer) { return !lv_obj_has_flag(layer.obj, LV_OBJ_FLAG_HIDDEN); }

}  // namespace

void cc_display_set_media(const CCDisplayMedia& lookups) { media = lookups; }

void cc_display_release_media() {
    releaseMedia(CC_DISPLAY_MEDIA_COVER);
    releaseMedia(CC_DISPLAY_MEDIA_ICON);
    if (media.cancelCover) cancelDecode(true);
    // The next claim starts from rest: its first render snaps, without the latched reduced motion.
    view.rendered = false;
    reducedMotion = false;
    if (offline && screen) {
        offline = false;
        offlinePinsHeld = false;
        setVisible(offlineLayer.obj, false);
    }
}

lv_obj_t* cc_display_create(uint8_t* art240Front, uint8_t* art240Back) {
    if (!art240Front) {                      // one buffer: it is the front
        art240Front = art240Back;
        art240Back = nullptr;
    }
    if (art240Back == art240Front) art240Back = nullptr;
    const bool attach = art240Front && !artBuffer[0];
    if (attach) {
        artBuffer[0] = art240Front;
        artBuffer[1] = art240Back;
    } else if (artBuffer[0] && !artBuffer[1] && art240Back && art240Back != artBuffer[0]) {
        artBuffer[1] = art240Back;           // a back buffer that became available later
        describeArt(1);
    }
    if (screen) {
        if (attach) attachArt();  // buffers that became available after the tree
        return screen;
    }
    screen = lv_obj_create(nullptr);
    lv_obj_remove_style_all(screen);
    lv_obj_set_size(screen, 240, 240);
    lv_obj_remove_flag(screen, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_bg_color(screen, lv_color_hex(CCInk::background), 0);
    lv_obj_set_style_bg_opa(screen, LV_OPA_COVER, 0);
    tag(screen, "screen");

    stage = makeBox(screen, 0, 0, 240, 240, "stage");
    art = lv_image_create(stage);
    lv_obj_remove_style_all(art);
    lv_obj_set_pos(art, 0, 0);
    lv_obj_set_size(art, 240, 240);
    lv_obj_add_flag(art, LV_OBJ_FLAG_HIDDEN);
    lv_obj_set_style_opa(art, 0, 0);
    tag(art, "art");
    if (artBuffer[0]) attachArt();

    makeLayer(content, stage, 0, 0, CONTENT_BOX, "content");
    makeLabel(heading, content, HEADING, &cc_font_12, 1, LV_TEXT_ALIGN_CENTER, "heading", "heading.twin",
              static_cast<int16_t>(HEADING_R), HEADING_TRACKING);
    applyInk(heading, CCInk::context);

    makeLayer(homeLayer, content, HOME_BOX, "home");
    makeLayer(trackLayer, homeLayer, TRACK_BOX, "track");
    makeLabel(homeTitle, trackLayer, HOME_TITLE, &cc_font_22, 2, LV_TEXT_ALIGN_CENTER, "home.title", "home.title.twin");
    makeLabel(homeArtist, trackLayer, HOME_ARTIST, &cc_font_14, 1, LV_TEXT_ALIGN_CENTER, "home.artist",
              "home.artist.twin");
    makeLayer(volumeLayer, homeLayer, VOLUME_BOX, "volume");
    makeLabel(volumeCaption, volumeLayer, VOL_CAPTION, &cc_font_14, 1, LV_TEXT_ALIGN_CENTER, "volume.caption",
              "volume.caption.twin");
    const Box digitsBox = {0, DIGITS_Y, 120, CC_FONT_48_LINE_HEIGHT};
    makeLabel(digits, volumeLayer, digitsBox, &cc_font_48, 1, LV_TEXT_ALIGN_LEFT, "volume.digits",
              "volume.digits.twin", static_cast<int16_t>(SAFE_R), DIGITS_TRACKING);
    const Box percentBox = {0, PERCENT_Y, 40, CC_FONT_22_LINE_HEIGHT};
    makeLabel(percent, volumeLayer, percentBox, &cc_font_22, 1, LV_TEXT_ALIGN_LEFT, "volume.percent",
              "volume.percent.twin");
    applyInk(digits, CCInk::text);
    applyInk(percent, CCInk::context);
    lv_obj_set_style_opa(volumeLayer.obj, 0, 0);
    lv_obj_set_style_translate_y(volumeLayer.obj, 6, 0);
    makeLabel(status, homeLayer, STATUS, &cc_font_12, 1, LV_TEXT_ALIGN_CENTER, "status");
    for (uint8_t i = 0; i < 4; ++i) {
        const Box column = {static_cast<int16_t>(IDLE_CX[i] - IDLE_COLUMN_W / 2), IDLE_Y, IDLE_COLUMN_W,
                            static_cast<int16_t>(IDLE_WORD_DY + CC_FONT_12_LINE_HEIGHT)};
        Layer col;
        makeLayer(col, homeLayer, column, "idle.item");
        idleColumn[i] = col.obj;
        makeIcon(idleIcon[i], col, column.x + (IDLE_COLUMN_W - IDLE_ICON) / 2, IDLE_Y, IDLE_ICON, "idle.icon");
        const Box word = {column.x, static_cast<int16_t>(IDLE_Y + IDLE_WORD_DY), IDLE_COLUMN_W, CC_FONT_12_LINE_HEIGHT};
        makeLabel(idleWord[i], col, word, &cc_font_12, 1, LV_TEXT_ALIGN_CENTER, "idle.word");
        lv_obj_set_style_opa(col.obj, 0, 0);
        lv_obj_set_style_translate_y(col.obj, 14, 0);
        initTween(idleOpa[i], col.obj, PROP_OPA, 0);
        initTween(idleTy[i], col.obj, PROP_TY, 14);
    }

    makeLayer(listLayer, content, LIST_BOX, "list");
    makeLabel(listTitle, listLayer, LIST_TITLE, &cc_font_22, 2, LV_TEXT_ALIGN_CENTER, "list.title", "list.title.twin");
    makeLabel(listSub, listLayer, LIST_SUB, &cc_font_14, 1, LV_TEXT_ALIGN_CENTER, "list.subtitle",
              "list.subtitle.twin");
    makeLabel(listMeta, listLayer, LIST_META, &cc_font_12, 1, LV_TEXT_ALIGN_CENTER, "list.meta");

    makeLayer(tracksLayer, content, TRACKS_BOX, "tracks");
    makeLabel(tracksTitle, tracksLayer, TRACKS_TITLE, &cc_font_22, 1, LV_TEXT_ALIGN_CENTER, "tracks.title",
              "tracks.title.twin");
    for (uint8_t i = 0; i < 3; ++i)
        makeIcon(positionIcon[i], tracksLayer, TRACKS_POS_X[i], TRACKS_POS_Y, POS_ICON, "tracks.position");
    makeLabel(tracksSub, tracksLayer, TRACKS_SUB, &cc_font_14, 1, LV_TEXT_ALIGN_CENTER, "tracks.subtitle",
              "tracks.subtitle.twin");
    makeLabel(tracksMeta, tracksLayer, TRACKS_META, &cc_font_12, 1, LV_TEXT_ALIGN_CENTER, "tracks.meta");

    makeLayer(seekLayer, content, SEEK_BOX, "seek");
    makeLabel(seekCaption, seekLayer, SEEK_CAPTION, &cc_font_14, 1, LV_TEXT_ALIGN_CENTER, "seek.caption",
              "seek.caption.twin");
    makeLabel(seekTime, seekLayer, SEEK_TIME, &cc_font_48t, 1, LV_TEXT_ALIGN_CENTER, "seek.time", "seek.time.twin",
              static_cast<int16_t>(SAFE_R), DIGITS_TRACKING);
    makeLabel(seekLine, seekLayer, SEEK_LINE, &cc_font_14, 1, LV_TEXT_ALIGN_CENTER, "seek.line");

    makeLayer(windowsLayer, content, WINDOWS_BOX, "windows");
    Layer tileLayer;
    makeLayer(tileLayer, windowsLayer, TILE, "windows.tile");
    tile = tileLayer.obj;
    lv_obj_set_style_bg_color(tile, lv_color_hex(CCInk::tile), 0);
    lv_obj_set_style_bg_opa(tile, LV_OPA_COVER, 0);
    const Box letterBox = {TILE.x, static_cast<int16_t>(TILE.y + TILE_LETTER_Y), TILE.w, CC_FONT_16_LINE_HEIGHT};
    makeLabel(tileLetter, tileLayer, letterBox, &cc_font_16, 1, LV_TEXT_ALIGN_CENTER, "windows.letter");
    // artwork2 app icon: a 32x32 RGB565 image filling the tile, drawn as is (no recolour), above
    // the letter; hidden until the store has the key.
    tileIcon = lv_image_create(tile);
    lv_obj_remove_style_all(tileIcon);
    lv_obj_set_pos(tileIcon, 0, 0);
    lv_obj_set_size(tileIcon, TILE.w, TILE.h);
    lv_obj_set_style_image_recolor_opa(tileIcon, LV_OPA_TRANSP, 0);
    describeImage(iconDsc, iconPixels, 32);
    lv_image_set_src(tileIcon, &iconDsc);
    lv_obj_add_flag(tileIcon, LV_OBJ_FLAG_HIDDEN);
    tag(tileIcon, "windows.icon");
    makeLabel(winApp, windowsLayer, WIN_APP, &cc_font_14, 1, LV_TEXT_ALIGN_CENTER, "windows.app");
    makeLabel(winTitle, windowsLayer, WIN_TITLE, &cc_font_16, 2, LV_TEXT_ALIGN_CENTER, "windows.title");
    makeLabel(winMeta, windowsLayer, WIN_META, &cc_font_12, 1, LV_TEXT_ALIGN_CENTER, "windows.meta");

    makeLayer(offlineLayer, content, OFFLINE_BOX, "offline");
    makeLabel(offTitle, offlineLayer, OFF_TITLE, &cc_font_22, 1, LV_TEXT_ALIGN_CENTER, "offline.title");
    makeLabel(offSub, offlineLayer, OFF_SUB, &cc_font_14, 2, LV_TEXT_ALIGN_CENTER, "offline.subtitle");

    makeLayer(footerLayer, stage, 0, 0, FOOTER_BOX, "footer");
    for (uint8_t i = 0; i < 4; ++i)
        makeIcon(footerIcon[i], footerLayer, FOOTER_CX[i] - FOOTER_ICON / 2, FOOTER_Y, FOOTER_ICON, "footer.icon");

    const Layer* const layers[] = {&homeLayer, &listLayer, &tracksLayer, &seekLayer, &windowsLayer, &offlineLayer};
    for (size_t i = 0; i < sizeof(layers) / sizeof(layers[0]); ++i) lv_obj_add_flag(layers[i]->obj, LV_OBJ_FLAG_HIDDEN);

    initTween(trackOpa, trackLayer.obj, PROP_OPA, 255);
    initTween(trackTy, trackLayer.obj, PROP_TY, 0);
    initTween(volumeOpa, volumeLayer.obj, PROP_OPA, 0);
    initTween(volumeTy, volumeLayer.obj, PROP_TY, 6);
    initTween(statusOpa, status.obj, PROP_OPA, 255);
    initTween(footerOpa, footerLayer.obj, PROP_OPA, 255);
    initTween(artOpa, art, PROP_OPA, 0);
    initTween(contentTx, content.obj, PROP_TX, 0);
    initTween(contentOpa, content.obj, PROP_OPA, 255);
    initTween(listMetaOpa, listMeta.obj, PROP_OPA, 255);
    initTween(tracksMetaOpa, tracksMeta.obj, PROP_OPA, 255);
    initTween(winMetaOpa, winMeta.obj, PROP_OPA, 255);
    initTween(offSubOpa, offSub.obj, PROP_OPA, 255);
    return screen;
}

void cc_display_render(const CCFrame& frame, const uint8_t* artwork120) {
    if (!screen) cc_display_create(artBuffer[0], artBuffer[1]);
    ++stats.renders;
    changed = false;
    animated = false;
    stats.lastSlide = 0;
    stats.lastScreenChange = false;
    // Section 7.1: latched on acceptance; reset at every claim (release/offline, above). A frame
    // without the field keeps the latch. Every animation started from here on follows it.
    if (frame.reducedMotionPresent) reducedMotion = frame.reducedMotion;

    const uint8_t layout = frame.layoutId <= CC_LAYOUT_UPNEXT ? frame.layoutId
                                                              : static_cast<uint8_t>(CC_LAYOUT_NOW_PLAYING);
    const bool volume = layout == CC_LAYOUT_VOLUME;
    const bool homeish = layout == CC_LAYOUT_NOW_PLAYING || volume || layout == CC_LAYOUT_IDLE;
    const bool idle = homeish && (layout == CC_LAYOUT_IDLE || (volume && frame.restLayout == CC_LAYOUT_IDLE));
    const bool row = idle && !volume;
    const uint8_t group = groupOf(layout);
    const uint8_t page = group == GROUP_RECENT || group == GROUP_EXPLORER ? frame.page : 0;
    const bool first = !view.rendered;
    const bool fromOffline = offline;
    if (fromOffline) {
        offline = false;
        offlinePinsHeld = false;
    }
    // Section 8.4 "where art shows" (idle and a reveal over idle fade it out).
    const bool wantArt = !idle && (layout == CC_LAYOUT_NOW_PLAYING || volume || layout == CC_LAYOUT_RECENT ||
                                   layout == CC_LAYOUT_TRACKS || layout == CC_LAYOUT_SEEK ||
                                   layout == CC_LAYOUT_EXPLORER || layout == CC_LAYOUT_UPNEXT);
    // Cover lookup (and a synchronous decode) first, before this render starts any animation.
    const uint8_t artPixels = prepareArt(frame, artwork120, wantArt);

    // Screen change (section 8.7): only when (group, page') changes -- never on a control-id
    // change, a Home layout change, a detent, Seek on/off or a heartbeat. From the offline layer:
    // a fade, never a slide.
    bool screenChange = false;
    if (first) {
        tween(contentTx, 0, 0, 0, EASE_OUT, true);
        tween(contentOpa, 255, 0, 0, EASE_OUT, true);
    } else if (fromOffline) {
        tween(contentTx, 0, 0, 0, EASE_OUT, true);
        tweenFrom(contentOpa, 0, 255, CONTENT_FADE_MS, 0, EASE_OUT);
        screenChange = true;
    } else if (group != view.group || page != view.page) {
        const int32_t dir = depthOf(group, page) >= depthOf(view.group, view.page) ? SLIDE_PX : -SLIDE_PX;
        if (reducedMotion) tween(contentTx, 0, 0, 0, EASE_OUT, true);   // section 8.9: fade only
        else tweenFrom(contentTx, dir, 0, CONTENT_SLIDE_MS, 0, EASE_OUT);
        tweenFrom(contentOpa, 0, 255, CONTENT_FADE_MS, 0, EASE_OUT);
        ++stats.slides;
        stats.lastSlide = reducedMotion ? 0 : dir;
        screenChange = true;
    }
    stats.lastScreenChange = screenChange;

    showHeading(heading, frame.heading);
    const bool wasVisible[5] = {layerVisible(homeLayer), layerVisible(listLayer), layerVisible(tracksLayer),
                                layerVisible(seekLayer), layerVisible(windowsLayer)};
    showLayers(layout, homeish, false);
    // A line fades at rest only when its layer was already on screen and the screen did not change.
    const bool rest = !first && !screenChange;
    const bool inkFade = !first && !fromOffline;
    // Layers that were not on screen appear at their final state (the screen change provides the
    // motion), exactly like freshly created design nodes.
    if (homeish) {
        renderHome(frame, volume, idle, first || !view.homeish || fromOffline, rest && wasVisible[0] && !view.row,
                   inkFade && view.row && row);
    } else if (layout == CC_LAYOUT_TRACKS) {
        renderTracks(frame, rest && wasVisible[2]);
    } else if (layout == CC_LAYOUT_SEEK) {
        renderSeek(frame);
    } else if (layout == CC_LAYOUT_WINDOWS) {
        renderWindows(frame, rest && wasVisible[4]);
    } else {
        renderList(frame, rest && wasVisible[1]);
    }
    if (layout != CC_LAYOUT_WINDOWS) releaseMedia(CC_DISPLAY_MEDIA_ICON);  // icons: Windows tile only
    renderFooter(frame, idle, first, inkFade && view.footerShown && !idle);
    renderArt(frame, artPixels, first);

    view.rendered = true;
    view.group = group;
    view.page = page;
    view.layout = layout;
    view.homeish = homeish;
    view.row = row;
    view.footerShown = !idle;
    stats.lastChanged = changed;
    stats.lastAnimated = animated;
}

void cc_display_offline(bool nativeInput) {
    if (!screen) return;
    changed = false;
    animated = false;
    stats.lastSlide = 0;
    stats.lastScreenChange = false;
    if (!offline) {
        offline = true;
        offlineNative = nativeInput;
        offlinePinsHeld = true;
        offlineAt = lv_tick_get();
        reducedMotion = false;               // the session ended (lease expiry); the next claim sets it
        if (media.cancelCover) cancelDecode(true);
        setLabelVisible(heading, false);
        showLayers(CC_LAYOUT_NOW_PLAYING, false, true);
        showText(offTitle, OFFLINE_TITLE);
        applyInk(offTitle, CCInk::text);
        showOfflineSub(nativeInput ? OFFLINE_NATIVE : OFFLINE_SUB, nativeInput);
        applyInk(offSub, CCInk::context);
        tween(offSubOpa, 255, 0, 0, EASE_OUT, true);
        tween(contentTx, 0, 0, 0, EASE_OUT, true);
        tweenFrom(contentOpa, 0, 255, CONTENT_FADE_MS, 0, EASE_OUT);
        tween(footerOpa, 0, 160, 0, EASE_IN, false);
        tween(artOpa, 0, ART_FADE_MS, 0, EASE_OUT, false);
        // The next render sees a group change from offline (never a slide).
        view.group = GROUP_OFFLINE;
        view.page = 0;
        view.homeish = false;
        view.row = false;
        view.footerShown = false;
        stats.lastScreenChange = true;
    } else if (nativeInput && !offlineNative) {
        offlineNative = true;
        showOfflineSub(OFFLINE_NATIVE, true);
        tweenFrom(offSubOpa, 0, 255, LINE_FADE_MS, 0, EASE_OUT);
        ++stats.lineFades;
    }
    // AW2 4.4: both display pins are released once the cover has faded out.
    if (offlinePinsHeld && lv_tick_elaps(offlineAt) >= ART_FADE_MS) {
        offlinePinsHeld = false;
        releaseMedia(CC_DISPLAY_MEDIA_COVER);
        releaseMedia(CC_DISPLAY_MEDIA_ICON);
    }
    stats.lastChanged = changed;
    stats.lastAnimated = animated;
}

bool cc_display_offline_shown() { return offline; }

bool cc_offline_input_update(CCOfflineInput& input, uint16_t pos, uint32_t keyEdges) {
    if (!input.armed) {
        input.armed = true;
        input.native = false;
        input.pos = pos;
        input.keyEdges = keyEdges;
    } else if (pos != input.pos || keyEdges != input.keyEdges) {
        input.native = true;
    }
    return input.native;
}

void cc_offline_input_reset(CCOfflineInput& input) {
    input.armed = false;
    input.native = false;
}

void cc_anim_cadence_sample(CCAnimCadence& cadence, uint32_t animTimerLastRunMs, bool animating, uint32_t periodMs) {
    if (!animating) {                     // episode over: the timer is paused until the next one
        cadence.primed = false;
        return;
    }
    if (!cadence.primed) {
        cadence.primed = true;
        cadence.lastRunMs = animTimerLastRunMs;
        return;
    }
    if (animTimerLastRunMs == cadence.lastRunMs) return;   // the timer did not run this pass
    const uint32_t gap = animTimerLastRunMs - cadence.lastRunMs;
    cadence.lastRunMs = animTimerLastRunMs;
    if (gap > cadence.maxGapMs) cadence.maxGapMs = gap;
    if (gap * 2u > 3u * periodMs) ++cadence.lateRuns;
}

bool cc_anim_cadence_poll(CCAnimCadence& cadence) {
    const lv_timer_t* timer = lv_anim_get_timer();
    if (!timer) return false;
    const uint32_t late = cadence.lateRuns, gap = cadence.maxGapMs;
    cc_anim_cadence_sample(cadence, timer->last_run, lv_anim_count_running() > 0, timer->period);
    return cadence.lateRuns != late || cadence.maxGapMs != gap;
}

const CCDisplayStats& cc_display_stats() { return stats; }
