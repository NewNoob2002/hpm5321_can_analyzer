use std::env;
use std::process::ExitCode;
use std::time::{Duration, Instant};

const VID: u16 = 0x34b7;
const PID: u16 = 0x1236;
const INTERFACE: u8 = 0;
const EP_OUT: u8 = 0x01;
const EP_IN: u8 = 0x81;
const DEVICE_WINDOW: usize = 2048;

fn fill_payload(payload: &mut [u8], state: &mut u32) {
    for byte in payload {
        *state = state.wrapping_mul(1_664_525).wrapping_add(1_013_904_223);
        *byte = (*state >> 24) as u8;
    }
}

fn parse_bytes() -> Result<usize, String> {
    let mut args = env::args().skip(1);
    match (args.next().as_deref(), args.next(), args.next()) {
        (None, None, None) => Ok(64 * 1024 * 1024),
        (Some("--bytes"), Some(value), None) => value
            .parse::<usize>()
            .map_err(|_| "--bytes must be a positive integer".to_owned())
            .and_then(|bytes| {
                (bytes > 0)
                    .then_some(bytes)
                    .ok_or("--bytes must be positive".to_owned())
            }),
        _ => Err("usage: hpm-usb-smoke [--bytes N]".to_owned()),
    }
}

fn run(total: usize) -> Result<(), String> {
    let timeout = Duration::from_secs(3);
    let handle = rusb::open_device_with_vid_pid(VID, PID)
        .ok_or_else(|| "device 34b7:1236 absent or inaccessible".to_owned())?;
    handle
        .claim_interface(INTERFACE)
        .map_err(|error| format!("claim interface 0: {error}"))?;

    let mut state = 0x5321_u32;
    let mut completed = 0usize;
    let started = Instant::now();
    while completed < total {
        let size = (total - completed).min(DEVICE_WINDOW);
        let mut payload = vec![0u8; size];
        fill_payload(&mut payload, &mut state);
        let written = handle
            .write_bulk(EP_OUT, &payload, timeout)
            .map_err(|error| format!("bulk OUT after {completed} bytes: {error}"))?;
        if written != size {
            return Err(format!("short bulk OUT: {written}/{size}"));
        }
        if size < DEVICE_WINDOW && size.is_multiple_of(512) {
            handle
                .write_bulk(EP_OUT, &[], timeout)
                .map_err(|error| format!("OUT ZLP: {error}"))?;
        }
        let mut echoed = vec![0u8; size];
        let read = handle
            .read_bulk(EP_IN, &mut echoed, timeout)
            .map_err(|error| format!("bulk IN after {completed} bytes: {error}"))?;
        if read != size || echoed != payload {
            return Err(format!("echo mismatch after {completed} bytes"));
        }
        completed += size;
    }
    handle
        .release_interface(INTERFACE)
        .map_err(|error| format!("release interface 0: {error}"))?;
    let elapsed = started.elapsed().as_secs_f64();
    println!(
        "PASS platform={} vid=34b7 pid=1236 interface=0 bytes={} elapsed_s={:.3} throughput_MiB_s={:.3}",
        env::consts::OS,
        completed,
        elapsed,
        completed as f64 / 1_048_576.0 / elapsed
    );
    Ok(())
}

fn main() -> ExitCode {
    match parse_bytes().and_then(run) {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("FAIL {error}");
            ExitCode::from(2)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::fill_payload;

    #[test]
    fn payload_generator_is_chunk_boundary_independent() {
        let mut whole = [0u8; 32];
        let mut whole_state = 0x5321;
        fill_payload(&mut whole, &mut whole_state);

        let mut split = [0u8; 32];
        let mut split_state = 0x5321;
        fill_payload(&mut split[..13], &mut split_state);
        fill_payload(&mut split[13..], &mut split_state);
        assert_eq!(whole, split);
        assert_eq!(whole_state, split_state);
    }
}
