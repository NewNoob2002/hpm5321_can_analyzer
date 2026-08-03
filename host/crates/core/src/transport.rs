use std::fmt;
use std::time::Duration;

use hpm_usb_can_protocol::{CodecError, Frame};

/// Transport-level errors. The host core maps every backend failure onto this
/// set so the CLI can produce stable exit codes (PRD Phase 6).
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum TransportError {
    /// No device matched the requested identity.
    NoDevice(String),
    /// The device disappeared mid-session (hotplug / re-enumeration).
    Disconnected,
    /// A frame failed to encode or decode.
    Frame(CodecError),
    /// The read timed out without a complete frame.
    Timeout,
    /// Backend-specific I/O failure.
    Io(String),
    /// The backend does not implement the requested operation.
    Unsupported(String),
}

impl fmt::Display for TransportError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::NoDevice(what) => write!(f, "no device: {what}"),
            Self::Disconnected => write!(f, "device disconnected"),
            Self::Frame(error) => write!(f, "frame error: {error}"),
            Self::Timeout => write!(f, "transport timeout"),
            Self::Io(error) => write!(f, "io error: {error}"),
            Self::Unsupported(what) => write!(f, "unsupported: {what}"),
        }
    }
}

impl std::error::Error for TransportError {}

impl From<CodecError> for TransportError {
    fn from(error: CodecError) -> Self {
        Self::Frame(error)
    }
}

/// A bidirectional, frame-oriented transport to the analyzer device.
///
/// Implementations are responsible for USB framing/reassembly, so the client
/// only ever exchanges decoded [`Frame`]s. The `fake` backend speaks the same
/// wire contract in memory; `usb` wraps libusb.
pub trait Transport {
    /// Stable identity of the current device connection (backend-specific).
    fn device_id(&self) -> &str;

    /// Encode and transmit one frame.
    fn write_frame(&mut self, frame: &Frame) -> Result<(), TransportError>;

    /// Block until one complete frame arrives or `timeout` elapses.
    fn read_frame(&mut self, timeout: Duration) -> Result<Frame, TransportError>;

    /// Force a connection reset (simulates device reboot / re-enumeration).
    /// The peer must be re-negotiated (HELLO) afterwards.
    fn reset(&mut self) -> Result<(), TransportError>;
}
