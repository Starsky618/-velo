"""
坐标转换纯函数测试——验证 GCJ-02 → WGS-84 转换的正确性。

纯数学计算测试，不需要数据库，直接调函数验证输入输出。
用已知的 GCJ-02 / WGS-84 对照坐标验证精度和边界情况。

注意事项：
- 所有测试都是纯函数级别，不依赖任何 fixture
- 偏移量范围是经验值，来自 GCJ-02 在不同地区的已知偏移特征
"""

import pytest

from app.segment.coord_convert import convert_points_to_wgs84, gcj02_to_wgs84


def test_01_gcj02_to_wgs84_taiyuan():
    """
    太原市中心坐标转换：GCJ-02 → WGS-84 偏移量应在合理范围。

    太原迎泽公园附近的 GCJ-02 坐标约 (37.87, 112.55)，
    转换后 WGS-84 坐标应有偏移，
    这是 GCJ-02 在华北地区的典型偏移量。
    """
    gcj_lat, gcj_lon = 37.87, 112.55
    wgs_lat, wgs_lon = gcj02_to_wgs84(gcj_lat, gcj_lon)

    # 转换后坐标应该和原坐标不同（有偏移）
    assert wgs_lat != gcj_lat
    assert wgs_lon != gcj_lon

    # 偏移量应在合理范围：0.0001°~0.01°（约 10m~1000m）
    # 纬度偏移在华北地区约 0.0005°（~55m），经度偏移约 0.005°（~450m）
    assert 0.0001 < abs(wgs_lat - gcj_lat) < 0.01
    assert 0.001 < abs(wgs_lon - gcj_lon) < 0.01


def test_02_gcj02_to_wgs84_outside_china():
    """
    中国境外坐标不偏移：GCJ-02 在境外等于 WGS-84。

    东京的坐标 (35.68, 139.69) 不在中国范围内，
    转换结果应与输入完全一致。
    """
    lat, lon = 35.68, 139.69
    wgs_lat, wgs_lon = gcj02_to_wgs84(lat, lon)
    assert wgs_lat == lat
    assert wgs_lon == lon


def test_03_convert_points_gcj02():
    """批量转换 GCJ-02 坐标点：所有点都应被转换。"""
    points = [
        {"lat": 37.87, "lon": 112.55, "ele": 800.0},
        {"lat": 37.875, "lon": 112.55, "ele": 810.0},
    ]
    converted = convert_points_to_wgs84(points, "gcj02")

    # 转换后坐标应与原坐标不同
    assert converted[0]["lat"] != points[0]["lat"]
    assert converted[1]["lat"] != points[1]["lat"]
    # 海拔不受坐标系转换影响
    assert converted[0]["ele"] == 800.0
    assert converted[1]["ele"] == 810.0
    # 不修改原数据
    assert points[0]["lat"] == 37.87


def test_04_convert_points_wgs84_passthrough():
    """WGS-84 坐标直接跳过转换，原样返回。"""
    points = [
        {"lat": 37.87, "lon": 112.55},
        {"lat": 37.875, "lon": 112.55},
    ]
    result = convert_points_to_wgs84(points, "wgs84")
    # wgs84 模式直接返回原列表
    assert result is points


def test_05_gcj02_conversion_consistency():
    """转换一致性：同一坐标多次转换结果相同（纯函数无副作用）。"""
    lat, lon = 37.87, 112.55
    r1 = gcj02_to_wgs84(lat, lon)
    r2 = gcj02_to_wgs84(lat, lon)
    assert r1 == r2


def test_06_convert_empty_list():
    """空列表输入应返回空列表。"""
    result = convert_points_to_wgs84([], "gcj02")
    assert result == []


def test_07_invalid_coordinate_system():
    """非法坐标系参数应抛出 ValueError。"""
    points = [{"lat": 37.87, "lon": 112.55}]
    with pytest.raises(ValueError, match="不支持的坐标系"):
        convert_points_to_wgs84(points, "bd09")
