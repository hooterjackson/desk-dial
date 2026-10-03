
#pragma once



#include <ArduinoJSON.h>


typedef struct {
    bool in = true;
    bool out = true;
    bool thru = false;
    bool route = false;
    bool nano = true;
} midiSettings;


typedef struct {
    int8_t direction;
    float zero_angle;
} MotorCalibration;



typedef struct {
    uint8_t ledMaxBrightness;
    uint16_t deviceOrientation;
    midiSettings midiUsb;
    midiSettings midi2;
    uint8_t midi_sysex_id;
} HmiDeviceSettings;



/**
 * Device settings.
 * For use from setup() or comms thread only.
 */
class DeviceSettings {
    friend class HmiThread;
    friend class ComThread;
public:
    static DeviceSettings& getInstance();

    DeviceSettings& operator=(JsonObject& obj);
    void toJSON(JsonObject& obj);

    bool toSPIFFS();

    // load settings - call only from main or in comms thread
    bool fromSPIFFS();

    void storeCurrentProfile(String profile);
    String loadCurrentProfile();
    MotorCalibration loadCalibration();
    // FW-BUG-028: one checked NVS entry; false when it was not stored (the previous calibration stays).
    bool storeCalibration(const MotorCalibration& cal);
    // FW-BUG-013: a Desk Dial host has claimed a control on this knob at least once (NVS "host_seen").
    // Until then the offline system volume never arms and the native profile keeps the knob and keys.
    bool loadHostSeen();
    void storeHostSeen();
    bool init();

    bool dirty;

    bool debug;
    uint8_t ledMaxBrightness;
    float maxVelocity;
    float maxVoltage;
    String deviceName;
    uint16_t deviceOrientation;
    midiSettings midiUsb;
    midiSettings midi2;
    uint8_t midi_sysex_id;
    bool wifiEnabled;   // FW-SEC-003: no Wi-Fi; SSID and password are never kept or reported
    uint32_t idleTimeout;

    // read-only settings
    String serialNumber;
    String firmwareVersion;
protected:
    DeviceSettings();
    ~DeviceSettings();

    static DeviceSettings instance;
};

