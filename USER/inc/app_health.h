#ifndef APP_HEALTH_H
#define APP_HEALTH_H

#include <stdbool.h>
#include <stdint.h>

typedef struct {
    uint32_t magic;
    uint32_t version;
    uint32_t heartbeat_count;
    uint32_t timer_queue_drops;
    uint32_t stack_high_watermark;
    uint32_t status_led_on;
    uint32_t timestamp_frequency_hz;
    uint32_t watchdog_missing_mask;
    uint32_t watchdog_healthy_evaluations;
    uint64_t last_heartbeat_tick;
} app_health_state_t;

extern volatile app_health_state_t g_app_health_state;

bool app_health_start(void);
bool app_health_signal_can0_rx(void);
bool app_health_signal_can0_tx(void);

#endif /* APP_HEALTH_H */
