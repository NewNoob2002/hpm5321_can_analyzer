# Ralplan Consensus Handoff — HPM5321 USB-CAN Analyzer

```yaml
mode: ralplan
terminal_status: complete
planning_artifacts:
  context: not-versioned (planning input only)
  prd: docs/approved-plan/prd-hpm5321-usb-can-analyzer.md
  test_spec: docs/approved-plan/test-spec-hpm5321-usb-can-analyzer.md
  protocol_spec: docs/approved-plan/usb-can-protocol-v1.md
ralplan_architect_review:
  path: docs/approved-plan/architect-approval.md
  verdict: APPROVE
  sequence: 1
ralplan_critic_review:
  path: docs/approved-plan/critic-approval.md
  verdict: APPROVE
  sequence: 2
ralplan_consensus_gate:
  complete: true
  execution_authorized: true
  approved_order: Architect -> Critic
```

## Approval disposition

用户 Review 已固定 USB HS composite、MVP/Beta/1.0/v1.1 产品分级，并将 GUI
设为 1.0 required。修订后的 Architect → Critic 顺序复核均已批准；规划阶段
完成，后续实现必须由显式执行 lane 接管。

## Required execution follow-ups

1. Phase 1 重新验证或修复 Git history、remote、ignore、version 与 release
   metadata；最新 context 中 “not a git repository” 已是过时证据。
2. 保留 USB 跨平台绑定、外部 CAN 物理层、flash topology 三项未关闭 Gate；
   USB HS 480 Mbps 与 MCAN0/MCAN2 80 MHz 已有工程证据，但正式 Gate 仍需完整 evidence contract；本审批不构成硬件能力证明。
3. 执行 ledger 保留 Architect 的四组验证条件。
4. T-PROTO-007 覆盖 pending DATA_LOSS 的 generation 变化、wrap 与不可合并 key；
   T-REL-002 冻结统一的跨平台恶意路径 corpus。

## Execution lanes

- 默认 durable 路径：`$ultragoal`
- 需要并行分工：`$ultragoal` + `$team`
- 单所有者持续验证仅作显式 fallback：`$ralph`

建议 `executor` 负责实现，`test-engineer` 负责 host/target/HIL 证据，
`verifier` 负责阶段 gate。Team 应按 PRD phase/DAG 分配互不冲突的 ownership，
并在每个 checkpoint 汇总 targeted tests、build、静态分析和硬件证据。
