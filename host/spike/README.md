# Phase 1B Host Stack Spike

Both candidates execute the same dependency-free fake-backend workload:

- 1,000,000 fixed-size frames, representing 100 seconds at 10k frame/s;
- deterministic encode/decode and checksum reconciliation;
- disconnect/reconnect every 10,000 frames;
- recovery resumes at the next sequence without duplicate or loss;
- JSON result consumed by `scripts/phase1/run_host_spike.py`.

The C++ implementation isolates the prospective Qt-independent protocol/data
core. It is not evidence for Qt deployment, USB integration or licensing.
