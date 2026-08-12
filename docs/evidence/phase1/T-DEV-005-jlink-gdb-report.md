# T-DEV-005: J-Link GDB Debug Contract

Status: `PASS`  
Date: 2026-08-09  
Board: `hpm5321_custom`, serial `20260723`  
Probe: J-Link PLUS, S/N `607000454`, JTAG 4 MHz, VTref 3.31 V  
ELF SHA-256: `9255dafe0824032289a833d287fd66a0ffdaa030cdaebdddcaa3cca887f96071`

## Tools

- SEGGER J-Link GDB Server `V9.66`
- GNU RISC-V GDB `13.2`
- VSCode `1.132.0`
- Test-time editor profile: port 2331, `break main`; the repository-owned
  launch file was later removed as optional editor configuration

## Procedure And Result

The root Flash Debug ELF was programmed temporarily. The test then used the
test-time profile's ELF, port and reset/break commands plus the J-Link target,
interface and speed now frozen directly by `setup-linux.md`:

```text
target remote localhost:2331
monitor reset
break main
continue

Breakpoint 1, main () at USER/src/main.c:29
29        elog_init();
pc  0x80007eb4  <main+4>

stepi
elog_init () at third_party/easylogger/src/elog.c:160
160       ElogErrCode elog_init(void) {

monitor reset
monitor halt
disconnect
```

J-Link reported the HPM5321 RV32 target, accepted reset/halt, installed the
breakpoint, stopped at `main`, exposed source/register state and completed an
instruction step. This closes the adapter behavior contract used by VSCode;
no OpenOCD profile is selected.

After the test, `build/phase0-usb-hs-probe/output/demo.elf` was restored and
the target re-enumerated as `34b7:1236 HPMicro WinUSB Demo` on bus 007, device
072. The closure test did not leave the root skeleton running on the probe.
