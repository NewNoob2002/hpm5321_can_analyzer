set pagination off
set confirm off

# Pinned GNU GDB 13.2 has no built-in `error` command. Keep every guard
# fail-closed with a non-zero process exit status.
define error
  echo ERROR: $arg0\n
  quit 1
end

target remote localhost:2331
monitor halt

printf "P3B_BUS_OFF_SNAPSHOT\n"
if g_app_mcan0_bus_off_test_result.magic != 0x424f4652
  error "wrong image/hook ABI: result magic mismatch"
end
if g_app_mcan0_bus_off_test_result.version != 2
  error "wrong image/hook ABI: result version mismatch"
end
if g_app_mcan0_bus_off_test_result.size != sizeof(g_app_mcan0_bus_off_test_result)
  error "wrong image/hook ABI: result size mismatch"
end
if !$_isvoid($p3b_expected_run_nonce)
  if g_app_mcan0_bus_off_test_result.run_nonce != $p3b_expected_run_nonce
    error "result run nonce does not match $p3b_expected_run_nonce"
  end
end

set $p3b_live_cccr = *(unsigned int *)0xF0280018
set $p3b_live_txbrp = *(unsigned int *)0xF02800CC
if g_app_mcan0_bus_off_test_result.state == 1
  if g_app_mcan0_bus_off_test_result.once_per_boot_consumed != 0
    error "preflight once-per-boot state is already consumed"
  end
  if g_app_mcan0_owner_state.initialized != 1
    error "preflight MCAN0 owner is not initialized"
  end
  if g_app_mcan0_owner_state.online != 1
    error "preflight MCAN0 owner is not online"
  end
  if g_app_mcan0_owner_state.mode != 1
    error "preflight MCAN0 owner is not listen-only"
  end
  if g_app_mcan0_owner_state.tx_armed != 0
    error "preflight MCAN0 TX is armed"
  end
  if ($p3b_live_cccr & 0x20) == 0
    error "preflight live MCAN0 CCCR.MON is not set"
  end
  if $p3b_live_txbrp != 0
    error "preflight live MCAN0 TXBRP is non-zero"
  end
else
  if g_app_mcan0_bus_off_test_result.state != 3
    error "terminal result is not BUS_OFF_LATCHED"
  end
  if g_app_mcan0_bus_off_test_result.once_per_boot_consumed != 1
    error "terminal once-per-boot state was not consumed"
  end
  if g_app_mcan0_bus_off_test_result.last_submit_status != 0
    error "terminal TX submit status is not success"
  end
  if g_app_mcan0_bus_off_test_result.tx_submit_count != 1
    error "terminal result did not submit exactly one TX request"
  end
  if g_app_mcan0_bus_off_test_result.warning_observed != 1
    error "error-warning progression was not observed"
  end
  if g_app_mcan0_bus_off_test_result.error_passive_observed != 1
    error "error-passive progression was not observed"
  end
  if g_app_mcan0_bus_off_test_result.bus_off_observed != 1
    error "bus-off was not observed"
  end
  if (g_app_mcan0_bus_off_test_result.final_protocol_status & 0x80) == 0
    error "terminal PSR.BO is not set"
  end
  if g_app_mcan0_bus_off_test_result.cancel_timeout_observed != 0
    error "TX cancellation timed out"
  end
  if g_app_mcan0_bus_off_test_result.automatic_recovery_attempts != 0
    error "automatic recovery attempts are non-zero"
  end
  if g_app_mcan0_bus_off_test_result.post_cleanup_init != 1
    error "terminal controller is not held in INIT"
  end
  if g_app_mcan0_bus_off_test_result.post_cleanup_tx_pending != 0
    error "terminal result reports pending TX"
  end
  if g_app_mcan0_bus_off_test_result.post_cleanup_pads_disconnected != 1
    error "terminal MCAN0 pads are not disconnected"
  end
  if g_app_mcan0_owner_state.tx_armed != 0
    error "terminal MCAN0 TX is armed"
  end
  if ($p3b_live_cccr & 0x1) == 0
    error "live terminal MCAN0 CCCR.INIT is not set"
  end
  if $p3b_live_txbrp != 0
    error "live terminal MCAN0 TXBRP is non-zero"
  end
end

p g_app_mcan0_bus_off_test_mailbox
p g_app_mcan0_bus_off_test_result
p g_app_mcan0_owner_state
p/x g_app_mcan0_bus_off_test_result.run_nonce
p/x g_app_mcan0_bus_off_test_result.last_submit_status
p/x g_app_mcan0_bus_off_test_result.tx_submit_count
p/x g_app_mcan0_bus_off_test_result.max_tec
p/x g_app_mcan0_bus_off_test_result.warning_observed
p/x g_app_mcan0_bus_off_test_result.error_passive_observed
p/x g_app_mcan0_bus_off_test_result.bus_off_observed
p/x g_app_mcan0_bus_off_test_result.final_protocol_status
p/x g_app_mcan0_bus_off_test_result.final_error_count
p/x g_app_mcan0_bus_off_test_result.final_control_status
p/x g_app_mcan0_bus_off_test_result.final_interrupt_flags
p/x g_app_mcan0_bus_off_test_result.final_tx_request_pending
p/x g_app_mcan0_bus_off_test_result.post_cleanup_init
p/x g_app_mcan0_bus_off_test_result.post_cleanup_monitor
p/x g_app_mcan0_bus_off_test_result.post_cleanup_tx_pending
p/x g_app_mcan0_bus_off_test_result.post_cleanup_pads_disconnected
p/x g_app_mcan0_bus_off_test_result.cancel_timeout_observed
p/x g_app_mcan0_bus_off_test_result.automatic_recovery_attempts

detach
quit
