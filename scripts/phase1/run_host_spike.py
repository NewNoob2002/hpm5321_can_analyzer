#!/usr/bin/env python3
import json
from pathlib import Path
import subprocess
import os

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build/host-spike"
BUILD.mkdir(parents=True, exist_ok=True)

subprocess.run(
    ["cargo", "build", "--locked", "--release", "--manifest-path", str(ROOT / "host/Cargo.toml"), "-p", "hpm-host-spike-rust"],
    check=True,
)
subprocess.run(
    ["cmake", "-S", str(ROOT / "host/spike/cpp"), "-B", str(BUILD / "cpp"), "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release"],
    check=True,
)
subprocess.run(["cmake", "--build", str(BUILD / "cpp")], check=True)

binaries = {
    "rust": ROOT / "host/target/release/hpm-host-spike-rust",
    "cpp-core": BUILD / "cpp/hpm-host-spike-cpp",
}
results = {}
for candidate, binary in binaries.items():
    state = BUILD / f"{candidate}.state"
    env = os.environ.copy()
    env.update({"SPIKE_STATE": str(state), "SPIKE_CRASH_AT": "500000"})
    crashed = subprocess.run([str(binary)], env=env, check=False)
    if crashed.returncode != 75 or not state.is_file():
        raise SystemExit(f"{candidate}: controlled crash checkpoint failed")
    env.pop("SPIKE_CRASH_AT")
    result = json.loads(subprocess.check_output([str(binary)], env=env, text=True))
    result["binary_bytes"] = binary.stat().st_size
    result["crash_recovery"] = "pass"
    if result["frames"] != 1_000_000 or result["frames_per_second"] < 10_000:
        raise SystemExit(f"{candidate}: synthetic throughput contract failed")
    if result["reconnects"] != 99 or result["recovered"] != 99:
        raise SystemExit(f"{candidate}: recovery contract failed")
    results[candidate] = result
if results["rust"]["checksum"] != results["cpp-core"]["checksum"]:
    raise SystemExit("candidate checksums differ")

output = BUILD / "result.json"
output.write_text(json.dumps({"schema": 1, "profile": "HOST-SPIKE-10K-v1", "results": results}, indent=2) + "\n")
print(output.read_text(), end="")
