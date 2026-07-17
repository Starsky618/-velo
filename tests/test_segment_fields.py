"""赛段字段测试：所有入口都消费统一的 GLO-30 成品海拔链。"""

import pytest

from app.elevation.route_elevation import build_route_elevation_result
from app.segment._geo_utils import _haversine


def _glo_query(points, dem_url=None):
    """按固定 20m 查询网格长度返回可重复的先升后降剖面。"""
    if not points:
        return []
    denominator = max(len(points) - 1, 1)
    elevations = []
    for index in range(len(points)):
        ratio = index / denominator
        if ratio <= 0.6:
            elevation = 800.0 + 100.0 * ratio / 0.6
        else:
            elevation = 900.0 - 50.0 * (ratio - 0.6) / 0.4
        elevations.append(elevation)
    return elevations


def _expected_result(reference_points, query_func=_glo_query):
    return build_route_elevation_result(
        [[point["lon"], point["lat"]] for point in reference_points],
        query_func=query_func,
    )


@pytest.fixture(autouse=True)
def mock_dem(monkeypatch):
    """单测不下载 GLO 瓦片，但仍走完整的重采样、平滑和有效爬升算法。"""
    monkeypatch.setattr(
        "app.segment.service_create.query_elevations",
        _glo_query,
    )


def test_01_create_segment_new_fields(client, admin_header):
    """上传 ele 不能覆盖公共底座；四个派生字段来自同一 GLO 成品剖面。"""
    payload = {
        "name": "测试坡段",
        "reference_points": [
            {"lat": 37.87, "lon": 112.55, "ele": 800.0},
            {"lat": 37.871, "lon": 112.55, "ele": 850.0},
            {"lat": 37.872, "lon": 112.55, "ele": 900.0},
            {"lat": 37.873, "lon": 112.55, "ele": 880.0},
            {"lat": 37.874, "lon": 112.55, "ele": 850.0},
        ],
        "coordinate_system": "wgs84",
    }
    resp = client.post("/api/segments", json=payload, headers=admin_header)
    assert resp.status_code == 200
    data = resp.json()
    expected = _expected_result(payload["reference_points"])

    assert data["elevation_gain"] == expected.climb
    assert data["elevation_loss"] == expected.descent
    total_distance = sum(
        _haversine(
            previous["lat"], previous["lon"], current["lat"], current["lon"]
        )
        for previous, current in zip(
            payload["reference_points"], payload["reference_points"][1:]
        )
    )
    assert data["avg_gradient"] == round(
        (expected.snapshot[-1][2] - expected.snapshot[0][2])
        / total_distance
        * 100,
        1,
    )
    profile = data["elevation_profile"]
    assert isinstance(profile, list)
    assert profile == [point[1] for point in expected.profile]
    # 明确证明上传的 800/850/900/880/850 没有成为公共赛段剖面。
    assert profile != [800.0, 850.0, 900.0, 880.0, 850.0]


def test_02_create_segment_no_elevation(client, admin_header):
    """即使没有上传海拔，GLO 仍生成完整的预计爬升和曲线。"""
    payload = {
        "name": "无海拔赛段",
        "reference_points": [
            {"lat": 37.87, "lon": 112.55},
            {"lat": 37.875, "lon": 112.55},
        ],
        "coordinate_system": "wgs84",
    }
    resp = client.post("/api/segments", json=payload, headers=admin_header)
    assert resp.status_code == 200
    data = resp.json()
    expected = _expected_result(payload["reference_points"])

    assert data["elevation_gain"] == expected.climb
    assert data["elevation_loss"] == expected.descent
    assert data["avg_gradient"] is not None
    assert data["elevation_profile"] == [point[1] for point in expected.profile]


def test_03_create_segment_distance_precision(client, admin_header):
    """距离精度应为 2 位小数。"""
    payload = {
        "name": "精度测试",
        "reference_points": [
            {"lat": 37.87, "lon": 112.55},
            {"lat": 37.875, "lon": 112.55},
        ],
        "coordinate_system": "wgs84",
    }
    resp = client.post("/api/segments", json=payload, headers=admin_header)
    data = resp.json()
    dist_str = str(data["distance"])
    if "." in dist_str:
        decimal_places = len(dist_str.split(".")[1])
        assert decimal_places <= 2


def test_04_flat_segment_zero_gradient(client, admin_header, monkeypatch):
    """完全平坦的赛段，坡度应为 0。"""
    monkeypatch.setattr(
        "app.segment.service_create.query_elevations",
        lambda points, dem_url=None: [800.0 for _ in points],
    )
    payload = {
        "name": "平坦赛段",
        "reference_points": [
            {"lat": 37.87, "lon": 112.55, "ele": 800.0},
            {"lat": 37.871, "lon": 112.55, "ele": 800.0},
            {"lat": 37.872, "lon": 112.55, "ele": 800.0},
        ],
        "coordinate_system": "wgs84",
    }
    resp = client.post("/api/segments", json=payload, headers=admin_header)
    data = resp.json()

    # 海拔无变化：爬升=0，下降=0，坡度=0
    assert data["elevation_gain"] == 0.0
    assert data["elevation_loss"] == 0.0
    assert data["avg_gradient"] == 0.0
