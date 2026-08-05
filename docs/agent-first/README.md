# VELO Agent-First 当前交接

> 最后核实：2026-08-05，`origin/main@ff8e09081d9613e761c01ab308fda068cd4651e7`（PR #46）。这份文件回答三个问题：我们为什么做 Agent、现在真实做到了哪一层、下一刀是什么。

## 1. 一开始要解决什么

VELO 不是为了“接一个会聊天的模型”而做 Agent。真正目标是建立一套可持续的路线认知系统：

1. 把 Tim、骑友、路线材料、实测数据和外部来源保留为可追溯的原始信息。
2. 严格区分“Tim 已明确确认的判断”“Agent 提议”“外部证据”“尚未解决的矛盾”，不让模型替 Tim 发明观点。
3. 让判断可以被确认、拒绝、修订和替代，同时保留来源、版本和时间。
4. 每次模型运行前，只编译当前任务真正需要的事实、判断、未决问题和来源，生成可审计 Context；聊天窗口压缩后仍能从事件重放，而不是靠模型回忆。
5. 用 Eval、真实结果和反馈检查 Agent 的输出，再把有效修正进入下一轮，而不是把一次回答直接升级成长期真相。

Reborn 是重要参照系：借鉴它的原始记录、显式状态、状态机、来源权威、review/Eval 和反馈回流思想；不复制它的具体目录或把 Reborn 的项目状态塞进 VELO。

## 2. 两个低耦合产品

| 产品 | 服务对象 | 核心责任 | 不能做 |
|---|---|---|---|
| Creator Agent | Tim 与 VELO 建设者 | 摄取信息、保留判断、核对来源、形成 Evidence/Claim、发现冲突、运行 Eval、提出 World Change | 替 Tim 确认判断；绕过审核发布世界事实；面向骑友直接规划 |
| Rider Consumer Agent | 骑友用户 | 读取已发布路线认知，理解需求，组合锁定核心赛段与腾讯连接段，生成/校验/比较方案 | 读取 Creator 私有原文；修改 canonical truth；让腾讯重算或替换核心赛段 |

两边不能合成一个靠 `role` 开关区分的 Super Agent。它们只通过版本化 Published World、Traversal、Plan 和 Feedback Proposal 交换信息。

## 3. 现在真实做到了哪

| 层面 | 当前事实 | 证据边界 |
|---|---|---|
| 语言中立合同 | Context、Session、Run、Map/Action、Tool Registry/Call/Result 已进入主线 | [`contracts/agent_v0`](../../contracts/agent_v0/README.md)，PR #41–#43 |
| TypeScript Rider 内核 | 已有 append-only JSONL Session、原始 turn、明确决定、unknown、Context 编译、Run/Tool deadline、重放与 reconciliation | [`agent_runtime`](../../agent_runtime/README.md)，PR #44、#46 |
| TypeScript Creator 内核 | 已有独立 capability 与来源 → Rights → Evidence → Claim → Conflict → Eval → World Change Proposal 状态机和 JSONL store | [`agent_runtime/creator`](../../agent_runtime/creator)，PR #46 |
| 路线规划 Shadow | 已验证锁定 canonical core Traversal，腾讯只生成 access/connector/exit/return；支持多核心段拼接 | synthetic 天龙山 fixture，不是真实腾讯调用或真实推荐质量 |
| 数据库设计 | 已核实现有 Route Cognition/PostGIS 可复用对象，并提出 Creator/Published World/Rider 三个数据面 | [`DATABASE_BOUNDARY.md`](../../agent_runtime/DATABASE_BOUNDARY.md) 仍是迁移前边界，不是已落库 schema |
| 验证 | PR #46 双独立审查通过；GitHub CI run #319 为 TypeScript 43/43、pytest 2447 passed / 0 skipped | 证明代码、空白 PostGIS migration 和 Redis 测试通过，不证明生产或骑友可用 |

当前还没有：

- Creator 对真实聊天/资料的自动摄取流程。
- Creator 自己的 Conversation Session、判断确认/替代协议和 Context Compiler。
- 真实 LLM/provider loop、tracing 后端或人机审核界面。
- 生产鉴权、进程隔离、数据库迁移、API、小程序接线、真实腾讯调用或 Strava ingestion。
- 能证明“保留的信息确实改善下一次判断”的端到端 Eval。

所以，PR #46 建成的是可信内核，不是最终的“第二大脑”。

## 4. 当前唯一推荐下一刀

下一阶段叫 **Creator Information & Judgment Loop v0**。先让开发者 Agent 在本地真实完成一次“记录 → 判断 → 确认 → 编译上下文 → 再运行 → Eval”，再讨论生产数据库。

按顺序完成：

1. 深读 Reborn 当前最新 Session、TypeScript 状态机、review/Eval 与内外部反馈回流，输出可以复用到 VELO 的不变量和不能照搬的差异。
2. 给 Creator 增加原始 conversation/source event；所有原文 append-only，并记录作者、来源和时间。
3. 增加 judgment proposal、Tim 明确确认/拒绝、supersede 与 contradiction 事件；Agent prose 永远不能自行升级成 Tim 的判断。
4. 建立 Creator Context Compiler：每轮只加载当前 mission、已确认且未被替代的判断、相关 Evidence、未决冲突和省略清单，并生成 manifest。
5. 接一个可替换的模型端口与确定性 fake model；模型只能提议 typed action，状态机掌控写入、权限、预算和停止。
6. 建立 context-compression Eval：清空聊天窗口后，仅从 JSONL 重放，仍能恢复正确判断、来源和未决问题；旧判断不能覆盖新确认。
7. 用一组 Tim 的真实路线材料跑通本地闭环。暴露真实查询、并发、冲突与恢复模式后，才落最小 PostgreSQL migration。

### v0 验收

- 同一份原始话语不会被重复写入；冲突 event id fail closed。
- Agent 提议与 Tim 确认在数据结构和权限上不可混淆。
- 判断替代保留完整链路，旧判断不再进入新 Context。
- Context Manifest 能说明加载了什么、为什么加载、遗漏了什么、使用哪个 revision。
- 在全新进程和空聊天上下文中重放，得到相同的有效判断与未决问题。
- 至少一个 Eval 能证明错误或过时信息不会静默进入 Published World。

## 5. 数据库进入条件

不要先造一套“Agent 万能库”。Creator Loop v0 在 JSONL Shadow 暴露稳定写入和查询后，首个 migration 只考虑：

- `creator_workspaces` / `creator_workspace_events`
- `source_records`
- `knowledge_claims` / `knowledge_claim_evidence`
- `claim_evaluations`
- `world_change_proposals`

Published World 与 Rider 私有表族仍按 [`DATABASE_BOUNDARY.md`](../../agent_runtime/DATABASE_BOUNDARY.md) 分面设计。首个 migration 不修改 `users`、`activities`、`segments` 或 `segment_efforts`。

## 6. 文档权威与历史边界

1. 当前用户指令。
2. 当前代码、测试、CI 和真实运行结果。
3. 仓库根 [`VELO_ORCHESTRATOR_STATE.yaml`](../../VELO_ORCHESTRATOR_STATE.yaml) 的当前交接状态。
4. 本 README 与 Accepted ADR。
5. 三份 source 蓝图：领域宪法、Agent 架构研究、长期领域架构。
6. 历史 Phase A 规格和 Control Pack。

[`phase-a-implementation-spec.md`](phase-a-implementation-spec.md) 与 [`VELO_Orchestrator_Control_Pack_v1.0.md`](VELO_Orchestrator_Control_Pack_v1.0.md) 保留为当时的设计与执行证据，不再承担当前状态。旧任务编号、旧 PR head 和当时的授权不能覆盖现在的代码事实。

## 7. 本地验证入口

```bash
npm ci
npm test
npm run demo:shadow -- \
  --origin 太原站附近 \
  --minutes 240 \
  --max-climb-m 1200 \
  --urban-exposure low
```

当前 Runtime 的开发者说明看 [`agent_runtime/README.md`](../../agent_runtime/README.md)，语言中立合同看 [`contracts/agent_v0/README.md`](../../contracts/agent_v0/README.md)。
