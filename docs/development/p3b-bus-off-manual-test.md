# P3B bus-off 手工 HIL 测试

## 当前结论

- 本文仅定义人工执行步骤；截至 2026-08-15，真实 HIL **未执行**。
- readiness 为 `READY_FOR_MANUAL_HIL`，不是测试通过结论。
- P3B 仍为 `PARTIAL`，P4E 仍为 `BLOCKED`。
- 仅允许使用 `hpm5321-ram-debug-bus-off` 的 RAM Debug 构建；不得把该测试钩子带入普通或量产固件。

## 安全边界

1. 只在**隔离台架**执行，禁止连接车辆，也禁止连接任何可能转发到车辆或生产网络的网关。
2. DUT、调试器、可控 CAN 故障注入设备和终端电阻必须由现场操作员逐项确认；测试结束后断电恢复。
3. 故障注入设备必须能主动造成持续发送失败并独立观察总线状态。不能仅依赖 ACK error 判断 bus-off；单次或少量 ACK error 不等于 bus-off。
4. 在写入 arm mailbox 前保持 DUT 停止，确认 run nonce 为本次唯一非零值，并确认测试钩子是 once-per-boot。
5. 若任何接线、终端、供电、调试镜像或隔离条件不明确，停止测试，不得写入 command。

## 离线准备

1. 构建 RAM Debug 专用镜像：
   `./scripts/build.sh hpm5321-ram-debug-bus-off`
2. 保存构建 manifest、ELF SHA-256、当前源码 commit 与 dirty 状态。
3. 不执行 flash/program 命令；仅由现场操作员按既有 RAM 调试流程装载专用镜像。
4. 将 GDB 当前加载 ELF 的 SHA-256 与第 2 步记录逐字比对，禁止仅凭文件名判断镜像身份。
5. 启动后先运行 snapshot，确认：
   - mailbox/result magic、version、size 正确；
   - `state == LISTEN_ONLY_LOCKED`；
   - `once_per_boot_consumed == 0`；
   - owner 为 listen-only 且 `tx_armed == 0`；
   - `automatic_recovery_attempts == 0`。
   snapshot 会直接读取 MCAN0 `CCCR.MON` 与 `TXBRP`，任一 fail-closed
   断言失败都会由 GDB `error` 中止。

## 人工 HIL 步骤

1. 在隔离台架上连接 DUT 与专用故障注入设备；再次确认禁止连接车辆。
2. 让故障注入设备进入预备状态，但尚不制造故障。
3. 用 GDB 连接 RAM Debug 镜像并停止 CPU。
4. 为本次执行选择唯一非零 run nonce，在 GDB 中先执行
   `set $p3b_run_nonce = 0x...`；不得把固定 nonce 写回脚本。
5. 执行 arm 脚本。脚本会对 hook ABI、listen-only、TX disarmed、
   owner initialized/online、`automatic_recovery_attempts == 0`、实时
   `CCCR.MON == 1`、实时 `TXBRP == 0`、mailbox reserved、once-per-boot
   和 nonce 做 fail-closed 检查；任一检查失败必须由 GDB `error`
   中止。脚本必须先写 magic/version/size、nonce、unlock token 和
   arm token，**command 最后写入**。
6. 恢复 CPU 后，由专用设备制造可重复的发送失败条件；不得使用普通车辆网络作为故障源。
7. 在两秒有界窗口内等待钩子结束，然后停止 CPU；先设置
   `set $p3b_expected_run_nonce = $p3b_run_nonce`，再运行 snapshot 脚本。
   snapshot 会断言 ABI、`BUS_OFF_LATCHED`、PSR.BO、唯一 TX、无恢复、
   INIT、pads 隔离及实时 `TXBRP == 0`，不是仅打印字段。
8. 若首次结果为 `BUS_OFF_LATCHED`，记录原始 `run_nonce`、
   `rejected_command_count` 和 `tx_submit_count`，设置另一个唯一非零
   `$p3b_retrigger_nonce`，执行 retrigger 脚本并恢复 CPU 至少 100 ms。
   再次停止 CPU，在同一 GDB 会话中执行
   `scripts/phase3/p3b_bus_off_retrigger_verify.gdb`；该脚本验证拒绝计数
   恰好加一、原 run nonce/state/`tx_submit_count == 1` 不变、mailbox
   command 已清零且实时 `TXBRP == 0`。该步骤只验证固件拒绝第二次
   请求，不得重新连接 MCAN0 pads，也不得再次提交 TX。
9. 保存完整 GDB 输出、构建 manifest、ELF SHA-256、接线照片/台架标识和操作员签名；不得手工改写结果字段。

## PASS 判据

真实 HIL 只能在以下条件全部有原始证据时判为 PASS：

- `bus_off_observed == 1`，且最终协议状态的 **PSR.BO** 位为 1；
- `state == BUS_OFF_LATCHED`，`once_per_boot_consumed == 1`；
- `last_submit_status == status_success` 且 `tx_submit_count == 1`；
- `warning_observed == 1`、`error_passive_observed == 1`、
  `max_tec >= 128`；MCAN ECR.TEC
  是 8 位字段，最大值为 255，绝不能把 256 作为 TEC 阈值；
- 不能仅依赖 ACK error；warning/error-passive、PSR.BO 和最终锁存状态
  必须形成连续的原始证据链；
- `automatic_recovery_attempts == 0`；
- `cancel_timeout_observed == 0`；
- `post_cleanup_init == 1`、`post_cleanup_tx_pending == 0`、
  `post_cleanup_pads_disconnected == 1`，且没有自动恢复或第二次触发；
- bus-off 收敛后 MCAN0 TX/RX pads 保持 GPIO input 物理隔离，不能仅以软件
  `OFFLINE` 状态代替总线隔离；
- run nonce 与 arm/snapshot/操作员记录完全一致。
- retrigger 后 `rejected_command_count` 恰好增加 1，原始 `run_nonce`、
  `state` 和 `tx_submit_count == 1` 保持不变，证明 once-per-boot 拒绝路径
  未产生第二次 TX。

任一条件缺失、超时、结果结构不完整或原始日志缺失均不得声明 PASS。即使该手工 HIL 后续通过，P3B 状态升级也必须由独立资格审查完成；本 readiness 证据本身只允许 P3B 仍为 `PARTIAL`。
