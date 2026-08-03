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
