/*
 * Copyright (c) 2026 HPMicro
 *
 * SPDX-License-Identifier: BSD-3-Clause
 *
 * Generated from the HPM Pinmux Tool configuration and adapted for the
 * hpm5321_custom board.
 *
 * PY pins need both IOC and PIOC configuration before they can be controlled
 * by GPIO0.
 */

#include "pinmux.h"
#include "hpm_gpio_drv.h"
#include "hpm_gpiom_drv.h"
#include "hpm_soc.h"

#define BOARD_GPIO_DEFAULT_OFF_LEVEL (1U)
#define BOARD_SD_DETECT_PAD_CTL                                              \
  (IOC_PAD_PAD_CTL_HYS_SET(1) | IOC_PAD_PAD_CTL_PE_SET(1) |                 \
   IOC_PAD_PAD_CTL_PS_SET(1) | IOC_PAD_PAD_CTL_PRS_SET(0))
#define BOARD_SPI_MISO_PAD_CTL BOARD_SD_DETECT_PAD_CTL

static void init_gpio_output(uint32_t port, uint8_t pin, uint8_t initial) {
  gpiom_set_pin_controller(HPM_GPIOM, port, pin, gpiom_soc_gpio0);
  gpiom_disable_pin_visibility(HPM_GPIOM, port, pin, gpiom_core0_fast);
  gpio_set_pin_output_with_initial(HPM_GPIO0, port, pin, initial);
}

static void init_gpio_input(uint32_t port, uint8_t pin) {
  gpiom_set_pin_controller(HPM_GPIOM, port, pin, gpiom_soc_gpio0);
  gpiom_disable_pin_visibility(HPM_GPIOM, port, pin, gpiom_core0_fast);
  gpio_set_pin_input(HPM_GPIO0, port, pin);
  gpio_disable_pin_interrupt(HPM_GPIO0, port, pin);
}

void init_uart0_pins(void) {
  HPM_IOC->PAD[IOC_PAD_PA00].FUNC_CTL = IOC_PA00_FUNC_CTL_UART0_TXD;
  HPM_IOC->PAD[IOC_PAD_PA01].FUNC_CTL = IOC_PA01_FUNC_CTL_UART0_RXD;
}

void init_usb0_pins(void) {
  HPM_IOC->PAD[IOC_PAD_PA24].FUNC_CTL = IOC_PAD_FUNC_CTL_ANALOG_MASK;
  HPM_IOC->PAD[IOC_PAD_PA25].FUNC_CTL = IOC_PAD_FUNC_CTL_ANALOG_MASK;
}

void disconnect_mcan_pins(void) {
  /* IOC-only writes are safe before the board clock tree is reconfigured and
   * also handle warm resets where the previous MCAN mux selection persists. */
  HPM_IOC->PAD[IOC_PAD_PB00].FUNC_CTL = IOC_PB00_FUNC_CTL_GPIO_B_00;
  HPM_IOC->PAD[IOC_PAD_PB01].FUNC_CTL = IOC_PB01_FUNC_CTL_GPIO_B_01;
  HPM_IOC->PAD[IOC_PAD_PB08].FUNC_CTL = IOC_PB08_FUNC_CTL_GPIO_B_08;
  HPM_IOC->PAD[IOC_PAD_PB09].FUNC_CTL = IOC_PB09_FUNC_CTL_GPIO_B_09;
}

void init_mcan_safe_gpio_inputs(void) {
  /* Establish GPIO ownership and input direction before selecting the GPIO
   * mux. This closes the warm-reset window in which a retained output-enable
   * bit could otherwise drive TXD as soon as FUNC_CTL changes. */
  init_gpio_input(GPIO_DI_GPIOB, 0U);
  init_gpio_input(GPIO_DI_GPIOB, 1U);
  init_gpio_input(GPIO_DI_GPIOB, 8U);
  init_gpio_input(GPIO_DI_GPIOB, 9U);
  disconnect_mcan_pins();
}

void init_mcan0_pins(void) {
  HPM_IOC->PAD[IOC_PAD_PB00].FUNC_CTL = IOC_PB00_FUNC_CTL_MCAN0_TXD;
  HPM_IOC->PAD[IOC_PAD_PB01].FUNC_CTL = IOC_PB01_FUNC_CTL_MCAN0_RXD;
}

void init_mcan2_pins(void) {
  HPM_IOC->PAD[IOC_PAD_PB08].FUNC_CTL = IOC_PB08_FUNC_CTL_MCAN2_TXD;
  HPM_IOC->PAD[IOC_PAD_PB09].FUNC_CTL = IOC_PB09_FUNC_CTL_MCAN2_RXD;
}

void init_spi2_pins(void) {
  HPM_IOC->PAD[IOC_PAD_PB10].FUNC_CTL = IOC_PB10_FUNC_CTL_GPIO_B_10;
  HPM_IOC->PAD[IOC_PAD_PB11].FUNC_CTL =
      IOC_PB11_FUNC_CTL_SPI2_SCLK | IOC_PAD_FUNC_CTL_LOOP_BACK_MASK;
  HPM_IOC->PAD[IOC_PAD_PB12].FUNC_CTL = IOC_PB12_FUNC_CTL_SPI2_MISO;
  HPM_IOC->PAD[IOC_PAD_PB12].PAD_CTL = BOARD_SPI_MISO_PAD_CTL;
  HPM_IOC->PAD[IOC_PAD_PB13].FUNC_CTL = IOC_PB13_FUNC_CTL_SPI2_MOSI;

  init_gpio_output(GPIO_DO_GPIOB, 10U, 1U);
}

void init_board_gpio_pins(void) {
  /* Status LED: PA31, active low. */
  HPM_IOC->PAD[IOC_PAD_PA31].FUNC_CTL = IOC_PA31_FUNC_CTL_GPIO_A_31;
  init_gpio_output(GPIO_DO_GPIOA, 31U, BOARD_GPIO_DEFAULT_OFF_LEVEL);

  /* CAN activity LEDs: active low. */
  HPM_IOC->PAD[IOC_PAD_PY01].FUNC_CTL = IOC_PY01_FUNC_CTL_GPIO_Y_01;
  HPM_PIOC->PAD[IOC_PAD_PY01].FUNC_CTL = PIOC_PY01_FUNC_CTL_SOC_GPIO_Y_01;
  init_gpio_output(GPIO_DO_GPIOY, 1U, BOARD_GPIO_DEFAULT_OFF_LEVEL);

  HPM_IOC->PAD[IOC_PAD_PY02].FUNC_CTL = IOC_PY02_FUNC_CTL_GPIO_Y_02;
  HPM_PIOC->PAD[IOC_PAD_PY02].FUNC_CTL = PIOC_PY02_FUNC_CTL_SOC_GPIO_Y_02;
  init_gpio_output(GPIO_DO_GPIOY, 2U, BOARD_GPIO_DEFAULT_OFF_LEVEL);

  HPM_IOC->PAD[IOC_PAD_PY03].FUNC_CTL = IOC_PY03_FUNC_CTL_GPIO_Y_03;
  HPM_PIOC->PAD[IOC_PAD_PY03].FUNC_CTL = PIOC_PY03_FUNC_CTL_SOC_GPIO_Y_03;
  init_gpio_output(GPIO_DO_GPIOY, 3U, BOARD_GPIO_DEFAULT_OFF_LEVEL);

  HPM_IOC->PAD[IOC_PAD_PA09].FUNC_CTL = IOC_PA09_FUNC_CTL_GPIO_A_09;
  init_gpio_output(GPIO_DO_GPIOA, 9U, BOARD_GPIO_DEFAULT_OFF_LEVEL);

  /* SD card detect: PY00 input. */
  HPM_IOC->PAD[IOC_PAD_PY00].FUNC_CTL = IOC_PY00_FUNC_CTL_GPIO_Y_00;
  HPM_IOC->PAD[IOC_PAD_PY00].PAD_CTL = BOARD_SD_DETECT_PAD_CTL;
  HPM_PIOC->PAD[IOC_PAD_PY00].FUNC_CTL = PIOC_PY00_FUNC_CTL_SOC_GPIO_Y_00;
  HPM_PIOC->PAD[IOC_PAD_PY00].PAD_CTL = BOARD_SD_DETECT_PAD_CTL;
  init_gpio_input(GPIO_DI_GPIOY, 0U);
}

void init_pins(void) {
  init_uart0_pins();
  init_usb0_pins();
  init_mcan_safe_gpio_inputs();
  /*
   * Do not connect MCAN TX/RX during generic board initialization. The
   * application must first initialize the selected MCAN controller in a safe
   * mode, then call board_init_can() to connect the pads. This prevents a
   * normal-mode transceiver with hardware-low STB from seeing an undefined
   * controller TXD level during startup.
   */
  init_spi2_pins();
  init_board_gpio_pins();
}
