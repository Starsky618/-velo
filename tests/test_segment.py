"""
赛段模块测试——"赛道系统的期末考试"。

分为两大板块：
1. matcher 纯函数测试（不需要数据库，直接调函数验证算法正确性）
2. API 接口测试（通过 HTTP 请求测试排行榜、用户成绩、途经赛段等端点）

注意事项：
- matcher 测试用构造的坐标数据，精心设计每种边界情况
- API 测试需要 SQLite 测试数据库，但 PostGIS 函数（ST_DWithin 等）不可用
  因此创建赛段、附近搜索等 PostGIS 依赖功能无法在 SQLite 中测试
- 排行榜和用户成绩的测试通过直接插入 _segments_table/_segment_efforts_table 数据绕过 PostGIS
"""

from datetime import datetime, timedelta

from app.segment.matcher import match_segment


# ==================== 测试数据构造 ====================

def _make_trackpoints(coords, start_time=None, interval=10):
    """
    构造一组轨迹点字典列表。

    参数：
    - coords: [(lat, lon), ...] 坐标序列
    - start_time: 起始时间，默认 2026-01-01 08:00:00
    - interval: 相邻点之间的秒数间隔，默认 10 秒
    """
    if start_time is None:
        start_time = datetime(2026, 1, 1, 8, 0, 0)
    return [
        {
            "lat": lat,
            "lon": lon,
            "time": start_time + timedelta(seconds=i * interval),
            "seq": i,
        }
        for i, (lat, lon) in enumerate(coords)
    ]


# 标准测试赛段：太原汾河东岸一段直线（南→北）
# 起点 (37.87, 112.55) → 终点 (37.875, 112.55)，约 556 米
_SEG_START = (37.87, 112.55)
_SEG_END = (37.875, 112.55)
_SEG_REF = [
    (37.870, 112.55),
    (37.871, 112.55),
    (37.872, 112.55),
    (37.873, 112.55),
    (37.874, 112.55),
    (37.875, 112.55),
]


# ==================== matcher 纯函数测试 ====================

def test_01_match_success():
    """正常匹配：轨迹完整经过赛段，返回 matched=True + 正确用时"""
    # 轨迹：从赛段起点前方出发，沿赛段走完，继续前进
    coords = [
        (37.869, 112.55),   # seq=0：起点之前（约 111m 外，超出 50m tolerance）
        (37.870, 112.55),   # seq=1：正好在赛段起点（0m）
        (37.871, 112.55),   # seq=2：赛段中间
        (37.872, 112.55),   # seq=3
        (37.873, 112.55),   # seq=4
        (37.874, 112.55),   # seq=5
        (37.875, 112.55),   # seq=6：正好在赛段终点
        (37.876, 112.55),   # seq=7：终点之后
    ]
    tps = _make_trackpoints(coords, interval=10)

    result = match_segment(
        trackpoints=tps,
        segment_start=_SEG_START,
        segment_end=_SEG_END,
        reference_coords=_SEG_REF,
    )

    assert result["matched"] is True
    assert result["start_index"] == 1       # seq=1 是第一个在 tolerance 内的
    assert result["end_index"] == 6         # seq=6 最接近终点
    assert result["elapsed_time"] == 50     # (6 - 1) * 10 = 50 秒


def test_02_match_start_too_far():
    """起点不在容差范围内：轨迹没经过赛段起点附近"""
    # 所有点都在赛段起点以南 200m+
    coords = [
        (37.867, 112.55),   # 约 333m 南
        (37.868, 112.55),   # 约 222m 南
        (37.869, 112.55),   # 约 111m 南（仍超出 50m 默认 tolerance）
    ]
    tps = _make_trackpoints(coords)

    result = match_segment(
        trackpoints=tps,
        segment_start=_SEG_START,
        segment_end=_SEG_END,
        reference_coords=_SEG_REF,
    )
    assert result["matched"] is False


def test_03_match_end_too_far():
    """经过起点但没到终点：骑了一半就掉头了"""
    coords = [
        (37.870, 112.55),   # seq=0：在起点
        (37.871, 112.55),   # seq=1：赛段中间
        (37.872, 112.55),   # seq=2：赛段中间
        # 没有到达终点 (37.875, 112.55)，最近也距终点 ~333m
    ]
    tps = _make_trackpoints(coords)

    result = match_segment(
        trackpoints=tps,
        segment_start=_SEG_START,
        segment_end=_SEG_END,
        reference_coords=_SEG_REF,
    )
    assert result["matched"] is False


def test_04_match_low_coverage():
    """覆盖率不足：骑手走了捷径，大部分轨迹不在赛道上"""
    # 起点和终点都对，但中间大部分点偏离赛道（经度偏移 0.002 ≈ 170m）
    coords = [
        (37.870, 112.55),    # seq=0：在起点
        (37.871, 112.552),   # seq=1：偏离赛道约 170m
        (37.872, 112.552),   # seq=2：偏离
        (37.873, 112.552),   # seq=3：偏离
        (37.874, 112.552),   # seq=4：偏离
        (37.875, 112.55),    # seq=5：回到终点
    ]
    tps = _make_trackpoints(coords)

    result = match_segment(
        trackpoints=tps,
        segment_start=_SEG_START,
        segment_end=_SEG_END,
        reference_coords=_SEG_REF,
    )
    # 6 个点中只有 2 个在赛道上（seq=0 和 seq=5），覆盖率 2/6 ≈ 33% < 80%
    assert result["matched"] is False


def test_05_match_no_timestamp():
    """无时间戳：起终点都有但没有时间信息，无法计时"""
    coords = [
        (37.870, 112.55),
        (37.872, 112.55),
        (37.875, 112.55),
    ]
    # 手动构造没有 time 字段的轨迹点
    tps = [{"lat": lat, "lon": lon, "time": None, "seq": i}
           for i, (lat, lon) in enumerate(coords)]

    result = match_segment(
        trackpoints=tps,
        segment_start=_SEG_START,
        segment_end=_SEG_END,
        reference_coords=_SEG_REF,
    )
    assert result["matched"] is False


def test_06_match_empty_input():
    """空输入：轨迹点或参考路线为空"""
    result1 = match_segment(
        trackpoints=[],
        segment_start=_SEG_START,
        segment_end=_SEG_END,
        reference_coords=_SEG_REF,
    )
    assert result1["matched"] is False

    tps = _make_trackpoints([(37.870, 112.55), (37.875, 112.55)])
    result2 = match_segment(
        trackpoints=tps,
        segment_start=_SEG_START,
        segment_end=_SEG_END,
        reference_coords=[],  # 空参考路线
    )
    assert result2["matched"] is False


def test_07_match_reversed_direction():
    """方向相反：从终点向起点骑，应该不匹配"""
    # 赛段方向是 南→北 (37.87→37.875)，轨迹方向是 北→南
    coords = [
        (37.876, 112.55),   # 从终点以北出发
        (37.875, 112.55),   # 经过终点（但这是轨迹的"起始段"）
        (37.874, 112.55),
        (37.873, 112.55),
        (37.872, 112.55),
        (37.871, 112.55),
        (37.870, 112.55),   # 到达赛段起点（但这是轨迹的"末尾"）
    ]
    tps = _make_trackpoints(coords)

    result = match_segment(
        trackpoints=tps,
        segment_start=_SEG_START,
        segment_end=_SEG_END,
        reference_coords=_SEG_REF,
    )
    # 算法先找起点（第一个在 start tolerance 内的点）→ seq=6
    # 然后从 seq=7 开始找终点 → 没有更多点了 → 不匹配
    assert result["matched"] is False


def test_08_match_single_point():
    """只有一个轨迹点：不可能同时满足起终点"""
    tps = _make_trackpoints([(37.870, 112.55)])
    result = match_segment(
        trackpoints=tps,
        segment_start=_SEG_START,
        segment_end=_SEG_END,
        reference_coords=_SEG_REF,
    )
    assert result["matched"] is False


# ==================== API 接口测试 ====================
# 以下测试需要 conftest.py 中的 db、client、test_user、auth_header fixture

def test_08_create_segment_non_admin(client, auth_header):
    """非管理员创建赛段 → 403"""
    resp = client.post("/api/segments", json={
        "name": "测试赛段",
        "reference_points": [
            {"lat": 37.87, "lon": 112.55},
            {"lat": 37.875, "lon": 112.55},
        ],
    }, headers=auth_header)
    assert resp.status_code == 403


def test_09_create_segment_no_auth(client):
    """未登录创建赛段 → 401"""
    resp = client.post("/api/segments", json={
        "name": "测试赛段",
        "reference_points": [
            {"lat": 37.87, "lon": 112.55},
            {"lat": 37.875, "lon": 112.55},
        ],
    })
    assert resp.status_code == 401


def test_10_create_segment_bad_params(client, auth_header):
    """参数校验：名称为空、坐标点不足 2 个"""
    # 名称为空
    resp = client.post("/api/segments", json={
        "name": "",
        "reference_points": [
            {"lat": 37.87, "lon": 112.55},
            {"lat": 37.875, "lon": 112.55},
        ],
    }, headers=auth_header)
    assert resp.status_code == 422

    # 只有 1 个坐标点
    resp = client.post("/api/segments", json={
        "name": "太短",
        "reference_points": [{"lat": 37.87, "lon": 112.55}],
    }, headers=auth_header)
    assert resp.status_code == 422


def _insert_segment(db, name="汾河北段计时", distance=556.0, elevation_gain=10.0):
    """直接往数据库插入一条赛段（绕过 PostGIS）"""
    from tests.conftest import _segments_table
    db.execute(_segments_table.insert().values(
        name=name,
        distance=distance,
        elevation_gain=elevation_gain,
        start_lat=37.87,
        start_lon=112.55,
        end_lat=37.875,
        end_lon=112.55,
        match_tolerance=50.0,
        min_match_ratio=0.8,
        created_at=datetime(2026, 4, 1),
    ))
    db.commit()
    # 返回插入的 id（SQLite 最后插入的 rowid）
    result = db.execute(_segments_table.select().where(
        _segments_table.c.name == name
    )).first()
    return result.id


def _insert_effort(db, segment_id, activity_id, user_id,
                    elapsed_time=142, avg_speed=36.2, avg_power=245.0):
    """直接往数据库插入一条赛段成绩"""
    from tests.conftest import _segment_efforts_table
    db.execute(_segment_efforts_table.insert().values(
        segment_id=segment_id,
        activity_id=activity_id,
        user_id=user_id,
        elapsed_time=elapsed_time,
        avg_speed=avg_speed,
        avg_power=avg_power,
        start_index=1,
        end_index=6,
        created_at=datetime(2026, 4, 1),
    ))
    db.commit()


def _insert_activity(db, user_id, title="测试骑行"):
    """直接往数据库插入一条活动记录"""
    from tests.conftest import _activities_table
    db.execute(_activities_table.insert().values(
        user_id=user_id,
        title=title,
        status="completed",
        file_url="test.gpx",
        distance=50000.0,
        created_at=datetime(2026, 4, 1),
    ))
    db.commit()
    result = db.execute(_activities_table.select().where(
        _activities_table.c.title == title
    )).first()
    return result.id


def test_11_leaderboard_empty(client, db):
    """赛段排行榜：赛段存在但没有任何成绩记录"""
    seg_id = _insert_segment(db)
    resp = client.get(f"/api/segments/{seg_id}/leaderboard")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["items"] == []


def test_12_leaderboard_sorted(client, db, test_user):
    """排行榜按 elapsed_time 升序排列，rank 正确"""
    seg_id = _insert_segment(db)
    act_id = _insert_activity(db, test_user.id, "骑行A")

    # 创建第二个用户
    from app.user.models import User
    user2 = User(openid="leaderboard_user_2")
    db.add(user2)
    db.commit()
    db.refresh(user2)
    act_id2 = _insert_activity(db, user2.id, "骑行B")

    # 用户 2 更快（100 秒），用户 1 更慢（200 秒）
    _insert_effort(db, seg_id, act_id, test_user.id, elapsed_time=200)
    _insert_effort(db, seg_id, act_id2, user2.id, elapsed_time=100)

    resp = client.get(f"/api/segments/{seg_id}/leaderboard")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    # 第一名应该是 100 秒（user2），第二名 200 秒（test_user）
    assert data["items"][0]["rank"] == 1
    assert data["items"][0]["elapsed_time"] == 100
    assert data["items"][1]["rank"] == 2
    assert data["items"][1]["elapsed_time"] == 200


def test_13_leaderboard_not_found(client):
    """赛段不存在 → 404"""
    resp = client.get("/api/segments/99999/leaderboard")
    assert resp.status_code == 404


def test_14_user_efforts(client, db, test_user, auth_header):
    """用户赛段成绩：返回所有赛段成绩 + 正确排名"""
    seg_id = _insert_segment(db)
    act_id = _insert_activity(db, test_user.id)
    _insert_effort(db, seg_id, act_id, test_user.id, elapsed_time=150)

    # 添加另一个更快的用户，让 test_user 排第 2 名
    from app.user.models import User
    user2 = User(openid="effort_user_2")
    db.add(user2)
    db.commit()
    db.refresh(user2)
    act_id2 = _insert_activity(db, user2.id, "快骑")
    _insert_effort(db, seg_id, act_id2, user2.id, elapsed_time=100)

    resp = client.get("/api/user/efforts", headers=auth_header)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["segment_name"] == "汾河北段计时"
    assert data["items"][0]["rank"] == 2  # 有人比 150 秒快（100 秒）


def test_15_user_efforts_no_auth(client):
    """未登录查用户成绩 → 401"""
    resp = client.get("/api/user/efforts")
    assert resp.status_code == 401


def test_16_activity_segments(client, db, test_user, auth_header):
    """活动途经赛段：返回匹配的赛段 + rank + is_pr"""
    seg_id = _insert_segment(db)
    act_id = _insert_activity(db, test_user.id, "正常骑行")
    _insert_effort(db, seg_id, act_id, test_user.id, elapsed_time=142)

    resp = client.get(f"/api/activities/{act_id}/segments", headers=auth_header)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["segment_name"] == "汾河北段计时"
    assert item["elapsed_time"] == 142
    assert item["rank"] == 1     # 唯一一条成绩，排第 1
    assert item["is_pr"] is True  # 唯一一条成绩，就是个人最佳


def test_17_activity_segments_not_pr(client, db, test_user, auth_header):
    """活动途经赛段：当存在更好成绩时 is_pr=False"""
    seg_id = _insert_segment(db)

    # 第一次骑行：用时 100 秒（个人最佳）
    act_id1 = _insert_activity(db, test_user.id, "快骑")
    _insert_effort(db, seg_id, act_id1, test_user.id, elapsed_time=100)

    # 第二次骑行：用时 150 秒（不是个人最佳）
    act_id2 = _insert_activity(db, test_user.id, "慢骑")
    _insert_effort(db, seg_id, act_id2, test_user.id, elapsed_time=150)

    resp = client.get(f"/api/activities/{act_id2}/segments", headers=auth_header)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["is_pr"] is False  # 有更好的 100 秒


def test_18_activity_segments_other_user(client, db, test_user, auth_header):
    """查看别人活动的途经赛段 → 403"""
    from app.user.models import User
    other_user = User(openid="other_user_segments")
    db.add(other_user)
    db.commit()
    db.refresh(other_user)

    act_id = _insert_activity(db, other_user.id, "别人的骑行")

    resp = client.get(f"/api/activities/{act_id}/segments", headers=auth_header)
    assert resp.status_code == 403


def test_19_activity_segments_not_found(client, auth_header):
    """活动不存在 → 404"""
    resp = client.get("/api/activities/99999/segments", headers=auth_header)
    assert resp.status_code == 404


def test_20_segment_detail_not_found(client):
    """赛段详情不存在 → 404"""
    resp = client.get("/api/segments/99999")
    assert resp.status_code == 404
