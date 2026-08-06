# Creator PostgreSQL Persistence Spec v0

> 状态：Persistence Slice v0 已实现事件真值、事务投影、内部 Store 与重放对账；Projection-native Context + Drift-stop Shadow v0 进一步实现了 §6 的关系投影事件重建、唯一 TypeScript compiler 双路径对账和模型调用前停机告警。`20260806_creator_ctx_v1` 在此基础上增加解释、任务、行为校准和长期判断升格 lineage。两条 migration、Python 单事务 service、可组合但未挂载公共 API 的内部 router，以及 TypeScript HTTP Store/Context guard 都仍是 Shadow 边界；生产身份、路由挂载与生产迁移尚未实现，不能称为完整生产持久化。

## 1. 推荐方案

采用 **一条 append-only 事件真值流 + 同事务可重建投影**，由 Python Domain Plane 持有数据库连接和事务；TypeScript Creator Runtime 只依赖 `CreatorWorkspaceStore`，通过内部鉴权 API 使用生产持久化。

不推荐两种做法：

- 不把整个 `CreatorView` 塞进一行 JSONB 当真值；并发 revision、去重、判断确认绑定和局部查询都会变成应用自觉。
- 不让 TypeScript Agent 直接拿现有业务库 SQL 权限；它不应跨过 Route Cognition、PostGIS、用户数据和发布事务的所有权边界。

最短数据流：

```text
Tim 审核动作 / Creator 模型 typed action
  → TypeScript event validator + capability
  → CreatorWorkspaceStore 内部 API adapter
  → Python Domain Plane 单事务 append + project
  → committed revision receipt
  → TypeScript 按该 revision 重读并编译 Context
```

当前 Shadow 已在任务专属 PostgreSQL 验证内部 Store wire contract、并发 CAS、幂等、投影回滚、精确判断绑定、撤权/到期 fail-closed、contradiction/replacement、commit 后 event-ID 收敛，以及 PostgreSQL event truth、关系投影重建与 JSONL 的 Context/Manifest 对账。仍未证明的是生产 bearer 身份签发、网络隔离、真实断网、告警后人工处置和 Tim UI；因此 router factory 不挂到 `app/main.py`，migration 也不在本切片部署生产。

跨语言事件合同以 JavaScript 可精确表达、Python 可编码为标准 UTF-8 的 JSON 为交集：整数必须位于 `Number.isSafeInteger` 范围；字符串只允许 Unicode scalar value，拒绝孤立 surrogate；`context_subject_refs` 必须采用 JavaScript 默认的 UTF-16 code-unit 顺序。Python 边界在计算 hash 和写入事件真值前执行相同门禁，不能接收会在 Node 读取时静默变值、编码失败或重排的 payload。

## 2. 为什么不能直接复用现有表

现有 `judgment_runs` 记录一次算法/Agent/人工审查的过程摘要和置信状态，适合 Domain judgment，不等于某个可确认的 Tim 判断提议。

现有 `evidence_items.first_judgment_run_id` 非空，语义是“已经被某次判断使用的证据”；Creator 需要先独立摄取 Source、原始 turn 和 Evidence，再决定是否形成 Claim/Judgment，所以不能强塞进去。

现有 `route_cognition_segments` 和 `segment_geometry_sources` 继续拥有正式赛段几何准入与 provenance。Creator 只提出 World Change，不复制、不覆盖这些对象。

因此本规格新增 Creator 私有表族，不修改：

- `users`
- `activities`
- `segments`
- `segment_efforts`
- `route_books` / `route_versions`
- 现有 Route Cognition 表

## 3. 真值表

### 3.1 `creator_workspaces`

| 列 | 约束/用途 |
|---|---|
| `id text` | PK；沿用 Runtime 安全 workspace ID |
| `mission text` | 非空 |
| `status varchar(16)` | `active / completed / archived`；v0 只写 active |
| `current_revision bigint` | 非负；每次事件 CAS +1 |
| `created_at / updated_at timestamptz` | 数据库时间 |

这是 revision 所有者，不保存大 Context 或 View。

### 3.2 `creator_workspace_events`

| 列 | 约束/用途 |
|---|---|
| `workspace_id text` | FK workspace，`ON DELETE RESTRICT` |
| `revision bigint` | 与 workspace 内事件顺序一致 |
| `event_id text` | 客户端幂等身份 |
| `event_type varchar(64)` | 当前 Creator event enum |
| `schema_version smallint` | 历史事件为 1；仅 evidence-only `creator.judgment_proposed` 允许 2 |
| `base_revision bigint` | 必须等于 `revision - 1` |
| `occurred_at timestamptz` | 领域事件时间 |
| `principal_id text` | 实际提交 principal；不能只相信 payload actor |
| `principal_product / principal_environment / authorized_capability text` | 认证层写入的授权收据；重放时可审计 Agent proposal 与 Tim reviewer decision |
| `payload_json jsonb` | exact validated event |
| `payload_sha256 char(71)` | `sha256:<64 hex>`，用于 idempotency/conflict |
| `derivation_key_id / derivation_signature / derivation_prior_records_hash` | interpretation/task/calibration/promotion/schema-v2 judgment 的 reducer attestation；普通事件必须为空 |
| `committed_at timestamptz` | 数据库提交时间 |

关键约束：

- PK `(workspace_id, revision)`；
- UNIQUE `(workspace_id, event_id)`；
- CHECK `revision > 0 AND base_revision = revision - 1`；
- CHECK hash 格式；
- 表只允许 INSERT；数据库角色撤销 UPDATE/DELETE，迁移/修复角色例外且需审计。

事件是唯一长期真值。下面所有表都是同事务投影，可由事件重放校验或重建。

## 4. 必要投影表

### 4.1 `creator_sources`

保存 `(workspace_id, source_ref)`、source kind、content hash、不可变 `immutable_ref`（Git blob/provider revision/content-addressed object）、provenance、当前 rights decision/policy/reason、source 与 rights 对应 event revision。UNIQUE `(workspace_id, source_ref)`。同一 `occurred_at` 可以有多次 rights 变化，“最新”必须按 workspace event revision 判定，不能按 event ID 或时间字符串打破并列。

rights 变更必须追加新 event，再更新投影；不能直接改投影冒充事件。

实现中另有窄表 `creator_rights_checks` 保留每个 `rights_check_id`，使历史 check identity 在数据库层也不可复用；`creator_sources` 仍只缓存当前 rights。否则旧 check 被新 check 覆盖后，数据库会接受 TypeScript reducer 无法重放的重复 ID。

### 4.2 `creator_source_messages`

保存 exact raw turn：

- `turn_id`
- `source_ref`
- `source_message_ref`
- `source_role`
- `actor`
- `authorship_basis`
- `raw_text`
- `content_hash`
- `subject_refs jsonb`
- 可空的 `interaction_proposal_id / interaction_statement_hash / interaction_response`
- `event_revision`

关键约束：

- PK `(workspace_id, turn_id)`；
- UNIQUE `(workspace_id, source_message_ref)`，与 Runtime 一致，在整个 workspace 防同一原始消息跨 source 重复导入；
- interaction 四列必须全空或按协议全有；有 interaction 时 `source_role='user' AND actor='tim'`；
- 为 decision 精确 FK 建 UNIQUE `(workspace_id, turn_id, interaction_proposal_id, interaction_statement_hash, interaction_response)`。

### 4.3 `creator_evidence_items`

保存 `(workspace_id, evidence_id)`、source ref、subject ref、raw observation、observed time、event revision。它是 Creator 私有摄取证据，不替代现有 `evidence_items`。

只有某条 Domain Claim 进入既有 Judgment/World Change 流程时，才由显式 adapter 建立到现有 `evidence_items` 或未来 Published World provenance 的关系。

### 4.4 `creator_judgments`

一行代表一个 Agent proposal 及其派生当前状态：

- proposal ID、judgment key、subject ref；
- statement、statement hash、typed value JSON、temporality、review_at；
- status：`proposed / tim_confirmed / rejected`；
- `supersedes_proposal_id`、`superseded_at`；
- Context compiler version、normalized request、request hash、context hash；
- model ref、proposal reason、proposal event revision；
- decision ID、responded_at（投影缓存）。

关键约束：

- PK `(workspace_id, proposal_id)`；
- UNIQUE `(workspace_id, proposal_id, statement_hash)`，供 decision 精确 FK；
- UNIQUE `(workspace_id, proposal_id, judgment_key)`，供 replacement 同 key FK；
- partial UNIQUE `(workspace_id, judgment_key) WHERE status='proposed' AND superseded_at IS NULL`；
- partial UNIQUE `(workspace_id, judgment_key) WHERE status='tim_confirmed' AND superseded_at IS NULL`；
- replacement 用复合 FK `(workspace_id, supersedes_proposal_id, judgment_key)` 指向同 key 旧 proposal；
- 非 permanent judgment 必须有 `review_at`。

### 4.5 `creator_judgment_turns` / `creator_judgment_evidence`

两张窄连接表保存 proposal 的 source turn refs 和 evidence refs，均使用复合 FK 约束 workspace 内身份；UNIQUE 防重复。不要把这些引用只塞在 JSONB 里，否则删除/重放和 Context 查询没有可靠关系约束。

### 4.6 `creator_judgment_decisions`

保存 decision ID、proposal ID、response turn ID、response、expected statement hash、event revision、reviewer principal ID。

关键约束：

- UNIQUE `(workspace_id, decision_id)`；
- UNIQUE `(workspace_id, proposal_id)`，一份 proposal 只能回答一次；
- UNIQUE `(workspace_id, response_turn_id)`，一条 Tim action 不能回答多个 proposal；
- FK `(workspace_id, proposal_id, expected_statement_hash)` → judgment 的 exact statement；
- FK `(workspace_id, response_turn_id, proposal_id, expected_statement_hash, response)` → source message 的 exact interaction；
- reviewer principal 来自认证层/事件 envelope，不能由模型 payload 自报。

这两组复合 FK 是数据库层最关键的不变量：即使应用漏检，也不能用普通“我同意”、另一条 proposal 或旧 statement hash 提交 Tim 判断。

### 4.7 `creator_judgment_contradictions`

保存 contradiction ID、目标 judgment、reason、状态、resolution、resolution ref、record/resolved event revision。

`contradicting_ref` 在数据库中拆成三个可空 FK：evidence、turn、judgment；CHECK `num_nonnulls(...) = 1`，避免不可校验的 polymorphic string。partial index 支持按 workspace/subject 查 unresolved contradiction。

### 4.8 Context Interpretation & Promotion v1 投影

`20260806_creator_ctx_v1` 增加四张表，不修改 Rider 或路线核心表：

- `creator_turn_interpretations`：模型对精确原话的可替代解释、作用域、认识状态、替代解释、反证、关系和生成 Context；它不是 Tim 判断。
- `creator_task_states`：`task_ref` 的 objective、focus、acceptance、open loops 和精确 Tim 原话依据；同一 task 只有一个未替代状态。
- `creator_behavior_calibrations`：预测与观察结果分开，保存 authority 和所用 Context refs；结果型升格还必须携带同主体 real-world Evidence，不能只自报标签。
- `creator_judgment_interpretations`：长期判断到解释的关系 lineage，双端都受 workspace 内复合 FK 约束。

`creator_judgments` 同步增加 proposal event type、task Context、interpretation refs 与 promotion basis。历史 schema v1 的 conversation judgment 保持冷回放，但所有在线 append 入口拒绝新写 v1 judgment；新 `CreatorAgentV0` 发出的 schema v2 `creator.judgment_proposed` 仅允许 route/domain Evidence，禁止引用 conversation turn。新的对话长期判断只能走 interpretation → mechanical promotion → exact Tim response。

每条 interpretation 关系投影还保存完整 normalized Context request，而不只有两个 hash；support/counterevidence 只允许同主体、权利允许的原始 turn 或 Evidence。promotion 要求专用 capability、固定 engine/compiler identity、JavaScript safe positive interpretation budget、精确 Tim 作者与匹配项目。Task update 绑定 source interpretation 和固定 engine identity，稳定字段只能从前态复制。完整 Context hash 重放只由 TypeScript reducer/compiler 所有；HTTP Store 仅在 reducer 对精确前序 event prefix 预演通过后用 Ed25519 私钥签发 attestation，Python 只持公钥，在落盘前重算 payload/prefix/principal/capability 并验签，数据库再强制派生事件证明字段非空。每把验签公钥还显式限制 principal、environment 与 capability；bearer capability 或 Python verifier 单独都不能签发证明。

## 5. 一次 append 的事务算法

所有 event 走同一事务函数/服务，不给调用方直接写投影。

### 5.1 首个 `workspace_started` 原子 bootstrap

空库没有 workspace 行，不能走普通 CAS。`workspace_started(base_revision=0)` 使用专用事务：

1. 先查 `(workspace_id, event_id)`；已有同 hash 返回 revision 1，不同 hash 返回 conflict。
2. `INSERT creator_workspaces(..., current_revision=1, mission=payload.mission)`；workspace ID 冲突时再次查 event ID：同 event 收敛，否则返回 workspace already exists/stale。
3. 同事务 INSERT revision 1 的 `workspace_started` event 与初始化投影。
4. 任一 INSERT/约束失败则整个事务回滚，不能留下“有 workspace、无首事件”的半成品。

两个并发 bootstrap 只有一个 workspace INSERT 成功；另一个等待唯一约束后按 exact event ID + payload hash 幂等收敛或明确冲突。`creator_workspaces` 是事件流的 revision/查询投影，`workspace_started` event 仍是 mission 与创建事实的长期真值。

### 5.2 后续 event 通用 append

1. 按 `(workspace_id, event_id)` 查已有事件。
   - hash 相同：返回原 committed revision，幂等成功；
   - hash 不同：409 conflict，不做任何写入。
2. 执行 CAS：

```sql
UPDATE creator_workspaces
SET current_revision = current_revision + 1, updated_at = now()
WHERE id = :workspace_id AND current_revision = :base_revision
RETURNING current_revision;
```

3. 未返回行：重新检查 event ID；若仍不存在，返回 stale revision conflict。
4. INSERT event，revision 使用 CAS 返回值。
5. 按 event type 更新对应投影；所有 FK/partial unique/check 在同事务生效。
6. COMMIT 后返回 `event_id + committed_revision + payload_hash` receipt。
7. TypeScript 必须按 receipt 重读；连接中断且无法确认 commit 时返回 `reconciliation_required`，不能重做一个新 event ID。

两个相同 base revision 的并发 writer 最多一个 CAS 成功；另一个只能通过同 event ID 幂等收敛或显式 stale conflict。

## 6. Projection-native Context 查询与重放（Shadow v0 已实现）

Context 的业务语义仍只有一份：TypeScript reducer/compiler。Python 不复制 rights、freshness、supersession、omission 或 budget 规则，而是从关系投影重建 13 类已持久化的 `CreatorStoredEvent`，再由 TypeScript 走同一个 reducer/compiler。事件 metadata 与认证 receipt 可从 append-only event index 读取，但事件正文明确不得读取其中的 `payload_json`，否则两条路径会共享同一个错误而失去漂移检测价值。

内部接口 `GET /internal/creator/workspaces/{workspace_id}/projection-records?expected_revision=N` 只接受精确 revision，并返回 `{revision, records, digest}`。关系重建使用以下确定性规则：

- `source_turn_refs`、`evidence_refs` 与 `context_subject_refs` 是去重后按 JavaScript UTF-16 排序的数组；TypeScript 模型动作、TypeScript 事件和 Python append 三层同时拒绝非规范顺序；
- `creator_judgment_turns` 同时包含 proposal 来源回合与后来 decision response turn；重建 proposal 时只取 `source_message.event_revision < proposal_event_revision` 的回合，防止未来确认倒灌进过去 Context；
- 时间统一还原为毫秒精度 UTC `Z`；typed scalar、原文、rights 历史、contradiction/resolution 和 authenticated principal receipt 均逐字段还原；
- projection records 必须覆盖 `1..expected_revision` 的连续前缀，event type、base revision、capability 与 workspace 必须精确匹配。

TypeScript `ProjectionVerifiedCreatorContextCompiler` 在调用模型前执行：

1. 从 event truth 编译 Context/Manifest；
2. 从 Agent 已用于读取 event truth 的同一个 Store 实例读取同 revision 的 projection records，禁止单独注入第二数据源，并比较顶层 revision、digest revision 与完整 canonical record stream；
3. 将 event truth 冷重放得到的 projection digest 与同一事务读取的数据库当前缓存比较，覆盖 current/pending status、supersession、最新 rights、decision 与 unresolved contradiction；
4. 对 projection records 冷重放，再用唯一 compiler 编译同一 normalized request；
5. 比较完整 Context/Manifest，而不只比较摘要；
6. revision/read/replay/record/digest/Context 任一漂移都 fail closed，不调用模型、不写新事件，并写一条只含 refs 的 hash、Context hash、revision 和 reason code 的 JSONL 告警；告警本身写入失败时仍保持关闭。

告警不保存 source text、evidence、statement 或 event ID 原文；event ID 只保存 hash。请求内不做静默修复，人工修复必须另开受控命令。

编译规则仍保持：

- 当前 judgment：`status='tim_confirmed' AND superseded_at IS NULL AND (review_at IS NULL OR review_at > :as_of)`，且所有实际加载来源的最新 rights 为 allowed；
- pending proposal：`status='proposed'`，同时满足 freshness 与 rights；
- Evidence：当前/pending judgment 连接的必需证据优先，再按 subject/time 取可选证据；
- contradiction：未解决且目标 judgment 与 subject 匹配；
- source revision：从实际加载的 message/evidence 回 join source；
- omission 计数：rejected/superseded/resolved/subject mismatch/rights not allowed/review due/budget。

每次结果携带 workspace revision。Shadow v0 在一个 `REPEATABLE READ, READ ONLY` PostgreSQL 事务中读取全部关系投影，并使用显式 `expected_revision` 与读取首尾 revision fence；因此合法 append 或不更新 revision 的人工 repair/tamper 都不能被跨查询拼成一个从未真实存在的混合 Context。若未来需要读取任意历史 revision，再单独设计 `through_revision` 快照，不能用当前可变投影假装历史真值。

当前未挂载 Shadow、没有真实 LLM。此阶段的线性化点定义为 exact projection snapshot 被门禁接受的时刻；门禁之后发生的撤权不会让本次快照倒流变化。接入任何会接收 raw Context 的真实模型前，必须另行明确撤权语义并通过 hard gate：若要求撤权 commit 后零披露，单纯在模型调用前重查 revision 只能缩短竞态窗口，不能闭合，必须采用数据库/advisory lease、read epoch/token 或不向外部模型发送 raw material。

原有 projection digest 保留为窄诊断入口，不再承担完整漂移门禁。完整门禁比较 event truth 与关系投影的 canonical records，以及两次独立冷重放得到的 Context/Manifest。

## 7. 迁移和混合版本顺序

1. 先新增空表、约束和内部 repository/service；不改旧表、不 backfill。
2. CI 临时 PostgreSQL 跑 upgrade/downgrade/upgrade、两个并发 CAS、相同/冲突 event ID、exact decision FK、冷重放对账。
3. TypeScript 增加内部 API Store adapter，仅运行 Shadow；JSONL 仍保留为对照，不双写生产真值。**本切片已实现**。
4. 用天龙山同一组事件比较 JSONL、Postgres event truth 与关系投影重建的 Context/Manifest，并人工篡改关系投影验证模型调用前停机。**Shadow v0 已通过真实 PostgreSQL → FastAPI wire response → 同一个 TypeScript HTTP Store → drift guard → Agent 组合测试；尚不是生产网络、认证或真实模型接线验收**。
5. 通过后才启用一个内部 Creator workspace；此时 Postgres 成为该 workspace 的唯一事件真值，不能同时接受 JSONL 写入。
6. 生产验证稳定后再讨论 World Change/Published World migration；Rider 表族另开独立纵向切片。

回滚：功能开关停止新 Creator workspace 写入；已写事件保留只读。migration downgrade 只允许在确认无生产 Creator 事件时执行；有数据后使用向前修复，不删除事件真值。

## 8. 首个数据库验收

- 空白 PostgreSQL/PostGIS 上 Alembic upgrade 成功，revision ID 不超过 32 字符。
- 两个相同 base revision writer 不会都提交。
- 同 event ID 同 payload 幂等；不同 payload fail closed。
- 同 source message 不能重复写入。
- 普通 Tim prose、Agent principal、错误 proposal ID、错误 statement hash 均无法形成 decision。
- 首个 workspace 并发 bootstrap 只能形成一条 revision 1 event，失败时不留孤儿 workspace。
- 每条 event 保存真实 principal/capability 收据，冷重放不依赖注入万能 principal。
- source rights 撤销或 judgment 到达 `review_at` 后，raw material/current judgment 不再进入 Context，并有明确 omission。
- 新 replacement 未确认时旧判断仍 current；确认后 partial unique 与 projection 只留下新 current。
- transaction 在 event/projection 任一点失败时全部回滚。
- connection loss after commit 可用 event ID receipt reconciliation 收敛。
- Postgres 冷重放与 JSONL/TypeScript Context hash 一致。
- migration 不修改四张受保护核心表，也不让 Rider 读取 Creator raw text。

## 9. 会让方案改变的新证据

- 若真实查询证明事件 JSONB 重放足够快、projection 从未被在线读取，可进一步减少投影表；当前 Context 已明确需要 subject/status/ref 查询，所以不能先假设。
- 若生产边界改为独立 Node Creator 服务并获得隔离数据库账号，可以重新评估 TypeScript 直连；在此之前坚持 Domain Plane API。
- 若 exact decision 复合 FK 在真实 Alembic/Postgres 中造成不可接受的写入复杂度，允许退到单个数据库事务函数/trigger，但不能退成“应用记得校验”。
- 若 Creator v0 的事件合同在真实 UI/provider 接线中频繁变化，暂停 migration，继续 JSONL Shadow；不要用不停改表掩盖合同未稳定。

## 10. v0 实现边界

当前 PostgreSQL service 接受信息/判断/解释闭环所需的 13 类事件：workspace、source、rights、conversation turn、evidence、interpretation、task state、behavior calibration、legacy evidence judgment、guarded promotion、decision、contradiction record/resolve。Claim、通用 Eval、Human Review、World Change、Published World、Rider persistence 仍由 TypeScript Shadow 合同保留，不能借本 migration 偷渡入库。

`human_review_requested` 也不在这 13 类事件内，因此 contradiction resolution 只接受 same-subject evidence、turn、judgment，或已确认的 replacement；TypeScript Shadow 中指向 human-review request 的合法 resolution 要等该事件族进入后续 migration，当前 HTTP Store 会在发请求前明确拒绝，不会到服务端才得到隐式 422。

内部 API 使用 `GET /internal/creator/workspaces/{id}` 与 `POST /internal/creator/workspaces/{id}/events`。认证 principal 只能由部署方注入的 bearer authenticator 生成；普通写入 body 只有 event，派生写入 body 还必须带 Ed25519 `derivation_attestation`，两者都不能自报 principal。仓库没有生产 token verifier、签名私钥/验签公钥配置，也没有把 router 挂到公开 FastAPI app。
