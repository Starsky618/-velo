import csv
import json

from sqlalchemy import text


def _route_with_current_version(db):
    from app.route_book.models import RouteBook, RouteVersion

    line = "SRID=4326;LINESTRING(112.5 37.8, 112.6 37.9)"
    route = RouteBook(
        name="奥申",
        distance=15000.0,
        climb=None,
        reference_line=line,
        source="file_upload",
        file_id="routes/aoshen.gpx",
        file_type="gpx",
        city="taiyuan",
        visibility="public",
        publish_status="published",
    )
    db.add(route)
    db.commit()
    db.refresh(route)

    version = RouteVersion(
        route_book_id=route.id,
        version_no=1,
        status="current",
        geometry_source="file_upload",
        navigation_status="ready",
        reference_line_snapshot=line,
        line_hash=f"hash-{route.id}",
        distance=route.distance,
        climb=None,
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


def _create_route_guides_table(db):
    from app.route_book.models import RouteGuide

    db.execute(text("CREATE TABLE IF NOT EXISTS judgment_runs (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
    RouteGuide.__table__.create(bind=db.bind, checkfirst=True)


def _drop_route_guides_table(db):
    from app.route_book.models import RouteGuide

    RouteGuide.__table__.drop(bind=db.bind, checkfirst=True)
    db.execute(text("DROP TABLE IF EXISTS judgment_runs"))


def test_export_missing_points_writes_routes_that_need_authorized_elevation(db, tmp_path):
    from scripts.backfill_route_elevation import export_missing_points

    route, version = _route_with_current_version(db)
    output = tmp_path / "missing.csv"

    count = export_missing_points(db, output)

    rows = list(csv.DictReader(output.open(encoding="utf-8")))
    assert count == 2
    assert rows[0]["route_book_id"] == str(route.id)
    assert rows[0]["route_version_id"] == str(version.id)
    assert rows[0]["seq"] == "0"
    assert rows[0]["lon"] == "112.5"
    assert rows[0]["lat"] == "37.8"


def test_export_missing_points_includes_complete_but_untrusted_elevation(db, tmp_path):
    from scripts.backfill_route_elevation import export_missing_points

    route, version = _route_with_current_version(db)
    version.elevation_points_snapshot = "[[112.5,37.8,1.0],[112.6,37.9,2.0]]"
    version.navigation_metadata_json = None
    db.add(version)
    db.commit()
    output = tmp_path / "missing.csv"

    count = export_missing_points(db, output)

    rows = list(csv.DictReader(output.open(encoding="utf-8")))
    assert count == 2
    assert rows[0]["route_book_id"] == str(route.id)
    assert rows[0]["route_version_id"] == str(version.id)


def test_import_elevation_csv_requires_license_metadata_and_updates_route_version(db, tmp_path):
    from app.route_book.models import RouteBook, RouteVersion
    from scripts.backfill_route_elevation import import_elevation_csv

    route, version = _route_with_current_version(db)
    input_path = tmp_path / "authorized-elevation.csv"
    with input_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["route_version_id", "seq", "lon", "lat", "elevation_m"])
        writer.writeheader()
        writer.writerow(
            {"route_version_id": version.id, "seq": 0, "lon": 112.5, "lat": 37.8, "elevation_m": 701.2}
        )
        writer.writerow(
            {"route_version_id": version.id, "seq": 1, "lon": 112.6, "lat": 37.9, "elevation_m": 735.8}
        )

    updated = import_elevation_csv(
        db,
        input_path,
        source_name="国内合规高程供应商",
        license_id="contract-2026-001",
        accuracy_m=5.0,
        dry_run=False,
    )

    db.refresh(route)
    db.refresh(version)
    stored_route = db.query(RouteBook).filter(RouteBook.id == route.id).one()
    stored_version = db.query(RouteVersion).filter(RouteVersion.id == version.id).one()
    metadata = json.loads(stored_version.navigation_metadata_json)

    assert updated == 1
    assert json.loads(stored_version.elevation_points_snapshot) == [[112.5, 37.8, 701.2], [112.6, 37.9, 735.8]]
    assert stored_version.climb == 34.6
    assert stored_route.climb == 34.6
    assert metadata["elevation"]["source_name"] == "国内合规高程供应商"
    assert metadata["elevation"]["license_id"] == "contract-2026-001"
    assert metadata["elevation"]["accuracy_m"] == 5.0


def test_build_route_elevation_result_uses_shared_dem_path_and_keeps_full_points():
    from app.elevation.route_elevation import build_route_elevation_result

    calls = []

    def fake_query(coords):
        calls.append(coords)
        return [700.0, 725.5, 721.0]

    result = build_route_elevation_result(
        [[112.5, 37.8], [112.55, 37.85], [112.6, 37.9]],
        query_func=fake_query,
    )

    assert calls == [[(37.8, 112.5), (37.85, 112.55), (37.9, 112.6)]]
    assert result.snapshot == [[112.5, 37.8, 700.0], [112.55, 37.85, 725.5], [112.6, 37.9, 721.0]]
    assert result.profile[0] == [0.0, 700.0]
    assert result.profile[-1][1] == 721.0
    assert result.climb == 25.5
    assert result.point_count == 3


def test_build_route_elevation_result_rejects_invalid_elevation_values():
    from app.elevation.route_elevation import build_route_elevation_result

    def fake_query(_coords):
        return [700.0, float("nan")]

    try:
        build_route_elevation_result(
            [[112.5, 37.8], [112.6, 37.9]],
            query_func=fake_query,
        )
    except ValueError as exc:
        assert "异常高度" in str(exc)
    else:
        raise AssertionError("异常海拔不能写进路书海拔结果")


def test_backfill_route_version_elevation_writes_route_version_route_and_guide(db):
    from app.route_book.elevation_workflow import backfill_route_version_elevation
    from app.route_book.models import RouteBook, RouteGuide, RouteVersion

    _create_route_guides_table(db)
    try:
        route, version = _route_with_current_version(db)
        guide = RouteGuide(
            name="奥申导览",
            city="太原",
            route_book_id=route.id,
            source_route_version_id=version.id,
            content_md="# 奥申导览",
        )
        db.add(guide)
        db.commit()

        def fake_query(coords):
            assert coords == [(37.8, 112.5), (37.9, 112.6)]
            return [701.2, 735.8]

        updated = backfill_route_version_elevation(
            db,
            version.id,
            query_func=fake_query,
            source_name="SRTM3 90m DEM",
            license_id="srtm3-public-dem",
            accuracy_m=90.0,
            dry_run=False,
        )

        stored_route = db.query(RouteBook).filter(RouteBook.id == route.id).one()
        stored_version = db.query(RouteVersion).filter(RouteVersion.id == version.id).one()
        stored_guide = db.query(RouteGuide).filter(RouteGuide.id == guide.id).one()
        profile = json.loads(stored_version.elevation_profile)
        metadata = json.loads(stored_version.navigation_metadata_json)

        assert updated is True
        assert json.loads(stored_version.elevation_points_snapshot) == [[112.5, 37.8, 701.2], [112.6, 37.9, 735.8]]
        assert stored_version.climb == 34.6
        assert stored_route.climb == 34.6
        assert json.loads(stored_route.elevation_profile) == profile
        assert json.loads(stored_guide.elevation_profile) == profile
        assert metadata["elevation"]["method"] == "shared_route_elevation_v1"
        assert metadata["elevation"]["source_name"] == "SRTM3 90m DEM"
    finally:
        _drop_route_guides_table(db)


def test_backfill_missing_with_srtm_updates_only_missing_current_versions(db):
    from app.route_book.models import RouteVersion
    from scripts.backfill_route_elevation import backfill_missing_with_srtm

    route, version = _route_with_current_version(db)

    def fake_query(coords):
        assert coords == [(37.8, 112.5), (37.9, 112.6)]
        return [701.2, 735.8]

    updated = backfill_missing_with_srtm(
        db,
        query_func=fake_query,
        source_name="SRTM3 90m DEM",
        license_id="srtm3-public-dem",
        accuracy_m=90.0,
        dry_run=False,
    )

    stored_version = db.query(RouteVersion).filter(RouteVersion.id == version.id).one()
    metadata = json.loads(stored_version.navigation_metadata_json)

    assert updated == 1
    assert json.loads(stored_version.elevation_points_snapshot) == [[112.5, 37.8, 701.2], [112.6, 37.9, 735.8]]
    assert route.id == stored_version.route_book_id
    assert metadata["elevation"]["method"] == "shared_route_elevation_v1"


def test_backfill_missing_with_srtm_overwrites_complete_untrusted_snapshot(db):
    from app.route_book.models import RouteVersion
    from scripts.backfill_route_elevation import backfill_missing_with_srtm

    _route, version = _route_with_current_version(db)
    version.elevation_points_snapshot = "[[112.5,37.8,1.0],[112.6,37.9,2.0]]"
    version.navigation_metadata_json = None
    db.add(version)
    db.commit()

    def fake_query(coords):
        assert coords == [(37.8, 112.5), (37.9, 112.6)]
        return [701.2, 735.8]

    updated = backfill_missing_with_srtm(
        db,
        query_func=fake_query,
        source_name="SRTM3 90m DEM",
        license_id="srtm3-public-dem",
        accuracy_m=16.0,
        dry_run=False,
    )

    stored_version = db.query(RouteVersion).filter(RouteVersion.id == version.id).one()
    metadata = json.loads(stored_version.navigation_metadata_json)

    assert updated == 1
    assert json.loads(stored_version.elevation_points_snapshot) == [[112.5, 37.8, 701.2], [112.6, 37.9, 735.8]]
    assert metadata["elevation"]["method"] == "shared_route_elevation_v1"
    assert metadata["elevation"]["horizontal_resolution_m"] == 90.0


def test_backfill_missing_with_srtm_dry_run_rolls_back(db):
    from app.route_book.models import RouteVersion
    from scripts.backfill_route_elevation import backfill_missing_with_srtm

    _route, version = _route_with_current_version(db)

    def fake_query(_coords):
        return [701.2, 735.8]

    updated = backfill_missing_with_srtm(
        db,
        query_func=fake_query,
        dry_run=True,
    )

    stored_version = db.query(RouteVersion).filter(RouteVersion.id == version.id).one()
    assert updated == 1
    assert stored_version.elevation_points_snapshot is None
    assert stored_version.navigation_metadata_json is None


def test_virtual_gpx_experiment_runs_import_srtm_fill_export_loop():
    from scripts.experiment_route_srtm_export import run_experiment

    def fake_query(coords):
        return [700.0 + index for index, _coord in enumerate(coords)]

    report = run_experiment(
        count=3,
        seed=20260630,
        points_per_route=8,
        query_func=fake_query,
    )

    assert report["total"] == 3
    assert report["succeeded"] == 3
    assert report["failed"] == 0
    assert all(item["gpx_ele_count"] == item["point_count"] for item in report["items"])
    assert all(item["tcx_altitude_count"] == item["point_count"] for item in report["items"])
