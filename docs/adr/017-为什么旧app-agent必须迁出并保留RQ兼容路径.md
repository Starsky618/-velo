# ADR-017: 为什么旧 `app/agent` 必须迁出并保留 RQ 兼容路径

> **状态：Proposed — A1.5，等待 Orchestrator 审查**
>
> **一句话核心决策：现有赛段 AI 草稿实现未来归属唯一 canonical package `app.segment_draft_ai`；`app.agent` 只能作为默认长期保留的 compatibility tombstone，用极薄 wrapper 继续执行旧 RQ serialized path，并永久禁止被新 Planning Agent Runtime 复用。**

## 1. 决策范围

本 ADR 只裁决命名空间所有权、RQ 序列化路径兼容和未来 M1/M2/M3 迁移顺序。它不实施代码搬迁，不修改 producer、worker、queue、compose、测试、schema、migration、API 或数据库，不部署，不开始 A2。

本决策不选择未来 Runtime 的 package 名、语言、SDK 或框架；`app.planning_agent` 与 `app.agent_control` 只是举例，不是命名结论。

## 2. 当前代码事实

- `app/agent/segment_writer.py` 通过 OpenAI-compatible client 调用 DeepSeek，输入赛段属性并生成赛段文案；它不是在线 Planning Agent。
- `app/agent/tasks.py` 定义 RQ task `generate_segment_draft_task(segment_id: int) -> None`，直接创建 `SessionLocal`，读取 `Segment`，并对 `SegmentAiDraft` 执行 pending-only 写入。
- `app/admin/service.py::_AI_DRAFT_TASK` 当前是字符串 `app.agent.tasks.generate_segment_draft_task`，并把它发往 `ai_drafts` 队列。
- RQ 2.7.0 把函数名、instance、args 和 kwargs 序列化成 job data，worker 执行时根据保存的完整 Python 路径 import callable。因此直接移除旧模块会破坏 queued、started、deferred、scheduled、failed registry 或重试中的旧 job。
- `app/queue.py`、`worker.py`、`docker-compose.yml` 与 `docker-compose.dev.yml` 都使用 `ai_drafts`；队列名称与 Python package 名称是两个独立合同。
- `segment_ai_drafts` 表、`Segment` / `SegmentAiDraft` 模型、admin AI draft API 和 `pending → human_edited → approved/rejected` 审核语义不需要因 Python 包改名而改变。
- 当前运行代码中不存在 Planning Session、Agent Run Controller、Tool Registry、VeloBench 或新 Planning Agent Runtime；未来 Runtime 的命名和技术栈仍为 deferred。

## 3. 考虑过的四个方案

### 方案 A：一次性直接 rename

将 `app/agent` 直接搬到新目录，并立即切换 producer。文件最少，但已序列化的旧 RQ job 会失去 import 路径，混合版本 worker 可能失败，回滚也会受制于队列中的新旧 job。拒绝。

### 方案 B：永久保留旧实现

不搬迁业务逻辑，新 Runtime 只换其他名称。它没有 RQ 迁移风险，但 `app.agent` 会继续被误读为 Agent Control Plane，且 ORM/LLM 业务逻辑永久占用了错误的 namespace。拒绝。

### 方案 C：复用 `app/agent` 给新 Runtime

在旧文案生成模块中逐步加入 Session、tool 和 controller。它会把直接 ORM/LLM task 与新 Runtime 权限边界混在一起，违反 ADR-014、015 与 016 的所有权和能力隔离。永久禁止。

### 方案 D：canonical 新包 + compatibility tombstone + 分阶段 producer 切换

真实实现未来迁入 `app.segment_draft_ai`；`app.agent` 只留旧 import/RQ 路径的极薄兼容层；先让所有 worker 兼容新旧路径，再以独立部署切 producer。选择。

## 4. 正式决策

选择方案 D。赛段 AI 草稿的唯一 canonical package 是：

```text
app.segment_draft_ai
```

未来结构为：

```text
app/segment_draft_ai/
  __init__.py
  segment_writer.py
  tasks.py
```

`app.agent` 的永久角色是 `legacy compatibility tombstone`；它不再拥有业务实现，也永久不拥有新 Planning Agent Runtime。

审查不变量是：**old RQ serialized path remains executable**；**producer switch after compatible workers**；**ai_drafts queue unchanged**；**DB/API unchanged**；**app.agent reuse for Planning Runtime forbidden**；**future removal requires new ADR**；**M1 before production Runtime**；**M2 requires deployment and worker evidence**。

## 5. Namespace ownership

- `app.segment_draft_ai` 拥有赛段文案生成与草稿 RQ task 的真实实现。
- `app.agent` 只拥有旧 import 和旧 serialized RQ path 兼容责任。
- 未来 Planning Runtime 必须拥有独立 namespace；即使未来 tombstone 被删除，`app.agent` 也不得被回收利用。
- A2 contracts、A3 VeloBench 与 A4 Fake Environment 不得 import `app.agent`，也不得复用其 ORM 或 LLM 逻辑。

## 6. 为什么命名为 `app.segment_draft_ai`

该名称同时限定了对象（segment）、产物（draft）和手段（AI），与现有代码责任一致。它不暗示通用 Agent、计划控制权或万能 AI 工具库，避免生成 `content_ai`、`ai_utils` 等会持续吸纳无关逻辑的模糊目录。

## 7. Compatibility tombstone 与长期 shim 策略

可保留 `app/agent/__init__.py`、`app/agent/segment_writer.py` 和 `app/agent/tasks.py`，但只能：

- 明确标记 deprecated / compatibility-only；
- 转发旧 Python import；
- 保持 `app.agent.tasks.generate_segment_draft_task` 可被 RQ import 和执行。

这些文件禁止包含新业务实现、复制 ORM/LLM 调用逻辑、产生第二次 DB/LLM 副作用，或成为新 Runtime 的入口。

**shim removal is not required**。旧 shim 默认可以无限期保留；两个极薄 wrapper 的维护成本，低于证明所有历史 job、failed registry、外部脚本与回滚镜像永不再用旧路径的成本。A1.5、A2、A3 和 A4 均不以删除 shim 为完成条件。

未来如要删除 shim，必须新开 ADR 和 Task Packet，并证明所有仍可能执行的旧路径引用均不存在。

## 8. M1：双路径兼容版本

未来独立实施任务才可：

1. 新建 `app/segment_draft_ai/{__init__.py,segment_writer.py,tasks.py}` 并迁入唯一真实实现。
2. 将旧 `segment_writer.py` 和 `tasks.py` 变为极薄 wrapper。
3. producer 继续 enqueue `app.agent.tasks.generate_segment_draft_task`，M1 期间禁止切换。
4. 部署同时支持新旧路径的 API 和全部 `ai_drafts` worker。
5. 用真实 worker 证明已排队旧 job 能在兼容版本中反序列化并执行。

M1 失败时回滚应用镜像；producer 仍使用旧路径，无需改写 Redis job。

## 9. M2：producer 切换

只有证明所有生产 worker 都支持新旧路径后，独立部署任务才能把 producer 切换为：

```text
app.segment_draft_ai.tasks.generate_segment_draft_task
```

M2 中 `ai_drafts` queue unchanged，旧 shim 继续保留。切换必须有实际 worker 版本证据与单独部署授权；混合版本期间不得让新路径 job 被旧 worker 消费。

M2 失败时只将 producer 字符串切回旧路径，由仍然存在的 shim 继续执行。

## 10. M3：稳定期

- 新 job 使用 canonical 新路径，旧 job 继续通过 shim 执行。
- 增加 architecture/import guard，任何新的非 shim 代码 import `app.agent` 都必须使测试失败。
- 旧 shim 默认继续保留，不把队列暂时为空视为必须删除的理由。

## 11. Wrapper 语义

`app.agent.segment_writer.generate_segment_draft` 只委托一次 `app.segment_draft_ai.segment_writer.generate_segment_draft`；`app.agent.tasks.generate_segment_draft_task` 只委托一次 `app.segment_draft_ai.tasks.generate_segment_draft_task`。

两个 wrapper 都必须保持旧函数签名，不创建 DB Session，不重复调用 LLM，不使用 wildcard import，不做复杂 `sys.modules` alias。旧模块与新模块不必是同一 module object。

## 12. 保持不变的合同

未来迁移不得改变：

- `ai_drafts` Redis queue 名称、`RQ_QUEUES` 配置和 worker 优先级；
- `segment_ai_drafts` 表和 `Segment` / `SegmentAiDraft` 模型；
- admin AI draft API；
- pending-only overwrite 和 `human_edited` / `approved` / `rejected` 保护；
- DeepSeek 配置、数据库 schema、migration 与用户可见行为。

## 13. 未来实施的测试门槛

M1/M2 至少必须机器化验证：

- canonical 模块保持现有成功与失败语义；
- 两个旧 wrapper 各只委托一次；
- 新旧 RQ 字符串都可 import 和执行；
- 已排队旧 job 可由兼容 worker 执行，producer 切换前后字符串正确；
- pending-only upsert、三类受保护状态和 `IntegrityError` 并发语义不变；
- `ai_drafts` 队列与 worker 订阅不变；
- 新增非 shim `app.agent` import 时 architecture test 失败。

主体行为测试迁到 canonical 模块；shim 测试只证明单次委托和旧 RQ 字符串兼容。

## 14. 回滚与数据边界

不得修改或重写已有 Redis job 的序列化函数路径，不得清空 Redis 作为迁移方案，不得在旧 job 仍可能执行时删除 shim。M1 和 M2 按前述镜像/producer 回滚；该迁移不需要数据库 migration 或 backfill。

## 15. 与 A2–A4 和 Phase B 的关系

A1.5 只完成架构裁决，不实施 M1/M2。ADR-017 若被 Accepted，A1 可收口为 `completed / PASS`，A2 才可转为 `ready_to_specify`。

实际 M1/M2 不阻塞 A2 contracts、A3 VeloBench 或 A4 Fake Environment；但 M1 必须在第一个生产 Planning Agent Runtime 或 Phase B live Agent integration 之前完成。M2 是独立部署任务，必须有 worker 兼容证据；本 ADR 不提前授权它。

## 16. 非目标与 reopen triggers

本轮不搬移/修改 `app/agent`，不创建 `app/segment_draft_ai`，不切 producer，不改 worker/queue/compose/test/schema/migration/API/DB，不选 Runtime package/语言/框架，不部署，不开始 A2。

以下证据可触发新 ADR 重评，不得直接改写本文：RQ 序列化合同发生破坏性改变；真实混合版本证据证明 M1/M2 无法防止丢 job 或重复副作用；有可审计证据表明 tombstone 产生了不可接受的安全/维护成本；或未来拟删除 shim。删除 shim 必须明确 `clarifies ADR-017` 或 `supersedes ADR-017`。

## 17. 引用路径

- [ADR-013：骑前静态规划边界](./013-为什么区分骑前静态规划与骑中实时导航.md)
- [ADR-014：单一有界主 Agent 与确定性 Workflow](./014-为什么在线规划采用单一有界主Agent与确定性工作流.md)
- [ADR-015：状态与记忆所有权](./015-为什么世界事实会话运行与长期记忆必须分离.md)
- [ADR-016：能力、审批与副作用](./016-为什么在线Agent的能力审批与副作用必须显式化.md)
- [Agent-First 文档入口](../agent-first/README.md)
- [Phase A 文件级实施规格](../agent-first/phase-a-implementation-spec.md)
- [根 Orchestrator State](../../VELO_ORCHESTRATOR_STATE.yaml)
- [旧赛段文案生成器](../../app/agent/segment_writer.py)
- [旧 RQ task](../../app/agent/tasks.py)
- [admin producer 字符串](../../app/admin/service.py)
- [RQ queue 定义](../../app/queue.py)
- [worker 队列订阅](../../worker.py)
