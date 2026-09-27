# knob-anim: renders scripted frame sequences with the knob firmware's own LCD renderer
# (src/cc_display.cpp, cc_frame_parse.cpp, cc_icons.cpp, cc_jpeg.cpp and the generated fonts) on
# LVGL 9.0.0 with the firmware's lv_conf.h, on a steppable fake tick. Headless: no window, no device.
#
# Configure with:
#   -DFIRMWARE_DIR=<knob firmware checkout>   (src/, include/lv_conf.h, .pio/libdeps/nanofoc_d/)
#   -DHARNESS_DIR=<host LCD harness>          (tjpgd_shim/: the ESP ROM TJpgDec API on LVGL's TJpgDec)
#   -DLV_CONF_DIR=<dir with the host lv_conf.h> (written by render_media.py from the firmware file)
cmake_minimum_required(VERSION 3.20)
project(knob_anim LANGUAGES C CXX)
set(CMAKE_C_STANDARD 11)

set(FIRMWARE_DIR "" CACHE PATH "Knob firmware checkout")
set(HARNESS_DIR "" CACHE PATH "Host LCD harness (tjpgd_shim/)")
set(LV_CONF_DIR "" CACHE PATH "Directory holding the host lv_conf.h")
foreach(var FIRMWARE_DIR HARNESS_DIR LV_CONF_DIR)
  if(NOT IS_DIRECTORY "${${var}}")
    message(FATAL_ERROR "${var} must point at an existing directory")
  endif()
endforeach()

set(SRC "${FIRMWARE_DIR}/src")
set(LVGL "${FIRMWARE_DIR}/.pio/libdeps/nanofoc_d/lvgl")
set(ARDUINOJSON "${FIRMWARE_DIR}/.pio/libdeps/nanofoc_d/ArduinoJson/src")
set(SHIM "${HARNESS_DIR}/tjpgd_shim")

file(GLOB_RECURSE LVGL_SOURCES "${LVGL}/src/*.c")
add_library(lvgl STATIC ${LVGL_SOURCES})
target_include_directories(lvgl SYSTEM PUBLIC "${LVGL}" "${LV_CONF_DIR}")
target_compile_definitions(lvgl PUBLIC LV_CONF_INCLUDE_SIMPLE LV_LVGL_H_INCLUDE_SIMPLE _CRT_SECURE_NO_WARNINGS)
if(MSVC)
  target_compile_options(lvgl PRIVATE /W0)
endif()

file(GLOB CC_FONTS "${SRC}/fonts/cc_font_*.c")
add_library(firmware_lcd OBJECT "${SRC}/cc_display.cpp" "${SRC}/cc_icons.cpp" "${SRC}/cc_frame_parse.cpp" ${CC_FONTS})
set_target_properties(firmware_lcd PROPERTIES CXX_STANDARD 14 CXX_STANDARD_REQUIRED ON)
target_include_directories(firmware_lcd PUBLIC "${SRC}")
target_include_directories(firmware_lcd SYSTEM PUBLIC "${ARDUINOJSON}")
target_link_libraries(firmware_lcd PUBLIC lvgl)

add_library(jpeg_glue OBJECT "${SRC}/cc_jpeg.cpp")
target_include_directories(jpeg_glue BEFORE PUBLIC "${SHIM}")
target_include_directories(jpeg_glue PUBLIC "${SRC}")
target_include_directories(jpeg_glue SYSTEM PRIVATE "${LVGL}/src/libs/tjpgd")
set_target_properties(jpeg_glue PROPERTIES CXX_STANDARD 14 CXX_STANDARD_REQUIRED ON)
target_link_libraries(jpeg_glue PUBLIC lvgl)

if(MSVC)
  target_compile_options(firmware_lcd PRIVATE /EHsc)
endif()

add_executable(knob-anim knob_anim.cpp)
set_target_properties(knob-anim PROPERTIES CXX_STANDARD 17 CXX_STANDARD_REQUIRED ON)
target_link_libraries(knob-anim PRIVATE firmware_lcd jpeg_glue lvgl)
if(MSVC)
  target_compile_options(knob-anim PRIVATE /EHsc /utf-8)
endif()
