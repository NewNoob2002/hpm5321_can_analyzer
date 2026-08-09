# T-HOST-USB-WINDOWS — WinUSB Host Evidence

Phase 1B lane: `PASS`  
Product PnP/package evidence: `PARTIAL`

Date: 2026-08-03  
Device: HPMicro `VID_34B7&PID_1236`, vendor interface 0  
Endpoints: Bulk OUT `0x01`, Bulk IN `0x81`

## Linux-to-Windows GNU cross-built executable

```text
hpm-usb-smoke.exe --bytes 67108864
PASS platform=windows vid=34b7 pid=1236 interface=0 bytes=67108864 elapsed_s=21.660 throughput_MiB_s=2.955
exit=0

hpm-usb-smoke.exe --bytes 1073741824
FAIL bulk IN after 11307008 bytes: Pipe error
exit=2

hpm-usb-smoke.exe --bytes 1048576
PASS platform=windows vid=34b7 pid=1236 interface=0 bytes=1048576 elapsed_s=0.342 throughput_MiB_s=2.920
```

## Windows-native executable

```text
hpm-usb-smoke.exe --bytes 67108864
PASS platform=windows vid=34b7 pid=1236 interface=0 bytes=67108864 elapsed_s=21.695 throughput_MiB_s=2.950
exit=0

hpm-usb-smoke.exe --bytes 1073741824
FAIL bulk OUT after 22190080 bytes: Pipe error
exit=2

hpm-usb-smoke.exe --bytes 1048576
PASS platform=windows vid=34b7 pid=1236 interface=0 bytes=1048576 elapsed_s=0.345 throughput_MiB_s=2.898
```

## Conclusions and limits

- Both build paths opened the real device and completed an exact 64 MiB echo.
- Both detected an intentional reset/disconnect with stable exit code 2 and
  recovered after re-enumeration.
- Opening interface 0 through libusb's Windows backend is functional WinUSB HIL
  evidence, but the PnP driver-binding record has not yet been archived.
- The approximately 2.9 MiB/s figure is the synchronous 2 KiB stop-and-wait echo
  profile, not the USB physical link rate. Earlier descriptor/topology evidence
  establishes High-Speed operation; this profile is not a throughput gate.
- Windows-native clean build/test/clippy, OS and Rust/MSVC target evidence is
  archived separately in `T-HOST-WINDOWS-CI-report.md`; `host/Cargo.lock`
  SHA-256 is `4c12ca3aa919f02d6496f4dcdcb3d90efbc77f02d2a63cd435e9f31326b8c7af`.
- The exact native HIL EXE SHA-256 and PnP binding output were not captured in
  the original session. They remain required for P3A/P6 product evidence, but
  do not reopen the completed Phase 1B build/stack/functional lane.
