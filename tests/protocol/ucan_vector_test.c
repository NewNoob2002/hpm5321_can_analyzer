/*
 * Host parity harness for the C USB-CAN v1.0 codec.
 *
 * Reads every golden vector under protocol/v1/0/, decodes the frame with the
 * C codec, re-encodes the payload, rebuilds the frame and requires a
 * byte-exact match with the original vector. Also runs CRC canonical and
 * negative-path checks. Compiles against protocol/v1/c with the host
 * toolchain only.
 */
#include "ucan_codec.h"

#include <dirent.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

/* All payload structs share offset 0 in the union, so a single address is
 * valid for every typed decode/encode wrapper below. */
typedef union {
    ucan_hello_req_t hello_req;
    ucan_hello_resp_t hello_resp;
    ucan_device_info_t device_info;
    ucan_capabilities_t capabilities;
    ucan_diagnostics_t diagnostics;
    ucan_mcan_diagnostics_t mcan_diagnostics;
    uint32_t reset_mask;
    ucan_session_state_t session_state;
    ucan_channel_config_t channel_config;
    ucan_clear_filters_req_t get_channel_config;
    ucan_capture_req_t capture_req;
    ucan_capture_resp_t capture_resp;
    ucan_set_filters_req_t set_filters;
    ucan_set_filters_resp_t set_filters_resp;
    ucan_clear_filters_req_t clear_filters;
    ucan_clear_filters_resp_t clear_filters_resp;
    ucan_tx_arm_req_t tx_arm;
    ucan_tx_arm_resp_t tx_arm_resp;
    ucan_tx_disarm_req_t tx_disarm;
    ucan_tx_disarm_resp_t tx_disarm_resp;
    ucan_can_tx_req_t can_tx;
    ucan_can_tx_resp_t can_tx_resp;
    ucan_can_tx_cancel_req_t can_tx_cancel;
    ucan_can_tx_cancel_resp_t can_tx_cancel_resp;
    ucan_ping_req_t ping_req;
    ucan_ping_resp_t ping_resp;
    ucan_error_payload_t error_payload;
    ucan_can_rx_batch_t can_rx_batch;
    ucan_can_tx_result_event_t can_tx_result;
    ucan_channel_state_event_t channel_state;
    ucan_flow_control_event_t flow_control;
    ucan_data_loss_event_t data_loss;
} payload_t;

/* Payload struct plus decode arrays for the multi-record payloads. */
typedef struct {
    payload_t u;
    ucan_channel_cap_t channels[4];
    ucan_channel_diag_t diag[4];
    ucan_filter_state_t filters[8];
    ucan_filter_rule_t filter_rules[8];
    ucan_tx_rule_t tx_rules[16];
    ucan_can_rx_record_t rx_records[16];
} test_ctx_t;

typedef int (*decoder_fn)(const uint8_t *, uint32_t, void *);
typedef int (*encoder_fn)(const void *, uint8_t *, uint32_t, uint32_t *);

#define WRAP_DEC(name, T)                                                      \
    static int dec_##name(const uint8_t *d, uint32_t l, void *o) {             \
        return ucan_decode_##name(d, l, (T *)o);                               \
    }
#define WRAP_ENC(name, T)                                                      \
    static int enc_##name(const void *o, uint8_t *d, uint32_t c, uint32_t *l) { \
        return ucan_encode_##name((const T *)o, d, c, l);                      \
    }

static int dec_empty(const uint8_t *d, uint32_t l, void *o) {
    (void)o;
    return ucan_decode_empty(d, l);
}
static int enc_empty(const void *o, uint8_t *d, uint32_t c, uint32_t *l) {
    (void)o;
    (void)d;
    (void)c;
    *l = 0;
    return 0;
}

WRAP_DEC(hello_req, ucan_hello_req_t)
WRAP_ENC(hello_req, ucan_hello_req_t)
WRAP_DEC(hello_resp, ucan_hello_resp_t)
WRAP_ENC(hello_resp, ucan_hello_resp_t)
WRAP_DEC(device_info, ucan_device_info_t)
WRAP_ENC(device_info, ucan_device_info_t)
WRAP_ENC(capabilities, ucan_capabilities_t)
WRAP_ENC(diagnostics, ucan_diagnostics_t)
WRAP_DEC(mcan_diagnostics, ucan_mcan_diagnostics_t)
WRAP_ENC(mcan_diagnostics, ucan_mcan_diagnostics_t)
WRAP_DEC(reset_diagnostics, uint32_t)
static int enc_reset_diagnostics(const void *o, uint8_t *d, uint32_t c,
                                 uint32_t *l) {
    return ucan_encode_reset_diagnostics(*(const uint32_t *)o, d, c, l);
}
WRAP_ENC(session_state, ucan_session_state_t)
WRAP_DEC(channel_config, ucan_channel_config_t)
WRAP_ENC(channel_config, ucan_channel_config_t)
WRAP_DEC(get_channel_config, ucan_clear_filters_req_t)
WRAP_ENC(get_channel_config, ucan_clear_filters_req_t)
WRAP_DEC(capture_req, ucan_capture_req_t)
WRAP_ENC(capture_req, ucan_capture_req_t)
WRAP_DEC(capture_resp, ucan_capture_resp_t)
WRAP_ENC(capture_resp, ucan_capture_resp_t)
WRAP_ENC(set_filters, ucan_set_filters_req_t)
WRAP_DEC(set_filters_resp, ucan_set_filters_resp_t)
WRAP_ENC(set_filters_resp, ucan_set_filters_resp_t)
WRAP_DEC(clear_filters, ucan_clear_filters_req_t)
WRAP_ENC(clear_filters, ucan_clear_filters_req_t)
WRAP_DEC(clear_filters_resp, ucan_clear_filters_resp_t)
WRAP_ENC(clear_filters_resp, ucan_clear_filters_resp_t)
WRAP_ENC(tx_arm, ucan_tx_arm_req_t)
WRAP_DEC(tx_arm_resp, ucan_tx_arm_resp_t)
WRAP_ENC(tx_arm_resp, ucan_tx_arm_resp_t)
WRAP_DEC(tx_disarm, ucan_tx_disarm_req_t)
WRAP_ENC(tx_disarm, ucan_tx_disarm_req_t)
WRAP_DEC(tx_disarm_resp, ucan_tx_disarm_resp_t)
WRAP_ENC(tx_disarm_resp, ucan_tx_disarm_resp_t)
WRAP_DEC(can_tx, ucan_can_tx_req_t)
WRAP_ENC(can_tx, ucan_can_tx_req_t)
WRAP_DEC(can_tx_resp, ucan_can_tx_resp_t)
WRAP_ENC(can_tx_resp, ucan_can_tx_resp_t)
WRAP_DEC(can_tx_cancel, ucan_can_tx_cancel_req_t)
WRAP_ENC(can_tx_cancel, ucan_can_tx_cancel_req_t)
WRAP_DEC(can_tx_cancel_resp, ucan_can_tx_cancel_resp_t)
WRAP_ENC(can_tx_cancel_resp, ucan_can_tx_cancel_resp_t)
WRAP_DEC(ping_req, ucan_ping_req_t)
WRAP_ENC(ping_req, ucan_ping_req_t)
WRAP_DEC(ping_resp, ucan_ping_resp_t)
WRAP_ENC(ping_resp, ucan_ping_resp_t)
WRAP_DEC(error_payload, ucan_error_payload_t)
WRAP_ENC(error_payload, ucan_error_payload_t)
WRAP_ENC(can_rx_batch, ucan_can_rx_batch_t)
WRAP_DEC(can_tx_result, ucan_can_tx_result_event_t)
WRAP_ENC(can_tx_result, ucan_can_tx_result_event_t)
WRAP_DEC(channel_state, ucan_channel_state_event_t)
WRAP_ENC(channel_state, ucan_channel_state_event_t)
WRAP_DEC(flow_control, ucan_flow_control_event_t)
WRAP_ENC(flow_control, ucan_flow_control_event_t)
WRAP_DEC(data_loss, ucan_data_loss_event_t)
WRAP_ENC(data_loss, ucan_data_loss_event_t)

/* Multi-record decoders need the context arrays. */
static int dec_capabilities(const uint8_t *d, uint32_t l, void *o) {
    test_ctx_t *ctx = o;
    return ucan_decode_capabilities(d, l, &ctx->u.capabilities, ctx->channels,
                                    (uint8_t)(sizeof(ctx->channels) /
                                              sizeof(ctx->channels[0])));
}
static int dec_diagnostics(const uint8_t *d, uint32_t l, void *o) {
    test_ctx_t *ctx = o;
    return ucan_decode_diagnostics(d, l, &ctx->u.diagnostics, ctx->diag,
                                   (uint8_t)(sizeof(ctx->diag) / sizeof(ctx->diag[0])));
}
static int dec_session_state(const uint8_t *d, uint32_t l, void *o) {
    test_ctx_t *ctx = o;
    return ucan_decode_session_state(d, l, &ctx->u.session_state, ctx->filters,
                                     (uint8_t)(sizeof(ctx->filters) /
                                               sizeof(ctx->filters[0])));
}
static int dec_set_filters(const uint8_t *d, uint32_t l, void *o) {
    test_ctx_t *ctx = o;
    return ucan_decode_set_filters(d, l, &ctx->u.set_filters, ctx->filter_rules,
                                   (uint8_t)(sizeof(ctx->filter_rules) /
                                             sizeof(ctx->filter_rules[0])));
}
static int dec_tx_arm(const uint8_t *d, uint32_t l, void *o) {
    test_ctx_t *ctx = o;
    return ucan_decode_tx_arm(d, l, &ctx->u.tx_arm, ctx->tx_rules,
                              (uint8_t)(sizeof(ctx->tx_rules) /
                                        sizeof(ctx->tx_rules[0])));
}
static int dec_can_rx_batch(const uint8_t *d, uint32_t l, void *o) {
    test_ctx_t *ctx = o;
    return ucan_decode_can_rx_batch(d, l, &ctx->u.can_rx_batch, ctx->rx_records,
                                    (uint16_t)(sizeof(ctx->rx_records) /
                                               sizeof(ctx->rx_records[0])));
}

typedef struct {
    const char *name;
    uint16_t message_type;
    int is_error;
    decoder_fn dec;
    encoder_fn enc;
} vector_entry_t;

static const vector_entry_t VECTORS[] = {
    {"hello-request.hex", UCAN_MSG_HELLO, 0, dec_hello_req, enc_hello_req},
    {"hello-response.hex", UCAN_MSG_HELLO, 0, dec_hello_resp, enc_hello_resp},
    {"device-info-response.hex", UCAN_MSG_GET_DEVICE_INFO, 0, dec_device_info,
     enc_device_info},
    {"capabilities-response.hex", UCAN_MSG_GET_CAPABILITIES, 0, dec_capabilities,
     enc_capabilities},
    {"get-diagnostics-request.hex", UCAN_MSG_GET_DIAGNOSTICS, 0, dec_empty,
     enc_empty},
    {"get-diagnostics-response.hex", UCAN_MSG_GET_DIAGNOSTICS, 0, dec_diagnostics,
     enc_diagnostics},
    {"get-mcan-diagnostics-request.hex", UCAN_MSG_GET_MCAN_DIAGNOSTICS, 0,
     dec_empty, enc_empty},
    {"get-mcan-diagnostics-response.hex", UCAN_MSG_GET_MCAN_DIAGNOSTICS, 0,
     dec_mcan_diagnostics, enc_mcan_diagnostics},
    {"reset-diagnostics-request.hex", UCAN_MSG_RESET_DIAGNOSTICS, 0,
     dec_reset_diagnostics, enc_reset_diagnostics},
    {"get-session-state-request.hex", UCAN_MSG_GET_SESSION_STATE, 0, dec_empty,
     enc_empty},
    {"get-session-state-response.hex", UCAN_MSG_GET_SESSION_STATE, 0,
     dec_session_state, enc_session_state},
    {"config-channel-request.hex", UCAN_MSG_CONFIG_CHANNEL, 0, dec_channel_config,
     enc_channel_config},
    {"config-channel-response.hex", UCAN_MSG_CONFIG_CHANNEL, 0, dec_channel_config,
     enc_channel_config},
    {"error-response.hex", UCAN_MSG_CONFIG_CHANNEL, 1, dec_error_payload,
     enc_error_payload},
    {"get-channel-config-request.hex", UCAN_MSG_GET_CHANNEL_CONFIG, 0,
     dec_get_channel_config, enc_get_channel_config},
    {"start-capture-request.hex", UCAN_MSG_START_CAPTURE, 0, dec_capture_req,
     enc_capture_req},
    {"start-capture-response.hex", UCAN_MSG_START_CAPTURE, 0, dec_capture_resp,
     enc_capture_resp},
    {"stop-capture-request.hex", UCAN_MSG_STOP_CAPTURE, 0, dec_capture_req,
     enc_capture_req},
    {"stop-capture-response.hex", UCAN_MSG_STOP_CAPTURE, 0, dec_capture_resp,
     enc_capture_resp},
    {"set-filters-request.hex", UCAN_MSG_SET_FILTERS, 0, dec_set_filters,
     enc_set_filters},
    {"set-filters-response.hex", UCAN_MSG_SET_FILTERS, 0, dec_set_filters_resp,
     enc_set_filters_resp},
    {"clear-filters-request.hex", UCAN_MSG_CLEAR_FILTERS, 0, dec_clear_filters,
     enc_clear_filters},
    {"clear-filters-response.hex", UCAN_MSG_CLEAR_FILTERS, 0,
     dec_clear_filters_resp, enc_clear_filters_resp},
    {"tx-arm-request.hex", UCAN_MSG_TX_ARM, 0, dec_tx_arm, enc_tx_arm},
    {"tx-arm-response.hex", UCAN_MSG_TX_ARM, 0, dec_tx_arm_resp, enc_tx_arm_resp},
    {"tx-disarm-request.hex", UCAN_MSG_TX_DISARM, 0, dec_tx_disarm, enc_tx_disarm},
    {"tx-disarm-response.hex", UCAN_MSG_TX_DISARM, 0, dec_tx_disarm_resp,
     enc_tx_disarm_resp},
    {"can-tx-request.hex", UCAN_MSG_CAN_TX, 0, dec_can_tx, enc_can_tx},
    {"can-tx-response.hex", UCAN_MSG_CAN_TX, 0, dec_can_tx_resp, enc_can_tx_resp},
    {"can-tx-cancel-request.hex", UCAN_MSG_CAN_TX_CANCEL, 0, dec_can_tx_cancel,
     enc_can_tx_cancel},
    {"can-tx-cancel-response.hex", UCAN_MSG_CAN_TX_CANCEL, 0,
     dec_can_tx_cancel_resp, enc_can_tx_cancel_resp},
    {"ping-request.hex", UCAN_MSG_PING, 0, dec_ping_req, enc_ping_req},
    {"ping-response.hex", UCAN_MSG_PING, 0, dec_ping_resp, enc_ping_resp},
    {"can-rx-batch.hex", UCAN_MSG_CAN_RX_BATCH, 0, dec_can_rx_batch,
     enc_can_rx_batch},
    {"can-tx-result.hex", UCAN_MSG_CAN_TX_RESULT, 0, dec_can_tx_result,
     enc_can_tx_result},
    {"channel-state.hex", UCAN_MSG_CHANNEL_STATE, 0, dec_channel_state,
     enc_channel_state},
    {"flow-control.hex", UCAN_MSG_FLOW_CONTROL, 0, dec_flow_control,
     enc_flow_control},
    {"data-loss.hex", UCAN_MSG_DATA_LOSS, 0, dec_data_loss, enc_data_loss},
};

static int failures = 0;

static void check(int ok, const char *what, const char *vector) {
    if (!ok) {
        ++failures;
        fprintf(stderr, "FAIL: %s (%s)\n", what, vector == NULL ? "global" : vector);
    }
}

static int parse_hex_file(const char *path, uint8_t *out, uint32_t cap,
                          uint32_t *out_len) {
    FILE *f = fopen(path, "r");
    if (f == NULL) {
        return -1;
    }
    uint32_t n = 0;
    int hi = -1;
    int c;
    while ((c = fgetc(f)) != EOF) {
        int nibble;
        if (c >= '0' && c <= '9') {
            nibble = c - '0';
        } else if (c >= 'a' && c <= 'f') {
            nibble = c - 'a' + 10;
        } else if (c >= 'A' && c <= 'F') {
            nibble = c - 'A' + 10;
        } else {
            continue; /* whitespace */
        }
        if (hi < 0) {
            hi = nibble;
        } else {
            if (n >= cap) {
                fclose(f);
                return -2;
            }
            out[n++] = (uint8_t)((hi << 4) | nibble);
            hi = -1;
        }
    }
    fclose(f);
    *out_len = n;
    return hi < 0 ? 0 : -3;
}

static void check_field_vectors(const vector_entry_t *e, const test_ctx_t *ctx) {
    const payload_t *u = &ctx->u;
    if (strcmp(e->name, "hello-response.hex") == 0) {
        check(u->hello_resp.session_id == 0x12345678u, "hello session_id",
              e->name);
        check(u->hello_resp.max_message == 65536u, "hello max_message", e->name);
    } else if (strcmp(e->name, "capabilities-response.hex") == 0) {
        check(u->capabilities.channel_count == 1, "cap channel_count", e->name);
        check(u->capabilities.usb_mode == 2, "cap usb_mode", e->name);
        check(u->capabilities.channels[0].max_filters == 32, "cap max_filters",
              e->name);
        check(u->capabilities.channels[0].mode_mask == 0x07, "cap mode_mask",
              e->name);
    } else if (strcmp(e->name, "get-mcan-diagnostics-response.hex") == 0) {
        check(u->mcan_diagnostics.version == UCAN_MCAN_DIAGNOSTICS_VERSION,
              "mcan diagnostics version", e->name);
        check(u->mcan_diagnostics.length == UCAN_MCAN_DIAGNOSTICS_LEN,
              "mcan diagnostics length", e->name);
        check(u->mcan_diagnostics.generation == 7u,
              "mcan diagnostics generation", e->name);
        check(u->mcan_diagnostics.snapshot_tick == 0x1122334455667788ull,
              "mcan diagnostics snapshot tick", e->name);
        check(u->mcan_diagnostics.rxfifo0_high_watermark == 9u,
              "mcan diagnostics fifo hwm", e->name);
        check(u->mcan_diagnostics.queue_high_watermark == 11u,
              "mcan diagnostics queue hwm", e->name);
        check(u->mcan_diagnostics.ring_drops == 15u,
              "mcan diagnostics ring drops", e->name);
        check(u->mcan_diagnostics.automatic_recovery_attempts == 20u,
              "mcan diagnostics recovery attempts", e->name);
    } else if (strcmp(e->name, "can-tx-request.hex") == 0) {
        check(u->can_tx.client_tag == 42u, "can_tx client_tag", e->name);
        check(u->can_tx.arm_epoch == 3u, "can_tx arm_epoch", e->name);
        check(u->can_tx.payload_len == 8u, "can_tx payload_len", e->name);
        check(u->can_tx.can_flags == 0x0001u, "can_tx flags", e->name);
    } else if (strcmp(e->name, "can-tx-response.hex") == 0) {
        check(u->can_tx_resp.tx_state == 1u, "can_tx_resp pending", e->name);
        check(u->can_tx_resp.client_tag == 42u, "can_tx_resp tag", e->name);
    } else if (strcmp(e->name, "ping-request.hex") == 0) {
        check(u->ping_req.sample_id == 7u, "ping sample_id", e->name);
    } else if (strcmp(e->name, "data-loss.hex") == 0) {
        check(u->data_loss.source == 1u, "data_loss source", e->name);
        check(u->data_loss.sequence_domain == 2u, "data_loss domain", e->name);
        check(u->data_loss.dropped_count == 3u, "data_loss dropped_count", e->name);
    } else if (strcmp(e->name, "can-rx-batch.hex") == 0) {
        check(u->can_rx_batch.record_count == 2u, "rx_batch record_count",
              e->name);
        check(u->can_rx_batch.config_generation == 3u, "rx_batch generation",
              e->name);
        check(u->can_rx_batch.records[0].channel_sequence == 1u,
              "rx_batch seq0", e->name);
        check(u->can_rx_batch.records[1].payload_len == 24u, "rx_batch payload1",
              e->name);
        check(u->can_rx_batch.records[1].dlc == 12u, "rx_batch dlc1", e->name);
    } else if (strcmp(e->name, "error-response.hex") == 0) {
        check(u->error_payload.detail_code == 1u, "error detail_code", e->name);
        check(u->error_payload.field_offset == 8u, "error field_offset", e->name);
    } else if (strcmp(e->name, "set-filters-request.hex") == 0) {
        check(u->set_filters.rule_count == 2u, "set_filters count", e->name);
        check(u->set_filters.rules[0].flags == 0x0004u, "set_filters rule0 flags",
              e->name);
    }
}

static void run_vector(const char *dir, const vector_entry_t *e) {
    char path[1024];
    snprintf(path, sizeof(path), "%s/%s", dir, e->name);
    uint8_t original[512];
    uint32_t original_len = 0;
    if (parse_hex_file(path, original, sizeof(original), &original_len) != 0) {
        check(0, "read vector", e->name);
        return;
    }

    ucan_frame_t frame;
    int rc = ucan_frame_decode(original, original_len, 65536u, &frame);
    check(rc == 0, "frame decode", e->name);
    if (rc != 0) {
        return;
    }
    check(frame.message_type == e->message_type, "message type", e->name);
    check(((frame.flags & UCAN_FLAG_ERROR) != 0) == (e->is_error != 0),
          "error flag", e->name);

    test_ctx_t ctx;
    memset(&ctx, 0, sizeof(ctx));
    rc = e->dec(frame.payload, frame.payload_len, &ctx);
    check(rc == 0, "payload decode", e->name);
    if (rc != 0) {
        return;
    }
    check_field_vectors(e, &ctx);

    /* Decode the exact same vector from an OS-enforced read-only mapping. */
    long page_size = sysconf(_SC_PAGESIZE);
    int zero = open("/dev/zero", O_RDWR);
    void *mapping = MAP_FAILED;
    if (page_size > 0 && zero >= 0) {
        mapping = mmap(NULL, (size_t)page_size, PROT_READ | PROT_WRITE,
                       MAP_PRIVATE, zero, 0);
    }
    if (zero >= 0) {
        close(zero);
    }
    check(mapping != MAP_FAILED && original_len <= (uint32_t)page_size,
          "immutable mapping setup", e->name);
    if (mapping != MAP_FAILED && original_len <= (uint32_t)page_size) {
        memcpy(mapping, original, original_len);
        check(mprotect(mapping, (size_t)page_size, PROT_READ) == 0,
              "immutable mapping protect", e->name);
        ucan_frame_t immutable_frame;
        test_ctx_t immutable_ctx;
        memset(&immutable_ctx, 0, sizeof(immutable_ctx));
        rc = ucan_frame_decode((const uint8_t *)mapping, original_len, 65536u,
                               &immutable_frame);
        check(rc == 0, "immutable frame decode", e->name);
        if (rc == 0) {
            rc = e->dec(immutable_frame.payload, immutable_frame.payload_len,
                        &immutable_ctx);
            check(rc == 0, "immutable payload decode", e->name);
        }
        munmap(mapping, (size_t)page_size);
    }

    uint8_t encoded[512];
    uint32_t payload_len = 0;
    rc = e->enc(&ctx.u, encoded, sizeof(encoded), &payload_len);
    check(rc == 0, "payload encode", e->name);
    if (rc != 0) {
        return;
    }
    check(payload_len == frame.payload_len &&
              memcmp(encoded, original + UCAN_HEADER_LEN, payload_len) == 0,
          "payload byte parity", e->name);

    ucan_frame_t rebuilt = frame;
    rebuilt.payload = encoded;
    rebuilt.payload_len = payload_len;
    uint8_t reframe[512];
    uint32_t reframe_len = 0;
    rc = ucan_frame_encode(&rebuilt, reframe, sizeof(reframe), &reframe_len);
    check(rc == 0, "frame re-encode", e->name);
    check(reframe_len == original_len &&
              memcmp(reframe, original, original_len) == 0,
          "frame byte parity", e->name);
}

static void run_stream_tests(const char *dir) {
    uint8_t wire[512];
    uint32_t wire_len = 0;
    char path[1024];
    snprintf(path, sizeof(path), "%s/%s", dir, "hello-request.hex");
    check(parse_hex_file(path, wire, sizeof(wire), &wire_len) == 0,
          "stream vector setup", NULL);
    if (wire_len == 0) {
        return;
    }

    uint8_t storage[128];
    ucan_stream_decoder_t decoder;
    ucan_frame_t frame;
    uint32_t consumed = 0;
    check(ucan_stream_decoder_init(&decoder, storage, sizeof(storage), 64) == 0,
          "stream init", NULL);
    check(ucan_stream_decoder_feed(&decoder, wire, 7, &consumed, &frame) ==
                  UCAN_STREAM_NEED_MORE &&
              consumed == 7,
          "stream fragmented prefix", NULL);
    check(ucan_stream_decoder_feed(&decoder, wire + 7, wire_len - 7, &consumed,
                                   &frame) == UCAN_STREAM_FRAME &&
              consumed == wire_len - 7 && frame.message_type == UCAN_MSG_HELLO,
          "stream fragmented completion", NULL);

    uint8_t coalesced[1024];
    memcpy(coalesced, wire, wire_len);
    memcpy(coalesced + wire_len, wire, wire_len);
    check(ucan_stream_decoder_init(&decoder, storage, sizeof(storage), 64) == 0,
          "stream coalesced init", NULL);
    check(ucan_stream_decoder_feed(&decoder, coalesced, wire_len * 2, &consumed,
                                   &frame) == UCAN_STREAM_FRAME &&
              consumed == wire_len,
          "stream coalesced first", NULL);
    uint32_t consumed2 = 0;
    check(ucan_stream_decoder_feed(&decoder, coalesced + consumed,
                                   wire_len * 2 - consumed, &consumed2,
                                   &frame) == UCAN_STREAM_FRAME &&
              consumed2 == wire_len,
          "stream coalesced second", NULL);

    uint8_t corrupt[1100];
    uint32_t offset = 0;
    const uint8_t noise[] = {0x55, 0x00, 0x55, 0x43, 0x41, 0x00};
    memcpy(corrupt + offset, noise, sizeof(noise));
    offset += sizeof(noise);
    memcpy(corrupt + offset, wire, wire_len);
    corrupt[offset + 20] ^= 1; /* CRC failure */
    offset += wire_len;
    memcpy(corrupt + offset, wire, wire_len);
    corrupt[offset + 16] = 0xff; /* impossible payload length */
    corrupt[offset + 17] = 0xff;
    corrupt[offset + 18] = 0xff;
    corrupt[offset + 19] = 0x7f;
    offset += wire_len;
    memcpy(corrupt + offset, wire, wire_len);
    offset += wire_len;
    check(ucan_stream_decoder_init(&decoder, storage, sizeof(storage), 64) == 0,
          "stream recovery init", NULL);
    check(ucan_stream_decoder_feed(&decoder, corrupt, offset, &consumed,
                                   &frame) == UCAN_STREAM_FRAME &&
              consumed == offset && frame.sequence == 1,
          "stream magic crc length recovery", NULL);

    check(ucan_stream_decoder_init(&decoder, storage, UCAN_HEADER_LEN + 63, 64) ==
              UCAN_ERR_CAPACITY,
          "stream bounded storage rejected", NULL);
}

static void run_negative_tests(void) {
    uint8_t bytes[512];
    uint32_t len = 0;
    const char *dir = "protocol/v1/0";
    char path[1024];
    snprintf(path, sizeof(path), "%s/%s", dir, "hello-request.hex");
    if (parse_hex_file(path, bytes, sizeof(bytes), &len) != 0) {
        check(0, "negative setup read", NULL);
        return;
    }

    ucan_frame_t frame;
    uint8_t buf[512];

    uint8_t bad_magic[512];
    memcpy(bad_magic, bytes, len);
    bad_magic[0] ^= 0xff;
    check(ucan_frame_decode(bad_magic, len, 65536u, &frame) == UCAN_ERR_BAD_MAGIC,
          "bad magic rejected", NULL);

    uint8_t bad_crc[512];
    memcpy(bad_crc, bytes, len);
    bad_crc[20] ^= 0xff;
    check(ucan_frame_decode(bad_crc, len, 65536u, &frame) == UCAN_ERR_CRC,
          "bad crc rejected", NULL);

    check(ucan_frame_decode(bytes, len - 25u, 65536u, &frame) ==
              UCAN_ERR_TOO_SHORT,
          "truncated rejected", NULL);
    check(ucan_frame_decode(bytes, len - 1u, 65536u, &frame) ==
              UCAN_ERR_LENGTH_MISMATCH,
          "declared length mismatch rejected", NULL);

    uint8_t bad_hdr[512];
    memcpy(bad_hdr, bytes, len);
    bad_hdr[6] = 25;
    check(ucan_frame_decode(bad_hdr, len, 65536u, &frame) ==
              UCAN_ERR_BAD_HEADER_LEN,
          "bad header len rejected", NULL);

    uint8_t extra[513];
    memcpy(extra, bytes, len);
    extra[len] = 0;
    check(ucan_frame_decode(extra, len + 1, 65536u, &frame) ==
              UCAN_ERR_LENGTH_MISMATCH,
          "length mismatch rejected", NULL);

    check(ucan_crc32c((const uint8_t *)"123456789", 9) == 0xe3069283u,
          "crc canonical check", NULL);
    check(ucan_can_dlc_to_payload_len(0) == 0 &&
              ucan_can_dlc_to_payload_len(8) == 8 &&
              ucan_can_dlc_to_payload_len(9) == 12 &&
              ucan_can_dlc_to_payload_len(12) == 24 &&
              ucan_can_dlc_to_payload_len(15) == 64 &&
              ucan_can_dlc_to_payload_len(16) == -1,
          "dlc mapping", NULL);

    ucan_hello_req_t bad_hello = {0, 1, 0, 0, 65536, 0};
    check(ucan_encode_hello_req(&bad_hello, buf, sizeof(buf), &len) ==
              UCAN_ERR_BAD_VALUE,
          "hello min_major 0 rejected", NULL);

    ucan_can_tx_req_t bad_tx = {0, 8, 0x0021, 0x1ff, 3, 42, 0, NULL, 8};
    check(ucan_encode_can_tx(&bad_tx, buf, sizeof(buf), &len) ==
              UCAN_ERR_BAD_VALUE,
          "can_tx ESI rejected", NULL);

    ucan_can_tx_req_t rtr_with_data = {0, 8, 0x0003, 0x1ff, 3, 42, 0, NULL, 8};
    check(ucan_encode_can_tx(&rtr_with_data, buf, sizeof(buf), &len) ==
              UCAN_ERR_BAD_VALUE,
          "can_tx RTR data rejected", NULL);

    ucan_can_rx_batch_t bad_batch = {0, 0, 0, 1, NULL, 0};
    check(ucan_encode_can_rx_batch(&bad_batch, buf, sizeof(buf), &len) == 0,
          "empty batch ok", NULL);

    ucan_mcan_diagnostics_t mcan = {
        .version = UCAN_MCAN_DIAGNOSTICS_VERSION,
        .length = UCAN_MCAN_DIAGNOSTICS_LEN,
        .generation = 7,
        .state_flags = UCAN_MCAN_DIAG_STATE_INITIALIZED |
                       UCAN_MCAN_DIAG_STATE_ONLINE |
                       UCAN_MCAN_DIAG_STATE_LISTEN_ONLY,
        .snapshot_tick = 0x1122334455667788ull,
        .interrupt_flags = 1,
        .error_interrupt_flags = 2,
        .last_interrupt_flags = 3,
        .protocol_status = 4,
        .error_count = 5,
        .transmit_error_count = 6,
        .receive_error_count = 7,
        .rxfifo0_fill_level = 8,
        .rxfifo0_high_watermark = 9,
        .queue_count = 10,
        .queue_high_watermark = 11,
        .ring_count = 12,
        .ring_high_watermark = 13,
        .queue_drops = 14,
        .ring_drops = 15,
        .invalid_frames = 16,
        .bus_off_count = 17,
        .warning_count = 18,
        .error_passive_count = 19,
        .automatic_recovery_attempts = 0,
    };
    ucan_mcan_diagnostics_t decoded_mcan;
    check(enc_mcan_diagnostics(&mcan, buf, sizeof(buf), &len) == 0 &&
              len == UCAN_MCAN_DIAGNOSTICS_LEN &&
              dec_mcan_diagnostics(buf, len, &decoded_mcan) == 0 &&
              memcmp(&mcan, &decoded_mcan, sizeof(mcan)) == 0,
          "mcan diagnostics round trip", NULL);
    buf[12] = 0x80;
    check(dec_mcan_diagnostics(buf, len, &decoded_mcan) ==
              UCAN_ERR_BAD_VALUE,
          "mcan diagnostics unknown state rejected", NULL);
}

int main(int argc, char **argv) {
    const char *dir = argc > 1 ? argv[1] : "protocol/v1/0";
    size_t count = sizeof(VECTORS) / sizeof(VECTORS[0]);
    for (size_t i = 0; i < count; ++i) {
        run_vector(dir, &VECTORS[i]);
    }
    run_negative_tests();
    run_stream_tests(dir);
    printf("%s: %zu vectors + negative suite, %d failures\n",
           failures == 0 ? "PASS" : "FAIL", count, failures);
    return failures == 0 ? 0 : 1;
}
