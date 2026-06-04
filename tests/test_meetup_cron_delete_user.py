"""约骑模块 Task 7：cron 完成和删账号 hook 测试。"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.meetup import service
from app.meetup.models import Meetup, MeetupMedia, MeetupParticipant
from app.segment.models import Segment
from app.user.models import User


ROOT = Path(__file__).resolve().parents[1]


def _segment(db):
    segment = Segment(
        name="cron路线",
        distance=10000.0,
        elevation_gain=100.0,
        start_lat=37.8,
        start_lon=112.5,
        end_lat=37.9,
        end_lon=112.6,
        reference_line="SRID=4326;LINESTRING(112.5 37.8, 112.6 37.9)",
        city="taiyuan",
    )
    db.add(segment)
    db.commit()
    db.refresh(segment)
    return segment


def _meetup(db, user_id, status="OPEN", start_delta=-3, end_delta=-1):
    segment = _segment(db)
    start = datetime.now(timezone.utc) + timedelta(hours=start_delta)
    meetup = service.create_meetup(
        db,
        user_id,
        segment.id,
        None,
        start,
        datetime.now(timezone.utc) + timedelta(hours=end_delta),
        "集合点",
        "cruise",
        4,
        None,
    )
    if status == "DRAFT":
        return meetup
    # 直接置 OPEN + 补 creator 占位（等价 publish_meetup 的效果），不走 publish_meetup：
    # 它现在有出发前 30min 截止线，会挡住"造过去/近期 OPEN 约骑"的 cron 测试 setup。
    meetup.status = "OPEN"
    db.add(MeetupParticipant(meetup_id=meetup.id, user_id=user_id, is_creator=True))
    if status == "CANCELLED":
        meetup.status = "CANCELLED"
        meetup.cancelled_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(meetup)
    return meetup


def test_cron_completes_open_meetups_after_estimated_end(db, test_user):
    from app.meetup import cron

    past = _meetup(db, test_user.id, status="OPEN", end_delta=-1)
    future = _meetup(db, test_user.id, status="OPEN", start_delta=1, end_delta=3)
    cancelled = _meetup(db, test_user.id, status="CANCELLED", start_delta=-3, end_delta=-1)

    changed = cron.complete_due_meetups(db)

    db.refresh(past)
    db.refresh(future)
    db.refresh(cancelled)
    assert changed == 1
    assert past.status == "COMPLETED"
    assert past.completed_at is not None
    assert future.status == "OPEN"
    assert cancelled.status == "CANCELLED"


def test_scheduler_has_independent_meetup_tick():
    source = (ROOT / "scheduler.py").read_text(encoding="utf-8")

    assert "from app.meetup.cron import run_meetup_complete_tick" in source
    assert "_meetup_tick_counter" in source
    assert "run_import_tick()" in source
    assert "run_meetup_complete_tick()" in source
    assert source.count("logger.exception") >= 2


def test_delete_user_cancels_open_deletes_draft_and_storage(db, test_user, monkeypatch):
    from app.user.service import delete_user

    user_id = test_user.id
    open_meetup = _meetup(db, user_id, status="OPEN", start_delta=5, end_delta=8)
    draft_meetup = _meetup(db, user_id, status="DRAFT", start_delta=5, end_delta=8)
    open_meetup_id = open_meetup.id
    draft_meetup_id = draft_meetup.id
    db.add(MeetupMedia(meetup_id=draft_meetup_id, uploader_id=user_id, type="image", file_id="202606/draft.jpg", seq=0))
    db.commit()
    deleted_files = []
    monkeypatch.setattr("app.meetup.service._storage.delete", lambda file_id: deleted_files.append(file_id))

    delete_user(db, user_id)

    cancelled = db.query(Meetup).filter(Meetup.id == open_meetup_id).first()
    draft = db.query(Meetup).filter(Meetup.id == draft_meetup_id).first()
    user = db.query(User).filter(User.id == user_id).first()
    media_count = db.query(MeetupMedia).filter(MeetupMedia.meetup_id == draft_meetup_id).count()
    assert cancelled.status == "CANCELLED"
    assert cancelled.cancelled_at is not None
    assert draft is None
    assert user is None
    assert media_count == 0
    assert deleted_files == ["202606/draft.jpg"]


def test_delete_user_purges_all_personal_data(db, test_user, monkeypatch):
    """彻底注销（Tim 2026-06-01 拍）：删光骑行/赛段成绩/突破/Strava + 收集 GPX 文件清理 + 删 user。

    这些子表的 user_id 是 RESTRICT（无级联），旧版 delete_user 只删约骑、直接 db.delete(user)
    在生产 PG 上会被外键挡住抛 500。本测试锁死"全部个人数据被显式删干净"。"""
    from datetime import datetime, timedelta, timezone

    from app.activity.models import Activity, BreakthroughEvent
    from app.segment.models import SegmentEffort
    from app.strava.models import StravaImport
    from app.user.models import User
    from app.user.service import delete_user

    user_id = test_user.id
    seg = _segment(db)

    act = Activity(user_id=user_id, status="completed", file_url="202606/ride.gpx")
    db.add(act)
    db.flush()
    act_id = act.id

    # 三类"挡路"子行（user_id RESTRICT）：赛段成绩 / 突破事件 / Strava 导入台账
    db.add(SegmentEffort(segment_id=seg.id, activity_id=act_id, user_id=user_id,
                         elapsed_time=600, start_index=0, end_index=10))
    db.add(BreakthroughEvent(user_id=user_id, activity_id=act_id, old_ftp=200, suggested_ftp=220,
                             expires_at=datetime.now(timezone.utc) + timedelta(days=7)))
    db.add(StravaImport(user_id=user_id, strava_athlete_id=123456))

    # 脏数据兜底（Codex 异源审 I1）：另一个用户的突破事件却挂在被注销用户的活动上。
    # breakthrough_events.activity_id 是 RESTRICT，若只按 user_id 删会漏掉它，删活动时被外键挡住抛 500。
    other = User(openid="del-user-dirty-bt", is_admin=False)
    db.add(other)
    db.flush()
    dirty_bt = BreakthroughEvent(user_id=other.id, activity_id=act_id, old_ftp=180, suggested_ftp=200,
                                 expires_at=datetime.now(timezone.utc) + timedelta(days=7))
    db.add(dirty_bt)
    db.commit()
    dirty_bt_id = dirty_bt.id

    deleted_files = []
    monkeypatch.setattr("app.meetup.service._storage.delete", lambda fid: deleted_files.append(fid))

    delete_user(db, user_id)

    assert db.query(User).filter(User.id == user_id).first() is None
    assert db.query(Activity).filter(Activity.user_id == user_id).count() == 0
    assert db.query(SegmentEffort).filter(SegmentEffort.user_id == user_id).count() == 0
    assert db.query(BreakthroughEvent).filter(BreakthroughEvent.user_id == user_id).count() == 0
    assert db.query(StravaImport).filter(StravaImport.user_id == user_id).count() == 0
    assert "202606/ride.gpx" in deleted_files  # 活动 GPX 文件被收集并清理
    # 挂在被删活动上的"脏"突破事件也必须被清掉（否则 activity_id RESTRICT 外键会挡住删活动）
    assert db.query(BreakthroughEvent).filter(BreakthroughEvent.id == dirty_bt_id).first() is None


def test_delete_account_endpoint_requires_auth_and_deletes_self(client, db, auth_header, test_user):
    """DELETE /api/user/me：无 token → 401；本人调用 → 204 且 user 被删。"""
    from app.user.models import User

    user_id = test_user.id
    assert client.delete("/api/user/me").status_code == 401  # 未登录不能注销
    res = client.delete("/api/user/me", headers=auth_header)
    assert res.status_code == 204
    assert db.query(User).filter(User.id == user_id).first() is None


def test_delete_user_uses_single_transaction():
    source = (ROOT / "app" / "user" / "service.py").read_text(encoding="utf-8")
    assert "def delete_user" in source
    block = source[source.index("def delete_user"):]
    # 只看代码行（剥掉以 # 开头的整行注释），否则解释性注释里出现的
    # "with db.begin()" / "db.commit()" 字面会污染静态断言（合同测试的脆弱点）。
    code = "\n".join(ln for ln in block.splitlines() if not ln.strip().startswith("#"))

    # 不能调用会各自 commit 的 delete_draft_meetup（中途 commit 破坏删号原子性）
    assert "delete_draft_meetup(" not in code
    # 必须用单次 db.commit() 收尾，且禁止 with db.begin()——真实注销端点注入的 session
    # 已因身份查询触发 autobegin，再 with db.begin() 二次开启事务会抛 InvalidRequestError。
    assert "with db.begin()" not in code
    assert code.count("db.commit()") == 1


def test_delete_user_works_when_session_in_active_transaction(db, test_user):
    # 复现真实注销端点会话状态：端点先做身份查询触发 autobegin、session 处于活动事务，
    # 再调 delete_user。delete_user 不能用 with db.begin() 二次开启事务（会抛 InvalidRequestError 500）。
    from app.user.service import delete_user

    user_id = test_user.id
    open_meetup = _meetup(db, user_id, status="OPEN", start_delta=5, end_delta=8)
    open_meetup_id = open_meetup.id

    # 制造活动事务（模拟端点里 get_current_user 等先行查询）
    db.query(User).filter(User.id == user_id).first()
    assert db.in_transaction()

    delete_user(db, user_id)  # 不能抛 InvalidRequestError

    assert db.query(User).filter(User.id == user_id).first() is None
    assert db.query(Meetup).filter(Meetup.id == open_meetup_id).first().status == "CANCELLED"
