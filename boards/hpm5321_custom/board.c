/*
 * Copyright (c) 2026 HPMicro
 *
 * SPDX-License-Identifier: BSD-3-Clause
 *
 */

#include "board.h"
#include "clock.h"
#include "hpm_clock_drv.h"
#include "hpm_gpio_drv.h"
#include "hpm_gptmr_drv.h"
#include "hpm_pcfg_drv.h"
#include "hpm_pllctlv2_drv.h"
#include "hpm_sdk_version.h"
#include "hpm_uart_drv.h"
#include "hpm_usb_drv.h"
#include <stdio.h>

#if defined(FLASH_XIP) && FLASH_XIP
__attribute__((section(".nor_cfg_option"), used))
const uint32_t option[4] = {0xfcf90002U, 0x00000005U, 0x00001000U, 0x0U};
#endif

#if defined(FLASH_UF2) && FLASH_UF2
ATTR_PLACE_AT(".uf2_signature")
__attribute__((used)) const uint32_t uf2_signature = BOARD_UF2_SIGNATURE;
#endif

#if defined(FLASH_DFU) && FLASH_DFU
ATTR_PLACE_AT(".dfu_signature")
__attribute__((used)) const uint32_t dfu_signature = BOARD_DFU_SIGNATURE;
#endif

static void board_print_banner(void) {
#ifdef SDK_VERSION_STRING
  printf("hpm_sdk: %s\n", SDK_VERSION_STRING);
#endif
  printf("board: %s\n", BOARD_NAME);
}

static void board_print_clock_freq(void) {
  printf("==============================\n");
  printf(" %s clock summary\n", BOARD_NAME);
  printf("==============================\n");
  printf("cpu0:\t\t %luHz\n", clock_get_frequency(clock_cpu0));
  printf("ahb:\t\t %luHz\n", clock_get_frequency(clock_ahb));
  printf("mchtmr0:\t %luHz\n", clock_get_frequency(clock_mchtmr0));
  printf("xpi0:\t\t %luHz\n", clock_get_frequency(clock_xpi0));
  printf("==============================\n");
}

void board_init_console(void) {
#if !defined(CONFIG_NDEBUG_CONSOLE) || !CONFIG_NDEBUG_CONSOLE
#if BOARD_CONSOLE_TYPE == CONSOLE_TYPE_UART
  console_config_t cfg;

  init_uart0_pins();
  init_uart0_clock();

  cfg.type = BOARD_CONSOLE_TYPE;
  cfg.base = (uint32_t)BOARD_CONSOLE_UART_BASE;
  cfg.src_freq_in_hz = clock_get_frequency(BOARD_CONSOLE_UART_CLK_NAME);
  cfg.baudrate = BOARD_CONSOLE_UART_BAUDRATE;

  if (console_init(&cfg) != status_success) {
    while (1) {
    }
  }
#endif
#endif
}

void board_init(void) {
  /* First board-level action: disconnect retained MCAN mux state before clock,
   * console or other peripheral initialization. */
  init_mcan_safe_gpio_inputs();
  board_init_clock();
  init_pins();
  board_init_usb_dp_dm_pins();
  board_init_console();
  board_init_pmp();

#if BOARD_SHOW_CLOCK
  board_print_clock_freq();
#endif
#if BOARD_SHOW_BANNER
  board_print_banner();
#endif
}

void board_init_usb_dp_dm_pins(void) {
  while (sysctl_resource_any_is_busy(HPM_SYSCTL)) {
  }

  if (!clock_check_in_group(clock_usb0, 0)) {
    init_usb0_clock();
    usb_phy_disable_dp_dm_pulldown(HPM_USB0);
    clock_remove_from_group(clock_usb0, 0);
  } else {
    usb_phy_disable_dp_dm_pulldown(HPM_USB0);
  }
}

void board_init_clock(void) {
  uint32_t cpu0_freq = clock_get_frequency(clock_cpu0);

  if (cpu0_freq == PLLCTL_SOC_PLL_REFCLK_FREQ) {
    pllctlv2_xtal_set_rampup_time(HPM_PLLCTLV2, 32UL * 1000UL * 9U);
    sysctl_clock_set_preset(HPM_SYSCTL, 2);
  }

  init_board_clock();
  clock_connect_group_to_cpu(0, 0);

  /* Remove this call when the board supplies the core rail from an external
   * DCDC. */
  pcfg_dcdc_set_voltage(HPM_PCFG, 1275);

  sysctl_config_cpu0_domain_clock(HPM_SYSCTL, clock_source_pll0_clk0, 2, 3);
  init_board_clock_source();
  clock_update_core_clock();
}

void board_delay_us(uint32_t us) { clock_cpu_delay_us(us); }

void board_delay_ms(uint32_t ms) { clock_cpu_delay_ms(ms); }

static board_timer_cb timer_cb;

SDK_DECLARE_EXT_ISR_M(BOARD_CALLBACK_TIMER_IRQ, board_timer_isr)
void board_timer_isr(void) {
  uint32_t status = GPTMR_CH_RLD_STAT_MASK(BOARD_CALLBACK_TIMER_CH);

  if (gptmr_check_status(BOARD_CALLBACK_TIMER, status)) {
    gptmr_clear_status(BOARD_CALLBACK_TIMER, status);
    if (timer_cb != NULL) {
      timer_cb();
    }
  }
}

void board_timer_create(uint32_t ms, board_timer_cb cb) {
  gptmr_channel_config_t config;
  uint32_t timer_freq;

  timer_cb = cb;
  gptmr_channel_get_default_config(BOARD_CALLBACK_TIMER, &config);

  init_gptmr3_clock();
  timer_freq = clock_get_frequency(BOARD_CALLBACK_TIMER_CLK_NAME);
  config.reload = timer_freq / 1000U * ms;

  gptmr_channel_config(BOARD_CALLBACK_TIMER, BOARD_CALLBACK_TIMER_CH, &config,
                       false);
  gptmr_enable_irq(BOARD_CALLBACK_TIMER,
                   GPTMR_CH_RLD_IRQ_MASK(BOARD_CALLBACK_TIMER_CH));
  intc_m_enable_irq_with_priority(BOARD_CALLBACK_TIMER_IRQ, 1);
  gptmr_start_counter(BOARD_CALLBACK_TIMER, BOARD_CALLBACK_TIMER_CH);
}

void board_init_usb(USB_Type *ptr) {
  if (ptr == HPM_USB0) {
    init_usb0_pins();
    init_usb0_clock();
  }
}

void board_init_uart(UART_Type *ptr) {
  if (ptr == HPM_UART0) {
    init_uart0_pins();
    (void)board_init_uart_clock(ptr);
  }
}

uint32_t board_init_uart_clock(UART_Type *ptr) {
  if (ptr == HPM_UART0) {
    init_uart0_clock();
    return clock_get_frequency(clock_uart0);
  }
  return 0U;
}

void board_init_can(MCAN_Type *ptr) {
  if (ptr == HPM_MCAN0) {
    init_mcan0_pins();
  } else if (ptr == HPM_MCAN2) {
    init_mcan2_pins();
  }
}

uint32_t board_init_can_clock(MCAN_Type *ptr) {
  if (ptr == HPM_MCAN0) {
    init_can0_clock();
    return clock_get_frequency(clock_can0);
  }
  if (ptr == HPM_MCAN2) {
    init_can2_clock();
    return clock_get_frequency(clock_can2);
  }
  return 0U;
}

void board_init_spi_pins(SPI_Type *ptr) {
  if (ptr == HPM_SPI2) {
    init_spi2_pins();
  }
}

void board_init_spi_pins_with_gpio_as_cs(SPI_Type *ptr) {
  board_init_spi_pins(ptr);
}

uint32_t board_init_spi_clock(SPI_Type *ptr) {
  if (ptr == HPM_SPI2) {
    init_spi2_clock();
    return clock_get_frequency(clock_spi2);
  }
  return 0U;
}

void board_write_spi_cs(uint32_t pin, uint8_t state) {
  gpio_write_pin(BOARD_SPI_CS_GPIO_CTRL, GPIO_GET_PORT_INDEX(pin),
                 GPIO_GET_PIN_INDEX(pin), state);
}

void board_init_led_pins(void) {
  gpio_set_pin_output_with_initial(BOARD_LED_GPIO_CTRL, BOARD_LED_GPIO_INDEX,
                                   BOARD_LED_GPIO_PIN, BOARD_LED_OFF_LEVEL);
}

void board_led_write(uint8_t state) {
  gpio_write_pin(BOARD_LED_GPIO_CTRL, BOARD_LED_GPIO_INDEX, BOARD_LED_GPIO_PIN,
                 state);
}

void board_led_toggle(void) {
  gpio_toggle_pin(BOARD_LED_GPIO_CTRL, BOARD_LED_GPIO_INDEX,
                  BOARD_LED_GPIO_PIN);
}

uint8_t board_get_led_gpio_off_level(void) { return BOARD_LED_OFF_LEVEL; }

bool board_is_sd_card_present(void) {
  return gpio_read_pin(BOARD_SD_DETECT_GPIO_CTRL, BOARD_SD_DETECT_GPIO_INDEX,
                       BOARD_SD_DETECT_GPIO_PIN) ==
         BOARD_SD_DETECT_PRESENT_LEVEL;
}

void board_ungate_mchtmr_at_lp_mode(void) {
  sysctl_set_cpu_lp_mode(HPM_SYSCTL, BOARD_RUNNING_CORE,
                         cpu_lp_mode_ungate_cpu_clock);
}

void board_init_pmp(void) {}
