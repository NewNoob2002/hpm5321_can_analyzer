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
    CaptureRequest, CaptureResponse, Diagnostics, McanDiagnostics, SessionState,
};
use hpm_usb_can_protocol::payload_events::{CanRxBatch, ChannelStateEvent, DataLossEvent};
use hpm_usb_can_protocol::{Frame, flags, msg};

const IO_TIMEOUT: Duration = Duration::from_secs(3);
const PING_BURST: u32 = 32;
const CONTROL_RETRY_ATTEMPTS: usize = 3;

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
    intra_batch_discontinuities: u64,
    cross_batch_discontinuities: u64,
    forward_missing_records: u64,
    backward_or_duplicate_records: u64,
    first_channel_sequence: u32,
    last_channel_sequence: u32,
    first_device_drop_total: Option<u64>,
    maximum_device_drop_total: u64,
    channel_state_events: u64,
    error_passive_events: u64,
    bus_off_events: u64,
    data_loss_events: u64,
    data_loss_dropped: u64,
    previous_event_sequence: u32,
    previous_channel_sequence: u32,
    timing_samples: Vec<(u64, u64)>,
    tick_window: Option<TickWindow>,
}

#[derive(Clone, Copy)]
struct TickWindow {
    start: u64,
    end: Option<u64>,
}

impl TickWindow {
    fn contains(self, tick: u64) -> bool {
        tick >= self.start && self.end.is_none_or(|end| tick <= end)
    }
}

impl CaptureStats {
    fn new() -> Self {
        Self {
            frames: 0,
            batches: 0,
            event_gaps: 0,
            channel_gaps: 0,
            intra_batch_discontinuities: 0,
            cross_batch_discontinuities: 0,
            forward_missing_records: 0,
            backward_or_duplicate_records: 0,
            first_channel_sequence: 0,
            last_channel_sequence: 0,
            first_device_drop_total: None,
            maximum_device_drop_total: 0,
            channel_state_events: 0,
            error_passive_events: 0,
            bus_off_events: 0,
            data_loss_events: 0,
            data_loss_dropped: 0,
            previous_event_sequence: 0,
            previous_channel_sequence: 0,
            timing_samples: Vec::new(),
            tick_window: None,
        }
    }

    fn measurement(start_tick: u64) -> Self {
        Self {
            tick_window: Some(TickWindow {
                start: start_tick,
                end: None,
            }),
            ..Self::new()
        }
    }

    fn close_measurement_window(&mut self, end_tick: u64) {
        let window = self
            .tick_window
            .as_mut()
            .expect("measurement stats must have a tick window");
        assert!(
            end_tick >= window.start,
            "measurement end tick must not precede start tick"
        );
        window.end = Some(end_tick);
    }

    fn includes_tick(&self, tick: u64) -> bool {
        self.tick_window.is_none_or(|window| window.contains(tick))
    }

    fn device_drop_delta(&self) -> u64 {
        self.first_device_drop_total
            .map(|baseline| self.maximum_device_drop_total.saturating_sub(baseline))
            .unwrap_or(0)
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
) -> Result<PingSample, Box<dyn std::error::Error>> {
    let host_send_ns = now_ns();
    let payload = PingRequest {
        host_send_ns,
        sample_id,
    }
    .encode();
    transport.write_frame(&request(msg::PING, sequence, payload))?;
    let response = read_response_during_capture(transport, msg::PING, sequence, stats, raw, true)?;
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

fn ping_burst_during_capture(
    transport: &mut UsbTransport,
    sequence: &mut u32,
    samples: &mut Vec<PingSample>,
    stats: &mut CaptureStats,
    raw: &mut BufWriter<File>,
) -> Result<(), Box<dyn std::error::Error>> {
    for _ in 0..PING_BURST {
        let sample_id = samples.len() as u32 + 1;
        samples.push(ping_during_capture(
            transport, *sequence, sample_id, stats, raw,
        )?);
        *sequence = next_nonzero(*sequence);
    }
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

fn diagnostics_csv_header() -> &'static str {
    concat!(
        "host_poll_ns,phase,generation,snapshot_tick,state_flags,interrupt_flags,",
        "error_interrupt_flags,last_interrupt_flags,protocol_status,error_count,",
        "transmit_error_count,receive_error_count,rxfifo0_fill_level,",
        "rxfifo0_high_watermark,queue_count,queue_high_watermark,ring_count,",
        "ring_high_watermark,queue_drops,ring_drops,invalid_frames,bus_off_count,",
        "warning_count,error_passive_count,automatic_recovery_attempts"
    )
}

fn write_diagnostics_row<W: Write>(
    output: &mut W,
    host_poll_ns: u64,
    phase: &str,
    diagnostics: &McanDiagnostics,
) -> std::io::Result<()> {
    writeln!(
        output,
        concat!(
            "{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},",
            "{},{},{},{},{},{},{},{},{}"
        ),
        host_poll_ns,
        phase,
        diagnostics.generation,
        diagnostics.snapshot_tick,
        diagnostics.state_flags,
        diagnostics.interrupt_flags,
        diagnostics.error_interrupt_flags,
        diagnostics.last_interrupt_flags,
        diagnostics.protocol_status,
        diagnostics.error_count,
        diagnostics.transmit_error_count,
        diagnostics.receive_error_count,
        diagnostics.rxfifo0_fill_level,
        diagnostics.rxfifo0_high_watermark,
        diagnostics.queue_count,
        diagnostics.queue_high_watermark,
        diagnostics.ring_count,
        diagnostics.ring_high_watermark,
        diagnostics.queue_drops,
        diagnostics.ring_drops,
        diagnostics.invalid_frames,
        diagnostics.bus_off_count,
        diagnostics.warning_count,
        diagnostics.error_passive_count,
        diagnostics.automatic_recovery_attempts,
    )
}

fn read_response_during_capture(
    transport: &mut UsbTransport,
    message_type: u16,
    sequence: u32,
    stats: &mut CaptureStats,
    raw: &mut BufWriter<File>,
    retain: bool,
) -> Result<Frame, Box<dyn std::error::Error>> {
    loop {
        let frame = transport.read_frame(IO_TIMEOUT)?;
        if frame.flags & flags::EVENT != 0 {
            record_event(frame, stats, raw, retain)?;
            continue;
        }
        if frame.flags != flags::RESPONSE
            || frame.message_type != message_type
            || frame.sequence != sequence
            || frame.status != 0
        {
            return Err(format!(
                "unexpected response during capture type=0x{:04x} flags=0x{:02x} status={} sequence={}",
                frame.message_type, frame.flags, frame.status, frame.sequence
            )
            .into());
        }
        return Ok(frame);
    }
}

fn poll_mcan_diagnostics(
    transport: &mut UsbTransport,
    sequence: u32,
    phase: &str,
    diagnostics_csv: &mut BufWriter<File>,
    stats: &mut CaptureStats,
    raw: &mut BufWriter<File>,
    retain: bool,
) -> Result<McanDiagnostics, Box<dyn std::error::Error>> {
    let host_poll_ns = now_ns();
    transport.write_frame(&request(msg::GET_MCAN_DIAGNOSTICS, sequence, Vec::new()))?;
    let response = read_response_during_capture(
        transport,
        msg::GET_MCAN_DIAGNOSTICS,
        sequence,
        stats,
        raw,
        retain,
    )?;
    let diagnostics = McanDiagnostics::decode(&response.payload)?;
    validate_mcan_safety_state(&diagnostics)?;
    write_diagnostics_row(diagnostics_csv, host_poll_ns, phase, &diagnostics)?;
    Ok(diagnostics)
}

fn validate_mcan_safety_state(
    diagnostics: &McanDiagnostics,
) -> Result<(), Box<dyn std::error::Error>> {
    let required = McanDiagnostics::STATE_INITIALIZED
        | McanDiagnostics::STATE_ONLINE
        | McanDiagnostics::STATE_LISTEN_ONLY;
    if diagnostics.state_flags & required != required {
        return Err(format!(
            "refusing capture because MCAN safety state is not initialized+online+listen-only: 0x{:08x}",
            diagnostics.state_flags
        )
        .into());
    }
    if diagnostics.state_flags & McanDiagnostics::STATE_TX_ARMED != 0 {
        return Err("refusing capture because MCAN diagnostics report TX armed".into());
    }
    if diagnostics.automatic_recovery_attempts != 0 {
        return Err(format!(
            "refusing capture because MCAN diagnostics report {} automatic recovery attempts",
            diagnostics.automatic_recovery_attempts
        )
        .into());
    }
    Ok(())
}

fn record_event<W: Write>(
    frame: Frame,
    stats: &mut CaptureStats,
    raw: &mut W,
    retain: bool,
) -> Result<(), Box<dyn std::error::Error>> {
    if stats.previous_event_sequence != 0
        && frame.sequence != next_nonzero(stats.previous_event_sequence)
    {
        stats.event_gaps += 1;
    }
    stats.previous_event_sequence = frame.sequence;
    match frame.message_type {
        msg::CAN_RX_BATCH => {
            let host_ingest_ns = now_ns();
            let batch = CanRxBatch::decode(&frame.payload)?;
            let mut retained_batch = false;
            for (record_index, record) in batch.records.into_iter().enumerate() {
                let device_tick = batch.base_timestamp.wrapping_add(record.delta_tick as u64);
                if stats.previous_channel_sequence != 0
                    && record.channel_sequence != next_nonzero(stats.previous_channel_sequence)
                {
                    stats.channel_gaps += 1;
                    if record_index == 0 {
                        stats.cross_batch_discontinuities += 1;
                    } else {
                        stats.intra_batch_discontinuities += 1;
                    }
                    let expected = next_nonzero(stats.previous_channel_sequence);
                    let delta = record.channel_sequence.wrapping_sub(expected);
                    if delta < 0x8000_0000 {
                        stats.forward_missing_records = stats
                            .forward_missing_records
                            .saturating_add(u64::from(delta));
                    } else {
                        stats.backward_or_duplicate_records += 1;
                    }
                }
                stats.previous_channel_sequence = record.channel_sequence;
                if !stats.includes_tick(device_tick) {
                    continue;
                }
                retained_batch = true;
                if stats.first_channel_sequence == 0 {
                    stats.first_channel_sequence = record.channel_sequence;
                }
                stats.last_channel_sequence = record.channel_sequence;
                stats.frames += 1;
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
            if retained_batch {
                stats.batches += 1;
                if stats.first_device_drop_total.is_none() {
                    stats.first_device_drop_total = Some(batch.device_drop_total);
                }
                stats.maximum_device_drop_total =
                    stats.maximum_device_drop_total.max(batch.device_drop_total);
            }
        }
        msg::CHANNEL_STATE => {
            let event = ChannelStateEvent::decode(&frame.payload)?;
            if stats.includes_tick(event.device_tick) {
                stats.channel_state_events += 1;
                if event.state == hpm_usb_can_protocol::payload_events::channel_state::ERROR_PASSIVE
                {
                    stats.error_passive_events += 1;
                } else if event.state
                    == hpm_usb_can_protocol::payload_events::channel_state::BUS_OFF
                {
                    stats.bus_off_events += 1;
                }
            }
        }
        msg::DATA_LOSS => {
            let event = DataLossEvent::decode(&frame.payload)?;
            if stats.includes_tick(event.device_tick) {
                stats.data_loss_events += 1;
                stats.data_loss_dropped =
                    stats.data_loss_dropped.saturating_add(event.dropped_count);
            }
        }
        _ => {}
    }
    Ok(())
}

fn capture_events_until(
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

#[allow(clippy::too_many_arguments)]
fn capture_with_diagnostics_until(
    transport: &mut UsbTransport,
    deadline: Instant,
    next_diagnostics_poll: &mut Instant,
    phase: &str,
    command_sequence: &mut u32,
    diagnostics_csv: &mut BufWriter<File>,
    raw: &mut BufWriter<File>,
    retain: bool,
    stats: &mut CaptureStats,
) -> Result<(), Box<dyn std::error::Error>> {
    while Instant::now() < deadline {
        let now = Instant::now();
        if now >= *next_diagnostics_poll {
            let _ = poll_mcan_diagnostics(
                transport,
                *command_sequence,
                phase,
                diagnostics_csv,
                stats,
                raw,
                retain,
            )?;
            *command_sequence = next_nonzero(*command_sequence);
            while *next_diagnostics_poll <= Instant::now() {
                *next_diagnostics_poll += Duration::from_secs(1);
            }
            continue;
        }

        let read_deadline = deadline.min(*next_diagnostics_poll);
        let remaining = read_deadline.saturating_duration_since(now);
        if remaining < Duration::from_millis(1) {
            continue;
        }
        match transport.read_frame(remaining.min(IO_TIMEOUT)) {
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
    let mut diagnostics_csv = BufWriter::new(File::create(output_dir.join("diagnostics.csv"))?);
    writeln!(diagnostics_csv, "{}", diagnostics_csv_header())?;

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
    write_ping_csv(&output_dir.join("pings.csv"), &pings)?;

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

    let mut preflight_stats = CaptureStats::new();
    let _ = poll_mcan_diagnostics(
        &mut transport,
        command_sequence,
        "preflight",
        &mut diagnostics_csv,
        &mut preflight_stats,
        &mut raw,
        false,
    )?;
    command_sequence = next_nonzero(command_sequence);

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
    let mut next_diagnostics_poll = Instant::now();
    eprintln!("RUNNING warmup_seconds={warmup_seconds}");
    capture_with_diagnostics_until(
        &mut transport,
        Instant::now() + Duration::from_secs(warmup_seconds),
        &mut next_diagnostics_poll,
        "warmup",
        &mut command_sequence,
        &mut diagnostics_csv,
        &mut raw,
        false,
        &mut warmup,
    )?;
    eprintln!("RUNNING warmup_complete frames={}", warmup.frames);
    let measurement_start_diagnostics = poll_mcan_diagnostics(
        &mut transport,
        command_sequence,
        "measurement_start",
        &mut diagnostics_csv,
        &mut warmup,
        &mut raw,
        false,
    )?;
    command_sequence = next_nonzero(command_sequence);
    eprintln!("RUNNING measurement_seconds={duration_seconds}");
    let mut measured = CaptureStats::measurement(measurement_start_diagnostics.snapshot_tick);
    let measurement_deadline = Instant::now() + Duration::from_secs(duration_seconds);
    while Instant::now() < measurement_deadline {
        let segment_deadline = (Instant::now() + Duration::from_secs(60)).min(measurement_deadline);
        capture_with_diagnostics_until(
            &mut transport,
            segment_deadline,
            &mut next_diagnostics_poll,
            "measurement",
            &mut command_sequence,
            &mut diagnostics_csv,
            &mut raw,
            true,
            &mut measured,
        )?;
    }
    let measurement_end_diagnostics = poll_mcan_diagnostics(
        &mut transport,
        command_sequence,
        "measurement_end",
        &mut diagnostics_csv,
        &mut measured,
        &mut raw,
        true,
    )?;
    measured.close_measurement_window(measurement_end_diagnostics.snapshot_tick);
    command_sequence = next_nonzero(command_sequence);
    raw.flush()?;
    diagnostics_csv.flush()?;
    ping_burst_during_capture(
        &mut transport,
        &mut command_sequence,
        &mut pings,
        &mut measured,
        &mut raw,
    )?;
    write_ping_csv(&output_dir.join("pings.csv"), &pings)?;
    transport.write_frame(&request(msg::GET_DIAGNOSTICS, command_sequence, Vec::new()))?;
    let diagnostics = Diagnostics::decode(
        &read_response_during_capture(
            &mut transport,
            msg::GET_DIAGNOSTICS,
            command_sequence,
            &mut measured,
            &mut raw,
            true,
        )?
        .payload,
    )?;
    command_sequence = next_nonzero(command_sequence);

    let stop = CaptureRequest {
        expected_generation: started.applied_generation,
        flags: 0,
    }
    .encode()?;
    let stop_request = request(msg::STOP_CAPTURE, command_sequence, stop);
    let mut stop_response = None;
    let mut stop_error = None;
    for attempt in 1..=CONTROL_RETRY_ATTEMPTS {
        if let Err(error) = transport.write_frame(&stop_request) {
            stop_error = Some(error.to_string());
        } else {
            loop {
                match transport.read_frame(IO_TIMEOUT) {
                    Ok(frame) if frame.flags & flags::EVENT != 0 => {
                        record_event(frame, &mut measured, &mut raw, true)?;
                    }
                    Ok(frame)
                        if frame.flags == flags::RESPONSE
                            && frame.message_type == msg::STOP_CAPTURE
                            && frame.sequence == command_sequence
                            && frame.status == 0 =>
                    {
                        stop_response = Some(frame);
                        break;
                    }
                    Ok(_) => return Err("invalid STOP_CAPTURE response".into()),
                    Err(error) => {
                        stop_error = Some(error.to_string());
                        break;
                    }
                }
            }
        }
        if stop_response.is_some() {
            break;
        }
        if attempt < CONTROL_RETRY_ATTEMPTS {
            std::thread::sleep(Duration::from_millis(20));
        }
    }
    let Some(stop_response) = stop_response else {
        return Err(format!(
            "STOP_CAPTURE failed after {CONTROL_RETRY_ATTEMPTS} attempts: {}",
            stop_error.unwrap_or_else(|| "unknown transport error".to_owned())
        )
        .into());
    };
    let stopped = CaptureResponse::decode(&stop_response.payload)?;
    if stopped.state != 0 {
        return Err("capture did not stop".into());
    }
    /* Responses have priority over the data queue. STOP_CAPTURE may therefore
     * arrive before the final batch that it flushed. Drain that bounded tail
     * before finalizing the retained measurement artifacts. */
    capture_events_until(
        &mut transport,
        Instant::now() + Duration::from_millis(100),
        &mut raw,
        true,
        &mut measured,
    )?;
    raw.flush()?;
    diagnostics_csv.flush()?;
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
    let measurement_device_drop_delta = measured.device_drop_delta();
    let measurement_queue_drops = measurement_end_diagnostics
        .queue_drops
        .wrapping_sub(measurement_start_diagnostics.queue_drops);
    let measurement_ring_drops = measurement_end_diagnostics
        .ring_drops
        .wrapping_sub(measurement_start_diagnostics.ring_drops);
    let host_acceptance = measured.frames >= 6000 * duration_seconds
        && measured.event_gaps == 0
        && measured.channel_gaps == 0
        && measurement_device_drop_delta == 0
        && measured.data_loss_dropped == 0
        && measurement_queue_drops == 0
        && measurement_ring_drops == 0
        && percentile(&latency_ns, 95) <= 5_000_000
        && percentile(&residuals, 95) <= 1_000_000;
    let summary = format!(
        concat!(
            "{{\n  \"status\": \"{}\",\n  \"session_id\": {},\n  \"warmup_seconds\": {},\n",
            "  \"duration_seconds\": {},\n  \"frames\": {},\n  \"batches\": {},\n",
            "  \"frames_per_second\": {:.3},\n  \"event_gaps\": {},\n  \"channel_gaps\": {},\n",
            "  \"intra_batch_discontinuities\": {},\n  \"cross_batch_discontinuities\": {},\n",
            "  \"forward_missing_records\": {},\n  \"backward_or_duplicate_records\": {},\n",
            "  \"first_channel_sequence\": {},\n  \"last_channel_sequence\": {},\n",
            "  \"device_drop_total\": {},\n  \"device_drop_total_start\": {},\n",
            "  \"device_drop_total_end\": {},\n  \"diagnostic_channel_drops\": {},\n",
            "  \"measurement_queue_drops\": {},\n  \"measurement_ring_drops\": {},\n",
            "  \"measurement_rxfifo0_hwm_start\": {},\n  \"measurement_rxfifo0_hwm_end\": {},\n",
            "  \"measurement_queue_hwm_start\": {},\n  \"measurement_queue_hwm_end\": {},\n",
            "  \"measurement_ring_hwm_start\": {},\n  \"measurement_ring_hwm_end\": {},\n",
            "  \"channel_state_events\": {},\n  \"error_passive_events\": {},\n",
            "  \"bus_off_events\": {},\n  \"data_loss_events\": {},\n",
            "  \"data_loss_dropped\": {},\n",
            "  \"latency_ns_p50\": {},\n  \"latency_ns_p95\": {},\n  \"latency_ns_p99\": {},\n",
            "  \"fit_residual_ns_p95\": {},\n  \"clock_slope_ns_per_tick\": {:.9},\n",
            "  \"clock_offset_ns\": {:.3},\n  \"clock_drift_ppm\": {:.3},\n",
            "  \"host_acceptance\": {},\n  \"external_analyzer_reconciliation\": \"PENDING\",\n",
            "  \"mcan_diagnostics_csv\": \"diagnostics.csv\",\n  \"tx_armed_before_capture\": false,\n",
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
        measured.intra_batch_discontinuities,
        measured.cross_batch_discontinuities,
        measured.forward_missing_records,
        measured.backward_or_duplicate_records,
        measured.first_channel_sequence,
        measured.last_channel_sequence,
        measurement_device_drop_delta,
        measured.first_device_drop_total.unwrap_or(0),
        measured.maximum_device_drop_total,
        channel_drops,
        measurement_queue_drops,
        measurement_ring_drops,
        measurement_start_diagnostics.rxfifo0_high_watermark,
        measurement_end_diagnostics.rxfifo0_high_watermark,
        measurement_start_diagnostics.queue_high_watermark,
        measurement_end_diagnostics.queue_high_watermark,
        measurement_start_diagnostics.ring_high_watermark,
        measurement_end_diagnostics.ring_high_watermark,
        measured.channel_state_events,
        measured.error_passive_events,
        measured.bus_off_events,
        measured.data_loss_events,
        measured.data_loss_dropped,
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

#[cfg(test)]
mod tests {
    use super::*;

    fn can_event(event_sequence: u32, base_timestamp: u64, records: &[(u32, u32)]) -> Frame {
        let records = records
            .iter()
            .map(|(delta_tick, channel_sequence)| {
                hpm_usb_can_protocol::payload_events::CanRxRecord {
                    delta_tick: *delta_tick,
                    arbitration_id: 0x123,
                    channel_sequence: *channel_sequence,
                    flags: 0,
                    channel: 0,
                    dlc: 0,
                    filter_hit: 0xff,
                    rx_status: 0,
                    payload: Vec::new(),
                }
            })
            .collect();
        Frame {
            major: 1,
            minor: 0,
            flags: flags::EVENT,
            message_type: msg::CAN_RX_BATCH,
            status: 0,
            sequence: event_sequence,
            payload: CanRxBatch {
                flags: 0,
                base_timestamp,
                device_drop_total: 0,
                config_generation: 1,
                records,
            }
            .encode()
            .unwrap(),
        }
    }

    fn diagnostics() -> McanDiagnostics {
        McanDiagnostics {
            version: McanDiagnostics::VERSION,
            length: McanDiagnostics::LEN as u32,
            generation: 3,
            state_flags: McanDiagnostics::STATE_INITIALIZED
                | McanDiagnostics::STATE_ONLINE
                | McanDiagnostics::STATE_LISTEN_ONLY,
            snapshot_tick: 4,
            interrupt_flags: 5,
            error_interrupt_flags: 6,
            last_interrupt_flags: 7,
            protocol_status: 8,
            error_count: 9,
            transmit_error_count: 10,
            receive_error_count: 11,
            rxfifo0_fill_level: 12,
            rxfifo0_high_watermark: 13,
            queue_count: 14,
            queue_high_watermark: 15,
            ring_count: 16,
            ring_high_watermark: 17,
            queue_drops: 18,
            ring_drops: 19,
            invalid_frames: 20,
            bus_off_count: 21,
            warning_count: 22,
            error_passive_count: 23,
            automatic_recovery_attempts: 0,
        }
    }

    #[test]
    fn diagnostics_csv_has_stable_compact_layout() {
        let mut output = Vec::new();
        writeln!(output, "{}", diagnostics_csv_header()).unwrap();
        write_diagnostics_row(&mut output, 1, "measurement", &diagnostics()).unwrap();
        let csv = String::from_utf8(output).unwrap();
        let lines = csv.lines().collect::<Vec<_>>();
        assert_eq!(lines.len(), 2);
        assert_eq!(lines[0].split(',').count(), 25);
        assert_eq!(lines[1].split(',').count(), 25);
        assert_eq!(
            lines[1],
            "1,measurement,3,4,7,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,0"
        );
    }

    #[test]
    fn diagnostics_safety_requires_listen_only_and_disarmed() {
        let safe = diagnostics();
        validate_mcan_safety_state(&safe).unwrap();

        let mut not_listen_only = safe.clone();
        not_listen_only.state_flags &= !McanDiagnostics::STATE_LISTEN_ONLY;
        assert!(validate_mcan_safety_state(&not_listen_only).is_err());

        let mut armed = safe;
        armed.state_flags |= McanDiagnostics::STATE_TX_ARMED;
        assert!(validate_mcan_safety_state(&armed).is_err());

        let mut recovering = diagnostics();
        recovering.automatic_recovery_attempts = 1;
        assert!(validate_mcan_safety_state(&recovering).is_err());
    }

    #[test]
    fn measurement_window_retains_delayed_in_window_records_without_false_gaps() {
        let mut stats = CaptureStats::measurement(100);
        stats.close_measurement_window(200);
        let mut raw = Vec::new();

        record_event(can_event(10, 100, &[(0, 100)]), &mut stats, &mut raw, true).unwrap();
        record_event(
            can_event(11, 201, &[(0, 101), (1, 102)]),
            &mut stats,
            &mut raw,
            true,
        )
        .unwrap();
        record_event(can_event(12, 150, &[(0, 103)]), &mut stats, &mut raw, true).unwrap();

        assert_eq!(stats.frames, 2);
        assert_eq!(stats.batches, 2);
        assert_eq!(stats.first_channel_sequence, 100);
        assert_eq!(stats.last_channel_sequence, 103);
        assert_eq!(stats.channel_gaps, 0);
        assert_eq!(stats.event_gaps, 0);
        assert_eq!(stats.timing_samples.len(), 2);
        assert_eq!(String::from_utf8(raw).unwrap().lines().count(), 2);
    }

    #[test]
    fn measurement_window_still_reports_real_sequence_loss() {
        let mut stats = CaptureStats::measurement(100);
        stats.close_measurement_window(200);
        let mut raw = Vec::new();

        record_event(can_event(20, 100, &[(0, 100)]), &mut stats, &mut raw, false).unwrap();
        record_event(can_event(21, 110, &[(0, 102)]), &mut stats, &mut raw, false).unwrap();

        assert_eq!(stats.frames, 2);
        assert_eq!(stats.channel_gaps, 1);
        assert_eq!(stats.forward_missing_records, 1);
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
