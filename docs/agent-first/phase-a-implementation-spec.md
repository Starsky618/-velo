# VELO Phase A 文件级实施规格

> A0 内容决定：`PASS`；A0C 交付状态：`in_review`。本文只记录执行时仓库事实与 A1–A5 候选任务边界，不实现 Agent Runtime，不改变生产行为，也不构成合并、部署或阶段推进授权。

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

### Migration 与 CI 基线

- 当前 Alembic 唯一 head：`20260718_meetup_route_snap (head)`。任务包要求的 `python -m alembic heads` 因本机无 `python` 命令而退出 127；等价的 `python3 -m alembic heads` 退出 0。迁移目录和 `down_revision` 搜索显示单链，远端 CI 进一步验证从空 PostgreSQL/PostGIS 升级到该 head。
- 当前工作流唯一入口为 [`.github/workflows/test.yml`](../../.github/workflows/test.yml)：PostgreSQL 16/PostGIS 3.4、Redis 7、fresh `alembic upgrade head`、完整 pytest，并拒绝任何 skip；没有部署步骤。
- 最新 `origin/main@2d58fe2d…` GitHub Actions run 为 `30742485347`，job `91482253170`，结论 `success`；日志为 `2074 passed, 814 warnings in 71.93s`，0 skip，fresh migration 成功。
- 该 run 只证明远端基线，不覆盖 R1 未提交的 A0 diff；A0C 专用分支的 CI 以 Draft PR 当前 head run 为准，不能用 baseline run 冒充交付 CI。两者都不证明真实腾讯/DEM、生产数据库、微信开发者工具/真机、部署或用户可用。

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

## 2.3 Legacy `app/agent` Rename Plan（仅计划）

### 影响面清单

- Python import：`app/agent/tasks.py` → `app.agent.segment_writer`；`tests/test_agent_segment_writer.py`、`tests/test_agent_tasks.py`。
- RQ 字符串任务：`app/admin/service.py::_AI_DRAFT_TASK`；`tests/test_admin_router.py` 对该字符串有断言。
- 队列/worker：`app/queue.py` 示例、`worker.py` 的 `ai_drafts` 注册和默认 `RQ_QUEUES`、`docker-compose.yml`、`docker-compose.dev.yml`。
- DB/管理兼容面：`segment_ai_drafts` 表和 admin draft endpoint 名称不随 Python 包改名。
- 当前文档：`docs/architecture-guide.md`、`docs/data-flow-guide.md`、ADR-009、产品/部署说明；历史 `docs/plans`、`docs/archive`、changelog 保留历史文字，不批量改写。

### 三种方案

| 方案 | 好处 | 主要风险 | 判断 |
|---|---|---|---|
| 直接把 `app/agent` 改为 `app/segment_draft_ai` | 最少重复文件 | 已排队 RQ job 仍反序列化旧字符串；混合版本 worker 可能 `ModuleNotFoundError`；紧急回滚困难 | 不采用 |
| 新目录 + 旧路径 compatibility shim | 新语义清楚；旧 job 和旧 worker 可继续执行；可分步切 producer | 短期两条 import 路径；必须明确 shim 移除门槛 | **推荐** |
| 永久保留 `app/agent`，新 Runtime 另起名 | 无现有迁移风险 | “agent”继续被误读为 Runtime，命名债长期存在 | 仅作无法迁移时兜底 |

### 推荐切换顺序

1. 在获准的独立任务中新增 `app/segment_draft_ai/{__init__.py,segment_writer.py,tasks.py}`，保持现有函数输入、DB 幂等和异常语义。
2. 将 `app/agent/segment_writer.py`、`app/agent/tasks.py` 变为无副作用的转发 shim；旧全限定函数路径必须仍可被 RQ import。此时 producer 仍发旧字符串。
3. 测试同一进程和真实 RQ worker 均可执行新旧路径；部署一个能同时消费两种路径的版本，重启订阅 `ai_drafts` 的 worker。
4. 只读检查 Redis/RQ queued、started、deferred、scheduled、failed registries，并确认所有 worker 已是兼容版本；这些是生产操作，另需部署 Task Packet 和授权。
5. 再把 `_AI_DRAFT_TASK` 切到 `app.segment_draft_ai.tasks.generate_segment_draft_task`。保留旧 shim，直到超过最大 job 生命周期、队列和 registry 均无旧路径、且无旧 worker。
6. 后续单独任务才删除 shim，并更新当前文档；历史归档只注明迁移，不重写历史证词。

回滚：producer 字符串恢复旧 shim 即可；新目录保留，不涉及 schema/data migration。若新 worker 异常，回滚应用镜像仍能消费旧路径；在旧 job 未清零前绝不能先删 shim。

最小测试：新旧 import 路径等价；新旧 task 的 pending-only upsert/人工编辑保护；admin enqueue 字符串；RQ worker 反序列化已排队旧 job；混合版本队列；异常/重试幂等；worker 队列订阅。A0 不移动任何代码。

## 2.4 Static Planning vs Realtime Navigation Conflict Report

| 冲突文字 | 当前真实行为 | A1 候选裁决 |
|---|---|---|
| [AGENTS.md](../../AGENTS.md) 禁止实时导航/动态改路，同时允许静态路线、GPX 和外部地图跳转 | 项目级产品边界本身已区分骑前静态交付与骑中动态行为 | 保持该不变量，并让下列产品决策与它使用同一边界 |
| [product-decisions.md](../../docs/agent-rules/product-decisions.md) `INV-P03` / `D-P04` 将“路径规划/路线生成”整体写成不做 | Route Draw 已通过腾讯 bicycling 生成骑前静态路径，并允许明确失败后的本地手画绕行 | 将禁令收窄到“骑中实时导航、语音、偏航重规划和自建全国路由”；明确允许骑前静态 Ride Plan 编译与受控 Provider 连接段 |
| 同文档 `D-P07` 要求路线生成由确定性服务负责 | [tencent_direction.py](../../app/route_book/tencent_direction.py)、draw snap、elevation、export 正是确定性服务 | 保留并强化：LLM 只表达意图/选择，不产坐标、距离、爬升、验证或导出 |
| [ADR-010](../../docs/adr/010-为什么不做实时导航.md) 禁止实时导航，但明确允许骑前规划和 GPX | 现有静态 Route Draw/GPX 与 ADR-010 一致 | 使 INV-P03/D-P04、AGENTS、架构总览与 ADR-010 用词对齐 |
| [architecture-guide.md](../../docs/architecture-guide.md) 仍写“骑行路线算法生成（只推荐历史轨迹）” | 代码已有真实腾讯骑行规划 | 将其标为过时基线并在 A1 更新当前能力；不能以旧文档否定现有代码 |

**candidate A1 decision boundary**：允许讨论和定义骑前静态 `RidePlan` 编译、官方核心路线的 access/core/return 拼接、受控腾讯 Provider 接入段、确定性校验及用户选择后的静态 GPX/TCX；继续禁止骑中 GPS 跟随、语音导航、偏航重规划、自建全国路由和 LLM 生成坐标。

**A1 may change**：`AGENTS.md`、`docs/agent-rules/product-decisions.md`、`docs/adr/README.md`、新增的 Agent-First ADR、`docs/architecture-guide.md`、`docs/agent-first/README.md`、`docs/agent-first/phase-a-implementation-spec.md`、`VELO_ORCHESTRATOR_STATE.yaml`。最终 ADR 编号以 A1 开始时的 `docs/adr/` 为准（当前最高为 012）。

**A1 must not change**：`app/`、`miniprogram/`、`migrations/`、`tests/`、依赖、workflow、compose、生产配置、Route Draw/Export API/交互/schema；也不改写三份 source 文档原文。

**A1 open questions**：产品文案是否保留“路径规划”统称，还是统一为“骑前静态规划”；官方核心路线允许被拼接到什么程度；用户选择前是否只能生成 draft、选择后何时可触发真实导出；这些由 A1 ADR 裁决，A0 不替 Tim 决定。

## 2.5 Phase A File-Level Breakdown

以下每一项都必须由 Orchestrator 重新校准 `origin/main` 后拆成一个独立 Task Packet；路径是候选 allowlist，不是当前授权。

### A1 — Architecture ADRs

- **目标**：裁决五个边界：骑前静态规划/骑中导航；单一有界主 Agent/确定性 Workflow；World Fact/Session/Run/Memory；Capability/Approval/副作用；旧 `app/agent` 命名迁移。
- **前置**：A0 经 Orchestrator `PASS`；当前代码与产品裁决重新核对。
- **允许文件**：`docs/adr/README.md`；建议新增 `docs/adr/013-骑前静态规划与骑中导航边界.md`、`014-agent-runtime与确定性工作流边界.md`、`015-world-session-run-memory边界.md`、`016-agent-tool权限与副作用边界.md`、`017-旧-app-agent-命名迁移.md`（若编号已占用则顺延）；以及 2.4 的 `A1 may change` 文档和根 State。
- **禁止范围**：运行代码、合同、schema/migration、API、小程序、依赖、队列和部署。
- **最小测试**：Markdown 链接/路径检查；冲突词搜索；`git diff --check`；受保护路径零 diff；每个 ADR 都含状态、事实、决策、后果、非目标和撤回条件。
- **退出门槛**：五项均有唯一裁决；INV-P03/D-P04/D-P07/ADR-010 不再矛盾；旧命名采用或拒绝 2.3 推荐方案；不偷偷选 Runtime 框架。
- **失败回滚**：只回滚 A1 新增/修改的文档与 State，代码无需回滚。
- **Orchestrator 判定**：逐项 `PASS/REVISE/HARD_BLOCK/DEFER`；任何产品边界未由 Tim 确认则不得进入 A2。

### A2 — Agent v0 Contracts

- **目标**：以 JSON Schema Draft 2020-12 建立语言中立、可版本化的控制面合同，不决定 TypeScript Runtime。
- **前置**：A1 通过；五个 ADR 的术语和副作用分类稳定。
- **允许文件**：`contracts/agent_v0/README.md`、`session_state.schema.json`、`map_action.schema.json`、`tool_call.schema.json`、`tool_result.schema.json`、`ride_plan_draft.schema.json`、`validation_result.schema.json`、`trace_event.schema.json`、`error.schema.json`；合同校验测试建议 `tests/contracts/test_agent_v0_contracts.py`；State/入口文档只做必要路由。
- **字段下限**：所有对象含 `schema_version`、稳定 ID、创建时间或序号和可扩展 `metadata`；Session 含 revision/intent/map state/candidates/selection/unknowns/pending approval；MapAction 含 action type/target/payload/expected session revision；ToolCall 含 tool name+version/capability/side-effect class/approval/idempotency/deadline/input；ToolResult 含 status/output refs/warnings/unknowns/error；RidePlanDraft 含 revision、access/core/return legs、geometry refs、约束、指标和 validation state；ValidationResult 含 hard/soft checks 和 deterministic evidence；TraceEvent 含 run/session/sequence/event type/input-output refs/side-effect ref；Error 含稳定 code/retryability/user-safe message/details。
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
- **case 下限**：`case_id`、`version`、`tags`、输入 Session/fixture、scripted tool outcomes、`expected_end_state`、`forbidden_actions`、确定性 `code_grader`、可接受 trace/错误、重跑 seed。覆盖天龙山 access/core/return、歧义位置、隐私、超时、无结果、断连、硬约束失败、approval、重试幂等和禁止副作用。
- **禁止范围**：LLM 评分作为唯一 grader、真实网络/生产 DB/storage/export、修改产品运行代码、为了凑 30 个只改文案的重复 case。
- **最小测试**：case schema 自校验；grader 自身正反测试；同 seed 重跑一致；每个 case 都具备五个必填控制字段；测试明确失败时输出状态 diff。
- **退出门槛**：至少 30 case 全部可重复；每个都有 expected end state、forbidden actions、code grader、标签和版本；grader 能抓到状态正确但禁用副作用发生、以及语言漂亮但状态错误两类问题。
- **失败回滚**：回退新增 case/grader，不改变 A2 合同；若合同不足，记录具体失败并退回 A2 `REVISE`。
- **Orchestrator 判定**：按覆盖矩阵和 grader 变异测试决定，不按 case 数量单项判过。

### A4 — Deterministic Fake Environment

- **目标**：在无网络/无生产资源的情况下，以确定性时钟、ID、状态和工具脚本运行 A3。
- **前置**：A2 合同通过；可与 A3 用独立 Task Packet 迭代，但不能并行写相同文件。
- **允许文件**：`tests/velobench/fake_env/environment.py`、`clock.py`、`ids.py`、`state_store.py`、`scripted_tools.py`、`failure_modes.py`、`side_effect_ledger.py`、`trace_ledger.py` 及专用测试/README。
- **行为下限**：可脚本化 `success`、`timeout`、`ambiguity`、`no_result`、`disconnect`、`hard_constraint_failure`；固定 clock/ID；乐观 revision；调用/approval/副作用/trace ledger；断点重放；未注册工具 fail-closed。
- **禁止范围**：socket/http、生产 DB/Redis、真实 filesystem storage、真实 export、真实腾讯或 DEM、import raw Provider/ORM、公共发布；Fake 不复制底层业务实现，只模拟 A2 高层合同。
- **最小测试**：六种结果；同 seed/replay 一致；超时不迟到写；disconnect 后状态可恢复；硬失败阻止 RidePlan validated；禁用能力不可达；side-effect/trace 顺序稳定。
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
| 旧 `app.agent` RQ 字符串和排队 job | 采用新目录 + 旧 shim；兼容版本先部署、检查所有 registry/worker，再切 producer，最后删 shim | 任一 queued/started/deferred/scheduled/failed job 或旧 worker 仍引用旧路径 |
| 把 RouteBook 当长期 World Model 中心 | RouteBook 保持现有用户路线聚合；长期 Fact/Traversal/Research 通过合同与独立边界引用，不向现有表盲塞字段 | A2/A5 需要把 Session/Memory/Agent trace 写进 RouteBook，或 RouteBook 变成所有对象 owner |
| 过早选择 TypeScript/框架 | A2 先做语言中立 JSON Schema，A3/A4 用评测暴露需求；SDK/TS/LangGraph 延后 | 合同和 30 case 稳定后，现有 Python 无法满足明确的隔离/吞吐/工具需求 |
| Fake 过度 mock，与真实高层合同不一致 | Fake 只模拟已定义的高层 tool contract；用真实代码的 schema/错误样例做 contract fixture，不复制底层算法 | 真实 Route Draw/Tencent/elevation/export 出现 Fake 无法表达的返回或失败语义 |
| grader 只评语言，不评状态 | 必填 expected_end_state/forbidden_actions/code grader；做 mutation 测试并核对 ledger/trace | 漂亮回答能在错误状态或发生禁用副作用时通过 |
| A0 文档被误读为生产授权 | README/State/spec 明写 A0 `PASS`、A0C `in_review`、A1–A5 blocked、deploy false；未来对象不等于 migration 授权 | 有人以 source/spec 为由改 runtime/schema、调用真实 Provider、导出或部署 |
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
