# P2 One-Hour Heartbeat Preflight

- Status: `PASS`
- Qualification status: `PARTIAL` (expected for less than 86,400 seconds)
- Date: 2026-08-09
- Firmware source revision: `980a38c9196dfe5971ff3b624c235edb33625e6d`
- Frozen Flash Debug ELF SHA-256:
  `c3feef5d36867d021e26a95548b4bd055150ca2e4be54cf907d847c8afee70d2`
- Raw evidence: `T-RTOS-003-3600-2026-08-09.json`
- Raw evidence SHA-256:
  `7359f016027b343ac1ddf0060439134e5cbdbe68d8015b7b0038deab414e913b`

## Result

The frozen-artifact runner completed 3,600.128 seconds with 61 samples at a
60-second interval. Its expected and measured ELF hashes match.

| Check | Result |
| --- | --- |
| Boot magic | `0x424f4f54` in all samples |
| Boot timestamp | constant `385385`; no reset detected |
| Reset snapshot | constant `0x00000010` |
| Heartbeat | `2488 -> 9662`, strictly increasing |
| Voter evaluations/healthy | `2488 -> 9662`, equal in every sample |
| Missing/stalled voter mask | `0/0` in every sample |
| Health queue drops | `0` in every sample |
| Health/MCAN stack minimum | `445/335` words |
| Fault magic/reason | `0/0` in every sample |
| Allocation policy | frozen in every sample; one startup allocation, zero post-freeze allocations |
| MCAN0 priority | `4` in every sample |
| MCAN0 counts | `1024/1024` interrupt/submitted/received/matched/queue-send |
| MCAN0 failures | zero queue drops, IRQ faults, terminal faults, error counters, mismatches and timeouts |
| MCAN0 cleanup | PASS with `CCCR.INIT=1` in every sample |

This is a preflight only. It does not close `T-RTOS-003`; the collector
correctly leaves `qualification_status: PARTIAL`.

## 24-Hour Run

Connect the frozen board and J-Link, ensure no other J-Link client is running,
then run from the repository root:

```bash
export GNURISCV_TOOLCHAIN_PATH=/path/to/riscv-toolchain
scripts/phase2/run_frozen_heartbeat.sh
```

The script defaults to 86,400 seconds and 60-second samples. It validates the
ELF against the frozen SHA-256 before opening J-Link and writes a dated JSON
file under `docs/evidence/phase2/`. A successful full run exits 0 and records
both `status: PASS` and `qualification_status: PASS`. Ctrl-C records
`status: ABORTED` and exits 130; any invariant violation records `status: FAIL`
and exits nonzero.
