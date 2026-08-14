"""约骑模块 Task 2：路书 API 测试。"""

from datetime import datetime, timezone
import json
import math
import re
import struct
from typing import get_args

import pytest

from app.activity.models import Activity, Trackpoint
from app.elevation.climb_planner import build_climb_plan
from app.main import app
from app.route_book.router import router as route_book_router
from app.route_book import schemas


# task2 阶段 route_book router 还没挂进 app.main（task4 才统一挂载所有 router）。
# 这里在测试 app 上临时挂一次，让 TestClient 能请求 /api/route-books。
# 幂等判断：多个测试文件可能都想挂，避免重复 include 同一 router。
if not any(getattr(route, "path", "") == "/api/route-books" for route in app.router.routes):
    app.include_router(route_book_router)


_TRUSTED_ELEVATION_METADATA = json.dumps(
    {
        "elevation": {
            "method": "glo30_meaningful_ascent_v1",
            "source_name": "Copernicus DEM GLO-30 Public",
            "license_id": "Copernicus DEM Licence",
            "accuracy_m": 4.0,
            "point_count": 2,
            "horizontal_resolution_m": 30.0,
            "processing_grid_m": 20.0,
            "median_filter_points": 3,
            "smoothing_sigma_m": 100.0,
            "ascent_prominence_m": 3.0,
            "ascent_minimum_span_m": 100.0,
            "maximum_processing_distance_m": 1000000.0,
            "calibration_role": "ALOS+FIT+authorized_Strava_offline_evidence",
            "dataset_id": "COP-DEM_GLO-30-DGED",
            "vertical_datum": "EGM2008 (EPSG:3855)",
            "grid_registration": "RasterPixelIsPoint",
        }
    }
)


def _trusted_metadata_with_climb_plan(distance_m: float) -> str:
    metadata = json.loads(_TRUSTED_ELEVATION_METADATA)
    elevations = [701.2, 735.8]
    metadata["climb_plan"] = build_climb_plan(
        [0.0, distance_m],
        elevations,
        source_method="glo30_meaningful_ascent_v1",
        horizontal_resolution_m=30.0,
        smoothing_variants={"80m": elevations, "150m": elevations},
    )
    return json.dumps(metadata)


def _linear_elevations(coords, *, start=700.0, end=725.0):
    """固定网格 fake：返回数量必须和生产采样点一一对应。"""
    if len(coords) == 1:
        return [float(start)]
    return [
        float(start + (end - start) * index / (len(coords) - 1))
        for index, _coord in enumerate(coords)
    ]


def _piecewise_elevations(coords, controls):
    """按经度构造可复现坡形，避免把三点旧查询假装成固定 20m 网格。"""
    controls = sorted((float(lon), float(ele)) for lon, ele in controls)
    result = []
    for _lat, lon in coords:
        if lon <= controls[0][0]:
            result.append(controls[0][1])
            continue
        if lon >= controls[-1][0]:
            result.append(controls[-1][1])
            continue
        for (left_lon, left_ele), (right_lon, right_ele) in zip(controls, controls[1:]):
            if left_lon <= lon <= right_lon:
                ratio = (lon - left_lon) / (right_lon - left_lon)
                result.append(left_ele + (right_ele - left_ele) * ratio)
                break
    return result


def _assert_version_uses_strict_glo_contract(version, expected_elevation):
    """通用创建入口也必须保存和手画路线相同的唯一 GLO 成品。"""
    assert version.climb == pytest.approx(expected_elevation.climb)
    assert json.loads(version.elevation_profile) == expected_elevation.profile
    assert json.loads(version.elevation_points_snapshot) == expected_elevation.snapshot
    assert version.point_count == expected_elevation.point_count

    elevation_metadata = json.loads(version.navigation_metadata_json)["elevation"]
    generated_at = elevation_metadata.pop("generated_at")
    datetime.fromisoformat(generated_at)
    expected_metadata = json.loads(_TRUSTED_ELEVATION_METADATA)["elevation"]
    expected_metadata["point_count"] = expected_elevation.point_count
    assert elevation_metadata == expected_metadata


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
    assert "strava_projection" in get_args(schemas.RouteBookSource)
    assert "strava_projection" not in get_args(schemas.RouteBookCreateSource)


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

    # 这些测试要验证导出坐标真来自 reference_line；SQLite 默认假 EWKB 会掩盖错配。
    _install_dynamic_linestring_ewkb_stub(db)
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
        elevation_points_snapshot="[[112.5,37.8,701.2],[112.6,37.9,735.8]]",
        navigation_metadata_json=_trusted_metadata_with_climb_plan(route.distance),
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

    def delete(self, file_id):
        return self.files.pop(file_id, None) is not None


def _install_dynamic_linestring_ewkb_stub(db):
    def ewkb_from_ewkt(value):
        text = str(value or "")
        match = re.search(r"LINESTRING\s*\((.+)\)", text, re.IGNORECASE)
        if not match:
            return "0102000020E610000000000000"
        points = []
        for pair in match.group(1).split(","):
            parts = pair.strip().split()
            if len(parts) < 2:
                continue
            points.append((float(parts[0]), float(parts[1])))
        data = struct.pack("<BII", 1, 0x20000000 | 2, 4326)
        data += struct.pack("<I", len(points))
        for lon, lat in points:
            data += struct.pack("<dd", lon, lat)
        return data.hex()

    raw_connection = db.connection().connection
    driver_connection = getattr(raw_connection, "driver_connection", raw_connection)
    driver_connection.create_function("AsEWKB", 1, ewkb_from_ewkt)
    driver_connection.create_function("ST_AsEWKB", 1, ewkb_from_ewkt)


def test_public_strava_projection_is_listable_and_readable(client, db, admin_user):
    route, _version = _route_with_current_version(
        db,
        admin_user.id,
        name="奥申完整赛段投影",
        source="strava_projection",
        file_id="strava:module:taiyuan_xishan_wanmu_aoshen",
        file_type=None,
    )

    listed = client.get("/api/route-books?city=taiyuan")
    assert listed.status_code == 200
    item = next(row for row in listed.json()["items"] if row["id"] == route.id)
    assert item["source"] == "strava_projection"

    detail = client.get(f"/api/route-books/{route.id}")
    assert detail.status_code == 200
    assert detail.json()["source"] == "strava_projection"


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
    version.elevation_points_snapshot = "[[112.5,37.8,701.2],[112.6,37.9,735.8]]"
    db.add(version)
    db.commit()
    monkeypatch.setattr("app.route_book.export_workflow._storage", _FakeExportStorage())

    created = client.post(f"/api/route-books/{route.id}/exports", json={"format": "gpx"})
    download = client.get(created.json()["download_url"])

    assert download.status_code == 200
    assert b"<ele>701.2</ele>" in download.content
    assert b"<ele>735.8</ele>" in download.content


def test_route_export_rejects_route_without_complete_elevation_snapshot(client, db, admin_user):
    route, version = _route_with_current_version(db, admin_user.id)
    version.elevation_points_snapshot = None
    db.add(version)
    db.commit()

    res = client.post(f"/api/route-books/{route.id}/exports", json={"format": "gpx"})

    assert res.status_code == 422
    assert "海拔" in res.json()["detail"]


def test_route_export_rejects_complete_but_untrusted_elevation_snapshot(client, db, admin_user):
    route, version = _route_with_current_version(db, admin_user.id)
    version.navigation_metadata_json = None
    db.add(version)
    db.commit()

    res = client.post(f"/api/route-books/{route.id}/exports", json={"format": "gpx"})

    assert res.status_code == 422
    assert "统一海拔源" in res.json()["detail"]


def test_route_export_rejects_glo_method_label_without_full_algorithm_contract(
    client,
    db,
    admin_user,
):
    route, version = _route_with_current_version(db, admin_user.id)
    version.navigation_metadata_json = json.dumps(
        {
            "elevation": {
                "method": "glo30_meaningful_ascent_v1",
                "source_name": "Copernicus DEM GLO-30 Public",
                "license_id": "Copernicus DEM Licence",
                "accuracy_m": 4.0,
                "point_count": 2,
            }
        }
    )
    db.add(version)
    db.commit()

    res = client.post(f"/api/route-books/{route.id}/exports", json={"format": "gpx"})

    assert res.status_code == 422
    assert "统一海拔源" in res.json()["detail"]


def test_route_export_allows_authorized_csv_elevation_snapshot(client, db, admin_user, monkeypatch):
    route, version = _route_with_current_version(db, admin_user.id)
    version.navigation_metadata_json = json.dumps(
        {
            "elevation": {
                "method": "authorized_point_elevation_csv_v1",
                "source_name": "国内合规高程供应商",
                "license_id": "contract-2026-001",
                "accuracy_m": 5.0,
                "point_count": 2,
            }
        }
    )
    db.add(version)
    db.commit()
    monkeypatch.setattr("app.route_book.export_workflow._storage", _FakeExportStorage())

    res = client.post(f"/api/route-books/{route.id}/exports", json={"format": "gpx"})

    assert res.status_code == 200


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


def test_route_export_download_rejects_artifact_after_elevation_snapshot_changes(
    client,
    db,
    admin_user,
    monkeypatch,
):
    route, version = _route_with_current_version(db, admin_user.id)
    monkeypatch.setattr("app.route_book.export_workflow._storage", _FakeExportStorage())
    created = client.post(f"/api/route-books/{route.id}/exports", json={"format": "gpx"}).json()

    # 模拟同一 RouteVersion 被新版底座回填；旧文件仍在存储中，但不能继续下载。
    version.elevation_points_snapshot = "[[112.5,37.8,710.0],[112.6,37.9,744.0]]"
    db.add(version)
    db.commit()

    res = client.get(created["download_url"])

    assert res.status_code == 404
    assert "stale" in res.json()["detail"]


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


def test_activity_derived_creates_route_book(client, db, auth_header, test_user, monkeypatch):
    from app.elevation.route_elevation import build_route_elevation_result
    from app.route_book.models import RouteBook, RouteVersion

    # Activity/FIT 的海拔只用于离线拟合，不能直接成为公共路线的产品海拔。
    activity = _activity(db, test_user.id, city="taiyuan", elevation_gain=9876.0)
    db.query(Trackpoint).filter(Trackpoint.activity_id == activity.id, Trackpoint.seq == 0).update({"elevation": 111.0})
    db.query(Trackpoint).filter(Trackpoint.activity_id == activity.id, Trackpoint.seq == 1).update({"elevation": 222.0})
    db.commit()

    queried = []

    def fake_query(coords):
        queried.append(coords)
        return _linear_elevations(coords, start=800.0, end=850.0)

    monkeypatch.setattr("app.route_book.service.query_elevations", fake_query, raising=False)

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

    expected_elevation = build_route_elevation_result(
        [[112.5, 37.8], [112.6, 37.9]],
        query_func=lambda coords: _linear_elevations(coords, start=800.0, end=850.0),
    )
    assert len(queried) == 1
    assert len(queried[0]) > 2  # 证明不是只给原始两点补高度，而是走统一约 20m 物理网格。
    assert body["climb"] == pytest.approx(expected_elevation.climb)
    assert body["climb"] != pytest.approx(activity.elevation_gain)
    assert body["elevation_ready"] is True
    assert body["elevation_profile"] == expected_elevation.profile

    route = db.query(RouteBook).filter(RouteBook.id == body["id"]).one()
    version = db.query(RouteVersion).filter(RouteVersion.route_book_id == route.id).one()
    assert route.current_version_id == version.id
    assert route.line_hash == version.line_hash
    assert version.version_no == 1
    assert version.status == "current"
    assert version.navigation_status == "ready"
    assert version.geometry_source == "activity_derived"
    assert route.climb == pytest.approx(expected_elevation.climb)
    assert json.loads(route.elevation_profile) == expected_elevation.profile
    _assert_version_uses_strict_glo_contract(version, expected_elevation)
    assert json.loads(version.elevation_points_snapshot) != [
        [112.5, 37.8, 111.0],
        [112.6, 37.9, 222.0],
    ]


def test_file_upload_supports_gpx_and_preserves_file_id(client, db, auth_header, monkeypatch):
    from app.elevation.route_elevation import build_route_elevation_result

    class FakeStorage:
        def upload(self, file_bytes, filename):
            assert filename == "route.gpx"
            return "202605/route.gpx"

    monkeypatch.setattr("app.route_book.service._storage", FakeStorage())
    monkeypatch.setattr("app.route_book.service._parse_route_file", lambda filename, b: {
        "distance": 1234.0,
        "climb": 9876.0,
        "city": "taiyuan",
        "wkt": "SRID=4326;LINESTRING(112.5 37.8, 112.6 37.9)",
        "elevation_points_snapshot": "[[112.5,37.8,111.0],[112.6,37.9,222.0]]",
    })
    monkeypatch.setattr(
        "app.route_book.service.query_elevations",
        lambda coords: _linear_elevations(coords, start=900.0, end=960.0),
        raising=False,
    )

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

    expected_elevation = build_route_elevation_result(
        [[112.5, 37.8], [112.6, 37.9]],
        query_func=lambda coords: _linear_elevations(coords, start=900.0, end=960.0),
    )
    assert body["climb"] == pytest.approx(expected_elevation.climb)
    assert body["climb"] != pytest.approx(9876.0)
    assert body["elevation_ready"] is True
    assert body["elevation_profile"] == expected_elevation.profile
    version = db.query(RouteVersion).filter(RouteVersion.route_book_id == body["id"]).one()
    _assert_version_uses_strict_glo_contract(version, expected_elevation)
    assert json.loads(version.elevation_points_snapshot) != [
        [112.5, 37.8, 111.0],
        [112.6, 37.9, 222.0],
    ]


def test_file_upload_supports_fit_and_preserves_file_id(client, db, auth_header, monkeypatch):
    from app.elevation.route_elevation import build_route_elevation_result
    from app.route_book.models import RouteVersion

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
    monkeypatch.setattr(
        "app.route_book.service.query_elevations",
        lambda coords: _linear_elevations(coords, start=700.0, end=735.0),
        raising=False,
    )

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
    expected_elevation = build_route_elevation_result(
        [[112.5, 37.8], [112.6, 37.9]],
        query_func=lambda coords: _linear_elevations(coords, start=700.0, end=735.0),
    )
    version = db.query(RouteVersion).filter(RouteVersion.route_book_id == body["id"]).one()
    _assert_version_uses_strict_glo_contract(version, expected_elevation)


def test_activity_derived_maps_glo_failure_to_503(client, db, auth_header, test_user, monkeypatch):
    from app.elevation.dem_client import DEMServiceError
    from app.route_book.models import RouteBook

    activity = _activity(db, test_user.id)

    def fail_query(_coords):
        raise DEMServiceError("测试 GLO 瓦片不可用")

    monkeypatch.setattr("app.route_book.service.query_elevations", fail_query, raising=False)

    res = client.post(
        "/api/route-books",
        data={"name": "活动海拔失败", "source": "activity_derived", "source_activity_id": str(activity.id)},
        headers=auth_header,
    )

    assert res.status_code == 503
    assert "路线海拔查询失败" in res.text
    assert "测试 GLO 瓦片不可用" in res.text
    assert db.query(RouteBook).filter(RouteBook.name == "活动海拔失败").first() is None


def test_file_upload_glo_failure_deletes_uploaded_file(client, db, auth_header, monkeypatch):
    from app.elevation.dem_client import DEMServiceError
    from app.route_book.models import RouteBook

    class FakeStorage:
        def __init__(self):
            self.uploaded = []
            self.deleted = []

        def upload(self, file_bytes, filename):
            self.uploaded.append((file_bytes, filename))
            return "202605/glo-failure.gpx"

        def delete(self, file_id):
            self.deleted.append(file_id)

    storage = FakeStorage()
    monkeypatch.setattr("app.route_book.service._storage", storage)
    monkeypatch.setattr("app.route_book.service._parse_route_file", lambda filename, b: {
        "distance": 1234.0,
        "climb": 50.0,
        "city": "taiyuan",
        "wkt": "SRID=4326;LINESTRING(112.5 37.8, 112.6 37.9)",
        "elevation_points_snapshot": "[[112.5,37.8,111.0],[112.6,37.9,222.0]]",
    })

    def fail_query(_coords):
        raise DEMServiceError("测试 GLO 瓦片不可用")

    monkeypatch.setattr("app.route_book.service.query_elevations", fail_query, raising=False)

    res = client.post(
        "/api/route-books",
        data={"name": "上传海拔失败", "source": "file_upload"},
        files={"file": ("route.gpx", b"<gpx></gpx>", "application/gpx+xml")},
        headers=auth_header,
    )

    assert res.status_code == 503
    assert "路线海拔查询失败" in res.text
    assert storage.uploaded == [(b"<gpx></gpx>", "route.gpx")]
    assert storage.deleted == ["202605/glo-failure.gpx"]
    assert db.query(RouteBook).filter(RouteBook.name == "上传海拔失败").first() is None


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
    from app.elevation.route_elevation import build_route_elevation_result
    from app.route_book.models import RouteBook, RouteVersion

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
    monkeypatch.setattr(
        "app.route_book.service.query_elevations",
        _linear_elevations,
        raising=False,
    )

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
    expected_elevation = build_route_elevation_result(
        expected_preview_points,
        query_func=_linear_elevations,
    )
    assert body["elevation_ready"] is True
    assert body["climb"] == pytest.approx(expected_elevation.climb)
    assert len(body["elevation_profile"]) == len(expected_elevation.profile)
    for actual, expected in zip(body["elevation_profile"], expected_elevation.profile):
        assert actual == pytest.approx(expected)

    route = db.query(RouteBook).filter(RouteBook.id == body["id"]).first()
    assert route is not None
    assert route.distance == 6800.0
    assert route.source == "tencent_direction"
    assert route.climb == pytest.approx(expected_elevation.climb)
    assert json.loads(route.elevation_profile) == expected_elevation.profile

    version = db.query(RouteVersion).filter(RouteVersion.id == route.current_version_id).one()
    assert version.climb == pytest.approx(expected_elevation.climb)
    assert json.loads(version.elevation_profile) == expected_elevation.profile
    assert json.loads(version.elevation_points_snapshot) == expected_elevation.snapshot
    assert version.point_count == expected_elevation.point_count

    elevation_metadata = json.loads(version.navigation_metadata_json)["elevation"]
    generated_at = elevation_metadata.pop("generated_at")
    datetime.fromisoformat(generated_at)
    expected_metadata = json.loads(_TRUSTED_ELEVATION_METADATA)["elevation"]
    expected_metadata["point_count"] = expected_elevation.point_count
    assert elevation_metadata == expected_metadata


def test_tencent_direction_maps_glo_failure_to_503(client, db, auth_header, monkeypatch):
    from app.elevation.dem_client import DEMServiceError
    from app.route_book.models import RouteBook

    monkeypatch.setattr(
        "app.route_book.service.plan_tencent_bicycling_route",
        lambda _start, _end: {
            "distance": 6800.0,
            "duration": 28,
            "points": [
                {"lat": 37.8001, "lon": 112.5001},
                {"lat": 37.8601, "lon": 112.5601},
            ],
        },
    )

    def fail_query(_coords):
        raise DEMServiceError("测试瓦片不可用")

    monkeypatch.setattr("app.route_book.service.query_elevations", fail_query, raising=False)

    res = client.post(
        "/api/route-books/tencent-direction",
        json={
            "name": "海拔失败路线",
            "from_lat": 37.8001,
            "from_lon": 112.5001,
            "to_lat": 37.8601,
            "to_lon": 112.5601,
        },
        headers=auth_header,
    )

    assert res.status_code == 503
    assert "路线海拔查询失败" in res.text
    assert "测试瓦片不可用" in res.text
    assert db.query(RouteBook).filter(RouteBook.name == "海拔失败路线").first() is None


def test_manual_drawn_route_creates_route_with_elevation_profile(client, db, auth_header, monkeypatch):
    from app.route_book.models import RouteBook, RouteVersion

    calls = []

    def fake_query(coords):
        calls.append(coords)
        return _piecewise_elevations(
            coords,
            [(112.5, 700.0), (112.55, 725.0), (112.6, 720.0)],
        )

    monkeypatch.setattr("app.route_book.service.query_elevations", fake_query, raising=False)

    res = client.post(
        "/api/route-books/manual-drawn",
        json={
            "name": "手画山地绕圈",
            "client_request_id": "test-manual-drawn-mountain-loop",
            "points": [
                [112.5, 37.8],
                [112.55, 37.85],
                [112.6, 37.9],
            ],
        },
        headers=auth_header,
    )

    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "手画山地绕圈"
    assert body["source"] == "manual_drawn"
    assert body["file_id"] is None
    assert body["file_type"] is None
    assert body["source_activity_id"] is None
    assert body["preview_points"] == [[112.5, 37.8], [112.55, 37.85], [112.6, 37.9]]
    assert body["elevation_ready"] is True
    assert body["elevation_profile"][0][0] == 0.0
    assert body["elevation_profile"][0][1] == pytest.approx(700.1)
    assert body["elevation_profile"][-1][1] == pytest.approx(720.0)
    assert body["climb"] == pytest.approx(24.8)
    assert len(calls) == 1
    assert len(calls[0]) == math.ceil(body["distance"] / 20.0) + 1
    assert calls[0][0] == pytest.approx((37.8, 112.5))
    assert calls[0][-1] == pytest.approx((37.9, 112.6))

    route = db.query(RouteBook).filter(RouteBook.id == body["id"]).one()
    version = db.query(RouteVersion).filter(RouteVersion.id == body["current_version_id"]).one()
    metadata = json.loads(version.navigation_metadata_json)
    assert route.source == "manual_drawn"
    assert route.current_version_id == version.id
    assert json.loads(version.elevation_points_snapshot) == [
        [112.5, 37.8, 700.1],
        [112.55, 37.85, 724.8],
        [112.6, 37.9, 720.0],
    ]
    assert metadata["elevation"]["method"] == "glo30_meaningful_ascent_v1"
    assert metadata["elevation"]["processing_grid_m"] == 20.0
    assert metadata["elevation"]["point_count"] == 3


def test_manual_drawn_route_reuses_same_client_request_without_duplicate(
    client, db, auth_header, monkeypatch
):
    from app.route_book.models import RouteBook, RouteBookSaveRequest, RouteVersion

    query_calls = []

    def fake_query(coords):
        query_calls.append(coords)
        return _linear_elevations(coords, start=700.0, end=710.0)

    monkeypatch.setattr("app.route_book.service.query_elevations", fake_query, raising=False)
    payload = {
        "name": "响应丢失恢复路线",
        "client_request_id": "test-manual-response-loss-recovery",
        "points": [[112.5, 37.8], [112.6, 37.9]],
    }

    first = client.post("/api/route-books/manual-drawn", json=payload, headers=auth_header)
    retried = client.post("/api/route-books/manual-drawn", json=payload, headers=auth_header)

    assert first.status_code == 200
    assert retried.status_code == 200
    assert retried.json()["id"] == first.json()["id"]
    assert len(query_calls) == 1
    assert query_calls[0][0] == pytest.approx((37.8, 112.5))
    assert query_calls[0][-1] == pytest.approx((37.9, 112.6))
    assert (
        db.query(RouteBookSaveRequest)
        .filter(RouteBookSaveRequest.client_request_id == payload["client_request_id"])
        .count()
        == 1
    )
    assert db.query(RouteVersion).filter(RouteVersion.route_book_id == first.json()["id"]).count() == 1


def test_manual_drawn_route_rejects_same_client_request_for_different_payload(
    client, auth_header, monkeypatch
):
    request_id = "test-manual-idempotency-conflict"
    monkeypatch.setattr(
        "app.route_book.service.query_elevations",
        lambda coords: [700.0 for _coord in coords],
        raising=False,
    )
    first = client.post(
        "/api/route-books/manual-drawn",
        json={
            "name": "原路线",
            "client_request_id": request_id,
            "points": [[112.5, 37.8], [112.6, 37.9]],
        },
        headers=auth_header,
    )
    conflict = client.post(
        "/api/route-books/manual-drawn",
        json={
            "name": "另一条路线",
            "client_request_id": request_id,
            "points": [[112.5, 37.8], [112.7, 37.9]],
        },
        headers=auth_header,
    )

    assert first.status_code == 200
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "保存记录冲突，请重新确认路线"
    assert request_id not in conflict.text


def test_deleted_manual_route_cannot_be_recreated_by_late_request(
    client, db, auth_header, monkeypatch
):
    from app.route_book.models import RouteBook, RouteBookSaveRequest

    monkeypatch.setattr(
        "app.route_book.service.query_elevations",
        lambda coords: [700.0 for _coord in coords],
        raising=False,
    )
    payload = {
        "name": "删除后不得复活",
        "client_request_id": "test-manual-deleted-route-tombstone",
        "points": [[112.5, 37.8], [112.6, 37.9]],
    }
    created = client.post("/api/route-books/manual-drawn", json=payload, headers=auth_header)
    assert created.status_code == 200
    route_id = created.json()["id"]

    deleted = client.delete(f"/api/route-books/{route_id}", headers=auth_header)
    replayed = client.post("/api/route-books/manual-drawn", json=payload, headers=auth_header)

    assert deleted.status_code == 204
    assert replayed.status_code == 410
    assert replayed.json()["detail"] == "上次保存的路线已删除，请重新保存"
    assert db.query(RouteBook).filter(RouteBook.id == route_id).count() == 0
    save_request = (
        db.query(RouteBookSaveRequest)
        .filter(RouteBookSaveRequest.client_request_id == payload["client_request_id"])
        .one()
    )
    assert save_request.route_book_id is None


def test_deleted_user_token_cannot_create_manual_route(
    client, db, auth_header, test_user, monkeypatch
):
    from app.route_book.models import RouteBook, RouteBookSaveRequest

    elevation_called = False

    def fake_query(_coords):
        nonlocal elevation_called
        elevation_called = True
        return [700.0, 710.0]

    monkeypatch.setattr("app.route_book.service.query_elevations", fake_query, raising=False)
    db.delete(test_user)
    db.commit()

    response = client.post(
        "/api/route-books/manual-drawn",
        json={
            "name": "注销后的幽灵路线",
            "client_request_id": "test-deleted-user-token-manual-draw",
            "points": [[112.5, 37.8], [112.6, 37.9]],
        },
        headers=auth_header,
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "用户不存在或已注销"
    assert elevation_called is False
    assert db.query(RouteBook).count() == 0
    assert db.query(RouteBookSaveRequest).count() == 0


def test_manual_draw_does_not_hide_unrelated_integrity_error(
    db, test_user, monkeypatch
):
    from sqlalchemy.exc import IntegrityError

    from app.route_book import service

    class OtherConstraintError(Exception):
        class Diag:
            constraint_name = "uq_some_other_business_rule"

        diag = Diag()

    monkeypatch.setattr(service, "query_elevations", lambda coords: [700.0 for _coord in coords])

    def fail_flush():
        raise IntegrityError("INSERT", {}, OtherConstraintError())

    monkeypatch.setattr(db, "flush", fail_flush)

    with pytest.raises(IntegrityError):
        service.create_route_book_from_manual_drawn(
            db=db,
            current_user_id=test_user.id,
            name="不应吞掉约束错误",
            client_request_id="test-unrelated-integrity-error",
            points=[(112.5, 37.8), (112.6, 37.9)],
        )


def test_manual_drawn_route_accepts_gcj02_and_stores_draw_metadata(client, db, auth_header, monkeypatch):
    from app.route_book.models import RouteBook, RouteVersion

    convert_calls = []
    elevation_calls = []

    def fake_convert(points, coordinate_system):
        convert_calls.append((points, coordinate_system))
        return [
            {"lon": 112.4936, "lat": 37.7994},
            {"lon": 112.5437, "lat": 37.8495},
            {"lon": 112.5938, "lat": 37.8996},
        ]

    def fake_query(coords):
        elevation_calls.append(coords)
        return _piecewise_elevations(
            coords,
            [(112.4936, 700.0), (112.5437, 725.0), (112.5938, 720.0)],
        )

    monkeypatch.setattr("app.route_book.service.convert_points_to_wgs84", fake_convert)
    monkeypatch.setattr("app.route_book.service.query_elevations", fake_query, raising=False)

    res = client.post(
        "/api/route-books/manual-drawn",
        json={
            "name": "贴路后保存",
            "client_request_id": "test-manual-drawn-snapped-save",
            "coordinate_system": "gcj02",
            "points": [
                [112.5, 37.8],
                [112.55, 37.85],
                [112.6, 37.9],
            ],
            "draw_metadata": {
                "tool": "route_draw_v0",
                "snap_provider": "tencent_bicycling",
                "segment_count": 2,
                "freehand_segment_count": 1,
                "warnings": ["第一段贴路偏移较大"],
                "raw_points_summary": {
                    "total_raw_points": 6,
                    "sample": [[112.5, 37.8], [112.6, 37.9]],
                },
            },
        },
        headers=auth_header,
    )

    assert res.status_code == 200
    body = res.json()
    assert body["source"] == "manual_drawn"
    assert body["preview_points"] == [
        [112.4936, 37.7994],
        [112.5437, 37.8495],
        [112.5938, 37.8996],
    ]
    assert convert_calls == [(
        [
            {"lon": 112.5, "lat": 37.8},
            {"lon": 112.55, "lat": 37.85},
            {"lon": 112.6, "lat": 37.9},
        ],
        "gcj02",
    )]
    assert len(elevation_calls) == 1
    assert elevation_calls[0][0] == pytest.approx((37.7994, 112.4936))
    assert elevation_calls[0][-1] == pytest.approx((37.8996, 112.5938))

    route = db.query(RouteBook).filter(RouteBook.id == body["id"]).one()
    version = db.query(RouteVersion).filter(RouteVersion.id == body["current_version_id"]).one()
    metadata = json.loads(version.navigation_metadata_json)
    assert route.source == "manual_drawn"
    assert version.geometry_source == "manual_drawn"
    assert json.loads(version.elevation_points_snapshot) == [
        [112.4936, 37.7994, 700.1],
        [112.5437, 37.8495, 724.8],
        [112.5938, 37.8996, 720.0],
    ]
    assert metadata["draw"] == {
        "tool": "route_draw_v0",
        "snap_provider": "tencent_bicycling",
        "segment_count": 2,
        "freehand_segment_count": 1,
        "warnings": ["第一段贴路偏移较大"],
        "raw_points_summary": {
            "total_raw_points": 6,
            "sample": [[112.5, 37.8], [112.6, 37.9]],
        },
    }
    assert metadata["elevation"]["method"] == "glo30_meaningful_ascent_v1"
    assert metadata["elevation"]["processing_grid_m"] == 20.0


def test_manual_draw_releases_database_transaction_while_glo_fetches(
    client,
    db,
    auth_header,
    monkeypatch,
):
    transaction_states = []

    def fake_query(coords):
        transaction_states.append(db.in_transaction())
        return [700.0 for _coord in coords]

    monkeypatch.setattr("app.route_book.service.query_elevations", fake_query, raising=False)

    response = client.post(
        "/api/route-books/manual-drawn",
        json={
            "name": "GLO 下载不占数据库事务",
            "client_request_id": "test-manual-draw-no-db-transaction-during-glo",
            "points": [[112.5, 37.8], [112.6, 37.9]],
        },
        headers=auth_header,
    )

    assert response.status_code == 200
    assert transaction_states == [False]


def test_route_draw_v0_mock_verification_runs_100_snap_save_elevation_detail_flows(
    client,
    auth_header,
    monkeypatch,
):
    snap_calls = []
    convert_calls = []
    elevation_calls = []
    route_ids = []

    def fake_plan(start, end, timeout_sec=None):
        snap_calls.append((start, end, timeout_sec))
        return {
            "distance": 180.0,
            "duration": 1,
            "points": [
                {"lat": start[0], "lon": start[1]},
                {"lat": round((start[0] + end[0]) / 2, 6), "lon": round((start[1] + end[1]) / 2, 6)},
                {"lat": end[0], "lon": end[1]},
            ],
        }

    def fake_convert(points, coordinate_system):
        convert_calls.append((points, coordinate_system))
        return [
            {"lon": round(point["lon"] - 0.0064, 6), "lat": round(point["lat"] - 0.0006, 6)}
            for point in points
        ]

    def fake_query(coords):
        elevation_calls.append(coords)
        return [round(700.0 + index * 3.5, 1) for index, _coord in enumerate(coords)]

    monkeypatch.setattr("app.route_book.draw_snap_service.plan_tencent_bicycling_route", fake_plan)
    monkeypatch.setattr("app.route_book.service.convert_points_to_wgs84", fake_convert)
    monkeypatch.setattr("app.route_book.service.query_elevations", fake_query, raising=False)

    for index in range(100):
        base_lon = 112.5000 + (index % 10) * 0.002
        base_lat = 37.8000 + (index // 10) * 0.002
        raw_points = [
            [round(base_lon, 6), round(base_lat, 6)],
            [round(base_lon + 0.001, 6), round(base_lat + 0.0006, 6)],
            [round(base_lon + 0.002, 6), round(base_lat + 0.0012, 6)],
        ]

        snap = client.post(
            "/api/route-books/manual-drawn/snap-preview",
            json={
                "coordinate_system": "gcj02",
                "mode": "snap",
                "points": raw_points,
            },
            headers=auth_header,
        )
        assert snap.status_code == 200
        snap_body = snap.json()
        assert snap_body["snapped_points"]
        assert snap_body["segment_count"] >= 1

        saved = client.post(
            "/api/route-books/manual-drawn",
            json={
                "name": f"Task6 虚拟手画路线 {index + 1}",
                "client_request_id": f"test-task6-virtual-route-{index + 1:03d}",
                "coordinate_system": "gcj02",
                "points": snap_body["snapped_points"],
                "draw_metadata": {
                    "tool": "route_draw_v0",
                    "snap_provider": "tencent_bicycling",
                    "segment_count": snap_body["segment_count"],
                    "freehand_segment_count": 0,
                    "warnings": snap_body["warnings"],
                    "raw_points_summary": {
                        "total_raw_points": len(raw_points),
                        "sample": raw_points[:2],
                    },
                },
            },
            headers=auth_header,
        )
        assert saved.status_code == 200
        saved_body = saved.json()
        assert saved_body["source"] == "manual_drawn"
        assert saved_body["current_version_id"] is not None
        assert saved_body["elevation_ready"] is True
        assert len(saved_body["preview_points"]) == len(snap_body["snapped_points"])
        expected_profile_count = min(100, math.ceil(saved_body["distance"] / 20.0) + 1)
        assert len(saved_body["elevation_profile"]) == expected_profile_count

        detail = client.get(f"/api/route-books/{saved_body['id']}/detail", headers=auth_header)
        assert detail.status_code == 200
        detail_body = detail.json()
        assert detail_body["id"] == saved_body["id"]
        assert detail_body["export_ready"] is True
        assert detail_body["export_formats"] == ["gpx", "tcx"]
        route_ids.append(saved_body["id"])

    assert len(route_ids) == 100
    assert len(set(route_ids)) == 100
    assert len(snap_calls) >= 100
    assert len(convert_calls) == 100
    assert len(elevation_calls) == 100


def test_route_draw_v0_manual_drawn_export_gpx_tcx_include_three_elevation_points(
    client,
    db,
    auth_header,
    monkeypatch,
):
    fake_storage = _FakeExportStorage()
    _install_dynamic_linestring_ewkb_stub(db)

    def fake_convert(points, coordinate_system):
        assert coordinate_system == "gcj02"
        return [{"lon": point["lon"], "lat": point["lat"]} for point in points]

    def fake_query(coords):
        return _piecewise_elevations(
            coords,
            [(112.5, 701.2), (112.55, 735.8), (112.6, 742.4)],
        )

    monkeypatch.setattr("app.route_book.service.convert_points_to_wgs84", fake_convert)
    monkeypatch.setattr("app.route_book.service.query_elevations", fake_query, raising=False)
    monkeypatch.setattr("app.route_book.export_workflow._storage", fake_storage)

    freehand = client.post(
        "/api/route-books/manual-drawn/snap-preview",
        json={
            "coordinate_system": "gcj02",
            "mode": "freehand",
            "points": [
                [112.5, 37.8],
                [112.55, 37.85],
                [112.6, 37.9],
            ],
        },
        headers=auth_header,
    )
    assert freehand.status_code == 200
    assert freehand.json()["mode"] == "freehand"

    created = client.post(
        "/api/route-books/manual-drawn",
        json={
            "name": "Task6 三点自由画线导出",
            "client_request_id": "test-task6-freehand-export-route",
            "coordinate_system": "gcj02",
            "points": freehand.json()["snapped_points"],
            "draw_metadata": {
                "tool": "route_draw_v0",
                "snap_provider": "freehand",
                "segment_count": freehand.json()["segment_count"],
                "freehand_segment_count": freehand.json()["segment_count"],
            },
        },
        headers=auth_header,
    )
    assert created.status_code == 200
    route_id = created.json()["id"]
    assert created.json()["elevation_ready"] is True

    detail = client.get(f"/api/route-books/{route_id}/detail", headers=auth_header)
    assert detail.status_code == 200
    assert detail.json()["export_ready"] is True

    gpx = client.post(f"/api/route-books/{route_id}/exports", json={"format": "gpx"}, headers=auth_header)
    tcx = client.post(f"/api/route-books/{route_id}/exports", json={"format": "tcx"}, headers=auth_header)
    assert gpx.status_code == 200, gpx.text
    assert tcx.status_code == 200, tcx.text

    gpx_download = client.get(gpx.json()["download_url"], headers=auth_header)
    tcx_download = client.get(tcx.json()["download_url"], headers=auth_header)
    assert gpx_download.status_code == 200
    assert tcx_download.status_code == 200
    from app.route_book.models import RouteVersion

    version = db.query(RouteVersion).filter(RouteVersion.id == created.json()["current_version_id"]).one()
    exported_elevations = [point[2] for point in json.loads(version.elevation_points_snapshot)]
    assert gpx_download.content.count(b"<ele>") == 3
    assert tcx_download.content.count(b"<AltitudeMeters>") == 3
    for elevation in exported_elevations:
        encoded = str(elevation).encode()
        assert b"<ele>" + encoded + b"</ele>" in gpx_download.content
        assert b"<AltitudeMeters>" + encoded + b"</AltitudeMeters>" in tcx_download.content


def test_manual_drawn_route_rejects_bad_gcj02_conversion_before_insert(client, db, auth_header, monkeypatch):
    from app.route_book.models import RouteBook

    convert_calls = []
    elevation_calls = []

    def fake_convert(points, coordinate_system):
        convert_calls.append((points, coordinate_system))
        return [
            {"lon": 37.8, "lat": 112.5},
            {"lon": 37.9, "lat": 112.6},
        ]

    def fake_query(coords):
        elevation_calls.append(coords)
        return [700.0 for _ in coords]

    monkeypatch.setattr("app.route_book.service.convert_points_to_wgs84", fake_convert)
    monkeypatch.setattr("app.route_book.service.query_elevations", fake_query, raising=False)

    res = client.post(
        "/api/route-books/manual-drawn",
        json={
            "name": "转换后坏坐标",
            "client_request_id": "test-manual-bad-converted-coordinate",
            "coordinate_system": "gcj02",
            "points": [[112.5, 37.8], [112.6, 37.9]],
        },
        headers=auth_header,
    )

    assert res.status_code == 422
    assert "超出经纬度范围" in res.text
    assert convert_calls
    assert elevation_calls == []
    assert db.query(RouteBook).filter(RouteBook.name == "转换后坏坐标").first() is None


def test_manual_drawn_route_rejects_oversized_draw_metadata_before_insert(client, db, auth_header, monkeypatch):
    from app.route_book.models import RouteBook

    elevation_calls = []

    def fake_query(coords):
        elevation_calls.append(coords)
        return [700.0 for _ in coords]

    monkeypatch.setattr("app.route_book.service.query_elevations", fake_query, raising=False)

    res = client.post(
        "/api/route-books/manual-drawn",
        json={
            "name": "元数据太大",
            "client_request_id": "test-manual-oversized-metadata",
            "points": [[112.5, 37.8], [112.6, 37.9]],
            "draw_metadata": {
                "tool": "route_draw_v0",
                "warnings": ["x" * 9000],
            },
        },
        headers=auth_header,
    )

    assert res.status_code == 422
    assert "draw_metadata" in res.text
    assert elevation_calls == []
    assert db.query(RouteBook).filter(RouteBook.name == "元数据太大").first() is None


def test_route_book_detail_returns_elevation_profile_for_owner(client, auth_header, monkeypatch):
    def fake_query(coords):
        return _linear_elevations(coords, start=700.0, end=725.0)

    monkeypatch.setattr("app.route_book.service.query_elevations", fake_query, raising=False)

    created = client.post(
        "/api/route-books/manual-drawn",
        json={
            "name": "详情有海拔",
            "client_request_id": "test-manual-detail-with-elevation",
            "points": [[112.5, 37.8], [112.6, 37.9]],
        },
        headers=auth_header,
    )
    assert created.status_code == 200

    detail = client.get(f"/api/route-books/{created.json()['id']}", headers=auth_header)

    assert detail.status_code == 200
    assert detail.json()["elevation_ready"] is True
    assert detail.json()["elevation_profile"] == created.json()["elevation_profile"]


def test_route_book_detail_endpoint_exposes_export_state_for_private_owner(client, db, auth_header, test_user):
    route, _version = _route_with_current_version(
        db,
        test_user.id,
        name="我的可导出私密路线",
        visibility="private",
        publish_status="draft",
    )

    detail = client.get(f"/api/route-books/{route.id}/detail", headers=auth_header)

    assert detail.status_code == 200
    body = detail.json()
    assert body["id"] == route.id
    assert body["name"] == "我的可导出私密路线"
    assert "file_id" not in body
    assert "source" not in body
    assert "source_activity_id" not in body
    assert "current_version_id" not in body
    assert "visibility" not in body
    assert "publish_status" not in body
    assert body["preview_points"] == [[112.5, 37.8], [112.6, 37.9]]
    assert body["export_ready"] is True
    assert body["export_formats"] == ["gpx", "tcx"]
    assert body["export_block_reason"] is None
    assert body["anonymous_export_download_allowed"] is False
    assert body["climb_plan"]["algorithm_version"] == "velo_climb_plan_v1"
    assert body["climb_plan"]["source"]["confidence"] in {"terrain_estimate", "low"}
    assert body["rider_climb_plan"]["status"] == "needs_profile"


def test_route_book_detail_does_not_replay_sparse_legacy_elevation_as_current_climb_plan(
    client,
    db,
    auth_header,
    test_user,
):
    route, version = _route_with_current_version(
        db,
        test_user.id,
        visibility="private",
        publish_status="draft",
    )
    metadata = json.loads(version.navigation_metadata_json)
    metadata.pop("climb_plan")
    version.navigation_metadata_json = json.dumps(metadata)
    db.add(version)
    db.commit()

    detail = client.get(f"/api/route-books/{route.id}/detail", headers=auth_header)

    assert detail.status_code == 200
    assert detail.json()["climb_plan"] is None
    assert detail.json()["rider_climb_plan"] is None


@pytest.mark.parametrize(
    "mutation",
    [
        lambda plan: plan.update(algorithm_version="legacy_climb_plan_v0"),
        lambda plan: plan.update(unexpected_internal_field=True),
        lambda plan: plan["partition_alternatives"].update(
            {
                "80m": [
                    {
                        "start_distance_m": 0,
                        "end_distance_m": 5_000,
                        "length_m": 5_000,
                        "net_gain_m": 300,
                        "average_grade_pct": 6,
                        "score": 30_000,
                        "category": "not-a-category",
                        "unexpected_internal_field": "must-not-pass",
                    }
                ]
            }
        ),
    ],
)
def test_route_book_detail_degrades_unknown_or_corrupt_stored_climb_plan_to_pending(
    client,
    db,
    auth_header,
    test_user,
    mutation,
):
    route, version = _route_with_current_version(
        db,
        test_user.id,
        visibility="private",
        publish_status="draft",
    )
    metadata = json.loads(version.navigation_metadata_json)
    mutation(metadata["climb_plan"])
    version.navigation_metadata_json = json.dumps(metadata)
    db.add(version)
    db.commit()

    detail = client.get(f"/api/route-books/{route.id}/detail", headers=auth_header)

    assert detail.status_code == 200
    assert detail.json()["climb_plan"] is None
    assert detail.json()["rider_climb_plan"] is None


def test_route_book_detail_power_curve_cache_failure_falls_back_to_ftp_without_500(
    client,
    db,
    auth_header,
    test_user,
    monkeypatch,
):
    test_user.ftp = 280
    test_user.weight = 70
    db.add(test_user)
    db.commit()
    route, _version = _route_with_current_version(
        db,
        test_user.id,
        visibility="private",
        publish_status="draft",
    )

    def fail_cache(*_args, **_kwargs):
        raise TimeoutError("redis black hole")

    monkeypatch.setattr("app.route_book.service.get_cached_user_power_curve", fail_cache)

    detail = client.get(f"/api/route-books/{route.id}/detail", headers=auth_header)

    assert detail.status_code == 200
    rider = detail.json()["rider_climb_plan"]
    assert rider["status"] == "estimated"
    assert rider["basis"] == "ftp_weight"
    assert rider["physiology_model"] == "ftp_only"


def test_route_detail_redis_client_has_request_timeouts():
    from app.queue import request_redis_conn

    options = request_redis_conn.connection_pool.connection_kwargs
    assert options["socket_connect_timeout"] == pytest.approx(1.0)
    assert options["socket_timeout"] == pytest.approx(1.0)
    assert options["retry_on_timeout"] is False


def test_route_book_detail_endpoint_exposes_export_state_for_public_anonymous(client, db, admin_user):
    route, _version = _route_with_current_version(
        db,
        admin_user.id,
        name="公开游客可导出路线",
        visibility="public",
        publish_status="published",
    )

    detail = client.get(f"/api/route-books/{route.id}/detail")

    assert detail.status_code == 200
    body = detail.json()
    assert body["id"] == route.id
    assert "file_id" not in body
    assert "source_activity_id" not in body
    assert body["export_ready"] is True
    assert body["export_formats"] == ["gpx", "tcx"]
    assert body["export_block_reason"] is None
    assert body["anonymous_export_download_allowed"] is True
    assert body["climb_plan"]["algorithm_version"] == "velo_climb_plan_v1"
    assert body["rider_climb_plan"] is None


def test_route_book_detail_endpoint_marks_no_elevation_for_owner(client, db, auth_header, test_user):
    route, version = _route_with_current_version(
        db,
        test_user.id,
        name="还没海拔的私密路线",
        visibility="private",
        publish_status="draft",
    )
    version.elevation_points_snapshot = None
    db.add(version)
    db.commit()

    detail = client.get(f"/api/route-books/{route.id}/detail", headers=auth_header)

    assert detail.status_code == 200
    body = detail.json()
    assert body["export_ready"] is False
    assert body["export_formats"] == []
    assert body["export_block_reason"] == "no_elevation"


def test_route_book_detail_endpoint_marks_no_current_version_before_elevation(client, db, auth_header, test_user):
    from app.route_book.models import RouteBook

    route = RouteBook(
        creator_id=test_user.id,
        name="只有路线壳",
        distance=42000.0,
        reference_line="SRID=4326;LINESTRING(112.5 37.8, 112.6 37.9)",
        source="manual_drawn",
        source_activity_id=None,
        city="taiyuan",
        visibility="private",
        publish_status="draft",
        current_version_id=None,
    )
    db.add(route)
    db.commit()
    db.refresh(route)

    detail = client.get(f"/api/route-books/{route.id}/detail", headers=auth_header)

    assert detail.status_code == 200
    body = detail.json()
    assert body["export_ready"] is False
    assert body["export_formats"] == []
    assert body["export_block_reason"] == "no_current_version"


def test_route_book_list_marks_elevation_ready_without_sending_profile(client, auth_header, monkeypatch):
    def fake_query(coords):
        return _linear_elevations(coords, start=700.0, end=725.0)

    monkeypatch.setattr("app.route_book.service.query_elevations", fake_query, raising=False)

    created = client.post(
        "/api/route-books/manual-drawn",
        json={
            "name": "列表只亮状态",
            "client_request_id": "test-manual-list-elevation-status",
            "points": [[112.5, 37.8], [112.6, 37.9]],
        },
        headers=auth_header,
    )
    assert created.status_code == 200

    listed = client.get("/api/route-books?mine=true", headers=auth_header)

    assert listed.status_code == 200
    item = next(route for route in listed.json()["items"] if route["id"] == created.json()["id"])
    assert item["elevation_ready"] is True
    assert item["elevation_profile"] is None


def test_manual_drawn_route_rejects_invalid_coordinates(client, db, auth_header):
    from app.route_book.models import RouteBook

    res = client.post(
        "/api/route-books/manual-drawn",
        json={
            "name": "坏坐标路线",
            "client_request_id": "test-manual-invalid-coordinates",
            "points": [[181.0, 37.8], [112.6, 37.9]],
        },
        headers=auth_header,
    )

    assert res.status_code == 422
    assert db.query(RouteBook).filter(RouteBook.name == "坏坐标路线").first() is None


def test_manual_drawn_route_returns_503_when_elevation_source_fails(client, db, auth_header, monkeypatch):
    from app.elevation.dem_client import DEMServiceError
    from app.route_book.models import RouteBook

    def fake_query(_coords):
        raise DEMServiceError("cache unavailable")

    monkeypatch.setattr("app.route_book.service.query_elevations", fake_query, raising=False)

    res = client.post(
        "/api/route-books/manual-drawn",
        json={
            "name": "海拔源失败",
            "client_request_id": "test-manual-elevation-source-failure",
            "points": [[112.5, 37.8], [112.6, 37.9]],
        },
        headers=auth_header,
    )

    assert res.status_code == 503
    assert "路线海拔查询失败" in res.text
    assert db.query(RouteBook).filter(RouteBook.name == "海拔源失败").first() is None


def test_manual_drawn_route_rejects_too_many_points_before_elevation_query(client, auth_header, monkeypatch):
    calls = []

    def fake_query(coords):
        calls.append(coords)
        return [700.0 for _ in coords]

    monkeypatch.setattr("app.route_book.service.query_elevations", fake_query, raising=False)

    res = client.post(
        "/api/route-books/manual-drawn",
        json={
            "name": "点太多",
            "client_request_id": "test-manual-too-many-points",
            "points": [[112.5 + index * 0.00001, 37.8] for index in range(5001)],
        },
        headers=auth_header,
    )

    assert res.status_code == 422
    assert calls == []


def test_manual_drawn_route_rejects_over_1000km_before_elevation_query(
    client,
    auth_header,
    monkeypatch,
):
    calls = []

    def fake_query(coords):
        calls.append(coords)
        return [700.0 for _ in coords]

    monkeypatch.setattr("app.route_book.service.query_elevations", fake_query, raising=False)

    res = client.post(
        "/api/route-books/manual-drawn",
        json={
            "name": "跨越同步处理上限",
            "client_request_id": "test-manual-over-1000km",
            "points": [[112.0, 30.0], [112.0, 40.0]],
        },
        headers=auth_header,
    )

    assert res.status_code == 422
    assert "1000 公里" in res.text
    assert calls == []


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
    monkeypatch.setattr(
        "app.route_book.service.query_elevations",
        _linear_elevations,
        raising=False,
    )

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


def test_delete_route_book_removes_generated_export_files(
    client, db, auth_header, test_user, monkeypatch
):
    route, _version = _route_with_current_version(
        db,
        test_user.id,
        visibility="private",
        publish_status="draft",
    )
    storage = _FakeExportStorage()
    monkeypatch.setattr("app.route_book.export_workflow._storage", storage)
    monkeypatch.setattr("app.route_book.service._storage", storage)

    exported = client.post(
        f"/api/route-books/{route.id}/exports",
        json={"format": "gpx"},
        headers=auth_header,
    )
    assert exported.status_code == 200
    assert storage.files

    deleted = client.delete(f"/api/route-books/{route.id}", headers=auth_header)

    assert deleted.status_code == 204
    assert storage.files == {}


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
