# T-CAN-BOOT-001 MCAN Pinmux Ordering

Date: 2026-08-03  
Firmware: safe-order listen-only probe  
ELF SHA-256: `e39b06a40c8d05e2fa265f03714d111ab2be08b826f400e039523d75261d1292`

GDB stopped immediately before and after `board_init_can(HPM_MCAN0)`:

| Register | Before pinmux | After pinmux |
|---|---:|---:|
| MCAN0 CCCR | `0x00000060` (listen-only/monitoring configured) | `0x00000060` |
| PB00 FUNC_CTL | `0x00000000` (GPIO) | `0x00000007` (MCAN0 TXD) |
| PB01 FUNC_CTL | `0x00000000` (GPIO) | `0x00000007` (MCAN0 RXD) |

Result: software ordering **PASS**. MCAN pads are disconnected during generic
board initialization and connected only after the controller is in listen-only
mode. Raw evidence: `T-CAN-BOOT-001-pinmux-order-gdb.txt`.

Residual limitation: STB is hardware-low. Firmware cannot control the interval
from reset release until its first IOC writes. An unconditional power-up safety
claim therefore remains a future PCB requirement (default STB high or a
controllable STB/enable path).
