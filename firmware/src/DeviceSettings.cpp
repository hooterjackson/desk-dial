
#include "./DeviceSettings.h"
#include <Arduino.h>
#include "nanofoc_d.h"
#include "cc_fw_version.h"
#include "cc_cal_blob.h"
#include "cc_serial_out.h"
#include "SPIFFS.h"
#include <Preferences.h>
#include <common/foc_utils.h>

#define DEVICE_SETTINGS_FILE "/device_settings.json"


// global singleton instance
DeviceSettings DeviceSettings::instance = DeviceSettings();

Preferences nano_preferences; 


DeviceSettings& DeviceSettings::getInstance() {
    return instance;
};



DeviceSettings::DeviceSettings() {
    // default settings
    debug = false;
    ledMaxBrightness = DEFAULT_LED_MAX_BRIGHTNESS;
    maxVelocity = 10.0;
    maxVoltage = 5.0;
    deviceOrientation = 1;
    serialNumber = String(ESP.getEfuseMac(), HEX);
    deviceName = "Nano_" + serialNumber;
    firmwareVersion = String(cc_fw_version());   // FW-PUB-004: "<public>+<build id>.<binary>"
    midiUsb = midiSettings();
    midi2 = midiSettings();
    dirty = true;
    wifiEnabled = false;
    midi_sysex_id = 0x00;
    idleTimeout = 10000;
};


DeviceSettings::~DeviceSettings() {
    // nothing to do here
};


DeviceSettings& DeviceSettings::operator=(JsonObject& obj){
    if (obj["debug"]!=nullptr)
        debug = obj["debug"].as<bool>();
    if (obj["ledMaxBrightness"]!=nullptr)
        ledMaxBrightness = obj["ledMaxBrightness"].as<uint8_t>();
    if (obj["maxVelocity"]!=nullptr)
        maxVelocity = obj["maxVelocity"].as<float>();
    if (obj["maxVoltage"]!=nullptr)
        maxVoltage = obj["maxVoltage"].as<float>();
    if (obj["deviceOrientation"].is<uint16_t>())
        deviceOrientation = obj["deviceOrientation"].as<uint16_t>();
    if (obj["deviceName"]!=nullptr)
        deviceName = obj["deviceName"].as<String>();
    // FW-SEC-003: the knob has no Wi-Fi. "wifiSsid" / "wifiPassword" are neither accepted nor kept (an older
    // configurator stored them in clear text); fromSPIFFS() drops them from the file at the next save.
    if (obj["wifiEnabled"]!=nullptr)
        wifiEnabled = obj["wifiEnabled"].as<bool>();
    if (obj["midiUsb"]!=nullptr) {
        JsonObject midiUsbObj = obj["midiUsb"].as<JsonObject>();
        if (midiUsbObj["in"]!=nullptr)
            midiUsb.in = midiUsbObj["in"].as<bool>();
        if (midiUsbObj["out"]!=nullptr)
            midiUsb.out = midiUsbObj["out"].as<bool>();
        if (midiUsbObj["thru"]!=nullptr)
            midiUsb.thru = midiUsbObj["thru"].as<bool>();
        if (midiUsbObj["route"]!=nullptr)
            midiUsb.route = midiUsbObj["route"].as<bool>();
        if (midiUsbObj["nano"]!=nullptr)
            midiUsb.nano = midiUsbObj["nano"].as<bool>();
    }
    if (obj["midi2"]!=nullptr) {
        JsonObject midi2Obj = obj["midi2"].as<JsonObject>();
        if (midi2Obj["in"]!=nullptr)
            midi2.in = midi2Obj["in"].as<bool>();
        if (midi2Obj["out"]!=nullptr)
            midi2.out = midi2Obj["out"].as<bool>();
        if (midi2Obj["thru"]!=nullptr)
            midi2.thru = midi2Obj["thru"].as<bool>();
        if (midi2Obj["route"]!=nullptr)
            midi2.route = midi2Obj["route"].as<bool>();
        if (midi2Obj["nano"]!=nullptr)
            midi2.nano = midi2Obj["nano"].as<bool>();
    }
    if (obj["sysexId"].is<uint8_t>())
        midi_sysex_id = obj["sysexId"].as<uint8_t>();
    if (obj["idleTimeout"].is<uint32_t>())
        idleTimeout = obj["idleTimeout"].as<uint32_t>();
    dirty = true;
    return *this;
};



void DeviceSettings::toJSON(JsonObject& obj){
    obj["debug"] = debug;
    obj["ledMaxBrightness"] = ledMaxBrightness;
    obj["maxVelocity"] = maxVelocity;
    obj["maxVoltage"] = maxVoltage;
    obj["deviceOrientation"] = deviceOrientation;
    obj["deviceName"] = deviceName;

    // FW-SEC-003: no Wi-Fi credentials, ever (this is both the settings reply and the SPIFFS file).
    obj["wifiEnabled"] = wifiEnabled;

    obj["serialNumber"] = serialNumber;
    obj["firmwareVersion"] = firmwareVersion;
    JsonObject midiUsbObj = obj["midiUsb"].to<JsonObject>();
    midiUsbObj["in"] = midiUsb.in;
    midiUsbObj["out"] = midiUsb.out;
    midiUsbObj["thru"] = midiUsb.thru;
    midiUsbObj["route"] = midiUsb.route;
    midiUsbObj["nano"] = midiUsb.nano;
    JsonObject midi2Obj = obj["midi2"].to<JsonObject>();
    midi2Obj["in"] = midi2.in;
    midi2Obj["out"] = midi2.out;
    midi2Obj["thru"] = midi2.thru;
    midi2Obj["route"] = midi2.route;
    midi2Obj["nano"] = midi2.nano;
    obj["sysexId"] = midi_sysex_id;
    obj["idleTimeout"] = idleTimeout;
};



bool DeviceSettings::toSPIFFS(){
    // note: called from the comms thread (off the task watchdog): diagnostics go through cc_send_note(), which never waits (FW-BUG-001).
    if (dirty) {
        cc_send_note("Saving settings to SPIFFS...");
        File file = SPIFFS.open(DEVICE_SETTINGS_FILE, "w");
        if (!file) {
            cc_send_note("ERROR: unable to open settings file!");
            return false;
        }
        // create the JSON
        JsonDocument doc;
        JsonObject obj = doc.to<JsonObject>();
        toJSON(obj);
        // write the JSON to the file
        serializeJson(doc, file);
        file.close();
        cc_send_note("Settings saved");
        dirty = false;
    }
    return true;
};


bool DeviceSettings::fromSPIFFS(){
    // note: called from setup() in main.cpp, or from the comms thread: diagnostics use cc_send_note(), which never waits (FW-BUG-001).
    cc_send_note("Loading settings from SPIFFS...");
    if (SPIFFS.exists(DEVICE_SETTINGS_FILE)) {
        File file = SPIFFS.open(DEVICE_SETTINGS_FILE, "r");
        if (!file) {
            cc_send_note("ERROR: unable to open settings file!");
            return false;
        }
        // parse the JSON
        JsonDocument doc;
        DeserializationError error = deserializeJson(doc, file);
        if (error) {
            cc_send_note("ERROR: unable to parse settings file!");
            return false;
        }
        // update the settings
        JsonObject obj = doc.as<JsonObject>();
        *this = obj;
        cc_send_note("Settings loaded");
        // FW-SEC-003: a file that still holds Wi-Fi credentials stays dirty, so the next save rewrites it without them.
        dirty = obj["wifiSsid"] != nullptr || obj["wifiPassword"] != nullptr;
    }
    else {
        cc_send_note("Settings not found, default settings used...");
    }
    return true;
};


bool DeviceSettings::init() {
    if (!nano_preferences.begin("nano_D", false)) {
        cc_send_note("ERROR: unable to open Preferences!");
        return false;
    }
    if (SPIFFS.begin(true)) {
        cc_send_note("SPIFFS mounted successfully");
    }
    else {
        cc_send_note("ERROR: SPIFFS mount failed");
        // this is kind of fatal...
        return false;
    }
    return true;
};


// FW-BUG-028: one NVS entry ("cal", cc_cal_blob.h), written whole or not at all; false when it was not stored (an
// implausible calibration, or the put wrote less than the blob), and NVS then still holds the previous one.
bool DeviceSettings::storeCalibration(const MotorCalibration& cal) {
    if (!cc_cal_values_ok(cal.direction, cal.zero_angle)) return false;
    const CcCalBlob blob = cc_cal_encode(cal.direction, cal.zero_angle);
    if (nano_preferences.putBytes("cal", &blob, sizeof blob) != sizeof blob) return false;
    // The two-key pair of older firmware is stale from here on. Removed after the blob is in, so a cut between the
    // two leaves the blob (read first); an older firmware finds no pair and aligns again.
    if (nano_preferences.isKey("direction")) nano_preferences.remove("direction");
    if (nano_preferences.isKey("zero_angle")) nano_preferences.remove("zero_angle");
    return true;
};


// Uncalibrated ({0, NOT_SET}: initFOC() aligns) unless NVS holds a whole, plausible calibration: the "cal" blob, or,
// on a knob last calibrated by older firmware, the two-key pair (range-checked; a damaged blob never falls back to it).
MotorCalibration DeviceSettings::loadCalibration() {
    MotorCalibration result;
    result.direction = 0;
    result.zero_angle = NOT_SET;
    int8_t direction = 0;
    float zero = NOT_SET;
    if (nano_preferences.isKey("cal")) {
        CcCalBlob blob;
        const size_t length = nano_preferences.getBytesLength("cal");
        const size_t got = length == sizeof blob ? nano_preferences.getBytes("cal", &blob, sizeof blob) : 0;
        if (cc_cal_decode(&blob, got, direction, zero)) { result.direction = direction; result.zero_angle = zero; }
        return result;
    }
    direction = static_cast<int8_t>(nano_preferences.getUChar("direction", 0));
    zero = nano_preferences.getFloat("zero_angle", NOT_SET);
    if (cc_cal_values_ok(direction, zero)) { result.direction = direction; result.zero_angle = zero; }
    return result;
};


bool DeviceSettings::loadHostSeen() {
    return nano_preferences.getBool("host_seen", false);
};


// Written once per knob (the HMI thread calls it only on the first claim it sees while the flag is clear).
void DeviceSettings::storeHostSeen() {
    nano_preferences.putBool("host_seen", true);
};


String DeviceSettings::loadCurrentProfile() {
    String profile = nano_preferences.getString("current_profile", "Default Profile");
    return profile;
};


void DeviceSettings::storeCurrentProfile(String profile) {
    nano_preferences.putString("current_profile", profile);
};
