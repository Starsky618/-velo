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

from datetime import datetime, timedelta, timezone  # task-0.1 双审 C2：加 timezone 用于 aware datetime

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
        start_time = datetime(2026, 1, 1, 8, 0, 0, tzinfo=timezone.utc)  # task-0.1 双审 C2 修复
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
        created_at=datetime(2026, 4, 1, tzinfo=timezone.utc),  # task-0.1 双审 C2 修复
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
        created_at=datetime(2026, 4, 1, tzinfo=timezone.utc),  # task-0.1 双审 C2 修复
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
        created_at=datetime(2026, 4, 1, tzinfo=timezone.utc),  # task-0.1 双审 C2 修复
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


# ========== Sprint 4 D7 hotfix：my_rank + my_elapsed_time ==========


def test_13a_leaderboard_no_auth_my_rank_none(client, db):
    """未登录访问 leaderboard → my_rank / my_elapsed_time 为 None（不抛 401）"""
    seg_id = _insert_segment(db)
    resp = client.get(f"/api/segments/{seg_id}/leaderboard")
    assert resp.status_code == 200
    data = resp.json()
    assert data["my_rank"] is None
    assert data["my_elapsed_time"] is None


def test_13b_leaderboard_logged_in_no_effort_my_rank_none(client, db, test_user, auth_header):
    """登录但没骑过该赛段 → my_rank=None / my_elapsed_time=None"""
    seg_id = _insert_segment(db)
    resp = client.get(f"/api/segments/{seg_id}/leaderboard", headers=auth_header)
    assert resp.status_code == 200
    data = resp.json()
    assert data["my_rank"] is None
    assert data["my_elapsed_time"] is None


def test_13c_leaderboard_logged_in_with_pr_returns_rank(client, db, test_user, auth_header):
    """登录用户骑过该赛段 → my_rank+my_elapsed_time 正确（基于 PR / 比我快的 effort 数 + 1）"""
    seg_id = _insert_segment(db)
    act_id = _insert_activity(db, test_user.id, "骑行A")

    # 创建另外两个用户都更快（比我快）
    from app.user.models import User
    user2 = User(openid="d7_test_user_2")
    user3 = User(openid="d7_test_user_3")
    db.add(user2)
    db.add(user3)
    db.commit()
    db.refresh(user2)
    db.refresh(user3)
    act_id2 = _insert_activity(db, user2.id, "骑行B")
    act_id3 = _insert_activity(db, user3.id, "骑行C")

    # user2: 100 秒 / user3: 150 秒 / test_user: 300 秒（PR）
    _insert_effort(db, seg_id, act_id2, user2.id, elapsed_time=100)
    _insert_effort(db, seg_id, act_id3, user3.id, elapsed_time=150)
    _insert_effort(db, seg_id, act_id, test_user.id, elapsed_time=300)

    resp = client.get(f"/api/segments/{seg_id}/leaderboard", headers=auth_header)
    assert resp.status_code == 200
    data = resp.json()
    # 我的 PR=300 / 比我快的 effort 有 2 个（100 + 150）/ 我的 rank=3
    assert data["my_rank"] == 3
    assert data["my_elapsed_time"] == 300
    # 验证跟 items 里同 user_id 的 rank 一致（top 内场景）
    me_in_items = next(item for item in data["items"] if item["user_id"] == test_user.id)
    assert me_in_items["rank"] == 3


def test_13d_leaderboard_logged_in_pr_with_multiple_efforts(client, db, test_user, auth_header):
    """登录用户对同赛段有多次 effort → my_elapsed_time 取最快（PR）/ my_rank 基于 PR 计算"""
    seg_id = _insert_segment(db)
    act_id = _insert_activity(db, test_user.id)

    # 我的 3 次 effort：250 / 200 / 280 → PR=200
    _insert_effort(db, seg_id, act_id, test_user.id, elapsed_time=250)
    _insert_effort(db, seg_id, act_id, test_user.id, elapsed_time=200)
    _insert_effort(db, seg_id, act_id, test_user.id, elapsed_time=280)

    resp = client.get(f"/api/segments/{seg_id}/leaderboard", headers=auth_header)
    assert resp.status_code == 200
    data = resp.json()
    # 我的 PR=200 / 没有比我更快的 effort（不算我自己的 250/280）/ rank=1
    assert data["my_rank"] == 1
    assert data["my_elapsed_time"] == 200


def test_13e_leaderboard_my_rank_out_of_top_page(client, db, test_user, auth_header):
    """D7 hotfix 核心动机回归（Codex 异源审 I2-a）：
    用户排在 page 之外仍能精确返回 my_rank（不是 # 占位 / 不是 None）。

    场景：4 个 effort（user2:50, user3:80, user4:120, test_user:200）+ page_size=3
    → items 含前 3 / 我（test_user）排第 4 不在 items 里 / my_rank=4 / my_elapsed_time=200
    """
    seg_id = _insert_segment(db)
    act_id = _insert_activity(db, test_user.id)

    from app.user.models import User
    user2 = User(openid="d7_top_out_2")
    user3 = User(openid="d7_top_out_3")
    user4 = User(openid="d7_top_out_4")
    db.add_all([user2, user3, user4])
    db.commit()
    db.refresh(user2)
    db.refresh(user3)
    db.refresh(user4)
    act_id2 = _insert_activity(db, user2.id, "B")
    act_id3 = _insert_activity(db, user3.id, "C")
    act_id4 = _insert_activity(db, user4.id, "D")

    _insert_effort(db, seg_id, act_id2, user2.id, elapsed_time=50)
    _insert_effort(db, seg_id, act_id3, user3.id, elapsed_time=80)
    _insert_effort(db, seg_id, act_id4, user4.id, elapsed_time=120)
    _insert_effort(db, seg_id, act_id, test_user.id, elapsed_time=200)

    resp = client.get(f"/api/segments/{seg_id}/leaderboard?page_size=3", headers=auth_header)
    assert resp.status_code == 200
    data = resp.json()
    # items 只 3 条（前 3 名）/ 我不在
    assert len(data["items"]) == 3
    assert all(item["user_id"] != test_user.id for item in data["items"])
    # 真 my_rank=4（不是 # 占位 / 不是 None）
    assert data["my_rank"] == 4
    assert data["my_elapsed_time"] == 200


def test_13f_leaderboard_bike_type_filter_no_match(client, db, test_user, auth_header):
    """D7 hotfix bike_type filter 边界（Codex 异源审 I2-b）：
    ?bike_type=road 而用户无 road effort → my_rank=None / my_elapsed_time=None。

    场景：user2 bike_type=road 骑了 / test_user bike_type=None（默认）骑了
    → ?bike_type=road 时 / items 只含 user2 / 我的 PR query JOIN User 后被
    bike_type=road filter 排除 → my_rank=None
    """
    seg_id = _insert_segment(db)
    act_id = _insert_activity(db, test_user.id)

    from app.user.models import User
    user2 = User(openid="d7_bike_road_user", bike_type="road")
    db.add(user2)
    db.commit()
    db.refresh(user2)
    act_id2 = _insert_activity(db, user2.id, "RoadRide")

    _insert_effort(db, seg_id, act_id2, user2.id, elapsed_time=100)
    _insert_effort(db, seg_id, act_id, test_user.id, elapsed_time=200)

    resp = client.get(
        f"/api/segments/{seg_id}/leaderboard?bike_type=road",
        headers=auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    # items 只含 road 用户（user2）/ 不含 test_user
    assert len(data["items"]) == 1
    assert data["items"][0]["user_id"] == user2.id
    # test_user 没 road effort → my_rank=None
    assert data["my_rank"] is None
    assert data["my_elapsed_time"] is None


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
