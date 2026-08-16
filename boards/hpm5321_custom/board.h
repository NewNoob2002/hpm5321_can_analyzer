/*
 * Copyright (c) 2026 HPMicro
 *
 * SPDX-License-Identifier: BSD-3-Clause
 *
 */

#ifndef HPM_BOARD_H
#define HPM_BOARD_H

#include "hpm_clock_drv.h"
#include "hpm_common.h"
#include "hpm_soc.h"
#include "pinmux.h"
#include <stdbool.h>
#include <stdint.h>

#if !defined(CONFIG_NDEBUG_CONSOLE) || !CONFIG_NDEBUG_CONSOLE
#include "hpm_debug_console.h"
#endif

#define BOARD_NAME "hpm5321_custom"
#define BOARD_UF2_SIGNATURE (0x0A4D5048UL)
#define BOARD_DFU_SIGNATURE (0x48504D21UL)

#ifndef BOARD_RUNNING_CORE
#define BOARD_RUNNING_CORE HPM_CORE0
#endif

/* Debug console: UART0 on PA00/PA01. */
#if !defined(CONFIG_NDEBUG_CONSOLE) || !CONFIG_NDEBUG_CONSOLE
#ifndef BOARD_CONSOLE_TYPE
#define BOARD_CONSOLE_TYPE CONSOLE_TYPE_UART
#endif
#define BOARD_CONSOLE_UART_BASE HPM_UART0
#define BOARD_CONSOLE_UART_CLK_NAME clock_uart0
#define BOARD_CONSOLE_UART_IRQ IRQn_UART0
#define BOARD_CONSOLE_UART_TX_DMA_REQ HPM_DMA_SRC_UART0_TX
#define BOARD_CONSOLE_UART_RX_DMA_REQ HPM_DMA_SRC_UART0_RX
#define BOARD_CONSOLE_UART_BAUDRATE (921600UL)
#endif

/* On-chip flash. */
#define BOARD_FLASH_BASE_ADDRESS (0x80000000UL)
#define BOARD_FLASH_SIZE (SIZE_1MB)

/* Status LED: PA31, active low. */
#define BOARD_LED_GPIO_NAME "PA31"
#define BOARD_LED_GPIO_CTRL HPM_GPIO0
#define BOARD_LED_GPIO_INDEX GPIO_DO_GPIOA
#define BOARD_LED_GPIO_PIN (31U)
#define BOARD_LED_OFF_LEVEL (1U)
#define BOARD_LED_ON_LEVEL (0U)

/* SD card over SPI2: PB10/PB11/PB12/PB13. */
#define BOARD_APP_SPI_BASE HPM_SPI2
#define BOARD_APP_SPI_CLK_NAME clock_spi2
#define BOARD_APP_SPI_IRQ IRQn_SPI2
#define BOARD_APP_SPI_SCLK_FREQ (20000000UL)
#define BOARD_APP_SPI_ADDR_LEN_IN_BYTES (1U)
#define BOARD_APP_SPI_DATA_LEN_IN_BITS (8U)
#define BOARD_APP_SPI_RX_DMA HPM_DMA_SRC_SPI2_RX
#define BOARD_APP_SPI_TX_DMA HPM_DMA_SRC_SPI2_TX
#define BOARD_SPI_CS_GPIO_CTRL HPM_GPIO0
#define BOARD_SPI_CS_PIN IOC_PAD_PB10
#define BOARD_SPI_CS_ACTIVE_LEVEL (0U)

/* SD card detect: PY00. Adjust the present level if the socket is active high.
 */
#define BOARD_SD_DETECT_GPIO_CTRL HPM_GPIO0
#define BOARD_SD_DETECT_GPIO_INDEX GPIO_DI_GPIOY
#define BOARD_SD_DETECT_GPIO_PIN (0U)
#define BOARD_SD_DETECT_PRESENT_LEVEL (0U)

/* MCAN0 on PB00/PB01 and MCAN2 on PB08/PB09. */
#define BOARD_APP_CAN_BASE HPM_MCAN0
#define BOARD_APP_CAN_IRQn IRQn_MCAN0
#define BOARD_CAN0_BASE HPM_MCAN0
#define BOARD_CAN0_IRQn IRQn_MCAN0
#define BOARD_CAN2_BASE HPM_MCAN2
#define BOARD_CAN2_IRQn IRQn_MCAN2

/* Internal board callback timer; no external pin is used. */
#define BOARD_CALLBACK_TIMER HPM_GPTMR3
#define BOARD_CALLBACK_TIMER_CH (1U)
#define BOARD_CALLBACK_TIMER_IRQ IRQn_GPTMR3
#define BOARD_CALLBACK_TIMER_CLK_NAME clock_gptmr3

/* CAN activity LEDs, active low. */
#define BOARD_CAN_LED_ON_LEVEL (0U)
#define BOARD_CAN_LED_OFF_LEVEL (1U)

#define BOARD_CAN0_TX_LED_GPIO_CTRL HPM_GPIO0
#define BOARD_CAN0_TX_LED_GPIO_INDEX GPIO_DO_GPIOY
#define BOARD_CAN0_TX_LED_GPIO_PIN (1U)
#define BOARD_CAN0_RX_LED_GPIO_CTRL HPM_GPIO0
#define BOARD_CAN0_RX_LED_GPIO_INDEX GPIO_DO_GPIOY
#define BOARD_CAN0_RX_LED_GPIO_PIN (2U)
#define BOARD_CAN2_TX_LED_GPIO_CTRL HPM_GPIO0
#define BOARD_CAN2_TX_LED_GPIO_INDEX GPIO_DO_GPIOY
#define BOARD_CAN2_TX_LED_GPIO_PIN (3U)
#define BOARD_CAN2_RX_LED_GPIO_CTRL HPM_GPIO0
#define BOARD_CAN2_RX_LED_GPIO_INDEX GPIO_DO_GPIOA
#define BOARD_CAN2_RX_LED_GPIO_PIN (9U)

#ifndef BOARD_SHOW_CLOCK
#define BOARD_SHOW_CLOCK (1U)
#endif
#ifndef BOARD_SHOW_BANNER
#define BOARD_SHOW_BANNER (1U)
#endif

#ifdef __cplusplus
extern "C" {
#endif

typedef void (*board_timer_cb)(void);

void board_init(void);
void board_init_clock(void);
void board_init_console(void);
void board_init_pmp(void);
void board_init_usb_dp_dm_pins(void);
void board_init_usb(USB_Type *ptr);
void board_init_uart(UART_Type *ptr);
uint32_t board_init_uart_clock(UART_Type *ptr);
void board_init_can(MCAN_Type *ptr);
void board_disconnect_can(MCAN_Type *ptr);
bool board_can_pads_are_disconnected(MCAN_Type *ptr);
uint32_t board_init_can_clock(MCAN_Type *ptr);
void board_init_spi_pins(SPI_Type *ptr);
void board_init_spi_pins_with_gpio_as_cs(SPI_Type *ptr);
uint32_t board_init_spi_clock(SPI_Type *ptr);
void board_write_spi_cs(uint32_t pin, uint8_t state);
void board_init_led_pins(void);
void board_led_write(uint8_t state);
void board_led_toggle(void);
uint8_t board_get_led_gpio_off_level(void);
bool board_is_sd_card_present(void);
void board_delay_us(uint32_t us);
void board_delay_ms(uint32_t ms);
void board_timer_create(uint32_t ms, board_timer_cb cb);
void board_ungate_mchtmr_at_lp_mode(void);

#ifdef __cplusplus
}
#endif

#endif /* HPM_BOARD_H */
