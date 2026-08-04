/*
 * Host scenario harness for the device-side session core.
 *
 * Drives ucan_session through the normative flows of
 * docs/approved-plan/usb-can-protocol-v1.md sections 5.2/7/8: version
 * negotiation, CAS generations, arm epoch, conservative TX admission,
 * exactly-once TX result ledger, replay cache, bounded-loss accounting and
 * the priority egress scheduler.
 */
#include "ucan_session.h"

#include <stdio.h>
#include <string.h>

static int failures = 0;

static void check(int ok, const char *what) {
    if (!ok) {
        ++failures;
        fprintf(stderr, "FAIL: %s\n", what);
    }
}

static const ucan_session_config_t cfg = {
    .fw_semver = "1.0.0",
    .build_id = "abc123",
    .board_id = "Gerber_PCB1_2026-07-23",
    .serial = "20260723",
    .tick_hz = 1000000,
    .tick_resolution_ns = 1000,
    .tx_depth = 32,
    .outstanding_limit = 8,
    .response_capacity = 8,
    .event_capacity = 16,
    .data_capacity = 32,
    .arm_timeout_min_ms = 100,
    .arm_timeout_max_ms = 60000,
    .usb_mode = 2,
    .global_features = 0x0017,
    .replay_cache_entries = 8,
    .tx_result_cache_entries = 16,
    .replay_retention_ms = 5000,
    .tag_reuse_guard_ms = 1000,
    .channel_count = 1,
    .channels = {{
        .channel = 0,
        .mode_mask = 0x07,
        .feature_bits = 0x0069,
        .nominal_min = 10000,
        .nominal_max = 1000000,
        .data_min = 0,
        .data_max = 0,
        .max_filters = 32,
    }},
};

typedef struct {
    uint16_t type;
    uint16_t status;
    int is_error;
    ucan_frame_t frame;
} resp_t;

static uint32_t seq_counter = 1;

static resp_t send(ucan_session_t *s, uint16_t type, const uint8_t *payload,
                   uint32_t payload_len);
static void drain_all(ucan_session_t *s, uint16_t *types, uint32_t *seqs,
                      uint32_t max, uint32_t *count);

/* Spec 2.2: the host must HELLO before any other request. Each scenario
 * negotiates first so the HELLO-first gate is exercised correctly. The HELLO
 * response is drained so it does not consume response-reserve capacity the
 * scenario relies on. */
static void hello_negotiate(ucan_session_t *s) {
    uint8_t hello[12] = {1, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0}; /* max 65536 */
    resp_t r = send(s, UCAN_MSG_HELLO, hello, 12);
    check(r.status == UCAN_STATUS_OK && !r.is_error, "hello negotiate");
    drain_all(s, NULL, NULL, 0, &(uint32_t){0});
}

static resp_t send(ucan_session_t *s, uint16_t type, const uint8_t *payload,
                   uint32_t payload_len) {
    uint8_t reqbuf[512];
    uint32_t reqlen = 0;
    ucan_frame_t req;
    memset(&req, 0, sizeof(req));
    req.major = UCAN_PROTOCOL_MAJOR;
    req.minor = UCAN_PROTOCOL_MINOR;
    req.flags = UCAN_FLAG_REQUEST;
    req.message_type = type;
    req.sequence = seq_counter++;
    req.payload = payload;
    req.payload_len = payload_len;
    ucan_frame_encode(&req, reqbuf, sizeof(reqbuf), &reqlen);

    ucan_frame_t decoded_req;
    ucan_frame_decode(reqbuf, reqlen, 65536, &decoded_req);
    static uint8_t respbuf[512];
    uint32_t resplen = 0;
    ucan_session_handle_frame(s, &decoded_req, respbuf, sizeof(respbuf), &resplen);
    resp_t out;
    memset(&out, 0, sizeof(out));
    ucan_frame_decode(respbuf, resplen, 65536, &out.frame);
    out.type = out.frame.message_type;
    out.status = out.frame.status;
    out.is_error = (out.frame.flags & UCAN_FLAG_ERROR) != 0;
    return out;
}

static void drain_all(ucan_session_t *s, uint16_t *types, uint32_t *seqs,
                      uint32_t max, uint32_t *count) {
    uint32_t n = 0;
    for (;;) {
        uint8_t buf[512];
        uint32_t len = 0;
        uint32_t evt = 0;
        if (ucan_session_dequeue(s, buf, sizeof(buf), &len, &evt) != 0) {
            break;
        }
        ucan_frame_t f;
        ucan_frame_decode(buf, len, 65536, &f);
        if (n < max) {
            types[n] = f.message_type;
            seqs[n] = evt;
            n++;
        }
    }
    *count = n;
}

static void test_version_and_identity(void) {
    ucan_session_t s;
    ucan_session_init(&s, &cfg);

    uint8_t hello[12] = {1, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0}; /* max 65536 */
    resp_t r = send(&s, UCAN_MSG_HELLO, hello, 12);
    check(r.status == UCAN_STATUS_OK && !r.is_error, "hello ok");
    ucan_hello_resp_t hr;
    check(ucan_decode_hello_resp(r.frame.payload, r.frame.payload_len, &hr) == 0,
          "hello resp decodes");
    check(hr.major == 1 && hr.minor == 0, "hello version");
    check(hr.session_id == 0x12345678u, "hello session id");
    check(hr.max_message == 65536u, "hello max message");
    check(hr.device_features == 0u, "hello feature intersection");

    uint8_t hello_f[12] = {1, 1, 0, 0, 0, 0, 1, 0, 0x11, 0, 0, 0};
    r = send(&s, UCAN_MSG_HELLO, hello_f, 12);
    check(ucan_decode_hello_resp(r.frame.payload, r.frame.payload_len, &hr) == 0,
          "hello features decode");
    check(hr.device_features == 0x11u, "hello feature intersection 0x11");

    uint8_t hello_bad[12] = {2, 2, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0};
    r = send(&s, UCAN_MSG_HELLO, hello_bad, 12);
    check(r.status == UCAN_STATUS_INCOMPATIBLE_VERSION && r.is_error,
          "hello incompatible version");

    r = send(&s, UCAN_MSG_GET_DEVICE_INFO, NULL, 0);
    ucan_device_info_t info;
    check(ucan_decode_device_info(r.frame.payload, r.frame.payload_len, &info) == 0,
          "device info decodes");
    check(info.firmware_semver.len == 5 && info.serial.len == 8, "device info lens");
    check(memcmp(info.build_id.str, "abc123", 6) == 0, "device info build id");

    r = send(&s, UCAN_MSG_GET_CAPABILITIES, NULL, 0);
    ucan_channel_cap_t caps[2];
    ucan_capabilities_t c;
    check(ucan_decode_capabilities(r.frame.payload, r.frame.payload_len, &c, caps, 2) ==
              0,
          "capabilities decode");
    check(c.tick_hz == 1000000u && c.usb_mode == 2, "capabilities tick/usb");
    check(c.channel_count == 1 && c.tx_depth == 32, "capabilities channels");
    check(c.arm_timeout_min_ms == 100 && c.arm_timeout_max_ms == 60000,
          "capabilities arm range");

    r = send(&s, UCAN_MSG_PING, (const uint8_t *)"", 0);
    check(r.status == UCAN_STATUS_INVALID_ARGUMENT,
          "ping without payload rejected");

    uint8_t ping[16];
    memset(ping, 0, sizeof(ping));
    ping[0] = 0x15;
    ping[1] = 0xcd;
    ping[2] = 0x5b;
    ping[3] = 0x07; /* host_send_ns = 123456789 */
    ping[8] = 7;    /* sample_id */
    r = send(&s, UCAN_MSG_PING, ping, 16);
    ucan_ping_resp_t pr;
    check(ucan_decode_ping_resp(r.frame.payload, r.frame.payload_len, &pr) == 0,
          "ping decode");
    check(pr.host_send_ns == 123456789ull && pr.sample_id == 7, "ping echo");
    check(pr.device_rx_tick == pr.device_tx_tick, "ping ticks");

    uint8_t unsupported[4] = {0, 0, 0, 0};
    r = send(&s, 0x0024, unsupported, 4);
    check(r.status == UCAN_STATUS_UNSUPPORTED && r.is_error,
          "v1.1 reserved message unsupported");
    drain_all(&s, NULL, NULL, 0, &(uint32_t){0});
}

static void test_cas_and_capture(void) {
    ucan_session_t s;
    ucan_session_init(&s, &cfg);
    hello_negotiate(&s);

    uint8_t cfg_buf[20];
    ucan_channel_config_t ch = {0, 2, 0, 500000, 0, 875, 5};
    ucan_encode_channel_config(&ch, cfg_buf, sizeof(cfg_buf), &(uint32_t){0});

    resp_t r = send(&s, UCAN_MSG_CONFIG_CHANNEL, cfg_buf, 20);
    check(r.status == UCAN_STATUS_BAD_STATE && r.is_error, "config CAS mismatch");
    ucan_error_payload_t err;
    check(ucan_decode_error_payload(r.frame.payload, r.frame.payload_len, &err) == 0 &&
              err.error_flags == 0x0002 && err.actual == 1,
          "config CAS error payload");

    ch.generation = 1;
    ucan_encode_channel_config(&ch, cfg_buf, sizeof(cfg_buf), &(uint32_t){0});
    r = send(&s, UCAN_MSG_CONFIG_CHANNEL, cfg_buf, 20);
    check(r.status == UCAN_STATUS_OK && !r.is_error, "config applied");
    ucan_channel_config_t applied;
    check(ucan_decode_channel_config(r.frame.payload, r.frame.payload_len, &applied) ==
              0 &&
              applied.generation == 2 && applied.mode == 2,
          "config applied generation 2");
    drain_all(&s, NULL, NULL, 0, &(uint32_t){0});

    uint8_t get[4] = {0, 0, 0, 0};
    r = send(&s, UCAN_MSG_GET_CHANNEL_CONFIG, get, 4);
    check(ucan_decode_channel_config(r.frame.payload, r.frame.payload_len, &applied) ==
              0 &&
              applied.nominal_bps == 500000 && applied.generation == 2,
          "get channel config");

    uint8_t start[8] = {2, 0, 0, 0, 1, 0, 0, 0};
    r = send(&s, UCAN_MSG_START_CAPTURE, start, 8);
    check(r.status == UCAN_STATUS_OK, "start capture");
    ucan_capture_resp_t cr;
    ucan_decode_capture_resp(r.frame.payload, r.frame.payload_len, &cr);
    check(cr.applied_generation == 3 && cr.state == 1, "capture generation 3");
    drain_all(&s, NULL, NULL, 0, &(uint32_t){0});

    uint8_t filters[32];
    ucan_filter_rule_t fr = {0x123, 0x7ff, 0};
    ucan_set_filters_req_t sf = {0, 3, &fr, 1};
    uint32_t flen = 0;
    ucan_encode_set_filters(&sf, filters, sizeof(filters), &flen);
    r = send(&s, UCAN_MSG_SET_FILTERS, filters, flen);
    check(r.status == UCAN_STATUS_OK, "set filters");
    ucan_set_filters_resp_t sfr;
    ucan_decode_set_filters_resp(r.frame.payload, r.frame.payload_len, &sfr);
    check(sfr.applied_generation == 4 && sfr.applied_count == 1,
          "set filters generation 4");
    drain_all(&s, NULL, NULL, 0, &(uint32_t){0});

    uint8_t canon[12] = {0x23, 0x01, 0x00, 0x00, 0xff, 0x07,
                         0x00, 0x00, 0x00, 0x00, 0x00, 0x00};
    uint32_t expected_crc = ucan_crc32c(canon, 12);

    r = send(&s, UCAN_MSG_GET_SESSION_STATE, NULL, 0);
    ucan_filter_state_t fs[2];
    ucan_session_state_t st;
    check(ucan_decode_session_state(r.frame.payload, r.frame.payload_len, &st, fs, 2) ==
              0,
          "session state decode");
    check(st.config_generation == 4 && st.capture_generation == 3 &&
              st.capture_state == 1,
          "session state generations");
    check(!st.tx_armed && st.arm_epoch == 1, "session state not armed");
    check(fs[0].filter_crc32c == expected_crc, "session state filter crc");
    drain_all(&s, NULL, NULL, 0, &(uint32_t){0});

    uint8_t clear[8] = {0, 0, 0, 0, 4, 0, 0, 0};
    r = send(&s, UCAN_MSG_CLEAR_FILTERS, clear, 8);
    check(r.status == UCAN_STATUS_OK, "clear filters");
    ucan_clear_filters_resp_t cfr;
    ucan_decode_clear_filters_resp(r.frame.payload, r.frame.payload_len, &cfr);
    check(cfr.applied_generation == 5, "clear filters generation 5");
    drain_all(&s, NULL, NULL, 0, &(uint32_t){0});

    uint8_t stop[8] = {5, 0, 0, 0, 1, 0, 0, 0};
    r = send(&s, UCAN_MSG_STOP_CAPTURE, stop, 8);
    check(r.status == UCAN_STATUS_OK, "stop capture");
    ucan_decode_capture_resp(r.frame.payload, r.frame.payload_len, &cr);
    check(cr.state == 0 && cr.applied_generation == 6, "stop capture state");
    drain_all(&s, NULL, NULL, 0, &(uint32_t){0});
}

static void test_tx_lifecycle(void) {
    ucan_session_t s;
    ucan_session_init(&s, &cfg);
    hello_negotiate(&s);

    ucan_channel_config_t ch = {0, 2, 0, 500000, 0, 875, 1};
    uint8_t cfg_buf[20];
    ucan_encode_channel_config(&ch, cfg_buf, sizeof(cfg_buf), &(uint32_t){0});
    send(&s, UCAN_MSG_CONFIG_CHANNEL, cfg_buf, 20);
    drain_all(&s, NULL, NULL, 0, &(uint32_t){0});

    uint8_t arm[32];
    ucan_tx_rule_t rule = {0, 0x0f, 0x123, 0x7ff, 500};
    ucan_tx_arm_req_t arm_req = {2, 5000, 1000, 900, &rule, 1};
    uint32_t alen = 0;
    ucan_encode_tx_arm(&arm_req, arm, sizeof(arm), &alen);
    resp_t r = send(&s, UCAN_MSG_TX_ARM, arm, alen);
    check(r.status == UCAN_STATUS_OK, "arm ok");
    ucan_tx_arm_resp_t ar;
    ucan_decode_tx_arm_resp(r.frame.payload, r.frame.payload_len, &ar);
    check(ar.applied_config_generation == 3 && ar.arm_epoch == 2,
          "arm generation 3 epoch 2");
    check(ar.expiry_tick == 5000000ull, "arm expiry 5e6 ticks");

    uint8_t tx[36];
    ucan_can_tx_req_t txr = {0, 8, 0, 0x123, 2, 42, 0, NULL, 8};
    uint8_t payload[8] = {1, 2, 3, 4, 5, 6, 7, 8};
    txr.payload = payload;
    uint32_t tlen = 0;
    ucan_encode_can_tx(&txr, tx, sizeof(tx), &tlen);

    /* Wrong epoch rejected. */
    ucan_can_tx_req_t bad_epoch = txr;
    bad_epoch.arm_epoch = 1;
    uint8_t tx_bad[36];
    ucan_encode_can_tx(&bad_epoch, tx_bad, sizeof(tx_bad), &tlen);
    r = send(&s, UCAN_MSG_CAN_TX, tx_bad, tlen);
    check(r.status == UCAN_STATUS_BAD_STATE, "can_tx wrong epoch");

    /* No matching rule rejected. */
    ucan_can_tx_req_t no_rule = txr;
    no_rule.id = 0x777;
    uint8_t tx_nr[36];
    ucan_encode_can_tx(&no_rule, tx_nr, sizeof(tx_nr), &tlen);
    r = send(&s, UCAN_MSG_CAN_TX, tx_nr, tlen);
    check(r.status == UCAN_STATUS_INVALID_ARGUMENT, "can_tx no rule");

    r = send(&s, UCAN_MSG_CAN_TX, tx, tlen);
    check(r.status == UCAN_STATUS_OK && !r.is_error, "can_tx accepted");
    ucan_can_tx_resp_t tr;
    ucan_decode_can_tx_resp(r.frame.payload, r.frame.payload_len, &tr);
    check(tr.tx_state == 1 && tr.client_tag == 42, "can_tx pending snapshot");
    check(tr.final_result == 0 && tr.final_tick == 0, "can_tx pending zeros");

    /* Byte-identical replay reads the ledger PENDING snapshot, no new TX. */
    r = send(&s, UCAN_MSG_CAN_TX, tx, tlen);
    ucan_decode_can_tx_resp(r.frame.payload, r.frame.payload_len, &tr);
    check(tr.tx_state == 1 && tr.client_tag == 42, "can_tx replay pending");

    /* Same tag, different bytes -> INVALID_ARGUMENT. */
    ucan_can_tx_req_t diff = txr;
    diff.payload = payload;
    uint8_t tx_d[36];
    payload[0] = 0xff;
    ucan_encode_can_tx(&diff, tx_d, sizeof(tx_d), &tlen);
    r = send(&s, UCAN_MSG_CAN_TX, tx_d, tlen);
    check(r.status == UCAN_STATUS_INVALID_ARGUMENT, "can_tx tag mismatch");
    payload[0] = 1;

    /* Completion -> FINAL SENT + CAN_TX_RESULT event. */
    ucan_session_can_tx_complete(&s, 42, 1 /* SENT */, 0);
    uint16_t types[16];
    uint32_t seqs[16];
    uint32_t n = 0;
    drain_all(&s, types, seqs, 16, &n);
    int saw_result = 0;
    for (uint32_t i = 0; i < n; ++i) {
        if (types[i] == UCAN_MSG_CAN_TX_RESULT) {
            saw_result = 1;
        }
    }
    check(saw_result, "tx result event");

    r = send(&s, UCAN_MSG_CAN_TX, tx, tlen);
    ucan_decode_can_tx_resp(r.frame.payload, r.frame.payload_len, &tr);
    check(tr.tx_state == 2 && tr.final_result == 1, "can_tx replay final sent");

    uint8_t cancel[8] = {2, 0, 0, 0, 42, 0, 0, 0};
    r = send(&s, UCAN_MSG_CAN_TX_CANCEL, cancel, 8);
    ucan_can_tx_cancel_resp_t cc;
    ucan_decode_can_tx_cancel_resp(r.frame.payload, r.frame.payload_len, &cc);
    check(cc.cancel_state == 2, "cancel already complete");

    uint8_t cancel_unknown[8] = {2, 0, 0, 0, 99, 0, 0, 0};
    r = send(&s, UCAN_MSG_CAN_TX_CANCEL, cancel_unknown, 8);
    ucan_decode_can_tx_cancel_resp(r.frame.payload, r.frame.payload_len, &cc);
    check(cc.cancel_state == 3, "cancel not found");
    drain_all(&s, NULL, NULL, 0, &(uint32_t){0});
}

static void test_disarm_and_expiry(void) {
    ucan_session_t s;
    ucan_session_init(&s, &cfg);
    hello_negotiate(&s);

    ucan_channel_config_t ch = {0, 2, 0, 500000, 0, 875, 1};
    uint8_t cfg_buf[20];
    ucan_encode_channel_config(&ch, cfg_buf, sizeof(cfg_buf), &(uint32_t){0});
    send(&s, UCAN_MSG_CONFIG_CHANNEL, cfg_buf, 20);
    drain_all(&s, NULL, NULL, 0, &(uint32_t){0});

    ucan_tx_rule_t rule = {0, 0x0f, 0x123, 0x7ff, 500};
    ucan_tx_arm_req_t arm_req = {2, 5000, 1000, 900, &rule, 1};
    uint8_t arm[32];
    uint32_t alen = 0;
    ucan_encode_tx_arm(&arm_req, arm, sizeof(arm), &alen);
    send(&s, UCAN_MSG_TX_ARM, arm, alen);
    drain_all(&s, NULL, NULL, 0, &(uint32_t){0});

    /* Two pending TX, then disarm cancels them. */
    uint8_t payload[8] = {1, 2, 3, 4, 5, 6, 7, 8};
    ucan_can_tx_req_t txr = {0, 8, 0, 0x123, 2, 100, 0, payload, 8};
    uint8_t tx[36];
    uint32_t tlen = 0;
    ucan_encode_can_tx(&txr, tx, sizeof(tx), &tlen);
    resp_t r = send(&s, UCAN_MSG_CAN_TX, tx, tlen);
    check(r.status == UCAN_STATUS_OK, "tx1 accepted");
    txr.client_tag = 101;
    ucan_encode_can_tx(&txr, tx, sizeof(tx), &tlen);
    r = send(&s, UCAN_MSG_CAN_TX, tx, tlen);
    check(r.status == UCAN_STATUS_OK, "tx2 accepted");

    uint8_t disarm[16] = {3, 0, 0, 0, 2, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0};
    r = send(&s, UCAN_MSG_TX_DISARM, disarm, 16);
    check(r.status == UCAN_STATUS_OK, "disarm ok");
    ucan_tx_disarm_resp_t dr;
    ucan_decode_tx_disarm_resp(r.frame.payload, r.frame.payload_len, &dr);
    check(dr.cancelled_count == 2 && dr.new_arm_epoch == 3,
          "disarm cancelled 2 epoch 3");

    /* TX after disarm -> BAD_STATE. */
    txr.client_tag = 102;
    ucan_encode_can_tx(&txr, tx, sizeof(tx), &tlen);
    r = send(&s, UCAN_MSG_CAN_TX, tx, tlen);
    check(r.status == UCAN_STATUS_BAD_STATE, "can_tx after disarm");

    /* Expiry auto-disarm with a pending frame. */
    ucan_tx_arm_req_t arm2 = {4, 100, 1000, 900, &rule, 1};
    ucan_encode_tx_arm(&arm2, arm, sizeof(arm), &alen);
    r = send(&s, UCAN_MSG_TX_ARM, arm, alen);
    check(r.status == UCAN_STATUS_OK, "re-arm ok");
    ucan_tx_arm_resp_t ar2;
    ucan_decode_tx_arm_resp(r.frame.payload, r.frame.payload_len, &ar2);
    check(ar2.arm_epoch == 4, "re-arm epoch 4");
    drain_all(&s, NULL, NULL, 0, &(uint32_t){0});

    txr.client_tag = 200;
    txr.arm_epoch = 4;
    ucan_encode_can_tx(&txr, tx, sizeof(tx), &tlen);
    r = send(&s, UCAN_MSG_CAN_TX, tx, tlen);
    check(r.status == UCAN_STATUS_OK, "tx before expiry");
    drain_all(&s, NULL, NULL, 0, &(uint32_t){0});

    ucan_session_tick(&s, 100001); /* past 100 ms expiry */
    check(s.tx_armed == 0, "expiry auto-disarm");
    check(s.arm_epoch == 5, "expiry advances epoch");
    uint16_t types[16];
    uint32_t seqs[16];
    uint32_t n = 0;
    drain_all(&s, types, seqs, 16, &n);
    int saw_timeout = 0;
    for (uint32_t i = 0; i < n; ++i) {
        if (types[i] == UCAN_MSG_CAN_TX_RESULT) {
            saw_timeout = 1;
        }
    }
    check(saw_timeout, "expiry emits tx result");
    /* A new TX with the stale epoch is rejected. */
    txr.client_tag = 201;
    txr.arm_epoch = 4;
    ucan_encode_can_tx(&txr, tx, sizeof(tx), &tlen);
    r = send(&s, UCAN_MSG_CAN_TX, tx, tlen);
    check(r.status == UCAN_STATUS_BAD_STATE, "stale epoch after disarm");
    drain_all(&s, NULL, NULL, 0, &(uint32_t){0});
}

static void test_admission_and_replay(void) {
    ucan_session_t s;
    ucan_session_init(&s, &cfg);
    hello_negotiate(&s);

    ucan_channel_config_t ch = {0, 2, 0, 500000, 0, 875, 1};
    uint8_t cfg_buf[20];
    ucan_encode_channel_config(&ch, cfg_buf, sizeof(cfg_buf), &(uint32_t){0});
    send(&s, UCAN_MSG_CONFIG_CHANNEL, cfg_buf, 20);
    drain_all(&s, NULL, NULL, 0, &(uint32_t){0});

    /* Low rule rate: capacity = max(1, ceil(2/10)) = 1 token. */
    ucan_tx_rule_t rule = {0, 0x0f, 0x123, 0x7ff, 2};
    ucan_tx_arm_req_t arm_req = {2, 5000, 1000, 900, &rule, 1};
    uint8_t arm[32];
    uint32_t alen = 0;
    ucan_encode_tx_arm(&arm_req, arm, sizeof(arm), &alen);
    send(&s, UCAN_MSG_TX_ARM, arm, alen);
    drain_all(&s, NULL, NULL, 0, &(uint32_t){0});

    uint8_t payload[8] = {1, 2, 3, 4, 5, 6, 7, 8};
    ucan_can_tx_req_t txr = {0, 8, 0, 0x123, 2, 1, 0, payload, 8};
    uint8_t tx[36];
    uint32_t tlen = 0;
    ucan_encode_can_tx(&txr, tx, sizeof(tx), &tlen);
    resp_t r = send(&s, UCAN_MSG_CAN_TX, tx, tlen);
    check(r.status == UCAN_STATUS_OK, "token admit");

    txr.client_tag = 2;
    ucan_encode_can_tx(&txr, tx, sizeof(tx), &tlen);
    r = send(&s, UCAN_MSG_CAN_TX, tx, tlen);
    check(r.status == UCAN_STATUS_BUSY && r.is_error, "token bucket busy");
    ucan_error_payload_t err;
    check(ucan_decode_error_payload(r.frame.payload, r.frame.payload_len, &err) == 0 &&
              (err.error_flags & 0x0001) != 0,
          "busy retryable");

    /* One tick second refills the bucket. */
    ucan_session_tick(&s, 1000000);
    txr.client_tag = 2;
    ucan_encode_can_tx(&txr, tx, sizeof(tx), &tlen);
    r = send(&s, UCAN_MSG_CAN_TX, tx, tlen);
    check(r.status == UCAN_STATUS_OK, "token refill after second");
    drain_all(&s, NULL, NULL, 0, &(uint32_t){0});

    /* Replay cache: identical config request returns cached response. */
    ucan_session_t s2;
    ucan_session_init(&s2, &cfg);
    hello_negotiate(&s2);
    uint8_t cfg2[20];
    ucan_channel_config_t ch2 = {0, 2, 0, 500000, 0, 875, 1};
    ucan_encode_channel_config(&ch2, cfg2, sizeof(cfg2), &(uint32_t){0});
    uint8_t reqbuf[512];
    uint32_t reqlen = 0;
    ucan_frame_t req;
    memset(&req, 0, sizeof(req));
    req.major = 1;
    req.minor = 0;
    req.flags = UCAN_FLAG_REQUEST;
    req.message_type = UCAN_MSG_CONFIG_CHANNEL;
    req.sequence = 7;
    req.payload = cfg2;
    req.payload_len = 20;
    ucan_frame_encode(&req, reqbuf, sizeof(reqbuf), &reqlen);
    ucan_frame_t dreq;
    ucan_frame_decode(reqbuf, reqlen, 65536, &dreq);
    uint8_t respbuf[512];
    uint32_t resplen = 0;
    ucan_session_handle_frame(&s2, &dreq, respbuf, sizeof(respbuf), &resplen);
    check(s2.config_generation == 2, "replay setup gen 2");
    drain_all(&s2, NULL, NULL, 0, &(uint32_t){0});

    /* Same sequence, same bytes -> cached response, generation unchanged. */
    ucan_frame_decode(reqbuf, reqlen, 65536, &dreq);
    ucan_session_handle_frame(&s2, &dreq, respbuf, sizeof(respbuf), &resplen);
    check(s2.config_generation == 2, "replay does not advance generation");
    drain_all(&s2, NULL, NULL, 0, &(uint32_t){0});

    /* Same sequence, different bytes -> BAD_STATE, no side effect. */
    uint8_t cfg3[20];
    ucan_channel_config_t ch3 = {0, 3, 0, 250000, 0, 875, 1};
    ucan_encode_channel_config(&ch3, cfg3, sizeof(cfg3), &(uint32_t){0});
    ucan_frame_t req3 = req;
    req3.payload = cfg3;
    req3.payload_len = 20;
    ucan_frame_encode(&req3, reqbuf, sizeof(reqbuf), &reqlen);
    ucan_frame_decode(reqbuf, reqlen, 65536, &dreq);
    ucan_session_handle_frame(&s2, &dreq, respbuf, sizeof(respbuf), &resplen);
    ucan_frame_t resp;
    ucan_frame_decode(respbuf, resplen, 65536, &resp);
    check(resp.status == UCAN_STATUS_BAD_STATE && (resp.flags & UCAN_FLAG_ERROR) != 0,
          "replay different bytes bad state");
    check(s2.config_generation == 2, "replay mismatch no side effect");
    drain_all(&s2, NULL, NULL, 0, &(uint32_t){0});
}

static void test_loss_and_queues(void) {
    ucan_session_t s;
    ucan_session_init(&s, &cfg);
    hello_negotiate(&s);

    ucan_channel_config_t ch = {0, 2, 0, 500000, 0, 875, 1};
    uint8_t cfg_buf[20];
    ucan_encode_channel_config(&ch, cfg_buf, sizeof(cfg_buf), &(uint32_t){0});
    send(&s, UCAN_MSG_CONFIG_CHANNEL, cfg_buf, 20);
    uint8_t start[8] = {2, 0, 0, 0, 1, 0, 0, 0};
    send(&s, UCAN_MSG_START_CAPTURE, start, 8);
    drain_all(&s, NULL, NULL, 0, &(uint32_t){0});

    /* Fill the ring (tx_depth=32). */
    ucan_can_rx_record_t rec;
    memset(&rec, 0, sizeof(rec));
    rec.channel = 0;
    rec.dlc = 8;
    rec.payload_len = 8;
    rec.flags = 0;
    rec.arbitration_id = 0x123;
    rec.channel_sequence = 1;
    rec.rx_status = 0;
    uint8_t data[8] = {1, 2, 3, 4, 5, 6, 7, 8};
    rec.payload = data;
    for (uint32_t i = 0; i < 32; ++i) {
        rec.channel_sequence = i + 1;
        check(ucan_session_on_rx(&s, 0, &rec) == 0, "ring admit");
    }
    /* seq 33 and 34 overflow contiguously. */
    rec.channel_sequence = 33;
    check(ucan_session_on_rx(&s, 0, &rec) == 1, "ring overflow 33");
    rec.channel_sequence = 34;
    check(ucan_session_on_rx(&s, 0, &rec) == 1, "ring overflow 34");
    /* Non-contiguous seq 36 flushes the 33..34 notice. */
    rec.channel_sequence = 36;
    check(ucan_session_on_rx(&s, 0, &rec) == 1, "ring overflow 36");

    uint16_t types[16];
    uint32_t seqs[16];
    uint32_t n = 0;
    drain_all(&s, types, seqs, 16, &n);
    int saw_loss = 0;
    for (uint32_t i = 0; i < n; ++i) {
        if (types[i] == UCAN_MSG_DATA_LOSS) {
            saw_loss = 1;
        }
    }
    check(saw_loss, "data loss event emitted");
    check(s.channels[0].dropped == 3, "dropped counter 3");

    /* Data queue batch path. */
    ucan_session_t s3;
    ucan_session_init(&s3, &cfg);
    hello_negotiate(&s3);
    ucan_channel_config_t ch3 = {0, 2, 0, 500000, 0, 875, 1};
    uint8_t c3[20];
    ucan_encode_channel_config(&ch3, c3, sizeof(c3), &(uint32_t){0});
    send(&s3, UCAN_MSG_CONFIG_CHANNEL, c3, 20);
    uint8_t start3[8] = {2, 0, 0, 0, 1, 0, 0, 0};
    send(&s3, UCAN_MSG_START_CAPTURE, start3, 8);
    drain_all(&s3, NULL, NULL, 0, &(uint32_t){0});
    rec.channel_sequence = 1;
    check(ucan_session_on_rx(&s3, 0, &rec) == 0, "s3 ring admit");
    check(ucan_session_emit_rx_batch(&s3, 0, &rec) == 0, "batch enqueue");
    uint8_t out[512];
    uint32_t olen = 0;
    uint32_t evt = 0;
    check(ucan_session_dequeue(&s3, out, sizeof(out), &olen, &evt) == 0, "dequeue batch");
    ucan_frame_t f;
    ucan_frame_decode(out, olen, 65536, &f);
    check(f.message_type == UCAN_MSG_CAN_RX_BATCH, "dequeued rx batch");
    check(evt != 0, "batch event sequence allocated");

    /* Fill the data queue, then overflow -> EVENT-domain DATA_LOSS. */
    for (uint32_t i = 0; i < 33; ++i) {
        rec.channel_sequence = i + 2;
        ucan_session_on_rx(&s3, 0, &rec);
        ucan_session_emit_rx_batch(&s3, 0, &rec);
    }
    uint16_t t3[64];
    uint32_t q3[64];
    uint32_t n3 = 0;
    drain_all(&s3, t3, q3, 64, &n3);
    int saw_usb_loss = 0;
    for (uint32_t i = 0; i < n3; ++i) {
        if (t3[i] == UCAN_MSG_DATA_LOSS) {
            saw_usb_loss = 1;
        }
    }
    check(saw_usb_loss, "usb data queue loss event");
    drain_all(&s3, NULL, NULL, 0, &(uint32_t){0});
}

static void test_scheduler_and_reserve(void) {
    ucan_session_t s;
    ucan_session_init(&s, &cfg);
    hello_negotiate(&s);

    /* 8 pings fill the response queue. */
    uint8_t ping[16];
    memset(ping, 0, sizeof(ping));
    for (int i = 0; i < 8; ++i) {
        resp_t r = send(&s, UCAN_MSG_PING, ping, 16);
        check(r.status == UCAN_STATUS_OK, "ping queued");
    }
    /* 9th ping: response reserve exhausted -> BUSY. */
    resp_t r = send(&s, UCAN_MSG_PING, ping, 16);
    check(r.status == UCAN_STATUS_BUSY && r.is_error, "response reserve busy");

    /* A critical event is queued behind the 8 responses. */
    uint8_t out[512];
    uint32_t olen = 0;
    uint32_t evt = 0;
    uint16_t types[16];
    for (int i = 0; i < 8; ++i) {
        check(ucan_session_dequeue(&s, out, sizeof(out), &olen, &evt) == 0,
              "drain response");
        ucan_frame_t f;
        ucan_frame_decode(out, olen, 65536, &f);
        types[i] = f.message_type;
    }
    check(types[7] == UCAN_MSG_PING, "8 responses drained");
    check(ucan_session_dequeue(&s, out, sizeof(out), &olen, &evt) == 1,
          "queue empty after drain");
    drain_all(&s, NULL, NULL, 0, &(uint32_t){0});

    /* Frame-time formula sanity (spec 7.1). */
    uint64_t t = ucan_frame_time_us(500000, 0, 8, 0, 8);
    check(t == 304, "classic 8-byte frame time 304us");
    uint64_t fd = ucan_frame_time_us(500000, 2000000, 12, 0x0005, 24);
    check(fd > 0, "fd frame time positive");
    check(ucan_session_reserved_permille(&s, 0) == 0, "reserved load zero");
}

int main(void) {
    test_version_and_identity();
    test_cas_and_capture();
    test_tx_lifecycle();
    test_disarm_and_expiry();
    test_admission_and_replay();
    test_loss_and_queues();
    test_scheduler_and_reserve();
    printf("%s: session scenarios complete, %d failures\n",
           failures == 0 ? "PASS" : "FAIL", failures);
    return failures == 0 ? 0 : 1;
}
