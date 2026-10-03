// COM protocol host tests (lane F2, protocol_pins_tests.py). Python stdlib + MSVC only.
//
// Links src/cc_serial_out.cpp unchanged against a fake TinyUSB CDC (protocol_pins_tests.py
// writes the Arduino.h stub): a settable FIFO space, a DTR flag, and a simulated clock that
// taskYIELD() / vTaskDelay() advance, so a 250 ms stall costs no real time.
#include <Arduino.h>
#include <ArduinoJson.h>
#include <cstdio>
#include <cstdlib>
#include <map>
#include <string>
#include "cc_serial_out.h"
#include "haptic_bounds.h"   // FW-SEC-001 slot rules for the profile command tests

// ---------------------------------------------------------------------------
// The fake CDC (declared in the Arduino.h stub).
uint64_t g_now_us = 0;
int g_space = 64;
bool g_connected = true;
std::string g_wire;
FakeSerial Serial;

uint32_t millis() { return static_cast<uint32_t>(g_now_us / 1000u); }
uint32_t micros() { return static_cast<uint32_t>(g_now_us); }
void taskYIELD() { g_now_us += 10; }
void vTaskDelay(uint32_t ticks) { g_now_us += 1000u * ticks; }
extern "C" bool tud_cdc_n_connected(uint8_t) { return g_connected; }

int FakeSerial::availableForWrite() { return g_space; }
size_t FakeSerial::write(const uint8_t* data, size_t size) {
    const size_t n = size < static_cast<size_t>(g_space > 0 ? g_space : 0) ? size : static_cast<size_t>(g_space);
    g_wire.append(reinterpret_cast<const char*>(data), n);
    g_space -= static_cast<int>(n);
    return n;
}

namespace {
int failures = 0;
void check(bool ok, const char* what) {
    if (!ok) { ++failures; std::printf("FAIL %s\n", what); }
}
void reset(int space, bool connected = true) { g_space = space; g_connected = connected; g_wire.clear(); }

// ---------------------------------------------------------------------------
// FW-BUG-001: every COM reply goes through the bounded writer, which gives up on a host that
// keeps the port open (DTR high) but stops reading after 250 ms, counting the stall, instead of
// spinning in USBCDC::write() until the task watchdog reboots the knob. A native profile change
// ({"current":...} from handleMessages) is the scenario's reply.
void fw_bug_001_reply_to_a_stalled_host_is_bounded() {
    reset(0);
    JsonDocument doc;
    doc["current"] = "Profile";
    const uint32_t stalls = cc_tx_stalls();
    const uint64_t start = g_now_us;
    cc_send_json(doc);
    const uint64_t took = g_now_us - start;
    check(took >= 250000u && took < 300000u, "FW-BUG-001: a reply to a stalled host returns within 300 ms");
    check(cc_tx_stalls() == stalls + 1, "FW-BUG-001: the cut reply is counted in txStalls");
    check(g_wire.empty(), "FW-BUG-001: nothing reached the full FIFO");
    // The host reads again: the next reply goes out whole (a reply that was dropped whole leaves
    // no open line behind).
    reset(4096);
    cc_send_json(doc);
    check(g_wire == "{\"current\":\"Profile\"}\r\n", "FW-BUG-001: replies flow again once the host reads");
}

// The best-effort note (DeviceSettings / HapticProfileManager diagnostics on the COM task, also
// while it is off the watchdog for a SPIFFS save or load) never waits: whole line or nothing.
void fw_bug_001_note_never_waits() {
    reset(0);
    uint64_t start = g_now_us;
    cc_send_note("Saving settings to SPIFFS...");
    check(g_now_us == start && g_wire.empty(), "FW-BUG-001: a note to a full FIFO is dropped at once");
    reset(10);
    cc_send_note("Saving settings to SPIFFS...");
    check(g_wire.empty() && g_space == 10, "FW-BUG-001: a note that does not fit whole is dropped, not cut");
    reset(64, false);
    cc_send_note("Settings saved");
    check(g_wire.empty(), "FW-BUG-001: no note without a host (DTR low)");
    reset(64);
    start = g_now_us;
    cc_send_note("Settings saved");
    check(g_wire == "Settings saved\r\n" && g_now_us == start, "FW-BUG-001: a note that fits goes out whole");
    reset(4096);
}
}

// ---------------------------------------------------------------------------
// FW-BUG-002: com_thread.cpp's {"profiles":"#all"} branch, compiled verbatim (protocol_pins_tests.py
// cuts it to profiles_all.inc) against a manager with HapticProfileManager's slot rules: remove()
// only blanks the name, operator[](int) is nullptr for a blank slot, size() counts the named ones.
namespace inventory {
#define MAX_PROFILES 10
struct HapticProfile { std::string profile_name; };
struct Manager {
    HapticProfile profiles[MAX_PROFILES];
    HapticProfile* current = nullptr;
    HapticProfile* operator[](int index) {
        if (index < 0 || index >= MAX_PROFILES || profiles[index].profile_name.empty()) return nullptr;
        return &profiles[index];
    }
    int size() { int n = 0; for (auto& p : profiles) n += !p.profile_name.empty(); return n; }
    HapticProfile* getCurrentProfile() { return current; }
    void add(const char* name) { for (auto& p : profiles) if (p.profile_name.empty()) { p.profile_name = name; return; } }
    void remove(const char* name) { for (auto& p : profiles) if (p.profile_name == name) { p.profile_name.clear(); return; } }
};
std::string sent;
void cc_send_json(const JsonDocument& doc) { sent.clear(); serializeJson(doc, sent); }
void list_all(Manager& pm) {
#include "profiles_all.inc"
}
#undef MAX_PROFILES

void test_all_listing_survives_a_deleted_first_slot() {
    Manager pm;
    pm.add("A"); pm.add("B"); pm.add("C");
    pm.current = pm[1];
    pm.remove("A");                        // {"profiles":["B","C"]}: slot 0 blank, B and C stay in 1..2
    list_all(pm);                          // the old loop read pm[0]->profile_name: a null dereference
    check(sent == "{\"profiles\":[\"B\",\"C\"],\"current\":\"B\"}", "FW-BUG-002: #all lists B and C after A's slot was blanked");
    // A hole in the middle no longer hides the profiles stored after it.
    pm.add("D");                           // reuses slot 0
    pm.remove("B");
    pm.current = pm[2];
    list_all(pm);
    check(sent == "{\"profiles\":[\"D\",\"C\"],\"current\":\"C\"}",
          "FW-BUG-002: a hole in the middle hides nothing after it");
}
}

// ---------------------------------------------------------------------------
// FW-RES-002: ComThread::put_string_message, compiled verbatim (put_string_message.inc) against a
// 5-deep queue like _q_strings_in and a String that counts its live instances. The queue owns a
// queued message's String (handleMessages() deletes it); a full queue must not leak it.
namespace strings {
typedef uint32_t TickType_t;
const int pdTRUE = 1, pdFALSE = 0;
int live = 0;
struct String {
    explicit String(const char*) { ++live; }
    ~String() { --live; }
};
struct StringMessage { String* message; int type; };
struct Queue { StringMessage items[5]; int count = 0; };
int xQueueSend(Queue* queue, const void* item, TickType_t) {
    if (queue->count == 5) return pdFALSE;
    queue->items[queue->count++] = *static_cast<const StringMessage*>(item);
    return pdTRUE;
}
Queue strings_in;
Queue* _q_strings_in = &strings_in;
void put_string_message(const StringMessage& msg) {
#include "put_string_message.inc"
}

void test_full_queue_does_not_leak() {
    // 1000 FOC replies ({"R":...} answers) and debug lines while the COM task is not draining.
    for (int i = 0; i < 1000; ++i) put_string_message(StringMessage{new String("r1=2"), 2});
    check(strings_in.count == 5, "FW-RES-002: the queue keeps its 5 messages");
    check(live == 5, "FW-RES-002: only the queued Strings stay allocated (no leak per dropped message)");
    put_string_message(StringMessage{nullptr, 4});   // a NEXT_PROFILE message carries no String
    for (int i = 0; i < strings_in.count; ++i) delete strings_in.items[i].message;   // handleMessages()
    strings_in.count = 0;
    check(live == 0, "FW-RES-002: nothing left after the queue is drained");
}
}

// ---------------------------------------------------------------------------
// FW-BUG-006: com_thread.cpp's lcd_text(), compiled verbatim (lcd_text.inc): the COM task copies the
// screen command's and the profile's text into the LcdCommand, NUL-terminated, cut at a UTF-8
// character boundary, so the LCD task owns what it reads.
namespace lcdtext {
#include "lcd_text.inc"

void test_lcd_command_owns_its_text() {
    char title[8];
    std::string source = "Title";
    lcd_text(title, source.c_str());
    source[0] = 'X';                                   // the COM task reassigns its String later
    check(std::string(title) == "Title", "FW-BUG-006: the command keeps its own copy of the text");
    lcd_text(title, nullptr);
    check(title[0] == 0, "FW-BUG-006: a missing field is empty");
    lcd_text(title, "ABCDEFGHIJ");
    check(std::string(title) == "ABCDEFG", "FW-BUG-006: long text is cut to the field, NUL-terminated");
    lcd_text(title, "ABCDE\xC3\xA9" "Z");               // e-acute at bytes 5..6 fits the 7-byte field
    check(std::string(title) == "ABCDE\xC3\xA9", "FW-BUG-006: a character that fits whole is kept");
    lcd_text(title, "ABCDEF\xC3\xA9");                 // its second byte would be the 8th: dropped whole
    check(std::string(title) == "ABCDEF", "FW-BUG-006: no split UTF-8 character");
}
}

// ---------------------------------------------------------------------------
// FW-BUG-004: one handleEvents() pass behind a host that keeps DTR high but stopped reading, while the
// user keeps turning: the FOC task queues a position every 200 ms (5-deep queue). The pass drains at
// most com_thread.cpp's caps (event_caps.inc, verbatim) through the real cc_send_json, and must end
// well inside the 10 s task watchdog; every dropped line is counted in txStalls.
namespace drain {
#include "event_caps.inc"

void test_tx_stall_event_drain_is_bounded() {
    reset(0);
    int queued = 5;                                    // a full angle queue
    uint64_t refilled = g_now_us;
    const uint32_t stalls = cc_tx_stalls();
    const uint64_t start = g_now_us;
    int sent = 0;
    for (uint8_t budget = kAngleEventsPerPass; budget > 0 && queued > 0; --budget) {
        --queued;
        JsonDocument doc;
        doc["p"] = sent;
        cc_send_json(doc);
        ++sent;
        while (g_now_us - refilled >= 200000u) { refilled += 200000u; if (queued < 5) ++queued; }
    }
    const uint64_t took = g_now_us - start;
    check(took < 2000000u, "FW-BUG-004: one drain pass behind a stalled host ends within 2 s");
    check(took < 300000u, "FW-BUG-004: the pass costs one 250 ms stall, not one per line");
    check(cc_tx_stalls() - stalls == static_cast<uint32_t>(sent), "FW-BUG-004: every dropped line is counted in txStalls");
    check(kKeyEventsPerPass <= 16 && kAngleEventsPerPass <= 5, "FW-BUG-004: at most one full queue of each kind per pass");
    // Even with every reply waiting the full 250 ms (no latch), the capped pass ends inside the watchdog.
    check((kKeyEventsPerPass + kAngleEventsPerPass) * 250u < 10000u, "FW-BUG-004: the caps bound a pass below 10 s");
    // The host reads again: the latch clears on the first reply that finds room, which goes out whole.
    reset(4096);
    JsonDocument doc;
    doc["p"] = 7;
    cc_send_json(doc);
    check(g_wire == "{\"p\":7}\r\n", "FW-BUG-004: replies flow again once the FIFO has room");
    // DTR low (host gone) clears it too, uncounted.
    reset(0);
    cc_send_json(doc);                                 // stalls: latched
    reset(0, false);
    const uint32_t before = cc_tx_stalls();
    cc_send_json(doc);
    check(cc_tx_stalls() == before, "FW-BUG-004: no host: dropped uncounted");
    reset(4096);
    cc_send_json(doc);
    check(g_wire == "{\"p\":7}\r\n", "FW-BUG-004: a reconnected host gets the next reply");
}
}

// ---------------------------------------------------------------------------
// FW-BUG-006 (review): com_thread.cpp's {"profiles":[...]} branch, compiled verbatim
// (profiles_array.inc) against a manager whose remove() follows FW-SEC-001 (the current profile
// moves to the next named slot, wrapping; with none left it stays on the blanked slot). The LCD
// keeps copies of the name and description, so deleting the current profile must re-dispatch
// every config, in setCurrentProfile()'s order; deleting another profile must not.
namespace removal {
#define MAX_PROFILES 10
typedef std::string String;
struct HapticProfile { std::string profile_name; };
struct Manager {
    HapticProfile profiles[MAX_PROFILES];
    HapticProfile* current = nullptr;
    HapticProfile* operator[](int index) {
        if (index < 0 || index >= MAX_PROFILES || profiles[index].profile_name.empty()) return nullptr;
        return &profiles[index];
    }
    HapticProfile* getCurrentProfile() { return current; }
    void add(const char* name) { for (auto& p : profiles) if (p.profile_name.empty()) { p.profile_name = name; return; } }
    void remove(const std::string& name) {
        for (int i = 0; i < MAX_PROFILES; ++i) {
            if (profiles[i].profile_name != name) continue;
            profiles[i].profile_name.clear();
            if (current == &profiles[i]) {
                for (int k = 1; k <= MAX_PROFILES; ++k) {
                    const int j = (i + k) % MAX_PROFILES;
                    if (!profiles[j].profile_name.empty()) { current = &profiles[j]; break; }
                }
            }
            return;
        }
    }
};
std::string dispatched;
std::string lcd_title;
Manager* manager = nullptr;
void cc_send_line(const char*) {}
void dispatchHapticConfig() { dispatched += "H"; }
void dispatchLedConfig() { dispatched += "L"; }
void dispatchHmiConfig() { dispatched += "M"; }
void dispatchAudioConfig() { dispatched += "A"; }
void dispatchLcdConfig() { dispatched += "D"; lcd_title = manager->getCurrentProfile()->profile_name; }
#pragma warning(push)
#pragma warning(disable : 4018 4389 4456 4457 4458 4459)
void apply(Manager& pm, JsonVariant p) {
#include "profiles_array.inc"
}
#pragma warning(pop)
#undef MAX_PROFILES

void run(Manager& pm, const char* json) {
    JsonDocument doc;
    deserializeJson(doc, json);
    dispatched.clear();
    apply(pm, doc["profiles"]);
}

void test_deleting_the_current_profile_redispatches() {
    Manager pm;
    manager = &pm;
    pm.add("A"); pm.add("B"); pm.add("C");
    pm.current = pm[1];
    lcd_title = "B";
    run(pm, "{\"profiles\":[\"A\",\"C\"]}");
    check(pm.current == pm[2], "FW-BUG-006 review: deleting the current profile makes the next one current");
    check(dispatched == "HLMAD", "FW-BUG-006 review: deleting the current profile re-dispatches haptic, LED, HMI, audio and LCD");
    check(lcd_title == "C", "FW-BUG-006 review: the knob screen shows the new current profile, not the deleted one");
    run(pm, "{\"profiles\":[\"C\"]}");
    check(dispatched.empty(), "FW-BUG-006 review: deleting another profile dispatches nothing");
    manager = nullptr;
}

// FW-SEC-001: a list that keeps no existing profile is refused whole, so the current profile never lands on a
// blank slot ('#all' would answer current:"" and Desk Dial refuses that inventory).
void test_list_that_keeps_no_profile_is_refused() {
    Manager pm;
    manager = &pm;
    pm.add("A"); pm.add("B");
    pm.current = pm[0];
    lcd_title = "A";
    run(pm, "{\"profiles\":[]}");
    check(dispatched.empty() && pm[0] && pm[1] && pm.current == pm[0] && pm.current->profile_name == "A",
          "FW-SEC-001: {\"profiles\":[]} deletes nothing and keeps the current profile");
    run(pm, "{\"profiles\":[\"X\",\"\",7]}");
    check(dispatched.empty() && pm[0] && pm[1] && pm.current == pm[0],
          "FW-SEC-001: a list naming no existing profile deletes nothing");
    run(pm, "{\"profiles\":[\"B\",\"X\"]}");
    check(!pm[0] && pm[1] && pm.current == pm[1] && dispatched == "HLMAD" && lcd_title == "B",
          "FW-SEC-001: a list keeping one profile still deletes the rest and moves current to a named slot");
    check(!pm.current->profile_name.empty(), "FW-SEC-001: current always names a profile after a delete");
    manager = nullptr;
}
}

// ---------------------------------------------------------------------------
// FW-BUG-005 / FW-BUG-027 / FW-SEC-004: com_thread.cpp's isProfileNameOk(), handleProfileCommand() and
// {"save":true} branch, compiled verbatim (profile_name_ok.inc, profile_command.inc, profile_save.inc) against a
// profile manager with HapticProfileManager's slot rules and a SPIFFS that, like the knob's
// (CONFIG_SPIFFS_OBJ_NAME_LEN 32), cannot open a path longer than 31 characters. toSPIFFS() leaves a profile it
// could not write dirty, exactly as HapticProfileManager::toSPIFFS() does.
namespace profilecmd {
#define MAX_PROFILES 10
typedef std::string String;
std::map<std::string, std::string> flash;            // path -> stored profile name
bool fail_writes = false;
bool settings_ok = true;
std::string stored_current;
bool open_for_write(const std::string& path) { return !fail_writes && path.size() <= 31; }

struct HapticProfile {
    std::string profile_name;
    bool dirty = false;
    void toJSON(JsonObject& obj) { obj["name"] = profile_name; }
    HapticProfile& operator=(JsonObject& obj) {          // HapticProfile::operator=: FW-SEC-001's rename rule
        if (obj["name"].is<String>() && haptic_profile_name_ok(obj["name"].as<String>())) profile_name = obj["name"].as<String>();
        dirty = true;
        return *this;
    }
};
struct HapticProfileManager {
    HapticProfile profiles[MAX_PROFILES];
    HapticProfile* current = nullptr;
    static HapticProfileManager& getInstance() { static HapticProfileManager instance; return instance; }
    HapticProfile* operator[](const String& name) {
        const int i = haptic_profile_find(profiles, MAX_PROFILES, name);
        return i >= 0 ? &profiles[i] : nullptr;
    }
    HapticProfile* operator[](int index) {
        if (index < 0 || index >= MAX_PROFILES || profiles[index].profile_name.empty()) return nullptr;
        return &profiles[index];
    }
    HapticProfile* add(const String& name) {
        if (name.empty()) return nullptr;
        for (auto& p : profiles) if (p.profile_name.empty()) { p = HapticProfile(); p.profile_name = name; p.dirty = true; return &p; }
        return nullptr;
    }
    int size() { int n = 0; for (auto& p : profiles) n += !p.profile_name.empty(); return n; }
    HapticProfile* getCurrentProfile() { return current; }
    void toSPIFFS() {
        for (auto it = flash.begin(); it != flash.end();)   // FW-BUG-038: a file no live profile owns is removed
            it = (*this)[it->second] ? std::next(it) : flash.erase(it);
        for (auto& p : profiles) {
            if (p.profile_name.empty() || !p.dirty) continue;
            const std::string path = "/profiles/" + p.profile_name + ".json";
            if (open_for_write(path)) { flash[path] = p.profile_name; p.dirty = false; }
        }
    }
    void power_cycle() {                                // fromSPIFFS() after a reboot: only what reached flash
        for (auto& p : profiles) p = HapticProfile();
        int i = 0;
        for (auto& entry : flash) profiles[i++].profile_name = entry.second;
        current = (*this)[stored_current];
    }
    void reset() { for (auto& p : profiles) p = HapticProfile(); current = nullptr; flash.clear(); }
};
struct DeviceSettings {
    static DeviceSettings& getInstance() { static DeviceSettings instance; return instance; }
    bool toSPIFFS() { return settings_ok; }
    void storeCurrentProfile(const String& name) { stored_current = name; }
};
enum { CC_LIVE_COM = 1 };
void cc_wdt_unwatch(int) {}
void cc_wdt_watch(int) {}
std::string sent;
void cc_send_json(const JsonDocument& doc) { sent.clear(); serializeJson(doc, sent); }
#include "profile_name_limit.inc"

#pragma warning(push)
#pragma warning(disable : 4018 4100 4189 4389 4456 4457 4458 4459)
struct ComThread {
    std::string error;
    int dispatched = 0;
    void sendError(const char* e, const char* msg = nullptr) { error = e; (void)msg; sent = std::string("{\"error\":\"") + e + "\"}"; }
    void sendError(const char* e, String& msg) { sendError(e, msg.c_str()); }
    void dispatchHapticConfig() { ++dispatched; }
    void dispatchAudioConfig() { ++dispatched; }
    void dispatchLedConfig() { ++dispatched; }
    void dispatchHmiConfig() { ++dispatched; }
    void dispatchLcdConfig() { ++dispatched; }
    bool isProfileNameOk(String& name)
#include "profile_name_ok.inc"
    void handleProfileCommand(JsonVariant profile, JsonVariant updates)
#include "profile_command.inc"
    void save() {
#include "profile_save.inc"
    }
};
#pragma warning(pop)
#undef MAX_PROFILES

ComThread com;
void run(const std::string& json) {
    JsonDocument doc;
    deserializeJson(doc, json);
    com.error.clear();
    sent.clear();
    com.handleProfileCommand(doc["profile"], doc["updates"]);
}
void save() { sent.clear(); com.save(); }
HapticProfileManager& fresh() {
    HapticProfileManager& pm = HapticProfileManager::getInstance();
    pm.reset();
    fail_writes = false; settings_ok = true; stored_current.clear();
    pm.add("Default Profile");
    pm.current = pm[0];
    pm.toSPIFFS();
    stored_current = "Default Profile";
    return pm;
}

void test_profile_name_fits_spiffs_path() {
    HapticProfileManager& pm = fresh();
    const std::string n16(16, 'S'), n17(17, 'L');
    run("{\"profile\":\"" + n17 + "\",\"updates\":{\"detentCount\":3}}");
    check(com.error == "Invalid profile name" && pm[n17] == nullptr && pm.size() == 1,
          "FW-BUG-005: a 17-byte profile name is refused (its /profiles/<name>.json path does not fit SPIFFS)");
    std::string accented;
    for (int i = 0; i < 9; ++i) accented += "\xC3\xA9";   // 9 characters, 18 bytes
    run("{\"profile\":\"" + accented + "\",\"updates\":{}}");
    check(com.error == "Invalid profile name" && pm.size() == 1, "FW-BUG-005: the limit counts UTF-8 bytes");
    run("{\"profile\":\"" + n16 + "\",\"updates\":{\"detentCount\":3}}");
    check(com.error.empty() && pm[n16] != nullptr, "FW-BUG-005: a 16-byte name is accepted");
    save();
    check(sent == "{\"saved\":true}", "FW-BUG-005: saving a 16-byte profile answers saved:true");
    pm.power_cycle();
    check(pm[n16] != nullptr, "FW-BUG-005: the 16-byte profile is there after a power cycle");
    // A rename to a name that cannot be stored is refused before the profile changes.
    run("{\"profile\":\"" + n16 + "\",\"updates\":{\"name\":\"" + n17 + "\"}}");
    check(com.error == "Invalid profile name" && pm[n16] != nullptr && pm[n17] == nullptr,
          "FW-BUG-005: a rename to a 17-byte name is refused and the profile keeps its name");
    // A write that fails is reported, not answered saved:true.
    run("{\"profile\":\"" + n16 + "\",\"updates\":{\"detentCount\":4}}");
    fail_writes = true;
    save();
    check(sent == "{\"saved\":false,\"error\":\"Could not save every profile\",\"unsaved\":1}",
          "FW-BUG-005: a profile that could not be written answers saved:false");
    settings_ok = false;
    fail_writes = false;
    save();
    check(sent == "{\"saved\":false,\"error\":\"Could not save the settings\"}",
          "FW-BUG-005: settings that could not be written answer saved:false");
    settings_ok = true;
    // A new current profile that never reached flash is not stored as the current one.
    run("{\"profile\":\"Fresh\",\"updates\":{}}");
    pm.current = pm[std::string("Fresh")];
    fail_writes = true;
    save();
    check(stored_current == "Default Profile", "FW-BUG-005: the stored current profile never names a profile that is not on flash");
    fail_writes = false;
    save();
    check(sent == "{\"saved\":true}" && stored_current == "Fresh", "FW-BUG-005: once written, it is stored as current");
}

// FW-SEC-004: {"profile":name} is read-only inventory (allowed while claimed). Ten queries for unknown names used to
// fill every slot, and the next {"save":true} wrote them all to flash.
void test_profile_read_of_unknown_name_creates_nothing() {
    HapticProfileManager& pm = fresh();
    for (int i = 0; i < 12; ++i) {
        run("{\"profile\":\"Probe" + std::to_string(i) + "\"}");
        check(com.error == "Unknown profile", "FW-SEC-004: a read of an unknown profile answers an error");
    }
    check(pm.size() == 1, "FW-SEC-004: reads of unknown names create no profile");
    run("{\"profile\":\"Default Profile\"}");
    check(com.error.empty() && sent == "{\"profile\":{\"name\":\"Default Profile\"}}",
          "FW-SEC-004: a read of a known profile still answers it");
    run("{\"profile\":\"Made\",\"updates\":{\"detentCount\":3}}");
    check(com.error.empty() && pm[std::string("Made")] != nullptr && pm.size() == 2,
          "FW-SEC-004: a request with updates still creates the profile");
}

// FW-BUG-027: a rename through updates.name obeys the profile-name rule before anything changes. {"updates":{"name":""}}
// blanked the current profile's slot (a free slot to the manager) and {"save":true} then deleted its file.
void test_profile_rename_validates_name() {
    HapticProfileManager& pm = fresh();
    const std::string before = pm.current->profile_name;
    const char* bad[] = {"", "a/b", "../x", "tab\\there", "nul\\u0000x", "del\\u007f"};
    for (const char* name : bad) {
        run(std::string("{\"updates\":{\"name\":\"") + name + "\",\"detentCount\":9}}");
        check(com.error == "Invalid profile name" && pm.current->profile_name == before && !pm.current->dirty,
              "FW-BUG-027: a rename to an unusable name is refused before the profile changes");
    }
    run("{\"profile\":\"a/b\",\"updates\":{}}");
    check(com.error == "Invalid profile name" && pm.size() == 1, "FW-BUG-027: a new profile named with '/' is refused");
    run("{\"updates\":{\"name\":\"Renamed\"}}");
    check(com.error.empty() && pm.current->profile_name == "Renamed", "FW-BUG-027: a usable rename still applies");
    run("{\"updates\":{\"desc\":\"" + std::string(51, 'd') + "\"}}");
    check(com.error == "Invalid profile description", "FW-BUG-027: a description over 50 bytes is refused");
    run("{\"updates\":{\"profileTag\":\"" + std::string(21, 't') + "\"}}");
    check(com.error == "Invalid profile tag", "FW-BUG-027: a tag over 20 bytes is refused");
    run("{\"updates\":{\"desc\":\"" + std::string(50, 'd') + "\",\"profileTag\":\"" + std::string(20, 't') + "\"}}");
    check(com.error.empty(), "FW-BUG-027: a 50-byte description and a 20-byte tag are kept");
    save();
    pm.power_cycle();
    check(pm[std::string("Renamed")] != nullptr && pm.size() == 1, "FW-BUG-027: the renamed profile survives save and reboot");
}

// FW-BUG-027 review: a profile already on flash under a name the current rule refuses (older firmware wrote
// "/profiles/a/b.json" to the flat SPIFFS) stays readable, so Desk Dial can still read every #all name and connect.
// Creating or renaming to such a name is still refused.
void test_legacy_profile_name_stays_readable() {
    HapticProfileManager& pm = fresh();
    pm.add("a/b");
    pm.add("ctl\x01x");
    pm.toSPIFFS();
    pm.power_cycle();
    check(pm[std::string("a/b")] != nullptr && pm.size() == 3, "FW-BUG-027 review: the legacy profiles load after a reboot");
    run("{\"profile\":\"a/b\"}");
    check(com.error.empty() && sent == "{\"profile\":{\"name\":\"a/b\"}}",
          "FW-BUG-027 review: a read of an on-flash profile named with '/' answers the profile");
    run("{\"profile\":\"ctl\\u0001x\"}");
    if (sent.rfind("{\"profile\":{\"name\":\"ctl", 0) != 0) std::printf("  sent: %s\n", sent.c_str());
    check(com.error.empty() && sent.rfind("{\"profile\":{\"name\":\"ctl", 0) == 0,
          "FW-BUG-027 review: a read of an on-flash profile named with a control character answers the profile");
    run("{\"profile\":\"a/b\",\"updates\":{\"detentCount\":5}}");
    check(com.error.empty() && pm.size() == 3, "FW-BUG-027 review: an existing legacy profile can still be updated");
    run("{\"profile\":\"c/d\",\"updates\":{\"detentCount\":5}}");
    check(com.error == "Invalid profile name" && pm[std::string("c/d")] == nullptr && pm.size() == 3,
          "FW-BUG-027 review: creating a profile named with '/' is still refused");
    run("{\"profile\":\"c/d\"}");
    check(com.error == "Unknown profile" && pm.size() == 3, "FW-BUG-027 review: a read of an unknown bad name creates nothing");
    run("{\"profile\":\"Default Profile\",\"updates\":{\"name\":\"e/f\"}}");
    check(com.error == "Invalid profile name" && pm[std::string("Default Profile")] != nullptr && pm[std::string("e/f")] == nullptr,
          "FW-BUG-027 review: renaming to a name with '/' is still refused");
}
}

int main() {
    removal::test_deleting_the_current_profile_redispatches();
    removal::test_list_that_keeps_no_profile_is_refused();
    fw_bug_001_reply_to_a_stalled_host_is_bounded();
    fw_bug_001_note_never_waits();
    inventory::test_all_listing_survives_a_deleted_first_slot();
    strings::test_full_queue_does_not_leak();
    lcdtext::test_lcd_command_owns_its_text();
    drain::test_tx_stall_event_drain_is_bounded();
    profilecmd::test_profile_name_fits_spiffs_path();
    profilecmd::test_profile_read_of_unknown_name_creates_nothing();
    profilecmd::test_profile_rename_validates_name();
    profilecmd::test_legacy_profile_name_stays_readable();
    if (failures) { std::printf("protocol_tests: %d failure(s)\n", failures); return 1; }
    std::printf("protocol_tests: PASS\n");
    return 0;
}
