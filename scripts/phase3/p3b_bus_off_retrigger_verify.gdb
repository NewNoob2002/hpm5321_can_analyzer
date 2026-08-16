set pagination off
set confirm off

# Pinned GNU GDB 13.2 has no built-in `error` command. Keep every guard
# fail-closed with a non-zero process exit status.
define error
  echo ERROR: $arg0\n
  quit 1
end

monitor halt

printf "P3B_BUS_OFF_RETRIGGER_VERIFY\n"
if $_isvoid($p3b_original_run_nonce)
  error "$p3b_original_run_nonce is missing; source retrigger in this GDB session first"
end
if $_isvoid($p3b_rejected_before)
  error "$p3b_rejected_before is missing; source retrigger in this GDB session first"
end
if g_app_mcan0_bus_off_test_result.magic != 0x424f4652
  error "wrong image/hook ABI: result magic mismatch"
end
if g_app_mcan0_bus_off_test_result.version != 2
  error "wrong image/hook ABI: result version mismatch"
end
if g_app_mcan0_bus_off_test_result.size != sizeof(g_app_mcan0_bus_off_test_result)
  error "wrong image/hook ABI: result size mismatch"
end
if g_app_mcan0_bus_off_test_result.rejected_command_count != $p3b_rejected_before + 1
  error "retrigger rejection count did not increase by exactly one"
end
if g_app_mcan0_bus_off_test_result.run_nonce != $p3b_original_run_nonce
  error "retrigger changed the original run nonce"
end
if g_app_mcan0_bus_off_test_result.state != 3
  error "retrigger changed BUS_OFF_LATCHED state"
end
if g_app_mcan0_bus_off_test_result.tx_submit_count != 1
  error "retrigger caused an additional TX submission"
end
if g_app_mcan0_owner_state.tx_armed != 0
  error "retrigger armed MCAN0 TX"
end
if g_app_mcan0_bus_off_test_mailbox.command != 0
  error "retrigger mailbox command was not consumed"
end
if *(unsigned int *)0xF02800CC != 0
  error "live MCAN0 TXBRP is non-zero after retrigger rejection"
end

p g_app_mcan0_bus_off_test_result
p g_app_mcan0_owner_state
p/x g_app_mcan0_bus_off_test_result.rejected_command_count
p/x g_app_mcan0_bus_off_test_result.run_nonce
p/x g_app_mcan0_bus_off_test_result.tx_submit_count

detach
quit
