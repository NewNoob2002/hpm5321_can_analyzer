# Firmware memory budget

`scripts/build.sh` runs `scripts/env/check_memory_budget.py` after every CMake
preset build. The checker reads the generated GNU ld map, preserves the
linker-reported physical capacities (including DLM `130304` bytes), and fails
on configured product budgets:

| Region | Physical capacity | Product budget | Rationale |
|---|---:|---:|---|
| FLASH | 1 MiB | 950 KiB | leaves room for image growth and metadata |
| ILM | 128 KiB | 120 KiB | leaves 8 KiB execution headroom |
| DLM | 130304 B | 124160 B | requires at least 6 KiB linkable DLM to remain free |
| AHB_SRAM | 32 KiB | 24 KiB | leaves 8 KiB for future DMA/message buffers |

The checker measures each region from its origin to the highest allocated
top-level output-section end. This matches GNU ld's region high-water
accounting and includes alignment gaps plus explicit heap and stack
reservations; summing section sizes alone would under-report occupied DLM.
RAM-only debug builds do not define a `FLASH` region in their linker maps.
For those builds the checker reports `FLASH: N/A` while still requiring and
enforcing the ILM, DLM, and AHB SRAM budgets.

The explicit `hpm5321-ram-debug-bus-off` test-only preset uses the
`bus-off-debug` profile. Only its ILM ceiling changes, from 120 KiB to
126 KiB, leaving at least 2 KiB of physical ILM headroom for the Debug + RAM
fault-injection image. FLASH, DLM, and AHB SRAM limits remain identical to
the product profile. No normal or product preset selects this profile.

The linker defines DLM as origin `0x80300`, length `128K - 768`; the checker
does not reinterpret that capacity. The excluded 768 bytes are at the
beginning of raw DLM (`0x80000..0x802ff`), not additional application
headroom.

HPM5321's advertised 288 KiB SRAM is the aggregate of three separately
addressed banks: 128 KiB ILM0, 128 KiB DLM0, and 32 KiB AHB SRAM. Free space
in ILM0 or AHB SRAM does not automatically extend DLM; objects must be placed
in the appropriate linker section explicitly. With the current release map,
DLM occupies 123328 of 130304 bytes and leaves 6976 bytes linkable headroom.
