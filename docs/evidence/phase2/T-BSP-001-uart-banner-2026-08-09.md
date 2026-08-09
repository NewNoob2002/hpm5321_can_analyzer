# T-BSP-001 UART Boot Banner Evidence

Status: `PASS`
Date: 2026-08-09
Board: `hpm5321_custom`, revision `Gerber_PCB1_2026-07-23`, serial `20260723`
Probe: J-Link PLUS, S/N `607000454`, JTAG 4 MHz, VTref 3.30 V
SDK: `1.12.1`, build `v1.12.1-3-g88b01b43900d`

## Artifact

| Preset | ELF SHA-256 |
|---|---|
| Flash Debug | `faddfc9174fc3c1b9d4395a40c97bb1a89a66e20ab3378d098b93edb30494a90` |
| Flash Release | `fb1e2f825ee844e5b76987af9643a402649ef7e926ea998d2bb0e26419dd2591` |
| RAM Debug | `25b0bbb451b28d0ce52a0c535a1d920efa9586126a2bcdf342f20810648bdc53` |

All three presets were clean-built after removing the stale SDK archive
objects from the prior RTT-syscall configuration. The final ELF has one
`_write` implementation from the UART debug console while EasyLogger links
only the SEGGER RTT core.

## Banner Contract

UART0 uses PA00 TX, PA01 RX and 921600 baud. The application emits this
machine-readable record before scheduler start:

```text
P2_BOOT firmware=0.1.0-dev sdk=1.12.1 sdk_build=v1.12.1-3-g88b01b43900d board=hpm5321_custom board_revision=Gerber_PCB1_2026-07-23 uart=UART0 baud=921600 reset_flags=<hex> reset_cause=<name>
```

The reset decoder distinguishes brownout, debug, watchdog0, watchdog1, PMIC
watchdog, software, multiple, unknown, and zero-flag power-on/unknown cases.
The raw flags remain present so the decoded primary label cannot hide bits.

## Target Proof

The Flash Debug image was programmed with GDB `load`; `compare-sections`
matched every loadable section. A breakpoint after banner output and before
fault injection recorded:

```text
P2_UART_TARGET boot=0x424f4f54 reset=0x00000010 frozen=1 allocations=1 post=0 console=0xf0040000 uart_oscr=0x00000008 uart_lcr=0x00000003 uart_idle=0x000a080a
```

The `0x10` PPOR flag decodes to `debug`, as expected after the J-Link reset.
The console pointer equals the HPM UART0 base. After the target resumed, a
second sample recorded:

```text
P2_UART_HEALTH boot=0x424f4f54 heartbeat=36 drops=0 stack=447 eval=36 healthy=36 missing=0x00000000 frozen=1 allocations=1 post=0 console=0xf0040000
```

This proves that enabling UART stdout did not break the scheduler, watchdog
voters, stack watermark or runtime allocation freeze.

## Physical UART Capture

An external QinHeng USB serial adapter appeared as `/dev/ttyACM0`:

```text
USB 1a86:55d3, serial 586D017868
921600 baud, 8 data bits, 1 stop bit, no parity, no flow control
```

For the successful capture, board PA00/TX was connected to adapter RX and the
grounds were common; adapter TX was disconnected. With DTR/RTS asserted, a
30-second raw capture was armed before a J-Link debug reset and resume. The
adapter received 447 bytes. The raw byte stream used CRLF line endings and had
SHA-256
`e06b47bc574c19ce5ff149f40a3548f9ad184da1268f1e1fd80e4afb45a8a961`.
Decoded as ASCII with line endings normalized for Markdown, its complete text
was:

```text
==============================
 hpm5321_custom clock summary
==============================
cpu0:		 480000000Hz
ahb:		 160000000Hz
mchtmr0:	 24000000Hz
xpi0:		 100000000Hz
==============================
hpm_sdk: 1.12.1
board: hpm5321_custom
P2_BOOT firmware=0.1.0-dev sdk=1.12.1 sdk_build=v1.12.1-3-g88b01b43900d board=hpm5321_custom board_revision=Gerber_PCB1_2026-07-23 uart=UART0 baud=921600 reset_flags=0x00000010 reset_cause=debug
```

The machine-readable line exactly matches the banner contract. The raw
`reset_flags=0x00000010` value and `reset_cause=debug` decoding also match the
J-Link reset used for the capture. `T-BSP-001` is therefore `PASS` for the
UART boot-banner requirement.

A second capture then repeated the same procedure with all three UART wires
connected: common ground, board PA00/TX to adapter RX, and adapter TX to board
PA01/RX. It again received 447 bytes and produced the identical SHA-256
`e06b47bc574c19ce5ff149f40a3548f9ad184da1268f1e1fd80e4afb45a8a961`.
A byte-for-byte comparison reported no differences. This confirms that the
fully connected three-wire setup does not interfere with board UART output.

## Three-Wire Host-to-Board Retest

With all three wires still connected, the target was reset to clear UART0 RX,
then the host wrote this 13-byte payload through `/dev/ttyACM0` at 921600 8N1:

```text
ASCII: USB2BOARD_OK\n
HEX:   55534232424f4152445f4f4b0a
```

J-Link then halted the target and read the UART0 line-status register and all
13 receiver-buffer entries:

```text
UART_RX_LSR_BEFORE=0x000d0061 fifo=13 errors=0x00
UART_RX_DATA_HEX=55534232424f4152445f4f4b0a
UART_RX_LSR_AFTER=0x00000060 fifo=0 errors=0x00
```

The initial FIFO count exactly matched the host write, the received bytes were
identical, and no overrun, parity, framing, break or aggregate FIFO error was
set. After the reads, the FIFO count returned to zero. This proves the active
adapter-TX-to-board-PA01/RX hardware path. The product firmware does not yet
consume UART commands, so this is a physical/UART-peripheral receive proof,
not application-protocol handling evidence.

## Connection Diagnosis History

Before the adapter RX lead was corrected, three capture attempts produced zero
bytes even though a direct `_write("UART_LIVE_TEST\\n")` returned 15 bytes.
Target inspection showed:

```text
UART_PIN_STATE pa00_func=0x00000002 pa00_pad=0x01010053 pa01_func=0x00000002 pa01_pad=0x01010053 lsr=0x00000060 mcr=0x00000002 heartbeat=281 console=0xf0040000
```

PA00/PA01 are selected as UART0 TX/RX, and LSR `0x60` reports an empty transmit
holding register and idle transmitter. The firmware-side path is configured
and completes transmission, but no physical bytes reached the host adapter.

A reverse-direction probe then wrote 13 bytes from the host adapter to the
board. UART0 reported the exact count with no receive errors:

```text
host_tx_bytes=13
UART_RX_PROBE lsr=0x000d0061 rfifo_count=13 errors=0x00 heartbeat=281
```

Those diagnostics proved the adapter-TX-to-board-RX direction in the earlier
setup, but they did not identify why board TX produced no host bytes. The later
successful boot capture was taken with adapter TX disconnected; it proves the
board-PA00/TX-to-adapter-RX direction required by `T-BSP-001`. The subsequent
byte-identical capture with adapter TX reconnected rules out its normal
connection to PA01/RX as the cause. The earlier zero-byte result was therefore
transient wiring/contact or capture/reset timing, but the available evidence
does not distinguish those possibilities.
