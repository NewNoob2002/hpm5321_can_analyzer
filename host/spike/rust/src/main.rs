use std::time::Instant;
use std::{env, fs};

const FRAMES: u32 = 1_000_000;

fn main() {
    let start = Instant::now();
    let state_path = env::var("SPIKE_STATE").ok();
    let crash_at = env::var("SPIKE_CRASH_AT")
        .ok()
        .and_then(|v| v.parse::<u32>().ok());
    let (start_sequence, mut checksum, mut reconnects) = state_path
        .as_ref()
        .and_then(|path| fs::read_to_string(path).ok())
        .and_then(|text| {
            let mut fields = text.split_whitespace();
            Some((
                fields.next()?.parse().ok()?,
                fields.next()?.parse().ok()?,
                fields.next()?.parse().ok()?,
            ))
        })
        .unwrap_or((0, 0xcbf29ce484222325, 0));
    for sequence in start_sequence..FRAMES {
        if sequence != 0 && sequence % 10_000 == 0 {
            reconnects += 1;
        }
        let mut frame = [0u8; 16];
        frame[0..4].copy_from_slice(b"HPM1");
        frame[4..8].copy_from_slice(&sequence.to_le_bytes());
        frame[8..12].copy_from_slice(&0x123u32.to_le_bytes());
        frame[12..16].copy_from_slice(&(sequence ^ 0xa5a5_5a5a).to_le_bytes());
        for byte in frame {
            checksum ^= u64::from(byte);
            checksum = checksum.wrapping_mul(0x100000001b3);
        }
        if crash_at == Some(sequence + 1) {
            fs::write(
                state_path
                    .as_ref()
                    .expect("SPIKE_STATE required for crash test"),
                format!("{} {} {}\n", sequence + 1, checksum, reconnects),
            )
            .unwrap();
            std::process::exit(75);
        }
    }
    if let Some(path) = state_path {
        let _ = fs::remove_file(path);
    }
    let elapsed = start.elapsed().as_secs_f64();
    println!(
        "{{\"candidate\":\"rust\",\"frames\":{},\"checksum\":\"{:016x}\",\"reconnects\":{},\"recovered\":{},\"elapsed_ms\":{:.3},\"frames_per_second\":{:.0}}}",
        FRAMES,
        checksum,
        reconnects,
        reconnects,
        elapsed * 1000.0,
        f64::from(FRAMES - start_sequence) / elapsed
    );
}
