# T-CAN-EXT-001 Safety Preflight

Date: 2026-08-03

## Authorized isolated bench scope

- DUT: HPM5321 custom board, MCAN0 only
- Peer: CAN debugger connected directly to CAN0
- No vehicle, actuator, production network or other CAN node
- Classic CAN only, 500 kbit/s
- Active test frame: standard ID `0x123`, DLC 8
- Payload: `48 50 4D 30 <32-bit big-endian sequence>`
- Limit: 100 frames, 10 ms interval, automatic retransmission disabled

## Electrical preflight

| Check | Evidence | Disposition |
|---|---|---|
| TXD/RXD isolation/level conversion | Confirmed by operator | PASS |
| VCC / VIO | 5.2 V / 5.2 V | PASS |
| STB | 0.1 V, 10 kOhm pull-down to ISO_GND | PASS |
| Idle bus | CANH=2.52 V, CANL=2.52 V before peer attachment | PASS |
| Termination enabled | 119 ohm, power removed | PASS for the tested enabled state |
| Termination disabled | `OL/0L` open circuit, power removed | PASS |
| CANH/CANL continuity | Confirmed by operator | PASS |
| Board revision / serial | `Gerber_PCB1_2026-07-23` / `20260723` | PASS |
| CAN debugger asset/channel | Logical name `CANDBG-01`, channel `CAN0` | PASS |

## Stage gates

- Stage 1 must initialize in listen-only mode with no bus-off, warning or
  error-passive state before active firmware is loaded.
- Stage 2 is limited to the frame contract above.
- Target GDB logs are archived separately. CAN-debugger capture supplied by the
  operator is required to reconcile the external receive count and formally
  pass the active-transmit case.

## Reset/pinmux limitation

The repository overlay disconnects MCAN pads as the first `board_init()` action
and reconnects them only after controller-mode initialization. This contains
retained IOC state on warm reset once firmware executes. Because STB is
hardware-low, software cannot guarantee the interval from reset release to the
first instruction. A future PCB revision should default STB high or make it
controllable for an unconditional power-up safety contract.
