
#include "./HapticProfileManager.h"
#include "class/hid/hid.h"
#include "cc_serial_out.h"


void HapticProfileManager::updateProfile(HapticProfile* profile, uint8_t from_version) {
    if (from_version==1) {
        profile->hmi_config.keys[0].num_pressed_actions = 1;
        profile->hmi_config.keys[0].pressed[0].type = keyActionType::KA_KEY;
        profile->hmi_config.keys[0].pressed[0].hid.num = 1;
        profile->hmi_config.keys[0].pressed[0].hid.key_codes[0] = HID_KEY_N;
        profile->hmi_config.keys[1].num_pressed_actions = 1;
        profile->hmi_config.keys[1].pressed[0].type = keyActionType::KA_KEY;
        profile->hmi_config.keys[1].pressed[0].hid.num = 1;
        profile->hmi_config.keys[1].pressed[0].hid.key_codes[0] = HID_KEY_A;
        profile->hmi_config.keys[2].num_pressed_actions = 1;
        profile->hmi_config.keys[2].pressed[0].type = keyActionType::KA_KEY;
        profile->hmi_config.keys[2].pressed[0].hid.num = 1;
        profile->hmi_config.keys[2].pressed[0].hid.key_codes[0] = HID_KEY_N;
        profile->hmi_config.keys[3].num_pressed_actions = 1;
        profile->hmi_config.keys[3].pressed[0].type = keyActionType::KA_KEY;
        profile->hmi_config.keys[3].pressed[0].hid.num = 1;
        profile->hmi_config.keys[3].pressed[0].hid.key_codes[0] = HID_KEY_O;
        cc_send_note((String("Updated profile ") + profile->profile_name + " from version 1 to 2").c_str());  // FW-BUG-001
    }
}