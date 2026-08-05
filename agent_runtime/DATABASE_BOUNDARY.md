# Agent Runtime 数据库边界（首个可执行版本）

## 结论

VELO 不需要另起一套“Agent 万能数据库”，更不能让 TypeScript Agent 直接摸 SQL/PostGIS。现有 Python Domain Plane 已经拥有大量可复用的路线真值与证据台账；新库表只补它没有的事件、Claim、发布版本与骑友规划过程。

Creator 与 Rider Consumer 在数据库层也必须低耦合：分别写自己的事件和工作对象；骑友侧只读已发布 `world_revision`，反馈只能写 proposal。两边不能共用一张 `agent_sessions` 再靠 `role` 区分。

## 现有表的真实职责

| 现有对象 | 首版用途 | 不允许偷换的语义 |
|---|---|---|
| `segments` | 已存在的赛段几何与距离、爬升、坡度等基础指标 | 不是版本化 Traversal，也不承载临时路况或 Agent 状态 |
| `segment_geometry_sources` | 赛段几何来源、坐标系、内容/几何哈希、标准化版本与质量状态 | 当前 source type 还不包含 Strava 投影，不能伪装成 `admin_import` |
| `route_cognition_segments` | 经审核可进入路线认知的 segment 白名单，并锁定 `geometry_hash` | 不等于“热门”或“推荐”，只代表准入与几何版本 |
| `route_books` / `route_versions` | 用户或系统最终保存的完整路线及不可变几何快照 | 不是 Agent 草稿，也不保存会话 transcript |
| `route_segments` | 一版正式路线的顺序组件、方向、裁切比例、几何哈希和人工接受依据 | 不保存腾讯一次性 connector，也不反向改变 route version |
| `judgment_runs` | 算法、Agent、人工审查的判断运行与置信状态 | 不等于一个具体 Claim，也不等于发布记录 |
| `research_questions` / `research_runs` | 外部研究的原因、停止条件、检索运行和 unknown/contradiction | 不面向骑友暴露原始研究过程 |
| `evidence_items` / `judgment_run_evidence` | 原子证据及其支持、反驳、不可核验关系 | Evidence 永远不是 Fact；UGC 不因入库自动成为路线真相 |

因此第一阶段不修改 `users`、`activities`、`segments`、`segment_efforts`，也不复制上述表。

## 三个明确的数据面

### 1. Creator 私有面

Creator 首个生产持久化候选（表名与约束以 [`CREATOR_POSTGRESQL_SPEC_V0.md`](CREATOR_POSTGRESQL_SPEC_V0.md) 为准）：

- `creator_workspaces`：一次路线认知建设任务的身份、mission、状态与 current revision。
- `creator_workspace_events`：append-only 原始事件与实际 principal/capability 收据，唯一键 `(workspace_id, revision)` 与 `event_id`；raw Evidence 只在这个权限面可见。
- `creator_sources`：材料的 provider/source identity、rights、content hash、不可变 blob/provider revision 与 captured time；解决当前 `evidence_items` 必须“已被判断使用”才能存在的问题。
- `creator_source_messages`：精确原始 turn、通道角色、实际作者、作者依据与可选的 exact judgment response；同一来源消息不可重复摄取。
- `creator_judgments` / `creator_judgment_decisions`：Agent proposal 与 Tim exact response 分表，并用 proposal/turn/statement hash 复合约束绑定。
- `creator_judgment_contradictions`：未决矛盾、替代与解决链；不能把 contradiction 折成 false 或静默覆盖。
- `knowledge_claims`：subject、predicate、typed proposed value、temporality、valid time、状态。
- `knowledge_claim_evidence`：Claim 与现有 `evidence_items` 的 support/contradict/unknown 关系。
- `claim_evaluations`：grader/version/verdict/reason；不把一个裸 confidence 数字当作真伪。
- `world_change_proposals`：只提交拟变更 Claim 与目标 World revision；没有直接 publish 权限。

### 2. Published World 共享只读面

- `world_revisions`：一次原子发布的 revision、审核/发布人、发布时间、前一 revision。
- `world_fact_versions`：subject/predicate/typed value、`valid_from/valid_to`（现实有效期）、`recorded_at/superseded_at`（系统时间）、provenance、freshness、publication revision。
- `traversals` / `traversal_versions`：稳定路线认知身份与不可变方向几何版本；核心引用必须锁定 revision + geometry hash。

首版 `Traversal` 身份只能以 `route_cognition_segments.(segment_id, geometry_hash)` 作为已审核几何锚点；`direction/start_fraction/end_fraction` 实际属于 `route_segments`，只在某个既有 `route_version` 的组件关系里成立，不能假装是白名单赛段自身的字段。若要把某条既有正式路线组件投影为 Traversal，必须显式 join 两表并保留 route/version/component identity；通用、跨路线的方向与稳定裁切仍需未来的 `traversals` 表族承载。

### 3. Rider Consumer 私有面

- `rider_agent_sessions` / `rider_session_events`：骑友原始 turn、mainline/branch、明确决定与 revision；与 Creator 事件物理分表。
- `rider_session_snapshots`：重放缓存，可删可重建，永远不是真相源。
- `rider_agent_runs` / `rider_trace_events`：绑定 committed session revision、intent hash、world revision、模型/工具预算、结果与错误。
- `ride_plan_drafts` / `ride_plan_versions`：某次请求下的候选与修订链，绑定当前 intent 与 World revision。
- `ride_plan_legs`：顺序、role、source adapter、from/to、geometry hash。`core` 必须引用 immutable Traversal version；腾讯只产生 access/connector/exit/return，并绑定 provider observation。
- `rider_feedback_proposals`：骑友反馈的原文、目标 Traversal/Plan、时效范围与 consent；只进入 Creator 队列。

## 必须由数据库和 Runtime 双重固定的约束

1. 同一 Session/Workspace revision 只能追加一次；stale base revision 拒绝写入。
2. Agent Run 固定绑定 `intent_hash + session_revision + world_revision`，旧结果不能覆盖新请求。
3. Plan leg 必须首尾连续；core 的 traversal revision 与 geometry hash 必须匹配已发布版本。
4. 腾讯 observation 不能写成 core，不能覆盖 canonical geometry。
5. Claim 没有合格 Evidence/Eval 只能停在 proposed；World 发布必须在单事务内生成新 revision。
6. temporary Fact 必须有有效期或下一次复核时间；unknown/contradiction 是正式状态，不能折算为 `false`。
7. 原始 Evidence、精确家庭位置、raw Provider response 不进入 Rider Context。

## Strava 赛段不是可直接复制的公共真值

Strava 官方 API 的 `/segments/explore` 确实能按 bounds 返回热门 riding segments，但所有调用都需要认证，而且新应用有 athlete capacity 与 read rate limit。更关键的是，2026 API Agreement 明确把 segment/leaderboard 纳入 Strava Data，并限制复制 Strava 功能以及向其他用户展示特定用户数据。

因此首版 ingestion 必须 fail closed：

- Strava segment id/link 只作为 `source_record` / `research_question` 的候选发现线索，不自动进入 Published World。
- 未完成 API Agreement、展示方式与数据保留审查前，不持久化 Strava geometry/popularity 为 VELO canonical fact，也不把 Strava 热度直接用于骑友推荐分。
- 优先用 VELO 自有 Activity、骑友明确授权的 GPX/FIT、管理员实测或其他许可来源重建并核验核心 Traversal；发布时保留独立 geometry hash 与 provenance。
- 如果未来获准使用 Strava 数据，adapter 必须记录 provider object id、captured time、rights/display policy、删除/失效处理与 rate-limit observation，不能冒充当前 `admin_import`。

依据：[Strava API reference](https://developers.strava.com/docs/reference/)、[rate limits](https://developers.strava.com/docs/rate-limits/)、[2026 API Agreement](https://www.strava.com/legal/api)、[API changelog](https://developers.strava.com/docs/changelog/)。其中 changelog 已预告 2026-09-01 起部分新 segment 访问将要求获批的 Extended Access；在许可与产品展示方式明确前，Creator 的 `rights_checked` 必须保持 fail closed。

## 当前已落的数据库边界

Creator Persistence Slice v0 已新增 Alembic revision `20260806_creator_pg_v0`：只创建 `creator_*` 事件真值与信息/判断投影，不修改现有 Route Cognition、路线或 Rider 核心表。Python service 用单事务持有 revision CAS、event id/hash 幂等、投影与 exact Tim decision 绑定；事件表有 append-only trigger。

TypeScript 仍通过 `CreatorWorkspaceStore` 内部 HTTP adapter 访问，不直接连接 SQL。Python router 只能由部署 composition root 注入 bearer authenticator 后显式挂载；本切片未在 `app/main.py` 暴露路由，也未配置生产 secret 或部署 migration。

projection-native Context/漂移停机 Shadow 已实现：关系投影在一致只读快照中重建事件，由同一个 TypeScript reducer/compiler 对账，并在模型调用前 fail closed；它仍未生产挂载。下一刀不是继续扩大表族，而是为一个内部 workspace 建立真实登录 Tim 审核身份、内网挂载和 Shadow 观测。Published World、Rider persistence、腾讯、Strava 与真实 LLM 继续分开验收；真实 LLM 接收 raw Context 前还必须关闭并发撤权的披露竞态。
