# VELO Agent-First 当前交接

> 最后核实：2026-08-06。当前交接基线是 `origin/main@e7924654`；本轮实现 Context Interpretation & Promotion v0，PR、CI 与合并状态必须以 GitHub 为准。这份文件回答三个问题：我们为什么做 Agent、现在真实做到了哪一层、下一刀是什么。

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
| TypeScript Creator 内核 | 已有原始 Conversation/Evidence、可撤销解释、任务状态、机械升格、Tim 精确确认/拒绝/替代、Conflict Packet、Context Manifest 与真实病例 replay | [`agent_runtime/creator`](../../agent_runtime/creator)；解释模型仍是 deterministic fake |
| 路线规划 Shadow | 已验证锁定 canonical core Traversal，腾讯只生成 access/connector/exit/return；支持多核心段拼接 | synthetic 天龙山 fixture，不是真实腾讯调用或真实推荐质量 |
| Creator PostgreSQL Slice | 已实现 17 张独立 `creator_*` 表、append-only 真值流与关系投影、revision CAS、幂等与冲突、interpretation/task/calibration/promotion lineage、TypeScript HTTP Store 和精确回读对账 | router 未挂载生产应用，未配置生产 token，也未执行生产迁移 |
| 本轮验证 | TypeScript 107/107、Python compileall；一次性 PostgreSQL 17.9 空库上 migration 回环、事务、并发、鉴权、投影重建 21/21 通过；全量 pytest 仍以本轮 CI 为最终证据 | 本地真库仍不证明生产、真实 Tim UI、真实模型或骑友可用 |

当前还没有：

- Creator 对 Codex/ChatGPT/资料源的生产自动摄取适配器。
- 绑定真实登录 Tim 身份的审核 UI/API。
- 真实 LLM/provider loop、tracing 后端或人机审核界面。
- 生产鉴权与路由挂载、生产数据库迁移、小程序接线、真实腾讯调用或 Strava ingestion。
- 已挂载的生产 PostgreSQL Context 读模型与 drift-stop 告警处置；当前能力仍是未挂载 Shadow。
- 能证明“路线判断真实改善推荐与骑友结果”的现实端到端 Eval。

所以，PR #46 建成 Rider Runtime 地基，PR #49 建成 Creator 本地信息与判断闭环；两者都不是最终的“第二大脑”。

## 4. 本轮实现和当前唯一推荐下一刀

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
- task-local 纠正只在相同 `task_ref` 可见；后续解释显式 supersede 旧解释但不删除历史；
- 历史 schema v1 conversation judgment 可继续冷回放；新 schema v2 evidence judgment 禁止消费 conversation turn，对话长期判断必须经过 promotion gate；
- interpretation、Task State、calibration、promotion 与 schema v2 judgment 只有经过 TypeScript reducer 后由 Ed25519 私钥签发 attestation 才能写入 PostgreSQL；Python 只持按 principal/environment/capability 限域的公钥，bearer capability 不能单独绕过；
- 外部引语、歧义身份和未解决反证不能升格，当前判断遇到新矛盾时 Context 明确携带 Conflict Packet；
- 跨任务重复必须由不同原始消息和真实 Task State 支撑，结果型升格必须携带同主体 real-world Evidence。

**Creator PostgreSQL Persistence Slice v0** 与 projection drift-stop 已落成。TypeScript 仍是 reducer/compiler 的语义所有者；Python 只负责持久化事务和数据库约束，避免两套状态机各自演化。

**Context Interpretation & Promotion v0** 的完整冻结架构见 [`creator-context-interpretation-promotion-v0.md`](creator-context-interpretation-promotion-v0.md)。本轮增加“原话 → 模型解释候选 → task-local 状态 → 机械升格 → Tim 精确确认”的防火墙；单次纠正、外部引语、歧义身份与未解决反证不能变成长效判断，后来的矛盾会进入 Conflict Packet 供 Agent 主动提醒。

当前唯一推荐下一刀是 **真实 interpretation model 的 unseen Shadow + Tim 审核面**：先证明首次理解率、重复纠正率、过度升格、应当拒答和冲突挑战真的改善，再考虑把结果用于 Published World 或 Rider Agent。不能从本轮 deterministic 测试推导为“已经具有人类判断力”；测试数量以本 PR/CI 最终结果为准。

## 5. 数据库当前边界

本轮没有造“Agent 万能库”，Creator 私有面现有 17 张隔离表：

- `creator_workspaces` / `creator_workspace_events`：revision 与 append-only 真值流；
- `creator_sources` / `creator_rights_checks` / `creator_source_messages` / `creator_source_message_subjects`：来源、权限与原文；
- `creator_evidence_items`：可追溯证据；
- `creator_judgments` / `creator_judgment_turns` / `creator_judgment_evidence` / `creator_judgment_decisions`：Agent 提议与 Tim 精确决定；
- `creator_judgment_contradictions` / `creator_judgment_contradiction_resolutions`：未决冲突和解决记录。
- `creator_turn_interpretations` / `creator_task_states`：解释谱系与当前任务真值；局部纠正按 task_ref 隔离。
- `creator_behavior_calibrations` / `creator_judgment_interpretations`：行为结果与长期判断的精确解释 lineage。

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
