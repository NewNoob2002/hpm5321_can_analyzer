# P3B MCAN0 Product Owner Software Baseline

Date: 2026-08-12  
Status: `PARTIAL` — software/build contract only; no new target or external-bus
verdict is claimed

## Implemented boundary

The root product firmware now replaces the one-shot internal-loopback IRQ task
with a long-running, statically allocated `mcan0_owner`:

- MCAN0 initializes at 1 Mbit/s Classic CAN in `mcan_mode_listen_only`;
- MCAN pads are connected only after successful listen-only initialization;
- TX message RAM is disabled and the public TX submission entry point rejects
  every valid request as `APP_MCAN0_OWNER_TX_REJECTED_DISARMED`;
- the MCAN0 ISR drains RXFIFO0 into a bounded static event queue;
- the owner publishes accepted Classic CAN frames into a bounded 64-record ring
  with 64-bit MCHTMR arrival ticks and monotonic software sequence numbers;
- event-queue and consumer-ring saturation are separate explicit counters;
- warning, error-passive and bus-off indications are snapshotted; this slice
  performs zero automatic bus-off recovery attempts;
- `mcan0_owner` is a required watchdog voter;
- accepted RX records signal `health_task`, which remains the sole runtime GPIO
  writer and pulses the CAN1 RX activity LED; repeated activity is coalesced to
  one pending/active 50 ms pulse so frame-rate load cannot flood the health
  queue. No TX LED pulse is possible in this disarmed slice.

The historical `app_mcan_irq_test` source and target evidence remain archived
as P2 qualification inputs, but that one-shot internal-loopback task is no
longer compiled into product firmware.

The subsequent read-only USB-CAN integration connects the MCAN owner to the
vendor Bulk protocol path. It exposes `GET_MCAN_DIAGNOSTICS`, bounded CAN RX
batches, channel-state edges and explicit loss events. The MCAN owner copies a
120-byte internal diagnostics snapshot containing additional reconciliation
counters; the USB owner projects selected fields into the fixed 104-byte wire
payload instead of serializing the internal structure. This is an
implementation statement only: a current-source/current-image HIL rerun is
still required for qualification.

## 2026-08-14 current-source minimal HIL update

Release ELF
`0687f3cd009e411461c12b5b2e7ac9eb4d9e42872783bf8d950a090fcbbb6770`
was programmed and verified with J-Link. The local, Git-ignored run directory
is `artifacts/hil-2026-08-14/current-source-minimal/`.

- protocol negotiation and `GET_MCAN_DIAGNOSTICS` passed;
- the decoded MCAN wire payload reported `length=104`,
  `state_flags=0x00000007` (initialized, online, listen-only), and zero TX
  armed state;
- `GET_SESSION_STATE` reported capture stopped and TX disarmed;
- a 15-second host-read pause recovered with a subsequent response and zero
  queued response/event/data depth;
- a libusb reset reopened in about 198 ms and changed the session ID from
  `2205762619` to `2205762621`; the new session again reported capture stopped
  and TX disarmed;
- a target reset interrupted the old USB session with an I/O error, after
  re-enumeration a fresh HELLO succeeded with a different session ID;
- the 10-second warmup plus 30-second CAN measurement received zero frames.
  Diagnostics, sequence gaps and all drop counters remained mutually zero, but
  the `>=6000` frame/s acceptance criterion failed because no external CAN
  traffic source was present.

This is partial HIL evidence, not a P3B completion verdict. The raw USB echo
matrix is not relabelled as protocol-session evidence, and the failed sysfs
unbind attempt is not counted as a physical-disconnect pass.

## Software evidence

- Contract tests: `tests/phase3/test_mcan0_owner_contract.py`
- Runtime snapshot commands: `scripts/phase3/mcan0_owner_snapshot.gdb`
- Product sources: `USER/inc/app_mcan0_owner.h` and
  `USER/src/app_mcan0_owner.c`

## Remaining P3B hardware and integration gates

This software baseline does not close P3B or any new `T-CAN-*` test ID. It
still requires:

1. current-image 1 Mbit/s receive proof at `>=6000` frame/s with
   `GET_MCAN_DIAGNOSTICS` and sequence/drop reconciliation under traffic;
2. USB backpressure under CAN load plus state-edge and
   queue/ring/event-drop reconciliation;
3. physical USB disconnect proof that the old session and capture state are
   discarded; USB reset session replacement is already covered by the minimal
   rerun above;
4. external receive and timestamp/bit-timing correlation against an analyzer;
5. the frozen `BP-CAN-MVP-v1` 30-minute load run and non-intrusive
   capture-stop observation;
6. bounded/manual bus-off and fault-injection evidence;
7. protocol/session policy before authorized TX is enabled, including arm
   expiry, ID/DLC/rate/load admission and cancel/TX_RESULT semantics;
8. successful-completion-only CAN1 TX LED evidence after that TX path exists.

Until those gates are archived, P3B remains `PARTIAL` and the firmware must not
advertise an operational TX capability.
