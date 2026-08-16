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

printf "P3B_BUS_OFF_ARM_PRECHECK\n"
info files
p g_app_mcan0_bus_off_test_result
p g_app_mcan0_owner_state

# 仅在隔离台架人工执行。调用者必须先设置本次唯一非零值：
#   set $p3b_run_nonce = 0x...
if $_isvoid($p3b_run_nonce)
  error "set a unique non-zero $p3b_run_nonce before sourcing this script"
end
if $p3b_run_nonce == 0
  error "$p3b_run_nonce must be non-zero"
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
if g_app_mcan0_bus_off_test_result.state != 1
  error "hook is not LISTEN_ONLY_LOCKED"
end
if g_app_mcan0_bus_off_test_result.once_per_boot_consumed != 0
  error "once-per-boot hook was already consumed"
end
if g_app_mcan0_owner_state.magic != 0x4d43414e
  error "wrong image: MCAN owner magic mismatch"
end
if g_app_mcan0_owner_state.initialized != 1
  error "MCAN0 owner is not initialized"
end
if g_app_mcan0_owner_state.online != 1
  error "MCAN0 owner is not online"
end
if g_app_mcan0_owner_state.mode != 1
  error "MCAN0 owner is not listen-only"
end
if g_app_mcan0_owner_state.tx_armed != 0
  error "MCAN0 TX is already armed"
end
if g_app_mcan0_owner_state.automatic_recovery_attempts != 0
  error "automatic recovery attempts are non-zero"
end
set $p3b_live_cccr = *(unsigned int *)0xF0280018
if ($p3b_live_cccr & 0x20) == 0
  error "live MCAN0 CCCR.MON is not set"
end
set $p3b_live_txbrp = *(unsigned int *)0xF02800CC
if $p3b_live_txbrp != 0
  error "live MCAN0 TXBRP is non-zero"
end
if g_app_mcan0_bus_off_test_mailbox.command != 0
  error "mailbox command is not clear"
end
if g_app_mcan0_bus_off_test_mailbox.reserved != 0
  error "mailbox reserved field is not zero"
end

set var g_app_mcan0_bus_off_test_mailbox.magic = 0x424f4649
set var g_app_mcan0_bus_off_test_mailbox.version = 2
set var g_app_mcan0_bus_off_test_mailbox.size = sizeof(g_app_mcan0_bus_off_test_mailbox)
set var g_app_mcan0_bus_off_test_mailbox.run_nonce = $p3b_run_nonce
set var g_app_mcan0_bus_off_test_mailbox.unlock_token = 0x554e4c4b
set var g_app_mcan0_bus_off_test_mailbox.arm_token = 0x41524d21
set var g_app_mcan0_bus_off_test_mailbox.reserved = 0

# command 必须最后写入；本脚本不自动 continue。
set var g_app_mcan0_bus_off_test_mailbox.command = 1
