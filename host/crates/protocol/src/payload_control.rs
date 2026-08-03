use crate::payload::PayloadError;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ChannelConfig {
    pub channel: u8,
    pub mode: u8,
    pub flags: u16,
    pub nominal_bps: u32,
    pub data_bps: u32,
    pub sample_permille: u16,
    pub generation: u32,
}

impl ChannelConfig {
    pub const LEN: usize = 20;
    const KNOWN_FLAGS: u16 = 0x0003;

    pub fn encode(&self) -> Result<Vec<u8>, PayloadError> {
        if self.mode > 3
            || self.flags & !Self::KNOWN_FLAGS != 0
            || self.sample_permille > 1000
            || self.generation == 0
        {
            return Err(PayloadError::InvalidValue("channel config"));
        }
        let mut bytes = Vec::with_capacity(Self::LEN);
        bytes.extend([self.channel, self.mode]);
        bytes.extend(self.flags.to_le_bytes());
        bytes.extend(self.nominal_bps.to_le_bytes());
        bytes.extend(self.data_bps.to_le_bytes());
        bytes.extend(self.sample_permille.to_le_bytes());
        bytes.extend([0, 0]);
        bytes.extend(self.generation.to_le_bytes());
        Ok(bytes)
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, PayloadError> {
        exact_len(bytes, Self::LEN)?;
        reserved_zero(&bytes[14..16])?;
        let value = Self {
            channel: bytes[0],
            mode: bytes[1],
            flags: u16_at(bytes, 2),
            nominal_bps: u32_at(bytes, 4),
            data_bps: u32_at(bytes, 8),
            sample_permille: u16_at(bytes, 12),
            generation: u32_at(bytes, 16),
        };
        value.encode()?;
        Ok(value)
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct GetChannelConfigRequest {
    pub channel: u8,
}

impl GetChannelConfigRequest {
    pub const LEN: usize = 4;

    pub fn encode(&self) -> Vec<u8> {
        vec![self.channel, 0, 0, 0]
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, PayloadError> {
        exact_len(bytes, Self::LEN)?;
        reserved_zero(&bytes[1..4])?;
        Ok(Self { channel: bytes[0] })
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CaptureRequest {
    pub expected_generation: u32,
    pub flags: u32,
}

impl CaptureRequest {
    pub const LEN: usize = 8;
    const KNOWN_FLAGS: u32 = 0x0007;

    pub fn encode(&self) -> Result<Vec<u8>, PayloadError> {
        if self.expected_generation == 0 || self.flags & !Self::KNOWN_FLAGS != 0 {
            return Err(PayloadError::InvalidValue("capture flags"));
        }
        let mut bytes = Vec::with_capacity(Self::LEN);
        bytes.extend(self.expected_generation.to_le_bytes());
        bytes.extend(self.flags.to_le_bytes());
        Ok(bytes)
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, PayloadError> {
        exact_len(bytes, Self::LEN)?;
        let value = Self {
            expected_generation: u32_at(bytes, 0),
            flags: u32_at(bytes, 4),
        };
        value.encode()?;
        Ok(value)
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CaptureResponse {
    pub applied_generation: u32,
    pub state: u32,
}

impl CaptureResponse {
    pub const LEN: usize = 8;

    pub fn encode(&self) -> Result<Vec<u8>, PayloadError> {
        if self.applied_generation == 0 || self.state > 1 {
            return Err(PayloadError::InvalidValue("capture response"));
        }
        let mut bytes = Vec::with_capacity(Self::LEN);
        bytes.extend(self.applied_generation.to_le_bytes());
        bytes.extend(self.state.to_le_bytes());
        Ok(bytes)
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, PayloadError> {
        exact_len(bytes, Self::LEN)?;
        let value = Self {
            applied_generation: u32_at(bytes, 0),
            state: u32_at(bytes, 4),
        };
        value.encode()?;
        Ok(value)
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ResetDiagnosticsRequest {
    pub mask: u32,
}

impl ResetDiagnosticsRequest {
    pub const LEN: usize = 4;
    const KNOWN_MASK: u32 = 0x001f;

    pub fn encode(&self) -> Result<Vec<u8>, PayloadError> {
        if self.mask & !Self::KNOWN_MASK != 0 {
            return Err(PayloadError::InvalidValue("diagnostic mask"));
        }
        Ok(self.mask.to_le_bytes().to_vec())
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, PayloadError> {
        exact_len(bytes, Self::LEN)?;
        let value = Self {
            mask: u32_at(bytes, 0),
        };
        value.encode()?;
        Ok(value)
    }
}

pub fn decode_empty(bytes: &[u8]) -> Result<(), PayloadError> {
    exact_len(bytes, 0)
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ChannelDiagnostics {
    pub channel: u8,
    pub state: u8,
    pub rx_depth: u32,
    pub tx_depth: u32,
    pub rx_frames: u64,
    pub tx_frames: u64,
    pub filtered: u64,
    pub dropped: u64,
    pub bus_off_count: u32,
    pub error_count: u32,
}

impl ChannelDiagnostics {
    pub const LEN: usize = 52;

    fn encode_into(&self, bytes: &mut Vec<u8>) -> Result<(), PayloadError> {
        if self.state > 4 {
            return Err(PayloadError::InvalidValue("channel diagnostic state"));
        }
        bytes.extend([self.channel, self.state, 0, 0]);
        bytes.extend(self.rx_depth.to_le_bytes());
        bytes.extend(self.tx_depth.to_le_bytes());
        bytes.extend(self.rx_frames.to_le_bytes());
        bytes.extend(self.tx_frames.to_le_bytes());
        bytes.extend(self.filtered.to_le_bytes());
        bytes.extend(self.dropped.to_le_bytes());
        bytes.extend(self.bus_off_count.to_le_bytes());
        bytes.extend(self.error_count.to_le_bytes());
        Ok(())
    }

    fn decode(bytes: &[u8]) -> Result<Self, PayloadError> {
        exact_len(bytes, Self::LEN)?;
        reserved_zero(&bytes[2..4])?;
        let value = Self {
            channel: bytes[0],
            state: bytes[1],
            rx_depth: u32_at(bytes, 4),
            tx_depth: u32_at(bytes, 8),
            rx_frames: u64_at(bytes, 12),
            tx_frames: u64_at(bytes, 20),
            filtered: u64_at(bytes, 28),
            dropped: u64_at(bytes, 36),
            bus_off_count: u32_at(bytes, 44),
            error_count: u32_at(bytes, 48),
        };
        let mut sink = Vec::new();
        value.encode_into(&mut sink)?;
        Ok(value)
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Diagnostics {
    pub generation: u32,
    pub session_id: u32,
    pub response_depth: u32,
    pub event_depth: u32,
    pub data_depth: u32,
    pub pool_high_water: u32,
    pub usb_rx_bytes: u64,
    pub usb_tx_bytes: u64,
    pub channels: Vec<ChannelDiagnostics>,
}

impl Diagnostics {
    pub const FIXED_LEN: usize = 40;

    pub fn encode(&self) -> Result<Vec<u8>, PayloadError> {
        if self.generation == 0
            || self.session_id == 0
            || has_duplicate_channels(self.channels.iter().map(|channel| channel.channel))
        {
            return Err(PayloadError::InvalidValue("diagnostics"));
        }
        let mut bytes = Vec::with_capacity(Self::FIXED_LEN + self.channels.len() * 52);
        for value in [
            self.generation,
            self.session_id,
            self.response_depth,
            self.event_depth,
            self.data_depth,
            self.pool_high_water,
        ] {
            bytes.extend(value.to_le_bytes());
        }
        bytes.extend(self.usb_rx_bytes.to_le_bytes());
        bytes.extend(self.usb_tx_bytes.to_le_bytes());
        for channel in &self.channels {
            channel.encode_into(&mut bytes)?;
        }
        Ok(bytes)
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, PayloadError> {
        if bytes.len() < Self::FIXED_LEN
            || !(bytes.len() - Self::FIXED_LEN).is_multiple_of(ChannelDiagnostics::LEN)
        {
            return Err(PayloadError::InvalidLength {
                expected: Self::FIXED_LEN,
                actual: bytes.len(),
            });
        }
        let mut channels = Vec::new();
        for chunk in bytes[Self::FIXED_LEN..].chunks_exact(ChannelDiagnostics::LEN) {
            channels.push(ChannelDiagnostics::decode(chunk)?);
        }
        let value = Self {
            generation: u32_at(bytes, 0),
            session_id: u32_at(bytes, 4),
            response_depth: u32_at(bytes, 8),
            event_depth: u32_at(bytes, 12),
            data_depth: u32_at(bytes, 16),
            pool_high_water: u32_at(bytes, 20),
            usb_rx_bytes: u64_at(bytes, 24),
            usb_tx_bytes: u64_at(bytes, 32),
            channels,
        };
        value.encode()?;
        Ok(value)
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FilterState {
    pub channel: u8,
    pub filter_generation: u32,
    pub filter_crc32c: u32,
}

impl FilterState {
    pub const LEN: usize = 12;

    fn encode_into(&self, bytes: &mut Vec<u8>) {
        bytes.extend([self.channel, 0, 0, 0]);
        bytes.extend(self.filter_generation.to_le_bytes());
        bytes.extend(self.filter_crc32c.to_le_bytes());
    }

    fn decode(bytes: &[u8]) -> Result<Self, PayloadError> {
        exact_len(bytes, Self::LEN)?;
        reserved_zero(&bytes[1..4])?;
        Ok(Self {
            channel: bytes[0],
            filter_generation: u32_at(bytes, 4),
            filter_crc32c: u32_at(bytes, 8),
        })
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SessionState {
    pub config_generation: u32,
    pub capture_generation: u32,
    pub capture_state: u8,
    pub tx_armed: bool,
    pub arm_epoch: u32,
    pub arm_expiry_tick: u64,
    pub aggregate_max_frames_per_s: u32,
    pub filters: Vec<FilterState>,
}

impl SessionState {
    pub const FIXED_LEN: usize = 28;

    pub fn encode(&self) -> Result<Vec<u8>, PayloadError> {
        if self.config_generation == 0
            || self.capture_state > 1
            || self.arm_epoch == 0
            || !self.tx_armed && self.arm_expiry_tick != 0
            || has_duplicate_channels(self.filters.iter().map(|filter| filter.channel))
        {
            return Err(PayloadError::InvalidValue("session state"));
        }
        let mut bytes = Vec::with_capacity(Self::FIXED_LEN + self.filters.len() * 12);
        bytes.extend(self.config_generation.to_le_bytes());
        bytes.extend(self.capture_generation.to_le_bytes());
        bytes.extend([self.capture_state, u8::from(self.tx_armed), 0, 0]);
        bytes.extend(self.arm_epoch.to_le_bytes());
        bytes.extend(self.arm_expiry_tick.to_le_bytes());
        bytes.extend(self.aggregate_max_frames_per_s.to_le_bytes());
        for filter in &self.filters {
            filter.encode_into(&mut bytes);
        }
        Ok(bytes)
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, PayloadError> {
        if bytes.len() < Self::FIXED_LEN
            || !(bytes.len() - Self::FIXED_LEN).is_multiple_of(FilterState::LEN)
        {
            return Err(PayloadError::InvalidLength {
                expected: Self::FIXED_LEN,
                actual: bytes.len(),
            });
        }
        reserved_zero(&bytes[10..12])?;
        if bytes[9] > 1 {
            return Err(PayloadError::InvalidValue("tx armed"));
        }
        let mut filters = Vec::new();
        for chunk in bytes[Self::FIXED_LEN..].chunks_exact(FilterState::LEN) {
            filters.push(FilterState::decode(chunk)?);
        }
        let value = Self {
            config_generation: u32_at(bytes, 0),
            capture_generation: u32_at(bytes, 4),
            capture_state: bytes[8],
            tx_armed: bytes[9] != 0,
            arm_epoch: u32_at(bytes, 12),
            arm_expiry_tick: u64_at(bytes, 16),
            aggregate_max_frames_per_s: u32_at(bytes, 24),
            filters,
        };
        value.encode()?;
        Ok(value)
    }
}

fn has_duplicate_channels(channels: impl Iterator<Item = u8>) -> bool {
    let mut seen = [false; 256];
    for channel in channels {
        if seen[channel as usize] {
            return true;
        }
        seen[channel as usize] = true;
    }
    false
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
    fn channel_config_vectors_and_validation() {
        let request = config(1);
        let payload = request.encode().unwrap();
        assert_eq!(ChannelConfig::decode(&payload).unwrap(), request);
        assert_vector(
            Frame::request(0x0010, 10, payload),
            include_str!("../../../../protocol/v1/0/config-channel-request.hex"),
        );

        let response_value = config(2);
        let payload = response_value.encode().unwrap();
        assert_vector(
            response(0x0010, 10, payload),
            include_str!("../../../../protocol/v1/0/config-channel-response.hex"),
        );

        let mut invalid = request;
        invalid.mode = 4;
        assert!(invalid.encode().is_err());
        invalid.mode = 2;
        invalid.flags = 4;
        assert!(invalid.encode().is_err());
    }

    #[test]
    fn get_channel_config_request_vector() {
        let request = GetChannelConfigRequest { channel: 0 };
        let payload = request.encode();
        assert_eq!(GetChannelConfigRequest::decode(&payload).unwrap(), request);
        assert_vector(
            Frame::request(0x0011, 11, payload),
            include_str!("../../../../protocol/v1/0/get-channel-config-request.hex"),
        );
        let mut invalid = request.encode();
        invalid[1] = 1;
        assert_eq!(
            GetChannelConfigRequest::decode(&invalid),
            Err(PayloadError::InvalidReserved)
        );
    }

    #[test]
    fn start_and_stop_capture_vectors() {
        let start = CaptureRequest {
            expected_generation: 2,
            flags: 7,
        };
        assert_vector(
            Frame::request(0x0012, 12, start.encode().unwrap()),
            include_str!("../../../../protocol/v1/0/start-capture-request.hex"),
        );
        assert_vector(
            response(
                0x0012,
                12,
                CaptureResponse {
                    applied_generation: 3,
                    state: 1,
                }
                .encode()
                .unwrap(),
            ),
            include_str!("../../../../protocol/v1/0/start-capture-response.hex"),
        );
        let stop = CaptureRequest {
            expected_generation: 3,
            flags: 7,
        };
        assert_vector(
            Frame::request(0x0013, 13, stop.encode().unwrap()),
            include_str!("../../../../protocol/v1/0/stop-capture-request.hex"),
        );
        assert_vector(
            response(
                0x0013,
                13,
                CaptureResponse {
                    applied_generation: 4,
                    state: 0,
                }
                .encode()
                .unwrap(),
            ),
            include_str!("../../../../protocol/v1/0/stop-capture-response.hex"),
        );
        let mut invalid = start;
        invalid.flags = 8;
        assert!(invalid.encode().is_err());
    }

    #[test]
    fn diagnostics_vectors_and_record_validation() {
        let request = Frame::request(0x0004, 14, vec![]);
        decode_empty(&request.payload).unwrap();
        assert_vector(
            request,
            include_str!("../../../../protocol/v1/0/get-diagnostics-request.hex"),
        );

        let diagnostics = diagnostics();
        let payload = diagnostics.encode().unwrap();
        assert_eq!(payload.len(), 92);
        assert_eq!(Diagnostics::decode(&payload).unwrap(), diagnostics);
        assert_vector(
            response(0x0004, 14, payload),
            include_str!("../../../../protocol/v1/0/get-diagnostics-response.hex"),
        );

        let reset = ResetDiagnosticsRequest { mask: 0x001f };
        assert_vector(
            Frame::request(0x0005, 15, reset.encode().unwrap()),
            include_str!("../../../../protocol/v1/0/reset-diagnostics-request.hex"),
        );
        let mut invalid = reset;
        invalid.mask = 0x20;
        assert!(invalid.encode().is_err());
    }

    #[test]
    fn session_state_vectors_and_safety_constraints() {
        let request = Frame::request(0x0006, 16, vec![]);
        decode_empty(&request.payload).unwrap();
        assert_vector(
            request,
            include_str!("../../../../protocol/v1/0/get-session-state-request.hex"),
        );
        let state = SessionState {
            config_generation: 3,
            capture_generation: 3,
            capture_state: 1,
            tx_armed: false,
            arm_epoch: 2,
            arm_expiry_tick: 0,
            aggregate_max_frames_per_s: 0,
            filters: vec![FilterState {
                channel: 0,
                filter_generation: 3,
                filter_crc32c: 0xdead_beef,
            }],
        };
        let payload = state.encode().unwrap();
        assert_eq!(SessionState::decode(&payload).unwrap(), state);
        assert_vector(
            response(0x0006, 16, payload),
            include_str!("../../../../protocol/v1/0/get-session-state-response.hex"),
        );

        let mut invalid = state;
        invalid.arm_expiry_tick = 1;
        assert!(invalid.encode().is_err());
        invalid.arm_expiry_tick = 0;
        invalid.filters.push(invalid.filters[0].clone());
        assert!(invalid.encode().is_err());
    }

    #[test]
    fn malformed_diagnostic_and_session_lengths_are_rejected() {
        assert!(Diagnostics::decode(&[0; 41]).is_err());
        assert!(SessionState::decode(&[0; 29]).is_err());
        assert!(decode_empty(&[0]).is_err());
    }

    fn config(generation: u32) -> ChannelConfig {
        ChannelConfig {
            channel: 0,
            mode: 2,
            flags: 3,
            nominal_bps: 500_000,
            data_bps: 0,
            sample_permille: 875,
            generation,
        }
    }

    fn diagnostics() -> Diagnostics {
        Diagnostics {
            generation: 4,
            session_id: 0x1234_5678,
            response_depth: 1,
            event_depth: 2,
            data_depth: 3,
            pool_high_water: 4,
            usb_rx_bytes: 1000,
            usb_tx_bytes: 2000,
            channels: vec![ChannelDiagnostics {
                channel: 0,
                state: 2,
                rx_depth: 5,
                tx_depth: 6,
                rx_frames: 100,
                tx_frames: 10,
                filtered: 2,
                dropped: 1,
                bus_off_count: 0,
                error_count: 3,
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

    fn assert_vector(frame: Frame, expected: &str) {
        let bytes = frame.encode(MAX_MESSAGE).unwrap();
        let actual = bytes
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<Vec<_>>()
            .join(" ");
        assert_eq!(actual, expected.trim());
    }
}
