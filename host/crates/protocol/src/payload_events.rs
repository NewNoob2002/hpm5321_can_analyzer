use crate::payload::{self, CAN_FLAG_EXT, PayloadError, validate_can_id, validate_can_rx_payload};

/// CAN RX batch event (spec section 6): mixed-channel batch with a 32-byte
/// header followed by tightly packed 20-byte-prefix records.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CanRxBatch {
    pub flags: u16,
    pub base_timestamp: u64,
    pub device_drop_total: u64,
    pub config_generation: u32,
    pub records: Vec<CanRxRecord>,
}

impl CanRxBatch {
    pub const HEADER_LEN: usize = 32;
    const KNOWN_FLAGS: u16 = 0x0001; // DROP_SNAPSHOT_CHANGED

    pub fn encode(&self) -> Result<Vec<u8>, PayloadError> {
        if self.flags & !Self::KNOWN_FLAGS != 0 || self.config_generation == 0 {
            return Err(PayloadError::InvalidValue("CAN RX batch"));
        }
        let record_count = u16::try_from(self.records.len())
            .map_err(|_| PayloadError::InvalidValue("RX batch"))?;
        let record_bytes = u32::try_from(
            self.records
                .iter()
                .map(|record| CanRxRecord::LEN + record.payload.len())
                .sum::<usize>(),
        )
        .map_err(|_| PayloadError::InvalidValue("RX batch size"))?;
        let mut bytes = Vec::with_capacity(Self::HEADER_LEN + record_bytes as usize);
        bytes.extend(record_count.to_le_bytes());
        bytes.extend(self.flags.to_le_bytes());
        bytes.extend(record_bytes.to_le_bytes());
        bytes.extend(self.base_timestamp.to_le_bytes());
        bytes.extend(self.device_drop_total.to_le_bytes());
        bytes.extend(self.config_generation.to_le_bytes());
        bytes.extend([0; 4]);
        debug_assert_eq!(bytes.len(), Self::HEADER_LEN);
        for record in &self.records {
            record.encode_into(&mut bytes)?;
        }
        Ok(bytes)
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, PayloadError> {
        if bytes.len() < Self::HEADER_LEN {
            return Err(PayloadError::InvalidLength {
                expected: Self::HEADER_LEN,
                actual: bytes.len(),
            });
        }
        reserved_zero(&bytes[28..32])?;
        let record_count = u16_at(bytes, 0) as usize;
        let flags = u16_at(bytes, 2);
        let record_bytes = u32_at(bytes, 4) as usize;
        if flags & !Self::KNOWN_FLAGS != 0 {
            return Err(PayloadError::InvalidValue("CAN RX batch flags"));
        }
        exact_len(bytes, Self::HEADER_LEN + record_bytes)?;
        let mut records = Vec::with_capacity(record_count);
        let mut offset = Self::HEADER_LEN;
        let mut counted_bytes = 0usize;
        for _ in 0..record_count {
            // Read the per-record payload length only after confirming the
            // byte that carries it is inside the buffer; a hostile batch can
            // declare a record_count larger than record_bytes describes.
            if offset + 17 > bytes.len() {
                return Err(PayloadError::InvalidLength {
                    expected: offset + 17,
                    actual: bytes.len(),
                });
            }
            let record_len = CanRxRecord::LEN + bytes[offset + 16] as usize;
            let record_end = offset + record_len;
            if record_end > bytes.len() {
                return Err(PayloadError::InvalidLength {
                    expected: record_end,
                    actual: bytes.len(),
                });
            }
            let record = CanRxRecord::decode(&bytes[offset..record_end])?;
            counted_bytes += record_len;
            offset = record_end;
            records.push(record);
        }
        if counted_bytes != record_bytes {
            return Err(PayloadError::InvalidValue("CAN RX batch record bytes"));
        }
        let value = Self {
            flags,
            base_timestamp: u64_at(bytes, 8),
            device_drop_total: u64_at(bytes, 16),
            config_generation: u32_at(bytes, 24),
            records,
        };
        value.encode()?;
        Ok(value)
    }
}

/// Single CAN RX record (spec section 6): 20-byte fixed prefix + payload.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CanRxRecord {
    pub delta_tick: u32,
    pub arbitration_id: u32,
    pub channel_sequence: u32,
    pub flags: u16,
    pub channel: u8,
    pub dlc: u8,
    pub filter_hit: u8,
    pub rx_status: u16,
    pub payload: Vec<u8>,
}

impl CanRxRecord {
    pub const LEN: usize = 20;

    fn encode_into(&self, bytes: &mut Vec<u8>) -> Result<(), PayloadError> {
        if self.flags & !payload::CAN_RX_FLAGS_MASK != 0
            || self.channel_sequence == 0
            || !(0..=3).contains(&self.rx_status)
            || self.payload.len() > 64
        {
            return Err(PayloadError::InvalidValue("CAN RX record"));
        }
        validate_can_id(self.arbitration_id, self.flags & CAN_FLAG_EXT != 0)?;
        validate_can_rx_payload(self.dlc, self.flags, self.payload.len())?;
        bytes.extend(self.delta_tick.to_le_bytes());
        bytes.extend(self.arbitration_id.to_le_bytes());
        bytes.extend(self.channel_sequence.to_le_bytes());
        bytes.extend(self.flags.to_le_bytes());
        bytes.extend([
            self.channel,
            self.dlc,
            self.payload.len() as u8,
            self.filter_hit,
        ]);
        bytes.extend(self.rx_status.to_le_bytes());
        bytes.extend(&self.payload);
        Ok(())
    }

    fn decode(bytes: &[u8]) -> Result<Self, PayloadError> {
        if bytes.len() < Self::LEN {
            return Err(PayloadError::InvalidLength {
                expected: Self::LEN,
                actual: bytes.len(),
            });
        }
        let payload_len = bytes[16] as usize;
        exact_len(bytes, Self::LEN + payload_len)?;
        let value = Self {
            delta_tick: u32_at(bytes, 0),
            arbitration_id: u32_at(bytes, 4),
            channel_sequence: u32_at(bytes, 8),
            flags: u16_at(bytes, 12),
            channel: bytes[14],
            dlc: bytes[15],
            filter_hit: bytes[17],
            rx_status: u16_at(bytes, 18),
            payload: bytes[Self::LEN..].to_vec(),
        };
        let mut sink = Vec::new();
        value.encode_into(&mut sink)?;
        Ok(value)
    }
}

/// CAN_TX_RESULT event (spec section 5.3), 28 bytes.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CanTxResultEvent {
    pub client_tag: u32,
    pub arm_epoch: u32,
    pub result: u16,
    pub hardware_tick: u64,
    pub can_error: u32,
    pub queue_generation: u32,
}

impl CanTxResultEvent {
    pub const LEN: usize = 28;

    pub fn encode(&self) -> Result<Vec<u8>, PayloadError> {
        if self.arm_epoch == 0
            || !(1..=5).contains(&self.result)
            || self.can_error & 0xfff8_0000 != 0
            || self.queue_generation == 0
        {
            return Err(PayloadError::InvalidValue("CAN_TX_RESULT"));
        }
        let mut bytes = Vec::with_capacity(Self::LEN);
        bytes.extend(self.client_tag.to_le_bytes());
        bytes.extend(self.arm_epoch.to_le_bytes());
        bytes.extend(self.result.to_le_bytes());
        bytes.extend([0, 0]);
        bytes.extend(self.hardware_tick.to_le_bytes());
        bytes.extend(self.can_error.to_le_bytes());
        bytes.extend(self.queue_generation.to_le_bytes());
        Ok(bytes)
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, PayloadError> {
        exact_len(bytes, Self::LEN)?;
        reserved_zero(&bytes[6..8])?;
        let value = Self {
            client_tag: u32_at(bytes, 0),
            arm_epoch: u32_at(bytes, 4),
            result: u16_at(bytes, 8),
            hardware_tick: u64_at(bytes, 12),
            can_error: u32_at(bytes, 20),
            queue_generation: u32_at(bytes, 24),
        };
        value.encode()?;
        Ok(value)
    }
}

/// Channel state values (spec section 5.1).
pub mod channel_state {
    pub const DISABLED: u8 = 0;
    pub const LISTEN_ONLY: u8 = 1;
    pub const ACTIVE: u8 = 2;
    pub const ERROR_PASSIVE: u8 = 3;
    pub const BUS_OFF: u8 = 4;
}

/// CHANNEL_STATE event (spec section 5.3), 24 bytes.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ChannelStateEvent {
    pub channel: u8,
    pub state: u8,
    pub reason: u16,
    pub config_generation: u32,
    pub tx_error: u32,
    pub rx_error: u32,
    pub device_tick: u64,
}

impl ChannelStateEvent {
    pub const LEN: usize = 24;
    pub const REASON_CONFIG_APPLIED: u16 = 16;

    pub fn encode(&self) -> Result<Vec<u8>, PayloadError> {
        if self.state > channel_state::BUS_OFF
            || !(1..=6).contains(&self.reason) && self.reason != Self::REASON_CONFIG_APPLIED
            || self.config_generation == 0
        {
            return Err(PayloadError::InvalidValue("CHANNEL_STATE"));
        }
        let mut bytes = Vec::with_capacity(Self::LEN);
        bytes.extend([self.channel, self.state]);
        bytes.extend(self.reason.to_le_bytes());
        bytes.extend(self.config_generation.to_le_bytes());
        bytes.extend(self.tx_error.to_le_bytes());
        bytes.extend(self.rx_error.to_le_bytes());
        bytes.extend(self.device_tick.to_le_bytes());
        Ok(bytes)
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, PayloadError> {
        exact_len(bytes, Self::LEN)?;
        let value = Self {
            channel: bytes[0],
            state: bytes[1],
            reason: u16_at(bytes, 2),
            config_generation: u32_at(bytes, 4),
            tx_error: u32_at(bytes, 8),
            rx_error: u32_at(bytes, 12),
            device_tick: u64_at(bytes, 16),
        };
        value.encode()?;
        Ok(value)
    }
}

/// FLOW_CONTROL event (spec section 5.3), 24 bytes.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FlowControlEvent {
    pub response_depth: u32,
    pub event_depth: u32,
    pub data_depth: u32,
    pub pool_high_water: u32,
    pub device_tick: u64,
}

impl FlowControlEvent {
    pub const LEN: usize = 24;

    pub fn encode(&self) -> Vec<u8> {
        let mut bytes = Vec::with_capacity(Self::LEN);
        bytes.extend(self.response_depth.to_le_bytes());
        bytes.extend(self.event_depth.to_le_bytes());
        bytes.extend(self.data_depth.to_le_bytes());
        bytes.extend(self.pool_high_water.to_le_bytes());
        bytes.extend(self.device_tick.to_le_bytes());
        bytes
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, PayloadError> {
        exact_len(bytes, Self::LEN)?;
        Ok(Self {
            response_depth: u32_at(bytes, 0),
            event_depth: u32_at(bytes, 4),
            data_depth: u32_at(bytes, 8),
            pool_high_water: u32_at(bytes, 12),
            device_tick: u64_at(bytes, 16),
        })
    }
}

/// DATA_LOSS event (spec section 5.3), 40 bytes.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DataLossEvent {
    pub channel: u8,
    pub source: u8,
    pub sequence_domain: u8,
    pub reason: u16,
    pub config_generation: u32,
    pub first_dropped_sequence: u32,
    pub last_dropped_sequence: u32,
    pub dropped_count: u64,
    pub device_tick: u64,
}

impl DataLossEvent {
    pub const LEN: usize = 40;
    const MAX_SOURCE: u8 = 4; // CAN_RING | USB_DATA_QUEUE | STORAGE_QUEUE | USB_EVENT_QUEUE
    const MAX_REASON: u16 = 4; // OVERFLOW | ADMISSION | ENDPOINT_STALL | STORAGE_UNAVAILABLE

    pub fn encode(&self) -> Result<Vec<u8>, PayloadError> {
        if !(1..=2).contains(&self.sequence_domain)
            || self.source == 0
            || self.source > Self::MAX_SOURCE
            || self.reason == 0
            || self.reason > Self::MAX_REASON
            || self.config_generation == 0
        {
            return Err(PayloadError::InvalidValue("DATA_LOSS"));
        }
        let mut bytes = Vec::with_capacity(Self::LEN);
        bytes.extend([self.channel, self.source, self.sequence_domain, 0]);
        bytes.extend(self.reason.to_le_bytes());
        bytes.extend([0, 0]);
        bytes.extend(self.config_generation.to_le_bytes());
        bytes.extend(self.first_dropped_sequence.to_le_bytes());
        bytes.extend(self.last_dropped_sequence.to_le_bytes());
        bytes.extend([0; 4]);
        bytes.extend(self.dropped_count.to_le_bytes());
        bytes.extend(self.device_tick.to_le_bytes());
        Ok(bytes)
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, PayloadError> {
        exact_len(bytes, Self::LEN)?;
        reserved_zero(&bytes[3..4])?;
        reserved_zero(&bytes[6..8])?;
        reserved_zero(&bytes[20..24])?;
        let value = Self {
            channel: bytes[0],
            source: bytes[1],
            sequence_domain: bytes[2],
            reason: u16_at(bytes, 4),
            config_generation: u32_at(bytes, 8),
            first_dropped_sequence: u32_at(bytes, 12),
            last_dropped_sequence: u32_at(bytes, 16),
            dropped_count: u64_at(bytes, 24),
            device_tick: u64_at(bytes, 32),
        };
        value.encode()?;
        Ok(value)
    }
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
    fn rx_batch_vector_matches_golden() {
        let batch = CanRxBatch {
            flags: 0,
            base_timestamp: 1000,
            device_drop_total: 2,
            config_generation: 3,
            records: vec![
                CanRxRecord {
                    delta_tick: 0,
                    arbitration_id: 0x123,
                    channel_sequence: 1,
                    flags: 0x0001,
                    channel: 0,
                    dlc: 8,
                    filter_hit: 0xff,
                    rx_status: 0,
                    payload: vec![1, 2, 3, 4, 5, 6, 7, 8],
                },
                CanRxRecord {
                    delta_tick: 25,
                    arbitration_id: 0x1fff_ffff,
                    channel_sequence: 2,
                    flags: 0x0005,
                    channel: 0,
                    dlc: 12,
                    filter_hit: 3,
                    rx_status: 1,
                    payload: vec![0; 24],
                },
            ],
        };
        assert_vector(
            event_frame(0x8001, batch.encode().unwrap()),
            include_str!("../../../../protocol/v1/0/can-rx-batch.hex"),
        );
    }

    #[test]
    fn tx_result_event_vector_matches_golden() {
        let event = CanTxResultEvent {
            client_tag: 7,
            arm_epoch: 2,
            result: crate::payload_control::can_tx_result::SENT,
            hardware_tick: 1234,
            can_error: 0x0003_0101,
            queue_generation: 5,
        };
        assert_vector(
            event_frame(0x8002, event.encode().unwrap()),
            include_str!("../../../../protocol/v1/0/can-tx-result.hex"),
        );
    }

    #[test]
    fn channel_state_event_vector_matches_golden() {
        let event = ChannelStateEvent {
            channel: 0,
            state: channel_state::ACTIVE,
            reason: ChannelStateEvent::REASON_CONFIG_APPLIED,
            config_generation: 4,
            tx_error: 0,
            rx_error: 1,
            device_tick: 99,
        };
        assert_vector(
            event_frame(0x8003, event.encode().unwrap()),
            include_str!("../../../../protocol/v1/0/channel-state.hex"),
        );
    }

    #[test]
    fn flow_control_event_vector_matches_golden() {
        let event = FlowControlEvent {
            response_depth: 1,
            event_depth: 2,
            data_depth: 3,
            pool_high_water: 4,
            device_tick: 5,
        };
        assert_vector(
            event_frame(0x8004, event.encode()),
            include_str!("../../../../protocol/v1/0/flow-control.hex"),
        );
    }

    #[test]
    fn data_loss_event_vector_matches_golden() {
        let event = DataLossEvent {
            channel: 0,
            source: 1,
            sequence_domain: 2,
            reason: 1,
            config_generation: 3,
            first_dropped_sequence: 10,
            last_dropped_sequence: 12,
            dropped_count: 3,
            device_tick: 456,
        };
        assert_vector(
            event_frame(0x8005, event.encode().unwrap()),
            include_str!("../../../../protocol/v1/0/data-loss.hex"),
        );
    }

    #[test]
    fn rx_batch_round_trip_with_classic_and_fd_records() {
        let batch = CanRxBatch {
            flags: 0,
            base_timestamp: 1000,
            device_drop_total: 2,
            config_generation: 3,
            records: vec![
                CanRxRecord {
                    delta_tick: 0,
                    arbitration_id: 0x123,
                    channel_sequence: 1,
                    flags: 0x0001, // EXT
                    channel: 0,
                    dlc: 8,
                    filter_hit: 0xff,
                    rx_status: 0,
                    payload: vec![1, 2, 3, 4, 5, 6, 7, 8],
                },
                CanRxRecord {
                    delta_tick: 25,
                    arbitration_id: 0x1fffffff,
                    channel_sequence: 2,
                    flags: 0x0005, // EXT | FD
                    channel: 0,
                    dlc: 12,
                    filter_hit: 3,
                    rx_status: 1,
                    payload: vec![0; 24],
                },
            ],
        };
        let encoded = batch.encode().unwrap();
        assert_eq!(encoded.len(), 32 + 28 + 44);
        assert_eq!(CanRxBatch::decode(&encoded).unwrap(), batch);
    }

    #[test]
    fn rx_batch_rejects_bad_payload_rules_and_ids() {
        let mut batch = CanRxBatch {
            flags: 0,
            base_timestamp: 1,
            device_drop_total: 0,
            config_generation: 1,
            records: vec![CanRxRecord {
                delta_tick: 0,
                arbitration_id: 0x800, // exceeds standard range with EXT=0
                channel_sequence: 1,
                flags: 0,
                channel: 0,
                dlc: 8,
                filter_hit: 0xff,
                rx_status: 0,
                payload: vec![0; 8],
            }],
        };
        assert!(batch.encode().is_err());

        batch.records[0].arbitration_id = 0x123;
        batch.records[0].flags = 0x0008; // BRS without FD
        assert!(batch.encode().is_err());

        batch.records[0].flags = 0;
        batch.records[0].dlc = 8;
        batch.records[0].payload = vec![0; 7]; // Classic DLC 8 needs 8 bytes
        assert!(batch.encode().is_err());

        batch.records[0].payload = vec![0; 8];
        assert!(batch.encode().is_ok());
    }

    #[test]
    fn rx_batch_rejects_truncated_records_without_panicking() {
        // record_count=1 but record_bytes=0: the declared total length matches
        // the header, yet the record would run past the end of the buffer.
        let mut bytes = vec![0u8; CanRxBatch::HEADER_LEN];
        bytes[0..2].copy_from_slice(&1u16.to_le_bytes()); // record_count = 1
        // record_bytes stays 0; config_generation must be nonzero for the
        // post-decode re-encode to pass, but we expect failure before that.
        bytes[24..28].copy_from_slice(&1u32.to_le_bytes());
        let result = CanRxBatch::decode(&bytes);
        assert!(result.is_err());

        // count higher than record_bytes: reads run past the header too.
        bytes[0..2].copy_from_slice(&5u16.to_le_bytes());
        assert!(CanRxBatch::decode(&bytes).is_err());
    }

    #[test]
    fn rtr_records_carry_no_payload() {
        let record = CanRxRecord {
            delta_tick: 0,
            arbitration_id: 0x7ff,
            channel_sequence: 1,
            flags: 0x0003, // EXT | RTR
            channel: 1,
            dlc: 4,
            filter_hit: 0xff,
            rx_status: 0,
            payload: vec![],
        };
        let batch = CanRxBatch {
            flags: 0,
            base_timestamp: 0,
            device_drop_total: 0,
            config_generation: 1,
            records: vec![record],
        };
        let encoded = batch.encode().unwrap();
        assert_eq!(CanRxBatch::decode(&encoded).unwrap(), batch);
    }

    #[test]
    fn tx_result_event_validation() {
        let event = CanTxResultEvent {
            client_tag: 7,
            arm_epoch: 2,
            result: crate::payload_control::can_tx_result::SENT,
            hardware_tick: 1234,
            can_error: 0x0003_0101, // TEC=1 REC=1 WARNING=1
            queue_generation: 5,
        };
        let encoded = event.encode().unwrap();
        assert_eq!(CanTxResultEvent::decode(&encoded).unwrap(), event);

        let mut invalid = event;
        invalid.result = 6;
        assert!(invalid.encode().is_err());
        invalid.result = 1;
        invalid.can_error = 0x8000_0000; // unlisted bit set
        assert!(invalid.encode().is_err());
    }

    #[test]
    fn channel_state_reason_registry() {
        let event = ChannelStateEvent {
            channel: 0,
            state: channel_state::ACTIVE,
            reason: ChannelStateEvent::REASON_CONFIG_APPLIED,
            config_generation: 4,
            tx_error: 0,
            rx_error: 1,
            device_tick: 99,
        };
        let encoded = event.encode().unwrap();
        assert_eq!(ChannelStateEvent::decode(&encoded).unwrap(), event);

        let mut invalid = event;
        invalid.reason = 7; // not a disarm value nor CONFIG_APPLIED
        assert!(invalid.encode().is_err());
        invalid.reason = 16;
        invalid.state = 5;
        assert!(invalid.encode().is_err());
    }

    #[test]
    fn flow_control_round_trip() {
        let event = FlowControlEvent {
            response_depth: 1,
            event_depth: 2,
            data_depth: 3,
            pool_high_water: 4,
            device_tick: 5,
        };
        let encoded = event.encode();
        assert_eq!(encoded.len(), 24);
        assert_eq!(FlowControlEvent::decode(&encoded).unwrap(), event);
    }

    #[test]
    fn data_loss_event_validation() {
        let event = DataLossEvent {
            channel: 0,
            source: 1,          // CAN_RING
            sequence_domain: 2, // CHANNEL
            reason: 1,          // OVERFLOW
            config_generation: 3,
            first_dropped_sequence: 10,
            last_dropped_sequence: 12,
            dropped_count: 3,
            device_tick: 456,
        };
        let encoded = event.encode().unwrap();
        assert_eq!(DataLossEvent::decode(&encoded).unwrap(), event);

        let mut invalid = event;
        invalid.sequence_domain = 3;
        assert!(invalid.encode().is_err());
        invalid.sequence_domain = 2;
        invalid.source = 5;
        assert!(invalid.encode().is_err());
        invalid.source = 4;
        invalid.reason = 5;
        assert!(invalid.encode().is_err());
    }

    fn event_frame(message_type: u16, payload: Vec<u8>) -> Frame {
        Frame {
            major: 1,
            minor: 0,
            flags: flags::EVENT,
            message_type,
            status: 0,
            sequence: 1,
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
