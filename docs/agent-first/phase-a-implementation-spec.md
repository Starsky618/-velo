# VELO Phase A 文件级实施规格

> A0/A0C/A1.1/A1.2/A1.3/A1.4：`PASS / completed`；A1 parent 保持 `in_progress`。ADR-013–016 均已 Accepted；A1.5 已形成 Proposed ADR-017，当前 `in_review / READY_FOR_REVIEW / execution unauthorized`。A2–A5 继续 `blocked`。本文不实施 `app/agent` 代码迁移、Agent Runtime、Session、Run、Memory、Capability Engine、Approval UI、Side-effect Ledger 或 Contribution，不改变生产行为，也不构成部署或 A2 授权。

## 2.1 Repository Fact Baseline

### 仓库与 Git 基线

| 事实 | 执行时结果 | 证据 |
|---|---|---|
| 唯一远端 | `origin https://github.com/Starsky618/-velo.git`（fetch/push） | `git remote -v` |
| 默认分支 / 交付分支 | GitHub 默认分支与权威基线为 `main`；A0C 交付分支为 `codex/agent-first-a0-docs`，直接基于任务开始时的 `origin/main` | `git symbolic-ref refs/remotes/origin/HEAD`、`git branch --show-current`、`git merge-base` |
| 原始编写 HEAD | `44bdd95d61d3b3b622bc992978f15eda3e255730`，`fix(miniprogram): make route map actions tappable`；R1 证据在 `codex/agent-first-a0` 分支收集 | R1 evidence bundle 中的 `git-branch.txt`、`git-head.txt`、`git-log-1.txt` |
| 最新 `origin/main` | `2d58fe2d10b1dda2e67f26375bd82c2243df9597`，2026-08-02T09:48:14Z，`feat(miniprogram): polish personal settings (#34)` | 成功执行 `git fetch origin` 后的 `git rev-parse origin/main`、`git show` |
| 原始编写基线 | `44bdd95d…` 含与 A0 无关的 route-draw commit；A0C 因此在新工作树从 `origin/main@2d58fe2d…` 创建独立交付分支 | R1 evidence bundle、`git worktree list --porcelain`、`git merge-base` |
| A0 写入前工作树 | 原始编写工作树当时为 clean；A0C 不修改、reset、stash、rebase 或覆盖该工作树 | R1 evidence bundle 中写入前的 `git-status-short.txt`，以及 A0C 前后状态对比 |
| 主线移动 | 执行前本地 remote-tracking ref 为 `cb6a7406…`，首次 fetch 后为任务包已观察到的 `2d58fe2d…`；最终 fetch 仍为 `2d58fe2d…`，实施期间未再次移动 | 开始、结束两次 `git fetch origin` 后的 `origin/main` 读数 |

这里的“原始编写 HEAD”、“R1 证据分支”、“GitHub 权威基线”和“A0C 交付分支”是四个事实，不能合并叙述。A0C 只把已通过审查的 A0 文档应用到直接基于 `origin/main@2d58fe2d…` 的干净独立分支，不要求改变现有本地 `main` 或原始编写工作树。

> 上表保留 A0/A0C 执行时基线。A1.1 开始前已重新 fetch 并核实当前权威基线为 `origin/main@88dd16562d777e896859c0955920f7a52b7dd50e`；本轮独立分支直接从该提交创建。

> A1.2 开始前再次 fetch：A1.1 已通过 PR #36 合并，当前权威基线为 `origin/main@aa955edc67694fc2cbb628ec3f5caacc80e6d60c`；post-merge CI run `30754762304` 为 `2074 passed / 0 skipped` 且 fresh migration 成功。A1.2 专用分支 `codex/agent-first-a1-bounded-agent-workflow` 直接从该提交创建，初始状态 clean。

> A1.3 开始前再次 fetch：A1.2 已通过 PR #37 合并，当前权威基线为 `origin/main@2b6538ca01f45593ac8a2d4aecd8f7e8f95265a4`；post-merge CI run `30757438481` 为 `2074 passed / 0 skipped` 且 fresh migration 成功。A1.3 专用分支 `codex/agent-first-a1-state-memory-boundary` 直接从该提交创建，初始状态 clean。

> A1.4 开始前再次 fetch：A1.3 已通过 PR #38 合并，当前权威基线为 `origin/main@dfef5b693dc06461210c2d065564b42333990143`；post-merge CI run `30795837307` 为 `2074 passed / 0 skipped` 且 fresh migration 成功。A1.4 专用分支 `codex/agent-first-a1-capability-approval-boundary` 直接从该提交创建，初始状态 clean。

> A1.5 开始前再次 fetch：A1.4 已通过 PR #39 squash merge，当前权威基线为 `origin/main@cae88a4d4d1e365baddd394d196444f4ee6d1e8f`；post-merge CI run `30804485326` 为 `2074 passed / 0 skipped` 且 fresh PostGIS migration 成功。A1.5 专用分支 `codex/agent-first-a1-legacy-agent-rename` 直接从该提交创建，初始状态 clean。

### Migration 与 CI 基线

- 当前 Alembic 唯一 head：`20260718_meetup_route_snap (head)`。任务包要求的 `python -m alembic heads` 因本机无 `python` 命令而退出 127；等价的 `python3 -m alembic heads` 退出 0。迁移目录和 `down_revision` 搜索显示单链，远端 CI 进一步验证从空 PostgreSQL/PostGIS 升级到该 head。
- 当前工作流唯一入口为 [`.github/workflows/test.yml`](../../.github/workflows/test.yml)：PostgreSQL 16/PostGIS 3.4、Redis 7、fresh `alembic upgrade head`、完整 pytest，并拒绝任何 skip；没有部署步骤。
- 最新 `origin/main@2d58fe2d…` GitHub Actions run 为 `30742485347`，job `91482253170`，结论 `success`；日志为 `2074 passed, 814 warnings in 71.93s`，0 skip，fresh migration 成功。
- 该 run 只证明远端基线，不覆盖 R1 未提交的 A0 diff；A0C 专用分支的 CI 以 Draft PR 当前 head run 为准，不能用 baseline run 冒充交付 CI。两者都不证明真实腾讯/DEM、生产数据库、微信开发者工具/真机、部署或用户可用。
- A0C 合并后的 `main@88dd1656…` 已由 workflow run `30751066756` 验证：fresh PostGIS migration 成功，`2074 passed`、`0 skipped`、`814 warnings`；这是 A1.1 的远端起点，不代替本任务分支和 merge-ref CI。

### 证据分层

1. **代码事实**：文件、调用链、模型、配置存在。
2. **本地测试事实**：A0 最小测试为 `pytest -q tests/test_agent_segment_writer.py`，结果 `6 passed, 7 warnings`，0 skip；只证明被测草稿生成边界。
3. **远端 CI 事实**：上述 baseline run 证明 `origin/main` 的空库迁移和全套测试，不覆盖 A0C 交付 diff；后者必须由 Draft PR 当前 head 的 workflow 单独证明。
4. **部署事实**：本轮未读取或改变生产部署，`UNVERIFIED`。
5. **真实用户事实**：本轮未走腾讯真实 Provider、DEM 下载、真实导出、微信开发者工具或真机，`UNVERIFIED`。

## 2.2 Existing Capability Matrix

| 能力 | 存在性 | 当前 owner | 已存在的真实副作用 | 当前测试证据 | 对 Agent-First 的缺口 |
|---|---|---|---|---|---|
| 旧 `app/agent` | exists | [segment_writer.py](../../app/agent/segment_writer.py) 负责 DeepSeek/OpenAI 兼容调用；[tasks.py](../../app/agent/tasks.py) 是 RQ task 并直接读写 SQLAlchemy 模型 | 外部 LLM 网络；写 `segment_ai_drafts` | `test_agent_segment_writer.py` mock client；`test_agent_tasks.py` 真 PG 路径由 CI 的 no-skip 策略覆盖 | 不是 Agent Runtime；没有 Session/Tool Registry/Capability/Trace/Replay；违反未来“Agent 不直 ORM”的目标边界，必须先安全改名隔离语义 |
| RQ 派发 | exists | [admin/service.py](../../app/admin/service.py) 用字符串 `app.agent.tasks.generate_segment_draft_task` 入 `ai_drafts`；[queue.py](../../app/queue.py)、[worker.py](../../worker.py) 和 compose 订阅该队列 | Redis job、worker 执行、草稿入库 | admin/queue/task 测试；baseline CI 通过 | 字符串序列化与已排队 job 是迁移兼容面；不能直接搬目录 |
| RouteBook / RouteVersion | exists | [route_book/models.py](../../app/route_book/models.py)、[service.py](../../app/route_book/service.py)；保存 GCJ-02 输入时转换 WGS84，并创建 RouteBook/RouteVersion | PostgreSQL 写入；保存请求幂等记录 | route book API、draw idempotency 真 PG、版本/导出测试 | 是现有路线业务对象，不应被膨胀为长期 World Model 或 Agent Memory；当前海拔 backfill 会更新 current RouteVersion，Agent 方案需尊重现有版本/导出失效合同 |
| 腾讯骑行规划 | exists | [tencent_direction.py](../../app/route_book/tencent_direction.py) 的 `plan_tencent_bicycling_route`；[draw_snap_service.py](../../app/route_book/draw_snap_service.py) 分段调用 | 真实 `httpx` 腾讯网络、签名 key/SK、超时与 Provider 错误 | 单元测试 mock `httpx.get`；snap/API 测试 mock Provider | 可作为未来受控高层工具的底层能力；Agent 不得拿 raw client，也没有 success/timeout/ambiguity/no-result/disconnect 的统一合同 |
| 贴路与本地绕行 | exists | draw snap 支持 `snap` / `freehand`，失败段可由用户明确转为本地手画绕行 | 可能触发多次腾讯调用；preview 本身不写 RouteBook | snap 失败、约束、点数及虚拟路线测试 | 仍是确定性工作流，不是 Agent 自由生成坐标；未来 MapAction/RidePlan 只能引用其结果 |
| 海拔 | exists | [route_elevation.py](../../app/elevation/route_elevation.py)、[dem_client.py](../../app/elevation/dem_client.py) 查询 GLO-30 COG，重采样/平滑/累计爬升；Route Draw preview 与保存/backfill 接入 | 真实 DEM HTTP 下载、磁盘 cache、RouteVersion 数据更新 | elevation 单元、preview、backfill 测试，多数以 fake query/fixture 验证 | 具备确定性计算能力，但真实瓦片可用性/精度未在 A0 验证；Agent 只能经带超时和来源信息的高层工具使用 |
| GPX/TCX 导出 | exists | [export_workflow.py](../../app/route_book/export_workflow.py)、[export_service.py](../../app/route_book/export_service.py)、[export_generator.py](../../app/route_book/export_generator.py) | DB job/artifact、storage 文件、下载/权限与 stale/hash 门禁 | export foundation/workflow/API 测试；baseline CI 通过 | 真实导出是副作用；Phase A/B shadow 不可触达，必须在用户选择和阶段权限之后才允许 |
| Route Cognition | partially present | [models.py](../../app/route_cognition/models.py) 已有 Judgment/Collection/Concept/Candidate/Formal Link/Membership/Research/Evidence/Segment 来源模型；`services/` 已有内部 writer、`write_guard` 和只读 demo snapshot | 内部 DB 写入；人审 judgment、来源、publish/visibility、关系真相元数据门禁 | 多组 schema/writer/seed dry-run/真 PG 测试；baseline CI 通过 | 旧 [architecture-guide.md](../../docs/architecture-guide.md) 对“writer 未实现”的描述已过时；当前仍无通用 Agent Control Plane、公开 API/admin UI、Session/Trace/Replay，也不能把正式知识写入暴露给规划 Agent |
| Agent v0 合同与评测 | absent | 运行时、测试和工作流路径中不存在 Agent v0 runtime/test implementation、Tool Registry、Trace/Replay implementation、VeloBench harness 或 fake environment；`docs/agent-first/source/` 与 A0 计划文档中的同名符号只是设计引用，不是实现证据 | 无 | 无 | A2–A4 尚未开始；不能把源设计文档中的概念误报为现存实现 |

总体判断：VELO 已有真实路线/海拔/导出确定性地基，也有内部路线认知审核地基；缺少的是受限 Agent 控制面、语言中立合同和状态型评测，不需要重写已有业务链。

## 2.3 Legacy `app/agent` Namespace Decision（A1.5 in review）

### 影响面清单

- Python import：`app/agent/tasks.py` → `app.agent.segment_writer`；`tests/test_agent_segment_writer.py`、`tests/test_agent_tasks.py`。
- RQ 字符串任务：`app/admin/service.py::_AI_DRAFT_TASK`；`tests/test_admin_router.py` 对该字符串有断言。
- 队列/worker：`app/queue.py` 示例、`worker.py` 的 `ai_drafts` 注册和默认 `RQ_QUEUES`、`docker-compose.yml`、`docker-compose.dev.yml`。
- DB/管理兼容面：`segment_ai_drafts` 表和 admin draft endpoint 名称不随 Python 包改名。
- 当前文档：`docs/architecture-guide.md`、`docs/data-flow-guide.md`、ADR-009、产品/部署说明；历史 `docs/plans`、`docs/archive`、changelog 保留历史文字，不批量改写。

### 选定边界

Proposed [ADR-017](../adr/017-为什么旧app-agent必须迁出并保留RQ兼容路径.md) 在“一次性 rename”、“永久保留旧实现”、“复用 `app.agent` 给新 Runtime”和“canonical 新包 + compatibility tombstone + 分阶段 producer 切换”中选择最后一项：

- 未来真实实现的唯一 owner 为 `app.segment_draft_ai`，结构固定为 `app/segment_draft_ai/{__init__.py,segment_writer.py,tasks.py}`。
- `app.agent` 只能是 `legacy compatibility tombstone`，转发旧 import 并保持旧 RQ 全限定路径可执行；不得保留/新增业务实现或复制 DB/LLM 副作用。
- shim 默认可无限期保留，删除不是 A1.5/A2/A3/A4 完成条件；未来删除必须新开 ADR + Task Packet 并证明旧路径已不可能执行。
- 即使 shim 被删除，`app.agent` 也永久禁止被 Planning Runtime 复用；未来 Runtime 命名、语言和框架继续 deferred。

### 冻结的 M1/M2/M3 顺序

1. **M1 双路径兼容**：独立实施任务才新建 canonical 包、将旧文件变为极薄 wrapper，producer 仍 enqueue `app.agent.tasks.generate_segment_draft_task`。部署同时支持两种路径的 API 和全部 `ai_drafts` worker，并验证旧序列化 job 可执行；M1 期间禁止切 producer。
2. **M2 producer 切换**：只有所有生产 worker 兼容新旧路径后，独立部署任务才可切为 `app.segment_draft_ai.tasks.generate_segment_draft_task`。`ai_drafts` 队列不变、shim 保留；必须有 worker 版本证据，混合版本期间不让新路径 job 进入旧 worker。
3. **M3 稳定期**：新 job 用 canonical 路径，旧 job 通过 shim；增加 architecture/import guard 禁止新的非 shim `app.agent` import，shim 默认继续保留。

回滚：M1 失败回滚应用镜像，producer 始终是旧路径；M2 失败只把 producer 字符串切回旧路径，shim 继续工作。禁止重写已有 Redis job、清空 Redis，或在旧 job 可能执行时删除 shim；不涉及 schema/data migration 或 backfill。

未来测试：canonical 模块保持成功/失败语义；旧 writer/task wrapper 各只委托一次且 shim 不创建 DB Session/不重复 LLM；新旧 RQ 字符串都可 import/执行；旧 job 可由兼容 worker 执行；producer 切换前后字符串正确；pending-only/三类 protected status/IntegrityError 并发语义不变；queue/worker 订阅不变；非 shim 新增 `app.agent` import 使 architecture test 失败。本 A1.5 任务不实现这些测试或搬移任何代码。

## 2.4 Static Planning vs Realtime Navigation Conflict Report

**A1.1 status**：Orchestrator 已判定 `PASS / completed`，并由 Accepted [ADR-013](../adr/013-为什么区分骑前静态规划与骑中实时导航.md) 编码；该 ADR clarifies ADR-010、does not supersede ADR-010，运行时行为没有改变。

| 冲突文字 | 当前真实行为 | A1.1 处理结果 |
|---|---|---|
| [AGENTS.md](../../AGENTS.md) 禁止实时导航/动态改路，同时允许静态路线、GPX 和外部地图跳转 | 项目级产品边界本身已区分骑前静态交付与骑中动态行为 | 保持该不变量，并让下列产品决策与它使用同一边界 |
| A0 基线中的 [product-decisions.md](../../docs/agent-rules/product-decisions.md) `INV-P03` / `D-P04` 将“路径规划/路线生成”整体写成不做 | Route Draw 已通过腾讯 bicycling 生成骑前静态路径，并允许明确失败后的本地手画绕行 | A1.1 已将禁令收窄到“骑中实时导航、语音、偏航动态重规划和自建全国路由”，并明确允许骑前静态 Ride Plan 编译与受控 Provider 连接段 |
| 同文档 `D-P07` 要求路线生成由确定性服务负责 | [tencent_direction.py](../../app/route_book/tencent_direction.py)、draw snap、elevation、export 正是确定性服务 | 保留并强化：LLM 只表达意图/选择，不产坐标、距离、爬升、验证或导出 |
| [ADR-010](../../docs/adr/010-为什么不做实时导航.md) 禁止实时导航，但明确允许骑前规划和 GPX | 现有静态 Route Draw/GPX 与 ADR-010 一致 | 使 INV-P03/D-P04、AGENTS、架构总览与 ADR-010 用词对齐 |
| A0 基线中的 [architecture-guide.md](../../docs/architecture-guide.md) 写“骑行路线算法生成（只推荐历史轨迹）” | 代码已有真实腾讯骑行规划 | A1.1 已用骑前静态能力和骑中实时排除项替换旧描述；不能以历史文档否定现有代码 |

**A1.1 decision boundary**：允许骑前静态 `RidePlan` 编译、已审核核心路线的 access/core/connector/return 拼接、受控 Provider 生成、确定性校验、静态预览，以及未来获得阶段与任务授权后的用户确认导出；继续禁止骑中 GPS 跟随、语音导航、偏航动态重规划、自建全国路由和 LLM 生成坐标或几何。

**A1.1 may change**：`docs/adr/013-为什么区分骑前静态规划与骑中实时导航.md`、`docs/adr/README.md`、`docs/agent-rules/product-decisions.md`、`docs/architecture-guide.md`、`docs/agent-first/README.md`、本文件与 `VELO_ORCHESTRATOR_STATE.yaml`。

**A1.1 must not change**：`AGENTS.md`、ADR-010、`app/`、`miniprogram/`、`migrations/`、`tests/`、依赖、workflow、compose、生产配置、Route Draw/Export API/交互/schema，以及三份 source 文档与 Control Pack 原文。

**A1.1 resolved terminology**：当前文档使用“骑前静态规划”“骑中实时导航”“动态重规划”，避免无时间边界地单独使用“路径规划”。真实导出仍需用户确认、未来阶段许可和新的 Task Packet。

### A1.2 单一有界主 Agent / 确定性 Workflow 决策边界

**A1.2 status**：Orchestrator 已判定 `PASS / completed`，并由 Accepted [ADR-014](../adr/014-为什么在线规划采用单一有界主Agent与确定性工作流.md) 编码；这只完成控制权文档裁决，不授权 Runtime 或 A1.3 实现。

**选定候选**：一次在线骑前规划 run 采用一个逻辑主 Agent 和一个确定性 run controller。模型路由或降级不创建第二个权威；不允许 peer agent、subagent 或 multi-agent planning。

**模型职责**：理解意图、提出澄清、选择高层工具类别、比较已验证候选、解释拒绝/修订和生成用户可读说明。模型输出只是 typed action proposal，不能直接写状态、调用 raw Provider/ORM/SQL、制造路线事实或批准副作用。

**Workflow 职责**：接收事件、加载状态、编译上下文、执行 policy/tool/schema/approval gate、形成 typed observation、reducer 推进、调用 Domain Plane 校验与持久化、记录 trace，并负责停止/恢复。

**确定性权威**：几何、距离、海拔、Provider 结果、硬约束验证、版本/revision/hash 与导出工件属于 Domain Plane；最终方案选择、意图纠正和敏感副作用批准属于用户。模型没有这两类最终权威。

**不可绕过门禁**：状态版本、capability、approval、side effect、tool registry、schema、deadline、幂等、typed observation、领域校验、受控持久化、trace 和停止条件均由代码执行。A1.4 已由 ADR-016 裁决完整 taxonomy；未明确注册或可能产生敏感副作用的能力继续 fail closed。

**有界循环**：未来 controller 必须强制 `max_model_turns`、`max_tool_calls`、`max_plan_generations`、`max_same_tool_retries`、`wall_clock_deadline`、`token_or_cost_budget`；停止原因至少包含 `completed`、`waiting_for_user`、`no_result`、`approval_required`、`budget_exceeded`、`deterministic_error`。具体数值留待实现与 VeloBench 证据。

**后续边界**：action/schema 的精确合同延后 A2；World Fact/Session/Run/Memory 生命周期已由 A1.3 裁决；Capability/Approval/Side Effect taxonomy 已由 A1.4 裁决；旧 `app/agent` namespace 由审查中的 A1.5 Proposed ADR-017 隔离为 compatibility tombstone。`Framework choice: DEFERRED`，本轮不选择 Python/TypeScript、OpenAI Agents SDK、LangGraph、LangChain 或其他 Runtime 框架。

**A1.2 allowlist**：ADR-014、ADR index、Agent-First README、本文件与根 State，共五个文件。禁止修改 runtime、contracts、schema/migration、API、小程序、Provider、export、测试、依赖、workflow、compose、source 文档、Control Pack、ADR-013、产品裁决或架构总览。

### A1.3 World Fact / User State / Session / Run / Memory / Trace 决策边界

**A1.3 status**：Orchestrator 已判定 `PASS / completed`，并由 Accepted [ADR-015](../adr/015-为什么世界事实会话运行与长期记忆必须分离.md) 编码；这只完成状态与记忆所有权裁决，不授权 Session、Run、Memory、Context 或 A1.4 实现。

**当前代码事实**：`User` 保存 FTP、体重、车型和城市等明确资料；Activity 是结构化用户历史；`RouteBook` / `RouteVersion` 是用户路线资产和版本化几何。route cognition 已有 Judgment/Evidence/Research、Concept/Collection、候选/正式关系及人审 writer guard，但没有一等 Claim World Model。`JudgmentRun` 是路线认知/研究/人审台账，route export job 是领域副作用任务，二者都不是在线 Planning Agent Run。运行代码中不存在目标意义的 Planning Session、Agent Run State、Memory Service、Context Manifest、统一 Map State、Replay 或 VeloBench；当前 `app/agent` 仍是赛段文案生成模块，也没有向量数据库或生产长期 Memory。

**状态 Ownership / Lifecycle 矩阵**：

| 状态类别 | 唯一 Owner | 生命周期 | 在线 Agent 边界 |
|---|---|---|---|
| Canonical World Fact | Deterministic Domain + Curation/Human Review | 长期、版本化、带 provenance/freshness | 只读最小 FactPacket；禁止直写 |
| User State | User + Business Domain Services | 账号范围、用户可控 | 读取授权子集；写入走显式产品服务 |
| Planning Session | Deterministic Interaction/Session Service | 一次可恢复骑行决策，可跨多轮/多 Run | reducer 推进；原始聊天不是唯一真相 |
| Agent Run | Deterministic Run Controller | 一次 event/resume 触发的有界执行 | 绑定 base Session revision；stale commit 拒绝 |
| Long-term Memory v0 | User-controlled Memory Service | 跨 Session、可见/可改/可删/版本化 | 只允许 explicit proposal；不复制产品字段/敏感原值 |
| Trace / Eval | Evaluation & Operations Plane | append-only 运行证据 | 不成为业务真相、Session 或 Memory |
| Compiled Context | Context Compiler | 单次 model call 的临时投影 | 记录 source refs/revisions；不是状态库 |

**Session / Run**：one Session can have many Runs；Session 是 working memory，保存 intent、map/focus、candidate/selection、assumptions/unknowns 与 revision。Run 保存单次控制器执行的 step、预算、tool/observation refs、retry、pending gate 和 stop reason；Run 绑定已提交 Session revision，Session 更新后旧 Run 不得提交。

**User State / Memory**：已有稳定产品字段、Activity、saved asset 都留在 User/Business Domain；Memory 不做第二套用户数据库。Explicit Memory v0 只接收用户主动陈述或明确确认、且尚无一等产品字段的个人偏好/纠正；用户可见、可改、可删，模型只有 proposal 权。精确敏感位置默认以 opaque ref + 粗粒度 label 进入 Context，不复制坐标。

**Inferred / episodic**：inferred memory 继续 `DEFERRED`，只可作为 eval/proposal 证据，不自动进生产 Context、改变硬约束或写资产。Episodic history 来自结构化用户历史与 Trace，可做确定性摘要/Eval，不自动变成跨 Session Prompt Memory。

**Plan / Trace / Context**：RidePlanDraft 是由确定性 Planning Domain 生成、Session 引用的版本化候选工件，不是 World Fact 或 Memory；每次 revision 使旧 validation 失效。Trace 是 append-only evidence；Context 是 policy、授权 User State、已提交 Session、相关 Explicit Memory、最小 FactPacket 与 Plan summary 的编译投影，默认不加载完整历史或全库。

**延后**：具体 ID、字段、revision/error 与 JSON Schema 延后 A2；Memory write authorization 与 approval/side-effect taxonomy 已由 A1.4 裁决；旧 `app/agent` namespace 由审查中的 A1.5 Proposed ADR-017 隔离为 compatibility tombstone；数据库、TTL、存储、vector DB、embedding、检索算法与 Runtime/framework 均不在 A1.3 选择。

**A1.3 allowlist**：ADR-015、ADR index、Agent-First README、本文件与根 State，共五个文件。ADR-013/014、产品裁决、架构总览、source 文档、Control Pack、运行代码、schema/migration、API、小程序、测试、依赖、workflow 与 compose 保持不变。

### A1.4 Capability / Approval / Side Effect 决策边界

**A1.4 status**：Orchestrator 已判定 `PASS / completed`，并由 Accepted [ADR-016](../adr/016-为什么在线Agent的能力审批与副作用必须显式化.md) 编码；这只完成 Capability / Approval / Side Effect 架构边界，不授权 A1.5、Runtime、schema、UI、Provider/export 行为或部署。

**四类门禁**：Capability 注册、user/service resource/data-scope authorization、deterministic domain validation 与 user approval 分开。`resource permission is not approval`；`approval is not validation`。在线 Agent deny by default，只能 pass through 当前 user identity、service identity、capability 与 data scope 的交集，不是 admin/superuser。

**分阶段顺序**：environment allowlist → capability registry → user/service identity + data scope → normalize exact effect identity → preflight idempotency lookup。已有相同 committed effect 直接返回原结果且不重新批准/执行；已有 started/outcome_unknown/reconciliation_required effect 只对账或返回 pending/unknown；同 key 不同 effect identity 返回 `IDEMPOTENCY_CONFLICT`。只有没有 prior effect 时才继续 schema/stale revision → deterministic validation → required approval → atomic reservation/final duplicate guard → execute → effect ledger + Trace。exact identity 至少包含 capability、tool name/version、effect scope、targets、payload hash、相关 Session/Plan/asset revisions、disclosure summary 与 idempotency key。未注册工具与 raw Provider/SQL/ORM/shell/arbitrary network/direct GPX/canonical/admin 能力 fail closed。

**Effect / approval matrix**：

| Effect scope | 典型动作 | Approval mode |
|---|---|---|
| `READ` | World/User authorized read、validation、`export.prepare` | `NONE` |
| `SESSION` | candidate/Plan draft/reducer；`plan.select` | 普通更新 `NONE`；选择 `EXPLICIT_INTENT` |
| `PROVIDER_QUERY` | Domain 内有界高层候选生成与最小披露 | 当前规划意图下 `EXPLICIT_INTENT` |
| `PERSONAL` | saved place/draft/explicit memory/settings | `EXPLICIT_INTENT` 或 `CONFIRM_EXACT` |
| `CONTRIBUTION` | attributable proposal/evidence submit/withdraw | `EXPLICIT_INTENT` 或 `CONFIRM_EXACT` |
| `EXTERNAL_DELIVERY` | export artifact/share/send | `CONFIRM_EXACT` |
| `CANONICAL` | publish/accept/activate/reviewer decision | 在线 Agent `FORBIDDEN`；reviewer 环境 `REVIEW_REQUIRED` |

**Exact grant**：只授权 single exact effect，带 expiry、默认 single-use；稳定锚点是 `approval_request_id` 或 `proposed_effect_id`，而非原始 Run。记录 `requested_by_run_id`、`decided_by_user_event_ref`、`decision_recorded_at` 与首次消费时的 `consumed_by_run_id`。Run A 可在同一 Session 提议并停在 `APPROVAL_REQUIRED`，用户事件触发 Run B 后，只有同一 pending request/effect、相同 capability/tool/scope、targets/hash/revisions 且未过期、未撤销、未被其他 effect 消费时才能恢复；无关 Run 不能消费。payload、target、revision、tool/capability 或 disclosure 变化即失效；沉默不是批准，批准不能绕过 validator。

**Ledger / replay**：`PROVIDER_QUERY` 披露、`PERSONAL`、`CONTRIBUTION`、`EXTERNAL_DELIVERY`、`CANONICAL` 必须可关联 approval/effect/Trace；概念状态除 proposed/approval_required/approved/started/committed/failed/compensated/withdrawn 外，还必须能表达 `outcome_unknown` 与 `reconciliation_required`，但 A1.4 不冻结精确 enum/schema。committed effect 的相同重试返回原 artifact/ref/result，不 fresh approve、不 re-execute、不再次消费批准；同 key 改 payload/target/revision 等 fail closed。disconnect/deadline 在 started 前阻止启动并保持 zero effect；started 后不假定回滚、不启动第二个 effect，保持 pending/unknown 并按 key/ledger 对账，最终才收敛为 committed/failed/compensated。replay/shadow zero real effect；failed/rejected 不包装成 success。

**A3/A4 后续验收案例**：后续独立任务必须机器验证：(1) committed 后 response 丢失，identical retry 返回 prior result 且不 reapproval；(2) 同 key 改 payload 返回 conflict 且 zero second effect；(3) approval 由 Run A 请求、由同一 pending effect 的 resume Run B 消费；(4) unrelated Run 不能消费；(5) disconnect before started 保持 zero effect；(6) disconnect after started 进入 `outcome_unknown` / `reconciliation_required` 且不重复执行；(7) reconciliation 最终收敛 committed 或 failed，期间不误报成功或失败。A1.4 只预留这些案例，不实现 schema、Fake 或测试。

**Provider / export**：精确 saved-place 坐标只在 Domain 内解析，模型只见 opaque ref/粗粒度 label；raw Tencent 隐藏，披露进入 ledger。当前 `create_route_export` 会写 storage、job、artifact 和 DB，不能成为未来 `export.prepare`；后者只做 readiness/preview/exact summary 且 zero artifact，`export.commit` 才在精确批准、幂等和 ledger 下产生制品。

**Memory / contribution**：Memory/saved place durable write 属于 `PERSONAL`，用户可见/可改/可删且不复制 Profile/Activity/saved asset。贡献按 draft → explicit submit → attributable proposal/evidence → triage/corroboration/request-more → accept/reject → visible feedback/credit → correction/appeal；proposal 不是 canonical truth，Agent 可协助整理但不能擅自提交或审核。

**A1.4 allowlist**：ADR-016、ADR index、Agent-First README、本文件与根 State，共五个文件。ADR-013/014/015、产品裁决、架构总览、source 文档、Control Pack、运行代码、schema/migration、API、小程序、测试、依赖、workflow 与 compose 保持不变。

### A1.5 Legacy `app/agent` Namespace 迁移裁决

**A1.5 status**：当前 `in_review / READY_FOR_REVIEW`，Proposed [ADR-017](../adr/017-为什么旧app-agent必须迁出并保留RQ兼容路径.md) 等待 Orchestrator 裁决；执行授权为 false。

**核心决策**：现有赛段文案/AI 草稿实现未来唯一 canonical package 为 `app.segment_draft_ai`；`app.agent` 只能作为默认长期保留的 compatibility tombstone，用无业务副作用的极薄 wrapper 支持旧 import 和 `app.agent.tasks.generate_segment_draft_task` serialized RQ path。`app.agent` 永久禁止被未来 Planning Runtime 复用。

**与后续任务的关系**：ADR-017 Accepted 后，A1 可收口 `completed / PASS`，A2 才可 `ready_to_specify`。实际 M1/M2 不阻塞 A2 contracts、A3 VeloBench 或 A4 Fake Environment；但 M1 必须在第一个生产 Planning Agent Runtime 或 Phase B live Agent integration 前完成。M2 必须拆为带实际 worker 兼容证据和独立部署授权的任务。

**本轮 allowlist**：ADR-017、ADR index、Agent-First README、本文件与根 State，共五个文件。本轮不移动/修改 `app/agent`，不创建 `app/segment_draft_ai`，不切 producer，不改 worker/queue/compose/test/schema/migration/API/DB，不部署，不开始 A2。

## 2.5 Phase A File-Level Breakdown

以下每一项都必须由 Orchestrator 重新校准 `origin/main` 后拆成一个独立 Task Packet；路径是候选 allowlist，不是当前授权。

### A1 — Architecture ADRs

- **目标**：裁决五个边界：骑前静态规划/骑中导航；单一有界主 Agent/确定性 Workflow；World Fact/Session/Run/Memory；Capability/Approval/副作用；旧 `app/agent` 命名迁移。
- **前置**：A0/A0C 经 Orchestrator `PASS`；每个子任务开始时重新核对代码、产品裁决和 `origin/main`。
- **执行方式**：五个子任务串行推进，每项都需要独立 Task Packet 和 Orchestrator 判定；A1.1 不授权后续子任务。

| 子任务 | 决策边界 | 当前状态 | 依赖 |
|---|---|---|---|
| A1.1 | static planning vs realtime navigation | `completed / PASS` | A0C |
| A1.2 | bounded Agent vs deterministic Workflow | `completed / PASS` | A1.1 |
| A1.3 | World Fact / User State / Session / Run / Memory / Trace | `completed / PASS` | A1.2 |
| A1.4 | Capability / Approval / Side Effect | `completed / PASS` | A1.3 |
| A1.5 | legacy `app/agent` naming migration | `in_review / READY_FOR_REVIEW / unauthorized` | A1.4 |

- **A1.1 结果**：七文件 allowlist 内的文档裁决已完成，ADR-013 为 Accepted。
- **A1.2 结果**：五文件 allowlist 内的控制权裁决已由 Orchestrator 判定 `PASS`，ADR-014 为 Accepted；PR #37 的 post-merge CI 已通过。
- **A1.3 结果**：五文件 allowlist 内的状态与记忆边界已由 Orchestrator 判定 `PASS`，ADR-015 为 Accepted，PR #38 与 post-merge CI 已完成；无 Session/Run/Memory/Context、schema、runtime 或部署授权。随后新的独立 Task Packet 才选择 A1.4。
- **A1.4 结果**：五文件 allowlist 内的 ADR-016 已由 Orchestrator 判定 `PASS` 并转为 Accepted；PR #39 已 squash merge，post-merge CI run `30804485326` 为 `2074 passed / 0 skipped` 且 fresh PostGIS migration 成功。无 Capability Engine、Approval UI、Side-effect Ledger、Contribution、schema、runtime 或部署授权。
- **A1.5 候选结果**：五文件 allowlist 内已形成 Proposed ADR-017，决定 `app.segment_draft_ai` canonical owner、`app.agent` 长期 compatibility tombstone、shim 删除非完成条件、M1/M2/M3 序列与永久禁止 Runtime 复用旧 namespace。当前等待 Orchestrator 审查；无代码迁移、Runtime、部署或 A2 授权。
- **禁止范围**：运行代码、合同、schema/migration、API、小程序、依赖、队列和部署。
- **最小测试**：Markdown 链接/路径检查；冲突词搜索；`git diff --check`；受保护路径零 diff；每个 ADR 都含状态、事实、决策、后果、非目标和撤回条件。
- **退出门槛**：五项均有唯一裁决；INV-P03/D-P04/D-P07/ADR-010 不再矛盾；旧命名采用或拒绝 2.3 推荐方案；不偷偷选 Runtime 框架。
- **失败回滚**：只回滚 A1 新增/修改的文档与 State，代码无需回滚。
- **Orchestrator 判定**：逐项 `PASS/REVISE/HARD_BLOCK/DEFER`；任何产品边界未由 Tim 确认则不得进入 A2。

### A2 — Agent v0 Contracts

- **目标**：以 JSON Schema Draft 2020-12 建立语言中立、可版本化的控制面合同，不决定 TypeScript Runtime。
- **前置**：A1 通过；五个 ADR 的术语和副作用分类稳定。
- **允许文件**：`contracts/agent_v0/README.md`、`session_state.schema.json`、`map_action.schema.json`、`tool_call.schema.json`、`tool_result.schema.json`、`ride_plan_draft.schema.json`、`validation_result.schema.json`、`trace_event.schema.json`、`error.schema.json`；合同校验测试建议 `tests/contracts/test_agent_v0_contracts.py`；State/入口文档只做必要路由。
- **字段下限**：所有对象含 `schema_version`、稳定 ID、创建时间或序号和可扩展 `metadata`；Session 含 revision/intent/map state/candidates/selection/unknowns/pending approval；MapAction 含 action type/target/payload/expected session revision；ToolCall 含 tool name+version/capability/effect scope/approval mode/data classification/reversibility/idempotency/deadline/input、approval ref、side-effect ref、request/payload hash、target refs 与 base revisions；ToolResult 含 status/output refs/warnings/unknowns/error；RidePlanDraft 含 revision、access/core/return legs、geometry refs、约束、指标和 validation state；ValidationResult 含 hard/soft checks 和 deterministic evidence；TraceEvent 含 run/session/sequence/event type/input-output refs/approval/effect refs；Error 含稳定 code/retryability/user-safe message/details。合同还必须表达 contribution proposal/status、`RiderContextPacket`、`WorldFactPacket` 与 `ContextManifest`，但 A1.4 不创建 schema。
- **版本策略**：目录主版本 `agent_v0`；每个 schema 有 `$id` 和 SemVer `schema_version`；同主版本只允许向后兼容新增可选字段，破坏性变化新开目录；fixture 固定所用版本。
- **代码生成/验证**：JSON Schema 是单一真相源；CI 对 schema、正反 fixture 和跨引用做确定性校验，后续 Python/TS 类型必须从同一 schema 生成或一致性比对，禁止手工维护两套真相。A2 先核对仓库现有依赖；若需要新增 validator/codegen 依赖，必须在 A2 Task Packet 明示，不在 A0 猜选。
- **禁止范围**：Agent Runtime、网络工具、ORM、生产 DB、真实腾讯/导出、TS 框架或大 World Model schema。
- **最小测试**：每份 schema 的 valid/invalid fixture；额外字段策略；版本/ID/ref；approval 和副作用不变量；RidePlan leg 枚举；error/timeout 表达；contract round-trip。
- **退出门槛**：8 份合同均可被机器验证；Python/未来 TS 不产生语义分叉；raw provider/ORM/public publish/real export 无可表达的直接 capability。
- **失败回滚**：删除 A2 新合同/测试并恢复路由文档；无运行数据迁移。
- **Orchestrator 判定**：审查字段是否足够支撑 30 个 case，若仍靠自然语言解释关键状态则 `REVISE`；Runtime 技术选型继续 `DEFER`。

### A3 — VeloBench v0

- **目标**：评估状态、约束和副作用，而非文案“像不像”；最终不少于 30 个可重复 case。
- **前置**：A2 合同通过并冻结一个 v0 版本。
- **允许文件**：`tests/velobench/README.md`、`case_schema.json`、`cases/`、`fixtures/`、`graders/`；只在需要时增加专用 pytest 入口和 State/路由。
- **case 下限**：`case_id`、`version`、`tags`、输入 Session/fixture、scripted tool outcomes、`expected_end_state`、`forbidden_actions`、确定性 `code_grader`、可接受 trace/错误、重跑 seed。覆盖天龙山 access/core/return、歧义位置、隐私、超时、无结果、断连、硬约束失败、ambiguous consent、Plan revision 后 stale approval、同 key payload change conflict、committed-response-loss identical retry、Run A approval request / resume Run B consumption、unrelated Run 拒绝消费、disconnect-before-start zero effect、disconnect-after-start unknown outcome、reconciliation 收敛且不误报、raw/canonical capability 不可达、`export.prepare` zero artifact、contribution submit 不等于 accept、未验证报告保持标签、贡献状态/结果可见，以及 READ/SESSION 不制造确认疲劳。
- **禁止范围**：LLM 评分作为唯一 grader、真实网络/生产 DB/storage/export、修改产品运行代码、为了凑 30 个只改文案的重复 case。
- **最小测试**：case schema 自校验；grader 自身正反测试；同 seed 重跑一致；每个 case 都具备五个必填控制字段；测试明确失败时输出状态 diff。
- **退出门槛**：至少 30 case 全部可重复；每个都有 expected end state、forbidden actions、code grader、标签和版本；grader 能抓到状态正确但禁用副作用发生、以及语言漂亮但状态错误两类问题。
- **失败回滚**：回退新增 case/grader，不改变 A2 合同；若合同不足，记录具体失败并退回 A2 `REVISE`。
- **Orchestrator 判定**：按覆盖矩阵和 grader 变异测试决定，不按 case 数量单项判过。

### A4 — Deterministic Fake Environment

- **目标**：在无网络/无生产资源的情况下，以确定性时钟、ID、状态和工具脚本运行 A3。
- **前置**：A2 合同通过；可与 A3 用独立 Task Packet 迭代，但不能并行写相同文件。
- **允许文件**：`tests/velobench/fake_env/environment.py`、`clock.py`、`ids.py`、`state_store.py`、`scripted_tools.py`、`failure_modes.py`、`side_effect_ledger.py`、`trace_ledger.py` 及专用测试/README。
- **行为下限**：可脚本化 `success`、`timeout`、`ambiguity`、`no_result`、`disconnect`、`hard_constraint_failure`；固定 clock/ID；乐观 revision；调用/approval/副作用/trace ledger；断点重放；未注册工具 fail-closed。Fake 还必须证明 replay/shadow zero real effect、`export.prepare` zero artifact、两阶段 idempotency lookup + atomic reservation、committed-response-loss 返回原结果、same-key changed-effect conflict、跨 Run approval request anchor、disconnect-before-start zero effect、disconnect-after-start unknown-outcome reconciliation、contribution submit 仍是 proposal，以及 stale/exact approval 失效。
- **禁止范围**：socket/http、生产 DB/Redis、真实 filesystem storage、真实 export、真实腾讯或 DEM、import raw Provider/ORM、公共发布；Fake 不复制底层业务实现，只模拟 A2 高层合同。
- **最小测试**：六种结果；同 seed/replay 一致；超时/断连在 started 前阻止 effect；started 后超时/断连不重复 effect 并进入 outcome_unknown/reconciliation_required；committed identical retry 不重批不重做；同 key changed payload 冲突；同一 pending approval 可由后续 Run 消费且无关 Run 不可消费；对账最终 committed/failed 且中途不误报；硬失败阻止 RidePlan validated；禁用能力不可达；side-effect/trace 顺序稳定。
- **退出门槛**：A3 case 无外部资源可运行；六种模式都有确定性证据；raw provider、ORM、public publish、real export 通过 import/registry/ledger 测试均不可达。
- **失败回滚**：移除 Fake 实现，保留暴露合同差异的失败 fixture；若 Fake 与真实高层合同不一致，回到 A2 修合同而非扩大 mock。
- **Orchestrator 判定**：检查网络隔离和能力不可达的机器证据；仅“测试跑过”但未做 forbidden-path 测试则 `REVISE`。

### A5 — Phase B Tianlongshan Shadow Spec

- **目标**：只定义“太原天龙山门到门”shadow slice：用户选起点，编译 access + 已有官方 core + return，观测结果但不接生产流量、不生成真实导出。
- **前置**：A3 ≥30 cases 和 A4 六种失败模式通过；A1 产品边界已裁决。
- **允许文件**：建议新增 `docs/agent-first/phase-b-tianlongshan-shadow-spec.md`，必要时更新本 README、State；不写 runtime。
- **进入条件**：起点为用户明确选择的粗粒度位置；官方 core RouteBook/RouteVersion 有稳定引用和来源；access/return 由受控高层工具返回；合同/validator/trace/approval/隐私和 stop 条件通过；只读 shadow 数据集可用。
- **观测**：每条 leg 来源与几何 ref、Provider outcome、硬/软约束、未知项、工具/副作用 ledger、deterministic validation、case/grader 结果、人工是否会选择；不以自然语言满意度代替状态。
- **退出门槛**：预定义 shadow case 连续满足 end state/forbidden action；零 raw provider/ORM/public publish/real export；无精确家庭位置持久化；失败可明确降级或停止。进入生产仍需另立 Phase B 实现与发布任务。
- **禁止范围**：生产流量、真实导出、用户可见入口、长期 Memory、大 road graph、动态重规划、部署。
- **最小测试**：spec lint/链接、进入条件和 stop condition 完整性、对 A2–A4 证据的可追踪矩阵。
- **失败回滚**：撤回 shadow spec 的阶段候选状态，保留失败分析；不影响生产。
- **Orchestrator 判定**：只决定是否允许另发 Phase B shadow 实现 Task Packet；A5 通过不等于生产授权。

## 2.6 Risk Register

| 风险 | Mitigation | Reopen trigger |
|---|---|---|
| `main` 移动造成规格基线漂移 | 每个 Task Packet 开始与审查前 fetch 并记录 `origin/main`、merge-base、工作树；事实表写 commit | `origin/main` 与记录 SHA 不同、分叉变化或相关文件 diff |
| 旧 `app.agent` RQ 字符串和排队 job | `app.segment_draft_ai` 拥有真实实现，旧 namespace 只作默认长期保留的 tombstone；M1 先部署双路径 worker，M2 有实际 worker 证据后才切 producer，M3 增加 import guard；删 shim 另开 ADR | 任一 queued/started/deferred/scheduled/failed job 或旧 worker 仍引用旧路径，或出现新的非 shim `app.agent` import |
| 把 RouteBook 当长期 World Model 中心 | RouteBook 保持现有用户路线聚合；长期 Fact/Traversal/Research 通过合同与独立边界引用，不向现有表盲塞字段 | A2/A5 需要把 Session/Memory/Agent trace 写进 RouteBook，或 RouteBook 变成所有对象 owner |
| 过早选择 TypeScript/框架 | A2 先做语言中立 JSON Schema，A3/A4 用评测暴露需求；SDK/TS/LangGraph 延后 | 合同和 30 case 稳定后，现有 Python 无法满足明确的隔离/吞吐/工具需求 |
| Fake 过度 mock，与真实高层合同不一致 | Fake 只模拟已定义的高层 tool contract；用真实代码的 schema/错误样例做 contract fixture，不复制底层算法 | 真实 Route Draw/Tencent/elevation/export 出现 Fake 无法表达的返回或失败语义 |
| grader 只评语言，不评状态 | 必填 expected_end_state/forbidden_actions/code grader；做 mutation 测试并核对 ledger/trace | 漂亮回答能在错误状态或发生禁用副作用时通过 |
| Agent-First 文档被误读为生产授权 | README/State/spec 明写 A0/A0C/A1.1/A1.2/A1.3/A1.4 `PASS` 只代表架构裁决；Accepted ADR-016 不授权 Capability/Approval/Contribution/runtime 实现；Proposed ADR-017 只是 namespace/RQ 裁决，A1.5 仍等待审查且 M1/M2/M3 未授权。A2–A5 blocked、deploy false | 有人以 source/spec/ADR 为由改 runtime/schema/UI、搬迁 `app.agent`、切 producer、调用真实 Provider、生成导出、开始 A2 或部署 |
| 测试/CI 被误当 Provider/真机/部署证据 | 汇报强制分为本地、baseline CI、A0 diff CI、部署、线上真用；未验证写 `UNVERIFIED` | 用 mock/CI success 宣称腾讯可用、微信可用、已部署或用户可用 |
| 原始 A0 编写 HEAD 含无关 route-draw commit | 保持原工作树与现有本地 `main` 不变；A0C 在直接基于最新 `origin/main` 的干净独立分支交付八个文件 | 交付分支的 merge-base 不再是任务开始时的 `origin/main`，或出现 allowlist 外改动 |
| RouteVersion 当前可被海拔 backfill 原位更新，导出存在 stale/hash 门禁 | A2 只引用 version/revision/hash；不得绕过 export workflow；A5 把变更后重验写进 stop condition | Agent draft 持有的 version/hash 在验证或导出前已变化 |

## 2.7 No Production Behavior Change Evidence

A0 allowlist 只有以下 Markdown/YAML：

- `docs/README.md`
- `docs/agent-first/README.md`
- `docs/agent-first/source/VELO_路线认知基础设施_v0.1.md`
- `docs/agent-first/source/VELO_目标领域架构与渐进式迁移蓝图_v1.0.md`
- `docs/agent-first/source/VELO_Agent_First_架构研究与系统设计_v0.1.md`
- `docs/agent-first/VELO_Orchestrator_Control_Pack_v1.0.md`
- `docs/agent-first/phase-a-implementation-spec.md`
- `VELO_ORCHESTRATOR_STATE.yaml`

最终审查必须运行并记录：

```bash
git diff --check
git diff --name-only
git diff -- app miniprogram migrations tests .github requirements.txt docker-compose.yml docker-compose.dev.yml
```

最后一条必须为空。R1 收集时，该命令比较的是 A0 未提交工作树与原始编写 HEAD，因此能隔离证明“A0 没改受保护路径”；A0C 则在直接基于 `origin/main` 的干净独立分支重新核对八文件 allowlist，不改变现有本地 `main`。四份随包文件还必须与给定 SHA-256 完全一致。A0 编写阶段未执行 commit、push、merge、tag、release、deploy、真实 Provider、生产 DB、真实 storage/export 或微信真机操作；A0C 只获授权在专用分支上 commit、push 和创建 Draft PR，不获授权合并或部署。

实际结果：`git diff --check` 退出 0；`git diff --name-only` 只列出已跟踪的 `docs/README.md`（Git 默认不列未跟踪文件）；`git status --short` 另列根 State 与 `docs/agent-first/`，逐文件展开后与上述 8 项 allowlist 完全一致；受保护路径 diff 命令退出 0 且输出为空；四份来源/Control Pack 的 SHA-256 与任务包逐字匹配。本地测试只产生 pytest cache 既有忽略项，没有新增受保护路径 diff。
