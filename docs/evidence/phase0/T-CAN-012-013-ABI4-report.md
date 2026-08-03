# ABI-v4 Reset, One-Shot ARM, TX and Cleanup Report

Date: 2026-08-03  
Git revision: `9ac4294d7b55f82c5532eeb3cfa4371633162e07`  
Board: `Gerber_PCB1_2026-07-23`, serial `20260723`  
ELF SHA-256: `bbbef9d7cba5ec9bcf09bf56486db7e75f466ea533d4c1f5fa9823437a0348ef`

## Reset-disarmed subcase

Raw evidence: `T-CAN-012-ABI4-reset-disarmed-gdb.txt`, SHA-256
`d92f1f733ced95c4a635e184dad385ff72e8785f5a2409abf1af9efe2fe2401a`.

- ABI version 4, active-TX build
- arm token 0
- TX attempted/succeeded 0/0
- live `CCCR=0x60`: INIT clear, monitor/listen-only set
- live IR 0
- result cleanup snapshot invalid while waiting (`cleanup_completed=0`)

Verdict: ABI-v4 reset-after-CRT disarmed subcase **PASS**. This still does not
prove reset-to-first-instruction physical containment or externally observed
zero traffic during reset.

## Explicit one-shot ARM and synchronous cleanup subcase

J-Link wrote the one-shot token `0x41524D21` and continued to the terminal
result. Raw evidence: `T-CAN-013-ABI4-armed-cleanup-gdb.txt`, SHA-256
`db07bce02276d1c7a40f7a72680a63a23220d4be0958ea0484e1724950a147f2`.

- magic `DONE`, ABI 4
- TX attempted/succeeded 100/100
- token consumed back to 0
- TEC/REC/CEL 0; no warning, passive or bus-off
- cleanup completed 1
- post-cleanup `CCCR=0x1` (INIT acknowledged)
- TX pending/add-request registers 0
- PB00/PB01 `FUNC_CTL=0` (GPIO, MCAN disconnected)
- GPIOB OE PB00/PB01 clear; GPIOM ownership GPIO0

External adapter capture `T-CAN-013-ABI4-adapter-capture.txt` confirms all 100
frames under the operator-declared CANDBG-01/CAN0, 500 kbit/s standard Classic
CAN data-frame configuration: ID `0x123`,
DLC 8, payload prefix `HPM0`, sequence 0..99, duration 1017 ms, and intervals
9..11 ms (mean 10.273 ms). Its metadata binds the capture hash to the current
artifact attestation and therefore to the exact ELF, SDK revision, build
definitions, ABI and canonical source manifest.

Verdict: the probe-level one-shot ARM, bounded TX and synchronous cleanup
subcase **PASS** on target and external adapter. Formal
product T-CAN-013 remains NOT_TESTED because this probe has no arm expiry, USB
session reset/disconnect, immediate TX queue or scheduled TX queue.
