#include "cc_frame_parse.h"
#include <string.h>

namespace {
// Defaults of every CCFrame field: constant-initialised, so the reset below is
// a copy and never puts another CCFrame on the caller's stack.
constexpr CCFrame kDefaultFrame{};

struct Token { const char* name; uint8_t value; };

// Wire tokens, in enum order where an enum exists.
constexpr Token kActivities[] = {{"idle", CC_IDLE}, {"loading", CC_LOADING}, {"pending", CC_PENDING},
    {"error", CC_ERROR}, {"unavailable", CC_UNAVAILABLE}, {"offline", CC_OFFLINE}};
constexpr Token kLayouts[] = {{"nowPlaying", CC_LAYOUT_NOW_PLAYING}, {"volume", CC_LAYOUT_VOLUME},
    {"idle", CC_LAYOUT_IDLE}, {"recent", CC_LAYOUT_RECENT}, {"tracks", CC_LAYOUT_TRACKS},
    {"windows", CC_LAYOUT_WINDOWS}, {"notice", CC_LAYOUT_NOTICE},
    // Presentation 5 (PRESENTATION_V5.md section 3.1).
    {"seek", CC_LAYOUT_SEEK}, {"explorer", CC_LAYOUT_EXPLORER}, {"upnext", CC_LAYOUT_UPNEXT}};
constexpr Token kRestLayouts[] = {{"nowPlaying", CC_LAYOUT_NOW_PLAYING}, {"idle", CC_LAYOUT_IDLE}};
constexpr Token kTitleTones[] = {{"ink", CC_TITLE_INK}, {"muted", CC_TITLE_MUTED}};
constexpr Token kLineTones[] = {{"meta", CC_LINE_META}, {"secondary", CC_LINE_SECONDARY},
    {"error", CC_LINE_ERROR}, {"success", CC_LINE_SUCCESS}};
constexpr Token kLedStyles[] = {{"white", 0}, {"color", 1}};
constexpr Token kRingStyles[] = {{"off", CC_RING_OFF}, {"level", CC_RING_LEVEL},
    {"selection", CC_RING_SELECTION}, {"transport", CC_RING_TRANSPORT}, {"lap", CC_RING_LAP}};
constexpr Token kIcons[] = {{"", CC_ICON_NONE}, {"play", CC_ICON_PLAY}, {"pause", CC_ICON_PAUSE},
    {"list", CC_ICON_LIST}, {"win", CC_ICON_WIN}, {"tracks", CC_ICON_TRACKS}, {"back", CC_ICON_BACK},
    {"home", CC_ICON_HOME}, {"more", CC_ICON_MORE}, {"prev", CC_ICON_PREV}, {"next", CC_ICON_NEXT},
    {"switch", CC_ICON_SWITCH}, {"cancel", CC_ICON_CANCEL},
    // Presentation 5 (PRESENTATION_V5.md section 9.1).
    {"expand", CC_ICON_EXPAND}, {"clock", CC_ICON_CLOCK}, {"playlists", CC_ICON_PLAYLISTS},
    {"playnext", CC_ICON_PLAYNEXT}, {"seek", CC_ICON_SEEK}, {"shuffle", CC_ICON_SHUFFLE},
    {"heart", CC_ICON_HEART}, {"snapleft", CC_ICON_SNAPLEFT}, {"snapright", CC_ICON_SNAPRIGHT}};
constexpr Token kFeedbackKinds[] = {{"ok", CC_FEEDBACK_OK}, {"err", CC_FEEDBACK_ERR}};
// Derived tone names (cc_token_name only; tones are never parsed). [r2.2] 7 "liked" (5.2 row 4).
constexpr Token kTones[] = {{"none", CC_TONE_NONE}, {"dim", CC_TONE_DIM}, {"stop", CC_TONE_STOP},
    {"go", CC_TONE_GO}, {"nav", CC_TONE_NAV}, {"on", CC_TONE_ON}, {"off", CC_TONE_OFF},
    {"liked", CC_TONE_LIKED}};
// Presentation 5: button lit (section 5.1) and feedback.moment (section 6.1).
constexpr Token kLit[] = {{"on", CC_LIT_ON}, {"off", CC_LIT_OFF}};
constexpr Token kMoments[] = {{"queued", CC_MOMENT_QUEUED}, {"shuffle", CC_MOMENT_SHUFFLE},
    {"like", CC_MOMENT_LIKE}, {"unlike", CC_MOMENT_UNLIKE}, {"snap", CC_MOMENT_SNAP},
    {"started", CC_MOMENT_STARTED}};

template <size_t N>
bool token(JsonVariantConst value, const Token (&tokens)[N], uint8_t& out) {
    if (!value.is<const char*>()) return false;
    const JsonString wire = value.as<JsonString>();
    for (size_t i = 0; i < N; ++i) {
        // Length-aware: an embedded NUL never matches a shorter token.
        if (strlen(tokens[i].name) == wire.size() && !memcmp(tokens[i].name, wire.c_str(), wire.size())) {
            out = tokens[i].value;
            return true;
        }
    }
    return false;
}

template <size_t N>
const char* token_name(const Token (&tokens)[N], uint8_t value) {
    for (size_t i = 0; i < N; ++i) if (tokens[i].value == value) return tokens[i].name;
    return nullptr;
}

bool has(JsonObjectConst object, const char* key) { return object.containsKey(key); }

// Absent optional token keeps `out` (its default); present must be valid.
template <size_t N>
bool optional_token(JsonObjectConst object, const char* key, const Token (&tokens)[N], uint8_t& out) {
    return !has(object, key) || token(object[key], tokens, out);
}

bool optional_bool(JsonObjectConst object, const char* key, bool& out) {
    if (!has(object, key)) return true;
    if (!object[key].is<bool>()) return false;
    out = object[key].as<bool>();
    return true;
}

template <size_t N>
bool text(JsonVariantConst value, char (&out)[N]) { return cc_json_text(value, out, N); }

template <size_t N>
bool optional_text(JsonObjectConst object, const char* key, char (&out)[N]) {
    return !has(object, key) || cc_json_text(object[key], out, N);
}

// artKey: [A-Za-z0-9_-]{0,64}; never truncated (a longer key is invalid).
bool art_key(JsonVariantConst value, char (&out)[65]) {
    if (!value.is<const char*>()) return false;
    const JsonString key = value.as<JsonString>();
    if (key.size() >= sizeof(out)) return false;
    for (size_t i = 0; i < key.size(); ++i) {
        const char c = key.c_str()[i];
        const bool valid = (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') ||
                           (c >= '0' && c <= '9') || c == '_' || c == '-';
        if (!valid) return false;
    }
    memcpy(out, key.c_str(), key.size());
    out[key.size()] = 0;
    return true;
}

// iconKey (ARTWORK2.md section 6): [A-Za-z0-9_-]{0,24}. Stripped, never fatal: a malformed
// value (not a string, too long, other characters) leaves the default "" and the frame is
// still accepted, as the host strips it (identical accept/strip results).
void icon_key(JsonVariantConst value, char (&out)[25]) {
    if (!value.is<const char*>()) return;
    const JsonString key = value.as<JsonString>();
    if (key.size() >= sizeof(out)) return;
    for (size_t i = 0; i < key.size(); ++i) {
        const char c = key.c_str()[i];
        const bool valid = (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') ||
                           (c >= '0' && c <= '9') || c == '_' || c == '-';
        if (!valid) return;
    }
    memcpy(out, key.c_str(), key.size());
    out[key.size()] = 0;
}

// ALIVE.md section 3 (1.0.0-cc5.4) ranges; mirrored by presentation.py ALIVE_*.
constexpr uint32_t kAliveClockMax = 1439;          // local minutes since midnight
constexpr uint32_t kAliveProgressMax = 86400000;   // ms (24 h)
constexpr uint32_t kLedPinkMax = 0xFFFFFF;         // PRESENTATION_V5.md 7.3 (presentation.LED_PINK_MAX)

// Home layouts (nowPlaying/volume/idle/notice): the only ones that keep `playing`.
bool home_layout(uint8_t layout) {
    return layout == CC_LAYOUT_NOW_PLAYING || layout == CC_LAYOUT_VOLUME || layout == CC_LAYOUT_IDLE ||
           layout == CC_LAYOUT_NOTICE;
}

// ALIVE.md section 3 top-level fields, after the layout is known. Every present value is
// validated on every layout (invalid -> reject, like other v4 fields); a valid `playing`
// is then kept only on the Home layouts. device.py alive_parse() is the Python reading.
bool parse_alive(JsonObjectConst frame, CCFrame& f) {
    if (has(frame, "clock")) {
        uint32_t minute = 0;
        if (!cc_json_uint(frame["clock"], 0, kAliveClockMax, minute)) return false;
        f.clockPresent = true;
        f.clockMinute = static_cast<uint16_t>(minute);
    }
    if (has(frame, "playing")) {
        if (!frame["playing"].is<bool>()) return false;
        if (home_layout(f.layoutId)) f.playing = frame["playing"].as<bool>() ? 1 : 0;
    }
    if (has(frame, "progress")) {
        JsonVariantConst progress = frame["progress"];
        uint32_t pos = 0, dur = 0;
        // Extra keys inside the object are ignored, like feedback's.
        if (!progress.is<JsonObjectConst>() || !cc_json_uint(progress["pos"], 0, kAliveProgressMax, pos) ||
            !cc_json_uint(progress["dur"], 0, kAliveProgressMax, dur) || (dur != 0 && pos > dur)) return false;
        f.progressPresent = true;
        f.progressPos = pos;
        f.progressDur = dur;
    }
    if (has(frame, "ledDrive")) {
        uint32_t drive = 0;
        if (!cc_json_uint(frame["ledDrive"], 1, 255, drive)) return false;
        f.ledDrivePresent = true;
        f.ledDrive = static_cast<uint8_t>(drive);
    }
    if (has(frame, "ledDither")) {
        if (!frame["ledDither"].is<bool>()) return false;
        f.ledDitherPresent = true;
        f.ledDither = frame["ledDither"].as<bool>();
    }
    return true;
}

// PRESENTATION_V5.md sections 7.1 and 7.3: the latched reducedMotion (bool), ledPink (int
// 0..0xFFFFFF, 0 = the built-in PINK) and ledVolFull (bool), on every layout. The present flags
// tell the latch (control_center.cpp / the ALIVE struct) which ones this frame carries.
bool parse_v5_latched(JsonObjectConst frame, CCFrame& f) {
    if (has(frame, "reducedMotion")) {
        if (!frame["reducedMotion"].is<bool>()) return false;
        f.reducedMotionPresent = true;
        f.reducedMotion = frame["reducedMotion"].as<bool>();
    }
    if (has(frame, "ledPink")) {
        uint32_t pink = 0;
        if (!cc_json_uint(frame["ledPink"], 0, kLedPinkMax, pink)) return false;
        f.ledPinkPresent = true;
        f.ledPink = pink;
    }
    if (has(frame, "ledVolFull")) {
        if (!frame["ledVolFull"].is<bool>()) return false;
        f.ledVolFullPresent = true;
        f.ledVolFull = frame["ledVolFull"].as<bool>();
    }
    return true;
}

// feedback.skip (ALIVE.md section 3): the JSON integer -1 or 1 (never a bool or a float),
// validated with any kind; kept only when the kind is ok, stripped otherwise.
bool parse_feedback_skip(JsonObjectConst feedback, CCFrame& f) {
    if (!has(feedback, "skip")) return true;
    JsonVariantConst skip = feedback["skip"];
    if (skip.is<bool>() || !skip.is<int32_t>()) return false;
    const int32_t direction = skip.as<int32_t>();
    if (direction != 1 && direction != -1) return false;
    if (f.feedbackKind == CC_FEEDBACK_OK) f.feedbackSkip = static_cast<int8_t>(direction);
    return true;
}

// PRESENTATION_V5.md section 6.2, after kind, seq and skip: every present moment (token), side
// (the JSON integer -1 or 1) and color (int 0..0xFFFFFF) is validated with any kind. With kind
// ok, skip and moment together reject, and so does snap without side; then the moment is kept,
// its side only with snap and its colour only with snap or started. With err all three are
// stripped (the defaults stay).
bool parse_feedback_v5(JsonObjectConst feedback, CCFrame& f) {
    uint8_t moment = CC_MOMENT_NONE;
    int32_t side = 0;
    uint32_t color = 0;
    const bool hasMoment = has(feedback, "moment"), hasSide = has(feedback, "side");
    if (hasMoment && !token(feedback["moment"], kMoments, moment)) return false;
    if (hasSide) {
        JsonVariantConst value = feedback["side"];
        if (value.is<bool>() || !value.is<int32_t>()) return false;
        side = value.as<int32_t>();
        if (side != 1 && side != -1) return false;
    }
    if (has(feedback, "color") && !cc_json_uint(feedback["color"], 0, 0xFFFFFF, color)) return false;
    if (f.feedbackKind != CC_FEEDBACK_OK) return true;
    if (hasMoment && has(feedback, "skip")) return false;
    if (moment == CC_MOMENT_SNAP && !hasSide) return false;
    f.feedbackMoment = moment;
    if (moment == CC_MOMENT_SNAP) f.feedbackSide = static_cast<int8_t>(side);
    if (moment == CC_MOMENT_SNAP || moment == CC_MOMENT_STARTED) f.feedbackColor = color;
    return true;
}

// Section 2: layout of a legacy frame without one.
uint8_t legacy_layout(const char* mode) {
    if (!strcmp(mode, "RECENTLY ADDED")) return CC_LAYOUT_RECENT;
    if (!strcmp(mode, "TRACKS")) return CC_LAYOUT_TRACKS;
    if (!strcmp(mode, "WINDOWS")) return CC_LAYOUT_WINDOWS;
    return CC_LAYOUT_NOW_PLAYING; // "VOLUME" and anything else
}

bool parse_buttons(JsonVariantConst value, CCFrame& f) {
    if (!value.is<JsonArrayConst>()) return false;
    JsonArrayConst buttons = value.as<JsonArrayConst>();
    if (buttons.size() != 4) return false;
    for (size_t i = 0; i < 4; ++i) {
        JsonVariantConst item = buttons[i];
        if (!item.is<JsonObjectConst>()) return false;
        JsonObjectConst button = item.as<JsonObjectConst>();
        CCButton& out = f.buttons[i];
        if (!text(button["label"], out.label) || !button["enabled"].is<bool>()) return false;
        out.enabled = button["enabled"].as<bool>();
        if (has(button, "icon")) {
            if (!token(button["icon"], kIcons, out.icon)) return false;
            out.iconSent = true;
        }
        if (has(button, "color") && !cc_json_uint(button["color"], 0, 0xFFFFFF, out.color)) return false;
        // Presentation 5 (section 5.1): lit "on" | "off"; no scope strip (the tone order handles it).
        if (has(button, "lit") && !token(button["lit"], kLit, out.lit)) return false;
    }
    return true;
}

bool parse_ring(JsonVariantConst value, CCFrame& f) {
    if (!value.is<JsonObjectConst>()) return false;
    JsonObjectConst ring = value.as<JsonObjectConst>();
    uint32_t level = 0, index = 0, count = 0;
    if (!token(ring["style"], kRingStyles, f.ringStyle) ||
        !cc_json_uint(ring["value"], 0, 100, level) ||
        !cc_json_uint(ring["index"], 0, 65535, index) ||
        !cc_json_uint(ring["count"], 0, 65535, count)) return false;
    if ((f.ringStyle == CC_RING_SELECTION || f.ringStyle == CC_RING_TRANSPORT) && index >= count) return false;
    // PRESENTATION_V5.md 4.3: the Seek lap needs 1 <= count (D s) <= CC_LAP_COUNT_MAX and index < count.
    if (f.ringStyle == CC_RING_LAP && (count < 1 || count > CC_LAP_COUNT_MAX || index >= count)) return false;
    f.ringValue = static_cast<uint8_t>(level);
    f.ringIndex = static_cast<uint16_t>(index);
    f.ringCount = static_cast<uint16_t>(count);

    // Section 4 window rule. A present first must satisfy
    // 0 <= first <= index < first+20 and be 0 when count <= 20. An absent
    // first is derived; colours and the mask were relative to an implicit 0,
    // so they are kept only when the derived first is 0 (rules.absentFirst).
    bool relative = true;
    if (has(ring, "first")) {
        uint32_t first = 0;
        if (!cc_json_uint(ring["first"], 0, 65535, first) || first > index ||
            index >= first + CC_RING_WINDOW || (count <= CC_RING_WINDOW && first != 0)) return false;
        f.ringFirst = static_cast<uint16_t>(first);
    } else {
        f.ringFirst = cc_window_first(f.ringIndex, f.ringCount);
        relative = f.ringFirst == 0;
    }
    const uint32_t remaining = count > f.ringFirst ? count - f.ringFirst : 0;
    const uint32_t window = remaining < CC_RING_WINDOW ? remaining : CC_RING_WINDOW;
    if (relative && has(ring, "colors")) {
        if (!ring["colors"].is<JsonArrayConst>()) return false;
        JsonArrayConst colors = ring["colors"].as<JsonArrayConst>();
        if (colors.size() > window) return false;
        for (size_t k = 0; k < colors.size(); ++k)
            if (!cc_json_uint(colors[k], 0, 0xFFFFFF, f.ringColors[k])) return false;
        f.ringColorCount = static_cast<uint8_t>(colors.size());
    }
    if (relative && has(ring, "unavailable") &&
        !cc_json_uint(ring["unavailable"], 0, (1UL << window) - 1, f.ringUnavailable)) return false;
    // PRESENTATION_V5.md 4.4 (P5-R24): Up next rows have no unavailable state. A valid mask is
    // stripped on layout upnext, so no entry reads as unavailable (or as the card) there.
    if (f.layoutId == CC_LAYOUT_UPNEXT) f.ringUnavailable = 0;
    if (has(ring, "moreIndex")) {
        JsonVariantConst more = ring["moreIndex"];
        if (more.is<bool>() || !more.is<int32_t>()) return false;
        const int32_t moreIndex = more.as<int32_t>();
        if (moreIndex < -1 || moreIndex > static_cast<int32_t>(count) - 1) return false;
        f.ringMoreIndex = moreIndex;
    }
    if (!optional_bool(ring, "external", f.ringExternal)) return false;
    // PRESENTATION_V5.md 4.4: now (int -1..count-1) and card (bool) are validated on every layout
    // and kept only on the Up next mirror (selection ring, layout upnext). card:true there needs
    // count >= 2 and now == count - 2 (the card follows the now-playing row), else reject.
    const bool upnext = f.ringStyle == CC_RING_SELECTION && f.layoutId == CC_LAYOUT_UPNEXT;
    int32_t now = -1;
    if (has(ring, "now")) {
        JsonVariantConst wire = ring["now"];
        if (wire.is<bool>() || !wire.is<int32_t>()) return false;
        now = wire.as<int32_t>();
        if (now < -1 || now > static_cast<int32_t>(count) - 1) return false;
        if (upnext) f.ringNow = now;
    }
    if (has(ring, "card")) {
        if (!ring["card"].is<bool>()) return false;
        const bool card = ring["card"].as<bool>();
        if (upnext) {
            if (card && (count < 2 || now != static_cast<int32_t>(count) - 2)) return false;
            f.ringCard = card;
        }
    }
    return true;
}
} // namespace

bool cc_json_uint(JsonVariantConst value, uint32_t lo, uint32_t hi, uint32_t& out) {
    if (value.is<bool>() || !value.is<uint32_t>()) return false;
    const uint32_t number = value.as<uint32_t>();
    if (number < lo || number > hi) return false;
    out = number;
    return true;
}

bool cc_json_text(JsonVariantConst value, char* out, size_t capacity) {
    if (!capacity || !value.is<const char*>()) return false;
    const JsonString string = value.as<JsonString>();
    const unsigned char* p = reinterpret_cast<const unsigned char*>(string.c_str());
    const size_t size = string.size();
    size_t i = 0, written = 0;
    bool truncated = false;
    while (i < size) {
        const unsigned char lead = p[i];
        size_t n = 1;
        uint32_t cp = lead;
        if (lead < 0x20) return false; // control characters, including NUL
        if (lead >= 0x80) {
            if (lead >= 0xC2 && lead <= 0xDF) { n = 2; cp = lead & 0x1F; }
            else if (lead >= 0xE0 && lead <= 0xEF) { n = 3; cp = lead & 0x0F; }
            else if (lead >= 0xF0 && lead <= 0xF4) { n = 4; cp = lead & 0x07; }
            else return false;
            if (n > size - i) return false;
            for (size_t j = 1; j < n; ++j) {
                if ((p[i + j] & 0xC0) != 0x80) return false;
                cp = (cp << 6) | (p[i + j] & 0x3F);
            }
            if ((n == 3 && cp < 0x800) || (n == 4 && cp < 0x10000) || cp > 0x10FFFF ||
                (cp >= 0xD800 && cp <= 0xDFFF)) return false;
        }
        // Keep whole code points while they fit; the rest is still validated.
        if (!truncated && written + n < capacity) {
            memcpy(out + written, p + i, n);
            written += n;
        } else {
            truncated = true;
        }
        i += n;
    }
    out[written] = 0;
    return true;
}

bool cc_parse_frame(JsonVariantConst value, CCFrame& f) {
    f = kDefaultFrame;
    if (!value.is<JsonObjectConst>()) return false;
    JsonObjectConst frame = value.as<JsonObjectConst>();
    if (has(frame, "id")) {
        uint32_t id = 0;
        if (!cc_json_uint(frame["id"], 1, 0x7FFFFFFF, id)) return false;
    }
    // Required text.
    if (!text(frame["mode"], f.mode) || !text(frame["target"], f.target) ||
        !text(frame["value"], f.value) || !text(frame["detail"], f.detail) ||
        !text(frame["status"], f.status)) return false;
    // Optional text ("" when absent).
    if (!optional_text(frame, "title", f.title) || !optional_text(frame, "subtitle", f.subtitle) ||
        !optional_text(frame, "counter", f.counter) || !optional_text(frame, "heading", f.heading) ||
        !optional_text(frame, "meta", f.meta) ||
        !optional_text(frame, "volumeCaption", f.volumeCaption)) return false;
    if (has(frame, "artKey") && !art_key(frame["artKey"], f.artKey)) return false;
    // Enumerations (defaults from the CCFrame initialisers).
    uint8_t ledStyle = 0;
    if (!optional_token(frame, "activity", kActivities, f.activity) ||
        !optional_token(frame, "restLayout", kRestLayouts, f.restLayout) ||
        !optional_token(frame, "titleTone", kTitleTones, f.titleTone) ||
        !optional_token(frame, "metaTone", kLineTones, f.metaTone) ||
        !optional_token(frame, "statusTone", kLineTones, f.statusTone) ||
        !optional_token(frame, "ledStyle", kLedStyles, ledStyle)) return false;
    f.coloredLeds = ledStyle != 0;
    if (has(frame, "layout")) {
        if (!token(frame["layout"], kLayouts, f.layoutId)) return false;
    } else {
        f.layoutId = legacy_layout(f.mode);
    }
    // iconKey is meaningful only on the windows layout (after the legacy derivation): on any
    // other layout it is stripped, like the host does.
    if (f.layoutId == CC_LAYOUT_WINDOWS && has(frame, "iconKey")) icon_key(frame["iconKey"], f.iconKey);
    // 1.0.0-cc5.4: clock, playing (Home layouts only), progress, ledDrive, ledDither.
    if (!parse_alive(frame, f)) return false;
    // Presentation 5: reducedMotion, ledPink, ledVolFull (latched by the caller on acceptance).
    if (!parse_v5_latched(frame, f)) return false;
    if (has(frame, "page")) {
        uint32_t page = 0;
        if (!cc_json_uint(frame["page"], 0, 255, page)) return false;
        f.page = static_cast<uint8_t>(page);
    }
    // volumeVisible is a legacy mirror of layout == "volume": validated, not stored.
    bool volumeVisible = false;
    if (!optional_bool(frame, "artDim", f.artDim) || !optional_bool(frame, "volumeVisible", volumeVisible))
        return false;
    if (has(frame, "feedback")) {
        JsonVariantConst feedback = frame["feedback"];
        if (!feedback.is<JsonObjectConst>() || !token(feedback["kind"], kFeedbackKinds, f.feedbackKind) ||
            !cc_json_uint(feedback["seq"], 1, 0x7FFFFFFF, f.feedbackSeq) ||
            !parse_feedback_skip(feedback.as<JsonObjectConst>(), f) ||
            !parse_feedback_v5(feedback.as<JsonObjectConst>(), f)) return false;
        f.feedbackPresent = true;
    }
    if (!parse_buttons(frame["buttons"], f) || !parse_ring(frame["ring"], f)) return false;
    if (has(frame, "confirmedVolume")) {
        uint32_t confirmed = 0;
        if (!cc_json_uint(frame["confirmedVolume"], 0, 100, confirmed)) return false;
        f.confirmedVolume = static_cast<uint8_t>(confirmed);
    } else {
        f.confirmedVolume = f.ringValue;
    }
    return true;
}

const char* cc_token_name(CCTokenSet set, uint8_t value) {
    switch (set) {
        case CC_TOKENS_ACTIVITY: return token_name(kActivities, value);
        case CC_TOKENS_LAYOUT: return token_name(kLayouts, value);
        case CC_TOKENS_TITLE_TONE: return token_name(kTitleTones, value);
        case CC_TOKENS_LINE_TONE: return token_name(kLineTones, value);
        case CC_TOKENS_RING_STYLE: return token_name(kRingStyles, value);
        case CC_TOKENS_ICON: return token_name(kIcons, value);
        case CC_TOKENS_FEEDBACK: return token_name(kFeedbackKinds, value);
        case CC_TOKENS_TONE: return token_name(kTones, value);
        case CC_TOKENS_LIT: return token_name(kLit, value);
        case CC_TOKENS_MOMENT: return token_name(kMoments, value);
    }
    return nullptr;
}
