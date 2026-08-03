use std::fmt;

const V1_FEATURES: u32 = 0x0017;

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum PayloadError {
    InvalidLength { expected: usize, actual: usize },
    InvalidReserved,
    InvalidValue(&'static str),
    InvalidUtf8,
    StringTooLong,
    TrailingBytes,
}

impl fmt::Display for PayloadError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}

impl std::error::Error for PayloadError {}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HelloRequest {
    pub min_major: u8,
    pub max_major: u8,
    pub min_minor: u8,
    pub max_minor: u8,
    pub host_max_message: u32,
    pub host_features: u32,
}

impl HelloRequest {
    pub const LEN: usize = 12;

    pub fn encode(&self) -> Result<Vec<u8>, PayloadError> {
        if self.min_major == 0
            || self.min_major > self.max_major
            || self.min_minor > self.max_minor
            || self.host_max_message == 0
            || self.host_features & !V1_FEATURES != 0
        {
            return Err(PayloadError::InvalidValue("HELLO range"));
        }
        let mut bytes = Vec::with_capacity(Self::LEN);
        bytes.extend([
            self.min_major,
            self.max_major,
            self.min_minor,
            self.max_minor,
        ]);
        bytes.extend(self.host_max_message.to_le_bytes());
        bytes.extend(self.host_features.to_le_bytes());
        Ok(bytes)
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, PayloadError> {
        exact_len(bytes, Self::LEN)?;
        let value = Self {
            min_major: bytes[0],
            max_major: bytes[1],
            min_minor: bytes[2],
            max_minor: bytes[3],
            host_max_message: u32_at(bytes, 4),
            host_features: u32_at(bytes, 8),
        };
        value.encode()?;
        Ok(value)
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HelloResponse {
    pub major: u8,
    pub minor: u8,
    pub session_id: u32,
    pub max_message: u32,
    pub device_features: u32,
}

impl HelloResponse {
    pub const LEN: usize = 16;

    pub fn encode(&self) -> Result<Vec<u8>, PayloadError> {
        if self.major == 0
            || self.session_id == 0
            || self.max_message == 0
            || self.device_features & !V1_FEATURES != 0
        {
            return Err(PayloadError::InvalidValue("HELLO response"));
        }
        let mut bytes = Vec::with_capacity(Self::LEN);
        bytes.extend([self.major, self.minor, 0, 0]);
        bytes.extend(self.session_id.to_le_bytes());
        bytes.extend(self.max_message.to_le_bytes());
        bytes.extend(self.device_features.to_le_bytes());
        Ok(bytes)
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, PayloadError> {
        exact_len(bytes, Self::LEN)?;
        reserved_zero(&bytes[2..4])?;
        let value = Self {
            major: bytes[0],
            minor: bytes[1],
            session_id: u32_at(bytes, 4),
            max_message: u32_at(bytes, 8),
            device_features: u32_at(bytes, 12),
        };
        value.encode()?;
        Ok(value)
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DeviceInfo {
    pub firmware_semver: String,
    pub build_id: String,
    pub board_id: String,
    pub serial: String,
}

impl DeviceInfo {
    pub fn encode(&self) -> Result<Vec<u8>, PayloadError> {
        let fields = [
            self.firmware_semver.as_bytes(),
            self.build_id.as_bytes(),
            self.board_id.as_bytes(),
            self.serial.as_bytes(),
        ];
        if fields.iter().any(|field| field.len() > 64) {
            return Err(PayloadError::StringTooLong);
        }
        let mut bytes = Vec::with_capacity(8 + fields.iter().map(|v| v.len()).sum::<usize>());
        for field in fields {
            bytes.extend((field.len() as u16).to_le_bytes());
        }
        for field in fields {
            bytes.extend(field);
        }
        Ok(bytes)
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, PayloadError> {
        if bytes.len() < 8 {
            return Err(PayloadError::InvalidLength {
                expected: 8,
                actual: bytes.len(),
            });
        }
        let lengths = [
            u16_at(bytes, 0) as usize,
            u16_at(bytes, 2) as usize,
            u16_at(bytes, 4) as usize,
            u16_at(bytes, 6) as usize,
        ];
        if lengths.iter().any(|length| *length > 64) {
            return Err(PayloadError::StringTooLong);
        }
        let expected = 8 + lengths.iter().sum::<usize>();
        exact_len(bytes, expected)?;
        let mut offset = 8;
        let mut next = |length: usize| -> Result<String, PayloadError> {
            let value = std::str::from_utf8(&bytes[offset..offset + length])
                .map_err(|_| PayloadError::InvalidUtf8)?
                .to_owned();
            offset += length;
            Ok(value)
        };
        Ok(Self {
            firmware_semver: next(lengths[0])?,
            build_id: next(lengths[1])?,
            board_id: next(lengths[2])?,
            serial: next(lengths[3])?,
        })
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ChannelCapability {
    pub channel: u8,
    pub mode_mask: u8,
    pub feature_bits: u16,
    pub nominal_min: u32,
    pub nominal_max: u32,
    pub data_min: u32,
    pub data_max: u32,
    pub max_filters: u16,
}

impl ChannelCapability {
    pub const LEN: usize = 24;
    const KNOWN_MODE_MASK: u8 = 0x0f;
    const KNOWN_FEATURE_BITS: u16 = 0x007f;

    fn encode_into(&self, bytes: &mut Vec<u8>) -> Result<(), PayloadError> {
        if self.mode_mask == 0
            || self.mode_mask & !Self::KNOWN_MODE_MASK != 0
            || self.feature_bits & !Self::KNOWN_FEATURE_BITS != 0
            || self.nominal_min > self.nominal_max
            || self.data_min > self.data_max
        {
            return Err(PayloadError::InvalidValue("channel capability"));
        }
        bytes.extend([self.channel, self.mode_mask]);
        bytes.extend(self.feature_bits.to_le_bytes());
        bytes.extend(self.nominal_min.to_le_bytes());
        bytes.extend(self.nominal_max.to_le_bytes());
        bytes.extend(self.data_min.to_le_bytes());
        bytes.extend(self.data_max.to_le_bytes());
        bytes.extend(self.max_filters.to_le_bytes());
        bytes.extend([0, 0]);
        Ok(())
    }

    fn decode(bytes: &[u8]) -> Result<Self, PayloadError> {
        exact_len(bytes, Self::LEN)?;
        reserved_zero(&bytes[22..24])?;
        let value = Self {
            channel: bytes[0],
            mode_mask: bytes[1],
            feature_bits: u16_at(bytes, 2),
            nominal_min: u32_at(bytes, 4),
            nominal_max: u32_at(bytes, 8),
            data_min: u32_at(bytes, 12),
            data_max: u32_at(bytes, 16),
            max_filters: u16_at(bytes, 20),
        };
        let mut sink = Vec::new();
        value.encode_into(&mut sink)?;
        Ok(value)
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Capabilities {
    pub cap_generation: u32,
    pub max_message: u32,
    pub max_rx_batch: u32,
    pub tx_depth: u32,
    pub tick_hz: u32,
    pub tick_resolution_ns: u32,
    pub boot_epoch: u64,
    pub outstanding_limit: u16,
    pub response_capacity: u16,
    pub event_capacity: u16,
    pub data_capacity: u16,
    pub arm_timeout_min_ms: u16,
    pub arm_timeout_max_ms: u16,
    pub usb_mode: u8,
    pub global_features: u16,
    pub replay_cache_entries: u16,
    pub tx_result_cache_entries: u16,
    pub replay_retention_ms: u32,
    pub tag_reuse_guard_ms: u32,
    pub channels: Vec<ChannelCapability>,
}

impl Capabilities {
    pub const FIXED_LEN: usize = 60;
    const KNOWN_GLOBAL_FEATURES: u16 = 0x0017;

    pub fn encode(&self) -> Result<Vec<u8>, PayloadError> {
        let channel_count = u8::try_from(self.channels.len())
            .map_err(|_| PayloadError::InvalidValue("channel count"))?;
        if self.cap_generation == 0
            || self.max_message == 0
            || self.tick_hz == 0
            || self.tick_resolution_ns == 0
            || self.boot_epoch == 0
            || !matches!(self.usb_mode, 1 | 2)
            || self.global_features & !Self::KNOWN_GLOBAL_FEATURES != 0
            || self.arm_timeout_min_ms > self.arm_timeout_max_ms
            || self.channels.iter().enumerate().any(|(index, channel)| {
                self.channels[..index]
                    .iter()
                    .any(|seen| seen.channel == channel.channel)
            })
        {
            return Err(PayloadError::InvalidValue("capabilities"));
        }
        let mut bytes = Vec::with_capacity(Self::FIXED_LEN + self.channels.len() * 24);
        for value in [
            self.cap_generation,
            self.max_message,
            self.max_rx_batch,
            self.tx_depth,
            self.tick_hz,
            self.tick_resolution_ns,
        ] {
            bytes.extend(value.to_le_bytes());
        }
        bytes.extend(self.boot_epoch.to_le_bytes());
        for value in [
            self.outstanding_limit,
            self.response_capacity,
            self.event_capacity,
            self.data_capacity,
            self.arm_timeout_min_ms,
            self.arm_timeout_max_ms,
        ] {
            bytes.extend(value.to_le_bytes());
        }
        bytes.extend([channel_count, self.usb_mode]);
        bytes.extend(self.global_features.to_le_bytes());
        bytes.extend(self.replay_cache_entries.to_le_bytes());
        bytes.extend(self.tx_result_cache_entries.to_le_bytes());
        bytes.extend(self.replay_retention_ms.to_le_bytes());
        bytes.extend(self.tag_reuse_guard_ms.to_le_bytes());
        debug_assert_eq!(bytes.len(), Self::FIXED_LEN);
        for channel in &self.channels {
            channel.encode_into(&mut bytes)?;
        }
        Ok(bytes)
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, PayloadError> {
        if bytes.len() < Self::FIXED_LEN {
            return Err(PayloadError::InvalidLength {
                expected: Self::FIXED_LEN,
                actual: bytes.len(),
            });
        }
        let channel_count = bytes[44] as usize;
        exact_len(
            bytes,
            Self::FIXED_LEN + channel_count * ChannelCapability::LEN,
        )?;
        let mut channels = Vec::with_capacity(channel_count);
        for index in 0..channel_count {
            let offset = Self::FIXED_LEN + index * ChannelCapability::LEN;
            channels.push(ChannelCapability::decode(
                &bytes[offset..offset + ChannelCapability::LEN],
            )?);
        }
        let value = Self {
            cap_generation: u32_at(bytes, 0),
            max_message: u32_at(bytes, 4),
            max_rx_batch: u32_at(bytes, 8),
            tx_depth: u32_at(bytes, 12),
            tick_hz: u32_at(bytes, 16),
            tick_resolution_ns: u32_at(bytes, 20),
            boot_epoch: u64_at(bytes, 24),
            outstanding_limit: u16_at(bytes, 32),
            response_capacity: u16_at(bytes, 34),
            event_capacity: u16_at(bytes, 36),
            data_capacity: u16_at(bytes, 38),
            arm_timeout_min_ms: u16_at(bytes, 40),
            arm_timeout_max_ms: u16_at(bytes, 42),
            usb_mode: bytes[45],
            global_features: u16_at(bytes, 46),
            replay_cache_entries: u16_at(bytes, 48),
            tx_result_cache_entries: u16_at(bytes, 50),
            replay_retention_ms: u32_at(bytes, 52),
            tag_reuse_guard_ms: u32_at(bytes, 56),
            channels,
        };
        value.encode()?;
        Ok(value)
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PingRequest {
    pub host_send_ns: u64,
    pub sample_id: u32,
}

impl PingRequest {
    pub const LEN: usize = 16;

    pub fn encode(&self) -> Vec<u8> {
        let mut bytes = Vec::with_capacity(Self::LEN);
        bytes.extend(self.host_send_ns.to_le_bytes());
        bytes.extend(self.sample_id.to_le_bytes());
        bytes.extend([0; 4]);
        bytes
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, PayloadError> {
        exact_len(bytes, Self::LEN)?;
        reserved_zero(&bytes[12..16])?;
        Ok(Self {
            host_send_ns: u64_at(bytes, 0),
            sample_id: u32_at(bytes, 8),
        })
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PingResponse {
    pub host_send_ns: u64,
    pub device_rx_tick: u64,
    pub device_tx_tick: u64,
    pub sample_id: u32,
}

impl PingResponse {
    pub const LEN: usize = 32;

    pub fn encode(&self) -> Vec<u8> {
        let mut bytes = Vec::with_capacity(Self::LEN);
        bytes.extend(self.host_send_ns.to_le_bytes());
        bytes.extend(self.device_rx_tick.to_le_bytes());
        bytes.extend(self.device_tx_tick.to_le_bytes());
        bytes.extend(self.sample_id.to_le_bytes());
        bytes.extend([0; 4]);
        bytes
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, PayloadError> {
        exact_len(bytes, Self::LEN)?;
        reserved_zero(&bytes[28..32])?;
        Ok(Self {
            host_send_ns: u64_at(bytes, 0),
            device_rx_tick: u64_at(bytes, 8),
            device_tx_tick: u64_at(bytes, 16),
            sample_id: u32_at(bytes, 24),
        })
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ErrorPayload {
    pub detail_code: u16,
    pub error_flags: u16,
    pub field_offset: u32,
    pub expected: u32,
    pub actual: u32,
    pub debug: String,
}

impl ErrorPayload {
    pub const PREFIX_LEN: usize = 20;
    const KNOWN_FLAGS: u16 = 0x0007;

    pub fn encode(&self) -> Result<Vec<u8>, PayloadError> {
        if self.error_flags & !Self::KNOWN_FLAGS != 0 || self.debug.len() > 128 {
            return Err(PayloadError::InvalidValue("error payload"));
        }
        let debug_len = self.debug.len() as u16;
        let mut bytes = Vec::with_capacity(Self::PREFIX_LEN + self.debug.len());
        bytes.extend(self.detail_code.to_le_bytes());
        bytes.extend(self.error_flags.to_le_bytes());
        bytes.extend(self.field_offset.to_le_bytes());
        bytes.extend(self.expected.to_le_bytes());
        bytes.extend(self.actual.to_le_bytes());
        bytes.extend(debug_len.to_le_bytes());
        bytes.extend([0, 0]);
        bytes.extend(self.debug.as_bytes());
        Ok(bytes)
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, PayloadError> {
        if bytes.len() < Self::PREFIX_LEN {
            return Err(PayloadError::InvalidLength {
                expected: Self::PREFIX_LEN,
                actual: bytes.len(),
            });
        }
        reserved_zero(&bytes[18..20])?;
        let debug_len = u16_at(bytes, 16) as usize;
        if debug_len > 128 {
            return Err(PayloadError::StringTooLong);
        }
        exact_len(bytes, Self::PREFIX_LEN + debug_len)?;
        let debug = std::str::from_utf8(&bytes[Self::PREFIX_LEN..])
            .map_err(|_| PayloadError::InvalidUtf8)?
            .to_owned();
        let value = Self {
            detail_code: u16_at(bytes, 0),
            error_flags: u16_at(bytes, 2),
            field_offset: u32_at(bytes, 4),
            expected: u32_at(bytes, 8),
            actual: u32_at(bytes, 12),
            debug,
        };
        value.encode()?;
        Ok(value)
    }
}

/// Shared CAN frame constants and payload-consistency validation used by the
/// TX control payloads and the CAN RX batch (spec sections 5.1, 6, 7).
pub const CAN_ID_STD_MAX: u32 = 0x0000_07ff;
pub const CAN_ID_EXT_MAX: u32 = 0x1fff_ffff;
/// CAN flags permitted on CAN_TX: EXT, RTR, FD, BRS (ESI/ERROR_FRAME forbidden).
pub const CAN_TX_FLAGS_MASK: u16 = 0x000f;
/// CAN flags permitted on RX records: EXT, RTR, FD, BRS, ESI, ERROR.
pub const CAN_RX_FLAGS_MASK: u16 = 0x003f;
pub const CAN_FLAG_EXT: u16 = 0x0001;
pub const CAN_FLAG_RTR: u16 = 0x0002;
pub const CAN_FLAG_FD: u16 = 0x0004;
pub const CAN_FLAG_BRS: u16 = 0x0008;
pub const CAN_FLAG_ESI: u16 = 0x0010;
pub const CAN_FLAG_ERROR: u16 = 0x0020;

/// DLC → payload byte count: 0..8 → 0..8, 9→12, 10→16, 11→20, 12→24,
/// 13→32, 14→48, 15→64 (spec section 6).
pub fn can_dlc_to_payload_len(dlc: u8) -> Option<u8> {
    match dlc {
        0..=8 => Some(dlc),
        9 => Some(12),
        10 => Some(16),
        11 => Some(20),
        12 => Some(24),
        13 => Some(32),
        14 => Some(48),
        15 => Some(64),
        _ => None,
    }
}

/// Validate a CAN identifier against the frame's EXT flag.
pub fn validate_can_id(id: u32, ext: bool) -> Result<(), PayloadError> {
    let max = if ext { CAN_ID_EXT_MAX } else { CAN_ID_STD_MAX };
    if id > max {
        return Err(PayloadError::InvalidValue("CAN id range"));
    }
    Ok(())
}

/// Validate TX payload consistency (spec section 7):
/// RTR must be Classic with no data; FD payload must match the DLC mapping;
/// Classic data frames must have DLC ≤ 8 and payload_len == DLC.
pub fn validate_can_tx_payload(
    dlc: u8,
    flags: u16,
    payload_len: usize,
) -> Result<(), PayloadError> {
    if flags & CAN_FLAG_BRS != 0 && flags & CAN_FLAG_FD == 0 {
        return Err(PayloadError::InvalidValue("BRS requires FD"));
    }
    if flags & CAN_FLAG_RTR != 0 {
        if flags & CAN_FLAG_FD != 0 || dlc > 8 || payload_len != 0 {
            return Err(PayloadError::InvalidValue("RTR CAN_TX payload"));
        }
        return Ok(());
    }
    if flags & CAN_FLAG_FD != 0 {
        let expected =
            can_dlc_to_payload_len(dlc).ok_or(PayloadError::InvalidValue("CAN-FD DLC"))?;
        if payload_len != expected as usize {
            return Err(PayloadError::InvalidValue("CAN-FD payload length"));
        }
        return Ok(());
    }
    if dlc > 8 || payload_len != dlc as usize {
        return Err(PayloadError::InvalidValue("Classic CAN payload"));
    }
    Ok(())
}

/// Validate an RX record payload. Error frames are unconstrained; the
/// remaining rules mirror `validate_can_tx_payload` (spec section 6).
pub fn validate_can_rx_payload(
    dlc: u8,
    flags: u16,
    payload_len: usize,
) -> Result<(), PayloadError> {
    if flags & CAN_FLAG_ERROR != 0 {
        return Ok(());
    }
    validate_can_tx_payload(dlc, flags, payload_len)
}

fn exact_len(bytes: &[u8], expected: usize) -> Result<(), PayloadError> {
    if bytes.len() != expected {
        return Err(PayloadError::InvalidLength {
            expected,
            actual: bytes.len(),
        });
    }
    Ok(())
}

fn reserved_zero(bytes: &[u8]) -> Result<(), PayloadError> {
    if bytes.iter().any(|byte| *byte != 0) {
        return Err(PayloadError::InvalidReserved);
    }
    Ok(())
}

fn u16_at(bytes: &[u8], offset: usize) -> u16 {
    u16::from_le_bytes(bytes[offset..offset + 2].try_into().unwrap())
}

fn u32_at(bytes: &[u8], offset: usize) -> u32 {
    u32::from_le_bytes(bytes[offset..offset + 4].try_into().unwrap())
}

fn u64_at(bytes: &[u8], offset: usize) -> u64 {
    u64::from_le_bytes(bytes[offset..offset + 8].try_into().unwrap())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{Frame, flags};

    const MAX_MESSAGE: usize = 65_536;

    #[test]
    fn hello_request_and_response_vectors() {
        let request = HelloRequest {
            min_major: 1,
            max_major: 1,
            min_minor: 0,
            max_minor: 0,
            host_max_message: 65_536,
            host_features: 0,
        };
        assert_round_trip(&request.encode().unwrap(), HelloRequest::decode);

        let response = HelloResponse {
            major: 1,
            minor: 0,
            session_id: 0x1234_5678,
            max_message: 65_536,
            device_features: 0,
        };
        let payload = response.encode().unwrap();
        assert_round_trip(&payload, HelloResponse::decode);
        assert_frame_vector(
            Frame {
                major: 1,
                minor: 0,
                flags: flags::RESPONSE,
                message_type: 0x0001,
                status: 0,
                sequence: 1,
                payload,
            },
            include_str!("../../../../protocol/v1/0/hello-response.hex"),
        );
    }

    #[test]
    fn device_info_vector_and_utf8_validation() {
        let value = DeviceInfo {
            firmware_semver: "1.0.0".to_owned(),
            build_id: "abc123".to_owned(),
            board_id: "Gerber_PCB1_2026-07-23".to_owned(),
            serial: "20260723".to_owned(),
        };
        let payload = value.encode().unwrap();
        assert_round_trip(&payload, DeviceInfo::decode);
        assert_frame_vector(
            response(0x0002, 2, payload),
            include_str!("../../../../protocol/v1/0/device-info-response.hex"),
        );

        let mut invalid = vec![1, 0, 0, 0, 0, 0, 0, 0, 0xff];
        assert_eq!(DeviceInfo::decode(&invalid), Err(PayloadError::InvalidUtf8));
        invalid[0] = 65;
        assert_eq!(
            DeviceInfo::decode(&invalid),
            Err(PayloadError::StringTooLong)
        );
    }

    #[test]
    fn capabilities_vector_and_registry_validation() {
        let value = sample_capabilities();
        let payload = value.encode().unwrap();
        assert_eq!(payload.len(), 84);
        assert_round_trip(&payload, Capabilities::decode);
        assert_frame_vector(
            response(0x0003, 3, payload),
            include_str!("../../../../protocol/v1/0/capabilities-response.hex"),
        );

        let mut invalid = value;
        invalid.global_features = 0x0008;
        assert!(matches!(
            invalid.encode(),
            Err(PayloadError::InvalidValue("capabilities"))
        ));
    }

    #[test]
    fn ping_request_and_response_vectors() {
        let request = PingRequest {
            host_send_ns: 123_456_789,
            sample_id: 7,
        };
        let request_payload = request.encode();
        assert_round_trip(&request_payload, PingRequest::decode);
        assert_frame_vector(
            Frame::request(0x0030, 4, request_payload),
            include_str!("../../../../protocol/v1/0/ping-request.hex"),
        );

        let response_value = PingResponse {
            host_send_ns: 123_456_789,
            device_rx_tick: 1000,
            device_tx_tick: 1100,
            sample_id: 7,
        };
        let response_payload = response_value.encode();
        assert_round_trip(&response_payload, PingResponse::decode);
        assert_frame_vector(
            response(0x0030, 4, response_payload),
            include_str!("../../../../protocol/v1/0/ping-response.hex"),
        );
    }

    #[test]
    fn error_response_vector_and_limits() {
        let value = ErrorPayload {
            detail_code: 1,
            error_flags: 1,
            field_offset: 8,
            expected: 1_000_000,
            actual: 12_345,
            debug: "bad bitrate".to_owned(),
        };
        let payload = value.encode().unwrap();
        assert_round_trip(&payload, ErrorPayload::decode);
        let frame = Frame {
            major: 1,
            minor: 0,
            flags: flags::RESPONSE | flags::ERROR,
            message_type: 0x0010,
            status: 1,
            sequence: 5,
            payload,
        };
        assert_frame_vector(
            frame,
            include_str!("../../../../protocol/v1/0/error-response.hex"),
        );

        let mut invalid = value;
        invalid.error_flags = 0x0008;
        assert!(invalid.encode().is_err());
        invalid.error_flags = 0;
        invalid.debug = "x".repeat(129);
        assert!(invalid.encode().is_err());
    }

    #[test]
    fn reserved_fields_are_rejected() {
        let mut hello = HelloResponse {
            major: 1,
            minor: 0,
            session_id: 1,
            max_message: 1024,
            device_features: 0,
        }
        .encode()
        .unwrap();
        hello[2] = 1;
        assert_eq!(
            HelloResponse::decode(&hello),
            Err(PayloadError::InvalidReserved)
        );

        let mut ping = PingRequest {
            host_send_ns: 1,
            sample_id: 1,
        }
        .encode();
        ping[15] = 1;
        assert_eq!(
            PingRequest::decode(&ping),
            Err(PayloadError::InvalidReserved)
        );
    }

    fn sample_capabilities() -> Capabilities {
        Capabilities {
            cap_generation: 1,
            max_message: 65_536,
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
        }
    }

    fn response(message_type: u16, sequence: u32, payload: Vec<u8>) -> Frame {
        Frame {
            major: 1,
            minor: 0,
            flags: flags::RESPONSE,
            message_type,
            status: 0,
            sequence,
            payload,
        }
    }

    fn assert_round_trip<T: PartialEq + fmt::Debug>(
        bytes: &[u8],
        decode: impl FnOnce(&[u8]) -> Result<T, PayloadError>,
    ) {
        assert!(decode(bytes).is_ok());
    }

    fn assert_frame_vector(frame: Frame, expected: &str) {
        let bytes = frame.encode(MAX_MESSAGE).unwrap();
        let actual = bytes
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<Vec<_>>()
            .join(" ");
        assert_eq!(actual, expected.trim());
    }
}
