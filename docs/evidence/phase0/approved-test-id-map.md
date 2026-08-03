# Phase 0 Evidence to Approved Test-ID Map

| Phase 0 evidence | Approved test ID | Scope / limitation |
|---|---|---|
| T-CAN-BOOT-001 | T-CAN-012 | Startup pinmux containment and default TX-disarmed state |
| T-CAN-EXT-001 | T-CAN-012 | Listen-only initialization; no external receive claim |
| T-CAN-EXT-002 | T-CAN-003 (partial) | Historical 500 kbit/s bounded-TX timing evidence; source-unbound and sample point was not independently measured |
| T-CAN-RX-002 | T-CAN-003 (partial) | MCAN0 standard Classic receive at 500 kbit/s; sample point was not independently measured |
| Reset-disarmed TX probe | T-CAN-012 (partial, ABI v2) | Historical ELF `06c86cfe...`; proves reset-after-CRT token zero and zero application TX only, not ABI-v4 behavior, `ARM! -> reset -> 0`, reset-to-first-instruction containment, or externally observed zero traffic |
| One-shot arm consumption and post-TX disconnect | T-CAN-013 subcase (NOT_TESTED) | Implementation is prepared to test token consumption, bounded traffic and synchronous cleanup, but ABI-v4 has not run on target; the probe has no arm expiry, USB session reset/disconnect, immediate TX queue, or scheduled-TX queue |

The Phase 0 identifiers are evidence-run identifiers. They do not replace the
approved `T-CAN-001..015` requirements or imply full coverage of a mapped test.
