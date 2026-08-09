# Copyright (c) 2021 HPMicro
# SPDX-License-Identifier: BSD-3-Clause

cmake_minimum_required(VERSION 3.13)

set(CONFIG_FREERTOS 1)
set(CONFIG_FREERTOS_HEAP custom)
set(CONFIG_SEGGER_RTT 1)

set(APP_FAULT_INJECT_REASON "0" CACHE STRING
    "Direct P2 fault-hook injection: 0=off, 1=assert, 2=stack hook, 3=malloc hook")
set_property(CACHE APP_FAULT_INJECT_REASON PROPERTY STRINGS 0 1 2 3)
if(NOT APP_FAULT_INJECT_REASON MATCHES "^[0-3]$")
    message(FATAL_ERROR "APP_FAULT_INJECT_REASON must be 0, 1, 2, or 3")
endif()

find_package(hpm-sdk REQUIRED HINTS $ENV{HPM_SDK_BASE})

project(hpm5321_can_analyzer)

sdk_compile_definitions(
    -DCONFIG_NDEBUG_CONSOLE=1
    -DUSE_SYSCALL_INTERRUPT_PRIORITY=1
    -DAPP_FAULT_INJECT_REASON=${APP_FAULT_INJECT_REASON}
    $<$<CONFIG:Debug>:DEBUG>
)

foreach(allocation_symbol malloc calloc realloc free
                          _malloc_r _calloc_r _realloc_r _free_r)
    sdk_ld_options("-Wl,--wrap=${allocation_symbol}")
endforeach()

sdk_inc(USER/inc)
sdk_app_src(USER/src/app_allocation.c)
sdk_app_src(USER/src/app_health.c)
sdk_app_src(USER/src/app_time.c)
sdk_app_src(USER/src/app_time_core.c)
sdk_app_src(USER/src/app_watchdog.c)
sdk_app_src(USER/src/freertos_hooks.c)
sdk_app_src(USER/src/main.c)

add_subdirectory(third_party/easylogger)
target_link_libraries(app PRIVATE easylogger)



generate_ide_projects()
