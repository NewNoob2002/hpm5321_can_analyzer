from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROMPTS = Path("docs/development/p3b-next-step-agent-prompts.md")
PLAN = Path("docs/development/p3b-next-step-work-plan.md")


def load_validator():
    path = ROOT / "scripts/phase3/validate_p3b_next_step_agent_prompts.py"
    spec = importlib.util.spec_from_file_location("p3b_next_step_agent_prompts", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validator = load_validator()


class P3bNextStepAgentPromptTests(unittest.TestCase):
    def validate_prompts(self, text: str) -> list[str]:
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = Path(directory) / "prompts.md"
            path.write_text(text, encoding="utf-8")
            return validator.validate(ROOT, path.relative_to(ROOT), PLAN)

    def test_repository_prompts_pass(self):
        self.assertEqual(validator.validate(ROOT, PROMPTS, PLAN), [])

    def test_each_prompt_must_preserve_governance_state(self):
        text = (ROOT / PROMPTS).read_text(encoding="utf-8")
        start = text.index("## 8. Prompt C2")
        end = text.index("## 9. Prompt C3")
        altered = text[:start] + text[start:end].replace(
            "hardware_execution_authorized=false", "", 1
        ) + text[end:]
        self.assertIn(
            "## 8. Prompt C2 missing governance marker: "
            "hardware_execution_authorized=false",
            self.validate_prompts(altered),
        )

    def test_wave_order_cannot_move_dual_channel_before_single_channel(self):
        text = (ROOT / PROMPTS).read_text(encoding="utf-8")
        c1 = text.index("## 7. Prompt C1")
        c2 = text.index("## 8. Prompt C2")
        e1 = text.index("## 12. Prompt E1")
        v1 = text.index("## 13. Prompt V1")
        altered = text[:c1] + text[e1:v1] + text[c1:e1] + text[v1:]
        errors = self.validate_prompts(altered)
        self.assertIn("agent prompt wave order mismatch", errors)
        self.assertIn(
            "agent prompts must sequence single-channel before dual-channel", errors
        )

    def test_protocol_core_exclusive_owner_is_required(self):
        text = (ROOT / PROMPTS).read_text(encoding="utf-8")
        altered = text.replace("B1 独占 protocol/v1/**", "B1 共享 protocol/v1/**", 1)
        self.assertIn(
            "agent prompts missing grouping contract: B1 独占 protocol/v1/**",
            self.validate_prompts(altered),
        )

    def test_hardware_execution_command_is_rejected(self):
        text = (ROOT / PROMPTS).read_text(encoding="utf-8")
        altered = text + "\nJLinkExe -device HPM5321XCFX\n"
        self.assertIn(
            "agent prompts contain forbidden hardware command: JLinkExe ",
            self.validate_prompts(altered),
        )


if __name__ == "__main__":
    unittest.main()
