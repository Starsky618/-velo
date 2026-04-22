# ADR-002: 为什么选择 rq 不用 Celery

## 状态
accepted (2026-04-22)

## 上下文

velo 需要异步任务处理能力:
- GPX/FIT 文件解析(大文件 50MB / 50000 trackpoints,解析 5-30s)
- Strava 历史导入(每用户几百到几千 activity,跨 Strava API 限流需要异步慢推)
- 赛段自动匹配(对每个新 activity 在 PostGIS 粗筛 + 精确匹配,几秒)
- 通知事件检测(PR/KOM 实时判定)

Python 生态有两个主流任务队列选择:
- **Celery + RabbitMQ/Redis**: 工业标准,功能全,生态大
- **rq (Redis Queue) + Redis**: 轻量,专注 Redis 一种 broker

选型讨论发生在 v0 期(2026-03 初)。

## 决策

velo 使用 **rq + Redis** 作为异步任务队列。**不用 Celery**。

- Broker: Redis 7-alpine(已经作为缓存/状态存储)
- Worker: 独立 `velo-worker` 容器,启动 `python worker.py`
- 队列: 单队列 `rq:queue:default`,不分优先级
- 调度: 简单 enqueue / BLPOP,不用 rq-scheduler(已在 requirements.txt 但未启用)

## 理由

1. **rq 总代码量 < Celery 的 1/10**。rq 源码 3000 行左右,worker.py 启动脚本 31 行能跑,新人 2 小时内理解全流程。Celery 源码 30000+ 行,配置项数十个(broker_url / result_backend / task_serializer / task_routes / beat_schedule / worker_pool 等),学习曲线陡峭。

2. **已经有 Redis,不引入新组件**。velo 的 Redis 已经被用作 OAuth state 存储 + 限流计数器,rq 直接复用同一个 Redis 实例,零运维成本。换 Celery 若用 RabbitMQ 就多一个容器,用 Redis 又放弃了 Celery 最大优势(broker 多样性)。

3. **MVP 性能足够**。rq 单 worker 进程每秒可处理几十到上百任务。velo 当前日活 100 MAU × 每人日均 2 次上传 = 200 任务/日,峰值每分钟 < 10 任务。rq 性能天花板远高于需求。

4. **调试直观**。rq 任务失败在 Redis 里有明确的 failed job list,可以直接 `rq info` 看队列状态。Celery flower 虽然功能丰富但多一个 web 服务维护。

5. **fork 子进程模式崩溃隔离**。rq 默认每个任务 fork 一个子进程,任务崩溃不影响主 worker 进程,符合 velo 的容错需求(大文件解析失败不能拖垮 worker)。

## 后果

### 正面
- 运维简单,docker-compose 配置从 v0 期起保持稳定,没有为队列调优花过时间
- 任务失败 retry 3 次后进 failed queue,人工介入流程清晰
- 同步业务代码可以直接 enqueue 作为异步任务,不需要为 Celery 改写

### 负面
- 不支持任务链(chain)、任务组(group)、任务回调(chord)等高级编排。velo 目前场景都是简单的"enqueue 一个任务 → 任务完成",没触发这些需求。
- 单队列无优先级。如果未来需要"Strava 历史导入是慢任务优先级低,通知检测是快任务优先级高",需要拆多队列,rq 支持但要自己设计
- 社区活跃度比 Celery 低一个量级,遇到疑难问题 StackOverflow 答案少

### 触发重新评估的条件
- 日任务量 > 10 万(需要集群 worker + 任务分区)
- 需要复杂任务编排(chain/group/chord)且自己实现成本高
- 需要跨语言任务(velo 全 Python,暂无此需求)

## 违反代价

如果未来某次需求 PR 引入 Celery(或 Dramatiq / Huey 等其他队列),会触发:

1. **双队列维护**: 新老任务无法共享 worker,需要维护两套 worker 容器
2. **业务代码分裂**: `@shared_task` (Celery) vs rq 的 `q.enqueue()` 语法不同,业务逻辑无法简单复用
3. **部署复杂度翻倍**: 如果 Celery 用 RabbitMQ 就多一个容器 + 监控;用 Redis 就丢了 Celery 最大优势
4. **团队重新学习**: Celery 学习曲线陡,对 3 人团队是非必要成本

**防御措施**: 新增异步任务时,统一使用 `q.enqueue(func_name, *args)` 模式入队。禁止在 requirements.txt 加入 `celery` / `dramatiq` 等竞品。

## 相关文档

- 架构 guide v2 §3.1 worker 容器 / §3.2 worker 职责细则
- 数据流 guide 链路 1(本地上传链路用 rq) / 链路 3(Strava 导入用 scheduler 直接调用不入队列,与 rq 并存)
- ADR-001(为什么禁用 async def)— rq 同步性支持该决策
- 附录: `worker.py` 入口脚本 31 行
