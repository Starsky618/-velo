# VELO Agent-First 当前交接

> 最后核实：2026-08-06。本轮从 `origin/main@70b4e97d` 开始实现 Creator PostgreSQL Persistence Slice v0，交付 PR 为 #51；最终合并与 CI 状态以 GitHub checks 为准。这份文件回答三个问题：我们为什么做 Agent、现在真实做到了哪一层、下一刀是什么。

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
| TypeScript Creator 内核 | 已有原始 Conversation/Evidence、Agent 判断提议、Tim 精确确认/拒绝/替代、Contradiction、Context Manifest、模型端口与冷启动重放 Eval | [`agent_runtime/creator`](../../agent_runtime/creator)，PR #49 |
| 路线规划 Shadow | 已验证锁定 canonical core Traversal，腾讯只生成 access/connector/exit/return；支持多核心段拼接 | synthetic 天龙山 fixture，不是真实腾讯调用或真实推荐质量 |
| Creator PostgreSQL Slice | 已实现独立 `creator_*` append-only 真值流与关系投影、revision CAS、幂等与冲突、Python 事务服务、鉴权注入式内部 HTTP router、TypeScript HTTP Store 和精确回读对账 | 迁移与本地任务 PostgreSQL 已验证；router 未挂载到生产应用，未配置生产 token，也未执行生产迁移 |
| 本轮本地验证 | TypeScript 81/81；真实 PostgreSQL 16/16 且 0 skipped；Alembic 单 head；Python compileall 与 diff check 通过 | 完整临时 PostGIS/Redis 和全量 pytest 仍由本轮 GitHub CI 证明；本地结果不证明生产、真实 Tim UI 或骑友可用 |

当前还没有：

- Creator 对 Codex/ChatGPT/资料源的生产自动摄取适配器。
- 绑定真实登录 Tim 身份的审核 UI/API。
- 真实 LLM/provider loop、tracing 后端或人机审核界面。
- 生产鉴权与路由挂载、生产数据库迁移、小程序接线、真实腾讯调用或 Strava ingestion。
- 直接从 PostgreSQL 投影编译 Context 的生产读模型与 drift-stop 告警；当前 TypeScript 仍读取精确事件前缀并自行重放。
- 能证明“路线判断真实改善推荐与骑友结果”的现实端到端 Eval。

所以，PR #46 建成 Rider Runtime 地基，PR #49 建成 Creator 本地信息与判断闭环；两者都不是最终的“第二大脑”。

## 4. 本轮已实现和当前唯一推荐下一刀

**Creator Information & Judgment Loop v0** 已通过 PR #49 合并：真实读取天龙山拍定本与路线认知蓝图，运行“来源 → Evidence → Agent 提议 → Shadow Tim 精确响应 → 判断替代 → Context → 冷启动 Eval”。详细合同和 Reborn 迁移审计见 [`creator-information-judgment-loop-v0.md`](creator-information-judgment-loop-v0.md)。

本地已证明：

- 同一 source message 不会重复写入，冲突 event ID fail closed；
- 普通 prose 和 Agent principal 都不能确认 Tim 判断；
- 被拒绝或替代的判断不会进入 current Context；
- Manifest 记录 workspace revision、加载 refs、source hash/provenance、omission 与 context hash；
- 支持当前判断的 Evidence 不会被 Context 预算裁掉；
- 全新 Node 进程可从空聊天上下文重放相同当前判断和未决矛盾；
- 每条 event 持久化实际 principal/capability 收据，Rider principal 在模型读取 Creator 私有 Context 前即被拒绝；
- source 撤权、judgment 到达 `review_at` 或引用跨 subject 时 fail closed，commit 响应不明按 exact event 对账。

**Creator PostgreSQL Persistence Slice v0** 已把 [`CREATOR_POSTGRESQL_SPEC_V0.md`](../../agent_runtime/CREATOR_POSTGRESQL_SPEC_V0.md) 的最小可执行部分落成：13 张独立 `creator_*` 表、append-only trigger、同事务投影、revision CAS、source message 去重、proposal/decision 复合绑定、supersession、contradiction、精确事件回读与 reconciliation。TypeScript 仍是 reducer/compiler 的语义所有者；Python 只负责持久化事务和数据库约束，避免两套状态机各自演化。

当前唯一推荐下一刀是 **Projection-native Context + Drift-stop Shadow**：让数据库投影生成与 TypeScript 冷重放可逐字段比较的 Context/Manifest，在差异出现时 fail closed 并留下告警；随后才接真实 Tim 身份与内部 Shadow API。仍不同时扩 Published World 或 Rider 数据面。

## 5. 数据库当前边界

本轮没有造“Agent 万能库”，只实现 Creator Information & Judgment Loop 已稳定使用的 13 张隔离表：

- `creator_workspaces` / `creator_workspace_events`：revision 与 append-only 真值流；
- `creator_sources` / `creator_rights_checks` / `creator_source_messages` / `creator_source_message_subjects`：来源、权限与原文；
- `creator_evidence_items`：可追溯证据；
- `creator_judgments` / `creator_judgment_turns` / `creator_judgment_evidence` / `creator_judgment_decisions`：Agent 提议与 Tim 精确决定；
- `creator_judgment_contradictions` / `creator_judgment_contradiction_resolutions`：未决冲突和解决记录。

Published World、Claim/Eval/World Change 和 Rider 私有表族仍按 [`DATABASE_BOUNDARY.md`](../../agent_runtime/DATABASE_BOUNDARY.md) 分面设计，没有被本轮顺手实现。migration 不修改 `users`、`activities`、`segments` 或 `segment_efforts`。生产迁移、真实鉴权和路由挂载需要单独授权与验收，不能从“CI 迁移成功”推导为“线上已启用”。

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
VELO_TEST_DATABASE_URL='postgresql://.../task_db' \
  VELO_REQUIRE_POSTGRES_TESTS=1 \
  python3 -m pytest -q tests/test_creator_persistence_pg.py
python3 -m alembic heads
npm run demo:shadow -- \
  --origin 太原站附近 \
  --minutes 240 \
  --max-climb-m 1200 \
  --urban-exposure low
```

当前 Runtime 的开发者说明看 [`agent_runtime/README.md`](../../agent_runtime/README.md)，语言中立合同看 [`contracts/agent_v0/README.md`](../../contracts/agent_v0/README.md)。
