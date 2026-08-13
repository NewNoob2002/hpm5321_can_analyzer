/*
 * USB-CAN protocol v1.0 device-side session core.
 *
 * Pure C99, no HAL/RTOS deps: the same sources run host unit tests and the
 * HPM firmware protocol task. Implements the normative state machine from
 * docs/approved-plan/usb-can-protocol-v1.md sections 5.2/7/8: CAS
 * generations, arm epoch, conservative TX admission, exactly-once TX result
 * ledger, request replay cache, bounded-loss accounting and priority egress
 * queues.
 */
#ifndef UCAN_SESSION_H
#define UCAN_SESSION_H

#include "ucan_codec.h"

#ifdef __cplusplus
extern "C" {
#endif

#define UCAN_SESSION_MAX_CHANNELS 2
#define UCAN_SESSION_MAX_RULES 16
#define UCAN_SESSION_MAX_FILTERS 32
#define UCAN_SESSION_MAX_TX_SLOTS 16
#define UCAN_SESSION_REPLAY_ENTRIES 8

/* Bounded egress queues (spec 8.1). */
#define UCAN_QUEUE_RESPONSE_CAP 8
#define UCAN_QUEUE_CRITICAL_CAP 16
#define UCAN_QUEUE_DATA_CAP 32
#define UCAN_QUEUE_FRAME_BYTES 512

typedef struct {
    uint8_t channel;
    uint8_t mode; /* 0 DISABLED, 1 LISTEN_ONLY, 2 CLASSIC, 3 FD */
    uint16_t flags;
    uint32_t nominal_bps;
    uint32_t data_bps;
    uint16_t sample_permille;
    uint8_t state; /* 0..4 channel state */
    uint32_t filter_generation;
    uint32_t filter_crc;
    uint16_t filter_count;
    ucan_filter_rule_t filters[UCAN_SESSION_MAX_FILTERS];
    uint64_t rx_frames;
    uint64_t tx_frames;
    uint64_t filtered;
    uint64_t dropped;
    uint32_t rx_depth;
    uint32_t tx_depth;
    uint32_t bus_off_count;
    uint32_t error_count;
} ucan_session_channel_t;

/* TX result ledger slot (spec 5.2/8.1): exactly one semantic final result. */
typedef struct {
    uint8_t occupied;
    uint8_t delivery_pending;
    uint8_t submitted;
    uint8_t channel;
    uint16_t can_flags;
    uint8_t dlc;
    uint8_t payload_len;
    uint8_t payload[64];
    uint32_t client_tag;
    uint32_t arm_epoch;
    uint16_t state; /* tx_state: PENDING=1, FINAL=2 */
    uint16_t final_result;
    uint64_t final_tick;
    uint32_t can_error;
    uint32_t arbitration_id;
    uint64_t completed_tick;
    uint32_t rule_index;
    uint32_t result_evt_seq; /* device_event_sequence of the CAN_TX_RESULT event */
    uint64_t deadline_tick;  /* client-declared deadline; 0 = immediate */
} ucan_tx_slot_t;

/* Request replay cache entry (spec 5.2). */
typedef struct {
    uint8_t occupied;
    uint32_t sequence;
    uint16_t message_type;
    uint64_t stored_tick;
    uint32_t payload_len;
    uint32_t payload_crc32c;
    uint32_t response_len;
    uint8_t response[512];
} ucan_replay_entry_t;

/* DATA_LOSS accumulator (spec 8.1): merged contiguous ranges per key. */
typedef struct {
    uint8_t occupied;
    uint8_t channel;
    uint8_t source;
    uint8_t sequence_domain;
    uint16_t reason;
    uint32_t config_generation;
    uint32_t first_sequence;
    uint32_t last_sequence;
    uint64_t dropped_count;
    uint32_t evt_seq; /* device_event_sequence, allocated only on successful admission */
} ucan_loss_acc_t;

typedef struct {
    uint8_t data[UCAN_QUEUE_FRAME_BYTES];
    uint32_t len;
    uint32_t evt_seq;
    uint8_t kind; /* 1 response, 2 critical, 3 data */
} ucan_queue_item_t;

typedef struct {
    ucan_queue_item_t items[UCAN_QUEUE_RESPONSE_CAP];
    uint16_t head;
    uint16_t count;
} ucan_q_response_t;

typedef struct {
    ucan_queue_item_t items[UCAN_QUEUE_CRITICAL_CAP];
    uint16_t head;
    uint16_t count;
} ucan_q_critical_t;

typedef struct {
    ucan_queue_item_t items[UCAN_QUEUE_DATA_CAP];
    uint16_t head;
    uint16_t count;
} ucan_q_data_t;

typedef struct {
    const char *fw_semver;
    const char *build_id;
    const char *board_id;
    const char *serial;
    uint32_t tick_hz;
    uint32_t tick_resolution_ns;
    uint16_t tx_depth;
    uint16_t outstanding_limit;
    uint16_t response_capacity;
    uint16_t event_capacity;
    uint16_t data_capacity;
    uint16_t arm_timeout_min_ms;
    uint16_t arm_timeout_max_ms;
    uint8_t usb_mode; /* 1 FS, 2 HS */
    uint16_t global_features;
    uint16_t replay_cache_entries;
    uint16_t tx_result_cache_entries;
    uint32_t replay_retention_ms;
    uint32_t tag_reuse_guard_ms;
    uint32_t max_message; /* device/configured receive ceiling */
    uint32_t session_id;  /* nonzero boot/session nonce */
    uint64_t boot_epoch;  /* nonzero boot identity */
    uint8_t channel_count;
    ucan_channel_cap_t channels[UCAN_SESSION_MAX_CHANNELS];
    /* Actual safe hardware mode present when a session is initialized. It
     * must be advertised in the corresponding mode_mask. */
    uint8_t initial_mode[UCAN_SESSION_MAX_CHANNELS];
    /* Immutable product safety ceiling for each physical channel. A zero
     * entry disables TX on that channel. */
    uint16_t product_max_bus_load_permille[UCAN_SESSION_MAX_CHANNELS];
} ucan_session_config_t;

typedef struct {
    uint32_t config_generation; /* starts 1; CAS by equality; wrap skips 0 */
    uint32_t capture_generation;
    uint8_t capture_state; /* STOPPED=0, STARTED=1 */
    uint32_t capture_flags;
    uint8_t tx_armed;
    uint32_t arm_epoch; /* starts 1; advances on arm/disarm; wrap skips 0 */
    uint64_t arm_expiry_tick;
    uint32_t aggregate_max_frames_per_s;
    uint16_t max_bus_load_permille;
    uint32_t session_id;
    uint32_t diag_generation;
    uint32_t queue_generation;
    uint64_t boot_epoch;
    uint64_t tick;
    uint64_t usb_rx_bytes;
    uint64_t usb_tx_bytes;
    uint32_t response_depth;
    uint32_t event_depth;
    uint32_t data_depth;
    uint32_t pool_high_water;
    uint32_t device_event_sequence; /* allocated before queue admission */
    uint32_t next_channel_sequence[UCAN_SESSION_MAX_CHANNELS];
    uint8_t negotiated; /* set once HELLO succeeds; gates all other requests */
    uint8_t min_minor;  /* negotiated minimum minor (lowest common) */
    uint8_t max_minor;  /* negotiated maximum minor */
    uint32_t host_rx_max_message; /* device->host payload ceiling from HELLO */
    uint32_t negotiated_features; /* immutable until USB session reset */
    ucan_session_channel_t channels[UCAN_SESSION_MAX_CHANNELS];
    ucan_tx_slot_t tx_ledger[UCAN_SESSION_MAX_TX_SLOTS];
    ucan_replay_entry_t replay[UCAN_SESSION_REPLAY_ENTRIES];
    ucan_loss_acc_t loss[4]; /* one accumulator per loss key slot */
    /* TX admission */
    uint32_t rule_count;
    ucan_tx_rule_t rules[UCAN_SESSION_MAX_RULES];
    uint64_t rule_tokens[UCAN_SESSION_MAX_RULES];
    uint64_t rule_capacity[UCAN_SESSION_MAX_RULES];
    uint64_t rule_last_tick[UCAN_SESSION_MAX_RULES];
    uint64_t agg_tokens;
    uint64_t agg_capacity;
    uint64_t agg_last_tick;
    uint16_t served_since_data;
    uint16_t response_streak;
    uint8_t pending_channel_state_valid[UCAN_SESSION_MAX_CHANNELS];
    uint8_t pending_channel_state[UCAN_SESSION_MAX_CHANNELS];
    uint16_t pending_channel_reason[UCAN_SESSION_MAX_CHANNELS];
    uint8_t flow_control_pending;
    uint64_t last_flow_control_tick;
    /* egress queues */
    ucan_q_response_t q_response;
    ucan_q_critical_t q_critical;
    ucan_q_critical_t q_critical_pending;
    ucan_q_data_t q_data;
    const ucan_session_config_t *cfg;
} ucan_session_t;

int ucan_session_init(ucan_session_t *s, const ucan_session_config_t *cfg);

/* Reinitialize a session with a new nonzero boot/session identity. */
int ucan_session_reinit(ucan_session_t *s, const ucan_session_config_t *cfg,
                        uint32_t session_id, uint64_t boot_epoch);

/* Advance the device tick; auto-disarms an expired arm. */
void ucan_session_tick(ucan_session_t *s, uint64_t ticks);

/* CAN ring admission hook (called before queue write). Returns 0 on admit,
 * 1 when the ring dropped the frame (accumulates DATA_LOSS, CHANNEL domain),
 * or 2 when capture flags/filters intentionally exclude it. */
int ucan_session_on_rx(ucan_session_t *s, uint8_t channel,
                       ucan_can_rx_record_t *rec);

/* Report frames lost by an upstream hardware/ISR ring before payload-level
 * filtering was possible. Conservatively allocates CHANNEL-domain sequence
 * numbers and emits DATA_LOSS, so the loss is never silent. */
void ucan_session_note_rx_ring_loss(ucan_session_t *s, uint8_t channel,
                                    uint32_t count);

/* Emit/retry a rate-limited FLOW_CONTROL snapshot when any queue reaches 75%
 * of its advertised capacity. Safe to call from the protocol task poll loop. */
void ucan_session_poll_flow_control(ucan_session_t *s);

/* USB-task hook: move one captured frame into the data queue as a single-record
 * CAN_RX_BATCH (capture active). Returns 0 on enqueue; 1 when the data queue is
 * full (accumulates DATA_LOSS, EVENT domain, channel 0xFF). */
int ucan_session_emit_rx_batch(ucan_session_t *s, uint8_t channel,
                               const ucan_can_rx_record_t *rec);
/* Timestamp-preserving form for hardware RX owners. The single encoded record
 * has delta_tick=0 and base_timestamp equal to the supplied hardware tick. */
int ucan_session_emit_rx_batch_at(ucan_session_t *s, uint8_t channel,
                                  const ucan_can_rx_record_t *rec,
                                  uint64_t base_timestamp);

/* Poll one newly accepted TX exactly once for submission to the CAN owner.
 * Returns 0 and fills tx, or 1 when no unsubmitted TX is pending. The payload
 * pointer remains owned by the session. */
int ucan_session_take_pending_tx(ucan_session_t *s, ucan_can_tx_req_t *tx);

/* Mark an immediate hardware submission failure as the request's single final
 * result (for example BUS_ERROR); equivalent to a completion at current tick. */
void ucan_session_can_tx_submit_failed(ucan_session_t *s, uint32_t client_tag,
                                       uint16_t result, uint32_t can_error);

/* Hardware TX completion hook: exactly one semantic final per client tag. */
void ucan_session_can_tx_complete(ucan_session_t *s, uint32_t client_tag,
                                  uint16_t result, uint32_t can_error);

/* Host-request entry: returns the response synchronously only; responses are
 * never also placed in the dequeue queue. Async events remain queued. */
int ucan_session_handle_frame(ucan_session_t *s, const ucan_frame_t *req,
                              uint8_t *out, uint32_t cap, uint32_t *out_len);

/* Priority egress (spec 8.1): response first, then at least one critical per
 * 8 responses and one data batch per 16 control/critical messages. Copies
 * the next frame into out. Returns 0, or 1 when all queues are empty. */
int ucan_session_dequeue(ucan_session_t *s, uint8_t *out, uint32_t cap,
                         uint32_t *out_len, uint32_t *evt_seq);

/* Per-channel reserved load permille used by admission (spec 7.1). */
uint32_t ucan_session_reserved_permille(const ucan_session_t *s, uint8_t channel);

/* Worst-case CAN frame time in microseconds (spec 7.1). */
uint64_t ucan_frame_time_us(uint32_t nominal_bps, uint32_t data_bps, uint8_t dlc,
                            uint16_t can_flags, uint8_t payload_len);

#ifdef __cplusplus
}
#endif

#endif /* UCAN_SESSION_H */
