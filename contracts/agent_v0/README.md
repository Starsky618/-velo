# VELO Agent v0 language-neutral contracts

本目录包含 A2.1 Context contracts、A2.2 Session/Run/Map/Action contracts，以及 A2.3a Tool Registry/ToolCall/ToolResult contracts。它们继续固定语言中立、版本化的 shape 与 semantic conformance，不是数据库 schema。仓库现在另有 [`agent_runtime`](../../agent_runtime/README.md) TypeScript Shadow 内核；该实现不把 TypeScript 私有状态偷渡进这些跨语言合同，也不证明生产 Context Compiler、Tool Gateway、数据库或 Provider 已存在。

## 当前包含

- Common definitions
- Predicate Registry
- RiderCapabilitySnapshot
- RiderContextPacket
- WorldFactPacket
- ContextManifest
- SessionState
- AgentRun
- MapEvent / MapAction
- AgentAction
- Tool Registry v0
- ToolCall / ToolResult

## 当前不包含

- Approval / SideEffect
- IntentSnapshot / PlanConstraintSet
- RidePlanDraft / ValidationResult
- TraceEvent / Error
- Contribution contract
- Runtime

## Agent 能看到什么

| 合同 | 职责 |
|---|---|
| `RiderCapabilitySnapshot` | Python Domain Plane 从当前骑手近 42 天 Activity 汇总出的距离、时长、爬升密度、数据新鲜度和置信度；不含原始轨迹、精确坐标、功率、心率或健康判断。 |
| `RiderContextPacket` | 仅投影当前任务已授权且相关的骑手资料、opaque saved-place ref、结构化 familiarity、明确偏好/记忆、unknown 与省略项。 |
| `WorldFactPacket` | 仅投影当前任务需要的版本化路线对象、Traversal、关系、带 scope/provenance/freshness 的事实、时效动态、隔离 advisory 与 explicit unknown。 |
| `ContextManifest` | 记录一次 model call 使用的 source revision、选择/省略、隐私删减与 token 预算，使编译输入可审计和可重放；它不是事实来源。 |
| `SessionState` | 一次可恢复骑行决策的 working state；保存 intent/focus/candidate/map/unknown/用户决策引用，不保存 transcript、Run checkpoint、World Fact 副本或长期 Memory。 |
| `AgentRun` | 确定性 Run Controller 的一次有界执行；一个 Session 可以有多个 Run，每个 Run 固定绑定一个 committed Session revision，预算在 resume lineage 中只能单调消耗。 |
| `MapEvent` | 用户从共享地图产生的 typed input；pin 只携带 opaque location handle，candidate switch 不等于最终 Plan selection。 |
| `MapAction` | 必须经过 deterministic gate/reducer 的声明式地图动作；不允许 JS command、CSS/style JSON 或坐标 payload。 |
| `AgentAction` | 单一主 Agent 在一次 model turn 中提出的单个 typed proposal；`propose_tool_call` 只携带 `tool_call_ref`，不能直接改 Session、选择 Plan、调用 raw Provider 或制造外部副作用。 |
| `Tool Registry` | `deterministic_control_plane` 拥有的版本化 deny-by-default allowlist；v0 恰好注册 8 个在线静态规划高层工具。 |
| `ToolCall` | Agent 提出的 immutable request identity；只携带 opaque input envelope。同一 ID 的 authoritative request 字段不可在 retry 时改变，不是 approval、execution、provider request 或副作用。 |
| `ToolResult` | `deterministic_domain_plane` 返回的一次 typed attempt observation；同一 ToolCall 可有多个 Result，但最多一个且最后一个是 terminal。它不是 canonical fact、ValidationResult 本体、Session mutation 或 effect receipt。 |

## Session、Run 与地图动作边界

- `SessionState` 是 deterministic interaction service 拥有的 working state，不是完整聊天记录。one Session can have many Runs；Run 与 Session 分离，Run/AgentAction/MapAction 都绑定 `base_session_revision`，stale proposal 不能覆盖新版 Session。
- `session_commit.commit_status=reconciliation_required` 只用于持久层写入返回异常且 exact-event 重读也无法判断结果的窄故障面；它必须停止为 `deterministic_error` 或 `cancelled`，禁止自动重试、禁止声称 committed，并由恢复流程按 immutable event id 对账。不得把该状态藏进 metadata。
- `AgentRun` 的 created 状态不含任何执行引用或预算消耗，且不能提交 Session；每个实际 model turn 必须恰好对应一个 `ContextManifest`。running Run 也不能提前声称最终 commit，deadline 必须严格晚于 started time。resume 使用新 `run_id`，继承同一 lineage 与单调预算，并绑定 parent 已提交后的 current Session revision。
- `MapEvent` 和 `MapAction` 都必须经过 deterministic reducer；地图状态不能从自然语言回复反推。用户切换 active candidate 只改变当前关注项，只有 `plan_confirmed` 用户事件或未来等价明确事件才能产生 `selected_plan`。
- Session 的地图状态只保存 deterministic boundary 已解析的 opaque `available_bounds_refs`。`fit_bounds` 可以把 viewport 从当前 bounds 改到其中另一个已知 ref；viewport 用 `source_kind/source_ref` 区分 initial、MapEvent 与 MapAction 来源，仍禁止 bbox、坐标、WKT 或 GeoJSON。
- active、switch、leg selection 与最终 selection 不能引用 hidden candidate，且必须 current 并携带 validation ref。`selected_plan` 必须由真实 user `plan_confirmed` MapEvent 对齐 candidate、Plan revision、前一 Session revision 与时间，不能只保存一个看似事件的字符串。
- Session 合法拥有 0–3 个 candidate；0 个候选是正式状态，Agent 应返回 typed `no_result`，不能强凑三条或用空 `present_valid_candidates` 伪装成功。
- 起点或目的地改变后，旧 candidate/selection 必须失效；resume Run 不能重置已消费预算；stale Run、AgentAction、MapAction 与 MapEvent 都必须 fail closed。
- 地图 pin 先由确定性 interaction adapter 转为 opaque place/location ref。A2.2 合同只允许粗粒度 label 与 `exact_coordinates_exposed=false`，不传精确坐标、bbox、WKT/GeoJSON 或 raw track。
- `AgentAction` 永远 `proposal_only=true`。旧的 `call_approved_tool` 已删除，不保留 compatibility alias；`propose_tool_call` 只引用独立 `ToolCall`，模型无权把静态 approval policy 说成某次请求已批准。

## A2.3a Tool Registry / ToolCall / ToolResult 边界

- Registry 默认 `DENY`，Owner 是 `deterministic_control_plane`；执行 Owner 固定为 `deterministic_domain_plane`。Run Controller 继续掌控 environment/Registry/revision/validation/retry/deadline gate。模型只有 proposal 权。
- v0 恰好允许 8 个工具：`planning.resolve_ride_object`、`planning.retrieve_rider_context`、`planning.retrieve_world_context`、`planning.generate_candidate_plans`、`planning.revise_plan`、`planning.validate_plan`、`planning.compare_plans`、`planning.prepare_export`。`planning.select_plan`、`export.commit`、Contribution/Memory/个人资产写入与 canonical world writer 均不可达。
- `planning.generate_candidate_plans` 的 `DOMAIN_MEDIATED` 只表示 production Domain Plane 可在自身边界内查询 Provider；Agent 不获得 raw Provider、URL、HTTP、SQL、ORM、shell、database/storage handle、坐标或 polyline。Provider 查询即使不产出 external artifact，也会产生不可撤回的最小外部数据披露，因此固定为 `IRREVERSIBLE_EXTERNAL_DISCLOSURE / MINIMIZED_DOMAIN_MEDIATED`；精确 effect identity、ledger 与 reconciliation runtime 仍属于未来 A2.3b。
- `ToolCall.input` 只有 `input_kind/input_ref/input_revision/input_schema_version/target_revision_refs`；不复制 payload，不允许 `arguments`、`params`、prompt prose、坐标、Provider request 或数据库命令。`tool_call_id` 是 immutable request identity；同 ID 的 environment、Run/Session revision、model turn、source action、Registry/tool/capability/purpose、input、expected observation、proposal flag 或 proposed time 任一变化都非法，需要新 ToolCall ID。
- `ToolResult` 用 `observation_id` 与 `AgentRun.observation_refs` 对齐，每条记录是一次 execution attempt observation。attempt 从 1 连续递增、时间单调不减；同一 ToolCall 可先有 `INTERMEDIATE` timeout/disconnect，再有至多一个且最后出现的 `TERMINAL` Result。stopped Run 的已执行 ToolCall 必须收敛到 terminal；仍 running/paused 且等待确定性 retry 时可暂时只有 intermediate。
- retry attempt chain 必须与同一 AgentRun 精确交叉绑定：ToolCall 的 run、session、base revision、environment、fixture mode 必须与 Run 一致，每个 ToolResult 再精确绑定该 Call 与 Run；Call/Result 时间必须落在 Run start/checkpoint 边界内，且 Result 不得早于 Call。
- running/paused Run 只保留 `INTERMEDIATE` observation 时，Run 本身仍必须通过 AgentRun schema；running Run 的 `session_commit.commit_status` 是 `not_attempted`，不存在 `not_committed` 状态。
- `RETRY_SAME_CALL` 只是 typed retry eligibility，不是执行授权；Run Controller 仍检查 deadline、retry budget、environment、Registry、stale revision，以及未来 A2.3b 的 exact-effect/reconciliation gate。deterministic retry 不自动新增 model turn 或 AgentAction；`AgentRun.budget.consumed.tool_calls` 统计 initial attempt 加 retry attempts，而 `tool_call_refs` 统计唯一 request proposal，因此 `len(tool_call_refs) <= consumed.tool_calls`。
- ToolResult 的 status/code/finality/retry/domain reason/result refs 作为组合 fail closed；success/ambiguous 不能携带 domain reason，timeout 与 disconnect 不能互换 reason。revision Result 只服务 `planning.revise_plan`，并严格要求 `object_type=ride_plan`；不定义 RidePlanDraft 内容。`planning.validate_plan` 只能引用未来 typed `plan_validation`，不能自行写 pass；`planning.prepare_export` 只能引用 `export_preview`，零 artifact、零 storage、零外部交付。
- candidate synthetic scenario 是两轮：turn 1 `ContextManifest` → `propose_tool_call` → generate → typed observation；deterministic mandatory validation gate 不伪装成第二个 Agent ToolCall；工具观察后重新编译的 turn 2 `ContextManifest` 必须包含待展示的两个 Plan revisions，turn 2 的 `present_valid_candidates` 不能引用 Manifest 中不存在的 Plan。每个非-resume Run 已消费 model turn 恰好对应一个 ContextManifest 与 typed AgentAction proposal ref；resume lineage 的累计计数由 parent+child refs 共同核对。
- A2.3b Approval/SideEffect 与 A2.3c IntentSnapshot/PlanConstraintSet/RidePlanDraft/ValidationResult 均未开始。A2.3c 只记录裁决：opaque intent ref 单独不足，preference 必须由 deterministic compiler 转成带来源的 `hard/soft/advisory` constraint，`unknown` 不能当 `pass`。

## Agent 不能看到什么

- 完整数据库或原始 ORM
- 精确家庭坐标
- 完整聊天历史
- 完整 Activity 轨迹
- 所有 Evidence 原文
- raw Provider response
- 未标注的骑友报告

精确位置只能由 Domain Tool 在模型边界内解析。未核验骑友报告只能进入 `advisories`，且必须携带 Registry 对齐的 `reported_value`、scope 与 freshness；`usage_policy` 只能是 `advisory_only` 或 `unknown_only`，不得静默成为 canonical fact 或 hard constraint。

## Predicate Registry 与扩展纪律

Registry v0 不是全国路线字段全集。新增路线特征时优先增加版本化 Predicate；重复、稳定且需要高频计算的 Predicate，才可能通过未来 ADR/合同升级成为一等字段。罕见特征仍应建模为带 `scope`、provenance 和 `freshness` 的 Predicate；缺失信息必须进入 explicit `unknowns`，正式 Fact 不得用 `enum_value=unknown` 或 `freshness_status=unknown` 伪装缺失值。

`route_shape` 只属于 `cycling_area`、`named_route`、`named_line`、`climb`、`classic_ride`；当这些类型出现在 `focus_refs` 中时，必须解析到带 `route_shape` 的对应对象。road section、destination、path、traversal、legacy route artifact 和 plan 不能携带 `route_shape`，仅聚焦它们的 packet 也不需要伪造 shape。

Predicate request 与 Relation request 是两条独立合同面。每个 requested Predicate 必须由 Fact、Dynamic State、Advisory、predicate unknown 或 typed request omission 明确响应；每个 requested Relation 必须由正式 `relations[]`、relation unknown 或 typed request omission 明确响应。`route.exit_option` 已从 Registry 删除，正式退出关系只使用 `exit_to`，不得双写成 Fact。

需要过滤、校验、追踪、比较或作为事实使用的数据，必须提升为正式字段或 Predicate，不得塞入 `metadata`。`metadata` 仅允许 `x-` namespaced 的显示/调试标量，不能保存路线事实、Session 状态真相、精确位置、tool payload、approval、validation、provenance、freshness 或 side effect，Agent 也不能依赖它做硬判断。禁止用任意 prose blob 规避正式建模。

## 版本与验证

- 目录主版本：`agent_v0`
- 当前 schema instance version：`0.1.0`
- JSON Schema：Draft 2020-12
- `$id` 前缀：`https://schemas.velo.invalid/agent_v0/`
- 同主版本只允许兼容性新增可选字段；破坏性变更使用新目录或新主版本。
- fixture 固定 `schema_version`，World fixture 均为 `packet_environment=test`、`fixture_only=true` 的合成合同数据，不是已核验产品事实。
- A2.2 fixture 均为 `environment=test`、`fixture_only=true` 的 synthetic interaction scenario，不是生产 Session、真实 Plan、Provider 结果或持久化记录。
- A2.3a ToolCall/ToolResult fixture 同样是 `environment=test`、`fixture_only=true` 的合成 observation；它可以表达 timeout → same-call retry → success 的 attempt chain，并由 conformance harness 绑定同一 AgentRun。该合同已通过 PR #43 进入主线并被 TypeScript Shadow 消费，但仍没有执行真实网络、Provider、export、数据库、storage 或外部 effect；Approval/SideEffect 与完整 Intent/Constraint/Plan/Validation 合同仍未实现。
- 所有 `$ref` 必须由本地 `referencing.Registry` 解析；合同测试不得联网、访问数据库、Redis 或真实 filesystem storage。
- JSON Schema 负责语言中立的 shape validation，但不等于 semantic conformance。Registry unit/value/freshness、request 完整响应、route-shape focus、范围顺序、带时区时间顺序、跨合同 environment/fixture/time、Session/Run revision、resume budget/current Session、candidate/selection provenance、viewport Event/Action transition、MapEvent/MapAction target identity、Manifest binding 与 token accounting 等跨字段不变量由 conformance suite 固定。未来任何语言的消费者都必须实现并通过这些不变量，不能只跑 schema shape validation。

## Python / TypeScript 与 Runtime 边界

- A2 合同是 language-neutral JSON Schema。当前 Python pytest 只利用既有 Python 仓库与 CI 执行 semantic conformance，不代表选择 Python Agent Runtime。
- 当前用户已明确选择 TypeScript Agent 项目；首个 plain TypeScript、event-sourced Shadow 内核位于 [`agent_runtime`](../../agent_runtime/README.md)。OpenAI Agents SDK、Mastra、LangGraph 与 XState 仍只可作为未来 orchestration 依赖，不能成为 Session、世界事实或权限的唯一真相源。
- 创造者 Agent 与骑友 Agent 是两个独立产品和权限面，不是同一 Agent 的角色开关。骑友侧已跑通会话/Context/路线 Shadow；创造者侧已跑通来源、Evidence、Claim、Eval 到 World Change Proposal 的独立确定性状态机，但两边都尚未接生产服务。
- 现有 Python/FastAPI Deterministic Domain Plane 继续保留，不因未来可能采用 TypeScript Agent Control Plane 而重写。
- `RiderCapabilitySnapshot` 已有当前用户只读 FastAPI 投影和 TypeScript Context 编译器；生产 Consumer 尚未接 HTTP adapter，Creator 也无权读取个人骑手快照。当前仍没有真实模型、腾讯 Provider 或小程序 Agent 接线，这些未验证层级不能由 Shadow 测试冒充。

安装 `requirements.txt` 中固定的测试依赖后运行：

```bash
pytest -q tests/contracts/test_agent_v0_context_contracts.py
pytest -q tests/contracts/test_agent_v0_session_run_map_action_contracts.py
pytest -q tests/contracts/test_agent_v0_tool_contracts.py
```
