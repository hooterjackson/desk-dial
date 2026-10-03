#include <Arduino.h>

#include "nanofoc_d.h"
#include "./foc_thread.h"
#include "./hmi_thread.h"
#include "./lcd_thread.h"
#include "./com_thread.h"
#include "./DeviceSettings.h"
#include "cc_artwork.h"
#include "cc_diag.h"
#include "cc_media.h"
#include "cc_app_store_msg.h"
#include "cc_fw_version.h"
#include <esp_heap_caps.h>
#include <esp32s3/spiram.h>   // esp_spiram_is_initialized() (IDF 4.4, ESP32-S3)
#include <esp_task_wdt.h>
#include "SPIFFS.h"
#include <Adafruit_TinyUSB.h>

#include <SparkFun_STUSB4500.h>

FocThread foc_thread(1);
HmiThread hmi_thread(0);
LcdThread lcd_thread(0);
ComThread com_thread(0);

STUSB4500 usb;


// FW-BUG-017: LVGL's own objects record sizeof(lv_obj_t) as they were compiled (lv_obj_class.instance_size); this unit
// sees the size src/ was compiled with. They differ when an lv_conf.h change reached only part of the build (a stale
// incremental build; lv_conf.h comes in through a macro include the dependency scan cannot see), and then every
// lv_obj_t field after the difference (user_data, ...) lands in another field. scripts/lvconf_guard.py prevents it at
// build time; this reports it at boot.
bool cc_lvgl_layout_ok() {
  return lv_obj_class.instance_size == sizeof(lv_obj_t);
}


void setup() {
  // Reset reason and the previous boot's RTC breadcrumbs, before anything else
  // ({"diag":"?"}: resetReason, bootCount, previous; cc_diag.h).
  cc_boot_begin();
  // Task watchdog 10 s with panic (1.0.0-cc5.2, cc_diag.h). IDLE0 stays subscribed; the
  // HMI, LCD and COM threads subscribe themselves when they start.
  cc_wdt_begin();

  // initialize USB
  TinyUSBDevice.begin();
  hmi_thread.init_usb();
  TinyUSBDevice.setID(0x239A, 0x8010); // TODO move to #define
  TinyUSBDevice.setProductDescriptor("Nano_D++ (Beta)"); // TODO move to #define
  TinyUSBDevice.setManufacturerDescriptor("Binaris Circuitry");
  TinyUSBDevice.setSerialDescriptor("Nano_D");
  //TinyUSBDevice.attach();
  // Serial is the core's USBCDC (Adafruit_USBD_CDC is an alias on ESP32). With
  // ARDUINO_USB_CDC_ON_BOOT=1/ARDUINO_USB_MODE=0 the core's app_main has already
  // run Serial.begin() (256-byte RX queue) and USB.begin(), so this replaces that
  // queue. The device/HID/MIDI descriptors set just above are what the host
  // enumerates, so this runs before the host can open the CDC port and no RX
  // callback can race the swap. On allocation failure it returns 0 and keeps
  // the existing 256-byte queue (no panic).
  //
  // 1.0.0-cc5.1: the queue (4096 B plus an 84 B Queue_t, spinlock and event
  // lists) must be in INTERNAL RAM. psramInit() sends every malloc of 4096 B
  // or more to PSRAM first (CONFIG_SPIRAM_MALLOC_ALWAYSINTERNAL), so in 1.0.0-cc5
  // this kernel object was allocated in PSRAM and every received byte took a
  // PSRAM-resident spinlock from the priority-24 usbd task. Raise the limit
  // just for this allocation, then restore it. The PSRAM free size tells where
  // it went; {"diag":"?"} reports it as rxQueue.
  //
  // 1.0.0-cc5.3 (ARTWORK2.md section 3): the queue is 8192 bytes, so an artwork2 host can
  // write whole lines unpaced (one media line of at most 2.9 KB plus two frames in flight).
  // xQueueCreate() makes ONE allocation of the 8192-byte storage plus the Queue_t, so the
  // limit (allocations up to it stay internal) is raised to 16384 for this call only. diag
  // rxQueueBytes reports the size actually configured (256 when the core's default queue was
  // kept). capabilities artwork2.rxBytes reports it only while the queue is in internal RAM,
  // and 0 when it landed in PSRAM anyway (rxQueue "psram"): the host writes unpaced only
  // against an 8192-byte internal queue, so either failure keeps it on paced v1 art.
  //
  // Only when psramInit() actually set that limit: it does so only after PSRAM
  // initialised and joined the heap, which is when psramFound() is true (and
  // esp_spiram_is_initialized() confirms the IDF side). After a failed PSRAM
  // init the global malloc policy was never changed, and it stays untouched.
  const size_t psramBefore = heap_caps_get_free_size(MALLOC_CAP_SPIRAM);
#if CONFIG_SPIRAM_USE_MALLOC && !CONFIG_ARDUINO_ISR_IRAM   // the condition psramInit() set the limit under
  const bool psramMallocPolicy = psramFound() && esp_spiram_is_initialized();
  if (psramMallocPolicy) heap_caps_malloc_extmem_enable(2 * CC_MEDIA_RX_BYTES);
#endif
  const size_t rxQueueBytes = Serial.setRxBufferSize(CC_MEDIA_RX_BYTES);
#if CONFIG_SPIRAM_USE_MALLOC && !CONFIG_ARDUINO_ISR_IRAM   // the condition psramInit() set the limit under
  if (psramMallocPolicy) heap_caps_malloc_extmem_enable(CONFIG_SPIRAM_MALLOC_ALWAYSINTERNAL);
#endif
  const size_t psramAfter = heap_caps_get_free_size(MALLOC_CAP_SPIRAM);
  const bool rxQueueSet = rxQueueBytes == CC_MEDIA_RX_BYTES;   // 0 on failure: the 256-byte queue stays
  cc_boot_rx_queue(!rxQueueSet ? CC_RX_QUEUE_DEFAULT
                   : (psramBefore >= psramAfter + CC_MEDIA_RX_BYTES ? CC_RX_QUEUE_PSRAM : CC_RX_QUEUE_INTERNAL),
                   rxQueueSet ? CC_MEDIA_RX_BYTES : 256);
  Serial.begin(DEFAULT_SERIAL_SPEED);

  delay(100);
  Serial.println("Welcome to Nano_D++!");
  Serial.print("Firmware version: ");
  Serial.println(cc_fw_version());   // FW-PUB-004: the public version, build id and binary
  if (!cc_lvgl_layout_ok()) {
    Serial.println("ERROR: LVGL was compiled with another lv_conf.h than src/ (lv_obj_t sizes differ). "
                   "Run `pio run -t clean`, then build again.");
  }
  Serial.println("Initializing...");
  // before we begin, load our global settings...
  DeviceSettings& settings = DeviceSettings::getInstance();
  settings.init();
  settings.fromSPIFFS(); // attempt to load settings from SPIFFS

  // initialize PD power
  hmi_thread.init_pd();

  // then load the profiles
  HapticProfileManager& profileManager = HapticProfileManager::getInstance();
  profileManager.fromSPIFFS(); // attempt to load profiles from SPIFFS

  // load motor calibration from Preferences
  MotorCalibration cal = settings.loadCalibration();
  foc_thread.setCalibration(cal);
  
  // load current profile from Preferences
  String current_profile = settings.loadCurrentProfile();
  profileManager.setCurrentProfile(current_profile);

  // init threads
  hmi_thread.init(profileManager.getCurrentProfile()->led_config, profileManager.getCurrentProfile()->hmi_config);
  if (profileManager.getCurrentProfile()->hmi_config.knob.num > 0)
    foc_thread.init(profileManager.getCurrentProfile()->hmi_config.knob.values[0].haptic);

  // Artwork cover cache (PSRAM) and its mutex, created once before any thread
  // can query or use it. Null-safe: failure only disables artwork.
  cc_art_init();
  // artwork2 media stores (1.0.0-cc5.3): 25 x 32 KB covers and 49 x 2 KB icons in PSRAM,
  // and their mutex, before any thread starts. Fail-soft: artwork2.available false.
  cc_media_init();
  // App profiles (APP_PROFILES.md section 7): the RAM-only profile store's hooks (PSRAM, a static mutex), before
  // the LCD task can draw a profile or the COM task upload one. Allocates nothing until an upload.
  cc_app_store_device_init();

  // Read-only: is a core dump stored in the coredump partition? (never erased here)
  cc_boot_check_coredump();

  // start threads
  Serial.println("Starting threads...");
  Serial.flush();
  vTaskDelay(100 / portTICK_PERIOD_MS);
  lcd_thread.begin();
  com_thread.begin();
  hmi_thread.begin();
  foc_thread.begin();
  vTaskDelete(NULL);
}

void loop() {
  // main loop not used...
  vTaskDelay(1000);
}
