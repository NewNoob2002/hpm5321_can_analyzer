/* HPM5321 USB-CAN analyzer RTOS ownership baseline. */
#include <stdint.h>
#include <stdio.h>

#include "FreeRTOS.h"
#include "app_allocation.h"
#include "app_fault.h"
#include "app_health.h"
#include "app_irq_contract.h"
#include "app_time.h"
#include "board.h"
#include "elog.h"
#include "hpm_clock_drv.h"
#include "hpm_ppor_drv.h"
#include "hpm_sdk_version.h"
#include "task.h"

#define APP_BOOT_MAGIC (0x424F4F54U) /* "BOOT" */
#define APP_STRINGIFY_VALUE(value) #value
#define APP_STRINGIFY(value) APP_STRINGIFY_VALUE(value)

#ifndef APP_FIRMWARE_VERSION
#error "APP_FIRMWARE_VERSION must be provided by the build"
#endif
#ifndef APP_BOARD_REVISION
#error "APP_BOARD_REVISION must be provided by the build"
#endif

#ifdef BUILD_VERSION
#define APP_SDK_BUILD_VERSION APP_STRINGIFY(BUILD_VERSION)
#else
#define APP_SDK_BUILD_VERSION "unknown"
#endif

typedef struct {
    uint32_t magic;
    uint32_t cpu_hz;
    uint32_t ahb_hz;
    uint32_t mchtmr_hz;
    uint32_t usb0_hz;
    uint32_t can0_hz;
    uint32_t can2_hz;
    uint32_t spi2_hz;
    uint32_t reset_flags;
    uint64_t boot_timestamp;
} app_boot_state_t;

volatile app_boot_state_t g_app_boot_state;

static void init_logger(void)
{
    elog_init();
    elog_set_fmt(ELOG_LVL_ASSERT,
                 ELOG_FMT_LVL | ELOG_FMT_TAG | ELOG_FMT_TIME | ELOG_FMT_FUNC |
                     ELOG_FMT_LINE);
    elog_set_fmt(ELOG_LVL_ERROR,
                 ELOG_FMT_LVL | ELOG_FMT_TAG | ELOG_FMT_TIME | ELOG_FMT_FUNC |
                     ELOG_FMT_LINE);
    elog_set_fmt(ELOG_LVL_WARN, ELOG_FMT_LVL | ELOG_FMT_TAG | ELOG_FMT_TIME);
    elog_set_fmt(ELOG_LVL_INFO, ELOG_FMT_LVL | ELOG_FMT_TAG | ELOG_FMT_TIME);
    elog_start();
}

static void capture_clock_state(void)
{
    const uint32_t reset_flags = ppor_reset_get_flags(HPM_PPOR);

    g_app_boot_state.magic = APP_BOOT_MAGIC;
    g_app_boot_state.cpu_hz = clock_get_frequency(clock_cpu0);
    g_app_boot_state.ahb_hz = clock_get_frequency(clock_ahb);
    g_app_boot_state.mchtmr_hz = clock_get_frequency(clock_mchtmr0);
    g_app_boot_state.usb0_hz = clock_get_frequency(clock_usb0);
    g_app_boot_state.can0_hz = board_init_can_clock(HPM_MCAN0);
    g_app_boot_state.can2_hz = board_init_can_clock(HPM_MCAN2);
    g_app_boot_state.spi2_hz = board_init_spi_clock(HPM_SPI2);
    g_app_boot_state.reset_flags = reset_flags;
    g_app_boot_state.boot_timestamp = app_time_now();
    if (reset_flags != 0U) {
        ppor_reset_clear_flags(HPM_PPOR, reset_flags);
    }

    configASSERT(g_app_boot_state.cpu_hz != 0U);
    configASSERT(g_app_boot_state.ahb_hz != 0U);
    configASSERT(g_app_boot_state.mchtmr_hz == configCPU_CLOCK_HZ);
    configASSERT(g_app_boot_state.can0_hz != 0U);
    configASSERT(g_app_boot_state.can2_hz != 0U);
    configASSERT(g_app_boot_state.spi2_hz != 0U);
}

static const char *reset_cause_name(uint32_t flags)
{
    const uint32_t known_mask =
        ppor_reset_brownout | ppor_reset_debug | ppor_reset_wdog0 |
        ppor_reset_wdog1 | ppor_reset_pmic_wdog | ppor_reset_software;
    const uint32_t known = flags & known_mask;

    if (known == 0U) {
        return flags == 0U ? "power_on_or_unknown" : "unknown";
    }
    if ((known & (known - 1U)) != 0U) {
        return "multiple";
    }
    if (known == ppor_reset_brownout) {
        return "brownout";
    }
    if (known == ppor_reset_debug) {
        return "debug";
    }
    if (known == ppor_reset_wdog0) {
        return "watchdog0";
    }
    if (known == ppor_reset_wdog1) {
        return "watchdog1";
    }
    if (known == ppor_reset_pmic_wdog) {
        return "pmic_watchdog";
    }
    return "software";
}

static void print_boot_banner(void)
{
    printf("P2_BOOT firmware=%s sdk=%s sdk_build=%s board=%s "
           "board_revision=%s uart=UART0 baud=%lu reset_flags=0x%08lx "
           "reset_cause=%s\n",
           APP_FIRMWARE_VERSION, SDK_VERSION_STRING, APP_SDK_BUILD_VERSION,
           BOARD_NAME, APP_BOARD_REVISION,
           (unsigned long)BOARD_CONSOLE_UART_BAUDRATE,
           (unsigned long)g_app_boot_state.reset_flags,
           reset_cause_name(g_app_boot_state.reset_flags));
}

int main(void)
{
    board_init();
    init_logger();
    capture_clock_state();
    print_boot_banner();

    log_i("P2 RTOS baseline: static health task, queue, timer, 64-bit time");
    configASSERT(app_health_start());
    app_allocation_freeze();
    app_fault_inject_if_configured();

    vTaskStartScheduler();
    vAssertCalled(__FILE__, __LINE__);
    return 0;
}
