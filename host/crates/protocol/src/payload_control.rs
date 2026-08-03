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

/// Filter rule (spec section 5.1): canonical 12-byte record used both on the
/// wire and as the CRC-32C input for `filter_crc32c`.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FilterRule {
    pub id: u32,
    pub mask: u32,
    pub flags: u16,
}

impl FilterRule {
    pub const LEN: usize = 12;
    const KNOWN_FLAGS: u16 = 0x0007; // EXT_ONLY | RTR_ONLY | INVERT
    const MAX_ID: u32 = 0x1fff_ffff;

    fn encode_into(&self, bytes: &mut Vec<u8>) -> Result<(), PayloadError> {
        if self.flags & !Self::KNOWN_FLAGS != 0
            || self.id > Self::MAX_ID
            || self.mask > Self::MAX_ID
        {
            return Err(PayloadError::InvalidValue("filter rule"));
        }
        bytes.extend(self.id.to_le_bytes());
        bytes.extend(self.mask.to_le_bytes());
        bytes.extend(self.flags.to_le_bytes());
        bytes.extend([0, 0]);
        Ok(())
    }

    fn decode(bytes: &[u8]) -> Result<Self, PayloadError> {
        exact_len(bytes, Self::LEN)?;
        reserved_zero(&bytes[10..12])?;
        let value = Self {
            id: u32_at(bytes, 0),
            mask: u32_at(bytes, 4),
            flags: u16_at(bytes, 8),
        };
        let mut sink = Vec::new();
        value.encode_into(&mut sink)?;
        Ok(value)
    }
}

/// CRC-32C over the canonical little-endian filter records (spec section 5.1);
/// the empty set also has a fixed CRC.
pub fn filter_crc32c(rules: &[FilterRule]) -> u32 {
    let mut canonical = Vec::new();
    for rule in rules {
        canonical.extend(rule.id.to_le_bytes());
        canonical.extend(rule.mask.to_le_bytes());
        canonical.extend(rule.flags.to_le_bytes());
        canonical.extend([0u8; 2]);
    }
    crate::crc32c(&canonical)
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SetFiltersRequest {
    pub channel: u8,
    pub expected_generation: u32,
    pub rules: Vec<FilterRule>,
}

impl SetFiltersRequest {
    pub const FIXED_LEN: usize = 8;

    pub fn encode(&self) -> Result<Vec<u8>, PayloadError> {
        let count = u8::try_from(self.rules.len())
            .map_err(|_| PayloadError::InvalidValue("filter count"))?;
        if self.expected_generation == 0 {
            return Err(PayloadError::InvalidValue("set filters generation"));
        }
        let mut bytes = Vec::with_capacity(Self::FIXED_LEN + self.rules.len() * FilterRule::LEN);
        bytes.extend([self.channel, count, 0, 0]);
        bytes.extend(self.expected_generation.to_le_bytes());
        for rule in &self.rules {
            rule.encode_into(&mut bytes)?;
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
        reserved_zero(&bytes[2..4])?;
        let count = bytes[1] as usize;
        exact_len(bytes, Self::FIXED_LEN + count * FilterRule::LEN)?;
        let mut rules = Vec::with_capacity(count);
        for index in 0..count {
            let offset = Self::FIXED_LEN + index * FilterRule::LEN;
            rules.push(FilterRule::decode(
                &bytes[offset..offset + FilterRule::LEN],
            )?);
        }
        let value = Self {
            channel: bytes[0],
            expected_generation: u32_at(bytes, 4),
            rules,
        };
        value.encode()?;
        Ok(value)
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SetFiltersResponse {
    pub applied_generation: u32,
    pub applied_count: u16,
}

impl SetFiltersResponse {
    pub const LEN: usize = 8;

    pub fn encode(&self) -> Result<Vec<u8>, PayloadError> {
        if self.applied_generation == 0 {
            return Err(PayloadError::InvalidValue("set filters response"));
        }
        let mut bytes = Vec::with_capacity(Self::LEN);
        bytes.extend(self.applied_generation.to_le_bytes());
        bytes.extend(self.applied_count.to_le_bytes());
        bytes.extend([0, 0]);
        Ok(bytes)
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, PayloadError> {
        exact_len(bytes, Self::LEN)?;
        reserved_zero(&bytes[6..8])?;
        let value = Self {
            applied_generation: u32_at(bytes, 0),
            applied_count: u16_at(bytes, 4),
        };
        value.encode()?;
        Ok(value)
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ClearFiltersRequest {
    pub channel: u8,
    pub expected_generation: u32,
}

impl ClearFiltersRequest {
    pub const LEN: usize = 8;

    pub fn encode(&self) -> Result<Vec<u8>, PayloadError> {
        if self.expected_generation == 0 {
            return Err(PayloadError::InvalidValue("clear filters generation"));
        }
        let mut bytes = Vec::with_capacity(Self::LEN);
        bytes.extend([self.channel, 0, 0, 0]);
        bytes.extend(self.expected_generation.to_le_bytes());
        Ok(bytes)
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, PayloadError> {
        exact_len(bytes, Self::LEN)?;
        reserved_zero(&bytes[1..4])?;
        let value = Self {
            channel: bytes[0],
            expected_generation: u32_at(bytes, 4),
        };
        value.encode()?;
        Ok(value)
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ClearFiltersResponse {
    pub applied_generation: u32,
}

impl ClearFiltersResponse {
    pub const LEN: usize = 4;

    pub fn encode(&self) -> Result<Vec<u8>, PayloadError> {
        if self.applied_generation == 0 {
            return Err(PayloadError::InvalidValue("clear filters response"));
        }
        Ok(self.applied_generation.to_le_bytes().to_vec())
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, PayloadError> {
        exact_len(bytes, Self::LEN)?;
        let value = Self {
            applied_generation: u32_at(bytes, 0),
        };
        value.encode()?;
        Ok(value)
    }
}

/// TX arm admission rule (spec section 5.1, 16 bytes).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TxRule {
    pub channel: u8,
    pub allowed_flag_mask: u8,
    pub id: u32,
    pub id_mask: u32,
    pub max_frames_per_s: u32,
}

impl TxRule {
    pub const LEN: usize = 16;
    const KNOWN_FLAG_MASK: u8 = 0x0f; // EXT | RTR | FD | BRS
    const MAX_ID: u32 = 0x1fff_ffff;

    fn encode_into(&self, bytes: &mut Vec<u8>) -> Result<(), PayloadError> {
        if self.allowed_flag_mask & !Self::KNOWN_FLAG_MASK != 0
            || self.id > Self::MAX_ID
            || self.id_mask > Self::MAX_ID
        {
            return Err(PayloadError::InvalidValue("TX arm rule"));
        }
        bytes.extend([self.channel, self.allowed_flag_mask, 0, 0]);
        bytes.extend(self.id.to_le_bytes());
        bytes.extend(self.id_mask.to_le_bytes());
        bytes.extend(self.max_frames_per_s.to_le_bytes());
        Ok(())
    }

    fn decode(bytes: &[u8]) -> Result<Self, PayloadError> {
        exact_len(bytes, Self::LEN)?;
        reserved_zero(&bytes[2..4])?;
        let value = Self {
            channel: bytes[0],
            allowed_flag_mask: bytes[1],
            id: u32_at(bytes, 4),
            id_mask: u32_at(bytes, 8),
            max_frames_per_s: u32_at(bytes, 12),
        };
        let mut sink = Vec::new();
        value.encode_into(&mut sink)?;
        Ok(value)
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TxArmRequest {
    pub expected_config_generation: u32,
    pub timeout_ms: u32,
    pub max_frames_per_s: u32,
    pub max_bus_load_permille: u16,
    pub rules: Vec<TxRule>,
}

impl TxArmRequest {
    pub const FIXED_LEN: usize = 16;
    pub const MAX_RULES: usize = 16;

    pub fn encode(&self) -> Result<Vec<u8>, PayloadError> {
        let rule_count = u16::try_from(self.rules.len())
            .map_err(|_| PayloadError::InvalidValue("TX arm rule count"))?;
        if self.expected_config_generation == 0
            || !(100..=60_000).contains(&self.timeout_ms)
            || self.max_bus_load_permille > 1000
            || self.rules.len() > Self::MAX_RULES
        {
            return Err(PayloadError::InvalidValue("TX arm"));
        }
        let mut bytes = Vec::with_capacity(Self::FIXED_LEN + self.rules.len() * TxRule::LEN);
        bytes.extend(self.expected_config_generation.to_le_bytes());
        bytes.extend(self.timeout_ms.to_le_bytes());
        bytes.extend(self.max_frames_per_s.to_le_bytes());
        bytes.extend(self.max_bus_load_permille.to_le_bytes());
        bytes.extend(rule_count.to_le_bytes());
        for rule in &self.rules {
            rule.encode_into(&mut bytes)?;
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
        let rule_count = u16_at(bytes, 14) as usize;
        if rule_count > Self::MAX_RULES {
            return Err(PayloadError::InvalidValue("TX arm rule count"));
        }
        exact_len(bytes, Self::FIXED_LEN + rule_count * TxRule::LEN)?;
        let mut rules = Vec::with_capacity(rule_count);
        for index in 0..rule_count {
            let offset = Self::FIXED_LEN + index * TxRule::LEN;
            rules.push(TxRule::decode(&bytes[offset..offset + TxRule::LEN])?);
        }
        let value = Self {
            expected_config_generation: u32_at(bytes, 0),
            timeout_ms: u32_at(bytes, 4),
            max_frames_per_s: u32_at(bytes, 8),
            max_bus_load_permille: u16_at(bytes, 12),
            rules,
        };
        value.encode()?;
        Ok(value)
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TxArmResponse {
    pub applied_config_generation: u32,
    pub arm_epoch: u32,
    pub expiry_tick: u64,
}

impl TxArmResponse {
    pub const LEN: usize = 16;

    pub fn encode(&self) -> Result<Vec<u8>, PayloadError> {
        if self.applied_config_generation == 0 || self.arm_epoch == 0 {
            return Err(PayloadError::InvalidValue("TX arm response"));
        }
        let mut bytes = Vec::with_capacity(Self::LEN);
        bytes.extend(self.applied_config_generation.to_le_bytes());
        bytes.extend(self.arm_epoch.to_le_bytes());
        bytes.extend(self.expiry_tick.to_le_bytes());
        Ok(bytes)
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, PayloadError> {
        exact_len(bytes, Self::LEN)?;
        let value = Self {
            applied_config_generation: u32_at(bytes, 0),
            arm_epoch: u32_at(bytes, 4),
            expiry_tick: u64_at(bytes, 8),
        };
        value.encode()?;
        Ok(value)
    }
}

/// Disarm reasons (spec section 5.1 numeric registry).
pub mod disarm_reason {
    pub const HOST: u32 = 1;
    pub const EXPIRY: u32 = 2;
    pub const USB_RESET: u32 = 3;
    pub const WATCHDOG: u32 = 4;
    pub const CONFIG_FAILURE: u32 = 5;
    pub const BUS_OFF: u32 = 6;
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TxDisarmRequest {
    pub expected_config_generation: u32,
    pub arm_epoch: u32,
    pub reason: u32,
}

impl TxDisarmRequest {
    pub const LEN: usize = 16;

    pub fn encode(&self) -> Result<Vec<u8>, PayloadError> {
        if self.expected_config_generation == 0
            || self.arm_epoch == 0
            || !(1..=6).contains(&self.reason)
        {
            return Err(PayloadError::InvalidValue("TX disarm"));
        }
        let mut bytes = Vec::with_capacity(Self::LEN);
        bytes.extend(self.expected_config_generation.to_le_bytes());
        bytes.extend(self.arm_epoch.to_le_bytes());
        bytes.extend(self.reason.to_le_bytes());
        bytes.extend([0; 4]);
        Ok(bytes)
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, PayloadError> {
        exact_len(bytes, Self::LEN)?;
        reserved_zero(&bytes[12..16])?;
        let value = Self {
            expected_config_generation: u32_at(bytes, 0),
            arm_epoch: u32_at(bytes, 4),
            reason: u32_at(bytes, 8),
        };
        value.encode()?;
        Ok(value)
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TxDisarmResponse {
    pub applied_config_generation: u32,
    pub new_arm_epoch: u32,
    pub cancelled_count: u32,
}

impl TxDisarmResponse {
    pub const LEN: usize = 16;

    pub fn encode(&self) -> Result<Vec<u8>, PayloadError> {
        if self.applied_config_generation == 0 || self.new_arm_epoch == 0 {
            return Err(PayloadError::InvalidValue("TX disarm response"));
        }
        let mut bytes = Vec::with_capacity(Self::LEN);
        bytes.extend(self.applied_config_generation.to_le_bytes());
        bytes.extend(self.new_arm_epoch.to_le_bytes());
        bytes.extend(self.cancelled_count.to_le_bytes());
        bytes.extend([0; 4]);
        Ok(bytes)
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, PayloadError> {
        exact_len(bytes, Self::LEN)?;
        reserved_zero(&bytes[12..16])?;
        let value = Self {
            applied_config_generation: u32_at(bytes, 0),
            new_arm_epoch: u32_at(bytes, 4),
            cancelled_count: u32_at(bytes, 8),
        };
        value.encode()?;
        Ok(value)
    }
}

/// CAN_TX request (spec section 5.1): 28-byte fixed prefix + 0..64 data bytes.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CanTxRequest {
    pub channel: u8,
    pub dlc: u8,
    pub can_flags: u16,
    pub id: u32,
    pub arm_epoch: u32,
    pub client_tag: u32,
    pub deadline_tick: u64,
    pub payload: Vec<u8>,
}

impl CanTxRequest {
    pub const FIXED_LEN: usize = 28;

    pub fn encode(&self) -> Result<Vec<u8>, PayloadError> {
        if self.can_flags & !crate::payload::CAN_TX_FLAGS_MASK != 0
            || self.arm_epoch == 0
            || self.payload.len() > 64
        {
            return Err(PayloadError::InvalidValue("CAN_TX"));
        }
        crate::payload::validate_can_id(
            self.id,
            self.can_flags & crate::payload::CAN_FLAG_EXT != 0,
        )?;
        crate::payload::validate_can_tx_payload(self.dlc, self.can_flags, self.payload.len())?;
        let mut bytes = Vec::with_capacity(Self::FIXED_LEN + self.payload.len());
        bytes.extend([self.channel, self.dlc]);
        bytes.extend(self.can_flags.to_le_bytes());
        bytes.extend(self.id.to_le_bytes());
        bytes.extend(self.arm_epoch.to_le_bytes());
        bytes.extend(self.client_tag.to_le_bytes());
        bytes.extend(self.deadline_tick.to_le_bytes());
        bytes.extend([self.payload.len() as u8, 0, 0, 0]);
        bytes.extend(&self.payload);
        Ok(bytes)
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, PayloadError> {
        if bytes.len() < Self::FIXED_LEN {
            return Err(PayloadError::InvalidLength {
                expected: Self::FIXED_LEN,
                actual: bytes.len(),
            });
        }
        reserved_zero(&bytes[25..28])?;
        let payload_len = bytes[24] as usize;
        exact_len(bytes, Self::FIXED_LEN + payload_len)?;
        let value = Self {
            channel: bytes[0],
            dlc: bytes[1],
            can_flags: u16_at(bytes, 2),
            id: u32_at(bytes, 4),
            arm_epoch: u32_at(bytes, 8),
            client_tag: u32_at(bytes, 12),
            deadline_tick: u64_at(bytes, 16),
            payload: bytes[Self::FIXED_LEN..].to_vec(),
        };
        value.encode()?;
        Ok(value)
    }
}

/// CAN_TX result enum (shared by FINAL ledger snapshots and CAN_TX_RESULT).
pub mod can_tx_result {
    pub const SENT: u16 = 1;
    pub const CANCELLED: u16 = 2;
    pub const TIMEOUT: u16 = 3;
    pub const BUS_ERROR: u16 = 4;
    pub const DISARMED: u16 = 5;
}

/// Ledger snapshot state (spec section 5.1): PENDING=1, FINAL=2.
pub mod tx_state {
    pub const PENDING: u16 = 1;
    pub const FINAL: u16 = 2;
}

/// CAN_TX response: 24-byte ledger snapshot.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CanTxResponse {
    pub client_tag: u32,
    pub queue_generation: u32,
    pub tx_state: u16,
    pub final_result: u16,
    pub final_tick: u64,
    pub can_error: u32,
}

impl CanTxResponse {
    pub const LEN: usize = 24;

    pub fn encode(&self) -> Result<Vec<u8>, PayloadError> {
        if self.queue_generation == 0
            || !matches!(self.tx_state, tx_state::PENDING | tx_state::FINAL)
            || self.tx_state == tx_state::PENDING
                && (self.final_result != 0 || self.final_tick != 0 || self.can_error != 0)
            || self.tx_state == tx_state::FINAL
                && (!(1..=5).contains(&self.final_result) || self.can_error & 0xfff8_0000 != 0)
        {
            return Err(PayloadError::InvalidValue("CAN_TX response"));
        }
        let mut bytes = Vec::with_capacity(Self::LEN);
        bytes.extend(self.client_tag.to_le_bytes());
        bytes.extend(self.queue_generation.to_le_bytes());
        bytes.extend(self.tx_state.to_le_bytes());
        bytes.extend(self.final_result.to_le_bytes());
        bytes.extend(self.final_tick.to_le_bytes());
        bytes.extend(self.can_error.to_le_bytes());
        Ok(bytes)
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, PayloadError> {
        exact_len(bytes, Self::LEN)?;
        let value = Self {
            client_tag: u32_at(bytes, 0),
            queue_generation: u32_at(bytes, 4),
            tx_state: u16_at(bytes, 8),
            final_result: u16_at(bytes, 10),
            final_tick: u64_at(bytes, 12),
            can_error: u32_at(bytes, 20),
        };
        value.encode()?;
        Ok(value)
    }
}

/// CAN_TX_CANCEL cancel states (spec section 5.1).
pub mod cancel_state {
    pub const CANCELLED: u32 = 1;
    pub const ALREADY_COMPLETE: u32 = 2;
    pub const NOT_FOUND: u32 = 3;
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CanTxCancelRequest {
    pub arm_epoch: u32,
    pub client_tag: u32,
}

impl CanTxCancelRequest {
    pub const LEN: usize = 8;

    pub fn encode(&self) -> Result<Vec<u8>, PayloadError> {
        if self.arm_epoch == 0 {
            return Err(PayloadError::InvalidValue("CAN_TX_CANCEL"));
        }
        let mut bytes = Vec::with_capacity(Self::LEN);
        bytes.extend(self.arm_epoch.to_le_bytes());
        bytes.extend(self.client_tag.to_le_bytes());
        Ok(bytes)
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, PayloadError> {
        exact_len(bytes, Self::LEN)?;
        let value = Self {
            arm_epoch: u32_at(bytes, 0),
            client_tag: u32_at(bytes, 4),
        };
        value.encode()?;
        Ok(value)
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CanTxCancelResponse {
    pub client_tag: u32,
    pub cancel_state: u32,
}

impl CanTxCancelResponse {
    pub const LEN: usize = 8;

    pub fn encode(&self) -> Result<Vec<u8>, PayloadError> {
        if !(1..=3).contains(&self.cancel_state) {
            return Err(PayloadError::InvalidValue("CAN_TX_CANCEL response"));
        }
        let mut bytes = Vec::with_capacity(Self::LEN);
        bytes.extend(self.client_tag.to_le_bytes());
        bytes.extend(self.cancel_state.to_le_bytes());
        Ok(bytes)
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, PayloadError> {
        exact_len(bytes, Self::LEN)?;
        let value = Self {
            client_tag: u32_at(bytes, 0),
            cancel_state: u32_at(bytes, 4),
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

    #[test]
    fn set_clear_filters_vectors_match_golden() {
        let set = SetFiltersRequest {
            channel: 0,
            expected_generation: 5,
            rules: vec![
                FilterRule {
                    id: 0x123,
                    mask: 0x7ff,
                    flags: 0x0004,
                },
                FilterRule {
                    id: 0x1fff_ffff,
                    mask: 0x1fff_ffff,
                    flags: 0x0001,
                },
            ],
        };
        assert_vector(
            Frame::request(0x0014, 20, set.encode().unwrap()),
            include_str!("../../../../protocol/v1/0/set-filters-request.hex"),
        );
        assert_vector(
            response(
                0x0014,
                20,
                SetFiltersResponse {
                    applied_generation: 6,
                    applied_count: 2,
                }
                .encode()
                .unwrap(),
            ),
            include_str!("../../../../protocol/v1/0/set-filters-response.hex"),
        );
        assert_vector(
            Frame::request(
                0x0015,
                21,
                ClearFiltersRequest {
                    channel: 1,
                    expected_generation: 6,
                }
                .encode()
                .unwrap(),
            ),
            include_str!("../../../../protocol/v1/0/clear-filters-request.hex"),
        );
        assert_vector(
            response(
                0x0015,
                21,
                ClearFiltersResponse {
                    applied_generation: 7,
                }
                .encode()
                .unwrap(),
            ),
            include_str!("../../../../protocol/v1/0/clear-filters-response.hex"),
        );
    }

    #[test]
    fn tx_arm_disarm_vectors_match_golden() {
        let arm = TxArmRequest {
            expected_config_generation: 4,
            timeout_ms: 5000,
            max_frames_per_s: 1000,
            max_bus_load_permille: 900,
            rules: vec![TxRule {
                channel: 0,
                allowed_flag_mask: 0x0f,
                id: 0x321,
                id_mask: 0x7ff,
                max_frames_per_s: 500,
            }],
        };
        assert_vector(
            Frame::request(0x0020, 22, arm.encode().unwrap()),
            include_str!("../../../../protocol/v1/0/tx-arm-request.hex"),
        );
        assert_vector(
            response(
                0x0020,
                22,
                TxArmResponse {
                    applied_config_generation: 5,
                    arm_epoch: 3,
                    expiry_tick: 123_456,
                }
                .encode()
                .unwrap(),
            ),
            include_str!("../../../../protocol/v1/0/tx-arm-response.hex"),
        );
        let disarm = TxDisarmRequest {
            expected_config_generation: 5,
            arm_epoch: 3,
            reason: disarm_reason::HOST,
        };
        assert_vector(
            Frame::request(0x0021, 23, disarm.encode().unwrap()),
            include_str!("../../../../protocol/v1/0/tx-disarm-request.hex"),
        );
        assert_vector(
            response(
                0x0021,
                23,
                TxDisarmResponse {
                    applied_config_generation: 6,
                    new_arm_epoch: 4,
                    cancelled_count: 2,
                }
                .encode()
                .unwrap(),
            ),
            include_str!("../../../../protocol/v1/0/tx-disarm-response.hex"),
        );
    }

    #[test]
    fn can_tx_and_cancel_vectors_match_golden() {
        let can_tx = CanTxRequest {
            channel: 0,
            dlc: 8,
            can_flags: 0x0001,
            id: 0x1ff,
            arm_epoch: 3,
            client_tag: 42,
            deadline_tick: 0,
            payload: vec![0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88],
        };
        assert_vector(
            Frame::request(0x0022, 24, can_tx.encode().unwrap()),
            include_str!("../../../../protocol/v1/0/can-tx-request.hex"),
        );
        assert_vector(
            response(
                0x0022,
                24,
                CanTxResponse {
                    client_tag: 42,
                    queue_generation: 7,
                    tx_state: tx_state::PENDING,
                    final_result: 0,
                    final_tick: 0,
                    can_error: 0,
                }
                .encode()
                .unwrap(),
            ),
            include_str!("../../../../protocol/v1/0/can-tx-response.hex"),
        );
        assert_vector(
            Frame::request(
                0x0023,
                25,
                CanTxCancelRequest {
                    arm_epoch: 3,
                    client_tag: 42,
                }
                .encode()
                .unwrap(),
            ),
            include_str!("../../../../protocol/v1/0/can-tx-cancel-request.hex"),
        );
        assert_vector(
            response(
                0x0023,
                25,
                CanTxCancelResponse {
                    client_tag: 42,
                    cancel_state: 1,
                }
                .encode()
                .unwrap(),
            ),
            include_str!("../../../../protocol/v1/0/can-tx-cancel-response.hex"),
        );
    }

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

    #[test]
    fn set_and_clear_filters_round_trip_and_validation() {
        let rules = vec![
            FilterRule {
                id: 0x123,
                mask: 0x7ff,
                flags: 0x0004, // INVERT
            },
            FilterRule {
                id: 0x1fff_ffff,
                mask: 0x1fff_ffff,
                flags: 0x0001, // EXT_ONLY
            },
        ];
        let set = SetFiltersRequest {
            channel: 0,
            expected_generation: 5,
            rules: rules.clone(),
        };
        let payload = set.encode().unwrap();
        assert_eq!(payload.len(), 8 + 24);
        assert_eq!(SetFiltersRequest::decode(&payload).unwrap(), set);

        let response = SetFiltersResponse {
            applied_generation: 6,
            applied_count: 2,
        };
        let response_payload = response.encode().unwrap();
        assert_eq!(
            SetFiltersResponse::decode(&response_payload).unwrap(),
            response
        );

        let clear = ClearFiltersRequest {
            channel: 1,
            expected_generation: 6,
        };
        let clear_payload = clear.encode().unwrap();
        assert_eq!(ClearFiltersRequest::decode(&clear_payload).unwrap(), clear);
        let clear_response = ClearFiltersResponse {
            applied_generation: 7,
        };
        let clear_response_payload = clear_response.encode().unwrap();
        assert_eq!(
            ClearFiltersResponse::decode(&clear_response_payload).unwrap(),
            clear_response
        );

        let mut invalid = set;
        invalid.rules[0].flags = 0x0008;
        assert!(invalid.encode().is_err());
        invalid.rules[0].flags = 0;
        invalid.rules[0].id = 0x2000_0000;
        assert!(invalid.encode().is_err());
    }

    #[test]
    fn filter_crc_matches_canonical_records() {
        let rules = vec![FilterRule {
            id: 0x123,
            mask: 0x7ff,
            flags: 0,
        }];
        let crc = filter_crc32c(&rules);
        assert_eq!(
            crc,
            crate::crc32c(&[
                0x23, 0x01, 0x00, 0x00, 0xff, 0x07, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00
            ])
        );
        // Empty set has a fixed, deterministic CRC (crc32c of the empty input).
        let empty_crc = filter_crc32c(&[]);
        assert_eq!(filter_crc32c(&[]), empty_crc);
        assert_eq!(empty_crc, crate::crc32c(&[]));
    }

    #[test]
    fn tx_arm_disarm_round_trip_and_limits() {
        let arm = TxArmRequest {
            expected_config_generation: 4,
            timeout_ms: 5000,
            max_frames_per_s: 1000,
            max_bus_load_permille: 900,
            rules: vec![TxRule {
                channel: 0,
                allowed_flag_mask: 0x000f,
                id: 0x321,
                id_mask: 0x7ff,
                max_frames_per_s: 500,
            }],
        };
        let payload = arm.encode().unwrap();
        assert_eq!(payload.len(), 16 + 16);
        assert_eq!(TxArmRequest::decode(&payload).unwrap(), arm);

        let arm_response = TxArmResponse {
            applied_config_generation: 5,
            arm_epoch: 3,
            expiry_tick: 123_456,
        };
        let response_payload = arm_response.encode().unwrap();
        assert_eq!(
            TxArmResponse::decode(&response_payload).unwrap(),
            arm_response
        );

        let disarm = TxDisarmRequest {
            expected_config_generation: 5,
            arm_epoch: 3,
            reason: disarm_reason::HOST,
        };
        let disarm_payload = disarm.encode().unwrap();
        assert_eq!(TxDisarmRequest::decode(&disarm_payload).unwrap(), disarm);
        let disarm_response = TxDisarmResponse {
            applied_config_generation: 6,
            new_arm_epoch: 4,
            cancelled_count: 2,
        };
        let disarm_response_payload = disarm_response.encode().unwrap();
        assert_eq!(
            TxDisarmResponse::decode(&disarm_response_payload).unwrap(),
            disarm_response
        );

        let mut invalid = arm;
        invalid.timeout_ms = 99;
        assert!(invalid.encode().is_err());
        invalid.timeout_ms = 5000;
        invalid.max_bus_load_permille = 1001;
        assert!(invalid.encode().is_err());
        invalid.max_bus_load_permille = 0;
        invalid.rules.push(invalid.rules[0].clone());
        invalid
            .rules
            .extend(std::iter::repeat_n(invalid.rules[0].clone(), 15));
        assert!(invalid.encode().is_err());

        let mut bad_disarm = disarm;
        bad_disarm.reason = 0;
        assert!(bad_disarm.encode().is_err());
        bad_disarm.reason = 7;
        assert!(bad_disarm.encode().is_err());
    }

    #[test]
    fn can_tx_round_trip_and_ledger_snapshot() {
        let request = CanTxRequest {
            channel: 0,
            dlc: 8,
            can_flags: 0x0001, // EXT
            id: 0x1ff,
            arm_epoch: 3,
            client_tag: 42,
            deadline_tick: 0, // immediate
            payload: vec![0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88],
        };
        let payload = request.encode().unwrap();
        assert_eq!(payload.len(), 28 + 8);
        assert_eq!(CanTxRequest::decode(&payload).unwrap(), request);

        let pending = CanTxResponse {
            client_tag: 42,
            queue_generation: 7,
            tx_state: tx_state::PENDING,
            final_result: 0,
            final_tick: 0,
            can_error: 0,
        };
        let pending_payload = pending.encode().unwrap();
        assert_eq!(CanTxResponse::decode(&pending_payload).unwrap(), pending);

        let final_snapshot = CanTxResponse {
            client_tag: 42,
            queue_generation: 8,
            tx_state: tx_state::FINAL,
            final_result: can_tx_result::SENT,
            final_tick: 555,
            can_error: 0,
        };
        let final_payload = final_snapshot.encode().unwrap();
        assert_eq!(
            CanTxResponse::decode(&final_payload).unwrap(),
            final_snapshot
        );

        let cancel = CanTxCancelRequest {
            arm_epoch: 3,
            client_tag: 42,
        };
        let cancel_payload = cancel.encode().unwrap();
        assert_eq!(CanTxCancelRequest::decode(&cancel_payload).unwrap(), cancel);
        let cancel_response = CanTxCancelResponse {
            client_tag: 42,
            cancel_state: cancel_state::CANCELLED,
        };
        let cancel_response_payload = cancel_response.encode().unwrap();
        assert_eq!(
            CanTxCancelResponse::decode(&cancel_response_payload).unwrap(),
            cancel_response
        );

        let mut invalid_request = request;
        invalid_request.can_flags = 0x0020; // ERROR_FRAME forbidden on TX
        assert!(invalid_request.encode().is_err());
        invalid_request.can_flags = 0x0001;
        invalid_request.arm_epoch = 0;
        assert!(invalid_request.encode().is_err());
        invalid_request.arm_epoch = 3;
        invalid_request.payload = vec![0; 9]; // Classic DLC 8 mismatch
        assert!(invalid_request.encode().is_err());

        let mut invalid_snapshot = pending;
        invalid_snapshot.queue_generation = 0;
        assert!(invalid_snapshot.encode().is_err());
        invalid_snapshot.queue_generation = 7;
        invalid_snapshot.tx_state = 3;
        assert!(invalid_snapshot.encode().is_err());
        invalid_snapshot.tx_state = tx_state::FINAL;
        invalid_snapshot.final_result = can_tx_result::SENT;
        invalid_snapshot.final_tick = 1;
        invalid_snapshot.can_error = 0x1000_0000; // unlisted bit
        assert!(invalid_snapshot.encode().is_err());

        let mut invalid_cancel = cancel;
        invalid_cancel.arm_epoch = 0;
        assert!(invalid_cancel.encode().is_err());
        let mut invalid_cancel_response = cancel_response;
        invalid_cancel_response.cancel_state = 0;
        assert!(invalid_cancel_response.encode().is_err());
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
