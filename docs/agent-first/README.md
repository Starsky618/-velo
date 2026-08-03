# VELO Agent-First / Orchestrator 文档入口

> 当前状态：Phase A 与 A2 parent 均为 `in_progress`；A0/A0C/A1.1–A1.5、A2.1 和 A2.2 均已由 Orchestrator 判定 `PASS / completed`。PR #42 已 squash merge 为 `main@2e2f5e227308b9f2244904f2d7fde32c1ce20a87`，post-merge CI run `30838576675` 为 `2312 passed / 0 skipped` 且 fresh PostGIS migration 成功。A2.3 已串行拆为 A2.3a/b/c；A2.3a 首轮 review 为 `REVISE`，R1 合同修订处于 `in_review / pending_orchestrator_re_review`，A2.3b 与 A2.3c 未开始且 blocked。A2.4 与 A3–A5 继续 `blocked`。Agent v0 尚未 freeze；当前不授权代码迁移、Agent Runtime、生产 Context Compiler/reducer、数据库、API、小程序、真实 Provider/export 或部署。

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

## 2. 当前 Phase A、已完成的 A1/A2.1/A2.2 与 A2.3a 审查边界

- Phase A 目标是先建立 ADR、语言中立合同、VeloBench v0 和确定性 Fake Environment，再决定 Runtime 技术栈。
- A0 已完成 Repository Intake、来源文档安置和 [Phase A 文件级实施规格](phase-a-implementation-spec.md)，并经 Orchestrator `PASS`。
- A0C 已完成 clean-branch delivery，通过 PR #35 将经审查的八个文档/State 文件交付到权威主线，并经 Orchestrator `PASS`。
- A1 parent 的五个串行子任务已全部通过，A1 已由 Orchestrator 判定 `completed / PASS`；A1.1 由 Accepted [ADR-013](../adr/013-为什么区分骑前静态规划与骑中实时导航.md) 编码并以 `PASS / completed` 收口。
- A1.1 已通过 PR #36 合并为 `main@aa955edc67694fc2cbb628ec3f5caacc80e6d60c`，post-merge CI run `30754762304` 为 `2074 passed / 0 skipped` 且 fresh migration 成功。
- A1.2 已由 Accepted [ADR-014](../adr/014-为什么在线规划采用单一有界主Agent与确定性工作流.md) 编码并以 `PASS / completed` 收口：模型只提议 typed action，代码掌控状态、门禁、校验、持久化、预算和停止；Framework choice 保持 `DEFERRED`。
- A1.2 已通过 PR #37 合并为 `main@2b6538ca01f45593ac8a2d4aecd8f7e8f95265a4`；post-merge CI run `30757438481` 完成 fresh PostGIS migration，结果为 `2074 passed / 0 skipped`。
- A1.3 已由 Accepted [ADR-015](../adr/015-为什么世界事实会话运行与长期记忆必须分离.md) 编码并以 `PASS / completed` 收口：World Fact、User State、Planning Session、Agent Run、Explicit Memory v0、Trace/Eval 分别拥有唯一 Owner，Context 只是一轮模型调用的编译投影。
- A1.3 已通过 PR #38 合并为 `main@dfef5b693dc06461210c2d065564b42333990143`；post-merge CI run `30795837307` 完成 fresh PostGIS migration，结果为 `2074 passed / 0 skipped`。
- A1.4 已由 Accepted [ADR-016](../adr/016-为什么在线Agent的能力审批与副作用必须显式化.md) 编码 deny-by-default Capability、七类 effect scope、五类 approval mode、exact grant、幂等/ledger/replay 与骑友贡献 proposal 边界，并由 Orchestrator 判定 `PASS / completed`；PR #39 获准完成状态收口并 squash merge。
- ADR-016 明确 resource permission、domain validation 与 user approval 是三类独立门禁；`export.prepare` 必须零 artifact，`export.commit` 才能在精确确认后产生外部交付；online Agent 不能发布公共真相或接受 Claim。
- A1.4 已通过 PR #39 squash merge 为 `main@cae88a4d4d1e365baddd394d196444f4ee6d1e8f`；post-merge CI run `30804485326` 完成 fresh PostGIS migration，结果为 `2074 passed / 0 skipped`。
- A1.5 已由 Accepted [ADR-017](../adr/017-为什么旧app-agent必须迁出并保留RQ兼容路径.md) 编码并以 `PASS / completed` 收口：`app.segment_draft_ai` 是未来赛段草稿实现的唯一 canonical package；`app.agent` 只能作为默认长期保留的 compatibility tombstone，并永久禁止被 Planning Runtime 复用。
- `app/agent` 当前仍未迁移，`app/segment_draft_ai` 仍未创建，M1/M2/M3 均未实施或获授权。实际 M1/M2 不阻塞 A2–A4，但 M1 必须在首个生产 Planning Runtime 或 Phase B live Agent 集成前完成。
- A2 parent 继续 `in_progress`，尚未整体完成。A2.1 已由 Orchestrator 判定 `PASS / completed`，并通过 PR #41 squash merge 为 `main@25169cac110a330c305d5b5f66d74a585277217a`；post-merge CI run `30823721358` 为 `2122 passed / 0 skipped` 且 fresh PostGIS migration 成功。A2.1 只建立 [`contracts/agent_v0`](../../contracts/agent_v0/README.md) 中的 Common definitions、21 个事实／动态 Predicate、`RiderContextPacket`、`WorldFactPacket` 与 `ContextManifest`。正式 Relation 使用独立 relation request，不能重新加入 `route.exit_option`。
- A2.2 已由 Orchestrator 判定 `PASS / completed`，PR #42 获准完成状态收口与 squash merge。它建立 `SessionState`、`AgentRun`、typed `MapEvent`、declarative `MapAction` 与 proposal-only `AgentAction` 五份 Draft 2020-12 schema，以及 clarification/context alignment 和 candidate presentation/user selection 两条 synthetic scenario；R1 固定 created/running lifecycle、resume current Session revision、跨合同 environment/time、可改变 viewport 的 opaque fit-bounds transition，以及由真实 user `plan_confirmed` Event 支撑的 selection provenance。该 PASS 只代表 A2.2 合同通过，不代表 reducer、Runtime、持久化或 Agent v0 freeze 已存在。
- A2.3a 只新增确定性 Control Plane 拥有、deny-by-default 的 8-tool Registry，以及 proposal-only `ToolCall` 与 typed attempt observation `ToolResult`。AgentAction 已由语义错误的 `call_approved_tool` 改为只携带 `tool_call_ref` 的 `propose_tool_call`；模型不能声称批准、执行或副作用。8 个高层工具仅为 `planning.resolve_ride_object`、`planning.retrieve_rider_context`、`planning.retrieve_world_context`、`planning.generate_candidate_plans`、`planning.revise_plan`、`planning.validate_plan`、`planning.compare_plans`、`planning.prepare_export`。
- A2.3a R1 固定 `tool_call_id` 为 immutable request identity；同一请求可有 attempt 1 timeout/disconnect intermediate 与 attempt 2 terminal Result，但最多一个 terminal 且必须最后出现。`RETRY_SAME_CALL` 只是资格而非执行授权；`consumed.tool_calls` 统计 initial attempt 加 deterministic retries，`tool_call_refs` 只统计唯一 proposal。修改 input/tool/capability/Session revision/expected observation 等权威请求字段必须换新 ToolCall ID。
- Registry 不再把“没有 external artifact”误写成“没有 effect”：`planning.generate_candidate_plans` 固定为 `IRREVERSIBLE_EXTERNAL_DISCLOSURE / MINIMIZED_DOMAIN_MEDIATED`，并声明未来 A2.3b 需要 effect reconciliation；`planning.revise_plan` 是可逆 Session artifact，其余六个工具无持久 effect。模型仍只见 opaque refs，Provider disclosure 的 exact identity、ledger 与 runtime reconciliation 未在本轮实现。
- A2.3a 的 candidate scenario 固定为两轮：第一轮 Manifest → proposal → `planning.generate_candidate_plans` → typed `candidate_plan_set` observation；不可绕过的 deterministic validation gate 不是第二个 Agent ToolCall；第二轮真实 Manifest 必须包含随后 `present_valid_candidates` 引用的两个 `ride_plan` revisions，模型不能引用未进入该 turn Context 的 Plan。`planning.revise_plan` 成功也只能返回 `object_type=ride_plan` 的 revision；`planning.prepare_export` 只返回 `export_preview`，零 artifact、零个人/世界写入，不调用真实 export。
- A2.3a 首轮 Orchestrator 结论是 `REVISE`；五组 finding 已在同一 Draft PR 分支应用，当前只能是 `in_review / pending_orchestrator_re_review / applied_waiting_orchestrator_re_review`，不能写成 PASS/completed。A2.3b Approval/SideEffect 与 A2.3c IntentSnapshot/PlanConstraintSet/RidePlanDraft/ValidationResult 均未开始；A2.3c 已记录但未实现的裁决是 opaque intent ref 单独不足、preference 必须经确定性 compiler 转为带来源的 hard/soft/advisory constraint，且 unknown 不能当 pass。
- A2 JSON Schema 完全语言中立；当前 Python pytest 只是既有仓库/CI 的 contract conformance harness，不构成 Python Runtime 选择。Proposed research 中 Agent Control Plane 的优先候选仍是独立 TypeScript Shadow Service，但 Accepted Runtime 语言/框架继续 deferred，必须在第一个 Runtime implementation Task Packet 前正式裁决；现有 Python/FastAPI Deterministic Domain Plane 不重写。
- A2.3 parent 为 `in_progress`；A2.3a 等待 Orchestrator re-review，A2.3b/A2.3c blocked 且 execution unauthorized。A2.4（Trace/Error/Contribution/全量交叉验证与 v0 freeze）及 A3–A5 继续 `blocked`。A2.1–A2.3a 都只是语言中立合同与合成 fixture，不是完整 Agent v0 freeze、生产 Tool Gateway/Context Compiler、数据库 schema、Runtime、API、小程序、真实路线事实或部署。两个 World fixture 只覆盖 `linear_climb` 与 `corridor` 的合同结构；Phase A 仍需至少 10 个版本化 Gold World Package、覆盖至少 6 种 route shape，并由至少 30 个 VeloBench case 消费。
- 不可变的 Control Pack v1.0 §11 中“当前唯一下一任务 A0”是 v1.0 创建时的 bootstrap snapshot，不是持续更新的 live state；不得为同步状态而修改 Control Pack 原文或哈希。
- 当前阶段、下一任务和执行授权始终以仓库根 [`VELO_ORCHESTRATOR_STATE.yaml`](../../VELO_ORCHESTRATOR_STATE.yaml) 为准。
- 后续文档提到的 `AgentSession`、`RidePlan`、`Traversal`、`RoadNode`、`RoadEdge`、合同或表，只是候选设计对象，不是当前 schema、migration、API 或实现授权。

## 3. 执行状态边界

唯一可变执行状态位于仓库根目录 [`VELO_ORCHESTRATOR_STATE.yaml`](../../VELO_ORCHESTRATOR_STATE.yaml)。本 README、Control Pack、来源文档和实施规格都不能替代 State，也不能单独推动阶段。

当前没有以下授权：A1.5 代码迁移 M1/M2/M3、A2.3b、A2.3c、A2.4、生产 Agent、Tool Gateway、Session/Run/Memory/Context Compiler、production reducer、Capability Engine、Approval UI、Side-effect Ledger、Contribution、LangGraph、multi-agent、长期推断 Memory、向量数据库、完整 road graph、真实腾讯/DEM、真实导出、公开发布、生产流量或部署。Accepted ADR-017 只代表 namespace/RQ 兼容迁移边界完成；A2.1 `PASS / completed` 只代表 Context contracts 通过，A2.2 `PASS / completed` 只代表 Session/Run/Map/Action contracts 通过；A2.3a 等待 re-review，三者都不代表 Agent v0 已 freeze，或 Runtime、数据库、API、小程序、Provider 与生产数据已经实现。

A2.2 已由 Orchestrator 判定 `PASS / completed`。当前 R1 Task Packet 只授权 A2.3a allowlist 内合同修订、测试、push 与现有 Draft PR 更新；不授权 merge/deploy，也不授权 A2.3b、A2.3c 或后续任务。A2.3a 交付状态只能是 `in_review / pending_orchestrator_re_review / applied_waiting_orchestrator_re_review`，`main` 继续只作为远程权威基线与 PR target。
