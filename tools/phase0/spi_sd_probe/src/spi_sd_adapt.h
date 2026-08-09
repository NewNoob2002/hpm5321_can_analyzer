/*
 * Copyright (c) 2023 HPMicro
 *
 * SPDX-License-Identifier: BSD-3-Clause
 */

#ifndef SPI_SD_ADAPT_H
#define SPI_SD_ADAPT_H

#include "hpm_common.h"

typedef struct {
    uint32_t command_count;
    uint32_t last_command;
    uint32_t last_argument;
    uint32_t byte_exchange_count;
    uint32_t last_tx;
    uint32_t last_rx;
    uint32_t non_ff_rx_count;
    uint32_t last_non_ff_rx;
} spi_sd_probe_bus_diagnostics_t;

extern volatile spi_sd_probe_bus_diagnostics_t g_spi_sd_bus_diagnostics;

hpm_stat_t spi_sd_init(void);

#endif
