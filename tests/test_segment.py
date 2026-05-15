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

from app.activity.models import ActivityPrivacy
from app.segment.matcher import match_segment
from app.user.models import User


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


def test_leaderboard_filters_private_for_others(client, db):
    """他人看榜时，私密成绩整条消失，total 和 rank 都按过滤后重算。"""
    seg_id = _insert_segment(db)
    users = [User(openid=f"privacy_other_{i}") for i in range(5)]
    db.add_all(users)
    db.commit()
    for user in users:
        db.refresh(user)

    activity_ids = [_insert_activity(db, user.id, f"骑行{i}") for i, user in enumerate(users)]
    for idx, (user, activity_id) in enumerate(zip(users, activity_ids), start=1):
        _insert_effort(db, seg_id, activity_id, user.id, elapsed_time=idx * 100)
    db.add(ActivityPrivacy(activity_id=activity_ids[2], visibility="private"))
    db.commit()

    resp = client.get(f"/api/segments/{seg_id}/leaderboard")
    data = resp.json()

    assert resp.status_code == 200
    assert data["total"] == 4
    assert [item["rank"] for item in data["items"]] == [1, 2, 3, 4]
    assert [item["elapsed_time"] for item in data["items"]] == [100, 200, 400, 500]
    assert all(item["is_private_self"] is False for item in data["items"])


def test_leaderboard_shows_own_private_to_self(client, db, test_user, auth_header):
    """本人看榜时，自己的私密成绩仍保留，并带上专属标记。"""
    seg_id = _insert_segment(db)
    act_id = _insert_activity(db, test_user.id, "我的私密骑行")
    _insert_effort(db, seg_id, act_id, test_user.id, elapsed_time=150)
    db.add(ActivityPrivacy(activity_id=act_id, visibility="private"))
    db.commit()

    resp = client.get(f"/api/segments/{seg_id}/leaderboard", headers=auth_header)
    data = resp.json()

    assert resp.status_code == 200
    assert data["total"] == 1
    assert data["items"][0]["user_id"] == test_user.id
    assert data["items"][0]["is_private_self"] is True


def test_leaderboard_rank_continuous_after_filter(client, db):
    """第 3 名私密后，外部榜单仍是连续 1-2-3-4，不留下泄密跳号。"""
    seg_id = _insert_segment(db)
    users = [User(openid=f"privacy_gap_{i}") for i in range(5)]
    db.add_all(users)
    db.commit()
    for user in users:
        db.refresh(user)

    activity_ids = [_insert_activity(db, user.id, f"Gap{i}") for i, user in enumerate(users)]
    for idx, (user, activity_id) in enumerate(zip(users, activity_ids), start=1):
        _insert_effort(db, seg_id, activity_id, user.id, elapsed_time=idx * 10)
    db.add(ActivityPrivacy(activity_id=activity_ids[2], visibility="private"))
    db.commit()

    resp = client.get(f"/api/segments/{seg_id}/leaderboard")
    data = resp.json()

    assert [item["rank"] for item in data["items"]] == [1, 2, 3, 4]


def test_my_rank_excludes_private_efforts(client, db, test_user, auth_header):
    """my_rank 只数公开的更快成绩，避免主榜和“我的排名”说两套话。"""
    seg_id = _insert_segment(db)
    my_act_id = _insert_activity(db, test_user.id, "我的骑行")
    faster_public = User(openid="rank_public")
    faster_private = User(openid="rank_private")
    db.add_all([faster_public, faster_private])
    db.commit()
    db.refresh(faster_public)
    db.refresh(faster_private)
    public_act_id = _insert_activity(db, faster_public.id, "公开快骑")
    private_act_id = _insert_activity(db, faster_private.id, "私密快骑")

    _insert_effort(db, seg_id, public_act_id, faster_public.id, elapsed_time=100)
    _insert_effort(db, seg_id, private_act_id, faster_private.id, elapsed_time=120)
    _insert_effort(db, seg_id, my_act_id, test_user.id, elapsed_time=200)
    db.add(ActivityPrivacy(activity_id=private_act_id, visibility="private"))
    db.commit()

    resp = client.get(f"/api/segments/{seg_id}/leaderboard", headers=auth_header)
    data = resp.json()

    assert resp.status_code == 200
    assert data["my_rank"] == 2
    assert data["my_elapsed_time"] == 200


def test_segment_detail_top20_filters_private(client, db, test_user, auth_header):
    """TOP20 路径（GET /api/segments/{id}）也按隐私过滤。

    本人 + 4 个他人骑过同赛段；第 2 个他人设私密。
    - 未登录看 GET /api/segments/{id}：TOP20 共 4 条（私密消失）/ rank 1-2-3-4 连续
    - 本人看 GET /api/segments/{id}：TOP20 共 5 条（含自己 + 含其他人非私密；不含他人私密）
    """
    seg_id = _insert_segment(db)
    # 本人骑行
    my_act_id = _insert_activity(db, test_user.id, "我的骑行")
    _insert_effort(db, seg_id, my_act_id, test_user.id, elapsed_time=250)
    # 4 个他人骑行（其中第 2 个私密）
    others = [User(openid=f"top20_other_{i}") for i in range(4)]
    db.add_all(others)
    db.commit()
    for u in others:
        db.refresh(u)
    other_activity_ids = [_insert_activity(db, u.id, f"他骑{i}") for i, u in enumerate(others)]
    times = [100, 200, 300, 400]
    for u, aid, t in zip(others, other_activity_ids, times):
        _insert_effort(db, seg_id, aid, u.id, elapsed_time=t)
    # 第 2 个他人（elapsed_time=200）设私密
    db.add(ActivityPrivacy(activity_id=other_activity_ids[1], visibility="private"))
    db.commit()

    # 未登录访问：私密那条消失 / 共 4 条 / rank 1-2-3-4
    resp = client.get(f"/api/segments/{seg_id}")
    data = resp.json()
    assert resp.status_code == 200
    times_in_response = [item["elapsed_time"] for item in data["leaderboard"]]
    assert times_in_response == [100, 250, 300, 400]
    assert [item["rank"] for item in data["leaderboard"]] == [1, 2, 3, 4]
    assert all(item["is_private_self"] is False for item in data["leaderboard"])

    # 本人访问：他人私密仍消失（自己没有私密）/ 共 4 条
    resp_self = client.get(f"/api/segments/{seg_id}", headers=auth_header)
    data_self = resp_self.json()
    assert resp_self.status_code == 200
    times_self = [item["elapsed_time"] for item in data_self["leaderboard"]]
    assert times_self == [100, 250, 300, 400]
    # 本人没有私密 effort，is_private_self 全 False
    assert all(item["is_private_self"] is False for item in data_self["leaderboard"])


# ==================== task-4.2：按人去重 + activity_id ====================

def test_leaderboard_dedupes_by_user(client, db, test_user, auth_header):
    """同一人骑 3 次同赛段，榜上只显示最快那次 / total = 1 而非 3。"""
    seg_id = _insert_segment(db)
    # 同一用户 3 条 effort，3 个不同 activity
    times = [180, 120, 240]  # 中间那条最快
    for t in times:
        aid = _insert_activity(db, test_user.id, f"骑行 elapsed={t}")
        _insert_effort(db, seg_id, aid, test_user.id, elapsed_time=t)

    resp = client.get(f"/api/segments/{seg_id}/leaderboard", headers=auth_header)
    data = resp.json()

    assert resp.status_code == 200
    assert data["total"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["user_id"] == test_user.id
    assert data["items"][0]["elapsed_time"] == 120  # 最快那条


def test_leaderboard_returns_activity_id(client, db, test_user, auth_header):
    """每行带 activity_id，对应最快那次的 activity（前端 task-4.4 用来跳转）。"""
    seg_id = _insert_segment(db)
    slow_act = _insert_activity(db, test_user.id, "慢骑")
    fast_act = _insert_activity(db, test_user.id, "快骑")
    _insert_effort(db, seg_id, slow_act, test_user.id, elapsed_time=200)
    _insert_effort(db, seg_id, fast_act, test_user.id, elapsed_time=100)

    resp = client.get(f"/api/segments/{seg_id}/leaderboard", headers=auth_header)
    data = resp.json()

    assert resp.status_code == 200
    assert data["items"][0]["activity_id"] == fast_act  # 不是 slow_act


def test_leaderboard_total_counts_users_not_efforts(client, db):
    """5 个用户各骑 3 次 → total=5（不是 15 / 不是 effort 条数）。"""
    seg_id = _insert_segment(db)
    users = [User(openid=f"dedupe_total_{i}") for i in range(5)]
    db.add_all(users)
    db.commit()
    for u in users:
        db.refresh(u)
    for idx, u in enumerate(users):
        # 每人 3 条 effort（不同时间）
        for t in [100 + idx * 20, 200 + idx * 20, 300 + idx * 20]:
            aid = _insert_activity(db, u.id, f"u{u.id}_t{t}")
            _insert_effort(db, seg_id, aid, u.id, elapsed_time=t)

    resp = client.get(f"/api/segments/{seg_id}/leaderboard")
    data = resp.json()

    assert resp.status_code == 200
    assert data["total"] == 5
    assert len(data["items"]) == 5


def test_my_rank_counts_users_not_efforts(client, db, test_user, auth_header):
    """CCF 比我快但骑了 3 次 / 不应把我从第 2 挤到第 4。"""
    seg_id = _insert_segment(db)
    # 比我快的对手（3 条 effort 都比我快）
    faster = User(openid="faster_competitor")
    db.add(faster)
    db.commit()
    db.refresh(faster)
    for t in [80, 90, 95]:
        aid = _insert_activity(db, faster.id, f"faster_{t}")
        _insert_effort(db, seg_id, aid, faster.id, elapsed_time=t)
    # 我自己（PR = 150）
    my_act = _insert_activity(db, test_user.id, "我的")
    _insert_effort(db, seg_id, my_act, test_user.id, elapsed_time=150)

    resp = client.get(f"/api/segments/{seg_id}/leaderboard", headers=auth_header)
    data = resp.json()

    assert resp.status_code == 200
    # 比我快的"人数"= 1（faster 算 1 人不算 3 次） → my_rank = 2
    assert data["my_rank"] == 2


def test_activity_segments_rank_consistent_with_leaderboard(client, db, test_user, auth_header):
    """activity 详情里的 rank 跟主排行榜里的 rank 完全一致（都按人数算）。"""
    seg_id = _insert_segment(db)
    # 比我快的对手骑了 4 次（都比我快）
    faster = User(openid="rank_consistent_faster")
    db.add(faster)
    db.commit()
    db.refresh(faster)
    for t in [70, 75, 80, 85]:
        aid = _insert_activity(db, faster.id, f"opp_{t}")
        _insert_effort(db, seg_id, aid, faster.id, elapsed_time=t)
    # 我自己
    my_act = _insert_activity(db, test_user.id, "我的活动")
    _insert_effort(db, seg_id, my_act, test_user.id, elapsed_time=200)

    # 主榜 my_rank
    resp_board = client.get(f"/api/segments/{seg_id}/leaderboard", headers=auth_header)
    my_rank_board = resp_board.json()["my_rank"]

    # activity 详情里看 rank
    resp_act = client.get(f"/api/activities/{my_act}/segments", headers=auth_header)
    rank_in_activity = resp_act.json()["items"][0]["rank"]

    assert my_rank_board == 2
    assert rank_in_activity == 2  # 跟主榜一致 / 不是 5


def test_leaderboard_dedupe_keeps_best_effort_metadata(client, db, test_user, auth_header):
    """同人 3 条 effort（不同 created_at），榜上的 created_at + activity_id 都对应最快那条（不是最新那条）。"""
    from tests.conftest import _segment_efforts_table

    seg_id = _insert_segment(db)
    # 注意：3 条 effort 故意让"最快那条"不是时间上最新的，避免实现里悄悄用"latest"通过测试
    # 第 1 条：最早 / 中等用时 200
    aid1 = _insert_activity(db, test_user.id, "first_ride")
    db.execute(_segment_efforts_table.insert().values(
        segment_id=seg_id, activity_id=aid1, user_id=test_user.id,
        elapsed_time=200, avg_speed=30.0, avg_power=200.0,
        start_index=1, end_index=6,
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    ))
    # 第 2 条：中间 / 最快用时 100
    aid2 = _insert_activity(db, test_user.id, "second_ride_fastest")
    db.execute(_segment_efforts_table.insert().values(
        segment_id=seg_id, activity_id=aid2, user_id=test_user.id,
        elapsed_time=100, avg_speed=40.0, avg_power=250.0,
        start_index=1, end_index=6,
        created_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
    ))
    # 第 3 条：最新 / 最慢用时 300
    aid3 = _insert_activity(db, test_user.id, "third_ride_latest")
    db.execute(_segment_efforts_table.insert().values(
        segment_id=seg_id, activity_id=aid3, user_id=test_user.id,
        elapsed_time=300, avg_speed=20.0, avg_power=150.0,
        start_index=1, end_index=6,
        created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    ))
    db.commit()

    resp = client.get(f"/api/segments/{seg_id}/leaderboard", headers=auth_header)
    item = resp.json()["items"][0]

    # 榜上必须显示"最快那条"的所有元数据，不是"最新那条"
    assert item["elapsed_time"] == 100
    assert item["activity_id"] == aid2  # 不是 aid3（最新）
    assert "2024-06-01" in item["created_at"]  # 不是 2025-01-01


def test_honors_dedupes_efforts_per_user(client, db, test_user, auth_header):
    """荣誉墙 rank 跟主排行榜一致：同人多 effort 只算 1 人 + 排除他人私密 effort。"""
    seg_id = _insert_segment(db)
    # 比我快的对手 / 骑了 3 次都比我快（按老逻辑会让我从 rank=2 挤到 rank=4）
    faster = User(openid="honors_faster_dedupe")
    db.add(faster)
    db.commit()
    db.refresh(faster)
    for t in [70, 80, 90]:
        aid = _insert_activity(db, faster.id, f"honor_fast_{t}")
        _insert_effort(db, seg_id, aid, faster.id, elapsed_time=t)
    # 我自己 1 条 effort
    my_act = _insert_activity(db, test_user.id, "honors_my_ride")
    _insert_effort(db, seg_id, my_act, test_user.id, elapsed_time=120)

    resp = client.get("/api/user/honors", headers=auth_header)
    data = resp.json()

    # 我应该在 top10s 里 / rank=2（faster 算 1 人，我第 2）
    # 老逻辑 effort-based 会算 rank=4（faster 3 条 effort 都比我快）
    all_entries = data["koms"] + data["top10s"]
    assert len(all_entries) == 1
    assert all_entries[0]["rank"] == 2


def test_my_rank_matches_leaderboard_when_users_tie(client, db, test_user, auth_header):
    """不同用户同秒并列时，my_rank 跟主榜 enumerate 显示的 rank 数字完全一致（防 Codex I2 回归）。"""
    seg_id = _insert_segment(db)
    # 3 个不同用户都骑出 200s（完全并列）
    users = [User(openid=f"tie_user_{i}") for i in range(3)]
    db.add_all(users)
    db.commit()
    for u in users:
        db.refresh(u)
    for u in users:
        aid = _insert_activity(db, u.id, f"tie_{u.id}")
        _insert_effort(db, seg_id, aid, u.id, elapsed_time=200)
    # 我自己也骑 200s（也参与并列）
    my_act = _insert_activity(db, test_user.id, "tie_mine")
    _insert_effort(db, seg_id, my_act, test_user.id, elapsed_time=200)

    resp = client.get(f"/api/segments/{seg_id}/leaderboard", headers=auth_header)
    data = resp.json()

    # 主榜里我的 rank（找到 item.user_id==me 那行）
    my_row_in_board = next(item for item in data["items"] if item["user_id"] == test_user.id)
    # my_rank 字段（独立计算路径）
    assert data["my_rank"] == my_row_in_board["rank"]
    # total = 4 个不同的人
    assert data["total"] == 4


def test_segment_detail_top20_dedupes_too(client, db, test_user, auth_header):
    """TOP20 路径（GET /api/segments/{id}）也按人去重。"""
    seg_id = _insert_segment(db)
    # 我骑了 2 次
    for t in [150, 200]:
        aid = _insert_activity(db, test_user.id, f"mine_{t}")
        _insert_effort(db, seg_id, aid, test_user.id, elapsed_time=t)
    # 别人骑了 2 次（其中一次比我所有都快）
    other = User(openid="top20_dedupe_other")
    db.add(other)
    db.commit()
    db.refresh(other)
    for t in [100, 130]:
        aid = _insert_activity(db, other.id, f"other_{t}")
        _insert_effort(db, seg_id, aid, other.id, elapsed_time=t)

    resp = client.get(f"/api/segments/{seg_id}", headers=auth_header)
    data = resp.json()

    assert resp.status_code == 200
    # 一共 2 人 / TOP20 应该 2 行
    assert len(data["leaderboard"]) == 2
    # 第 1 名是 other 的 100 / 第 2 名是 test_user 的 150
    assert data["leaderboard"][0]["elapsed_time"] == 100
    assert data["leaderboard"][1]["elapsed_time"] == 150


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


def test_18_activity_segments_other_user_default_public(client, db, test_user, auth_header):
    """查看别人活动的途经赛段，默认公开 → 200（task-4.1 更新产品契约）。

    task-4.1 之前：他人 activity 一律 403。
    task-4.1 之后：activity 默认公开，他人能看到 segments。
    若 owner 设私密 → endpoint 返回 404（不存在）。
    """
    from app.user.models import User
    other_user = User(openid="other_user_segments")
    db.add(other_user)
    db.commit()
    db.refresh(other_user)

    act_id = _insert_activity(db, other_user.id, "别人的骑行")

    resp = client.get(f"/api/activities/{act_id}/segments", headers=auth_header)
    assert resp.status_code == 200


def test_19_activity_segments_not_found(client, auth_header):
    """活动不存在 → 404"""
    resp = client.get("/api/activities/99999/segments", headers=auth_header)
    assert resp.status_code == 404


def test_20_segment_detail_not_found(client):
    """赛段详情不存在 → 404"""
    resp = client.get("/api/segments/99999")
    assert resp.status_code == 404


# ==================== task-4.3：我在某赛段的所有成绩 ====================

def test_my_efforts_returns_only_self(client, db, test_user, auth_header):
    """别人 3 条 + 我 2 条 → 接口只返我的 2 条。"""
    seg_id = _insert_segment(db)
    other = User(openid="my_efforts_other")
    db.add(other)
    db.commit()
    db.refresh(other)
    # 别人 3 条
    for t in [80, 90, 100]:
        aid = _insert_activity(db, other.id, f"other_{t}")
        _insert_effort(db, seg_id, aid, other.id, elapsed_time=t)
    # 我 2 条
    for t in [150, 200]:
        aid = _insert_activity(db, test_user.id, f"mine_{t}")
        _insert_effort(db, seg_id, aid, test_user.id, elapsed_time=t)

    resp = client.get(f"/api/segments/{seg_id}/my-efforts", headers=auth_header)
    data = resp.json()

    assert resp.status_code == 200
    assert len(data["items"]) == 2
    assert all(it["elapsed_time"] in [150, 200] for it in data["items"])


def test_my_efforts_ordered_by_created_at_desc(client, db, test_user, auth_header):
    """最新骑的在前（跟图 1 一致）。"""
    from tests.conftest import _segment_efforts_table

    seg_id = _insert_segment(db)
    # 3 条 effort，故意让 created_at 顺序跟 elapsed_time 顺序不同
    cases = [
        ("ride_2024_jan", 100, datetime(2024, 1, 1, tzinfo=timezone.utc)),
        ("ride_2025_jun", 200, datetime(2025, 6, 1, tzinfo=timezone.utc)),
        ("ride_2024_dec", 150, datetime(2024, 12, 1, tzinfo=timezone.utc)),
    ]
    for title, t, created in cases:
        aid = _insert_activity(db, test_user.id, title)
        db.execute(_segment_efforts_table.insert().values(
            segment_id=seg_id, activity_id=aid, user_id=test_user.id,
            elapsed_time=t, avg_speed=30.0, avg_power=200.0,
            start_index=1, end_index=6,
            created_at=created,
        ))
    db.commit()

    resp = client.get(f"/api/segments/{seg_id}/my-efforts", headers=auth_header)
    data = resp.json()

    times = [it["elapsed_time"] for it in data["items"]]
    # 期望顺序：2025-06(200) / 2024-12(150) / 2024-01(100)
    assert times == [200, 150, 100]


def test_my_efforts_is_pr_marks_fastest(client, db, test_user, auth_header):
    """3 条 [150/100/200]，is_pr=true 只在 100 那条上。"""
    seg_id = _insert_segment(db)
    for t in [150, 100, 200]:
        aid = _insert_activity(db, test_user.id, f"pr_{t}")
        _insert_effort(db, seg_id, aid, test_user.id, elapsed_time=t)

    resp = client.get(f"/api/segments/{seg_id}/my-efforts", headers=auth_header)
    data = resp.json()

    pr_items = [it for it in data["items"] if it["is_pr"]]
    assert len(pr_items) == 1
    assert pr_items[0]["elapsed_time"] == 100


def test_my_efforts_empty_when_no_effort(client, db, test_user, auth_header):
    """我没骑过这条赛段 → 返 200 + items=[]。"""
    seg_id = _insert_segment(db)

    resp = client.get(f"/api/segments/{seg_id}/my-efforts", headers=auth_header)

    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_my_efforts_segment_not_found(client, auth_header):
    """不存在的赛段 → 404（不是 200 []）。"""
    resp = client.get("/api/segments/99999/my-efforts", headers=auth_header)
    assert resp.status_code == 404


def test_my_efforts_requires_auth(client, db):
    """无 token → 401（这是"我的数据"，不能匿名）。"""
    seg_id = _insert_segment(db)
    resp = client.get(f"/api/segments/{seg_id}/my-efforts")
    assert resp.status_code == 401


def test_my_efforts_is_pr_tiebreaker(client, db, test_user, auth_header):
    """2 条都 100s（不同 id），is_pr 只标 id 最小那条（跟主榜 task-4.2 tiebreaker 一致）。"""
    seg_id = _insert_segment(db)
    aid1 = _insert_activity(db, test_user.id, "tie_first")
    _insert_effort(db, seg_id, aid1, test_user.id, elapsed_time=100)
    aid2 = _insert_activity(db, test_user.id, "tie_second")
    _insert_effort(db, seg_id, aid2, test_user.id, elapsed_time=100)

    resp = client.get(f"/api/segments/{seg_id}/my-efforts", headers=auth_header)
    data = resp.json()

    pr_items = [it for it in data["items"] if it["is_pr"]]
    assert len(pr_items) == 1
    # 第一条 effort (aid1 对应的) 的 segment_efforts.id 更小，应被标 PR
    assert pr_items[0]["activity_id"] == aid1
