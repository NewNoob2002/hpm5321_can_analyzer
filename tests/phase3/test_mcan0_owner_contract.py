from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
USER = ROOT / "USER"


class Mcan0OwnerContractTests(unittest.TestCase):
    def test_hardware_capture_collector_is_read_only(self):
        source = (
            ROOT / "host/crates/core/examples/can_hil_capture.rs"
        ).read_text()

        self.assertIn("msg::START_CAPTURE", source)
        self.assertIn("msg::STOP_CAPTURE", source)
        self.assertIn("msg::CAN_RX_BATCH", source)
        self.assertIn("tx_operations_issued", source)
        self.assertIn("remaining < Duration::from_millis(1)", source)
        self.assertIn("if !host_acceptance", source)
        self.assertIn("Duration::from_millis(100)", source)
        self.assertNotIn("msg::TX_ARM", source)
        self.assertNotIn("msg::CAN_TX", source)

    def test_product_build_replaces_one_shot_irq_probe(self):
        cmake = (ROOT / "CMakeLists.txt").read_text()
        main = (USER / "src/main.c").read_text()

        self.assertIn("sdk_app_src(USER/src/app_mcan0_owner.c)", cmake)
        self.assertNotIn("sdk_app_src(USER/src/app_mcan_irq_test.c)", cmake)
        self.assertIn('#include "app_mcan0_owner.h"', main)
        self.assertIn("app_mcan0_owner_start()", main)
        self.assertNotIn("app_mcan_irq_test_start()", main)

    def test_owner_starts_listen_only_and_keeps_tx_disarmed(self):
        source = (USER / "src/app_mcan0_owner.c").read_text()
        header = (USER / "inc/app_mcan0_owner.h").read_text()

        self.assertIn("mcan_mode_listen_only", source)
        self.assertIn("config.baudrate = APP_MCAN0_OWNER_BITRATE", source)
        self.assertIn("config.enable_canfd = false", source)
        self.assertIn("board_init_can(HPM_MCAN0)", source)
        self.assertIn("MCAN_CCCR_MON_MASK", source)
        self.assertIn("nominal_bit_timing", header)
        self.assertLess(
            source.index("mcan_init(HPM_MCAN0"),
            source.index("board_init_can(HPM_MCAN0)"),
        )
        self.assertIn("APP_MCAN0_OWNER_TX_REJECTED_DISARMED", header)
        self.assertIn("tx_rejected_disarmed", header)
        self.assertIn("request->reserved != 0U", source)
        self.assertNotIn("mcan_transmit_", source)

    def test_500k_preflight_is_a_separate_listen_only_build(self):
        presets = (ROOT / "CMakePresets.json").read_text()
        cmake = (ROOT / "CMakeLists.txt").read_text()

        self.assertIn("hpm5321-flash-release-500k-preflight", presets)
        self.assertIn('"APP_MCAN_BITRATE": "500000"', presets)
        self.assertIn("-DAPP_MCAN0_OWNER_BITRATE=${APP_MCAN_BITRATE}U", cmake)

    def test_owner_uses_static_bounded_isr_and_rx_queues(self):
        source = (USER / "src/app_mcan0_owner.c").read_text()
        header = (USER / "inc/app_mcan0_owner.h").read_text()

        self.assertRegex(header, r"APP_MCAN0_OWNER_ISR_PRIORITY\s+\(4U\)")
        self.assertIn(
            "APP_IRQ_ASSERT_FREERTOS_API_PRIORITY(APP_MCAN0_OWNER_ISR_PRIORITY)",
            source,
        )
        self.assertIn("SDK_DECLARE_EXT_ISR_M(BOARD_CAN0_IRQn", source)
        self.assertIn("xQueueSendFromISR", source)
        self.assertIn("mcan_is_interrupt_flag_set", source)
        self.assertIn("xQueueCreateStatic", source)
        self.assertIn("xTaskCreateStatic", source)
        self.assertIn("APP_MCAN0_OWNER_EVENT_QUEUE_LENGTH", header)
        self.assertIn("APP_MCAN0_OWNER_RX_RING_CAPACITY", header)
        self.assertRegex(
            header, r"APP_MCAN0_OWNER_EVENT_QUEUE_LENGTH\s+\(64U\)"
        )
        self.assertRegex(
            source, r"APP_MCAN0_OWNER_TASK_PRIORITY\s+\(4U\)"
        )
        self.assertIn("app_mcan0_owner_pop_rx", source)
        self.assertNotIn("xQueueCreate(", source)
        self.assertNotIn("xTaskCreate(", source)
        self.assertNotIn("pvPortMalloc", source)

    def test_owner_records_timestamp_loss_and_bus_state(self):
        source = (USER / "src/app_mcan0_owner.c").read_text()
        header = (USER / "inc/app_mcan0_owner.h").read_text()

        self.assertIn("app_time_now()", source)
        self.assertIn("mcan_get_diagnostic_snapshot", source)
        self.assertIn("MCAN_INT_BUS_OFF_STATUS", source)
        self.assertIn("automatic_recovery_attempts", header)
        self.assertIn("queue_drops", header)
        self.assertIn("ring_drops", header)
        self.assertIn("ring_count", header)
        self.assertIn("last_rx_tick", header)
        self.assertIn("bus_off_count", header)
        self.assertNotIn("mcan_recover_from_busoff", source)

    def test_owner_votes_and_health_owns_can1_led_gpio(self):
        watchdog = (USER / "inc/app_watchdog.h").read_text()
        owner = (USER / "src/app_mcan0_owner.c").read_text()
        health = (USER / "src/app_health.c").read_text()

        self.assertIn("APP_WATCHDOG_VOTER_MCAN0_OWNER = 3", watchdog)
        self.assertIn(
            "APP_WATCHDOG_VOTER_MASK(APP_WATCHDOG_VOTER_MCAN0_OWNER)",
            watchdog,
        )
        self.assertIn(
            "app_watchdog_vote(APP_WATCHDOG_VOTER_MCAN0_OWNER)", owner
        )
        self.assertIn("app_health_signal_can0_rx", owner)
        self.assertNotIn("gpio_write_pin", owner)
        self.assertIn("APP_HEALTH_EVENT_CAN0_RX", health)
        self.assertIn("BOARD_CAN0_RX_LED_GPIO_PIN", health)
        self.assertIn("can0_rx_activity_pending", health)
        self.assertIn("should_queue = !*pending", health)
        self.assertEqual(health.count("app_watchdog_evaluate()"), 1)
        self.assertLess(
            health.index("event == APP_HEALTH_EVENT_HEARTBEAT"),
            health.index("app_watchdog_evaluate()"),
        )

    def test_snapshot_script_covers_product_owner(self):
        snapshot = (ROOT / "scripts/phase3/mcan0_owner_snapshot.gdb").read_text()

        for field in (
            "mode",
            "tx_armed",
            "frames_received",
            "queue_drops",
            "ring_drops",
            "bus_off_count",
            "last_rx_tick",
            "stack_high_watermark",
        ):
            self.assertIn(f"g_app_mcan0_owner_state.{field}", snapshot)


if __name__ == "__main__":
    unittest.main()
