#pragma once
#include <Arduino.h>
#include <ArduinoJson.h>

// Bounded replies for the COM thread (1.0.0-cc5.1).
//
// USBCDC::write() (Arduino-ESP32 2.0.14) loops without yielding while the
// 64-byte TinyUSB transmit FIFO is full and DTR is set. A host that keeps the
// port open but stops reading would pin the COM task on core 0, starve IDLE0
// and trip the task watchdog. These helpers write only what the FIFO has room
// for, yield (taskYIELD for the first 2 ms, then vTaskDelay(1)) while it is
// full, and drop the rest of a reply after 250 ms without progress, counting
// the stall. A disconnected port (DTR low) drops at once, as the core does.
// A reply cut after part of it went out is ended with '\n' at once when the
// FIFO has room, otherwise the next reply starts with '\n': the host loses
// only the cut reply, never the one after it.
//
// COM thread only: one static serialisation buffer, no locking.
void cc_send_json(const JsonDocument& doc);   // serializeJson + "\r\n", like serializeJson(doc, Serial); Serial.println()
void cc_send_line(const char* text);          // text + "\r\n", like Serial.println(text)
uint32_t cc_tx_stalls();                      // replies cut short by the 250 ms stall limit
uint32_t cc_tx_dropped_bytes();               // bytes those replies lost
