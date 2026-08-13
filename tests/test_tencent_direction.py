"""腾讯地图路线规划客户端测试：不打真实网络，只验证签名、解码和响应解析。"""

import pytest

from app.config import settings
from app.route_book.tencent_direction import (
    _TENCENT_DIRECTION_PATH,
    _build_sig,
    _decode_polyline,
    plan_tencent_bicycling_route,
)


def test_build_sig_sorts_params_and_appends_secret_key():
    params = {
        "to": "39.2,116.3",
        "key": "test-key",
        "output": "json",
        "from": "39.1,116.2",
    }

    assert _build_sig(_TENCENT_DIRECTION_PATH, params, "test-sk") == "25fa2a54233b7e0f61780994ec58c669"


def test_decode_polyline_expands_delta_points():
    points = _decode_polyline([39.1, 116.2, 100000, 200000, -50000, 10000])

    assert points[0] == {"lat": 39.1, "lon": 116.2}
    assert points[1] == {"lat": 39.2, "lon": 116.4}
    assert points[2]["lat"] == pytest.approx(39.15)
    assert points[2]["lon"] == pytest.approx(116.41)


def test_plan_tencent_bicycling_route_parses_response(monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "status": 0,
                "result": {
                    "routes": [
                        {
                            "distance": 6800,
                            "duration": 1800,
                            "polyline": [37.8, 112.5, 100000, 100000],
                            "steps": [
                                {
                                    "road_name": "测试路",
                                    "distance": 6800,
                                    "instruction": "沿测试路行驶",
                                    "act_desc": "直行",
                                }
                            ],
                        }
                    ]
                },
            }

    def fake_get(url, params, timeout):
        captured["url"] = url
        captured["params"] = params
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(settings, "TENCENT_MAP_KEY", "test-key")
    monkeypatch.setattr(settings, "TENCENT_MAP_SK", "test-sk")
    monkeypatch.setattr("app.route_book.tencent_direction.httpx.get", fake_get)

    result = plan_tencent_bicycling_route((37.8, 112.5), (37.9, 112.6))

    assert captured["url"].endswith("/ws/direction/v1/bicycling/")
    assert captured["params"]["from"] == "37.8,112.5"
    assert captured["params"]["to"] == "37.9,112.6"
    assert captured["params"]["key"] == "test-key"
    assert captured["params"]["sig"]
    assert captured["timeout"] == 8.0
    assert result["distance"] == 6800.0
    assert result["duration"] == 1800
    assert result["points"] == [
        {"lat": 37.8, "lon": 112.5},
        {"lat": 37.9, "lon": 112.6},
    ]
    assert result["steps"] == [
        {
            "road_name": "测试路",
            "distance_m": 6800.0,
            "instruction": "沿测试路行驶",
            "act_desc": "直行",
        }
    ]


def test_plan_tencent_route_rejects_invalid_step_distance(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "status": 0,
                "result": {
                    "routes": [
                        {
                            "distance": 100,
                            "duration": 60,
                            "polyline": [37.8, 112.5, 1000, 1000],
                            "steps": [{"road_name": "坏账", "distance": "nan"}],
                        }
                    ]
                },
            }

    monkeypatch.setattr(settings, "TENCENT_MAP_KEY", "test-key")
    monkeypatch.setattr(settings, "TENCENT_MAP_SK", "test-sk")
    monkeypatch.setattr("app.route_book.tencent_direction.httpx.get", lambda *args, **kwargs: FakeResponse())

    with pytest.raises(ValueError, match="道路步骤距离异常"):
        plan_tencent_bicycling_route((37.8, 112.5), (37.9, 112.6))
