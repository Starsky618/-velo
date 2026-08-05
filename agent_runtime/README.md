# VELO TypeScript Agent Runtime

这是 VELO 的 Agent 控制面，不是 Python 业务后端的翻译版。当前第一刀只建立可重放内核、权限边界和确定性天龙山 Shadow；没有接真实模型、腾讯网络、生产数据库或小程序。

## 两个 Agent 产品

| 产品 | 服务对象 | 可以做 | 明确不能做 |
|---|---|---|---|
| `creator/` 创造者 Agent | Tim 与 VELO 建设者 | 摄取来源、检查原始证据、提出 Claim/World Change、运行 Eval | 面向骑友生成方案；跳过审核直接发布世界真相 |
| `consumer/` 骑友 Agent | 骑友用户 | 读取已发布 World Fact、生成/校验/比较/修订 Plan、准备导出、提出反馈 | 看原始证据；写 canonical truth；直接调用 SQL/ORM/raw Provider |

二者不是一个 Super Agent 的两种 role。它们分别拥有 capability registry、context、状态机、评测与未来部署。唯一允许的耦合面是版本化的 Published World Fact / Traversal、Plan API 和 Feedback Proposal。

## 当前已经运行的内核

- `consumer/session/`：append-only JSONL 事件、精确原始 turn、mainline/branch、显式 blocking unknown、revision 冲突和原子写入。决定必须先 proposal，再由绑定 exact decision id + statement hash 的骑友 UI action 回答；普通聊天文字不能被提升成“用户确认”。所有外部事件使用 exact-key 校验。终态 Session/Topic 不会被隐式重开；跨进程锁使用 atomic mkdir、heartbeat、stale recovery 与 ownership-aware release。Agent 回复只有在 reducer/store 返回真实 committed revision 后才完成；atomic rename 后的异常会按 exact event id + canonical payload 重读对账，无法判断时显式标记 `reconciliation_required`。
- `consumer/context/`：把最近对话、所有仍生效的用户确认决定与未结分支编译成 `RiderConversationContext`；它会真实进入每次运行的 ContextManifest，但自身永远不冒充 Agent v0 `ContextManifest` 或事实源。
- `consumer/runtime/`：从现有 `contracts/agent_v0/tool_registry.v0.json` deny-by-default 解析 namespaced Tool，记录 AgentRun / ContextManifest / AgentAction / ToolCall / ToolResult。每个逻辑 model turn 都会先编译 Context，再让可替换的 `ShadowDecisionModel` 消费它并返回 typed proposal；当前实现是可重复的 deterministic fake model，不是外部 LLM。model、tool 和 Session commit 都受 AbortSignal、执行前/后 deadline 与不可逆写入前 guard 约束；超时 model turn 收敛为 typed action，超时 ToolCall 收敛为 terminal ToolResult。tool-call 与 plan-generation 预算在执行前门禁；校验和比较仍由确定性 gate 所有。Node AJV 验单体 schema，Python 测试直接复用既有 `assert_run_semantics` 并检查正常/超时 trace 的跨 artifact identity。
- `consumer/planning/`：门到门候选绑定 request hash、origin identity/revision 与 world revision；腾讯连接段与 canonical Traversal 使用不同身份命名空间。腾讯可以连接多个核心赛段，不能重算、降级或冒充核心赛段。
- `creator/state/`：独立的来源 → Rights Check → 原始 Evidence → Claim（含有效期/复核时间）→ Conflict Analysis → Eval → World Change Proposal 状态机；`needs_review`/`needs_more_evidence` 可显式进入 Human Review Request。没有 publish 事件，不能绕过人工/确定性发布边界。

当前 capability gate 是运行时执行守卫，不冒充生产鉴权：测试与 Shadow 使用显式 test/shadow principal，并验证 Creator/Rider principal 互相拒绝；生产 authenticated service principal、进程/网络隔离和部署身份尚未实现，所以本目录仍不进入 Python 生产镜像。

当前没有新增数据库迁移。原因是现有 Postgres 还没有承载这些 runtime 事件的真实失败证据；先让事件合同和评测暴露稳定写入模式，再分别设计 Creator evidence/claim/proposal 表族与 Consumer session/run/plan/trace 表族，避免一次性把蓝图猜成生产 schema。

数据库复用与后续表族边界见 [`DATABASE_BOUNDARY.md`](DATABASE_BOUNDARY.md)。

## 本地运行

```bash
npm ci
npm test
npm run demo:shadow -- \
  --origin 太原站附近 \
  --minutes 240 \
  --max-climb-m 1200 \
  --urban-exposure low
```

CLI 会把精确请求与 Agent 回复写入默认的 `.agent-runtime/sessions/<session_id>.jsonl`，便于压缩上下文后重放。
