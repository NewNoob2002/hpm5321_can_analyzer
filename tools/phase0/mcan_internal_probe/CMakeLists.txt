cmake_minimum_required(VERSION 3.13)

find_package(hpm-sdk REQUIRED HINTS $ENV{HPM_SDK_BASE})
project(hpm5321_mcan_internal_probe)

sdk_app_src(src/main.c)
generate_ide_projects()
