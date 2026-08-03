# ABI-v5 Nonce-Bound One-Shot TX Report

Date: 2026-08-03
Board: `Gerber_PCB1_2026-07-23`, serial `20260723`
ELF SHA-256: `3dd776cc8ef54db777fe9cfeab7d161c355d3cddd290652a6b126c4e43906268`
SDK commit: `88b01b43900d8c30844a1e5cdd3f3b7aff6db40e`

ABI-v5 adds a nonzero 16-bit run nonce. GDB must preserve the nonce and ARM
writes/readback; the terminal result records the same nonce; every CAN payload
is `48 50 <nonce-be16> <sequence-be32>`; metadata and artifact attestation must
match it. The validator rejects ABI-v4 or replayed fixed-payload captures.

## Attempt nonce `0xA503` — safe failure

Raw log: `T-CAN-013-ABI5-nonce-arm-cleanup-gdb.txt`.

The transcript records nonce zero/token zero before ARM, explicit writes and
readback of nonce `0xA503` and token `0x41524D21`, and terminal nonce `0xA503`
with consumed token zero. The external adapter did not ACK: one TX attempt,
zero successes, status 3, TEC 8 and CEL 2. Firmware returned `FAIL`, entered
MCAN INIT, cleared TX request/pending state and disconnected PB00/PB01.

Verdict: fail-closed behavior **PASS**; bounded TX evidence **FAIL/NOT_TESTED**.
Nonce `0xA503` is retired and must not be reused.

## Next run

Reserved nonce: `0xA504`. Status: target and external capture pending. Formal
T-CAN-013 remains NOT_TESTED because the probe has no expiry, USB session
lifecycle, immediate queue or scheduled queue.
