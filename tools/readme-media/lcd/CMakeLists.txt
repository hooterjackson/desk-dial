# Headless renderers for the README media, built from the knob firmware's own sources (never edited here):
#   knob-anim        the LCD renderer (cc_display.cpp and friends on LVGL 9.0.0) on a fake tick
#   app-canvas-anim  the Onshape app canvas (Karl Malota's UI, cc_app_*.cpp/.c) on a fake tick, one frame per step
#   haptic-trace     the feel laws (cc_haptic_fx.h) and the harness's knob model: torque against angle traces
#   sound-dump       the click bank (audio/cc_sound.h) rendered to raw int16 samples
# All headless: no window, no device, no network.
#
# Configure with:
#   -DFIRMWARE_DIR=<knob firmware checkout>   (src/, include/lv_conf.h, .pio/libdeps/nanofoc_d/)
#   -DHARNESS_DIR=<host LCD harness>          (tjpgd_shim/: the ESP ROM TJpgDec API on LVGL's TJpgDec)
#   -DLV_CONF_DIR=<dir with the host lv_conf.h> (written by build_lcd.py from the firmware file)
#   -DREADME_NO_LOGO=ON                       (app-canvas-anim draws a text badge instead of the Onshape icon)
cmake_minimum_required(VERSION 3.20)
project(readme_media LANGUAGES C CXX)
set(CMAKE_C_STANDARD 11)

set(FIRMWARE_DIR "" CACHE PATH "Knob firmware checkout")
set(HARNESS_DIR "" CACHE PATH "Host LCD harness (tjpgd_shim/)")
set(LV_CONF_DIR "" CACHE PATH "Directory holding the host lv_conf.h")
option(README_NO_LOGO "app-canvas-anim: replace the Onshape icon with a plain text badge" OFF)
foreach(var FIRMWARE_DIR HARNESS_DIR LV_CONF_DIR)
  if(NOT IS_DIRECTORY "${${var}}")
    message(FATAL_ERROR "${var} must point at an existing directory")
  endif()
endforeach()

set(SRC "${FIRMWARE_DIR}/src")
set(LVGL "${FIRMWARE_DIR}/.pio/libdeps/nanofoc_d/lvgl")
set(ARDUINOJSON "${FIRMWARE_DIR}/.pio/libdeps/nanofoc_d/ArduinoJson/src")
set(SHIM "${HARNESS_DIR}/tjpgd_shim")

# ---------------------------------------------------------------- LVGL 9.0.0 as the firmware pins it
file(GLOB_RECURSE LVGL_SOURCES "${LVGL}/src/*.c")
add_library(lvgl STATIC ${LVGL_SOURCES})
target_include_directories(lvgl SYSTEM PUBLIC "${LVGL}" "${LV_CONF_DIR}")
target_compile_definitions(lvgl PUBLIC LV_CONF_INCLUDE_SIMPLE LV_LVGL_H_INCLUDE_SIMPLE _CRT_SECURE_NO_WARNINGS)
if(MSVC)
  target_compile_options(lvgl PRIVATE /W0)
endif()

# ---------------------------------------------------------------- the firmware LCD units, unchanged
# Same set as the harness (work/lcd-preview/CMakeLists.txt firmware_shared): cc5.7's cc_display.cpp calls
# cc_crumbs.cpp (arc breadcrumbs) and cc_icon_morph.cpp (the Play/Pause morph).
file(GLOB CC_FONTS "${SRC}/fonts/cc_font_*.c")
if(NOT CC_FONTS)
  message(FATAL_ERROR "No generated fonts under ${SRC}/fonts")
endif()
add_library(firmware_lcd OBJECT
  "${SRC}/cc_display.cpp" "${SRC}/cc_icons.cpp" "${SRC}/cc_icon_morph.cpp" "${SRC}/cc_crumbs.cpp"
  "${SRC}/cc_frame_parse.cpp" ${CC_FONTS})
set_target_properties(firmware_lcd PROPERTIES CXX_STANDARD 14 CXX_STANDARD_REQUIRED ON)
target_include_directories(firmware_lcd PUBLIC "${SRC}")
target_include_directories(firmware_lcd SYSTEM PUBLIC "${ARDUINOJSON}")
target_link_libraries(firmware_lcd PUBLIC lvgl)
if(MSVC)
  target_compile_options(firmware_lcd PRIVATE /EHsc)
endif()

add_library(jpeg_glue OBJECT "${SRC}/cc_jpeg.cpp")
target_include_directories(jpeg_glue BEFORE PUBLIC "${SHIM}")
target_include_directories(jpeg_glue PUBLIC "${SRC}")
target_include_directories(jpeg_glue SYSTEM PRIVATE "${LVGL}/src/libs/tjpgd")
set_target_properties(jpeg_glue PROPERTIES CXX_STANDARD 14 CXX_STANDARD_REQUIRED ON)
target_link_libraries(jpeg_glue PUBLIC lvgl)

add_executable(knob-anim knob_anim.cpp)
set_target_properties(knob-anim PROPERTIES CXX_STANDARD 17 CXX_STANDARD_REQUIRED ON)
target_link_libraries(knob-anim PRIVATE firmware_lcd jpeg_glue lvgl)
if(MSVC)
  target_compile_options(knob-anim PRIVATE /EHsc /utf-8)
endif()

# ---------------------------------------------------------------- the Onshape app canvas (no LVGL)
# The same units work/lcd-preview/app_canvas_tests.py compiles: the C++ canvas and the C data (compiled as C).
if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/app_canvas_anim.cpp")
  # The Onshape icon arrays are const (cc_app_icons.c:7, :82), so README_NO_LOGO swaps the source: the generated
  # app_icons_nologo.c (gen_nologo_icons.py: a plain hexagon outline in the icon's colours) defines the same symbols.
  if(README_NO_LOGO)
    set(APP_ICONS "${CMAKE_CURRENT_SOURCE_DIR}/app_icons_nologo.c")
  else()
    set(APP_ICONS "${SRC}/cc_app_icons.c")
  endif()
  add_library(firmware_app OBJECT
    "${SRC}/cc_frame_parse.cpp" "${SRC}/cc_app_canvas.cpp" "${SRC}/cc_app_gfx.cpp" "${SRC}/cc_app_fonts.cpp"
    "${SRC}/cc_app_shape.cpp" "${SRC}/cc_app_cards.cpp" "${SRC}/cc_app_screens.cpp"
    "${SRC}/cc_app_onshape.c" "${APP_ICONS}")
  set_target_properties(firmware_app PROPERTIES CXX_STANDARD 14 CXX_STANDARD_REQUIRED ON)
  target_include_directories(firmware_app PUBLIC "${SRC}")
  target_include_directories(firmware_app SYSTEM PUBLIC "${ARDUINOJSON}")
  target_compile_definitions(firmware_app PUBLIC _CRT_SECURE_NO_WARNINGS)
  if(MSVC)
    target_compile_options(firmware_app PRIVATE /EHsc)
  endif()
  add_executable(app-canvas-anim app_canvas_anim.cpp)
  set_target_properties(app-canvas-anim PROPERTIES CXX_STANDARD 17 CXX_STANDARD_REQUIRED ON)
  target_link_libraries(app-canvas-anim PRIVATE firmware_app)
  if(README_NO_LOGO)
    target_compile_definitions(app-canvas-anim PRIVATE README_NO_LOGO=1)
  endif()
  if(MSVC)
    target_compile_options(app-canvas-anim PRIVATE /EHsc /utf-8)
  endif()
endif()

# ---------------------------------------------------------------- feel traces and the sound bank (header-only firmware)
if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/haptic_trace.cpp")
  add_executable(haptic-trace haptic_trace.cpp)
  set_target_properties(haptic-trace PROPERTIES CXX_STANDARD 17 CXX_STANDARD_REQUIRED ON)
  target_include_directories(haptic-trace PRIVATE "${SRC}")
  target_compile_definitions(haptic-trace PRIVATE _CRT_SECURE_NO_WARNINGS)
  if(MSVC)
    target_compile_options(haptic-trace PRIVATE /EHsc /utf-8)
  endif()
endif()
if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/sound_dump.cpp")
  add_executable(sound-dump sound_dump.cpp)
  set_target_properties(sound-dump PROPERTIES CXX_STANDARD 17 CXX_STANDARD_REQUIRED ON)
  target_include_directories(sound-dump PRIVATE "${SRC}")
  target_compile_definitions(sound-dump PRIVATE _CRT_SECURE_NO_WARNINGS)
  if(MSVC)
    target_compile_options(sound-dump PRIVATE /EHsc /utf-8)
  endif()
endif()
