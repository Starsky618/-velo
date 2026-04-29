# tests/test_notification.py
"""
通知模块测试。

测试分三层：
1. 纯函数测试（detector.classify）—— 不需要数据库
2. Service 测试（detect_events、get_notifications 等）—— 需要数据库
3. API 测试（router）—— 需要 TestClient
"""
from app.notification.detector import classify, EventResult, KomLostResult


# ===================== 纯函数测试 =====================

def test_classify_first_effort_is_pr_and_kom():
    """赛段第一条成绩：既是 PR 又是 KOM，无被夺者"""
    event, lost = classify(
        elapsed_time=300,
        rank=1,
        is_pr=True,
        previous_kom_user_id=None,
        current_user_id=1,
    )
    assert event is not None
    assert event.event_type == "kom"
    assert event.rank == 1
    assert lost is None


def test_classify_new_kom_dethrones_previous():
    """夺走别人的 KOM：生成 KOM + KOM 被夺"""
    event, lost = classify(
        elapsed_time=280,
        rank=1,
        is_pr=True,
        previous_kom_user_id=5,
        current_user_id=1,
    )
    assert event is not None
    assert event.event_type == "kom"
    assert event.rank == 1
    assert lost is not None
    assert lost.previous_holder_user_id == 5
    assert lost.new_rank == 2


def test_classify_self_dethrone_no_lost():
    """自己打破自己的 KOM：只生成 KOM，不生成被夺"""
    event, lost = classify(
        elapsed_time=250,
        rank=1,
        is_pr=True,
        previous_kom_user_id=1,
        current_user_id=1,
    )
    assert event is not None
    assert event.event_type == "kom"
    assert lost is None


def test_classify_pr_top10():
    """破 PR 且进前 10：通知带排名"""
    event, lost = classify(
        elapsed_time=320,
        rank=5,
        is_pr=True,
        previous_kom_user_id=None,
        current_user_id=2,
    )
    assert event is not None
    assert event.event_type == "pr"
    assert event.rank == 5
    assert lost is None


def test_classify_pr_outside_top10():
    """破 PR 但排名 > 10：通知不带排名"""
    event, lost = classify(
        elapsed_time=500,
        rank=15,
        is_pr=True,
        previous_kom_user_id=None,
        current_user_id=3,
    )
    assert event is not None
    assert event.event_type == "pr"
    assert event.rank is None
    assert lost is None


def test_classify_not_pr():
    """不是 PR：不生成通知"""
    event, lost = classify(
        elapsed_time=600,
        rank=20,
        is_pr=False,
        previous_kom_user_id=None,
        current_user_id=4,
    )
    assert event is None
    assert lost is None


def test_classify_tied_first_but_not_pr():
    """并列情况下 rank=1 但不是 PR（理论上不会发生，但防御）"""
    event, lost = classify(
        elapsed_time=300,
        rank=1,
        is_pr=False,
        previous_kom_user_id=None,
        current_user_id=5,
    )
    # rank==1 但不是 PR 意味着这个用户之前有更好的成绩
    # 这种情况不应该生成通知
    assert event is None
    assert lost is None


# ===================== Service 层测试 =====================

from datetime import datetime, timedelta, timezone


def _insert_activity(db, user_id, data_source="gpx", started_at=None):
    """测试辅助：插入活动记录"""
    if started_at is None:
        started_at = datetime.now(timezone.utc)
    from tests.conftest import _activities_table
    result = db.execute(
        _activities_table.insert().values(
            user_id=user_id,
            status="completed",
            data_source=data_source,
            started_at=started_at,
        )
    )
    db.commit()
    return result.inserted_primary_key[0]


def _insert_segment(db):
    """测试辅助：插入赛段记录"""
    from tests.conftest import _segments_table
    result = db.execute(
        _segments_table.insert().values(
            name="测试赛段",
            distance=5000.0,
            start_lat=37.87, start_lon=112.55,
            end_lat=37.88, end_lon=112.56,
            reference_line="LINESTRING(112.55 37.87, 112.56 37.88)",
        )
    )
    db.commit()
    return result.inserted_primary_key[0]


def _insert_effort(db, segment_id, activity_id, user_id, elapsed_time, created_at=None):
    """测试辅助：插入赛段成绩"""
    from tests.conftest import _segment_efforts_table
    if created_at is None:
        created_at = datetime.now(timezone.utc)
    result = db.execute(
        _segment_efforts_table.insert().values(
            segment_id=segment_id,
            activity_id=activity_id,
            user_id=user_id,
            elapsed_time=elapsed_time,
            start_index=0,
            end_index=100,
            created_at=created_at,
        )
    )
    db.commit()
    return result.inserted_primary_key[0]


def test_detect_events_pr(db, test_user):
    """上传骑行后破 PR → 生成 KOM 通知（自己打破自己的记录）"""
    seg_id = _insert_segment(db)
    act1_id = _insert_activity(db, test_user.id)
    act2_id = _insert_activity(db, test_user.id)

    # 第一条成绩：300 秒（这会是 KOM）
    _insert_effort(db, seg_id, act1_id, test_user.id, 300)

    # 第二条更好的成绩：280 秒（这会是新 KOM + PR）
    eff2_id = _insert_effort(db, seg_id, act2_id, test_user.id, 280)

    # 手动调用 detect_events
    from app.notification.service import detect_events
    from app.segment.models import SegmentEffort
    effort = db.get(SegmentEffort, eff2_id)
    detect_events(db, effort)

    # 验证：应该生成 KOM 通知（因为自己就是 KOM，自己打破自己的）
    from app.notification.models import Notification
    notifs = db.query(Notification).filter_by(user_id=test_user.id).all()
    assert len(notifs) == 1
    assert notifs[0].event_type == "kom"
    assert notifs[0].elapsed_time == 280
    assert notifs[0].rank == 1


def test_detect_events_idempotent(db, test_user):
    """重复调用 detect_events → 不产生重复通知"""
    seg_id = _insert_segment(db)
    act_id = _insert_activity(db, test_user.id)
    eff_id = _insert_effort(db, seg_id, act_id, test_user.id, 300)

    from app.notification.service import detect_events
    from app.segment.models import SegmentEffort
    from app.notification.models import Notification
    effort = db.get(SegmentEffort, eff_id)

    detect_events(db, effort)
    detect_events(db, effort)  # 重复调用

    notifs = db.query(Notification).filter_by(user_id=test_user.id).all()
    assert len(notifs) == 1  # 只有一条，不重复


def test_detect_events_strava_history_skipped(db, test_user):
    """Strava 历史导入（超过 7 天）→ 不生成通知"""
    seg_id = _insert_segment(db)
    old_date = datetime.now(timezone.utc) - timedelta(days=30)
    act_id = _insert_activity(db, test_user.id, data_source="strava", started_at=old_date)
    eff_id = _insert_effort(db, seg_id, act_id, test_user.id, 300)

    from app.notification.service import detect_events
    from app.segment.models import SegmentEffort
    from app.notification.models import Notification
    effort = db.get(SegmentEffort, eff_id)

    detect_events(db, effort)

    notifs = db.query(Notification).filter_by(user_id=test_user.id).all()
    assert len(notifs) == 0  # 历史导入不触发通知


def test_detect_events_gpx_old_activity_triggers(db, test_user):
    """手动上传的旧 GPX → 即使超过 7 天也生成通知"""
    seg_id = _insert_segment(db)
    old_date = datetime.now(timezone.utc) - timedelta(days=30)
    act_id = _insert_activity(db, test_user.id, data_source="gpx", started_at=old_date)
    eff_id = _insert_effort(db, seg_id, act_id, test_user.id, 300)

    from app.notification.service import detect_events
    from app.segment.models import SegmentEffort
    from app.notification.models import Notification
    effort = db.get(SegmentEffort, eff_id)

    detect_events(db, effort)

    notifs = db.query(Notification).filter_by(user_id=test_user.id).all()
    assert len(notifs) == 1  # 手动上传永远触发


# ===================== API 测试 =====================

def test_api_notifications_empty(client, auth_header):
    """通知列表为空时返回空数组"""
    resp = client.get("/api/notifications", headers=auth_header)
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["total"] == 0


def test_api_notifications_with_data(client, db, test_user, auth_header):
    """通知列表包含数据时正确返回"""
    seg_id = _insert_segment(db)
    act_id = _insert_activity(db, test_user.id)
    eff_id = _insert_effort(db, seg_id, act_id, test_user.id, 300)

    from app.notification.service import detect_events
    from app.segment.models import SegmentEffort
    effort = db.get(SegmentEffort, eff_id)
    detect_events(db, effort)

    resp = client.get("/api/notifications", headers=auth_header)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    item = data["items"][0]
    assert item["event_type"] in ("pr", "kom")
    assert item["segment_name"] == "测试赛段"
    assert isinstance(item["elapsed_time"], int)


def test_api_honors_empty(client, auth_header):
    """荣誉表为空时返回空数组"""
    resp = client.get("/api/user/honors", headers=auth_header)
    assert resp.status_code == 200
    data = resp.json()
    assert data["koms"] == []
    assert data["top10s"] == []
    assert data["kom_count"] == 0


# ===================== 清理 + 集成测试 =====================

def test_cleanup_expired(db, test_user):
    """过期通知被正确删除"""
    seg_id = _insert_segment(db)
    act_id = _insert_activity(db, test_user.id)
    eff_id = _insert_effort(db, seg_id, act_id, test_user.id, 300)

    from app.notification.service import detect_events, cleanup_expired
    from app.segment.models import SegmentEffort
    from app.notification.models import Notification

    effort = db.get(SegmentEffort, eff_id)
    detect_events(db, effort)

    # 确认生成了通知
    assert db.query(Notification).count() >= 1

    # 手动把 expires_at 改到过去
    db.query(Notification).update(
        {"expires_at": datetime.now(timezone.utc) - timedelta(days=1)},
        synchronize_session=False,
    )
    db.commit()

    # 清理
    count = cleanup_expired(db)
    assert count >= 1
    assert db.query(Notification).count() == 0


def test_full_flow_pr_and_kom(db, test_user):
    """完整流程：两个用户，第二个拿 KOM，第一个收到被夺通知"""
    seg_id = _insert_segment(db)

    # 用户 1 先骑，成绩 300 秒（KOM）
    act1_id = _insert_activity(db, test_user.id)
    eff1_id = _insert_effort(db, seg_id, act1_id, test_user.id, 300)

    from app.notification.service import detect_events
    from app.segment.models import SegmentEffort
    from app.notification.models import Notification

    effort1 = db.get(SegmentEffort, eff1_id)
    detect_events(db, effort1)

    # 用户 1 应收到 KOM 通知
    notifs1 = db.query(Notification).filter_by(user_id=test_user.id).all()
    assert len(notifs1) == 1
    assert notifs1[0].event_type == "kom"

    # 创建用户 2
    from app.user.models import User
    user2 = User(openid="test_user_2", nickname="对手")
    db.add(user2)
    db.commit()

    # 用户 2 骑更快，成绩 250 秒（夺 KOM）
    act2_id = _insert_activity(db, user2.id)
    eff2_id = _insert_effort(db, seg_id, act2_id, user2.id, 250)

    effort2 = db.get(SegmentEffort, eff2_id)
    detect_events(db, effort2)

    # 用户 2 应收到 KOM 通知
    user2_notifs = db.query(Notification).filter_by(user_id=user2.id).all()
    assert any(n.event_type == "kom" for n in user2_notifs)

    # 用户 1 应收到 KOM 被夺通知
    user1_notifs = db.query(Notification).filter_by(
        user_id=test_user.id, event_type="kom_lost"
    ).all()
    assert len(user1_notifs) == 1
    assert user1_notifs[0].rank == 2
    assert user1_notifs[0].rival_user_id == user2.id
