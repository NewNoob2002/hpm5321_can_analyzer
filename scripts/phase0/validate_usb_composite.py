#!/usr/bin/env python3
"""Validate only the planned USB composite resource model.

This script does not parse firmware descriptors and must not be used as
evidence that optional CDC or DFU interfaces are implemented.
"""

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import re


CAPACITY_RE = re.compile(
    r"^#define\s+USB_SOC_DCD_MAX_ENDPOINT_COUNT\s+\((\d+)U\)\s*$",
    re.MULTILINE,
)


@dataclass(frozen=True)
class Variant:
    name: str
    cdc: bool
    dfu: bool

    @property
    def interfaces(self) -> tuple[str, ...]:
        result = ["vendor"]
        if self.cdc:
            result.extend(("cdc_control", "cdc_data"))
        if self.dfu:
            result.append("dfu_runtime")
        return tuple(result)

    @property
    def endpoints(self) -> tuple[tuple[int, str], ...]:
        result = [(0x01, "vendor_out"), (0x81, "vendor_in")]
        if self.cdc:
            result.extend(
                (
                    (0x82, "cdc_notify_in"),
                    (0x03, "cdc_data_out"),
                    (0x83, "cdc_data_in"),
                )
            )
        return tuple(result)


VARIANTS = (
    Variant("vendor-only", cdc=False, dfu=False),
    Variant("vendor-cdc", cdc=True, dfu=False),
    Variant("vendor-dfu", cdc=False, dfu=True),
    Variant("vendor-cdc-dfu", cdc=True, dfu=True),
)


class ValidationError(RuntimeError):
    """Raised when the planned resource model violates a constraint."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def load_endpoint_capacity(soc_feature: Path) -> int:
    match = CAPACITY_RE.search(soc_feature.read_text())
    if match is None:
        raise ValidationError(
            f"USB_SOC_DCD_MAX_ENDPOINT_COUNT not found in {soc_feature}"
        )
    return int(match.group(1))


def validate(variant: Variant, max_endpoint_count: int) -> None:
    addresses = [address for address, _ in variant.endpoints]
    require(
        len(addresses) == len(set(addresses)),
        f"{variant.name}: duplicate endpoint address",
    )
    require(
        all(0 <= address <= 0x8F and (address & 0x70) == 0 for address in addresses),
        f"{variant.name}: malformed endpoint address",
    )
    numbers = [address & 0x0F for address in addresses]
    require(0 not in numbers, f"{variant.name}: EP0 appears in data endpoints")
    require(
        bool(numbers)
        and all(number < max_endpoint_count for number in numbers),
        f"{variant.name}: endpoint number exceeds controller capacity",
    )
    require(
        len(variant.interfaces) <= 4,
        f"{variant.name}: planned interface count exceeds model limit",
    )
    if variant.cdc:
        require(
            variant.interfaces[1:3] == ("cdc_control", "cdc_data"),
            f"{variant.name}: CDC control/data ordering is invalid",
        )
    if variant.dfu:
        expected = 3 if variant.cdc else 1
        require(
            variant.interfaces.index("dfu_runtime") == expected,
            f"{variant.name}: DFU interface position is invalid",
        )


def main() -> None:
    default_soc_feature = None
    if os.environ.get("HPM_SDK_BASE"):
        default_soc_feature = Path(os.environ["HPM_SDK_BASE"]) / (
            "soc/HPM5300/HPM5361/hpm_soc_feature.h"
        )
    parser = argparse.ArgumentParser()
    parser.add_argument("--soc-feature", type=Path, default=default_soc_feature)
    args = parser.parse_args()
    if args.soc_feature is None:
        raise SystemExit("set HPM_SDK_BASE or pass --soc-feature")
    max_endpoint_count = load_endpoint_capacity(args.soc_feature)

    for variant in VARIANTS:
        validate(variant, max_endpoint_count)
        print(
            f"MODEL-PASS {variant.name}: bNumInterfaces={len(variant.interfaces)}, "
            f"interfaces={','.join(variant.interfaces)}, "
            f"endpoints={','.join(f'0x{address:02X} {name}' for address, name in variant.endpoints)}"
        )
    highest_endpoint = max(
        address & 0x0F for variant in VARIANTS for address, _ in variant.endpoints
    )
    print(
        f"MODEL-PASS resource budget: highest endpoint number={highest_endpoint}, "
        f"HPM5321 bidirectional endpoint-number capacity="
        f"{max_endpoint_count} source={args.soc_feature}"
    )


if __name__ == "__main__":
    main()
