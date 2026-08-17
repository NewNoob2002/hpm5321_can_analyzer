# P3B deferral 后续系统工作计划

## 1. 计划身份与治理边界

- 计划日期：2026-08-17
- 规划基线：`af7796dd2c6fac5b13c49741e7b92b66cf8a2d47`
- 权威状态：`docs/evidence/phase3/P3B-current-status.json`
- 上位执行边界：`docs/development/system-functional-completion-plan.md`
- 批准产品路线：`docs/approved-plan/prd-hpm5321-usb-can-analyzer.md`
- 批准测试合同：`docs/approved-plan/test-spec-hpm5321-usb-can-analyzer.md`

本计划把已授权的非 bus-off 系统开发拆成可审查、可独立合并的工作包。
它不改变资格状态，不授权硬件操作，也不替代任何测试证据。

```text
planning_contract=POST_P3B_DEFERRAL_SYSTEM_WORK
P3B=PARTIAL
P4E=BLOCKED
freeze_ready=false
hardware_bus_off=NOT_COMPLETED
hardware_execution_authorized=false
bus_off_gate=DEFERRED_EXTERNAL_FAULT_INJECTION_CAPABILITY
development_continuation=AUTHORIZED_WITH_DEFERRED_HARDWARE_GATE
single_channel_before_dual_channel=true
```

允许继续的是非 bus-off 固件、USB/协议集成、host core/CLI、单通道 E2E
实现、双通道实现以及非 bus-off 可靠性工作。任何工作包完成都不能单独用于声明
P3B、P4E、P5、MVP、Beta、freeze 或 release 资格完成。

## 2. 执行原则与依赖

执行顺序遵循“先垂直闭环，再横向铺开”：

```text
WP0 gap ledger
  -> WP1 P4P protocol and host codec closure
  -> WP2 single-channel non-bus-off vertical slice
       -> WP3 non-bus-off fault and reliability hardening
       -> WP4 Linux/Windows CLI productization
       -> WP5 dual-channel readiness and implementation

Deferred lane: active bus-off HIL capability gate
```

WP3 与 WP4 可在 WP2 的接口、错误语义和证据格式稳定后并行。WP5 必须晚于
WP2，并且只有在与双通道相关的 WP3 安全控制已经明确后才能启用主动 TX。
这只是实现排序；批准路线中的资格 DAG
`P0H -> P1 -> P2 -> (P3A || P3B || P4P) -> P4E -> (P5 || P6)`
保持不变。P3B bus-off 未关闭时，P4E 及其下游聚合资格门仍然阻断。

所有工作包共同遵守：

1. 先引用批准需求、测试 ID 和当前证据，再修改实现。
2. 软件测试、模拟器结果和负向对照不能替代真实硬件证据。
3. 产品修改不得与 bus-off 治理、历史证据或资格升级混入同一提交。
4. 任何会改变目标板、总线、探针或外部设备状态的动作，必须另行完成安全
   preflight 并获得当次明确授权；本计划本身不构成授权。
5. 发现 required P0/P1 失败时，停止进入依赖它的后续工作包，保留首次失败
   证据，不以重试覆盖。
6. 只使用明确文件列表暂存；每个提交和 PR 都必须能说明需求、实现、测试和
   未关闭风险。

## 3. WP0 — 批准计划与当前证据缺口台账

### 目标

建立唯一的执行台账，避免从过期状态文档或“看起来已实现”的代码推导资格。
这是后续产品修改的入口门。

### 输入与依赖

- 批准 PRD、测试规范、planning contract 和 Linux/Windows CLI addendum；
- `docs/implementation-status.md`；
- P2、P3A、P3B、P4P、host 与 CI 的现有证据；
- 当前 P3B deferral/current-status 权威记录。

### 允许范围

- 为每个相关 test ID 记录 `PASS`、`PARTIAL`、`BLOCKED` 或 `NOT_TESTED`；
- 记录 requirement、owner role、实现位置、证据路径、证据 source identity、
  下一动作和阻断原因；
- 明确区分“已实现”“软件验证”“硬件证据”和“资格关闭”。

### 重点盘点

- Gate E：`T-PROTO-001..012`；
- Gate F：`T-E2E-001..004`、`T-E2E-006..009`；
- Gate H：`T-FW-004..010`、`T-FW-012..013`，并单列 Beta-only 项；
- Gate I：`T-HOST-001..005`，保持 macOS 条目 deferred；
- P2/P3A 中仍会阻塞上述路径的部分证据。

### 输出与验收

- 输出一份受版本控制的 gap ledger；
- 每一项都能追溯到批准测试 ID，且没有无 owner、无证据或无下一动作的行；
- 已有 `PASS` 不因重新整理而丢失，`PARTIAL/BLOCKED` 不被文本性升级；
- 对同一项存在冲突状态时，以更保守状态记录并停止相应下游工作。

### 提交与 PR 边界

仅包含台账、台账校验器和对应测试；不包含产品代码。推荐原子提交：

`docs(planning): inventory authorized post-deferral gaps`

## 4. WP1 — P4P 协议与 host codec 关闭

### 目标

在进入产品 E2E 前关闭协议语义、C/Rust codec、device session、fake transport
和 host core 的实际缺口。若 WP0 证明某项已经具备合格证据，则复用证据，不重复
实现。

### 输入与依赖

- WP0 gap ledger 已审核；
- `docs/approved-plan/usb-can-protocol-v1.md`；
- 固件 C codec、Rust codec/core、fake device 和 golden vectors。

### 允许范围

- framing、HELLO、capability、session、request correlation、timeout/cancel；
- configuration/capture/diagnostics、event/batch/channel sequence 与 DATA_LOSS；
- authorized-TX 的纯软件状态机、arm epoch/CAS、结果与取消语义；
- Bulk IN response reserve、调度优先级、反饥饿、兼容性与 fuzz/property corpus。

### 明确排除

- 不启用未经安全策略保护的产品 TX；
- 不执行真实 CAN、USB、探针或 bus-off 操作；
- 不扩展 STORAGE、UPDATE、GUI、周期 TX 或 v1.1 协议范围。

### 测试与证据

- 主验收：`T-PROTO-001..012`；
- C/Rust golden vector 必须 100% 一致；
- malformed/unknown input 必须产生稳定错误或可计数丢弃，会话继续；
- 输出测试报告、命令、工具链版本、source SHA 和任何剩余差距。

### 验收与停止条件

- WP0 标为当前适用的 Gate E 项全部具有可复现的软件 PASS；
- protocol spec、C codec、Rust codec 和 fake transport 不得出现未解释差异；
- 若必须修改规范或 wire ABI，停止 WP1，先走独立设计/兼容性评审。

### 提交与 PR 边界

协议合同/测试、实现、证据分别使用可审查的原子提交。不得混入硬件证据或
bus-off 治理修改。

## 5. WP2 — 单通道非 bus-off E2E 与 CLI 垂直闭环

### 目标

完成一路 `MCAN0 -> timestamp/ring -> USB batch -> protocol -> host core -> CLI`
的产品路径，并完成安全授权 TX 的实现闭环，但不声称 bus-off 或 P4E 聚合关闭。

### 输入与依赖

- WP1 软件验收通过；
- 当前 P3A/P3B 单通道基线；
- frozen `BP-CAN-MVP-v1` 与 `BP-LATENCY-v1`；
- 已审核的 TX allowlist、rate/bus-load、arm/expiry 和 fail-closed 策略。

### 允许范围

- enumerate/HELLO/capability、配置、capture、诊断和 CLI 展示；
- MCAN0 authorized TX、`TX_RESULT`、cancel、timeout、arm expiry 和 session reset；
- sequence/drop/counter reconciliation、backpressure 和 machine-readable CLI 输出；
- Linux 上的产品垂直切片；Windows 行为由 WP4 完成产品化。

### 明确排除

- active bus-off 注入与 `T-E2E-009` 的组合故障关闭；
- MCAN2、双通道聚合性能、STORAGE、UPDATE、GUI 和 macOS；
- 用错误波特率、错误终端/接线、silent/no-ACK 或 GDB 写状态替代 bus-off。

### 测试与证据

- `T-E2E-001` enumerate -> hello -> capability；
- `T-E2E-002` configure CAN -> capture；
- `T-E2E-003` authorized TX -> TX_RESULT -> external receive；
- `T-E2E-004` frozen latency profile；
- `T-E2E-006` host backpressure/drop；
- `T-E2E-007` USB disconnect during CAN load；
- `T-E2E-008` CLI machine-readable output/exit code。

软件、fake/recorded backend 和离线测试可以先关闭实现风险。真实外设测试必须在
独立安全 preflight、明确硬件授权和绑定 source/artifact identity 后执行。

### 验收与停止条件

- 普通单通道流程在软件层面可复现，错误路径 fail closed；
- 所有队列、重试、timeout 和 disconnect 均有界并可诊断；
- 硬件证据必须绑定 frozen profile、reference host、firmware/host SHA；
- `T-E2E-009` 保持 `BLOCKED` 或 `PARTIAL`，不得由拆分子场景推导为 PASS；
- 任一安全策略绕过、silent loss、unbounded growth 或 required P0 失败立即停止。

### 提交与 PR 边界

优先按“合同测试 -> 固件/host 实现 -> 非硬件证据”分提交。真实 HIL 证据另行
提交，不修改产品实现；bus-off 证据始终使用独立受控变更。

## 6. WP3 — 非 bus-off 故障与可靠性加固

### 目标

在不运行 active bus-off 的前提下，证明资源耗尽、命令洪泛、disconnect、
watchdog/config 故障和并发竞态都进入有界、可诊断、安全状态。

### 输入与依赖

- WP2 接口、错误码、计数器和 cleanup 语义稳定；
- WP0 对 P2/P3A/Gate H 的差距分类完成。

### 测试与证据

- `T-FW-004` command flood/rate limit；
- `T-FW-005` queue/pool exhaustion；
- `T-FW-006` watchdog recovery；
- `T-FW-007` configuration corruption/factory reset；
- `T-FW-008` map/RAM/stack budget，作为高风险变更持续门；
- `T-FW-009` static analysis and warning gate；
- `T-FW-010` cancel/TX-complete race，每个 tag 恰一 final result；
- `T-FW-012` power/config CRC failure 回到安全态；
- `T-FW-013` cleanup 证明 listen-only、TX queue/schedule 为零。

### 验收与停止条件

- 0 unexplained reset、deadlock、heap corruption 或 silent loss；
- 资源耗尽具有稳定错误、计数器和恢复/containment 行为；
- Release 构建与 Debug ABI/内存预算均在已批准门限内；
- 任何需要 bus-off 才能证明的组合项保持未关闭；
- 发现 Debug ILM 预算回归、ABI 漂移或清理后 TX 仍可能活动时立即停止。

### 提交与 PR 边界

每类故障优先使用独立小 PR；公共可靠性重构必须先有失败测试。硬件 watchdog、
断电或外设动作需要独立授权，不由本计划自动执行。

## 7. WP4 — Linux/Windows CLI 产品化

### 目标

在单一 Rust host core 上完成 Linux/Windows CLI 的确定性打包、会话恢复、诊断
和操作员可见错误；不引入第二套协议/USB core。

### 输入与依赖

- WP2 的 CLI/API 和 session semantics 稳定；
- Phase 1B 选定的 Rust host stack；
- Linux/Windows scope addendum。

### 测试与证据

- `T-HOST-001` Windows unit/integration/package；
- `T-HOST-002` Linux unit/integration/package；
- `T-HOST-004` hotplug/session recovery；
- `T-E2E-008` machine-readable output and exit codes；
- `T-HOST-005` 72 h capture memory plateau 作为 Beta 范围证据，不提前声明完成。

### 验收与停止条件

- Linux/Windows 使用同一协议测试套件和稳定退出码；
- package/install/uninstall、依赖/license、诊断 bundle 和 provenance 可追溯；
- hotplug 后旧 session/arm/config identity 不被复用；
- host RSS、队列和文件输出不存在未解释线性增长；
- macOS 保持 deferred，Qt/GUI 不进入当前依赖图。

### 提交与 PR 边界

共享 core、CLI 行为、平台 packaging 和平台证据按可独立审查的提交拆分。平台
证据不得反向改写 P4E/P6/MVP 资格状态。

## 8. WP5 — 双通道准备与实现

### 目标

在单通道闭环稳定后实现 MCAN0 + MCAN2 的独立配置、attribution、isolation、
fairness、诊断和非 bus-off 可靠性。该工作用于降低 P5 风险，不构成 P5/Beta
资格关闭。

### 输入与依赖

- WP2 已通过单通道软件验收；
- 相关 WP3 安全/资源控制已具备；
- P0C hardware contract 与 MCAN2 advisory/证据已在 WP0 登记。

### 允许范围

- MCAN2 owner、channel mapping、filter、统计、LED event 和协议 attribution；
- per-channel queue/rate/bus-load、fair scheduling 和 disconnect containment；
- 双通道 fake/target-unit/静态验证以及明确授权后的非 bus-off HIL。

### 测试与证据

- `T-CAN-002`、`T-CAN-005`、`T-CAN-009`；
- `T-E2E-005` frozen aggregate profile；
- `T-FW-001`、`T-FW-002`、`T-FW-008`、`T-FW-011`；
- `T-LED-004`、`T-LED-005`；
- `T-FW-003` 100 bus-off injections/channel 始终留在 deferred lane。

### 验收与停止条件

- 通道 ownership、sequence、drop 和 TX result 不交叉归属；
- 单通道已通过的性能与安全行为不发生未解释回归；
- 双通道资源耗尽可计数、可诊断、可 containment；
- 缺少 bus-off、72 h soak 或完整 Beta 证据时不得声明 P5/Beta 完成；
- 任一通道能绕过授权策略或使另一通道 control response 饥饿时立即停止。

### 提交与 PR 边界

先提交 channel-neutral contracts/refactor，再提交 MCAN2 实现，最后提交非
bus-off 证据。不得把大规模单通道重构与 MCAN2 启用放入同一不可分审查单元。

## 9. Deferred lane — active bus-off HIL

本车道只监控恢复条件，不执行硬件：

- 保留 debug-only hook、procedure、schema、validator 和历史记录；
- 不修改历史 blocker SHA 或 authority；
- 不执行 GDB 状态写入、错误波特率、错误终端/接线或 silent/no-ACK 替代；
- 不运行 bus-off 注入，不把 negative control 重分类为 PASS；
- 不 freeze、不 tag、不升级 P3B/P4E/MVP/Beta/release 状态。

只有 qualified active CAN fault injector 或独立合格等效设备可用，并完成设备
身份、电气限值、急停条件、bit timing/终端/地线/idle voltage preflight、三个独立
run ID/nonce/evidence path/reset boundary、raw transcript/capture 能力确认以及新的
明确硬件授权后，才能提出恢复本车道。恢复是新的受控工作，不是本计划的自动步骤。

## 10. 每个工作包的通用验证闭环

按实际变更范围选择最低充分验证，并在 PR 中记录准确命令和结果：

1. 相关 contract/unit/integration tests；
2. 严格 Python 全套，零 skip；
3. 产品代码变更时运行 `scripts/ci/verify_p0_software_closure.sh`；
4. 固件变更时运行适用的 Release/Debug 构建、Release 隔离、Debug ABI 和内存预算；
5. host/protocol 变更时运行 Cargo check、release tests 和 golden-vector parity；
6. `git diff --check`、禁止资产检查和明确文件范围审查；
7. 进入硬件证据前，在独立 clean checkout 绑定 source/artifact identity 并重新
   通过软件闭环。

测试数量不是固定资格条件；以当次发现的非零总数、全部通过、零 skip 和完整命令
记录为准。硬件不可用时，相关 required 项保持 blocked，不能由 mock 结果替代。

## 11. 当前规划分支的完成定义

本规划分支只需完成：

- 本文档与批准路线、当前状态、deferral authority 一致；
- 计划合同测试能够阻止状态升级、bus-off 替代和双通道抢跑；
- targeted tests、严格 Python 测试和 `git diff --check` 通过；
- 工作树只包含规划文档、规划校验器、测试和专用 CI 工作流；
- 经人工审核后再决定是否提交、push 或创建 PR。

规划合并后，推荐从最新 `origin/main` 创建 WP0 分支，先形成 gap ledger；在 WP0
审核完成前，不直接选择一个假定缺口进入大规模产品实现。
