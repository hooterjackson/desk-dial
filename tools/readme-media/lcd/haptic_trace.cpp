// haptic-trace: torque-against-angle traces from the knob firmware's own feel laws (src/cc_haptic_fx.h, header-only,
// compiled unchanged with /I <firmware>/src) and the host harness's knob model (work/lcd-preview/haptic_fx_tests.cpp
// struct Knob, copied verbatim below and kept in sync by tools/readme-media/model_sync.py). README media only: no
// device, no serial port, no network.
//
//   haptic-trace <spec.json> <out.json>
//
// spec {"mode":"static", "feel":"detent.value", "detents":67, "lo":0, "hi":8, "pos":4, "span_deg":[-40,40],
//       "step_deg":0.05}
//   -> the standing torque law around the committed detent `pos`: for every shaft angle theta (degrees, 0 = the
//      centre of detent `pos`) the attractor is the nearest detent centre inside the bounds (clamped at lo / hi), the
//      spring is cc_law_spring(law, kp, attract - theta, w) x 5.3 V, and past the last detent centre the wall
//      cc_wall_volts(cc_law_slope(law, kp), pen, w, 2.2 V) pushes back (haptic.cpp token_target, the same calls).
//      samples: {theta_deg, uq_volts, pct_of_cap, wall_pen_deg}.
// spec {"mode":"dynamic", "feel":"detent.value", "detents":67, "lo":0, "hi":8, "pos":4, "rest":true,
//       "segments":[{"kind":"drive","omega_rad_s":0.5,"ms":3000}, {"kind":"free","ms":1500},
//                   {"kind":"effect","token":"confirm.thump","ms":200}]}
//   -> the harness's Knob stepped at 60 us: "drive" turns the shaft as a velocity source (as model_tests' constant
//      speed turn does), "free" lets the rotor go, "effect" starts an event the way model_tests does
//      (k.fx.start(fx, false, k.now, lpf, false, cue)) then runs free for `ms` (default 0). One sample per ms:
//      {t_ms, theta_deg, pos, uq_volts, torque_model_mNm, asleep, at_limit}; torque_model_mNm = Kt (Uq - Kt omega) / R.
#include "cc_haptic_fx.h"

#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <map>
#include <sstream>
#include <string>
#include <vector>

// ===== BEGIN verbatim copy of work/lcd-preview/haptic_fx_tests.cpp struct Knob (lines 267-373) =====
// Do not edit: model_sync.py compares this block with the harness and fails when they differ.
struct Knob {
    double J = 3.25e-6, Kt = 0.04, friction = 2e-6;
    double theta = 0.0, omega = 0.0, lpf = 0.0;
    bool flip = false;
    // loop state
    CCFeelParams p = cc_feel_params(CC_FEEL_LIST, false);
    uint8_t feel = CC_FEEL_LIST;
    float w = 0.0f, origin = 0.0f, attract = 0.0f, lastAttract = 0.0f;
    int pos = 0, lo = 0, hi = 1000;
    bool atLimit = false, legacy = false;
    CCFxPlayer fx;
    CCFoldback fold;
    CCSpinTrip trip;
    bool tripEnabled = true;
    bool restEnabled = false;          // haptic.cpp's rest gate (off by default: the older cases predate it)
    CCRestGate rest;
    uint32_t now = 0;
    float lastUq = 0.0f;
    bool frozenBefore = false;
    double freezeStart = 0.0;
    void setFeel(uint8_t f, int detents) {
        feel = f; p = cc_feel_params(f, false); legacy = f == CC_FEEL_LEGACY;
        w = static_cast<float>(2.0 * 3.14159265358979 / (p.detents ? p.detents : detents));
        origin = attract = lastAttract = static_cast<float>(theta);
    }
    void findDetent() {
        const float hyst = w * 0.25f, th = static_cast<float>(theta);
        if (th < attract - hyst || th > attract + hyst) attract = std::round((th - origin) / w) * w + origin;
        if (attract != lastAttract) {
            if (attract > lastAttract) { if (pos < hi) { ++pos; lastAttract = attract; atLimit = false; } else atLimit = true; }
            else { if (pos > lo) { --pos; lastAttract = attract; atLimit = false; } else atLimit = true; }
        }
    }
    // haptic.cpp end_freeze(): still in a viscous feel, the grid moves with the pulses; otherwise the detents crossed
    // while frozen are counted one at a time (a bound stops the count).
    void endFreeze() {
        if (!legacy && p.law == CC_LAW_VISCOSE && std::fabs(lpf) < CC_HFX_FREEZE_RAD_S) {
            const float shift = static_cast<float>(theta - freezeStart);
            origin += shift; attract += shift; lastAttract += shift;
            return;
        }
        const float target = std::round((static_cast<float>(theta) - origin) / w) * w + origin;
        int steps = static_cast<int>(std::lround((target - lastAttract) / w));
        for (int i = 0; i < 256 && steps != 0; ++i) {
            attract = lastAttract + (steps > 0 ? w : -w);
            if (attract > lastAttract) { if (pos < hi) { ++pos; lastAttract = attract; atLimit = false; } else { atLimit = true; break; } }
            else { if (pos > lo) { --pos; lastAttract = attract; atLimit = false; } else { atLimit = true; break; } }
            steps += steps > 0 ? -1 : 1;
        }
    }
    float output() {
        const float vel = static_cast<float>(lpf);
        float spring = 0.0f, wallV = 0.0f;
        const float d = static_cast<float>(theta) - lastAttract;
        float pen = 0.0f;
        int outward = 0;
        if (pos >= hi && d > 0.0f) { pen = d; outward = 1; }
        else if (pos <= lo && d < 0.0f) { pen = -d; outward = -1; }
        if (legacy) {
            // haptic.cpp's legacy loop: P 3 on the error clamped to +-w, zero above 30 rad/s, limited to 0.4 A.
            float e = lastAttract - static_cast<float>(theta);
            if (std::fabs(vel) > 30.0f) e = 0.0f;
            e = e > w ? w : (e < -w ? -w : e);
            spring = 3.0f * e;
            spring = spring > 0.4f ? 0.4f : (spring < -0.4f ? -0.4f : spring);
        } else if (pen > 0.0f) {
            wallV = cc_wall_volts(cc_law_slope(p.law, p.kp), pen, w, CC_HAPTIC_CAP_VOLTS * fold.factor());
            spring = -static_cast<float>(outward) * wallV / CC_HAPTIC_PHASE_OHMS;
        } else {
            const bool coast = p.coast && std::fabs(vel) > CC_HAPTIC_COAST_RAD_S;
            spring = coast ? 0.0f : cc_law_spring(p.law, p.kp, lastAttract - static_cast<float>(theta), w);
        }
        fold.step(wallV, 60e-6f);
        float out = spring + (legacy ? 0.0f : cc_damping(p.kd, vel)) + fx.volts(now) / CC_HAPTIC_PHASE_OHMS;
        out = out > CC_HAPTIC_CAP_AMPS ? CC_HAPTIC_CAP_AMPS : (out < -CC_HAPTIC_CAP_AMPS ? -CC_HAPTIC_CAP_AMPS : out);
        if (restEnabled) {
            const bool busy = fx.busy(now);
            if (rest.step(now, static_cast<float>(theta), lastAttract - static_cast<float>(theta), vel, busy,
                          cc_rest_wake_rad(w))) out = 0.0f;
        }
        return out;
    }
    // One 60 us pass; `hand` N m of external torque, or a velocity source when `drive` is set.
    void step(double hand, bool drive = false, double driveOmega = 0.0) {
        const double dt = 60e-6;
        const bool frozen = fx.frozen(now);
        if (frozen && !frozenBefore) freezeStart = theta;
        if (!frozen && frozenBefore) endFreeze();
        frozenBefore = frozen;
        if (!frozen) findDetent();
        float amps = output();
        if (tripEnabled && trip.step(static_cast<float>(lpf), static_cast<float>(dt))) fx.cancel();
        if (trip.latched()) amps = 0.0f;
        lastUq = amps * CC_HAPTIC_PHASE_OHMS;
        const double current = (static_cast<double>(lastUq) - Kt * omega) / CC_HAPTIC_PHASE_OHMS;   // back-EMF
        const double torque = (flip ? -1.0 : 1.0) * Kt * current - friction * omega + hand;
        if (drive) omega = driveOmega;
        else omega += torque / J * dt;
        theta += omega * dt;
        lpf += (omega - lpf) * (dt / (0.01 + dt));
        now += 60;
    }
    void run(double seconds, double hand = 0.0) {
        const int n = static_cast<int>(seconds / 60e-6);
        for (int i = 0; i < n; ++i) step(hand);
    }
};
// ===== END verbatim copy of struct Knob =====

namespace {

// A minimal JSON reader for the spec file (objects, arrays, strings, numbers, true / false / null): the spec is tiny
// and the lead's CMake gives this target only /I <firmware>/src, so no ArduinoJson here.
struct JV {
    enum Kind { NUL, BOOL, NUM, STR, ARR, OBJ } kind = NUL;
    bool b = false;
    double num = 0.0;
    std::string str;
    std::vector<JV> arr;
    std::map<std::string, JV> obj;
    const JV* get(const char* key) const {
        if (kind != OBJ) return nullptr;
        auto it = obj.find(key);
        return it == obj.end() ? nullptr : &it->second;
    }
    double numOr(const char* key, double d) const { const JV* v = get(key); return v && v->kind == NUM ? v->num : d; }
    bool boolOr(const char* key, bool d) const { const JV* v = get(key); return v && v->kind == BOOL ? v->b : d; }
    std::string strOr(const char* key, const char* d) const { const JV* v = get(key); return v && v->kind == STR ? v->str : std::string(d); }
};
struct JParser {
    const std::string& s;
    size_t i = 0;
    bool ok = true;
    explicit JParser(const std::string& text) : s(text) {}
    void ws() { while (i < s.size() && (s[i] == ' ' || s[i] == '\t' || s[i] == '\n' || s[i] == '\r')) ++i; }
    bool lit(const char* w) { const size_t n = std::strlen(w); if (s.compare(i, n, w) == 0) { i += n; return true; } return false; }
    JV value() {
        JV v;
        ws();
        if (i >= s.size()) { ok = false; return v; }
        const char c = s[i];
        if (c == '{') {
            v.kind = JV::OBJ; ++i; ws();
            if (i < s.size() && s[i] == '}') { ++i; return v; }
            while (ok) {
                ws();
                if (i >= s.size() || s[i] != '"') { ok = false; break; }
                const std::string key = string();
                ws();
                if (i >= s.size() || s[i] != ':') { ok = false; break; }
                ++i;
                v.obj[key] = value();
                ws();
                if (i < s.size() && s[i] == ',') { ++i; continue; }
                if (i < s.size() && s[i] == '}') { ++i; break; }
                ok = false;
            }
        } else if (c == '[') {
            v.kind = JV::ARR; ++i; ws();
            if (i < s.size() && s[i] == ']') { ++i; return v; }
            while (ok) {
                v.arr.push_back(value());
                ws();
                if (i < s.size() && s[i] == ',') { ++i; continue; }
                if (i < s.size() && s[i] == ']') { ++i; break; }
                ok = false;
            }
        } else if (c == '"') {
            v.kind = JV::STR; v.str = string();
        } else if (lit("true")) { v.kind = JV::BOOL; v.b = true; }
        else if (lit("false")) { v.kind = JV::BOOL; v.b = false; }
        else if (lit("null")) { v.kind = JV::NUL; }
        else {
            char* end = nullptr;
            v.num = std::strtod(s.c_str() + i, &end);
            if (!end || end == s.c_str() + i) { ok = false; return v; }
            v.kind = JV::NUM; i = static_cast<size_t>(end - s.c_str());
        }
        return v;
    }
    std::string string() {
        std::string out;
        ++i;   // opening quote
        while (i < s.size() && s[i] != '"') {
            if (s[i] == '\\' && i + 1 < s.size()) {
                ++i;
                const char e = s[i];
                out += e == 'n' ? '\n' : (e == 't' ? '\t' : e);
            } else out += s[i];
            ++i;
        }
        if (i >= s.size()) { ok = false; return out; }
        ++i;
        return out;
    }
};

struct Spec {
    std::string mode, feelName;
    uint8_t feel = CC_FEEL_VALUE;
    int detents = 67, lo = 0, hi = 8, pos = 4;
    double spanLo = -40.0, spanHi = 40.0, stepDeg = 0.05;
    bool rest = true;
    std::vector<JV> segments;
};

constexpr double DEG = 180.0 / 3.14159265358979;

std::string esc(const std::string& s) {
    std::string o;
    for (char c : s) { if (c == '"' || c == '\\') o += '\\'; o += c; }
    return o;
}
const char* lawName(uint8_t law) { return law == CC_LAW_SINE ? "SINE" : (law == CC_LAW_VISCOSE ? "VISCOSE" : "SAW"); }

void constants(std::ostringstream& out, const Spec& s, const CCFeelParams& p, double w) {
    out << "  \"feel\": \"" << esc(s.feelName) << "\",\n"
        << "  \"law\": \"" << lawName(p.law) << "\",\n"
        << "  \"kp_a_per_rad\": " << p.kp << ",\n  \"kd_a_per_rad_s\": " << p.kd << ",\n"
        << "  \"detents_per_turn\": " << (p.detents ? p.detents : s.detents) << ",\n"
        << "  \"detent_width_deg\": " << w * DEG << ",\n"
        << "  \"lo\": " << s.lo << ", \"hi\": " << s.hi << ", \"pos\": " << s.pos << ",\n"
        << "  \"constants\": {\"cap_volts\": " << CC_HAPTIC_CAP_VOLTS << ", \"phase_ohms\": " << CC_HAPTIC_PHASE_OHMS
        << ", \"spring_limit_amps\": " << CC_HAPTIC_SPRING_AMPS << ", \"kt_nm_per_a_assumed\": 0.04"
        << ", \"j_kgm2_assumed\": 3.25e-6, \"friction_nms_assumed\": 2e-6, \"pass_us\": 60"
        << ", \"velocity_lpf_s\": 0.01, \"rest_idle_ms\": " << CC_REST_IDLE_MS
        << ", \"damp_deadband_rad_s\": " << CC_HAPTIC_DAMP_DEADBAND << "},\n"
        << "  \"model_note\": \"J, Kt and the viscous friction are assumptions, not measurements (HAPTICS.md "
           "section 10 'Model constants': J 3.25e-6 kg m^2, Kt = Ke 0.04 N m/A, friction 2e-6 N m s). The model "
           "(haptic_fx_tests.cpp struct Knob, lines 267-373) omits the profile's output ramp, feel.fade, hold.tension and "
           "the detent pulses that haptic.cpp token_target() applies (haptic.cpp:595-656); the static trace also omits "
           "the 25 % hysteresis gate of the attractor. Uq is the commanded q voltage before the motor.\",\n";
}

int runStatic(const Spec& s, const std::string& outPath) {
    const CCFeelParams p = cc_feel_params(s.feel, false);
    const int per = p.detents ? p.detents : s.detents;
    const double w = 2.0 * 3.14159265358979 / per;
    const float wf = static_cast<float>(w);
    const float slope = cc_law_slope(p.law, p.kp);
    std::ostringstream out;
    out.precision(6);
    out << "{\n  \"mode\": \"static\",\n";
    constants(out, s, p, w);
    out << "  \"samples\": [";
    int n = 0;
    double peak = 0.0, wallMax = 0.0;
    for (double deg = s.spanLo; deg <= s.spanHi + 1e-9; deg += s.stepDeg, ++n) {
        const double th = deg / DEG;
        long idx = std::lround(th / w);                       // nearest detent centre, relative to `pos`
        if (idx > s.hi - s.pos) idx = s.hi - s.pos;           // clamped at the bounds: the last detent is committed
        if (idx < s.lo - s.pos) idx = s.lo - s.pos;
        const double attract = idx * w;
        const float e = static_cast<float>(attract - th);
        float uq = 0.0f, pen = 0.0f;
        if (idx == s.hi - s.pos && th > attract) {
            pen = static_cast<float>(th - attract);
            uq = -cc_wall_volts(slope, pen, wf, CC_HAPTIC_CAP_VOLTS);
        } else if (idx == s.lo - s.pos && th < attract) {
            pen = static_cast<float>(attract - th);
            uq = cc_wall_volts(slope, pen, wf, CC_HAPTIC_CAP_VOLTS);
        } else {
            uq = cc_law_spring(p.law, p.kp, e, wf) * CC_HAPTIC_PHASE_OHMS;
        }
        if (pen == 0.0f && std::fabs(uq) > peak) peak = std::fabs(uq);
        if (std::fabs(uq) > wallMax) wallMax = std::fabs(uq);
        out << (n ? ",\n    " : "\n    ") << "{\"theta_deg\": " << deg << ", \"uq_volts\": " << uq
            << ", \"pct_of_cap\": " << 100.0 * uq / CC_HAPTIC_CAP_VOLTS << ", \"wall_pen_deg\": " << pen * DEG << "}";
    }
    out << "\n  ],\n  \"summary\": {\"samples\": " << n << ", \"well_peak_volts\": " << peak
        << ", \"max_abs_volts\": " << wallMax << "}\n}\n";
    std::ofstream f(outPath, std::ios::binary);
    f << out.str();
    std::printf("static %s %s %d/turn pos %d of %d..%d: %d samples, well peak %.3f V (%.0f %% of cap), max %.3f V\n",
                s.feelName.c_str(), lawName(p.law), per, s.pos, s.lo, s.hi, n, peak, 100.0 * peak / CC_HAPTIC_CAP_VOLTS, wallMax);
    return 0;
}

int runDynamic(const Spec& s, const std::string& outPath) {
    Knob k;
    k.setFeel(s.feel, s.detents);
    k.lo = s.lo; k.hi = s.hi; k.pos = s.pos;
    k.restEnabled = s.rest;
    const double w = k.w;
    CCSoundCue cue;
    std::ostringstream out;
    out.precision(6);
    out << "{\n  \"mode\": \"dynamic\",\n";
    constants(out, s, k.p, w);
    out << "  \"rest_enabled\": " << (s.rest ? "true" : "false") << ",\n  \"segments\": [";
    uint32_t tMs = 0;
    int n = 0;
    double maxAbs = 0.0;
    uint32_t lastNonZeroMs = 0, driveEndMs = 0;
    std::ostringstream samples;
    samples.precision(6);
    auto sample = [&]() {
        const double uq = k.lastUq;
        const double torque = k.Kt * (uq - k.Kt * k.omega) / CC_HAPTIC_PHASE_OHMS * 1000.0;
        if (std::fabs(uq) > maxAbs) maxAbs = std::fabs(uq);
        if (std::fabs(uq) > 1e-6) lastNonZeroMs = tMs;
        samples << (n ? ",\n    " : "\n    ") << "{\"t_ms\": " << tMs << ", \"theta_deg\": " << k.theta * DEG
                << ", \"pos\": " << k.pos << ", \"uq_volts\": " << uq << ", \"torque_model_mNm\": " << torque
                << ", \"asleep\": " << (k.rest.asleep() ? "true" : "false")
                << ", \"at_limit\": " << (k.atLimit ? "true" : "false") << "}";
        ++n;
    };
    auto runMs = [&](uint32_t ms, bool drive, double omega) {
        for (uint32_t i = 0; i < ms; ++i) {
            sample();
            const uint32_t until = k.now + 1000u;
            while (k.now < until) k.step(0.0, drive, omega);
            ++tMs;
        }
    };
    int segN = 0;
    for (const JV& seg : s.segments) {
        const std::string kind = seg.strOr("kind", "free");
        const uint32_t ms = static_cast<uint32_t>(seg.numOr("ms", 0.0));
        out << (segN++ ? ", " : "") << "{\"kind\": \"" << esc(kind) << "\", \"t_ms\": " << tMs << ", \"ms\": " << ms;
        if (kind == "drive") {
            const double omega = seg.numOr("omega_rad_s", 0.5);
            out << ", \"omega_rad_s\": " << omega << "}";
            runMs(ms, true, omega);
            driveEndMs = tMs;
        } else if (kind == "effect") {
            const std::string token = seg.strOr("token", "confirm.tick");
            uint8_t fx = 0;
            const bool known = cc_fx_parse(token.c_str(), fx);
            const bool started = known && k.fx.start(fx, false, k.now, static_cast<float>(k.lpf), false, cue);
            out << ", \"token\": \"" << esc(token) << "\", \"started\": " << (started ? "true" : "false") << "}";
            if (!known) std::fprintf(stderr, "unknown effect token %s\n", token.c_str());
            runMs(ms, false, 0.0);
        } else {
            out << "}";
            runMs(ms, false, 0.0);
        }
    }
    sample();
    out << "],\n  \"samples\": [" << samples.str() << "\n  ],\n"
        << "  \"summary\": {\"samples\": " << n << ", \"max_abs_volts\": " << maxAbs << ", \"final_pos\": " << k.pos
        << ", \"final_theta_deg\": " << k.theta * DEG << ", \"asleep_at_end\": " << (k.rest.asleep() ? "true" : "false")
        << ", \"last_nonzero_ms\": " << lastNonZeroMs << ", \"drive_end_ms\": " << driveEndMs
        << ", \"rest_sleeps\": " << k.rest.sleeps() << ", \"rest_wakes\": " << k.rest.wakes()
        << ", \"fx_played\": " << k.fx.counters().played << ", \"trip_latched\": " << (k.trip.latched() ? "true" : "false") << "}\n}\n";
    std::ofstream f(outPath, std::ios::binary);
    f << out.str();
    std::printf("dynamic %s %s pos %d -> %d (%d..%d): %d ms, max |Uq| %.3f V, output flat from %u ms (drive ended %u ms), "
                "asleep at end %s, sleeps %u wakes %u, effects %u\n",
                s.feelName.c_str(), lawName(k.p.law), s.pos, k.pos, s.lo, s.hi, n, maxAbs, lastNonZeroMs, driveEndMs,
                k.rest.asleep() ? "yes" : "no", k.rest.sleeps(), k.rest.wakes(), k.fx.counters().played);
    return 0;
}

}  // namespace

int main(int argc, char** argv) {
    if (argc != 3) {
        std::fprintf(stderr, "usage: haptic-trace <spec.json> <out.json>\n");
        return 2;
    }
    std::ifstream in(argv[1], std::ios::binary);
    if (!in) { std::fprintf(stderr, "cannot read %s\n", argv[1]); return 2; }
    std::stringstream buf;
    buf << in.rdbuf();
    const std::string text = buf.str();
    JParser parser(text);
    const JV doc = parser.value();
    if (!parser.ok || doc.kind != JV::OBJ) { std::fprintf(stderr, "spec: not a JSON object\n"); return 2; }
    Spec s;
    s.mode = doc.strOr("mode", "static");
    s.feelName = doc.strOr("feel", "detent.value");
    if (!cc_feel_parse(s.feelName.c_str(), s.feel)) { std::fprintf(stderr, "unknown feel %s\n", s.feelName.c_str()); return 2; }
    s.detents = static_cast<int>(doc.numOr("detents", 67));
    s.lo = static_cast<int>(doc.numOr("lo", 0)); s.hi = static_cast<int>(doc.numOr("hi", 8)); s.pos = static_cast<int>(doc.numOr("pos", 4));
    if (s.detents <= 0 || s.lo > s.hi || s.pos < s.lo || s.pos > s.hi) { std::fprintf(stderr, "bad detents / bounds\n"); return 2; }
    if (const JV* span = doc.get("span_deg")) {
        if (span->kind == JV::ARR && span->arr.size() == 2 && span->arr[0].kind == JV::NUM && span->arr[1].kind == JV::NUM) {
            s.spanLo = span->arr[0].num; s.spanHi = span->arr[1].num;
        }
    }
    s.stepDeg = doc.numOr("step_deg", 0.05);
    if (s.stepDeg <= 0.0) s.stepDeg = 0.05;
    s.rest = doc.boolOr("rest", true);
    if (const JV* segs = doc.get("segments")) { if (segs->kind == JV::ARR) s.segments = segs->arr; }
    if (s.mode == "static") return runStatic(s, argv[2]);
    if (s.mode == "dynamic") return runDynamic(s, argv[2]);
    std::fprintf(stderr, "mode must be static or dynamic\n");
    return 2;
}
