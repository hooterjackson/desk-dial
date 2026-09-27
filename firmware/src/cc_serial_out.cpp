#include "cc_serial_out.h"

// TinyUSB (Arduino-ESP32 core): the DTR test USBCDC::write() itself uses.
// Serial's own bool also needs RTS, which a host may leave low.
extern "C" bool tud_cdc_n_connected(uint8_t itf);

namespace {
constexpr uint32_t kSpinUs = 2000;        // yield without sleeping this long after the last progress
constexpr uint32_t kStallMs = 250;        // then give up on the rest of the reply
constexpr size_t kBufferBytes = 1536;     // capabilities, diag, artAck, events and errors all fit
constexpr uint8_t kNewline = '\n';
const uint8_t kLineEnd[] = {'\r', '\n'};
char buffer[kBufferBytes];
uint32_t stalls = 0, dropped = 0;
// A reply cut short after some of its bytes went out leaves an unterminated line on
// the wire. The next reply ends that line first, so the host's line parser loses
// only the cut reply (an unparseable line) and never the one after it.
bool lineOpen = false;

enum class Outcome { kDone, kStalled, kGone };

// Writes [data, data + size) only as fast as the TinyUSB FIFO drains; `done` counts
// the bytes written. kStalled: no progress for kStallMs. kGone: DTR low (no host),
// where the core would drop the bytes too.
Outcome fifo_write(const uint8_t* data, size_t size, size_t& done) {
    done = 0;
    uint32_t progressUs = micros(), progressMs = millis();
    while (done < size) {
        if (!tud_cdc_n_connected(0)) return Outcome::kGone;
        const int space = Serial.availableForWrite();
        if (space > 0) {
            const size_t chunk = size - done < static_cast<size_t>(space) ? size - done : static_cast<size_t>(space);
            const size_t written = Serial.write(data + done, chunk);   // fits the FIFO: never spins
            if (!written) return tud_cdc_n_connected(0) ? Outcome::kStalled : Outcome::kGone;
            done += written;
            progressUs = micros(); progressMs = millis();
            continue;
        }
        if (static_cast<uint32_t>(millis() - progressMs) >= kStallMs) return Outcome::kStalled;
        if (static_cast<uint32_t>(micros() - progressUs) < kSpinUs) taskYIELD();
        else vTaskDelay(1);                                     // IDLE0 (task watchdog) runs
    }
    return Outcome::kDone;
}

// Part of a reply went out and the rest was dropped: end the line now when the FIFO
// has room for one byte (never waits), otherwise before the next reply.
void end_cut_line() {
    if (tud_cdc_n_connected(0) && Serial.availableForWrite() > 0 && Serial.write(&kNewline, 1) == 1) return;
    lineOpen = true;
}

// One reply: `head`, then `tail` (may be empty), as a single line on the wire.
// A reply cut by the stall limit is counted (txStalls) with the bytes it lost
// (txDroppedBytes). With no host (DTR low) nothing is counted, as before.
void send_reply(const uint8_t* head, size_t headSize, const uint8_t* tail, size_t tailSize) {
    const size_t total = headSize + tailSize;
    size_t done = 0;
    if (lineOpen) {                              // a cut reply's line is still open: end it first
        const Outcome ended = fifo_write(&kNewline, 1, done);
        if (ended != Outcome::kDone) {            // still no room: drop this reply whole
            if (ended == Outcome::kStalled) { ++stalls; dropped += static_cast<uint32_t>(total); }
            return;
        }
        lineOpen = false;
    }
    Outcome outcome = fifo_write(head, headSize, done);
    size_t written = done;
    if (outcome == Outcome::kDone && tailSize) {
        outcome = fifo_write(tail, tailSize, done);
        written += done;
    }
    if (outcome == Outcome::kDone) return;
    if (written) end_cut_line();
    if (outcome == Outcome::kStalled) { ++stalls; dropped += static_cast<uint32_t>(total - written); }
}
}

void cc_send_json(const JsonDocument& doc) {
    const size_t length = measureJson(doc);
    if (length + 2 <= sizeof(buffer)) {
        serializeJson(doc, buffer, sizeof(buffer));
        buffer[length] = '\r'; buffer[length + 1] = '\n';
        send_reply(reinterpret_cast<const uint8_t*>(buffer), length + 2, nullptr, 0);
        return;
    }
    // Larger than any control-center reply: stream it through the same bound.
    String text; serializeJson(doc, text);
    send_reply(reinterpret_cast<const uint8_t*>(text.c_str()), text.length(), kLineEnd, sizeof(kLineEnd));
}

void cc_send_line(const char* text) {
    const size_t length = strlen(text);
    if (length + 2 <= sizeof(buffer)) {
        memcpy(buffer, text, length);
        buffer[length] = '\r'; buffer[length + 1] = '\n';
        send_reply(reinterpret_cast<const uint8_t*>(buffer), length + 2, nullptr, 0);
        return;
    }
    send_reply(reinterpret_cast<const uint8_t*>(text), length, kLineEnd, sizeof(kLineEnd));
}

uint32_t cc_tx_stalls() { return stalls; }
uint32_t cc_tx_dropped_bytes() { return dropped; }
