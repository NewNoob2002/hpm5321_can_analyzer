#include "app_health.h"

#include <stdint.h>

#include "FreeRTOS.h"
#include "app_time.h"
#include "app_watchdog.h"
#include "board.h"
#include "hpm_gpio_drv.h"
#include "queue.h"
#include "task.h"
#include "timers.h"

#define APP_HEALTH_MAGIC (0x484C5448U) /* "HLTH" */
#define APP_HEALTH_VERSION (1U)
#define APP_HEALTH_STACK_WORDS (configMINIMAL_STACK_SIZE + 256U)
#define APP_HEALTH_QUEUE_LENGTH (4U)
#define APP_HEALTH_TASK_PRIORITY (2U)
#define APP_HEALTH_HEARTBEAT_MS (500U)
#define APP_HEALTH_EVENT_HEARTBEAT (1U)

static StaticTask_t health_task_tcb;
static StackType_t health_task_stack[APP_HEALTH_STACK_WORDS];
static StaticQueue_t health_queue_control;
static uint8_t health_queue_storage[APP_HEALTH_QUEUE_LENGTH * sizeof(uint32_t)];
static StaticTimer_t heartbeat_timer_control;
static QueueHandle_t health_queue;
static TimerHandle_t heartbeat_timer;

volatile app_health_state_t g_app_health_state = {
    .magic = APP_HEALTH_MAGIC,
    .version = APP_HEALTH_VERSION,
};

static void write_activity_leds_off(void)
{
    gpio_write_pin(BOARD_CAN0_TX_LED_GPIO_CTRL, BOARD_CAN0_TX_LED_GPIO_INDEX,
                   BOARD_CAN0_TX_LED_GPIO_PIN, BOARD_CAN_LED_OFF_LEVEL);
    gpio_write_pin(BOARD_CAN0_RX_LED_GPIO_CTRL, BOARD_CAN0_RX_LED_GPIO_INDEX,
                   BOARD_CAN0_RX_LED_GPIO_PIN, BOARD_CAN_LED_OFF_LEVEL);
    gpio_write_pin(BOARD_CAN2_TX_LED_GPIO_CTRL, BOARD_CAN2_TX_LED_GPIO_INDEX,
                   BOARD_CAN2_TX_LED_GPIO_PIN, BOARD_CAN_LED_OFF_LEVEL);
    gpio_write_pin(BOARD_CAN2_RX_LED_GPIO_CTRL, BOARD_CAN2_RX_LED_GPIO_INDEX,
                   BOARD_CAN2_RX_LED_GPIO_PIN, BOARD_CAN_LED_OFF_LEVEL);
}

static void heartbeat_timer_callback(TimerHandle_t timer)
{
    const uint32_t event = APP_HEALTH_EVENT_HEARTBEAT;
    (void)timer;

    app_watchdog_vote(APP_WATCHDOG_VOTER_TIMER_SERVICE);
    if (xQueueSend(health_queue, &event, 0U) != pdPASS) {
        g_app_health_state.timer_queue_drops++;
    }
}

static void health_task(void *context)
{
    uint32_t event;
    bool status_on = false;
    (void)context;

    board_led_write(BOARD_LED_OFF_LEVEL);
    write_activity_leds_off();
    g_app_health_state.timestamp_frequency_hz = app_time_frequency_hz();

    while (1) {
        const BaseType_t received = xQueueReceive(
            health_queue, &event,
            pdMS_TO_TICKS(APP_HEALTH_HEARTBEAT_MS));

        if (received == pdPASS &&
            event == APP_HEALTH_EVENT_HEARTBEAT) {
            status_on = !status_on;
            board_led_write(status_on ? BOARD_LED_ON_LEVEL : BOARD_LED_OFF_LEVEL);
            g_app_health_state.status_led_on = (uint32_t)status_on;
            g_app_health_state.heartbeat_count++;
            g_app_health_state.last_heartbeat_tick = app_time_now();
            g_app_health_state.stack_high_watermark =
                uxTaskGetStackHighWaterMark(NULL);
        }

        app_watchdog_vote(APP_WATCHDOG_VOTER_HEALTH);
        (void)app_watchdog_evaluate();
        g_app_health_state.watchdog_missing_mask =
            g_app_watchdog_state.missing_mask;
        g_app_health_state.watchdog_healthy_evaluations =
            g_app_watchdog_state.healthy_evaluation_count;
    }
}

bool app_health_start(void)
{
    if (!app_watchdog_init(APP_WATCHDOG_REQUIRED_MASK)) {
        return false;
    }

    health_queue = xQueueCreateStatic(
        APP_HEALTH_QUEUE_LENGTH, sizeof(uint32_t), health_queue_storage,
        &health_queue_control);
    if (health_queue == NULL) {
        return false;
    }

    if (xTaskCreateStatic(health_task, "health", APP_HEALTH_STACK_WORDS, NULL,
                          APP_HEALTH_TASK_PRIORITY, health_task_stack,
                          &health_task_tcb) == NULL) {
        return false;
    }

    heartbeat_timer = xTimerCreateStatic(
        "heartbeat", pdMS_TO_TICKS(APP_HEALTH_HEARTBEAT_MS), pdTRUE, NULL,
        heartbeat_timer_callback, &heartbeat_timer_control);
    if (heartbeat_timer == NULL) {
        return false;
    }

    return xTimerStart(heartbeat_timer, 0U) == pdPASS;
}
