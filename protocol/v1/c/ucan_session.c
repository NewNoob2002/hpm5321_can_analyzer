/*
 * USB-CAN protocol v1.0 device-side session core implementation.
 */
#include "ucan_session.h"

#include <string.h>

#define V1_FEATURES 0x0017u

static void wr_helper_u16(uint8_t *p, uint16_t v) {
    p[0] = (uint8_t)v;
    p[1] = (uint8_t)(v >> 8);
}

static void wr_helper_u32(uint8_t *p, uint32_t v) {
    p[0] = (uint8_t)v;
    p[1] = (uint8_t)(v >> 8);
    p[2] = (uint8_t)(v >> 16);
    p[3] = (uint8_t)(v >> 24);
}

static uint32_t wrap_inc(uint32_t v) {
    uint32_t next = v + 1;
    return next == 0 ? 1 : next;
}

static uint64_t stuffed_bits(uint64_t raw) {
    return (5 * raw + 3) / 4 + 13; /* ceil(5*raw/4) + 13 */
}

uint64_t ucan_frame_time_us(uint32_t nominal_bps, uint32_t data_bps, uint8_t dlc,
                            uint16_t can_flags, uint8_t payload_len) {
    (void)dlc; /* frame time is a function of payload_len per spec 7.1 */
    int fd = (can_flags & 0x0004u) != 0;
    int ext = (can_flags & 0x0001u) != 0;
    uint64_t micro = 1000000u;
    /* A channel configured with nominal_bps=0 (never CONFIG'd) must not divide
     * by zero during bus-load admission. Treat it as unmeasurable and return
     * the worst case (full 64-byte FD frame at the slowest legal 10 kbps)
     * so admission stays conservative rather than crashing. */
    if (nominal_bps == 0) {
        nominal_bps = 10000;
    }
    if (fd) {
        uint64_t nom = stuffed_bits(35 + (ext ? 20 : 0));
        uint64_t dat = stuffed_bits(28 + 8u * payload_len + (payload_len <= 16 ? 17 : 21));
        uint64_t data_bps_eff = data_bps != 0 ? data_bps : nominal_bps;
        return (nom * micro + nominal_bps - 1) / nominal_bps +
               (dat * micro + data_bps_eff - 1) / data_bps_eff;
    }
    uint64_t raw = 47 + (ext ? 20 : 0) + 8u * payload_len;
    return (stuffed_bits(raw) * micro + nominal_bps - 1) / nominal_bps;
}

static uint32_t slot_rate(const ucan_session_t *s, const ucan_tx_slot_t *slot) {
    if (slot->rule_index < s->rule_count) {
        return s->rules[slot->rule_index].max_frames_per_s;
    }
    return 0;
}

static uint64_t channel_pending_us_rate(const ucan_session_t *s, uint8_t channel) {
    uint64_t sum_us_rate = 0;
    for (int i = 0; i < UCAN_SESSION_MAX_TX_SLOTS; ++i) {
        const ucan_tx_slot_t *slot = &s->tx_ledger[i];
        if (!slot->occupied || slot->state != 1 || slot->channel != channel) {
            continue;
        }
        uint64_t t = ucan_frame_time_us(
            s->channels[channel].nominal_bps, s->channels[channel].data_bps,
            slot->dlc, slot->can_flags, slot->payload_len);
        sum_us_rate += t * slot_rate(s, slot);
    }
    return sum_us_rate;
}

uint32_t ucan_session_reserved_permille(const ucan_session_t *s, uint8_t channel) {
    return (uint32_t)((2 * channel_pending_us_rate(s, channel) + 999) / 1000);
}

static void refill_rule_tokens(ucan_session_t *s, uint32_t index) {
    uint64_t elapsed = s->tick - s->rule_last_tick[index];
    uint32_t fill = s->rules[index].max_frames_per_s;
    if (elapsed >= (uint64_t)s->cfg->tick_hz) {
        s->rule_tokens[index] = s->rule_capacity[index];
    } else {
        uint64_t add = fill * elapsed / s->cfg->tick_hz;
        s->rule_tokens[index] += add;
        if (s->rule_tokens[index] > s->rule_capacity[index]) {
            s->rule_tokens[index] = s->rule_capacity[index];
        }
    }
    s->rule_last_tick[index] = s->tick;
}

static void refill_agg_tokens(ucan_session_t *s) {
    uint64_t elapsed = s->tick - s->agg_last_tick;
    if (elapsed >= (uint64_t)s->cfg->tick_hz) {
        s->agg_tokens = s->agg_capacity;
    } else {
        uint64_t add = s->aggregate_max_frames_per_s * elapsed / s->cfg->tick_hz;
        s->agg_tokens += add;
        if (s->agg_tokens > s->agg_capacity) {
            s->agg_tokens = s->agg_capacity;
        }
    }
    s->agg_last_tick = s->tick;
}

static int rule_matches(const ucan_tx_rule_t *rule, uint8_t channel, uint16_t flags,
                        uint32_t id) {
    if (rule->channel != channel) {
        return 0;
    }
    if ((flags & rule->allowed_flag_mask) != flags) {
        return 0;
    }
    return (id & rule->id_mask) == (rule->id & rule->id_mask);
}

static uint32_t find_rule(const ucan_session_t *s, uint8_t channel, uint16_t flags,
                          uint32_t id) {
    for (uint32_t i = 0; i < s->rule_count; ++i) {
        if (rule_matches(&s->rules[i], channel, flags, id)) {
            return i;
        }
    }
    return 0xffffffffu;
}

static uint32_t find_free_slot(const ucan_session_t *s) {
    for (int i = 0; i < UCAN_SESSION_MAX_TX_SLOTS; ++i) {
        if (!s->tx_ledger[i].occupied) {
            return (uint32_t)i;
        }
    }
    return 0xffffffffu;
}

static uint32_t find_tag_slot(const ucan_session_t *s, uint32_t client_tag,
                              uint32_t arm_epoch) {
    for (int i = 0; i < UCAN_SESSION_MAX_TX_SLOTS; ++i) {
        const ucan_tx_slot_t *slot = &s->tx_ledger[i];
        if (slot->occupied && slot->client_tag == client_tag &&
            slot->arm_epoch == arm_epoch) {
            return (uint32_t)i;
        }
    }
    return 0xffffffffu;
}

static uint32_t find_tag_slot_any(const ucan_session_t *s, uint32_t client_tag) {
    for (int i = 0; i < UCAN_SESSION_MAX_TX_SLOTS; ++i) {
        const ucan_tx_slot_t *slot = &s->tx_ledger[i];
        if (slot->occupied && slot->client_tag == client_tag) {
            return (uint32_t)i;
        }
    }
    return 0xffffffffu;
}

static int build_error_frame(const ucan_frame_t *req, uint8_t *out, uint32_t cap,
                             uint32_t *out_len, uint16_t status,
                             uint16_t error_flags, uint32_t expected, uint32_t actual);

static uint32_t alloc_event_sequence(ucan_session_t *s) {
    s->device_event_sequence = wrap_inc(s->device_event_sequence);
    return s->device_event_sequence;
}

static int enqueue_critical(ucan_session_t *s, const uint8_t *bytes, uint32_t len,
                            uint32_t seq) {
    ucan_q_critical_t *q = &s->q_critical;
    if (q->count >= UCAN_QUEUE_CRITICAL_CAP) {
        return -1;
    }
    uint16_t tail = (uint16_t)((q->head + q->count) % UCAN_QUEUE_CRITICAL_CAP);
    ucan_queue_item_t *item = &q->items[tail];
    memcpy(item->data, bytes, len);
    item->len = len;
    item->evt_seq = seq;
    item->kind = 2;
    q->count++;
    s->event_depth = q->count;
    if (s->event_depth > s->pool_high_water) {
        s->pool_high_water = s->event_depth;
    }
    return 0;
}

static int enqueue_response(ucan_session_t *s, const uint8_t *bytes, uint32_t len) {
    ucan_q_response_t *q = &s->q_response;
    if (q->count >= UCAN_QUEUE_RESPONSE_CAP) {
        return -1;
    }
    uint16_t tail = (uint16_t)((q->head + q->count) % UCAN_QUEUE_RESPONSE_CAP);
    ucan_queue_item_t *item = &q->items[tail];
    memcpy(item->data, bytes, len);
    item->len = len;
    item->evt_seq = 0;
    item->kind = 1;
    q->count++;
    s->response_depth = q->count;
    if (s->response_depth > s->pool_high_water) {
        s->pool_high_water = s->response_depth;
    }
    return 0;
}

static int enqueue_data(ucan_session_t *s, const uint8_t *bytes, uint32_t len,
                        uint32_t seq) {
    ucan_q_data_t *q = &s->q_data;
    if (q->count >= UCAN_QUEUE_DATA_CAP) {
        return -1;
    }
    uint16_t tail = (uint16_t)((q->head + q->count) % UCAN_QUEUE_DATA_CAP);
    ucan_queue_item_t *item = &q->items[tail];
    memcpy(item->data, bytes, len);
    item->len = len;
    item->evt_seq = seq;
    item->kind = 3;
    q->count++;
    s->data_depth = q->count;
    if (s->data_depth > s->pool_high_water) {
        s->pool_high_water = s->data_depth;
    }
    return 0;
}

static void emit_can_tx_result(ucan_session_t *s, ucan_tx_slot_t *slot) {
    ucan_can_tx_result_event_t ev;
    ev.client_tag = slot->client_tag;
    ev.arm_epoch = slot->arm_epoch;
    ev.result = slot->final_result;
    ev.hardware_tick = slot->final_tick;
    ev.can_error = slot->can_error;
    ev.queue_generation = s->queue_generation;
    uint8_t buf[64];
    uint32_t len = 0;
    if (ucan_encode_can_tx_result(&ev, buf, sizeof(buf), &len) == 0) {
        uint8_t frame[512];
        ucan_frame_t f;
        memset(&f, 0, sizeof(f));
        f.major = UCAN_PROTOCOL_MAJOR;
        f.minor = UCAN_PROTOCOL_MINOR;
        f.flags = UCAN_FLAG_EVENT;
        f.message_type = UCAN_MSG_CAN_TX_RESULT;
        /* One semantic final result -> one stable event sequence, reused
         * across delivery_pending retries (spec 8.1). */
        if (slot->result_evt_seq == 0) {
            slot->result_evt_seq = alloc_event_sequence(s);
        }
        f.sequence = slot->result_evt_seq;
        f.payload = buf;
        f.payload_len = len;
        uint32_t flen = 0;
        if (ucan_frame_encode(&f, frame, sizeof(frame), &flen) == 0) {
            if (enqueue_critical(s, frame, flen, slot->result_evt_seq) != 0) {
                slot->delivery_pending = 1;
            }
        }
    }
}

static void emit_channel_state(ucan_session_t *s, uint8_t channel, uint8_t state,
                               uint16_t reason) {
    ucan_channel_state_event_t ev;
    ev.channel = channel;
    ev.state = state;
    ev.reason = reason;
    ev.config_generation = s->config_generation;
    ev.tx_error = 0;
    ev.rx_error = 0;
    ev.device_tick = s->tick;
    uint8_t buf[64];
    uint32_t len = 0;
    if (ucan_encode_channel_state(&ev, buf, sizeof(buf), &len) == 0) {
        uint8_t frame[512];
        ucan_frame_t f;
        memset(&f, 0, sizeof(f));
        f.major = UCAN_PROTOCOL_MAJOR;
        f.minor = UCAN_PROTOCOL_MINOR;
        f.flags = UCAN_FLAG_EVENT;
        f.message_type = UCAN_MSG_CHANNEL_STATE;
        uint32_t seq = alloc_event_sequence(s);
        f.sequence = seq;
        f.payload = buf;
        f.payload_len = len;
        uint32_t flen = 0;
        if (ucan_frame_encode(&f, frame, sizeof(frame), &flen) == 0) {
            enqueue_critical(s, frame, flen, seq);
        }
    }
}

static void flush_loss_notice(ucan_session_t *s, ucan_loss_acc_t *acc) {
    ucan_data_loss_event_t ev;
    ev.channel = acc->channel;
    ev.source = acc->source;
    ev.sequence_domain = acc->sequence_domain;
    ev.reason = acc->reason;
    ev.config_generation = acc->config_generation;
    ev.first_dropped_sequence = acc->first_sequence;
    ev.last_dropped_sequence = acc->last_sequence;
    ev.dropped_count = acc->dropped_count;
    ev.device_tick = s->tick;
    uint8_t buf[64];
    uint32_t len = 0;
    if (ucan_encode_data_loss(&ev, buf, sizeof(buf), &len) == 0) {
        uint8_t frame[512];
        ucan_frame_t f;
        memset(&f, 0, sizeof(f));
        f.major = UCAN_PROTOCOL_MAJOR;
        f.minor = UCAN_PROTOCOL_MINOR;
        f.flags = UCAN_FLAG_EVENT;
        f.message_type = UCAN_MSG_DATA_LOSS;
        /* DATA_LOSS allocates its event sequence only on successful
         * critical-slot reservation (spec 8.1); a failed reservation keeps
         * the accumulator for the next retry without burning a sequence. */
        if (acc->evt_seq == 0) {
            acc->evt_seq = alloc_event_sequence(s);
        }
        f.sequence = acc->evt_seq;
        f.payload = buf;
        f.payload_len = len;
        uint32_t flen = 0;
        if (ucan_frame_encode(&f, frame, sizeof(frame), &flen) == 0) {
            if (enqueue_critical(s, frame, flen, acc->evt_seq) == 0) {
                acc->occupied = 0;
                acc->evt_seq = 0;
            }
        }
    }
}

/* Retry pending critical deliveries: loss notices and TX_RESULT events that
 * failed to reserve a critical slot keep their data and are retried once the
 * queue drains (spec 8.1). */
static void flush_pending(ucan_session_t *s) {
    if (s->q_critical.count >= UCAN_QUEUE_CRITICAL_CAP) {
        return;
    }
    for (int i = 0; i < 4; ++i) {
        if (s->loss[i].occupied) {
            flush_loss_notice(s, &s->loss[i]);
        }
    }
    for (int i = 0; i < UCAN_SESSION_MAX_TX_SLOTS; ++i) {
        ucan_tx_slot_t *slot = &s->tx_ledger[i];
        if (slot->occupied && slot->delivery_pending) {
            slot->delivery_pending = 0;
            emit_can_tx_result(s, slot);
        }
    }
}

static void accumulate_loss(ucan_session_t *s, uint8_t channel, uint8_t source,
                            uint8_t domain, uint16_t reason, uint32_t sequence) {
    for (int i = 0; i < 4; ++i) {
        ucan_loss_acc_t *acc = &s->loss[i];
        if (acc->occupied && acc->channel == channel && acc->source == source &&
            acc->sequence_domain == domain && acc->reason == reason &&
            acc->config_generation == s->config_generation) {
            uint32_t next = acc->last_sequence == 0xffffffffu
                                ? 1
                                : acc->last_sequence + 1;
            if (next == sequence) {
                acc->last_sequence = sequence;
                acc->dropped_count++;
                return;
            }
            flush_loss_notice(s, acc);
        }
    }
    for (int i = 0; i < 4; ++i) {
        ucan_loss_acc_t *acc = &s->loss[i];
        if (!acc->occupied) {
            acc->occupied = 1;
            acc->channel = channel;
            acc->source = source;
            acc->sequence_domain = domain;
            acc->reason = reason;
            acc->config_generation = s->config_generation;
            acc->first_sequence = sequence;
            acc->last_sequence = sequence;
            acc->dropped_count = 1;
            return;
        }
    }
    /* No accumulator slot: counters still record the drop. */
}

int ucan_session_init(ucan_session_t *s, const ucan_session_config_t *cfg) {
    memset(s, 0, sizeof(*s));
    s->cfg = cfg;
    s->config_generation = 1;
    s->arm_epoch = 1;
    s->session_id = 0x12345678u; /* replaced by real boot nonce in firmware */
    s->boot_epoch = 0x1122334455667788ull;
    s->device_event_sequence = 1;
    s->queue_generation = 1;
    s->channels[0].mode = 0;
    for (uint8_t i = 0; i < cfg->channel_count && i < UCAN_SESSION_MAX_CHANNELS; ++i) {
        s->channels[i].mode = 0;
        s->channels[i].state = 0;
        s->channels[i].nominal_bps = 0;
        s->channels[i].data_bps = 0;
        s->channels[i].sample_permille = 0;
        s->channels[i].filter_generation = 0;
        s->channels[i].filter_crc = 0;
        s->channels[i].filter_count = 0;
    }
    return 0;
}

void ucan_session_tick(ucan_session_t *s, uint64_t ticks) {
    s->tick += ticks;
    if (s->tx_armed && s->arm_expiry_tick != 0 && s->tick >= s->arm_expiry_tick) {
        /* Auto-disarm on expiry: cancel pending and advance the epoch. */
        for (int i = 0; i < UCAN_SESSION_MAX_TX_SLOTS; ++i) {
            ucan_tx_slot_t *slot = &s->tx_ledger[i];
            if (slot->occupied && slot->state == 1) {
                slot->state = 2;
                slot->final_result = 3; /* TIMEOUT */
                slot->final_tick = s->tick;
                slot->completed_tick = s->tick;
                slot->can_error = 0;
                s->queue_generation = wrap_inc(s->queue_generation);
                emit_can_tx_result(s, slot);
            }
        }
        s->tx_armed = 0;
        s->arm_expiry_tick = 0;
        s->arm_epoch = wrap_inc(s->arm_epoch);
    }
    /* Reclaim FINAL TX ledger slots once the tag-reuse guard has elapsed
     * (spec 5.2): the result must stay queryable for tag_reuse_guard_ms so
     * byte-identical CAN_TX replays can read the FINAL snapshot, then the
     * slot returns to the free pool instead of leaking permanently. */
    for (int i = 0; i < UCAN_SESSION_MAX_TX_SLOTS; ++i) {
        ucan_tx_slot_t *slot = &s->tx_ledger[i];
        if (slot->occupied && slot->state == 2 && !slot->delivery_pending &&
            s->tick - slot->completed_tick >= (uint64_t)s->cfg->tag_reuse_guard_ms *
                                                  s->cfg->tick_hz / 1000) {
            memset(slot, 0, sizeof(*slot));
        }
    }
}

int ucan_session_on_rx(ucan_session_t *s, uint8_t channel,
                       const ucan_can_rx_record_t *rec) {
    if (channel >= s->cfg->channel_count) {
        return 1;
    }
    ucan_session_channel_t *c = &s->channels[channel];
    c->rx_frames++;
    if (c->rx_depth >= (uint32_t)s->cfg->tx_depth) {
        c->dropped++;
        accumulate_loss(s, channel, 1 /* CAN_RING */, 2 /* CHANNEL */, 1 /* OVERFLOW */,
                        rec->channel_sequence);
        return 1;
    }
    c->rx_depth++;
    return 0;
}

int ucan_session_emit_rx_batch(ucan_session_t *s, uint8_t channel,
                               const ucan_can_rx_record_t *rec) {
    if (channel >= s->cfg->channel_count || s->capture_state != 1) {
        return 1;
    }
    ucan_can_rx_batch_t batch;
    batch.flags = 0;
    batch.base_timestamp = s->tick;
    batch.device_drop_total = s->channels[channel].dropped;
    batch.config_generation = s->config_generation;
    batch.record_count = 1;
    batch.records = rec;
    uint8_t buf[256];
    uint32_t len = 0;
    if (ucan_encode_can_rx_batch(&batch, buf, sizeof(buf), &len) != 0) {
        return 1;
    }
    /* Allocate the event sequence before data-queue admission (spec 8.1):
     * even a dropped batch consumes a sequence so the host can account it. */
    uint32_t seq = alloc_event_sequence(s);
    uint8_t frame[512];
    ucan_frame_t f;
    memset(&f, 0, sizeof(f));
    f.major = UCAN_PROTOCOL_MAJOR;
    f.minor = UCAN_PROTOCOL_MINOR;
    f.flags = UCAN_FLAG_EVENT;
    f.message_type = UCAN_MSG_CAN_RX_BATCH;
    f.sequence = seq;
    f.payload = buf;
    f.payload_len = len;
    uint32_t flen = 0;
    if (ucan_frame_encode(&f, frame, sizeof(frame), &flen) != 0) {
        return 1;
    }
    if (enqueue_data(s, frame, flen, seq) != 0) {
        /* USB data queue full: EVENT-domain loss, channel 0xFF. */
        accumulate_loss(s, 0xff, 2 /* USB_DATA_QUEUE */, 1 /* EVENT */,
                        1 /* OVERFLOW */, seq);
        return 1;
    }
    if (s->channels[channel].rx_depth > 0) {
        s->channels[channel].rx_depth--;
    }
    return 0;
}

void ucan_session_can_tx_complete(ucan_session_t *s, uint32_t client_tag,
                                  uint16_t result, uint32_t can_error) {
    uint32_t index = find_tag_slot_any(s, client_tag);
    if (index == 0xffffffffu) {
        return;
    }
    ucan_tx_slot_t *slot = &s->tx_ledger[index];
    if (slot->state == 2) {
        return; /* exactly one final */
    }
    slot->state = 2;
    /* A frame that completes after its client-declared deadline is a late
     * delivery -> TIMEOUT (3), not the passed-in result (spec 5.2). */
    slot->final_result = (slot->deadline_tick != 0 && s->tick > slot->deadline_tick)
                             ? 3 /* TIMEOUT */
                             : result;
    slot->final_tick = s->tick;
    slot->can_error = can_error;
    slot->completed_tick = s->tick;
    s->channels[slot->channel].tx_frames++;
    s->queue_generation = wrap_inc(s->queue_generation);
    emit_can_tx_result(s, slot);
}

static int is_side_effect(uint16_t message_type) {
    switch (message_type) {
    case UCAN_MSG_CONFIG_CHANNEL:
    case UCAN_MSG_START_CAPTURE:
    case UCAN_MSG_STOP_CAPTURE:
    case UCAN_MSG_SET_FILTERS:
    case UCAN_MSG_CLEAR_FILTERS:
    case UCAN_MSG_TX_ARM:
    case UCAN_MSG_TX_DISARM:
    case UCAN_MSG_RESET_DIAGNOSTICS:
        /* CAN_TX / CAN_TX_CANCEL intentionally bypass the generic replay
         * cache: their idempotency is served by the TX result ledger which
         * must return the latest PENDING/FINAL snapshot (spec 5.2). */
        return 1;
    default:
        return 0;
    }
}

/* Returns 1 when the request is a replay hit (response already written). */
static int replay_hit(ucan_session_t *s, const ucan_frame_t *req, uint8_t *out,
                      uint32_t cap, uint32_t *out_len) {
    if (!is_side_effect(req->message_type)) {
        return 0;
    }
    uint64_t retention_ticks =
        (uint64_t)s->cfg->replay_retention_ms * s->cfg->tick_hz / 1000;
    for (int i = 0; i < UCAN_SESSION_REPLAY_ENTRIES; ++i) {
        ucan_replay_entry_t *e = &s->replay[i];
        if (!e->occupied) {
            continue;
        }
        if (e->sequence == req->sequence && e->message_type == req->message_type) {
            int same_bytes = e->payload_len == req->payload_len &&
                             (e->payload_len == 0 ||
                              memcmp(e->payload, req->payload, e->payload_len) == 0);
            if (same_bytes && s->tick - e->stored_tick <= retention_ticks) {
                /* Never copy a cached response that does not fit the caller's
                 * buffer: surface BUSY|RETRYABLE instead of overflowing the
                 * destination (spec 5.2 / 8.1). */
                if (e->response_len > cap) {
                    build_error_frame(req, out, cap, out_len, UCAN_STATUS_BUSY, 0x0001,
                                      0, 0);
                    return 1;
                }
                memcpy(out, e->response, e->response_len);
                *out_len = e->response_len;
                return 1;
            }
            if (!same_bytes) {
                /* Sequence reused with different bytes: BAD_STATE, no side
                 * effect. Emit an error response directly. */
                ucan_error_payload_t err;
                memset(&err, 0, sizeof(err));
                err.detail_code = UCAN_STATUS_BAD_STATE;
                err.error_flags = 0x0001; /* RETRYABLE */
                err.field_offset = 0xffffffffu;
                uint8_t ebuf[64];
                uint32_t elen = 0;
                ucan_encode_error_payload(&err, ebuf, sizeof(ebuf), &elen);
                ucan_frame_t resp;
                memset(&resp, 0, sizeof(resp));
                resp.major = UCAN_PROTOCOL_MAJOR;
                resp.minor = UCAN_PROTOCOL_MINOR;
                resp.flags = UCAN_FLAG_RESPONSE | UCAN_FLAG_ERROR;
                resp.message_type = req->message_type;
                resp.status = UCAN_STATUS_BAD_STATE;
                resp.sequence = req->sequence;
                resp.payload = ebuf;
                resp.payload_len = elen;
                ucan_frame_encode(&resp, out, cap, out_len);
                return 1;
            }
        }
    }
    return 0;
}

/* True when every replay slot holds an entry still inside its retention
 * window, so a new side-effect request cannot be stored without evicting a
 * valid cache entry (spec 5.2). */
static int replay_cache_full_of_retention(const ucan_session_t *s) {
    uint64_t retention_ticks =
        (uint64_t)s->cfg->replay_retention_ms * s->cfg->tick_hz / 1000;
    for (int i = 0; i < UCAN_SESSION_REPLAY_ENTRIES; ++i) {
        const ucan_replay_entry_t *e = &s->replay[i];
        if (!e->occupied || s->tick - e->stored_tick > retention_ticks) {
            return 0; /* free slot, or an expired entry that may be evicted */
        }
    }
    return 1;
}

static void replay_store(ucan_session_t *s, const ucan_frame_t *req,
                         const uint8_t *response, uint32_t response_len) {
    if (!is_side_effect(req->message_type)) {
        return;
    }
    int slot = -1;
    uint64_t oldest = (uint64_t)-1;
    for (int i = 0; i < UCAN_SESSION_REPLAY_ENTRIES; ++i) {
        ucan_replay_entry_t *e = &s->replay[i];
        if (!e->occupied) {
            slot = i;
            break;
        }
        if (e->stored_tick < oldest) {
            oldest = e->stored_tick;
            slot = i;
        }
    }
    if (slot < 0) {
        return;
    }
    ucan_replay_entry_t *e = &s->replay[slot];
    e->occupied = 1;
    e->sequence = req->sequence;
    e->message_type = req->message_type;
    e->stored_tick = s->tick;
    e->payload_len = req->payload_len > sizeof(e->payload)
                         ? (uint32_t)sizeof(e->payload)
                         : req->payload_len;
    if (e->payload_len != 0) {
        memcpy(e->payload, req->payload, e->payload_len);
    }
    e->response_len = response_len < sizeof(e->response) ? response_len
                                                         : (uint32_t)sizeof(e->response);
    memcpy(e->response, response, e->response_len);
}

static int response_ok(ucan_session_t *s, const ucan_frame_t *req, uint8_t *out,
                       uint32_t cap, uint32_t *out_len, uint16_t message_type,
                       const uint8_t *payload, uint32_t payload_len) {
    ucan_frame_t resp;
    memset(&resp, 0, sizeof(resp));
    resp.major = UCAN_PROTOCOL_MAJOR;
    resp.minor = UCAN_PROTOCOL_MINOR;
    resp.flags = UCAN_FLAG_RESPONSE;
    resp.message_type = message_type;
    resp.status = UCAN_STATUS_OK;
    resp.sequence = req->sequence;
    resp.payload = payload;
    resp.payload_len = payload_len;
    int rc = ucan_frame_encode(&resp, out, cap, out_len);
    if (rc == 0) {
        if (enqueue_response(s, out, *out_len) != 0) {
            /* Response reserve exhausted (spec 8.1): refuse with BUSY. */
            rc = build_error_frame(req, out, cap, out_len, UCAN_STATUS_BUSY, 0x0001,
                                   0, 0);
            return rc;
        }
        replay_store(s, req, out, *out_len);
    }
    return rc;
}

static int build_error_frame(const ucan_frame_t *req, uint8_t *out, uint32_t cap,
                             uint32_t *out_len, uint16_t status,
                             uint16_t error_flags, uint32_t expected,
                             uint32_t actual) {
    ucan_error_payload_t err;
    memset(&err, 0, sizeof(err));
    err.detail_code = status;
    err.error_flags = error_flags;
    err.field_offset = 0xffffffffu;
    err.expected = expected;
    err.actual = actual;
    err.debug_len = 0;
    uint8_t ebuf[64];
    uint32_t elen = 0;
    if (ucan_encode_error_payload(&err, ebuf, sizeof(ebuf), &elen) != 0) {
        return -1;
    }
    ucan_frame_t resp;
    memset(&resp, 0, sizeof(resp));
    resp.major = UCAN_PROTOCOL_MAJOR;
    resp.minor = UCAN_PROTOCOL_MINOR;
    resp.flags = UCAN_FLAG_RESPONSE | UCAN_FLAG_ERROR;
    resp.message_type = req->message_type;
    resp.status = status;
    resp.sequence = req->sequence;
    resp.payload = ebuf;
    resp.payload_len = elen;
    return ucan_frame_encode(&resp, out, cap, out_len);
}

static int response_error(ucan_session_t *s, const ucan_frame_t *req, uint8_t *out,
                          uint32_t cap, uint32_t *out_len, uint16_t status,
                          uint16_t error_flags, uint32_t expected, uint32_t actual) {
    int rc = build_error_frame(req, out, cap, out_len, status, error_flags, expected,
                               actual);
    if (rc == 0 && enqueue_response(s, out, *out_len) == 0) {
        replay_store(s, req, out, *out_len);
    }
    return rc;
}

/* Cancel pending TX and drop the armed state without emitting a response.
 * Used when a configuration change invalidates the current arm (spec 5.2/11:
 * config changes must not let stale authorizations transmit). */
static void disarm_tx(ucan_session_t *s) {
    if (!s->tx_armed) {
        return;
    }
    for (int i = 0; i < UCAN_SESSION_MAX_TX_SLOTS; ++i) {
        ucan_tx_slot_t *slot = &s->tx_ledger[i];
        if (slot->occupied && slot->state == 1) {
            slot->state = 2;
            slot->final_result = 5; /* DISARMED */
            slot->final_tick = s->tick;
            slot->completed_tick = s->tick;
            slot->can_error = 0;
            s->queue_generation = wrap_inc(s->queue_generation);
            emit_can_tx_result(s, slot);
        }
    }
    s->tx_armed = 0;
    s->arm_expiry_tick = 0;
    s->arm_epoch = wrap_inc(s->arm_epoch);
}

static int cas_check(ucan_session_t *s, const ucan_frame_t *req, uint32_t expected,
                     uint8_t *out, uint32_t cap, uint32_t *out_len) {
    if (expected != s->config_generation) {
        response_error(s, req, out, cap, out_len, UCAN_STATUS_BAD_STATE, 0x0002,
                       expected, s->config_generation);
        return 1;
    }
    return 0;
}

int ucan_session_handle_frame(ucan_session_t *s, const ucan_frame_t *req,
                              uint8_t *out, uint32_t cap, uint32_t *out_len) {
    uint8_t scratch[512];
    uint32_t slen = 0;
    s->usb_rx_bytes += req->payload_len + UCAN_HEADER_LEN;

    if (req->flags & UCAN_FLAG_EVENT) {
        return -1; /* device never receives events */
    }
    if ((req->flags & UCAN_FLAG_REQUEST) == 0) {
        /* Spec 2.1: exactly one of REQUEST/RESPONSE/EVENT; a frame the device
         * must not act on (a response or bare status) is rejected, not echoed
         * as a response. */
        return -1;
    }

    if (!s->negotiated && req->message_type != UCAN_MSG_HELLO &&
        req->message_type != UCAN_MSG_GET_DEVICE_INFO) {
        /* Spec 2.2: host must HELLO first. Before negotiation only HELLO (and,
         * after a version mismatch, GET_DEVICE_INFO) is permitted. */
        return response_error(s, req, out, cap, out_len, UCAN_STATUS_BAD_STATE, 0x0002,
                              0, 0);
    }

    if (replay_hit(s, req, out, cap, out_len)) {
        return 0;
    }

    /* Spec 5.2: when every replay slot is still within retention, a NEW
     * side-effect request must be refused (BUSY|RETRYABLE) before executing,
     * not silently evict a still-valid cache entry. */
    if (is_side_effect(req->message_type) && replay_cache_full_of_retention(s)) {
        return response_error(s, req, out, cap, out_len, UCAN_STATUS_BUSY, 0x0001, 0, 0);
    }

    /* Spec 8.1: a side-effect request must be refused before executing when the
     * response reserve is exhausted, so the config/filter/arm mutation is never
     * applied yet answered BUSY. The BUSY frame is returned synchronously. */
    if (is_side_effect(req->message_type) &&
        s->q_response.count >= UCAN_QUEUE_RESPONSE_CAP) {
        return build_error_frame(req, out, cap, out_len, UCAN_STATUS_BUSY, 0x0001, 0, 0);
    }

    switch (req->message_type) {
    case UCAN_MSG_HELLO: {
        ucan_hello_req_t hello;
        if (ucan_decode_hello_req(req->payload, req->payload_len, &hello) != 0) {
            return response_error(s, req, out, cap, out_len, UCAN_STATUS_INVALID_ARGUMENT,
                                  0, 0, 0);
        }
        /* Spec 2.2: pick the highest major shared by both, then the highest
         * shared minor. v1 only defines major 1, so a host whose range does
         * not include 1 is incompatible. */
        if (hello.max_major < UCAN_PROTOCOL_MAJOR ||
            hello.min_major > UCAN_PROTOCOL_MAJOR) {
            return response_error(s, req, out, cap, out_len,
                                  UCAN_STATUS_INCOMPATIBLE_VERSION, 0, 0, 0);
        }
        /* Device minor is UCAN_PROTOCOL_MINOR (0). The intersection with the
         * host's [min_minor, max_minor] covers minor 0 iff min_minor <= 0.
         * (min_minor is u8 so this is only ever 0.) */
        if (hello.min_minor > UCAN_PROTOCOL_MINOR) {
            return response_error(s, req, out, cap, out_len,
                                  UCAN_STATUS_INCOMPATIBLE_VERSION, 0, 0, 0);
        }
        ucan_hello_resp_t resp;
        resp.major = UCAN_PROTOCOL_MAJOR;
        resp.minor = UCAN_PROTOCOL_MINOR;
        resp.session_id = s->session_id;
        resp.max_message = 65536;
        resp.device_features = hello.host_features & s->cfg->global_features;
        if (ucan_encode_hello_resp(&resp, scratch, sizeof(scratch), &slen) != 0) {
            return -1;
        }
        s->negotiated = 1;
        s->min_minor = 0;
        s->max_minor = 0;
        return response_ok(s, req, out, cap, out_len, UCAN_MSG_HELLO, scratch, slen);
    }
    case UCAN_MSG_GET_DEVICE_INFO: {
        if (ucan_decode_empty(req->payload, req->payload_len) != 0) {
            return response_error(s, req, out, cap, out_len,
                                  UCAN_STATUS_INVALID_ARGUMENT, 0, 0, 0);
        }
        ucan_device_info_t info;
        info.firmware_semver.str = (const uint8_t *)s->cfg->fw_semver;
        info.firmware_semver.len = (uint16_t)strlen(s->cfg->fw_semver);
        info.build_id.str = (const uint8_t *)s->cfg->build_id;
        info.build_id.len = (uint16_t)strlen(s->cfg->build_id);
        info.board_id.str = (const uint8_t *)s->cfg->board_id;
        info.board_id.len = (uint16_t)strlen(s->cfg->board_id);
        info.serial.str = (const uint8_t *)s->cfg->serial;
        info.serial.len = (uint16_t)strlen(s->cfg->serial);
        if (ucan_encode_device_info(&info, scratch, sizeof(scratch), &slen) != 0) {
            return -1;
        }
        return response_ok(s, req, out, cap, out_len, UCAN_MSG_GET_DEVICE_INFO, scratch,
                           slen);
    }
    case UCAN_MSG_GET_CAPABILITIES: {
        if (ucan_decode_empty(req->payload, req->payload_len) != 0) {
            return response_error(s, req, out, cap, out_len,
                                  UCAN_STATUS_INVALID_ARGUMENT, 0, 0, 0);
        }
        ucan_capabilities_t caps;
        memset(&caps, 0, sizeof(caps));
        caps.cap_generation = 1;
        caps.max_message = 65536;
        caps.max_rx_batch = 64;
        caps.tx_depth = s->cfg->tx_depth;
        caps.tick_hz = s->cfg->tick_hz;
        caps.tick_resolution_ns = s->cfg->tick_resolution_ns;
        caps.boot_epoch = s->boot_epoch;
        caps.outstanding_limit = s->cfg->outstanding_limit;
        caps.response_capacity = s->cfg->response_capacity;
        caps.event_capacity = s->cfg->event_capacity;
        caps.data_capacity = s->cfg->data_capacity;
        caps.arm_timeout_min_ms = s->cfg->arm_timeout_min_ms;
        caps.arm_timeout_max_ms = s->cfg->arm_timeout_max_ms;
        caps.channel_count = s->cfg->channel_count;
        caps.usb_mode = s->cfg->usb_mode;
        caps.global_features = s->cfg->global_features;
        caps.replay_cache_entries = s->cfg->replay_cache_entries;
        caps.tx_result_cache_entries = s->cfg->tx_result_cache_entries;
        caps.replay_retention_ms = s->cfg->replay_retention_ms;
        caps.tag_reuse_guard_ms = s->cfg->tag_reuse_guard_ms;
        caps.channels = s->cfg->channels;
        if (ucan_encode_capabilities(&caps, scratch, sizeof(scratch), &slen) != 0) {
            return -1;
        }
        return response_ok(s, req, out, cap, out_len, UCAN_MSG_GET_CAPABILITIES, scratch,
                           slen);
    }
    case UCAN_MSG_GET_DIAGNOSTICS: {
        if (ucan_decode_empty(req->payload, req->payload_len) != 0) {
            return response_error(s, req, out, cap, out_len,
                                  UCAN_STATUS_INVALID_ARGUMENT, 0, 0, 0);
        }
        ucan_diagnostics_t diag;
        memset(&diag, 0, sizeof(diag));
        diag.generation = s->diag_generation == 0 ? 1 : s->diag_generation;
        diag.session_id = s->session_id;
        diag.response_depth = s->response_depth;
        diag.event_depth = s->event_depth;
        diag.data_depth = s->data_depth;
        diag.pool_high_water = s->pool_high_water;
        diag.usb_rx_bytes = s->usb_rx_bytes;
        diag.usb_tx_bytes = s->usb_tx_bytes;
        ucan_channel_diag_t chans[UCAN_SESSION_MAX_CHANNELS];
        for (uint8_t i = 0; i < s->cfg->channel_count; ++i) {
            ucan_session_channel_t *c = &s->channels[i];
            chans[i].channel = i;
            chans[i].state = c->state;
            chans[i].rx_depth = c->rx_depth;
            chans[i].tx_depth = c->tx_depth;
            chans[i].rx_frames = c->rx_frames;
            chans[i].tx_frames = c->tx_frames;
            chans[i].filtered = c->filtered;
            chans[i].dropped = c->dropped;
            chans[i].bus_off_count = c->bus_off_count;
            chans[i].error_count = c->error_count;
        }
        diag.channel_count = s->cfg->channel_count;
        diag.channels = chans;
        if (ucan_encode_diagnostics(&diag, scratch, sizeof(scratch), &slen) != 0) {
            return -1;
        }
        return response_ok(s, req, out, cap, out_len, UCAN_MSG_GET_DIAGNOSTICS, scratch,
                           slen);
    }
    case UCAN_MSG_RESET_DIAGNOSTICS: {
        uint32_t mask = 0;
        if (ucan_decode_reset_diagnostics(req->payload, req->payload_len, &mask) != 0) {
            return response_error(s, req, out, cap, out_len,
                                  UCAN_STATUS_INVALID_ARGUMENT, 0, 0, 0);
        }
        if ((mask & 0x0002u) != 0) {
            for (uint8_t i = 0; i < s->cfg->channel_count; ++i) {
                s->channels[i].rx_frames = 0;
                s->channels[i].tx_frames = 0;
                s->channels[i].filtered = 0;
                s->channels[i].dropped = 0;
                s->channels[i].bus_off_count = 0;
                s->channels[i].error_count = 0;
                s->channels[i].rx_depth = 0;
                s->channels[i].tx_depth = 0;
            }
        }
        if ((mask & 0x0001u) != 0) {
            s->usb_rx_bytes = 0;
            s->usb_tx_bytes = 0;
        }
        s->diag_generation = wrap_inc(s->diag_generation);
        /* RESET responds with the new diagnostics snapshot (spec 5.1). */
        ucan_diagnostics_t diag;
        memset(&diag, 0, sizeof(diag));
        diag.generation = s->diag_generation;
        diag.session_id = s->session_id;
        diag.response_depth = s->response_depth;
        diag.event_depth = s->event_depth;
        diag.data_depth = s->data_depth;
        diag.pool_high_water = s->pool_high_water;
        diag.usb_rx_bytes = s->usb_rx_bytes;
        diag.usb_tx_bytes = s->usb_tx_bytes;
        ucan_channel_diag_t chans[UCAN_SESSION_MAX_CHANNELS];
        for (uint8_t i = 0; i < s->cfg->channel_count; ++i) {
            ucan_session_channel_t *c = &s->channels[i];
            chans[i].channel = i;
            chans[i].state = c->state;
            chans[i].rx_depth = c->rx_depth;
            chans[i].tx_depth = c->tx_depth;
            chans[i].rx_frames = c->rx_frames;
            chans[i].tx_frames = c->tx_frames;
            chans[i].filtered = c->filtered;
            chans[i].dropped = c->dropped;
            chans[i].bus_off_count = c->bus_off_count;
            chans[i].error_count = c->error_count;
        }
        diag.channel_count = s->cfg->channel_count;
        diag.channels = chans;
        if (ucan_encode_diagnostics(&diag, scratch, sizeof(scratch), &slen) != 0) {
            return -1;
        }
        return response_ok(s, req, out, cap, out_len, UCAN_MSG_RESET_DIAGNOSTICS,
                           scratch, slen);
    }
    case UCAN_MSG_GET_SESSION_STATE: {
        if (ucan_decode_empty(req->payload, req->payload_len) != 0) {
            return response_error(s, req, out, cap, out_len,
                                  UCAN_STATUS_INVALID_ARGUMENT, 0, 0, 0);
        }
        ucan_session_state_t st;
        memset(&st, 0, sizeof(st));
        st.config_generation = s->config_generation;
        st.capture_generation = s->capture_generation;
        st.capture_state = s->capture_state;
        st.tx_armed = s->tx_armed != 0;
        st.arm_epoch = s->arm_epoch;
        st.arm_expiry_tick = s->arm_expiry_tick;
        st.aggregate_max_frames_per_s = s->aggregate_max_frames_per_s;
        ucan_filter_state_t filters[UCAN_SESSION_MAX_CHANNELS];
        for (uint8_t i = 0; i < s->cfg->channel_count; ++i) {
            filters[i].channel = i;
            filters[i].filter_generation = s->channels[i].filter_generation;
            filters[i].filter_crc32c = s->channels[i].filter_crc;
        }
        st.filter_count = s->cfg->channel_count;
        st.filters = filters;
        if (ucan_encode_session_state(&st, scratch, sizeof(scratch), &slen) != 0) {
            return -1;
        }
        return response_ok(s, req, out, cap, out_len, UCAN_MSG_GET_SESSION_STATE,
                           scratch, slen);
    }
    case UCAN_MSG_CONFIG_CHANNEL: {
        ucan_channel_config_t cfg_req;
        if (ucan_decode_channel_config(req->payload, req->payload_len, &cfg_req) != 0) {
            return response_error(s, req, out, cap, out_len,
                                  UCAN_STATUS_INVALID_ARGUMENT, 0, 0, 0);
        }
        if (cfg_req.channel >= s->cfg->channel_count) {
            return response_error(s, req, out, cap, out_len,
                                  UCAN_STATUS_INVALID_ARGUMENT, 0, 0, 0);
        }
        if (cas_check(s, req, cfg_req.generation, out, cap, out_len)) {
            return 0;
        }
        /* A bitrate/mode change invalidates the armed TX admission contract:
         * disarm so no frame transmits under the stale arm (spec 5.2/11). */
        disarm_tx(s);
        ucan_session_channel_t *c = &s->channels[cfg_req.channel];
        c->mode = cfg_req.mode;
        c->flags = cfg_req.flags;
        c->nominal_bps = cfg_req.nominal_bps;
        c->data_bps = cfg_req.data_bps;
        c->sample_permille = cfg_req.sample_permille;
        c->state = (cfg_req.mode == 0) ? 0 : (cfg_req.mode == 1 ? 1 : 2);
        s->config_generation = wrap_inc(s->config_generation);
        ucan_channel_config_t applied = cfg_req;
        applied.generation = s->config_generation;
        if (ucan_encode_channel_config(&applied, scratch, sizeof(scratch), &slen) != 0) {
            return -1;
        }
        emit_channel_state(s, cfg_req.channel, c->state, 16 /* CONFIG_APPLIED */);
        return response_ok(s, req, out, cap, out_len, UCAN_MSG_CONFIG_CHANNEL, scratch,
                           slen);
    }
    case UCAN_MSG_GET_CHANNEL_CONFIG: {
        ucan_clear_filters_req_t get_req;
        if (ucan_decode_get_channel_config(req->payload, req->payload_len, &get_req) != 0) {
            return response_error(s, req, out, cap, out_len,
                                  UCAN_STATUS_INVALID_ARGUMENT, 0, 0, 0);
        }
        if (get_req.channel >= s->cfg->channel_count) {
            return response_error(s, req, out, cap, out_len,
                                  UCAN_STATUS_INVALID_ARGUMENT, 0, 0, 0);
        }
        ucan_session_channel_t *c = &s->channels[get_req.channel];
        ucan_channel_config_t cfg_resp;
        cfg_resp.channel = get_req.channel;
        cfg_resp.mode = c->mode;
        cfg_resp.flags = c->flags;
        cfg_resp.nominal_bps = c->nominal_bps;
        cfg_resp.data_bps = c->data_bps;
        cfg_resp.sample_permille = c->sample_permille;
        cfg_resp.generation = s->config_generation;
        if (ucan_encode_channel_config(&cfg_resp, scratch, sizeof(scratch), &slen) != 0) {
            return -1;
        }
        return response_ok(s, req, out, cap, out_len, UCAN_MSG_GET_CHANNEL_CONFIG,
                           scratch, slen);
    }
    case UCAN_MSG_START_CAPTURE:
    case UCAN_MSG_STOP_CAPTURE: {
        ucan_capture_req_t cap_req;
        if (ucan_decode_capture_req(req->payload, req->payload_len, &cap_req) != 0) {
            return response_error(s, req, out, cap, out_len,
                                  UCAN_STATUS_INVALID_ARGUMENT, 0, 0, 0);
        }
        if (cas_check(s, req, cap_req.expected_generation, out, cap, out_len)) {
            return 0;
        }
        s->config_generation = wrap_inc(s->config_generation);
        s->capture_state =
            req->message_type == UCAN_MSG_START_CAPTURE ? 1 : 0;
        s->capture_generation = s->config_generation;
        ucan_capture_resp_t cap_resp;
        cap_resp.applied_generation = s->config_generation;
        cap_resp.state = s->capture_state;
        if (ucan_encode_capture_resp(&cap_resp, scratch, sizeof(scratch), &slen) != 0) {
            return -1;
        }
        return response_ok(s, req, out, cap, out_len, req->message_type, scratch, slen);
    }
    case UCAN_MSG_SET_FILTERS: {
        ucan_filter_rule_t rules[UCAN_SESSION_MAX_FILTERS];
        ucan_set_filters_req_t filter_req;
        if (ucan_decode_set_filters(req->payload, req->payload_len, &filter_req, rules,
                                    UCAN_SESSION_MAX_FILTERS) != 0) {
            return response_error(s, req, out, cap, out_len,
                                  UCAN_STATUS_INVALID_ARGUMENT, 0, 0, 0);
        }
        if (filter_req.channel >= s->cfg->channel_count) {
            return response_error(s, req, out, cap, out_len,
                                  UCAN_STATUS_INVALID_ARGUMENT, 0, 0, 0);
        }
        if (cas_check(s, req, filter_req.expected_generation, out, cap, out_len)) {
            return 0;
        }
        disarm_tx(s);
        ucan_session_channel_t *c = &s->channels[filter_req.channel];
        s->config_generation = wrap_inc(s->config_generation);
        c->filter_count = filter_req.rule_count;
        for (uint16_t i = 0; i < filter_req.rule_count; ++i) {
            c->filters[i] = filter_req.rules[i];
        }
        c->filter_generation = s->config_generation;
        c->filter_crc = 0;
        {
            /* CRC over canonical records. */
            uint8_t canon[UCAN_SESSION_MAX_FILTERS * 12];
            for (uint16_t i = 0; i < filter_req.rule_count; ++i) {
                uint8_t *p = canon + i * 12;
                wr_helper_u32(p, c->filters[i].id);
                wr_helper_u32(p + 4, c->filters[i].mask);
                wr_helper_u16(p + 8, c->filters[i].flags);
                p[10] = 0;
                p[11] = 0;
            }
            c->filter_crc = ucan_crc32c(canon, filter_req.rule_count * 12);
        }
        ucan_set_filters_resp_t filter_resp;
        filter_resp.applied_generation = s->config_generation;
        filter_resp.applied_count = filter_req.rule_count;
        if (ucan_encode_set_filters_resp(&filter_resp, scratch, sizeof(scratch),
                                         &slen) != 0) {
            return -1;
        }
        return response_ok(s, req, out, cap, out_len, UCAN_MSG_SET_FILTERS, scratch,
                           slen);
    }
    case UCAN_MSG_CLEAR_FILTERS: {
        ucan_clear_filters_req_t clear_req;
        if (ucan_decode_clear_filters(req->payload, req->payload_len, &clear_req) != 0) {
            return response_error(s, req, out, cap, out_len,
                                  UCAN_STATUS_INVALID_ARGUMENT, 0, 0, 0);
        }
        if (clear_req.channel >= s->cfg->channel_count) {
            return response_error(s, req, out, cap, out_len,
                                  UCAN_STATUS_INVALID_ARGUMENT, 0, 0, 0);
        }
        if (cas_check(s, req, clear_req.expected_generation, out, cap, out_len)) {
            return 0;
        }
        disarm_tx(s);
        ucan_session_channel_t *c = &s->channels[clear_req.channel];
        s->config_generation = wrap_inc(s->config_generation);
        c->filter_count = 0;
        c->filter_generation = s->config_generation;
        c->filter_crc = ucan_crc32c(NULL, 0);
        ucan_clear_filters_resp_t clear_resp;
        clear_resp.applied_generation = s->config_generation;
        if (ucan_encode_clear_filters_resp(&clear_resp, scratch, sizeof(scratch),
                                           &slen) != 0) {
            return -1;
        }
        return response_ok(s, req, out, cap, out_len, UCAN_MSG_CLEAR_FILTERS, scratch,
                           slen);
    }
    case UCAN_MSG_TX_ARM: {
        ucan_tx_rule_t rules[UCAN_SESSION_MAX_RULES];
        ucan_tx_arm_req_t arm_req;
        if (ucan_decode_tx_arm(req->payload, req->payload_len, &arm_req, rules,
                               UCAN_SESSION_MAX_RULES) != 0) {
            return response_error(s, req, out, cap, out_len,
                                  UCAN_STATUS_INVALID_ARGUMENT, 0, 0, 0);
        }
        if (arm_req.timeout_ms < s->cfg->arm_timeout_min_ms ||
            arm_req.timeout_ms > s->cfg->arm_timeout_max_ms) {
            return response_error(s, req, out, cap, out_len,
                                  UCAN_STATUS_INVALID_ARGUMENT, 0, 0, 0);
        }
        if (cas_check(s, req, arm_req.expected_config_generation, out, cap, out_len)) {
            return 0;
        }
        s->config_generation = wrap_inc(s->config_generation);
        s->rule_count = arm_req.rule_count;
        for (uint8_t i = 0; i < arm_req.rule_count; ++i) {
            s->rules[i] = arm_req.rules[i];
            s->rule_capacity[i] =
                arm_req.rules[i].max_frames_per_s / 10 < 1
                    ? 1
                    : arm_req.rules[i].max_frames_per_s / 10;
            if (s->rule_capacity[i] > s->cfg->tx_depth) {
                s->rule_capacity[i] = s->cfg->tx_depth;
            }
            s->rule_tokens[i] = s->rule_capacity[i];
            s->rule_last_tick[i] = s->tick;
        }
        s->aggregate_max_frames_per_s = arm_req.max_frames_per_s;
        s->max_bus_load_permille = arm_req.max_bus_load_permille;
        s->agg_capacity = arm_req.max_frames_per_s / 10 < 1
                              ? 1
                              : arm_req.max_frames_per_s / 10;
        s->agg_tokens = s->agg_capacity;
        s->agg_last_tick = s->tick;
        s->arm_epoch = wrap_inc(s->arm_epoch);
        s->tx_armed = 1;
        s->arm_expiry_tick =
            s->tick + (uint64_t)arm_req.timeout_ms * s->cfg->tick_hz / 1000;
        ucan_tx_arm_resp_t arm_resp;
        arm_resp.applied_config_generation = s->config_generation;
        arm_resp.arm_epoch = s->arm_epoch;
        arm_resp.expiry_tick = s->arm_expiry_tick;
        if (ucan_encode_tx_arm_resp(&arm_resp, scratch, sizeof(scratch), &slen) != 0) {
            return -1;
        }
        return response_ok(s, req, out, cap, out_len, UCAN_MSG_TX_ARM, scratch, slen);
    }
    case UCAN_MSG_TX_DISARM: {
        ucan_tx_disarm_req_t disarm_req;
        if (ucan_decode_tx_disarm(req->payload, req->payload_len, &disarm_req) != 0) {
            return response_error(s, req, out, cap, out_len,
                                  UCAN_STATUS_INVALID_ARGUMENT, 0, 0, 0);
        }
        if (cas_check(s, req, disarm_req.expected_config_generation, out, cap, out_len)) {
            return 0;
        }
        if (!s->tx_armed || disarm_req.arm_epoch != s->arm_epoch) {
            return response_error(s, req, out, cap, out_len, UCAN_STATUS_BAD_STATE,
                                  0x0002, disarm_req.arm_epoch, s->arm_epoch);
        }
        uint32_t cancelled = 0;
        for (int i = 0; i < UCAN_SESSION_MAX_TX_SLOTS; ++i) {
            ucan_tx_slot_t *slot = &s->tx_ledger[i];
            if (slot->occupied && slot->state == 1) {
                slot->state = 2;
                slot->final_result = 5; /* DISARMED */
                slot->final_tick = s->tick;
                slot->completed_tick = s->tick;
                slot->can_error = 0;
                s->queue_generation = wrap_inc(s->queue_generation);
                emit_can_tx_result(s, slot);
                cancelled++;
            }
        }
        s->config_generation = wrap_inc(s->config_generation);
        s->arm_epoch = wrap_inc(s->arm_epoch);
        s->tx_armed = 0;
        s->arm_expiry_tick = 0;
        ucan_tx_disarm_resp_t disarm_resp;
        disarm_resp.applied_config_generation = s->config_generation;
        disarm_resp.new_arm_epoch = s->arm_epoch;
        disarm_resp.cancelled_count = cancelled;
        if (ucan_encode_tx_disarm_resp(&disarm_resp, scratch, sizeof(scratch),
                                       &slen) != 0) {
            return -1;
        }
        return response_ok(s, req, out, cap, out_len, UCAN_MSG_TX_DISARM, scratch,
                           slen);
    }
    case UCAN_MSG_CAN_TX: {
        ucan_can_tx_req_t tx_req;
        if (ucan_decode_can_tx(req->payload, req->payload_len, &tx_req) != 0) {
            return response_error(s, req, out, cap, out_len,
                                  UCAN_STATUS_INVALID_ARGUMENT, 0, 0, 0);
        }
        if (!s->tx_armed) {
            return response_error(s, req, out, cap, out_len, UCAN_STATUS_BAD_STATE,
                                  0x0002, 0, 0);
        }
        if (tx_req.arm_epoch != s->arm_epoch) {
            return response_error(s, req, out, cap, out_len, UCAN_STATUS_BAD_STATE,
                                  0x0002, tx_req.arm_epoch, s->arm_epoch);
        }
        if (tx_req.channel >= s->cfg->channel_count) {
            return response_error(s, req, out, cap, out_len,
                                  UCAN_STATUS_INVALID_ARGUMENT, 0, 0, 0);
        }
        if (tx_req.deadline_tick != 0 && tx_req.deadline_tick <= s->tick) {
            return response_error(s, req, out, cap, out_len, UCAN_STATUS_TIMEOUT, 0, 0,
                                  0);
        }
        uint32_t existing = find_tag_slot(s, tx_req.client_tag, tx_req.arm_epoch);
        if (existing != 0xffffffffu) {
            ucan_tx_slot_t *slot = &s->tx_ledger[existing];
            int same = slot->payload_len == tx_req.payload_len &&
                       (tx_req.payload_len == 0 ||
                        memcmp(slot->payload, tx_req.payload, tx_req.payload_len) == 0) &&
                       slot->dlc == tx_req.dlc && slot->can_flags == tx_req.can_flags &&
                       slot->channel == tx_req.channel;
            if (!same) {
                return response_error(s, req, out, cap, out_len,
                                      UCAN_STATUS_INVALID_ARGUMENT, 0, 0, 0);
            }
            ucan_can_tx_resp_t snap;
            snap.client_tag = slot->client_tag;
            snap.queue_generation = s->queue_generation;
            snap.tx_state = slot->state;
            snap.final_result = slot->final_result;
            snap.final_tick = slot->final_tick;
            snap.can_error = slot->can_error;
            if (ucan_encode_can_tx_resp(&snap, scratch, sizeof(scratch), &slen) != 0) {
                return -1;
            }
            return response_ok(s, req, out, cap, out_len, UCAN_MSG_CAN_TX, scratch,
                               slen);
        }
        uint32_t rule = find_rule(s, tx_req.channel, tx_req.can_flags, tx_req.id);
        if (rule == 0xffffffffu) {
            return response_error(s, req, out, cap, out_len,
                                  UCAN_STATUS_INVALID_ARGUMENT, 0, 0, 0);
        }
        uint32_t slot_index = find_free_slot(s);
        if (slot_index == 0xffffffffu) {
            return response_error(s, req, out, cap, out_len, UCAN_STATUS_NO_RESOURCE,
                                  0x0001, 0, 0);
        }
        /* Admission: token buckets + reserved load. */
        refill_rule_tokens(s, rule);
        refill_agg_tokens(s);
        if (s->rule_tokens[rule] < 1 || s->agg_tokens < 1) {
            return response_error(s, req, out, cap, out_len, UCAN_STATUS_BUSY,
                                  0x0001, 0, 0);
        }
        {
            uint64_t sum_us_rate =
                channel_pending_us_rate(s, tx_req.channel);
            uint64_t t = ucan_frame_time_us(
                s->channels[tx_req.channel].nominal_bps,
                s->channels[tx_req.channel].data_bps, tx_req.dlc, tx_req.can_flags,
                tx_req.payload_len);
            sum_us_rate += (uint64_t)s->rules[rule].max_frames_per_s * t;
            uint32_t permille = (uint32_t)((2 * sum_us_rate + 999) / 1000);
            if (permille > s->max_bus_load_permille) {
                return response_error(s, req, out, cap, out_len, UCAN_STATUS_BUSY,
                                      0x0001, 0, 0);
            }
        }
        s->rule_tokens[rule]--;
        s->agg_tokens--;
        ucan_tx_slot_t *slot = &s->tx_ledger[slot_index];
        memset(slot, 0, sizeof(*slot));
        slot->occupied = 1;
        slot->channel = tx_req.channel;
        slot->can_flags = tx_req.can_flags;
        slot->dlc = tx_req.dlc;
        slot->payload_len = tx_req.payload_len;
        if (tx_req.payload_len != 0) {
            memcpy(slot->payload, tx_req.payload, tx_req.payload_len);
        }
        slot->client_tag = tx_req.client_tag;
        slot->arm_epoch = tx_req.arm_epoch;
        slot->state = 1;
        slot->rule_index = rule;
        slot->deadline_tick = tx_req.deadline_tick;
        s->queue_generation = wrap_inc(s->queue_generation);
        ucan_can_tx_resp_t tx_resp;
        tx_resp.client_tag = tx_req.client_tag;
        tx_resp.queue_generation = s->queue_generation;
        tx_resp.tx_state = 1;
        tx_resp.final_result = 0;
        tx_resp.final_tick = 0;
        tx_resp.can_error = 0;
        if (ucan_encode_can_tx_resp(&tx_resp, scratch, sizeof(scratch), &slen) != 0) {
            return -1;
        }
        return response_ok(s, req, out, cap, out_len, UCAN_MSG_CAN_TX, scratch, slen);
    }
    case UCAN_MSG_CAN_TX_CANCEL: {
        ucan_can_tx_cancel_req_t cancel_req;
        if (ucan_decode_can_tx_cancel(req->payload, req->payload_len, &cancel_req) != 0) {
            return response_error(s, req, out, cap, out_len,
                                  UCAN_STATUS_INVALID_ARGUMENT, 0, 0, 0);
        }
        uint32_t slot_index = find_tag_slot(s, cancel_req.client_tag,
                                            cancel_req.arm_epoch);
        ucan_can_tx_cancel_resp_t cancel_resp;
        cancel_resp.client_tag = cancel_req.client_tag;
        if (slot_index == 0xffffffffu) {
            cancel_resp.cancel_state = 3; /* NOT_FOUND */
        } else {
            ucan_tx_slot_t *slot = &s->tx_ledger[slot_index];
            if (slot->state == 2) {
                cancel_resp.cancel_state = 2; /* ALREADY_COMPLETE */
            } else {
                slot->state = 2;
                slot->final_result = 2; /* CANCELLED */
                slot->final_tick = s->tick;
                slot->completed_tick = s->tick;
                slot->can_error = 0;
                s->queue_generation = wrap_inc(s->queue_generation);
                emit_can_tx_result(s, slot);
                cancel_resp.cancel_state = 1; /* CANCELLED */
            }
        }
        if (ucan_encode_can_tx_cancel_resp(&cancel_resp, scratch, sizeof(scratch),
                                           &slen) != 0) {
            return -1;
        }
        return response_ok(s, req, out, cap, out_len, UCAN_MSG_CAN_TX_CANCEL, scratch,
                           slen);
    }
    case UCAN_MSG_PING: {
        ucan_ping_req_t ping_req;
        if (ucan_decode_ping_req(req->payload, req->payload_len, &ping_req) != 0) {
            return response_error(s, req, out, cap, out_len,
                                  UCAN_STATUS_INVALID_ARGUMENT, 0, 0, 0);
        }
        ucan_ping_resp_t ping_resp;
        ping_resp.host_send_ns = ping_req.host_send_ns;
        ping_resp.device_rx_tick = s->tick;
        ping_resp.device_tx_tick = s->tick;
        ping_resp.sample_id = ping_req.sample_id;
        if (ucan_encode_ping_resp(&ping_resp, scratch, sizeof(scratch), &slen) != 0) {
            return -1;
        }
        return response_ok(s, req, out, cap, out_len, UCAN_MSG_PING, scratch, slen);
    }
    default:
        return response_error(s, req, out, cap, out_len, UCAN_STATUS_UNSUPPORTED, 0, 0,
                              0);
    }
}

int ucan_session_dequeue(ucan_session_t *s, uint8_t *out, uint32_t cap,
                         uint32_t *out_len, uint32_t *evt_seq) {
    flush_pending(s);
    ucan_q_response_t *qr = &s->q_response;
    ucan_q_critical_t *qc = &s->q_critical;
    ucan_q_data_t *qd = &s->q_data;
    if (qr->count == 0 && qc->count == 0 && qd->count == 0) {
        return 1;
    }
    /* Select the next queue + head WITHOUT popping, so a frame that does not
     * fit cap is left queued (caller retries with a larger buffer) instead of
     * being silently truncated to a CRC-invalid prefix (spec 8.1: no silent
     * drop). */
    ucan_queue_item_t *item = NULL;
    uint16_t head = 0;
    int kind = 0; /* 1 response, 2 critical, 3 data */
    if (qd->count != 0 &&
        ((qr->count == 0 && qc->count == 0) || s->served_since_data >= 16)) {
        head = qd->head;
        item = &qd->items[head];
        kind = 3;
    } else if (qc->count != 0 && s->response_streak >= 8) {
        head = qc->head;
        item = &qc->items[head];
        kind = 2;
    } else if (qr->count != 0) {
        head = qr->head;
        item = &qr->items[head];
        kind = 1;
    } else if (qc->count != 0) {
        head = qc->head;
        item = &qc->items[head];
        kind = 2;
    } else {
        head = qd->head;
        item = &qd->items[head];
        kind = 3;
    }
    if (item->len > cap) {
        return -1; /* frame preserved; caller must provide more space */
    }
    /* Pop now that the frame is known to fit. */
    switch (kind) {
    case 3:
        qd->head = (uint16_t)((head + 1) % UCAN_QUEUE_DATA_CAP);
        qd->count--;
        s->data_depth = qd->count;
        s->served_since_data = 0;
        s->response_streak = 0;
        break;
    case 2:
        qc->head = (uint16_t)((head + 1) % UCAN_QUEUE_CRITICAL_CAP);
        qc->count--;
        s->event_depth = qc->count;
        s->response_streak = 0;
        s->served_since_data++;
        break;
    default:
        qr->head = (uint16_t)((head + 1) % UCAN_QUEUE_RESPONSE_CAP);
        qr->count--;
        s->response_depth = qr->count;
        s->response_streak++;
        s->served_since_data++;
        break;
    }
    memcpy(out, item->data, item->len);
    *out_len = item->len;
    *evt_seq = item->evt_seq;
    return 0;
}
