# HPM5321 USB-CAN 多平台分析仪实施计划

> 状态：用户产品分级 Review 已吸收；Architect → Critic 顺序复核已批准  
> 上下文：`planning context (not a normative versioned artifact)`  
> 测试规格：`docs/approved-plan/test-spec-hpm5321-usb-can-analyzer.md`  
> 协议规格：`docs/approved-plan/usb-can-protocol-v1.md`
> SPI2 SD/LED addendum：`spi2-sd-led-2026-08-09`

## 1. 产品目标

以 HPM5321xCFx 和现有 `hpm5321_custom` 板级包为基础，构建一个双通道、
可观测、可恢复、可自动化测试的 USB-CAN/CAN-FD 调试分析仪：

- 固件运行于 FreeRTOS，USB、CAN、SPI/SD、UART 边界清晰；
- USB 数据面能持续承载 CAN 流量，不因 GUI 卡顿阻塞 CAN ISR；
- 协议支持版本协商、能力发现、异步事件、批量帧、流控、错误码和升级兼容；
- CLI 先于 GUI 交付，以便自动化、HIL 和协议稳定；
- 上位机支持 Windows、Linux、macOS，共享同一协议核心和测试向量；
- 每个里程碑都有可重现命令、原始日志和明确通过/失败判据。

## 2. 范围

### 2.1 本期包含

1. VSCode 阅读、构建、烧录、GDB 调试环境；
2. 裸机板级验证和 FreeRTOS 最小验证；
3. USB device、MCAN0/MCAN2、SPI2/SD、UART0 调试控制台；
4. USB HS composite：vendor bulk 主数据面、可选 CDC ACM、可选 DFU Runtime；
5. 固件任务、缓冲、诊断、配置、升级和故障恢复框架；
6. 跨平台 CLI、核心库和 GUI；
7. 主机测试、目标测试、USB/CAN HIL、性能和长稳；
8. 文档、打包、版本和发布证据。

### 2.2 默认不包含

- 在固件中解析 DBC；DBC 解码放在上位机；
- 将 SPI/UART 当作与 USB-CAN 同等优先级的分析协议；
- 首个 MVP 就支持插件市场、云服务或远程协作；
- 未确认硬件前承诺 CAN-FD 最大数据相位速率；
- 未完成 bootloader/回滚验证前对外宣称在线升级可用。

## 3. 当前基线与关键判断

- 当前工程为 `hpm5321_can_analyzer`，`CMakeLists.txt` 编译
  `USER/src/main.c`，已启用 FreeRTOS、SEGGER RTT、Debug-only `DEBUG` 和
  easylogger。Phase 1 已在 official SDK v1.12.1 commit `12bd9249...` 上从空
  build directory 完成三个 preset 的 `T-DEV-001/002/003/004` 日志、manifest
  和 checksum；历史硬件 artifact 仍只绑定其各自记录的 fork revision。
- 自定义板包已覆盖 UART0、USB0、MCAN0、MCAN2、SPI2 和 LED/SD detect，
  可按垂直切片验证；证据见上下文快照。
- 本地 SDK 1.12.1 已提供 FreeRTOS、CherryUSB CDC/WinUSB、MCAN 全套示例和
  SPI SD/FATFS，实施时应优先抽取这些已验证模式，避免另起 USB/CAN 栈。
- 板级 CAN 时钟依赖 PLL1 分频，但当前板级时钟初始化需实测确认；CAN 时序
  验收必须记录实际 kernel clock，而不是只记录期望值。
- 板级 YAML 将 1 MiB 存储描述为 `qspi-nor-flash`
  （`hpm5321_custom.yaml:9-11`），而 `board.h:43-45` 注释为 “On-chip flash”；
  执行前必须以芯片手册、原理图和 linker map 明确实际启动/擦写介质。
- UART0 当前承担调试控制台。除非原理图确认第二 UART，否则本期不把 UART0
  同时作为高吞吐桥接通道，避免日志与业务数据竞争；板包当前波特率为 921600。

### 3.1 SPI2 SD 与指示灯硬件合同

产品命名固定为 `CAN1 = MCAN0`、`CAN2 = MCAN2`；CAN2 不是 MCAN1 外设。

| Signal | Pin | Planned role |
|---|---|---|
| SPI2 SCLK | PB11 | SD SPI clock |
| SPI2 MISO | PB12 | SD-to-MCU data |
| SPI2 MOSI | PB13 | MCU-to-SD data |
| SD CS | PB10 | GPIO CS；active-low 仅为 BSP 假设，P0S 验证 |
| SD detect | PY00 | card-present input；P0S 冻结 polarity/pull/debounce |
| CAN1 TX LED | PY01 | MCAN0 successful TX completion activity |
| CAN1 RX LED | PY02 | MCAN0 accepted RX activity |
| CAN2 TX LED | PY03 | MCAN2 successful TX completion activity |
| CAN2 RX LED | PA09 | MCAN2 accepted RX activity |
| STATUS LED | PA31 | health/status indication |

规范来源与完整决策见
`docs/approved-plan/scope-addendum-spi2-sd-led.md`（stable ID
`spi2-sd-led-2026-08-09`）。CS/LED active-low 常量必须与原理图和目标电压证据
一致后才能作为硬件结论。

## 4. RALPLAN-DR

### 4.1 Principles

1. **先垂直闭环，再横向铺开**：先完成“一路 CAN → USB → CLI”端到端闭环，
   再做双通道、SD 和 GUI。
2. **ISR 有界、所有权明确**：ISR 只做时间戳、状态采集和入队；每个外设和缓冲区
   必须有唯一所有者。
3. **协议先于界面稳定**：协议、测试向量和 CLI 是 GUI 的前置条件。
4. **能力协商而非硬编码**：CAN-FD、通道数、时间戳频率、最大批量、存储和升级
   都通过 capability 返回。
5. **每阶段以证据退出**：构建日志、串口、USB 枚举、CAN trace、drop counter、
   测试报告和版本元数据必须可追溯。

### 4.2 Decision drivers

1. 双通道 CAN 满载时的无阻塞采集、丢帧可见性和长期稳定性；
2. Windows/Linux/macOS 的驱动与分发复杂度；
3. 协议和核心逻辑可测试、可演进，避免 GUI 与设备 I/O 强耦合。

### 4.3 Viable options

#### Option A — CDC ACM 单通道字节流

- 优点：上手最快；三平台通常都能看到串口；便于人工调试。
- 缺点：端点/驱动缓冲行为不一致；高吞吐与低延迟不稳定；数据面和控制面容易
  相互阻塞；Windows COM 端口管理增加产品摩擦。
- 结论：保留为维护控制台/恢复通道，不作为主数据面。

#### Option B — Vendor-specific USB bulk + WinUSB/libusb（推荐）

- 优点：批量数据吞吐、异步 I/O 和多端点设计更适合分析仪；Windows 可用
  WinUSB，Linux/macOS 用 libusb；控制与数据可以逻辑分离。
- 缺点：需维护描述符、Windows OS descriptor、Linux udev 和 macOS 权限/打包；
  需要自定义协议和完善测试。
- 结论：作为 v1 主数据面。

#### Option C — 标准 USB 网络类 + TCP/UDP

- 优点：主机侧网络 API 成熟，远期可复用远程协议。
- 缺点：枚举、网络配置、系统防火墙、包重排/拥塞语义使 MVP 风险上升；
  与本地低延迟设备模型不匹配。
- 结论：不进入 v1，可作为远程代理的后续能力。

### 4.4 上位机技术选项

#### Host A — Rust 核心 + CLI + 原生 GUI（推荐）

- 协议解析、并发和缓冲边界更安全；可产出单一核心供 CLI/GUI 共用；
- 需要团队接受 Rust，并在最早阶段验证 USB 库和 GUI 打包。

#### Host B — C++/Qt 6

- 硬件工具生态成熟，GUI 能力完整；
- C++ 并发/生命周期风险更高，Qt 部署和许可策略需提前确定。

#### Host C — Python + Qt

- 原型最快；
- 高帧率、分发体积、依赖和 GIL/线程边界对长期产品化不利。

**选择规则**：该技术门属于 Phase 1、早于 host codec/CLI 实现。用两周以内的
技术验证比较 Host A/B 的三平台枚举、10k frame/s 虚拟流、打包体积、许可和
崩溃恢复。默认进入 Rust 路线；只有团队能力或 USB 库兼容性未达标时切换
**单一 C++/Qt core**，v1 不维护 Rust/C++ 双核心。协议规范不随 UI 技术栈变化。

## 5. 目标架构

### 5.1 固件分层

```text
app/
  app_main, lifecycle, health, config
services/
  command_router, capture_service, tx_scheduler, storage_service, diagnostics
protocol/
  framing, codec, messages, capability, versioning
drivers/
  usb_device, mcan_channel, spi_sd, debug_uart
rtos/
  task_config, static_queues, memory_pools, watchdog
bsp/
  thin adapters over hpm5321_custom board APIs
```

任务与唯一所有权合同：

| 任务 | 唯一拥有资源 | 主要责任/边界 |
|---|---|---|
| `usb_rx_task` | Bulk OUT endpoint/parser | 只验证/解码并向 `command_task` 入队，不触碰 MCAN |
| `command_task` | 产品控制状态机、TX arm generation | 串行化配置；通过通道 mailbox 请求 MCAN 变更 |
| `can0_task` | MCAN0 寄存器、RX/TX queue、completion | 唯一 MCAN0 owner；消费 ISR snapshot |
| `can2_task` | MCAN2 寄存器、RX/TX queue、completion | 唯一 MCAN2 owner；消费 ISR snapshot |
| `usb_tx_task` | Bulk IN endpoint 和 response/event/data scheduler | 控制响应保留配额并反饥饿 |
| `storage_task` | SPI2、PB10 CS、PY00 hot-plug、SD/FatFs、capture file | 唯一存储 owner；以 `media_generation` 管理拔插；低于 CAN/USB 优先级 |
| `health_task` | watchdog liveness ledger、watermark snapshot、PA31/PY01/PY02/PY03/PA09 | BSP init 后唯一 LED GPIO writer；timer/ISR 只发布状态 |

关键约束：

- ISR 只读取/清除硬件状态、写入预分配 ring 并用 ISR-safe API 唤醒唯一 owner；
  所有会调用 FreeRTOS API 的 IRQ 优先级、`configMAX_SYSCALL_INTERRUPT_PRIORITY`
  和端口映射在 Phase 2 冻结并由 target test 验证；
- v1 的 task、queue、ring、memory pool 全部静态分配；若保留动态分配，只允许在
  启动期并冻结 heap，运行期不得增长；
- USB 不可用时 CAN 捕获按策略“丢弃并计数”或“转 SD”，不能无限堆积；
- CAN 配置切换先停止通道、清队列、应用 bit timing、验证状态，再恢复；
- 统一 64-bit 单调时间戳；在 32-bit MCU 上由 ISR-safe high/low 采样或临界区
  snapshot 保证原子读取，协议返回 tick frequency 和 wrap/boot epoch；
- 每通道记录 RX/TX/filtered/drop/error/bus-off/recovery counters。
- watchdog 采用 per-task generation/liveness voting；只有所有必需 owner 在期限内
  推进时才喂狗，超时记录缺失 voter 和队列水位。
- CAN TX/RX ISR 和任务只发布有界 activity counter/event；TX 在控制器成功完成后
  发布，RX 在有效帧被接受后发布。LED pulse 可合并，不能 busy-wait 或反压 CAN。
- SD/FatFs 调用全部 marshalled 到 `storage_task`；移除卡时递增
  `media_generation`，拒绝新块并使旧 handle/token 失效。

### 5.2 固件强制 TX 安全状态机

`SAFE_LISTEN_ONLY → CONFIGURED → TX_ARMED(session,generation,expiry) → DISARMED`：

- 上电、配置 CRC 失败、watchdog reset 后均进入 `SAFE_LISTEN_ONLY`，收发器进入
  硬件安全态；
- TX arm 绑定 USB session、generation 和超时，不能跨 reset/re-enumeration 复用；
- firmware 强制检查 channel、ID、DLC/flags、nominal/data bitrate、队列深度和
  估算 bus-load；未来 v1.1 capability-gated schedule 还须限制任务数量，CLI
  白名单只是附加防线；
- USB reset/disconnect、arm expiry、watchdog、配置失败会清空 immediate TX queue
  并 disarm；若未来协商启用 v1.1 schedule，也必须同时取消；
- bus-off 默认保持 disarm，只有人工命令或经批准的有界恢复策略才能重新 arm，
  禁止无限自动重试；
- HIL cleanup 必须读取 diagnostics 并证明设备回到 listen-only、TX queue 为空；
  v1.0 不存在周期任务，未来 v1.1 schedule 则还须证明任务数为零。

### 5.3 USB 设备组合

推荐 composite device：

1. **Interface 0 — Vendor-specific**：HS 主数据面；Bulk OUT 承载控制命令和
   CAN TX，Bulk IN 承载响应、CAN RX、状态和事件；
2. **CDC ACM IAD / Interfaces 1–2（可编译关闭）**：Communication + Data
   interfaces，承担日志、调试命令、版本/诊断和恢复；
3. **DFU Runtime（可编译关闭）**：CDC 启用时为 Interface 3，CDC 关闭时为
   Interface 1；只负责 detach/reboot 进入独立 bootloader，仅在 UPDATE claim
   完成完整性、断电恢复和 rollback 后发布。

HS composite 使用 vendor bulk IN/OUT、CDC notification IN 和 CDC data IN/OUT；
DFU Runtime 只使用 EP0。描述符提供 HS、FS fallback、device qualifier 和
other-speed configuration；Windows vendor interface 用 Microsoft OS 2.0
descriptor 绑定 WinUSB。

如果 HPM5321 USB endpoint/descriptor 资源不足，优先保留 vendor bulk，UART0
继续承担维护控制台。

### 5.4 上位机分层

```text
host/
  core/       protocol codec, model, filtering, DBC, capture/replay
  transport/  usb backend, fake backend, recorded backend
  cli/        enumeration, config, capture, send, diagnostics, update
  gui/        views and interaction only
```

- GUI 不直接依赖 libusb；通过 core session/event API 工作；
- 采集线程只写无锁/有界队列，渲染层按帧预算批量消费并降采样；
- 原始 capture 与 UI 显示解耦：UI 可丢显示采样，但保存链路不能静默丢帧；
- 支持导出 CSV、ASC、PCAPNG（具体格式在兼容性验证后冻结）；
- DBC 解析、信号曲线、过滤表达式和发送模板均在主机侧。

## 6. 分阶段实施路线

### 6.1 依赖 DAG 与 feature gates

阶段编号表示交付顺序，不表示所有分支都线性阻塞：

| Node | Prerequisite | Required evidence | Conditional branch / blocks |
|---|---|---|---|
| P0U USB contract | context snapshot | speed/PHY/endpoint/FIFO/host profile | 只阻塞 P3A/USB 性能 |
| P0C CAN/clock contract | context snapshot | PLL1/kernel clock/transceiver/termination | 只阻塞 P3B/P5 |
| P0F flash/update contract | context snapshot | flash/linker/erase/boot topology | 只阻塞 update/release |
| P0H reference-host/product profile | context snapshot | named hosts + workload profiles | 阻塞对应性能 claim |
| P0S storage/I/O contract | schematic/BOM + P0H workload | pin electrical contract、SDHC media matrix、BP-STORAGE-v1、stack/patch ownership | P3C1；不阻塞无 STORAGE claim 的发布 |
| P1 repo/toolchain + host stack spike | P0H reference hosts | fresh clean build、debug adapter evidence、Host A/B verdict | 阻塞 host codec/CLI；Qt 时整体切 C++ core |
| P2 RTOS/time/ownership baseline | P1 firmware build | IRQ/API、static allocation、timestamp、watchdog tests | 阻塞固件数据面 |
| P3A USB slice | P0U + P2 | descriptor/loopback/hotplug | 与 P3B 可并行 |
| P3B single-channel CAN slice | P0C + P2 | MCAN0 listen-only、授权 TX、timing trace | MCAN2 smoke 为 non-blocking advisory；与 P3A 可并行 |
| P4P protocol + host codec | P1 host verdict | normative spec、golden vectors、fake transport | 可与 P3A/P3B 并行，E2E 前必须合流 |
| P4E single-channel E2E | P3A + P3B + P4P | named benchmark profile + CLI evidence | MVP 核心门 |
| P5 dual-channel/reliability | P4E | soak/fault/safety evidence | Beta 门 |
| P3C1 storage substrate | P0S + P2 | SPI2/detect/media generation、geometry/sync、bounded DMA、mount/recovery | P3C2 |
| P3C2 CAN capture integration | P3C1 + P3B | bounded admission、preallocation/commit、throughput/fault/isolation | P5S 和 recording claim |
| P5S STORAGE protocol/host addendum | P3C2 + P4P | wire contract、host codec、golden vectors、E2E | conditional(1.0,STORAGE) |
| P6 host core/CLI productization | P4E + selected host core | Linux/Windows package/session/soak；macOS deferred | 可与 P5 并行；CLI release |
| P7 GUI | P6 | UI benchmark/package | Beta 推荐但不阻塞；**1.0 required** |
| P5U update branch | P0F + P4E | boot/update/rollback evidence | conditional(UPDATE)，不阻塞未声明 update 的 scope |
| P8R(scope) release evidence | scope 对应 feature nodes | T-REL-001..004 evidence bundle | 每个 MVP/Beta/1.0 scope 都必须生成 |
| P8G(scope) scoped release gate | 见下列 release-scope 表 | scope acceptance + P8R(scope) | gate 本身不是自己的 prerequisite |

关键合流：`P0H → P1 → P2 → (P3A || P3B || P4P) → P4E →
(P5 || P6)`，P5/P6 不互相依赖；`P0U→P3A`、`P0C→P3B/P5`、
`P0F→P5U`；storage 的精确条件链为
`P0S -> P3C1 -> P3C2 -> P5S`，P5U 是另一条件分支，GUI 是 1.0 必需分支。任何 capability
不支持的条件分支必须按测试规范标记 conditional/skip，
不能悄悄降低 MVP 核心门。

只有 `1.0 + STORAGE` 可以声明 STORAGE；MVP 与 Beta 不能声明。早期执行 P0S、
P3C1 或 P3C2 只用于消除风险，不改变发布依赖或 capability advertisement。

P8 唯一 scoped prerequisites：

| Release scope | AND prerequisites | Conditional prerequisites |
|---|---|---|
| MVP | P4E + P6(MVP package/CLI) + P8R(MVP) | none |
| Beta | MVP + P5 + P6(Beta soak/package) + P8R(Beta) | CAN_FD only when capability is claimed；P7 recommended, non-blocking |
| 1.0 | Beta + P7 + P8R(1.0) | P3C1 + P3C2 + P5S when STORAGE claimed；P5U when UPDATE claimed；CAN_FD capability-controlled |

## Phase 0 — 硬件/产品约束冻结

### 工作

1. 收集原理图、BOM、PCB revision、USB PHY/ESD/VBUS、CAN transceiver、
   终端电阻和 UART/SPI 连接。
2. 建立 `docs/hardware/board_manifest.md`：板卡序列号、revision、探针、
   CAN 通道映射、收发器能力、可控 STB/EN。
3. 产品目标固定为 USB High-Speed；验证 controller/PHY 的 HS 枚举和链路质量，
   冻结 endpoint/FIFO 预算、最大 transfer、连接器/ESD/VBUS 和三台 reference
   host 的 USB controller/OS。FS 仅为 fallback descriptor，不作为性能 claim。
4. 用原理图、手册、linker map 和擦写实验冻结 flash/linker/erase/boot topology；
   关闭 YAML `qspi-nor` 与 `board.h` “on-chip flash”矛盾。
5. 测量并记录 PLL1 来源及 MCAN0/MCAN2 kernel clock；冻结收发器型号、FD、
   STB/EN、termination、供电和测试点。
6. 冻结产品负载模型：Classic/FD、DLC/payload mix、standard/extended 比例、
   channel split、bus utilization、batch/latency 和 storage 模式。
7. 确认 SD 是否为 MVP、VID/PID/字符串/序列号策略及 reference host。
8. 建立 P0S：验证本节 pin table、CS/LED 电气属性、PY00 polarity/pull/debounce；
   对 4/8/16/32 GB SD v2 SDHC/FAT32/512-byte sector 多 vendor matrix 测试，
   冻结 `BP-STORAGE-v1` 和 native stack/versioned patch ownership。

### Exit criteria

- P0U/P0C/P0F/P0H 分别有 owner、版本、证据和 `PASS/BLOCKED` 状态；它们可独立关闭；
- P0C `PASS` 时 CAN-FD 能力不再是推断，板/探针/adapter 有稳定唯一标识；
- P0H `PASS` 时 MVP/Beta benchmark profiles 与 reference hosts 已冻结；
- P0S `PASS` 时 `BP-STORAGE-v1` 的 encoded rate、queue absorption 和 operation
  deadline 已为正数，且 frozen-mode planning validator 通过；
- 任一未通过 contract 只阻塞 DAG 中明确依赖它的 node，不无谓阻塞 repo clean
  build；但未知项绝不能越过其依赖边。

## Phase 1 — 可复现 VSCode/命令行开发环境

### 目标文件

- `CMakePresets.json`
- `.vscode/extensions.json`
- `.vscode/settings.json`
- `.vscode/tasks.json`
- optional local editor launch configuration; the versioned contract lives in
  `docs/development/setup-linux.md` and the J-Link evidence report
- `scripts/env/`、`scripts/build.*`、`scripts/flash.*`
- `docs/development/setup-{linux,windows,macos}.md`

### 工作

1. 将绝对路径改为环境契约：`HPM_SDK_BASE`、工具链路径、`BOARD`；
   不把 `/home/gtc/...` 写入共享配置。
2. 将 `hpm5321_custom` 变成可版本化的 board overlay、SDK patch 或明确的
   submodule/manifest 输入；正式构建不能依赖个人 SDK 目录中的未跟踪文件。
3. 建立 Debug/Release、flash_xip/ram_debug 等明确 preset；始终导出
   `compile_commands.json`。
4. VSCode 使用 C/C++ 或 clangd 阅读；构建任务只调用 CMake preset。
5. J-Link GDB Server 是选中的 MVP adapter；以 stop-at-main、breakpoint、
   source/register inspect、step/reset 证据验证 checked-in VSCode profile。
   当前 board 无 SDK OpenOCD config，因此 OpenOCD 为 non-selected/non-gating。
6. 定义 `build -> flash -> reset -> UART smoke` 的脚本接口，但实际烧录必须在
   执行期经过硬件安全预检。
7. 修复正式 Git 仓库状态；忽略 `build/`，保留可追溯版本号。
8. Rust vs C++/Qt spike 已选定 Rust single core；fake/USB backend、10k
   synthetic、recovery 和 Linux/Windows functional lane 已通过。Qt 只在 1.0
   GUI phase 重新评估，不允许引入第二套 protocol/USB core。

### Exit criteria

- Linux/Windows 各完成 clean configure/build；macOS 按当前 CLI scope deferred；
- VSCode 跳转、补全与真实编译参数一致；
- Debug 可停在 `main`、查看变量、单步和复位；
- 构建产物包含 ELF/BIN/MAP、size、SDK/toolchain version 和 checksum；
- setup docs 与 CI 可从 clean checkout 完成首次构建；新成员 30 分钟 timed
  onboarding exercise 留给 P6 packaging evidence；
- host stack 与 debug adapter 的决策均有官方兼容资料、实测日志和 ADR addendum。
- Phase 1B closure manifest/validator 为 PASS；physical cable/PnP/release package
  evidence 留在 P3A/P6，不混入 Gate A。

## Phase 2 — 板级与 FreeRTOS 最小验证

### 工作顺序

1. 将当前 `USER/src/main.c` 最小 FreeRTOS 样例固化为 `board_smoke`，
   补齐 scheduler/heartbeat 后验证时钟、UART0、LED、timer。
2. 增加时钟自检：打印/断言 CPU、AHB、USB、CAN0、CAN2、SPI2 实际频率。
3. 移植 FreeRTOS 最小任务：heartbeat、队列、软件定时器、idle；
   参考 SDK `freertos_hello`。
4. 开启 `configASSERT`、malloc failed、stack overflow hook、栈水位和运行统计；
   落实“全部静态分配”或“只在启动期动态分配、随后 heap freeze”的单一策略。
5. 建立 fault handler：保存 reset cause、断言位置和最小故障信息。
6. 用 target tests 锁定 IRQ priority/ISR API、32-bit rollover 下的 64-bit timestamp
   原子读取、runtime allocation freeze、逐 task watchdog generation voter stall。
7. 验证五个 LED 上电/软件接管后的 default-off、逐个 routing、实际 polarity，
   将现有 `idleTask` writer 迁移为 health-owned indicator service，并测量 STATUS pattern。

### Exit criteria

- 24 小时 heartbeat 无复位/断言；
- UART 日志包含 firmware version、SDK 1.12.1、board、reset cause、时钟；
- 所有任务栈余量高于定义阈值（建议最小 25%，最终以测量定值）；
- Release 构建不依赖调试串口才能运行；
- `T-RTOS-005..008` 全部通过后 P2 才允许下游外设任务开始。

## Phase 3 — 外设垂直切片

### 3A USB

1. 从 CherryUSB FreeRTOS CDC 示例验证枚举、断连/重连；
2. 从 WinUSB 2.0 示例演进 vendor bulk interface；
3. 实现异步 RX/TX、endpoint reset、host disconnect 和统计；
4. Linux/Windows 完成枚举、权限、热插拔和 1 小时 bulk loopback；macOS 在
   后续 scope 启用时执行，不阻塞当前 CLI scope。

**通过**：按已冻结 `benchmark-profile-v1` 的随机 payload loopback，累计至少
10 GiB（仅 USB speed/profile 支持时），校验无错误；拔插 100 次无死锁；
USB 不可用不阻塞调度器。

### 3B CAN

1. MCAN internal loopback；
2. 单通道外部 silent/listen-only；
3. 授权 ID 范围内的 TX/RX；
4. MCAN2 independent smoke/loopback 作为 non-blocking advisory；失败记录为 Beta
   blocker，但不阻塞 MCAN0 MVP；
5. timestamp、TX event、error、bus-off/recovery；filter 可提前实现，但只在 Beta
   成为 required；
6. CAN-FD 仅在收发器确认支持后启用。

**通过**：MCAN0 按 `BP-CAN-MVP-v1` 满载 30 分钟无未解释丢帧；目标 bit timing
与示波器/分析仪一致，bus-off 可观测且按策略恢复。MCAN2 smoke 和 filter 的失败
不阻塞 MVP，但必须登记为 Beta blocker。

### 3C SPI/SD

本分支只有 Phase 0 明确选择 storage/lossless recording 时才进入；不阻塞 P4E
单通道 USB-CAN CLI MVP。

1. **P3C1 substrate**：确认 mode-0，初始化时钟不高于 400 kHz，数据时钟配置和
   实测均不高于 20 MHz；实现 PY00 debounce、`media_generation` 和 sole-owner API；
2. 审计并修复 logical sector count、erase-block sectors、last LBA 和
   `CTRL_SYNC`；用有限 deadline、task notification/semaphore 和 cache-correct DMA
   取代 SDK sample 的无限等待；
3. **P3C2 capture integration**：预分配 128 MiB segment，写入 generation、
   sequence、length、CRC 和最后提交 marker；truthful sync 后更新冗余 checkpoint；
4. 运行 full/remove/DMA timeout/real power-cut matrix；重新插卡不得复用旧 handle；
5. 以 frozen `BP-STORAGE-v1` 验证 committed throughput、p99 stall、CPU/queue、
   CAN/USB drop 和 p95 regression。

**通过**：`T-SD-001..007` 通过，committed payload throughput 至少为 frozen
encoded capture rate 的 2 倍，geometry/sync 与独立 host tool 一致，故障后只接受
matching generation/sequence/CRC 的 committed block。未完成真实 power-cut
commit-state matrix 前，不声明“最多丢失一个未提交 block”。

### 3D UART

1. UART0 保留日志和恢复 CLI；
2. 定义非阻塞 RX ring、DMA/idle line（若需要）；
3. 如果产品要求 UART bridge，必须使用原理图确认的独立 UART 实例，不复用 UART0。

**通过**：日志洪泛不影响 CAN 捕获；UART 断开不影响 USB/CAN。

## Phase 4 — 协议 v1 与单通道端到端 MVP

1. 使用 Phase 1 已选定的 host stack，先实现最小 host codec/CLI 与
   `docs/approved-plan/usb-can-protocol-v1.md` 中的 framing、HELLO、
   GET_CAPABILITIES、CONFIG_CHANNEL、START/STOP_CAPTURE、CAN_RX_BATCH、
   CAN_TX/TX_RESULT、GET_DIAGNOSTICS。
2. 生成 golden vectors，固件 C codec 与主机 core 使用相同二进制样例。
3. 完成“一路 MCAN0 → timestamp/ring → USB batch → CLI capture”。
4. 加入 sequence、request correlation、错误码、timeout、cancel、drop counter，
   以及 response/event/data 的 bounded QoS。
5. 引入 fake USB transport，使大部分主机测试不依赖硬件。
6. 实现 firmware-enforced TX safety state machine，并让 CLI 仅能进一步收紧策略。

### Exit criteria

- CLI 可枚举、打印 capability、配置通道、捕获、发送和读诊断；
- 未知 message/type/flag 返回确定错误且会话继续；
- 主机/设备 golden vector 100% 一致；
- `BP-LATENCY-v1` 下 MCU RX timestamp 到 CLI 接收 p95 ≤ 5 ms；
- `BP-CAN-MVP-v1` normal profile 持续 30 分钟设备侧 drop=0；
- USB 主机停止读取时，设备按规定流控/丢弃并正确累计 drop，不死锁。

## Phase 5 — 双通道固件产品化

1. 启用 MCAN0 + MCAN2，独立配置、filter、统计和 LED；
2. 实现 v1.0 immediate TX queue/cancel；限制队列、per-channel rate 和 bus load。
   周期 TX 移出 Beta，等待独立 v1.1 addendum；
3. 配置持久化：schema version、CRC、默认值、恢复出厂；
4. health/watchdog、栈/heap/ring watermark、USB/CAN 诊断快照；
5. 静态分析、编译告警、map/stack/heap 预算门禁。
6. 验证 USB reset/disconnect、watchdog、config CRC、bus-off、arm expiry 均
   disarm 并清空 immediate TX queue；若未来协商启用 v1.1 schedule，也必须取消；
   HIL cleanup 必须读取状态证明安全态。

### Exit criteria

- 双通道满载及并发 TX 场景无死锁、无 silent drop；
- `BP-CAN-BETA-v1` 双通道 profile 持续 72 小时通过；
- 所有资源耗尽路径都有错误码和计数器；
- 72 小时 soak、1000 次 USB reconnect、100 次 CAN bus-off 注入通过；
- release map 中 Flash/RAM 留有约定余量（建议 MVP ≥ 20%，最终按实测）；

### Conditional P3C STORAGE branch

仅当 1.0 claim manifest 声明 `STORAGE` 时执行；即 `1.0 + STORAGE`，并严格依赖
`P0S -> P3C1 -> P3C2 -> P5S`。依赖 Phase 0 的 storage 决策，
实现 SD capture/replay、恢复与诊断，并通过 `T-SD-001..007`。未声明时固件 capability
不得发布 STORAGE，CLI/GUI 省略入口或稳定返回 `UNSUPPORTED`。

`STORAGE` claim 还必须完成 P5S addendum：冻结 SD start/stop/list/read/delete wire
contract、host codec、golden vectors 和端到端读回/删除/恢复测试
`T-SD-008..010`。只有设备侧写卡通过不得发布 STORAGE capability。

### Conditional P5U UPDATE branch

仅当 claim manifest 声明 `UPDATE` 时执行；硬依赖 `P0F + P4E`：

1. firmware image metadata、board/version 兼容检查；
2. DFU/bootloader、真实性/完整性、rollback/recovery；
3. 对每个 update phase 做断电注入并通过 `T-UPD-001..005`。

**Exit**：升级断电故障不导致不可恢复设备；未完成 P5U 时 capability 不得发布
UPDATE，任何主机入口必须省略或稳定返回 `UNSUPPORTED`。

## Phase 6 — 多平台核心与 CLI 产品化

1. 使用 Phase 1 已选定的单一 host stack 建立 workspace；本阶段不得重新打开
   Rust/Qt 选择，也不得产生双 core；
2. 实现 transport trait、libusb backend、fake/recorded backend；
3. 实现设备会话状态机、协议 codec、超时/取消、热插拔、日志；
4. CLI 子命令：
   `list`、`info`、`config`、`capture`、`send`、`diagnostics`；`update` 仅在
   `P5U complete && UPDATE claimed` 时构建/显示，否则省略或稳定返回
   `UNSUPPORTED`；
5. 支持 JSON Lines 输出供 CI/HIL，终端输出与机器输出分离；
6. Linux/Windows 打包、权限/udev/WinUSB 指南和签名策略；macOS deferred。

### Exit criteria

- Linux/Windows 同一 golden vector 和协议测试全部通过；
- CLI 在设备断连、重新枚举、协议版本不兼容时返回稳定 exit code；
- CLI HIL 可自动执行双通道 capture/send/error 测试；
- 主机长期采集 72 小时无内存无界增长。

## Phase 7 — GUI 分析仪

按价值排序：

1. 设备/通道配置、连接状态和诊断；
2. 高性能 trace table、过滤、暂停显示但不中断采集；
3. 手动发送、模板和安全确认；周期发送仅在未来 v1.1 capability 协商成功后显示；
4. 文件 capture/replay、CSV/ASC/PCAPNG 导入导出；
5. DBC 加载、信号解码、曲线和统计；
6. 错误帧、bus load、drop、bus-off 可视化；
7. 日志打包和问题报告；固件升级仅在
   `P5U complete && UPDATE claimed` 时构建/显示，否则省略或稳定返回
   `UNSUPPORTED`。

### GUI 性能策略

- 原始 ingest、持久化、过滤、聚合和渲染分线程/任务；
- table 使用虚拟化；曲线按像素宽度降采样；
- UI “显示丢帧”与“采集丢帧”分开计数；
- 自动保存 workspace/schema version，坏配置可回退。

### Exit criteria

- 20k frames/s 输入下 UI 保持可交互，参考机 p95 frame time < 33 ms；
- GUI 暂停/切换页面不增加设备 drop；
- 2 小时高负载后内存达到稳态，无持续线性增长；
- Windows/Linux 安装、首次枚举和卸载路径有文档；macOS deferred。

## Phase 8 — CI、HIL、发布与维护

1. 固件 clean build matrix、warning-as-error、static analysis、size budget；
2. 协议 codec fuzz/property tests、golden vector compatibility；
3. 主机 Linux/Windows unit/integration/package；macOS deferred；
4. HIL 资源锁：板卡/探针/CAN 适配器唯一 ID；
5. 自动 flash、UART health、USB enumerate、CAN loop、fault injection、cleanup；
6. 发布 SBOM/依赖许可、版本矩阵、固件/协议兼容表、checksum；
7. issue 模板自动附带 device info、firmware version 和 diagnostics。
8. 冻结 reproducible release contract：
   - pinned SDK/toolchain/CMake/Ninja/board overlay checksum；
   - source path、archive ordering、locale/timezone/timestamp 归一化；
   - firmware ELF/BIN/MAP、host package、SBOM、protocol vectors checksum；
   - firmware ↔ host ↔ protocol minor ↔ bootloader ↔ capture-format 兼容矩阵。
   - 在两个独立 clean environments 使用同一 pinned source/input manifest；
   - **raw artifacts**：构建器直接输出的 firmware ELF/BIN/MAP、unsigned archive、
     SBOM、vectors；每项报告 raw SHA-256，声明 deterministic 的项目必须 byte-identical；
   - **unsigned payload**：签名前实际被封装/签名的 payload tree；文件内容和 metadata
     归一化后必须一致，并生成整体 payload digest；
   - **normalized manifest**：UTF-8、lexicographic path 排序、LF、固定字段顺序的
     JSONL；每项必须含 canonical relative path、type(file/dir/symlink)、POSIX mode、
     symlink target、size、`content_sha256`，整体再计算 SHA-256。file：
     `size=content bytes`、hash=文件 bytes SHA-256、target=null；directory：
     `size=0`、hash=null、target=null；symlink：target 为未解析的 NFC UTF-8 相对
     target，`size=UTF-8 byte length`、hash=target bytes SHA-256；
     entry path 必须是 payload-root-relative NFC UTF-8、只用 `/`、不得含 absolute/
     drive prefix、空 segment、`.`、`..`、反斜杠、NUL 或 trailing slash；归一化后
     路径必须唯一，大小写折叠碰撞也拒绝；按 normalized UTF-8 bytes 排序。walk
     不 follow symlink，symlink target 不得解析后逃逸 payload root。portable POSIX
     mode 只保留 type + owner executable bits：regular `0644/0755`、directory
     `0755`、symlink `0777`，忽略 host umask/ACL；
   - **signed artifact**：raw bytes 可因签名/timestamp 不同；只验证它绑定的 unsigned
     payload digest、signature chain、subject、algorithm、timestamp authority 和
     validity，不能用 signed wrapper raw checksum 代替 payload reproducibility。
     若 scope 的 claim manifest 不声明签名，则第四类结果必须为
     `NOT_PRODUCED-BY-SCOPE` 并附 claim manifest；这是合法的 in-scope 结果而非 SKIP，
     且不得声称 signed distribution。

### Release gate

- 所有 in-scope required P0/P1 测试通过；conditional feature 只能按测试规范的
  capability 证据 `SKIP-UNSUPPORTED`，且不得出现在 release claim；
- 无未解释 drop、reset、bus-off 或内存增长；
- T-REL-002 分别报告 raw、unsigned、normalized、signed 四类结果；firmware BIN 与
  声明 deterministic 的 raw/unsigned payload byte-identical，normalized manifest
  digest 一致，signed artifact 按上条绑定关系验证；
- 协议兼容矩阵、已知问题、恢复路径和回滚步骤已发布；
- 两个独立 clean environments 的 source/input manifest 和比较报告已归档。

## 7. 功能优先级

### MVP

- 可复现 build/flash/debug；
- FreeRTOS health；
- vendor bulk USB；
- 单通道 Classic CAN capture/send；
- protocol v1 core；
- CLI；
- 基础诊断和 30 分钟满载测试。

### Beta

- 双通道、CAN-FD（硬件允许时）、filter；
- 72 小时 soak、热插拔、bus-off；
- GUI trace/filter/send/capture 推荐交付，但不作为 Beta release blocker；
- Linux/Windows 安装；macOS 在后续 scope 启用时补测。

### 1.0

- 双通道 + CLI + GUI；DBC、曲线、回放和 GUI 性能门全部 required；
- SD 记录（仅当声明 `STORAGE`）；
- 安全升级/回滚（仅当声明 `UPDATE`）；
- CI/HIL 发布门禁、文档和兼容策略。

## 8. 需求与验收标准

### 8.1 Benchmark profiles

Phase 0 必须把下表的 `TBD` 冻结为版本化 profile；未冻结前数值只是设计目标，
不能作为产品声明：

| Profile | USB/CAN workload | Batch/host | Measurement contract | Target |
|---|---|---|---|---|
| `BP-USB-INTEGRITY-v1` | HS；payload 1–4096 B seeded mix；FS 仅 fallback 枚举 | transfer/queue=`TBD`；named host | warm-up 60 s；10 GiB；CRC/byte count | HS 枚举且 content error=0 |
| `BP-CAN-MVP-v1` | MCAN0；Classic 1 Mbit/s；std/ext=90/10；DLC 0/1/2/4/8=5/5/10/20/60%；80±1% utilization；≥6000 frame/s | max 32 records / 1 ms；HS 2048 B；8 in flight；named Linux/xHCI host | 60 s warm-up + 30 min；≥10.8M frames；device/external/host counters reconcile | `bp-can-mvp-v1.json`；normal profile drop/gap/reset=0 |
| `BP-CAN-BETA-v1` | MCAN0+MCAN2；Classic/FD capability；channel split/bitrate/utilization=`TBD` | batch count/wait=`TBD` | 72 h；per-channel/aggregate counters reconcile | frozen supported aggregate rate（20k 仅为候选）；normal profile drop=0 |
| `BP-LATENCY-v1` | 完整继承 `BP-CAN-MVP-v1` 输入 | 同一 named Linux/xHCI host；32 PING before/after/every 60 s | 60 s warm-up；≥1M samples；lowest-RTT quartile offset+drift fit；nearest-rank p50/p95/p99 | `bp-latency-v1.json`；p95 ≤ 5 ms；residual+quantization ≤1 ms |
| `BP-BACKPRESSURE-v1` | 当前 release scope 的 BP-CAN-MVP/BETA 输入；host stop windows=`TBD` | fixed ring/pool/batch | 分别验证 normal 与 overload；对账 drop/event/sequence | normal=0 drop；overload=显式、精确可计数 |
| `BP-GUI-v1` | recorded 20k frame/s | named host；viewport/filter=`TBD` | 5 min warm-up；2 h；frame-time histogram/RSS slope | p95 < 33 ms；后 60 min RSS slope ≤ `TBD` |
| `BP-STORAGE-v1` | 4 KiB blocks、queue 8、128 MiB segments、frozen BP-CAN-BETA | 8 queued 16 KiB USB reads；20 MHz ceiling | 60 s warm-up；30 min/card；72 h soak | `BLOCKED(P0S)` until numeric rate/absorption/deadline are frozen |

所有 profile 记录 Classic/FD、DLC/payload、standard/extended、channel split、
bus utilization、USB speed、batch、reference host/OS/controller、样本数、warm-up、
percentile 算法。设备 tick 与 host time 只能通过明确的 PING 校准误差预算比较。

### 8.2 Requirement → test → evidence traceability

| ID | 验收标准 | Test IDs | Evidence / class |
|---|---|---|---|
| DEV-01 | clean checkout 生成 ELF/BIN/MAP，记录 SDK/toolchain | T-DEV-001/002/004 | build log + checksums；P0 required(MVP+) |
| DEV-02 | 选定 VSCode adapter 可 stop/main/step/reset | T-DEV-005/006 | debug transcript；P0/P1 required(MVP+) |
| DEV-03 | compile_commands 与真实编译一致 | T-DEV-003 | clangd/config evidence；P0 required(MVP+) |
| BSP-01 | UART/LED/timer/clock smoke 24 h 无 reset/assert | T-BSP-001..003,T-RTOS-003 | UART/clock/soak；P0 required(MVP+) |
| RTOS-01 | task/hooks/IRQ/allocation/timestamp/watchdog contract | T-RTOS-001/002/005..008 | target/fault evidence；P0 required(MVP+) |
| RTOS-02 | task stack ≥25% 或批准例外 | T-RTOS-004 | watermark + exception ADR；P1 required(MVP+) |
| USB-01 | BP-USB-INTEGRITY 内容零错误，100 次热插拔 | T-USB-001..010 | USB trace/counters；P0 required(MVP+) |
| CAN-01 | BP-CAN-MVP normal profile 无 device drop | T-CAN-001,003..004,006..008,011..015 | CAN analyzer + diagnostics；P0 required(MVP+) |
| CAN-03 | BP-CAN-BETA 双通道 72 h 无 silent drop | T-CAN-009,T-FW-001..003 | soak/analyzer bundle；P0 required(Beta+) |
| CAN-04 | CAN-FD/BRS/64 B capability | T-CAN-010 | analyzer/HIL；P0 conditional(Beta+,CAN_FD) |
| CAN-02 | error/timestamp 与外部仪器一致 | T-CAN-006/008/011 | CAN/UART trace；P0 required(MVP+) |
| CAN-05 | MCAN2 smoke 与 filter hit/miss | T-CAN-002/005 | CAN analyzer；P0 required(Beta+)，MVP advisory |
| LED-01 | STATUS/CAN1 electrical, ownership and semantics | T-LED-001,T-LED-002,T-LED-003,T-LED-006 | schematic/target/static/HIL；P0 required(MVP+) |
| LED-02 | CAN2 electrical and semantics | T-LED-004,T-LED-005 | schematic/target/HIL；P0 required(Beta+)，MVP advisory |
| PROTO-01 | C/selected-host codec golden vectors 一致 | T-PROTO-001 | vector corpus/report；P0 required(MVP+) |
| PROTO-02 | malformed input 安全且稳定错误 | T-PROTO-003..005/009 | fuzz corpus/report；P0 required(MVP+) |
| PROTO-03 | version/sequence/cancel/capability/QoS closure | T-PROTO-002/006..008/010..012 | compatibility/state-machine/HIL；P0 required(MVP+) |
| E2E-01 | BP-LATENCY p95 ≤ 5 ms | T-E2E-004 | calibrated raw samples；P0 required(MVP+) |
| E2E-02 | backpressure 无 silent loss | T-E2E-006/007,T-FW-004/005 | counter reconciliation；P0 required(MVP+) |
| E2E-03 | session/config/TX/CLI/compound fault | T-E2E-001..003/008/009 | HIL bundle；P0 required(MVP+) |
| E2E-04 | BP-CAN-BETA aggregate profile | T-E2E-005 | benchmark bundle；P0 required(Beta+) |
| FW-01 | 双通道并发 72 h 无 reset/deadlock/silent loss | T-FW-001..003 | soak/fault bundle；P0 required(Beta+) |
| FW-02 | Beta flash/RAM/stack budget 与运行期内存稳态 | T-FW-008 | map/watermark/RSS；P1 required(Beta+) |
| FW-03 | watchdog/config/static/safety/cancel/cleanup | T-FW-006/007/009/010/012/013 | target/HIL/static evidence；P0 required(MVP+) |
| FW-04 | dual-channel timestamp/order | T-FW-011 | HIL/order trace；P0 required(Beta+) |
| HOST-01 | Linux/Windows CLI 同套件、稳定 exit code | T-HOST-001/002/004 | package/test report；P0 required(MVP+)；T-HOST-003 deferred(macOS) |
| HOST-02 | CLI 72 h memory plateau | T-HOST-005 | profiler/RSS trace；P1 required(Beta+) |
| GUI-01 | BP-GUI、filter/export/recovery | T-GUI-001..006 | GUI/profiler evidence；P1 required(1.0)，Beta recommended |
| STORE-01 | 设备存储恢复 + protocol/host/E2E | T-SD-001..010 | fault/golden/host E2E；P1 conditional(1.0,storage) |
| UPDATE-01 | 断电后 rollback/recovery | T-UPD-001..005 | power-cut matrix；P1 conditional(1.0,update) |
| REL-01 | 固件/主机/版本/发布工件可追溯 | T-REL-001..004 | manifest/SBOM/checksums；P0 required(MVP+) |

`25%`/`20%` 预算在 Phase 2/5 的首次 measured baseline 冻结；例外必须记录 owner、
原因、最坏栈证据、补偿措施、过期版本。内存“稳态”定义为 warm-up 后固定窗口内
pool/queue watermark 不增长、host RSS slope 不超过 profile 阈值。

## 9. 风险与缓解

| 风险 | 缓解 |
|---|---|
| PLL1/CAN kernel clock 假设错误 | bring-up 打印/测量实际频率；bit timing 用仪器验证 |
| 收发器不支持 CAN-FD | Phase 0 查 BOM；capability 动态声明，不硬编码 |
| USB 主机读取停顿导致环形缓冲溢出 | 有界 ring、batch、watermark、drop counter、可选 SD fallback |
| USB composite endpoint 资源不足 | 优先 vendor bulk；CDC 可编译关闭，UART0 保底 |
| FreeRTOS IRQ 优先级错误 | 统一中断策略；ISR API 静态检查；目标 fault-injection |
| GUI 高负载冻结 | core/UI 解耦、虚拟化、降采样、reference benchmark |
| 三平台驱动/权限不一致 | CLI 技术验证提前；WinUSB descriptor、udev、macOS 打包分别测试 |
| SD 写阻塞实时采集 | 独立低优先级 task、双缓冲、吞吐 2x 门禁、可禁用 |
| 协议过早复杂化 | v1 只含核心命令；capability + TLV/length 支持扩展 |
| 升级变砖 | A/B 或恢复 bootloader、签名/CRC、断电故障注入；未达标不开放 |
| 当前仓库无有效 Git 元数据 | Phase 1 先建立正式版本库和 release metadata |
| 自定义 board 只存在于个人 SDK 目录 | repo 内 board overlay/patch + pinned SDK，并在 clean machine 验证 |
| Rust/GUI 技术栈不适配团队 | 两周技术门，与 Qt 6 同指标比较；协议和 CLI 不被 GUI 绑定 |

### 9.1 Pre-mortem

| Failure scenario | Early signal | Containment | Recovery | Owner | Go/no-go |
|---|---|---|---|---|---|
| USB HS/endpoint 预算误判，10 GiB/延迟指标不可达 | 未以 HS 枚举、descriptor/FIFO 超预算或 HS 吞吐不足 | 关闭 CDC/DFU Runtime 隔离 composite，缩小 batch | 回到 P0 修正 PHY/descriptor/FIFO；必要时修改硬件 | firmware architect + hardware owner | P3A 前 USB HS contract 必须签字；否则 no-go |
| PLL1/MCAN clock 或收发器 FD 能力误判 | measured kernel clock 与配置不符、分析仪 bit timing 偏差、FD error | 保持 listen-only，禁用 TX/FD capability | 修正 clock tree/bit timing；若硬件不支持则降级 Classic-only 并更新 capability | BSP/CAN owner + verifier | P3B TX 前 clock/transceiver evidence；否则 no-go |
| host backpressure 令 Bulk IN 控制面饥饿或 silent loss | response latency 上升、control reserve 耗尽、sequence gap 无 event | 固件 QoS 保留 response slots，超载显式 drop/data-loss，disarm TX | 调整 admission/batch/queue；启用容量验证后的 SD 模式或下调负载 | protocol/USB owner + test engineer | P4E 必须通过 normal/overload 两套 profile；否则 no-go |

风险取舍是明确的：v1 保证“实时路径有界且 overload 显式丢失”，不承诺 host
无限停读时仍无损；只有 `P3C` 容量与故障恢复均通过，才能声明 lossless recording。

## 10. 验证顺序

1. 静态验证：配置、pinmux、clock、编译告警、map、API 合同；
2. 主机单元：codec、ring、filter、DBC、capture 格式；
3. 目标 smoke：board、RTOS、USB loop、MCAN loop；
4. 外设集成：USB 热插拔、CAN listen-only 后授权 TX、SD；
5. E2E：设备 → USB → CLI；
6. 压力：双通道满载、host backpressure、日志洪泛；
7. 故障：USB disconnect、bus-off、SD 拔出、配置损坏、升级断电；
8. 长稳：24 h board、72 h full system；
9. 三平台安装/升级/卸载；
10. 发布证据审查。

硬件验证开始前必须记录：

- board/probe/CAN adapter 唯一身份；
- 固件 checksum；
- 允许的 CAN bitrate、ID 和 payload 范围；
- listen-only 基线；
- 超时、复位和安全清理路径。

## 11. ADR

### Decision

采用“**FreeRTOS 分层固件 + CherryUSB vendor bulk 主数据面 + 可选 CDC 维护面 +
版本化二进制协议 + CLI-first + 共享跨平台主机核心**”。

Phase 1 在任何 host codec/CLI 前用同一 evidence profile 在 Rust 与 C++/Qt 6
之间选定一个单一 core；默认候选 Rust，但该默认不构成实现承诺。GUI 不绑定设备
wire protocol，v1 禁止维护双 host core。

### Drivers

1. 双通道 CAN 满载采集时数据路径必须有界且可观测；
2. 三平台驱动/打包可落地；
3. 协议、自动化和 HIL 必须早于 GUI 稳定。

### Alternatives considered

- CDC ACM-only：保留维护用途，不满足主数据面稳定性目标；
- USB 网络类：v1 配置和系统依赖过重；
- C++/Qt：强 steelman 备选；对 C/C++ 团队可能降低 GUI/打包/FFI 风险，但增加
  生命周期、并发安全和 Qt 许可治理；
- Python/Qt：适合原型，不作为默认发布架构。

### Why chosen

本地 SDK 已有 FreeRTOS CherryUSB CDC/WinUSB 与 MCAN 示例，能降低固件集成风险；
vendor bulk 更适合有界批量帧；CLI-first 能同时验证协议、自动化和 HIL；
共享核心避免 GUI、CLI 各自实现协议。

### Consequences

- 前期必须投入 descriptor、协议、golden vector 和三平台权限/打包；
- 固件需要严格 ring/memory pool 和诊断体系；
- GUI 进度晚于 CLI，但返工和不可测试耦合显著减少；
- Phase 1 技术门之前不能实现正式 host codec；Rust 失败时整体切换单一 Qt/C++
  core，而不是维护双栈。

### Follow-ups

1. 获取原理图/BOM并关闭 Phase 0 未知项；
2. 通过重新 Architect→Critic 顺序复审完成 durable consensus gate；
3. 共识批准后以 `$ultragoal` 建立 durable story ledger；
4. Phase 1/3/6 可用 `$team` 并行，但每个阶段仍由 Ultragoal checkpoint；
5. 在首次主动 CAN/HIL 或烧录前执行硬件安全预检；
6. Phase 1 用 `researcher` 获取 HPM/OpenOCD/J-Link/USB backend 官方兼容证据，
   再由 `dependency-expert` 比较 Rust/Qt，不能靠 repo-local recall 决策。

## 12. Available agent types roster

可用且与实施相关的角色：

- `explore`：repo/SDK 文件、符号、示例定位；
- `researcher`：HPM/CherryUSB/FreeRTOS/libusb/平台官方文档；
- `dependency-expert`：Rust/Qt、USB 库、GUI/打包依赖比较；
- `planner`：story 分解、入口/退出门；
- `architect`：固件/协议/主机边界和长周期权衡；
- `executor`：通用实现；
- `debugger`：构建、USB、RTOS、CAN 根因；
- `test-engineer`：host/target/HIL/性能测试；
- `verifier`：独立完成证据；
- `code-reviewer`：综合变更审查；
- `code-simplifier`：已验证功能后的行为保持简化；
- `designer`：GUI 信息架构和交互；
- `writer`：协议、开发、发布文档；
- `git-master`：仓库恢复、提交/发布策略；
- `critic`：计划/门禁审查。

## 13. Follow-up staffing guidance

### `$ultragoal`（默认 durable 执行）

- Leader/ledger：`planner` 或主代理，high reasoning；
- 每个 story 实现：`executor`，medium；
- 嵌入式故障：`debugger`，high；
- 测试设计：`test-engineer`，medium；
- story 验收：`verifier`，high；
- 涉及外部 SDK 时：`researcher`，high，先于实现。

建议 stories：

1. Environment & repository baseline
2. Board/FreeRTOS smoke
3. USB vertical slice
4. CAN vertical slice
5. Protocol v1 + golden vectors
6. Single-channel E2E CLI MVP
7. Dual-channel/reliability/storage
8. Cross-platform core/CLI
9. GUI
10. CI/HIL/release

### `$team`（并行实施）

在 Phase 1、Phase 3、Phase 6-7 使用 3 个执行 lane：

1. Firmware lane：`executor` + 嵌入式技能，medium；
2. Host/protocol lane：`executor`，medium；
3. Test/evidence lane：`test-engineer`，medium；

阶段末追加一个 `verifier` high lane，独立读取原始日志和 acceptance matrix。
Architect/Critic 审查必须保持顺序，不与对方并行。

### Launch hints

```bash
# 默认：durable ledger，由 leader 逐 story checkpoint
$ultragoal docs/approved-plan/prd-hpm5321-usb-can-analyzer.md

# 大阶段内并行，例如 USB/CAN/测试工装
$team 3:executor "按 docs/approved-plan/prd-hpm5321-usb-can-analyzer.md 执行当前已批准 story；
固件、主机协议、测试证据分 lane；不得越过硬件安全预检"

# CLI/tmux 形式
omx team 3:executor "execute approved story from docs/approved-plan/prd-hpm5321-usb-can-analyzer.md"
```

### Team verification path

Team 关闭前必须证明：

1. 各 lane 修改范围、命令和原始日志完整；
2. target tests、host tests、build/size/static analysis 通过；
3. 硬件测试记录 board/probe/adapter identity 和 cleanup；
4. acceptance ID 映射到证据路径；
5. verifier 给出 pass/fail/skip，不用“看起来正常”替代数据。

Ultragoal 只把已验证的 Team 证据 checkpoint 为 story complete；未通过项回到原 story，
不靠 Team shutdown 自动视为完成。

### `$ralph` fallback

仅当用户明确选择“单一 owner 持续修复直到 evaluator 通过”时使用 `$ralph`。
本项目跨固件、协议、三平台和 HIL，需要 durable story ledger，因此不推荐 Ralph
替代 Ultragoal。

## 14. Goal-mode follow-up suggestions

- **推荐：`$ultragoal`** — 把本计划拆成 durable stories 并记录逐阶段证据；
- **并行：`$ultragoal` + `$team`** — Ultragoal 持有 ledger，Team 交付并行证据；
- **`$performance-goal`** — 后期若专门优化 frame/s、p95 latency、RAM 或 GUI frame time；
- **`$autoresearch-goal`** — 当前不是研究项目，不作为实施架构；仅在要产出正式
  USB/协议/依赖调研报告时使用；
- **`$ralph`** — 仅明确选择的单 owner fallback。

## 15. Planner draft changelog

- 将用户原来的 6 个大步骤重排为“硬件约束 → 工具链 → RTOS → 外设垂直切片 →
  协议/CLI MVP → 双通道可靠性 → GUI → CI/HIL/发布”；
- 把协议和 CLI 提前，避免 GUI 先行导致协议反复；
- 将 UART0 定位为维护/日志通道，避免和主数据面竞争；
- 将 SPI/SD 设为独立可选里程碑，不阻塞 USB-CAN MVP；
- 增加 capability、流控、drop counter、故障恢复、升级、版本兼容和发布门禁；
- 增加明确性能、长稳、故障注入和三平台验收指标。

## 16. Architect iteration 1 response

> 独立 typed Architect verdict 为 `ITERATE`；本节记录 Planner 已吸收的修订，
> 不代表复审已批准，也不替代后续 Critic 门。

1. **可复现性反例**：当前 board package 在 repo 外；已把版本化 board overlay /
   SDK patch 提升为 Phase 1 强制条件。
2. **存储介质歧义**：YAML 的 QSPI NOR 与 `board.h` 的 on-chip flash 注释不一致；
   升级、链接和擦写设计前必须用 linker map、原理图和手册关闭。
3. **USB composite 资源张力**：CDC 是可编译关闭的维护接口；endpoint 资源不足时
   vendor bulk 优先。
4. **技术栈锁定风险**：Rust 是默认候选，不是无条件承诺；Rust/Qt 必须通过同一
   三平台 USB、10k frame/s 和打包 spike。
5. **性能阈值环境依赖**：5 ms、20k frame/s、33 ms 必须绑定 reference host、
   USB 模式和 CAN 负载，技术 spike 后冻结。
6. **协议 ABI 风险**：wire codec 不得直接使用编译器 C struct 布局；所有字段按
   明确 offset、length 和 endianness 编解码。
7. **基线修复**：Context/§3 已记录 missing declared source、`USER/` 实际布局、
   FreeRTOS 开关和 UART 921600；fresh clean build 保持为 P1 首个失败待关闭门。
8. **依赖修复**：新增 DAG，Host A/B 门移至 P1，P3C SD 明确不阻塞 MVP。
9. **规范/安全修复**：协议固定 numeric registry、CRC、payload、sequence/cancel/
   QoS；固件新增 session-scoped TX safety state machine。
10. **验收修复**：新增 benchmark profiles、P0/P1/P2/conditional/skip 规则、
    requirement→test→evidence matrix、组合故障与三场景 pre-mortem。
11. **发布修复**：新增 pinned inputs、归一化构建、SBOM/checksum 与
    firmware/host/protocol/bootloader/capture-format 兼容矩阵。
