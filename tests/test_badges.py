"""徽章规则纯函数测试 — Sprint 6 task-2。

测试范围：
- app.user.badges.compute_badges 纯函数（不碰 DB / mock-free）
- 覆盖 5 种徽章规则 + 优先级 + top 3 限制 + 边界 + 性能

为什么不混进 test_user_service_remaining.py：
- compute_badges 是纯函数 / 测试只需 dict 输入 / 不需要 DB fixture
- 单独成文件让"换徽章规则"时只改这一处 / 不会影响 service 层测试

类比：把"奖项评定规则"测试和"档案管理系统"测试分开放——
评定规则改了只动评定卷宗，档案系统不受影响。
"""

import time

from app.user.badges import (
    BADGE_TYPE_CITY_LOCAL,
    BADGE_TYPE_DISTANCE,
    BADGE_TYPE_ELEVATION,
    BADGE_TYPE_FTP,
    BADGE_TYPE_REGULAR_MOUNTAIN,
    REGULAR_MOUNTAIN_THRESHOLD,
    compute_badges,
)


# ─────────────────────────────────────────────────────────────────────
# case 1: FTP + 累计里程组合
# ─────────────────────────────────────────────────────────────────────


def test_ftp_220_distance_8500km_returns_ftp_plus_distance_8000():
    """case 1：FTP=220 / distance 8500km → 含 FTP 220W + 累计 8000km。"""
    badges = compute_badges(
        ftp=220,
        total_distance_m=8_500_000,  # 8500km
        total_elevation_m=0,
        city=None,
        top_segments=[],
    )
    types = [b["type"] for b in badges]
    labels = [b["label"] for b in badges]
    assert BADGE_TYPE_FTP in types
    assert BADGE_TYPE_DISTANCE in types
    assert "FTP 220W" in labels
    assert "累计 8000km" in labels  # 8500km 命中 8000 阶梯（不是 10000+）


# ─────────────────────────────────────────────────────────────────────
# case 2: 全空输入
# ─────────────────────────────────────────────────────────────────────


def test_no_data_returns_empty_list():
    """case 2：用户无活动 / ftp NULL / city NULL → []。"""
    badges = compute_badges(
        ftp=None,
        total_distance_m=0,
        total_elevation_m=0,
        city=None,
        top_segments=[],
    )
    assert badges == []


# ─────────────────────────────────────────────────────────────────────
# case 3, 4: 山名常客阈值
# ─────────────────────────────────────────────────────────────────────


def test_regular_mountain_6_times_returns_badge():
    """case 3：雀儿山骑过 6 次（≥ 5 阈值）→ 含"雀儿山常客"。"""
    badges = compute_badges(
        ftp=None,
        total_distance_m=0,
        total_elevation_m=0,
        city=None,
        top_segments=[{"segment_id": 7, "segment_name": "雀儿山", "count": 6}],
    )
    assert len(badges) == 1
    assert badges[0]["type"] == BADGE_TYPE_REGULAR_MOUNTAIN
    assert badges[0]["label"] == "雀儿山常客"


def test_regular_mountain_4_times_below_threshold_not_returned():
    """case 4：雀儿山骑过 4 次（< 5 阈值）→ 不含常客徽章。"""
    badges = compute_badges(
        ftp=None,
        total_distance_m=0,
        total_elevation_m=0,
        city=None,
        top_segments=[{"segment_id": 7, "segment_name": "雀儿山", "count": 4}],
    )
    assert badges == []
    # 顺便锁阈值常量 = 5（防止未来手滑改成 3 / 10 等而本测试默默失效）
    assert REGULAR_MOUNTAIN_THRESHOLD == 5


# ─────────────────────────────────────────────────────────────────────
# case 5: 5 维度全有 → 只返 top 3（按优先级 FTP > 山 > 距离 > 爬升 > 城市）
# ─────────────────────────────────────────────────────────────────────


def test_all_five_dimensions_returns_top_3_by_priority():
    """case 5：FTP + 山 + 累计里程 + 爬升 + 城市 5 维都有 → top 3 = FTP / 山 / 距离。"""
    badges = compute_badges(
        ftp=240,
        total_distance_m=10_000_000,  # 10000km+
        total_elevation_m=100_000,     # 100000m+
        city="chengdu",
        top_segments=[{"segment_id": 3, "segment_name": "二郎山", "count": 8}],
    )
    assert len(badges) == 3
    types = [b["type"] for b in badges]
    assert types == [
        BADGE_TYPE_FTP,
        BADGE_TYPE_REGULAR_MOUNTAIN,
        BADGE_TYPE_DISTANCE,
    ], f"top 3 顺序应该是 FTP > 山 > 距离 / 实际：{types}"
    # 爬升 / 城市本地 被截断
    assert BADGE_TYPE_ELEVATION not in types
    assert BADGE_TYPE_CITY_LOCAL not in types


# ─────────────────────────────────────────────────────────────────────
# case 7: 山名并列频次 → segment_id 小者优先（稳定排序）
# ─────────────────────────────────────────────────────────────────────


def test_regular_mountain_tied_count_picks_smaller_segment_id():
    """case 7：两座山频次都 = 5 → 取 segment_id 小的（更早入库 = 用户骑得最久）。"""
    badges = compute_badges(
        ftp=None,
        total_distance_m=0,
        total_elevation_m=0,
        city=None,
        top_segments=[
            {"segment_id": 50, "segment_name": "B 山", "count": 5},
            {"segment_id": 7, "segment_name": "A 山", "count": 5},   # 应被选中
            {"segment_id": 100, "segment_name": "C 山", "count": 5},
        ],
    )
    assert len(badges) == 1
    assert badges[0]["label"] == "A 山常客"


# ─────────────────────────────────────────────────────────────────────
# case 11: FTP 脏数据下界 guard（ftp < 50 不挂 / ftp = 50 挂）
# ─────────────────────────────────────────────────────────────────────


def test_ftp_10_below_50_guard_skipped():
    """case 11a：ftp=10（< 50 脏数据下界）→ 不含 FTP 徽章。"""
    badges = compute_badges(
        ftp=10,
        total_distance_m=0,
        total_elevation_m=0,
        city=None,
        top_segments=[],
    )
    types = [b["type"] for b in badges]
    assert BADGE_TYPE_FTP not in types


def test_ftp_50_at_boundary_returns_badge():
    """case 11b：ftp=50（边界 / 与 schemas.UserProfileUpdate.ftp ge=50 一致）→ 含 FTP 50W。"""
    badges = compute_badges(
        ftp=50,
        total_distance_m=0,
        total_elevation_m=0,
        city=None,
        top_segments=[],
    )
    types = [b["type"] for b in badges]
    assert BADGE_TYPE_FTP in types
    assert badges[0]["label"] == "FTP 50W"


# ─────────────────────────────────────────────────────────────────────
# 城市本地徽章 — VALID_CITY_CODES 守卫
# ─────────────────────────────────────────────────────────────────────


def test_city_unknown_not_treated_as_local():
    """city='unknown' → 不挂本地徽章（unknown 是兜底值 / 不是真城市）。"""
    badges = compute_badges(
        ftp=None,
        total_distance_m=0,
        total_elevation_m=0,
        city="unknown",
        top_segments=[],
    )
    assert badges == []


def test_city_chengdu_returns_local_badge():
    """city='chengdu' → 含"成都"本地徽章（Tim 2026-05-16 真用拍裸字 / 不加"骑友"后缀）。"""
    badges = compute_badges(
        ftp=None,
        total_distance_m=0,
        total_elevation_m=0,
        city="chengdu",
        top_segments=[],
    )
    assert len(badges) == 1
    assert badges[0]["type"] == BADGE_TYPE_CITY_LOCAL
    assert badges[0]["label"] == "成都"


# ─────────────────────────────────────────────────────────────────────
# 阶梯防御：负数 / 0
# ─────────────────────────────────────────────────────────────────────


def test_negative_distance_no_badge():
    """累计 distance = -100（脏数据）→ 不挂里程徽章 / 不抛异常。"""
    badges = compute_badges(
        ftp=None,
        total_distance_m=-100,
        total_elevation_m=-100,
        city=None,
        top_segments=[],
    )
    assert badges == []


# ─────────────────────────────────────────────────────────────────────
# 输出 schema 守卫：仅 type + label / 无 priority 内部字段
# ─────────────────────────────────────────────────────────────────────


def test_output_strips_internal_priority_field():
    """compute_badges 输出每个 badge 只含 type / label / 不暴露内部 priority 字段。"""
    badges = compute_badges(
        ftp=200,
        total_distance_m=1_000_000,
        total_elevation_m=5_000,
        city="beijing",
        top_segments=[],
    )
    for b in badges:
        assert set(b.keys()) == {"type", "label"}, (
            f"badge 字段应只有 type / label / 实际：{set(b.keys())}"
        )


# ─────────────────────────────────────────────────────────────────────
# case 8: 性能 — 100 条 top_segments 输入 → 单次 compute_badges < 50ms
# ─────────────────────────────────────────────────────────────────────


def test_performance_100_segments_under_50ms():
    """case 8：100 条 top_segments 输入 / 5 维全有 → 单次 < 50ms。

    注：完整聚合（含 SQL 100 activities）的 < 200ms 由 service 层集成测试覆盖，
    这里只锁纯函数 compute_badges 性能层（防未来加复杂规则时悄悄拖慢）。
    """
    top_segments = [
        {"segment_id": i, "segment_name": f"山 {i}", "count": (i % 10) + 1}
        for i in range(100)
    ]
    start = time.perf_counter()
    for _ in range(100):  # 跑 100 次取平均稳定一些
        compute_badges(
            ftp=220,
            total_distance_m=8_500_000,
            total_elevation_m=50_000,
            city="chengdu",
            top_segments=top_segments,
        )
    elapsed_ms = (time.perf_counter() - start) * 1000 / 100  # 每次平均 ms
    assert elapsed_ms < 50, f"compute_badges 100 segments 单次 {elapsed_ms:.2f}ms > 50ms"
