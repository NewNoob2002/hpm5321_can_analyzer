# T-CAN-012 — Reset-Disarmed TX Probe

Date: 2026-08-03  
Artifact SHA-256: `06c86cfe19d21ceaa847d71d4f3d5b669c074d51cc92ba8f0fd657125b843f8b`

The historical ABI-v2 active-TX probe was downloaded, reset, and allowed to reach
`wait_for_tx_arm()` without writing the arm token. Raw evidence is in
`T-CAN-012-reset-disarmed-gdb.txt`.

Observed after reset:

- result ABI `version=2`
- `active_tx_build=1`, `g_mcan0_tx_arm_token=0`
- `tx_attempted=0`, `tx_succeeded=0`
- `CCCR=0x60`, including listen-only/monitor mode
- GPIOB OE value `0x00000400`: PB00/PB01 output-enable bits are clear
- GPIOM PB00/PB01 values `0x00000400`: GPIO0 ownership with fast-GPIO hidden

Verdict: **partial coverage of T-CAN-012**. No active-TX branch was entered, but
this record begins from a previously consumed-token state and then resets; it
does not directly demonstrate `ARM! -> reset -> token 0`, externally observed
zero traffic during reset, or reset-to-first-instruction containment. The PCB's
hardware-low STB keeps the last item blocked.

The probe can cover only a T-CAN-013 subcase: one-shot token consumption,
bounded traffic, and synchronous post-TX cleanup. It cannot cover arm expiry,
USB session reset/disconnect, or immediate/scheduled TX queue clearing because
those product facilities do not exist in this Phase 0 probe.
