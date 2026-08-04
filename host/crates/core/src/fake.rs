//! In-memory fake analyzer device and transport.
//!
//! `FakeDevice` implements the v1.0 wire contract (docs/approved-plan/
//! usb-can-protocol-v1.md) in memory: version negotiation, CAS generations,
//! arm epoch, TX result ledger, replay cache, capture streaming and loss
//! injection. `FakeTransport` exposes it through the [`Transport`] trait so
//! the host client and CLI can run the same regression suite against the fake
//! backend and the real libusb backend (fake-backend parity gate).

use std::collections::VecDeque;
use std::time::Duration;

use hpm_usb_can_protocol::payload::{
    Capabilities, ChannelCapability, DeviceInfo, ErrorPayload, HelloRequest, HelloResponse,
    PingRequest, PingResponse,
};
use hpm_usb_can_protocol::payload_control::{
    self, CanTxCancelRequest, CanTxCancelResponse, CanTxRequest, CanTxResponse, CaptureRequest,
    CaptureResponse, ChannelConfig, ClearFiltersRequest, ClearFiltersResponse, Diagnostics,
    FilterRule, GetChannelConfigRequest, ResetDiagnosticsRequest, SessionState, SetFiltersRequest,
    SetFiltersResponse, TxArmRequest, TxArmResponse, TxDisarmRequest, TxDisarmResponse,
};
use hpm_usb_can_protocol::payload_events::{
    CanRxBatch, CanRxRecord, CanTxResultEvent, ChannelStateEvent, DataLossEvent,
};
use hpm_usb_can_protocol::{
    Frame, PROTOCOL_MAJOR, PROTOCOL_MINOR, StreamDecoder, decode, flags, msg,
};

use crate::transport::{Transport, TransportError};

pub const MAX_MESSAGE: usize = 65_536;
const V1_FEATURES: u32 = 0x0017;

const STATUS_OK: u16 = 0;
const STATUS_INVALID_ARGUMENT: u16 = 1;
const STATUS_UNSUPPORTED: u16 = 2;
const STATUS_INCOMPATIBLE_VERSION: u16 = 3;
const STATUS_BAD_STATE: u16 = 4;
const STATUS_BUSY: u16 = 5;
const STATUS_TIMEOUT: u16 = 6;
const STATUS_NO_RESOURCE: u16 = 7;

const TX_PENDING: u8 = 1;
const TX_FINAL: u8 = 2;
const TX_SENT: u16 = 1;
const TX_CANCELLED: u16 = 2;
const TX_TIMEOUT: u16 = 3;
const TX_DISARMED: u16 = 5;

#[derive(Clone, Debug)]
struct TxSlot {
    client_tag: u32,
    arm_epoch: u32,
    can_flags: u16,
    dlc: u8,
    payload: Vec<u8>,
    state: u8,
    final_result: u16,
    final_tick: u64,
    can_error: u32,
    completion_tick: u64,
    deadline_tick: u64,
}

#[derive(Clone, Debug)]
struct ReplayEntry {
    sequence: u32,
    message_type: u16,
    payload: Vec<u8>,
    response: Vec<u8>,
    stored_tick: u64,
}

#[derive(Clone, Debug)]
struct ChannelState {
    mode: u8,
    flags: u16,
    nominal_bps: u32,
    data_bps: u32,
    sample_permille: u16,
    filter_generation: u32,
    filter_crc: u32,
    filters: Vec<FilterRule>,
}

/// In-memory analyzer device implementing the v1.0 protocol contract.
#[derive(Clone, Debug)]
pub struct FakeDevice {
    session_id: u32,
    negotiated: bool,
    config_generation: u32,
    capture_generation: u32,
    capture_state: u8,
    arm_epoch: u32,
    tx_armed: bool,
    arm_expiry_tick: u64,
    aggregate_max_frames_per_s: u32,
    max_bus_load_permille: u16,
    tick: u64,
    channel: ChannelState,
    rx_frames: u64,
    tx_frames: u64,
    filtered: u64,
    dropped: u64,
    slots: Vec<TxSlot>,
    replay: Vec<ReplayEntry>,
    next_channel_sequence: u32,
    /// Monotonic device event sequence (spec: event frames are sequenced so the
    /// host can detect loss/reorder/gap). Starts at 1, wraps past 0.
    device_event_sequence: u32,
    outbox: VecDeque<Vec<u8>>,
    rule_tokens: Vec<u64>,
    rule_capacity: Vec<u64>,
    rule_last_tick: Vec<u64>,
    agg_tokens: u64,
    agg_capacity: u64,
    agg_last_tick: u64,
    /// Simulated transmission time in ticks for an accepted CAN_TX.
    pub tx_delay_ticks: u64,
    /// When true, every CAN_TX admission is rejected BUSY (token exhaustion).
    pub force_busy: bool,
}

impl FakeDevice {
    pub fn new() -> Self {
        Self {
            session_id: 0x1234_5678,
            negotiated: false,
            config_generation: 1,
            capture_generation: 0,
            capture_state: 0,
            arm_epoch: 1,
            tx_armed: false,
            arm_expiry_tick: 0,
            aggregate_max_frames_per_s: 0,
            max_bus_load_permille: 0,
            tick: 0,
            channel: ChannelState {
                mode: 0,
                flags: 0,
                nominal_bps: 0,
                data_bps: 0,
                sample_permille: 0,
                filter_generation: 0,
                filter_crc: 0,
                filters: Vec::new(),
            },
            rx_frames: 0,
            tx_frames: 0,
            filtered: 0,
            dropped: 0,
            slots: Vec::new(),
            replay: Vec::new(),
            next_channel_sequence: 1,
            device_event_sequence: 1,
            outbox: VecDeque::new(),
            rule_tokens: Vec::new(),
            rule_capacity: Vec::new(),
            rule_last_tick: Vec::new(),
            agg_tokens: 0,
            agg_capacity: 0,
            agg_last_tick: 0,
            tx_delay_ticks: 1000,
            force_busy: false,
        }
    }

    pub fn session_id(&self) -> u32 {
        self.session_id
    }

    pub fn config_generation(&self) -> u32 {
        self.config_generation
    }

    pub fn arm_epoch(&self) -> u32 {
        self.arm_epoch
    }

    pub fn tx_armed(&self) -> bool {
        self.tx_armed
    }

    pub fn rx_frames(&self) -> u64 {
        self.rx_frames
    }

    pub fn tx_frames(&self) -> u64 {
        self.tx_frames
    }

    pub fn tick_value(&self) -> u64 {
        self.tick
    }

    /// Simulate a device reboot / re-enumeration: the session restarts and the
    /// session identity changes, invalidating any cached host state.
    pub fn reset(&mut self) {
        let next = self.session_id.wrapping_add(1);
        self.session_id = if next == 0 { 1 } else { next };
        self.negotiated = false;
        self.config_generation = 1;
        self.capture_generation = 0;
        self.capture_state = 0;
        self.arm_epoch = 1;
        self.tx_armed = false;
        self.arm_expiry_tick = 0;
        self.aggregate_max_frames_per_s = 0;
        self.max_bus_load_permille = 0;
        self.channel = ChannelState {
            mode: 0,
            flags: 0,
            nominal_bps: 0,
            data_bps: 0,
            sample_permille: 0,
            filter_generation: 0,
            filter_crc: 0,
            filters: Vec::new(),
        };
        self.rx_frames = 0;
        self.tx_frames = 0;
        self.filtered = 0;
        self.dropped = 0;
        self.slots.clear();
        self.replay.clear();
        self.next_channel_sequence = 1;
        self.device_event_sequence = 1;
        self.outbox.clear();
        self.rule_tokens.clear();
        self.rule_capacity.clear();
        self.rule_last_tick.clear();
        self.agg_tokens = 0;
        self.agg_capacity = 0;
        self.agg_last_tick = 0;
    }

    /// Advance the device clock; completes transmissions and expires arms.
    pub fn tick(&mut self, ticks: u64) {
        self.tick += ticks;
        let mut completed = Vec::new();
        for index in 0..self.slots.len() {
            let slot = &self.slots[index];
            if slot.state == TX_PENDING && slot.completion_tick <= self.tick {
                completed.push(index);
            }
        }
        let mut emitted = Vec::new();
        for index in completed {
            let slot = &mut self.slots[index];
            slot.state = TX_FINAL;
            // A frame that completes after its client-declared deadline is a
            // TIMEOUT (late delivery), not a clean SENT.
            slot.final_result = if slot.deadline_tick != 0 && self.tick > slot.deadline_tick {
                TX_TIMEOUT
            } else {
                TX_SENT
            };
            slot.final_tick = self.tick;
            self.tx_frames += 1;
            emitted.push(slot.clone());
        }
        for snapshot in emitted {
            self.emit_tx_result(&snapshot);
        }
        if self.tx_armed && self.arm_expiry_tick != 0 && self.tick >= self.arm_expiry_tick {
            let mut expired = Vec::new();
            for index in 0..self.slots.len() {
                let slot = &mut self.slots[index];
                if slot.state == TX_PENDING {
                    slot.state = TX_FINAL;
                    slot.final_result = TX_TIMEOUT;
                    slot.final_tick = self.tick;
                    expired.push(slot.clone());
                }
            }
            for snapshot in expired {
                self.emit_tx_result(&snapshot);
            }
            self.tx_armed = false;
            self.arm_expiry_tick = 0;
            self.arm_epoch = self.arm_epoch.wrapping_add(1).max(1);
            if self.arm_epoch == 0 {
                self.arm_epoch = 1;
            }
        }
        // Reclaim FINAL slots once the tag-reuse guard has elapsed (spec 5.2):
        // the FINAL snapshot stays queryable for tag_reuse_guard_ms, then the
        // slot is freed so the ledger does not leak to permanent NO_RESOURCE.
        let guard_ticks = 1_000u64 * 1_000; /* tag_reuse_guard_ms at 1 MHz */
        self.slots.retain(|slot| {
            !(slot.state == TX_FINAL && self.tick.saturating_sub(slot.final_tick) >= guard_ticks)
        });
    }

    fn alloc_event_sequence(&mut self) -> u32 {
        self.device_event_sequence = self.device_event_sequence.wrapping_add(1).max(1);
        self.device_event_sequence
    }

    /// Emit a DATA_LOSS notice for a simulated ring overflow.
    pub fn inject_loss(&mut self) {
        let event = DataLossEvent {
            channel: 0,
            source: 1,          // CAN_RING
            sequence_domain: 2, // CHANNEL
            reason: 1,          // OVERFLOW
            config_generation: self.config_generation,
            first_dropped_sequence: self.next_channel_sequence,
            last_dropped_sequence: self.next_channel_sequence,
            dropped_count: 1,
            device_tick: self.tick,
        };
        self.dropped += 1;
        self.next_channel_sequence = self.next_channel_sequence.wrapping_add(1).max(1);
        let payload = event.encode().expect("data loss encodes");
        let frame = Frame {
            major: PROTOCOL_MAJOR,
            minor: PROTOCOL_MINOR,
            flags: flags::EVENT,
            message_type: msg::DATA_LOSS,
            status: 0,
            sequence: self.alloc_event_sequence(),
            payload,
        };
        if let Ok(bytes) = frame.encode(MAX_MESSAGE) {
            self.outbox.push_back(bytes);
        }
    }

    fn emit_tx_result(&mut self, slot: &TxSlot) {
        let event = CanTxResultEvent {
            client_tag: slot.client_tag,
            arm_epoch: slot.arm_epoch,
            result: slot.final_result,
            hardware_tick: slot.final_tick,
            can_error: slot.can_error,
            queue_generation: 1,
        };
        if let Ok(payload) = event.encode() {
            let frame = Frame {
                major: PROTOCOL_MAJOR,
                minor: PROTOCOL_MINOR,
                flags: flags::EVENT,
                message_type: msg::CAN_TX_RESULT,
                status: 0,
                sequence: self.alloc_event_sequence(),
                payload,
            };
            if let Ok(bytes) = frame.encode(MAX_MESSAGE) {
                self.outbox.push_back(bytes);
            }
        }
    }

    fn emit_channel_state(&mut self) {
        let event = ChannelStateEvent {
            channel: 0,
            state: if self.channel.mode == 0 {
                0
            } else if self.channel.mode == 1 {
                1
            } else {
                2
            },
            reason: 16, // CONFIG_APPLIED
            config_generation: self.config_generation,
            tx_error: 0,
            rx_error: 0,
            device_tick: self.tick,
        };
        if let Ok(payload) = event.encode() {
            let frame = Frame {
                major: PROTOCOL_MAJOR,
                minor: PROTOCOL_MINOR,
                flags: flags::EVENT,
                message_type: msg::CHANNEL_STATE,
                status: 0,
                sequence: self.alloc_event_sequence(),
                payload,
            };
            if let Ok(bytes) = frame.encode(MAX_MESSAGE) {
                self.outbox.push_back(bytes);
            }
        }
    }

    /// Next encoded output: queued responses/events first, then a capture
    /// batch when capture is active. Returns `None` when idle.
    fn next_output(&mut self) -> Option<Vec<u8>> {
        if let Some(bytes) = self.outbox.pop_front() {
            return Some(bytes);
        }
        if self.capture_state == 1 {
            let mut data = vec![0u8; 8];
            data[..4].copy_from_slice(&self.next_channel_sequence.to_le_bytes());
            let record = CanRxRecord {
                delta_tick: 0,
                arbitration_id: 0x123,
                channel_sequence: self.next_channel_sequence,
                flags: 0,
                channel: 0,
                dlc: 8,
                filter_hit: 0xff,
                rx_status: 0,
                payload: data,
            };
            let batch = CanRxBatch {
                flags: 0,
                base_timestamp: self.tick,
                device_drop_total: self.dropped,
                config_generation: self.config_generation,
                records: vec![record],
            };
            if let Ok(payload) = batch.encode() {
                let frame = Frame {
                    major: PROTOCOL_MAJOR,
                    minor: PROTOCOL_MINOR,
                    flags: flags::EVENT,
                    message_type: msg::CAN_RX_BATCH,
                    status: 0,
                    sequence: self.alloc_event_sequence(),
                    payload,
                };
                if let Ok(bytes) = frame.encode(MAX_MESSAGE) {
                    self.rx_frames += 1;
                    self.next_channel_sequence = self.next_channel_sequence.wrapping_add(1).max(1);
                    return Some(bytes);
                }
            }
        }
        None
    }

    /// Process one request frame; returns the encoded response if any.
    fn process_request(&mut self, frame: &Frame) -> Result<Option<Vec<u8>>, TransportError> {
        if frame.flags & flags::REQUEST == 0 {
            return Err(TransportError::Io(
                "device only accepts request frames".to_owned(),
            ));
        }
        // Spec 2.2: host must HELLO first. Before negotiation only HELLO (and,
        // after a version mismatch, GET_DEVICE_INFO) is permitted.
        if !self.negotiated
            && frame.message_type != msg::HELLO
            && frame.message_type != msg::GET_DEVICE_INFO
        {
            return Ok(Some(self.error_response(
                frame,
                STATUS_BAD_STATE,
                0x0002,
                0,
                0,
            )));
        }
        if let Some(cached) = self.replay_hit(frame) {
            return Ok(Some(cached));
        }
        // Spec 5.2: refuse a NEW side-effect request when the replay cache is
        // full of entries still inside retention, rather than evicting a valid
        // one mid-retention.
        if Self::is_side_effect(frame.message_type) && self.replay_cache_full_of_retention() {
            return Ok(Some(self.error_response(frame, STATUS_BUSY, 0x0001, 0, 0)));
        }
        let response = match frame.message_type {
            msg::HELLO => self.handle_hello(frame),
            msg::GET_DEVICE_INFO => self.handle_device_info(frame),
            msg::GET_CAPABILITIES => self.handle_capabilities(frame),
            msg::GET_DIAGNOSTICS => self.handle_diagnostics(frame),
            msg::RESET_DIAGNOSTICS => self.handle_reset_diagnostics(frame),
            msg::GET_SESSION_STATE => self.handle_session_state(frame),
            msg::CONFIG_CHANNEL => self.handle_config_channel(frame),
            msg::GET_CHANNEL_CONFIG => self.handle_get_channel_config(frame),
            msg::START_CAPTURE => self.handle_capture(frame, 1),
            msg::STOP_CAPTURE => self.handle_capture(frame, 0),
            msg::SET_FILTERS => self.handle_set_filters(frame),
            msg::CLEAR_FILTERS => self.handle_clear_filters(frame),
            msg::TX_ARM => self.handle_tx_arm(frame),
            msg::TX_DISARM => self.handle_tx_disarm(frame),
            msg::CAN_TX => self.handle_can_tx(frame),
            msg::CAN_TX_CANCEL => self.handle_can_tx_cancel(frame),
            msg::PING => self.handle_ping(frame),
            _ => self.error_response(frame, STATUS_UNSUPPORTED, 0, 0, 0),
        };
        Ok(Some(response))
    }

    fn is_side_effect(message_type: u16) -> bool {
        matches!(
            message_type,
            msg::CONFIG_CHANNEL
                | msg::START_CAPTURE
                | msg::STOP_CAPTURE
                | msg::SET_FILTERS
                | msg::CLEAR_FILTERS
                | msg::TX_ARM
                | msg::TX_DISARM
                | msg::RESET_DIAGNOSTICS
        )
    }

    fn replay_hit(&mut self, frame: &Frame) -> Option<Vec<u8>> {
        if !Self::is_side_effect(frame.message_type) {
            return None;
        }
        let retention_ticks = 5_000u64 * 1_000; /* replay_retention_ms at 1 MHz */
        // The entry stays in the cache for the retention window so duplicate
        // side-effect requests are suppressed repeatedly, not just once
        // (spec 5.2). It is only evicted by replay_store FIFO pressure.
        self.replay.iter().find_map(|entry| {
            if entry.sequence == frame.sequence
                && entry.message_type == frame.message_type
                && entry.payload == frame.payload
                && self.tick.saturating_sub(entry.stored_tick) <= retention_ticks
            {
                Some(entry.response.clone())
            } else {
                None
            }
        })
    }

    fn replay_cache_full_of_retention(&self) -> bool {
        if self.replay.len() < 8 {
            return false;
        }
        let retention_ticks = 5_000u64 * 1_000; /* replay_retention_ms at 1 MHz */
        self.replay
            .iter()
            .all(|entry| self.tick.saturating_sub(entry.stored_tick) <= retention_ticks)
    }

    fn replay_store(&mut self, frame: &Frame, response: &[u8]) {
        if !Self::is_side_effect(frame.message_type) {
            return;
        }
        // FIFO pressure: drop the oldest. The preflight in process_request
        // prevents this from evicting an entry still inside retention.
        if self.replay.len() >= 8 {
            self.replay.remove(0);
        }
        self.replay.push(ReplayEntry {
            sequence: frame.sequence,
            message_type: frame.message_type,
            payload: frame.payload.clone(),
            response: response.to_vec(),
            stored_tick: self.tick,
        });
    }

    fn ok_response(&mut self, frame: &Frame, payload: Vec<u8>) -> Vec<u8> {
        let response = Frame {
            major: PROTOCOL_MAJOR,
            minor: PROTOCOL_MINOR,
            flags: flags::RESPONSE,
            message_type: frame.message_type,
            status: STATUS_OK,
            sequence: frame.sequence,
            payload,
        };
        let bytes = response.encode(MAX_MESSAGE).expect("response encodes");
        self.replay_store(frame, &bytes);
        bytes
    }

    fn error_response(
        &self,
        frame: &Frame,
        status: u16,
        error_flags: u16,
        expected: u32,
        actual: u32,
    ) -> Vec<u8> {
        let error = ErrorPayload {
            detail_code: status,
            error_flags,
            field_offset: u32::MAX,
            expected,
            actual,
            debug: String::new(),
        };
        let payload = error.encode().expect("error payload encodes");
        let response = Frame {
            major: PROTOCOL_MAJOR,
            minor: PROTOCOL_MINOR,
            flags: flags::RESPONSE | flags::ERROR,
            message_type: frame.message_type,
            status,
            sequence: frame.sequence,
            payload,
        };
        response
            .encode(MAX_MESSAGE)
            .expect("error response encodes")
    }

    fn handle_hello(&mut self, frame: &Frame) -> Vec<u8> {
        let Ok(request) = HelloRequest::decode(&frame.payload) else {
            return self.error_response(frame, STATUS_INVALID_ARGUMENT, 0, 0, 0);
        };
        if request.max_major < PROTOCOL_MAJOR || request.min_major > PROTOCOL_MAJOR {
            return self.error_response(frame, STATUS_INCOMPATIBLE_VERSION, 0, 0, 0);
        }
        self.negotiated = true;
        let response = HelloResponse {
            major: PROTOCOL_MAJOR,
            minor: PROTOCOL_MINOR,
            session_id: self.session_id,
            max_message: MAX_MESSAGE as u32,
            device_features: request.host_features & V1_FEATURES,
        };
        self.ok_response(frame, response.encode().expect("hello encodes"))
    }

    fn handle_device_info(&mut self, frame: &Frame) -> Vec<u8> {
        let info = DeviceInfo {
            firmware_semver: "1.0.0".to_owned(),
            build_id: "fake-abc123".to_owned(),
            board_id: "FakeDevice".to_owned(),
            serial: "20260723".to_owned(),
        };
        self.ok_response(frame, info.encode().expect("info encodes"))
    }

    fn handle_capabilities(&mut self, frame: &Frame) -> Vec<u8> {
        let caps = Capabilities {
            cap_generation: 1,
            max_message: MAX_MESSAGE as u32,
            max_rx_batch: 64,
            tx_depth: 32,
            tick_hz: 1_000_000,
            tick_resolution_ns: 1000,
            boot_epoch: 0x1122_3344_5566_7788,
            outstanding_limit: 8,
            response_capacity: 8,
            event_capacity: 16,
            data_capacity: 32,
            arm_timeout_min_ms: 100,
            arm_timeout_max_ms: 60_000,
            usb_mode: 2,
            global_features: 0,
            replay_cache_entries: 8,
            tx_result_cache_entries: 16,
            replay_retention_ms: 5000,
            tag_reuse_guard_ms: 1000,
            channels: vec![ChannelCapability {
                channel: 0,
                mode_mask: 0x07,
                feature_bits: 0x0069,
                nominal_min: 10_000,
                nominal_max: 1_000_000,
                data_min: 0,
                data_max: 0,
                max_filters: 32,
            }],
        };
        self.ok_response(frame, caps.encode().expect("caps encode"))
    }

    fn diagnostics_payload(&self) -> Vec<u8> {
        let diagnostics = Diagnostics {
            generation: 1,
            session_id: self.session_id,
            response_depth: 0,
            event_depth: 0,
            data_depth: 0,
            pool_high_water: 0,
            usb_rx_bytes: 0,
            usb_tx_bytes: 0,
            channels: vec![payload_control::ChannelDiagnostics {
                channel: 0,
                state: if self.channel.mode == 0 { 0 } else { 2 },
                rx_depth: 0,
                tx_depth: 0,
                rx_frames: self.rx_frames,
                tx_frames: self.tx_frames,
                filtered: self.filtered,
                dropped: self.dropped,
                bus_off_count: 0,
                error_count: 0,
            }],
        };
        diagnostics.encode().expect("diagnostics encode")
    }

    fn handle_diagnostics(&mut self, frame: &Frame) -> Vec<u8> {
        self.ok_response(frame, self.diagnostics_payload())
    }

    fn handle_reset_diagnostics(&mut self, frame: &Frame) -> Vec<u8> {
        let Ok(request) = ResetDiagnosticsRequest::decode(&frame.payload) else {
            return self.error_response(frame, STATUS_INVALID_ARGUMENT, 0, 0, 0);
        };
        if request.mask & 0x0002 != 0 {
            self.rx_frames = 0;
            self.tx_frames = 0;
            self.filtered = 0;
            self.dropped = 0;
        }
        self.ok_response(frame, self.diagnostics_payload())
    }

    fn handle_session_state(&mut self, frame: &Frame) -> Vec<u8> {
        let state = SessionState {
            config_generation: self.config_generation,
            capture_generation: self.capture_generation,
            capture_state: self.capture_state,
            tx_armed: self.tx_armed,
            arm_epoch: self.arm_epoch,
            arm_expiry_tick: self.arm_expiry_tick,
            aggregate_max_frames_per_s: self.aggregate_max_frames_per_s,
            filters: vec![payload_control::FilterState {
                channel: 0,
                filter_generation: self.channel.filter_generation,
                filter_crc32c: self.channel.filter_crc,
            }],
        };
        self.ok_response(frame, state.encode().expect("session state encodes"))
    }

    /// Cancel pending TX and drop the armed state (spec 5.2/11: config changes
    /// must not let a stale arm transmit). Used by config/filter mutations.
    fn disarm(&mut self) {
        if !self.tx_armed {
            return;
        }
        let mut emitted = Vec::new();
        for slot in self.slots.iter_mut() {
            if slot.state == TX_PENDING {
                slot.state = TX_FINAL;
                slot.final_result = TX_DISARMED;
                slot.final_tick = self.tick;
                emitted.push(slot.clone());
            }
        }
        for snapshot in emitted {
            self.emit_tx_result(&snapshot);
        }
        self.tx_armed = false;
        self.arm_expiry_tick = 0;
        self.arm_epoch = self.arm_epoch.wrapping_add(1).max(1);
        if self.arm_epoch == 0 {
            self.arm_epoch = 1;
        }
    }

    fn handle_config_channel(&mut self, frame: &Frame) -> Vec<u8> {
        let Ok(request) = ChannelConfig::decode(&frame.payload) else {
            return self.error_response(frame, STATUS_INVALID_ARGUMENT, 0, 0, 0);
        };
        if request.generation != self.config_generation {
            return self.error_response(
                frame,
                STATUS_BAD_STATE,
                0x0002, /* STATE_QUERY_REQUIRED */
                request.generation,
                self.config_generation,
            );
        }
        self.disarm();
        self.channel.mode = request.mode;
        self.channel.flags = request.flags;
        self.channel.nominal_bps = request.nominal_bps;
        self.channel.data_bps = request.data_bps;
        self.channel.sample_permille = request.sample_permille;
        self.config_generation = self.config_generation.wrapping_add(1).max(1);
        let mut applied = request;
        applied.generation = self.config_generation;
        self.emit_channel_state();
        self.ok_response(frame, applied.encode().expect("config encodes"))
    }

    fn handle_get_channel_config(&mut self, frame: &Frame) -> Vec<u8> {
        let Ok(request) = GetChannelConfigRequest::decode(&frame.payload) else {
            return self.error_response(frame, STATUS_INVALID_ARGUMENT, 0, 0, 0);
        };
        let current = ChannelConfig {
            channel: request.channel,
            mode: self.channel.mode,
            flags: self.channel.flags,
            nominal_bps: self.channel.nominal_bps,
            data_bps: self.channel.data_bps,
            sample_permille: self.channel.sample_permille,
            generation: self.config_generation,
        };
        self.ok_response(frame, current.encode().expect("config encodes"))
    }

    fn handle_capture(&mut self, frame: &Frame, state: u8) -> Vec<u8> {
        let Ok(request) = CaptureRequest::decode(&frame.payload) else {
            return self.error_response(frame, STATUS_INVALID_ARGUMENT, 0, 0, 0);
        };
        if request.expected_generation != self.config_generation {
            return self.error_response(
                frame,
                STATUS_BAD_STATE,
                0x0002,
                request.expected_generation,
                self.config_generation,
            );
        }
        self.config_generation = self.config_generation.wrapping_add(1).max(1);
        self.capture_state = state;
        self.capture_generation = self.config_generation;
        let response = CaptureResponse {
            applied_generation: self.config_generation,
            state: state as u32,
        };
        self.ok_response(frame, response.encode().expect("capture encodes"))
    }

    fn handle_set_filters(&mut self, frame: &Frame) -> Vec<u8> {
        let Ok(request) = SetFiltersRequest::decode(&frame.payload) else {
            return self.error_response(frame, STATUS_INVALID_ARGUMENT, 0, 0, 0);
        };
        if request.expected_generation != self.config_generation {
            return self.error_response(
                frame,
                STATUS_BAD_STATE,
                0x0002,
                request.expected_generation,
                self.config_generation,
            );
        }
        self.disarm();
        self.config_generation = self.config_generation.wrapping_add(1).max(1);
        self.channel.filters = request.rules.clone();
        self.channel.filter_generation = self.config_generation;
        self.channel.filter_crc = filter_crc32c(&request.rules);
        let response = SetFiltersResponse {
            applied_generation: self.config_generation,
            applied_count: request.rules.len() as u16,
        };
        self.ok_response(frame, response.encode().expect("filters encode"))
    }

    fn handle_clear_filters(&mut self, frame: &Frame) -> Vec<u8> {
        let Ok(request) = ClearFiltersRequest::decode(&frame.payload) else {
            return self.error_response(frame, STATUS_INVALID_ARGUMENT, 0, 0, 0);
        };
        if request.expected_generation != self.config_generation {
            return self.error_response(
                frame,
                STATUS_BAD_STATE,
                0x0002,
                request.expected_generation,
                self.config_generation,
            );
        }
        self.disarm();
        self.config_generation = self.config_generation.wrapping_add(1).max(1);
        self.channel.filters.clear();
        self.channel.filter_generation = self.config_generation;
        self.channel.filter_crc = 0;
        let response = ClearFiltersResponse {
            applied_generation: self.config_generation,
        };
        self.ok_response(frame, response.encode().expect("filters encode"))
    }

    fn handle_tx_arm(&mut self, frame: &Frame) -> Vec<u8> {
        let Ok(request) = TxArmRequest::decode(&frame.payload) else {
            return self.error_response(frame, STATUS_INVALID_ARGUMENT, 0, 0, 0);
        };
        if request.expected_config_generation != self.config_generation {
            return self.error_response(
                frame,
                STATUS_BAD_STATE,
                0x0002,
                request.expected_config_generation,
                self.config_generation,
            );
        }
        self.config_generation = self.config_generation.wrapping_add(1).max(1);
        self.aggregate_max_frames_per_s = request.max_frames_per_s;
        self.max_bus_load_permille = request.max_bus_load_permille;
        self.rule_capacity = request
            .rules
            .iter()
            .map(|rule| (rule.max_frames_per_s / 10).clamp(1, 32) as u64)
            .collect();
        self.rule_tokens = self.rule_capacity.clone();
        self.rule_last_tick = vec![self.tick; request.rules.len()];
        self.agg_capacity = (request.max_frames_per_s / 10).max(1) as u64;
        self.agg_tokens = self.agg_capacity;
        self.agg_last_tick = self.tick;
        self.arm_epoch = self.arm_epoch.wrapping_add(1).max(1);
        if self.arm_epoch == 0 {
            self.arm_epoch = 1;
        }
        self.tx_armed = true;
        self.arm_expiry_tick = self.tick + request.timeout_ms as u64 * 1000;
        let response = TxArmResponse {
            applied_config_generation: self.config_generation,
            arm_epoch: self.arm_epoch,
            expiry_tick: self.arm_expiry_tick,
        };
        self.ok_response(frame, response.encode().expect("arm encodes"))
    }

    fn handle_tx_disarm(&mut self, frame: &Frame) -> Vec<u8> {
        let Ok(request) = TxDisarmRequest::decode(&frame.payload) else {
            return self.error_response(frame, STATUS_INVALID_ARGUMENT, 0, 0, 0);
        };
        if request.expected_config_generation != self.config_generation {
            return self.error_response(
                frame,
                STATUS_BAD_STATE,
                0x0002,
                request.expected_config_generation,
                self.config_generation,
            );
        }
        if !self.tx_armed || request.arm_epoch != self.arm_epoch {
            return self.error_response(
                frame,
                STATUS_BAD_STATE,
                0x0002,
                request.arm_epoch,
                self.arm_epoch,
            );
        }
        let mut cancelled = 0u32;
        let mut disarmed = Vec::new();
        for (index, slot) in self.slots.iter_mut().enumerate() {
            if slot.state == TX_PENDING {
                slot.state = TX_FINAL;
                slot.final_result = TX_DISARMED;
                slot.final_tick = self.tick;
                cancelled += 1;
                disarmed.push(index);
            }
        }
        for index in disarmed {
            let slot = self.slots[index].clone();
            self.emit_tx_result(&slot);
        }
        self.config_generation = self.config_generation.wrapping_add(1).max(1);
        self.arm_epoch = self.arm_epoch.wrapping_add(1).max(1);
        if self.arm_epoch == 0 {
            self.arm_epoch = 1;
        }
        self.tx_armed = false;
        self.arm_expiry_tick = 0;
        let response = TxDisarmResponse {
            applied_config_generation: self.config_generation,
            new_arm_epoch: self.arm_epoch,
            cancelled_count: cancelled,
        };
        self.ok_response(frame, response.encode().expect("disarm encodes"))
    }

    fn refill_tokens(&mut self, rule_index: usize) {
        let elapsed = self.tick - self.rule_last_tick[rule_index];
        let fill = self.rule_capacity[rule_index] * 10; /* capacity = fill/10 */
        let added = if elapsed >= 1_000_000 {
            self.rule_capacity[rule_index]
        } else {
            (fill * elapsed / 1_000_000).min(self.rule_capacity[rule_index])
        };
        self.rule_tokens[rule_index] = self.rule_tokens[rule_index]
            .saturating_add(added)
            .min(self.rule_capacity[rule_index]);
        self.rule_last_tick[rule_index] = self.tick;
    }

    fn refill_agg(&mut self) {
        let elapsed = self.tick - self.agg_last_tick;
        let fill = self.agg_capacity * 10;
        let added = if elapsed >= 1_000_000 {
            self.agg_capacity
        } else {
            (fill * elapsed / 1_000_000).min(self.agg_capacity)
        };
        self.agg_tokens = self.agg_tokens.saturating_add(added).min(self.agg_capacity);
        self.agg_last_tick = self.tick;
    }

    fn find_slot(&self, client_tag: u32, arm_epoch: u32) -> Option<usize> {
        self.slots
            .iter()
            .position(|slot| slot.client_tag == client_tag && slot.arm_epoch == arm_epoch)
    }

    fn handle_can_tx(&mut self, frame: &Frame) -> Vec<u8> {
        let Ok(request) = CanTxRequest::decode(&frame.payload) else {
            return self.error_response(frame, STATUS_INVALID_ARGUMENT, 0, 0, 0);
        };
        if !self.tx_armed {
            return self.error_response(frame, STATUS_BAD_STATE, 0x0002, 0, 0);
        }
        if request.arm_epoch != self.arm_epoch {
            return self.error_response(
                frame,
                STATUS_BAD_STATE,
                0x0002,
                request.arm_epoch,
                self.arm_epoch,
            );
        }
        if request.deadline_tick != 0 && request.deadline_tick <= self.tick {
            return self.error_response(frame, STATUS_TIMEOUT, 0, 0, 0);
        }
        if let Some(index) = self.find_slot(request.client_tag, request.arm_epoch) {
            let slot = &self.slots[index];
            let same = slot.payload == request.payload
                && slot.dlc == request.dlc
                && slot.can_flags == request.can_flags;
            if !same {
                return self.error_response(frame, STATUS_INVALID_ARGUMENT, 0, 0, 0);
            }
            let response = CanTxResponse {
                client_tag: slot.client_tag,
                queue_generation: 1,
                tx_state: slot.state as u16,
                final_result: slot.final_result,
                final_tick: slot.final_tick,
                can_error: slot.can_error,
            };
            return self.ok_response(frame, response.encode().expect("ledger encodes"));
        }
        if self.slots.len() >= 16 {
            return self.error_response(frame, STATUS_NO_RESOURCE, 0x0001, 0, 0);
        }
        if self.force_busy {
            return self.error_response(frame, STATUS_BUSY, 0x0001, 0, 0);
        }
        if self.rule_tokens.is_empty() {
            return self.error_response(frame, STATUS_INVALID_ARGUMENT, 0, 0, 0);
        }
        self.refill_tokens(0);
        self.refill_agg();
        if self.rule_tokens[0] < 1 || self.agg_tokens < 1 {
            return self.error_response(frame, STATUS_BUSY, 0x0001, 0, 0);
        }
        self.rule_tokens[0] -= 1;
        self.agg_tokens -= 1;
        let completion_tick = self.tick + self.tx_delay_ticks;
        self.slots.push(TxSlot {
            client_tag: request.client_tag,
            arm_epoch: request.arm_epoch,
            can_flags: request.can_flags,
            dlc: request.dlc,
            payload: request.payload.clone(),
            state: TX_PENDING,
            final_result: 0,
            final_tick: 0,
            can_error: 0,
            completion_tick,
            deadline_tick: request.deadline_tick,
        });
        let response = CanTxResponse {
            client_tag: request.client_tag,
            queue_generation: 1,
            tx_state: TX_PENDING as u16,
            final_result: 0,
            final_tick: 0,
            can_error: 0,
        };
        self.ok_response(frame, response.encode().expect("tx encodes"))
    }

    fn handle_can_tx_cancel(&mut self, frame: &Frame) -> Vec<u8> {
        let Ok(request) = CanTxCancelRequest::decode(&frame.payload) else {
            return self.error_response(frame, STATUS_INVALID_ARGUMENT, 0, 0, 0);
        };
        let state = match self.find_slot(request.client_tag, request.arm_epoch) {
            None => 3, /* NOT_FOUND */
            Some(index) => {
                let slot = &mut self.slots[index];
                if slot.state == TX_FINAL {
                    2 /* ALREADY_COMPLETE */
                } else {
                    slot.state = TX_FINAL;
                    slot.final_result = TX_CANCELLED;
                    slot.final_tick = self.tick;
                    let snapshot = slot.clone();
                    self.emit_tx_result(&snapshot);
                    1 /* CANCELLED */
                }
            }
        };
        let response = CanTxCancelResponse {
            client_tag: request.client_tag,
            cancel_state: state,
        };
        self.ok_response(frame, response.encode().expect("cancel encodes"))
    }

    fn handle_ping(&mut self, frame: &Frame) -> Vec<u8> {
        let Ok(request) = PingRequest::decode(&frame.payload) else {
            return self.error_response(frame, STATUS_INVALID_ARGUMENT, 0, 0, 0);
        };
        let response = PingResponse {
            host_send_ns: request.host_send_ns,
            device_rx_tick: self.tick,
            device_tx_tick: self.tick,
            sample_id: request.sample_id,
        };
        self.ok_response(frame, response.encode())
    }
}

impl Default for FakeDevice {
    fn default() -> Self {
        Self::new()
    }
}

/// CRC-32C over canonical little-endian filter records (spec 5.1).
fn filter_crc32c(rules: &[FilterRule]) -> u32 {
    let mut canonical = Vec::new();
    for rule in rules {
        canonical.extend(rule.id.to_le_bytes());
        canonical.extend(rule.mask.to_le_bytes());
        canonical.extend(rule.flags.to_le_bytes());
        canonical.extend([0u8; 2]);
    }
    hpm_usb_can_protocol::crc32c(&canonical)
}

/// [`Transport`] over an in-memory [`FakeDevice`].
pub struct FakeTransport {
    device: FakeDevice,
    delivery: VecDeque<Vec<u8>>,
    pending_frames: VecDeque<Frame>,
    decoder: StreamDecoder,
    id: String,
    /// When non-zero, encoded outputs are delivered in fragments of this size
    /// to exercise transport reassembly (spec section 12.2).
    chunk_size: usize,
}

impl FakeTransport {
    pub fn new(device: FakeDevice) -> Self {
        Self {
            device,
            delivery: VecDeque::new(),
            pending_frames: VecDeque::new(),
            decoder: StreamDecoder::new(MAX_MESSAGE),
            id: "fake:0".to_owned(),
            chunk_size: 0,
        }
    }

    /// Deliver encoded outputs fragmented into `chunk_size` byte pieces.
    pub fn with_chunk_size(mut self, chunk_size: usize) -> Self {
        self.chunk_size = chunk_size;
        self
    }

    pub fn device(&self) -> &FakeDevice {
        &self.device
    }

    pub fn device_mut(&mut self) -> &mut FakeDevice {
        &mut self.device
    }

    /// Advance the fake device clock (completes TX, expires arms).
    pub fn tick(&mut self, ticks: u64) {
        self.device.tick(ticks);
    }

    /// Simulate a ring overflow and emit a DATA_LOSS notice.
    pub fn inject_loss(&mut self) {
        self.device.inject_loss();
    }
}

impl Transport for FakeTransport {
    fn device_id(&self) -> &str {
        &self.id
    }

    fn write_frame(&mut self, frame: &Frame) -> Result<(), TransportError> {
        if let Some(response) = self.device.process_request(frame)? {
            self.delivery.push_back(response);
        }
        Ok(())
    }

    fn read_frame(&mut self, _timeout: Duration) -> Result<Frame, TransportError> {
        loop {
            if let Some(frame) = self.pending_frames.pop_front() {
                return Ok(frame);
            }
            if let Some(chunk) = self.delivery.pop_front() {
                self.pending_frames.extend(self.decoder.push(&chunk));
                continue;
            }
            if let Some(output) = self.device.next_output() {
                match self.chunk_size {
                    0 => self.delivery.push_back(output),
                    size => {
                        self.delivery
                            .extend(output.chunks(size).map(|part| part.to_vec()));
                    }
                }
                continue;
            }
            return Err(TransportError::Timeout);
        }
    }

    fn reset(&mut self) -> Result<(), TransportError> {
        self.device.reset();
        self.delivery.clear();
        self.pending_frames.clear();
        self.decoder = StreamDecoder::new(MAX_MESSAGE);
        Ok(())
    }
}

/// Decode a frame from raw bytes (test helper).
pub fn decode_frame(bytes: &[u8]) -> Frame {
    decode(bytes, MAX_MESSAGE).expect("frame decodes")
}

/// Build a request frame (test helper).
pub fn request(message_type: u16, sequence: u32, payload: Vec<u8>) -> Frame {
    Frame::request(message_type, sequence, payload)
}
