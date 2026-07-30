cmake_minimum_required(VERSION 3.18)

set(Src
        ${CMAKE_CURRENT_SOURCE_DIR}/src/elog.c
        ${CMAKE_CURRENT_SOURCE_DIR}/src/elog_utils.c
        ${CMAKE_CURRENT_SOURCE_DIR}/port/elog_port.c
)

set(Include_Dirs
        ${CMAKE_CURRENT_SOURCE_DIR}/inc
        ${CMAKE_CURRENT_SOURCE_DIR}/port
)

add_library(easylogger STATIC ${Src})
target_include_directories(easylogger
        PUBLIC
        ${Include_Dirs}
)
target_compile_definitions(easylogger
        PUBLIC
        $<$<CONFIG:Debug>:ELOG_PORT_USING_FREERTOS>
)
target_link_libraries(easylogger
        PUBLIC
        ${HPM_SDK_LIB_ITF}
)

message(STATUS "  - easylogger 库已配置")
