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

printf "P3B_BUS_OFF_RETRIGGER_PRECHECK\n"
p g_app_mcan0_bus_off_test_result
p g_app_mcan0_owner_state

# 仅在首次结果已锁存 BUS_OFF 后执行。调用者必须先设置另一个唯一非零值：
#   set $p3b_retrigger_nonce = 0x...
if $_isvoid($p3b_retrigger_nonce)
  error "set a unique non-zero $p3b_retrigger_nonce before sourcing this script"
end
if $p3b_retrigger_nonce == 0
  error "$p3b_retrigger_nonce must be non-zero"
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
if g_app_mcan0_bus_off_test_result.state != 3
  error "first run is not BUS_OFF_LATCHED"
end
if g_app_mcan0_bus_off_test_result.once_per_boot_consumed != 1
  error "once-per-boot state was not consumed"
end
if g_app_mcan0_bus_off_test_result.tx_submit_count != 1
  error "first run did not submit exactly one TX request"
end
if g_app_mcan0_owner_state.tx_armed != 0
  error "MCAN0 TX is armed after bus-off containment"
end
if g_app_mcan0_bus_off_test_mailbox.command != 0
  error "mailbox command is not clear"
end

set $p3b_original_run_nonce = g_app_mcan0_bus_off_test_result.run_nonce
set $p3b_rejected_before = g_app_mcan0_bus_off_test_result.rejected_command_count
set var g_app_mcan0_bus_off_test_mailbox.magic = 0x424f4649
set var g_app_mcan0_bus_off_test_mailbox.version = 2
set var g_app_mcan0_bus_off_test_mailbox.size = sizeof(g_app_mcan0_bus_off_test_mailbox)
set var g_app_mcan0_bus_off_test_mailbox.run_nonce = $p3b_retrigger_nonce
set var g_app_mcan0_bus_off_test_mailbox.unlock_token = 0x554e4c4b
set var g_app_mcan0_bus_off_test_mailbox.arm_token = 0x41524d21
set var g_app_mcan0_bus_off_test_mailbox.reserved = 0

# command 必须最后写入；本脚本不自动 continue。
set var g_app_mcan0_bus_off_test_mailbox.command = 1
