"""
活动轨迹缩略图批量端点测试（GET /api/activities/track-thumbs）。

这个端点是"我的页/首页活动列表加轨迹小图"的数据源：
列表接口不带轨迹（ActivitySummary 刻意排除大 JSON），前端拿到一页活动 id 后
批量来这里换抽稀轨迹点，自己用 canvas 画形状线。

测试关注三件事：
1. 抽稀正确（≤60 点 / 起终点保留 / 格式 [[lon, lat], ...] 与 preview_points 一致）
2. 隐私（只返回自己的活动，别人的 id 静默缺席——不报错不泄露）
3. 容错（非法 id / 无轨迹活动 / 超量 ids 都不该 500）
"""

from datetime import datetime, timezone

from app.activity.models import Activity


def _make_track(n):
    """造 n 个点的 simplified_track（后端真实格式 [{lat, lon, ele}, ...]）"""
    return [
        {"lat": 37.8 + i * 0.001, "lon": 112.5 + i * 0.001, "ele": 800 + i}
        for i in range(n)
    ]


def _create_activity_with_track(db, user_id, track=None, title="带轨迹骑行"):
    activity = Activity(
        user_id=user_id,
        title=title,
        status="completed",
        file_url="202606/test.gpx",
        distance=50000.0,
        duration=3600,
        elevation_gain=500.0,
        started_at=datetime(2026, 6, 1, 6, 0, 0, tzinfo=timezone.utc),
        simplified_track=track,
    )
    db.add(activity)
    db.commit()
    db.refresh(activity)
    return activity.id


def test_track_thumbs_downsamples_to_60_points(client, auth_header, db, test_user):
    """200 点轨迹 → 抽稀到 ≤60 点 + 起终点保留 + [[lon, lat]] 格式"""
    aid = _create_activity_with_track(db, test_user.id, _make_track(200))

    resp = client.get(f"/api/activities/track-thumbs?ids={aid}", headers=auth_header)
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["activity_id"] == aid
    points = items[0]["points"]
    assert 2 <= len(points) <= 61  # 60 抽稀 + 终点补位最多 61
    # 格式 [[lon, lat]]：第一个点 = 轨迹起点
    assert points[0] == [112.5, 37.8]
    # 终点必保（最后一个原始点 lon = 112.5 + 199*0.001）
    assert abs(points[-1][0] - (112.5 + 0.199)) < 1e-9


def test_track_thumbs_excludes_other_users_activities(client, auth_header, db, test_user):
    """别人的活动 id 静默缺席：不报错、不泄露轨迹"""
    from app.user.models import User

    other = User(openid="track_thumb_other_user")
    db.add(other)
    db.commit()
    db.refresh(other)
    other_aid = _create_activity_with_track(db, other.id, _make_track(50))
    mine_aid = _create_activity_with_track(db, test_user.id, _make_track(50))

    resp = client.get(
        f"/api/activities/track-thumbs?ids={other_aid},{mine_aid}", headers=auth_header
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    returned_ids = [it["activity_id"] for it in items]
    assert mine_aid in returned_ids
    assert other_aid not in returned_ids


def test_track_thumbs_skips_activities_without_track(client, auth_header, db, test_user):
    """无轨迹（simplified_track 为 NULL 或点数不足）的活动不出现在结果里"""
    no_track = _create_activity_with_track(db, test_user.id, None, title="无轨迹")
    one_point = _create_activity_with_track(
        db, test_user.id, _make_track(1), title="单点轨迹"
    )
    ok = _create_activity_with_track(db, test_user.id, _make_track(30))

    resp = client.get(
        f"/api/activities/track-thumbs?ids={no_track},{one_point},{ok}",
        headers=auth_header,
    )
    assert resp.status_code == 200
    returned_ids = [it["activity_id"] for it in resp.json()["items"]]
    assert returned_ids == [ok]


def test_track_thumbs_tolerates_garbage_ids(client, auth_header):
    """非法 ids（非数字 / 空段）容错：200 空结果，不 500 不 422"""
    resp = client.get(
        "/api/activities/track-thumbs?ids=abc,,12x,-1", headers=auth_header
    )
    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_track_thumbs_requires_auth(client):
    """未登录 → 401（批量轨迹是个人数据）"""
    resp = client.get("/api/activities/track-thumbs?ids=1")
    assert resp.status_code == 401
