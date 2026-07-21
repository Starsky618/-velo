"""Route Draw V0 Task 1：手画线贴路预览 API 测试。"""

from pathlib import Path
import json
import subprocess
import textwrap

import pytest
from fastapi import HTTPException

from app.route_book.tencent_direction import (
    TencentMapError,
    TencentMapServiceUnavailableError,
    plan_tencent_bicycling_route,
)


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _disable_snap_preview_rate_limit(monkeypatch):
    # 普通测试只考业务逻辑，不让真实 Redis 计数串扰；限流参数另有专门测试锁住。
    monkeypatch.setattr("app.route_book.router.check_rate_limit_by_user", lambda *args, **kwargs: None)


def _snap_payload(points=None, mode="snap", coordinate_system="gcj02"):
    return {
        "coordinate_system": coordinate_system,
        "mode": mode,
        "points": points or [[112.5001, 37.8001], [112.5601, 37.8601]],
    }


def test_logged_in_user_gets_snap_preview_without_creating_route_book(client, db, auth_header, monkeypatch):
    from app.route_book.models import RouteBook

    calls = []

    def fake_plan(start, end, timeout_sec=None):
        calls.append((start, end, timeout_sec))
        return {
            "distance": 6800.0,
            "duration": 28,
            "points": [
                {"lat": start[0], "lon": start[1]},
                {"lat": 37.8301, "lon": 112.5301},
                {"lat": end[0], "lon": end[1]},
            ],
        }

    monkeypatch.setattr("app.route_book.draw_snap_service.plan_tencent_bicycling_route", fake_plan)

    res = client.post("/api/route-books/manual-drawn/snap-preview", json=_snap_payload(), headers=auth_header)

    assert res.status_code == 200
    body = res.json()
    assert body["mode"] == "snap"
    assert body["coordinate_system"] == "gcj02"
    assert body["raw_points"] == [[112.5001, 37.8001], [112.5601, 37.8601]]
    assert body["anchor_points"] == [[112.5001, 37.8001], [112.5601, 37.8601]]
    assert body["snapped_points"] == [[112.5001, 37.8001], [112.5301, 37.8301], [112.5601, 37.8601]]
    assert body["raw_distance_m"] > 0
    assert body["distance_m"] == 6800.0
    assert body["segment_count"] == 1
    assert body["warnings"] == []
    assert body["failed_segment"] is None
    assert calls == [((37.8001, 112.5001), (37.8601, 112.5601), 3.0)]
    assert db.query(RouteBook).count() == 0


def test_snap_preview_requires_login(client, monkeypatch):
    called = False

    def fake_plan(start, end, timeout_sec=None):
        nonlocal called
        called = True
        return {"distance": 1.0, "duration": 1, "points": []}

    monkeypatch.setattr("app.route_book.draw_snap_service.plan_tencent_bicycling_route", fake_plan)

    res = client.post("/api/route-books/manual-drawn/snap-preview", json=_snap_payload())

    assert res.status_code == 401
    assert called is False


def test_snap_preview_applies_user_rate_limit_before_tencent_call(client, auth_header, test_user, monkeypatch):
    calls = []

    def fake_rate_limit(user_id, key_prefix, limit, window_sec):
        calls.append((user_id, key_prefix, limit, window_sec))
        raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")

    def fake_plan(start, end, timeout_sec=None):
        raise AssertionError("限流已经拦下时不应调用腾讯")

    monkeypatch.setattr("app.route_book.router.check_rate_limit_by_user", fake_rate_limit)
    monkeypatch.setattr("app.route_book.draw_snap_service.plan_tencent_bicycling_route", fake_plan)

    res = client.post("/api/route-books/manual-drawn/snap-preview", json=_snap_payload(), headers=auth_header)

    assert res.status_code == 429
    assert calls == [(test_user.id, "route-book-draw-snap-preview", 60, 300)]


@pytest.mark.parametrize("coordinate_system", ["wgs84", "unknown", None])
def test_snap_preview_rejects_non_gcj02_coordinate_system(client, auth_header, coordinate_system, monkeypatch):
    called = False

    def fake_plan(start, end, timeout_sec=None):
        nonlocal called
        called = True
        return {"distance": 1.0, "duration": 1, "points": []}

    monkeypatch.setattr("app.route_book.draw_snap_service.plan_tencent_bicycling_route", fake_plan)

    res = client.post(
        "/api/route-books/manual-drawn/snap-preview",
        json=_snap_payload(coordinate_system=coordinate_system),
        headers=auth_header,
    )

    assert res.status_code == 422
    assert called is False


def test_snap_preview_passes_short_timeout_for_ten_segments(client, auth_header, monkeypatch):
    points = [
        [112.5000, 37.8000],
        [112.5010, 37.8020],
        [112.5020, 37.8000],
        [112.5030, 37.8020],
        [112.5040, 37.8000],
        [112.5050, 37.8020],
        [112.5060, 37.8000],
        [112.5070, 37.8020],
        [112.5080, 37.8000],
        [112.5090, 37.8020],
        [112.5100, 37.8000],
    ]
    timeouts = []

    def fake_plan(start, end, timeout_sec=None):
        timeouts.append(timeout_sec)
        return {
            "distance": 100.0,
            "duration": 1,
            "points": [
                {"lat": start[0], "lon": start[1]},
                {"lat": end[0], "lon": end[1]},
            ],
        }

    monkeypatch.setattr("app.route_book.draw_snap_service.plan_tencent_bicycling_route", fake_plan)

    res = client.post(
        "/api/route-books/manual-drawn/snap-preview",
        json=_snap_payload(points=points),
        headers=auth_header,
    )

    assert res.status_code == 200
    assert res.json()["segment_count"] == 10
    assert len(timeouts) == 10
    assert all(timeout == pytest.approx(1.2) for timeout in timeouts)


def test_freehand_preview_returns_raw_line_without_calling_tencent(client, auth_header, monkeypatch):
    def fake_plan(start, end, timeout_sec=None):
        raise AssertionError("freehand 模式不应调用腾讯")

    monkeypatch.setattr("app.route_book.draw_snap_service.plan_tencent_bicycling_route", fake_plan)

    points = [[112.5001, 37.8001], [112.5101, 37.8101], [112.5201, 37.8201]]
    res = client.post(
        "/api/route-books/manual-drawn/snap-preview",
        json=_snap_payload(points=points, mode="freehand"),
        headers=auth_header,
    )

    assert res.status_code == 200
    body = res.json()
    assert body["mode"] == "freehand"
    assert body["snapped_points"] == points
    assert body["raw_points"] == points
    assert body["anchor_points"] == points
    assert body["distance_m"] == pytest.approx(body["raw_distance_m"])
    assert body["segment_count"] == 2


def test_snap_preview_rejects_more_than_120_raw_points_before_tencent(client, auth_header, monkeypatch):
    called = False

    def fake_plan(start, end, timeout_sec=None):
        nonlocal called
        called = True
        return {"distance": 1.0, "duration": 1, "points": []}

    monkeypatch.setattr("app.route_book.draw_snap_service.plan_tencent_bicycling_route", fake_plan)

    points = [[112.5 + index * 0.0001, 37.8] for index in range(121)]
    res = client.post(
        "/api/route-books/manual-drawn/snap-preview",
        json=_snap_payload(points=points),
        headers=auth_header,
    )

    assert res.status_code == 422
    assert called is False


def test_snap_preview_rejects_more_than_ten_anchor_segments_before_tencent(client, auth_header, monkeypatch):
    called = False

    def fake_plan(start, end, timeout_sec=None):
        nonlocal called
        called = True
        return {"distance": 1.0, "duration": 1, "points": []}

    monkeypatch.setattr("app.route_book.draw_snap_service.plan_tencent_bicycling_route", fake_plan)

    points = [
        [112.5000, 37.8000],
        [112.5010, 37.8020],
        [112.5020, 37.8000],
        [112.5030, 37.8020],
        [112.5040, 37.8000],
        [112.5050, 37.8020],
        [112.5060, 37.8000],
        [112.5070, 37.8020],
        [112.5080, 37.8000],
        [112.5090, 37.8020],
        [112.5100, 37.8000],
        [112.5110, 37.8020],
    ]
    res = client.post(
        "/api/route-books/manual-drawn/snap-preview",
        json=_snap_payload(points=points),
        headers=auth_header,
    )

    assert res.status_code == 422
    assert "分几段" in res.text
    assert called is False


def test_snap_preview_tencent_failure_returns_failed_segment_without_creating_route_book(
    client, db, auth_header, monkeypatch
):
    from app.route_book.models import RouteBook

    def fake_plan(start, end, timeout_sec=None):
        raise TencentMapError("腾讯地图没有返回可用路线")

    monkeypatch.setattr("app.route_book.draw_snap_service.plan_tencent_bicycling_route", fake_plan)

    res = client.post("/api/route-books/manual-drawn/snap-preview", json=_snap_payload(), headers=auth_header)

    assert res.status_code == 422
    detail = res.json()["detail"]
    assert detail["message"] == "这段没有贴上路，换短一点再试。"
    assert detail["failed_segment"] == 0
    assert "腾讯地图没有返回可用路线" in detail["reason"]
    assert db.query(RouteBook).count() == 0


def test_snap_preview_reports_second_failed_segment(client, auth_header, monkeypatch):
    calls = []

    def fake_plan(start, end, timeout_sec=None):
        calls.append((start, end))
        if len(calls) == 2:
            raise TencentMapError("腾讯地图没有返回可用路线")
        return {
            "distance": 100.0,
            "duration": 1,
            "points": [
                {"lat": start[0], "lon": start[1]},
                {"lat": end[0], "lon": end[1]},
            ],
        }

    monkeypatch.setattr("app.route_book.draw_snap_service.plan_tencent_bicycling_route", fake_plan)

    points = [[112.5000, 37.8000], [112.5100, 37.8200], [112.5200, 37.8000]]
    res = client.post(
        "/api/route-books/manual-drawn/snap-preview",
        json=_snap_payload(points=points),
        headers=auth_header,
    )

    assert res.status_code == 422
    assert res.json()["detail"]["failed_segment"] == 1


def test_snap_preview_returns_503_when_tencent_service_unavailable(client, auth_header, monkeypatch):
    def fake_plan(start, end, timeout_sec=None):
        raise TencentMapServiceUnavailableError("腾讯地图请求失败：timed out")

    monkeypatch.setattr("app.route_book.draw_snap_service.plan_tencent_bicycling_route", fake_plan)

    res = client.post("/api/route-books/manual-drawn/snap-preview", json=_snap_payload(), headers=auth_header)

    assert res.status_code == 503
    assert "腾讯地图请求失败" in res.text


def test_snap_preview_deduplicates_join_point_when_merging_segments(client, auth_header, monkeypatch):
    calls = []

    def fake_plan(start, end, timeout_sec=None):
        calls.append((start, end))
        return {
            "distance": 100.0,
            "duration": 1,
            "points": [
                {"lat": start[0], "lon": start[1]},
                {"lat": end[0], "lon": end[1]},
            ],
        }

    monkeypatch.setattr("app.route_book.draw_snap_service.plan_tencent_bicycling_route", fake_plan)

    points = [[112.5000, 37.8000], [112.5100, 37.8200], [112.5200, 37.8000]]
    res = client.post(
        "/api/route-books/manual-drawn/snap-preview",
        json=_snap_payload(points=points),
        headers=auth_header,
    )

    assert res.status_code == 200
    assert calls == [
        ((37.8, 112.5), (37.82, 112.51)),
        ((37.82, 112.51), (37.8, 112.52)),
    ]
    assert res.json()["snapped_points"] == points


def test_snap_preview_mock_verification_handles_100_virtual_drawn_routes(client, auth_header, monkeypatch):
    calls = []

    def fake_plan(start, end, timeout_sec=None):
        calls.append((start, end, timeout_sec))
        return {
            "distance": 160.0,
            "duration": 1,
            "points": [
                {"lat": start[0], "lon": start[1]},
                {"lat": (start[0] + end[0]) / 2, "lon": (start[1] + end[1]) / 2},
                {"lat": end[0], "lon": end[1]},
            ],
        }

    monkeypatch.setattr("app.route_book.draw_snap_service.plan_tencent_bicycling_route", fake_plan)

    for index in range(100):
        base_lon = 112.5000 + (index % 10) * 0.002
        base_lat = 37.8000 + (index // 10) * 0.002
        points = [
            [base_lon, base_lat],
            [base_lon + 0.001, base_lat + 0.0005],
            [base_lon + 0.002, base_lat + 0.001],
        ]

        res = client.post(
            "/api/route-books/manual-drawn/snap-preview",
            json=_snap_payload(points=points),
            headers=auth_header,
        )

        assert res.status_code == 200
        body = res.json()
        assert body["mode"] == "snap"
        assert body["coordinate_system"] == "gcj02"
        assert len(body["raw_points"]) == 3
        assert len(body["snapped_points"]) >= 3
        assert body["distance_m"] > 0

    assert len(calls) >= 100


def test_tencent_client_uses_custom_timeout(monkeypatch):
    from app.config import settings
    from app.route_book import tencent_direction

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
                            "distance": 123.0,
                            "duration": 8,
                            "polyline": [37.8, 112.5, 1000, 1000],
                        }
                    ]
                },
            }

    def fake_get(url, params, timeout):
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(settings, "TENCENT_MAP_KEY", "key")
    monkeypatch.setattr(settings, "TENCENT_MAP_SK", "sk")
    monkeypatch.setattr(tencent_direction.httpx, "get", fake_get)

    planned = plan_tencent_bicycling_route((37.8, 112.5), (37.801, 112.501), timeout_sec=2.5)

    assert captured["timeout"] == 2.5
    assert planned["points"][-1] == {"lat": 37.800999999999995, "lon": 112.501}


def test_tencent_client_http_error_raises_service_unavailable(monkeypatch):
    import httpx

    from app.config import settings
    from app.route_book import tencent_direction

    def fake_get(url, params, timeout):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(settings, "TENCENT_MAP_KEY", "key")
    monkeypatch.setattr(settings, "TENCENT_MAP_SK", "sk")
    monkeypatch.setattr(tencent_direction.httpx, "get", fake_get)

    with pytest.raises(TencentMapServiceUnavailableError):
        plan_tencent_bicycling_route((37.8, 112.5), (37.801, 112.501), timeout_sec=2.5)


def test_tencent_client_http_status_error_does_not_leak_credentials(monkeypatch):
    import httpx
    import traceback

    from app.config import settings
    from app.route_book import tencent_direction

    dummy_key = "DUMMY_KEY_SHOULD_NOT_ESCAPE"

    def fake_get(url, params, timeout):
        response = httpx.Response(
            503,
            request=httpx.Request("GET", url, params=params),
        )
        response.raise_for_status()

    monkeypatch.setattr(settings, "TENCENT_MAP_KEY", dummy_key)
    monkeypatch.setattr(settings, "TENCENT_MAP_SK", "DUMMY_SK")
    monkeypatch.setattr(tencent_direction.httpx, "get", fake_get)

    with pytest.raises(TencentMapServiceUnavailableError) as error:
        plan_tencent_bicycling_route((37.8, 112.5), (37.801, 112.501), timeout_sec=2.5)

    assert dummy_key not in str(error.value)
    assert "sig=" not in str(error.value)
    assert error.value.__cause__ is None
    assert error.value.__suppress_context__ is True
    rendered_traceback = "".join(traceback.format_exception(error.value))
    assert dummy_key not in rendered_traceback
    assert "sig=" not in rendered_traceback


def test_api_js_exposes_snap_manual_drawn_route_helper():
    api_js = (ROOT / "miniprogram" / "utils" / "api.js").read_text(encoding="utf-8")

    assert "snapManualDrawnRoute" in api_js
    assert "return request('/api/route-books/manual-drawn/snap-preview', 'POST', payload)" in api_js


def test_api_js_keeps_structured_snap_error_detail_readable():
    script = """
    global.getApp = function () {
      return { globalData: { baseUrl: 'https://example.test', token: 'token' } }
    }
    global.wx = {
      removeStorageSync: function () {},
      request: function (options) {
        options.success({
          statusCode: 422,
          data: {
            detail: {
              message: '这段没有贴上路，换短一点再试。',
              failed_segment: 1,
              reason: '腾讯地图没有返回可用路线'
            }
          }
        })
      }
    }
    const api = require('./miniprogram/utils/api.js')
    api.snapManualDrawnRoute({}).then(function () {
      process.exit(2)
    }).catch(function (err) {
      process.stdout.write(JSON.stringify(err))
    })
    """
    result = subprocess.run(
        ["node", "-e", textwrap.dedent(script)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    err = json.loads(result.stdout)

    assert err["code"] == 422
    assert err["message"] == "这段没有贴上路，换短一点再试。"
    assert err["detail"]["failed_segment"] == 1
