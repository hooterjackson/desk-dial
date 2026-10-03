// Host tests for src/DeviceSettings.cpp (boot_pins_tests.py builds and runs this, MSVC /W4 /WX).
// The whole unit is compiled as shipped (#include "DeviceSettings.cpp" below) against the real ArduinoJson 7.0.2 and
// fakes of Arduino's String / Serial / Stream, SPIFFS and Preferences (boot_pins_tests.py SETTINGS_STUBS); nothing
// below re-implements it. The fake NVS and SPIFFS record every write so the tests can count and tear them.
#include <stdio.h>
#include <string.h>
#include <math.h>
#include <limits>
#include <string>
#include <vector>

#define NANO_FIRMWARE_PUBLIC "2.0.0"          // platformio.ini build flags
#define NANO_FIRMWARE_VERSION "1.0.0-cc5.8"
#include "DeviceSettings.cpp"

// FW-BUG-001: cc_send_note() (src/cc_serial_out.cpp, tested by protocol_pins_tests.py) is recorded here.
static std::vector<std::string> notes;
void cc_send_note(const char* text) { notes.push_back(text); }

static int failures = 0;
static void check(bool condition, const char* what) {
    printf("%s %s\n", condition ? "PASS" : "FAIL", what);
    if (!condition) ++failures;
}

static std::string reply_text() {
    JsonDocument doc;
    JsonObject obj = doc.to<JsonObject>();
    DeviceSettings::getInstance().toJSON(obj);
    std::string out;
    serializeJson(doc, out);
    return out;
}

// ---- FW-SEC-003 -------------------------------------------------------------------------------------------------
static void settings_reply_never_contains_wifi_password() {
    DeviceSettings& s = DeviceSettings::getInstance();
    // A host (or an older configurator) sends credentials: they are not taken.
    JsonDocument in;
    deserializeJson(in, "{\"wifiSsid\":\"net-x\",\"wifiPassword\":\"pw-x-123\",\"deviceOrientation\":2}");
    JsonObject obj = in.as<JsonObject>();
    s = obj;
    std::string out = reply_text();
    check(out.find("wifiPassword") == std::string::npos && out.find("pw-x-123") == std::string::npos,
          "FW-SEC-003: after a settings write with wifiPassword, the reply has neither the key nor the value");
    check(out.find("wifiSsid") == std::string::npos && out.find("net-x") == std::string::npos,
          "FW-SEC-003: nor the SSID");
    check(out.find("\"deviceOrientation\":2") != std::string::npos, "FW-SEC-003: the other settings still apply");

    // A file an earlier configurator saved: loaded without the credentials, and the next save scrubs it.
    fake_spiffs_files()["/device_settings.json"] =
        "{\"debug\":false,\"deviceName\":\"Nano_test\",\"wifiSsid\":\"net-y\",\"wifiPassword\":\"pw-y-456\","
        "\"wifiEnabled\":false,\"ledMaxBrightness\":90}";
    check(s.fromSPIFFS(), "FW-SEC-003: an old settings file loads");
    out = reply_text();
    check(out.find("pw-y-456") == std::string::npos && out.find("wifiPassword") == std::string::npos &&
          out.find("net-y") == std::string::npos,
          "FW-SEC-003: a stored password is never returned by {\"settings\":\"?\"}");
    check(out.find("\"ledMaxBrightness\":90") != std::string::npos, "FW-SEC-003: the file's other settings load");
    check(s.dirty, "FW-SEC-003: a file holding credentials stays dirty after loading");
    check(s.toSPIFFS(), "FW-SEC-003: the next save writes");
    const std::string& file = fake_spiffs_files()["/device_settings.json"];
    check(file.find("pw-y-456") == std::string::npos && file.find("wifiPassword") == std::string::npos &&
          file.find("net-y") == std::string::npos && file.find("\"ledMaxBrightness\":90") != std::string::npos,
          "FW-SEC-003: and the saved file no longer holds them");
    fake_spiffs_files()["/device_settings.json"] = "{\"deviceName\":\"Nano_test\",\"ledMaxBrightness\":80}";
    check(s.fromSPIFFS() && !s.dirty, "FW-SEC-003: a clean file loads clean (no extra flash write)");
}

// ---- FW-BUG-028 -------------------------------------------------------------------------------------------------
static bool same_cal(const MotorCalibration& a, int direction, float zero) {
    return a.direction == direction && a.zero_angle == zero;
}
static bool uncalibrated(const MotorCalibration& a) { return a.direction == 0 && a.zero_angle == NOT_SET; }
static void nvs_reset() {
    nano_preferences.entries.clear(); nano_preferences.writes.clear();
    nano_preferences.fail_puts = 0; nano_preferences.power_cut_after = -1;
}
static void legacy_pair(uint8_t direction, float zero) {
    nano_preferences.putUChar("direction", direction);
    nano_preferences.putFloat("zero_angle", zero);
    nano_preferences.writes.clear();
}
static void put_blob(const CcCalBlob& blob, size_t len = sizeof(CcCalBlob)) {
    nano_preferences.putBytes("cal", &blob, len);
    nano_preferences.writes.clear();
}

static void calibration_is_one_atomic_entry() {
    DeviceSettings& s = DeviceSettings::getInstance();
    const float nan = std::numeric_limits<float>::quiet_NaN();
    const float inf = std::numeric_limits<float>::infinity();

    nvs_reset();
    MotorCalibration cal = { -1, 4.25f };
    check(s.storeCalibration(cal), "FW-BUG-028: a plausible calibration stores (true)");
    check(nano_preferences.writes.size() == 1 && nano_preferences.writes[0] == "cal" &&
          nano_preferences.entries["cal"].size() == sizeof(CcCalBlob),
          "FW-BUG-028: storeCalibration is ONE NVS write, the 12-byte \"cal\" blob");
    check(same_cal(s.loadCalibration(), -1, 4.25f), "FW-BUG-028: and loads back the same direction and zero");

    // The torn-pair scenario: a knob with the old two-key pair recalibrates to the other direction and loses power.
    for (int cut = 0; cut <= 3; ++cut) {
        nvs_reset();
        legacy_pair(1, 1.5f);
        nano_preferences.power_cut_after = cut;
        MotorCalibration fresh = { -1, 5.0f };
        s.storeCalibration(fresh);
        nano_preferences.power_cut_after = -1;
        const MotorCalibration got = s.loadCalibration();
        char what[160];
        snprintf(what, sizeof what, "FW-BUG-028: power cut after %d entry write%s: the next boot loads the old or the new "
                 "pair whole (dir %d, zero %.2f)", cut, cut == 1 ? "" : "s", got.direction, got.zero_angle);
        check(same_cal(got, 1, 1.5f) || same_cal(got, -1, 5.0f), what);
    }
    nvs_reset();
    legacy_pair(1, 1.5f);
    MotorCalibration fresh = { -1, 5.0f };
    check(s.storeCalibration(fresh) && !nano_preferences.isKey("direction") && !nano_preferences.isKey("zero_angle"),
          "FW-BUG-028: a stored blob retires the old two-key pair");

    // A failed put is reported, and the previous calibration stays.
    nvs_reset();
    MotorCalibration old_cal = { 1, 2.0f };
    s.storeCalibration(old_cal);
    nano_preferences.fail_puts = 1;
    MotorCalibration new_cal = { -1, 3.0f };
    check(!s.storeCalibration(new_cal), "FW-BUG-028: a put that writes nothing returns false (CC_CAL_FAIL_SAVE upstream)");
    check(same_cal(s.loadCalibration(), 1, 2.0f), "FW-BUG-028: and the previous calibration still loads");

    nvs_reset();
    MotorCalibration bad[] = { { 0, 1.0f }, { 2, 1.0f }, { 1, nan }, { 1, inf }, { -1, -0.5f }, { 1, 7.0f } };
    bool none = true;
    for (MotorCalibration& b : bad) none &= !s.storeCalibration(b);
    check(none && nano_preferences.writes.empty(), "FW-BUG-028: an implausible calibration is never stored");

    // Damaged or implausible blobs load as uncalibrated (initFOC aligns again).
    nvs_reset();
    CcCalBlob blob = cc_cal_encode(1, 2.5f);
    blob.zero = 2.75f;                                    // payload changed, CRC not
    put_blob(blob);
    check(uncalibrated(s.loadCalibration()), "FW-BUG-028: a CRC mismatch loads as uncalibrated");
    nvs_reset();
    put_blob(cc_cal_encode(1, nan));
    check(uncalibrated(s.loadCalibration()), "FW-BUG-028: a non-finite zero (valid CRC) loads as uncalibrated");
    nvs_reset();
    put_blob(cc_cal_encode(1, inf));
    check(uncalibrated(s.loadCalibration()), "FW-BUG-028: an infinite zero loads as uncalibrated");
    nvs_reset();
    put_blob(cc_cal_encode(3, 1.0f));
    check(uncalibrated(s.loadCalibration()), "FW-BUG-028: a direction other than +-1 loads as uncalibrated");
    nvs_reset();
    put_blob(cc_cal_encode(1, 1.0f), 8);
    check(uncalibrated(s.loadCalibration()), "FW-BUG-028: a short blob loads as uncalibrated");
    nvs_reset();
    blob = cc_cal_encode(1, 1.0f);
    blob.version = 2;
    put_blob(blob);
    check(uncalibrated(s.loadCalibration()), "FW-BUG-028: an unknown blob version loads as uncalibrated");
    nvs_reset();
    legacy_pair(1, 1.5f);
    blob = cc_cal_encode(-1, 2.0f);
    blob.crc ^= 1;
    put_blob(blob);
    check(uncalibrated(s.loadCalibration()), "FW-BUG-028: a damaged blob never falls back to an older two-key pair");

    // Knobs calibrated by older firmware keep their two-key pair (checked the same way).
    nvs_reset();
    legacy_pair(0xFF, 3.5f);
    check(same_cal(s.loadCalibration(), -1, 3.5f), "FW-BUG-028: an older knob's pair (CCW = 0xFF) still loads");
    nvs_reset();
    legacy_pair(7, 3.5f);
    check(uncalibrated(s.loadCalibration()), "FW-BUG-028: an older pair with direction 7 loads as uncalibrated");
    nvs_reset();
    legacy_pair(1, nan);
    check(uncalibrated(s.loadCalibration()), "FW-BUG-028: an older pair with a NaN zero loads as uncalibrated");
    nvs_reset();
    nano_preferences.putUChar("direction", 1);
    nano_preferences.writes.clear();
    check(uncalibrated(s.loadCalibration()), "FW-BUG-028: half an older pair (no zero) loads as uncalibrated");
    nvs_reset();
    check(uncalibrated(s.loadCalibration()), "FW-BUG-028: a new knob loads as uncalibrated");
}

// ---- FW-BUG-001 -------------------------------------------------------------------------------------------------
static bool noted(const char* text) {
    for (const std::string& n : notes) if (n == text) return true;
    return false;
}

static void diagnostics_never_write_serial_directly() {
    DeviceSettings& s = DeviceSettings::getInstance();
    notes.clear();
    fake_serial_raw_writes = 0;
    check(s.init(), "FW-BUG-001: init() mounts");
    check(noted("SPIFFS mounted successfully"), "FW-BUG-001: init() reports through cc_send_note()");
    fake_spiffs_files().erase("/device_settings.json");
    check(s.fromSPIFFS() && noted("Loading settings from SPIFFS...") &&
          noted("Settings not found, default settings used..."),
          "FW-BUG-001: a load with no file reports through cc_send_note()");
    fake_spiffs_files()["/device_settings.json"] = "{not json";
    check(!s.fromSPIFFS() && noted("ERROR: unable to parse settings file!"),
          "FW-BUG-001: a damaged file reports its parse error through cc_send_note()");
    fake_spiffs_files()["/device_settings.json"] = "{\"deviceName\":\"Nano_test\",\"ledMaxBrightness\":80}";
    check(s.fromSPIFFS() && noted("Settings loaded"), "FW-BUG-001: a good load reports through cc_send_note()");
    s.dirty = true;
    check(s.toSPIFFS() && noted("Saving settings to SPIFFS...") && noted("Settings saved"),
          "FW-BUG-001: a save reports through cc_send_note()");
    check(fake_serial_raw_writes == 0, "FW-BUG-001: init / load / save never write Serial directly");
}

int main() {
    nano_preferences.begin("nano_D", false);
    diagnostics_never_write_serial_directly();
    settings_reply_never_contains_wifi_password();
    calibration_is_one_atomic_entry();
    printf("%s: boot_settings_tests (%d failure%s)\n", failures ? "FAIL" : "PASS", failures, failures == 1 ? "" : "s");
    return failures ? 1 : 0;
}
