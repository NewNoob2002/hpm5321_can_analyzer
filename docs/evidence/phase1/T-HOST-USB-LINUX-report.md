# Rust Host USB Linux Evidence

Date: 2026-08-03  
Board: `Gerber_PCB1_2026-07-23`, serial `20260723`  
Firmware ELF SHA-256: `fd73b02b53eacf883c1772970c07f6dc33ba7d581ae394546ddad8513ef27d9b`
Host: Rust 1.97.1, `rusb` 0.9.4 with vendored libusb
Host binary SHA-256: `523b557eab2be70e21eac179f54c5c57b890c4f1c7796366975a57850d081598`
Cargo lock SHA-256: `97687f061d9c7e0ceefa84798657354db17ea73da2d57debb67096607a5d0a67`

## Enumeration and integrity

`lsusb` enumerated `34b7:1236 HPMicro WinUSB Demo`; topology reported 480M,
vendor-specific interface 0 and no kernel driver. Rust claimed interface 0 and
completed 64 MiB EP1 OUT/IN echo with exact byte comparison:

```text
PASS bytes=67108864 elapsed_s=20.752 throughput_MiB_s=3.084
```

## Reset/disconnect recovery

During a 1 GiB requested transfer, J-Link reset the target after one second.
The CLI stopped after 3,512,320 bytes with a stable error and exit code 2:

```text
FAIL bulk IN after 3512320 bytes: Input/Output Error
interrupt_exit_code=2
```

After re-enumeration as a new USB device number, a 1 MiB transfer passed at
3.072 MiB/s. This proves reset/disconnect failure visibility and process-level
retry recovery; physical cable hotplug cycling remains separate evidence.

## Verdict

Linux Rust vendor-Bulk enumeration, 64 MiB integrity, reset interruption and
post-reset recovery: **PASS**. Windows WinUSB and physical hotplug remain open.
