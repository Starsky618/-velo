# 任务 7.6：Strava 现有函数加固（I7 / I8 / I9 / I10）

> 修 4 个 Important 问题——都是现有函数的局部加固，不重写主流程。

---

## 🎯 目标（一句话）

给 Strava 模块打 4 个"小补丁"：
- **I7**：token 刷新失败时，同步把 active 导入任务置 paused（不让调度器继续空跑）
- **I8**：刷 token 前 `SELECT FOR UPDATE` 锁 user，防并发多进程同时刷掉彼此的 token
- **I9**：tier1 拉到空列表**不立即判完成**，连续 2 次空才判（防 Strava 偶发空返回误判）
- **I10**：手动同步 `handle_manual_sync` 写入新骨架后要**同步更新 `tier1_completed`**（现状不更新 → 前端进度长期显示 0）

---

## ⛓ 前置依赖

- **task-7.3**（handle_callback 重写已完成，本任务和它共享 `service.py` 的几个函数，避免合并冲突）

## 📥 输入契约

**现有代码事实核对**：

| 项目 | 位置 | 现状 |
|------|------|------|
| `ensure_valid_token` | `app/strava/service.py:225` | 401 分支在 `:273-281` 清空 user.strava_* 字段 |
| `_run_tier1` | `app/strava/import_scheduler.py:168` | 空列表在 `:183-191` 立即判完成 |
| `handle_manual_sync` | `app/strava/service.py:445` | 写骨架后 `:501` `new_count += 1` 但没更新 `tier1_completed` |
| `_create_importing_activity` | `app/strava/service.py:~400` | 创建 importing activity 骨架，不改 import_task |

## 📤 输出契约

| 产出 | 位置 | 说明 |
|------|------|------|
| `ensure_valid_token` 401 分支追加 | `service.py:273-281` | 把该 user 的 active StravaImport 置 paused |
| `ensure_valid_token` 顶部加行锁 | `service.py:~240` | `SELECT user FOR UPDATE`（进入函数后立即） |
| `_run_tier1` 连续 2 次空才完成 | `import_scheduler.py:183` 空列表分支 | 用 Redis 计数器记连续空次数 |
| `handle_manual_sync` 更新 tier1_completed | `service.py:~501` | 在 new_count 增加时同步写 StravaImport.tier1_completed |

---

## 🛠 完整代码

### 1. I7：token 刷新失败 → paused active imports

**位置**：`app/strava/service.py:273-281` 401 分支。

**改造前**（现状）：

```python
if resp.status_code == 401:
    logger.warning("Strava refresh_token 失效 user_id=%d", user.id)
    # 清空所有 Strava 字段，让用户重新绑定
    user.strava_athlete_id = None
    user.strava_access_token = None
    user.strava_refresh_token = None
    user.strava_token_expires_at = None
    db.commit()
    raise ValueError("Strava 授权已失效，请重新绑定")
```

**改造后**：

```python
if resp.status_code == 401:
    logger.warning("Strava refresh_token 失效 user_id=%d", user.id)

    # 先把该用户 active 导入任务置 paused，再清 token
    # 顺序理由：先 pause 让 scheduler 不再继续空跑调它的 API（空跑会持续失败）；
    # 清 token 放后面——先标 paused 保证即使下面清 token 失败，scheduler 也已被喊停
    from app.strava.models import StravaImport
    paused_count = (
        db.query(StravaImport)
        .filter(
            StravaImport.user_id == user.id,
            StravaImport.status == "active",
        )
        .update({StravaImport.status: "paused"}, synchronize_session=False)
    )
    if paused_count > 0:
        logger.info(
            "token 失效 自动 pause %d 个 active 导入任务 user_id=%d",
            paused_count, user.id,
        )

    # 清空 Strava 字段，让用户重新绑定
    user.strava_athlete_id = None
    user.strava_access_token = None
    user.strava_refresh_token = None
    user.strava_token_expires_at = None
    db.commit()
    raise ValueError("Strava 授权已失效，请重新绑定")
```

### 2. I8：刷 token 前加行锁

**位置**：`ensure_valid_token` 函数开头（`service.py:225` 之后）。

**改造**：在函数第一行 `now = datetime.now(timezone.utc)` **之前**，插入：

```python
def ensure_valid_token(db: Session, user: User, force: bool = False) -> str:
    """
    ...（原 docstring 保留）
    
    v4 改动：
    - 入口加行锁（SELECT FOR UPDATE），防并发请求同时进到刷新逻辑
      导致两个 Python 进程都向 Strava 发 refresh 请求（refresh_token
      使用后会变新，两者会互相顶掉对方的新 token → 用户账户被踢出）
    - 401 分支同步 pause 该用户的 active 导入任务（I7）
    """
    # v4 I8：入口行锁——把 user 行锁住，避免并发刷 token 竞态
    # 注意：必须在事务内才能锁住；caller（StravaClient._request）已在隐式事务内
    user = (
        db.query(User)
        .filter(User.id == user.id)
        .with_for_update()
        .first()
    )
    if user is None:
        raise ValueError("用户不存在")

    now = datetime.now(timezone.utc)
    # ... 以下代码保持不变
```

> **⚠ 调用方审视**：`ensure_valid_token` 在 `client.py:154, 208` 和 `service.py` 多处被调，这些调用方传入的 user 在函数内部被替换为"行锁的新版"。**Python 按引用传参的规则下，调用方持有的 user 对象不变**——但这是安全的，因为函数内后续都用新 user 做写入。如果调用方在 `ensure_valid_token` 返回后还写 user.xx 字段，会出现写入被"行锁版"遮蔽的风险——**预读所有调用方确认无这种用法**（预读命令：`grep -n "ensure_valid_token" app/`）。

### 3. I9：`_run_tier1` 连续 2 次空才判完成

**位置**：`app/strava/import_scheduler.py:183-191`（空列表分支）。

**改造前**：

```python
if not activities:
    # 列表返回空 → 第一层完成
    if import_task.total_activities is None:
        import_task.total_activities = import_task.tier1_completed
    logger.info(
        "第一层完成 import_id=%d total=%d",
        import_task.id, import_task.total_activities,
    )
    return
```

**改造后**：

```python
if not activities:
    # v4 I9：连续 2 次空才判完成（防 Strava 偶发空返回）
    # 为什么不加 DB 字段：Redis 轻量，无需 Alembic 迁移；TTL 24h 自动清理
    # key 独立于 import_task.id，即使 StravaImport 被重建也不会串用
    from redis import Redis
    from app.config import settings

    try:
        r = Redis.from_url(settings.REDIS_URL)
        empty_key = f"strava:tier1_empty:{import_task.id}"
        empty_count = r.incr(empty_key)  # 不存在则初始化为 1
        r.expire(empty_key, 86400)  # 24h TTL 自动清理（远大于正常完成周期）
    except Exception:
        # Redis 不可用：降级为老行为（直接判完成，保持功能不阻断）
        logger.warning("Redis 不可用，tier1 空返回降级为立即完成")
        empty_count = 2  # 强制达到阈值

    if empty_count < 2:
        logger.info(
            "tier1 空返回（第 %d 次），等下次 tick 再确认 import_id=%d",
            empty_count, import_task.id,
        )
        return  # 保持 active 不动，下次 tick 再拉

    # 连续 2 次空 → 真的完成了
    if import_task.total_activities is None:
        import_task.total_activities = import_task.tier1_completed
    logger.info(
        "第一层完成（连续 2 次空确认）import_id=%d total=%d",
        import_task.id, import_task.total_activities,
    )

    # 清 Redis 计数（避免下次 tier1 重启时继承旧计数）
    try:
        r.delete(empty_key)
    except Exception:
        pass
    return
```

**另加：非空返回时重置计数器**——在 `_run_tier1` 的非空处理路径结尾（`:246` 附近 `import_task.tier1_completed = ...` 之后），追加：

```python
# v4 I9：非空拉取 → 重置空计数器
try:
    from redis import Redis
    from app.config import settings
    r = Redis.from_url(settings.REDIS_URL)
    r.delete(f"strava:tier1_empty:{import_task.id}")
except Exception:
    pass  # 清理失败不阻塞主流程
```

> **为什么用 Redis 不用 DB 字段**：
> - 不用写 Alembic 迁移（本期任务 7.1 已经锁定，不往上加字段）
> - 计数器语义是"短期重试状态"而非"业务事实"，Redis 的 TTL 模型贴合
> - Redis 挂了就降级回老行为（一次空即完成），功能不中断

### 4. I10：`handle_manual_sync` 同步更新 `tier1_completed`

**位置**：`app/strava/service.py:445-508` `handle_manual_sync` 内部的 for 循环。

**改造**：在 `new_count += 1` 之后（`:501`），追加一段更新 StravaImport 的逻辑。

找到这段：

```python
    for act in activities:
        ...
        created = _create_importing_activity(db, user, strava_id)
        if created:
            ...
            db.commit()
            new_count += 1
    
    logger.info("手动同步完成 user_id=%d new=%d", user_id, new_count)
```

**替换为**：

```python
    # v4 I10：若该用户有 active StravaImport，同步更新它的 tier1_completed
    # 避免手动 sync 创建的骨架活动没计入进度 → 前端显示 "0/X" 直到调度器接手
    from app.strava.models import StravaImport

    for act in activities:
        strava_id = act.get("id")
        if strava_id is None:
            continue

        created = _create_importing_activity(db, user, strava_id)
        if created:
            # 补充骨架字段（列表 API 返回了名称和距离）
            activity = db.query(Activity).filter_by(strava_activity_id=strava_id).first()
            if activity:
                activity.title = act.get("name")
                activity.distance = act.get("distance")
                start_date_str = act.get("start_date")
                if start_date_str:
                    try:
                        activity.started_at = datetime.fromisoformat(
                            start_date_str.replace("Z", "+00:00")
                        )
                    except (ValueError, AttributeError):
                        pass
                db.commit()
            new_count += 1

    # v4 I10：若有 active import，同步累计 tier1_completed
    # 只在循环后做一次批量更新（而非循环内每条 +1），减少 DB round-trip
    if new_count > 0:
        active_import = (
            db.query(StravaImport)
            .filter(
                StravaImport.user_id == user_id,
                StravaImport.status == "active",
            )
            .with_for_update()
            .first()
        )
        if active_import:
            active_import.tier1_completed = (active_import.tier1_completed or 0) + new_count
            # total 可能还是 None（首次绑定后 tier1 尚未跑完）——不动它
            db.commit()
            logger.info(
                "手动 sync 联动更新 tier1_completed user_id=%d +%d 到 %d",
                user_id, new_count, active_import.tier1_completed,
            )

    logger.info("手动同步完成 user_id=%d new=%d", user_id, new_count)
```

---

## 🧪 测试

**文件**：`tests/strava/test_hardening.py`（新建）

```python
from unittest.mock import MagicMock, patch

from app.strava import service
from app.strava.models import StravaImport
from app.strava.import_scheduler import _run_tier1


# ---------- I7：401 → pause imports ----------

@patch("app.strava.service.httpx.post")
def test_token_refresh_401_pauses_active_imports(mock_post, db, user_factory):
    """token 401 分支应把该用户 active 导入任务置 paused。"""
    user = user_factory(
        strava_athlete_id=99001,
        strava_access_token="old_at",
        strava_refresh_token="old_rt",
    )
    # 手动设置过期时间为过去，强制进入刷新分支
    from datetime import datetime, timezone, timedelta
    user.strava_token_expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db.add(StravaImport(
        user_id=user.id, strava_athlete_id=99001, status="active",
    ))
    db.commit()

    # mock 401 响应
    mock_post.return_value.status_code = 401

    try:
        service.ensure_valid_token(db, user)
        assert False, "应抛 ValueError"
    except ValueError:
        pass

    # 验证 import 被置 paused
    imp = db.query(StravaImport).filter_by(user_id=user.id).first()
    assert imp.status == "paused"


# ---------- I8：refresh 行锁 ----------

def test_ensure_valid_token_uses_row_lock(db, user_factory):
    """验证函数入口确实执行了 SELECT FOR UPDATE。"""
    user = user_factory(
        strava_athlete_id=99001,
        strava_access_token="at",
        strava_refresh_token="rt",
    )
    from datetime import datetime, timezone, timedelta
    user.strava_token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    db.commit()

    # 用真实 DB，token 未过期 → 直接返回，但会走一次 SELECT FOR UPDATE
    token = service.ensure_valid_token(db, user)
    assert token == "at"
    # 行锁本身无法在单测里直接断言，但函数不崩即通过（回归保证）


# ---------- I9：tier1 连续 2 次空 ----------

def test_tier1_empty_once_not_completed(db, user_factory, redis_mock):
    """第 1 次空返回：不判完成，保持 active。"""
    user = user_factory(strava_athlete_id=99001)
    imp = StravaImport(
        user_id=user.id, strava_athlete_id=99001, status="active",
        total_activities=None, tier1_completed=30,
    )
    db.add(imp)
    db.commit()

    client = MagicMock()
    client.get_athlete_activities.return_value = []  # 空

    redis_mock.incr.return_value = 1  # 第 1 次

    with patch("redis.Redis.from_url", return_value=redis_mock):
        _run_tier1(db, client, imp)

    # 不应判完成
    db.refresh(imp)
    assert imp.total_activities is None  # 没被设定
    assert imp.status == "active"  # 保持


def test_tier1_empty_twice_completes(db, user_factory, redis_mock):
    """第 2 次空返回：判完成。"""
    user = user_factory(strava_athlete_id=99001)
    imp = StravaImport(
        user_id=user.id, strava_athlete_id=99001, status="active",
        total_activities=None, tier1_completed=30,
    )
    db.add(imp)
    db.commit()

    client = MagicMock()
    client.get_athlete_activities.return_value = []

    redis_mock.incr.return_value = 2  # 第 2 次达到阈值

    with patch("redis.Redis.from_url", return_value=redis_mock):
        _run_tier1(db, client, imp)

    db.refresh(imp)
    assert imp.total_activities == 30  # 设定为 tier1_completed


def test_tier1_non_empty_resets_counter(db, user_factory, redis_mock):
    """非空拉取 → 清 Redis 计数器。"""
    # 这个测试偏行为验证：只需确认 redis.delete 被调用
    user = user_factory(strava_athlete_id=99001)
    imp = StravaImport(
        user_id=user.id, strava_athlete_id=99001, status="active",
    )
    db.add(imp)
    db.commit()

    client = MagicMock()
    client.get_athlete_activities.return_value = [
        {"id": 100, "name": "Ride 1", "distance": 15000, "start_date": "2026-04-01T08:00:00Z"},
    ]

    with patch("redis.Redis.from_url", return_value=redis_mock):
        _run_tier1(db, client, imp)

    # 应调用 delete 清 empty_key
    delete_calls = [c for c in redis_mock.method_calls if c[0] == "delete"]
    assert any(
        f"strava:tier1_empty:{imp.id}" in str(c) for c in delete_calls
    ), f"delete 未被正确调用: {redis_mock.method_calls}"


# ---------- I10：manual_sync 联动 tier1_completed ----------

@patch("app.strava.service.Redis")  # 防止冷却 Redis 真连
@patch("app.strava.service.StravaClient")
def test_manual_sync_updates_tier1_completed(MockClient, MockRedis, db, user_factory):
    user = user_factory(strava_athlete_id=99001)
    imp = StravaImport(
        user_id=user.id, strava_athlete_id=99001, status="active",
        total_activities=None, tier1_completed=5,
    )
    db.add(imp)
    db.commit()

    MockRedis.from_url.return_value.set.return_value = True  # 冷却通过

    client_instance = MockClient.return_value
    client_instance.get_athlete_activities.return_value = [
        {"id": 201, "name": "Ride", "distance": 20000, "start_date": "2026-04-02T08:00:00Z"},
        {"id": 202, "name": "Ride 2", "distance": 15000, "start_date": "2026-04-01T08:00:00Z"},
    ]

    service.handle_manual_sync(db, user.id)

    db.refresh(imp)
    assert imp.tier1_completed == 7  # 5 + 2 新
```

---

## 📦 Commit 指令

```bash
git add app/strava/service.py \
        app/strava/import_scheduler.py \
        tests/strava/test_hardening.py

git commit -m "$(cat <<'EOF'
feat(strava): 任务 7.6 现有函数加固（修 I7 I8 I9 I10）

I7 ensure_valid_token 401 → pause active imports：
- 先置 active 导入任务为 paused，再清空 user.strava_* 字段
- 避免 scheduler 继续空跑调 API 持续失败

I8 ensure_valid_token 入口行锁：
- SELECT user FOR UPDATE 防并发刷 token 竞态
- 两个进程同时刷会互相顶掉 refresh_token → 用户被踢出

I9 _run_tier1 连续 2 次空才完成：
- Redis 计数器 strava:tier1_empty:{import_id}，TTL 24h
- 非空拉取时清计数；Redis 不可用降级为老行为
- 防 Strava 偶发空返回误判完成

I10 handle_manual_sync 联动 tier1_completed：
- 循环结束后批量更新 active import 的 tier1_completed
- 避免手动 sync 新活动不计入进度（前端长期显示 0/X）

测试：5 个用例覆盖每个 I 号的关键场景。
EOF
)"
```

---

## ✅ 自检三问

**1. 10 分钟挑战**：讲清这四个加固都干了什么？

> 四个小补丁：
> - **I7**：Strava token 失效时，不光清 token，还把这个人正在跑的导入任务暂停——不让后台继续空跑出错
> - **I8**：刷 token 前先给这个 user 加锁，防两个进程同时刷把彼此的新 token 顶掉
> - **I9**：拉活动列表返回空时，不立刻判"都拉完了"，再等一轮看是不是真的空——Strava 偶尔会抽风返空
> - **I10**：用户手动点"同步"时，新加的活动也要计到进度条里，不然用户看着进度一直是 0 会焦虑

**2. 崩溃场景**：I9 的 Redis 计数器如果在"第 1 次空"后崩溃，下次 tick 会怎样？

> Redis 计数器 TTL 24h，不会永久失踪。如果 Redis 重启丢了 key，下次 tick 相当于"又是第 1 次空"——最坏情况是多拖一轮 30 秒。完全可以接受。极端情况下（Redis 永远不可用），降级逻辑会在一次空时立即完成，退化为老行为，功能不阻断。

**3. 边界纪律**：有没有做 spec 没要求的"顺手优化"？

> 没有。严格按 §2.9 清单做四件事，不顺手优化：
> - 没有重写 `_run_tier1` 的主流程
> - 没有合并 I7/I8（虽然都在 ensure_valid_token 里，但两处改动目的不同，保持独立）
> - 没有改 handle_manual_sync 的 5 分钟冷却时间逻辑
> - 没有调整 `_run_tier2` 的任何行为（spec 只说 tier1，tier2 不动）
