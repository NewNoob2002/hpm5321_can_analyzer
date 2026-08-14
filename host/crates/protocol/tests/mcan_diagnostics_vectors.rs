use hpm_usb_can_protocol::payload_control::McanDiagnostics;
use hpm_usb_can_protocol::{decode, flags, msg};

const MAX_MESSAGE: usize = 65_536;

fn parse_hex(source: &str) -> Vec<u8> {
    source
        .split_whitespace()
        .map(|octet| u8::from_str_radix(octet, 16).expect("valid hex octet"))
        .collect()
}

#[test]
fn get_mcan_diagnostics_vectors_have_byte_parity() {
    let request_bytes = parse_hex(include_str!(
        "../../../../protocol/v1/0/get-mcan-diagnostics-request.hex"
    ));
    let request = decode(&request_bytes, MAX_MESSAGE).unwrap();
    assert_eq!(request.flags, flags::REQUEST);
    assert_eq!(request.message_type, msg::GET_MCAN_DIAGNOSTICS);
    assert_eq!(request.sequence, 17);
    assert!(request.payload.is_empty());
    assert_eq!(request.encode(MAX_MESSAGE).unwrap(), request_bytes);

    let response_bytes = parse_hex(include_str!(
        "../../../../protocol/v1/0/get-mcan-diagnostics-response.hex"
    ));
    let response = decode(&response_bytes, MAX_MESSAGE).unwrap();
    assert_eq!(response.flags, flags::RESPONSE);
    assert_eq!(response.message_type, msg::GET_MCAN_DIAGNOSTICS);
    assert_eq!(response.sequence, 17);

    let diagnostics = McanDiagnostics::decode(&response.payload).unwrap();
    assert_eq!(diagnostics.generation, 7);
    assert_eq!(diagnostics.snapshot_tick, 0x1122_3344_5566_7788);
    assert_eq!(diagnostics.rxfifo0_high_watermark, 9);
    assert_eq!(diagnostics.queue_high_watermark, 11);
    assert_eq!(diagnostics.ring_drops, 15);
    assert_eq!(diagnostics.automatic_recovery_attempts, 20);
    assert_eq!(diagnostics.encode().unwrap(), response.payload);
    assert_eq!(response.encode(MAX_MESSAGE).unwrap(), response_bytes);
}
