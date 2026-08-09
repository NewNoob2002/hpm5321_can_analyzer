/*
 * Copyright (c) 2023 HPMicro
 *
 * SPDX-License-Identifier: BSD-3-Clause
 *
 * Phase 0 polling adapter derived from the HPM SDK SPI-SD sample adapter.
 */

#include "spi_sd_adapt.h"

#include <stdbool.h>
#include <stdio.h>
#include <string.h>

#include "board.h"
#include "hpm_spi.h"
#include "hpm_spi_drv.h"
#include "hpm_spi_sdcard.h"

#define SD_SPI_BASE (BOARD_APP_SPI_BASE)
#define SD_SPI_DATA_LEN_BITS (8U)
#define SD_SPI_TRANSFER_TIMEOUT_MS (1000U)
#define SD_SPI_CMD8 (0x48U)
#define SD_SPI_CMD8_SDK_CRC (0x86U)
#define SD_SPI_CMD8_WIRE_CRC (0x87U)

static hpm_stat_t set_spi_speed(uint32_t freq);
static void cs_select(void);
static void cs_release(void);
static bool sdcard_is_present(void);
static hpm_stat_t write_read_byte(uint8_t *in_byte, uint8_t *out_byte);
static hpm_stat_t write_cmd_data(uint8_t cmd, uint8_t *buffer, uint32_t size);
static hpm_stat_t write_data(uint8_t *buffer, uint32_t size);
static hpm_stat_t read_data(uint8_t *buffer, uint32_t size);

static sdcard_spi_interface_t g_spi_io;
ATTR_PLACE_AT_NONCACHEABLE uint8_t g_tx_dummy[SPI_SD_BLOCK_SIZE];
volatile spi_sd_probe_bus_diagnostics_t g_spi_sd_bus_diagnostics;

hpm_stat_t spi_sd_init(void)
{
    spi_initialize_config_t init_config;
    hpm_stat_t status;

    board_init_spi_clock(SD_SPI_BASE);
    board_init_spi_pins_with_gpio_as_cs(SD_SPI_BASE);

    hpm_spi_get_default_init_config(&init_config);
    init_config.direction = spi_msb_first;
    init_config.mode = spi_master_mode;
    init_config.clk_phase = spi_sclk_sampling_odd_clk_edges;
    init_config.clk_polarity = spi_sclk_low_idle;
    init_config.data_len = SD_SPI_DATA_LEN_BITS;

    status = hpm_spi_initialize(SD_SPI_BASE, &init_config);
    if (status != status_success) {
        printf("[p0s] hpm_spi_initialize failed: %u\n", status);
        return status;
    }
    status = hpm_spi_set_sclk_frequency(SD_SPI_BASE, 400000U);
    if (status != status_success) {
        printf("[p0s] initial SPI frequency failed: %u\n", status);
        return status;
    }

    memset((void *)&g_spi_sd_bus_diagnostics, 0,
           sizeof(g_spi_sd_bus_diagnostics));
    memset(g_tx_dummy, 0xFF, sizeof(g_tx_dummy));
    g_spi_io.set_spi_speed = set_spi_speed;
    g_spi_io.cs_select = cs_select;
    g_spi_io.cs_relese = cs_release;
    g_spi_io.sdcard_is_present = sdcard_is_present;
    g_spi_io.write_read_byte = write_read_byte;
    g_spi_io.write_cmd_data = write_cmd_data;
    g_spi_io.write = write_data;
    g_spi_io.read = read_data;
    g_spi_io.delay_ms = board_delay_ms;
    g_spi_io.delay_us = board_delay_us;
    return sdcard_spi_init(&g_spi_io);
}

static hpm_stat_t set_spi_speed(uint32_t freq)
{
    if (freq > SPI_SD_SPEED_MAX_HZ) {
        freq = SPI_SD_SPEED_MAX_HZ;
    }
    hpm_stat_t status = hpm_spi_set_sclk_frequency(SD_SPI_BASE, freq);
    if (status != status_success) {
        printf("[p0s] SPI frequency %u Hz failed: %u\n", freq, status);
    }
    return status;
}

static void cs_select(void)
{
    board_write_spi_cs(BOARD_SPI_CS_PIN, false);
}

static void cs_release(void)
{
    board_write_spi_cs(BOARD_SPI_CS_PIN, true);
}

static bool sdcard_is_present(void)
{
    return board_is_sd_card_present();
}

static hpm_stat_t write_read_byte(uint8_t *in_byte, uint8_t *out_byte)
{
    hpm_stat_t status = hpm_spi_transmit_receive_blocking(
        SD_SPI_BASE, in_byte, out_byte, 1U, SD_SPI_TRANSFER_TIMEOUT_MS);
    if (status == status_success) {
        ++g_spi_sd_bus_diagnostics.byte_exchange_count;
        g_spi_sd_bus_diagnostics.last_tx = *in_byte;
        g_spi_sd_bus_diagnostics.last_rx = *out_byte;
        if (*out_byte != 0xFFU) {
            ++g_spi_sd_bus_diagnostics.non_ff_rx_count;
            g_spi_sd_bus_diagnostics.last_non_ff_rx = *out_byte;
        }
    }
    return status;
}

static hpm_stat_t write_cmd_data(uint8_t cmd, uint8_t *buffer, uint32_t size)
{
    uint8_t command[6];
    if ((buffer == NULL) || (size > (sizeof(command) - 1U))) {
        return status_invalid_argument;
    }
    command[0] = cmd;
    memcpy(&command[1], buffer, size);
    if ((cmd == SD_SPI_CMD8) && (size == 5U) &&
        (command[5] == SD_SPI_CMD8_SDK_CRC)) {
        command[5] = SD_SPI_CMD8_WIRE_CRC;
    }
    ++g_spi_sd_bus_diagnostics.command_count;
    g_spi_sd_bus_diagnostics.last_command = cmd;
    if (size >= 4U) {
        g_spi_sd_bus_diagnostics.last_argument =
            ((uint32_t)buffer[0] << 24U) | ((uint32_t)buffer[1] << 16U) |
            ((uint32_t)buffer[2] << 8U) | (uint32_t)buffer[3];
    }
    return hpm_spi_transmit_blocking(
        SD_SPI_BASE, command, size + 1U, SD_SPI_TRANSFER_TIMEOUT_MS);
}

static hpm_stat_t write_data(uint8_t *buffer, uint32_t size)
{
    return hpm_spi_transmit_blocking(
        SD_SPI_BASE, buffer, size, SD_SPI_TRANSFER_TIMEOUT_MS);
}

static hpm_stat_t read_data(uint8_t *buffer, uint32_t size)
{
    return hpm_spi_transmit_receive_blocking(
        SD_SPI_BASE, g_tx_dummy, buffer, size, SD_SPI_TRANSFER_TIMEOUT_MS);
}
