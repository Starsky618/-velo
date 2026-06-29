"""约骑模块 Task 2：路书 API 测试。"""

from datetime import datetime, timezone
import json
from typing import get_args

import pytest

from app.activity.models import Activity, Trackpoint
from app.main import app
from app.route_book.router import router as route_book_router
from app.route_book import schemas


# task2 阶段 route_book router 还没挂进 app.main（task4 才统一挂载所有 router）。
# 这里在测试 app 上临时挂一次，让 TestClient 能请求 /api/route-books。
# 幂等判断：多个测试文件可能都想挂，避免重复 include 同一 router。
if not any(getattr(route, "path", "") == "/api/route-books" for route in app.router.routes):
    app.include_router(route_book_router)


@pytest.fixture(autouse=True)
def _disable_tencent_direction_rate_limit(monkeypatch):
    # 路书业务测试像“模拟考场”：每题应只考本题逻辑，不能被真实 Redis 里的旧限流计数串扰。
    # 专门的限流测试会在测试函数内再次 monkeypatch，单独验证 router 是否按正确参数调用限流门卫。
    monkeypatch.setattr("app.route_book.router.check_rate_limit_by_user", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.route_book.router.check_rate_limit_by_ip", lambda *args, **kwargs: None)


def test_generic_create_source_excludes_tencent_direction():
    assert get_args(schemas.RouteBookCreateSource) == ("file_upload", "activity_derived")
    assert "tencent_direction" in get_args(schemas.RouteBookSource)
    assert "manual_drawn" in get_args(schemas.RouteBookSource)
    assert "curated_composite" in get_args(schemas.RouteBookSource)
    assert "ai_generated" in get_args(schemas.RouteBookSource)


def _activity(db, user_id: int, **overrides):
    data = {
        "user_id": user_id,
        "title": "周末路线",
        "status": "completed",
        "activity_type": "cycling",
        "file_url": "202605/ride.gpx",
        "distance": 42000.0,
        "elevation_gain": 580.0,
        "started_at": datetime(2026, 5, 20, 1, 0, tzinfo=timezone.utc),
    }
    data.update(overrides)
    activity = Activity(**data)
    db.add(activity)
    db.commit()
    db.refresh(activity)
    db.add_all([
        Trackpoint(activity_id=activity.id, seq=0, latitude=37.8, longitude=112.5, distance=0.0),
        Trackpoint(activity_id=activity.id, seq=1, latitude=37.9, longitude=112.6, distance=42000.0),
    ])
    db.commit()
    return activity


def _route_with_current_version(db, creator_id: int | None, **overrides):
    from app.route_book.models import RouteBook, RouteVersion

    line = "SRID=4326;LINESTRING(112.5 37.8, 112.6 37.9)"
    data = {
        "creator_id": creator_id,
        "name": "公开可下载路线",
        "distance": 42000.0,
        "climb": 580.0,
        "reference_line": line,
        "source": "file_upload",
        "file_id": "original/private-source.gpx",
        "file_type": "gpx",
        "source_activity_id": None,
        "city": "taiyuan",
        "visibility": "public",
        "publish_status": "published",
    }
    data.update(overrides)
    route = RouteBook(**data)
    db.add(route)
    db.commit()
    db.refresh(route)

    version = RouteVersion(
        route_book_id=route.id,
        version_no=1,
        status="current",
        created_by=creator_id,
        geometry_source=route.source,
        navigation_status="ready",
        reference_line_snapshot=line,
        line_hash=f"hash-{route.id}",
        distance=route.distance,
        climb=route.climb,
        point_count=2,
    )
    db.add(version)
    db.commit()
    db.refresh(version)
    route.current_version_id = version.id
    db.add(route)
    db.commit()
    db.refresh(route)
    return route, version


class _FakeExportStorage:
    def __init__(self):
        self.files = {}
        self.uploads = []

    def upload(self, file_bytes, filename, subdir=""):
        assert file_bytes.startswith(b"<?xml")
        file_id = f"{subdir}/{filename}" if subdir else filename
        self.files[file_id] = file_bytes
        self.uploads.append((file_id, filename, subdir))
        return file_id

    def download(self, file_id):
        return self.files[file_id]


def test_public_route_export_creates_downloadable_gpx_without_leaking_file_id(client, db, admin_user, monkeypatch):
    route, version = _route_with_current_version(db, admin_user.id)
    fake_storage = _FakeExportStorage()
    monkeypatch.setattr("app.route_book.export_workflow._storage", fake_storage)

    res = client.post(
        f"/api/route-books/{route.id}/exports",
        json={"format": "gpx", "target_platform": "garmin"},
    )

    assert res.status_code == 200
    body = res.json()
    assert body["route_book_id"] == route.id
    assert body["route_version_id"] == version.id
    assert body["format"] == "gpx"
    assert body["filename"].endswith(f"-{route.id}-v{version.id}.gpx")
    assert body["download_url"] == f"/api/route-books/{route.id}/exports/{body['artifact_id']}/download"
    assert "file_id" not in body
    assert fake_storage.uploads

    download = client.get(body["download_url"])
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("application/gpx+xml")
    assert "attachment" in download.headers["content-disposition"]
    assert ".gpx" in download.headers["content-disposition"]
    assert not download.headers["content-type"].startswith("application/json")
    assert b"<gpx" in download.content
    assert b"TrainingCenterDatabase" not in download.content


def test_public_route_export_uses_route_version_precise_elevation_snapshot(client, db, admin_user, monkeypatch):
    route, version = _route_with_current_version(db, admin_user.id)
    # SQLite 测试库用固定假 EWKB 模拟 PostGIS 读 Geometry；这里跟随假坐标，只测 API 链路是否带出高程。
    version.elevation_points_snapshot = "[[112.55,37.87,701.2],[112.55,37.875,735.8]]"
    db.add(version)
    db.commit()
    monkeypatch.setattr("app.route_book.export_workflow._storage", _FakeExportStorage())

    created = client.post(f"/api/route-books/{route.id}/exports", json={"format": "gpx"})
    download = client.get(created.json()["download_url"])

    assert download.status_code == 200
    assert b"<ele>701.2</ele>" in download.content
    assert b"<ele>735.8</ele>" in download.content


def test_public_route_export_created_by_login_user_still_downloads_without_auth(client, db, auth_header, test_user, monkeypatch):
    route, _version = _route_with_current_version(db, test_user.id)
    monkeypatch.setattr("app.route_book.export_workflow._storage", _FakeExportStorage())

    created = client.post(
        f"/api/route-books/{route.id}/exports",
        json={"format": "gpx"},
        headers=auth_header,
    )
    assert created.status_code == 200

    download = client.get(created.json()["download_url"])

    assert download.status_code == 200
    assert download.headers["content-type"].startswith("application/gpx+xml")
    assert b"<gpx" in download.content


def test_creator_can_export_private_route_but_anonymous_cannot(client, db, auth_header, test_user, monkeypatch):
    route, _version = _route_with_current_version(
        db,
        test_user.id,
        name="我的私密路线",
        visibility="private",
        publish_status="draft",
    )
    monkeypatch.setattr("app.route_book.export_workflow._storage", _FakeExportStorage())

    anonymous = client.post(f"/api/route-books/{route.id}/exports", json={"format": "tcx"})
    assert anonymous.status_code == 403

    owner = client.post(
        f"/api/route-books/{route.id}/exports",
        json={"format": "tcx", "target_platform": "wahoo"},
        headers=auth_header,
    )
    assert owner.status_code == 200
    assert owner.json()["format"] == "tcx"
    assert "file_id" not in owner.json()


def test_route_export_rejects_public_route_without_current_version(client, db, admin_user):
    from app.route_book.models import RouteBook

    route = RouteBook(
        creator_id=admin_user.id,
        name="只有壳没有轨迹",
        distance=42000.0,
        reference_line="SRID=4326;LINESTRING(112.5 37.8, 112.6 37.9)",
        source="file_upload",
        source_activity_id=None,
        city="taiyuan",
        visibility="public",
        publish_status="published",
        current_version_id=None,
    )
    db.add(route)
    db.commit()
    db.refresh(route)

    res = client.post(f"/api/route-books/{route.id}/exports", json={"format": "gpx"})

    assert res.status_code == 422
    assert "没有可下载轨迹" in res.text


def test_route_export_download_rejects_artifact_job_mismatch(client, db, admin_user, monkeypatch):
    from app.route_book.models import RouteExportArtifact

    route, _version = _route_with_current_version(db, admin_user.id)
    monkeypatch.setattr("app.route_book.export_workflow._storage", _FakeExportStorage())
    created = client.post(f"/api/route-books/{route.id}/exports", json={"format": "gpx"}).json()

    artifact = db.query(RouteExportArtifact).filter(RouteExportArtifact.id == created["artifact_id"]).one()
    artifact.export_job_id = artifact.export_job_id + 999
    db.add(artifact)
    db.commit()

    res = client.get(created["download_url"])

    assert res.status_code == 403


def test_route_export_download_returns_404_when_storage_file_is_missing(client, db, admin_user, monkeypatch):
    route, _version = _route_with_current_version(db, admin_user.id)
    storage = _FakeExportStorage()
    monkeypatch.setattr("app.route_book.export_workflow._storage", storage)
    created = client.post(f"/api/route-books/{route.id}/exports", json={"format": "gpx"}).json()
    storage.files.clear()

    res = client.get(created["download_url"])

    assert res.status_code == 404
    assert "not found" in res.json()["detail"]


def test_activity_derived_requires_source_activity_id(client, auth_header):
    res = client.post(
        "/api/route-books",
        data={"name": "无来源", "source": "activity_derived"},
        headers=auth_header,
    )
    assert res.status_code == 422
    assert "source_activity_id" in res.text


def test_activity_derived_rejects_other_user_activity(client, db, auth_header, admin_user):
    other_activity = _activity(db, admin_user.id)

    res = client.post(
        "/api/route-books",
        data={"name": "别人的路线", "source": "activity_derived", "source_activity_id": str(other_activity.id)},
        headers=auth_header,
    )

    assert res.status_code == 403


def test_activity_derived_creates_route_book(client, db, auth_header, test_user):
    from app.route_book.models import RouteBook, RouteVersion

    activity = _activity(db, test_user.id, city="taiyuan")
    db.query(Trackpoint).filter(Trackpoint.activity_id == activity.id, Trackpoint.seq == 0).update({"elevation": 701.2})
    db.query(Trackpoint).filter(Trackpoint.activity_id == activity.id, Trackpoint.seq == 1).update({"elevation": 735.8})
    db.commit()

    res = client.post(
        "/api/route-books",
        data={"name": "汾河训练线", "source": "activity_derived", "source_activity_id": str(activity.id)},
        headers=auth_header,
    )

    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "汾河训练线"
    assert body["source"] == "activity_derived"
    assert body["source_activity_id"] == activity.id
    assert body["file_id"] is None
    assert body["file_type"] is None
    assert body["city"] == "taiyuan"
    assert body["visibility"] == "private"
    assert body["publish_status"] == "draft"
    assert body["current_version_id"] is not None

    route = db.query(RouteBook).filter(RouteBook.id == body["id"]).one()
    version = db.query(RouteVersion).filter(RouteVersion.route_book_id == route.id).one()
    assert route.current_version_id == version.id
    assert route.line_hash == version.line_hash
    assert version.version_no == 1
    assert version.status == "current"
    assert version.navigation_status == "ready"
    assert version.geometry_source == "activity_derived"
    assert json.loads(version.elevation_points_snapshot) == [[112.5, 37.8, 701.2], [112.6, 37.9, 735.8]]


def test_file_upload_supports_gpx_and_preserves_file_id(client, db, auth_header, monkeypatch):
    class FakeStorage:
        def upload(self, file_bytes, filename):
            assert filename == "route.gpx"
            return "202605/route.gpx"

    monkeypatch.setattr("app.route_book.service._storage", FakeStorage())
    monkeypatch.setattr("app.route_book.service._parse_route_file", lambda filename, b: {
        "distance": 1234.0,
        "climb": 50.0,
        "city": "taiyuan",
        "wkt": "SRID=4326;LINESTRING(112.5 37.8, 112.6 37.9)",
        "elevation_points_snapshot": "[[112.5,37.8,701.2],[112.6,37.9,735.8]]",
    })

    res = client.post(
        "/api/route-books",
        data={"name": "上传路线", "source": "file_upload"},
        files={"file": ("route.gpx", b"<?xml version='1.0'?><gpx></gpx>", "application/gpx+xml")},
        headers=auth_header,
    )

    assert res.status_code == 200
    body = res.json()
    assert body["file_id"] == "202605/route.gpx"
    assert body["file_type"] == "gpx"
    from app.route_book.models import RouteVersion

    version = db.query(RouteVersion).filter(RouteVersion.route_book_id == body["id"]).one()
    assert json.loads(version.elevation_points_snapshot)[0] == [112.5, 37.8, 701.2]


def test_file_upload_real_gpx_parser_saves_precise_elevation_points(client, db, auth_header, monkeypatch):
    class FakeStorage:
        def upload(self, file_bytes, filename):
            assert filename == "real-route.gpx"
            return "202605/real-route.gpx"

    gpx = b"""<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="pytest" xmlns="http://www.topografix.com/GPX/1/1">
  <trk>
    <trkseg>
      <trkpt lat="37.8" lon="112.5"><ele>701.2</ele></trkpt>
      <trkpt lat="37.9" lon="112.6"><ele>735.8</ele></trkpt>
    </trkseg>
  </trk>
</gpx>
"""
    monkeypatch.setattr("app.route_book.service._storage", FakeStorage())

    res = client.post(
        "/api/route-books",
        data={"name": "真实 GPX 上传路线", "source": "file_upload"},
        files={"file": ("real-route.gpx", gpx, "application/gpx+xml")},
        headers=auth_header,
    )

    assert res.status_code == 200
    from app.route_book.models import RouteVersion

    version = db.query(RouteVersion).filter(RouteVersion.route_book_id == res.json()["id"]).one()
    assert json.loads(version.elevation_points_snapshot) == [[112.5, 37.8, 701.2], [112.6, 37.9, 735.8]]


def test_file_upload_supports_fit_and_preserves_file_id(client, auth_header, monkeypatch):
    class FakeStorage:
        def upload(self, file_bytes, filename):
            assert filename == "route.fit"
            return "202605/route.fit"

    monkeypatch.setattr("app.route_book.service._storage", FakeStorage())
    monkeypatch.setattr("app.route_book.service._parse_route_file", lambda filename, b: {
        "distance": 2345.0,
        "climb": 80.0,
        "city": "taiyuan",
        "wkt": "SRID=4326;LINESTRING(112.5 37.8, 112.6 37.9)",
    })

    res = client.post(
        "/api/route-books",
        data={"name": "FIT 路线", "source": "file_upload"},
        files={"file": ("route.fit", b"fit-bytes", "application/octet-stream")},
        headers=auth_header,
    )

    assert res.status_code == 200
    body = res.json()
    assert body["file_id"] == "202605/route.fit"
    assert body["file_type"] == "fit"


def test_tencent_direction_requires_server_key(client, auth_header, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "TENCENT_MAP_KEY", "")
    monkeypatch.setattr(settings, "TENCENT_MAP_SK", "")

    res = client.post(
        "/api/route-books/tencent-direction",
        json={
            "name": "腾讯规划路线",
            "from_lat": 37.8001,
            "from_lon": 112.5001,
            "to_lat": 37.8601,
            "to_lon": 112.5601,
        },
        headers=auth_header,
    )

    assert res.status_code == 503
    assert "TENCENT_MAP_KEY" in res.text


def test_tencent_direction_creates_route_book(client, db, auth_header, monkeypatch):
    from app.route_book.models import RouteBook

    def fake_plan(start, end):
        assert start == (37.8001, 112.5001)
        assert end == (37.8601, 112.5601)
        return {
            "distance": 6800.0,
            "duration": 28,
            "points": [
                {"lat": 37.8001, "lon": 112.5001},
                {"lat": 37.8301, "lon": 112.5301},
                {"lat": 37.8601, "lon": 112.5601},
            ],
        }

    monkeypatch.setattr("app.route_book.service.plan_tencent_bicycling_route", fake_plan)

    res = client.post(
        "/api/route-books/tencent-direction",
        json={
            "name": "腾讯规划路线",
            "from_lat": 37.8001,
            "from_lon": 112.5001,
            "to_lat": 37.8601,
            "to_lon": 112.5601,
        },
        headers=auth_header,
    )

    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "腾讯规划路线"
    assert body["source"] == "tencent_direction"
    assert body["file_id"] is None
    assert body["file_type"] is None
    assert body["source_activity_id"] is None
    expected_preview_points = [
        [112.49364834456821, 37.799433332389704],
        [112.52375120797853, 37.829523730616],
        [112.55382682870768, 37.85959385355675],
    ]
    assert len(body["preview_points"]) == len(expected_preview_points)
    for actual, expected in zip(body["preview_points"], expected_preview_points):
        assert actual == pytest.approx(expected)
    route = db.query(RouteBook).filter(RouteBook.id == body["id"]).first()
    assert route is not None
    assert route.distance == 6800.0
    assert route.source == "tencent_direction"


def test_route_book_preview_points_parse_wkb_without_shapely(monkeypatch):
    import struct

    from geoalchemy2.elements import WKBElement

    from app.route_book import models
    from app.route_book.models import RouteBook

    def fail_to_shape(_value):
        raise ImportError("shapely missing")

    monkeypatch.setattr(models, "to_shape", fail_to_shape, raising=False)

    data = (
        struct.pack("<BI", 1, 2)
        + struct.pack("<I", 2)
        + struct.pack("<dd", 112.5001, 37.8001)
        + struct.pack("<dd", 112.5601, 37.8601)
    )
    route = RouteBook(
        name="WKB 路线",
        distance=1000,
        reference_line=WKBElement(data, srid=4326),
        source="tencent_direction",
        city="taiyuan",
    )

    assert route.preview_points == [[112.5001, 37.8001], [112.5601, 37.8601]]


def test_tencent_direction_applies_user_rate_limit(client, auth_header, test_user, monkeypatch):
    calls = []

    def fake_rate_limit(user_id, key_prefix, limit, window_sec):
        calls.append((user_id, key_prefix, limit, window_sec))

    monkeypatch.setattr("app.route_book.router.check_rate_limit_by_user", fake_rate_limit)
    monkeypatch.setattr("app.route_book.service.plan_tencent_bicycling_route", lambda start, end: {
        "distance": 6800.0,
        "duration": 28,
        "points": [
            {"lat": 37.8001, "lon": 112.5001},
            {"lat": 37.8601, "lon": 112.5601},
        ],
    })

    res = client.post(
        "/api/route-books/tencent-direction",
        json={
            "name": "限流路线",
            "from_lat": 37.8001,
            "from_lon": 112.5001,
            "to_lat": 37.8601,
            "to_lon": 112.5601,
        },
        headers=auth_header,
    )

    assert res.status_code == 200
    assert calls == [(test_user.id, "route-book-tencent-direction", 10, 300)]


def test_tencent_direction_rejects_same_point_before_calling_tencent(client, auth_header, monkeypatch):
    called = False

    def fake_plan(start, end):
        nonlocal called
        called = True
        return {"distance": 1.0, "duration": 1, "points": []}

    monkeypatch.setattr("app.route_book.service.plan_tencent_bicycling_route", fake_plan)

    res = client.post(
        "/api/route-books/tencent-direction",
        json={
            "name": "原地路线",
            "from_lat": 37.8001,
            "from_lon": 112.5001,
            "to_lat": 37.8001,
            "to_lon": 112.5001,
        },
        headers=auth_header,
    )

    assert res.status_code == 422
    assert called is False


def test_tencent_direction_rejects_too_short_route(client, db, auth_header, monkeypatch):
    from app.route_book.models import RouteBook

    monkeypatch.setattr("app.route_book.service.plan_tencent_bicycling_route", lambda start, end: {
        "distance": 20.0,
        "duration": 1,
        "points": [
            {"lat": 37.8001, "lon": 112.5001},
            {"lat": 37.8002, "lon": 112.5002},
        ],
    })

    res = client.post(
        "/api/route-books/tencent-direction",
        json={
            "name": "太短路线",
            "from_lat": 37.8001,
            "from_lon": 112.5001,
            "to_lat": 37.8002,
            "to_lon": 112.5002,
        },
        headers=auth_header,
    )

    assert res.status_code == 422
    assert db.query(RouteBook).filter(RouteBook.name == "太短路线").first() is None


def test_tencent_direction_rejects_empty_polyline(client, db, auth_header, monkeypatch):
    from app.route_book.models import RouteBook

    monkeypatch.setattr("app.route_book.service.plan_tencent_bicycling_route", lambda start, end: {
        "distance": 0.0,
        "duration": 0,
        "points": [],
    })

    res = client.post(
        "/api/route-books/tencent-direction",
        json={
            "name": "空路线",
            "from_lat": 37.8001,
            "from_lon": 112.5001,
            "to_lat": 37.8601,
            "to_lon": 112.5601,
        },
        headers=auth_header,
    )

    assert res.status_code == 422
    assert db.query(RouteBook).filter(RouteBook.name == "空路线").first() is None


def test_list_supports_visibility_mine_and_city_filters(client, db, auth_header, admin_header, test_user, admin_user):
    from app.route_book.models import RouteBook

    mine = RouteBook(
        creator_id=test_user.id,
        name="我的训练路线",
        distance=1800.0,
        reference_line="SRID=4326;LINESTRING(112.5 37.8, 112.6 37.9)",
        source="activity_derived",
        source_activity_id=None,
        city="taiyuan",
    )
    public_other = RouteBook(
        creator_id=admin_user.id,
        name="别人公开路线",
        distance=2200.0,
        reference_line="SRID=4326;LINESTRING(112.5 37.8, 112.7 37.9)",
        source="activity_derived",
        source_activity_id=None,
        city="taiyuan",
        visibility="public",
        publish_status="published",
    )
    private_other = RouteBook(
        creator_id=admin_user.id,
        name="别人私密路线",
        distance=2600.0,
        reference_line="SRID=4326;LINESTRING(112.5 37.8, 112.8 37.9)",
        source="activity_derived",
        source_activity_id=None,
        city="taiyuan",
    )
    db.add_all([mine, public_other, private_other])
    db.commit()
    db.refresh(mine)
    db.refresh(public_other)
    db.refresh(private_other)

    list_res = client.get("/api/route-books?city=taiyuan", headers=auth_header)
    assert list_res.status_code == 200
    names = [item["name"] for item in list_res.json()["items"]]
    assert "我的训练路线" in names
    assert "别人公开路线" in names
    assert "别人私密路线" not in names

    public_res = client.get("/api/route-books?city=taiyuan")
    assert public_res.status_code == 200
    assert [item["name"] for item in public_res.json()["items"]] == ["别人公开路线"]

    mine_res = client.get("/api/route-books?mine=1", headers=auth_header)
    assert mine_res.status_code == 200
    mine_names = [item["name"] for item in mine_res.json()["items"]]
    assert "我的训练路线" in mine_names
    assert "别人公开路线" not in mine_names

    unauth_mine = client.get("/api/route-books?mine=1")
    assert unauth_mine.status_code == 401

    detail_res = client.get(f"/api/route-books/{public_other.id}", headers=auth_header)
    assert detail_res.status_code == 200
    assert detail_res.json()["id"] == public_other.id

    hidden_detail = client.get(f"/api/route-books/{private_other.id}", headers=auth_header)
    assert hidden_detail.status_code == 404


def test_public_route_hides_source_activity_id_for_non_owner(client, db, auth_header, admin_header, test_user, admin_user):
    from app.route_book.models import RouteBook

    activity = _activity(db, admin_user.id, city="taiyuan")
    route = RouteBook(
        creator_id=admin_user.id,
        name="公开活动衍生路线",
        distance=2200.0,
        reference_line="SRID=4326;LINESTRING(112.5 37.8, 112.7 37.9)",
        source="activity_derived",
        source_activity_id=activity.id,
        city="taiyuan",
        visibility="public",
        publish_status="published",
    )
    db.add(route)
    db.commit()
    db.refresh(route)

    owner_res = client.get(f"/api/route-books/{route.id}", headers=admin_header)
    other_res = client.get(f"/api/route-books/{route.id}", headers=auth_header)

    assert owner_res.status_code == 200
    assert owner_res.json()["source_activity_id"] == activity.id
    assert other_res.status_code == 200
    assert other_res.json()["source_activity_id"] is None


def test_creatorless_private_route_is_not_visible_to_anonymous(client, db):
    from app.route_book.models import RouteBook

    route = RouteBook(
        creator_id=None,
        name="无主私密路线",
        distance=2200.0,
        reference_line="SRID=4326;LINESTRING(112.5 37.8, 112.7 37.9)",
        source="activity_derived",
        source_activity_id=None,
        city="taiyuan",
        visibility="private",
        publish_status="draft",
    )
    db.add(route)
    db.commit()
    db.refresh(route)

    res = client.get(f"/api/route-books/{route.id}")

    assert res.status_code == 404


def test_list_filters_official_route_books(client, db, test_user):
    from app.route_book.models import RouteBook

    official = RouteBook(
        creator_id=test_user.id,
        name="官方天龙山",
        distance=36000.0,
        reference_line="SRID=4326;LINESTRING(112.5 37.8, 112.6 37.9)",
        source="tencent_direction",
        city="taiyuan",
        is_official=True,
        visibility="public",
        publish_status="published",
    )
    personal = RouteBook(
        creator_id=test_user.id,
        name="我的夜骑线",
        distance=18000.0,
        reference_line="SRID=4326;LINESTRING(112.5 37.8, 112.7 37.9)",
        source="activity_derived",
        source_activity_id=None,
        city="taiyuan",
        is_official=False,
    )
    db.add_all([official, personal])
    db.commit()

    res = client.get("/api/route-books?official=true")

    assert res.status_code == 200
    assert [item["name"] for item in res.json()["items"]] == ["官方天龙山"]


def test_list_filters_non_official_route_books(client, db, test_user):
    from app.route_book.models import RouteBook

    official = RouteBook(
        creator_id=test_user.id,
        name="官方汾河线",
        distance=42000.0,
        reference_line="SRID=4326;LINESTRING(112.5 37.8, 112.6 37.9)",
        source="tencent_direction",
        city="taiyuan",
        is_official=True,
        visibility="public",
        publish_status="published",
    )
    personal = RouteBook(
        creator_id=test_user.id,
        name="我的训练线",
        distance=21000.0,
        reference_line="SRID=4326;LINESTRING(112.5 37.8, 112.7 37.9)",
        source="activity_derived",
        source_activity_id=None,
        city="taiyuan",
        is_official=False,
        visibility="public",
        publish_status="published",
    )
    db.add_all([official, personal])
    db.commit()

    res = client.get("/api/route-books?official=false")

    assert res.status_code == 200
    assert [item["name"] for item in res.json()["items"]] == ["我的训练线"]


def test_list_without_official_keeps_existing_unfiltered_behavior(client, db, test_user):
    from app.route_book.models import RouteBook

    official = RouteBook(
        creator_id=test_user.id,
        name="官方横岭",
        distance=30000.0,
        reference_line="SRID=4326;LINESTRING(112.5 37.8, 112.6 37.9)",
        source="tencent_direction",
        city="taiyuan",
        is_official=True,
        visibility="public",
        publish_status="published",
    )
    personal = RouteBook(
        creator_id=test_user.id,
        name="我的小西沟",
        distance=16000.0,
        reference_line="SRID=4326;LINESTRING(112.5 37.8, 112.7 37.9)",
        source="activity_derived",
        source_activity_id=None,
        city="taiyuan",
        is_official=False,
        visibility="public",
        publish_status="published",
    )
    db.add_all([official, personal])
    db.commit()

    res = client.get("/api/route-books")

    assert res.status_code == 200
    assert {item["name"] for item in res.json()["items"]} == {"我的小西沟", "官方横岭"}


def test_delete_route_book_is_owner_only(client, db, auth_header, admin_header, test_user):
    from app.route_book.models import RouteBook

    route = RouteBook(
        creator_id=test_user.id,
        name="可删路线",
        distance=1000.0,
        reference_line="SRID=4326;LINESTRING(112.5 37.8, 112.6 37.9)",
        source="activity_derived",
        source_activity_id=None,
        city="taiyuan",
    )
    db.add(route)
    db.commit()
    db.refresh(route)

    forbidden = client.delete(f"/api/route-books/{route.id}", headers=admin_header)
    assert forbidden.status_code == 403

    ok = client.delete(f"/api/route-books/{route.id}", headers=auth_header)
    assert ok.status_code == 204


def test_activity_candidates_only_returns_current_user_completed_cycling(client, db, auth_header, test_user, admin_user):
    own = _activity(db, test_user.id, title="自己的骑行", city="taiyuan")
    _activity(db, test_user.id, title="跑步", activity_type="running")
    _activity(db, test_user.id, title="失败上传", status="failed")
    _activity(db, admin_user.id, title="别人骑行")

    res = client.get("/api/route-books/activity-candidates", headers=auth_header)

    assert res.status_code == 200
    items = res.json()["items"]
    assert [item["id"] for item in items] == [own.id]


def test_activity_derived_rejects_non_completed_or_non_cycling(client, db, auth_header, test_user):
    # 还在处理中的活动不能衍生路书（轨迹尚未落库）
    processing = _activity(db, test_user.id, status="processing")
    res = client.post(
        "/api/route-books",
        data={"name": "未完成", "source": "activity_derived", "source_activity_id": str(processing.id)},
        headers=auth_header,
    )
    assert res.status_code == 422

    # 跑步类活动不能衍生骑行路书
    running = _activity(db, test_user.id, activity_type="running")
    res2 = client.post(
        "/api/route-books",
        data={"name": "跑步", "source": "activity_derived", "source_activity_id": str(running.id)},
        headers=auth_header,
    )
    assert res2.status_code == 422


def test_activity_derived_missing_activity_returns_404(client, auth_header):
    res = client.post(
        "/api/route-books",
        data={"name": "不存在的活动", "source": "activity_derived", "source_activity_id": "999999"},
        headers=auth_header,
    )
    assert res.status_code == 404


def test_file_upload_without_file_returns_422(client, auth_header):
    res = client.post(
        "/api/route-books",
        data={"name": "没传文件", "source": "file_upload"},
        headers=auth_header,
    )
    assert res.status_code == 422


def test_delete_tolerates_storage_failure(client, db, auth_header, test_user, monkeypatch):
    # storage 删文件失败（磁盘权限/IO）不该阻塞用户：DB 是 source of truth，记录已删即算成功。
    from app.route_book.models import RouteBook

    route = RouteBook(
        creator_id=test_user.id,
        name="带文件的路线",
        distance=1000.0,
        reference_line="SRID=4326;LINESTRING(112.5 37.8, 112.6 37.9)",
        source="file_upload",
        file_id="202605/orphan.gpx",
        file_type="gpx",
        source_activity_id=None,
        city="taiyuan",
    )
    db.add(route)
    db.commit()
    db.refresh(route)

    def boom(file_id):
        raise OSError("disk gone")

    monkeypatch.setattr("app.route_book.service._storage.delete", boom)

    res = client.delete(f"/api/route-books/{route.id}", headers=auth_header)
    assert res.status_code == 204


def test_file_upload_unparseable_returns_422_not_500(client, auth_header, monkeypatch):
    # 真实 GPX/FIT 解析器对损坏文件抛 GPXParseError(Exception)——它不继承 ValueError，
    # 若不在 service 层转译，会穿透 router 成 500。用户上传坏文件应得 422 而不是 500。
    from app.parsing.gpx_parser import GPXParseError

    monkeypatch.setattr("app.route_book.service.validate_ride_file", lambda f, b: None)

    def boom(self, content, **kw):
        raise GPXParseError("文件损坏无法解析")

    monkeypatch.setattr("app.parsing.gpx_parser.GPXParser.parse", boom)

    res = client.post(
        "/api/route-books",
        data={"name": "坏GPX", "source": "file_upload"},
        files={"file": ("x.gpx", b"whatever", "application/gpx+xml")},
        headers=auth_header,
    )
    assert res.status_code == 422


def test_create_rejects_overlong_name(client, db, auth_header, test_user):
    # name DB 列是 VARCHAR(128)；超长 name 不该走到 commit 才 DataError 500，
    # 应在请求层（Form max_length）拦成 422。
    activity = _activity(db, test_user.id)
    res = client.post(
        "/api/route-books",
        data={"name": "x" * 200, "source": "activity_derived", "source_activity_id": str(activity.id)},
        headers=auth_header,
    )
    assert res.status_code == 422


def test_get_deleted_route_book_returns_404_for_orphan_meetup_preview(client):
    """孤儿路书契约（S14-T9 集成审 I2）：约骑引用的路书被删（FK SET NULL 孤儿态）后，
    详情接口必须 404——前端约骑详情页靠这个 404 走 catch 分支把预览整块隐藏，不炸页面。"""
    res = client.get("/api/route-books/999999")
    assert res.status_code == 404
    assert "not found" in res.json()["detail"]
