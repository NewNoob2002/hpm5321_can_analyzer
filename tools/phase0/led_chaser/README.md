# HPM5321 Five-LED Chaser

Standalone Phase 0 firmware for visually checking all five board LEDs. It
keeps the MCAN pads disconnected and generates no CAN traffic. Exactly one LED
is on at a time, in this repeating order:

| Step | Product signal | MCU pin | Active level |
|---:|---|---|---:|
| 0 | STATUS | PA31 | Low |
| 1 | CAN1 TX (MCAN0) | PY01 | Low |
| 2 | CAN1 RX (MCAN0) | PY02 | Low |
| 3 | CAN2 TX (MCAN2) | PY03 | Low |
| 4 | CAN2 RX (MCAN2) | PA09 | Low |

The default step duration is 250 ms. This is a bring-up probe only; it does not
implement the product `health_task` ownership or CAN activity semantics from
`T-LED-002`, `T-LED-003`, `T-LED-005`, and `T-LED-006`.

```sh
export HPM_SDK_BASE=/path/to/hpm_sdk
export GNURISCV_TOOLCHAIN_PATH=/path/to/riscv-toolchain
export CCACHE_DISABLE=1
cmake -S tools/phase0/led_chaser \
  -B build/phase0-led-chaser -G Ninja \
  -DBOARD=hpm5321_custom -DBOARD_SEARCH_PATH="$PWD/boards" \
  -DHPM_BUILD_TYPE=flash_xip -DCMAKE_BUILD_TYPE=Debug
cmake --build build/phase0-led-chaser
```

Set `-DLED_CHASER_STEP_MS=<milliseconds>` during configuration to change the
speed. After flashing, verify the five LEDs follow the table without skipped,
simultaneous, or out-of-order illumination. `g_led_chaser_state` exposes the
current step and completed-cycle count to GDB.
