"""
Redis 连接 + RQ Queue 单一真相源——"全屋总进水阀"。

设计：
    全项目所有 Redis 操作 / RQ Queue 实例都从这里 import，禁止各模块自己
    `Redis.from_url(...)` 或 `Queue('xxx', connection=...)` 就地构造。

    类比：原来每个房间自己装一根独立水管接到自来水厂，房子大了水管十几根
    互相打架；现在全屋一个总进水阀，每个龙头分接——配置改一处全屋同步。

为什么单一源：
    - **统一连接池配置**（max_connections / socket_keepalive 等）改一处即可
    - **统一 Queue 命名**（避免 'ai_drafts' / 'ai-drafts' 拼写漂移成两个队列）
    - **测试 mock 简单**——patch 一处 attribute 全项目生效，不必每个 caller
      模块都各自 mock `redis.Redis.from_url`

使用：
    # 通用 Redis（限速 / RQ / 一次性消费等）
    from app.queue import redis_conn
    redis_conn.set(key, value, ex=300, nx=True)

    # 用户请求链路上的热图缓存（网络黑洞时必须有界失败）
    from app.queue import heatmap_redis_conn
    heatmap_redis_conn.get(key)

    # enqueue RQ 异步任务
    from app.queue import ai_drafts_queue
    ai_drafts_queue.enqueue('app.agent.tasks.generate_segment_draft_task', segment_id)

注意事项：
    - Redis.from_url 是惰性的（不立即连），import 此模块不会抛错——首次调用
      redis_conn.get() 等才尝试连接 → 测试环境无 Redis 时只要不真调就 OK
    - decode_responses=False：RQ 内部要 bytes；如个别 caller 需要 str，在
      调用点 `.decode()`（统一显式 False 防未来误改造成 RQ 失效）
    - Queue 实例**不 import 时执行 enqueue**——只是创建一个 Queue 对象指向
      Redis 中的 list key，真正读写要等 enqueue / dequeue 时才发生
"""
from redis import Redis
from rq import Queue

from app.config import settings


# Redis 连接池——线程安全的单例，全项目共享
# socket_keepalive=True 防长连接被中间网络设备 silently drop（生产 docker
# 网络偶发现象，不开 keepalive 会让 Worker 卡死在已断的 connection 上）
redis_conn = Redis.from_url(
    settings.REDIS_URL,
    decode_responses=False,
    socket_keepalive=True,
    socket_keepalive_options={},
)

# 热图会在请求线程上读写 Redis，还有后台续租线程。通用 redis_conn
# 不设 socket_timeout，因为 RQ 的阻塞取队列需要长读；热图必须使用
# 独立有界连接池，否则 Redis 网络黑洞会把请求和续租线程永久卡住。
heatmap_redis_conn = Redis.from_url(
    settings.REDIS_URL,
    decode_responses=False,
    socket_keepalive=True,
    socket_keepalive_options={},
    socket_connect_timeout=1.0,
    socket_timeout=1.0,
    retry_on_timeout=False,
)


# RQ Queue 实例——v5 用到的所有队列在此 expose，禁止 caller 就地构造
# 命名约定：snake_case + 与 enqueue 字符串一致（防拼写漂移）
#
# ⚠️ 新增 Queue 时必须**同步**修改下面 4 处（漏一处队列就是孤儿）：
#   1. 本文件：expose Queue 实例（如 `new_queue = Queue("new_q", ...)`）
#   2. worker.py: _QUEUES_MAP 登记 "new_q" → new_queue
#   3. docker-compose.yml: worker service 的 RQ_QUEUES env 加 "new_q"
#   4. 调用方 enqueue：`from app.queue import new_queue` + `.enqueue(...)`
default_queue = Queue("velo", connection=redis_conn)
ai_drafts_queue = Queue("ai_drafts", connection=redis_conn)
