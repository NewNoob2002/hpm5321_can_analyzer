use std::env;
use std::process::ExitCode;
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use hpm_usb_can_core::usb::UsbTransport;
use hpm_usb_can_core::{Transport, TransportError};
use hpm_usb_can_protocol::payload::{
    Capabilities, DeviceInfo, HelloRequest, PingRequest, PingResponse,
};
use hpm_usb_can_protocol::payload_control::Diagnostics;
use hpm_usb_can_protocol::{Frame, flags, msg};

const TIMEOUT: Duration = Duration::from_secs(3);

fn request(message_type: u16, sequence: u32, payload: Vec<u8>) -> Frame {
    Frame {
        major: 1,
        minor: 0,
        flags: flags::REQUEST,
        message_type,
        status: 0,
        sequence,
        payload,
    }
}

fn transact(
    transport: &mut UsbTransport,
    message_type: u16,
    sequence: u32,
) -> Result<Frame, TransportError> {
    transport.write_frame(&request(message_type, sequence, Vec::new()))?;
    let response = transport.read_frame(TIMEOUT)?;
    if response.flags != flags::RESPONSE
        || response.message_type != message_type
        || response.sequence != sequence
        || response.status != 0
    {
        return Err(TransportError::Protocol(format!(
            "unexpected response type=0x{:04x} flags=0x{:02x} status={} sequence={}",
            response.message_type, response.flags, response.status, response.sequence
        )));
    }
    Ok(response)
}

fn open() -> Result<(UsbTransport, hpm_usb_can_protocol::payload::HelloResponse), TransportError> {
    let mut transport = UsbTransport::open_default()?;
    let hello = transport.negotiate(
        1,
        &HelloRequest {
            min_major: 1,
            max_major: 1,
            min_minor: 0,
            max_minor: 0,
            host_max_message: 65_536,
            host_features: 0,
        },
        TIMEOUT,
    )?;
    Ok((transport, hello))
}

fn protocol_smoke() -> Result<(), Box<dyn std::error::Error>> {
    let (mut transport, hello) = open()?;

    let device = DeviceInfo::decode(&transact(&mut transport, msg::GET_DEVICE_INFO, 2)?.payload)?;
    let capabilities =
        Capabilities::decode(&transact(&mut transport, msg::GET_CAPABILITIES, 3)?.payload)?;
    let diagnostics =
        Diagnostics::decode(&transact(&mut transport, msg::GET_DIAGNOSTICS, 4)?.payload)?;
    let channel = capabilities
        .channels
        .first()
        .ok_or("device reported no CAN channels")?;
    let channel_diagnostics = diagnostics
        .channels
        .first()
        .ok_or("device reported no channel diagnostics")?;

    println!(
        "PASS protocol=1.0 session_id={} max_message={} firmware={} build_id={} board={} serial={} \
         usb_mode={} tick_hz={} channel={} mode_mask=0x{:02x} nominal_min={} nominal_max={} \
         diag_generation={} usb_rx_bytes={} usb_tx_bytes={} rx_frames={} tx_frames={} dropped={} \
         bus_off_count={} error_count={}",
        hello.session_id,
        hello.max_message,
        device.firmware_semver,
        device.build_id,
        device.board_id,
        device.serial,
        capabilities.usb_mode,
        capabilities.tick_hz,
        channel.channel,
        channel.mode_mask,
        channel.nominal_min,
        channel.nominal_max,
        diagnostics.generation,
        diagnostics.usb_rx_bytes,
        diagnostics.usb_tx_bytes,
        channel_diagnostics.rx_frames,
        channel_diagnostics.tx_frames,
        channel_diagnostics.dropped,
        channel_diagnostics.bus_off_count,
        channel_diagnostics.error_count,
    );
    Ok(())
}

fn ping_frame(sequence: u32, sample_id: u32) -> Frame {
    let host_send_ns = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos() as u64;
    request(
        msg::PING,
        sequence,
        PingRequest {
            host_send_ns,
            sample_id,
        }
        .encode(),
    )
}

fn validate_ping(response: Frame, sequence: u32, sample_id: u32) -> Result<(), TransportError> {
    if response.flags != flags::RESPONSE
        || response.message_type != msg::PING
        || response.sequence != sequence
        || response.status != 0
    {
        return Err(TransportError::Protocol(
            "invalid PING response envelope".into(),
        ));
    }
    let ping = PingResponse::decode(&response.payload)
        .map_err(|error| TransportError::Protocol(error.to_string()))?;
    if ping.sample_id != sample_id || ping.device_tx_tick < ping.device_rx_tick {
        return Err(TransportError::Protocol(
            "invalid PING response payload".into(),
        ));
    }
    Ok(())
}

fn backpressure(delay: Duration) -> Result<(), Box<dyn std::error::Error>> {
    let (mut transport, hello) = open()?;
    transport.write_frame(&ping_frame(2, 1))?;
    thread::sleep(delay);
    validate_ping(transport.read_frame(TIMEOUT)?, 2, 1)?;
    transport.write_frame(&ping_frame(3, 2))?;
    validate_ping(transport.read_frame(TIMEOUT)?, 3, 2)?;
    let diagnostics =
        Diagnostics::decode(&transact(&mut transport, msg::GET_DIAGNOSTICS, 4)?.payload)?;
    println!(
        "PASS backpressure_pause_ms={} session_id={} diag_generation={} usb_rx_bytes={} \
         usb_tx_bytes={} response_depth={} event_depth={} data_depth={}",
        delay.as_millis(),
        hello.session_id,
        diagnostics.generation,
        diagnostics.usb_rx_bytes,
        diagnostics.usb_tx_bytes,
        diagnostics.response_depth,
        diagnostics.event_depth,
        diagnostics.data_depth,
    );
    Ok(())
}

fn percentile(sorted: &[u128], percentile: usize) -> u128 {
    let rank = (percentile * sorted.len()).div_ceil(100).max(1);
    sorted[rank - 1]
}

fn ping_soak(duration: Duration) -> Result<(), Box<dyn std::error::Error>> {
    let (mut transport, hello) = open()?;
    let started = Instant::now();
    let mut sequence = 2u32;
    let mut samples = Vec::new();
    while started.elapsed() < duration {
        let sample_id = sequence - 1;
        let request_started = Instant::now();
        transport.write_frame(&ping_frame(sequence, sample_id))?;
        validate_ping(transport.read_frame(TIMEOUT)?, sequence, sample_id)?;
        samples.push(request_started.elapsed().as_micros());
        sequence = sequence.wrapping_add(1);
    }
    samples.sort_unstable();
    let diagnostics =
        Diagnostics::decode(&transact(&mut transport, msg::GET_DIAGNOSTICS, sequence)?.payload)?;
    println!(
        "PASS ping_soak elapsed_s={:.3} samples={} session_id={} rtt_us_p50={} rtt_us_p95={} \
         rtt_us_p99={} rtt_us_max={} usb_rx_bytes={} usb_tx_bytes={} dropped={} bus_off_count={} \
         error_count={}",
        started.elapsed().as_secs_f64(),
        samples.len(),
        hello.session_id,
        percentile(&samples, 50),
        percentile(&samples, 95),
        percentile(&samples, 99),
        samples.last().copied().unwrap_or_default(),
        diagnostics.usb_rx_bytes,
        diagnostics.usb_tx_bytes,
        diagnostics
            .channels
            .iter()
            .map(|channel| channel.dropped)
            .sum::<u64>(),
        diagnostics
            .channels
            .iter()
            .map(|channel| channel.bus_off_count)
            .sum::<u32>(),
        diagnostics
            .channels
            .iter()
            .map(|channel| channel.error_count)
            .sum::<u32>(),
    );
    Ok(())
}

fn parse_seconds(value: Option<String>, default: u64) -> Result<Duration, String> {
    let seconds = value
        .map(|value| value.parse::<u64>())
        .transpose()
        .map_err(|_| "duration must be a positive integer number of seconds".to_owned())?
        .unwrap_or(default);
    if seconds == 0 {
        return Err("duration must be positive".to_owned());
    }
    Ok(Duration::from_secs(seconds))
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = env::args().skip(1);
    match args.next().as_deref() {
        None | Some("smoke") if args.next().is_none() => protocol_smoke(),
        Some("backpressure") => backpressure(parse_seconds(args.next(), 15)?),
        Some("ping-soak") => ping_soak(parse_seconds(args.next(), 60)?),
        _ => Err("usage: protocol_smoke [smoke|backpressure [seconds]|ping-soak [seconds]]".into()),
    }
}

fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("FAIL {error}");
            ExitCode::FAILURE
        }
    }
}
