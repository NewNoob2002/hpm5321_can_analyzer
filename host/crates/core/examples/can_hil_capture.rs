use std::env;
use std::fs::{self, File};
use std::io::{BufWriter, Write};
use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use hpm_usb_can_core::usb::UsbTransport;
use hpm_usb_can_core::{Transport, TransportError};
use hpm_usb_can_protocol::payload::{HelloRequest, PingRequest, PingResponse};
use hpm_usb_can_protocol::payload_control::{
    CaptureRequest, CaptureResponse, Diagnostics, SessionState,
};
use hpm_usb_can_protocol::payload_events::CanRxBatch;
use hpm_usb_can_protocol::{Frame, flags, msg};

const IO_TIMEOUT: Duration = Duration::from_secs(3);
const PING_BURST: u32 = 32;

#[derive(Clone, Copy)]
struct PingSample {
    host_mid_ns: f64,
    device_tick: f64,
    rtt_ns: u64,
}

struct CaptureStats {
    frames: u64,
    batches: u64,
    event_gaps: u64,
    channel_gaps: u64,
    first_channel_sequence: u32,
    last_channel_sequence: u32,
    maximum_device_drop_total: u64,
    previous_event_sequence: u32,
    timing_samples: Vec<(u64, u64)>,
}

impl CaptureStats {
    fn new() -> Self {
        Self {
            frames: 0,
            batches: 0,
            event_gaps: 0,
            channel_gaps: 0,
            first_channel_sequence: 0,
            last_channel_sequence: 0,
            maximum_device_drop_total: 0,
            previous_event_sequence: 0,
            timing_samples: Vec::new(),
        }
    }
}

fn now_ns() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos() as u64
}

fn next_nonzero(value: u32) -> u32 {
    value.wrapping_add(1).max(1)
}

fn request(message_type: u16, sequence: u32, payload: Vec<u8>) -> Frame {
    Frame::request(message_type, sequence, payload)
}

fn read_response(
    transport: &mut UsbTransport,
    message_type: u16,
    sequence: u32,
) -> Result<Frame, TransportError> {
    loop {
        let frame = transport.read_frame(IO_TIMEOUT)?;
        if frame.flags & flags::EVENT != 0 {
            continue;
        }
        if frame.flags != flags::RESPONSE
            || frame.message_type != message_type
            || frame.sequence != sequence
            || frame.status != 0
        {
            return Err(TransportError::Protocol(format!(
                "unexpected response type=0x{:04x} flags=0x{:02x} status={} sequence={}",
                frame.message_type, frame.flags, frame.status, frame.sequence
            )));
        }
        return Ok(frame);
    }
}

fn transact(
    transport: &mut UsbTransport,
    message_type: u16,
    sequence: u32,
    payload: Vec<u8>,
) -> Result<Frame, TransportError> {
    transport.write_frame(&request(message_type, sequence, payload))?;
    read_response(transport, message_type, sequence)
}

fn ping(
    transport: &mut UsbTransport,
    sequence: u32,
    sample_id: u32,
) -> Result<PingSample, Box<dyn std::error::Error>> {
    let host_send_ns = now_ns();
    let payload = PingRequest {
        host_send_ns,
        sample_id,
    }
    .encode();
    let response = transact(transport, msg::PING, sequence, payload)?;
    let host_receive_ns = now_ns();
    let ping = PingResponse::decode(&response.payload)?;
    if ping.host_send_ns != host_send_ns || ping.sample_id != sample_id {
        return Err("PING identity mismatch".into());
    }
    Ok(PingSample {
        host_mid_ns: (host_send_ns as f64 + host_receive_ns as f64) / 2.0,
        device_tick: (ping.device_rx_tick as f64 + ping.device_tx_tick as f64) / 2.0,
        rtt_ns: host_receive_ns.saturating_sub(host_send_ns),
    })
}

fn ping_burst(
    transport: &mut UsbTransport,
    sequence: &mut u32,
    samples: &mut Vec<PingSample>,
) -> Result<(), Box<dyn std::error::Error>> {
    for _ in 0..PING_BURST {
        let sample_id = samples.len() as u32 + 1;
        samples.push(ping(transport, *sequence, sample_id)?);
        *sequence = next_nonzero(*sequence);
    }
    Ok(())
}

fn ping_during_capture(
    transport: &mut UsbTransport,
    sequence: u32,
    sample_id: u32,
    stats: &mut CaptureStats,
    raw: &mut BufWriter<File>,
    retain: bool,
) -> Result<PingSample, Box<dyn std::error::Error>> {
    let host_send_ns = now_ns();
    let payload = PingRequest {
        host_send_ns,
        sample_id,
    }
    .encode();
    transport.write_frame(&request(msg::PING, sequence, payload))?;
    let response = loop {
        let frame = transport.read_frame(IO_TIMEOUT)?;
        if frame.flags & flags::EVENT != 0 {
            record_event(frame, stats, raw, retain)?;
            continue;
        }
        if frame.flags != flags::RESPONSE
            || frame.message_type != msg::PING
            || frame.sequence != sequence
            || frame.status != 0
        {
            return Err("invalid PING response envelope during capture".into());
        }
        break frame;
    };
    let host_receive_ns = now_ns();
    let ping = PingResponse::decode(&response.payload)?;
    if ping.host_send_ns != host_send_ns || ping.sample_id != sample_id {
        return Err("PING identity mismatch during capture".into());
    }
    Ok(PingSample {
        host_mid_ns: (host_send_ns as f64 + host_receive_ns as f64) / 2.0,
        device_tick: (ping.device_rx_tick as f64 + ping.device_tx_tick as f64) / 2.0,
        rtt_ns: host_receive_ns.saturating_sub(host_send_ns),
    })
}

fn ping_burst_during_capture(
    transport: &mut UsbTransport,
    sequence: &mut u32,
    samples: &mut Vec<PingSample>,
    stats: &mut CaptureStats,
    raw: &mut BufWriter<File>,
    retain: bool,
) -> Result<(), Box<dyn std::error::Error>> {
    eprintln!("RUNNING capture_ping_burst_start samples={}", samples.len());
    for _ in 0..PING_BURST {
        let sample_id = samples.len() as u32 + 1;
        samples.push(ping_during_capture(
            transport, *sequence, sample_id, stats, raw, retain,
        )?);
        *sequence = next_nonzero(*sequence);
    }
    eprintln!("RUNNING capture_ping_burst_done samples={}", samples.len());
    Ok(())
}

fn fit_clock(samples: &[PingSample]) -> Result<(f64, f64, Vec<u64>), &'static str> {
    if samples.len() < 4 {
        return Err("insufficient PING samples");
    }
    let mut selected = samples.to_vec();
    selected.sort_by_key(|sample| sample.rtt_ns);
    selected.truncate((selected.len() / 4).max(2));
    let x_mean = selected
        .iter()
        .map(|sample| sample.device_tick)
        .sum::<f64>()
        / selected.len() as f64;
    let y_mean = selected
        .iter()
        .map(|sample| sample.host_mid_ns)
        .sum::<f64>()
        / selected.len() as f64;
    let covariance = selected
        .iter()
        .map(|sample| (sample.device_tick - x_mean) * (sample.host_mid_ns - y_mean))
        .sum::<f64>();
    let variance = selected
        .iter()
        .map(|sample| (sample.device_tick - x_mean).powi(2))
        .sum::<f64>();
    if variance == 0.0 {
        return Err("PING device ticks have zero variance");
    }
    let slope = covariance / variance;
    let offset = y_mean - slope * x_mean;
    let mut residuals = selected
        .iter()
        .map(|sample| (sample.host_mid_ns - (offset + slope * sample.device_tick)).abs() as u64)
        .collect::<Vec<_>>();
    residuals.sort_unstable();
    Ok((offset, slope, residuals))
}

fn percentile(sorted: &[u64], percentile: usize) -> u64 {
    if sorted.is_empty() {
        return 0;
    }
    let rank = (percentile * sorted.len()).div_ceil(100).max(1);
    sorted[rank - 1]
}

fn write_ping_csv(path: &Path, samples: &[PingSample]) -> std::io::Result<()> {
    let mut output = BufWriter::new(File::create(path)?);
    writeln!(output, "host_mid_ns,device_tick,rtt_ns")?;
    for sample in samples {
        writeln!(
            output,
            "{:.0},{:.0},{}",
            sample.host_mid_ns, sample.device_tick, sample.rtt_ns
        )?;
    }
    output.flush()
}

fn record_event(
    frame: Frame,
    stats: &mut CaptureStats,
    raw: &mut BufWriter<File>,
    retain: bool,
) -> Result<(), Box<dyn std::error::Error>> {
    if stats.previous_event_sequence != 0
        && frame.sequence != next_nonzero(stats.previous_event_sequence)
    {
        stats.event_gaps += 1;
    }
    stats.previous_event_sequence = frame.sequence;
    if frame.message_type != msg::CAN_RX_BATCH {
        return Ok(());
    }
    let host_ingest_ns = now_ns();
    let batch = CanRxBatch::decode(&frame.payload)?;
    stats.batches += 1;
    stats.maximum_device_drop_total = stats.maximum_device_drop_total.max(batch.device_drop_total);
    for record in batch.records {
        if stats.first_channel_sequence == 0 {
            stats.first_channel_sequence = record.channel_sequence;
        } else if record.channel_sequence != next_nonzero(stats.last_channel_sequence) {
            stats.channel_gaps += 1;
        }
        stats.last_channel_sequence = record.channel_sequence;
        stats.frames += 1;
        let device_tick = batch.base_timestamp.wrapping_add(record.delta_tick as u64);
        stats.timing_samples.push((host_ingest_ns, device_tick));
        if retain {
            writeln!(
                raw,
                "{host_ingest_ns},{device_tick},{},{},{},{},{},{},{}",
                record.channel_sequence,
                record.arbitration_id,
                record.flags,
                record.dlc,
                batch.device_drop_total,
                frame.sequence,
                hex_payload(&record.payload),
            )?;
        }
    }
    Ok(())
}

fn capture_until(
    transport: &mut UsbTransport,
    deadline: Instant,
    raw: &mut BufWriter<File>,
    retain: bool,
    stats: &mut CaptureStats,
) -> Result<(), Box<dyn std::error::Error>> {
    while Instant::now() < deadline {
        let remaining = deadline.saturating_duration_since(Instant::now());
        /* rusb/libusb interprets a zero-millisecond timeout as infinite. A
         * sub-millisecond Duration truncates to zero at the FFI boundary, so
         * end the bounded capture window instead of issuing an unbounded read. */
        if remaining < Duration::from_millis(1) {
            break;
        }
        let timeout = remaining.min(IO_TIMEOUT);
        match transport.read_frame(timeout) {
            Ok(frame) if frame.flags & flags::EVENT != 0 => {
                record_event(frame, stats, raw, retain)?;
            }
            Ok(_) | Err(TransportError::Timeout) => {}
            Err(error) => return Err(error.into()),
        }
    }
    Ok(())
}

fn hex_payload(payload: &[u8]) -> String {
    let mut encoded = String::with_capacity(payload.len() * 2);
    for byte in payload {
        use std::fmt::Write as _;
        let _ = write!(encoded, "{byte:02x}");
    }
    encoded
}

fn parse_args() -> Result<(u64, u64, PathBuf), String> {
    let mut args = env::args().skip(1);
    let warmup = args
        .next()
        .unwrap_or_else(|| "60".to_owned())
        .parse::<u64>()
        .map_err(|_| "warmup seconds must be an integer".to_owned())?;
    let duration = args
        .next()
        .unwrap_or_else(|| "1800".to_owned())
        .parse::<u64>()
        .map_err(|_| "duration seconds must be an integer".to_owned())?;
    let output = PathBuf::from(
        args.next()
            .unwrap_or_else(|| "artifacts/can-hil".to_owned()),
    );
    if warmup == 0 || duration == 0 || args.next().is_some() {
        return Err(
            "usage: can_hil_capture [warmup_seconds] [duration_seconds] [output_dir]".to_owned(),
        );
    }
    Ok((warmup, duration, output))
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let (warmup_seconds, duration_seconds, output_dir) = parse_args()?;
    fs::create_dir_all(&output_dir)?;
    let mut raw = BufWriter::new(File::create(output_dir.join("frames.csv"))?);
    writeln!(
        raw,
        "host_ingest_ns,device_tick,channel_sequence,arbitration_id,flags,dlc,device_drop_total,event_sequence,payload_hex"
    )?;

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
        IO_TIMEOUT,
    )?;
    let mut command_sequence = 2u32;
    let mut pings = Vec::new();
    ping_burst(&mut transport, &mut command_sequence, &mut pings)?;

    let state = SessionState::decode(
        &transact(
            &mut transport,
            msg::GET_SESSION_STATE,
            command_sequence,
            Vec::new(),
        )?
        .payload,
    )?;
    command_sequence = next_nonzero(command_sequence);
    if state.tx_armed {
        return Err("refusing capture because device reports TX armed".into());
    }

    let start = CaptureRequest {
        expected_generation: state.config_generation,
        flags: 0x0007,
    }
    .encode()?;
    let started = CaptureResponse::decode(
        &transact(&mut transport, msg::START_CAPTURE, command_sequence, start)?.payload,
    )?;
    command_sequence = next_nonzero(command_sequence);
    if started.state != 1 {
        return Err("capture did not enter active state".into());
    }

    let mut warmup = CaptureStats::new();
    eprintln!("RUNNING warmup_seconds={warmup_seconds}");
    capture_until(
        &mut transport,
        Instant::now() + Duration::from_secs(warmup_seconds),
        &mut raw,
        false,
        &mut warmup,
    )?;
    eprintln!("RUNNING warmup_complete frames={}", warmup.frames);
    ping_burst_during_capture(
        &mut transport,
        &mut command_sequence,
        &mut pings,
        &mut warmup,
        &mut raw,
        false,
    )?;
    eprintln!("RUNNING measurement_seconds={duration_seconds}");
    let mut measured = CaptureStats::new();
    let measurement_deadline = Instant::now() + Duration::from_secs(duration_seconds);
    while Instant::now() < measurement_deadline {
        let segment_deadline = (Instant::now() + Duration::from_secs(60)).min(measurement_deadline);
        capture_until(
            &mut transport,
            segment_deadline,
            &mut raw,
            true,
            &mut measured,
        )?;
        if Instant::now() < measurement_deadline {
            ping_burst_during_capture(
                &mut transport,
                &mut command_sequence,
                &mut pings,
                &mut measured,
                &mut raw,
                true,
            )?;
        }
    }

    let stop = CaptureRequest {
        expected_generation: started.applied_generation,
        flags: 0,
    }
    .encode()?;
    transport.write_frame(&request(msg::STOP_CAPTURE, command_sequence, stop))?;
    let stop_response = loop {
        let frame = transport.read_frame(IO_TIMEOUT)?;
        if frame.flags & flags::EVENT != 0 {
            record_event(frame, &mut measured, &mut raw, true)?;
            continue;
        }
        if frame.flags != flags::RESPONSE
            || frame.message_type != msg::STOP_CAPTURE
            || frame.sequence != command_sequence
            || frame.status != 0
        {
            return Err("invalid STOP_CAPTURE response".into());
        }
        break frame;
    };
    let stopped = CaptureResponse::decode(&stop_response.payload)?;
    command_sequence = next_nonzero(command_sequence);
    if stopped.state != 0 {
        return Err("capture did not stop".into());
    }
    /* Responses have priority over the data queue. STOP_CAPTURE may therefore
     * arrive before the final batch that it flushed. Drain that bounded tail
     * before issuing post-run PINGs, which intentionally ignore async events. */
    capture_until(
        &mut transport,
        Instant::now() + Duration::from_millis(100),
        &mut raw,
        true,
        &mut measured,
    )?;
    ping_burst(&mut transport, &mut command_sequence, &mut pings)?;
    let diagnostics = Diagnostics::decode(
        &transact(
            &mut transport,
            msg::GET_DIAGNOSTICS,
            command_sequence,
            Vec::new(),
        )?
        .payload,
    )?;
    raw.flush()?;
    write_ping_csv(&output_dir.join("pings.csv"), &pings)?;

    let (offset, slope, residuals) = fit_clock(&pings)?;
    let mut latency_ns = measured
        .timing_samples
        .iter()
        .map(|(host_ingest_ns, device_tick)| {
            (*host_ingest_ns as f64 - (offset + slope * *device_tick as f64)).max(0.0) as u64
        })
        .collect::<Vec<_>>();
    latency_ns.sort_unstable();
    let expected_slope = 1_000_000_000.0 / 24_000_000.0;
    let drift_ppm = (slope / expected_slope - 1.0) * 1_000_000.0;
    let channel_drops = diagnostics
        .channels
        .iter()
        .map(|channel| channel.dropped)
        .sum::<u64>();
    let host_acceptance = measured.frames >= 6000 * duration_seconds
        && measured.event_gaps == 0
        && measured.channel_gaps == 0
        && measured.maximum_device_drop_total == 0
        && channel_drops == 0
        && percentile(&latency_ns, 95) <= 5_000_000
        && percentile(&residuals, 95) <= 1_000_000;
    let summary = format!(
        concat!(
            "{{\n  \"status\": \"{}\",\n  \"session_id\": {},\n  \"warmup_seconds\": {},\n",
            "  \"duration_seconds\": {},\n  \"frames\": {},\n  \"batches\": {},\n",
            "  \"frames_per_second\": {:.3},\n  \"event_gaps\": {},\n  \"channel_gaps\": {},\n",
            "  \"first_channel_sequence\": {},\n  \"last_channel_sequence\": {},\n",
            "  \"device_drop_total\": {},\n  \"diagnostic_channel_drops\": {},\n",
            "  \"latency_ns_p50\": {},\n  \"latency_ns_p95\": {},\n  \"latency_ns_p99\": {},\n",
            "  \"fit_residual_ns_p95\": {},\n  \"clock_slope_ns_per_tick\": {:.9},\n",
            "  \"clock_offset_ns\": {:.3},\n  \"clock_drift_ppm\": {:.3},\n",
            "  \"host_acceptance\": {},\n  \"external_analyzer_reconciliation\": \"PENDING\",\n",
            "  \"mcan_ring_hwm_snapshot\": \"PENDING\",\n  \"tx_armed_before_capture\": false,\n",
            "  \"tx_operations_issued\": 0\n}}\n"
        ),
        if host_acceptance { "PARTIAL" } else { "FAIL" },
        hello.session_id,
        warmup_seconds,
        duration_seconds,
        measured.frames,
        measured.batches,
        measured.frames as f64 / duration_seconds as f64,
        measured.event_gaps,
        measured.channel_gaps,
        measured.first_channel_sequence,
        measured.last_channel_sequence,
        measured.maximum_device_drop_total,
        channel_drops,
        percentile(&latency_ns, 50),
        percentile(&latency_ns, 95),
        percentile(&latency_ns, 99),
        percentile(&residuals, 95),
        slope,
        offset,
        drift_ppm,
        host_acceptance,
    );
    fs::write(output_dir.join("summary.json"), &summary)?;
    print!("{summary}");
    if !host_acceptance {
        return Err("host-side frozen CAN HIL acceptance criteria were not met".into());
    }
    Ok(())
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
