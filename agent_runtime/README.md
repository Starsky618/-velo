# VELO TypeScript Agent Runtime

这是 VELO 的 Agent 控制面，不是 Python 业务后端的翻译版。当前第一刀只建立可重放内核、权限边界和确定性天龙山 Shadow；没有接真实模型、腾讯网络、生产数据库或小程序。

## 为什么做这个 Runtime

核心目的不是增加一个聊天入口，而是让 VELO 能长期保留来源信息、Tim 明确确认的判断及其修订链，并在每次模型运行前编译出可审计的最小 Context。聊天窗口被压缩或进程重启后，系统应从事件和 revision 恢复，而不是要求模型“记住”。

这套闭环最终需要：原始信息 → Agent 提议 → Tim 确认/拒绝 → 判断替代与冲突 → Context 编译 → Agent Run → Eval/反馈 → World Change Proposal。当前 Rider 与 Creator 都已有本地确定性闭环；Creator 已新增 conversation ingestion、精确判断确认/拒绝/替代、Context Manifest、可替换模型端口和冷启动重放 Eval。它仍是 JSONL Shadow，不是生产服务。

当前交接和下一阶段验收见 [`docs/agent-first/README.md`](../docs/agent-first/README.md)。

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
- `creator/state/`：独立的来源 → Rights Check → 原始 Conversation/Evidence → Claim/Judgment Proposal → Tim 精确响应 → Supersession/Contradiction → Eval → World Change Proposal 状态机。Agent 没有 `judgment.decide`；普通 prose 不能成为确认；没有 publish 事件。
- `creator/context/`：按 subject 与确定性 `as_of` 编译 mission、仍在复核期且来源权利允许的 Tim-confirmed judgment、pending proposal/input、相关 Evidence 与未决 contradiction，并输出 source event/rights revision、provenance/hash、加载项、遗漏原因和 context hash。撤权或到期信息 fail closed；当前判断的必要证据不会被预算静默裁掉。
- `creator/runtime/`：读取私有 Context 前先过 Creator capability；模型端口只返回 exact-key typed action；模型只能引用本次 Context 真正加载的 source/evidence。atomic commit 响应不明时按 exact event ID/payload 重读对账，重试不会再次调用模型。reducer 继续拥有权限、revision 和写入。
- `creator/eval/`：把进程内 view 与全新 Node 进程冷启动 JSONL 重放后的 Context 比较，并检查 superseded/rejected judgment 不会复活。

当前 capability gate 是运行时执行守卫，不冒充生产鉴权：测试与 Shadow 使用显式 test/shadow principal，并验证 Creator/Rider principal 互相拒绝；生产 authenticated service principal、进程/网络隔离和部署身份尚未实现，所以本目录仍不进入 Python 生产镜像。

当前没有新增数据库迁移。Creator v0 已暴露 revision CAS、source message 去重、proposal/decision 强绑定、supersession、contradiction 与 Context 查询等第一批稳定模式；最小 PostgreSQL 事务、约束、投影、回放和失败恢复已经形成架构规格。下一阶段按该规格在 CI 临时 PostgreSQL 实现并验证首个持久化切片，不把整个 `CreatorView` 粗暴固化成一行 JSON。

数据库复用与后续表族边界见 [`DATABASE_BOUNDARY.md`](DATABASE_BOUNDARY.md)，Creator 最小事务/约束/回放规格见 [`CREATOR_POSTGRESQL_SPEC_V0.md`](CREATOR_POSTGRESQL_SPEC_V0.md)。
Reborn 迁移审计、Creator v0 合同与真实天龙山材料 Eval 见 [`creator-information-judgment-loop-v0.md`](../docs/agent-first/creator-information-judgment-loop-v0.md)。

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
