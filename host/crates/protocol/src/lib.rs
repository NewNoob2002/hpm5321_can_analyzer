#![forbid(unsafe_code)]

use std::fmt;

pub mod payload;
pub mod payload_control;
pub mod payload_events;

pub const MAGIC: [u8; 4] = *b"UCAN";
pub const HEADER_LEN: usize = 24;
pub const PROTOCOL_MAJOR: u8 = 1;
pub const PROTOCOL_MINOR: u8 = 0;

/// Normative message-type registry (protocol v1.0, spec section 2.3).
pub mod msg {
    pub const HELLO: u16 = 0x0001;
    pub const GET_DEVICE_INFO: u16 = 0x0002;
    pub const GET_CAPABILITIES: u16 = 0x0003;
    pub const GET_DIAGNOSTICS: u16 = 0x0004;
    pub const RESET_DIAGNOSTICS: u16 = 0x0005;
    pub const GET_SESSION_STATE: u16 = 0x0006;
    pub const CONFIG_CHANNEL: u16 = 0x0010;
    pub const GET_CHANNEL_CONFIG: u16 = 0x0011;
    pub const START_CAPTURE: u16 = 0x0012;
    pub const STOP_CAPTURE: u16 = 0x0013;
    pub const SET_FILTERS: u16 = 0x0014;
    pub const CLEAR_FILTERS: u16 = 0x0015;
    pub const TX_ARM: u16 = 0x0020;
    pub const TX_DISARM: u16 = 0x0021;
    pub const CAN_TX: u16 = 0x0022;
    pub const CAN_TX_CANCEL: u16 = 0x0023;
    pub const PING: u16 = 0x0030;
    pub const CAN_RX_BATCH: u16 = 0x8001;
    pub const CAN_TX_RESULT: u16 = 0x8002;
    pub const CHANNEL_STATE: u16 = 0x8003;
    pub const FLOW_CONTROL: u16 = 0x8004;
    pub const DATA_LOSS: u16 = 0x8005;
}

pub mod flags {
    pub const REQUEST: u8 = 0x01;
    pub const RESPONSE: u8 = 0x02;
    pub const EVENT: u8 = 0x04;
    pub const ERROR: u8 = 0x08;
    pub const KNOWN: u8 = REQUEST | RESPONSE | EVENT | ERROR;
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Frame {
    pub major: u8,
    pub minor: u8,
    pub flags: u8,
    pub message_type: u16,
    pub status: u16,
    pub sequence: u32,
    pub payload: Vec<u8>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum CodecError {
    FrameTooShort,
    BadMagic,
    UnsupportedHeaderLength(u8),
    PayloadTooLarge { declared: usize, maximum: usize },
    LengthMismatch { declared: usize, actual: usize },
    InvalidFlags(u8),
    InvalidStatus,
    InvalidSequence,
    CrcMismatch { expected: u32, actual: u32 },
}

impl fmt::Display for CodecError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}

impl std::error::Error for CodecError {}

impl Frame {
    pub fn request(message_type: u16, sequence: u32, payload: Vec<u8>) -> Self {
        Self {
            major: PROTOCOL_MAJOR,
            minor: PROTOCOL_MINOR,
            flags: flags::REQUEST,
            message_type,
            status: 0,
            sequence,
            payload,
        }
    }

    pub fn encode(&self, max_message: usize) -> Result<Vec<u8>, CodecError> {
        validate_semantics(self.flags, self.status, self.sequence)?;
        if self.payload.len() > max_message {
            return Err(CodecError::PayloadTooLarge {
                declared: self.payload.len(),
                maximum: max_message,
            });
        }
        let payload_len =
            u32::try_from(self.payload.len()).map_err(|_| CodecError::PayloadTooLarge {
                declared: self.payload.len(),
                maximum: u32::MAX as usize,
            })?;
        let mut bytes = vec![0u8; HEADER_LEN + self.payload.len()];
        bytes[0..4].copy_from_slice(&MAGIC);
        bytes[4] = self.major;
        bytes[5] = self.minor;
        bytes[6] = HEADER_LEN as u8;
        bytes[7] = self.flags;
        bytes[8..10].copy_from_slice(&self.message_type.to_le_bytes());
        bytes[10..12].copy_from_slice(&self.status.to_le_bytes());
        bytes[12..16].copy_from_slice(&self.sequence.to_le_bytes());
        bytes[16..20].copy_from_slice(&payload_len.to_le_bytes());
        bytes[HEADER_LEN..].copy_from_slice(&self.payload);
        let crc = crc32c(&bytes);
        bytes[20..24].copy_from_slice(&crc.to_le_bytes());
        Ok(bytes)
    }
}

pub fn decode(bytes: &[u8], max_message: usize) -> Result<Frame, CodecError> {
    if bytes.len() < HEADER_LEN {
        return Err(CodecError::FrameTooShort);
    }
    if bytes[..4] != MAGIC {
        return Err(CodecError::BadMagic);
    }
    if bytes[6] as usize != HEADER_LEN {
        return Err(CodecError::UnsupportedHeaderLength(bytes[6]));
    }
    let payload_len = u32::from_le_bytes(bytes[16..20].try_into().unwrap()) as usize;
    if payload_len > max_message {
        return Err(CodecError::PayloadTooLarge {
            declared: payload_len,
            maximum: max_message,
        });
    }
    let declared = HEADER_LEN + payload_len;
    if bytes.len() != declared {
        return Err(CodecError::LengthMismatch {
            declared,
            actual: bytes.len(),
        });
    }
    let flags = bytes[7];
    let status = u16::from_le_bytes(bytes[10..12].try_into().unwrap());
    let sequence = u32::from_le_bytes(bytes[12..16].try_into().unwrap());
    validate_semantics(flags, status, sequence)?;

    let expected = u32::from_le_bytes(bytes[20..24].try_into().unwrap());
    let mut canonical = bytes.to_vec();
    canonical[20..24].fill(0);
    let actual = crc32c(&canonical);
    if expected != actual {
        return Err(CodecError::CrcMismatch { expected, actual });
    }

    Ok(Frame {
        major: bytes[4],
        minor: bytes[5],
        flags,
        message_type: u16::from_le_bytes(bytes[8..10].try_into().unwrap()),
        status,
        sequence,
        payload: bytes[HEADER_LEN..].to_vec(),
    })
}

fn validate_semantics(flags: u8, status: u16, sequence: u32) -> Result<(), CodecError> {
    if flags & !flags::KNOWN != 0 {
        return Err(CodecError::InvalidFlags(flags));
    }
    let kind = flags & (flags::REQUEST | flags::RESPONSE | flags::EVENT);
    if !matches!(kind, flags::REQUEST | flags::RESPONSE | flags::EVENT)
        || flags & flags::ERROR != 0 && kind != flags::RESPONSE
    {
        return Err(CodecError::InvalidFlags(flags));
    }
    let error = flags & flags::ERROR != 0;
    if kind != flags::RESPONSE && status != 0 || kind == flags::RESPONSE && (error == (status == 0))
    {
        return Err(CodecError::InvalidStatus);
    }
    if kind == flags::REQUEST && sequence == 0 {
        return Err(CodecError::InvalidSequence);
    }
    Ok(())
}

pub struct StreamDecoder {
    buffer: Vec<u8>,
    max_message: usize,
    discarded: u64,
}

impl StreamDecoder {
    pub fn new(max_message: usize) -> Self {
        Self {
            buffer: Vec::new(),
            max_message,
            discarded: 0,
        }
    }

    pub fn discarded_bytes(&self) -> u64 {
        self.discarded
    }

    pub fn push(&mut self, bytes: &[u8]) -> Vec<Frame> {
        self.buffer.extend_from_slice(bytes);
        let mut frames = Vec::new();
        loop {
            self.align_magic();
            if self.buffer.len() < HEADER_LEN {
                break;
            }
            let payload_len = u32::from_le_bytes(self.buffer[16..20].try_into().unwrap()) as usize;
            if self.buffer[6] as usize != HEADER_LEN || payload_len > self.max_message {
                self.discard_one();
                continue;
            }
            let frame_len = HEADER_LEN + payload_len;
            if self.buffer.len() < frame_len {
                break;
            }
            match decode(&self.buffer[..frame_len], self.max_message) {
                Ok(frame) => {
                    self.buffer.drain(..frame_len);
                    frames.push(frame);
                }
                Err(_) => self.discard_one(),
            }
        }
        frames
    }

    fn align_magic(&mut self) {
        if self.buffer.starts_with(&MAGIC) {
            return;
        }
        if let Some(offset) = self.buffer.windows(MAGIC.len()).position(|w| w == MAGIC) {
            self.buffer.drain(..offset);
            self.discarded += offset as u64;
        } else {
            let keep = self.buffer.len().min(MAGIC.len() - 1);
            let discard = self.buffer.len() - keep;
            self.buffer.drain(..discard);
            self.discarded += discard as u64;
        }
    }

    fn discard_one(&mut self) {
        self.buffer.remove(0);
        self.discarded += 1;
    }
}

pub fn crc32c(bytes: &[u8]) -> u32 {
    let mut crc = 0xffff_ffffu32;
    for byte in bytes {
        crc ^= u32::from(*byte);
        for _ in 0..8 {
            crc = (crc >> 1) ^ (0x82f6_3b78 & 0u32.wrapping_sub(crc & 1));
        }
    }
    !crc
}

#[cfg(test)]
mod tests {
    use super::*;

    fn hello() -> Frame {
        Frame::request(0x0001, 1, vec![1, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0])
    }

    #[test]
    fn crc32c_canonical_check() {
        assert_eq!(crc32c(b"123456789"), 0xe306_9283);
    }

    #[test]
    fn hello_golden_vector_round_trip() {
        let encoded = hello().encode(65_536).unwrap();
        assert_eq!(
            hex(&encoded),
            include_str!("../../../../protocol/v1/0/hello-request.hex").trim()
        );
        assert_eq!(decode(&encoded, 65_536).unwrap(), hello());
    }

    #[test]
    fn fragmented_and_coalesced_streams_decode() {
        let one = hello().encode(65_536).unwrap();
        let two = Frame::request(0x0030, 2, vec![0; 16])
            .encode(65_536)
            .unwrap();
        let mut decoder = StreamDecoder::new(65_536);
        assert!(decoder.push(&one[..7]).is_empty());
        assert!(decoder.push(&one[7..31]).is_empty());
        let mut tail = one[31..].to_vec();
        tail.extend_from_slice(&two);
        assert_eq!(
            decoder.push(&tail),
            vec![hello(), Frame::request(0x0030, 2, vec![0; 16])]
        );
    }

    #[test]
    fn malformed_frame_resynchronizes_to_next_magic() {
        let mut bad = hello().encode(65_536).unwrap();
        bad[20] ^= 1;
        let good = Frame::request(0x0002, 2, vec![]).encode(65_536).unwrap();
        bad.extend_from_slice(&good);
        let mut decoder = StreamDecoder::new(65_536);
        assert_eq!(decoder.push(&bad), vec![Frame::request(0x0002, 2, vec![])]);
        assert!(decoder.discarded_bytes() >= HEADER_LEN as u64);
    }

    #[test]
    fn reserved_flags_and_oversize_are_rejected() {
        let mut frame = hello();
        frame.flags |= 0x10;
        assert_eq!(frame.encode(65_536), Err(CodecError::InvalidFlags(0x11)));
        assert!(matches!(
            hello().encode(4),
            Err(CodecError::PayloadTooLarge { .. })
        ));
    }

    fn hex(bytes: &[u8]) -> String {
        bytes
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<Vec<_>>()
            .join(" ")
    }
}
