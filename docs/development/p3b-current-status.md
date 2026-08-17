# P3B current status

Authoritative entry: `docs/evidence/phase3/P3B-current-status.json`.

As of 2026-08-17, P3B is **PARTIAL** and P4E is **BLOCKED**. The qualified
30-minute host/device load gate passed, including the recorded backpressure and
low-rate independent-analyzer checks. Bus-off qualification has not passed: the
2026-08-15 negative-control attempt reached error-passive at TEC 128 and ended
`TIMEOUT_CLEANED_NOT_BUS_OFF`; controlled active error injection and three
independent reproductions remain pending. Active bus-off HIL is now
`DEFERRED_EXTERNAL_FAULT_INJECTION_CAPABILITY` until a qualified injector or
independently qualified equivalent device is available.

The original `BLOCKED_BY_MISSING_TEST_HOOK` record is retained unchanged as
historical evidence. It is no longer authoritative because the debug-only hook
and readiness contract now exist. The current deferral replaces readiness as the
operational gate, but it is not a HIL PASS. Non-bus-off system development is
`AUTHORIZED_WITH_DEFERRED_HARDWARE_GATE`; qualification closure is not.

Formal freeze is additionally blocked until the external raw-evidence records
contain immutable object IDs and locations, and until the full clean-checkout
software command passes at the commit to be tagged.

Deferral authority and resume conditions are recorded in
`docs/evidence/phase3/P3B-bus-off-deferral-2026-08-17.json`. The parallel system
work boundary is documented in
`docs/development/system-functional-completion-plan.md`.
