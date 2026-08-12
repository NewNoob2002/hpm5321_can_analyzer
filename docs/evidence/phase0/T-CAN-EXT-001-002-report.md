# MCAN0 External Bus Validation Report

Date: 2026-08-03  
Tests: T-CAN-EXT-001 (listen-only), T-CAN-EXT-002 (bounded transmit)  
Git base revision: `705e412d602afbd5c65382b13d47094da7445cea`  
Historical relevant-source digest: `27cc8b787d4991ec7d485ce629ff9f97e05f915850ac5fd77c3a9d44677e7ca7` (the corresponding file manifest was not preserved)  
Board revision/serial: `Gerber_PCB1_2026-07-23` / `20260723`  
CAN debugger logical asset/channel: `CANDBG-01/CAN0`

## Configuration

- HPM SDK 1.12.1; GNU RISC-V 13.2.0
- SEGGER J-Link GDB Server 9.62; probe S/N 607000454
- MCAN0 source clock: 80 MHz
- Classic CAN 500 kbit/s; CAN-FD disabled
- Termination enabled measurement: 119 ohm
- Termination disabled measurement: `OL/0L` open circuit, power removed
- Supply: VCC=5.2 V, VIO=5.2 V, STB=0.1 V
- Idle before peer attachment: CANH=2.52 V, CANL=2.52 V

## T-CAN-EXT-001 — listen-only

Firmware ELF SHA-256:
`4b73de7a6e86cecd86dcdaac539561aca9035a19f34855f7bae8d025491ff34c`

Exact build configuration:

`cmake -S tools/phase0/mcan0_external_probe -B build/phase0-mcan0-listen -G Ninja -DBOARD=hpm5321_custom -DBOARD_SEARCH_PATH="$PWD/boards" -DHPM_BUILD_TYPE=flash_xip -DMCAN0_ACTIVE_TX=0`

Result after 3 seconds: listen-only safe-state initialization **PASS**. Initialization succeeded; TEC=0,
REC=0, CEL=0; bus-off=false, warning=false, error-passive=false. No baseline
frames were received, so this run does not prove external receive. Raw GDB/program verification:
`T-CAN-EXT-001-listen-gdb.txt`.

## T-CAN-EXT-002 — bounded transmit

Firmware ELF SHA-256:
`6512813f56137e084de0a5ce067c498c1547cf87219cb55cead230d6505cc627`

Exact build configuration:

`cmake -S tools/phase0/mcan0_external_probe -B build/phase0-mcan0-tx -G Ninja -DBOARD=hpm5321_custom -DBOARD_SEARCH_PATH="$PWD/boards" -DHPM_BUILD_TYPE=flash_xip -DMCAN0_ACTIVE_TX=1`

Traffic contract: 100 Classic frames, standard ID `0x123`, DLC 8, 10 ms
interval, payload `48 50 4D 30 <big-endian sequence 0..99>`, automatic
retransmission disabled.

Target result: **100/100 transmit completions**, last status success; TEC=0,
REC=0, CEL=0; bus-off=false, warning=false, error-passive=false. Raw
GDB/program verification: `T-CAN-EXT-002-tx-gdb.txt`.

## External adapter reconciliation

The operator-provided `CANDBG-01/CAN0` capture is archived as
`T-CAN-EXT-002-adapter-capture.txt`, SHA-256
`13cbc45cd22ec0891c792af4e94ebcf70a4fd65435cf989f979c333f5ac18ac5`.
Automated validation reports:

- 100 frames received
- standard ID `0x123`, DLC 8
- payload prefix `48 50 4D 30`
- continuous big-endian sequence 0 through 99 with no gaps or duplicates
- capture duration 1009 ms
- inter-arrival min/mean/max = 3.000/10.192/16.000 ms

## Verdict

- MCAN0 controlled Classic CAN transmission: **PASS**. Target completion/error
  state and the independent external capture reconcile 100/100 frames.
- Timing is suitable for this 10 ms smoke test but is not a real-time periodic
  scheduling qualification; observed host timestamps span 3–16 ms.
- Switch-controlled termination: **PASS**; power-off CANH-to-CANL measurement
  is 119 ohm enabled and open circuit (`OL/0L`) disabled.
- Cleanup: the listen-only ELF was reprogrammed and verified after Stage 2;
  `T-CAN-EXT-cleanup-listen-gdb.txt` records `active_tx_build=0` and `DONE`.

## Provenance correction after review

This run remains valid engineering evidence for the physical MCAN0 path, but
it cannot formally close the source-reproducibility Gate: its probe and overlay
were untracked, and the report preserved only an aggregate digest rather than
the file-level manifest. The subsequent safe-startup revision now has a
file-level manifest at `T-CAN-EXT-source-manifest.sha256` (manifest digest
`332d2a056e5bd1b67bd07d410df7319074d915a519e6d604acfc720eb0d18be2`).
The former safe-order ELF
`b1076d8ea75589fa4491694b34398de7e3fcebb4f3dd6c414c33030413971187`
predates the current CMake definitions and is explicitly **superseded**, not
source-bound to the current manifest. The retained reset-disarmed TX artifact is
`build/review-mcan-tx/output/demo.elf`, SHA-256
`bfd96070d9dfb7575aee9b31361dd69746d8baa466e3b63b6d6b1d2f6cb10cc0`.
The artifact attestation inputs and archived source commit are recorded in
`T-CAN-TX-current-artifact.json`; validation intentionally does not bind this
historical artifact to the moving repository worktree.
This historical report is superseded for reset/disarm work by the ABI-v4 and
ABI-v5 reports. ABI-v4 target and external results passed independently but
lacked a same-run nonce; ABI-v5 is the retained nonce-bound evidence path.
