# VELO Agent-First / Orchestrator 文档入口

> 当前状态：Phase A `in_progress`；唯一当前任务 A0 为 `in_review`。这里安置的是来源文档、执行控制和后续实施规格，不是已上线能力，也不授权修改生产行为。

## 1. 文档角色与权威顺序

发生冲突时按以下顺序处理；不能用较低层文档覆盖较高层事实：

1. 当前用户指令。
2. 当前仓库代码、测试、CI 和真实运行证据。
3. [VELO_Orchestrator_Control_Pack_v1.0.md](VELO_Orchestrator_Control_Pack_v1.0.md) 与仓库根目录唯一状态文件 [`VELO_ORCHESTRATOR_STATE.yaml`](../../VELO_ORCHESTRATOR_STATE.yaml)。
4. [VELO_路线认知基础设施_v0.1.md](source/VELO_路线认知基础设施_v0.1.md)：产品与领域宪法，`authoritative`。
5. [VELO_Agent_First_架构研究与系统设计_v0.1.md](source/VELO_Agent_First_架构研究与系统设计_v0.1.md)：Agent Runtime 架构提案，`proposed_requires_eval`。
6. [VELO_目标领域架构与渐进式迁移蓝图_v1.0.md](source/VELO_目标领域架构与渐进式迁移蓝图_v1.0.md)：长期 World Model 蓝图，`proposed_long_term`。
7. 当前仓库其他文档。
8. 历史文档与聊天记录。

源文档保持随包原文和原始哈希，不在本目录中“顺手统一”彼此措辞。发现冲突时，先以当前代码确定现状，再由 ADR 和 State 记录裁决；历史本地仓库路径不构成事实来源。

## 2. 当前 Phase A 与唯一 A0

- Phase A 目标是先建立 ADR、语言中立合同、VeloBench v0 和确定性 Fake Environment，再决定 Runtime 技术栈。
- 当前唯一允许执行的任务是 A0：仓库事实 intake、来源文档安置和 [Phase A 文件级实施规格](phase-a-implementation-spec.md)。
- A0 只等待 Orchestrator 审查，不能自行判定 `PASS`；A1–A5 均仍受阻塞。
- 后续文档提到的 `AgentSession`、`RidePlan`、`Traversal`、`RoadNode`、`RoadEdge`、合同或表，只是候选设计对象，不是当前 schema、migration、API 或实现授权。

## 3. 执行状态边界

唯一可变执行状态位于仓库根目录 [`VELO_ORCHESTRATOR_STATE.yaml`](../../VELO_ORCHESTRATOR_STATE.yaml)。本 README、Control Pack、来源文档和实施规格都不能替代 State，也不能单独推动阶段。

当前没有以下授权：生产 Agent、长期 Memory、LangGraph、多 Agent、真实腾讯调用、真实导出、生产流量、部署、Git 提交或推送。任何实现必须由 Orchestrator 另发单一 Task Packet，并继续遵守 Agent 不直连 ORM/SQL/原始 Provider/公共发布/真实导出的硬边界。
