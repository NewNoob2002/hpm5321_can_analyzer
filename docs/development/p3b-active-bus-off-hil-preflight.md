# P3B 主动 bus-off HIL preflight

## 范围和当前门禁

本文只冻结主动 bus-off HIL 的输入、台架安全条件和三次独立运行边界，
不授权刷写、复位、调试器连接、CAN 发送、错误注入或任何真实硬件执行。

- 空白模板：
  `docs/evidence/phase3/P3B-active-bus-off-hil-preflight.template.json`
- 2026-08-17 当前现场记录：
  `docs/evidence/phase3/P3B-active-bus-off-hil-preflight-2026-08-17.json`
- 当前决策必须保持 `BLOCKED_FOR_HIL_PREFLIGHT`，直到当前记录中的所有真实现场值、
  设备限制和双人批准均已补齐并通过 validator。
- 即使预检随后变为 `READY_FOR_HIL_PREFLIGHT_APPROVAL`，真实 HIL 仍需另一次
  明确授权。
- 本预检不得改变 `P3B=PARTIAL`、`P4E=BLOCKED`、`freeze_ready=false`
  或 hardware bus-off 未完成状态。

## 冻结的软件输入

主动 bus-off HIL 的默认候选是 `hpm5321-ram-debug-bus-off`，不是 Release
产物。RAM 调试流程应以 ELF 为规范加载输入；只有在加载工具、目标地址和 RAM
装载语义经现场方案明确批准时，BIN 才可作为等价输入。

| 项目 | 冻结值 |
| --- | --- |
| source commit | `a4e310f79c40d1324a642c76d46403b927aa2a07` |
| source dirty | `false` |
| HPM SDK commit | `88b01b43900d8c30844a1e5cdd3f3b7aff6db40e` |
| compiler | `riscv32-unknown-elf-gcc (gc891d8dc23e) 13.2.0` |
| preset | `hpm5321-ram-debug-bus-off` |
| build options | Debug, RAM, bus-off hook ON, generic fault reason 0, CAN 1 Mbit/s |
| ELF SHA-256 | `880993181c64c5ede0dfd2d79a1a6d67f8257affae11f297cb6ecbf1a6ed64be` |
| BIN SHA-256 | `36c9d9b8ae4e2ed1f8430a66d5f61580e15d86887d48704d2fad1223ffe02b87` |
| map SHA-256 | `d5ffa8d400634ae36741ad31d9e58dd22f324904ca99ff332cbb85bec4a36bea` |
| manifest SHA-256 | `04fa7b72af3d465055b31a9e4a2647614b508ccad1c68f21f6f7c7a6000277ba` |

任何现场待加载文件与上述哈希不一致，或 manifest 不能证明
`source_dirty=false`，均立即 NO-GO。三次运行之间不得改变源码、preset、构建
选项、SDK、toolchain 或固件哈希。

## 现场 safety preflight

执行前必须由现场人员填写模板中的全部字段，不得从历史日志推断当前设备或接线。
至少确认：

1. 台架完全隔离，未连接车辆或生产网关，并有明确的紧急断电/停止方式。
2. DUT、debug probe、CAN analyzer、主动错误注入器均记录型号、序列号和版本。
3. 主动错误注入器能力覆盖已选错误类型；工作限制、电气限制、持续时间限制和
   紧急停止条件来自设备手册或实验室负责人批准。
4. bitrate、sample point、Classic CAN/CAN-FD 模式、终端电阻、公共地、供电和
   idle voltage 均为本次台架实测或批准值。
5. 操作者与独立审核人分别具名、分别批准且不是同一人。
6. post-latch 连续观察时长由项目/安全责任人明确批准；本文不预设秒数。
7. GDB transcript 和分析仪原始记录均可在每次运行中独立保存。

缺少任一项时，`approved` 必须为 `false`，决策必须为
`BLOCKED_FOR_HIL_PREFLIGHT`。

## 主动错误注入边界

- 选定注入类型必须来自设备实际支持列表。不得把“silent analyzer/no ACK”当作
  已具备主动 bit/form/stuff/CRC/ACK 注入能力。
- 注入强度、持续时间、电压、电流、占空比、重试次数和设备温度等限制不得猜测；
  缺少手册或人工批准时保持 `null` 并阻断。
- 注入只允许在一次 mailbox arm 和一次 TX 提交的有界实验窗口内发生。
- 观察到接线/电源异常、设备越限、台架失去隔离、日志丢失、固件身份变化或
  实际方案与记录冲突时立即停止。
- 固件路径具备 warning → error-passive → bus-off、锁存、无自动恢复、INIT、
  TXBRP=0、pads 隔离、timeout cleanup、listen-only fallback 和第二次触发拒绝
  的检查点；这些是待验证路径，不是已完成的硬件结论。

## GDB 与 ACK-only 替代方案边界

- GDB 写 mailbox 只负责启动现有 once-per-boot 测试钩子；它不是 CAN 错误
  注入器，仍需真实总线错误使 MCAN 的 ECR/PSR 发生硬件状态变化。
- 禁止通过 GDB 改写 `g_app_mcan0_bus_off_test_result`、owner state、内部 latch、
  `PSR` 或 `ECR` 来满足硬件 PASS。此类写入会绕过真实错误计数和协议状态，
  不能证明 warning → error-passive → bus-off。
- 若后续需要验证 latch、INIT、pad 隔离或无恢复的软件 containment 路径，可以
  另立明确标记的 synthetic/software-only 测试；它必须使用独立证据和判据，
  不得复用真实 HIL PASS、不得升级 P3B hardware bus-off 状态。
- JCAN 的 silent/no-ACK 或仅移除 ACK 不能视为主动 bit/form/stuff/CRC 错误注入。
  ACK-only 场景不能可靠证明 TEC 持续增长到 bus-off，因此本 preflight 明确拒绝
  将其作为硬件 PASS 替代方案。
- 若没有合格的外部注入器，可接受的规划方向仅包括借用/采购专用设备，或另行
  设计并资格确认一个能在物理总线上精确定时制造错误的独立节点。任何新方案都
  必须先补齐设备身份、电气限制、停止条件和独立审核，再获得硬件执行授权。

## 三次独立运行

模板固定三个 run 记录。每次运行都必须是不可被其他运行覆盖的独立实验：

1. 独立 run ID、非零 nonce、日志目录、GDB transcript、分析仪原始文件、接线
   记录、设备身份记录、开始时间和结束时间。
2. 每次运行前执行经批准的复位或断电重启，并重新确认 once-per-boot 未消费。
3. 三次均使用完全相同的 ELF/BIN/map/manifest SHA；禁止在运行间重新构建或
   修改固件。
4. 每次分别保存并判定 trigger、warning/error-passive/bus-off progression、
   BUS_OFF_LATCHED、PSR.BO、no-recovery、INIT、TXBRP=0、pads isolation、
   cleanup 和 retrigger rejection。
5. 单次失败、超时或原始证据缺失即使另外两次通过也仍是该次失败，不得合并覆盖。

## post-latch 观察

`post_latch_observation_seconds` 必须在执行前由项目/安全责任人给出正整数并由
操作者和独立审核人批准。每次运行从首次确认 `BUS_OFF_LATCHED` 起连续观察完整
时长，至少持续记录：

- `state == BUS_OFF_LATCHED` 和最终 `PSR.BO == 1`；
- `automatic_recovery_attempts == 0`，没有自动恢复；
- controller 保持 INIT，`TXBRP == 0`，TX 未重新 armed；
- MCAN0 pads 保持物理隔离；
- 无第二次 TX 提交，retrigger 只增加一次拒绝计数；
- GDB 原始 transcript、分析仪原始文件及连续时间戳没有缺口。

观察时长未批准、记录中断或任一状态偏离均为 NO-GO/FAIL，不得缩短观察窗口后
重解释为通过。

## GO / NO-GO

仅当模板没有 blocker、validator 通过、`approved=true`、操作者和独立审核人
均批准且角色分离时，预检决策才可为
`READY_FOR_HIL_PREFLIGHT_APPROVAL`。

出现以下任一项立即 NO-GO：main/source SHA 或固件哈希变化；设备身份不明；主动
注入能力/限制不明；台架未隔离；终端、公共地、供电或 idle voltage 未确认；
人员未指定；post-latch 时长未批准；无法保存原始 GDB/分析仪数据；三次运行不能
保持同一固件身份；文档与现场方案冲突。

## 证据打包边界

后续每次运行应独立打包本 run 的 preflight 快照、构建 manifest、哈希记录、GDB
transcript、分析仪原始文件、接线/设备身份记录、时间戳、结果和 cleanup 记录。
本任务不创建执行包、不移动或重打包既有 ZIP，也不更新 freeze/tag 或阶段状态。
