# T-CAN-RX-002 — MCAN0 External Receive Proof

Date: 2026-08-03  
Board revision/serial: `Gerber_PCB1_2026-07-23` / `20260723`  
Adapter/channel: `CANDBG-01/CAN0`

## Contract

- Classic CAN, 500 kbit/s, standard data frame
- ID `0x321`, DLC 8
- Payload `48 50 4D 52 00 00 00 01`
- MCAN normal mode only to provide the hardware ACK required to complete the
  frame on a two-node bus
- Software transmission disabled: `MCAN0_ACTIVE_TX=0`; the linked ELF contains
  neither `run_bounded_tx` nor `mcan_transmit`
- Automatic retransmission disabled

The complete preflight is recorded in `T-CAN-RX-002-safety-preflight.md`.

## Artifact and deployment

ELF: `build/phase0-mcan0-ack-rx-proof/output/demo.elf`  
SHA-256: `f312af45aecfc2a4d5208880625a8a71de09d15b82057253096c852cb146fadb`

Build definitions:

```text
MCAN0_ACTIVE_TX=0
MCAN0_REQUIRE_RX=1
MCAN0_ACK_RX=1
```

J-Link probe S/N `607000454`, target `HPM5321xCFx`, JTAG 4 MHz. The GDB
download record is `T-CAN-RX-002-arm-gdb.txt`.

## Raw observation and result

Before the CPU consumed the FIFO, live register and message-RAM evidence showed:

- `RXF0S=0x00010001`: one element present in RX FIFO 0
- Message header at `0xF0400180`: `0x0C840642 0x00080000`
- Message data: `0x524D5048 0x01000000`, little-endian bytes
  `48 50 4D 52 00 00 00 01`

The initial GDB detach kept the CPU halted. This explained why the peripheral
had accepted the frame while the application result still showed zero. The CPU
was resumed without reset and stopped at the probe completion point.

Final application result (`T-CAN-RX-002-result-gdb.txt`):

- magic `0x444F4E45` (`DONE`)
- `rx_frames=1`, `rx_expected_frames=1`
- `last_rx_id=0x321`, `last_rx_dlc=8`
- payload `48 50 4D 52 00 00 00 01`
- `tx_attempted=0`, `tx_succeeded=0`
- TEC=0, REC=0, CEL=0
- bus-off=false, warning=false, error-passive=false
- RX FIFO fill level returned to zero after consumption

## Verdict

**PASS.** The MCAN0 external physical receive path, Classic CAN nominal timing,
standard-frame decoding, message-RAM transfer, driver FIFO consumption, and
payload integrity are proven for the specified frame. This is an engineering
hardware result; formal reproducibility still depends on committing the source,
board overlay, dependency lock, and evidence files.
