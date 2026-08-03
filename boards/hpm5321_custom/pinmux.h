/*
 * Copyright (c) 2026 HPMicro
 *
 * SPDX-License-Identifier: BSD-3-Clause
 *
 */

#ifndef HPM_PINMUX_H
#define HPM_PINMUX_H

#ifdef __cplusplus
extern "C" {
#endif

void init_pins(void);
void init_uart0_pins(void);
void init_usb0_pins(void);
void disconnect_mcan_pins(void);
void init_mcan_safe_gpio_inputs(void);
void init_mcan0_pins(void);
void init_mcan2_pins(void);
void init_spi2_pins(void);
void init_board_gpio_pins(void);

#ifdef __cplusplus
}
#endif

#endif /* HPM_PINMUX_H */
