# ADR-016: 为什么在线 Agent 的 Capability、Approval 与 Side Effect 必须显式化

> **一句话核心决策：在线 Planning Agent 的每个动作都必须经过 deny-by-default 的环境与 Capability 注册、用户/服务身份及数据范围授权、schema/revision 与确定性领域校验，并在需要时绑定一次精确用户批准；有副作用的执行必须幂等、可记账、可重放而不重复生效，公共真相和管理员能力对在线 Agent 永远不可达。**

## 1. 状态与适用范围

**Proposed — A1.4，等待 Orchestrator 审查。**

本文承接 [ADR-013](./013-为什么区分骑前静态规划与骑中实时导航.md)、[ADR-014](./014-为什么在线规划采用单一有界主Agent与确定性工作流.md) 与 [ADR-015](./015-为什么世界事实会话运行与长期记忆必须分离.md)，只裁决在线骑前规划的能力、审批和副作用边界。

Proposed 不授权 Capability Engine、Approval UI、Side-effect Ledger、Contribution、Runtime、schema、数据库、API、小程序、真实 Provider、真实导出或部署。精确字段、状态枚举和序列化合同延后 A2。

## 2. 当前代码事实

- 当前运行代码没有在线 Planning Agent 的 Capability Registry、Approval Gate 或 Side-effect Ledger。
- `export_service` 已检查 owner、admin、public route 与 share link 等资源权限；这是“谁可访问资源”，不是用户是否批准 Agent 现在执行某个 effect。
- 当前 `create_route_export` 会读数据库、生成 GPX/TCX、写 storage、创建 job/artifact 并提交数据库；它不能充当未来无副作用的 `export.prepare`。
- 手画路线保存已有 `client_request_id + request_hash` 幂等记录，可作为相同请求安全重试的参考，但不是通用 Agent ledger。
- route cognition 的 `write_guard` 和 formal writer 会检查成功的人审 JudgmentRun、候选状态、目标与 revision/hash，再允许正式关系写入；这是 canonical write fail-closed 的现有参考。
- Route Draw 的明显绕行确认是在处理某段路线的领域风险，不等于通用副作用批准。
- RouteBook、腾讯、海拔和导出服务是现有确定性能力；在未来 Tool Registry 明确注册之前，它们不会自动成为 Agent 工具。
- 当前没有生产可用的骑友贡献 proposal、状态、反馈、credit 与 appeal 闭环。

## 3. 考虑过的方案

### 方案 A：只在 Prompt 中提醒模型谨慎

实现最少，但 Capability、批准、重试和副作用只靠模型自律，无法证明 raw Provider、公共发布或重复导出不可达，因此拒绝。

### 方案 B：所有动作都弹确认

表面最安全，却会让只读查询、Session 修订和同一规划意图下的高层 Provider 查询不断打断用户；确认疲劳最终会降低而不是提高有效控制，因此拒绝。

### 方案 C：只依赖现有 API / resource permission

现有权限能回答“当前身份是否有权访问这条路线”，但不能回答“用户是否批准 Agent 用这版 Plan、这个目标和这份披露现在生成制品”。**resource permission is not approval**，因此拒绝。

### 方案 D：Capability + effect scope + approval + ledger

把“能力能否触达”“身份/数据能否访问”“领域结果是否合法”“用户是否批准这次 effect”分开，由代码按分阶段门禁执行，并对有副作用的结果做幂等与 ledger。选择此方案。

## 4. 正式决策与门禁顺序

所有在线 Agent 动作先经过能力与访问门禁；需要幂等 key / ledger 的 effect 在新批准前先查询已有 effect，再对首次执行做最终原子占位：

```text
environment allowlist
→ capability registry
→ user + service identity / data-scope authorization
→ normalize exact effect identity
→ preflight idempotency lookup
    same key + same exact effect + committed
      → return prior result / artifact ref; no fresh approval or execute
    same key + same exact effect + started | outcome_unknown | reconciliation_required
      → reconcile or return pending/unknown; no execute
    same key + different effect identity
      → IDEMPOTENCY_CONFLICT; fail closed
    no prior effect
      → schema + stale revision check
      → deterministic domain validation
      → user approval when required
      → atomic reservation / final duplicate guard
      → execute
      → side-effect ledger + Trace
```

exact effect identity 至少包含 capability、tool name/version、effect scope、targets、payload hash、相关 Session/Plan/asset revisions、disclosure summary 与 idempotency key。任何未注册能力、环境不允许的工具、越过用户或服务 scope 的请求都 fail closed。批准不能补救前置门禁失败；atomic reservation 必须在批准后、execute 前完成，关闭并发请求同时通过 preflight 的竞态。

## 5. 四类门禁必须分开

1. **Capability**：该环境是否注册并允许这个高层动作。
2. **Resource / data-scope authorization**：当前 user identity 与 service identity 是否都可访问所需对象和最小数据。
3. **Deterministic validation**：payload、revision、几何、硬约束、来源和目标是否有效。
4. **Approval**：用户是否对当前展示的一次精确 effect 表达了有效意图。

因此同时成立：**resource permission is not approval**；**approval is not validation**。用户确认不能让 stale Plan、非法几何或无权数据变成有效请求。

## 6. Deny by default 与 pass-through scope

在线 Agent 不是 admin、superuser 或业务服务的完整权限继承者。Domain API 必须共同检查 user identity、service identity、capability 与 data scope；Agent 只能 pass through 当前任务已授权的交集。

未注册工具默认不可达。raw Tencent/provider、任意网络、SQL/ORM write、shell、直接 GPX generator 和任意 RouteBook 更新均不因底层服务存在而开放。

未来在线环境可注册或允许 Agent 提议的高层能力只包括受控类别：`world.read`、`user_context.read_authorized`、`contribution.status.read_own`、`session.update`、`plan.draft.create|revise`、`plan.validate|compare|select`、`generate_candidate_plans`、`saved_place.propose|create|update|delete`、`memory.propose|create|update|delete`、`contribution.draft|submit|withdraw`、`export.prepare|commit` 与 `share.create`。列入此集合仍不等于自动执行；每次调用继续受 Tool Policy、环境、scope、validation、approval 和 ledger 约束。

## 7. Tool Policy 的独立维度

每个未来高层工具必须独立声明：

- `capability`；
- `effect_scope`；
- `approval_mode`；
- `data_classification`；
- `reversibility`；
- `idempotency`；
- timeout / retry policy；
- environment allowlist；
- Trace / ledger policy。

这些维度不能互相代替。例如个人资产通常可逆，不代表可以无批准写入；Provider 查询是读取，不代表没有外部数据披露。

## 8. Effect Scope 矩阵

| Effect scope | 语义 | 在线边界 | 默认 Approval |
|---|---|---|---|
| `READ` | 已授权范围内只读，无权威写入或新增外部披露 | World FactPacket、已授权 Rider Context、校验/preview | `NONE` |
| `SESSION` | 当前 Session/candidate 的可逆临时状态 | reducer 推进；`plan.select` 必须来自用户选择 | 普通更新 `NONE`；选择 `EXPLICIT_INTENT` |
| `PROVIDER_QUERY` | Domain 内执行的有界外部读取与最小数据披露 | 只开放高层候选生成，raw Provider 隐藏 | 当前规划意图下 `EXPLICIT_INTENT` |
| `PERSONAL` | 持久、用户拥有且通常可逆的资产或偏好 | saved place、saved draft、explicit memory、个人设置 | `EXPLICIT_INTENT` 或 `CONFIRM_EXACT` |
| `CONTRIBUTION` | 可归因的骑友 proposal/evidence，进入共享审核队列 | 不是 canonical truth；可撤回、可看状态 | `EXPLICIT_INTENT` 或 `CONFIRM_EXACT` |
| `EXTERNAL_DELIVERY` | artifact、share、send 等 Session 外交付 | 目标/格式/revision/disclosure 精确绑定 | `CONFIRM_EXACT` |
| `CANONICAL` | 公共真相、发布、激活或 reviewer 决定 | 在线 Planning Agent 不注册 | `FORBIDDEN` |

## 9. Approval Mode 矩阵

| Approval mode | 含义 | 适用边界 |
|---|---|---|
| `NONE` | policy 与 validation 足够，不额外打断用户 | READ、普通 SESSION |
| `EXPLICIT_INTENT` | 当前用户通过无歧义话语或 dedicated UI 对可见动作表达直接意图 | 选择 Plan、高层 Provider 查询、明确保存、用户直接提交可见内容 |
| `CONFIRM_EXACT` | 用户确认精确目标、payload、revision 与披露摘要 | 敏感/精确个人写入、Agent 整理的贡献、导出/分享/发送 |
| `REVIEW_REQUIRED` | 授权 curation/reviewer 处理 canonical promotion | 不是普通用户批准，也不暴露给在线 Agent |
| `FORBIDDEN` | 能力不在在线环境注册，任何 prompt/批准都不能开放 | raw/admin/canonical 能力 |

`NONE` 不等于没有门禁；它仍须通过 capability、scope、schema/revision 和 domain validation。

## 10. Exact Approval Grant 的绑定与失效

一次 Approval Grant 只授权 **single exact effect**，有 expiry，默认 single-use。授权对象的稳定锚点是 `approval_request_id` 或 `proposed_effect_id`，不是最初提出请求的 Run；这允许同一 Planning Session 中 Run A 提议并停在 `APPROVAL_REQUIRED`，随后用户事件触发 Run B 恢复并消费同一 pending effect。授权绑定：

- user identity 与 service identity；
- Session 与 `approval_request_id` / `proposed_effect_id`；
- capability、tool name/version、effect scope；
- target refs 与 request/payload hash；
- base Session revision 与相关 Plan/asset revision；
- data disclosure summary；
- expiry、single-use 或明确 retry scope；
- idempotency key。

批准记录保留 `requested_by_run_id` 作为提议 provenance、`decided_by_user_event_ref` 与 `decision_recorded_at` 作为用户决定证据，并在首次真实消费时写入 `consumed_by_run_id`。只有同一 Session、同一 pending approval request/effect、相同 capability/tool/effect scope、targets/hash/revisions，且未过期、未撤销、未被其他 effect 消费时，后续 Run 才能恢复和消费；无关 Run 不能借用批准。Run ID 继续用于 provenance，不充当授权对象。

payload、target、revision、capability/tool 或 disclosure 任一变化，批准立即失效；过期或用户撤销同样失效。沉默不是批准；自然语言“是/可以”只有在当前恰好一个 pending approval 且 exact summary 已展示时才有效。

批准不能覆盖未来未定义的一串操作，也不能绕过领域校验。直接 UI 手势可以同时构成批准，只要用户看到的是这次准确 effect；不得为形式合规强制无价值二次弹窗。

## 11. Idempotency 与 Side-effect Ledger

`PROVIDER_QUERY` 的外部披露、`PERSONAL`、`CONTRIBUTION`、`EXTERNAL_DELIVERY` 与 `CANONICAL` 必须进入确定性 ledger。概念生命周期至少能表达：

```text
proposed → approval_required → approved → started
→ committed | failed | outcome_unknown
outcome_unknown → reconciliation_required → committed | failed | compensated
proposed | approval_required | approved → withdrawn | cancelled_before_start
```

这些是 A1.4 要求表达的状态语义，不冻结 A2 的精确枚举或 schema。安全重试必须沿同一 idempotency key 与 exact effect identity 查询或继续同一 effect，不得创建第二份写入、导出或发送：

- 已有相同 effect `committed` 时返回原 artifact/ref/result，不重新执行、不要求新批准、不再次消费 approval，并记录 `idempotent_replay_returned_prior_result` 或等价 Trace event；
- 已有相同 effect `started`、`outcome_unknown` 或 `reconciliation_required` 时，只能按 key/ledger 对账或向用户显示 pending/unknown，不得启动第二个 effect；
- 相同 key 对应不同 payload、target、revision、tool/capability 或 disclosure 时返回 `IDEMPOTENCY_CONFLICT` 并 fail closed；
- 尚无 effect 时，只有通过当前 schema/revision、deterministic validation 与 approval 后，才能原子 reserve exact effect；reservation 是 execute 前的最终重复保护。

deadline/cancellation/disconnect 在 `started` 前生效时必须阻止 effect 开始，保持 **zero real effect**。effect 已 `started` 后发生 timeout/disconnect，不能假定外部系统已回滚，也不能据此报告成功或失败；ledger 进入 `outcome_unknown` / `reconciliation_required`，用户状态保持 pending/unknown，并按 idempotency key 对账，最终才收敛为 committed、failed 或 compensated。response 丢失但 effect 已 committed 时属于上述 committed 相同 effect 重试，直接返回原结果。准确不变量是：deadline/disconnect 不得启动新的未 reserve effect，任何 retry 不得制造第二个 effect；系统不承诺已开始的外部 effect 不会在断连后完成。

失败、拒绝或撤回不能包装成成功。approval、effect 和 Trace 必须可关联；精确 schema 延后 A2。

## 12. Provider Query 与精确位置

在线 Agent 只能调用 `generate_candidate_plans` 等高层 Domain tool；raw Tencent/provider response、key、坐标串和随机错误文案不进入模型。

用户当前明确的规划请求可授权本轮必要的有界高层 Provider 查询，无需每个候选重复弹窗。Domain 只披露当前任务所需最少数据；精确 saved-place 坐标由 opaque ref 在 Domain 内解析，模型只看粗粒度 label。

Provider、披露分类、调用结果与错误进入 Trace / disclosure ledger。换 Provider 不改变 Agent capability，也不能扩大数据 scope。

## 13. Export prepare / commit

当前 `create_route_export` 是 effectful：它生成文件、写 storage、创建 job/artifact 并 commit，因此不能注册为未来 `export.prepare`。

未来必须逻辑拆分：

- `export.prepare`：只做 readiness、preview 与 exact approval summary；**zero artifact**、不写 storage/job/artifact、不 commit 数据库。
- `export.commit`：在 `CONFIRM_EXACT` 后创建实际 artifact；批准绑定格式、目标、Plan revision、payload hash 与披露摘要，并使用 idempotency + ledger 防止断线重建。

现有 owner/admin/public/share resource permission 仍须保留，但它不替代 export approval 或 Plan/domain validation。

## 14. Memory 与 Saved Place

Agent 可以 propose memory 或 saved place，不能自由自写长期 Memory。durable write 属于 `PERSONAL`，必须用户可见、可改、可删，并按敏感度选择 `EXPLICIT_INTENT` 或 `CONFIRM_EXACT`。

精确位置、敏感内容、删除或 Agent 主动建议写入必须展示 exact summary。已有 Profile、Activity、saved asset 或稳定产品字段的数据继续由 User/Business Domain 拥有，不复制到 Memory。

## 15. 参与式知识贡献闭环

允许的贡献包括 rider correction、local name、road-condition report、route variant、ride feedback 与 expectation gap。完整流程是：

```text
draft
→ explicit submit
→ attributable proposal/evidence
→ triage / corroboration / request-more-info
→ accepted or rejected
→ visible outcome and feedback
→ contributor credit where appropriate
→ correction / appeal
```

dedicated UI 中用户看到并主动提交的精确内容可构成 `EXPLICIT_INTENT`；Agent 从对话整理的提交必须展示内容、对象、范围、证据和署名方式并 `CONFIRM_EXACT`。骑友原始陈述/证据与 AI 整理结果必须分开保留，AI 改写不得冒充用户原话。

Contribution 始终是 proposal/evidence，不是 canonical truth。当前用户刚报告的路况可在本 Session 作为带来源的 scoped assumption；其他未验证报告只能标为 unverified advisory / unknown，不能静默成为硬事实。

贡献者必须能看到处理状态、补充材料、撤回（安全时）、接受/拒绝理由、反馈、适当 credit 与 correction/appeal。reputation 只能影响审核优先级，不能绕过证据、校验或人审；不做脱离骑手价值的 points/badges/streaks。

## 16. Canonical / Admin 禁止能力

以下能力对在线 Planning Agent 永远不可达：

```text
raw provider / raw Tencent / raw SQL / ORM write / shell / arbitrary network
direct GPX generator / arbitrary RouteBook update / user_data.admin_read
world.publish / claim.accept / route.activate / traversal.publish
dynamic_state.verify / contribution.review|accept|reject / public_route.publish
```

Canonical promotion 只在 Curation/Reviewer Environment 暴露 `REVIEW_REQUIRED`，并继续要求 evidence、corroboration/human review、target/revision/hash 校验。普通用户批准不能授予 reviewer 权限。

## 17. Replay 与 Shadow

Replay、Eval 与 Shadow 环境必须 **zero real effect**：不得真实查询 Provider、写个人资产/贡献、创建导出、发送分享或修改 canonical world。

重放只复用记录的 observation/effect outcome 和确定性状态演进；不能因为 Trace 中存在一次历史批准，就再次执行真实副作用。任何 capability/environment 隔离失败都应使 case 失败。

## 18. 与其他 ADR 和任务的关系

- ADR-013 回答“在线 Agent 允许规划什么”。
- ADR-014 回答“谁控制一次 run”。
- ADR-015 回答“状态和记忆属于谁”。
- ADR-016 回答“哪些能力可执行、怎样批准、怎样记录副作用”。
- A1.5 继续 blocked，负责旧 `app/agent` 命名迁移，不在本文执行。
- A2 定义 capability/approval/effect/contribution 的语言中立合同；A3/A4 用 ambiguous consent、stale approval、committed-response-loss retry、idempotency conflict、跨 Run approval resume、disconnect-before/after-start、unknown-outcome reconciliation 和 zero-effect replay 等案例验证。

## 19. Trade-off 与后果

我们接受 Tool Policy、exact grant、idempotency 和 ledger 带来的实现与审计成本，换取最小权限、批准不漂移、断线不重复生效、Provider 披露可追踪以及公共真相不可被在线模型写入。

同时避免所有动作弹窗：READ、普通 SESSION 和已由明确规划意图涵盖的有界高层 Provider 查询不重复确认，把注意力留给真正敏感或外部 effect。

## 20. 非目标

- 不实现 Capability Registry、Approval Gate/UI、Side-effect Ledger 或 Contribution 产品。
- 不定义数据库表、API payload、JSON Schema、状态枚举或 Runtime/framework。
- 不修改 export、RouteBook、腾讯、海拔、route cognition、Memory、API、小程序、测试、migration、依赖或部署。
- 不调用真实 Provider、DEM、storage/export、生产数据库/Redis，不产生用户可见或生产行为变化。
- 不自判 A1.4 PASS，不开始 A1.5/A2–A5。

## 21. Reopen triggers 与引用路径

以下证据可触发新 ADR 重评估：A3/A4 证明某分类无法表达真实失败；真实用户研究证明确认疲劳仍阻断核心规划；Provider/隐私/法规要求更小披露或更强批准；effect 无法用稳定 idempotency/ledger 对账；贡献闭环无法在 proposal 与 canonical truth 分离下提供用户价值。

引用：

- [ADR-013](./013-为什么区分骑前静态规划与骑中实时导航.md)
- [ADR-014](./014-为什么在线规划采用单一有界主Agent与确定性工作流.md)
- [ADR-015](./015-为什么世界事实会话运行与长期记忆必须分离.md)
- [Agent-First 文档入口](../agent-first/README.md)
- [Phase A 文件级实施规格](../agent-first/phase-a-implementation-spec.md)
- [产品决策 D-P07](../agent-rules/product-decisions.md)
- [现有导出权限](../../app/route_book/export_service.py)
- [现有导出工作流](../../app/route_book/export_workflow.py)
- [手画路线幂等参考](../../app/route_book/service.py)
- [路线认知写入门禁](../../app/route_cognition/services/write_guard.py)
- [VELO Orchestrator State](../../VELO_ORCHESTRATOR_STATE.yaml)
