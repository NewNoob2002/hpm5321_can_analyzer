cmake_minimum_required(VERSION 3.13)

set(CONFIG_CHERRYUSB 1)
set(CONFIG_CHERRYUSB_DEVICE 1)
set(CONFIG_USB_DEVICE 1)

find_package(hpm-sdk REQUIRED HINTS $ENV{HPM_SDK_BASE})
project(hpm5321_usb_hs_probe)

sdk_compile_definitions(-DDOUBLE_WINUSB=0)
sdk_inc(config)
sdk_app_src(src/main.c)
sdk_app_src(src/usb_vendor_probe.c)

generate_ide_projects()
