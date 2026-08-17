#!/usr/bin/env python3
"""Validate grouping and safety contracts for post-deferral agent prompts."""

from __future__ import annotations

import argparse
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROMPTS = Path("docs/development/p3b-next-step-agent-prompts.md")
DEFAULT_PLAN = Path("docs/development/p3b-next-step-work-plan.md")

PROMPT_HEADINGS = (
    "## 3. Prompt A1",
    "## 4. Prompt A2",
    "## 5. Prompt B1",
    "## 6. Prompt B2",
    "## 7. Prompt C1",
    "## 8. Prompt C2",
    "## 9. Prompt C3",
    "## 10. Prompt D1",
    "## 11. Prompt D2",
    "## 12. Prompt E1",
    "## 13. Prompt V1",
    "## 14. Prompt M1",
)

GOVERNANCE_MARKERS = (
    "P3B=PARTIAL",
    "P4E=BLOCKED",
    "freeze_ready=false",
    "hardware_bus_off=NOT_COMPLETED",
    "hardware_execution_authorized=false",
)

GLOBAL_CONTRACT_MARKERS = (
    "WP0 governance coordinator",
    "protocol + host-core owner",
    "single-channel firmware integrator",
    "host CLI vertical-slice owner",
    "firmware reliability owner",
    "Linux/Windows CLI productization owner",
    "dual-channel owner",
    "independent clean-checkout verifier",
    "deferred active-bus-off capability monitor",
    "B1 独占 protocol/v1/**",
    "C1 独占单通道固件集成热点",
    "C2 只拥有 CLI/application 层",
    "E1 不得在 WP2 与相关 WP3 安全控制验收前开始",
    "NO_CHANGE / REMAINS_DEFERRED",
    "T-E2E-009",
    "T-FW-003",
    ".agents/、.claude/、.codex/、skills-lock.json",
)

FORBIDDEN_EXECUTION_FRAGMENTS = (
    "JLinkExe ",
    "openocd -f",
    "cansend can",
    "candump can",
    "gdb -ex",
)


def repository_file(
    root: Path, value: Path, label: str, errors: list[str]
) -> Path | None:
    rendered = value.as_posix()
    if not rendered or "\\" in rendered:
        errors.append(f"invalid {label}")
        return None
    relative = PurePosixPath(rendered)
    if relative.is_absolute() or any(
        part in {"", ".", ".."} for part in rendered.split("/")
    ):
        errors.append(f"invalid {label}")
        return None
    path = root / rendered
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root.resolve())
    except (FileNotFoundError, ValueError):
        errors.append(f"missing {label}: {rendered}")
        return None
    if path.is_symlink() or not resolved.is_file():
        errors.append(f"{label} must be a regular repository file")
        return None
    return resolved


def prompt_sections(text: str, errors: list[str]) -> list[tuple[str, str]]:
    positions: list[int] = []
    for heading in PROMPT_HEADINGS:
        position = text.find(heading)
        if position < 0:
            errors.append(f"agent prompts missing prompt: {heading}")
        positions.append(position)
    present = [position for position in positions if position >= 0]
    if present != sorted(present):
        errors.append("agent prompt wave order mismatch")
    if len(present) != len(PROMPT_HEADINGS):
        return []

    sections: list[tuple[str, str]] = []
    for index, heading in enumerate(PROMPT_HEADINGS):
        start = positions[index]
        end = positions[index + 1] if index + 1 < len(positions) else len(text)
        sections.append((heading, text[start:end]))
    return sections


def validate(
    root: Path,
    prompts_path: Path = DEFAULT_PROMPTS,
    plan_path: Path = DEFAULT_PLAN,
) -> list[str]:
    root = root.resolve()
    errors: list[str] = []
    prompts = repository_file(root, prompts_path, "agent prompts", errors)
    plan = repository_file(root, plan_path, "next-step work plan", errors)
    if prompts is None or plan is None:
        return errors

    try:
        text = prompts.read_text(encoding="utf-8")
        plan_text = plan.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [f"invalid agent prompt input: {exc}"]

    for marker in GLOBAL_CONTRACT_MARKERS:
        if marker not in text:
            errors.append(f"agent prompts missing grouping contract: {marker}")

    sections = prompt_sections(text, errors)
    for heading, section in sections:
        for marker in GOVERNANCE_MARKERS:
            if marker not in section:
                errors.append(f"{heading} missing governance marker: {marker}")
        for marker in ("rtk", "CodeGraph-first"):
            if marker not in section:
                errors.append(f"{heading} missing operating rule: {marker}")
        if "commit" not in section or "push" not in section:
            errors.append(f"{heading} missing default no-commit boundary")

    single_channel = text.find("## 7. Prompt C1")
    dual_channel = text.find("## 12. Prompt E1")
    if single_channel < 0 or dual_channel < 0 or single_channel >= dual_channel:
        errors.append("agent prompts must sequence single-channel before dual-channel")

    for marker in GOVERNANCE_MARKERS:
        if marker not in plan_text:
            errors.append(f"work plan missing governance marker required by prompts: {marker}")

    for fragment in FORBIDDEN_EXECUTION_FRAGMENTS:
        if fragment in text:
            errors.append(f"agent prompts contain forbidden hardware command: {fragment}")

    return errors


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--prompts", type=Path, default=DEFAULT_PROMPTS)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    args = parser.parse_args()
    errors = validate(args.root.resolve(), args.prompts, args.plan)
    if errors:
        raise SystemExit("; ".join(errors))
    print("PASS P3B next-step agent prompts preserve grouping and safety gates")


if __name__ == "__main__":
    main()
