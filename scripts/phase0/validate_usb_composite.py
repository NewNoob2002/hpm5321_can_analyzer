#!/usr/bin/env python3
"""Validate the planned USB composite variants against HPM5321 resources."""

from dataclasses import dataclass


MAX_BIDIRECTIONAL_ENDPOINT_NUMBERS = 16


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
    def endpoints(self) -> tuple[str, ...]:
        result = ["0x01 vendor_out", "0x81 vendor_in"]
        if self.cdc:
            result.extend(
                (
                    "0x82 cdc_notify_in",
                    "0x03 cdc_data_out",
                    "0x83 cdc_data_in",
                )
            )
        return tuple(result)


VARIANTS = (
    Variant("vendor-only", cdc=False, dfu=False),
    Variant("vendor-cdc", cdc=True, dfu=False),
    Variant("vendor-dfu", cdc=False, dfu=True),
    Variant("vendor-cdc-dfu", cdc=True, dfu=True),
)


def validate(variant: Variant) -> None:
    numbers = {int(item.split()[0], 16) & 0x0F for item in variant.endpoints}
    assert 0 not in numbers, f"{variant.name}: EP0 must not appear in data endpoints"
    assert max(numbers) < MAX_BIDIRECTIONAL_ENDPOINT_NUMBERS
    assert len(variant.interfaces) <= 4
    if variant.cdc:
        assert variant.interfaces[1:3] == ("cdc_control", "cdc_data")
    if variant.dfu:
        expected = 3 if variant.cdc else 1
        assert variant.interfaces.index("dfu_runtime") == expected


def main() -> None:
    for variant in VARIANTS:
        validate(variant)
        print(
            f"PASS {variant.name}: bNumInterfaces={len(variant.interfaces)}, "
            f"interfaces={','.join(variant.interfaces)}, "
            f"endpoints={','.join(variant.endpoints)}"
        )
    print(
        "PASS resource budget: highest endpoint number=3, "
        f"HPM5321 bidirectional endpoint-number capacity="
        f"{MAX_BIDIRECTIONAL_ENDPOINT_NUMBERS}"
    )


if __name__ == "__main__":
    main()
