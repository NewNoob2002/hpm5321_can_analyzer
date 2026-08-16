#!/usr/bin/env python3
"""Check GNU ld map memory regions against product budgets."""
import argparse
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
BUS_OFF_DEBUG_LIMITS = {
    **DEFAULT_LIMITS,
    # The explicit RAM Debug fault-injection image carries debug metadata and
    # test-only control flow in ILM. Keep a separate 2 KiB link headroom gate
    # without weakening any normal/product preset budget.
    "ILM": 126 * 1024,
}
LIMIT_PROFILES = {
    "product": DEFAULT_LIMITS,
    "bus-off-debug": BUS_OFF_DEBUG_LIMITS,
}
REQUIRED_REGIONS = {"ILM", "DLM", "AHB_SRAM"}
REGION_ORDER = ("FLASH", "ILM", "DLM", "AHB_SRAM")
MEMORY_RE = re.compile(r"^(FLASH|ILM|DLM|AHB_SRAM)\s+0x([0-9a-fA-F]+)\s+0x([0-9a-fA-F]+)")
SECTION_RE = re.compile(r"^\.(\S+)\s+0x([0-9a-fA-F]+)\s+0x([0-9a-fA-F]+)(?:\s|$)")
NONALLOC_SECTION_PREFIXES = (
    "comment",
    "debug",
    "gnu.attributes",
    "riscv.attributes",
    "shstrtab",
    "stab",
    "strtab",
    "symtab",
)

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
    missing_regions = REQUIRED_REGIONS - set(regions)
    if missing_regions:
        raise ValueError(
            f"missing memory regions in {path}: {missing_regions}"
        )
    usage = {name: 0 for name in regions}
    for line in text:
        m = SECTION_RE.match(line)
        if not m:
            continue
        if m.group(1).startswith(NONALLOC_SECTION_PREFIXES):
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
    for name in REGION_ORDER:
        if name not in regions:
            continue
        limit = limits[name]
        if usage[name] > limit:
            failures.append(f"{name} {usage[name]} > limit {limit}")
    return regions, usage, failures

def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--profile",
        choices=tuple(LIMIT_PROFILES),
        default="product",
    )
    parser.add_argument("map", type=Path)
    args = parser.parse_args(argv[1:])
    limits = LIMIT_PROFILES[args.profile]
    regions, usage, failures = check(args.map, limits)
    for name in REGION_ORDER:
        if name not in regions:
            print(f"{name}: N/A (region absent from linker map)")
            continue
        capacity = regions[name][1]
        print(
            f"{name}: {usage[name]} B / {capacity} B "
            f"(free {capacity - usage[name]} B, budget {limits[name]} B)"
        )
    if failures:
        print("MEMORY BUDGET FAILED: " + "; ".join(failures), file=sys.stderr)
        return 1
    print("MEMORY BUDGET PASS")
    return 0

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
