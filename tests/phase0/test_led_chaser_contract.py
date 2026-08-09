from pathlib import Path
import json
import unittest


ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / "tools/phase0/led_chaser"


class LedChaserContractTests(unittest.TestCase):
    def test_sequence_matches_board_product_mapping(self):
        source = (PROBE / "src/main.c").read_text()
        sequence = (
            "BOARD_LED_GPIO_PIN",
            "BOARD_CAN0_TX_LED_GPIO_PIN",
            "BOARD_CAN0_RX_LED_GPIO_PIN",
            "BOARD_CAN2_TX_LED_GPIO_PIN",
            "BOARD_CAN2_RX_LED_GPIO_PIN",
        )

        positions = [source.index(symbol) for symbol in sequence]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("BOARD_LED_ON_LEVEL", source)
        self.assertIn("BOARD_CAN_LED_ON_LEVEL", source)
        self.assertIn("#define LED_COUNT (5U)", source)

    def test_each_step_turns_every_led_off_before_enabling_one(self):
        source = (PROBE / "src/main.c").read_text()
        step_loop = source[source.index("while (1)") :]

        self.assertLess(step_loop.index("turn_all_leds_off();"),
                        step_loop.index("led_sequence[i].on_level"))
        self.assertNotIn("board_init_can(", source)
        self.assertNotIn("mcan_", source.lower())

    def test_build_exposes_configurable_step_duration(self):
        cmake = (PROBE / "CMakeLists.txt").read_text()

        self.assertIn("set(LED_CHASER_STEP_MS 250 CACHE STRING", cmake)
        self.assertIn("-DLED_CHASER_STEP_MS=${LED_CHASER_STEP_MS}", cmake)
        self.assertIn("sdk_app_src(src/main.c)", cmake)

    def test_target_evidence_records_all_five_routes(self):
        evidence = json.loads(
            (ROOT / "docs/evidence/phase0/T-LED-polarity-2026-08-09.json")
            .read_text()
        )

        self.assertEqual(evidence["target_evidence_status"], "PASS")
        self.assertEqual(evidence["led_chaser"]["completed_cycles_observed"], 2)
        self.assertEqual(
            [result["pin"] for result in evidence["results"]],
            ["PA31", "PY01", "PY02", "PY03", "PA09"],
        )
        for result in evidence["results"]:
            self.assertEqual(result["routing"], "PASS")
            self.assertEqual(result["polarity"], "PASS")
            self.assertEqual(result["default_off"], "PASS")


if __name__ == "__main__":
    unittest.main()
