"""路线编辑页实时海拔预览 API 合同。"""

from pathlib import Path

import pytest
from fastapi import HTTPException

from app.elevation.dem_client import DEMServiceError
from app.segment.coord_convert import convert_points_to_wgs84


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _disable_elevation_preview_rate_limit(monkeypatch):
    monkeypatch.setattr("app.route_book.router.check_rate_limit_by_user", lambda *args, **kwargs: None)


def _payload(points=None):
    return {
        "coordinate_system": "gcj02",
        "points": points or [[112.5001, 37.8001], [112.5201, 37.8201]],
    }


def test_elevation_preview_returns_profile_without_creating_route(
    client, db, auth_header, monkeypatch
):
    from app.route_book.models import RouteBook

    query_calls = []

    def fake_query(points, **kwargs):
        query_calls.append(points)
        assert kwargs["timeout_seconds"] == 8.0
        return [700.0 + index * 0.5 for index in range(len(points))]

    monkeypatch.setattr("app.route_book.service.query_elevations", fake_query)

    response = client.post(
        "/api/route-books/manual-drawn/elevation-preview",
        json=_payload(),
        headers=auth_header,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["coordinate_system"] == "gcj02"
    assert body["distance_m"] > 0
    assert body["climb_m"] > 0
    assert body["descent_m"] == pytest.approx(0.0)
    assert len(body["elevation_profile"]) >= 2
    assert len(query_calls) == 1
    assert db.query(RouteBook).count() == 0


def test_elevation_preview_converts_gcj02_to_wgs84_before_dem_query(
    client, auth_header, monkeypatch
):
    captured = []
    source = [[112.5001, 37.8001], [112.5011, 37.8011]]

    def fake_query(points, **kwargs):
        captured.extend(points)
        assert kwargs["timeout_seconds"] == 8.0
        return [700.0 for _point in points]

    monkeypatch.setattr("app.route_book.service.query_elevations", fake_query)

    response = client.post(
        "/api/route-books/manual-drawn/elevation-preview",
        json=_payload(source),
        headers=auth_header,
    )

    assert response.status_code == 200
    expected = convert_points_to_wgs84(
        [{"lon": lon, "lat": lat} for lon, lat in source],
        "gcj02",
    )
    assert captured[0] == pytest.approx((expected[0]["lat"], expected[0]["lon"]))
    assert captured[-1] == pytest.approx((expected[-1]["lat"], expected[-1]["lon"]))


def test_elevation_preview_requires_login_before_dem_query(client, monkeypatch):
    called = False

    def fake_query(points, **_kwargs):
        nonlocal called
        called = True
        return [700.0 for _point in points]

    monkeypatch.setattr("app.route_book.service.query_elevations", fake_query)

    response = client.post("/api/route-books/manual-drawn/elevation-preview", json=_payload())

    assert response.status_code == 401
    assert called is False


def test_elevation_preview_returns_503_when_glo_tile_is_unavailable(
    client, auth_header, monkeypatch
):
    def fake_query(_points, **_kwargs):
        raise DEMServiceError("GLO-30 瓦片正在下载")

    monkeypatch.setattr("app.route_book.service.query_elevations", fake_query)

    response = client.post(
        "/api/route-books/manual-drawn/elevation-preview",
        json=_payload(),
        headers=auth_header,
    )

    assert response.status_code == 503
    assert "海拔查询失败" in response.text
    assert "正在下载" in response.text


def test_elevation_preview_rejects_more_than_5000_points_before_dem_query(
    client, auth_header, monkeypatch
):
    called = False

    def fake_query(points, **_kwargs):
        nonlocal called
        called = True
        return [700.0 for _point in points]

    monkeypatch.setattr("app.route_book.service.query_elevations", fake_query)
    points = [[112.5 + index * 0.000001, 37.8] for index in range(5001)]

    response = client.post(
        "/api/route-books/manual-drawn/elevation-preview",
        json=_payload(points),
        headers=auth_header,
    )

    assert response.status_code == 422
    assert called is False


def test_elevation_preview_applies_its_own_rate_limit(
    client, auth_header, test_user, monkeypatch
):
    calls = []

    def fake_rate_limit(user_id, key_prefix, limit, window_sec):
        calls.append((user_id, key_prefix, limit, window_sec))
        raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")

    monkeypatch.setattr("app.route_book.router.check_rate_limit_by_user", fake_rate_limit)
    monkeypatch.setattr(
        "app.route_book.service.query_elevations",
        lambda _points, **_kwargs: (_ for _ in ()).throw(AssertionError("限流后不应查询 DEM")),
    )

    response = client.post(
        "/api/route-books/manual-drawn/elevation-preview",
        json=_payload(),
        headers=auth_header,
    )

    assert response.status_code == 429
    assert calls == [(test_user.id, "route-book-draw-elevation-preview", 30, 300)]


def test_miniprogram_api_bounds_elevation_preview_wait_time():
    api_js = (ROOT / "miniprogram" / "utils" / "api.js").read_text(encoding="utf-8")

    assert "previewManualDrawnElevation" in api_js
    assert "'/api/route-books/manual-drawn/elevation-preview'" in api_js
    assert "ROUTE_ELEVATION_PREVIEW_TIMEOUT_MS" in api_js.split(
        "previewManualDrawnElevation: function", 1
    )[1].split("},", 1)[0]
    assert "ROUTE_ELEVATION_PREVIEW_TIMEOUT_MS = 12000" in api_js
