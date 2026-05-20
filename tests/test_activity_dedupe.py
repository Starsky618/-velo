"""
GPX dedupe 算法单测（Sprint 5 task-2 Day 1）。

纯函数测 / 不连 DB / 全在 ActivitySig + ActivityScoreData 层。
覆盖：haversine 精度 / 4 维比对各维度短路 / 容差边界 / score 公式。
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.activity.dedupe import (
    ActivityScoreData,
    ActivitySig,
    compute_completeness_score,
    haversine_meters,
    is_potential_duplicate,
)


# ============================================================
# haversine 精度测试
# ============================================================


def test_haversine_zero_distance_same_point():
    """同一点距离 = 0。"""
    p = (39.9042, 116.4074)  # 北京天安门
    assert haversine_meters(p, p) == pytest.approx(0, abs=0.01)


def test_haversine_known_distance_beijing_shanghai():
    """北京天安门 → 上海外滩 ≈ 1067 km（球面大圆距离 / 已知基准）。"""
    beijing_tiananmen = (39.9042, 116.4074)
    shanghai_bund = (31.2402, 121.4900)
    distance_m = haversine_meters(beijing_tiananmen, shanghai_bund)
    # 真实大圆距离约 1067 km / 容差 ±10 km（haversine 球面简化误差）
    assert 1_057_000 < distance_m < 1_077_000


def test_haversine_meters_under_100():
    """100 米尺度精度（dedupe 起点比对的真实使用范围）。"""
    p1 = (39.9042, 116.4074)
    # 经度差 0.001 度 ≈ 北京纬度上 ~85m（cos(40°) × 111km × 0.001）
    p2 = (39.9042, 116.4084)
    distance_m = haversine_meters(p1, p2)
    assert 80 < distance_m < 95  # 实测 ~85m


# ============================================================
# is_potential_duplicate 4 维测试
# ============================================================


def _make_sig(
    *,
    started_at: datetime = None,
    distance: float = 8000,
    duration: int = 1500,
    start_lat: float = 37.85,
    start_lon: float = 112.55,
) -> ActivitySig:
    """fixture helper / 默认值贴近真实太原市区骑行（activity 326 的近似数据）。"""
    if started_at is None:
        started_at = datetime(2024, 12, 21, 19, 40, 23, tzinfo=timezone.utc)
    return ActivitySig(
        started_at=started_at,
        distance=distance,
        duration=duration,
        start_lat=start_lat,
        start_lon=start_lon,
    )


def test_is_duplicate_identical_sigs_returns_true():
    """两份完全一样的签名 → 视为重复。"""
    a = _make_sig()
    b = _make_sig()
    assert is_potential_duplicate(a, b) is True


def test_is_duplicate_strava_export_vs_gpx_realistic_drift():
    """模拟真实场景：Strava 同步 vs 用户后传 GPX，4 维都有微小漂移但全在容差内。"""
    a = _make_sig()  # Strava 同步那条
    b = _make_sig(
        started_at=a.started_at + timedelta(seconds=15),  # GPS 时钟漂 15s
        distance=a.distance + 47,                          # 累计误差 47m
        duration=a.duration + 8,                           # 开停差 8s
        start_lat=a.start_lat + 0.0005,                   # 起点漂 ~55m
        start_lon=a.start_lon + 0.0001,
    )
    assert is_potential_duplicate(a, b) is True


def test_is_duplicate_time_just_over_5min_returns_false():
    """时间差 5 分钟 + 1 秒 → 视为不同骑行（第 1 维短路）。"""
    a = _make_sig()
    b = _make_sig(started_at=a.started_at + timedelta(seconds=301))
    assert is_potential_duplicate(a, b) is False


def test_is_duplicate_distance_over_tolerance_returns_false():
    """距离差 101m → 不同骑行（第 2 维短路）。"""
    a = _make_sig()
    b = _make_sig(distance=a.distance + 101)
    assert is_potential_duplicate(a, b) is False


def test_is_duplicate_duration_over_tolerance_returns_false():
    """时长差 61s → 不同骑行（第 3 维短路）。"""
    a = _make_sig()
    b = _make_sig(duration=a.duration + 61)
    assert is_potential_duplicate(a, b) is False


def test_is_duplicate_start_point_far_returns_false():
    """起点差 ~150m → 不同骑行（第 4 维短路）。"""
    a = _make_sig()
    # 经度差 0.0017 度 ≈ 北京纬度 ~145m / 太原纬度差不多
    b = _make_sig(start_lon=a.start_lon + 0.0017)
    assert is_potential_duplicate(a, b) is False


def test_is_duplicate_different_day_same_route_not_duplicate():
    """同一条赛段每周固定时间骑（同起点 / 同距离 / 同时长 / 但不同日）→ 不重复。"""
    a = _make_sig()
    b = _make_sig(started_at=a.started_at + timedelta(days=7))
    assert is_potential_duplicate(a, b) is False


def test_is_duplicate_two_friends_same_time_different_route_not_duplicate():
    """两人同时间起骑但去不同地方 → 不重复（第 4 维起点距离短路）。"""
    a = _make_sig(start_lat=37.85, start_lon=112.55)  # 太原市区
    b = _make_sig(start_lat=39.90, start_lon=116.40)  # 北京（同时间起）
    assert is_potential_duplicate(a, b) is False


def test_is_duplicate_custom_tolerance_tighter():
    """caller 可调容差 / 赛事场景紧 / 同样 sigs 用更严容差被判不重复。"""
    a = _make_sig()
    b = _make_sig(distance=a.distance + 80)  # 80m 默认容差内
    assert is_potential_duplicate(a, b) is True
    # 紧容差 50m 不通过（注意：8km 骑行百分比维度才 40m，max(50, 40) = 50m 仍为严格上限）
    assert is_potential_duplicate(a, b, distance_tol_m=50) is False


def test_is_duplicate_long_distance_dynamic_tolerance():
    """长距离骑行（161km）距离差 519m 应判重复 —— 2026-05-20 真用回扫实证修复。

    场景：user_id=2 的 id=1（NULL data_source / 161.44km）vs id=151（Strava / 160.92km），
    起骑时间秒级一致 / 距离差 519m。
    旧固定 100m 容差漏判 / 新动态容差 = max(100, 161180 × 0.005 = 806m) = 806m → True。
    """
    started = datetime(2024, 7, 2, 23, 22, 23, tzinfo=timezone.utc)
    a = _make_sig(started_at=started, distance=161_440, duration=46_359)
    b = _make_sig(started_at=started, distance=160_921, duration=46_359)
    assert is_potential_duplicate(a, b) is True


def test_is_duplicate_long_distance_beyond_dynamic_tolerance():
    """长距离骑行距离差超过动态容差 → 仍判不重复（容差不是无限放宽）。"""
    started = datetime(2024, 7, 2, 23, 22, 23, tzinfo=timezone.utc)
    a = _make_sig(started_at=started, distance=161_000, duration=46_359)
    b = _make_sig(started_at=started, distance=162_500, duration=46_359)
    # 161750 × 0.005 = 808m / 距离差 1500m > 808m → False
    assert is_potential_duplicate(a, b) is False


def test_is_duplicate_distance_pct_zero_falls_back_to_fixed():
    """显式关闭百分比容差（赛事严格场景）→ 退化成纯固定阈值。"""
    started = datetime(2024, 7, 2, 23, 22, 23, tzinfo=timezone.utc)
    a = _make_sig(started_at=started, distance=161_000, duration=46_359)
    b = _make_sig(started_at=started, distance=161_300, duration=46_359)
    # 关闭百分比 → max(100, 0) = 100m / 距离差 300m > 100m → False
    assert is_potential_duplicate(a, b, distance_tol_pct=0) is False
    # 默认开启 → max(100, 161150 × 0.005 = 806m) = 806m / 300m < 806m → True
    assert is_potential_duplicate(a, b) is True


# ============================================================
# compute_completeness_score 测试
# ============================================================


def test_score_all_none_zero_trackpoint_returns_zero():
    """无传感器 + 无 trackpoint → 0 分。"""
    d = ActivityScoreData()
    assert compute_completeness_score(d) == 0.0


def test_score_full_sensors_max_density_caps_at_8():
    """三传感器全有 + 5000+ 数据点 → 3 + 5 = 8 分（trackpoint 封顶 5）。"""
    d = ActivityScoreData(
        avg_power=180.0,
        avg_hr=145.0,
        avg_cadence=85.0,
        trackpoint_count=10000,  # 远超 5000，应被 cap
    )
    assert compute_completeness_score(d) == pytest.approx(8.0)


def test_score_only_trackpoint_density():
    """无传感器 + 1500 点 → 0 + 1.5 = 1.5。"""
    d = ActivityScoreData(trackpoint_count=1500)
    assert compute_completeness_score(d) == pytest.approx(1.5)


def test_score_strava_vs_plain_gpx_strava_wins():
    """Strava 同步（带传感器 + 4000 点）vs 纯 GPX（只轨迹 + 800 点）→ Strava 高分。"""
    strava = ActivityScoreData(
        avg_power=200.0,
        avg_hr=150.0,
        avg_cadence=88.0,
        trackpoint_count=4000,
    )
    plain_gpx = ActivityScoreData(trackpoint_count=800)
    assert compute_completeness_score(strava) > compute_completeness_score(plain_gpx)
    # 具体值：Strava = 3 + 4.0 = 7.0; plain = 0 + 0.8 = 0.8
    assert compute_completeness_score(strava) == pytest.approx(7.0)
    assert compute_completeness_score(plain_gpx) == pytest.approx(0.8)


def test_score_partial_sensors_fit_with_power_only():
    """FIT 文件只带功率（无心率、无踏频）+ 2000 点 → 1 + 2.0 = 3.0。"""
    d = ActivityScoreData(avg_power=180.0, trackpoint_count=2000)
    assert compute_completeness_score(d) == pytest.approx(3.0)
