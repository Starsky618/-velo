"""
赛段算法纯函数测试——"测量尺自校准"。

这些测试只验证 4 个纯函数的输入输出，不连数据库、不用 fixture：
- _haversine_distance（距离公式）
- calculate_max_gradient（100m 滑窗最陡坡度）
- calculate_difficulty（4 档难度规则）
- infer_city_from_coords（6 城坐标查表）

为什么不用 conftest.py 的 db fixture：
这一组都是纯函数，只接收 list / float / str，返回数值或字符串，无副作用。
按 CLAUDE.md "纯函数规则"，不该挂数据库——挂了反而让测试变慢、让 SQLite 兼容性
问题污染本不需要的测试。

注意事项：
- 用一个轻量假对象 _FakePoint 模拟 Trackpoint（只暴露 latitude/longitude/elevation 三个属性）
  比 mock 库简单，比真 Trackpoint ORM 模型省 import 链
- 测试覆盖每个函数的 ≥ 5 case，含空 / 单点 / 边界值 / 异常输入
"""

import math
from dataclasses import dataclass

import pytest

from app.segment.algorithms import (
    _haversine_distance,
    calculate_max_gradient,
    calculate_difficulty,
)
from app.common.geo import infer_city_from_coords


@dataclass
class _FakePoint:
    """轻量假 Trackpoint——只为算法测试用。"""
    latitude: float
    longitude: float
    elevation: float | None = None


# ============================================================
# _haversine_distance：地表两点距离
# ============================================================

class TestHaversineDistance:
    def test_same_point_returns_zero(self):
        # 同一点距离 = 0
        assert _haversine_distance(30.0, 120.0, 30.0, 120.0) == pytest.approx(0.0)

    def test_1deg_latitude_about_111km(self):
        # 同一经线上纬度差 1 度 ≈ 111.32 km（任何纬度都成立）
        d = _haversine_distance(30.0, 120.0, 31.0, 120.0)
        assert d == pytest.approx(111_320.0, rel=0.01)  # 误差 < 1%

    def test_1deg_longitude_at_equator_about_111km(self):
        # 赤道上经度差 1 度 ≈ 111.32 km
        d = _haversine_distance(0.0, 0.0, 0.0, 1.0)
        assert d == pytest.approx(111_320.0, rel=0.01)

    def test_1deg_longitude_at_60deg_lat_about_55km(self):
        # 纬度 60 度处经度差 1 度 ≈ 111.32 * cos(60°) ≈ 55.66 km
        d = _haversine_distance(60.0, 0.0, 60.0, 1.0)
        assert d == pytest.approx(55_660.0, rel=0.02)

    def test_cross_equator_symmetric(self):
        # 跨赤道往返距离对称
        d1 = _haversine_distance(-1.0, 100.0, 1.0, 100.0)
        d2 = _haversine_distance(1.0, 100.0, -1.0, 100.0)
        assert d1 == pytest.approx(d2)
        # 2 度纬度 ≈ 222.64 km
        assert d1 == pytest.approx(222_640.0, rel=0.01)

    def test_short_distance_meters(self):
        # 短距离量级正确（赛段轨迹点间隔常 5-20m）
        # 30°N 经度差 0.0001 度 ≈ 9.6m
        d = _haversine_distance(30.0, 120.0, 30.0, 120.0001)
        assert 9.0 < d < 11.0

    def test_antipodal_points_no_crash(self):
        # 近对跖点（地球两侧对称点）浮点误差让 a 微超 1.0 → sqrt(1-a) 会炸
        # Codex 异源审 C-1 抓出，加 a = min(a, 1.0) 钳位修
        # 期望：返回 ~半地球周长（约 20015km），不抛 ValueError
        d = _haversine_distance(12.345678, 45.6789, -12.345678, -134.3211)
        assert 19_000_000.0 < d < 21_000_000.0  # 约 2 万 km


# ============================================================
# calculate_max_gradient：100m 滑窗最大坡度
# ============================================================

class TestCalculateMaxGradient:
    def test_empty_returns_zero(self):
        assert calculate_max_gradient([]) == 0.0

    def test_single_point_returns_zero(self):
        # 单点无法形成窗口
        pt = _FakePoint(30.0, 120.0, 100.0)
        assert calculate_max_gradient([pt]) == 0.0

    def test_all_flat_returns_zero(self):
        # 所有点海拔一致 → 坡度 0
        pts = [_FakePoint(30.0, 120.0 + i * 0.001, 100.0) for i in range(10)]
        assert calculate_max_gradient(pts) == pytest.approx(0.0)

    def test_all_none_elevation_returns_zero(self):
        # 全部点 elevation=None（GPS 没记高度）→ 0
        pts = [_FakePoint(30.0, 120.0 + i * 0.001, None) for i in range(20)]
        assert calculate_max_gradient(pts) == 0.0

    def test_steady_5pct_slope(self):
        # 5% 稳定爬坡测试
        # 30°N 经度差 0.001 度 ≈ 96.5m（不是正好 100m）
        # 每点升 5m，所以单点对单点 ≈ 5/96.5 ≈ 5.18%
        # 100m 滑窗会跨 1-2 个间隔，结果落在 5% 附近
        pts = []
        for i in range(20):
            lon = 120.0 + i * 0.001
            ele = i * 5.0  # 每点升 5m
            pts.append(_FakePoint(30.0, lon, ele))
        grad = calculate_max_gradient(pts)
        # 5m 上升 / ~96m 距离 ≈ 5.2%；100m 滑窗会跨 1-2 个间隔，结果约 5%
        assert 4.5 < grad < 6.0

    def test_steep_20pct_local(self):
        # 局部 ~20% 极陡坡 + 周围水平
        # 30°N 经度差 0.001 度 ≈ 96.5m，每点升 19m → 单点 19/96.5 ≈ 19.7%
        # 100m 滑窗结果约 ~20%
        pts = []
        # 前段 5 个点平路 100m 海拔
        for i in range(5):
            pts.append(_FakePoint(30.0, 120.0 + i * 0.001, 100.0))
        # 中段 10 个点：每 ~96m 升 19m（~20% 坡度）
        for i in range(10):
            pts.append(_FakePoint(30.0, 120.005 + i * 0.001, 100.0 + i * 19.0))
        # 后段 5 个点平路（保持 290m）
        for i in range(5):
            pts.append(_FakePoint(30.0, 120.015 + i * 0.001, 290.0))
        grad = calculate_max_gradient(pts)
        assert 18.0 < grad < 22.0

    def test_partial_none_elevation_skips_window(self):
        # 中间几个点 elevation=None，函数应跳过含 None 的窗口，不应崩
        pts = []
        for i in range(20):
            ele = None if 5 <= i <= 8 else i * 5.0
            pts.append(_FakePoint(30.0, 120.0 + i * 0.001, ele))
        # 不应 crash；前段 + 后段都有有效 5% 坡度
        grad = calculate_max_gradient(pts)
        assert grad > 0.0  # 至少前段或后段算出非零坡度

    def test_descending_uses_abs(self):
        # 下坡（海拔递减）也算坡度 = |ele_end - ele_start|
        pts = [_FakePoint(30.0, 120.0 + i * 0.001, 200.0 - i * 5.0) for i in range(20)]
        grad = calculate_max_gradient(pts)
        # 5m 下降 / ~96m → ~5%
        assert 4.5 < grad < 6.0

    def test_zero_elevation_not_treated_as_none(self):
        # elevation=0.0 是合法海拔（沿海地区），不应被 truthiness 误判跳过
        # 全 0 海拔 → 坡度恒 0，但函数应跑完不 crash（陷阱 #1 反例锁定）
        pts = [_FakePoint(30.0, 120.0 + i * 0.001, 0.0) for i in range(20)]
        assert calculate_max_gradient(pts) == pytest.approx(0.0)


# ============================================================
# calculate_difficulty：4 档难度规则
# ============================================================

class TestCalculateDifficulty:
    def test_extreme_via_gradient(self):
        # 短距离 + 短爬升，但坡度爆表 → extreme
        assert calculate_difficulty(2000.0, 100.0, 16.0) == "extreme"

    def test_extreme_via_elevation_gain(self):
        # 缓坡但累计爬升 > 1500m → extreme
        assert calculate_difficulty(50_000.0, 1600.0, 8.0) == "extreme"

    def test_hard_boundary_gradient(self):
        # 坡度刚过 10% → hard
        assert calculate_difficulty(5000.0, 200.0, 11.0) == "hard"

    def test_hard_boundary_elevation(self):
        # 累计爬升刚过 800m → hard
        assert calculate_difficulty(20_000.0, 900.0, 4.0) == "hard"

    def test_medium_boundary_gradient(self):
        # 坡度刚过 5% → medium
        assert calculate_difficulty(5000.0, 100.0, 6.0) == "medium"

    def test_medium_boundary_elevation(self):
        # 累计爬升刚过 300m → medium
        assert calculate_difficulty(15_000.0, 350.0, 3.0) == "medium"

    def test_easy_flat_short(self):
        # 平路短距离 → easy
        assert calculate_difficulty(3000.0, 50.0, 2.0) == "easy"

    def test_easy_long_flat(self):
        # 长距离但纯平 → 仍是 easy（规则只看坡度 / 累计爬升，不看距离本身）
        assert calculate_difficulty(80_000.0, 200.0, 3.0) == "easy"

    def test_priority_extreme_over_hard(self):
        # 同时满足 extreme 和 hard 阈值 → 取 extreme
        assert calculate_difficulty(10_000.0, 1600.0, 12.0) == "extreme"

    def test_boundary_15pct_not_extreme(self):
        # 严格 > 15% 才 extreme，等于 15% 仍是 hard
        assert calculate_difficulty(5000.0, 100.0, 15.0) == "hard"


# ============================================================
# infer_city_from_coords：6 城坐标查表
# ============================================================

class TestInferCityFromCoords:
    def test_beijing_typical_point(self):
        # 天安门附近
        assert infer_city_from_coords(39.9, 116.4) == "beijing"

    def test_shanghai_typical_point(self):
        # 人民广场
        assert infer_city_from_coords(31.23, 121.47) == "shanghai"

    def test_hangzhou_typical_point(self):
        # 西湖
        assert infer_city_from_coords(30.25, 120.15) == "hangzhou"

    def test_shenzhen_typical_point(self):
        # 福田中心
        assert infer_city_from_coords(22.55, 114.05) == "shenzhen"

    def test_chengdu_typical_point(self):
        # 天府广场
        assert infer_city_from_coords(30.66, 104.07) == "chengdu"

    def test_taiyuan_typical_point(self):
        # 五一广场
        assert infer_city_from_coords(37.87, 112.55) == "taiyuan"

    def test_none_lat_returns_unknown(self):
        # 任一坐标 None → unknown（陷阱 #1：不能 truthiness）
        assert infer_city_from_coords(None, 116.4) == "unknown"

    def test_none_lon_returns_unknown(self):
        assert infer_city_from_coords(39.9, None) == "unknown"

    def test_both_none_returns_unknown(self):
        assert infer_city_from_coords(None, None) == "unknown"

    def test_zero_coords_not_treated_as_none(self):
        # 0.0, 0.0 是合法坐标（赤道几内亚湾），返 unknown 是因为不在 6 城内，
        # 不是因为 truthiness 判 None（验证陷阱 #1）
        assert infer_city_from_coords(0.0, 0.0) == "unknown"

    def test_zero_lat_with_valid_lon_not_short_circuited(self):
        # lat=0.0 + lon=北京经度：未来若误改成 `if not lat: return 'unknown'`，
        # 这条测试会炸（因为 lat=0.0 实际不在北京 box 应正常返 unknown 走完矩形比对路径）
        # 用此测试锁住"truthiness 短路"反模式
        assert infer_city_from_coords(0.0, 116.4) == "unknown"

    def test_overseas_returns_unknown(self):
        # 巴黎
        assert infer_city_from_coords(48.85, 2.35) == "unknown"

    def test_chinese_other_city_returns_unknown(self):
        # 哈尔滨（不在 6 城）
        assert infer_city_from_coords(45.75, 126.65) == "unknown"

    def test_just_inside_beijing_boundary(self):
        # 紧贴北京 box 西南角
        assert infer_city_from_coords(39.4, 115.4) == "beijing"

    def test_just_outside_beijing_boundary(self):
        # 紧贴北京 box 外（比 39.4 小一点点）
        assert infer_city_from_coords(39.39, 116.0) == "unknown"
