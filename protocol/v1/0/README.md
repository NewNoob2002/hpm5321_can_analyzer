# USB-CAN Protocol v1.0 Golden Vectors

Files in this directory are canonical lowercase hexadecimal wire bytes with one
space between octets. They are consumed directly by the Rust codec tests and
will later be consumed by the firmware C codec tests.

- `hello-request.hex`: HELLO request, sequence 1, host max message 65536, no features.
- `hello-response.hex`: negotiated v1.0 session response.
- `device-info-response.hex`: four length-prefixed UTF-8 identity strings.
- `capabilities-response.hex`: HS, one Classic-CAN channel capability snapshot.
- `ping-request.hex` / `ping-response.hex`: timestamp sample 7.
- `error-response.hex`: CONFIG_CHANNEL `INVALID_ARGUMENT` with stable error prefix.
- `config-channel-*` / `get-channel-config-request.hex`: channel configuration CAS examples.
- `start-capture-*` / `stop-capture-*`: capture generation and state transitions.
- `get-diagnostics-*` / `reset-diagnostics-request.hex`: global and channel counters.
- `get-session-state-*`: capture, TX-arm and filter-generation snapshot.
- `set-filters-*` / `clear-filters-*`: filter rules with INVERT/EXT_ONLY and
  CAS generation.
- `tx-arm-*` / `tx-disarm-*`: TX admission rules, arm epoch and expiry.
- `can-tx-request.hex` / `can-tx-response.hex`: immediate TX admission with a
  PENDING ledger snapshot.
- `can-tx-cancel-request.hex` / `can-tx-cancel-response.hex`: idempotent cancel.
- `can-rx-batch.hex`: mixed-channel batch with one Classic and one FD record.
- `can-tx-result.hex`: final SENT result event.
- `channel-state.hex`: ACTIVE with CONFIG_APPLIED reason.
- `flow-control.hex`: depth and pool high-water snapshot.
- `data-loss.hex`: CAN_RING overflow in the CHANNEL sequence domain.

Message-type numbers follow the normative registry in
`docs/approved-plan/usb-can-protocol-v1.md` section 2.3; every file is a full
frame including magic, header, payload and CRC-32C.

Consumers:

- Rust: `host/crates/protocol` reads every vector with `include_str!` and
  asserts byte-exact decode and re-encode.
- C: `protocol/v1/c` implements the same codec; the host parity harness
  `tests/protocol/ucan_vector_test.c` decodes and re-encodes every vector with
  the C codec and requires byte parity, and is run by
  `tests/protocol/test_c_codec_parity.py`.
