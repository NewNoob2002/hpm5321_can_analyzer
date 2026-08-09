cmake_minimum_required(VERSION 3.13)

set(CONFIG_SDMMC 1)
set(CONFIG_HPM_SPI_SDCARD 1)
set(CONFIG_FATFS 1)
set(CONFIG_HPM_SPI 1)
set(CONFIG_DMA_MGR 1)

find_package(hpm-sdk REQUIRED HINTS $ENV{HPM_SDK_BASE})
project(hpm5321_spi_sd_probe)

sdk_compile_definitions(-DUSE_DMA_TRANSFER=0)
sdk_compile_definitions(-DFF_CODE_PAGE=437)
sdk_compile_definitions(-DSPI_SD_LOG=printf)
sdk_compile_definitions(-DSPI_SD_SPEED_MAX_HZ=20000000)

sdk_inc(src)
sdk_app_src(src/spi_sd_adapt.c)
sdk_app_src(src/main.c)

generate_ide_projects()
