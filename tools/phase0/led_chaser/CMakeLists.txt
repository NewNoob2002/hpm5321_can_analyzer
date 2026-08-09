cmake_minimum_required(VERSION 3.13)

set(LED_CHASER_STEP_MS 250 CACHE STRING "LED chaser step duration in milliseconds")

find_package(hpm-sdk REQUIRED HINTS $ENV{HPM_SDK_BASE})
project(hpm5321_led_chaser)

sdk_compile_definitions(-DLED_CHASER_STEP_MS=${LED_CHASER_STEP_MS})
sdk_app_src(src/main.c)

generate_ide_projects()
