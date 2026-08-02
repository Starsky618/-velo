# VELO Agent-First / Orchestrator 文档入口

> 当前状态：Phase A `in_progress`；A0/A0C 与 A1.1 已由 Orchestrator `PASS`，A1 parent 保持 `in_progress`。A1.2 为 `ready_to_specify`，但尚未开始且无执行授权；A1.3–A1.5 与 A2–A5 继续 `blocked`。A1.1 只完成文档裁决，不代表生产实现授权。

## 1. 文档角色与权威顺序

发生冲突时按以下顺序处理；不能用较低层文档覆盖较高层事实：

1. 当前用户指令。
2. 当前仓库代码、测试、CI 和真实运行证据。
3. [VELO_Orchestrator_Control_Pack_v1.0.md](VELO_Orchestrator_Control_Pack_v1.0.md) 的执行不变量，以及仓库根目录唯一 live state [`VELO_ORCHESTRATOR_STATE.yaml`](../../VELO_ORCHESTRATOR_STATE.yaml)。
4. [VELO_路线认知基础设施_v0.1.md](source/VELO_路线认知基础设施_v0.1.md)：产品与领域宪法，`authoritative`。
5. [VELO_Agent_First_架构研究与系统设计_v0.1.md](source/VELO_Agent_First_架构研究与系统设计_v0.1.md)：Agent Runtime 架构提案，`proposed_requires_eval`。
6. [VELO_目标领域架构与渐进式迁移蓝图_v1.0.md](source/VELO_目标领域架构与渐进式迁移蓝图_v1.0.md)：长期 World Model 蓝图，`proposed_long_term`。
7. 当前仓库其他文档。
8. 历史文档与聊天记录。

源文档保持随包原文和原始哈希，不在本目录中“顺手统一”彼此措辞。发现冲突时，先以当前代码确定现状，再由 ADR 和 State 记录裁决；历史本地仓库路径不构成事实来源。

## 2. 当前 Phase A、已完成 A0/A0C/A1.1 与待规格化的 A1.2

- Phase A 目标是先建立 ADR、语言中立合同、VeloBench v0 和确定性 Fake Environment，再决定 Runtime 技术栈。
- A0 已完成 Repository Intake、来源文档安置和 [Phase A 文件级实施规格](phase-a-implementation-spec.md)，并经 Orchestrator `PASS`。
- A0C 已完成 clean-branch delivery，通过 PR #35 将经审查的八个文档/State 文件交付到权威主线，并经 Orchestrator `PASS`。
- A1 parent 按五个串行子任务逐项裁决；A1.1 已由 Accepted [ADR-013](../adr/013-为什么区分骑前静态规划与骑中实时导航.md) 编码并以 `PASS / completed` 收口。
- A1.2 仅为 `ready_to_specify`，尚未开始且无执行授权；必须等待新的 Orchestrator Task Packet。A1.3–A1.5 按顺序继续 `blocked`；A2–A5 仍受仓库根 State 阻塞。
- 不可变的 Control Pack v1.0 §11 中“当前唯一下一任务 A0”是 v1.0 创建时的 bootstrap snapshot，不是持续更新的 live state；不得为同步状态而修改 Control Pack 原文或哈希。
- 当前阶段、下一任务和执行授权始终以仓库根 [`VELO_ORCHESTRATOR_STATE.yaml`](../../VELO_ORCHESTRATOR_STATE.yaml) 为准。
- 后续文档提到的 `AgentSession`、`RidePlan`、`Traversal`、`RoadNode`、`RoadEdge`、合同或表，只是候选设计对象，不是当前 schema、migration、API 或实现授权。

## 3. 执行状态边界

唯一可变执行状态位于仓库根目录 [`VELO_ORCHESTRATOR_STATE.yaml`](../../VELO_ORCHESTRATOR_STATE.yaml)。本 README、Control Pack、来源文档和实施规格都不能替代 State，也不能单独推动阶段。

当前没有以下授权：生产 Agent、LangGraph、multi-agent、长期推断 Memory、向量数据库、完整 road graph、真实腾讯/DEM、真实导出、公开发布、生产流量、部署或 A1.2–A1.5 实现。未来设计对象不等于 schema、migration、API 或 runtime 授权；任何实现必须由 Orchestrator 另发单一 Task Packet，并继续遵守 Agent 不直连 ORM/SQL/原始 Provider/公共发布/真实导出的硬边界。

A1.1 的一次性合并授权不构成长期权限；合并后没有新的代码/文档写入、merge 或 deploy 授权。A1.2 必须等待新的 Orchestrator Task Packet；`main` 继续只作为远程权威基线与 PR 目标。
