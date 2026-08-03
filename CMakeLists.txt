# Copyright (c) 2021 HPMicro
# SPDX-License-Identifier: BSD-3-Clause

cmake_minimum_required(VERSION 3.13)

set(CONFIG_FREERTOS 1)
set(CONFIG_SEGGER_RTT 1)

find_package(hpm-sdk REQUIRED HINTS $ENV{HPM_SDK_BASE})

project(hpm5321_can_analyzer)

sdk_compile_definitions(
    -DCONFIG_NDEBUG_CONSOLE=1
    $<$<CONFIG:Debug>:DEBUG>
)

sdk_inc(USER/inc)
sdk_app_src(USER/src/main.c)

add_subdirectory(third_party/easylogger)
target_link_libraries(app PRIVATE easylogger)



generate_ide_projects()
