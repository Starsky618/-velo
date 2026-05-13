# 任务 0.5：scheduler Redis 连接复用

## 🎯 目标

`app/strava/import_scheduler.py:187-198` 当前在循环内 `Redis.from_url(settings.REDIS_URL)` 造连接，每次 tick 重建——改为复用 task-0.8 建好的全局 `from app.queue import redis_conn`。

## ⛓ 前置依赖

**task-0.8（app/queue.py 必先建）**。

## 📤 输出契约

无新对外 API。仅消除连接散点。

## 🧱 现状（grep 已验证）

`app/strava/import_scheduler.py`：

| 行 | 现状 |
|----|------|
| 188-189 | 函数内部 `from redis import Redis; from app.config import settings`（局部 import） |
| 193 | `r = Redis.from_url(settings.REDIS_URL)` 每次 tick 重建 |
| 297 | 同样位置（另一段代码块）`r = Redis.from_url(...)` |

## 🛠 完整代码

`app/strava/import_scheduler.py`：

```diff
+ # 模块顶部
+ from app.queue import redis_conn

  # 行 185-200 块
  # v4 I9：连续 2 次空才判完成（防 Strava 偶发空返回）
- from redis import Redis
- from app.config import settings
  
  empty_key = f"strava:tier1_empty:{import_task.id}"
  try:
-     r = Redis.from_url(settings.REDIS_URL)
-     empty_count = r.incr(empty_key)
-     r.expire(empty_key, 86400)
+     empty_count = redis_conn.incr(empty_key)
+     redis_conn.expire(empty_key, 86400)
  except Exception:
      logger.warning("Redis 不可用，tier1 空返回降级为立即完成")
      empty_count = 2
-     r = None

  # 类似处理行 297 那段
```

> 检查文件其余位置是否有 `r.<method>(...)` 引用 r（局部变量）—— 删除 r 赋值后所有 r 调用换 redis_conn 直调。

## ✅ 测试

```bash
python3 -m pytest tests/test_strava_import*.py -x -q
```

预期：现有 import scheduler 测试全 passed。本 task 是连接源改造，不改业务逻辑。

## 📝 commit

```
refactor(strava): 任务 0.5 scheduler Redis 连接复用

import_scheduler.py 两处 Redis.from_url(...) → from app.queue import redis_conn
消除连接散点（task-0.8 单一源）
```

## 🔍 自检三问

1. **崩溃恢复**：redis_conn 单例连接断开（PG / Redis 重启）→ 自动重连吗？  
   → redis-py 内置连接池有自动重连。task-0.8 的 redis_conn 默认配置 socket_keepalive=True 也兜底。

2. **陷阱核查**：r = None 路径删了，except 分支后续代码引用 r 吗？  
   → 重读除了 r.incr / r.expire 别的不调 r。删完检查无残留 NameError 风险。

3. **下游波及**：scheduler 容器单独跑（v4 task 7.9 部署），改完后 docker 重启时 redis_conn 模块级初始化能跑通吗？  
   → app/queue.py 模块级 `redis_conn = Redis.from_url(settings.REDIS_URL)`，Python import 时完成，scheduler.py 顶部 import 无副作用。
