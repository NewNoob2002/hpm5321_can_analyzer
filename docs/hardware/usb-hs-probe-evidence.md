# USB HS Probe — Build and Static Resource Evidence

Date: 2026-07-30  
Board target: `hpm5321_custom` / HPM5321xCFx  
SDK: HPM SDK 1.12.1  
Toolchain: GNU RISC-V 13.2.0  
Build type: `flash_xip`, Debug

## Exact build

```sh
HPM_SDK_BASE=/path/to/hpm_sdk \
CCACHE_DISABLE=1 \
cmake -S tools/phase0/usb_hs_probe \
  -B build/phase0-usb-hs-probe -G Ninja \
  -DBOARD=hpm5321_custom -DBOARD_SEARCH_PATH="$PWD/boards" \
  -DHPM_BUILD_TYPE=flash_xip \
  -DCMAKE_BUILD_TYPE=Debug -DCMAKE_EXPORT_COMPILE_COMMANDS=ON

HPM_SDK_BASE=/path/to/hpm_sdk \
CCACHE_DISABLE=1 \
cmake --build build/phase0-usb-hs-probe -j8
```

Result: `PASS`, 60 build steps.

## Size

```text
text=63240 data=512 bss=49904 dec=113656
FLASH=75368/1048576 (7.19%)
ILM=1072/131072 (0.82%)
DLM=50448/130304 (38.72%)
```

## Artifact checksums

```text
027bee676ddc660117a77ef0668d1365a533ed229367bdd49f0f9ba392c9573e  demo.elf
e8cfcd7b1e171518154118f0b3aa26a4d09ccc14f6a50beca02c81bb05f4c404  demo.bin
c7de8030726fc7b0074a61d9b81b41c978cd5a36f28583017bc0d5597d79713f  demo.map
```

## Static descriptor/resource model

`scripts/phase0/validate_usb_composite.py` checks the resource model for all
planned variants. It does not parse compiled descriptors and is not evidence
that CDC or DFU Runtime has been implemented:

| Variant | Interfaces | Data endpoint addresses |
|---|---:|---|
| vendor-only | 1 | `0x01`, `0x81` |
| vendor-cdc | 3 | `0x01`, `0x81`, `0x82`, `0x03`, `0x83` |
| vendor-dfu | 2 | `0x01`, `0x81` |
| vendor-cdc-dfu | 4 | `0x01`, `0x81`, `0x82`, `0x03`, `0x83` |

Highest endpoint number used is 3. The selected HPM5321 SoC header declares
`USB_SOC_DCD_MAX_ENDPOINT_COUNT=16`, so the logical endpoint-number budget
passes with substantial margin. DFU Runtime consumes no non-control endpoint.

The compiled minimal probe includes:

- HS bulk descriptors with 512-byte MPS;
- FS fallback descriptors;
- device qualifier;
- other-speed configuration;
- Microsoft OS 2.0 WinUSB descriptors.

## Hardware deployment and diagnosis

J-Link deployment result:

- probe S/N `607000454`;
- target `HPM5321xCFx`, JTAG 4 MHz;
- VTref `3.303 V`;
- ELF programmed to XPI flash and J-Link verification passed;
- target reset and resumed at `main`.

The target firmware is running, but the development-board USB device did not
appear in either `lsusb` or direct sysfs enumeration.

Target register evidence:

```text
USBCMD       = 0x00000001  # controller running
USBSTS       = 0x00000080
DEVICEADDR   = 0x00000000  # host never completed SET_ADDRESS
PORTSC1      = 0x10000885
USBMODE      = 0x0000500A  # device mode
ENDPTSETUPSTAT/PRIME/COMPLETE = 0
PHY_CTRL0    = 0x00003803  # internal VBUS/session override enabled
PHY_STATUS   = 0x80820058  # UTMI clock valid
```

This proves the application and USB controller are alive, but no control setup
packet reached EP0 and no USB address was assigned. The absence of a host kernel
enumeration event makes the current blocker a physical Type-C/device-attach
path issue rather than a descriptor-resource failure. Check:

- Type-C receptacle CC1/CC2 device-role `Rd` resistors;
- cable data capability and orientation;
- VBUS/ground continuity;
- D+/D- routing to PA24/PA25, polarity, ESD device and soldering;
- whether the tested Type-C connector is the USB0 device connector.

The following remain unproven:

- actual 480 Mbit/s High-Speed negotiation;
- PHY/connector/ESD/VBUS signal integrity;
- Windows WinUSB binding;
- reconnect/stall behavior on the physical board.

## Post-rework enumeration

After the board was reworked, Linux enumerated:

```text
Bus 001 Device 042: ID 34b7:1236 HPMicro HPMicro WinUSB Demo
Negotiated speed: High Speed (480Mbps)
bcdUSB: 2.10
bNumInterfaces: 1
Interface 0: Vendor Specific
EP 0x81 IN: Bulk, wMaxPacketSize=512
EP 0x01 OUT: Bulk, wMaxPacketSize=512
```

The HS enumeration, mandatory vendor interface, endpoint direction and packet
size portions of P0U now pass.

Bulk integrity testing is temporarily blocked by host permissions:

```text
/dev/bus/usb/001/042 root:root 0664
FAIL cannot open 34b7:1236; device absent or access denied
```

The repository now contains:

- `config/udev/99-hpm5321-can-analyzer.rules`;
- `scripts/phase0/usb_bulk_loopback.py`.

## Bulk data-plane results

The udev rule was installed and interface 0 became accessible to `plugdev`.
Real traffic exposed two upstream-demo limitations that were corrected locally:
the OUT buffer was re-armed before IN DMA completion, and an extra IN ZLP became
the following host transaction's zero-byte response. The host test also sends
an OUT ZLP when a partial 2048-byte receive window ends exactly on a 512-byte HS
packet boundary.

```text
1 MiB smoke: PASS, 3.027 MiB/s
chunk matrix: 1,63,64,511,512,513,1024,2048 bytes — all PASS
64 MiB seeded loopback: PASS
seed: 21281
elapsed: 20.989 s
throughput: 3.049 MiB/s
content mismatches: 0
USB software reset + 64 KiB recovery: 10/10 PASS
```

Kernel evidence confirms repeated `reset high-speed USB device` operations with
successful recovery. The authorized descriptor capture also validates the
Microsoft OS 2.0 BOS platform capability.

## Gate disposition

The **Phase 0 minimum USB HS probe gate passes on Linux**: real HS negotiation,
descriptor/BOS correctness, endpoint resource budget, Bulk data integrity and
software-reset recovery all have evidence.

The broader product P0U contract remains `IN_PROGRESS` for the
schematic-approved VBUS policy, Windows/macOS validation, and the Phase 3
10 GiB integrity plus 100 physical reconnect qualification.
