# MCAN0 External Classic CAN Probe

Two separately built safety stages for an isolated bench containing only the
board and a CAN debugger:

1. `MCAN0_ACTIVE_TX=0`: 500 kbit/s listen-only for 3 seconds.
2. `MCAN0_ACTIVE_TX=1`: boot disarmed in listen-only mode. After every reset a
   debugger must explicitly write `0x41524D21` (`ARM!`) to
   `g_mcan0_tx_arm_token`; the token is consumed before normal mode is entered.
   The probe then transmits exactly 100 Classic CAN frames at 10 ms intervals,
   standard ID `0x123`, DLC 8, payload `48 50 4D 30
   <big-endian-sequence>`. It subsequently deinitializes MCAN, disconnects the
   pinmux, and clears the token.

Both builds disable automatic retransmission and publish the volatile
`g_mcan0_external_result` structure for GDB evidence. This probe is not product
firmware.

The result ABI is version 4 and includes post-cleanup CCCR, IOC FUNC_CTL,
GPIO OE, and GPIOM snapshots. DONE requires the cleanup readback to pass.
Build options accept only literal `0` or `1`;
active TX cannot be combined with either RX-proof option.

For explicit external receive proof, build with `MCAN0_ACTIVE_TX=0` and
`MCAN0_REQUIRE_RX=1`. The target remains listen-only for up to one hour and
passes only after the expected proof frame reaches RXFIFO0.
The required proof frame is Classic CAN standard ID `0x321`, DLC 8, data
`48 50 4D 52 00 00 00 01`.

If the bench has only the sender and this board, also set `MCAN0_ACK_RX=1`.
That selects normal controller mode so the hardware acknowledges a valid
incoming frame; application transmission remains disabled and the build rejects
`MCAN0_ACK_RX=1` unless receive proof is required and active TX is disabled.
For active TX, the debugger must write a fresh nonzero 16-bit
`g_mcan0_tx_run_nonce` before writing `g_mcan0_tx_arm_token=0x41524D21`.
Every transmitted payload is `48 50 <nonce-be16> <sequence-be32>`. Preserve
both writes, their readback, the terminal result and the adapter capture in a
single evidence log. Reusing a nonce invalidates same-run provenance.
