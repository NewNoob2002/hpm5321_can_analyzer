# Local Linux Host Toolchain Evidence

Status: `PASS`  
Date: 2026-08-09  
Host: Fedora 44, x86-64

## Toolchains

- `rustc 1.97.1 (8bab26f4f 2026-07-14)`
- `cargo 1.97.1 (c980f4866 2026-06-30)`
- `gcc 16.1.1 20260515 (Red Hat 16.1.1-2)`
- `clang 22.1.8` remains an automatically probed sanitizer fallback
- Fedora `libasan-16.1.1-2.fc44` and `libubsan-16.1.1-2.fc44`

The previously missing GCC sanitizer runtime files are present:
`/usr/lib64/libasan.so.8.0.0` and `/usr/lib64/libubsan.so.1.0.0`. A direct
GCC `-fsanitize=address,undefined` compile and execution returned exit code 0.

## Verification

The following fresh checks passed:

```text
cargo +1.97.1 fmt --manifest-path host/Cargo.toml --all --check
cargo +1.97.1 test --manifest-path host/Cargo.toml --workspace --release --locked
  55 passed; 0 failed
cargo +1.97.1 clippy --manifest-path host/Cargo.toml --workspace --all-targets --release --locked -- -D warnings
python3 -m unittest tests.protocol.test_c_codec_parity -v
  4 passed; C99 byte parity and session scenarios, both ASan/UBSan cases clean
```

`tests/protocol/test_c_codec_parity.py` probes sanitizer linkability rather
than assuming the default compiler runtime is usable. It prefers the selected
C compiler and falls back to Clang when needed. This host no longer blocks
local Rust or sanitizer validation.
