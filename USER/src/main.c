/*
 * Copyright (c) 2021 HPMicro
 *
 * SPDX-License-Identifier: BSD-3-Clause
 *
 */

#include <stdio.h>
#include <stdlib.h>
#include "SEGGER_RTT.h"
#include "board.h"
#include "hpm_debug_console.h"
/* FreeRTOS kernel includes. */
#include "FreeRTOS.h"
#include "elog.h"
#include "task.h"
#define LED_FLASH_PERIOD_IN_MS 300

TaskHandle_t idleTaskHandle;

static void idleTask(void* pvParameters) {
    while (1) {
        board_led_toggle();
        log_i("IdleTask\n");
        vTaskDelay(1000);
    }
}

int main(void) {
#if DEBUG
    elog_init();
    elog_set_fmt(ELOG_LVL_ASSERT, ELOG_FMT_LVL | ELOG_FMT_TAG | ELOG_FMT_TIME | ELOG_FMT_FUNC | ELOG_FMT_LINE);
    elog_set_fmt(ELOG_LVL_ERROR, ELOG_FMT_LVL | ELOG_FMT_TAG | ELOG_FMT_TIME | ELOG_FMT_FUNC | ELOG_FMT_LINE);
    elog_set_fmt(ELOG_LVL_WARN, ELOG_FMT_LVL | ELOG_FMT_TAG | ELOG_FMT_TIME);
    elog_set_fmt(ELOG_LVL_INFO, ELOG_FMT_LVL | ELOG_FMT_TAG | ELOG_FMT_TIME);
    elog_set_fmt(ELOG_LVL_DEBUG, ELOG_FMT_LVL | ELOG_FMT_TAG | ELOG_FMT_TIME);
    elog_start();
#endif
    board_init();
    board_init_led_pins();

    xTaskCreate(idleTask, "idleTask", 1024, NULL, 1, &idleTaskHandle);
    vTaskStartScheduler();
    for (;;) {
        ;
    }
    return 0;
}
