//! libusb (rusb) transport backend.
//!
//! Same frame contract as the fake backend. Hardware behaviour (bulk
//! enumeration, transfer, hotplug) is validated by `hpm-usb-smoke`; this
//! module wires the analyzer protocol framing onto the same endpoints so the
//! host client can run against the real device.

use std::collections::VecDeque;
use std::time::Duration;

use hpm_usb_can_protocol::{Frame, StreamDecoder};

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
            id,
        })
    }

    pub fn open_default() -> Result<Self, TransportError> {
        Self::open(DEFAULT_VID, DEFAULT_PID)
    }
}

impl Transport for UsbTransport {
    fn device_id(&self) -> &str {
        &self.id
    }

    fn write_frame(&mut self, frame: &Frame) -> Result<(), TransportError> {
        let bytes = frame.encode(MAX_MESSAGE)?;
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
