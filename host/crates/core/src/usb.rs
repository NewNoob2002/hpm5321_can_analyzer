//! libusb (rusb) transport backend.
//!
//! Same frame contract as the fake backend. Hardware behaviour (bulk
//! enumeration, transfer, hotplug) is validated by `hpm-usb-smoke`; this
//! module wires the analyzer protocol framing onto the same endpoints so the
//! host client can run against the real device.

use std::collections::VecDeque;
use std::time::Duration;

use hpm_usb_can_protocol::{
    Frame, PROTOCOL_MAJOR, PROTOCOL_MINOR, StreamDecoder, flags, msg,
    payload::{HelloRequest, HelloResponse},
    validate_negotiated_version,
};

use crate::transport::{Transport, TransportError};

pub const DEFAULT_VID: u16 = 0x34b7;
pub const DEFAULT_PID: u16 = 0x1236;
pub const INTERFACE: u8 = 0;
pub const EP_OUT: u8 = 0x01;
pub const EP_IN: u8 = 0x81;
const MAX_MESSAGE: usize = 65_536;
const DEFAULT_TIMEOUT: Duration = Duration::from_secs(3);

/// Frame-oriented transport over a claimed vendor-bulk interface.
pub struct UsbTransport {
    handle: rusb::DeviceHandle<rusb::GlobalContext>,
    decoder: StreamDecoder,
    /// Frames decoded from the last bulk read, in wire order (FIFO). A single
    /// read can carry multiple frames; draining in arrival order keeps the
    /// response/event ordering identical to the fake backend.
    pending: VecDeque<Frame>,
    tx_max_message: usize,
    rx_max_message: usize,
    negotiated_version: Option<(u8, u8)>,
    id: String,
}

impl UsbTransport {
    /// Open and claim the vendor-bulk interface of the first matching device.
    pub fn open(vid: u16, pid: u16) -> Result<Self, TransportError> {
        let handle = rusb::open_device_with_vid_pid(vid, pid)
            .ok_or_else(|| TransportError::NoDevice(format!("{vid:04x}:{pid:04x}")))?;
        handle
            .claim_interface(INTERFACE)
            .map_err(|error| TransportError::Io(format!("claim interface: {error}")))?;
        let id =
            handle.device().bus_number().to_string() + ":" + &handle.device().address().to_string();
        Ok(Self {
            handle,
            decoder: StreamDecoder::new(MAX_MESSAGE),
            pending: VecDeque::new(),
            tx_max_message: MAX_MESSAGE,
            rx_max_message: MAX_MESSAGE,
            negotiated_version: None,
            id,
        })
    }

    pub fn open_default() -> Result<Self, TransportError> {
        Self::open(DEFAULT_VID, DEFAULT_PID)
    }

    /// Perform HELLO and atomically install the directional limits/version.
    /// A new negotiation discards buffered frames from any prior USB session.
    pub fn negotiate(
        &mut self,
        sequence: u32,
        request: &HelloRequest,
        timeout: Duration,
    ) -> Result<HelloResponse, TransportError> {
        if self.negotiated_version.is_some() {
            return Err(TransportError::Protocol(
                "USB session is already negotiated; reconnect before changing limits".into(),
            ));
        }
        let rx_limit = usize::try_from(request.host_max_message)
            .map_err(|_| TransportError::Protocol("host_max_message does not fit usize".into()))?;
        if !(256..=MAX_MESSAGE).contains(&rx_limit) {
            return Err(TransportError::Protocol(format!(
                "host receive limit {rx_limit} is outside USB backend bounds"
            )));
        }
        self.pending.clear();
        self.decoder = StreamDecoder::new(rx_limit);
        self.rx_max_message = rx_limit;
        self.tx_max_message = MAX_MESSAGE;
        self.negotiated_version = None;

        let hello = Frame {
            major: PROTOCOL_MAJOR,
            minor: PROTOCOL_MINOR,
            flags: flags::REQUEST,
            message_type: msg::HELLO,
            status: 0,
            sequence,
            payload: request
                .encode()
                .map_err(|error| TransportError::Protocol(error.to_string()))?,
        };
        self.write_frame(&hello)?;
        let response = self.read_frame(timeout)?;
        if response.flags != flags::RESPONSE
            || response.message_type != msg::HELLO
            || response.sequence != sequence
            || response.status != 0
        {
            return Err(TransportError::Protocol(
                "invalid HELLO response envelope".into(),
            ));
        }
        let selected = HelloResponse::decode(&response.payload)
            .map_err(|error| TransportError::Protocol(error.to_string()))?;
        if selected.major < request.min_major
            || selected.major > request.max_major
            || selected.minor < request.min_minor
            || selected.minor > request.max_minor
        {
            return Err(TransportError::Protocol(
                "device selected a version outside the offered range".into(),
            ));
        }
        let tx_limit = usize::try_from(selected.max_message).map_err(|_| {
            TransportError::Protocol("device max_message does not fit usize".into())
        })?;
        if !(256..=MAX_MESSAGE).contains(&tx_limit) {
            return Err(TransportError::Protocol(format!(
                "device receive limit {tx_limit} is outside USB backend bounds"
            )));
        }
        self.tx_max_message = tx_limit;
        self.negotiated_version = Some((selected.major, selected.minor));
        Ok(selected)
    }

    pub fn max_message(&self) -> usize {
        self.tx_max_message
    }

    pub fn receive_max_message(&self) -> usize {
        self.rx_max_message
    }
}

impl Transport for UsbTransport {
    fn device_id(&self) -> &str {
        &self.id
    }

    fn write_frame(&mut self, frame: &Frame) -> Result<(), TransportError> {
        if let Some((major, minor)) = self.negotiated_version {
            validate_negotiated_version(frame, major, minor)?;
        } else if frame.flags != flags::REQUEST
            || !matches!(frame.message_type, msg::HELLO | msg::GET_DEVICE_INFO)
        {
            return Err(TransportError::Protocol(
                "USB session is not negotiated; call UsbTransport::negotiate first".into(),
            ));
        }
        let bytes = frame.encode(self.tx_max_message)?;
        let written = self
            .handle
            .write_bulk(EP_OUT, &bytes, DEFAULT_TIMEOUT)
            .map_err(|error| TransportError::Io(format!("bulk OUT: {error}")))?;
        if written != bytes.len() {
            return Err(TransportError::Io(format!(
                "short bulk OUT: {written}/{}",
                bytes.len()
            )));
        }
        Ok(())
    }

    fn read_frame(&mut self, timeout: Duration) -> Result<Frame, TransportError> {
        loop {
            if let Some(frame) = self.pending.pop_front() {
                if let Some((major, minor)) = self.negotiated_version {
                    validate_negotiated_version(&frame, major, minor)?;
                } else if frame.flags & flags::RESPONSE == 0
                    || !matches!(frame.message_type, msg::HELLO | msg::GET_DEVICE_INFO)
                {
                    return Err(TransportError::Protocol(
                        "received non-bootstrap frame before HELLO negotiation".into(),
                    ));
                }
                return Ok(frame);
            }
            let mut buffer = vec![0u8; 4096];
            let read = self
                .handle
                .read_bulk(EP_IN, &mut buffer, timeout)
                .map_err(map_usb_error)?;
            if read == 0 {
                continue;
            }
            for frame in self.decoder.push(&buffer[..read]) {
                self.pending.push_back(frame);
            }
        }
    }

    fn reset(&mut self) -> Result<(), TransportError> {
        Err(TransportError::Unsupported(
            "usb reset: reboot the device and re-enumerate".to_owned(),
        ))
    }
}

fn map_usb_error(error: rusb::Error) -> TransportError {
    match error {
        rusb::Error::Timeout => TransportError::Timeout,
        rusb::Error::NoDevice | rusb::Error::NotFound => TransportError::Disconnected,
        other => TransportError::Io(other.to_string()),
    }
}
