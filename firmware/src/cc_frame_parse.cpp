#include "cc_frame_parse.h"
#include "cc_haptic_fx.h"
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
    {"seek", CC_LAYOUT_SEEK}, {"explorer", CC_LAYOUT_EXPLORER}, {"upnext", CC_LAYOUT_UPNEXT},
    // Presentation 6 (PRESENTATION_V5.md section 19.1).
    {"lights", CC_LAYOUT_LIGHTS}, {"lightsbig", CC_LAYOUT_LIGHTSBIG}, {"scenes", CC_LAYOUT_SCENES}};
constexpr Token kRestLayouts[] = {{"nowPlaying", CC_LAYOUT_NOW_PLAYING}, {"idle", CC_LAYOUT_IDLE}};
constexpr Token kTitleTones[] = {{"ink", CC_TITLE_INK}, {"muted", CC_TITLE_MUTED}};
constexpr Token kLineTones[] = {{"meta", CC_LINE_META}, {"secondary", CC_LINE_SECONDARY},
    {"error", CC_LINE_ERROR}, {"success", CC_LINE_SUCCESS},
    {"warm", CC_LINE_WARM}};   // presentation 6 (section 19.9)
constexpr Token kLedStyles[] = {{"white", 0}, {"color", 1}};
constexpr Token kRingStyles[] = {{"off", CC_RING_OFF}, {"level", CC_RING_LEVEL},
    {"selection", CC_RING_SELECTION}, {"transport", CC_RING_TRANSPORT}, {"lap", CC_RING_LAP},
    // Presentation 6 (section 19.3).
    {"bri", CC_RING_BRI}, {"ctemp", CC_RING_CTEMP}, {"clusters", CC_RING_CLUSTERS},
    {"marker", CC_RING_MARKER},    // presentation 6 (section 19.9)
    {"queue", CC_RING_QUEUE}};     // [r3.1] section 19.10
constexpr Token kIcons[] = {{"", CC_ICON_NONE}, {"play", CC_ICON_PLAY}, {"pause", CC_ICON_PAUSE},
    {"list", CC_ICON_LIST}, {"win", CC_ICON_WIN}, {"tracks", CC_ICON_TRACKS}, {"back", CC_ICON_BACK},
    {"home", CC_ICON_HOME}, {"more", CC_ICON_MORE}, {"prev", CC_ICON_PREV}, {"next", CC_ICON_NEXT},
    {"switch", CC_ICON_SWITCH}, {"cancel", CC_ICON_CANCEL},
    // Presentation 5 (PRESENTATION_V5.md section 9.1).
    {"expand", CC_ICON_EXPAND}, {"clock", CC_ICON_CLOCK}, {"playlists", CC_ICON_PLAYLISTS},
    {"playnext", CC_ICON_PLAYNEXT}, {"seek", CC_ICON_SEEK}, {"shuffle", CC_ICON_SHUFFLE},
    {"heart", CC_ICON_HEART}, {"snapleft", CC_ICON_SNAPLEFT}, {"snapright", CC_ICON_SNAPRIGHT},
    // Presentation 6 (section 19.5).
    {"bulb", CC_ICON_BULB}, {"thermo", CC_ICON_THERMO}, {"power", CC_ICON_POWER}, {"wand", CC_ICON_WAND},
    {"house", CC_ICON_HOUSE}, {"album", CC_ICON_ALBUM}};
constexpr Token kFeedbackKinds[] = {{"ok", CC_FEEDBACK_OK}, {"err", CC_FEEDBACK_ERR}};
// Derived tone names (cc_token_name only; tones are never parsed). [r2.2] 7 "liked" (5.2 row 4).
constexpr Token kTones[] = {{"none", CC_TONE_NONE}, {"dim", CC_TONE_DIM}, {"stop", CC_TONE_STOP},
    {"go", CC_TONE_GO}, {"nav", CC_TONE_NAV}, {"on", CC_TONE_ON}, {"off", CC_TONE_OFF},
    {"liked", CC_TONE_LIKED}};
// Presentation 5: button lit (section 5.1) and feedback.moment (section 6.1).
constexpr Token kLit[] = {{"on", CC_LIT_ON}, {"off", CC_LIT_OFF}};
constexpr Token kMoments[] = {{"queued", CC_MOMENT_QUEUED}, {"shuffle", CC_MOMENT_SHUFFLE},
    {"like", CC_MOMENT_LIKE}, {"unlike", CC_MOMENT_UNLIKE}, {"snap", CC_MOMENT_SNAP},
    {"started", CC_MOMENT_STARTED},
    {"refused", CC_MOMENT_REFUSED}};   // presentation 6 (section 19.9): kind err only
// Presentation 6: valueUnit (section 19.2).
constexpr Token kUnits[] = {{"%", CC_UNIT_PERCENT}, {"K", CC_UNIT_KELVIN}};
// Presentation 6: crumb (section 19.9), in CCCrumb order.
constexpr Token kCrumbs[] = {{"music", CC_CRUMB_MUSIC}, {"recent", CC_CRUMB_RECENT},
    {"onScreenRecent", CC_CRUMB_ONSCREEN_RECENT}, {"onScreenPlaylists", CC_CRUMB_ONSCREEN_PLAYLISTS},
    {"tracks", CC_CRUMB_TRACKS}, {"upnext", CC_CRUMB_UPNEXT}, {"windows", CC_CRUMB_WINDOWS},
    {"lights", CC_CRUMB_LIGHTS}, {"scenes", CC_CRUMB_SCENES}, {"playlists", CC_CRUMB_PLAYLISTS}};

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

// Presentation 6 (PRESENTATION_V5.md section 19.2), after the layout is known.
bool parse_v6_text(JsonObjectConst frame, CCFrame& f) {
    uint8_t unit = CC_UNIT_PERCENT;
    if (!optional_token(frame, "valueUnit", kUnits, unit)) return false;
    if (f.layoutId == CC_LAYOUT_LIGHTSBIG) f.valueUnit = unit;
    const bool scenes = f.layoutId == CC_LAYOUT_SCENES;
    // Validated into the frame's own buffers, then cleared off scenes (no second 65 B buffer on the stack).
    if (!optional_text(frame, "prevTitle", f.prevTitle) || !optional_text(frame, "nextTitle", f.nextTitle))
        return false;
    if (!scenes) f.prevTitle[0] = f.nextTitle[0] = '\0';
    // Section 19.9: crumb (a token; invalid rejects), kept on every layout.
    if (!optional_token(frame, "crumb", kCrumbs, f.crumb)) return false;
    // [r3.1] section 19.10: holdMarker (a bool; anything else rejects), kept on every layout.
    if (!optional_bool(frame, "holdMarker", f.holdMarker)) return false;
    return true;
}

// A2 app canvas (1.0.0-cc5.6; CONTROL_CENTER.md "App canvas"): the optional `app` object, on any layout. Every
// present value is validated (invalid rejects the frame, the strict rule); unknown keys inside are ignored.
// App profiles (APP_PROFILES.md section 8): `id` is any profile id (1..11 of [a-z0-9_-]); one that is not loaded,
// or whose optional `crc` (u32) differs, is drawn as "Loading..." by the LCD thread, never rejected here. The slot
// tokens knob / f1..f4 follow the legacy ones; `index` goes to 32.
constexpr Token kAppSlots[] = {{"zoom", CC_APP_SLOT_ZOOM}, {"orbit", CC_APP_SLOT_ORBIT}, {"pan", CC_APP_SLOT_PAN},
                               {"tilt", CC_APP_SLOT_TILT}, {"knob", CC_APP_SLOT_KNOB}, {"f1", CC_APP_SLOT_F1},
                               {"f2", CC_APP_SLOT_F2}, {"f3", CC_APP_SLOT_F3}, {"f4", CC_APP_SLOT_F4}};

// The profile id: a string of 1..CC_APP_ID_CAPACITY - 1 characters of [a-z0-9_-] (so no NUL), copied with its NUL.
bool app_id(JsonVariantConst value, char (&out)[CC_APP_ID_CAPACITY]) {
    if (!value.is<const char*>()) return false;
    const JsonString wire = value.as<JsonString>();
    const size_t size = wire.size();
    if (size < 1 || size >= CC_APP_ID_CAPACITY) return false;
    for (size_t i = 0; i < size; ++i) {
        const char c = wire.c_str()[i];
        if (!((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_' || c == '-')) return false;
    }
    memcpy(out, wire.c_str(), size);
    out[size] = '\0';
    return true;
}
constexpr Token kAppModes[] = {{"A", 0}, {"B", 1}};

bool app_uint8(JsonVariantConst value, uint32_t lo, uint32_t hi, uint8_t& out) {
    uint32_t number = 0;
    if (!cc_json_uint(value, lo, hi, number)) return false;
    out = static_cast<uint8_t>(number);
    return true;
}

// r4 FEEL (1.0.0-cc5.7; HAPTICS.md "Events"): the optional `haptic` object {"token": CCFx wire token, "seq": int
// 1..0x7FFFFFFF}, on any layout, the strict rule (an unknown token, a missing or bad seq rejects the frame; unknown
// keys inside are ignored). device.py haptic_parse() is the Python reading.
bool parse_haptic(JsonObjectConst frame, CCFrame& f) {
    if (!has(frame, "haptic")) return true;
    if (!frame["haptic"].is<JsonObjectConst>()) return false;
    JsonObjectConst haptic = frame["haptic"].as<JsonObjectConst>();
    const char* wire = cc_json_token(haptic["token"]);   // FW-RES-007: no NUL-suffixed token
    if (wire == nullptr) return false;
    uint8_t fx = CC_HFX_NONE;
    uint32_t seq = 0;
    if (!cc_fx_parse(wire, fx) || !cc_json_uint(haptic["seq"], 1, 0x7FFFFFFF, seq)) return false;
    f.hapticFx = fx;
    f.hapticSeq = seq;
    return true;
}

bool parse_app(JsonObjectConst frame, CCFrame& f) {
    if (!has(frame, "app")) return true;
    if (!frame["app"].is<JsonObjectConst>()) return false;
    JsonObjectConst app = frame["app"].as<JsonObjectConst>();
    CCAppState a;
    if (!app_id(app["id"], a.id) || !token(app["slot"], kAppSlots, a.slot)) return false;
    if (has(app, "crc") && !cc_json_uint(app["crc"], 0, 0xFFFFFFFFu, a.crc)) return false;
    if (!optional_bool(app, "refused", a.refused)) return false;
    // DD-SEC-001: optional refusedFocus (default false), kept only with refused. Read leniently (a non-bool is
    // false, never a rejection): device.app_parse and older firmware ignore the key, so acceptance stays the same.
    a.refusedFocus = a.refused && app["refusedFocus"].is<bool>() && app["refusedFocus"].as<bool>();
    if (has(app, "flash") && !cc_json_uint(app["flash"], 0, 0x7FFFFFFF, a.flash)) return false;
    if (has(app, "wheel")) {
        if (!app["wheel"].is<JsonObjectConst>()) return false;
        JsonObjectConst wheel = app["wheel"].as<JsonObjectConst>();
        if (!app_uint8(wheel["ring"], 0, CC_APP_RING_MAX, a.wheelRing) ||
            !app_uint8(wheel["index"], 0, CC_APP_INDEX_MAX, a.wheelIndex)) return false;
        a.wheel = true;
    }
    if (has(app, "param")) {
        if (!app["param"].is<JsonObjectConst>()) return false;
        JsonObjectConst param = app["param"].as<JsonObjectConst>();
        uint8_t mode = 0;
        if (!app_uint8(param["ring"], 0, CC_APP_RING_MAX, a.paramRing) ||
            !app_uint8(param["index"], 1, CC_APP_INDEX_MAX, a.paramIndex) ||
            !token(param["mode"], kAppModes, mode) || !app_uint8(param["step"], 0, 2, a.paramStep)) return false;
        JsonVariantConst value = param["value"];
        if (value.is<bool>() || !value.is<int32_t>()) return false;
        const int32_t milli = value.as<int32_t>();
        if (milli < -CC_APP_VALUE_MAX || milli > CC_APP_VALUE_MAX) return false;
        if (has(param, "bump") && !cc_json_uint(param["bump"], 0, 0x7FFFFFFF, a.paramBump)) return false;
        // App profiles (APP_PROFILES.md section 8): the live constraint. `axis` 0..3 (X, Y, Z, uniform; absent = the
        // profile's axis_default, stored -1), `plane` a bool (the axis key with Shift; default false).
        uint8_t axis = 0;
        if (has(param, "axis")) {
            if (!app_uint8(param["axis"], 0, 3, axis)) return false;
            a.paramAxis = static_cast<int8_t>(axis);
        }
        if (!optional_bool(param, "plane", a.paramPlane)) return false;
        a.param = true;
        a.paramTyped = mode == 1;
        a.paramValue = milli;
    }
    if (has(app, "echo")) {
        if (!app["echo"].is<JsonObjectConst>()) return false;
        JsonObjectConst echo = app["echo"].as<JsonObjectConst>();
        if (!app_uint8(echo["ring"], 0, CC_APP_RING_MAX, a.echoRing) ||
            !app_uint8(echo["index"], 1, CC_APP_INDEX_MAX, a.echoIndex) ||
            !cc_json_uint(echo["seq"], 1, 0x7FFFFFFF, a.echoSeq)) return false;
    }
    f.app = a;
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
    // Presentation 6 (section 19.9): `refused` is kept only with kind err (then alone: no side, no colour);
    // with kind ok it is stripped (moment none), like every other moment is with err.
    if (f.feedbackKind != CC_FEEDBACK_OK) {
        if (moment == CC_MOMENT_REFUSED) f.feedbackMoment = moment;
        return true;
    }
    if (moment == CC_MOMENT_REFUSED) return true;
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
    // Presentation 6 (section 19.3): clusters needs 1 <= count <= 20 and index < count; ring.kelvin is an int
    // 2200..6500, required on bri and ctemp, validated on every other style and then stripped (0).
    if (f.ringStyle == CC_RING_CLUSTERS && (count < 1 || count > CC_CLUSTERS_MAX || index >= count)) return false;
    // Section 19.9: marker needs 1 <= count and index < count.
    if (f.ringStyle == CC_RING_MARKER && (count < 1 || index >= count)) return false;
    // [r3.1] section 19.10: queue needs 1 <= count and index < count.
    if (f.ringStyle == CC_RING_QUEUE && (count < 1 || index >= count)) return false;
    const bool kelvinStyle = f.ringStyle == CC_RING_BRI || f.ringStyle == CC_RING_CTEMP;
    if (has(ring, "kelvin")) {
        uint32_t kelvin = 0;
        if (!cc_json_uint(ring["kelvin"], CC_KELVIN_MIN, CC_KELVIN_MAX, kelvin)) return false;
        if (kelvinStyle) f.ringKelvin = static_cast<uint16_t>(kelvin);
    } else if (kelvinStyle) {
        return false;
    }
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
        // [r3.1] section 19.10: the queue ring keeps `now` (the playing row) on every layout.
        if (upnext || f.ringStyle == CC_RING_QUEUE) f.ringNow = now;
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

const char* cc_json_token(JsonVariantConst value) {
    if (!value.is<const char*>()) return nullptr;
    const JsonString wire = value.as<JsonString>();
    return strlen(wire.c_str()) == wire.size() ? wire.c_str() : nullptr;
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
    // Presentation 6 (section 19.2): valueUnit ("%" | "K") and prevTitle / nextTitle (text <= 64 B) are
    // validated on every layout (invalid rejects), then kept only on lightsbig / scenes respectively.
    if (!parse_v6_text(frame, f)) return false;
    // 1.0.0-cc5.4: clock, playing (Home layouts only), progress, ledDrive, ledDither.
    if (!parse_alive(frame, f)) return false;
    // Presentation 5: reducedMotion, ledPink, ledVolFull (latched by the caller on acceptance).
    if (!parse_v5_latched(frame, f)) return false;
    // A2 (1.0.0-cc5.6): the app canvas object.
    if (!parse_app(frame, f)) return false;
    // 1.0.0-cc5.7 (r4 FEEL): the haptic event.
    if (!parse_haptic(frame, f)) return false;
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
        case CC_TOKENS_UNIT: return token_name(kUnits, value);
        case CC_TOKENS_CRUMB: return value == CC_CRUMB_NONE ? "" : token_name(kCrumbs, value);
    }
    return nullptr;
}
