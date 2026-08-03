# hpm5321_custom Board Overlay

Repository-local HPM SDK 1.12.1 board overlay for PCB revision
`Gerber_PCB1_2026-07-23`.

## Authority and regeneration

`board.c`, `board.h`, `clock.c`, `clock.h`, `pinmux.c`, `pinmux.h` and
`hpm5321_custom.yaml` are the authoritative reviewed sources. They were adapted
for the HPM5321 application and are not reproducible from the discarded
HPM5361 Pinmux Tool project that accompanied the original local SDK overlay.

No cloud-tool client keys, secret keys or Pinmux Tool session metadata belong in
this repository. If future regeneration is required, create and review a new
HPM5321-specific configuration without credentials, then compare its generated
code against the authoritative sources.

## MCAN startup safety

Generic `board_init()` intentionally leaves MCAN0/MCAN2 pads disconnected.
Applications must initialize the selected MCAN controller and mode first, then
call `board_init_can()` to connect TXD/RXD. This ordering is required because
TCAN1044A STB is pulled low in hardware.

`board_init()` performs IOC-only MCAN disconnect writes as its first board
action to contain retained pinmux state across warm resets. Software still
cannot control the interval between reset release and its first instruction.
For an unconditional hardware-safe power-up contract, a future PCB revision
must default STB high (standby) or add a controllable enable/standby signal.
