
#include "./com_thread.h"
#include "./foc_thread.h"
#include "./hmi_thread.h"
#include "./lcd_thread.h"
#include <esp_task_wdt.h>
#include "./DeviceSettings.h"
#include "audio/audio.h"
#include "control_center.h"
#include "cc_diag.h"
#include "cc_media.h"
#include "cc_media_store.h"
#include "cc_serial_out.h"




ComThread::ComThread(const uint8_t task_core) : Thread("COM", 12000, 1, task_core) {
    _q_strings_in = xQueueCreate(5, sizeof( StringMessage ));
};

ComThread::~ComThread() {

};


void ComThread::put_string_message(const StringMessage& msg){
    xQueueSend(_q_strings_in, &msg, (TickType_t)0);
};



String title = "";
String data1 = "";
String data2 = "";
String data3 = "";
String data4 = "";

namespace {
// Serial command lines: up to 4096 bytes before the newline (the host's limit is
// 4096 including it). Static: never on the COM stack. The assembly and its oversize rule
// (one reply, then the rest of the line dropped through its newline) are CCLineAssembler
// in cc_media_store.h since 1.0.0-cc5.3, so harness/media_tests.py checks them.
constexpr size_t kLineCapacity = 4096;
char line_buffer[kLineCapacity + 1];
CCLineAssembler command_line(line_buffer, kLineCapacity);
constexpr size_t kDrainBudget = 2 * (kLineCapacity + 1); // bytes per pass
constexpr uint32_t kAbandonedLineMs = 2000;
constexpr size_t kArtScanBytes = 192; // bounded raw prefix scan for an art line's id/key
// COM idle sleep (1.0.0-cc5.3, ARTWORK2.md section 3, cc_com_idle_ticks in
// cc_media_store.h): when the last complete line was handled.
uint32_t line_handled_ms = 0;
bool line_handled = false;
// The {"screen":...} command's LCD command (set up in run(), sent by handleLine()).
LcdCommand remoteLcdCommand;

// Position just after `"name"`, optional spaces, ':' and optional spaces; 0 if absent.
size_t scan_member(const char* line, size_t limit, const char* name) {
    const size_t size = strlen(name);
    for (size_t i = 0; i + size + 2 < limit; ++i) {
        if (line[i] != '"' || memcmp(line + i + 1, name, size) || line[i + size + 1] != '"') continue;
        size_t j = i + size + 2;
        while (j < limit && line[j] == ' ') ++j;
        if (j >= limit || line[j] != ':') continue;
        ++j;
        while (j < limit && line[j] == ' ') ++j;
        return j < limit ? j : 0;
    }
    return 0;
}

// {"artAck":{"id":..,"key":..,"op":"parse","error":"parse"}} for an art line
// that is oversize or not JSON (contract section 7). id and key come from a
// bounded scan of the raw prefix and are omitted unless found intact in it.
void art_parse_reply(const char* line, size_t length) {
    const size_t limit = length < kArtScanBytes ? length : kArtScanBytes;
    char key[65]; // outlives serializeJson below
    JsonDocument out;
    JsonObject ack = out["artAck"].to<JsonObject>();
    size_t at = scan_member(line, limit, "id");
    if (at) {
        uint32_t id = 0;
        size_t digits = 0;
        while (at + digits < limit && digits < 10 && line[at + digits] >= '0' && line[at + digits] <= '9') {
            id = id * 10 + static_cast<uint32_t>(line[at + digits] - '0');
            ++digits;
        }
        const char next = at + digits < limit ? line[at + digits] : 0;
        // A complete integer 1..0x7FFFFFFF: delimited, no leading zero, no fraction.
        if (digits && (next == ',' || next == '}' || next == ' ') && line[at] != '0' &&
            id >= 1 && id <= 0x7FFFFFFF && !(digits == 10 && line[at] > '2')) ack["id"] = id;
    }
    at = scan_member(line, limit, "key");
    if (at && line[at] == '"') {
        size_t n = 0;
        while (at + 1 + n < limit && n <= 64) {
            const char c = line[at + 1 + n];
            if (!((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_' || c == '-')) break;
            ++n;
        }
        if (n >= 1 && n <= 64 && at + 1 + n < limit && line[at + 1 + n] == '"') {
            memcpy(key, line + at + 1, n);
            key[n] = 0;
            ack["key"] = key;
        }
    }
    ack["op"] = "parse";
    ack["error"] = "parse";
    cc_send_json(out);
}

// A line that is oversize or not JSON (cc_bad_line_reply): an art line gets the artAck parse
// reply (contract section 7), a media line the mediaAck parse reply (ARTWORK2.md 4.3 step 1,
// counted in mediaErrors). False for any other line: the caller sends its bare error.
bool protocol_parse_reply(const char* line, size_t length) {
    switch (cc_bad_line_reply(line, length)) {
        case CC_BAD_LINE_ART: art_parse_reply(line, length); return true;
        case CC_BAD_LINE_MEDIA: cc_media_parse_reply(line, length); return true;
        default: return false;
    }
}
}

void ComThread::run() {
    // Task watchdog (1.0.0-cc5.2, cc_diag.h): fed once per pass at the wait step and after
    // every handled line (each reply is bounded: cc_serial_out gives up after 250 ms
    // without progress). Unsubscribed around the SPIFFS/NVS save and load commands.
    cc_wdt_watch(CC_LIVE_COM);
    // serial is initialized in main.cpp, but subsequently used only here
    Serial.println("COM thread started");
    unsigned long ts = millis();
    ts_last_activity = ts;
    JsonDocument idleDoc;
    remoteLcdCommand.type = LCD_LAYOUT_DEFAULT;
    remoteLcdCommand.title = &title;
    remoteLcdCommand.data1 = &data1;
    remoteLcdCommand.data2 = &data2;
    remoteLcdCommand.data3 = &data3;
    remoteLcdCommand.data4 = &data4;
    dispatchSettings();
    dispatchLcdConfig();
    Serial.setTimeout(50);
    while (true) {
        cc_crumb_com_stage(CC_COM_STAGE_SERVICE);
        cc_service();
        cc_crumb_com_stage(CC_COM_STAGE_READ);
        // Non-blocking line assembly (Stage 2): drain what has arrived and
        // process every complete line; a partial line stays in line_buffer for
        // the next pass. The pass is bounded so knob events keep flowing.
        size_t budget = kDrainBudget;
        while (budget-- && Serial.available() > 0) {
            const int c = Serial.read();
            if (c < 0) break;
            const CCLineEvent event = command_line.feed(static_cast<char>(c), millis());
            if (event == CC_COM_LINE_COMPLETE) {
                cc_crumb_com_stage(CC_COM_STAGE_SERVICE);
                cc_service(); // as before: replies due before the next command go first
                cc_crumb_com(CC_COM_OP_NONE, CC_COM_STAGE_LINE, static_cast<uint32_t>(command_line.length()));
                cc_crumb_com_line();
                handleLine(command_line.text(), command_line.length());
                cc_wdt_feed();   // a line was handled: progress
                cc_crumb_com_stage(CC_COM_STAGE_READ);
            } else if (event == CC_COM_LINE_OVERSIZE) {
                // Oversize: exactly one reply (art and media lines in their own protocol); the
                // rest of the line is dropped through its newline, which gets no second one.
                cc_crumb_com(CC_COM_OP_OVERSIZE, CC_COM_STAGE_LINE, static_cast<uint32_t>(command_line.length()));
                if (!protocol_parse_reply(command_line.text(), command_line.length())) sendError("Command too large");
            }
            if (event == CC_COM_LINE_COMPLETE || event == CC_COM_LINE_DISCARDED) {
                line_handled_ms = millis(); line_handled = true;   // idle sleep rule (section 3)
            }
        }
        // A writer that stalls 2 s mid-line has gone (the lease is 2 s): its fragment is
        // dropped, never glued onto the next session's first command.
        command_line.expire(millis(), kAbandonedLineMs);

        // send any outgoing messages
        cc_crumb_com_stage(CC_COM_STAGE_EVENTS);
        handleMessages();

        // send key events
        handleEvents();

        // send idle message
        unsigned long now = millis();
        if (now-ts>1000 && now-ts_last_activity>global_idle_timeout && global_idle_timeout>0) {
          ts = now;          
          idleDoc["idle"] = now-ts_last_activity;
          cc_send_json(idleDoc);
        }
        if (now-ts_last_activity<=global_idle_timeout || global_idle_timeout==0)
          global_sleep_flag = false;
        else
          global_sleep_flag = true;

        // 1 tick while a line is still arriving (or more is queued), a media upload is
        // receiving, or the last complete line was handled less than 20 ms ago; else 10.
        const uint32_t ticks = cc_com_idle_ticks(command_line.partial(), Serial.available() > 0, cc_media_receiving(),
                                                 line_handled, static_cast<uint32_t>(millis() - line_handled_ms));
        cc_crumb_com_stage(CC_COM_STAGE_WAIT);
        cc_wdt_feed();                    // one full pass completed
        vTaskDelay(ticks);                // give other threads a chance to run...
    }

};


// One complete command line (without its newline). Same parsing, replies and
// command order as the previous readStringUntil() loop body.
void ComThread::handleLine(const char* line, size_t length) {
    JsonDocument doc;
    DeserializationError error = deserializeJson(doc, line, length);
    if (error) {
        doc.clear();
        cc_crumb_com(CC_COM_OP_PARSE_ERROR, CC_COM_STAGE_LINE, static_cast<uint32_t>(length));
        // An art line is answered as art (contract section 7), never a bare error; a media
        // line as media (ARTWORK2.md 4.3 step 1).
        if (!protocol_parse_reply(line, length)) sendError("JSON parse error", error.c_str());
        return;
    }
    ts_last_activity = millis();
    if (cc_handle_command(doc)) return;
    cc_crumb_com(CC_COM_OP_NATIVE, CC_COM_STAGE_LINE, static_cast<uint32_t>(length));
    //Serial.println("JSON received");
    JsonVariant profile = doc["profile"];
    JsonVariant v = doc["updates"];
    if (profile.is<String>() || v!=nullptr) { // haptic command
      handleProfileCommand(profile, v);
    }
    if (doc["current"]!=nullptr) { // set current profile
      setCurrentProfile(doc["current"].as<String>());
    }          
    if (doc["R"]!=nullptr) { // motor command
      // send message to FOC thread
      const char* cmd = doc["R"];
      String* cmdstr = new String(cmd);
      foc_thread.put_motor_command(cmdstr);
    }
    v = doc["message"];
    if (v.is<String>()) { // its a message
      // send message to screen
      StringMessage msg{new String(v.as<String>()), STRING_MESSAGE_DEBUG};
      // TODO lcd_thread.put_string_message(msg);
    }
    v = doc["screen"];
    if (v!=nullptr) {
      if (v["title"].is<String>()) title = v["title"].as<String>(); else title = "";
      if (v["data1"].is<String>()) data1 = v["data1"].as<String>(); else data1 = "";
      if (v["data2"].is<String>()) data2 = v["data2"].as<String>(); else data2 = "";
      if (v["data3"].is<String>()) data3 = v["data3"].as<String>(); else data3 = "";
      if (v["data4"].is<String>()) data4 = v["data4"].as<String>(); else data4 = "";
      lcd_thread.put_lcd_command(remoteLcdCommand);
    }
    v = doc["recalibrate"];
    if (v.is<bool>()) { // recalibrate motor
      // enter calibration mode
      if (v.as<bool>()) {
        Serial.println("Recalibrating motor");
        foc_thread.put_motor_command(new String("129=1"));
      }
    }
    v = doc["profiles"];
    if (v!=nullptr) { // list profiles
      handleProfilesCommand(v);
    }
    v = doc["settings"];
    if (v!=nullptr) { // get or set settings
      handleSettingsCommand(v);
    }
    if (doc["save"]) { // save settings and profiles to SPIFFS
      if (doc["save"].as<bool>()==true) {
        // A SPIFFS write may run a garbage collection that takes seconds: not a hang, so
        // this task leaves the task watchdog for the flash work (1.0.0-cc5.2).
        cc_wdt_unwatch(CC_LIVE_COM);
        DeviceSettings::getInstance().toSPIFFS();
        HapticProfileManager::getInstance().toSPIFFS();
        DeviceSettings::getInstance().storeCurrentProfile(HapticProfileManager::getInstance().getCurrentProfile()->profile_name);
        cc_wdt_watch(CC_LIVE_COM);
        JsonDocument reply;
        reply["saved"] = true;
        serializeJson(reply, Serial);
        Serial.println(); // add a newline
      }
    }
    if (doc["load"]) { // load settings and profiles from SPIFFS
      if (doc["load"].as<bool>()==true) {
        // first nuke existing profiles
        for (int i=0; i<MAX_PROFILES; i++) {
          HapticProfile* p = HapticProfileManager::getInstance()[i];
          if (p!=nullptr) {
            String name = p->profile_name;
            HapticProfileManager::getInstance().remove(name);
          }
        }
        cc_wdt_unwatch(CC_LIVE_COM);    // SPIFFS/NVS reads of every profile (1.0.0-cc5.2)
        DeviceSettings::getInstance().fromSPIFFS();
        HapticProfileManager::getInstance().fromSPIFFS();
        HapticProfileManager::getInstance().setCurrentProfile(DeviceSettings::getInstance().loadCurrentProfile());
        cc_wdt_watch(CC_LIVE_COM);
        dispatchSettings();
        dispatchHapticConfig();
        dispatchAudioConfig();
        dispatchLedConfig();
        dispatchHmiConfig();
        dispatchLcdConfig();
      }
    }
};





void ComThread::handleEvents() {
    JsonDocument eventDoc;
    bool hadEvent = false;
    do {
      KeyEvt keyEvt;
      hadEvent = hmi_thread.get_key_event(&keyEvt);
      if (hadEvent) {
        // 1.0.0-cc5.4 (PRESENTATION_V5 section 11; hmi_thread.h): the type, and the F24 tag of a
        // claimed key down in bit 7.
        const uint8_t type = keyEvt.type & kKeyEvtTypeMask;
        const bool hid = (keyEvt.type & kKeyEvtHid) != 0;
        const uint8_t keyNum = keyEvt.keyNum;
        // 11.2 step 5: every key-up seen here, forwarded or dropped, clears a deferred hold of that
        // raw; a hold with no control id matured while the session was entering: it goes to the
        // deferred slot and follows the next ready line (control_center.cpp).
        if (type == AceButton::kEventReleased) cc_hold_key_up(keyNum);
        if (type == kKeyEvtHold && !keyEvt.control_id) {
          if (cc_claimed()) cc_hold_deferred(keyNum);
          continue;
        }
        if ((cc_claimed() && (!keyEvt.control_id || keyEvt.control_id != cc_input_id())) ||
            (!cc_claimed() && keyEvt.control_id)) continue;
        eventDoc.clear();
        if (keyEvt.control_id) eventDoc["id"] = keyEvt.control_id;
        eventDoc["ks"] = keyEvt.keyState;
        if (type == AceButton::kEventPressed) {
          eventDoc["kd"] = keyNum;
          if (hid) eventDoc["hid"] = 1;    // 11.4: this press also sent F24
        } else if (type == AceButton::kEventReleased) {
          eventDoc["ku"] = keyNum;
        } else if (type == kKeyEvtHold) {
          eventDoc["kh"] = keyNum;         // 11.2: {"id","ks","kh"}, the kd rules
          cc_hold_sent();
        }
        cc_send_json(eventDoc);
        ts_last_activity = millis();
      }
    } while (hadEvent);
    do {
      AngleEvt angleEvt;
      hadEvent = foc_thread.get_angle_event(&angleEvt);
      if (hadEvent) {
        if ((cc_claimed() && (!angleEvt.control_id || angleEvt.control_id != cc_input_id())) ||
            (!cc_claimed() && angleEvt.control_id)) continue;
        eventDoc.clear();
        if (angleEvt.control_id) eventDoc["id"] = angleEvt.control_id;
        eventDoc["p"] = angleEvt.cur_pos;
        cc_send_json(eventDoc);
        ts_last_activity = millis();
      }
    } while (hadEvent);
};





void ComThread::handleSettingsCommand(JsonVariant s) {
  if (s.isNull()) return;
  if (s.is<String>()) {
    // send the settings
    JsonDocument doc;
    JsonObject obj = doc["settings"].to<JsonObject>();
    DeviceSettings::getInstance().toJSON(obj);
    serializeJson(doc, Serial);
    Serial.println(); // add a newline
  }
  if (s.is<JsonObject>()) {
    JsonObject obj = s.as<JsonObject>();
    DeviceSettings::getInstance() = obj;
    dispatchSettings();
  }
};



void ComThread::handleMessages() {
  StringMessage incoming;
  JsonDocument doc;
  String pName = "";
  if (xQueueReceive(_q_strings_in, &incoming, (TickType_t)0)) {
    if (cc_claimed() && (incoming.type == STRING_MESSAGE_PROFILE || incoming.type == STRING_MESSAGE_NEXT_PROFILE || incoming.type == STRING_MESSAGE_PREV_PROFILE)) {
      if (incoming.message) delete incoming.message;
      return;
    }
    HapticProfileManager& pm = HapticProfileManager::getInstance();
    bool sendDoc = false;
    switch(incoming.type) {
      case STRING_MESSAGE_DEBUG:
        if (incoming.message!=nullptr) {
          doc["debug"] = *incoming.message;
          sendDoc = true;
        }
        break;
      case STRING_MESSAGE_ERROR:
        if (incoming.message!=nullptr) {
          doc["error"] = *incoming.message;
          sendDoc = true;
        }
        break;
      case STRING_MESSAGE_MOTOR:
        if (incoming.message!=nullptr) {
          doc["r"] = *incoming.message;
          sendDoc = true;
        }
        break;
      case STRING_MESSAGE_PROFILE:
        if (incoming.message!=nullptr) {
          String s = *incoming.message;
          setCurrentProfile(s);
          doc["current"] = s;
          sendDoc = true;
        }
        break;
      case STRING_MESSAGE_NEXT_PROFILE:
        pName = pm.getNextProfileName();
        if (pName!="") {
          setCurrentProfile(pName);
          doc["current"] = pName;
          sendDoc = true;
        }
        break;
      case STRING_MESSAGE_PREV_PROFILE:
        pName = pm.getPrevProfileName();
        if (pName!="")  {
          setCurrentProfile(pName);
          doc["current"] = pName;
          sendDoc = true;
        }
        break;
      default:
        if (incoming.message!=nullptr) {
          Serial.println(*incoming.message);
        }
        break;
    }
    if (sendDoc) {
      serializeJson(doc, Serial);
      Serial.println(); // add a newline
    }
    if (incoming.message!=nullptr) {
      delete incoming.message;
    }
  }
};




void ComThread::handleProfilesCommand(JsonVariant p) {
  if (p.isNull()) return;
  HapticProfileManager& pm = HapticProfileManager::getInstance();
  if (p.is<String>()) {
    String s = p.as<String>();
    if (s=="#all") {
      // send the list of all profile names
      JsonDocument doc;
      JsonArray arr = doc["profiles"].to<JsonArray>();
      for (int i=0; i<pm.size(); i++) {
        arr.add(pm[i]->profile_name);
      }
      doc["current"] = pm.getCurrentProfile()->profile_name;
      serializeJson(doc, Serial);
      Serial.println(); // add a newline
    }
  }
  if (p.is<JsonArray>()) {
    JsonArray arr = p.as<JsonArray>();
    for (int i=0; i<MAX_PROFILES; i++) {
      HapticProfile* p = pm[i];
      if (p!=nullptr) {
        bool found = false;
        for (int i=0; i<arr.size(); i++) {
          if (arr[i].is<String>()) {
            String s = arr[i].as<String>();
            if (s==p->profile_name) {
              found = true;
              break;
            }
          }
        }
        if (!found) {
          Serial.println("Deleting profile "+p->profile_name);
          pm.remove(p->profile_name);
        }
      }
    }
  }
  // TODO reorder profiles
};




bool ComThread::isProfileNameOk(String& name){
  if (name==nullptr)
    return false;
  if (name.length()<1 || name.length()>20)
    return false;
  // TODO check for invalid characters
  return true;
};




void ComThread::sendError(String& error, String* msg){
      JsonDocument doc;
      doc["error"] = error;
      if (msg!=nullptr)
        doc["msg"] = *msg;
      cc_send_json(doc);
};
void ComThread::sendError(String& error, String& msg){
  sendError(error, &msg);
};
void ComThread::sendError(const char* error, String& msg) {
  String e = error;
  sendError(e, &msg);
};
void ComThread::sendError(const char* error, const char* msg) {
  String e = error;
  if (msg==nullptr) {
    sendError(e);
  }
  else {
    String m = msg;
    sendError(e, m);
  }
};



void ComThread::handleProfileCommand(JsonVariant profile, JsonVariant updates) {
  if (profile.isNull()&&updates.isNull()) return;
  HapticProfileManager& pm = HapticProfileManager::getInstance();
  HapticProfile* p;
  if (profile.is<String>()) {
    String pname = profile.as<String>();
    if (!isProfileNameOk(pname)) {
      sendError("Invalid profile name", pname);
      return;
    }
    p = pm[pname];
    if (p==nullptr) 
      p = pm.add(pname);
    if (p==nullptr) {
      sendError("Cannot add another profile");
      return;
    }
  }
  else 
    p = pm.getCurrentProfile();

  if (updates.isNull()) {
    JsonDocument doc, profileDoc;
    // send the selected profile
    JsonObject obj = doc["profile"].to<JsonObject>();
    p->toJSON(obj);
    serializeJson(doc, Serial);
    Serial.println(); // add a newline
  }
  else if (updates.is<JsonObject>()) {
    JsonObject obj = updates.as<JsonObject>();
    if (obj["name"].is<String>() && obj["name"].as<String>()!=p->profile_name) {
      String new_name = obj["name"].as<String>();
      if (pm[new_name]!=nullptr) {
        sendError("Profile name already exists");
        return;
      }
    }
    // update the profile
    *p = obj; // assigning the JSON object to the profile will update the profile's fields
    if (p==pm.getCurrentProfile()) {
      dispatchHapticConfig();
      dispatchAudioConfig();
      dispatchLedConfig();
      dispatchHmiConfig();
      dispatchLcdConfig();
    }
  }
};


void ComThread::setCurrentProfile(String name){
  HapticProfile* profile = HapticProfileManager::getInstance().setCurrentProfile(name);
  if (profile!=nullptr) { // if we changed profile, send the new haptic config to the FOC thread
    dispatchHapticConfig();
    dispatchLedConfig();
    dispatchHmiConfig();
    dispatchAudioConfig();
    dispatchLcdConfig();
  }
};


void ComThread::dispatchLedConfig() {
    ledConfig copy = HapticProfileManager::getInstance().getCurrentProfile()->led_config;
    if (copy.led_brightness>DeviceSettings::getInstance().ledMaxBrightness)
      copy.led_brightness = DeviceSettings::getInstance().ledMaxBrightness;
    hmi_thread.put_led_config(copy);
    //hmi_thread.put_key_config(HapticProfileManager::getInstance().getCurrentProfile()->key_config);
};


void ComThread::dispatchHmiConfig() {
    hmi_thread.put_hmi_config(HapticProfileManager::getInstance().getCurrentProfile()->hmi_config);
};

void ComThread::dispatchHapticConfig() {
  if (HapticProfileManager::getInstance().getCurrentProfile()->hmi_config.knob.num>0)
    foc_thread.put_haptic_config(HapticProfileManager::getInstance().getCurrentProfile()->hmi_config.knob.values[0].haptic);
};

void ComThread::dispatchSettings() {
    DeviceSettings& ds = DeviceSettings::getInstance();
    HmiDeviceSettings hmiSettings{
      .ledMaxBrightness = ds.ledMaxBrightness,
      .deviceOrientation = ds.deviceOrientation,
      .midiUsb = ds.midiUsb,
      .midi2 = ds.midi2,
      .midi_sysex_id = ds.midi_sysex_id
    };
    hmi_thread.put_settings(hmiSettings);
    global_idle_timeout = ds.idleTimeout;
};


void ComThread::dispatchAudioConfig() {
    audioPlayer.put_audio_config(HapticProfileManager::getInstance().getCurrentProfile()->audio_config);
};


String autoDescription = "";

String ComThread::generateDescription(HapticProfile& curr) {
  String desc = "";
  if (curr.hmi_config.knob.num>0) {
    switch (curr.hmi_config.knob.values[0].type) {
      case knobValueType::KV_MIDI:
        desc = "MIDI CC ";
        desc += curr.hmi_config.knob.values[0].midi.cc;
        break;
      case knobValueType::KV_GAMEPAD:
        desc = "Gamepad";
        break;
      case knobValueType::KV_MOUSE:
        desc = "Mouse";
        break;
      case knobValueType::KV_ACTIONS:
        desc = "Actions";
        break;
      case knobValueType::KV_DEVICE_PROFILES:
        desc = "Profiles";
        break;
      default:
        desc = "?";
        break;
    }
  }
  else {
    desc = "No Mapping";
  }
  return desc;
};

void ComThread::dispatchLcdConfig() {
    HapticProfile* curr = HapticProfileManager::getInstance().getCurrentProfile();
    LcdCommand cmd;
    cmd.type = LCD_LAYOUT_DEFAULT;
    cmd.title = &curr->profile_name;
    if (curr->profile_desc.length()>0)
      cmd.data1 = &curr->profile_desc;
    else {
      autoDescription = generateDescription(*curr);
      cmd.data1 = &autoDescription;
    }
    cmd.data2 = nullptr;
    cmd.data3 = nullptr;
    cmd.data4 = nullptr;
    lcd_thread.put_lcd_command(cmd);
};
