from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()
