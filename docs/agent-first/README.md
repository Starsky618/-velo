# VELO Agent-First / Orchestrator 文档入口

> 当前状态：Phase A `in_progress`；A0/A0C/A1.1/A1.2/A1.3/A1.4 已由 Orchestrator `PASS / completed`，A1 parent 保持 `in_progress`。ADR-013–016 已 Accepted；A1.5 已形成 Proposed [ADR-017](../adr/017-为什么旧app-agent必须迁出并保留RQ兼容路径.md)，当前 `in_review`。A2–A5 继续 `blocked`。本轮不授权代码迁移、Runtime、schema、UI、Provider、真实 export 或部署。

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

## 2. 当前 Phase A、已完成 A0/A0C/A1.1/A1.2/A1.3/A1.4 与审查中的 A1.5

- Phase A 目标是先建立 ADR、语言中立合同、VeloBench v0 和确定性 Fake Environment，再决定 Runtime 技术栈。
- A0 已完成 Repository Intake、来源文档安置和 [Phase A 文件级实施规格](phase-a-implementation-spec.md)，并经 Orchestrator `PASS`。
- A0C 已完成 clean-branch delivery，通过 PR #35 将经审查的八个文档/State 文件交付到权威主线，并经 Orchestrator `PASS`。
- A1 parent 按五个串行子任务逐项裁决；A1.1 已由 Accepted [ADR-013](../adr/013-为什么区分骑前静态规划与骑中实时导航.md) 编码并以 `PASS / completed` 收口。
- A1.1 已通过 PR #36 合并为 `main@aa955edc67694fc2cbb628ec3f5caacc80e6d60c`，post-merge CI run `30754762304` 为 `2074 passed / 0 skipped` 且 fresh migration 成功。
- A1.2 已由 Accepted [ADR-014](../adr/014-为什么在线规划采用单一有界主Agent与确定性工作流.md) 编码并以 `PASS / completed` 收口：模型只提议 typed action，代码掌控状态、门禁、校验、持久化、预算和停止；Framework choice 保持 `DEFERRED`。
- A1.2 已通过 PR #37 合并为 `main@2b6538ca01f45593ac8a2d4aecd8f7e8f95265a4`；post-merge CI run `30757438481` 完成 fresh PostGIS migration，结果为 `2074 passed / 0 skipped`。
- A1.3 已由 Accepted [ADR-015](../adr/015-为什么世界事实会话运行与长期记忆必须分离.md) 编码并以 `PASS / completed` 收口：World Fact、User State、Planning Session、Agent Run、Explicit Memory v0、Trace/Eval 分别拥有唯一 Owner，Context 只是一轮模型调用的编译投影。
- A1.3 已通过 PR #38 合并为 `main@dfef5b693dc06461210c2d065564b42333990143`；post-merge CI run `30795837307` 完成 fresh PostGIS migration，结果为 `2074 passed / 0 skipped`。
- A1.4 已由 Accepted [ADR-016](../adr/016-为什么在线Agent的能力审批与副作用必须显式化.md) 编码 deny-by-default Capability、七类 effect scope、五类 approval mode、exact grant、幂等/ledger/replay 与骑友贡献 proposal 边界，并由 Orchestrator 判定 `PASS / completed`；PR #39 获准完成状态收口并 squash merge。
- ADR-016 明确 resource permission、domain validation 与 user approval 是三类独立门禁；`export.prepare` 必须零 artifact，`export.commit` 才能在精确确认后产生外部交付；online Agent 不能发布公共真相或接受 Claim。
- A1.4 已通过 PR #39 squash merge 为 `main@cae88a4d4d1e365baddd394d196444f4ee6d1e8f`；post-merge CI run `30804485326` 完成 fresh PostGIS migration，结果为 `2074 passed / 0 skipped`。
- A1.5 Proposed [ADR-017](../adr/017-为什么旧app-agent必须迁出并保留RQ兼容路径.md) 选定 `app.segment_draft_ai` 为未来赛段草稿实现的唯一 canonical package；`app.agent` 只能作为默认长期保留的 compatibility tombstone，并永久禁止被 Planning Runtime 复用。实际迁移必须在后续独立任务按 M1 双路径兼容、M2 producer 切换、M3 import guard 稳定期执行。
- A1.5 当前仅为 `in_review / READY_FOR_REVIEW / execution unauthorized`；本轮没有移动 `app/agent`、创建 `app/segment_draft_ai`、切换 RQ producer 或改动 worker/queue/API/DB。A2–A5 继续 `blocked`。
- 不可变的 Control Pack v1.0 §11 中“当前唯一下一任务 A0”是 v1.0 创建时的 bootstrap snapshot，不是持续更新的 live state；不得为同步状态而修改 Control Pack 原文或哈希。
- 当前阶段、下一任务和执行授权始终以仓库根 [`VELO_ORCHESTRATOR_STATE.yaml`](../../VELO_ORCHESTRATOR_STATE.yaml) 为准。
- 后续文档提到的 `AgentSession`、`RidePlan`、`Traversal`、`RoadNode`、`RoadEdge`、合同或表，只是候选设计对象，不是当前 schema、migration、API 或实现授权。

## 3. 执行状态边界

唯一可变执行状态位于仓库根目录 [`VELO_ORCHESTRATOR_STATE.yaml`](../../VELO_ORCHESTRATOR_STATE.yaml)。本 README、Control Pack、来源文档和实施规格都不能替代 State，也不能单独推动阶段。

当前没有以下授权：A1.5 代码迁移 M1/M2/M3、生产 Agent、Session/Run/Memory/Context Compiler、Capability Engine、Approval UI、Side-effect Ledger、Contribution、LangGraph、multi-agent、长期推断 Memory、向量数据库、完整 road graph、真实腾讯/DEM、真实导出、公开发布、生产流量、部署或 A2–A5 实现。Proposed ADR-017 只是 namespace/RQ 兼容裁决，不是实施或部署授权；任何实现必须由 Orchestrator 另发单一 Task Packet。

A1.5 Task Packet 只授权专用分支的五文件文档/State 裁决、commit、push 和 Draft PR；不授权 Ready、merge、deploy、代码迁移或开始 A2。交付后 git write、merge 与 deploy 权限为 false，`main` 继续只作为远程权威基线。
