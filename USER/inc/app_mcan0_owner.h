#ifndef APP_MCAN0_OWNER_H
#define APP_MCAN0_OWNER_H

#include <stdbool.h>
#include <stdint.h>

#define APP_MCAN0_OWNER_MAGIC (0x4D43414EU) /* "MCAN" */
#define APP_MCAN0_OWNER_VERSION (1U)
#define APP_MCAN0_OWNER_ISR_PRIORITY (4U)
#ifndef APP_MCAN0_OWNER_BITRATE
#define APP_MCAN0_OWNER_BITRATE (1000000U)
#endif
#define APP_MCAN0_OWNER_EVENT_QUEUE_LENGTH (64U)
#define APP_MCAN0_OWNER_RX_RING_CAPACITY (64U)
#define APP_MCAN0_OWNER_STATE_EDGE_CAPACITY (16U)
#define APP_MCAN0_OWNER_CLASSIC_MAX_BYTES (8U)
#define APP_MCAN0_DIAGNOSTICS_VERSION (1U)
#define APP_MCAN0_DIAGNOSTICS_SNAPSHOT_LEN (120U)

#define APP_MCAN0_DIAG_STATE_INITIALIZED (1UL << 0)
#define APP_MCAN0_DIAG_STATE_ONLINE (1UL << 1)
#define APP_MCAN0_DIAG_STATE_LISTEN_ONLY (1UL << 2)
#define APP_MCAN0_DIAG_STATE_TX_ARMED (1UL << 3)
#define APP_MCAN0_DIAG_STATE_WARNING (1UL << 4)
#define APP_MCAN0_DIAG_STATE_ERROR_PASSIVE (1UL << 5)
#define APP_MCAN0_DIAG_STATE_BUS_OFF (1UL << 6)

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
    uint64_t timestamp_tick;
    uint32_t state_flags;
    uint32_t protocol_status;
    uint32_t error_count;
    uint32_t transmit_error_count;
    uint32_t receive_error_count;
} app_mcan0_owner_state_edge_t;

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
    uint32_t rx_queue_drops;
    uint32_t diagnostic_queue_drops;
    uint32_t state_edge_drops;
    uint32_t queue_count;
    uint32_t queue_high_watermark;
    uint32_t rxfifo0_fill_level;
    uint32_t rxfifo0_high_watermark;
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

typedef struct {
    uint32_t version;
    uint32_t snapshot_length;
    uint32_t generation;
    uint32_t state_flags;
    uint64_t snapshot_tick;
    uint32_t interrupt_flags;
    uint32_t error_interrupt_flags;
    uint32_t last_interrupt_flags;
    uint32_t protocol_status;
    uint32_t error_count;
    uint32_t transmit_error_count;
    uint32_t receive_error_count;
    uint32_t rxfifo0_fill_level;
    uint32_t rxfifo0_high_watermark;
    uint32_t queue_count;
    uint32_t queue_high_watermark;
    uint32_t ring_count;
    uint32_t ring_high_watermark;
    uint32_t queue_drops;
    uint32_t rx_queue_drops;
    uint32_t diagnostic_queue_drops;
    uint32_t state_edge_drops;
    uint32_t ring_drops;
    uint32_t invalid_frames;
    uint32_t bus_off_count;
    uint32_t warning_count;
    uint32_t error_passive_count;
    uint32_t automatic_recovery_attempts;
} app_mcan0_diagnostics_t;

extern volatile app_mcan0_owner_state_t g_app_mcan0_owner_state;

bool app_mcan0_owner_start(void);
bool app_mcan0_owner_pop_rx(app_mcan0_owner_rx_record_t *record);
bool app_mcan0_owner_rx_pending(void);
bool app_mcan0_owner_pop_state_edge(app_mcan0_owner_state_edge_t *edge);
bool app_mcan0_owner_get_diagnostics(app_mcan0_diagnostics_t *snapshot);
app_mcan0_owner_tx_result_t app_mcan0_owner_submit_tx(
    const app_mcan0_owner_tx_request_t *request);

#endif /* APP_MCAN0_OWNER_H */
