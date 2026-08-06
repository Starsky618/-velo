# VELO TypeScript Agent Runtime

这是 VELO 的 Agent 控制面，不是 Python 业务后端的翻译版。当前已有可重放内核、权限边界、确定性天龙山 Shadow、Creator PostgreSQL persistence、projection drift-stop，以及“原话 → 解释候选 → 任务状态 → 判断升格 → 精确确认”的 v0 切片；没有接真实模型、腾讯网络、生产数据库流量或小程序。

## 为什么做这个 Runtime

核心目的不是增加一个聊天入口，而是让 VELO 能长期保留来源信息、Tim 明确确认的判断及其修订链，并在每次模型运行前编译出可审计的最小 Context。聊天窗口被压缩或进程重启后，系统应从事件和 revision 恢复，而不是要求模型“记住”。

这套闭环最终需要：原始信息 → Agent 提议 → Tim 确认/拒绝 → 判断替代与冲突 → Context 编译 → Agent Run → Eval/反馈 → World Change Proposal。当前 Rider 与 Creator 都已有本地确定性闭环；Creator 的信息/判断子集还可通过内部 HTTP Store 写入 PostgreSQL 事件真值与投影。JSONL 仍是 Shadow 对照，内部 router 未挂载生产服务。

当前交接和下一阶段验收见 [`docs/agent-first/README.md`](../docs/agent-first/README.md)。

## 两个 Agent 产品

| 产品 | 服务对象 | 可以做 | 明确不能做 |
|---|---|---|---|
| `creator/` 创造者 Agent | Tim 与 VELO 建设者 | 摄取来源、检查原始证据、提出 Claim/World Change、运行 Eval | 面向骑友生成方案；跳过审核直接发布世界真相 |
| `consumer/` 骑友 Agent | 骑友用户 | 读取已发布 World Fact、生成/校验/比较/修订 Plan、准备导出、提出反馈 | 看原始证据；写 canonical truth；直接调用 SQL/ORM/raw Provider |

二者不是一个 Super Agent 的两种 role。它们分别拥有 capability registry、context、状态机、评测与未来部署。唯一允许的耦合面是版本化的 Published World Fact / Traversal、Plan API 和 Feedback Proposal。

## 当前已经运行的内核

- `consumer/session/`：append-only JSONL 事件、精确原始 turn、mainline/branch、显式 blocking unknown、revision 冲突和原子写入。决定必须先 proposal，再由绑定 exact decision id + statement hash 的骑友 UI action 回答；普通聊天文字不能被提升成“用户确认”。所有外部事件使用 exact-key 校验。终态 Session/Topic 不会被隐式重开；跨进程锁使用 atomic mkdir、heartbeat、stale recovery 与 ownership-aware release。Agent 回复只有在 reducer/store 返回真实 committed revision 后才完成；atomic rename 后的异常会按 exact event id + canonical payload 重读对账，无法判断时显式标记 `reconciliation_required`。
- `consumer/context/`：把最近对话、所有仍生效的用户确认决定与未结分支编译成 `RiderConversationContext`；另将 Python Domain Plane 的 `RiderCapabilitySnapshot` 编译成目的、scope、隐私和 source revision 明确的 `RiderContextPacket`。对话记忆只进入 memory refs，不再冒充语言中立的 Rider packet。
- `consumer/runtime/`：从现有 `contracts/agent_v0/tool_registry.v0.json` deny-by-default 解析 namespaced Tool，记录 AgentRun / ContextManifest / AgentAction / ToolCall / ToolResult。每个逻辑 model turn 都会先编译 Context，再让可替换的 `ShadowDecisionModel` 消费它并返回 typed proposal；当前实现是可重复的 deterministic fake model，不是外部 LLM。已授权的 Rider packet 会以精确 packet id、source revision 和 content hash 进入每次 ContextManifest；当前仍缺生产 HTTP adapter 从 FastAPI 拉取它。model、tool 和 Session commit 都受 AbortSignal、执行前/后 deadline 与不可逆写入前 guard 约束；超时 model turn 收敛为 typed action，超时 ToolCall 收敛为 terminal ToolResult。tool-call 与 plan-generation 预算在执行前门禁；校验和比较仍由确定性 gate 所有。Node AJV 验单体 schema，Python 测试直接复用既有 `assert_run_semantics` 并检查正常/超时 trace 的跨 artifact identity。
- `consumer/planning/`：门到门候选绑定 request hash、origin identity/revision 与 world revision；腾讯连接段与 canonical Traversal 使用不同身份命名空间。腾讯可以连接多个核心赛段，不能重算、降级或冒充核心赛段。
- `creator/state/`：独立的来源 → Rights Check → 原始 Conversation/Evidence → Claim/Judgment Proposal → Tim 精确响应 → Supersession/Contradiction → Eval → World Change Proposal 状态机。Agent 没有 `judgment.decide`；普通 prose 不能成为确认；没有 publish 事件。
- `creator/interpretation/`：模型只能先写可撤销的多标签解释；`task_ref/project_ref` 隔离局部纠正；机械 Task State Engine 只能改当前 focus；独立 Promotion Engine 以精确 Tim 作者、作用域、反证、独立任务或真实结果做非补偿门槛，形成的长期判断仍需 Tim 对精确 statement/hash 确认。
- `creator/context/`：按 subject、task_ref/project_ref 与确定性 `as_of` 编译 mission、当前任务、仍在复核期且来源权利允许的 Tim-confirmed judgment、局部解释及其精确原话、未知项、冲突包、pending proposal/input 与 Evidence，并输出 source event/rights revision、provenance/hash、加载项、遗漏原因和 context hash。撤权、到期或作用域不匹配的信息 fail closed。
- `creator/runtime/`：读取私有 Context 前先过 Creator capability；模型端口只返回 exact-key typed action；模型只能引用本次 Context 真正加载的 source/evidence。atomic commit 响应不明时按 exact event ID/payload 重读对账，重试不会再次调用模型。reducer 继续拥有权限、revision 和写入。
- `creator/eval/`：把进程内 view 与全新 Node 进程冷启动 JSONL 重放后的 Context 比较；真实 Tim 纠错病例检查过度升格、task scope leak、歧义拒答与未确认判断泄漏。
- `creator/state/http-store.ts`：依赖 bearer credential provider；派生事件还必须由注入的 reducer attestor 对 exact event/prefix/principal/capability 签名。POST 不发送可伪造 principal，commit receipt 必须重读 exact event/revision/hash/principal/capability 才算成功。
- `app/creator_persistence/`：Python Domain Plane 持有 PostgreSQL transaction、revision CAS、event id/hash 幂等、append-only 事件真值、必要投影和 proposal/Tim turn/statement hash 复合绑定。它不导入 TypeScript，也不修改 Rider 或路线核心表。

当前 capability gate 是运行时执行守卫，不冒充生产鉴权：测试与 Shadow 使用显式 test/shadow principal，并验证 Creator/Rider principal 互相拒绝。Python 提供需要部署方注入 token authenticator 的 router factory，但没有生产 token verifier、真实 Tim 身份签发、进程/网络隔离或公开路由挂载。

Creator persistence 由 `20260806_creator_pg_v0` 与 `20260806_creator_ctx_v1` 两个 revision 组成，共 17 张隔离的 `creator_*` 表。事件流是 append-only 真值，投影与事件同事务；不把整个 `CreatorView` 固化成一行 JSON。HTTP Store 当前覆盖 13 类 information/judgment/interpretation/task/calibration 事件，并在 transport 前拒绝其他 Creator event family；派生事件无 reducer attestation 时也在落盘前拒绝。Claim 通用 Eval/Human Review/World Change、Published World 和 Rider 表族仍未入库。Context 由同一 TypeScript reducer/compiler 对 event truth 与关系投影双路径重放；任何 record/digest/context 漂移都在模型调用前停止。

数据库复用与后续表族边界见 [`DATABASE_BOUNDARY.md`](DATABASE_BOUNDARY.md)，Creator 最小事务/约束/回放规格见 [`CREATOR_POSTGRESQL_SPEC_V0.md`](CREATOR_POSTGRESQL_SPEC_V0.md)。
Reborn 迁移审计、Creator v0 合同与真实天龙山材料 Eval 见 [`creator-information-judgment-loop-v0.md`](../docs/agent-first/creator-information-judgment-loop-v0.md)。
解释、任务、升格防火墙、外部项目设计考古与真实纠错 replay 的冻结架构见 [`creator-context-interpretation-promotion-v0.md`](../docs/agent-first/creator-context-interpretation-promotion-v0.md)。

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
