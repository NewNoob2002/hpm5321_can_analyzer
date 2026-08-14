#!/usr/bin/env python3
"""Check GNU ld map memory regions against product budgets."""
import re
import sys
from pathlib import Path

# Absolute budgets leave explicit headroom below each linkable region. DLM's
# SDK capacity remains 130304 B (128 KiB minus the linker-reserved first
# 768 B). Requiring 6 KiB free leaves very little growth allowance at the
# current image while preventing the remaining DLM from being consumed
# silently.
DEFAULT_LIMITS = {
    "FLASH": 950 * 1024,
    "ILM": 120 * 1024,
    "DLM": 130304 - 6 * 1024,
    "AHB_SRAM": 24 * 1024,
}
MEMORY_RE = re.compile(r"^(FLASH|ILM|DLM|AHB_SRAM)\s+0x([0-9a-fA-F]+)\s+0x([0-9a-fA-F]+)")
SECTION_RE = re.compile(r"^\.(\S+)\s+0x([0-9a-fA-F]+)\s+0x([0-9a-fA-F]+)(?:\s|$)")

def parse_map(path):
    text = Path(path).read_text(errors="replace").splitlines()
    regions = {}
    in_memory = False
    for line in text:
        if line.strip() == "Memory Configuration":
            in_memory = True
            continue
        if in_memory:
            m = MEMORY_RE.match(line)
            if m:
                regions[m.group(1)] = (int(m.group(2), 16), int(m.group(3), 16))
            elif regions and line.strip() == "Linker script and memory map":
                break
    if set(regions) != set(DEFAULT_LIMITS):
        raise ValueError(f"missing memory regions in {path}: {set(DEFAULT_LIMITS) - set(regions)}")
    usage = {name: 0 for name in regions}
    for line in text:
        m = SECTION_RE.match(line)
        if not m:
            continue
        address, size = int(m.group(2), 16), int(m.group(3), 16)
        for name, (origin, length) in regions.items():
            if origin <= address < origin + length:
                # GNU ld reports a region's occupied high-water span rather
                # than the sum of output-section sizes. Measuring the highest
                # section end preserves alignment holes between sections.
                usage[name] = max(usage[name], address + size - origin)
                break
    return regions, usage

def check(path, limits=DEFAULT_LIMITS):
    regions, usage = parse_map(path)
    failures = []
    for name in ("FLASH", "ILM", "DLM", "AHB_SRAM"):
        limit = limits[name]
        if usage[name] > limit:
            failures.append(f"{name} {usage[name]} > limit {limit}")
    return regions, usage, failures

def main(argv):
    if len(argv) != 2:
        raise SystemExit("usage: check_memory_budget.py <demo.map>")
    path = argv[1]
    regions, usage, failures = check(path)
    for name in ("FLASH", "ILM", "DLM", "AHB_SRAM"):
        capacity = regions[name][1]
        print(
            f"{name}: {usage[name]} B / {capacity} B "
            f"(free {capacity - usage[name]} B, budget {DEFAULT_LIMITS[name]} B)"
        )
    if failures:
        print("MEMORY BUDGET FAILED: " + "; ".join(failures), file=sys.stderr)
        return 1
    print("MEMORY BUDGET PASS")
    return 0

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
