from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
USER = ROOT / "USER"


class RtosBaselineContractTests(unittest.TestCase):
    def test_runtime_objects_and_heap_policy_are_static(self):
        config = (USER / "inc/FreeRTOSConfig.h").read_text()
        health = (USER / "src/app_health.c").read_text()

        self.assertIn("configSUPPORT_STATIC_ALLOCATION      1", config)
        self.assertIn("configSUPPORT_DYNAMIC_ALLOCATION     0", config)
        self.assertIn("xTaskCreateStatic", health)
        self.assertIn("xQueueCreateStatic", health)
        self.assertIn("xTimerCreateStatic", health)
        self.assertNotIn("xTaskCreate(", health)

    def test_health_task_is_the_only_post_bsp_led_writer(self):
        writer_tokens = ("board_led_write(", "board_led_toggle(", "gpio_write_pin(")
        writers = []
        for source in (USER / "src").glob("*.c"):
            text = source.read_text()
            if any(token in text for token in writer_tokens):
                writers.append(source.name)

        self.assertEqual(writers, ["app_health.c"])
        self.assertNotIn("idleTask", (USER / "src/main.c").read_text())

    def test_timebase_uses_stable_high_low_high_sampling(self):
        source = (USER / "src/app_time_core.c").read_text()

        self.assertLess(source.index("high_first = reader(context, 1U)"),
                        source.index("low = reader(context, 0U)"))
        self.assertLess(source.index("low = reader(context, 0U)"),
                        source.index("high_second = reader(context, 1U)"))
        self.assertIn("while (high_first != high_second)", source)

    def test_fault_hooks_and_stack_watermark_are_enabled(self):
        config = (USER / "inc/FreeRTOSConfig.h").read_text()
        hooks = (USER / "src/freertos_hooks.c").read_text()

        self.assertIn("configCHECK_FOR_STACK_OVERFLOW       2", config)
        self.assertIn("configUSE_MALLOC_FAILED_HOOK         1", config)
        self.assertIn("vApplicationStackOverflowHook", hooks)
        self.assertIn("vApplicationMallocFailedHook", hooks)
        self.assertIn("uxTaskGetStackHighWaterMark", (USER / "src/app_health.c").read_text())


if __name__ == "__main__":
    unittest.main()
