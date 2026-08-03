/*
 * USB-CAN protocol v1.0 C codec.
 *
 * Pure C99, no HAL/RTOS/allocator dependencies: the same sources compile on
 * the host (parity tests) and on the HPM target. Wire layout follows
 * docs/approved-plan/usb-can-protocol-v1.md; all multi-byte fields are
 * little-endian.
 */
#ifndef UCAN_CODEC_H
#define UCAN_CODEC_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define UCAN_MAGIC0 'U'
#define UCAN_MAGIC1 'C'
#define UCAN_MAGIC2 'A'
#define UCAN_MAGIC3 'N'
#define UCAN_HEADER_LEN 24u
#define UCAN_PROTOCOL_MAJOR 1u
#define UCAN_PROTOCOL_MINOR 0u

/* Frame flags (spec 2.1). */
enum {
    UCAN_FLAG_REQUEST = 0x01,
    UCAN_FLAG_RESPONSE = 0x02,
    UCAN_FLAG_EVENT = 0x04,
    UCAN_FLAG_ERROR = 0x08,
};

/* Message types (spec 2.3). */
enum {
    UCAN_MSG_HELLO = 0x0001,
    UCAN_MSG_GET_DEVICE_INFO = 0x0002,
    UCAN_MSG_GET_CAPABILITIES = 0x0003,
    UCAN_MSG_GET_DIAGNOSTICS = 0x0004,
    UCAN_MSG_RESET_DIAGNOSTICS = 0x0005,
    UCAN_MSG_GET_SESSION_STATE = 0x0006,
    UCAN_MSG_CONFIG_CHANNEL = 0x0010,
    UCAN_MSG_GET_CHANNEL_CONFIG = 0x0011,
    UCAN_MSG_START_CAPTURE = 0x0012,
    UCAN_MSG_STOP_CAPTURE = 0x0013,
    UCAN_MSG_SET_FILTERS = 0x0014,
    UCAN_MSG_CLEAR_FILTERS = 0x0015,
    UCAN_MSG_TX_ARM = 0x0020,
    UCAN_MSG_TX_DISARM = 0x0021,
    UCAN_MSG_CAN_TX = 0x0022,
    UCAN_MSG_CAN_TX_CANCEL = 0x0023,
    UCAN_MSG_PING = 0x0030,
    UCAN_MSG_CAN_RX_BATCH = 0x8001,
    UCAN_MSG_CAN_TX_RESULT = 0x8002,
    UCAN_MSG_CHANNEL_STATE = 0x8003,
    UCAN_MSG_FLOW_CONTROL = 0x8004,
    UCAN_MSG_DATA_LOSS = 0x8005,
};

/* Status codes (spec 2.3). */
enum {
    UCAN_STATUS_OK = 0,
    UCAN_STATUS_INVALID_ARGUMENT = 1,
    UCAN_STATUS_UNSUPPORTED = 2,
    UCAN_STATUS_INCOMPATIBLE_VERSION = 3,
    UCAN_STATUS_BAD_STATE = 4,
    UCAN_STATUS_BUSY = 5,
    UCAN_STATUS_TIMEOUT = 6,
    UCAN_STATUS_NO_RESOURCE = 7,
    UCAN_STATUS_CHANNEL_OFFLINE = 8,
    UCAN_STATUS_USB_BACKPRESSURE = 9,
    UCAN_STATUS_CAN_ERROR = 10,
    UCAN_STATUS_STORAGE_ERROR = 11,
    UCAN_STATUS_CANCELLED = 12,
    UCAN_STATUS_ALREADY_COMPLETE = 13,
    UCAN_STATUS_INTERNAL_ERROR = 255,
};

/* Codec error codes (negative to stay clear of status codes). */
enum {
    UCAN_ERR_TOO_SHORT = -1,
    UCAN_ERR_BAD_MAGIC = -2,
    UCAN_ERR_BAD_HEADER_LEN = -3,
    UCAN_ERR_LENGTH_MISMATCH = -4,
    UCAN_ERR_BAD_FLAGS = -5,
    UCAN_ERR_BAD_STATUS = -6,
    UCAN_ERR_BAD_SEQUENCE = -7,
    UCAN_ERR_CRC = -8,
    UCAN_ERR_PAYLOAD = -9,
    UCAN_ERR_CAPACITY = -10,
    UCAN_ERR_RESERVED = -11,
    UCAN_ERR_BAD_VALUE = -12,
};

/* CAN constants (spec 6/7). */
#define UCAN_CAN_ID_STD_MAX 0x000007ffu
#define UCAN_CAN_ID_EXT_MAX 0x1fffffffu
#define UCAN_CAN_TX_FLAGS_MASK 0x000fu /* EXT|RTR|FD|BRS */
#define UCAN_CAN_RX_FLAGS_MASK 0x003fu /* EXT|RTR|FD|BRS|ESI|ERROR */

typedef struct {
    uint8_t major;
    uint8_t minor;
    uint8_t flags;
    uint16_t message_type;
    uint16_t status;
    uint32_t sequence;
    const uint8_t *payload; /* points into the decoded buffer; NULL when empty */
    uint32_t payload_len;
} ucan_frame_t;

uint32_t ucan_crc32c(const uint8_t *data, uint32_t len);
int ucan_can_dlc_to_payload_len(uint8_t dlc);

int ucan_frame_encode(const ucan_frame_t *frame, uint8_t *out, uint32_t cap,
                      uint32_t *out_len);
int ucan_frame_decode(const uint8_t *bytes, uint32_t len, uint32_t max_message,
                      ucan_frame_t *frame);

/* ---- Payload structs (spec 5.1/5.3/6) ---- */

typedef struct {
    uint8_t min_major;
    uint8_t max_major;
    uint8_t min_minor;
    uint8_t max_minor;
    uint32_t host_max_message;
    uint32_t host_features;
} ucan_hello_req_t;

typedef struct {
    uint8_t major;
    uint8_t minor;
    uint32_t session_id;
    uint32_t max_message;
    uint32_t device_features;
} ucan_hello_resp_t;

typedef struct {
    uint16_t len;
    const uint8_t *str; /* not NUL-terminated */
} ucan_str_t;

typedef struct {
    ucan_str_t firmware_semver;
    ucan_str_t build_id;
    ucan_str_t board_id;
    ucan_str_t serial;
} ucan_device_info_t;

typedef struct {
    uint8_t channel;
    uint8_t mode_mask;
    uint16_t feature_bits;
    uint32_t nominal_min;
    uint32_t nominal_max;
    uint32_t data_min;
    uint32_t data_max;
    uint16_t max_filters;
} ucan_channel_cap_t;

typedef struct {
    uint32_t cap_generation;
    uint32_t max_message;
    uint32_t max_rx_batch;
    uint32_t tx_depth;
    uint32_t tick_hz;
    uint32_t tick_resolution_ns;
    uint64_t boot_epoch;
    uint16_t outstanding_limit;
    uint16_t response_capacity;
    uint16_t event_capacity;
    uint16_t data_capacity;
    uint16_t arm_timeout_min_ms;
    uint16_t arm_timeout_max_ms;
    uint8_t channel_count;
    uint8_t usb_mode;
    uint16_t global_features;
    uint16_t replay_cache_entries;
    uint16_t tx_result_cache_entries;
    uint32_t replay_retention_ms;
    uint32_t tag_reuse_guard_ms;
    const ucan_channel_cap_t *channels;
} ucan_capabilities_t;

typedef struct {
    uint8_t channel;
    uint8_t state;
    uint32_t rx_depth;
    uint32_t tx_depth;
    uint64_t rx_frames;
    uint64_t tx_frames;
    uint64_t filtered;
    uint64_t dropped;
    uint32_t bus_off_count;
    uint32_t error_count;
} ucan_channel_diag_t;

typedef struct {
    uint32_t generation;
    uint32_t session_id;
    uint32_t response_depth;
    uint32_t event_depth;
    uint32_t data_depth;
    uint32_t pool_high_water;
    uint64_t usb_rx_bytes;
    uint64_t usb_tx_bytes;
    const ucan_channel_diag_t *channels;
    uint8_t channel_count;
} ucan_diagnostics_t;

typedef struct {
    uint8_t channel;
    uint32_t filter_generation;
    uint32_t filter_crc32c;
} ucan_filter_state_t;

typedef struct {
    uint32_t config_generation;
    uint32_t capture_generation;
    uint8_t capture_state;
    bool tx_armed;
    uint32_t arm_epoch;
    uint64_t arm_expiry_tick;
    uint32_t aggregate_max_frames_per_s;
    const ucan_filter_state_t *filters;
    uint8_t filter_count;
} ucan_session_state_t;

typedef struct {
    uint8_t channel;
    uint8_t mode;
    uint16_t flags;
    uint32_t nominal_bps;
    uint32_t data_bps;
    uint16_t sample_permille;
    uint32_t generation;
} ucan_channel_config_t;

typedef struct {
    uint32_t expected_generation;
    uint32_t flags;
} ucan_capture_req_t;

typedef struct {
    uint32_t applied_generation;
    uint32_t state;
} ucan_capture_resp_t;

typedef struct {
    uint32_t id;
    uint32_t mask;
    uint16_t flags;
} ucan_filter_rule_t;

typedef struct {
    uint8_t channel;
    uint32_t expected_generation;
    const ucan_filter_rule_t *rules;
    uint8_t rule_count;
} ucan_set_filters_req_t;

typedef struct {
    uint32_t applied_generation;
    uint16_t applied_count;
} ucan_set_filters_resp_t;

typedef struct {
    uint8_t channel;
    uint32_t expected_generation;
} ucan_clear_filters_req_t;

typedef struct {
    uint32_t applied_generation;
} ucan_clear_filters_resp_t;

typedef struct {
    uint8_t channel;
    uint8_t allowed_flag_mask;
    uint32_t id;
    uint32_t id_mask;
    uint32_t max_frames_per_s;
} ucan_tx_rule_t;

typedef struct {
    uint32_t expected_config_generation;
    uint32_t timeout_ms;
    uint32_t max_frames_per_s;
    uint16_t max_bus_load_permille;
    const ucan_tx_rule_t *rules;
    uint8_t rule_count;
} ucan_tx_arm_req_t;

typedef struct {
    uint32_t applied_config_generation;
    uint32_t arm_epoch;
    uint64_t expiry_tick;
} ucan_tx_arm_resp_t;

typedef struct {
    uint32_t expected_config_generation;
    uint32_t arm_epoch;
    uint32_t reason;
} ucan_tx_disarm_req_t;

typedef struct {
    uint32_t applied_config_generation;
    uint32_t new_arm_epoch;
    uint32_t cancelled_count;
} ucan_tx_disarm_resp_t;

typedef struct {
    uint8_t channel;
    uint8_t dlc;
    uint16_t can_flags;
    uint32_t id;
    uint32_t arm_epoch;
    uint32_t client_tag;
    uint64_t deadline_tick;
    const uint8_t *payload;
    uint8_t payload_len;
} ucan_can_tx_req_t;

typedef struct {
    uint32_t client_tag;
    uint32_t queue_generation;
    uint16_t tx_state;
    uint16_t final_result;
    uint64_t final_tick;
    uint32_t can_error;
} ucan_can_tx_resp_t;

typedef struct {
    uint32_t arm_epoch;
    uint32_t client_tag;
} ucan_can_tx_cancel_req_t;

typedef struct {
    uint32_t client_tag;
    uint32_t cancel_state;
} ucan_can_tx_cancel_resp_t;

typedef struct {
    uint64_t host_send_ns;
    uint32_t sample_id;
} ucan_ping_req_t;

typedef struct {
    uint64_t host_send_ns;
    uint64_t device_rx_tick;
    uint64_t device_tx_tick;
    uint32_t sample_id;
} ucan_ping_resp_t;

typedef struct {
    uint16_t detail_code;
    uint16_t error_flags;
    uint32_t field_offset;
    uint32_t expected;
    uint32_t actual;
    uint16_t debug_len;
    const uint8_t *debug;
} ucan_error_payload_t;

typedef struct {
    uint32_t delta_tick;
    uint32_t arbitration_id;
    uint32_t channel_sequence;
    uint16_t flags;
    uint8_t channel;
    uint8_t dlc;
    uint8_t filter_hit;
    uint16_t rx_status;
    const uint8_t *payload;
    uint8_t payload_len;
} ucan_can_rx_record_t;

typedef struct {
    uint16_t flags;
    uint64_t base_timestamp;
    uint64_t device_drop_total;
    uint32_t config_generation;
    const ucan_can_rx_record_t *records;
    uint16_t record_count;
} ucan_can_rx_batch_t;

typedef struct {
    uint32_t client_tag;
    uint32_t arm_epoch;
    uint16_t result;
    uint64_t hardware_tick;
    uint32_t can_error;
    uint32_t queue_generation;
} ucan_can_tx_result_event_t;

typedef struct {
    uint8_t channel;
    uint8_t state;
    uint16_t reason;
    uint32_t config_generation;
    uint32_t tx_error;
    uint32_t rx_error;
    uint64_t device_tick;
} ucan_channel_state_event_t;

typedef struct {
    uint32_t response_depth;
    uint32_t event_depth;
    uint32_t data_depth;
    uint32_t pool_high_water;
    uint64_t device_tick;
} ucan_flow_control_event_t;

typedef struct {
    uint8_t channel;
    uint8_t source;
    uint8_t sequence_domain;
    uint16_t reason;
    uint32_t config_generation;
    uint32_t first_dropped_sequence;
    uint32_t last_dropped_sequence;
    uint64_t dropped_count;
    uint64_t device_tick;
} ucan_data_loss_event_t;

/* ---- Payload codec entry points (encode: caller-provided buffer) ---- */

int ucan_encode_hello_req(const ucan_hello_req_t *v, uint8_t *out, uint32_t cap, uint32_t *len);
int ucan_decode_hello_req(const uint8_t *data, uint32_t len, ucan_hello_req_t *v);
int ucan_encode_hello_resp(const ucan_hello_resp_t *v, uint8_t *out, uint32_t cap, uint32_t *len);
int ucan_decode_hello_resp(const uint8_t *data, uint32_t len, ucan_hello_resp_t *v);
int ucan_encode_device_info(const ucan_device_info_t *v, uint8_t *out, uint32_t cap, uint32_t *len);
int ucan_decode_device_info(const uint8_t *data, uint32_t len, ucan_device_info_t *v);
int ucan_encode_capabilities(const ucan_capabilities_t *v, uint8_t *out, uint32_t cap, uint32_t *len);
int ucan_decode_capabilities(const uint8_t *data, uint32_t len, ucan_capabilities_t *v,
                             ucan_channel_cap_t *channels, uint8_t max_channels);
int ucan_encode_diagnostics(const ucan_diagnostics_t *v, uint8_t *out, uint32_t cap, uint32_t *len);
int ucan_decode_diagnostics(const uint8_t *data, uint32_t len, ucan_diagnostics_t *v,
                            ucan_channel_diag_t *channels, uint8_t max_channels);
int ucan_encode_reset_diagnostics(uint32_t mask, uint8_t *out, uint32_t cap, uint32_t *len);
int ucan_decode_reset_diagnostics(const uint8_t *data, uint32_t len, uint32_t *mask);
int ucan_encode_session_state(const ucan_session_state_t *v, uint8_t *out, uint32_t cap, uint32_t *len);
int ucan_decode_session_state(const uint8_t *data, uint32_t len, ucan_session_state_t *v,
                              ucan_filter_state_t *filters, uint8_t max_filters);
int ucan_encode_channel_config(const ucan_channel_config_t *v, uint8_t *out, uint32_t cap, uint32_t *len);
int ucan_decode_channel_config(const uint8_t *data, uint32_t len, ucan_channel_config_t *v);
int ucan_encode_get_channel_config(const ucan_clear_filters_req_t *v, uint8_t *out, uint32_t cap, uint32_t *len);
int ucan_decode_get_channel_config(const uint8_t *data, uint32_t len, ucan_clear_filters_req_t *v);
int ucan_encode_capture_req(const ucan_capture_req_t *v, uint8_t *out, uint32_t cap, uint32_t *len);
int ucan_decode_capture_req(const uint8_t *data, uint32_t len, ucan_capture_req_t *v);
int ucan_encode_capture_resp(const ucan_capture_resp_t *v, uint8_t *out, uint32_t cap, uint32_t *len);
int ucan_decode_capture_resp(const uint8_t *data, uint32_t len, ucan_capture_resp_t *v);
int ucan_encode_set_filters(const ucan_set_filters_req_t *v, uint8_t *out, uint32_t cap, uint32_t *len);
int ucan_decode_set_filters(const uint8_t *data, uint32_t len, ucan_set_filters_req_t *v,
                            ucan_filter_rule_t *rules, uint8_t max_rules);
int ucan_encode_set_filters_resp(const ucan_set_filters_resp_t *v, uint8_t *out, uint32_t cap, uint32_t *len);
int ucan_decode_set_filters_resp(const uint8_t *data, uint32_t len, ucan_set_filters_resp_t *v);
int ucan_encode_clear_filters(const ucan_clear_filters_req_t *v, uint8_t *out, uint32_t cap, uint32_t *len);
int ucan_decode_clear_filters(const uint8_t *data, uint32_t len, ucan_clear_filters_req_t *v);
int ucan_encode_clear_filters_resp(const ucan_clear_filters_resp_t *v, uint8_t *out, uint32_t cap, uint32_t *len);
int ucan_decode_clear_filters_resp(const uint8_t *data, uint32_t len, ucan_clear_filters_resp_t *v);
int ucan_encode_tx_arm(const ucan_tx_arm_req_t *v, uint8_t *out, uint32_t cap, uint32_t *len);
int ucan_decode_tx_arm(const uint8_t *data, uint32_t len, ucan_tx_arm_req_t *v,
                       ucan_tx_rule_t *rules, uint8_t max_rules);
int ucan_encode_tx_arm_resp(const ucan_tx_arm_resp_t *v, uint8_t *out, uint32_t cap, uint32_t *len);
int ucan_decode_tx_arm_resp(const uint8_t *data, uint32_t len, ucan_tx_arm_resp_t *v);
int ucan_encode_tx_disarm(const ucan_tx_disarm_req_t *v, uint8_t *out, uint32_t cap, uint32_t *len);
int ucan_decode_tx_disarm(const uint8_t *data, uint32_t len, ucan_tx_disarm_req_t *v);
int ucan_encode_tx_disarm_resp(const ucan_tx_disarm_resp_t *v, uint8_t *out, uint32_t cap, uint32_t *len);
int ucan_decode_tx_disarm_resp(const uint8_t *data, uint32_t len, ucan_tx_disarm_resp_t *v);
int ucan_encode_can_tx(const ucan_can_tx_req_t *v, uint8_t *out, uint32_t cap, uint32_t *len);
int ucan_decode_can_tx(const uint8_t *data, uint32_t len, ucan_can_tx_req_t *v);
int ucan_encode_can_tx_resp(const ucan_can_tx_resp_t *v, uint8_t *out, uint32_t cap, uint32_t *len);
int ucan_decode_can_tx_resp(const uint8_t *data, uint32_t len, ucan_can_tx_resp_t *v);
int ucan_encode_can_tx_cancel(const ucan_can_tx_cancel_req_t *v, uint8_t *out, uint32_t cap, uint32_t *len);
int ucan_decode_can_tx_cancel(const uint8_t *data, uint32_t len, ucan_can_tx_cancel_req_t *v);
int ucan_encode_can_tx_cancel_resp(const ucan_can_tx_cancel_resp_t *v, uint8_t *out, uint32_t cap, uint32_t *len);
int ucan_decode_can_tx_cancel_resp(const uint8_t *data, uint32_t len, ucan_can_tx_cancel_resp_t *v);
int ucan_encode_ping_req(const ucan_ping_req_t *v, uint8_t *out, uint32_t cap, uint32_t *len);
int ucan_decode_ping_req(const uint8_t *data, uint32_t len, ucan_ping_req_t *v);
int ucan_encode_ping_resp(const ucan_ping_resp_t *v, uint8_t *out, uint32_t cap, uint32_t *len);
int ucan_decode_ping_resp(const uint8_t *data, uint32_t len, ucan_ping_resp_t *v);
int ucan_encode_error_payload(const ucan_error_payload_t *v, uint8_t *out, uint32_t cap, uint32_t *len);
int ucan_decode_error_payload(const uint8_t *data, uint32_t len, ucan_error_payload_t *v);
int ucan_encode_can_rx_batch(const ucan_can_rx_batch_t *v, uint8_t *out, uint32_t cap, uint32_t *len);
int ucan_decode_can_rx_batch(const uint8_t *data, uint32_t len, ucan_can_rx_batch_t *v,
                             ucan_can_rx_record_t *records, uint16_t max_records);
int ucan_encode_can_tx_result(const ucan_can_tx_result_event_t *v, uint8_t *out, uint32_t cap, uint32_t *len);
int ucan_decode_can_tx_result(const uint8_t *data, uint32_t len, ucan_can_tx_result_event_t *v);
int ucan_encode_channel_state(const ucan_channel_state_event_t *v, uint8_t *out, uint32_t cap, uint32_t *len);
int ucan_decode_channel_state(const uint8_t *data, uint32_t len, ucan_channel_state_event_t *v);
int ucan_encode_flow_control(const ucan_flow_control_event_t *v, uint8_t *out, uint32_t cap, uint32_t *len);
int ucan_decode_flow_control(const uint8_t *data, uint32_t len, ucan_flow_control_event_t *v);
int ucan_encode_data_loss(const ucan_data_loss_event_t *v, uint8_t *out, uint32_t cap, uint32_t *len);
int ucan_decode_data_loss(const uint8_t *data, uint32_t len, ucan_data_loss_event_t *v);

/* Encode/decode an empty request payload (GET_DEVICE_INFO, GET_CAPABILITIES, ...). */
int ucan_decode_empty(const uint8_t *data, uint32_t len);

#ifdef __cplusplus
}
#endif

#endif /* UCAN_CODEC_H */
