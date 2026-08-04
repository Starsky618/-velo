# VELO TypeScript Agent Runtime

这是 VELO 的 Agent 控制面，不是 Python 业务后端的翻译版。当前第一刀只建立可重放内核、权限边界和确定性天龙山 Shadow；没有接真实模型、腾讯网络、生产数据库或小程序。

## 两个 Agent 产品

| 产品 | 服务对象 | 可以做 | 明确不能做 |
|---|---|---|---|
| `creator/` 创造者 Agent | Tim 与 VELO 建设者 | 摄取来源、检查原始证据、提出 Claim/World Change、运行 Eval | 面向骑友生成方案；跳过审核直接发布世界真相 |
| `consumer/` 骑友 Agent | 骑友用户 | 读取已发布 World Fact、生成/校验/比较/修订 Plan、准备导出、提出反馈 | 看原始证据；写 canonical truth；直接调用 SQL/ORM/raw Provider |

二者不是一个 Super Agent 的两种 role。它们分别拥有 capability registry、context、状态机、评测与未来部署。唯一允许的耦合面是版本化的 Published World Fact / Traversal、Plan API 和 Feedback Proposal。

## 当前已经运行的内核

- `consumer/session/`：append-only JSONL 事件、精确原始 turn、mainline/branch、用户确认决策、revision 冲突和原子写入。
- `consumer/context/`：把最近对话、所有仍生效的用户确认决定与未结分支编译成可审计投影；投影永远不冒充事实源。
- `consumer/planning/`：门到门候选由腾讯连接段与锁定的 canonical core Traversal 组成。腾讯可以连接赛段，不能重算核心赛段。
- `creator/state/`：独立的来源 → 原始 Evidence → Claim → Eval → World Change Proposal 状态机；没有 publish 事件，不能绕过人工/确定性发布边界。

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
