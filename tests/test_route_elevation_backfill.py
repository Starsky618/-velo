"""路线海拔回填测试——先证明“只给同一条路线补高度”，再允许脚本动数据库。"""

import json
from pathlib import Path
import subprocess
import sys

import pytest
from geoalchemy2 import WKTElement


ROOT_DIR = Path(__file__).resolve().parents[1]


def test_backfill_script_can_start_from_repo_root():
    result = subprocess.run(
        [sys.executable, "-B", "scripts/backfill_route_elevation.py", "--help"],
        cwd=ROOT_DIR,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "--route-book-id" in result.stdout


def test_backfill_script_requires_source_license_note_before_apply():
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "scripts/backfill_route_elevation.py",
            "--route-book-id",
            "1",
            "--source-json",
            "missing.json",
            "--apply",
        ],
        cwd=ROOT_DIR,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "--source-license-note" in result.stderr


def test_parse_igpsport_share_tracks_reads_altitude_and_longitute_typo():
    from scripts.backfill_route_elevation import parse_igpsport_share_payload

    payload = {
        "data": {
            "routeInfo": {
                "tracks": [
                    {"longitute": 112.5, "latitude": 37.8, "alt": 701.2},
                    {"longitute": 112.6, "latitude": 37.9, "alt": 735.8},
                ]
            }
        }
    }

    points = parse_igpsport_share_payload(payload)

    assert points == [[112.5, 37.8, 701.2], [112.6, 37.9, 735.8]]


def test_project_precise_elevation_rejects_different_route():
    from scripts.backfill_route_elevation import project_precise_elevation

    target_points = [[112.5, 37.8], [112.6, 37.9]]
    source_points = [[113.5, 38.8, 701.2], [113.6, 38.9, 735.8]]

    with pytest.raises(ValueError, match="不是同一条路线"):
        project_precise_elevation(target_points, source_points, max_distance_m=30)


def test_project_precise_elevation_rejects_same_endpoints_but_detour_route():
    from scripts.backfill_route_elevation import project_precise_elevation

    target_points = [[112.5, 37.8], [112.55, 37.85], [112.6, 37.9]]
    source_points = [
        [112.5, 37.8, 701.2],
        [113.2, 38.5, 1300.0],
        [112.6, 37.9, 735.8],
    ]

    with pytest.raises(ValueError, match="不是同一条路线"):
        project_precise_elevation(target_points, source_points, max_distance_m=30)


def test_project_precise_elevation_rejects_sparse_target_with_detour_source():
    from scripts.backfill_route_elevation import project_precise_elevation

    target_points = [[112.5, 37.8], [112.6, 37.9]]
    source_points = [
        [112.5, 37.8, 701.2],
        [113.2, 38.5, 1300.0],
        [112.6, 37.9, 735.8],
    ]

    with pytest.raises(ValueError, match="不是同一条路线"):
        project_precise_elevation(target_points, source_points, max_distance_m=30)


def test_project_precise_elevation_uses_reference_coordinates_not_source():
    from scripts.backfill_route_elevation import project_precise_elevation

    target_points = [[112.5, 37.8], [112.6, 37.9]]
    source_points = [
        [112.50001, 37.80001, 701.2],
        [112.60001, 37.90001, 735.8],
    ]

    projected = project_precise_elevation(target_points, source_points, max_distance_m=5)

    assert projected.elevation_points == [[112.5, 37.8, 701.2], [112.6, 37.9, 735.8]]
    assert projected.matched_point_count == 2


def test_backfill_creates_new_route_version_and_preserves_old_version(db, monkeypatch):
    from app.route_book.models import RouteBook, RouteVersion
    from app.route_book.service import _line_hash
    from scripts.backfill_route_elevation import apply_elevation_backfill

    reference_line = "SRID=4326;LINESTRING(112.5 37.8, 112.6 37.9)"
    route = RouteBook(
        name="奥申",
        distance=1000.0,
        climb=None,
        reference_line=WKTElement(reference_line, srid=4326),
        file_id="source.gpx",
        file_type="gpx",
        source="file_upload",
        city="taiyuan",
        visibility="public",
        publish_status="published",
        line_hash=_line_hash(reference_line),
    )
    db.add(route)
    db.flush()
    old_version = RouteVersion(
        route_book_id=route.id,
        version_no=1,
        status="current",
        geometry_source="file_upload",
        navigation_status="ready",
        reference_line_snapshot=WKTElement(reference_line, srid=4326),
        line_hash=_line_hash(reference_line),
        distance=1000.0,
        climb=None,
        elevation_profile=None,
        elevation_points_snapshot=None,
        point_count=2,
    )
    db.add(old_version)
    db.flush()
    route.current_version_id = old_version.id
    db.commit()

    monkeypatch.setattr(
        "scripts.backfill_route_elevation.reference_points_from_version",
        lambda _version: [[112.5, 37.8], [112.6, 37.9]],
    )

    result = apply_elevation_backfill(
        db,
        route_book_id=route.id,
        source_points=[[112.50001, 37.80001, 701.2], [112.60001, 37.90001, 735.8]],
        max_distance_m=5,
        commit=True,
        source_license_note="pytest fixture: user-owned precise GPX",
    )

    versions = db.query(RouteVersion).filter_by(route_book_id=route.id).order_by(RouteVersion.version_no).all()
    db.refresh(route)

    assert result.changed is True
    assert len(versions) == 2
    assert versions[0].id == old_version.id
    assert versions[0].status == "archived"
    assert versions[0].elevation_points_snapshot is None
    assert versions[1].status == "current"
    assert versions[1].version_no == 2
    assert versions[1].elevation_points_snapshot == "[[112.5,37.8,701.2],[112.6,37.9,735.8]]"
    assert route.current_version_id == versions[1].id
    assert json.loads(route.elevation_profile) == [[0.0, 701.2], [1.0, 735.8]]


def test_backfill_dry_run_does_not_create_new_route_version(db, monkeypatch):
    from app.route_book.models import RouteBook, RouteVersion
    from app.route_book.service import _line_hash
    from scripts.backfill_route_elevation import apply_elevation_backfill

    reference_line = "SRID=4326;LINESTRING(112.5 37.8, 112.6 37.9)"
    route = RouteBook(
        name="奥申",
        distance=1000.0,
        climb=None,
        reference_line=WKTElement(reference_line, srid=4326),
        file_id="source.gpx",
        file_type="gpx",
        source="file_upload",
        city="taiyuan",
        visibility="public",
        publish_status="published",
        line_hash=_line_hash(reference_line),
    )
    db.add(route)
    db.flush()
    old_version = RouteVersion(
        route_book_id=route.id,
        version_no=1,
        status="current",
        geometry_source="file_upload",
        navigation_status="ready",
        reference_line_snapshot=WKTElement(reference_line, srid=4326),
        line_hash=_line_hash(reference_line),
        distance=1000.0,
        climb=None,
        elevation_profile=None,
        elevation_points_snapshot=None,
        point_count=2,
    )
    db.add(old_version)
    db.flush()
    route.current_version_id = old_version.id
    db.commit()

    monkeypatch.setattr(
        "scripts.backfill_route_elevation.reference_points_from_version",
        lambda _version: [[112.5, 37.8], [112.6, 37.9]],
    )

    result = apply_elevation_backfill(
        db,
        route_book_id=route.id,
        source_points=[[112.50001, 37.80001, 701.2], [112.60001, 37.90001, 735.8]],
        max_distance_m=5,
        commit=False,
    )

    versions = db.query(RouteVersion).filter_by(route_book_id=route.id).all()
    db.refresh(route)

    assert result.changed is True
    assert result.new_version_id is None
    assert len(versions) == 1
    assert versions[0].status == "current"
    assert route.current_version_id == old_version.id
    assert route.elevation_profile is None


def test_backfill_is_noop_when_current_version_already_has_same_elevation(db, monkeypatch):
    from app.route_book.models import RouteBook, RouteVersion
    from app.route_book.service import _line_hash
    from scripts.backfill_route_elevation import apply_elevation_backfill

    reference_line = "SRID=4326;LINESTRING(112.5 37.8, 112.6 37.9)"
    elevation_points = "[[112.5,37.8,701.2],[112.6,37.9,735.8]]"
    route = RouteBook(
        name="奥申",
        distance=1000.0,
        climb=34.6,
        elevation_profile="[[0.0,701.2],[1.0,735.8]]",
        reference_line=WKTElement(reference_line, srid=4326),
        file_id="source.gpx",
        file_type="gpx",
        source="file_upload",
        city="taiyuan",
        visibility="public",
        publish_status="published",
        line_hash=_line_hash(reference_line),
    )
    db.add(route)
    db.flush()
    version = RouteVersion(
        route_book_id=route.id,
        version_no=1,
        status="current",
        geometry_source="file_upload",
        navigation_status="ready",
        reference_line_snapshot=WKTElement(reference_line, srid=4326),
        line_hash=_line_hash(reference_line),
        distance=1000.0,
        climb=34.6,
        elevation_profile="[[0.0,701.2],[1.0,735.8]]",
        elevation_points_snapshot=elevation_points,
        point_count=2,
    )
    db.add(version)
    db.flush()
    route.current_version_id = version.id
    db.commit()

    monkeypatch.setattr(
        "scripts.backfill_route_elevation.reference_points_from_version",
        lambda _version: [[112.5, 37.8], [112.6, 37.9]],
    )

    result = apply_elevation_backfill(
        db,
        route_book_id=route.id,
        source_points=[[112.5, 37.8, 701.2], [112.6, 37.9, 735.8]],
        max_distance_m=5,
        commit=True,
        source_license_note="pytest fixture: user-owned precise GPX",
    )

    assert result.changed is False
    assert db.query(RouteVersion).filter_by(route_book_id=route.id).count() == 1


def test_core_backfill_requires_source_license_note_when_writing(db):
    from scripts.backfill_route_elevation import apply_elevation_backfill

    with pytest.raises(ValueError, match="source_license_note"):
        apply_elevation_backfill(
            db,
            route_book_id=1,
            source_points=[[112.5, 37.8, 701.2], [112.6, 37.9, 735.8]],
            max_distance_m=5,
            commit=True,
        )
