# HPM5321 USB-CAN Analyzer — Test Specification

> 对应 PRD：`docs/approved-plan/prd-hpm5321-usb-can-analyzer.md`  
> 状态：Planner 草案；硬件阈值在 Phase 0 后冻结

## 0. Priority, applicability, and release semantics

- **P0**：产品安全、数据完整性或核心 MVP；任何 required P0 失败立即 stop。
- **P1**：可靠性、三平台发布或选中 feature 的产品质量；进入相应 Beta/1.0 前必须通过。
- **P2**：增强/诊断；允许带 owner、期限和已知问题的 deferred。
- **required**：当前 release scope 必须运行并通过；
- **required(MVP+)**：MVP、Beta、1.0 均必需；
- **required(Beta+)**：Beta、1.0 必需，不阻塞单通道 MVP；
- **required(1.0)**：只阻塞 1.0；
- **conditional(feature/capability)**：仅当 Phase 0/Capability 声明该 feature 时转为
  required；不支持时可 `SKIP-UNSUPPORTED`，但必须附 hardware/capability evidence；
- **deferred**：只允许 P2，必须记录 issue/owner/expiry。

`SKIP-HW-UNAVAILABLE` 不能满足 release；它使依赖该硬件的 gate 保持 blocked。
`SKIP-UNSUPPORTED` 只对明确 conditional 项有效，且 release notes 必须声明 capability
缺失。required P0/P1 不允许普通 SKIP。

### Complete test classification registry

| IDs | Priority | Applicability |
|---|---|---|
| T-DEV-001..005 | P0 | required(MVP+) |
| T-DEV-006 | P1 | required(MVP+) |
| T-BSP-001..003,T-RTOS-001..003,T-RTOS-005..008 | P0 | required(MVP+) |
| T-RTOS-004 | P1 | required(MVP+) |
| T-USB-001,T-USB-001A,T-USB-001B,T-USB-002..010 | P0 | required(MVP+) |
| T-CAN-001,T-CAN-003..004,T-CAN-006..008,T-CAN-011..015 | P0 | required(MVP+) |
| T-CAN-002,T-CAN-005,T-CAN-009 | P0 | required(Beta+)；002/005 may run advisory in MVP |
| T-CAN-010 | P0 | conditional(Beta+,CAN_FD) |
| T-PROTO-001..012 | P0 | required(MVP+) |
| T-E2E-001..004,T-E2E-006..009 | P0 | required(MVP+) |
| T-E2E-005 | P0 | required(Beta+) |
| T-SD-001..010 | P1 | conditional(1.0,STORAGE) |
| T-FW-001..003 | P0 | required(Beta+) |
| T-FW-004..007,T-FW-009..010,T-FW-012..013 | P0 | required(MVP+) |
| T-FW-011 | P0 | required(Beta+) |
| T-FW-008 | P1 | required(Beta+) |
| T-HOST-001..004 | P0 | required(MVP+) |
| T-HOST-005 | P1 | required(Beta+) |
| T-GUI-001..006 | P1 | required(1.0)；Beta recommended/non-blocking |
| T-UPD-001..005 | P1 | conditional(1.0,UPDATE) |
| T-REL-001..004 | P0 | required(MVP+) |

## 1. Test levels

| Level | 范围 | 不能证明 |
|---|---|---|
| Host unit | codec、ring、filter、DBC、capture、状态机 | MCU ABI、ISR、DMA、时序 |
| Host integration | USB abstraction、fake/recorded backend、CLI/GUI | 真实 USB controller |
| Target unit | parser、queue、service 状态机 | 外部收发器/USB host |
| Target peripheral | clock、UART、USB loop、MCAN loop、SPI/SD | 完整端到端 |
| HIL | USB + CAN adapter + board + UART/probe | 所有客户 PC/线束 |
| Soak/fault | 长时、拔插、bus-off、backpressure、断电 | 未覆盖的环境/EMC |

## 2. Evidence contract

每次 target/HIL 测试记录：

- requirement/test ID；
- source revision 或 source archive checksum；
- firmware ELF/BIN checksum；
- SDK/toolchain/CMake/OpenOCD/J-Link 版本；
- board revision/serial、probe serial、CAN adapter/channel；
- bitrate/sample point/FD settings、termination 和供电；
- exact command、timeout、repetition；
- UART/USB/CAN 原始日志；
- pass/fail/skip、失败分类、cleanup 状态。

重试不能覆盖第一次失败；报告 attempts 和 flakiness。

## 3. Phase gates

### Gate A — Build and debug

- `T-DEV-001` clean Debug build；
- `T-DEV-002` clean Release build；
- `T-DEV-003` compile_commands 可被 clangd/C++ 扩展读取；
- `T-DEV-004` ELF/BIN/MAP/size/checksum 生成；
- `T-DEV-005` GDB stop-at-main、breakpoint、step、reset；
- `T-DEV-006` 三平台 setup 文档 dry run。

**Pass**：全部必需测试通过；任何绝对个人路径进入共享配置则失败。

### Gate B — Board/RTOS

- `T-BSP-001` UART banner/version/reset cause；
- `T-BSP-002` LED/timer frequency；
- `T-BSP-003` CPU/AHB/USB/CAN0/CAN2/SPI2 clock measurement；
- `T-RTOS-001` task/queue/timer；
- `T-RTOS-002` assert/stack overflow/malloc failed hooks；
- `T-RTOS-003` 24 h heartbeat；
- `T-RTOS-004` task stack watermark。
- `T-RTOS-005` IRQ priority 与 ISR-safe API contract；
- `T-RTOS-006` runtime allocation freeze（启动完成后 allocation count 不变）；
- `T-RTOS-007` 32-bit timer rollover / torn-read 64-bit timestamp；
- `T-RTOS-008` 逐 task watchdog voter stall 与缺失 voter 诊断。

**Pass**：0 unexpected reset/assert，task stack 余量达门槛；IRQ/ISR API、
runtime allocation freeze、timestamp rollover/torn-read、watchdog voter stall
四项合同全部通过。

### Gate C — USB

- `T-USB-001` descriptor and capability validation；
- `T-USB-001A` HS enumeration、device qualifier/other-speed 与 FS fallback
  descriptor consistency；
- `T-USB-001B` composite layout：Interface 0 vendor bulk、CDC IAD Interfaces
  1–2（可选）、DFU Runtime（仅 UPDATE claim）；覆盖 vendor-only、
  vendor+CDC、vendor+DFU、vendor+CDC+DFU 四种构建。interface number 按实际
  descriptor 连续分配：CDC 启用时 DFU 为 3，CDC 关闭时 DFU 为 1；
  `bNumInterfaces`、IAD、endpoint 和 Windows driver binding 必须匹配且互不抢占；
- `T-USB-002` Windows WinUSB enumerate/open；
- `T-USB-003` Linux enumerate/open + permissions；
- `T-USB-004` macOS enumerate/open；
- `T-USB-005` transfer fragmentation/coalescing；
- `T-USB-006` 10 GiB pseudo-random loopback；
- `T-USB-007` 100 disconnect/reconnect；
- `T-USB-008` host stops reading / resumes；
- `T-USB-009` malformed messages；
- `T-USB-010` endpoint stall/reset。

**Pass**：内容错误=0、deadlock=0、unbounded allocation=0，所有 loss 可计数。

### Gate D — CAN

先 listen-only，主动 TX 仅在 safety preflight 允许的 ID/payload/rate 内。

- `T-CAN-001` MCAN0 internal loopback；
- `T-CAN-002` MCAN2 internal loopback；
- `T-CAN-003` nominal bitrate/sample point；
- `T-CAN-004` standard/extended/RTR；
- `T-CAN-005` filter hit/miss；
- `T-CAN-006` timestamp monotonicity/resolution；
- `T-CAN-007` TX event/timeout/cancel；
- `T-CAN-008` error passive/bus-off/recovery；
- `T-CAN-009` dual-channel full load 30 min；
- `T-CAN-010` CAN-FD/BRS/64 B（capability 支持时）；
- `T-CAN-011` cable/termination/bitrate mismatch diagnosis。
- `T-CAN-012` power/reset 后默认 listen-only、TX disarmed；
- `T-CAN-013` TX arm expiry/session reset/disconnect 清除 immediate TX queue；
  若未来 capability-gated v1.1 schedule 存在则同时取消，v1.0 无周期 TX；
- `T-CAN-014` firmware 拒绝越界 ID/DLC/flags/rate/bus-load；
- `T-CAN-015` bus-off 只执行人工或有界恢复，不无限自动 TX。

**Pass**：外部分析仪与设备记录一致；无 silent drop；错误计数和状态转换一致。

### Gate E — Protocol

- `T-PROTO-001` C ↔ host golden vectors；
- `T-PROTO-002` incompatible major；
- `T-PROTO-003` unknown minor/type/flag；
- `T-PROTO-004` length/count integer boundaries；
- `T-PROTO-005` CRC and resynchronization；
- `T-PROTO-006` request sequence/timeout/cancel、GET_SESSION_STATE、arm epoch/CAS；
- `T-PROTO-007` event/batch/channel sequence gaps 与 DATA_LOSS domain/wrap 对账；
- `T-PROTO-008` capability-driven feature gating；
- `T-PROTO-009` fuzz/property corpus；
- `T-PROTO-010` prior minor compatibility；
- `T-PROTO-011` old-host/new-fw 与 new-host/old-fw pairing；
- `T-PROTO-012` Bulk IN response reserve、调度优先级和反饥饿。

**Pass**：100% golden vector；malformed input 不越界、不挂死；稳定 status。

### Gate F — End-to-end MVP

- `T-E2E-001` enumerate → hello → capability；
- `T-E2E-002` configure CAN → capture；
- `T-E2E-003` authorized TX → TX_RESULT → external receive；
- `T-E2E-004` `BP-LATENCY-v1` over frozen `BP-CAN-MVP-v1` input；
- `T-E2E-005` `BP-CAN-BETA-v1` frozen supported aggregate profile；
- `T-E2E-006` host backpressure/drop event；
- `T-E2E-007` USB disconnect during CAN load；
- `T-E2E-008` CLI machine-readable output/exit code；
- `T-E2E-009` USB disconnect + CAN bus-off + command flood 组合故障。

**Pass**：

- `BP-LATENCY-v1` p95 device RX timestamp → CLI receive ≤ 5 ms；
- `BP-CAN-MVP-v1`、30 min、normal supported profile device drop=0；
- 故障场景恢复或进入可诊断安全状态。

### Gate G — Storage

- `T-SD-001` init/card detect；
- `T-SD-002` sustained throughput ≥ target stream × 2；
- `T-SD-003` full card；
- `T-SD-004` remove during write；
- `T-SD-005` power loss at every commit phase；
- `T-SD-006` scan/recover committed blocks；
- `T-SD-007` storage disabled does not affect CAN/USB。
- `T-SD-008` STORAGE protocol addendum golden vectors + host codec；
- `T-SD-009` host start/stop/list/read/delete E2E and idempotency；
- `T-SD-010` power-loss recovery 后 host readback 与 CRC/sequence 对账。

**Pass**：最多损失一个未提交 block，已提交 block CRC/sequence 可恢复。

### Gate H — Full firmware reliability

- `T-FW-001` dual CAN + USB + UART + optional SD 72 h；
- `T-FW-002` 1000 USB reconnect；
- `T-FW-003` 100 bus-off injections/channel；
- `T-FW-004` command flood/rate limit；
- `T-FW-005` queue/pool exhaustion；
- `T-FW-006` watchdog recovery；
- `T-FW-007` configuration corruption/factory reset；
- `T-FW-008` map/RAM/stack budget；
- `T-FW-009` static analysis and warning gate；
- `T-FW-010` cancel 与 TX complete 竞态，每个 tag 恰一 final result；
- `T-FW-011` 双通道 timestamp/order 与 event sequence gap；
- `T-FW-012` power cycle/config CRC failure 回到安全态；
- `T-FW-013` HIL cleanup 证明 listen-only、TX queue/schedule 为零。

**Pass**：0 unexplained reset/deadlock/silent loss；资源耗尽均有稳定错误和计数。

### Gate I — Host CLI/GUI

- `T-HOST-001` Windows unit/integration/package；
- `T-HOST-002` Linux unit/integration/package；
- `T-HOST-003` macOS unit/integration/package；
- `T-HOST-004` hotplug/session recovery；
- `T-HOST-005` 72 h capture memory plateau；
- `T-GUI-001` 20k frame/s table virtualization；
- `T-GUI-002` filter/DBC/plot correctness；
- `T-GUI-003` render p95 < 33 ms；
- `T-GUI-004` pause view does not pause capture；
- `T-GUI-005` import/export round trip；
- `T-GUI-006` corrupted workspace recovery。

**Pass**：三平台相同 protocol suite；无持续线性内存增长；UI 和 capture loss 分离。

### Gate J — Update/release

- `T-UPD-001` valid image；
- `T-UPD-002` wrong board/version；
- `T-UPD-003` corrupt/truncated image；
- `T-UPD-004` power loss at each update phase；
- `T-UPD-005` rollback/recovery；
- `T-REL-001` version/capability compatibility matrix；
- `T-REL-002` 两个独立 clean environments，分别输出：
  1) raw artifact SHA-256/byte-equality；
  2) unsigned payload file/content/metadata equality 与 payload digest；
  3) normalized JSONL manifest digest（canonical path/type/mode/symlink target/size/
     content SHA-256；file/dir/symlink null/hash、NFC UTF-8 `/` path、禁止
     absolute/drive/empty/dot/dotdot/backslash/NUL/trailing slash、碰撞拒绝、
     byte-order 排序、不 follow/逃逸 symlink、portable mode 规则分别验证）；
  4) signed artifact 绑定的 unsigned digest 与 chain/subject/algorithm/timestamp/
     validity 验证；scope 未声明签名时输出 `NOT_PRODUCED-BY-SCOPE` + claim manifest，
     不得写普通 SKIP 或 signed claim；
- `T-REL-003` **host package** clean install/host-package upgrade/uninstall；
- `T-REL-004` diagnostics bundle。

**Pass**：发布工件和证据完整；仅当 claim manifest 声明 `UPDATE` 时，额外要求
设备不会因单次失败升级永久不可用并通过 `T-UPD-001..005`。

## 4. Performance measurements

统一记录：

- CAN frames/s、payload bytes/s；
- USB transfer size/queue depth；
- MCU ring high-watermark、drop；
- ISR → USB submit、USB receive、CLI ingest、GUI render timestamps；
- p50/p95/p99 latency；
- CPU load、task stack、heap/pool；
- host RSS、queue depth、render FPS；
- reference host CPU/OS/USB controller。

阈值不是脱离环境的宣传数据；每个结果必须绑定 reference setup。

### 4.1 Normative benchmark method

使用 PRD §8.1 的 versioned profiles。每份性能报告必须额外记录：

- Classic/FD、DLC/payload distribution、standard/extended ratio、channel split、
  bus utilization、USB FS/HS、transfer/batch/queue；
- reference host CPU/OS/USB controller，固件/host checksum；
- warm-up、样本数、采样窗口、percentile 算法；
- 测试前后及每 60 s 采集至少 20 个 PING，以最低 RTT quartile 拟合
  `host_time = offset + drift × device_tick`；报告 RTT p95、drift ppm、fit residual
  p95 和 device tick 量化误差。若 residual/量化总预算超过 latency target 的
  20%，测试无效；
- normal profile 与 overload profile 分开：normal 必须 zero drop；overload 必须
  通过 device counter、DATA_LOSS、event gap 和 host metadata 精确对账；
- “内存稳态”在 warm-up 后固定窗口判定：device pool/queue high-watermark 不再增长，
  host RSS 后半窗口 slope 不超过 profile 阈值。

## 5. Fault injection matrix

| Fault | Expected result |
|---|---|
| USB cable pull | session ends；CAN path不死锁；重连新 session |
| Host stops IN reads | bounded buffering；drop/flow event；恢复后可查询 |
| Invalid USB frame | stable error 或丢弃并计数；parser 可继续 |
| CAN bitrate mismatch | error counters 上升；不虚报正常接收 |
| CAN bus-off | event/counter；按配置 manual/auto recovery |
| SD remove/full | storage error；CAN/USB 继续或按策略降级 |
| UART log flood | CAN/USB latency 不越界 |
| Queue/pool exhaustion | NO_RESOURCE/drop counter；无 heap corruption |
| Config CRC failure | defaults/factory reset；诊断可见 |
| Update power loss | rollback/recovery，不执行不完整 image |
| USB disconnect + bus-off + command flood | TX disarm；control response 不饥饿；事件可对账 |
| CAN_TX_CANCEL vs TX complete | SENT 或 CANCELLED 恰一最终结果 |
| Dual-channel simultaneous timestamp | channel/order 规则一致；event sequence 无静默 gap |
| Power cycle after TX armed | listen-only；arm generation 失效；schedule=0 |

## 6. Stop/release rules

- required P0/P1 test failure：禁止进入依赖它的下一产品阶段；
- hardware unavailable：相关测试标记 SKIP，不能用 host mock 宣称硬件通过；
- flaky：未定位前不允许 retry 后转绿；
- 性能未达标：保留原始 trace，进入 `$performance-goal`，不得只调整宣传阈值；
- 升级恢复未通过：关闭发布包中的 update 入口；
- 独立 verifier 未读取证据：Team story 不得 checkpoint complete。
- conditional capability 不支持时仅允许 `SKIP-UNSUPPORTED`，必须附 capability/
  BOM evidence；feature 不得出现在 release claim；
- 每个 release 报告必须由 PRD §8.2 traceability matrix 生成 requirement→test→raw
  evidence 反向链接，存在孤立 requirement 或孤立 P0 test 即失败。
