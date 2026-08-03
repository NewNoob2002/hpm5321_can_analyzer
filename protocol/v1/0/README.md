# USB-CAN Protocol v1.0 Golden Vectors

Files in this directory are canonical lowercase hexadecimal wire bytes with one
space between octets. They are consumed directly by the Rust codec tests and
will later be consumed by the firmware C codec tests.

- `hello-request.hex`: HELLO request, sequence 1, host max message 65536, no features.
