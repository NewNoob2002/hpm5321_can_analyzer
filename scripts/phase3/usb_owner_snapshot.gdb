set pagination off
set confirm off
target remote localhost:2331
monitor halt
printf "P3A_USB magic=%08x version=%u priority=%u irq_requests=%u initialized=%u online=%u connected=%u configured=%u generation=%u connects=%u resets=%u disconnects=%u configurations=%u queue_sends=%u queue_drops=%u stale=%u rx_completions=%u tx_completions=%u rx_bytes=%llu tx_bytes=%llu transfer_errors=%u out_armed=%u in_flight=%u stack=%u\n", g_app_usb_owner_state.magic, g_app_usb_owner_state.version, g_app_usb_owner_state.irq_priority, g_app_usb_owner_state.irq_enable_requests, g_app_usb_owner_state.initialized, g_app_usb_owner_state.online, g_app_usb_owner_state.connected, g_app_usb_owner_state.configured, g_app_usb_owner_state.generation, g_app_usb_owner_state.connect_count, g_app_usb_owner_state.reset_count, g_app_usb_owner_state.disconnect_count, g_app_usb_owner_state.configured_count, g_app_usb_owner_state.queue_send_count, g_app_usb_owner_state.queue_drops, g_app_usb_owner_state.stale_events, g_app_usb_owner_state.rx_completions, g_app_usb_owner_state.tx_completions, g_app_usb_owner_state.rx_bytes, g_app_usb_owner_state.tx_bytes, g_app_usb_owner_state.transfer_errors, g_app_usb_owner_state.out_armed, g_app_usb_owner_state.in_flight, g_app_usb_owner_state.stack_high_watermark
monitor go
detach
quit
