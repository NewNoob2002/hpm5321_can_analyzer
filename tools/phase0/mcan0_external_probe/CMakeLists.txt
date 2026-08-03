cmake_minimum_required(VERSION 3.13)

if(NOT DEFINED MCAN0_ACTIVE_TX)
    set(MCAN0_ACTIVE_TX 0)
endif()
if(NOT DEFINED MCAN0_REQUIRE_RX)
    set(MCAN0_REQUIRE_RX 0)
endif()
if(NOT DEFINED MCAN0_ACK_RX)
    set(MCAN0_ACK_RX 0)
endif()

foreach(flag MCAN0_ACTIVE_TX MCAN0_REQUIRE_RX MCAN0_ACK_RX)
    if(NOT "${${flag}}" MATCHES "^[01]$")
        message(FATAL_ERROR "${flag} must be exactly 0 or 1 (got '${${flag}}')")
    endif()
endforeach()
if(MCAN0_ACTIVE_TX AND (MCAN0_REQUIRE_RX OR MCAN0_ACK_RX))
    message(FATAL_ERROR "MCAN0_ACTIVE_TX cannot be combined with RX-proof options")
endif()
if(MCAN0_ACK_RX AND NOT MCAN0_REQUIRE_RX)
    message(FATAL_ERROR "MCAN0_ACK_RX requires MCAN0_REQUIRE_RX=1")
endif()

find_package(hpm-sdk REQUIRED HINTS $ENV{HPM_SDK_BASE})
project(hpm5321_mcan0_external_probe)

sdk_compile_definitions(
    -DMCAN0_ACTIVE_TX=${MCAN0_ACTIVE_TX}
    -DMCAN0_REQUIRE_RX=${MCAN0_REQUIRE_RX}
    -DMCAN0_ACK_RX=${MCAN0_ACK_RX}
)
# Normalize absolute workspace, build and SDK paths embedded in DWARF so a
# clean checkout can reproduce the attested ELF byte-for-byte.
get_filename_component(REPOSITORY_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../../.." ABSOLUTE)
foreach(prefix "${REPOSITORY_ROOT}" "${CMAKE_BINARY_DIR}" "$ENV{HPM_SDK_BASE}")
    sdk_compile_options(-ffile-prefix-map=${prefix}=.)
    sdk_compile_options(-fmacro-prefix-map=${prefix}=.)
endforeach()
sdk_app_src(src/main.c)
generate_ide_projects()
