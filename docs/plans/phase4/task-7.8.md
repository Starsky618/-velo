# 任务 7.8：mark-all-read + unread_count 接口

> 修 Important I2：进通知中心页后标已读——给前端"一键标全读"接口。
> 修 Important I3：mark-all-read 必须幂等（重复调不重复计数）。

---

## 🎯 目标（一句话）

给通知系统补两个口子：
1. 新接口 `POST /api/notifications/mark-all-read` — 把当前用户所有未读标为已读，返回这次标了几条
2. 扩展 `GET /api/notifications` — 加可选参数 `unread_only` + 响应永远带 `unread_count`（给首页红点用）

---

## ⛓ 前置依赖

- **task-7.1**（`notifications.is_read` 字段 + 部分索引 `idx_notifications_user_unread` 就位）

## 📥 输入契约

**现有代码事实核对**：

| 项目 | 位置 | 现状 |
|------|------|------|
| notification service | `app/notification/service.py:174-229` | `get_notifications(db, user_id, page, page_size)` 无 unread_only |
| notification router | `app/notification/router.py:22-36` | `GET ""` 映射到 service.get_notifications |
| Notification 模型 | `app/notification/models.py` | task-7.1 已加 `is_read` 字段 |

## 📤 输出契约

| 产出 | 签名 | 说明 |
|------|------|------|
| `service.mark_all_read` | `(db, user_id) -> int` | 返回本次标读的数量 |
| `service.get_notifications` | 加 `unread_only: bool = False` 参数 | 默认 False 向后兼容；响应加 `unread_count` |
| `POST /api/notifications/mark-all-read` | 无参数 | 返 `{"marked": N}` |
| `GET /api/notifications?unread_only=...` | 可选 bool | 响应体多一个 `unread_count` 字段 |

---

## 🛠 完整代码

### 1. `app/notification/service.py` 新增 `mark_all_read`

在文件**末尾**（`cleanup_expired` 之后）追加：

```python
def mark_all_read(db: Session, user_id: int) -> int:
    """
    把当前用户所有未读通知标为已读。

    幂等性：
        SQL 层自带 `WHERE is_read == False` 过滤——已读的不会被重复计数，
        重复调用此函数返 0。无需额外去重逻辑。

    为什么用 == False 而不用 !is_read：
        Python truthiness 陷阱——SQLAlchemy 表达式里用 `not is_read` 会被
        当成 Python bool，生成的 SQL 不对。必须用显式 `== False`。

    索引支撑：
        task-7.1 建立的部分索引 idx_notifications_user_unread（user_id, expires_at）
        WHERE is_read=FALSE，此查询 + 更新都能命中。

    Args:
        db: SQLAlchemy Session
        user_id: 当前用户 ID

    Returns:
        本次标读的数量（0 表示本来就全读了）
    """
    count = (
        db.query(Notification)
        .filter(
            Notification.user_id == user_id,
            Notification.is_read == False,  # noqa: E712 — SQLAlchemy 需要显式 == False
        )
        .update(
            {Notification.is_read: True},
            synchronize_session=False,
        )
    )
    db.commit()
    logger.info("mark_all_read user_id=%d 标读 %d 条", user_id, count)
    return count
```

### 2. `app/notification/service.py` 改造 `get_notifications`

**替换整个函数**（`:174-229`）为：

```python
def get_notifications(
    db: Session,
    user_id: int,
    page: int = 1,
    page_size: int = 20,
    unread_only: bool = False,
) -> dict:
    """
    查询用户的通知列表，按时间倒序分页。

    v4 扩展：
    1. 加 unread_only 参数（默认 False，向后兼容）
    2. 响应永远带 unread_count 字段——首页红点和通知页共用这个数

    为什么 unread_count 独立查询（不从 items 里数）：
        items 被分页限制在 page_size 条内，数出来的未读数 ≤ 实际未读数。
        独立用部分索引走 COUNT 查询，走 idx_notifications_user_unread，极快。

    Args:
        db: SQLAlchemy Session
        user_id: 当前用户 ID
        page: 页码（从 1 起）
        page_size: 每页条数
        unread_only: True 只查未读；False 查所有（默认）

    Returns:
        {
          "items": [...],
          "total": 总条数（按 unread_only 过滤后）,
          "unread_count": 未读总数（不受 unread_only 影响）,
          "page": page,
          "page_size": page_size,
        }
    """
    now = datetime.utcnow()

    # 基础查询：JOIN 赛段名和对手昵称
    query = (
        db.query(
            Notification,
            Segment.name.label("segment_name"),
            User.nickname.label("rival_nickname"),
        )
        # ⚠ 外连接 segment：task-7.1 把外键改成 SET NULL 后，segment_id 可能为 NULL
        # 用 outerjoin 而非 join，否则 NULL 的通知会被 inner join 过滤掉
        .outerjoin(Segment, Segment.id == Notification.segment_id)
        .outerjoin(User, User.id == Notification.rival_user_id)
        .filter(
            Notification.user_id == user_id,
            Notification.expires_at > now,
        )
    )

    if unread_only:
        query = query.filter(Notification.is_read == False)  # noqa: E712

    query = query.order_by(Notification.created_at.desc())

    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()

    items = []
    for notif, segment_name, rival_nickname in rows:
        items.append({
            "id": notif.id,
            "event_type": notif.event_type,
            "segment_id": notif.segment_id,
            "segment_name": segment_name,  # 可能为 None（外键 SET NULL 后）
            "activity_id": notif.activity_id,
            "elapsed_time": notif.elapsed_time,
            "rank": notif.rank,
            "rival_user_id": notif.rival_user_id,
            "rival_nickname": rival_nickname,
            "is_read": notif.is_read,
            "created_at": notif.created_at.isoformat() + "Z" if notif.created_at else None,
        })

    # ---- unread_count 独立查询 ----
    # 无论 unread_only 为何值都返回（首页红点调 unread_only=True&page_size=1 也能拿到）
    # 走部分索引 idx_notifications_user_unread，单次 COUNT 极快
    unread_count = (
        db.query(sa.func.count(Notification.id))
        .filter(
            Notification.user_id == user_id,
            Notification.is_read == False,  # noqa: E712
            Notification.expires_at > now,
        )
        .scalar()
    )

    return {
        "items": items,
        "total": total,
        "unread_count": unread_count,
        "page": page,
        "page_size": page_size,
    }
```

> **⚠ inner → outer JOIN**：原代码用 `.join(Segment, ...)` 是 inner join。task-7.1 把 `notifications.segment_id` 改成可空 + SET NULL 后，**被删赛段的通知** segment_id 会变 NULL，inner join 会把它们过滤掉——导致用户看不到"该记录已失效"的通知。本任务改成 `outerjoin`——segment_name 可能为 None，前端按 spec §3.1 做兜底显示"该记录已失效"。

### 3. `app/notification/router.py` 加路由 + 参数

**替换现有 router.py 全文**：

```python
# app/notification/router.py
"""
通知模块 API 路由——"广播室的服务窗口"。

三个窗口：
1. GET  /api/notifications — 通知列表
2. POST /api/notifications/mark-all-read — 一键标全读
3. GET  /api/user/honors — 荣誉表

操作注意事项：
- 两个路由前缀不同（/api/notifications 和 /api/user），所以需要两个 router 实例
- 和 segment 模块的 /api/user/efforts 是同一个挂载模式
- get_current_user 返回 int（user_id），不是 User 对象
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.notification import service

# 通知列表路由
notification_router = APIRouter(prefix="/api/notifications", tags=["notification"])

# 荣誉表路由（挂在 /api/user 下）
honor_router = APIRouter(prefix="/api/user", tags=["notification"])


@notification_router.get("")
def get_notifications(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    unread_only: bool = Query(False),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user),
):
    """
    查询当前用户的通知列表，按时间倒序分页。

    参数：
        unread_only: True 只查未读；False 查所有（默认，向后兼容）
    
    响应永远带 unread_count 字段，供首页红点使用。
    """
    return service.get_notifications(db, user_id, page, page_size, unread_only=unread_only)


@notification_router.post("/mark-all-read")
def mark_all_read(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user),
):
    """
    把当前用户所有未读通知标为已读。

    幂等：重复调用返回 0。
    前端使用场景：用户进通知中心页时立即调用，实现"进页即标读"。
    """
    marked = service.mark_all_read(db, user_id)
    return {"marked": marked}


@honor_router.get("/honors")
def get_user_honors(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user),
):
    """查询当前用户的 KOM 和前十名荣誉表。"""
    return service.get_user_honors(db, user_id)
```

---

## 🧪 测试

**文件**：`tests/notification/test_mark_all_read.py`（新建）

```python
from datetime import datetime, timedelta

from app.notification import service
from app.notification.models import Notification


def _make_notif(db, user_id, is_read=False, event_type="pr", segment_id=1, effort_id=1):
    """测试辅助：创建一条通知。"""
    n = Notification(
        user_id=user_id,
        event_type=event_type,
        segment_id=segment_id,
        activity_id=1,
        effort_id=effort_id,
        elapsed_time=100,
        rank=1,
        is_read=is_read,
        expires_at=datetime.utcnow() + timedelta(days=30),
    )
    db.add(n)
    db.commit()
    return n


def test_mark_all_read_marks_unread(db, user_factory):
    user = user_factory()
    _make_notif(db, user.id, is_read=False, effort_id=101)
    _make_notif(db, user.id, is_read=False, effort_id=102)
    _make_notif(db, user.id, is_read=True, effort_id=103)  # 已读

    marked = service.mark_all_read(db, user.id)
    assert marked == 2

    # 全部应为 is_read=True
    all_read = db.query(Notification).filter_by(user_id=user.id).all()
    assert all(n.is_read is True for n in all_read)


def test_mark_all_read_idempotent(db, user_factory):
    """重复调用返 0（已全读）。"""
    user = user_factory()
    _make_notif(db, user.id, is_read=False, effort_id=201)

    assert service.mark_all_read(db, user.id) == 1
    assert service.mark_all_read(db, user.id) == 0
    assert service.mark_all_read(db, user.id) == 0


def test_mark_all_read_isolated_per_user(db, user_factory):
    """不跨用户——只标当前 user 的。"""
    u1 = user_factory()
    u2 = user_factory()
    _make_notif(db, u1.id, is_read=False, effort_id=301)
    _make_notif(db, u2.id, is_read=False, effort_id=302)

    assert service.mark_all_read(db, u1.id) == 1

    u2_notif = db.query(Notification).filter_by(user_id=u2.id).first()
    assert u2_notif.is_read is False  # u2 未被波及


def test_get_notifications_includes_unread_count(db, user_factory):
    user = user_factory()
    _make_notif(db, user.id, is_read=False, effort_id=401)
    _make_notif(db, user.id, is_read=False, effort_id=402)
    _make_notif(db, user.id, is_read=True, effort_id=403)

    res = service.get_notifications(db, user.id, page=1, page_size=20)
    assert res["unread_count"] == 2
    assert res["total"] == 3  # 默认返所有
    assert len(res["items"]) == 3


def test_get_notifications_unread_only_filters(db, user_factory):
    user = user_factory()
    _make_notif(db, user.id, is_read=False, effort_id=501)
    _make_notif(db, user.id, is_read=True, effort_id=502)

    res = service.get_notifications(db, user.id, page=1, page_size=20, unread_only=True)
    assert res["total"] == 1  # 只数未读
    assert len(res["items"]) == 1
    assert res["items"][0]["is_read"] is False
    assert res["unread_count"] == 1


def test_unread_count_does_not_change_with_unread_only(db, user_factory):
    """unread_count 不受 unread_only 影响。"""
    user = user_factory()
    _make_notif(db, user.id, is_read=False, effort_id=601)
    _make_notif(db, user.id, is_read=True, effort_id=602)

    res_all = service.get_notifications(db, user.id, unread_only=False)
    res_filtered = service.get_notifications(db, user.id, unread_only=True)

    # 两次的 unread_count 应一致
    assert res_all["unread_count"] == 1
    assert res_filtered["unread_count"] == 1


def test_expired_notifications_excluded_from_unread_count(db, user_factory):
    """过期通知不计入 unread_count。"""
    user = user_factory()
    expired = Notification(
        user_id=user.id, event_type="pr",
        segment_id=1, activity_id=1, effort_id=701,
        elapsed_time=100, rank=1, is_read=False,
        expires_at=datetime.utcnow() - timedelta(days=1),  # 过期
    )
    db.add(expired)
    db.commit()

    res = service.get_notifications(db, user.id)
    assert res["unread_count"] == 0


def test_notification_with_null_segment_still_returned(db, user_factory):
    """外键 SET NULL 后 segment_id=NULL 的通知仍返回（outerjoin）。"""
    user = user_factory()
    n = Notification(
        user_id=user.id,
        event_type="pr",
        segment_id=None,  # 赛段已被删
        activity_id=1,
        effort_id=801,
        elapsed_time=100,
        rank=1,
        is_read=False,
        expires_at=datetime.utcnow() + timedelta(days=30),
    )
    db.add(n)
    db.commit()

    res = service.get_notifications(db, user.id)
    assert len(res["items"]) == 1
    assert res["items"][0]["segment_id"] is None
    assert res["items"][0]["segment_name"] is None  # JOIN 不到
```

**接口手工验证**：

```bash
# 1. 查询通知列表（带 unread_count）
curl -H "Authorization: Bearer TOKEN" \
  "https://DOMAIN/api/notifications?page=1&page_size=20"

# 2. 只查未读
curl -H "Authorization: Bearer TOKEN" \
  "https://DOMAIN/api/notifications?unread_only=true&page_size=1"
# 响应的 unread_count 就是首页红点数字

# 3. 一键标已读
curl -X POST -H "Authorization: Bearer TOKEN" \
  "https://DOMAIN/api/notifications/mark-all-read"
# 应返 {"marked": N}

# 4. 重复标读（验证幂等）
curl -X POST -H "Authorization: Bearer TOKEN" \
  "https://DOMAIN/api/notifications/mark-all-read"
# 第二次应返 {"marked": 0}
```

---

## 📦 Commit 指令

```bash
git add app/notification/service.py \
        app/notification/router.py \
        tests/notification/test_mark_all_read.py

git commit -m "$(cat <<'EOF'
feat(notification): 任务 7.8 mark-all-read + unread_count（修 I2 I3）

新增 service.mark_all_read(db, user_id) -> int：
- SQL WHERE is_read == False 天然幂等
- 走 task-7.1 建立的部分索引 idx_notifications_user_unread

扩展 service.get_notifications：
- 新增 unread_only 可选参数（默认 False，向后兼容）
- 响应永远带 unread_count 字段（首页红点 + 通知页共用）
- Segment JOIN 改 inner → outer（配合 task-7.1 外键 SET NULL）

新增 POST /api/notifications/mark-all-read 路由。
GET /api/notifications 加 unread_only 查询参数。

响应结构：{items, total, unread_count, page, page_size, items[].is_read}

测试：8 个用例覆盖幂等、用户隔离、过期过滤、NULL segment、unread_only 过滤。
EOF
)"
```

---

## ✅ 自检三问

**1. 10 分钟挑战**：讲清这两个接口怎么用？

> 想象广播室的工作台——
> - `POST /mark-all-read`：用户一进通知中心，前端 "啪" 一下调这个接口，广播室把所有未读便签盖上"已看"章，返回"这次盖了 X 个章"
> - `GET /notifications?unread_only=true&page_size=1`：首页红点只想知道"还剩几个没看"，调这个接口但其实不关心列表，只读响应里的 `unread_count`——这就是首页红点显示的数字

**2. 崩溃场景**：mark_all_read 中途崩了怎么办？

> `.update(...)` 是单条 SQL，PostgreSQL 保证原子——要么全标，要么都不标。崩溃时事务回滚，状态回到崩前。用户刷新重试即可，不会出现"标了一半"的半态。

**3. 边界纪律**：有没有做 spec 没要求的"顺手优化"？

> 没有。严格 spec §2.1 + §2.2 范围：
> - 没有实现"按条标读"（本期只做全部标读）
> - 没有加 event_type 过滤参数（§9.4 未来 100+ 用户规模再做）
> - 没有改 get_user_honors（那是另一个接口）
> - 没有给 mark_all_read 加 Redis 限速（标读属于极低频操作，无需限速）
