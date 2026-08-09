# HPM5321 SPI2 SD Read-Only Probe

Phase 0 characterization firmware for the repository SPI2/PY00 contract. It
uses a repository-owned polling adapter, derived from the locked HPM SDK
SPI-SD sample adapter, in SPI mode 0 at 400 kHz initialization and a 20 MHz
data ceiling. The probe checks the active-low PY00 signal through
`board_is_sd_card_present()`, initializes the card, records CID/CSD and
geometry, reads sector 0, and mounts the filesystem to require FAT32.

The probe is intentionally read-only: it never calls a block or filesystem
write API. Individual polling transfers use a 1000 ms timeout and propagate
errors instead of trapping in the adapter. The locked SDK card protocol still
contains long/unbounded response loops, so this offline probe does not prove
bounded end-to-end deadlines, write throughput, truthful `CTRL_SYNC`,
power-cut durability or the P3C1 production adapter.

The locked SDK 1.12.1 card layer supplies `0x86` for CMD8's CRC byte. The
repository adapter corrects its local transmit copy to the required `0x87`
(CRC7 plus end bit) and leaves all other commands unchanged. Bus diagnostics
retain the last command/argument and response counters for target evidence.

```sh
export HPM_SDK_BASE=/path/to/hpm_sdk
export CCACHE_DISABLE=1
cmake -S tools/phase0/spi_sd_probe \
  -B build/phase0-spi-sd-probe -G Ninja \
  -DBOARD=hpm5321_custom -DBOARD_SEARCH_PATH="$PWD/boards" \
  -DHPM_BUILD_TYPE=flash_xip -DCMAKE_BUILD_TYPE=Debug
cmake --build build/phase0-spi-sd-probe
```

After flashing and allowing initialization to complete, read
`g_spi_sd_probe_result` through J-Link/GDB. `magic == 0x50415353` (`PASS`)
requires a present card, successful SPI/card initialization, a 512-byte sector
read and a FAT32 mount. `0x4E4D4544` (`NMED`) records an empty slot without
attempting SPI traffic.

Run the probe once per P0S media-matrix card and archive the exact ELF hash,
result structure and physical card label. The required matrix remains two
vendors for each claimed 4/8/16/32 GB capacity.
