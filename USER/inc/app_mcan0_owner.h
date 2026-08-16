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

#ifndef APP_MCAN0_BUS_OFF_TEST_HOOK
#define APP_MCAN0_BUS_OFF_TEST_HOOK (0)
#endif
#if APP_MCAN0_BUS_OFF_TEST_HOOK && !defined(DEBUG)
#error "APP_MCAN0_BUS_OFF_TEST_HOOK requires DEBUG"
#endif

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
    APP_MCAN0_OWNER_MODE_FAULT_NORMAL = 2,
    APP_MCAN0_OWNER_MODE_BUS_OFF_LATCHED = 3,
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

#if APP_MCAN0_BUS_OFF_TEST_HOOK
#define APP_MCAN0_BUS_OFF_TEST_MAILBOX_MAGIC (0x424F4649U) /* "BOFI" */
#define APP_MCAN0_BUS_OFF_TEST_RESULT_MAGIC (0x424F4652U)  /* "BOFR" */
#define APP_MCAN0_BUS_OFF_TEST_VERSION (2U)
#define APP_MCAN0_BUS_OFF_TEST_UNLOCK_TOKEN (0x554E4C4BU) /* "UNLK" */
#define APP_MCAN0_BUS_OFF_TEST_ARM_TOKEN (0x41524D21U)    /* "ARM!" */
#define APP_MCAN0_BUS_OFF_TEST_COMMAND_START (1U)

typedef enum {
    APP_MCAN0_BUS_OFF_TEST_STATE_BOOT_SAFE = 0,
    APP_MCAN0_BUS_OFF_TEST_STATE_LISTEN_ONLY_LOCKED = 1,
    APP_MCAN0_BUS_OFF_TEST_STATE_FAULT_ACTIVE = 2,
    APP_MCAN0_BUS_OFF_TEST_STATE_BUS_OFF_LATCHED = 3,
    APP_MCAN0_BUS_OFF_TEST_STATE_TIMEOUT_CLEANED = 4,
    APP_MCAN0_BUS_OFF_TEST_STATE_TX_COMPLETED_CLEANED = 5,
    APP_MCAN0_BUS_OFF_TEST_STATE_FAULT_CONTAINED = 6,
} app_mcan0_bus_off_test_state_t;

typedef struct {
    uint32_t magic;
    uint32_t version;
    uint32_t size;
    uint32_t run_nonce;
    uint32_t unlock_token;
    uint32_t arm_token;
    uint32_t command;
    uint32_t reserved;
} app_mcan0_bus_off_test_mailbox_t;

typedef struct {
    uint32_t magic;
    uint32_t version;
    uint32_t size;
    uint32_t state;
    uint32_t run_nonce;
    uint32_t once_per_boot_consumed;
    uint32_t rejected_command_count;
    uint32_t tx_submit_count;
    int32_t last_submit_status;
    uint32_t max_tec;
    uint32_t warning_observed;
    uint32_t error_passive_observed;
    uint32_t bus_off_observed;
    uint32_t start_tick;
    uint32_t end_tick;
    uint32_t final_protocol_status;
    uint32_t final_error_count;
    uint32_t final_control_status;
    uint32_t final_interrupt_flags;
    uint32_t final_tx_request_pending;
    uint32_t post_cleanup_init;
    uint32_t post_cleanup_monitor;
    uint32_t post_cleanup_tx_pending;
    uint32_t post_cleanup_pads_disconnected;
    uint32_t cancel_timeout_observed;
    uint32_t automatic_recovery_attempts;
} app_mcan0_bus_off_test_result_t;

extern volatile app_mcan0_bus_off_test_mailbox_t
    g_app_mcan0_bus_off_test_mailbox;
extern volatile app_mcan0_bus_off_test_result_t
    g_app_mcan0_bus_off_test_result;
#endif

bool app_mcan0_owner_start(void);
bool app_mcan0_owner_pop_rx(app_mcan0_owner_rx_record_t *record);
bool app_mcan0_owner_rx_pending(void);
bool app_mcan0_owner_pop_state_edge(app_mcan0_owner_state_edge_t *edge);
bool app_mcan0_owner_get_diagnostics(app_mcan0_diagnostics_t *snapshot);
app_mcan0_owner_tx_result_t app_mcan0_owner_submit_tx(
    const app_mcan0_owner_tx_request_t *request);

#endif /* APP_MCAN0_OWNER_H */
