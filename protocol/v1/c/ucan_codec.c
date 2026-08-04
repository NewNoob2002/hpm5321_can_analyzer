/*
 * USB-CAN protocol v1.0 C codec implementation.
 * See ucan_codec.h for the contract; wire layout follows
 * docs/approved-plan/usb-can-protocol-v1.md.
 */
#include "ucan_codec.h"

#include <string.h>

/* ---------- little-endian helpers ---------- */

static uint16_t rd_u16(const uint8_t *p) {
    return (uint16_t)((uint16_t)p[0] | ((uint16_t)p[1] << 8));
}

static uint32_t rd_u32(const uint8_t *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) |
           ((uint32_t)p[3] << 24);
}

static uint64_t rd_u64(const uint8_t *p) {
    return (uint64_t)rd_u32(p) | ((uint64_t)rd_u32(p + 4) << 32);
}

static void wr_u16(uint8_t *p, uint16_t v) {
    p[0] = (uint8_t)v;
    p[1] = (uint8_t)(v >> 8);
}

static void wr_u32(uint8_t *p, uint32_t v) {
    p[0] = (uint8_t)v;
    p[1] = (uint8_t)(v >> 8);
    p[2] = (uint8_t)(v >> 16);
    p[3] = (uint8_t)(v >> 24);
}

static void wr_u64(uint8_t *p, uint64_t v) {
    wr_u32(p, (uint32_t)v);
    wr_u32(p + 4, (uint32_t)(v >> 32));
}

static int need(uint32_t cap, uint32_t n) {
    return cap < n ? UCAN_ERR_CAPACITY : 0;
}

static int reserved_ok(const uint8_t *p, uint32_t n) {
    for (uint32_t i = 0; i < n; ++i) {
        if (p[i] != 0) {
            return UCAN_ERR_RESERVED;
        }
    }
    return 0;
}

/* ---------- CRC-32C (Castagnoli), matches the Rust reference ---------- */

uint32_t ucan_crc32c(const uint8_t *data, uint32_t len) {
    uint32_t crc = 0xffffffffu;
    for (uint32_t i = 0; i < len; ++i) {
        crc ^= data[i];
        for (int j = 0; j < 8; ++j) {
            crc = (crc >> 1) ^ (0x82f63b78u & (0u - (crc & 1u)));
        }
    }
    return ~crc;
}

int ucan_can_dlc_to_payload_len(uint8_t dlc) {
    static const uint8_t table[16] = {0,  1,  2,  3,  4,  5,  6,  7,
                                      8,  12, 16, 20, 24, 32, 48, 64};
    if (dlc > 15) {
        return -1;
    }
    return table[dlc];
}

/* ---------- frame envelope ---------- */

static int validate_semantics(uint8_t flags, uint16_t status, uint32_t sequence) {
    if ((flags & ~(UCAN_FLAG_REQUEST | UCAN_FLAG_RESPONSE | UCAN_FLAG_EVENT |
                   UCAN_FLAG_ERROR)) != 0) {
        return UCAN_ERR_BAD_FLAGS;
    }
    uint8_t kind = flags & (UCAN_FLAG_REQUEST | UCAN_FLAG_RESPONSE | UCAN_FLAG_EVENT);
    if (!(kind == UCAN_FLAG_REQUEST || kind == UCAN_FLAG_RESPONSE ||
          kind == UCAN_FLAG_EVENT)) {
        return UCAN_ERR_BAD_FLAGS;
    }
    if ((flags & UCAN_FLAG_ERROR) != 0 && kind != UCAN_FLAG_RESPONSE) {
        return UCAN_ERR_BAD_FLAGS;
    }
    int is_error = (flags & UCAN_FLAG_ERROR) != 0;
    if (kind != UCAN_FLAG_RESPONSE) {
        if (status != 0) {
            return UCAN_ERR_BAD_STATUS;
        }
    } else if (is_error == (status == 0)) {
        /* error response must carry a non-zero status and vice versa */
        return UCAN_ERR_BAD_STATUS;
    }
    if (kind == UCAN_FLAG_REQUEST && sequence == 0) {
        return UCAN_ERR_BAD_SEQUENCE;
    }
    return 0;
}

int ucan_frame_encode(const ucan_frame_t *frame, uint8_t *out, uint32_t cap,
                      uint32_t *out_len) {
    int rc = validate_semantics(frame->flags, frame->status, frame->sequence);
    if (rc != 0) {
        return rc;
    }
    uint32_t total = UCAN_HEADER_LEN + frame->payload_len;
    if (total > cap) {
        return UCAN_ERR_CAPACITY;
    }
    out[0] = UCAN_MAGIC0;
    out[1] = UCAN_MAGIC1;
    out[2] = UCAN_MAGIC2;
    out[3] = UCAN_MAGIC3;
    out[4] = frame->major;
    out[5] = frame->minor;
    out[6] = UCAN_HEADER_LEN;
    out[7] = frame->flags;
    wr_u16(out + 8, frame->message_type);
    wr_u16(out + 10, frame->status);
    wr_u32(out + 12, frame->sequence);
    wr_u32(out + 16, frame->payload_len);
    out[20] = 0;
    out[21] = 0;
    out[22] = 0;
    out[23] = 0;
    if (frame->payload_len != 0 && frame->payload != NULL) {
        memcpy(out + UCAN_HEADER_LEN, frame->payload, frame->payload_len);
    }
    uint32_t crc = ucan_crc32c(out, total);
    wr_u32(out + 20, crc);
    if (out_len != NULL) {
        *out_len = total;
    }
    return 0;
}

int ucan_frame_decode(const uint8_t *bytes, uint32_t len, uint32_t max_message,
                      ucan_frame_t *frame) {
    if (len < UCAN_HEADER_LEN) {
        return UCAN_ERR_TOO_SHORT;
    }
    if (bytes[0] != UCAN_MAGIC0 || bytes[1] != UCAN_MAGIC1 ||
        bytes[2] != UCAN_MAGIC2 || bytes[3] != UCAN_MAGIC3) {
        return UCAN_ERR_BAD_MAGIC;
    }
    if (bytes[6] != UCAN_HEADER_LEN) {
        return UCAN_ERR_BAD_HEADER_LEN;
    }
    uint32_t payload_len = rd_u32(bytes + 16);
    if (payload_len > max_message) {
        return UCAN_ERR_LENGTH_MISMATCH;
    }
    uint32_t total = UCAN_HEADER_LEN + payload_len;
    if (len != total) {
        return UCAN_ERR_LENGTH_MISMATCH;
    }
    uint8_t flags = bytes[7];
    uint16_t status = rd_u16(bytes + 10);
    uint32_t sequence = rd_u32(bytes + 12);
    int rc = validate_semantics(flags, status, sequence);
    if (rc != 0) {
        return rc;
    }
    uint8_t canonical[UCAN_HEADER_LEN + 128u];
    /* CRC is computed over the frame with the CRC field zeroed. */
    uint32_t expected = rd_u32(bytes + 20);
    uint32_t actual;
    if (total <= sizeof(canonical)) {
        memcpy(canonical, bytes, total);
        memset(canonical + 20, 0, 4);
        actual = ucan_crc32c(canonical, total);
    } else {
        /* Stream CRC over header+payload, skipping the CRC field. */
        uint32_t crc = 0xffffffffu;
        for (uint32_t i = 0; i < total; ++i) {
            if (i >= 20 && i < 24) {
                continue;
            }
            crc ^= bytes[i];
            for (int j = 0; j < 8; ++j) {
                crc = (crc >> 1) ^ (0x82f63b78u & (0u - (crc & 1u)));
            }
        }
        actual = ~crc;
    }
    if (actual != expected) {
        return UCAN_ERR_CRC;
    }
    frame->major = bytes[4];
    frame->minor = bytes[5];
    frame->flags = flags;
    frame->message_type = rd_u16(bytes + 8);
    frame->status = status;
    frame->sequence = sequence;
    frame->payload = payload_len == 0 ? NULL : bytes + UCAN_HEADER_LEN;
    frame->payload_len = payload_len;
    return 0;
}

/* ---------- payload codecs ---------- */

#define V1_FEATURES 0x0017u

int ucan_decode_empty(const uint8_t *data, uint32_t len) {
    (void)data;
    return len == 0 ? 0 : UCAN_ERR_PAYLOAD;
}

/* HELLO */

static int hello_req_fields_valid(const ucan_hello_req_t *v);

int ucan_encode_hello_req(const ucan_hello_req_t *v, uint8_t *out, uint32_t cap,
                          uint32_t *len) {
    if (!hello_req_fields_valid(v)) {
        return UCAN_ERR_BAD_VALUE;
    }
    int rc = need(cap, 12);
    if (rc != 0) {
        return rc;
    }
    out[0] = v->min_major;
    out[1] = v->max_major;
    out[2] = v->min_minor;
    out[3] = v->max_minor;
    wr_u32(out + 4, v->host_max_message);
    wr_u32(out + 8, v->host_features);
    *len = 12;
    return 0;
}

static int hello_req_fields_valid(const ucan_hello_req_t *v) {
    return v->min_major != 0 && v->min_major <= v->max_major &&
           v->min_minor <= v->max_minor && v->host_max_message != 0 &&
           (v->host_features & ~V1_FEATURES) == 0;
}

int ucan_decode_hello_req(const uint8_t *data, uint32_t len, ucan_hello_req_t *v) {
    if (len != 12) {
        return UCAN_ERR_PAYLOAD;
    }
    v->min_major = data[0];
    v->max_major = data[1];
    v->min_minor = data[2];
    v->max_minor = data[3];
    v->host_max_message = rd_u32(data + 4);
    v->host_features = rd_u32(data + 8);
    /* Pure validation: never write back into the const input buffer. */
    return hello_req_fields_valid(v) ? 0 : UCAN_ERR_BAD_VALUE;
}

static int hello_resp_fields_valid(const ucan_hello_resp_t *v);

int ucan_encode_hello_resp(const ucan_hello_resp_t *v, uint8_t *out, uint32_t cap,
                           uint32_t *len) {
    if (!hello_resp_fields_valid(v)) {
        return UCAN_ERR_BAD_VALUE;
    }
    int rc = need(cap, 16);
    if (rc != 0) {
        return rc;
    }
    out[0] = v->major;
    out[1] = v->minor;
    out[2] = 0;
    out[3] = 0;
    wr_u32(out + 4, v->session_id);
    wr_u32(out + 8, v->max_message);
    wr_u32(out + 12, v->device_features);
    *len = 16;
    return 0;
}

static int hello_resp_fields_valid(const ucan_hello_resp_t *v) {
    return v->major != 0 && v->session_id != 0 && v->max_message != 0 &&
           (v->device_features & ~V1_FEATURES) == 0;
}

int ucan_decode_hello_resp(const uint8_t *data, uint32_t len, ucan_hello_resp_t *v) {
    if (len != 16) {
        return UCAN_ERR_PAYLOAD;
    }
    int rc = reserved_ok(data + 2, 2);
    if (rc != 0) {
        return rc;
    }
    v->major = data[0];
    v->minor = data[1];
    v->session_id = rd_u32(data + 4);
    v->max_message = rd_u32(data + 8);
    v->device_features = rd_u32(data + 12);
    /* Pure validation: never write back into the const input buffer. */
    return hello_resp_fields_valid(v) ? 0 : UCAN_ERR_BAD_VALUE;
}

/* GET_DEVICE_INFO */

int ucan_encode_device_info(const ucan_device_info_t *v, uint8_t *out, uint32_t cap,
                            uint32_t *len) {
    const ucan_str_t *fields[4] = {&v->firmware_semver, &v->build_id, &v->board_id,
                                   &v->serial};
    uint32_t total = 8;
    for (int i = 0; i < 4; ++i) {
        if (fields[i]->len > 64) {
            return UCAN_ERR_BAD_VALUE;
        }
        total += fields[i]->len;
    }
    int rc = need(cap, total);
    if (rc != 0) {
        return rc;
    }
    for (int i = 0; i < 4; ++i) {
        wr_u16(out + 2u * (uint32_t)i, fields[i]->len);
    }
    uint32_t offset = 8;
    for (int i = 0; i < 4; ++i) {
        if (fields[i]->len != 0) {
            memcpy(out + offset, fields[i]->str, fields[i]->len);
        }
        offset += fields[i]->len;
    }
    *len = total;
    return 0;
}

int ucan_decode_device_info(const uint8_t *data, uint32_t len, ucan_device_info_t *v) {
    if (len < 8) {
        return UCAN_ERR_PAYLOAD;
    }
    ucan_str_t *fields[4] = {&v->firmware_semver, &v->build_id, &v->board_id, &v->serial};
    uint32_t lengths[4];
    uint32_t total = 8;
    for (int i = 0; i < 4; ++i) {
        lengths[i] = rd_u16(data + 2u * (uint32_t)i);
        if (lengths[i] > 64) {
            return UCAN_ERR_BAD_VALUE;
        }
        total += lengths[i];
    }
    if (len != total) {
        return UCAN_ERR_PAYLOAD;
    }
    uint32_t offset = 8;
    for (int i = 0; i < 4; ++i) {
        fields[i]->len = (uint16_t)lengths[i];
        fields[i]->str = lengths[i] == 0 ? NULL : data + offset;
        offset += lengths[i];
    }
    return 0;
}

/* GET_CAPABILITIES */

int ucan_encode_capabilities(const ucan_capabilities_t *v, uint8_t *out, uint32_t cap,
                             uint32_t *len) {
    if (v->cap_generation == 0 || v->max_message == 0 || v->tick_hz == 0 ||
        v->tick_resolution_ns == 0 || v->boot_epoch == 0 ||
        !(v->usb_mode == 1 || v->usb_mode == 2) ||
        (v->global_features & ~0x0017u) != 0 ||
        v->arm_timeout_min_ms > v->arm_timeout_max_ms) {
        return UCAN_ERR_BAD_VALUE;
    }
    uint32_t total = 60 + (uint32_t)v->channel_count * 24;
    int rc = need(cap, total);
    if (rc != 0) {
        return rc;
    }
    uint8_t *p = out;
    wr_u32(p + 0, v->cap_generation);
    wr_u32(p + 4, v->max_message);
    wr_u32(p + 8, v->max_rx_batch);
    wr_u32(p + 12, v->tx_depth);
    wr_u32(p + 16, v->tick_hz);
    wr_u32(p + 20, v->tick_resolution_ns);
    wr_u64(p + 24, v->boot_epoch);
    wr_u16(p + 32, v->outstanding_limit);
    wr_u16(p + 34, v->response_capacity);
    wr_u16(p + 36, v->event_capacity);
    wr_u16(p + 38, v->data_capacity);
    wr_u16(p + 40, v->arm_timeout_min_ms);
    wr_u16(p + 42, v->arm_timeout_max_ms);
    p[44] = v->channel_count;
    p[45] = v->usb_mode;
    wr_u16(p + 46, v->global_features);
    wr_u16(p + 48, v->replay_cache_entries);
    wr_u16(p + 50, v->tx_result_cache_entries);
    wr_u32(p + 52, v->replay_retention_ms);
    wr_u32(p + 56, v->tag_reuse_guard_ms);
    for (uint8_t i = 0; i < v->channel_count; ++i) {
        const ucan_channel_cap_t *c = &v->channels[i];
        p = out + 60 + (uint32_t)i * 24;
        p[0] = c->channel;
        p[1] = c->mode_mask;
        wr_u16(p + 2, c->feature_bits);
        wr_u32(p + 4, c->nominal_min);
        wr_u32(p + 8, c->nominal_max);
        wr_u32(p + 12, c->data_min);
        wr_u32(p + 16, c->data_max);
        wr_u16(p + 20, c->max_filters);
        wr_u16(p + 22, 0);
    }
    *len = total;
    return 0;
}

static int has_duplicate_channel(const uint8_t *channels, uint8_t count) {
    uint8_t seen[256];
    memset(seen, 0, sizeof(seen));
    for (uint8_t i = 0; i < count; ++i) {
        uint8_t ch = channels[i];
        if (seen[ch] != 0) {
            return 1;
        }
        seen[ch] = 1;
    }
    return 0;
}

int ucan_decode_capabilities(const uint8_t *data, uint32_t len, ucan_capabilities_t *v,
                             ucan_channel_cap_t *channels, uint8_t max_channels) {
    if (len < 60) {
        return UCAN_ERR_PAYLOAD;
    }
    uint8_t channel_count = data[44];
    if (len != 60 + (uint32_t)channel_count * 24) {
        return UCAN_ERR_PAYLOAD;
    }
    if (channel_count > max_channels) {
        return UCAN_ERR_CAPACITY;
    }
    uint8_t ch_ids[256];
    for (uint8_t i = 0; i < channel_count; ++i) {
        const uint8_t *p = data + 60 + (uint32_t)i * 24;
        int rc = reserved_ok(p + 22, 2);
        if (rc != 0) {
            return rc;
        }
        ucan_channel_cap_t *c = &channels[i];
        c->channel = p[0];
        c->mode_mask = p[1];
        c->feature_bits = rd_u16(p + 2);
        c->nominal_min = rd_u32(p + 4);
        c->nominal_max = rd_u32(p + 8);
        c->data_min = rd_u32(p + 12);
        c->data_max = rd_u32(p + 16);
        c->max_filters = rd_u16(p + 20);
        if (c->mode_mask == 0 || (c->mode_mask & ~0x0fu) != 0 ||
            (c->feature_bits & ~0x007fu) != 0 ||
            c->nominal_min > c->nominal_max || c->data_min > c->data_max) {
            return UCAN_ERR_BAD_VALUE;
        }
        ch_ids[i] = c->channel;
    }
    if (has_duplicate_channel(ch_ids, channel_count)) {
        return UCAN_ERR_BAD_VALUE;
    }
    v->cap_generation = rd_u32(data + 0);
    v->max_message = rd_u32(data + 4);
    v->max_rx_batch = rd_u32(data + 8);
    v->tx_depth = rd_u32(data + 12);
    v->tick_hz = rd_u32(data + 16);
    v->tick_resolution_ns = rd_u32(data + 20);
    v->boot_epoch = rd_u64(data + 24);
    v->outstanding_limit = rd_u16(data + 32);
    v->response_capacity = rd_u16(data + 34);
    v->event_capacity = rd_u16(data + 36);
    v->data_capacity = rd_u16(data + 38);
    v->arm_timeout_min_ms = rd_u16(data + 40);
    v->arm_timeout_max_ms = rd_u16(data + 42);
    v->channel_count = channel_count;
    v->usb_mode = data[45];
    v->global_features = rd_u16(data + 46);
    v->replay_cache_entries = rd_u16(data + 48);
    v->tx_result_cache_entries = rd_u16(data + 50);
    v->replay_retention_ms = rd_u32(data + 52);
    v->tag_reuse_guard_ms = rd_u32(data + 56);
    v->channels = channels;
    if (v->cap_generation == 0 || v->max_message == 0 || v->tick_hz == 0 ||
        v->tick_resolution_ns == 0 || v->boot_epoch == 0 ||
        !(v->usb_mode == 1 || v->usb_mode == 2) ||
        (v->global_features & ~0x0017u) != 0 ||
        v->arm_timeout_min_ms > v->arm_timeout_max_ms) {
        return UCAN_ERR_BAD_VALUE;
    }
    return 0;
}

/* GET/RESET_DIAGNOSTICS */

int ucan_encode_diagnostics(const ucan_diagnostics_t *v, uint8_t *out, uint32_t cap,
                            uint32_t *len) {
    if (v->generation == 0 || v->session_id == 0) {
        return UCAN_ERR_BAD_VALUE;
    }
    uint32_t total = 40 + (uint32_t)v->channel_count * 52;
    int rc = need(cap, total);
    if (rc != 0) {
        return rc;
    }
    uint8_t *p = out;
    wr_u32(p + 0, v->generation);
    wr_u32(p + 4, v->session_id);
    wr_u32(p + 8, v->response_depth);
    wr_u32(p + 12, v->event_depth);
    wr_u32(p + 16, v->data_depth);
    wr_u32(p + 20, v->pool_high_water);
    wr_u64(p + 24, v->usb_rx_bytes);
    wr_u64(p + 32, v->usb_tx_bytes);
    for (uint8_t i = 0; i < v->channel_count; ++i) {
        const ucan_channel_diag_t *c = &v->channels[i];
        p = out + 40 + (uint32_t)i * 52;
        p[0] = c->channel;
        p[1] = c->state;
        p[2] = 0;
        p[3] = 0;
        wr_u32(p + 4, c->rx_depth);
        wr_u32(p + 8, c->tx_depth);
        wr_u64(p + 12, c->rx_frames);
        wr_u64(p + 20, c->tx_frames);
        wr_u64(p + 28, c->filtered);
        wr_u64(p + 36, c->dropped);
        wr_u32(p + 44, c->bus_off_count);
        wr_u32(p + 48, c->error_count);
    }
    *len = total;
    return 0;
}

int ucan_decode_diagnostics(const uint8_t *data, uint32_t len, ucan_diagnostics_t *v,
                            ucan_channel_diag_t *channels, uint8_t max_channels) {
    if (len < 40 || (len - 40) % 52 != 0) {
        return UCAN_ERR_PAYLOAD;
    }
    uint8_t channel_count = (uint8_t)((len - 40) / 52);
    if (channel_count > max_channels) {
        return UCAN_ERR_CAPACITY;
    }
    uint8_t ch_ids[256];
    for (uint8_t i = 0; i < channel_count; ++i) {
        const uint8_t *p = data + 40 + (uint32_t)i * 52;
        int rc = reserved_ok(p + 2, 2);
        if (rc != 0) {
            return rc;
        }
        ucan_channel_diag_t *c = &channels[i];
        c->channel = p[0];
        c->state = p[1];
        c->rx_depth = rd_u32(p + 4);
        c->tx_depth = rd_u32(p + 8);
        c->rx_frames = rd_u64(p + 12);
        c->tx_frames = rd_u64(p + 20);
        c->filtered = rd_u64(p + 28);
        c->dropped = rd_u64(p + 36);
        c->bus_off_count = rd_u32(p + 44);
        c->error_count = rd_u32(p + 48);
        if (c->state > 4) {
            return UCAN_ERR_BAD_VALUE;
        }
        ch_ids[i] = c->channel;
    }
    if (has_duplicate_channel(ch_ids, channel_count)) {
        return UCAN_ERR_BAD_VALUE;
    }
    v->generation = rd_u32(data + 0);
    v->session_id = rd_u32(data + 4);
    v->response_depth = rd_u32(data + 8);
    v->event_depth = rd_u32(data + 12);
    v->data_depth = rd_u32(data + 16);
    v->pool_high_water = rd_u32(data + 20);
    v->usb_rx_bytes = rd_u64(data + 24);
    v->usb_tx_bytes = rd_u64(data + 32);
    v->channel_count = channel_count;
    v->channels = channels;
    if (v->generation == 0 || v->session_id == 0) {
        return UCAN_ERR_BAD_VALUE;
    }
    return 0;
}

int ucan_encode_reset_diagnostics(uint32_t mask, uint8_t *out, uint32_t cap,
                                  uint32_t *len) {
    if ((mask & ~0x001fu) != 0) {
        return UCAN_ERR_BAD_VALUE;
    }
    int rc = need(cap, 4);
    if (rc != 0) {
        return rc;
    }
    wr_u32(out + 0, mask);
    *len = 4;
    return 0;
}

int ucan_decode_reset_diagnostics(const uint8_t *data, uint32_t len, uint32_t *mask) {
    if (len != 4) {
        return UCAN_ERR_PAYLOAD;
    }
    *mask = rd_u32(data + 0);
    return ucan_encode_reset_diagnostics(*mask, (uint8_t *)data, 4, &len) == 0
               ? 0
               : UCAN_ERR_BAD_VALUE;
}

/* GET_SESSION_STATE */

int ucan_encode_session_state(const ucan_session_state_t *v, uint8_t *out, uint32_t cap,
                              uint32_t *len) {
    if (v->config_generation == 0 || v->capture_state > 1 || v->arm_epoch == 0 ||
        (!v->tx_armed && v->arm_expiry_tick != 0)) {
        return UCAN_ERR_BAD_VALUE;
    }
    uint32_t total = 28 + (uint32_t)v->filter_count * 12;
    int rc = need(cap, total);
    if (rc != 0) {
        return rc;
    }
    uint8_t *p = out;
    wr_u32(p + 0, v->config_generation);
    wr_u32(p + 4, v->capture_generation);
    p[8] = v->capture_state;
    p[9] = v->tx_armed ? 1 : 0;
    p[10] = 0;
    p[11] = 0;
    wr_u32(p + 12, v->arm_epoch);
    wr_u64(p + 16, v->arm_expiry_tick);
    wr_u32(p + 24, v->aggregate_max_frames_per_s);
    for (uint8_t i = 0; i < v->filter_count; ++i) {
        const ucan_filter_state_t *f = &v->filters[i];
        p = out + 28 + (uint32_t)i * 12;
        p[0] = f->channel;
        p[1] = 0;
        p[2] = 0;
        p[3] = 0;
        wr_u32(p + 4, f->filter_generation);
        wr_u32(p + 8, f->filter_crc32c);
    }
    *len = total;
    return 0;
}

int ucan_decode_session_state(const uint8_t *data, uint32_t len,
                              ucan_session_state_t *v, ucan_filter_state_t *filters,
                              uint8_t max_filters) {
    if (len < 28 || (len - 28) % 12 != 0) {
        return UCAN_ERR_PAYLOAD;
    }
    int rc = reserved_ok(data + 10, 2);
    if (rc != 0) {
        return rc;
    }
    if (data[9] > 1 || data[8] > 1) {
        return UCAN_ERR_BAD_VALUE;
    }
    uint8_t filter_count = (uint8_t)((len - 28) / 12);
    if (filter_count > max_filters) {
        return UCAN_ERR_CAPACITY;
    }
    uint8_t ch_ids[256];
    for (uint8_t i = 0; i < filter_count; ++i) {
        const uint8_t *p = data + 28 + (uint32_t)i * 12;
        int rc = reserved_ok(p + 1, 3);
        if (rc != 0) {
            return rc;
        }
        ucan_filter_state_t *f = &filters[i];
        f->channel = p[0];
        f->filter_generation = rd_u32(p + 4);
        f->filter_crc32c = rd_u32(p + 8);
        ch_ids[i] = f->channel;
    }
    if (has_duplicate_channel(ch_ids, filter_count)) {
        return UCAN_ERR_BAD_VALUE;
    }
    v->config_generation = rd_u32(data + 0);
    v->capture_generation = rd_u32(data + 4);
    v->capture_state = data[8];
    v->tx_armed = data[9] != 0;
    v->arm_epoch = rd_u32(data + 12);
    v->arm_expiry_tick = rd_u64(data + 16);
    v->aggregate_max_frames_per_s = rd_u32(data + 24);
    v->filter_count = filter_count;
    v->filters = filters;
    if (v->config_generation == 0 || v->arm_epoch == 0 ||
        (!v->tx_armed && v->arm_expiry_tick != 0)) {
        return UCAN_ERR_BAD_VALUE;
    }
    return 0;
}

/* CONFIG_CHANNEL / GET_CHANNEL_CONFIG */

int ucan_encode_channel_config(const ucan_channel_config_t *v, uint8_t *out, uint32_t cap,
                               uint32_t *len) {
    if (v->mode > 3 || (v->flags & ~0x0003u) != 0 || v->sample_permille > 1000 ||
        v->generation == 0) {
        return UCAN_ERR_BAD_VALUE;
    }
    int rc = need(cap, 20);
    if (rc != 0) {
        return rc;
    }
    out[0] = v->channel;
    out[1] = v->mode;
    wr_u16(out + 2, v->flags);
    wr_u32(out + 4, v->nominal_bps);
    wr_u32(out + 8, v->data_bps);
    wr_u16(out + 12, v->sample_permille);
    wr_u16(out + 14, 0);
    wr_u32(out + 16, v->generation);
    *len = 20;
    return 0;
}

int ucan_decode_channel_config(const uint8_t *data, uint32_t len,
                               ucan_channel_config_t *v) {
    if (len != 20) {
        return UCAN_ERR_PAYLOAD;
    }
    int rc = reserved_ok(data + 14, 2);
    if (rc != 0) {
        return rc;
    }
    v->channel = data[0];
    v->mode = data[1];
    v->flags = rd_u16(data + 2);
    v->nominal_bps = rd_u32(data + 4);
    v->data_bps = rd_u32(data + 8);
    v->sample_permille = rd_u16(data + 12);
    v->generation = rd_u32(data + 16);
    return ucan_encode_channel_config(v, (uint8_t *)data, 20, &len) == 0 ? 0
                                                                         : UCAN_ERR_BAD_VALUE;
}

int ucan_encode_get_channel_config(const ucan_clear_filters_req_t *v, uint8_t *out,
                                   uint32_t cap, uint32_t *len) {
    int rc = need(cap, 4);
    if (rc != 0) {
        return rc;
    }
    out[0] = v->channel;
    out[1] = 0;
    out[2] = 0;
    out[3] = 0;
    *len = 4;
    return 0;
}

int ucan_decode_get_channel_config(const uint8_t *data, uint32_t len,
                                   ucan_clear_filters_req_t *v) {
    if (len != 4) {
        return UCAN_ERR_PAYLOAD;
    }
    int rc = reserved_ok(data + 1, 3);
    if (rc != 0) {
        return rc;
    }
    v->channel = data[0];
    return 0;
}

/* START/STOP_CAPTURE */

int ucan_encode_capture_req(const ucan_capture_req_t *v, uint8_t *out, uint32_t cap,
                            uint32_t *len) {
    if (v->expected_generation == 0 || (v->flags & ~0x0007u) != 0) {
        return UCAN_ERR_BAD_VALUE;
    }
    int rc = need(cap, 8);
    if (rc != 0) {
        return rc;
    }
    wr_u32(out + 0, v->expected_generation);
    wr_u32(out + 4, v->flags);
    *len = 8;
    return 0;
}

int ucan_decode_capture_req(const uint8_t *data, uint32_t len, ucan_capture_req_t *v) {
    if (len != 8) {
        return UCAN_ERR_PAYLOAD;
    }
    v->expected_generation = rd_u32(data + 0);
    v->flags = rd_u32(data + 4);
    /* Pure validation: never write back into the const input buffer. */
    if (v->expected_generation == 0 || (v->flags & ~0x0007u) != 0) {
        return UCAN_ERR_BAD_VALUE;
    }
    return 0;
}

int ucan_encode_capture_resp(const ucan_capture_resp_t *v, uint8_t *out, uint32_t cap,
                             uint32_t *len) {
    if (v->applied_generation == 0 || v->state > 1) {
        return UCAN_ERR_BAD_VALUE;
    }
    int rc = need(cap, 8);
    if (rc != 0) {
        return rc;
    }
    wr_u32(out + 0, v->applied_generation);
    wr_u32(out + 4, v->state);
    *len = 8;
    return 0;
}

int ucan_decode_capture_resp(const uint8_t *data, uint32_t len, ucan_capture_resp_t *v) {
    if (len != 8) {
        return UCAN_ERR_PAYLOAD;
    }
    v->applied_generation = rd_u32(data + 0);
    v->state = rd_u32(data + 4);
    /* Pure validation: never write back into the const input buffer. */
    if (v->applied_generation == 0 || v->state > 1) {
        return UCAN_ERR_BAD_VALUE;
    }
    return 0;
}

/* SET/CLEAR_FILTERS */

int ucan_encode_set_filters(const ucan_set_filters_req_t *v, uint8_t *out, uint32_t cap,
                            uint32_t *len) {
    if (v->expected_generation == 0) {
        return UCAN_ERR_BAD_VALUE;
    }
    uint32_t total = 8 + (uint32_t)v->rule_count * 12;
    int rc = need(cap, total);
    if (rc != 0) {
        return rc;
    }
    out[0] = v->channel;
    out[1] = v->rule_count;
    out[2] = 0;
    out[3] = 0;
    wr_u32(out + 4, v->expected_generation);
    for (uint8_t i = 0; i < v->rule_count; ++i) {
        const ucan_filter_rule_t *r = &v->rules[i];
        if ((r->flags & ~0x0007u) != 0 || r->id > UCAN_CAN_ID_EXT_MAX ||
            r->mask > UCAN_CAN_ID_EXT_MAX) {
            return UCAN_ERR_BAD_VALUE;
        }
        uint8_t *p = out + 8 + (uint32_t)i * 12;
        wr_u32(p + 0, r->id);
        wr_u32(p + 4, r->mask);
        wr_u16(p + 8, r->flags);
        wr_u16(p + 10, 0);
    }
    *len = total;
    return 0;
}

int ucan_decode_set_filters(const uint8_t *data, uint32_t len,
                            ucan_set_filters_req_t *v, ucan_filter_rule_t *rules,
                            uint8_t max_rules) {
    if (len < 8) {
        return UCAN_ERR_PAYLOAD;
    }
    int rc = reserved_ok(data + 2, 2);
    if (rc != 0) {
        return rc;
    }
    uint8_t count = data[1];
    if (count > max_rules) {
        return UCAN_ERR_CAPACITY;
    }
    if (len != 8 + (uint32_t)count * 12) {
        return UCAN_ERR_PAYLOAD;
    }
    for (uint8_t i = 0; i < count; ++i) {
        const uint8_t *p = data + 8 + (uint32_t)i * 12;
        int rc = reserved_ok(p + 10, 2);
        if (rc != 0) {
            return rc;
        }
        ucan_filter_rule_t *r = &rules[i];
        r->id = rd_u32(p + 0);
        r->mask = rd_u32(p + 4);
        r->flags = rd_u16(p + 8);
        if ((r->flags & ~0x0007u) != 0 || r->id > UCAN_CAN_ID_EXT_MAX ||
            r->mask > UCAN_CAN_ID_EXT_MAX) {
            return UCAN_ERR_BAD_VALUE;
        }
    }
    v->channel = data[0];
    v->expected_generation = rd_u32(data + 4);
    v->rule_count = count;
    v->rules = rules;
    return v->expected_generation == 0 ? UCAN_ERR_BAD_VALUE : 0;
}

int ucan_encode_set_filters_resp(const ucan_set_filters_resp_t *v, uint8_t *out,
                                 uint32_t cap, uint32_t *len) {
    if (v->applied_generation == 0) {
        return UCAN_ERR_BAD_VALUE;
    }
    int rc = need(cap, 8);
    if (rc != 0) {
        return rc;
    }
    wr_u32(out + 0, v->applied_generation);
    wr_u16(out + 4, v->applied_count);
    wr_u16(out + 6, 0);
    *len = 8;
    return 0;
}

int ucan_decode_set_filters_resp(const uint8_t *data, uint32_t len,
                                 ucan_set_filters_resp_t *v) {
    if (len != 8) {
        return UCAN_ERR_PAYLOAD;
    }
    int rc = reserved_ok(data + 6, 2);
    if (rc != 0) {
        return rc;
    }
    v->applied_generation = rd_u32(data + 0);
    v->applied_count = rd_u16(data + 4);
    return ucan_encode_set_filters_resp(v, (uint8_t *)data, 8, &len) == 0 ? 0
                                                                          : UCAN_ERR_BAD_VALUE;
}

int ucan_encode_clear_filters(const ucan_clear_filters_req_t *v, uint8_t *out,
                              uint32_t cap, uint32_t *len) {
    if (v->expected_generation == 0) {
        return UCAN_ERR_BAD_VALUE;
    }
    int rc = need(cap, 8);
    if (rc != 0) {
        return rc;
    }
    out[0] = v->channel;
    out[1] = 0;
    out[2] = 0;
    out[3] = 0;
    wr_u32(out + 4, v->expected_generation);
    *len = 8;
    return 0;
}

int ucan_decode_clear_filters(const uint8_t *data, uint32_t len,
                              ucan_clear_filters_req_t *v) {
    if (len != 8) {
        return UCAN_ERR_PAYLOAD;
    }
    int rc = reserved_ok(data + 1, 3);
    if (rc != 0) {
        return rc;
    }
    v->channel = data[0];
    v->expected_generation = rd_u32(data + 4);
    return ucan_encode_clear_filters(v, (uint8_t *)data, 8, &len) == 0 ? 0
                                                                       : UCAN_ERR_BAD_VALUE;
}

int ucan_encode_clear_filters_resp(const ucan_clear_filters_resp_t *v, uint8_t *out,
                                   uint32_t cap, uint32_t *len) {
    if (v->applied_generation == 0) {
        return UCAN_ERR_BAD_VALUE;
    }
    int rc = need(cap, 4);
    if (rc != 0) {
        return rc;
    }
    wr_u32(out + 0, v->applied_generation);
    *len = 4;
    return 0;
}

int ucan_decode_clear_filters_resp(const uint8_t *data, uint32_t len,
                                   ucan_clear_filters_resp_t *v) {
    if (len != 4) {
        return UCAN_ERR_PAYLOAD;
    }
    v->applied_generation = rd_u32(data + 0);
    return ucan_encode_clear_filters_resp(v, (uint8_t *)data, 4, &len) == 0 ? 0
                                                                            : UCAN_ERR_BAD_VALUE;
}

/* TX_ARM / TX_DISARM */

int ucan_encode_tx_arm(const ucan_tx_arm_req_t *v, uint8_t *out, uint32_t cap,
                       uint32_t *len) {
    if (v->expected_config_generation == 0 || v->timeout_ms < 100 ||
        v->timeout_ms > 60000 || v->max_bus_load_permille > 1000 ||
        v->rule_count > 16) {
        return UCAN_ERR_BAD_VALUE;
    }
    uint32_t total = 16 + (uint32_t)v->rule_count * 16;
    int rc = need(cap, total);
    if (rc != 0) {
        return rc;
    }
    wr_u32(out + 0, v->expected_config_generation);
    wr_u32(out + 4, v->timeout_ms);
    wr_u32(out + 8, v->max_frames_per_s);
    wr_u16(out + 12, v->max_bus_load_permille);
    wr_u16(out + 14, v->rule_count);
    for (uint8_t i = 0; i < v->rule_count; ++i) {
        const ucan_tx_rule_t *r = &v->rules[i];
        if ((r->allowed_flag_mask & ~0x0fu) != 0 || r->id > UCAN_CAN_ID_EXT_MAX ||
            r->id_mask > UCAN_CAN_ID_EXT_MAX) {
            return UCAN_ERR_BAD_VALUE;
        }
        uint8_t *p = out + 16 + (uint32_t)i * 16;
        p[0] = r->channel;
        p[1] = r->allowed_flag_mask;
        p[2] = 0;
        p[3] = 0;
        wr_u32(p + 4, r->id);
        wr_u32(p + 8, r->id_mask);
        wr_u32(p + 12, r->max_frames_per_s);
    }
    *len = total;
    return 0;
}

int ucan_decode_tx_arm(const uint8_t *data, uint32_t len, ucan_tx_arm_req_t *v,
                       ucan_tx_rule_t *rules, uint8_t max_rules) {
    if (len < 16) {
        return UCAN_ERR_PAYLOAD;
    }
    /* Read the wire u16 in full before narrowing: (uint8_t)0x0100 == 0 would
     * otherwise slip past the upper-bound check and decode as "no rules". */
    uint16_t wire_rule_count = rd_u16(data + 14);
    if (wire_rule_count > 16 || wire_rule_count > max_rules) {
        return UCAN_ERR_BAD_VALUE;
    }
    uint8_t rule_count = (uint8_t)wire_rule_count;
    if (len != 16 + (uint32_t)rule_count * 16) {
        return UCAN_ERR_PAYLOAD;
    }
    for (uint8_t i = 0; i < rule_count; ++i) {
        const uint8_t *p = data + 16 + (uint32_t)i * 16;
        int rc = reserved_ok(p + 2, 2);
        if (rc != 0) {
            return rc;
        }
        ucan_tx_rule_t *r = &rules[i];
        r->channel = p[0];
        r->allowed_flag_mask = p[1];
        r->id = rd_u32(p + 4);
        r->id_mask = rd_u32(p + 8);
        r->max_frames_per_s = rd_u32(p + 12);
        if ((r->allowed_flag_mask & ~0x0fu) != 0 ||
            r->id > UCAN_CAN_ID_EXT_MAX || r->id_mask > UCAN_CAN_ID_EXT_MAX) {
            return UCAN_ERR_BAD_VALUE;
        }
    }
    v->expected_config_generation = rd_u32(data + 0);
    v->timeout_ms = rd_u32(data + 4);
    v->max_frames_per_s = rd_u32(data + 8);
    v->max_bus_load_permille = rd_u16(data + 12);
    v->rule_count = rule_count;
    v->rules = rules;
    if (v->expected_config_generation == 0 || v->timeout_ms < 100 ||
        v->timeout_ms > 60000 || v->max_bus_load_permille > 1000) {
        return UCAN_ERR_BAD_VALUE;
    }
    return 0;
}

int ucan_encode_tx_arm_resp(const ucan_tx_arm_resp_t *v, uint8_t *out, uint32_t cap,
                            uint32_t *len) {
    if (v->applied_config_generation == 0 || v->arm_epoch == 0) {
        return UCAN_ERR_BAD_VALUE;
    }
    int rc = need(cap, 16);
    if (rc != 0) {
        return rc;
    }
    wr_u32(out + 0, v->applied_config_generation);
    wr_u32(out + 4, v->arm_epoch);
    wr_u64(out + 8, v->expiry_tick);
    *len = 16;
    return 0;
}

int ucan_decode_tx_arm_resp(const uint8_t *data, uint32_t len, ucan_tx_arm_resp_t *v) {
    if (len != 16) {
        return UCAN_ERR_PAYLOAD;
    }
    v->applied_config_generation = rd_u32(data + 0);
    v->arm_epoch = rd_u32(data + 4);
    v->expiry_tick = rd_u64(data + 8);
    return ucan_encode_tx_arm_resp(v, (uint8_t *)data, 16, &len) == 0 ? 0
                                                                      : UCAN_ERR_BAD_VALUE;
}

int ucan_encode_tx_disarm(const ucan_tx_disarm_req_t *v, uint8_t *out, uint32_t cap,
                          uint32_t *len) {
    if (v->expected_config_generation == 0 || v->arm_epoch == 0 ||
        v->reason < 1 || v->reason > 6) {
        return UCAN_ERR_BAD_VALUE;
    }
    int rc = need(cap, 16);
    if (rc != 0) {
        return rc;
    }
    wr_u32(out + 0, v->expected_config_generation);
    wr_u32(out + 4, v->arm_epoch);
    wr_u32(out + 8, v->reason);
    wr_u32(out + 12, 0);
    *len = 16;
    return 0;
}

int ucan_decode_tx_disarm(const uint8_t *data, uint32_t len, ucan_tx_disarm_req_t *v) {
    if (len != 16) {
        return UCAN_ERR_PAYLOAD;
    }
    int rc = reserved_ok(data + 12, 4);
    if (rc != 0) {
        return rc;
    }
    v->expected_config_generation = rd_u32(data + 0);
    v->arm_epoch = rd_u32(data + 4);
    v->reason = rd_u32(data + 8);
    return ucan_encode_tx_disarm(v, (uint8_t *)data, 16, &len) == 0 ? 0
                                                                    : UCAN_ERR_BAD_VALUE;
}

int ucan_encode_tx_disarm_resp(const ucan_tx_disarm_resp_t *v, uint8_t *out,
                               uint32_t cap, uint32_t *len) {
    if (v->applied_config_generation == 0 || v->new_arm_epoch == 0) {
        return UCAN_ERR_BAD_VALUE;
    }
    int rc = need(cap, 16);
    if (rc != 0) {
        return rc;
    }
    wr_u32(out + 0, v->applied_config_generation);
    wr_u32(out + 4, v->new_arm_epoch);
    wr_u32(out + 8, v->cancelled_count);
    wr_u32(out + 12, 0);
    *len = 16;
    return 0;
}

int ucan_decode_tx_disarm_resp(const uint8_t *data, uint32_t len,
                               ucan_tx_disarm_resp_t *v) {
    if (len != 16) {
        return UCAN_ERR_PAYLOAD;
    }
    int rc = reserved_ok(data + 12, 4);
    if (rc != 0) {
        return rc;
    }
    v->applied_config_generation = rd_u32(data + 0);
    v->new_arm_epoch = rd_u32(data + 4);
    v->cancelled_count = rd_u32(data + 8);
    return ucan_encode_tx_disarm_resp(v, (uint8_t *)data, 16, &len) == 0 ? 0
                                                                         : UCAN_ERR_BAD_VALUE;
}

/* CAN_TX / CAN_TX_CANCEL */

static int can_tx_fields_valid(const ucan_can_tx_req_t *v);

static int can_payload_ok(uint8_t dlc, uint16_t flags, uint32_t payload_len) {
    if ((flags & 0x0008u) != 0 && (flags & 0x0004u) == 0) {
        return 0; /* BRS requires FD */
    }
    if ((flags & 0x0002u) != 0) { /* RTR */
        return (flags & 0x0004u) == 0 && dlc <= 8 && payload_len == 0;
    }
    if ((flags & 0x0004u) != 0) { /* FD */
        int expected = ucan_can_dlc_to_payload_len(dlc);
        return expected >= 0 && payload_len == (uint32_t)expected;
    }
    return dlc <= 8 && payload_len == (uint32_t)dlc;
}

int ucan_encode_can_tx(const ucan_can_tx_req_t *v, uint8_t *out, uint32_t cap,
                       uint32_t *len) {
    if (!can_tx_fields_valid(v)) {
        return UCAN_ERR_BAD_VALUE;
    }
    int rc = need(cap, 28 + v->payload_len);
    if (rc != 0) {
        return rc;
    }
    out[0] = v->channel;
    out[1] = v->dlc;
    wr_u16(out + 2, v->can_flags);
    wr_u32(out + 4, v->id);
    wr_u32(out + 8, v->arm_epoch);
    wr_u32(out + 12, v->client_tag);
    wr_u64(out + 16, v->deadline_tick);
    out[24] = v->payload_len;
    out[25] = 0;
    out[26] = 0;
    out[27] = 0;
    if (v->payload_len != 0) {
        memcpy(out + 28, v->payload, v->payload_len);
    }
    *len = 28 + v->payload_len;
    return 0;
}

static int can_tx_fields_valid(const ucan_can_tx_req_t *v) {
    if ((v->can_flags & ~UCAN_CAN_TX_FLAGS_MASK) != 0 || v->arm_epoch == 0 ||
        v->payload_len > 64) {
        return 0;
    }
    int ext = (v->can_flags & 0x0001u) != 0;
    uint32_t id_max = ext ? UCAN_CAN_ID_EXT_MAX : UCAN_CAN_ID_STD_MAX;
    if (v->id > id_max) {
        return 0;
    }
    return can_payload_ok(v->dlc, v->can_flags, v->payload_len);
}

int ucan_decode_can_tx(const uint8_t *data, uint32_t len, ucan_can_tx_req_t *v) {
    if (len < 28) {
        return UCAN_ERR_PAYLOAD;
    }
    int rc = reserved_ok(data + 25, 3);
    if (rc != 0) {
        return rc;
    }
    uint8_t payload_len = data[24];
    if (len != 28 + (uint32_t)payload_len) {
        return UCAN_ERR_PAYLOAD;
    }
    v->channel = data[0];
    v->dlc = data[1];
    v->can_flags = rd_u16(data + 2);
    v->id = rd_u32(data + 4);
    v->arm_epoch = rd_u32(data + 8);
    v->client_tag = rd_u32(data + 12);
    v->deadline_tick = rd_u64(data + 16);
    v->payload_len = payload_len;
    v->payload = payload_len == 0 ? NULL : data + 28;
    /* Pure validation: never write back into the const input buffer. */
    return can_tx_fields_valid(v) ? 0 : UCAN_ERR_BAD_VALUE;
}

int ucan_encode_can_tx_resp(const ucan_can_tx_resp_t *v, uint8_t *out, uint32_t cap,
                            uint32_t *len) {
    if (v->queue_generation == 0 ||
        !(v->tx_state == 1 || v->tx_state == 2)) {
        return UCAN_ERR_BAD_VALUE;
    }
    if (v->tx_state == 1) { /* PENDING: final fields must be zero */
        if (v->final_result != 0 || v->final_tick != 0 || v->can_error != 0) {
            return UCAN_ERR_BAD_VALUE;
        }
    } else { /* FINAL */
        if (v->final_result < 1 || v->final_result > 5 ||
            (v->can_error & 0xfff80000u) != 0) {
            return UCAN_ERR_BAD_VALUE;
        }
    }
    int rc = need(cap, 24);
    if (rc != 0) {
        return rc;
    }
    wr_u32(out + 0, v->client_tag);
    wr_u32(out + 4, v->queue_generation);
    wr_u16(out + 8, v->tx_state);
    wr_u16(out + 10, v->final_result);
    wr_u64(out + 12, v->final_tick);
    wr_u32(out + 20, v->can_error);
    *len = 24;
    return 0;
}

int ucan_decode_can_tx_resp(const uint8_t *data, uint32_t len, ucan_can_tx_resp_t *v) {
    if (len != 24) {
        return UCAN_ERR_PAYLOAD;
    }
    v->client_tag = rd_u32(data + 0);
    v->queue_generation = rd_u32(data + 4);
    v->tx_state = rd_u16(data + 8);
    v->final_result = rd_u16(data + 10);
    v->final_tick = rd_u64(data + 12);
    v->can_error = rd_u32(data + 20);
    return ucan_encode_can_tx_resp(v, (uint8_t *)data, 24, &len) == 0 ? 0
                                                                      : UCAN_ERR_BAD_VALUE;
}

int ucan_encode_can_tx_cancel(const ucan_can_tx_cancel_req_t *v, uint8_t *out,
                              uint32_t cap, uint32_t *len) {
    if (v->arm_epoch == 0) {
        return UCAN_ERR_BAD_VALUE;
    }
    int rc = need(cap, 8);
    if (rc != 0) {
        return rc;
    }
    wr_u32(out + 0, v->arm_epoch);
    wr_u32(out + 4, v->client_tag);
    *len = 8;
    return 0;
}

int ucan_decode_can_tx_cancel(const uint8_t *data, uint32_t len,
                              ucan_can_tx_cancel_req_t *v) {
    if (len != 8) {
        return UCAN_ERR_PAYLOAD;
    }
    v->arm_epoch = rd_u32(data + 0);
    v->client_tag = rd_u32(data + 4);
    return ucan_encode_can_tx_cancel(v, (uint8_t *)data, 8, &len) == 0 ? 0
                                                                       : UCAN_ERR_BAD_VALUE;
}

int ucan_encode_can_tx_cancel_resp(const ucan_can_tx_cancel_resp_t *v, uint8_t *out,
                                   uint32_t cap, uint32_t *len) {
    if (v->cancel_state < 1 || v->cancel_state > 3) {
        return UCAN_ERR_BAD_VALUE;
    }
    int rc = need(cap, 8);
    if (rc != 0) {
        return rc;
    }
    wr_u32(out + 0, v->client_tag);
    wr_u32(out + 4, v->cancel_state);
    *len = 8;
    return 0;
}

int ucan_decode_can_tx_cancel_resp(const uint8_t *data, uint32_t len,
                                   ucan_can_tx_cancel_resp_t *v) {
    if (len != 8) {
        return UCAN_ERR_PAYLOAD;
    }
    v->client_tag = rd_u32(data + 0);
    v->cancel_state = rd_u32(data + 4);
    return ucan_encode_can_tx_cancel_resp(v, (uint8_t *)data, 8, &len) == 0 ? 0
                                                                            : UCAN_ERR_BAD_VALUE;
}

/* PING */

int ucan_encode_ping_req(const ucan_ping_req_t *v, uint8_t *out, uint32_t cap,
                         uint32_t *len) {
    int rc = need(cap, 16);
    if (rc != 0) {
        return rc;
    }
    wr_u64(out + 0, v->host_send_ns);
    wr_u32(out + 8, v->sample_id);
    wr_u32(out + 12, 0);
    *len = 16;
    return 0;
}

int ucan_decode_ping_req(const uint8_t *data, uint32_t len, ucan_ping_req_t *v) {
    if (len != 16) {
        return UCAN_ERR_PAYLOAD;
    }
    int rc = reserved_ok(data + 12, 4);
    if (rc != 0) {
        return rc;
    }
    v->host_send_ns = rd_u64(data + 0);
    v->sample_id = rd_u32(data + 8);
    return 0;
}

int ucan_encode_ping_resp(const ucan_ping_resp_t *v, uint8_t *out, uint32_t cap,
                          uint32_t *len) {
    int rc = need(cap, 32);
    if (rc != 0) {
        return rc;
    }
    wr_u64(out + 0, v->host_send_ns);
    wr_u64(out + 8, v->device_rx_tick);
    wr_u64(out + 16, v->device_tx_tick);
    wr_u32(out + 24, v->sample_id);
    wr_u32(out + 28, 0);
    *len = 32;
    return 0;
}

int ucan_decode_ping_resp(const uint8_t *data, uint32_t len, ucan_ping_resp_t *v) {
    if (len != 32) {
        return UCAN_ERR_PAYLOAD;
    }
    int rc = reserved_ok(data + 28, 4);
    if (rc != 0) {
        return rc;
    }
    v->host_send_ns = rd_u64(data + 0);
    v->device_rx_tick = rd_u64(data + 8);
    v->device_tx_tick = rd_u64(data + 16);
    v->sample_id = rd_u32(data + 24);
    return 0;
}

/* ERROR payload */

int ucan_encode_error_payload(const ucan_error_payload_t *v, uint8_t *out, uint32_t cap,
                              uint32_t *len) {
    if ((v->error_flags & ~0x0007u) != 0 || v->debug_len > 128) {
        return UCAN_ERR_BAD_VALUE;
    }
    int rc = need(cap, 20 + v->debug_len);
    if (rc != 0) {
        return rc;
    }
    wr_u16(out + 0, v->detail_code);
    wr_u16(out + 2, v->error_flags);
    wr_u32(out + 4, v->field_offset);
    wr_u32(out + 8, v->expected);
    wr_u32(out + 12, v->actual);
    wr_u16(out + 16, v->debug_len);
    wr_u16(out + 18, 0);
    if (v->debug_len != 0) {
        memcpy(out + 20, v->debug, v->debug_len);
    }
    *len = 20 + v->debug_len;
    return 0;
}

int ucan_decode_error_payload(const uint8_t *data, uint32_t len,
                              ucan_error_payload_t *v) {
    if (len < 20) {
        return UCAN_ERR_PAYLOAD;
    }
    int rc = reserved_ok(data + 18, 2);
    if (rc != 0) {
        return rc;
    }
    uint16_t debug_len = rd_u16(data + 16);
    if (debug_len > 128 || len != 20 + (uint32_t)debug_len) {
        return UCAN_ERR_PAYLOAD;
    }
    v->detail_code = rd_u16(data + 0);
    v->error_flags = rd_u16(data + 2);
    v->field_offset = rd_u32(data + 4);
    v->expected = rd_u32(data + 8);
    v->actual = rd_u32(data + 12);
    v->debug_len = debug_len;
    v->debug = debug_len == 0 ? NULL : data + 20;
    return ucan_encode_error_payload(v, (uint8_t *)data, len, &len) == 0 ? 0
                                                                         : UCAN_ERR_BAD_VALUE;
}

/* CAN_RX_BATCH */

int ucan_encode_can_rx_batch(const ucan_can_rx_batch_t *v, uint8_t *out, uint32_t cap,
                             uint32_t *len) {
    if ((v->flags & ~0x0001u) != 0 || v->config_generation == 0) {
        return UCAN_ERR_BAD_VALUE;
    }
    uint32_t record_bytes = 0;
    for (uint16_t i = 0; i < v->record_count; ++i) {
        record_bytes += 20 + v->records[i].payload_len;
    }
    int rc = need(cap, 32 + record_bytes);
    if (rc != 0) {
        return rc;
    }
    uint8_t *p = out;
    wr_u16(p + 0, v->record_count);
    wr_u16(p + 2, v->flags);
    wr_u32(p + 4, record_bytes);
    wr_u64(p + 8, v->base_timestamp);
    wr_u64(p + 16, v->device_drop_total);
    wr_u32(p + 24, v->config_generation);
    wr_u32(p + 28, 0);
    uint32_t offset = 32;
    for (uint16_t i = 0; i < v->record_count; ++i) {
        const ucan_can_rx_record_t *r = &v->records[i];
        if ((r->flags & ~UCAN_CAN_RX_FLAGS_MASK) != 0 || r->channel_sequence == 0 ||
            r->rx_status > 3 || r->payload_len > 64) {
            return UCAN_ERR_BAD_VALUE;
        }
        int ext = (r->flags & 0x0001u) != 0;
        uint32_t id_max = ext ? UCAN_CAN_ID_EXT_MAX : UCAN_CAN_ID_STD_MAX;
        if (r->arbitration_id > id_max) {
            return UCAN_ERR_BAD_VALUE;
        }
        uint16_t rx_flags = r->flags;
        if ((rx_flags & 0x0020u) == 0 &&
            !can_payload_ok(r->dlc, rx_flags, r->payload_len)) {
            return UCAN_ERR_BAD_VALUE;
        }
        p = out + offset;
        wr_u32(p + 0, r->delta_tick);
        wr_u32(p + 4, r->arbitration_id);
        wr_u32(p + 8, r->channel_sequence);
        wr_u16(p + 12, r->flags);
        p[14] = r->channel;
        p[15] = r->dlc;
        p[16] = r->payload_len;
        p[17] = r->filter_hit;
        wr_u16(p + 18, r->rx_status);
        if (r->payload_len != 0) {
            memcpy(p + 20, r->payload, r->payload_len);
        }
        offset += 20 + r->payload_len;
    }
    *len = 32 + record_bytes;
    return 0;
}

int ucan_decode_can_rx_batch(const uint8_t *data, uint32_t len,
                             ucan_can_rx_batch_t *v, ucan_can_rx_record_t *records,
                             uint16_t max_records) {
    if (len < 32) {
        return UCAN_ERR_PAYLOAD;
    }
    int rc = reserved_ok(data + 28, 4);
    if (rc != 0) {
        return rc;
    }
    uint16_t record_count = rd_u16(data + 0);
    uint16_t flags = rd_u16(data + 2);
    if ((flags & ~0x0001u) != 0) {
        return UCAN_ERR_BAD_VALUE;
    }
    uint32_t record_bytes = rd_u32(data + 4);
    if (len != 32 + record_bytes) {
        return UCAN_ERR_PAYLOAD;
    }
    if (record_count > max_records) {
        return UCAN_ERR_CAPACITY;
    }
    const uint8_t *p = data + 32;
    uint32_t counted = 0;
    for (uint16_t i = 0; i < record_count; ++i) {
        if (p + 20 > data + len) {
            return UCAN_ERR_PAYLOAD;
        }
        uint8_t payload_len = p[16];
        if (payload_len > 64 || p + 20 + payload_len > data + len) {
            return UCAN_ERR_PAYLOAD;
        }
        ucan_can_rx_record_t *r = &records[i];
        r->delta_tick = rd_u32(p + 0);
        r->arbitration_id = rd_u32(p + 4);
        r->channel_sequence = rd_u32(p + 8);
        r->flags = rd_u16(p + 12);
        r->channel = p[14];
        r->dlc = p[15];
        r->filter_hit = p[17];
        r->rx_status = rd_u16(p + 18);
        r->payload_len = payload_len;
        r->payload = payload_len == 0 ? NULL : p + 20;
        if ((r->flags & ~UCAN_CAN_RX_FLAGS_MASK) != 0 ||
            r->channel_sequence == 0 || r->rx_status > 3) {
            return UCAN_ERR_BAD_VALUE;
        }
        int ext = (r->flags & 0x0001u) != 0;
        uint32_t id_max = ext ? UCAN_CAN_ID_EXT_MAX : UCAN_CAN_ID_STD_MAX;
        if (r->arbitration_id > id_max) {
            return UCAN_ERR_BAD_VALUE;
        }
        if ((r->flags & 0x0020u) == 0 &&
            !can_payload_ok(r->dlc, r->flags, r->payload_len)) {
            return UCAN_ERR_BAD_VALUE;
        }
        counted += 20 + payload_len;
        p += 20 + payload_len;
    }
    if (counted != record_bytes) {
        return UCAN_ERR_PAYLOAD;
    }
    v->flags = flags;
    v->base_timestamp = rd_u64(data + 8);
    v->device_drop_total = rd_u64(data + 16);
    v->config_generation = rd_u32(data + 24);
    v->record_count = record_count;
    v->records = records;
    return v->config_generation == 0 ? UCAN_ERR_BAD_VALUE : 0;
}

/* CAN_TX_RESULT event */

int ucan_encode_can_tx_result(const ucan_can_tx_result_event_t *v, uint8_t *out,
                              uint32_t cap, uint32_t *len) {
    if (v->arm_epoch == 0 || v->result < 1 || v->result > 5 ||
        (v->can_error & 0xfff80000u) != 0 || v->queue_generation == 0) {
        return UCAN_ERR_BAD_VALUE;
    }
    int rc = need(cap, 28);
    if (rc != 0) {
        return rc;
    }
    wr_u32(out + 0, v->client_tag);
    wr_u32(out + 4, v->arm_epoch);
    wr_u16(out + 8, v->result);
    wr_u16(out + 10, 0);
    wr_u64(out + 12, v->hardware_tick);
    wr_u32(out + 20, v->can_error);
    wr_u32(out + 24, v->queue_generation);
    *len = 28;
    return 0;
}

int ucan_decode_can_tx_result(const uint8_t *data, uint32_t len,
                              ucan_can_tx_result_event_t *v) {
    if (len != 28) {
        return UCAN_ERR_PAYLOAD;
    }
    int rc = reserved_ok(data + 6, 2);
    if (rc != 0) {
        return rc;
    }
    v->client_tag = rd_u32(data + 0);
    v->arm_epoch = rd_u32(data + 4);
    v->result = rd_u16(data + 8);
    v->hardware_tick = rd_u64(data + 12);
    v->can_error = rd_u32(data + 20);
    v->queue_generation = rd_u32(data + 24);
    /* Pure validation: never write back into the const input buffer. */
    if (v->arm_epoch == 0 || v->result < 1 || v->result > 5 ||
        (v->can_error & 0xfff80000u) != 0 || v->queue_generation == 0) {
        return UCAN_ERR_BAD_VALUE;
    }
    return 0;
}

/* CHANNEL_STATE event */

int ucan_encode_channel_state(const ucan_channel_state_event_t *v, uint8_t *out,
                              uint32_t cap, uint32_t *len) {
    if (v->state > 4 || ((v->reason < 1 || v->reason > 6) && v->reason != 16) ||
        v->config_generation == 0) {
        return UCAN_ERR_BAD_VALUE;
    }
    int rc = need(cap, 24);
    if (rc != 0) {
        return rc;
    }
    out[0] = v->channel;
    out[1] = v->state;
    wr_u16(out + 2, v->reason);
    wr_u32(out + 4, v->config_generation);
    wr_u32(out + 8, v->tx_error);
    wr_u32(out + 12, v->rx_error);
    wr_u64(out + 16, v->device_tick);
    *len = 24;
    return 0;
}

int ucan_decode_channel_state(const uint8_t *data, uint32_t len,
                              ucan_channel_state_event_t *v) {
    if (len != 24) {
        return UCAN_ERR_PAYLOAD;
    }
    v->channel = data[0];
    v->state = data[1];
    v->reason = rd_u16(data + 2);
    v->config_generation = rd_u32(data + 4);
    v->tx_error = rd_u32(data + 8);
    v->rx_error = rd_u32(data + 12);
    v->device_tick = rd_u64(data + 16);
    return ucan_encode_channel_state(v, (uint8_t *)data, 24, &len) == 0 ? 0
                                                                        : UCAN_ERR_BAD_VALUE;
}

/* FLOW_CONTROL event */

int ucan_encode_flow_control(const ucan_flow_control_event_t *v, uint8_t *out,
                             uint32_t cap, uint32_t *len) {
    int rc = need(cap, 24);
    if (rc != 0) {
        return rc;
    }
    wr_u32(out + 0, v->response_depth);
    wr_u32(out + 4, v->event_depth);
    wr_u32(out + 8, v->data_depth);
    wr_u32(out + 12, v->pool_high_water);
    wr_u64(out + 16, v->device_tick);
    *len = 24;
    return 0;
}

int ucan_decode_flow_control(const uint8_t *data, uint32_t len,
                             ucan_flow_control_event_t *v) {
    if (len != 24) {
        return UCAN_ERR_PAYLOAD;
    }
    v->response_depth = rd_u32(data + 0);
    v->event_depth = rd_u32(data + 4);
    v->data_depth = rd_u32(data + 8);
    v->pool_high_water = rd_u32(data + 12);
    v->device_tick = rd_u64(data + 16);
    return 0;
}

/* DATA_LOSS event */

int ucan_encode_data_loss(const ucan_data_loss_event_t *v, uint8_t *out, uint32_t cap,
                          uint32_t *len) {
    if (v->sequence_domain < 1 || v->sequence_domain > 2 || v->source == 0 ||
        v->source > 4 || v->reason == 0 || v->reason > 4 ||
        v->config_generation == 0) {
        return UCAN_ERR_BAD_VALUE;
    }
    int rc = need(cap, 40);
    if (rc != 0) {
        return rc;
    }
    out[0] = v->channel;
    out[1] = v->source;
    out[2] = v->sequence_domain;
    out[3] = 0;
    wr_u16(out + 4, v->reason);
    wr_u16(out + 6, 0);
    wr_u32(out + 8, v->config_generation);
    wr_u32(out + 12, v->first_dropped_sequence);
    wr_u32(out + 16, v->last_dropped_sequence);
    wr_u32(out + 20, 0);
    wr_u64(out + 24, v->dropped_count);
    wr_u64(out + 32, v->device_tick);
    *len = 40;
    return 0;
}

int ucan_decode_data_loss(const uint8_t *data, uint32_t len, ucan_data_loss_event_t *v) {
    if (len != 40) {
        return UCAN_ERR_PAYLOAD;
    }
    int rc = reserved_ok(data + 3, 1);
    if (rc != 0) {
        return rc;
    }
    rc = reserved_ok(data + 6, 2);
    if (rc != 0) {
        return rc;
    }
    rc = reserved_ok(data + 20, 4);
    if (rc != 0) {
        return rc;
    }
    v->channel = data[0];
    v->source = data[1];
    v->sequence_domain = data[2];
    v->reason = rd_u16(data + 4);
    v->config_generation = rd_u32(data + 8);
    v->first_dropped_sequence = rd_u32(data + 12);
    v->last_dropped_sequence = rd_u32(data + 16);
    v->dropped_count = rd_u64(data + 24);
    v->device_tick = rd_u64(data + 32);
    return ucan_encode_data_loss(v, (uint8_t *)data, 40, &len) == 0 ? 0
                                                                    : UCAN_ERR_BAD_VALUE;
}
