#ifndef APP_MCAN0_OWNER_H
#define APP_MCAN0_OWNER_H

#include <stdbool.h>
#include <stdint.h>

#define APP_MCAN0_OWNER_MAGIC (0x4D43414EU) /* "MCAN" */
#define APP_MCAN0_OWNER_VERSION (1U)
#define APP_MCAN0_OWNER_ISR_PRIORITY (4U)
#define APP_MCAN0_OWNER_BITRATE (1000000U)
#define APP_MCAN0_OWNER_EVENT_QUEUE_LENGTH (16U)
#define APP_MCAN0_OWNER_RX_RING_CAPACITY (64U)
#define APP_MCAN0_OWNER_CLASSIC_MAX_BYTES (8U)

typedef enum {
    APP_MCAN0_OWNER_MODE_OFFLINE = 0,
    APP_MCAN0_OWNER_MODE_LISTEN_ONLY = 1,
} app_mcan0_owner_mode_t;

typedef enum {
    APP_MCAN0_OWNER_TX_REJECTED_DISARMED = 1,
    APP_MCAN0_OWNER_TX_REJECTED_INVALID = 2,
} app_mcan0_owner_tx_result_t;

typedef struct {
    uint32_t can_id;
    uint8_t dlc;
    uint8_t use_ext_id;
    uint8_t rtr;
    uint8_t reserved;
    uint8_t data[APP_MCAN0_OWNER_CLASSIC_MAX_BYTES];
} app_mcan0_owner_tx_request_t;

typedef struct {
    uint64_t timestamp_tick;
    uint32_t sequence;
    uint32_t can_id;
    uint8_t dlc;
    uint8_t use_ext_id;
    uint8_t rtr;
    uint8_t error_state_indicator;
    uint8_t data[APP_MCAN0_OWNER_CLASSIC_MAX_BYTES];
} app_mcan0_owner_rx_record_t;

typedef struct {
    uint32_t magic;
    uint32_t version;
    uint32_t mode;
    uint32_t initialized;
    uint32_t online;
    uint32_t tx_armed;
    uint32_t source_clock_hz;
    uint32_t control_status;
    uint32_t nominal_bit_timing;
    int32_t message_ram_status;
    int32_t init_status;
    uint32_t irq_priority;
    uint32_t interrupt_count;
    uint32_t interrupt_flags;
    uint32_t error_interrupt_flags;
    uint32_t frames_received;
    uint32_t frames_published;
    uint32_t invalid_frames;
    uint32_t queue_send_count;
    uint32_t queue_drops;
    uint32_t ring_count;
    uint32_t ring_drops;
    uint32_t ring_high_watermark;
    uint32_t rx_sequence;
    uint32_t bus_off_count;
    uint32_t warning_count;
    uint32_t error_passive_count;
    uint32_t automatic_recovery_attempts;
    uint32_t tx_rejected_disarmed;
    uint32_t tx_rejected_invalid;
    uint32_t activity_signal_drops;
    uint32_t last_protocol_status;
    uint32_t last_error_count;
    uint32_t last_interrupt_snapshot;
    uint32_t stack_high_watermark;
    uint64_t last_rx_tick;
} app_mcan0_owner_state_t;

extern volatile app_mcan0_owner_state_t g_app_mcan0_owner_state;

bool app_mcan0_owner_start(void);
bool app_mcan0_owner_pop_rx(app_mcan0_owner_rx_record_t *record);
app_mcan0_owner_tx_result_t app_mcan0_owner_submit_tx(
    const app_mcan0_owner_tx_request_t *request);

#endif /* APP_MCAN0_OWNER_H */
