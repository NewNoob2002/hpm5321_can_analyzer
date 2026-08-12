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

## Software evidence

- Contract tests: `tests/phase3/test_mcan0_owner_contract.py`
- Runtime snapshot commands: `scripts/phase3/mcan0_owner_snapshot.gdb`
- Product sources: `USER/inc/app_mcan0_owner.h` and
  `USER/src/app_mcan0_owner.c`

## Remaining P3B hardware and integration gates

This software baseline does not close P3B or any new `T-CAN-*` test ID. It
still requires:

1. target proof that the product image starts and remains listen-only with
   `tx_armed=0`, correct IRQ priority, stack watermark and zero unexplained
   queue/ring drops;
2. external receive and timestamp/bit-timing correlation against an analyzer;
3. the frozen `BP-CAN-MVP-v1` 30-minute load run;
4. bounded/manual bus-off injection and recovery-policy evidence;
5. protocol/session integration before authorized TX is enabled, including
   arm expiry, ID/DLC/rate/load admission, cancel/TX_RESULT and disconnect/reset
   disarm semantics;
6. successful-completion-only CAN1 TX LED evidence after that TX path exists.

Until those gates are archived, P3B remains `PARTIAL` and the firmware must not
advertise an operational TX capability.
