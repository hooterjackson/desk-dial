#pragma once

#include <Arduino.h>
#include "foc_thread.h"
#include "com_thread.h"
#include <lvgl.h>
#include "thread_crtp.h"
#include "ui.h"



typedef enum {
    LCD_LAYOUT_DEFAULT = 0x00,
    LCD_LAYOUT_MESSAGE = 0x01,
    LCD_LAYOUT_MENU = 0x02     // TODO future menu mode
} LcdLayoutType;


// FW-BUG-006: the command carries its text by value. The COM task copies it in (com_thread.cpp
// lcd_text(), cut at a UTF-8 boundary); this task never reads a String the COM task may reassign.
// "" is an empty field (the old nullptr or empty String).
#define CC_LCD_COMMAND_BY_VALUE 1
constexpr size_t kLcdTitleBytes = 48;
constexpr size_t kLcdDataBytes = 96;

class LcdCommand {
public:
    LcdLayoutType type = LCD_LAYOUT_DEFAULT;
    char title[kLcdTitleBytes] = {};
    char data1[kLcdDataBytes] = {};
    char data2[kLcdDataBytes] = {};
    char data3[kLcdDataBytes] = {};
    char data4[kLcdDataBytes] = {};
};



class LcdThread : public Thread<LcdThread> {
    friend class Thread<LcdThread>; //Allow Base Thread to invoke protected run()

    public:
        LcdThread(const uint8_t task_core);
        ~LcdThread();
        
        void put_lcd_command(LcdCommand& cmd);
        void handleLcdCommand();
        LcdCommand last_command;
        
    protected:
        void run();
        
    private:
        QueueHandle_t _q_lcd_in;
};

extern LcdThread lcd_thread;
