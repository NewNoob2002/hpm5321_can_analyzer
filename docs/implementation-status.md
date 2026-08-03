# Implementation Status

## Product firmware

The root firmware is currently a FreeRTOS/RTT/EasyLogger skeleton with an LED
idle task. It does **not** yet implement the USB-CAN protocol, vendor Bulk data
plane, MCAN service/task, queues, CLI, or host application. A successful root
build is only Gate A build evidence, not analyzer functionality evidence.

## Phase 0 probes

Projects under `tools/phase0/` are isolated hardware-characterization firmware:

- `usb_hs_probe`: USB HS vendor-Bulk probe
- `mcan_internal_probe`: controller-only MCAN0/MCAN2 loopback
- `mcan0_external_probe`: MCAN0 listen-only and bounded Classic CAN traffic

Probe results reduce hardware risk but are not product-feature completion.

## Reproducibility boundary

The custom `hpm5321_custom` board overlay, dependency lock, probes, validators
and approved plans are tracked in Git; all shared CMake examples use
repository-relative `BOARD_SEARCH_PATH`. HPM SDK is
an external dependency. `dependencies/hpm-sdk.lock` pins the desired official
v1.12.1 commit, but the existing builds were made with a local fork commit.
Clean official-SDK builds remain required before Gate A is closed. The current
fork-based ABI-v5 artifact has a destructive clean-rebuild validator, but is
not evidence for the official-SDK Gate.
