//! Host-core regression flows against the fake device backend. These are the
//! same protocol-level flows the libusb backend will run on hardware
//! (fake-backend parity gate, scope addendum 2026-08-03).

use std::time::Duration;

use hpm_usb_can_core::fake::{FakeDevice, FakeTransport, MAX_MESSAGE, request};
use hpm_usb_can_core::{Transport, TransportError};
use hpm_usb_can_protocol::payload::{Capabilities, HelloRequest, HelloResponse, PingResponse};
use hpm_usb_can_protocol::payload_control::{
    self, CanTxCancelRequest, CanTxCancelResponse, CanTxRequest, CanTxResponse, CaptureRequest,
    CaptureResponse, ChannelConfig, ClearFiltersRequest, ClearFiltersResponse, FilterRule,
    ResetDiagnosticsRequest, SetFiltersRequest, SetFiltersResponse, TxArmRequest, TxArmResponse,
    TxDisarmRequest, TxDisarmResponse,
};
use hpm_usb_can_protocol::payload_events::{CanRxBatch, CanTxResultEvent, DataLossEvent};
use hpm_usb_can_protocol::{Frame, flags, msg};

const ZERO: Duration = Duration::ZERO;

fn seq(counter: &mut u32) -> u32 {
    let value = *counter;
    *counter = counter.wrapping_add(1);
    value
}

fn read_ok(transport: &mut FakeTransport) -> Frame {
    let frame = transport.read_frame(ZERO).expect("frame arrives");
    assert_eq!(
        frame.flags & flags::ERROR,
        0,
        "unexpected error status {}",
        frame.status
    );
    frame
}

fn expect_error(transport: &mut FakeTransport, status: u16) -> Frame {
    let frame = transport.read_frame(ZERO).expect("error frame arrives");
    assert_ne!(frame.flags & flags::ERROR, 0, "expected error response");
    assert_eq!(frame.status, status);
    frame
}

fn hello_request(counter: &mut u32) -> Frame {
    let payload = HelloRequest {
        min_major: 1,
        max_major: 1,
        min_minor: 0,
        max_minor: 0,
        host_max_message: MAX_MESSAGE as u32,
        host_features: 0,
    }
    .encode()
    .unwrap();
    request(msg::HELLO, seq(counter), payload)
}

fn config_request(counter: &mut u32, generation: u32, mode: u8) -> Frame {
    let payload = ChannelConfig {
        channel: 0,
        mode,
        flags: 0,
        nominal_bps: 500_000,
        data_bps: 0,
        sample_permille: 875,
        generation,
    }
    .encode()
    .unwrap();
    request(msg::CONFIG_CHANNEL, seq(counter), payload)
}

fn arm_request(counter: &mut u32, generation: u32, rate: u32) -> Frame {
    let rule = payload_control::TxRule {
        channel: 0,
        allowed_flag_mask: 0x0f,
        id: 0x123,
        id_mask: 0x7ff,
        max_frames_per_s: rate,
    };
    let payload = TxArmRequest {
        expected_config_generation: generation,
        timeout_ms: 5000,
        max_frames_per_s: 1000,
        max_bus_load_permille: 900,
        rules: vec![rule],
    }
    .encode()
    .unwrap();
    request(msg::TX_ARM, seq(counter), payload)
}

/// Apply a channel config and drain the asynchronous CHANNEL_STATE notice the
/// device emits after every successful config (real async-event behaviour).
fn apply_config(transport: &mut FakeTransport, counter: &mut u32, generation: u32, mode: u8) {
    transport
        .write_frame(&config_request(counter, generation, mode))
        .unwrap();
    let response = read_ok(transport);
    assert_eq!(response.message_type, msg::CONFIG_CHANNEL);
    let event = read_ok(transport);
    assert_eq!(event.message_type, msg::CHANNEL_STATE);
}

fn can_tx_request(counter: &mut u32, tag: u32, epoch: u32) -> Frame {
    let payload = CanTxRequest {
        channel: 0,
        dlc: 4,
        can_flags: 0,
        id: 0x123,
        arm_epoch: epoch,
        client_tag: tag,
        deadline_tick: 0,
        payload: tag.to_le_bytes().to_vec(),
    }
    .encode()
    .unwrap();
    request(msg::CAN_TX, seq(counter), payload)
}

fn start_capture_request(counter: &mut u32, generation: u32) -> Frame {
    let payload = CaptureRequest {
        expected_generation: generation,
        flags: 0x0001,
    }
    .encode()
    .unwrap();
    request(msg::START_CAPTURE, seq(counter), payload)
}

#[test]
fn hello_negotiates_and_caps_expose_limits() {
    let mut transport = FakeTransport::new(FakeDevice::new());
    let mut counter = 1;

    transport.write_frame(&hello_request(&mut counter)).unwrap();
    let response = read_ok(&mut transport);
    assert_eq!(response.message_type, msg::HELLO);
    let hello = HelloResponse::decode(&response.payload).unwrap();
    assert_eq!((hello.major, hello.minor), (1, 0));
    assert_eq!(hello.session_id, 0x1234_5678);
    assert_eq!(hello.max_message, MAX_MESSAGE as u32);

    transport
        .write_frame(&request(msg::GET_CAPABILITIES, seq(&mut counter), vec![]))
        .unwrap();
    let response = read_ok(&mut transport);
    let caps = Capabilities::decode(&response.payload).unwrap();
    assert_eq!(caps.tick_hz, 1_000_000);
    assert_eq!(caps.channels.len(), 1);
    assert_eq!(caps.channels[0].max_filters, 32);
    assert_eq!(
        (caps.arm_timeout_min_ms, caps.arm_timeout_max_ms),
        (100, 60_000)
    );
}

#[test]
fn incompatible_version_is_rejected() {
    let mut transport = FakeTransport::new(FakeDevice::new());
    let payload = HelloRequest {
        min_major: 2,
        max_major: 2,
        min_minor: 0,
        max_minor: 0,
        host_max_message: 4096,
        host_features: 0,
    }
    .encode()
    .unwrap();
    transport
        .write_frame(&request(msg::HELLO, 1, payload))
        .unwrap();
    expect_error(&mut transport, 3 /* INCOMPATIBLE_VERSION */);
}

#[test]
fn config_cas_rejects_stale_then_applies() {
    let mut transport = FakeTransport::new(FakeDevice::new());
    let mut counter = 1;

    transport.write_frame(&hello_request(&mut counter)).unwrap();
    read_ok(&mut transport);

    transport
        .write_frame(&config_request(&mut counter, 99, 2))
        .unwrap();
    expect_error(&mut transport, 4 /* BAD_STATE */);

    transport
        .write_frame(&config_request(&mut counter, 1, 2))
        .unwrap();
    let response = read_ok(&mut transport);
    let applied = ChannelConfig::decode(&response.payload).unwrap();
    assert_eq!(applied.generation, 2);
    assert_eq!(applied.mode, 2);

    // Session state confirms the applied generation.
    transport
        .write_frame(&request(msg::GET_SESSION_STATE, seq(&mut counter), vec![]))
        .unwrap();
    let response = read_ok(&mut transport);
    let state = payload_control::SessionState::decode(&response.payload).unwrap();
    assert_eq!(state.config_generation, 2);
}

#[test]
fn arm_tx_result_is_exactly_once() {
    let mut transport = FakeTransport::new(FakeDevice::new());
    let mut counter = 1;
    transport.write_frame(&hello_request(&mut counter)).unwrap();
    read_ok(&mut transport);
    apply_config(&mut transport, &mut counter, 1, 2);

    transport
        .write_frame(&arm_request(&mut counter, 2, 500))
        .unwrap();
    let response = read_ok(&mut transport);
    let arm = TxArmResponse::decode(&response.payload).unwrap();
    assert_eq!(arm.arm_epoch, 2);
    assert!(transport.device().tx_armed());

    transport
        .write_frame(&can_tx_request(&mut counter, 7, 2))
        .unwrap();
    let response = read_ok(&mut transport);
    let snapshot = CanTxResponse::decode(&response.payload).unwrap();
    assert_eq!(snapshot.tx_state, 1); // PENDING
    assert_eq!(snapshot.final_result, 0);

    // Replay reads the ledger, still PENDING, without a second TX.
    transport
        .write_frame(&can_tx_request(&mut counter, 7, 2))
        .unwrap();
    let response = read_ok(&mut transport);
    let snapshot = CanTxResponse::decode(&response.payload).unwrap();
    assert_eq!(snapshot.tx_state, 1);
    assert_eq!(transport.device().tx_frames(), 0);

    // Simulated transmission completes -> exactly one CAN_TX_RESULT.
    transport.tick(1000);
    let event = read_ok(&mut transport);
    assert_eq!(event.message_type, msg::CAN_TX_RESULT);
    let result = CanTxResultEvent::decode(&event.payload).unwrap();
    assert_eq!(result.result, 1); // SENT
    assert_eq!(result.client_tag, 7);
    assert_eq!(transport.device().tx_frames(), 1);

    // Replay now returns the FINAL ledger snapshot.
    transport
        .write_frame(&can_tx_request(&mut counter, 7, 2))
        .unwrap();
    let response = read_ok(&mut transport);
    let snapshot = CanTxResponse::decode(&response.payload).unwrap();
    assert_eq!(snapshot.tx_state, 2);
    assert_eq!(snapshot.final_result, 1);
}

#[test]
fn capture_streams_monotonic_batches() {
    let mut transport = FakeTransport::new(FakeDevice::new());
    let mut counter = 1;
    transport.write_frame(&hello_request(&mut counter)).unwrap();
    read_ok(&mut transport);
    apply_config(&mut transport, &mut counter, 1, 2);

    transport
        .write_frame(&start_capture_request(&mut counter, 2))
        .unwrap();
    let response = read_ok(&mut transport);
    let capture = CaptureResponse::decode(&response.payload).unwrap();
    assert_eq!(capture.state, 1);

    let mut previous = 0u32;
    for _ in 0..5 {
        let event = read_ok(&mut transport);
        assert_eq!(event.message_type, msg::CAN_RX_BATCH);
        let batch = CanRxBatch::decode(&event.payload).unwrap();
        assert_eq!(batch.records.len(), 1);
        assert!(batch.records[0].channel_sequence > previous);
        previous = batch.records[0].channel_sequence;
    }
    assert_eq!(transport.device().rx_frames(), 5);

    // Stop capture: reads now time out instead of streaming.
    let stop = CaptureRequest {
        expected_generation: 3,
        flags: 0x0001,
    }
    .encode()
    .unwrap();
    transport
        .write_frame(&request(msg::STOP_CAPTURE, seq(&mut counter), stop))
        .unwrap();
    read_ok(&mut transport);
    assert_eq!(transport.read_frame(ZERO), Err(TransportError::Timeout));
}

#[test]
fn filters_apply_and_clear_with_cas() {
    let mut transport = FakeTransport::new(FakeDevice::new());
    let mut counter = 1;
    transport.write_frame(&hello_request(&mut counter)).unwrap();
    read_ok(&mut transport);
    apply_config(&mut transport, &mut counter, 1, 2);

    let set = SetFiltersRequest {
        channel: 0,
        expected_generation: 2,
        rules: vec![FilterRule {
            id: 0x123,
            mask: 0x7ff,
            flags: 0,
        }],
    }
    .encode()
    .unwrap();
    transport
        .write_frame(&request(msg::SET_FILTERS, seq(&mut counter), set))
        .unwrap();
    let response = read_ok(&mut transport);
    let applied = SetFiltersResponse::decode(&response.payload).unwrap();
    assert_eq!((applied.applied_generation, applied.applied_count), (3, 1));

    let clear = ClearFiltersRequest {
        channel: 0,
        expected_generation: 3,
    }
    .encode()
    .unwrap();
    transport
        .write_frame(&request(msg::CLEAR_FILTERS, seq(&mut counter), clear))
        .unwrap();
    let response = read_ok(&mut transport);
    let cleared = ClearFiltersResponse::decode(&response.payload).unwrap();
    assert_eq!(cleared.applied_generation, 4);
}

#[test]
fn replay_cache_returns_same_response_without_side_effect() {
    let mut transport = FakeTransport::new(FakeDevice::new());
    let mut counter = 1;
    transport.write_frame(&hello_request(&mut counter)).unwrap();
    read_ok(&mut transport);

    let request_frame = config_request(&mut counter, 1, 2);
    transport.write_frame(&request_frame).unwrap();
    let first = read_ok(&mut transport);
    assert_eq!(transport.device().config_generation(), 2);

    // Byte-identical replay at the same sequence: cached response, no advance.
    transport.write_frame(&request_frame).unwrap();
    let replayed = read_ok(&mut transport);
    assert_eq!(first.payload, replayed.payload);
    assert_eq!(transport.device().config_generation(), 2);

    // Different bytes at the same sequence: BAD_STATE, no side effect.
    let mut conflicting = config_request(&mut counter, 1, 2);
    conflicting.payload[1] = 3; // different mode byte
    transport.write_frame(&conflicting).unwrap();
    expect_error(&mut transport, 4 /* BAD_STATE */);
    assert_eq!(transport.device().config_generation(), 2);
}

#[test]
fn reset_requires_renegotiation() {
    let mut transport = FakeTransport::new(FakeDevice::new());
    let mut counter = 1;
    transport.write_frame(&hello_request(&mut counter)).unwrap();
    let first = read_ok(&mut transport);
    let first_session = HelloResponse::decode(&first.payload).unwrap().session_id;
    transport
        .write_frame(&config_request(&mut counter, 1, 2))
        .unwrap();
    read_ok(&mut transport);

    transport.reset().unwrap();
    assert_eq!(transport.device().config_generation(), 1);

    // The old session config is gone; the new session id differs.
    transport.write_frame(&hello_request(&mut counter)).unwrap();
    let second = read_ok(&mut transport);
    let second_session = HelloResponse::decode(&second.payload).unwrap().session_id;
    assert_ne!(first_session, second_session);

    // Config must restart from generation 1 under the new session.
    transport
        .write_frame(&config_request(&mut counter, 1, 2))
        .unwrap();
    read_ok(&mut transport);
}

#[test]
fn tx_cancel_and_disarm_lifecycle() {
    let mut transport = FakeTransport::new(FakeDevice::new());
    let mut counter = 1;
    transport.write_frame(&hello_request(&mut counter)).unwrap();
    read_ok(&mut transport);
    apply_config(&mut transport, &mut counter, 1, 2);
    transport
        .write_frame(&arm_request(&mut counter, 2, 500))
        .unwrap();
    read_ok(&mut transport);

    // Cancel a pending TX -> CANCELLED + result event.
    transport
        .write_frame(&can_tx_request(&mut counter, 42, 2))
        .unwrap();
    let response = read_ok(&mut transport);
    assert_eq!(
        CanTxResponse::decode(&response.payload).unwrap().tx_state,
        1
    );
    let cancel = CanTxCancelRequest {
        arm_epoch: 2,
        client_tag: 42,
    }
    .encode()
    .unwrap();
    transport
        .write_frame(&request(msg::CAN_TX_CANCEL, seq(&mut counter), cancel))
        .unwrap();
    let response = read_ok(&mut transport);
    assert_eq!(
        CanTxCancelResponse::decode(&response.payload)
            .unwrap()
            .cancel_state,
        1 // CANCELLED
    );
    let event = read_ok(&mut transport);
    assert_eq!(event.message_type, msg::CAN_TX_RESULT);

    // Second cancel is idempotent: ALREADY_COMPLETE.
    let cancel = CanTxCancelRequest {
        arm_epoch: 2,
        client_tag: 42,
    }
    .encode()
    .unwrap();
    transport
        .write_frame(&request(msg::CAN_TX_CANCEL, seq(&mut counter), cancel))
        .unwrap();
    let response = read_ok(&mut transport);
    assert_eq!(
        CanTxCancelResponse::decode(&response.payload)
            .unwrap()
            .cancel_state,
        2 // ALREADY_COMPLETE
    );

    // Unknown tag -> NOT_FOUND.
    let cancel = CanTxCancelRequest {
        arm_epoch: 2,
        client_tag: 999,
    }
    .encode()
    .unwrap();
    transport
        .write_frame(&request(msg::CAN_TX_CANCEL, seq(&mut counter), cancel))
        .unwrap();
    let response = read_ok(&mut transport);
    assert_eq!(
        CanTxCancelResponse::decode(&response.payload)
            .unwrap()
            .cancel_state,
        3 // NOT_FOUND
    );

    // Disarm with a pending frame: cancelled_count reflects the flush.
    transport
        .write_frame(&can_tx_request(&mut counter, 43, 2))
        .unwrap();
    read_ok(&mut transport);
    let disarm = TxDisarmRequest {
        expected_config_generation: 3,
        arm_epoch: 2,
        reason: 1, // HOST
    }
    .encode()
    .unwrap();
    transport
        .write_frame(&request(msg::TX_DISARM, seq(&mut counter), disarm))
        .unwrap();
    let response = read_ok(&mut transport);
    let disarm = TxDisarmResponse::decode(&response.payload).unwrap();
    assert_eq!(disarm.cancelled_count, 1);
    assert!(!transport.device().tx_armed());
}

#[test]
fn token_bucket_rejects_then_refills() {
    let mut transport = FakeTransport::new(FakeDevice::new());
    let mut counter = 1;
    transport.write_frame(&hello_request(&mut counter)).unwrap();
    read_ok(&mut transport);
    apply_config(&mut transport, &mut counter, 1, 2);
    // Rule rate 2 -> capacity 1 token.
    transport
        .write_frame(&arm_request(&mut counter, 2, 2))
        .unwrap();
    read_ok(&mut transport);

    transport
        .write_frame(&can_tx_request(&mut counter, 1, 2))
        .unwrap();
    read_ok(&mut transport);
    transport
        .write_frame(&can_tx_request(&mut counter, 2, 2))
        .unwrap();
    expect_error(&mut transport, 5 /* BUSY */);

    // One simulated second refills the bucket.
    transport.tick(1_000_000);
    transport
        .write_frame(&can_tx_request(&mut counter, 2, 2))
        .unwrap();
    read_ok(&mut transport);
}

#[test]
fn diagnostics_counters_track_capture() {
    let mut transport = FakeTransport::new(FakeDevice::new());
    let mut counter = 1;
    transport.write_frame(&hello_request(&mut counter)).unwrap();
    read_ok(&mut transport);
    apply_config(&mut transport, &mut counter, 1, 2);
    transport
        .write_frame(&start_capture_request(&mut counter, 2))
        .unwrap();
    read_ok(&mut transport);
    for _ in 0..3 {
        read_ok(&mut transport);
    }

    transport
        .write_frame(&request(msg::GET_DIAGNOSTICS, seq(&mut counter), vec![]))
        .unwrap();
    let response = read_ok(&mut transport);
    let diagnostics = payload_control::Diagnostics::decode(&response.payload).unwrap();
    assert_eq!(diagnostics.channels[0].rx_frames, 3);

    let reset = ResetDiagnosticsRequest { mask: 0x0002 }.encode().unwrap();
    transport
        .write_frame(&request(msg::RESET_DIAGNOSTICS, seq(&mut counter), reset))
        .unwrap();
    let response = read_ok(&mut transport);
    let diagnostics = payload_control::Diagnostics::decode(&response.payload).unwrap();
    assert_eq!(diagnostics.channels[0].rx_frames, 0);
}

#[test]
fn data_loss_notice_arrives() {
    let mut transport = FakeTransport::new(FakeDevice::new());
    transport.inject_loss();
    let event = read_ok(&mut transport);
    assert_eq!(event.message_type, msg::DATA_LOSS);
    let loss = DataLossEvent::decode(&event.payload).unwrap();
    assert_eq!((loss.source, loss.sequence_domain), (1, 2));
    assert_eq!(loss.dropped_count, 1);
}

#[test]
fn ping_echoes_ticks() {
    let mut counter = 0u32;
    let mut transport = FakeTransport::new(FakeDevice::new());
    transport.write_frame(&hello_request(&mut counter)).unwrap();
    let _ = read_ok(&mut transport);
    let payload = hpm_usb_can_protocol::payload::PingRequest {
        host_send_ns: 123_456_789,
        sample_id: 7,
    }
    .encode();
    transport
        .write_frame(&request(msg::PING, seq(&mut counter), payload))
        .unwrap();
    let response = read_ok(&mut transport);
    let ping = PingResponse::decode(&response.payload).unwrap();
    assert_eq!(ping.host_send_ns, 123_456_789);
    assert_eq!(ping.sample_id, 7);
    assert_eq!(ping.device_rx_tick, ping.device_tx_tick);
}

#[test]
fn fragmented_transport_reassembles_frames() {
    let mut transport = FakeTransport::new(FakeDevice::new()).with_chunk_size(7);
    let mut counter = 1;
    transport.write_frame(&hello_request(&mut counter)).unwrap();
    let response = read_ok(&mut transport);
    assert_eq!(response.message_type, msg::HELLO);

    transport
        .write_frame(&request(msg::GET_CAPABILITIES, seq(&mut counter), vec![]))
        .unwrap();
    let response = read_ok(&mut transport);
    assert_eq!(response.message_type, msg::GET_CAPABILITIES);
}

#[test]
fn usb_backend_constants_are_stable() {
    // The USB backend compiles with rusb; these structural constants must stay
    // aligned with the firmware descriptor and hpm-usb-smoke.
    assert_eq!(hpm_usb_can_core::usb::DEFAULT_VID, 0x34b7);
    assert_eq!(hpm_usb_can_core::usb::DEFAULT_PID, 0x1236);
    assert_eq!(hpm_usb_can_core::usb::EP_OUT, 0x01);
    assert_eq!(hpm_usb_can_core::usb::EP_IN, 0x81);
}
