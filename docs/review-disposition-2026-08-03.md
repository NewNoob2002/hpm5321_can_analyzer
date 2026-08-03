# Review Disposition — 2026-08-03

| Review finding | Exists? | Disposition |
|---|---:|---|
| MCAN power-up order unsafe | Yes | Software warm-reset containment fixed and proven by T-CAN-BOOT-001; absolute reset-to-first-instruction safety remains a PCB blocker because STB is hardware-low |
| Overlay contains client/secret keys | Yes | Stale `.hpmpc` removed; misleading EVK READMEs removed; external credential rotation remains owner action if values were real |
| External evidence not reconstructible from revision | Yes | Tracked file-level manifest, dependency lock and clean-rebuild script cover the current ABI-v5 artifact; historical TX evidence remains non-formal |
| CAN validator lacks timing gates | Yes | Strict timestamp monotonicity, 900–1100 ms duration, 8–12 ms mean and 1–20 ms individual interval gates added with negative tests |
| Capture format cannot prove flags/config | Yes | Operator metadata sidecar is mandatory; validator now binds it to exact capture and ELF hashes. Historical capture is explicitly `historical-unbound` because no source manifest was preserved |
| Overlay generation metadata conflicts | Yes | Non-authoritative HPM5361 `.hpmpc` and HPM5300EVK READMEs removed; authoritative adapted sources and regeneration limits documented |
| Listen-only PASS did not prove receive | Yes | Original result relabeled safe-state initialization only; T-CAN-RX-002 normal-mode hardware-ACK receive proof passed with exact ID/DLC/payload and zero errors |
| Portability/Gate A incomplete | Yes | VSCode and clangd personal paths removed; Debug and Release presets added; official v1.12.1 commit locked. Current local SDK is a fork commit, so clean official-SDK build is still open |
| USB endpoint model checks weak | Yes | Raw addresses, duplicate addresses, reserved bits, dynamic SDK-header capacity and computed highest endpoint are checked; regression tests added |
| Active-TX image replays 100 frames after every reset and remains connected | Yes | Fixed: every reset clears a RAM arm token; TX build starts listen-only, consumes a one-shot debugger token before normal mode, then deinitializes MCAN and returns pads to GPIO inputs after TX or failure |
| CMake permits unsafe/ambiguous flag combinations | Yes | Fixed: all flags must be literal 0/1; active TX plus either RX option and ACK_RX without REQUIRE_RX fail at configure time |
| Claimed source-bound TX ELF predates current manifest | Yes | Historical artifacts are superseded. Current ABI-v5 artifact records exact ELF, canonical source manifest, SDK commit, build flags and nonce; `rebuild_current_artifact.sh` performs a clean rebuild before validation |
| Fixes absent from version control | Yes | Closed by Phase 0 commits beginning at `9ac4294`; board overlay, lock, plans, probes, tests and evidence are tracked |
| GPIO mux precedes input-direction establishment | Yes | Fixed order: GPIOM ownership and GPIO input direction are established before FUNC_CTL selects GPIO. T-CAN-012 evidence records PB00/PB01 OE cleared and GPIOM selection |
| RX proof waits up to one hour before checking errors | Yes | Fixed: every polling iteration captures error state and stops on CEL, warning, passive, or bus-off before checking completion |
| Result ABI changed but version stayed 1 | Yes | Fixed: current external-probe result ABI is version 5; historical v1/v2/v4 evidence remains labeled historical |
| Source manifest depends on caller locale | Yes | Fixed: script exports `LC_ALL=C`; byte comparison under default and alternate caller locale passed |
| Evidence IDs do not map to approved IDs | Yes | Added `approved-test-id-map.md`; reset/disarm work maps explicitly to T-CAN-012/013 with partial-coverage limits |
| Python cache files pollute workspace | Yes | Ignore rules and tracked cleanup are committed; the standard test entry disables bytecode generation |
| Board overlay SHA256SUMS is stale while manifest says PASS | Yes | Regenerated all 9 member hashes; `sha256sum -c` passes and the new checksum-file digest is `84e8b800...` |
| Probe cannot fully close approved T-CAN-013 | Yes | Corrected all claims to partial coverage: the probe has no expiry, USB session lifecycle, immediate queue, or scheduled queue |
| Historical capture incorrectly maps to T-CAN-012/013 | Yes | Metadata now maps only to T-CAN-003; validator enforces the exact approved-test-ID list |
| T-CAN-012 reset evidence is incomplete | Yes | Report now explicitly states partial coverage and lists missing `ARM! -> reset -> 0`, external zero-traffic, and pre-first-instruction evidence |
| RX proof accepts Classic DLC 9..15 after size truncation | Yes | Exact `rx.dlc == 8` is now required before the proof counter increments |
| Final RX/TX success omits CEL | Yes | Both final predicates now require `error_logging_count == 0` after the final snapshot |
| Source-bound validator validates only digest syntax | Yes | It now opens the named manifest, verifies its own digest, rejects unsafe paths, and hashes every listed repository member |
| Timestamp negative test exits at capture hash | Yes | Test recomputes the sidecar hash and asserts the timestamp failure; standard discovery is package-enabled and the mandatory runner rejects a missing SDK environment |
| Cleanup snapshot precedes cleanup | Yes | ABI-v4 target evidence passed; ABI-v5 retains the cleanup gates and adds a same-run nonce, with fresh target/external evidence required |
| PARTIAL status is used but undeclared | Yes | `PARTIAL` added to the manifest status vocabulary |
| Current ELF omits actual SDK revision binding | Yes | Lock and artifact JSON now record clean SDK checkout `88b01b43900d8c30844a1e5cdd3f3b7aff6db40e`, matching generated `BUILD_VERSION=88b01b43900d`; official-release Gate remains open |
| CEL is read twice and second read can clear an unreported error | Yes | `capture_status()` now reads ECR exactly once, derives raw/decoded fields from that value, and accumulates CEL across snapshots; cleanup performs a final sampled check |
| ABI cleanup proof omits IOC FUNC_CTL | Yes | ABI v4 records PB00/PB01 FUNC_CTL and gates `cleanup_completed`/DONE on GPIO mux, OE, GPIOM, MCAN INIT and CEL readback |
| MCAN deinit completion is unchecked | Yes | Cleanup now waits with a bounded loop for `CCCR.INIT`, then performs and gates on the complete readback set |
| ARM transition can skip final listen-only error check | Yes | A final single-sample status check now runs after token observation and before token consumption/normal-mode transition |
| Manifest validator accepts empty/subset/duplicate/escaping manifests | Yes | Validator now requires the exact 14-member set, rejects duplicates/extras/missing files, resolves paths and enforces repository containment. Semantics renamed `manifest-bound`; it does not claim build reproducibility by itself |
| `.omx` and Python cache workspace state regressed | Yes | `.omx/`, `.codegraph/` and Python caches are ignored; tracked cache cleanup was committed |
| Internal-loopback HEAD connects physical MCAN pads before init | Yes | Working source removes `board_init_can()`; new ELF `cd5585e7...` ran 8/8 and GDB confirmed PB00/PB01/PB08/PB09 FUNC_CTL remained GPIO-safe (`0`) |
| Internal-loopback evidence points to unsafe old ELF | Yes | Evidence now references the safe ELF, exact SDK commit, source manifest and raw GDB/compare-sections record |
| Historical capture can be relabelled manifest-bound | Yes | Capture validator now accepts only `historical-unbound`; the former positive relabel test is inverted and must fail |
| Current artifact JSON has no validator | Yes | Added `validate_current_artifact.py` plus positive/stale-hash tests; it verifies ELF, canonical manifest, SDK commit/BUILD_VERSION, compile definitions and ABI |
| `cleanup_completed` remains 1 during normal TX | Yes | Cleanup snapshot is invalidated immediately before normal-mode initialization |
| ARM final check omits listen-only mode and critical IR | Yes | ARM checks require INIT=0, MON=1, zero BO/EW/EP/CEL and no ARA/WDI/ELO/BEU/BEC/MRAF/RXFIFO-loss fault bits |
| Target and adapter results lack same-run binding | Yes | ABI-v4 is relabeled independent/unbound. ABI-v5 nonce `0xA504` is verified across debugger write/readback, terminal result, every CAN payload, metadata and attestation; target flash sections are matched to the ELF and replay regression coverage is included |
| Default unittest discovery runs zero tests | Yes | `tests` and `tests.phase0` are packages; `scripts/phase0/run_tests.sh` requires `HPM_SDK_BASE` and cannot silently skip artifact validation |
