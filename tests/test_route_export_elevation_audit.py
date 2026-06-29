"""路线导出海拔审计测试——保证运营验货表不把二维路线说成精确路线。"""

from pathlib import Path
import json
import subprocess
import sys

from geoalchemy2 import WKTElement


ROOT_DIR = Path(__file__).resolve().parents[1]


def test_audit_script_can_start_from_repo_root():
    result = subprocess.run(
        [sys.executable, "-B", "scripts/audit_route_export_elevation.py", "--help"],
        cwd=ROOT_DIR,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "--public-only" in result.stdout


def _route_with_version(db, **overrides):
    from app.route_book.models import RouteBook, RouteVersion

    route_data = {
        "name": "公开二维路线",
        "distance": 1000.0,
        "climb": 20.0,
        "reference_line": WKTElement("SRID=4326;LINESTRING(112.5 37.8, 112.6 37.9)", srid=4326),
        "source": "manual_drawn",
        "file_id": None,
        "file_type": None,
        "city": "taiyuan",
        "visibility": "public",
        "publish_status": "published",
    }
    route_data.update(overrides.pop("route", {}))
    route = RouteBook(**route_data)
    db.add(route)
    db.flush()

    version_data = {
        "route_book_id": route.id,
        "version_no": 1,
        "status": "current",
        "created_by": None,
        "geometry_source": route.source,
        "navigation_status": "ready",
        "reference_line_snapshot": WKTElement("SRID=4326;LINESTRING(112.5 37.8, 112.6 37.9)", srid=4326),
        "line_hash": "hash-" + str(route.id),
        "distance": route.distance,
        "climb": route.climb,
        "point_count": 2,
    }
    version_data.update(overrides.pop("version", {}))
    version = RouteVersion(**version_data)
    db.add(version)
    db.flush()
    route.current_version_id = version.id
    db.commit()
    db.refresh(route)
    db.refresh(version)
    return route, version


def test_audit_marks_public_route_without_elevation_as_2d_download(db):
    from scripts.audit_route_export_elevation import audit_route_export_elevation

    route, version = _route_with_version(db)

    rows = audit_route_export_elevation(db, route_book_ids=[route.id])

    assert len(rows) == 1
    row = rows[0]
    assert row.route_book_id == route.id
    assert row.current_version_id == version.id
    assert row.public_export_ready is True
    assert row.export_elevation_included is False
    assert row.export_elevation_point_count == 0
    assert row.precise_source_candidates == []
    assert row.action == "download_is_2d_need_precise_source"


def test_audit_reports_current_version_elevation_points(db):
    from scripts.audit_route_export_elevation import audit_route_export_elevation

    route, _version = _route_with_version(
        db,
        version={
            # SQLite 测试库读取 Geometry 时返回固定假 EWKB 坐标，快照跟随这组坐标。
            "elevation_points_snapshot": "[[112.55,37.87,701.2],[112.55,37.875,735.8]]",
        },
    )

    row = audit_route_export_elevation(db, route_book_ids=[route.id])[0]

    assert row.export_elevation_included is True
    assert row.export_elevation_point_count == 2
    assert row.precise_source_candidates == ["current_version"]
    assert row.action == "export_contains_elevation"


def test_audit_finds_source_activity_as_precise_backfill_candidate(db):
    from app.activity.models import Activity, Trackpoint
    from scripts.audit_route_export_elevation import audit_route_export_elevation

    activity = Activity(
        user_id=1,
        title="源活动",
        status="completed",
        activity_type="cycling",
        distance=1000.0,
    )
    db.add(activity)
    db.flush()
    db.add_all(
        [
            # SQLite 测试库读取 Geometry 时返回固定假 EWKB 坐标，候选来源必须同线匹配。
            Trackpoint(activity_id=activity.id, seq=0, latitude=37.87, longitude=112.55, elevation=701.2),
            Trackpoint(activity_id=activity.id, seq=1, latitude=37.875, longitude=112.55, elevation=735.8),
        ]
    )
    route, _version = _route_with_version(
        db,
        route={
            "name": "可用源活动回填",
            "source": "activity_derived",
            "source_activity_id": activity.id,
        },
    )

    row = audit_route_export_elevation(db, route_book_ids=[route.id])[0]

    assert row.export_elevation_included is False
    assert row.precise_source_candidates == ["source_activity"]
    assert row.action == "download_is_2d_can_backfill_from_precise_source"


def test_audit_rejects_source_activity_when_geometry_does_not_match(db):
    from app.activity.models import Activity, Trackpoint
    from scripts.audit_route_export_elevation import audit_route_export_elevation

    activity = Activity(
        user_id=1,
        title="另一条线",
        status="completed",
        activity_type="cycling",
        distance=1000.0,
    )
    db.add(activity)
    db.flush()
    db.add_all(
        [
            Trackpoint(activity_id=activity.id, seq=0, latitude=37.8, longitude=112.5, elevation=701.2),
            Trackpoint(activity_id=activity.id, seq=1, latitude=37.9, longitude=112.6, elevation=735.8),
        ]
    )
    route, _version = _route_with_version(
        db,
        route={
            "name": "源活动不同线",
            "source": "activity_derived",
            "source_activity_id": activity.id,
        },
    )

    row = audit_route_export_elevation(db, route_book_ids=[route.id])[0]

    assert row.export_elevation_included is False
    assert row.precise_source_candidates == []
    assert row.action == "download_is_2d_need_precise_source"


def test_audit_finds_repo_route_file_as_precise_backfill_candidate(db):
    from scripts.audit_route_export_elevation import audit_route_export_elevation

    route, _version = _route_with_version(
        db,
        route={
            "name": "可用仓库 GPX 回填",
            "source": "file_upload",
            "file_id": "tests/fixtures/routes/fake-ewkb-route/track.gpx",
            "file_type": "gpx",
        },
    )

    row = audit_route_export_elevation(db, route_book_ids=[route.id])[0]

    assert row.export_elevation_included is False
    assert row.precise_source_candidates == ["repo_route_file"]
    assert row.action == "download_is_2d_can_backfill_from_precise_source"


def test_audit_rejects_repo_route_file_when_geometry_does_not_match(db):
    from scripts.audit_route_export_elevation import audit_route_export_elevation

    route, _version = _route_with_version(
        db,
        route={
            "name": "仓库 GPX 不同线",
            "source": "file_upload",
            "file_id": "tests/fixtures/routes/test-gpx-route/track.gpx",
            "file_type": "gpx",
        },
    )

    row = audit_route_export_elevation(db, route_book_ids=[route.id])[0]

    assert row.export_elevation_included is False
    assert row.precise_source_candidates == []
    assert row.action == "download_is_2d_need_precise_source"


def test_audit_cli_prints_json_with_selected_route(db, monkeypatch, capsys):
    from scripts import audit_route_export_elevation as script

    route, _version = _route_with_version(db)
    monkeypatch.setattr(script, "SessionLocal", lambda: db)

    script.main(["--route-book-id", str(route.id)])

    payload = json.loads(capsys.readouterr().out)
    assert [item["route_book_id"] for item in payload] == [route.id]
    assert payload[0]["action"] == "download_is_2d_need_precise_source"
