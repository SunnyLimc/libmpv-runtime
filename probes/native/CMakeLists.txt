cmake_minimum_required(VERSION 3.20)
project(libmpv_runtime_probe LANGUAGES C)

add_executable(mpv_dsp_probe mpv_dsp_probe.c)
set_target_properties(mpv_dsp_probe PROPERTIES C_STANDARD 11 C_STANDARD_REQUIRED YES)

if(UNIX AND NOT APPLE AND NOT ANDROID)
  target_link_libraries(mpv_dsp_probe PRIVATE dl)
endif()

if(MSVC)
  target_compile_definitions(mpv_dsp_probe PRIVATE _CRT_SECURE_NO_WARNINGS)
  target_compile_options(mpv_dsp_probe PRIVATE /W4 /WX)
else()
  target_compile_options(mpv_dsp_probe PRIVATE -Wall -Wextra -Werror)
endif()
