#pragma once
// App profiles (plan §1c; APP_PROFILES.md section 7): the {"appProfile":{...}} serial request over the store's
// upload state machine (cc_app_store.h). Platform-neutral: ArduinoJson only, compiled unchanged by the firmware
// (com_thread.cpp sends the reply), by harness/app_store_tests.py (MSVC /W4 /WX) and by cpp11_gate.py
// (gnu++11). The upload model is adapted from Karl Malota's (katbinaris) host_link.c, feat/firmware-esp-idf-quadra,
// with permission.
//
// Requests and replies (one reply per line, except a begin that succeeded, which has none):
//   {"op":"begin","id":I,"bytes":N,"crc":C,"wire":1}   -> nothing | {"error":...}
//   {"op":"data","off":O,"b64":"..."}                  -> {"ack":O_next} | {"error":...}
//   {"op":"end"}                                       -> {"id":I,"crc":C,"ok":true} | {"error":...}
//   {"op":"list"}                                      -> {"loaded":[{"id":I,"crc":C}, ...]}
// Errors: "crc" | "size" | "order" | "busy" | "wire" | "decode:<code>@<offset>". A field of the wrong type is the
// error of its family: id -> order, bytes / b64 length -> size, crc -> crc, wire -> wire, off / b64 type -> order;
// a request that is not an object, or an unknown op, is "order".
#include <ArduinoJson.h>
#include <stdint.h>

// Handles one request (the value of "appProfile"); fills `reply` (the object under "appProfile") and returns true
// when there is a reply to send. COM task.
bool cc_app_profile_command(JsonVariantConst request, uint32_t now_ms, JsonObject reply);

// The knob's store hooks (PSRAM, a static FreeRTOS mutex): once from setup(), before the tasks start
// (cc_app_store_device.cpp; firmware only).
void cc_app_store_device_init();
