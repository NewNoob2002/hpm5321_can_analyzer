# BP-STORAGE-v1

Stable addendum ID: `spi2-sd-led-2026-08-09`  
Release contract: only `1.0 + STORAGE`; chain `P0S -> P3C1 -> P3C2 -> P5S`.

This file fixes the benchmark shape without inventing target measurements.
`BLOCKED(P0S)` values must become numeric and the status must become `FROZEN`
before P3C1 starts.

| Key | Value |
|---|---|
| status | BLOCKED |
| media | SD v2 SDHC; FAT32; 512-byte sectors; two vendors per claimed 4/8/16/32 GB capacity |
| spi_init_max_hz | 400000 |
| spi_data_max_hz | 20000000 |
| io_block_bytes | 4096 |
| queue_depth | 8 |
| segment_bytes | 134217728 |
| fat_allocation_unit_bytes | 32768 |
| usb_reads_queued | 8 |
| usb_read_bytes | 16384 |
| warmup_seconds | 60 |
| measurement_seconds | 1800 |
| soak_hours | 72 |
| throughput_multiplier | 2.0 |
| encoded_capture_bytes_per_s | BLOCKED(P0S) |
| queue_absorption_ms | BLOCKED(P0S) |
| operation_deadline_ms | BLOCKED(P0S) |

## Fixed Thresholds

- p99 block admission-to-truthful-sync is at most 25% of measured queue
  absorption time; the maximum operation deadline is at most 50%.
- Storage adds at most 15 percentage points CPU, queue watermark is at most
  75%, release Flash/RAM free is at least 20%, and each task stack margin is at
  least 25% unless an approved exception exists.
- Under frozen `BP-CAN-BETA-v1`, device/host normal-profile drop is zero;
  CAN-to-host p95 regression is at most 10% and absolute p95 remains at most
  5 ms.
- Removal, full media and DMA timeout fail within the frozen deadline,
  increment diagnostics, invalidate `media_generation` and leave CAN/USB live.

Every card runs 60 seconds warm-up plus 30 minutes measurement. The full
configuration also runs the Gate H 72-hour soak. Any SdFat comparison uses the
same cards, clocks, buffers, workload and thresholds.
