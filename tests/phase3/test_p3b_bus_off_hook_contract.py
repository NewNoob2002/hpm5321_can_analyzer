from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
OWNER = ROOT / "USER/src/app_mcan0_owner.c"
HEADER = ROOT / "USER/inc/app_mcan0_owner.h"


def function_body(source: str, signature: str) -> str:
    start = source.index(signature)
    while True:
        brace = source.index("{", start)
        semicolon = source.find(";", start, brace)
        if semicolon == -1:
            break
        start = source.index(signature, semicolon + 1)
    depth = 0
    for index in range(brace, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"unterminated function: {signature}")


class P3bBusOffHookContractTests(unittest.TestCase):
    def test_hook_is_default_off_debug_ram_only_and_has_dedicated_preset(self):
        cmake = (ROOT / "CMakeLists.txt").read_text()
        presets = (ROOT / "CMakePresets.json").read_text()
        build_script = (ROOT / "scripts/build.sh").read_text()
        manifest = (ROOT / "scripts/env/write_build_manifest.py").read_text()

        self.assertIn("option(APP_MCAN0_BUS_OFF_TEST_HOOK", cmake)
        self.assertRegex(
            cmake,
            r'option\(APP_MCAN0_BUS_OFF_TEST_HOOK[\s\S]+?\n\s+OFF\)',
        )
        self.assertIn("APP_MCAN0_BUS_OFF_TEST_HOOK requires Debug", cmake)
        self.assertIn("APP_MCAN0_BUS_OFF_TEST_HOOK requires HPM_BUILD_TYPE=ram", cmake)
        self.assertIn(
            "APP_MCAN0_BUS_OFF_TEST_HOOK cannot be combined with "
            "APP_FAULT_INJECT_REASON",
            cmake,
        )
        self.assertIn("-DAPP_MCAN0_BUS_OFF_TEST_HOOK=1", cmake)
        self.assertIn("-DAPP_MCAN0_BUS_OFF_TEST_HOOK=0", cmake)
        self.assertIn("hpm5321-ram-debug-bus-off", presets)
        self.assertIn('"APP_MCAN0_BUS_OFF_TEST_HOOK": "ON"', presets)
        self.assertIn('"APP_FAULT_INJECT_REASON": "0"', presets)
        self.assertIn("hpm5321-ram-debug-bus-off", build_script)
        self.assertIn('"APP_MCAN0_BUS_OFF_TEST_HOOK"', manifest)

    def test_hook_has_compile_gate_and_debugger_mailbox_abi(self):
        header = HEADER.read_text()

        self.assertIn("#if APP_MCAN0_BUS_OFF_TEST_HOOK && !defined(DEBUG)", header)
        self.assertIn("#error", header)
        self.assertIn("APP_MCAN0_BUS_OFF_TEST_MAILBOX_MAGIC", header)
        self.assertIn("APP_MCAN0_BUS_OFF_TEST_UNLOCK_TOKEN", header)
        self.assertIn("APP_MCAN0_BUS_OFF_TEST_ARM_TOKEN", header)
        self.assertIn("app_mcan0_bus_off_test_mailbox_t", header)
        self.assertIn("app_mcan0_bus_off_test_result_t", header)
        self.assertIn("g_app_mcan0_bus_off_test_mailbox", header)
        self.assertIn("g_app_mcan0_bus_off_test_result", header)

    def test_product_usb_tx_path_remains_permanently_disarmed(self):
        owner = OWNER.read_text()
        usb = (ROOT / "USER/src/app_usb_owner.c").read_text()

        submit_tx = owner[owner.index("app_mcan0_owner_submit_tx(") :]
        self.assertIn("APP_MCAN0_OWNER_TX_REJECTED_DISARMED", submit_tx)
        self.assertNotIn("mcan_transmit_", submit_tx)
        self.assertIn("channels[0].mode_mask = 0x02U", usb)
        self.assertIn(
            "ucan_config.product_max_bus_load_permille[0] = 0U",
            usb,
        )

    def test_fault_path_is_owner_polled_once_per_boot_and_bounded(self):
        owner = OWNER.read_text()
        start = function_body(owner, "static void start_bus_off_test(")

        self.assertIn("#if APP_MCAN0_BUS_OFF_TEST_HOOK", owner)
        self.assertIn("process_bus_off_test_hook", owner)
        self.assertIn("APP_MCAN0_BUS_OFF_TEST_ACTIVE_TIMEOUT_MS", owner)
        self.assertIn("APP_MCAN0_BUS_OFF_TEST_ACTIVE_POLL_MS", owner)
        self.assertIn("once_per_boot_consumed", owner)
        self.assertIn("run_nonce == 0U", owner)
        self.assertIn("mcan_transmit_via_txbuf_nonblocking", owner)
        self.assertEqual(owner.count("mcan_transmit_via_txbuf_nonblocking"), 1)
        self.assertNotIn("mcan_transmit_blocking", owner)
        self.assertIn("mcan_is_transmit_request_pending", owner)
        self.assertIn("mcan_cancel_tx_buf_send_request", owner)
        self.assertIn("app_watchdog_vote(APP_WATCHDOG_VOTER_MCAN0_OWNER)", owner)
        self.assertGreater(
            start.index("g_app_mcan0_bus_off_test_result.tx_submit_count = 1U"),
            start.index("status_success"),
        )
        self.assertLess(
            start.index("board_disconnect_can(HPM_MCAN0)"),
            start.index(
                "configure_controller(APP_MCAN0_OWNER_MODE_FAULT_NORMAL"
            ),
        )
        self.assertIn(
            "configure_controller(APP_MCAN0_OWNER_MODE_FAULT_NORMAL, false,\n"
            "                              false)",
            start,
        )
        self.assertLess(
            start.index("mcan0_bus_off_test_active = 1U"),
            start.index("enable_controller_irq()"),
        )
        self.assertLess(
            start.index("mcan0_bus_off_test_active = 1U"),
            start.index("board_init_can(HPM_MCAN0)"),
        )
        self.assertLess(
            start.index("board_init_can(HPM_MCAN0)"),
            start.index("mcan_transmit_via_txbuf_nonblocking"),
        )

    def test_bus_off_is_latched_without_automatic_recovery(self):
        owner = OWNER.read_text()
        header = HEADER.read_text()
        isr_latch = function_body(owner, "static void latch_bus_off_from_isr(")
        task_latch = function_body(owner, "static void latch_bus_off(")

        self.assertIn("APP_MCAN0_OWNER_MODE_FAULT_NORMAL", header)
        self.assertIn("APP_MCAN0_OWNER_MODE_BUS_OFF_LATCHED", header)
        self.assertIn("latch_bus_off_from_isr", owner)
        self.assertIn("MCAN_PSR_BO_GET(fault_protocol_status)", owner)
        self.assertIn("mcan0_bus_off_test_latch.pending = 1U", isr_latch)
        self.assertNotIn("mcan_enter_init_mode", isr_latch)
        self.assertNotIn("mcan_deinit", isr_latch)
        self.assertNotIn("mcan_cancel_tx_buf_send_request", isr_latch)
        self.assertNotIn("mcan0_bus_off_test_active = 0U", isr_latch)
        self.assertIn("g_app_mcan0_owner_state.tx_armed = 0U", task_latch)
        self.assertIn("if (mcan0_bus_off_test_active == 0U)", task_latch)
        self.assertIn("mcan0_bus_off_test_latch.pending = 0U", task_latch)
        self.assertIn("taskEXIT_CRITICAL();\n        return;", task_latch)
        self.assertIn("APP_MCAN0_OWNER_MODE_BUS_OFF_LATCHED", owner)
        self.assertIn("MCAN_CCCR_INIT_MASK", owner)
        self.assertIn("board_disconnect_can(HPM_MCAN0)", task_latch)
        self.assertIn("post_cleanup_tx_pending != 0U", task_latch)
        self.assertIn("final_protocol_status", task_latch)
        self.assertNotIn("mcan_recover_from_busoff", owner)
        self.assertIn("automatic_recovery_attempts = 0U", owner)
        self.assertIn("observe_bus_off_test_status", owner)
        capture = function_body(owner, "static void capture_diagnostics(")
        self.assertIn("observe_bus_off_test_status", capture)

    def test_timeout_cleanup_reinitializes_listen_only_fail_closed(self):
        owner = OWNER.read_text()
        cleanup = function_body(
            owner, "static void cleanup_fault_test_to_listen_only("
        )
        containment = function_body(
            owner, "static void contain_fault_test("
        )
        startup_containment = function_body(
            owner, "static void contain_controller_initialization_failure("
        )

        self.assertGreaterEqual(cleanup.count("take_or_sample_bus_off_latch"), 3)
        self.assertIn("board_disconnect_can(HPM_MCAN0)", cleanup)
        self.assertIn("mcan_enter_init_mode(HPM_MCAN0)", cleanup)
        self.assertIn("mcan_deinit(HPM_MCAN0)", cleanup)
        self.assertIn(
            (
                "configure_controller("
                "APP_MCAN0_OWNER_MODE_LISTEN_ONLY, true, true)"
            ),
            cleanup,
        )
        self.assertIn("MCAN_CCCR_MON_MASK", cleanup)
        self.assertIn("HPM_MCAN0->TXBRP == 0U", cleanup)
        self.assertIn("board_disconnect_can(HPM_MCAN0)", containment)
        self.assertIn(
            "contain_controller_initialization_failure()", containment
        )
        self.assertIn(
            "APP_MCAN0_OWNER_MODE_OFFLINE", startup_containment
        )
        self.assertIn("HPM_MCAN0->TXBRP != 0U", containment)
        cancel = function_body(owner, "static bool cancel_bus_off_test_tx(")
        self.assertIn("cancel_timeout_observed = 1U", cancel)
        self.assertIn("return false", cancel)
        self.assertIn("if (!cancel_bus_off_test_tx())", cleanup)
        self.assertIn("contain_fault_test(false)", cleanup)
        final_wait = cleanup.index("if (!wait_for_init_mode())")
        final_bus_off_gate = cleanup.index(
            "if (take_or_sample_bus_off_latch(&latch))",
            final_wait,
        )
        deactivate = cleanup.index(
            "mcan0_bus_off_test_active = 0U", final_bus_off_gate
        )
        reconfigure = cleanup.index(
            "configure_controller(APP_MCAN0_OWNER_MODE_LISTEN_ONLY",
            deactivate,
        )
        self.assertLess(final_wait, final_bus_off_gate)
        self.assertLess(final_bus_off_gate, deactivate)
        self.assertLess(deactivate, reconfigure)

    def test_inactive_poll_does_not_sample_live_psr_or_repeat_terminal_latch(self):
        owner = OWNER.read_text()
        poll = function_body(owner, "static void poll_bus_off_test(")
        sampler = function_body(
            owner, "static bool take_or_sample_bus_off_latch("
        )

        self.assertIn("take_bus_off_latch(&latch)", poll)
        self.assertLess(
            poll.index("if (mcan0_bus_off_test_active == 0U)"),
            poll.index("const uint32_t protocol_status = HPM_MCAN0->PSR"),
        )
        self.assertLess(
            sampler.index("if (mcan0_bus_off_test_active == 0U)"),
            sampler.index("const uint32_t protocol_status = HPM_MCAN0->PSR"),
        )

    def test_startup_configuration_failure_is_forced_offline(self):
        owner = OWNER.read_text()
        task = function_body(owner, "static void mcan0_owner_task(")
        containment = function_body(
            owner, "static void contain_controller_initialization_failure("
        )

        self.assertIn("contain_controller_initialization_failure()", task)
        self.assertIn("board_disconnect_can(HPM_MCAN0)", containment)
        self.assertIn("intc_m_disable_irq(BOARD_CAN0_IRQn)", containment)
        self.assertIn("mcan_enter_init_mode(HPM_MCAN0)", containment)
        self.assertIn("mcan_deinit(HPM_MCAN0)", containment)
        self.assertIn("APP_MCAN0_OWNER_MODE_OFFLINE", containment)

    def test_board_containment_disconnects_only_selected_can_pads(self):
        board = (ROOT / "boards/hpm5321_custom/board.c").read_text()
        pinmux = (ROOT / "boards/hpm5321_custom/pinmux.c").read_text()
        disconnect = function_body(board, "void board_disconnect_can(")
        mcan0_safe = function_body(
            pinmux, "void init_mcan0_safe_gpio_inputs("
        )
        readback = function_body(
            pinmux, "bool mcan0_pads_are_safe_gpio_inputs("
        )

        self.assertIn("init_mcan0_safe_gpio_inputs()", disconnect)
        self.assertIn("init_mcan2_safe_gpio_inputs()", disconnect)
        self.assertIn("GPIO_DI_GPIOB, 0U", mcan0_safe)
        self.assertIn("GPIO_DI_GPIOB, 1U", mcan0_safe)
        self.assertNotIn("GPIO_DI_GPIOB, 8U", mcan0_safe)
        self.assertNotIn("GPIO_DI_GPIOB, 9U", mcan0_safe)
        self.assertIn("IOC_PB00_FUNC_CTL_GPIO_B_00", readback)
        self.assertIn("IOC_PB01_FUNC_CTL_GPIO_B_01", readback)
        self.assertIn("HPM_GPIO0->OE[GPIO_OE_GPIOB].VALUE", readback)
        self.assertIn("board_can_pads_are_disconnected", board)

    def test_manual_hil_assets_forbid_uncontrolled_traffic_and_ack_only_pass(self):
        procedure = (
            ROOT / "docs/development/p3b-bus-off-manual-test.md"
        ).read_text()
        arm_script = (ROOT / "scripts/phase3/p3b_bus_off_arm.gdb").read_text()
        snapshot_script = (
            ROOT / "scripts/phase3/p3b_bus_off_snapshot.gdb"
        ).read_text()
        retrigger_script = (
            ROOT / "scripts/phase3/p3b_bus_off_retrigger.gdb"
        ).read_text()
        retrigger_verify_script = (
            ROOT / "scripts/phase3/p3b_bus_off_retrigger_verify.gdb"
        ).read_text()

        self.assertIn("隔离台架", procedure)
        self.assertIn("禁止连接车辆", procedure)
        self.assertIn("不能仅依赖 ACK error", procedure)
        self.assertIn("PSR.BO", procedure)
        self.assertIn("automatic_recovery_attempts == 0", procedure)
        self.assertIn("cancel_timeout_observed == 0", procedure)
        self.assertIn("post_cleanup_pads_disconnected == 1", procedure)
        self.assertIn("P3B 仍为 `PARTIAL`", procedure)
        self.assertIn("set var g_app_mcan0_bus_off_test_mailbox.command", arm_script)
        self.assertIn("最后写入", arm_script)
        self.assertIn("$_isvoid($p3b_run_nonce)", arm_script)
        self.assertIn('error "', arm_script)
        for script in (
            arm_script,
            snapshot_script,
            retrigger_script,
            retrigger_verify_script,
        ):
            self.assertIn("define error", script)
            self.assertIn("quit 1", script)
        self.assertIn("g_app_mcan0_owner_state.initialized", arm_script)
        self.assertIn("g_app_mcan0_owner_state.online", arm_script)
        self.assertIn("g_app_mcan0_owner_state.automatic_recovery_attempts", arm_script)
        self.assertIn("0xF0280018", arm_script)
        self.assertIn("0xF02800CC", arm_script)
        self.assertIn("g_app_mcan0_bus_off_test_mailbox.reserved", arm_script)
        self.assertNotIn("0x20260815", arm_script)
        self.assertIn("g_app_mcan0_bus_off_test_result", snapshot_script)
        self.assertIn("post_cleanup_pads_disconnected", snapshot_script)
        self.assertIn("state != 3", snapshot_script)
        self.assertIn("final_protocol_status & 0x80", snapshot_script)
        self.assertIn("$_isvoid($p3b_expected_run_nonce)", snapshot_script)
        self.assertIn("$p3b_retrigger_nonce", retrigger_script)
        self.assertIn("$p3b_rejected_before", retrigger_script)
        self.assertNotIn("\ncontinue\n", retrigger_script)
        self.assertIn("$p3b_rejected_before + 1", retrigger_verify_script)
        self.assertIn("$p3b_original_run_nonce", retrigger_verify_script)
        self.assertIn("tx_submit_count != 1", retrigger_verify_script)
        self.assertIn("g_app_mcan0_bus_off_test_mailbox.command != 0", retrigger_verify_script)
        self.assertNotIn("set var ", retrigger_verify_script)


if __name__ == "__main__":
    unittest.main()
