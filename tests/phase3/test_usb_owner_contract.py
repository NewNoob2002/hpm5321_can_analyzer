from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
USER = ROOT / "USER"


class UsbOwnerContractTests(unittest.TestCase):
    def test_root_firmware_enables_cherryusb_device(self):
        cmake = (ROOT / "CMakeLists.txt").read_text()

        self.assertIn("set(CONFIG_CHERRYUSB 1)", cmake)
        self.assertIn("set(CONFIG_CHERRYUSB_DEVICE 1)", cmake)
        self.assertIn("set(CONFIG_USB_DEVICE 1)", cmake)
        self.assertIn("sdk_inc(config)", cmake)
        self.assertIn("sdk_app_src(USER/src/app_usb_owner.c)", cmake)
        self.assertIn("usb_osal_freertos.c", cmake)
        self.assertIn("list(REMOVE_ITEM APP_HPM_SDK_SOURCES", cmake)

    def test_usb_owner_uses_static_freertos_objects_and_irq_queue(self):
        source = (USER / "src/app_usb_owner.c").read_text()
        header = (USER / "inc/app_usb_owner.h").read_text()

        self.assertRegex(
            header, r"APP_USB_OWNER_ISR_PRIORITY\s+\(4U\)"
        )
        self.assertIn(
            "APP_IRQ_ASSERT_FREERTOS_API_PRIORITY(APP_USB_OWNER_ISR_PRIORITY)",
            source,
        )
        self.assertIn("xQueueCreateStatic", source)
        self.assertIn("xTaskCreateStatic", source)
        self.assertIn("xQueueSendFromISR", source)
        self.assertIn("xPortIsInsideInterrupt", source)
        self.assertIn("intc_m_enable_irq_with_priority", source)
        self.assertIn("void hpm_usb_isr_enable(uint32_t base)", source)
        self.assertNotIn("xQueueCreate(", source)
        self.assertNotIn("xTaskCreate(", source)
        self.assertNotIn("pvPortMalloc", source)

    def test_vendor_bulk_descriptor_contract(self):
        cmake = (ROOT / "CMakeLists.txt").read_text()
        config = (ROOT / "config/usb_config.h").read_text()
        source = (USER / "src/app_usb_owner.c").read_text()
        header = (USER / "inc/app_usb_owner.h").read_text()

        self.assertRegex(config, r"USBD_VID\s+\(0x34B7U\)")
        self.assertRegex(config, r"USBD_PID\s+\(0x1236U\)")
        self.assertIn("CONFIG_USB_HS", config)
        self.assertIn("APP_USB_FORCE_FULL_SPEED", cmake)
        self.assertIn("CONFIG_USB_DEVICE_FORCE_FULL_SPEED", cmake)
        self.assertRegex(header, r"APP_USB_OWNER_OUT_EP\s+\(0x01U\)")
        self.assertRegex(header, r"APP_USB_OWNER_IN_EP\s+\(0x81U\)")
        self.assertRegex(
            header, r"APP_USB_OWNER_TRANSFER_SIZE\s+\(2048U\)"
        )
        self.assertIn("USB_BULK_EP_MPS_HS", source)
        self.assertIn("USB_BULK_EP_MPS_FS", source)
        self.assertIn("USB_DEVICE_QUALIFIER_DESCRIPTOR_INIT", source)
        self.assertIn("USB_OTHER_SPEED_CONFIG_DESCRIPTOR_INIT", source)
        self.assertIn("USB_BOS_CAP_PLATFORM_WINUSB_DESCRIPTOR_INIT", source)
        self.assertIn("USB_MSOSV2_COMP_ID_FUNCTION_WINUSB_SINGLE", source)

    def test_owner_wires_bulk_stream_to_ucan_session(self):
        source = (USER / "src/app_usb_owner.c").read_text()
        mcan = (USER / "src/app_mcan0_owner.c").read_text()
        header = (USER / "inc/app_usb_owner.h").read_text()
        cmake = (ROOT / "CMakeLists.txt").read_text()

        self.assertIn("protocol/v1/c/ucan_codec.c", cmake)
        self.assertIn("protocol/v1/c/ucan_session.c", cmake)
        self.assertIn("ucan_stream_decoder_feed", source)
        self.assertIn("ucan_session_handle_frame", source)
        self.assertIn("ucan_session_dequeue", source)
        self.assertIn("ucan_session_on_rx", source)
        self.assertIn("ucan_session_emit_rx_batch_records_at", source)
        self.assertIn("APP_UCAN_RX_BATCH_MAX_RECORDS", source)
        self.assertIn("APP_UCAN_RX_BATCH_WAIT_US", source)
        self.assertIn("APP_USB_EVENT_CAN_RX_READY", source)
        self.assertIn("can_rx_event_pending", source)
        self.assertIn("app_usb_owner_signal_can_rx", header)
        self.assertIn("app_usb_owner_signal_can_rx()", mcan)
        self.assertNotIn("APP_USB_OWNER_STARTUP_DELAY_MS", source)

    def test_owner_refreshes_protocol_clock_before_request_dispatch(self):
        source = (USER / "src/app_usb_owner.c").read_text()
        loop = source[source.index("while (1) {"):]

        clock = loop.index("advance_protocol_clock();")
        dispatch = loop.index("process_event(&event);")
        self.assertLess(clock, dispatch)

    def test_owner_uses_level_safe_rx_drain_with_bounded_batch_poll(self):
        source = (USER / "src/app_usb_owner.c").read_text()
        drain = source[
            source.index("static void complete_can_rx_drain(void)") :
            source.index("static uint32_t read_irq_priority")
        ]
        loop = source[source.index("while (1) {") :]

        self.assertIn(
            "mcan_rx_batch_count != 0U || app_mcan0_owner_rx_pending()",
            source,
        )
        self.assertNotIn("can_rx_drain_ack_pending", source)
        self.assertIn("complete_can_rx_drain();", source)
        self.assertIn("can_rx_event_pending = false", drain)
        self.assertIn("app_mcan0_owner_rx_pending()", drain)
        self.assertIn("app_usb_owner_signal_can_rx();", drain)
        self.assertNotIn("return;", drain)
        self.assertLess(
            loop.index("publish_mcan_rx();"),
            loop.index("complete_can_rx_drain();"),
        )
        self.assertNotIn(
            "ucan_session.capture_state != 0U || mcan_rx_batch_count != 0U",
            source,
        )

    def test_owner_splits_nonmonotonic_timestamp_batches_and_checks_emit(self):
        source = (USER / "src/app_usb_owner.c").read_text()

        self.assertIn("source.timestamp_tick < previous_timestamp", source)
        self.assertIn(
            "mcan_rx_batch_records[mcan_rx_batch_count - 1U]",
            source,
        )
        self.assertRegex(
            source,
            r"if \(ucan_session_emit_rx_batch_records_at\([\s\S]*?\) != 0\)",
        )

    def test_read_only_requests_do_not_force_rx_batch_flush(self):
        source = (USER / "src/app_usb_owner.c").read_text()
        dispatch = source[
            source.index("static void dispatch_usb_chunk(void)") :
            source.index("static uint8_t mcan_channel_state")
        ]
        rx_case = source[
            source.index("case APP_USB_EVENT_RX_COMPLETE:") :
            source.index("case APP_USB_EVENT_TX_COMPLETE:")
        ]

        self.assertIn("request_is_mcan_batch_boundary(request.message_type)", dispatch)
        self.assertIn("case UCAN_MSG_START_CAPTURE:", source)
        self.assertIn("case UCAN_MSG_STOP_CAPTURE:", source)
        self.assertNotIn("flush_mcan_rx_batch();", rx_case)

    def test_owner_advertises_extended_id_capture(self):
        source = (USER / "src/app_usb_owner.c").read_text()

        self.assertIn("ucan_config.channels[0].feature_bits = 0x0079U", source)
        self.assertIn("source.use_ext_id ? 0x0001U : 0U", source)

    def test_mcan_diagnostics_projects_internal_snapshot_to_wire_contract(self):
        source = (USER / "src/app_usb_owner.c").read_text()
        codec = (ROOT / "protocol/v1/c/ucan_codec.c").read_text()

        self.assertIn(
            "snapshot.snapshot_length != APP_MCAN0_DIAGNOSTICS_SNAPSHOT_LEN",
            source,
        )
        self.assertIn(
            "diagnostics->length = UCAN_MCAN_DIAGNOSTICS_LEN",
            source,
        )
        self.assertNotIn("diagnostics->length = snapshot.", source)
        self.assertIn(
            "_Static_assert(sizeof(ucan_mcan_diagnostics_t)",
            codec,
        )
        self.assertIn(
            "offsetof(ucan_mcan_diagnostics_t, ring_drops) == 80U",
            codec,
        )

    def test_owner_preserves_protocol_tx_buffer_until_in_completion(self):
        source = (USER / "src/app_usb_owner.c").read_text()

        rx_case = source.index("case APP_USB_EVENT_RX_COMPLETE:")
        tx_case = source.index("case APP_USB_EVENT_TX_COMPLETE:")
        rx_body = source[rx_case:tx_case]
        tx_body = source[tx_case:]
        self.assertNotIn("usbd_ep_start_write", rx_body)
        self.assertIn("arm_out_transfer", rx_body)
        self.assertIn("start_next_in_transfer", tx_body)
        self.assertIn("arm_out_transfer", tx_body)
        self.assertRegex(
            tx_body,
            r"usb_chunk_offset\s*==\s*usb_chunk_length[\s\S]*?"
            r"response_pending\s*==\s*0U[\s\S]*?arm_out_transfer",
        )
        self.assertIn("stale_events", source)
        self.assertIn("generation", source)

    def test_owner_batches_rx_and_coalesces_usb_in_frames(self):
        source = (USER / "src/app_usb_owner.c").read_text()

        self.assertRegex(
            source,
            r"usb_in_buffer\[APP_USB_OWNER_TRANSFER_SIZE\]",
        )
        self.assertIn(
            "#define APP_USB_OWNER_IN_AGGREGATE_MAX "
            "APP_USB_OWNER_TRANSFER_SIZE",
            source,
        )
        self.assertIn(
            "APP_USB_OWNER_IN_AGGREGATE_MAX - length >=",
            source,
        )
        self.assertIn("flush_mcan_rx_batch", source)
        self.assertIn("mcan_rx_batch_record_bytes", source)
        self.assertIn("UCAN_SESSION_MAX_RX_BATCH", source)
        self.assertIn(
            "ucan_session_dequeue(&ucan_session, usb_in_buffer + length",
            source,
        )
        self.assertIn("mcan_rx_batch_payload_limit", source)
        self.assertIn("ucan_session.host_rx_max_message", source)

    def test_usb_in_exact_mps_aggregate_uses_retryable_zlp(self):
        source = (USER / "src/app_usb_owner.c").read_text()

        self.assertIn("usb_in_zlp_pending", source)
        self.assertIn("usb_in_zlp_in_flight", source)
        self.assertIn("usbd_get_ep_mps", source)
        self.assertRegex(
            source,
            r"event->length\s*%\s*endpoint_mps\s*==\s*0U"
            r"[\s\S]*?usb_in_zlp_pending\s*=\s*true",
        )
        zlp_branch = source[
            source.index("if (usb_in_zlp_pending) {"):
            source.index("uint32_t length = 0U;")
        ]
        self.assertIn(
            "usbd_ep_start_write(APP_USB_BUS_ID, APP_USB_OWNER_IN_EP, "
            "NULL, 0U)",
            zlp_branch,
        )
        self.assertRegex(
            zlp_branch,
            r"usbd_ep_start_write[\s\S]*?!=\s*0[\s\S]*?return false;"
            r"[\s\S]*?usb_in_zlp_pending\s*=\s*false",
        )
        self.assertIn("usb_in_zlp_in_flight = false", source)

    def test_usb_owner_is_a_required_watchdog_voter(self):
        watchdog = (USER / "inc/app_watchdog.h").read_text()
        source = (USER / "src/app_usb_owner.c").read_text()

        self.assertIn("APP_WATCHDOG_VOTER_USB_OWNER = 2", watchdog)
        self.assertIn(
            "APP_WATCHDOG_VOTER_MASK(APP_WATCHDOG_VOTER_USB_OWNER)",
            watchdog,
        )
        self.assertIn(
            "app_watchdog_vote(APP_WATCHDOG_VOTER_USB_OWNER)", source
        )

    def test_usb_owner_enables_rng_clock_before_identity_generation(self):
        source = (USER / "src/app_usb_owner.c").read_text()

        clock_enable = source.index("clock_add_to_group(clock_rng, 0)")
        rng_init = source.index("rng_init(HPM_RNG)")
        self.assertLess(clock_enable, rng_init)

    def test_gdb_snapshot_covers_usb_runtime_contract(self):
        snapshot = (
            ROOT / "scripts/phase3/usb_owner_snapshot.gdb"
        ).read_text()

        self.assertIn("g_app_usb_owner_state.irq_priority", snapshot)
        self.assertIn("g_app_usb_owner_state.queue_drops", snapshot)
        self.assertIn("g_app_usb_owner_state.rx_bytes", snapshot)
        self.assertIn("g_app_usb_owner_state.tx_bytes", snapshot)
        self.assertIn("g_app_usb_owner_state.transfer_errors", snapshot)
        self.assertIn("g_app_usb_owner_state.stack_high_watermark", snapshot)


if __name__ == "__main__":
    unittest.main()
