# System functional completion plan with deferred bus-off HIL

## Objective and boundary

Continue implementing and validating the complete analyzer system while active
bus-off HIL waits for qualified external fault-injection capability. Development
progress and qualification closure are separate: implementation may advance, but
the P3B/P4E/freeze/release gates remain blocked where bus-off is a prerequisite.

## Track A: system functionality — authorized

1. Audit the current P3A, P4P, and non-bus-off P4E gaps against the approved plan
   and assign each gap an implementation owner, test ID, and evidence output.
2. Close the normal single-channel path from MCAN0 capture/configuration through
   USB transport, protocol reconciliation, host core, and CLI presentation.
3. Validate USB disconnect/reconnect, backpressure, queue exhaustion, command
   flood, timeout cleanup, diagnostics, and fail-contained behavior without
   claiming the combined bus-off fault scenario.
4. Implement the second CAN channel and prove channel ownership, attribution,
   isolation, fairness, and non-bus-off reliability before aggregate P5 closure.
5. Complete host CLI/productization work, including deterministic packaging,
   Linux/Windows behavior, diagnostics, and operator-visible failure reporting.
6. Run reliability, memory-budget, watchdog, soak, protocol, and clean-checkout CI
   gates continuously; retain the Debug ILM budget as a high-risk change gate.

Each item may reach implementation/test completion independently. It may not be
used to declare P4E, P5, MVP, Beta, freeze, or release qualification complete
while a required bus-off acceptance criterion remains unresolved.

## Track B: active bus-off HIL — deferred

Preserve the current firmware hook, procedure, evidence schemas, validators, and
historical records without running hardware. Monitor availability of a qualified
fault injector or an independently qualified equivalent development device. Once
available, refresh the safety preflight, obtain new execution authorization, and
perform three independent runs with the frozen artifact identity and 60-second
post-latch observation.

## Change-control rules

- Product changes and bus-off governance/evidence changes use separate commits.
- No synthetic or negative-control result is reclassified as hardware PASS.
- Any firmware identity change requires rebuilding and rebinding future HIL
  artifacts; historical evidence remains attached to its original source identity.
- Resuming Track B is a new controlled action and requires explicit authorization.
