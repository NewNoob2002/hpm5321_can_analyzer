# Copyright (c) 2021 HPMicro
# SPDX-License-Identifier: BSD-3-Clause

cmake_minimum_required(VERSION 3.13)

set(CONFIG_FREERTOS 1)
set(CONFIG_FREERTOS_HEAP custom)
set(CONFIG_CHERRYUSB 1)
set(CONFIG_CHERRYUSB_DEVICE 1)
set(CONFIG_USB_DEVICE 1)

option(APP_USB_FORCE_FULL_SPEED
    "Force the USB device controller to enumerate at Full Speed for P3A qualification"
    OFF)

set(APP_FIRMWARE_VERSION "0.1.0-dev" CACHE STRING
    "Firmware semantic version reported by the P2 UART boot banner")
if(NOT APP_FIRMWARE_VERSION MATCHES "^[0-9]+[.][0-9]+[.][0-9]+(-[0-9A-Za-z.-]+)?$")
    message(FATAL_ERROR "APP_FIRMWARE_VERSION must be a semantic version")
endif()
set(APP_BOARD_REVISION "Gerber_PCB1_2026-07-23" CACHE STRING
    "PCB revision reported by the product firmware boot banner")
if(APP_BOARD_REVISION STREQUAL "")
    message(FATAL_ERROR "APP_BOARD_REVISION must not be empty")
endif()

set(APP_FAULT_INJECT_REASON "0" CACHE STRING
    "Direct P2 fault-hook injection: 0=off, 1=assert, 2=stack hook, 3=malloc hook")
set_property(CACHE APP_FAULT_INJECT_REASON PROPERTY STRINGS 0 1 2 3)
if(NOT APP_FAULT_INJECT_REASON MATCHES "^[0-3]$")
    message(FATAL_ERROR "APP_FAULT_INJECT_REASON must be 0, 1, 2, or 3")
endif()

find_package(hpm-sdk REQUIRED HINTS $ENV{HPM_SDK_BASE})

project(hpm5321_can_analyzer)

if(APP_USB_FORCE_FULL_SPEED)
    sdk_compile_definitions(-DCONFIG_USB_DEVICE_FORCE_FULL_SPEED)
endif()

# The SDK adds CherryUSB's dynamic FreeRTOS OSAL and OTG translation units
# unconditionally. This device-only slice uses neither surface and removes both
# so no dynamic RTOS API is present in the firmware image.
get_property(APP_HPM_SDK_SOURCES TARGET ${HPM_SDK_LIB} PROPERTY SOURCES)
list(REMOVE_ITEM APP_HPM_SDK_SOURCES
    "${HPM_SDK_BASE}/middleware/cherryusb/osal/usb_osal_freertos.c"
    "${HPM_SDK_BASE}/middleware/cherryusb/core/usbotg_core.c")
set_property(TARGET ${HPM_SDK_LIB} PROPERTY SOURCES "${APP_HPM_SDK_SOURCES}")

# EasyLogger owns RTT directly. Do not enable the SDK RTT syscall layer because
# libc stdout is reserved for the UART debug console.
set(APP_SEGGER_RTT_ROOT "${HPM_SDK_BASE}/middleware/segger_rtt")
sdk_inc(${APP_SEGGER_RTT_ROOT}/Config ${APP_SEGGER_RTT_ROOT}/RTT)
sdk_src(${APP_SEGGER_RTT_ROOT}/RTT/SEGGER_RTT.c)
# Keep RTT available to EasyLogger, but remove its newlib syscall shim so the
# SDK debug console remains the sole libc stdout owner.
get_property(APP_HPM_SDK_GCC_SOURCES TARGET ${HPM_SDK_GCC_LIB} PROPERTY SOURCES)
list(REMOVE_ITEM APP_HPM_SDK_GCC_SOURCES
    "${APP_SEGGER_RTT_ROOT}/Syscalls/SEGGER_RTT_Syscalls_GCC.c")
set_property(TARGET ${HPM_SDK_GCC_LIB} PROPERTY SOURCES
    "${APP_HPM_SDK_GCC_SOURCES}")

# The SDK forces float-capable printf/scanf into every GCC image when nano.specs
# is enabled. This product uses integer/string formatting only, and the forced
# objects overflow the 128 KiB ILM in the RAM Debug preset. Keep nano.specs, but
# remove the two unused force-link options from this application's SDK
# interface.
get_property(APP_HPM_SDK_LINK_LIBRARIES
    TARGET ${HPM_SDK_LIB_ITF} PROPERTY INTERFACE_LINK_LIBRARIES)
list(REMOVE_ITEM APP_HPM_SDK_LINK_LIBRARIES
    "-u _printf_float"
    "-u _scanf_float")
set_property(TARGET ${HPM_SDK_LIB_ITF} PROPERTY INTERFACE_LINK_LIBRARIES
    "${APP_HPM_SDK_LINK_LIBRARIES}")

sdk_compile_definitions(
    -DCONFIG_NDEBUG_CONSOLE=0
    -DAPP_FIRMWARE_VERSION=\"${APP_FIRMWARE_VERSION}\"
    -DAPP_BOARD_REVISION=\"${APP_BOARD_REVISION}\"
    -DUSE_SYSCALL_INTERRUPT_PRIORITY=1
    -DAPP_FAULT_INJECT_REASON=${APP_FAULT_INJECT_REASON}
    $<$<CONFIG:Debug>:DEBUG>
)

foreach(allocation_symbol malloc calloc realloc free
                          _malloc_r _calloc_r _realloc_r _free_r)
    sdk_ld_options("-Wl,--wrap=${allocation_symbol}")
endforeach()

sdk_inc(config)
sdk_inc(USER/inc)
sdk_inc(protocol/v1/c)
sdk_app_src(protocol/v1/c/ucan_codec.c)
sdk_app_src(protocol/v1/c/ucan_session.c)
sdk_app_src(USER/src/app_allocation.c)
sdk_app_src(USER/src/app_health.c)
sdk_app_src(USER/src/app_mcan0_owner.c)
sdk_app_src(USER/src/app_time.c)
sdk_app_src(USER/src/app_time_core.c)
sdk_app_src(USER/src/app_usb_owner.c)
sdk_app_src(USER/src/app_watchdog.c)
sdk_app_src(USER/src/freertos_hooks.c)
sdk_app_src(USER/src/main.c)

add_subdirectory(third_party/easylogger)
target_link_libraries(app PRIVATE easylogger)



generate_ide_projects()
