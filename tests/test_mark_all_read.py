# tests/test_mark_all_read.py
"""
task-7.8：mark-all-read 接口 + unread_count 扩展测试。

测试覆盖 8 个用例：
1. 标读基本功能——把未读标成已读，已读不重复计数
2. 幂等性——重复调用返 0，不出错
3. 用户隔离——只标当前用户的，不影响他人
4. unread_count 永远返回——get_notifications 响应里带
5. unread_only 过滤——True 只返未读
6. unread_count 不随 unread_only 改变——永远是未读总数
7. 过期通知不计入 unread_count
8. NULL segment 通知也返回（配合 task-7.1 外键 SET NULL）

注意事项：
- effort_id 在每个测试里要唯一，否则 UNIQUE(effort_id, event_type) 会冲突
- user_factory 在 conftest 里不存在，每个测试直接 new User
"""
from datetime import datetime, timedelta

import pytest

from app.notification import service
from app.notification.models import Notification
from app.user.models import User


def _new_user(db, suffix):
    """创建一个测试用户并返回——避免依赖不存在的 user_factory fixture。"""
    user = User(openid=f"test_mark_read_{suffix}", nickname=f"用户{suffix}")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_notif(db, user_id, is_read=False, event_type="pr",
                segment_id=1, effort_id=1, activity_id=1):
    """测试辅助：创建一条通知。effort_id 必须在测试内唯一。"""
    n = Notification(
        user_id=user_id,
        event_type=event_type,
        segment_id=segment_id,
        activity_id=activity_id,
        effort_id=effort_id,
        elapsed_time=100,
        rank=1,
        is_read=is_read,
        expires_at=datetime.utcnow() + timedelta(days=30),
    )
    db.add(n)
    db.commit()
    return n


# ==================== mark_all_read 核心行为 ====================

def test_mark_all_read_marks_unread(db):
    """把所有未读标为已读，已读的保持不变且不重复计数。"""
    user = _new_user(db, "a")
    _make_notif(db, user.id, is_read=False, effort_id=101)
    _make_notif(db, user.id, is_read=False, effort_id=102)
    _make_notif(db, user.id, is_read=True, effort_id=103)  # 已读，不该被计入

    marked = service.mark_all_read(db, user.id)
    assert marked == 2

    # 全部通知现在应该都是 is_read=True
    all_notifs = db.query(Notification).filter_by(user_id=user.id).all()
    assert all(n.is_read is True for n in all_notifs)


def test_mark_all_read_idempotent(db):
    """重复调用：第二次起返回 0（幂等）。"""
    user = _new_user(db, "b")
    _make_notif(db, user.id, is_read=False, effort_id=201)

    assert service.mark_all_read(db, user.id) == 1
    assert service.mark_all_read(db, user.id) == 0
    assert service.mark_all_read(db, user.id) == 0


def test_mark_all_read_isolated_per_user(db):
    """只标当前用户——不跨用户。"""
    u1 = _new_user(db, "c1")
    u2 = _new_user(db, "c2")
    _make_notif(db, u1.id, is_read=False, effort_id=301)
    _make_notif(db, u2.id, is_read=False, effort_id=302)

    assert service.mark_all_read(db, u1.id) == 1

    # u2 的通知应保持未读
    u2_notif = db.query(Notification).filter_by(user_id=u2.id).first()
    assert u2_notif.is_read is False


# ==================== get_notifications 扩展 ====================

def test_get_notifications_includes_unread_count(db):
    """响应永远带 unread_count 字段（默认模式下也要有）。"""
    user = _new_user(db, "d")
    _make_notif(db, user.id, is_read=False, effort_id=401)
    _make_notif(db, user.id, is_read=False, effort_id=402)
    _make_notif(db, user.id, is_read=True, effort_id=403)

    res = service.get_notifications(db, user.id, page=1, page_size=20)
    assert res["unread_count"] == 2
    assert res["total"] == 3  # 默认返所有
    assert len(res["items"]) == 3
    # items 每条带 is_read 字段
    assert all("is_read" in item for item in res["items"])


def test_get_notifications_unread_only_filters(db):
    """unread_only=True 只返未读记录。"""
    user = _new_user(db, "e")
    _make_notif(db, user.id, is_read=False, effort_id=501)
    _make_notif(db, user.id, is_read=True, effort_id=502)

    res = service.get_notifications(db, user.id, page=1, page_size=20, unread_only=True)
    assert res["total"] == 1  # 只数未读
    assert len(res["items"]) == 1
    assert res["items"][0]["is_read"] is False
    assert res["unread_count"] == 1


def test_unread_count_does_not_change_with_unread_only(db):
    """unread_count 是独立查询，不受 unread_only 过滤影响。"""
    user = _new_user(db, "f")
    _make_notif(db, user.id, is_read=False, effort_id=601)
    _make_notif(db, user.id, is_read=True, effort_id=602)

    res_all = service.get_notifications(db, user.id, unread_only=False)
    res_filtered = service.get_notifications(db, user.id, unread_only=True)

    # 两次 unread_count 应一致（都是 1）——这是首页红点的数字基础
    assert res_all["unread_count"] == 1
    assert res_filtered["unread_count"] == 1


def test_expired_notifications_excluded_from_unread_count(db):
    """过期通知不计入 unread_count（即使 is_read=False）。"""
    user = _new_user(db, "g")
    expired = Notification(
        user_id=user.id,
        event_type="pr",
        segment_id=1,
        activity_id=1,
        effort_id=701,
        elapsed_time=100,
        rank=1,
        is_read=False,
        expires_at=datetime.utcnow() - timedelta(days=1),  # 已过期
    )
    db.add(expired)
    db.commit()

    res = service.get_notifications(db, user.id)
    assert res["unread_count"] == 0
    assert res["total"] == 0  # 过期通知也不在 total 里


def test_notification_with_null_segment_still_returned(db):
    """
    外键 SET NULL 后 segment_id=NULL 的通知仍要返回（outerjoin 保留）。

    task-7.1 把 notifications.segment_id 外键改成 ON DELETE SET NULL 后，
    赛段被删的通知 segment_id 会变 NULL。inner join 会过滤掉，outerjoin 能保留。
    """
    user = _new_user(db, "h")
    n = Notification(
        user_id=user.id,
        event_type="pr",
        segment_id=None,  # 赛段已被删，外键 SET NULL
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
    assert res["items"][0]["segment_name"] is None  # outerjoin 不到赛段
