# ADR-001: 为什么禁用 async def,全用同步模式

## 状态
accepted (2026-04-22)

## 上下文

FastAPI 原生同时支持同步 `def` 和异步 `async def` 两种路由定义方式。SQLAlchemy 2.0 同样同时支持同步 `Session` 和异步 `AsyncSession`。rq 作为任务队列走同步模式,但业界主流(Celery)和 asyncio 生态(httpx / aiohttp)都偏好异步。

velo 启动时(v0 期,2026-03 前后)技术栈选型讨论过:要不要 FastAPI 用 async 路由 + SQLAlchemy 异步 session + httpx 异步调 Strava API?

async 的理论优势:
- 高并发 I/O 场景下线程池不阻塞,QPS 天花板更高
- httpx 调 Strava API 时释放事件循环
- 时髦,业界热门

async 的实际代价:
- async/sync 混用死锁(任何一个同步函数里调 async 必须 await,任何 async 调同步要用 run_in_executor)
- SQLAlchemy 异步 session 比同步 session 多一层抽象,ORM lazy loading 行为不一致
- 调试困难:traceback 断在 coroutine 里
- rq 本身是同步的,worker 代码和 API 代码无法共享业务逻辑函数

## 决策

velo 后端**全部使用同步 `def`**。**禁止在任何业务代码中使用 `async def`**。

- FastAPI 路由: 同步 `def endpoint():`
- SQLAlchemy: 同步 `Session` + `sessionmaker`
- 调第三方 API (Strava / 微信): 同步 `requests` 或 `httpx.Client` (非 AsyncClient)
- rq worker: 原生同步

## 理由

1. **团队 3 人学生,认知负担优先**。async 正确性需要理解 event loop / coroutine / Future / Task / 同步桥 5 个概念。同步代码只需要理解函数调用。出 bug 时的调试成本是指数级差异。

2. **规模不达 async 优势阈值**。velo v1 目标用户量 100 人 MAU,v3 目标 5000 MAU。uvicorn 同步模式 2 workers × 10 threads = 20 并发,峰值 QPS 约 200-500。严肃骑手日活高峰也就几十并发,同步模式绰绰有余。

3. **Worker 进程物理分离**。慢任务(GPX 解析 / Strava 历史导入)在 worker 容器异步执行,API 容器不需要承担长任务,自然不需要 async 释放线程。

4. **生态一致性**。rq 同步 + SQLAlchemy 同步 + FastAPI 同步,业务代码可以在 API 层和 worker 层完全共享(如 `activity.worker.save_parse_result` 被 Strava import_scheduler 复用)。换 async 这个复用要拆成两套函数。

5. **未来切换成本可控**。如果真到 async 价值出现的那天(日请求过百万),velo 的业务逻辑函数都是纯同步 `def`,加层 async wrapper 即可,不需要重写所有业务代码。

## 后果

### 正面
- 心智模型极简,新成员上手 1 天内能改业务逻辑
- 调试链路直观,stack trace 清晰
- 业务代码跨 API/worker 层完全复用

### 负面
- QPS 天花板低于异步架构(同机器对比约 5-10 倍差距)
- Strava API 调用时线程阻塞,单个慢 API 影响当前线程其他请求(但 worker 2 进程 × 10 线程 = 20 并发不是问题)
- 与业界"现代化 Python Web"潮流不一致,招新人时可能需要解释选型

### 触发重新评估的条件
- 日均请求 > 100 万(当前预期 v5 完成时日均约 5000-20000)
- API 响应 p95 > 500ms 且瓶颈确认在线程池不足而非下游慢
- 团队扩张到 10 人以上,async 学习成本可分摊

## 违反代价

如果未来某次 PR 加入 `async def`,会触发以下连锁故障:

1. **混用死锁**: async 路由调用同步 SQLAlchemy 会在高负载下偶发死锁,极难复现
2. **session 管理崩溃**: FastAPI `Depends(get_db)` 返回同步 session,async 路由无法正确使用
3. **测试框架不兼容**: pytest-asyncio 和当前 pytest 同步测试套件要并存配置
4. **代码复用断裂**: 该 async 函数无法在 worker 容器复用,需要维护两套版本

**防御措施**: CLAUDE.md 已在"技术栈(不可变更)"章节明确声明。每次 code review(双审判机制)必须 grep `async def` 清零。

## 相关文档

- CLAUDE.md 第 50 行: "Python 3.11+ / FastAPI(**同步模式,禁止 async def**)"
- 架构 guide v2 §3.2 "api 全同步模式(见 ADR-001,禁止 async def)"
- 数据流 guide 链路 1-6 所有代码路径均同步
- ADR-002(为什么选择 rq 不用 Celery)— rq 同步性是本决策的支撑
