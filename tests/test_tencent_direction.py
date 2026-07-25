"""腾讯地图路线规划客户端测试：不打真实网络，只验证签名、解码和响应解析。"""

import pytest

from app.config import settings
from app.route_book.tencent_direction import (
    _TENCENT_DIRECTION_PATH,
    _build_sig,
    _decode_polyline,
    TencentMapError,
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
    assert captured["params"]["added_fields"] == "ferry_count"
    assert captured["params"]["key"] == "test-key"
    assert captured["params"]["sig"]
    assert captured["timeout"] == 8.0
    assert result["distance"] == 6800.0
    assert result["duration"] == 1800
    assert isinstance(result["duration"], int)
    assert result["points"] == [
        {"lat": 37.8, "lon": 112.5},
        {"lat": 37.9, "lon": 112.6},
    ]
    assert result["mode"] is None
    assert result["direction"] is None
    assert result["ferry_count"] is None
    assert result["request_id"] is None
    assert result["steps"] == []


def test_plan_tencent_bicycling_route_preserves_route_and_normalizes_steps(monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "status": 0,
                # request_id 不是骑行正式契约；标量类型漂移不应让有效路线失败。
                "request_id": 123,
                "result": {
                    "routes": [
                        {
                            "distance": 456,
                            "duration": 3,
                            "mode": "BICYCLING",
                            "direction": "北",
                            "ferry_count": 0,
                            "polyline": [37.8, 112.5, 1000, 1000, 1000, 1000],
                            "steps": [
                                {
                                    "instruction": "沿天清隧道骑行",
                                    "polyline_idx": [0, 3],
                                    "road_name": "天清隧道",
                                    "dir_desc": "向北",
                                    "distance": 321,
                                    "act_desc": "直行",
                                    "road_class": 0,
                                },
                                {
                                    "instruction": "驶出隧道",
                                    "polyline_idx": [4, 5],
                                    "road_name": "",
                                    "dir_desc": "向北",
                                    "distance": 135,
                                    "act_desc": "",
                                },
                            ],
                        }
                    ]
                },
            }

    def fake_get(url, params, timeout):
        captured["params"] = dict(params)
        return FakeResponse()

    monkeypatch.setattr(settings, "TENCENT_MAP_KEY", "test-key")
    monkeypatch.setattr(settings, "TENCENT_MAP_SK", "test-sk")
    monkeypatch.setattr("app.route_book.tencent_direction.httpx.get", fake_get)

    result = plan_tencent_bicycling_route(
        (37.8, 112.5),
        (37.802, 112.502),
        from_poi=" from-poi-id ",
        to_poi="to-poi-id",
    )

    unsigned_params = {key: value for key, value in captured["params"].items() if key != "sig"}
    assert captured["params"]["from_poi"] == "from-poi-id"
    assert captured["params"]["to_poi"] == "to-poi-id"
    assert captured["params"]["sig"] == _build_sig(_TENCENT_DIRECTION_PATH, unsigned_params, "test-sk")
    assert result == {
        "distance": 456.0,
        "duration": 3.0,
        "points": [
            {"lat": 37.8, "lon": 112.5},
            {"lat": pytest.approx(37.801), "lon": pytest.approx(112.501)},
            {"lat": pytest.approx(37.802), "lon": pytest.approx(112.502)},
        ],
        "mode": "BICYCLING",
        "direction": "北",
        "ferry_count": 0,
        "request_id": "123",
        "steps": [
            {
                "instruction": "沿天清隧道骑行",
                "polyline_idx": [0, 3],
                "point_start": 0,
                "point_end": 1,
                "road_name": "天清隧道",
                "dir_desc": "向北",
                "distance": 321.0,
                "act_desc": "直行",
                "road_class": 0,
            },
            {
                "instruction": "驶出隧道",
                "polyline_idx": [4, 5],
                "point_start": 2,
                "point_end": 2,
                "road_name": "",
                "dir_desc": "向北",
                "distance": 135.0,
                "act_desc": "",
                "road_class": None,
            },
        ],
    }


@pytest.mark.parametrize("field_name,bad_value", [("from_poi", ""), ("from_poi", "   "), ("to_poi", 123)])
def test_plan_tencent_bicycling_route_rejects_invalid_optional_poi(monkeypatch, field_name, bad_value):
    monkeypatch.setattr(settings, "TENCENT_MAP_KEY", "test-key")
    monkeypatch.setattr(settings, "TENCENT_MAP_SK", "test-sk")

    with pytest.raises(TencentMapError, match=f"{field_name}必须是非空字符串"):
        plan_tencent_bicycling_route(
            (37.8, 112.5),
            (37.9, 112.6),
            **{field_name: bad_value},
        )


@pytest.mark.parametrize(
    "route_patch,error_match",
    [
        ({"distance": "456"}, "distance不是有效数字"),
        ({"duration": -1}, "duration不能为负数"),
        ({"direction": 87}, "direction格式异常"),
        ({"steps": {}}, "steps 格式异常"),
        (
            {
                "steps": [
                    {
                        "polyline_idx": [1, 3],
                        "distance": 10,
                    }
                ]
            },
            "polyline_idx 越界或未对齐坐标对",
        ),
        (
            {
                "steps": [
                    {
                        "polyline_idx": [0, 7],
                        "distance": 10,
                    }
                ]
            },
            "polyline_idx 越界或未对齐坐标对",
        ),
    ],
)
def test_plan_tencent_bicycling_route_rejects_malformed_route_fields(
    monkeypatch,
    route_patch,
    error_match,
):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            route = {
                "distance": 456,
                "duration": 3,
                "polyline": [37.8, 112.5, 1000, 1000],
                "steps": [],
            }
            route.update(route_patch)
            return {"status": 0, "result": {"routes": [route]}}

    monkeypatch.setattr(settings, "TENCENT_MAP_KEY", "test-key")
    monkeypatch.setattr(settings, "TENCENT_MAP_SK", "test-sk")
    monkeypatch.setattr("app.route_book.tencent_direction.httpx.get", lambda *args, **kwargs: FakeResponse())

    with pytest.raises(TencentMapError, match=error_match):
        plan_tencent_bicycling_route((37.8, 112.5), (37.9, 112.6))


@pytest.mark.parametrize(
    "payload,error_match",
    [
        ([], "腾讯地图返回格式异常"),
        ({"status": 0, "result": []}, "腾讯地图缺少路线结果"),
        ({"status": 0, "result": {"routes": {}}}, "腾讯地图 routes 格式异常"),
        ({"status": 0, "result": {"routes": [None]}}, "腾讯地图路线格式异常"),
    ],
)
def test_plan_tencent_bicycling_route_rejects_malformed_envelope(monkeypatch, payload, error_match):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return payload

    monkeypatch.setattr(settings, "TENCENT_MAP_KEY", "test-key")
    monkeypatch.setattr(settings, "TENCENT_MAP_SK", "test-sk")
    monkeypatch.setattr("app.route_book.tencent_direction.httpx.get", lambda *args, **kwargs: FakeResponse())

    with pytest.raises(TencentMapError, match=error_match):
        plan_tencent_bicycling_route((37.8, 112.5), (37.9, 112.6))
