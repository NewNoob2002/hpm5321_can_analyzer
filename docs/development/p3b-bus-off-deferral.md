# P3B active bus-off HIL deferral

Authoritative decision record:
`docs/evidence/phase3/P3B-bus-off-deferral-2026-08-17.json`.

As of 2026-08-17, active hardware bus-off qualification is deferred because no
qualified device is available to inject controlled CAN errors after the DUT
enters error-passive. The 2026-08-15 isolated-bench attempt remains valid
negative evidence: warning and error-passive were observed, TEC reached 128,
and the bounded cleanup completed, but bus-off and `PSR.BO=1` were not observed.

This deferral authorizes continued development of non-bus-off system functions.
It does not waive an approved-plan requirement and does not change
`P3B=PARTIAL`, `P4E=BLOCKED`, `freeze_ready=false`, or hardware bus-off status.
In particular, it is not `SKIP-UNSUPPORTED` and cannot be used as release or
qualification evidence.

## Authorized continuation

Work may continue on firmware behavior unrelated to the missing physical fault
source, USB/protocol integration, host core and CLI, single-channel E2E paths
that do not claim bus-off closure, dual-channel implementation, and non-bus-off
reliability. These workstreams must preserve their own test and evidence gates.
Any aggregate P4E, P5, MVP, Beta, freeze, or release decision must still account
for the unresolved P3B bus-off prerequisite.

## Prohibited substitutions

The following cannot satisfy hardware bus-off qualification:

- writing result, latch, PSR, or ECR state through GDB;
- treating silent/no-ACK operation as an active error injector;
- deliberately mismatching bitrate;
- deliberately using incorrect termination, grounding, or wiring.

Such methods either bypass MCAN protocol state or create uncontrolled electrical
conditions. A separately labelled software-only containment test may be added,
but it cannot upgrade the hardware gate.

## Resume conditions

The active HIL track may resume only after all conditions in the machine-readable
decision are met: a qualified injector or equivalent device exists; identity,
capability and limits are recorded; electrical preflight is complete; three runs
and evidence paths are assigned; raw capture is available; and a new explicit
hardware execution authorization is obtained. The existing safety preflight must
then be refreshed against the actual equipment and candidate firmware identity.

Historical attempt, readiness, preflight, and blocker records remain preserved.
No hardware action, freeze, tag, or qualification-state upgrade is authorized by
this document.
