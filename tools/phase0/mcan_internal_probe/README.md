# HPM5321 Dual-MCAN Internal Probe

Target-only Phase 0 probe for MCAN0 and MCAN2. It uses each controller's internal
loopback and therefore does not require populated CAN transceivers or a live bus.
For each channel it checks Classic CAN and CAN FD, standard and extended IDs,
8-byte and 64-byte payload integrity, controller initialization, and AHB message
RAM setup.

```sh
export HPM_SDK_BASE=/home/gtc/HPMicro/sdk/hpm_sdk
export CCACHE_DISABLE=1
cmake -S tools/phase0/mcan_internal_probe \
  -B build/phase0-mcan-internal-probe -G Ninja \
  -DBOARD=hpm5321_custom -DHPM_BUILD_TYPE=flash_xip
cmake --build build/phase0-mcan-internal-probe
```

Read `g_mcan_probe_result` with GDB after the target reaches its final loop.
`magic == 0x50415353` (`PASS`) means all eight frame cases passed.

This proves only MCU/controller operation. It does not prove transceiver power,
VIO compatibility, STB control, termination, signal integrity, bus arbitration,
or physical-layer CAN FD operation.
