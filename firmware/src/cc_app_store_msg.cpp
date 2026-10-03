// App profiles (plan §1c; APP_PROFILES.md section 7): the appProfile serial request (cc_app_store_msg.h). Adapted
// from Karl Malota's (katbinaris) host_link.c upload handling, feat/firmware-esp-idf-quadra, with permission.
#include "cc_app_store_msg.h"
#include "cc_app_store.h"
#include <stdio.h>
#include <string.h>

namespace {
// A JSON integer (never a bool or float) that fits a u32.
bool json_u32(JsonVariantConst value, uint32_t& out) {
    if (value.is<bool>() || !value.is<uint32_t>()) return false;
    out = value.as<uint32_t>();
    return true;
}

bool op_is(JsonVariantConst op, const char* name) {
    if (!op.is<const char*>()) return false;
    const JsonString wire = op.as<JsonString>();
    return strlen(name) == wire.size() && !memcmp(name, wire.c_str(), wire.size());
}

bool error(JsonObject reply, cc_app_up_result_t result, const cc_app_up_end_t* end = nullptr) {
    if (result == CC_APP_UP_DECODE && end != nullptr) {
        char text[40];   // "decode:" + code + "@" + offset < 40 characters
        snprintf(text, sizeof text, "decode:%d@%u", end->decode, static_cast<unsigned>(end->offset));
        reply["error"] = static_cast<char*>(text);   // char*: copied into the reply document
    } else {
        reply["error"] = cc_app_up_error_name(result);
    }
    return true;
}

bool begin(JsonObjectConst request, uint32_t now_ms, JsonObject reply) {
    uint32_t bytes = 0, crc = 0, wire = 0;
    // Field families, checked in the order the state machine checks them (wire, size, id) plus crc.
    if (!json_u32(request["wire"], wire)) return error(reply, CC_APP_UP_WIRE);
    if (!json_u32(request["bytes"], bytes)) return error(reply, CC_APP_UP_SIZE);
    if (!json_u32(request["crc"], crc)) return error(reply, CC_APP_UP_CRC);
    JsonVariantConst id = request["id"];
    char text[CC_APP_ID_MAX + 1] = {};
    if (id.is<const char*>()) {
        const JsonString wireId = id.as<JsonString>();
        if (wireId.size() <= CC_APP_ID_MAX && strlen(wireId.c_str()) == wireId.size())
            memcpy(text, wireId.c_str(), wireId.size());
    }
    // An absent, non-string, NUL-holding or malformed id leaves `text` invalid: begin answers order.
    const cc_app_up_result_t result = cc_app_upload_begin(text, bytes, crc, wire, now_ms);
    if (result != CC_APP_UP_OK) return error(reply, result);
    return false;   // no reply: the first data line's ack follows
}

bool data(JsonObjectConst request, uint32_t now_ms, JsonObject reply) {
    uint32_t off = 0, next = 0;
    JsonVariantConst b64 = request["b64"];
    if (!json_u32(request["off"], off) || !b64.is<const char*>()) {
        cc_app_upload_data(0, nullptr, 0, now_ms, nullptr);   // drops the upload, as any failed data line does
        return error(reply, CC_APP_UP_ORDER);
    }
    const JsonString text = b64.as<JsonString>();
    const cc_app_up_result_t result = cc_app_upload_data(off, text.c_str(), text.size(), now_ms, &next);
    if (result != CC_APP_UP_OK) return error(reply, result);
    reply["ack"] = next;
    return true;
}

bool end(uint32_t now_ms, JsonObject reply) {
    cc_app_up_end_t done;
    const cc_app_up_result_t result = cc_app_upload_end(now_ms, &done);
    if (result != CC_APP_UP_OK) return error(reply, result, &done);
    reply["id"] = static_cast<char*>(done.id);   // copied
    reply["crc"] = done.crc;
    reply["ok"] = true;
    return true;
}

bool list(JsonObject reply) {
    cc_app_store_item_t items[CC_APP_STORE_SLOTS];
    const size_t count = cc_app_store_list(items, CC_APP_STORE_SLOTS);
    JsonArray loaded = reply["loaded"].to<JsonArray>();
    for (size_t i = 0; i < count; ++i) {
        JsonObject item = loaded.add<JsonObject>();
        item["id"] = static_cast<char*>(items[i].id);   // copied
        item["crc"] = items[i].crc;
    }
    return true;
}
}  // namespace

bool cc_app_profile_command(JsonVariantConst request, uint32_t now_ms, JsonObject reply) {
    if (!request.is<JsonObjectConst>()) return error(reply, CC_APP_UP_ORDER);
    JsonObjectConst object = request.as<JsonObjectConst>();
    JsonVariantConst op = object["op"];
    if (op_is(op, "begin")) return begin(object, now_ms, reply);
    if (op_is(op, "data")) return data(object, now_ms, reply);
    if (op_is(op, "end")) return end(now_ms, reply);
    if (op_is(op, "list")) return list(reply);
    return error(reply, CC_APP_UP_ORDER);
}
