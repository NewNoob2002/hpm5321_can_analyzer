# USB-CAN Protocol v1 — Normative Planning Contract

> 状态：用户产品分级 Review 与 Architect/Critic 复核已完成；实现期须完成 golden-vector 评审  
> 传输：USB High-Speed vendor-specific bulk；CDC ACM 为可选维护控制台；
> DFU Runtime 为可选 bootloader detach interface  
> 字节序：little-endian  
> 设计目标：可流式重同步、可扩展、请求/响应与异步 CAN 数据共存、显式流控

## 1. 传输与会话

- USB bulk 是可靠字节流，不能把一个 USB transfer 当成一个完整协议 message；
- host 连接后首先发送 `HELLO`，设备返回选定版本、session id 和最大 message；
- 每次 USB reset/re-enumeration 创建新 session，旧 request/sequence 全部失效；
- endpoint：
  - Bulk OUT：host → device commands / CAN TX；
  - Bulk IN：device → host responses / events / CAN RX batch；
- 如果 endpoint 资源允许，可把 event/data 拆分；v1 不依赖多 IN endpoint。

## 2. Message envelope

v1 固定 24-byte header：

| Offset | Size | Field | 说明 |
|---:|---:|---|---|
| 0 | 4 | `magic` | 固定 `UCAN` |
| 4 | 1 | `major` | 主版本，不兼容变更递增 |
| 5 | 1 | `minor` | 向后兼容扩展 |
| 6 | 1 | `header_len` | v1 = 24 |
| 7 | 1 | `flags` | 见下列固定 bit assignment |
| 8 | 2 | `message_type` | 命令/响应/事件 |
| 10 | 2 | `status` | response/error 状态 |
| 12 | 4 | `sequence` | request correlation；event 也单调递增 |
| 16 | 4 | `payload_len` | 不含 header/CRC |
| 20 | 4 | `crc32c` | header 中该字段置 0 后连同 payload 计算 |

约束：

- `payload_len <= negotiated_max_message`；
- parser 必须能跨 USB transfer 拼包、拆包并在 magic/length 错误后有界重同步；
- wire codec 必须逐字段编码/解码，禁止直接发送或 `memcpy` 编译器布局的 C struct；
- 未知 `minor` 扩展按 length 跳过；未知 mandatory flag 返回错误；
- `major` 不兼容时只允许 `HELLO`/`GET_DEVICE_INFO`；
- CRC32C 不是为替代 USB CRC，而是保护跨队列、记录和重同步边界。

### 2.1 固定常量与 flags

- `magic` bytes 为 `55 43 41 4E`（ASCII `UCAN`）；
- v1 `major=1`、本规范初始 `minor=0`、`header_len=24`；
- CRC 为 **CRC-32C/Castagnoli**：reflected polynomial `0x82F63B78`
  （normal `0x1EDC6F41`），`init=0xFFFFFFFF`，`refin=true`，
  `refout=true`，`xorout=0xFFFFFFFF`；计算范围为 header（CRC 字段四字节置零）
  后紧接 payload；
- flags：`REQUEST=0x01`、`RESPONSE=0x02`、`EVENT=0x04`、
  `ERROR=0x08`；`0x10..0x80` 保留且 v1 必须为 0。v1 **不定义 `MORE`**，
  大 payload 只能使用规范定义的 batch/chunk message；
- `REQUEST`、`RESPONSE`、`EVENT` 恰好一个为 1；`ERROR` 只可与
  `RESPONSE` 同时出现；非法组合返回 `INVALID_ARGUMENT`，无法安全关联时丢弃并计数。
- request/event header `status` 必须为 0；成功 response 为 `RESPONSE,status=0`
  且无 ERROR；失败 response 必须为 `RESPONSE|ERROR,status!=0`。`ERROR` 与
  `status=0` 或非零 status 无 ERROR 均为 malformed。

### 2.2 Sequence 与 version selection

- host request sequence 是非零 `uint32`，同一 session 内未完成 request 不得复用；
  response 必须原样镜像；
- 所有 device async event（包括 `CAN_RX_BATCH`、`CAN_TX_RESULT`）共享一个
  `device_event_sequence`，从 1 开始，`0xFFFFFFFF` 后 wrap 到 1，跳过 0；
- request 和 event 是两个独立命名空间。`sequence=0` 只用于 host 尚未建立
  session 时无法关联的 fatal protocol response；
- `HELLO` request 宣告 `min_major/max_major/min_minor/max_minor`。设备只在 major
  交集内选择最高 major，再选双方支持的最高 minor；v1 只有 major 1。无交集返回
  `INCOMPATIBLE_VERSION`，并只允许重新 `HELLO` 或 `GET_DEVICE_INFO`；
- minor 未知字段只允许追加到已有 payload 尾部；接收方以 payload length 跳过。

### 2.3 Message type 与 status 数值

| Type | Value | Kind |
|---|---:|---|
| HELLO | `0x0001` | request/response |
| GET_DEVICE_INFO | `0x0002` | request/response |
| GET_CAPABILITIES | `0x0003` | request/response |
| GET_DIAGNOSTICS | `0x0004` | request/response |
| RESET_DIAGNOSTICS | `0x0005` | request/response |
| GET_SESSION_STATE | `0x0006` | request/response |
| CONFIG_CHANNEL | `0x0010` | request/response |
| GET_CHANNEL_CONFIG | `0x0011` | request/response |
| START_CAPTURE | `0x0012` | request/response |
| STOP_CAPTURE | `0x0013` | request/response |
| SET_FILTERS | `0x0014` | request/response |
| CLEAR_FILTERS | `0x0015` | request/response |
| TX_ARM | `0x0020` | request/response |
| TX_DISARM | `0x0021` | request/response |
| CAN_TX | `0x0022` | request/response |
| CAN_TX_CANCEL | `0x0023` | request/response |
| PING | `0x0030` | request/response |
| CAN_RX_BATCH | `0x8001` | event |
| CAN_TX_RESULT | `0x8002` | event |
| CHANNEL_STATE | `0x8003` | event |
| FLOW_CONTROL | `0x8004` | event |
| DATA_LOSS | `0x8005` | event |

| Status | Value | Status | Value |
|---|---:|---|---:|
| OK | `0` | INVALID_ARGUMENT | `1` |
| UNSUPPORTED | `2` | INCOMPATIBLE_VERSION | `3` |
| BAD_STATE | `4` | BUSY | `5` |
| TIMEOUT | `6` | NO_RESOURCE | `7` |
| CHANNEL_OFFLINE | `8` | USB_BACKPRESSURE | `9` |
| CAN_ERROR | `10` | STORAGE_ERROR | `11` |
| CANCELLED | `12` | ALREADY_COMPLETE | `13` |
| INTERNAL_ERROR | `255` | | |

### 2.4 Error payload and CRC check

所有 `ERROR|RESPONSE` 使用：
`u16 detail_code,u16 error_flags,u32 field_offset,u32 expected,u32 actual,
u16 debug_len,u16 reserved`（20 B）+ `debug_len` UTF-8 bytes，`debug_len<=128`。
`field_offset=0xFFFFFFFF` 表示无单一字段；`error_flags`：
`RETRYABLE=0x0001,STATE_QUERY_REQUIRED=0x0002,SESSION_FATAL=0x0004`。

CRC canonical check：ASCII `123456789` 的 CRC-32C 必须是 `0xE3069283`；
golden corpus 还必须包含完整 HELLO frame 的逐字节 CRC。

## 3. 状态码

最小集合：

- `OK`
- `INVALID_ARGUMENT`
- `UNSUPPORTED`
- `INCOMPATIBLE_VERSION`
- `BAD_STATE`
- `BUSY`
- `TIMEOUT`
- `NO_RESOURCE`
- `CHANNEL_OFFLINE`
- `USB_BACKPRESSURE`
- `CAN_ERROR`
- `STORAGE_ERROR`
- `INTERNAL_ERROR`

错误响应必须带：

- 原 request sequence；
- 稳定 status；
- §2.4 固定 error prefix；`detail_code=0` 表示无更细分类；
- 可选 UTF-8 debug text（不得作为机器判断依据）。

## 4. Capability negotiation

会话能力由 `HELLO + GET_DEVICE_INFO + GET_CAPABILITIES` 三条响应共同冻结：

- `HELLO` 返回 protocol major/minor、session 和 negotiated feature；
- `GET_DEVICE_INFO` 返回 firmware semantic version/build id、board id、serial；
- `GET_CAPABILITIES` 返回：
- CAN channel count 和每通道：
  - Classic CAN / CAN-FD；
  - supported nominal/data bitrates 或 bit timing 范围；
  - standard/extended/filter/error/timestamp；
- timestamp tick frequency、resolution、boot epoch；
- max message、max RX batch、TX queue depth；
- USB transport mode；
- storage/DFU/CDC support；
- feature bitset、queue/replay/outstanding limit 和 arm timeout 范围。

Host 不得通过产品型号猜测 capability。

## 5. Control messages

### Required for MVP

- `HELLO`
- `GET_DEVICE_INFO`
- `GET_CAPABILITIES`
- `GET_DIAGNOSTICS`
- `RESET_DIAGNOSTICS`
- `GET_SESSION_STATE`
- `CONFIG_CHANNEL`
- `GET_CHANNEL_CONFIG`
- `START_CAPTURE`
- `STOP_CAPTURE`
- `CAN_TX`
- `CAN_TX_CANCEL`
- `TX_ARM`
- `TX_DISARM`
- `PING`

### Required for Beta

- `SET_FILTERS`
- `CLEAR_FILTERS`

### Future capability-gated extensions（不属于 v1.0/MVP/Beta）

- periodic TX schedule；
- device configuration save/reset；
- SD capture start/stop/list/read/delete；
- time synchronization samples；
- enter bootloader / firmware update；
- diagnostic log snapshot。

`STORAGE` 仅可由独立协议 addendum 分配消息号并冻结 start/stop/list/read/delete
payload、幂等性、恢复和 golden vectors；addendum 与 host E2E 未通过时
`global_features.STORAGE` 必须为 0。v1.1 `PERIODIC_TX` 同样不属于本次 v1.0
consensus scope，必须经过独立 addendum、测试分类和 release gate 后才可置位。

所有修改状态的命令必须：

- 有 request sequence；
- 明确幂等性；
- 返回 applied configuration/generation；
- 在 timeout 后允许 host 查询真实状态，而不是盲目重试。

### 5.1 Required payload schemas

所有 offset 从 payload 0 开始、little-endian；`u8/u16/u32/u64` 均为无符号。
response 的 header `status` 是机器结果；成功 response payload 如下：

| Message | Request payload | Success response |
|---|---|---|
| HELLO | `u8 min_major,u8 max_major,u8 min_minor,u8 max_minor,u32 host_max_message,u32 host_features`（12 B） | `u8 major,u8 minor,u16 reserved=0,u32 session_id,u32 max_message,u32 device_features`（16 B） |
| GET_DEVICE_INFO | empty | `u16 fw_semver_len,u16 build_id_len,u16 board_id_len,u16 serial_len` + four UTF-8 byte strings；每段 ≤64 B |
| GET_CAPABILITIES | empty | 60 B fixed header + `channel_count` × 24 B channel record（如下） |
| GET/RESET_DIAGNOSTICS | RESET: `u32 mask` | 40 B global diagnostics + `channel_count` × 52 B channel diagnostics |
| GET_SESSION_STATE | empty | 28 B fixed state + `channel_count` × 12 B filter-state record（如下） |
| CONFIG_CHANNEL | `u8 channel,u8 mode,u16 flags,u32 nominal_bps,u32 data_bps,u16 sample_permille,u16 reserved,u32 expected_generation`（20 B） | same fields with applied generation |
| GET_CHANNEL_CONFIG | `u8 channel,u8 reserved[3]` | CONFIG_CHANNEL applied schema |
| START/STOP_CAPTURE | `u32 expected_generation,u32 flags` | `u32 applied_generation,u32 state` |
| SET_FILTERS | `u8 channel,u8 count,u16 flags,u32 expected_generation` + `count` × `{u32 id,u32 mask,u16 flags,u16 reserved}`；`count<=cap` | `u32 applied_generation,u16 applied_count,u16 reserved` |
| CLEAR_FILTERS | `u8 channel,u8 reserved[3],u32 expected_generation` | `u32 applied_generation` |
| TX_ARM | `u32 expected_config_generation,u32 timeout_ms,u32 max_frames_per_s,u16 max_bus_load_permille,u16 rule_count` + `rule_count` × 16 B rule | `u32 applied_config_generation,u32 arm_epoch,u64 expiry_tick` |
| TX_DISARM | `u32 expected_config_generation,u32 arm_epoch,u32 reason,u32 reserved` | `u32 applied_config_generation,u32 new_arm_epoch,u32 cancelled_count,u32 reserved` |
| CAN_TX | fixed prefix `u8 channel,u8 dlc,u16 can_flags,u32 id,u32 arm_epoch,u32 client_tag,u64 deadline_tick,u8 payload_len,u8 reserved[3]` + 0..64 data | `u32 client_tag,u32 queue_generation,u16 tx_state,u16 final_result,u64 final_tick,u32 can_error`（24 B ledger snapshot） |
| CAN_TX_CANCEL | `u32 arm_epoch,u32 client_tag` | `u32 client_tag,u32 cancel_state` |
| PING | `u64 host_send_ns,u32 sample_id,u32 reserved` | `u64 host_send_ns,u64 device_rx_tick,u64 device_tx_tick,u32 sample_id,u32 reserved` |

`mode`: `0=DISABLED,1=LISTEN_ONLY,2=CLASSIC,3=FD`；`usb_mode`：
`1=FS,2=HS`。所有 reserved 字段发送为 0、接收必须为 0。

Numeric registries：

- CONFIG flags：`AUTO_RECOVER_BOUNDED=0x0001,TIMESTAMP_ENABLE=0x0002`；
- capture flags：`RX=0x0001,ERROR=0x0002,TX_RESULT=0x0004`；
- capture state：`STOPPED=0,STARTED=1`；
- filter flags：`EXT_ONLY=0x0001,RTR_ONLY=0x0002,INVERT=0x0004`；
- diagnostic mask：`USB=0x00000001,CAN0=0x00000002,CAN2=0x00000004,
  STORAGE=0x00000008,RTOS=0x00000010,ALL=0x0000001F`；
- disarm reason：`HOST=1,EXPIRY=2,USB_RESET=3,WATCHDOG=4,
  CONFIG_FAILURE=5,BUS_OFF=6`；
- cancel state：`CANCELLED=1,ALREADY_COMPLETE=2,NOT_FOUND=3`；
- channel state：`DISABLED=0,LISTEN_ONLY=1,ACTIVE=2,ERROR_PASSIVE=3,
  BUS_OFF=4`；channel reason 使用 disarm values，并增加 `CONFIG_APPLIED=16`；
- loss source：`CAN_RING=1,USB_DATA_QUEUE=2,STORAGE_QUEUE=3`；
  `USB_EVENT_QUEUE=4`；
  loss reason：`OVERFLOW=1,ADMISSION=2,ENDPOINT_STALL=3,
  STORAGE_UNAVAILABLE=4`。
- CAN flags 共用：`EXT=0x0001,RTR=0x0002,FD=0x0004,BRS=0x0008,
  ESI=0x0010,ERROR_FRAME=0x0020`；CAN_TX 只允许前四项，ESI/ERROR_FRAME 必须为 0；
- batch flags：`DROP_SNAPSHOT_CHANGED=0x0001`；其余为 0；
- `filter_hit=0xFF` 表示未命中过滤器，否则为 0..`max_filters-1`；
- `rx_status`：`OK=0,ERROR_WARNING=1,ERROR_PASSIVE=2,BUS_OFF_SNAPSHOT=3`；
- `can_error` packed u32：bits 0..7=`TEC`，8..15=`REC`，
  bit16=`WARNING`，bit17=`PASSIVE`，bit18=`BUS_OFF`，其余为 0。

未列 flag/reason/mask 必须拒绝为 `INVALID_ARGUMENT` 或 `UNSUPPORTED`。

`GET_CAPABILITIES` fixed header 为 60 B：
`u32 cap_generation,u32 max_message,u32 max_rx_batch,u32 tx_depth,u32 tick_hz,
u32 tick_resolution_ns,u64 boot_epoch,u16 outstanding_limit,u16 response_capacity,
u16 event_capacity,u16 data_capacity,u16 arm_timeout_min_ms,u16 arm_timeout_max_ms,
u8 channel_count,u8 usb_mode,u16 global_features,u16 replay_cache_entries,
u16 tx_result_cache_entries,u32 replay_retention_ms,u32 tag_reuse_guard_ms`。
`boot_epoch` 是每次 boot 随机或持久递增的非零身份，不是 wall clock。
`global_features`：`CDC=0x0001,STORAGE=0x0002,DFU=0x0004,
SD_FALLBACK=0x0010`；`0x0008` 为 v1.1 periodic-TX addendum 保留，v1.0 必须为 0。
HELLO 的 `host_features/device_features`
使用同一 registry，device response 返回双方交集。

每个 24 B channel record：
`u8 channel,u8 mode_mask,u16 feature_bits,u32 nominal_min,u32 nominal_max,
u32 data_min,u32 data_max,u16 max_filters,u16 reserved`。channel `feature_bits`：
`CLASSIC=0x0001,FD=0x0002,BRS=0x0004,STD_ID=0x0008,EXT_ID=0x0010,
HW_TIMESTAMP=0x0020,ERROR_EVENT=0x0040`。未列 bit 为 0。
`mode_mask`：`DISABLED=0x01,LISTEN_ONLY=0x02,CLASSIC=0x04,FD=0x08`。

40 B global diagnostics：
`u32 generation,u32 session_id,u32 response_depth,u32 event_depth,u32 data_depth,
u32 pool_high_water,u64 usb_rx_bytes,u64 usb_tx_bytes`。每通道 52 B：
`u8 channel,u8 state,u16 reserved,u32 rx_depth,u32 tx_depth,u64 rx_frames,
u64 tx_frames,u64 filtered,u64 dropped,u32 bus_off_count,u32 error_count`。

16 B TX arm rule：
`u8 channel,u8 allowed_flag_mask,u16 reserved,u32 id,u32 id_mask,
u32 max_frames_per_s`。`rule_count<=16`，`max_bus_load_permille<=1000`，
`timeout_ms` 必须在 capability 给出的 `[100,60000]` 范围。

`GET_SESSION_STATE` 28 B fixed state：
`u32 config_generation,u32 capture_generation,u8 capture_state,u8 tx_armed,
u16 reserved,u32 arm_epoch,u64 arm_expiry_tick,u32 aggregate_max_frames_per_s`。
每通道 12 B filter-state record：
`u8 channel,u8 reserved[3],u32 filter_generation,u32 filter_crc32c`。
`filter_generation` 是该通道 filters 最后变更时的 `config_generation`；
`filter_crc32c` 对 canonical little-endian filter records 计算，空集合也有固定 CRC。
`tx_armed=0` 时 `arm_expiry_tick=0`，但 `arm_epoch` 保留最近一次非零 epoch。

CAN_TX response `tx_state`：`PENDING=1,FINAL=2`。PENDING 时
`final_result/final_tick/can_error=0`；FINAL 时 `final_result` 使用
CAN_TX_RESULT enum。首次 accepted response 通常为 PENDING；相同 CAN_TX bytes
重放必须绕过普通 response-cache snapshot，读取 result ledger 并返回最新
PENDING/FINAL 状态，不产生第二个 TX 副作用或第二个语义结果。

### 5.2 幂等性、timeout、cancel 与 late result

| Command class | Idempotency |
|---|---|
| GET/PING | 相同输入可安全重试 |
| CONFIG/START/STOP/FILTER | 以 `expected_config_generation` compare-and-set；重复已应用 generation 返回当前 state，不重复副作用 |
| TX_ARM/DISARM | 同时以 `expected_config_generation` 做 CAS；成功推进 config generation；独立 `arm_epoch` 每次 arm/disarm 推进并绑定 CAN_TX |
| RESET_DIAGNOSTICS | 非幂等；response 丢失后只能 GET，不得盲重试 |
| CAN_TX | `session_id + arm_epoch + client_tag` 去重；重复从 result ledger 返回当前 PENDING/FINAL snapshot |
| CAN_TX_CANCEL | 幂等；重复返回 CANCELLED 或 ALREADY_COMPLETE |

- host timeout 不等于 device cancel；host 必须先查询状态或发送显式 cancel；
- 每个 accepted CAN_TX 在接受前必须原子预留一个静态 result-ledger slot；
  无 slot 则同步 `NO_RESOURCE` 且不入队。slot 至少保留到 final result 后
  `tag_reuse_guard_ms` 结束；
- cancel 与 hardware TX complete 竞态由唯一 MCAN owner 串行化。先观察到 completion
  则最终 `CAN_TX_RESULT=SENT`，否则 `CANCELLED`；每个 client tag 恰好一个最终 event；
- late response/result 仍带原 sequence/tag；host 若已关闭 request，记录 late event，
  不得把它关联到复用后的 sequence；
- session reset 清除 request 去重表、arm 和 pending queue。
- 所有 configuration/capture/filter/TX arm 状态修改共享 session-local `u32
  config_generation`；0 保留，`0xFFFFFFFF` 后 wrap 到 1。CAS 只判断相等，
  不用大小关系跨 wrap；
- `capture_generation` 是 capture state 最后变化时的 `config_generation`；
  capture state 数值见 §5.1；
- `arm_epoch` 是独立 session-local 非零 `u32` epoch；session 建立时初始化为 1，
  每次成功 TX_ARM/TX_DISARM 都 +1 并按 wrap 跳过 0。是否 armed 只由显式
  `tx_armed` 表示，0 不再兼作 disarmed。TX_DISARM response 返回推进后的 epoch；
- `cap_generation` 每次 boot 从 1 开始，只有 runtime capability 集合改变时推进；
  diagnostics `generation` 每次 RESET_DIAGNOSTICS 成功时推进；`queue_generation`
  每次 accepted/cancel/completion/disarm flush 后推进。上述 generation 均为
  session-local u32，0 保留，wrap 跳过 0；
- CAN_TX `deadline_tick=0` 表示 immediate；非零表示 device monotonic absolute
  deadline，接收时已过期则同步返回 `TIMEOUT` 且不入队；
- device 保留最近 `replay_cache_entries` 个 completed request，至少
  `replay_retention_ms`。同 sequence + byte-identical request 返回缓存 response；
  同 sequence + 不同 bytes 返回 `BAD_STATE` 且无副作用；若 cache 已淘汰则返回
  `BAD_STATE|STATE_QUERY_REQUIRED`；
- host request sequence 从随机非零起点逐次 +1，`0xFFFFFFFF` 后 wrap 到 1；
  同一 sequence 在 `replay_retention_ms` 内不得用于不同 request。cache 全部仍在
  retention 且无空位时，device 必须在执行前以 `BUSY|RETRYABLE` 拒绝新的
  side-effect request；read-only GET/PING 可执行但可不缓存；
- response cache 淘汰或 command timeout 后，host 使用 `GET_SESSION_STATE` 查询
  config/capture/filter/arm 真实状态；GET_CHANNEL_CONFIG 和 GET_DIAGNOSTICS
  分别补充 channel 与 counter 状态，不允许通过盲重试推断；
- `client_tag` 从 accepted 到 final result 后 `tag_reuse_guard_ms` 内不得复用。
  同 tag + 相同 CAN_TX bytes 返回原结果；同 tag + 不同 bytes 返回
  `INVALID_ARGUMENT`。缓存达到 `tx_result_cache_entries` 时拒绝新 TX，不淘汰仍在
  guard 内的结果。

### 5.3 Required event payloads

- `CAN_TX_RESULT`：`u32 client_tag,u32 arm_epoch,u16 result,u16 reserved,
  u64 hardware_tick,u32 can_error,u32 queue_generation`（28 B）；result：
  `SENT=1,CANCELLED=2,TIMEOUT=3,BUS_ERROR=4,DISARMED=5`。
- `CHANNEL_STATE`：`u8 channel,u8 state,u16 reason,u32 config_generation,
  u32 tx_error,u32 rx_error,u64 device_tick`（24 B）。
- `FLOW_CONTROL`：`u32 response_depth,u32 event_depth,u32 data_depth,
  u32 pool_high_water,u64 device_tick`（24 B）。
- `DATA_LOSS`：`u8 channel,u8 source,u8 sequence_domain,u8 loss_flags,u16 reason,
  u16 reserved,u32 config_generation,u32 first_dropped_sequence,
  u32 last_dropped_sequence,u32 reserved2,u64 dropped_count,u64 device_tick`（40 B）。
  `sequence_domain`：`EVENT=1,CHANNEL=2`；`loss_flags` v1 必须为 0。

## 6. CAN RX batch

v1 采用**混合通道 batch**；batch header 不再包含 channel：

- `u16 record_count,u16 flags,u32 record_bytes,u64 base_timestamp,
  u64 device_drop_total,u32 config_generation,u32 reserved`（32 B）。

每条 record：

- fixed prefix `u32 delta_tick,u32 arbitration_id,u32 channel_sequence,u16 flags,
  u8 channel,u8 dlc,u8 payload_len,u8 filter_hit,u16 rx_status`（20 B）+
  `payload_len` data；
- `delta_tick` 相对 batch base；溢出或不连续时结束当前 batch；
- flags 数值：`EXT=0x0001,RTR=0x0002,FD=0x0004,BRS=0x0008,
  ESI=0x0010,ERROR=0x0020`；其余 bit 为 0。
- DLC mapping：0..8→0..8 B，9→12，10→16，11→20，12→24，13→32，
  14→48，15→64。Classic 必须 DLC≤8 且 `payload_len=DLC`；FD 必须按映射相等；
  RTR 必须 Classic、`payload_len=0` 且不得 FD/BRS；BRS 只可与 FD；TX 禁止 ESI；
  standard ID≤`0x7FF`，EXT ID≤`0x1FFFFFFF`；
- records 紧密排列、无 padding；`record_bytes = Σ(20 + payload_len)`，
  CAN_RX_BATCH payload 总长必须为 `32 + record_bytes`，实际解析 record 数必须等于
  `record_count`，否则整 batch 无效。

规则：

- v1 支持 Classic CAN 和最多 64-byte CAN-FD payload；
- batch 同时受 `max_message`、最大等待时间和最大 record count 约束；
- 低流量不能因等待填满 batch 产生无界延迟；
- device drop counter 的变化必须在下一可用 event/batch 中上报；
- host 必须检测 event/batch sequence gap 并写入 capture metadata。
- 一个 batch 只能包含同一 `config_generation`；generation 变化立即 flush。
  每通道 `channel_sequence` 在 ISR 观察到 frame、尝试写入 CAN ring **之前**分配，
  从 1 单调递增并按 u32 wrap 跳过 0，因此 ring overflow 也能以 CHANNEL domain
  精确表达。mixed-channel merge
  排序为 `(timestamp, channel_id, channel_sequence)`，同 tick 时 channel 小者先；
  host 用 event sequence + channel sequence 检测全局和每通道 gap。

## 7. CAN TX / TX result

`CAN_TX` 支持：

- channel、ID、flags、payload；
- immediate 或 device monotonic deadline；
- client tag；
- 可选 request generation。

设备返回“已入队”不等于“已上总线”。最终通过 `CAN_TX_RESULT` event 返回：

- client tag；
- sent/cancelled/timeout/bus-error/disarmed；
- hardware timestamp（若支持）；
- CAN controller error snapshot。

周期发送不属于 v1.0/MVP/Beta；`0x0024..0x002F` 为未来 v1.1 addendum 保留，
v1.0 device 必须返回 `UNSUPPORTED`。v1.1 必须另行冻结 phase/count/deadline、
状态查询、cancel/complete race、disconnect semantics 和 golden vectors 后才能启用。

### 7.1 Conservative bus-load admission

安全门使用确定性上界，而不是实测平均值：

- Classic raw bits = `47 + (EXT ? 20 : 0) + 8*payload_len`；
- FD nominal raw bits = `35 + (EXT ? 20 : 0)`；
- FD data raw bits = `28 + 8*payload_len + (payload_len<=16 ? 17 : 21)`；
- `stuffed(x)=ceil(5*x/4)+13`；Classic frame time =
  `stuffed(raw)*1e6/nominal_bps`；FD frame time =
  `stuffed(nominal_raw)*1e6/nominal_bps + stuffed(data_raw)*1e6/data_bps`；
- **每个物理 channel 独立**计算并加两倍 retransmission margin：
  `reserved_permille[channel] =
  ceil(2 * Σ(frame_time_us*rate_hz) * 1000 / 1e6)`。

每通道 immediate TX 使用 token bucket：fill=`rule.max_frames_per_s` tokens/s，
capacity=`min(tx_depth,max(1,ceil(fill/10)))`，每帧消耗 1 token；同时将已接受但未
完成 frame 的最坏 frame time 纳入该通道 reserved load。只有每个 channel 的
`reserved_permille <= min(TX_ARM.max_bus_load_permille, product_limit[channel])`
且 token 可用才接受。
TX_ARM 顶层 `max_frames_per_s` 另定义跨所有 channel/rule 的 aggregate token bucket：
fill=`max_frames_per_s`、capacity=`max(1,ceil(fill/10))`；每个 accepted frame 同时
消耗 rule bucket 与 aggregate bucket，任一不足均以 `BUSY|RETRYABLE` 拒绝。
该公式是保守 admission contract，不替代真实 analyzer bus-utilization 测量。

## 8. Backpressure and loss semantics

- 所有 device queue 都是有界的；
- host 不读取时，设备不得阻塞 CAN ISR 或无限分配；
- v1 至少实现：
  - ring high-watermark；
  - dropped frame/message counters；
  - `FLOW_CONTROL`/`DATA_LOSS` event；
  - host 可查询当前 queue depth；
- 禁止 silent drop；
- 如果启用 SD fallback，必须在 capability/状态中明确数据被重定向到哪里。

### 8.1 单 Bulk IN 的 control-plane QoS

- 三个独立 bounded queue：response、critical event、CAN data；容量由 capability
  返回，response capacity 必须 ≥ `max(4, outstanding_limit)`；
- scheduler 使用 priority + weighted round robin：response 优先，但连续发送
  8 个 response 后若 critical event 等待则至少服务 1 个；CAN data 每 16 个
  control/critical message 至少服务 1 batch，除非 endpoint stalled；
- response queue 不得被 CAN batch 占用；response reserve 耗尽时拒绝新 command
  为 `BUSY/NO_RESOURCE`，不得接受后丢失；
- `CAN_TX_RESULT` 使用已预留 result-ledger slot；final result 不得被 counter
  coalescing 丢弃。若 critical queue 暂满，slot 保持 `delivery_pending`，scheduler
  在释放 slot 前重试投递；host 也可用相同 CAN_TX bytes 重放读取 ledger 的 FINAL
  snapshot。每个 accepted tag 只有一个语义 final result；
- `DATA_LOSS`、bus-off、TX disarm 属 critical event；除 TX_RESULT 外，critical
  queue 满时使用各类型持久 pending accumulator，合并 counter snapshot并保留最新
  generation 和首次/末次 sequence。DATA_LOSS notice 自身只有在成功预留 critical
  slot 时才分配 event sequence；预留失败只更新 accumulator，不递归制造新 gap；
- 除上一条 DATA_LOSS 特例外，所有 async event（含 CAN_RX_BATCH）在尝试写入对应
  event/data queue **之前**分配 `device_event_sequence`。USB data/event queue
  丢失使用 EVENT domain；
  CAN ring 丢失使用 CHANNEL domain。STORAGE_QUEUE 丢失使用 CHANNEL domain
  并携带对应 channel；无法归属单通道时 `channel=0xFF` 且不得合并跨通道区间；
- DATA_LOSS 只合并相同 channel/source/reason/domain/config generation 且序列连续
  的区间；u32 wrap 必须拆成两条（末段到 `0xFFFFFFFF`、新段从 1），因此每条
  始终 `first<=last`；
- `dropped_count` 单位由 source 固定：CAN_RING=CAN frames；
  USB_DATA_QUEUE=CAN_RX_BATCH messages（mixed-channel batch 使用
  `channel=0xFF`，frame 数另由 device_drop_total/per-channel counters 对账）；
  USB_EVENT_QUEUE=event messages；STORAGE_QUEUE=capture records。sequence range
  计数与 dropped_count 可因 batch 内 record 数不同而不同，host 必须同时对账；
- normal supported profile 要求 zero drop；overload profile 允许且只允许能通过
  device counters、event sequence 和 host capture metadata 完整对账的显式 drop。

## 9. Timestamp

- 设备提供 64-bit 单调 tick/微秒时间；
- `GET_CAPABILITIES` 返回频率与分辨率；
- boot/reset 产生新的 session/epoch；
- host 使用多次 ping 样本估算 offset/RTT，不把 USB 到达时间当 CAN 接收时间；
- 多设备绝对同步不属于 v1 保证，后续可增加硬件/协议同步。

## 10. Compatibility policy

- Major：wire incompatibility；
- Minor：只新增可忽略字段/message/capability；
- length-delimited payload 支持旧 host 跳过尾部；
- firmware 在发布后至少保留当前 major 的最近两个 minor；
- golden vectors 按 `protocol/v1/<minor>/` 归档；
- capture 文件记录 protocol、firmware、board、capability snapshot。

## 11. Security and safety boundaries

- USB 被视为本地但不可信输入；所有 length/count/flag/enum 都要验证；
- parser 不动态递归、不基于未验证长度分配大块内存；
- CAN TX 默认关闭；firmware 实现 session-scoped `TX_ARM`，带 generation/expiry；
- firmware（而非仅 HIL/CLI）强制 channel、ID/mask、DLC/flags、bitrate、queue、
  frames/s 和 bus-load 上限；未来 v1.1 schedule 还须强制 periodic count；
- USB reset/disconnect、watchdog、config CRC failure、arm expiry 自动 disarm 并
  清空 immediate TX queue；若未来 capability-gated schedule 存在则同时取消。
  v1.0 无周期 TX；bus-off 默认保持 disarm，禁止无限自动重试；
- HIL/CLI 仍实现更窄的 ID、payload、rate 和 timeout 白名单；
- firmware update 要独立做 image authenticity/integrity 和 rollback 设计；
- debug text 不泄露未初始化内存或地址。

## 12. Required protocol evidence

1. C 与 host-core codec 的 golden vectors；
2. fragmented/coalesced USB transfer parser tests；
3. bad magic/CRC/length/count/flag fuzz corpus；
4. version/capability compatibility matrix；
5. backpressure/drop/sequence-gap HIL；
6. TX accepted vs sent semantics HIL；
7. capture metadata 能复现 device/session/config。
