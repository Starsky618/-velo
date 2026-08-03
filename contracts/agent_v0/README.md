# VELO Agent v0 language-neutral contracts

本目录包含 A2.1 Context contracts 与 A2.2 Session/Run/Map/Action contracts。它们固定语言中立、版本化的 shape 与 semantic conformance，不是数据库 schema，不选择 Python、TypeScript 或 Agent Runtime，也不证明生产 Context Compiler、reducer 或持久化服务已存在。

## 当前包含

- Common definitions
- Predicate Registry
- RiderContextPacket
- WorldFactPacket
- ContextManifest
- SessionState
- AgentRun
- MapEvent / MapAction
- AgentAction

## 当前不包含

- ToolCall / ToolResult
- Approval / SideEffect
- RidePlanDraft / ValidationResult
- TraceEvent / Error
- Contribution contract
- Runtime

## Agent 能看到什么

| 合同 | 职责 |
|---|---|
| `RiderContextPacket` | 仅投影当前任务已授权且相关的骑手资料、opaque saved-place ref、结构化 familiarity、明确偏好/记忆、unknown 与省略项。 |
| `WorldFactPacket` | 仅投影当前任务需要的版本化路线对象、Traversal、关系、带 scope/provenance/freshness 的事实、时效动态、隔离 advisory 与 explicit unknown。 |
| `ContextManifest` | 记录一次 model call 使用的 source revision、选择/省略、隐私删减与 token 预算，使编译输入可审计和可重放；它不是事实来源。 |
| `SessionState` | 一次可恢复骑行决策的 working state；保存 intent/focus/candidate/map/unknown/用户决策引用，不保存 transcript、Run checkpoint、World Fact 副本或长期 Memory。 |
| `AgentRun` | 确定性 Run Controller 的一次有界执行；一个 Session 可以有多个 Run，每个 Run 固定绑定一个 committed Session revision，预算在 resume lineage 中只能单调消耗。 |
| `MapEvent` | 用户从共享地图产生的 typed input；pin 只携带 opaque location handle，candidate switch 不等于最终 Plan selection。 |
| `MapAction` | 必须经过 deterministic gate/reducer 的声明式地图动作；不允许 JS command、CSS/style JSON 或坐标 payload。 |
| `AgentAction` | 单一主 Agent 在一次 model turn 中提出的单个 typed proposal；不能直接改 Session、选择 Plan、调用 raw Provider 或制造外部副作用。 |

## Session、Run 与地图动作边界

- `SessionState` 是 deterministic interaction service 拥有的 working state，不是完整聊天记录。one Session can have many Runs；Run 与 Session 分离，Run/AgentAction/MapAction 都绑定 `base_session_revision`，stale proposal 不能覆盖新版 Session。
- `MapEvent` 和 `MapAction` 都必须经过 deterministic reducer；地图状态不能从自然语言回复反推。用户切换 active candidate 只改变当前关注项，只有 `plan_confirmed` 用户事件或未来等价明确事件才能产生 `selected_plan`。
- Session 合法拥有 0–3 个 candidate；0 个候选是正式状态，Agent 应返回 typed `no_result`，不能强凑三条或用空 `present_valid_candidates` 伪装成功。
- 起点或目的地改变后，旧 candidate/selection 必须失效；resume Run 不能重置已消费预算；stale Run、AgentAction、MapAction 与 MapEvent 都必须 fail closed。
- 地图 pin 先由确定性 interaction adapter 转为 opaque place/location ref。A2.2 合同只允许粗粒度 label 与 `exact_coordinates_exposed=false`，不传精确坐标、bbox、WKT/GeoJSON 或 raw track。
- `AgentAction` 永远 `proposal_only=true`。ToolCall/ToolResult、Capability/Approval/Effect、RidePlanDraft/ValidationResult 仍属于 A2.3；Trace/Error/Contribution 与完整 Agent v0 freeze 属于 A2.4。

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
- 所有 `$ref` 必须由本地 `referencing.Registry` 解析；合同测试不得联网、访问数据库、Redis 或真实 filesystem storage。
- JSON Schema 负责语言中立的 shape validation，但不等于 semantic conformance。Registry unit/value/freshness、request 完整响应、route-shape focus、范围顺序、带时区时间顺序、environment/fixture 组合、Session/Run revision、resume budget、candidate/selection transition、MapEvent/MapAction target identity、Manifest binding 与 token accounting 等跨字段不变量由 conformance suite 固定。未来任何语言的消费者都必须实现并通过这些不变量，不能只跑 schema shape validation。

安装 `requirements.txt` 中固定的测试依赖后运行：

```bash
pytest -q tests/contracts/test_agent_v0_context_contracts.py
pytest -q tests/contracts/test_agent_v0_session_run_map_action_contracts.py
```
