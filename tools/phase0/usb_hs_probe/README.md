# HPM5321 USB HS Probe

Minimal vendor-bulk enumeration firmware derived from the HPM SDK 1.12.1
CherryUSB WinUSB 2.0 sample. It deliberately excludes FreeRTOS, CAN, CDC and DFU
so Phase 0 can isolate the USB clock/PHY/HS path.

```sh
export HPM_SDK_BASE=/home/gtc/HPMicro/sdk/hpm_sdk
export CCACHE_DISABLE=1
cmake -S tools/phase0/usb_hs_probe \
  -B build/phase0-usb-hs-probe -G Ninja \
  -DBOARD=hpm5321_custom -DHPM_BUILD_TYPE=flash_xip
cmake --build build/phase0-usb-hs-probe
python3 scripts/phase0/validate_usb_composite.py
```

The firmware descriptor contains HS, FS, device-qualifier, other-speed and
Microsoft OS 2.0 WinUSB descriptors. Hardware enumeration is still required to
prove that the negotiated link is actually High-Speed.

The probe currently uses the HPM SDK sample VID/PID and strings. They are
development-only identifiers and must be replaced after the product USB
identity is allocated.
