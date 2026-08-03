# VELO Agent v0 context contracts

本目录是 A2.1 的语言中立 JSON Schema 合同基础。它定义一次模型调用可接收的最小、版本化投影，不是数据库 schema，不选择 Python、TypeScript 或 Agent Runtime，也不证明生产 Context Compiler 已存在。

## 当前包含

- Common definitions
- Predicate Registry
- RiderContextPacket
- WorldFactPacket
- ContextManifest

## 当前不包含

- SessionState
- AgentRun
- MapEvent / MapAction
- AgentAction
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

## Agent 不能看到什么

- 完整数据库或原始 ORM
- 精确家庭坐标
- 完整聊天历史
- 完整 Activity 轨迹
- 所有 Evidence 原文
- raw Provider response
- 未标注的骑友报告

精确位置只能由 Domain Tool 在模型边界内解析。未核验骑友报告只能进入 `advisories`，且 `usage_policy` 只能是 `advisory_only` 或 `unknown_only`，不得静默成为 canonical fact 或 hard constraint。

## Predicate Registry 与扩展纪律

Registry v0 不是全国路线字段全集。新增路线特征时优先增加版本化 Predicate；重复、稳定且需要高频计算的 Predicate，才可能通过未来 ADR/合同升级成为一等字段。罕见特征仍应建模为带 `scope`、provenance 和 `freshness` 的 Predicate；缺失信息必须进入 explicit `unknowns`。

需要过滤、校验、追踪、比较或作为事实使用的数据，必须提升为正式字段或 Predicate，不得塞入 `metadata`。`metadata` 仅允许 `x-` namespaced 的显示/调试标量，不能保存路线事实、精确位置、approval、validation、provenance 或 freshness，Agent 也不能依赖它做硬判断。禁止用任意 prose blob 规避正式建模。

## 版本与验证

- 目录主版本：`agent_v0`
- 当前 schema instance version：`0.1.0`
- JSON Schema：Draft 2020-12
- `$id` 前缀：`https://schemas.velo.invalid/agent_v0/`
- 同主版本只允许兼容性新增可选字段；破坏性变更使用新目录或新主版本。
- fixture 固定 `schema_version`，World fixture 均为 `packet_environment=test`、`fixture_only=true` 的合成合同数据，不是已核验产品事实。
- 所有 `$ref` 必须由本地 `referencing.Registry` 解析；合同测试不得联网、访问数据库、Redis 或真实 filesystem storage。
- JSON Schema 负责语言中立的结构约束；Registry unit/value/freshness、section authorization、跨对象 identity/reference、Manifest source hash 与 token accounting 等跨字段不变量由同一 conformance suite 固定。未来任何语言的消费者都必须实现并通过这些不变量，不能只跑 schema shape validation。

安装 `requirements.txt` 中固定的测试依赖后运行：

```bash
pytest -q tests/contracts/test_agent_v0_context_contracts.py
```
