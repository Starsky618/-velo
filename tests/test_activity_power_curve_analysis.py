"""
单次 activity 功率曲线分析测试——防止把 Strava 曲线降级成 7 个固定成绩点。

这组测试盯三件事：
- 任意秒数都能精确查最佳平均功率
- 轨迹点不是 1 秒一个时，也要按 timestamp 还原真实 elapsed time
- 隐藏功率时，别人不能通过曲线反推出功率
"""
from datetime import datetime, timedelta, timezone

from app.activity.models import Activity, ActivityPrivacy, Trackpoint
from app.activity.service import (
    get_activity_power_curve,
    get_activity_power_curve_effort,
)
from app.user.models import User
from app.user.service import create_token


def _activity(db, user_id: int, duration: int = 120) -> Activity:
    act = Activity(
        user_id=user_id,
        title="功率曲线测试骑行",
        status="completed",
        distance=30000.0,
        duration=duration,
        started_at=datetime(2026, 5, 20, 8, 0, tzinfo=timezone.utc),
        activity_type="cycling",
    )
    db.add(act)
    db.commit()
    db.refresh(act)
    return act


def _add_power_points(db, activity_id: int, points: list[tuple[int, int | None]]) -> None:
    start = datetime(2026, 5, 20, 8, 0, tzinfo=timezone.utc)
    for seq, (offset_sec, power) in enumerate(points):
        db.add(
            Trackpoint(
                activity_id=activity_id,
                seq=seq,
                latitude=30.0 + seq * 0.0001,
                longitude=120.0,
                elevation=100.0,
                timestamp=start + timedelta(seconds=offset_sec),
                power=power,
                speed=8.0,
                distance=offset_sec * 8.0,
            )
        )
    db.commit()


def test_effort_uses_elapsed_seconds_not_trackpoint_count(db, test_user):
    """10 秒一个点时，15 秒窗口仍能滑到第 5 秒开始，而不是只能卡在点上。"""
    act = _activity(db, test_user.id, duration=30)
    _add_power_points(
        db,
        act.id,
        [
            (0, 100),
            (10, 300),
            (20, 100),
            (30, 100),
        ],
    )

    effort = get_activity_power_curve_effort(db, act.id, test_user.id, duration_sec=15)

    assert effort["duration_sec"] == 15
    assert abs(effort["best_power_w"] - 233.3) < 0.01
    assert effort["start_sec"] == 5
    assert effort["end_sec"] == 20


def test_large_timestamp_gap_is_zero_not_fake_continuous_power(db, test_user):
    """大于 60 秒的断点不能把前一个 300W 一路延续过去，否则睡眠/GPS 丢失会造假。"""
    act = _activity(db, test_user.id, duration=90)
    _add_power_points(
        db,
        act.id,
        [
            (0, 300),
            (10, 300),
            (80, 300),
            (90, 300),
        ],
    )

    effort = get_activity_power_curve_effort(db, act.id, test_user.id, duration_sec=70)

    assert abs(effort["best_power_w"] - 42.9) < 0.01
    assert effort["start_sec"] in {0, 20}
    assert effort["end_sec"] == effort["start_sec"] + 70


def test_curve_summary_keeps_benchmarks_inside_smart_points(db, test_user):
    """画图点可以抽样，但 Strava 常见成绩点必须强制保留，方便用户直接读关键时长。"""
    act = _activity(db, test_user.id, duration=130)
    _add_power_points(db, act.id, [(sec, 200) for sec in range(0, 131)])

    curve = get_activity_power_curve(db, act.id, test_user.id, max_points=20)
    durations = {point["duration_sec"] for point in curve["points"]}

    assert curve["has_power"] is True
    assert curve["max_duration_sec"] == 130
    assert len(curve["points"]) <= 20
    assert {1, 5, 15, 30, 60, 120}.issubset(durations)
    assert curve["benchmarks"]["60"]["best_power_w"] == 200.0
    assert curve["resolution_label"]


def test_power_none_counts_as_zero_inside_best_effort(db, test_user):
    """None 代表这一秒没有可用功率读数，要按 0W 进入平均值，不能跳过。"""
    act = _activity(db, test_user.id, duration=30)
    _add_power_points(db, act.id, [(0, 300), (10, None), (20, 300), (30, 300)])

    effort = get_activity_power_curve_effort(db, act.id, test_user.id, duration_sec=20)

    assert effort["best_power_w"] == 150.0
    assert effort["start_sec"] == 0
    assert effort["end_sec"] == 20


def test_zero_power_is_still_valid_power_data(db, test_user):
    """全 0W 也说明有功率通道，只是这段没输出；卡片应显示 0W 曲线而不是消失。"""
    act = _activity(db, test_user.id, duration=20)
    _add_power_points(db, act.id, [(0, 0), (10, 0), (20, 0)])

    curve = get_activity_power_curve(db, act.id, test_user.id, max_points=20)

    assert curve["has_power"] is True
    assert curve["benchmarks"]["5"]["best_power_w"] == 0.0


def test_no_timestamp_or_no_power_returns_empty_curve(db, test_user):
    """没有 timestamp 无法还原 elapsed time；没有 power 则不展示整张卡。"""
    act_no_timestamp = _activity(db, test_user.id, duration=20)
    for seq in range(3):
        db.add(
            Trackpoint(
                activity_id=act_no_timestamp.id,
                seq=seq,
                latitude=30.0,
                longitude=120.0,
                timestamp=None,
                power=200,
            )
        )

    act_no_power = _activity(db, test_user.id, duration=20)
    _add_power_points(db, act_no_power.id, [(0, None), (10, None), (20, None)])
    db.commit()

    no_timestamp = get_activity_power_curve(db, act_no_timestamp.id, test_user.id, max_points=20)
    no_power = get_activity_power_curve(db, act_no_power.id, test_user.id, max_points=20)

    assert no_timestamp["has_power"] is False
    assert no_timestamp["points"] == []
    assert no_power["has_power"] is False
    assert no_power["points"] == []


def test_curve_max_duration_uses_trackpoint_span_not_activity_duration_padding(db, test_user):
    """曲线最长时长来自原始点首尾时间，不能被 activity.duration 拉出一段假尾巴。"""
    act = _activity(db, test_user.id, duration=120)
    _add_power_points(db, act.id, [(0, 200), (10, 200), (20, 200)])

    curve = get_activity_power_curve(db, act.id, test_user.id, max_points=20)

    assert curve["max_duration_sec"] == 20
    assert "30" not in curve["benchmarks"]


def test_power_curve_hidden_for_other_viewer_when_hide_power(db, test_user):
    """别人看 hide_power=true 的公开活动，接口应像“没功率计”一样返回空曲线。"""
    owner = User(openid="activity_power_curve_owner", is_admin=False)
    db.add(owner)
    db.commit()
    db.refresh(owner)

    act = _activity(db, owner.id, duration=30)
    _add_power_points(db, act.id, [(0, 250), (10, 250), (20, 250), (30, 250)])
    db.add(ActivityPrivacy(activity_id=act.id, visibility="public", hide_power=True))
    db.commit()

    curve = get_activity_power_curve(db, act.id, test_user.id, max_points=20)
    effort = get_activity_power_curve_effort(db, act.id, test_user.id, duration_sec=10)

    assert curve["has_power"] is False
    assert curve["points"] == []
    assert curve["benchmarks"] == {}
    assert effort["has_power"] is False
    assert effort["best_power_w"] is None


def test_power_curve_api_returns_summary_and_exact_effort(client, auth_header, db, test_user):
    """前端真实请求两个新接口时，应拿到画图点和拖动停住后的精确读数。"""
    act = _activity(db, test_user.id, duration=30)
    _add_power_points(db, act.id, [(0, 100), (10, 300), (20, 100), (30, 100)])

    curve_resp = client.get(
        f"/api/activities/{act.id}/power-curve?points=50",
        headers=auth_header,
    )
    effort_resp = client.get(
        f"/api/activities/{act.id}/power-curve/effort?duration_sec=15",
        headers=auth_header,
    )

    assert curve_resp.status_code == 200
    curve = curve_resp.json()
    assert curve["has_power"] is True
    assert curve["max_duration_sec"] == 30
    assert len(curve["points"]) <= 50
    assert "15" in curve["benchmarks"]

    assert effort_resp.status_code == 200
    effort = effort_resp.json()
    assert abs(effort["best_power_w"] - 233.3) < 0.01
    assert effort["start_sec"] == 5
    assert effort["end_sec"] == 20


def test_power_curve_api_owner_can_see_hidden_power(client, db):
    """hide_power 只挡别人；owner 打开自己的详情页仍能看到完整功率曲线。"""
    owner = User(openid="activity_power_curve_hidden_owner", is_admin=False)
    db.add(owner)
    db.commit()
    db.refresh(owner)

    act = _activity(db, owner.id, duration=20)
    _add_power_points(db, act.id, [(0, 250), (10, 250), (20, 250)])
    db.add(ActivityPrivacy(activity_id=act.id, visibility="public", hide_power=True))
    db.commit()

    owner_header = {"Authorization": f"Bearer {create_token(owner.id)}"}
    resp = client.get(f"/api/activities/{act.id}/power-curve?points=50", headers=owner_header)

    assert resp.status_code == 200
    body = resp.json()
    assert body["has_power"] is True
    assert body["benchmarks"]["5"]["best_power_w"] == 250.0


def test_power_curve_api_private_activity_still_404(client, auth_header, db):
    """私密骑行仍然按详情页旧规则隐藏，不能因为新曲线接口绕过门禁。"""
    owner = User(openid="activity_power_curve_private_owner", is_admin=False)
    db.add(owner)
    db.commit()
    db.refresh(owner)

    act = _activity(db, owner.id, duration=20)
    _add_power_points(db, act.id, [(0, 250), (10, 250), (20, 250)])
    db.add(ActivityPrivacy(activity_id=act.id, visibility="private", hide_power=False))
    db.commit()

    resp = client.get(f"/api/activities/{act.id}/power-curve?points=50", headers=auth_header)

    assert resp.status_code == 404


def test_power_curve_effort_api_rejects_duration_beyond_activity(client, auth_header, db, test_user):
    """duration_sec 超过本次骑行长度时是参数错，应该返回 400 而不是伪装成 404。"""
    act = _activity(db, test_user.id, duration=20)
    _add_power_points(db, act.id, [(0, 250), (10, 250), (20, 250)])

    resp = client.get(
        f"/api/activities/{act.id}/power-curve/effort?duration_sec=21",
        headers=auth_header,
    )

    assert resp.status_code == 400
