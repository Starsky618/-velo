# 任务 0.8：app/queue.py 单一 Redis 连接源

## 🎯 目标

新建 `app/queue.py` 暴露 `redis_conn` / `default_queue` / `ai_drafts_queue` 单一真相源。同步重构现有 4 处散点 Redis 连接（worker.py / activity.service / cleanup_zombies / strava.client._redis）都改用 `from app.queue import redis_conn`。

## ⛓ 前置依赖

无。可独立跑。

## 📤 输出契约

| 产出 | 用途 |
|------|------|
| `app/queue.py` | 项目唯一 Redis 连接 + Queue 实例源 |
| `redis_conn` | 所有需要 Redis 的模块统一 import 此对象 |
| `default_queue` (velo) | 现有任务沿用 |
| `ai_drafts_queue` | v5 新 AI 草稿生成异步任务（task 1.B.1 / 3.A.3 使用） |

## 🧱 现状（grep 已验证）

| 散点位置 | 现状 |
|---------|------|
| `app/worker.py:24` | `redis_conn = Redis.from_url(...)` |
| `app/activity/service.py:31` | `_redis_conn = Redis.from_url(...) / _queue = Queue(...)` |
| `scripts/cleanup_zombies.py` | `Redis.from_url(...)` 局部 |
| `app/strava/client.py:59` | `_redis = Redis.from_url(settings.REDIS_URL)` |

合计 4 处需收敛。

## 🛠 完整代码

### `app/queue.py`（新建）

```python
"""Redis 连接 + RQ Queue 单一真相源。

设计：
    全项目所有 Redis 操作 / RQ Queue 实例都从这里 import，
    禁止各模块自己 Redis.from_url 或 Queue('xxx') 就地构造。
    
    单一源好处：
    - 统一连接池配置（max_connections / socket_keepalive）
    - 统一 Queue 命名约定（避免 "ai_drafts" / "ai-drafts" 拼写漂移）
    - 单元测试 mock 一处即可覆盖

使用：
    from app.queue import redis_conn  # 直接读写 Redis
    from app.queue import ai_drafts_queue  # enqueue RQ task
    ai_drafts_queue.enqueue('app.agent.tasks.generate_segment_draft_task', segment_id)
"""
from redis import Redis
from rq import Queue

from app.config import settings


# Redis 连接池（线程安全，单例可全局复用）
redis_conn = Redis.from_url(
    settings.REDIS_URL,
    decode_responses=False,  # RQ 要 bytes；如需 str 在调用点 .decode()
    socket_keepalive=True,
    socket_keepalive_options={},
)


# RQ Queue 实例（v5 用到的所有队列在此 expose，禁止调用方就地构造）
default_queue = Queue("velo", connection=redis_conn)
ai_drafts_queue = Queue("ai_drafts", connection=redis_conn)
```

### 改造 4 处现有散点

#### `app/worker.py`

```diff
- from redis import Redis
- from app.config import settings
- redis_conn = Redis.from_url(settings.REDIS_URL)
+ from app.queue import redis_conn

  # 行 31 Worker(...) 启动逻辑：从 env 读队列名，单 worker 多队列订阅
- queue = Queue("velo", connection=redis_conn)
- Worker([queue], connection=redis_conn).work()
+ import os
+ from app.queue import default_queue, ai_drafts_queue
+ queue_names = os.getenv("RQ_QUEUES", "velo,ai_drafts").split(",")
+ queues_map = {"velo": default_queue, "ai_drafts": ai_drafts_queue}
+ queues = [queues_map[name.strip()] for name in queue_names if name.strip() in queues_map]
+ Worker(queues, connection=redis_conn).work()
```

#### `app/activity/service.py`

```diff
- _redis_conn = Redis.from_url(settings.REDIS_URL)
- _queue = Queue("velo", connection=_redis_conn)
+ from app.queue import redis_conn as _redis_conn, default_queue as _queue
```

> 沿用旧别名 `_redis_conn` / `_queue`，避免本文件内大量 caller 改动。

#### `scripts/cleanup_zombies.py`

```diff
- from redis import Redis
- from app.config import settings
- r = Redis.from_url(settings.REDIS_URL)
+ from app.queue import redis_conn as r
```

#### `app/strava/client.py`

```diff
  # 行 59
- _redis = Redis.from_url(settings.REDIS_URL)
+ from app.queue import redis_conn as _redis
```

## ✅ 测试

### 启动验证（连接池单例）

```python
# tests/test_queue.py 新增
def test_redis_conn_is_singleton():
    from app.queue import redis_conn
    from app.queue import redis_conn as redis_conn_2
    assert redis_conn is redis_conn_2  # 模块级单例
    
def test_queues_share_connection():
    from app.queue import redis_conn, default_queue, ai_drafts_queue
    assert default_queue.connection is redis_conn
    assert ai_drafts_queue.connection is redis_conn
```

### 现有测试无回归

```bash
python3 -m pytest tests/ -x -q
```

预期：所有现有测试 passed（连接源换了，行为不变）。

### docker-compose env 同步

`docker-compose.yml` worker service 加：

```yaml
  worker:
    environment:
      RQ_QUEUES: "velo,ai_drafts"
```

部署时 `docker compose up --scale worker=3` 三个 worker 同时订阅两队列。

## 📝 commit

```
feat(queue): 任务 0.8 app/queue.py 单一 Redis 连接源

新建 app/queue.py：redis_conn / default_queue / ai_drafts_queue 三个单例
重构 4 处散点：worker.py / activity.service / cleanup_zombies / strava.client._redis
docker-compose worker 加 RQ_QUEUES env，单 worker 容器订阅多队列

为什么必须先做：
v5 §3.7.3 RQ async + admin/service.py enqueue 入口都依赖 ai_drafts_queue
不收敛会让 v5 + 现有 4 处散点继续扩散，未来连接池配置改一处漏六处
```

## 🔍 自检三问

1. **崩溃恢复**：app/queue.py 模块级 Redis.from_url 在 import 时执行——Redis 服务挂了会怎样？  
   → Redis.from_url 是惰性的（不立即连），首次调用 redis_conn.get() 等才尝试连接。import 不会抛错。

2. **陷阱核查**：`decode_responses=False` 改了之前？  
   → 现有散点都没显式设 decode_responses（默认 False）。统一显式设 False 防未来误改。如个别 caller 需要 str 在调用点 .decode()。

3. **下游波及**：worker 改 RQ_QUEUES env 模式后，旧部署（无此 env）会怎样？  
   → 给 default 值 "velo,ai_drafts"，env 不设也跑得通；但生产部署时 docker-compose 必须显式加 env，否则忘了改的部署会订阅 ai_drafts 但 ai_drafts 表/RQ 还没准备好——硬要求 docker-compose 同 commit 改。
