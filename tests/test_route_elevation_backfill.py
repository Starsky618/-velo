import csv
from datetime import datetime, timedelta, timezone
import json
import math

import pytest
from sqlalchemy import text


def _linear_elevations(coords, *, start=701.2, end=735.8):
    if len(coords) == 1:
        return [float(start)]
    return [
        float(start + (end - start) * index / (len(coords) - 1))
        for index, _coord in enumerate(coords)
    ]


def _assert_fixed_grid_query(coords, *, start=(37.8, 112.5), end=(37.9, 112.6)):
    from app.parsing.geo_math import haversine

    expected_count = math.ceil(haversine(start[0], start[1], end[0], end[1]) / 20.0) + 1
    assert len(coords) == expected_count
    assert coords[0] == start
    assert coords[-1] == end


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


def _route_meetup(db, route_book_id, *, status, start_time, snapshot_climb=999.0):
    from app.meetup.models import Meetup

    meetup = Meetup(
        status=status,
        route_book_id=route_book_id,
        snapshot_route_name="旧路线快照",
        snapshot_distance=15000.0,
        snapshot_climb=snapshot_climb,
        snapshot_city="taiyuan",
        start_time=start_time,
        estimated_end_time=start_time + timedelta(hours=3),
        meeting_point="集合点",
        pace_level="cruise",
        max_participants=6,
    )
    db.add(meetup)
    return meetup


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
    from scripts.backfill_route_elevation import backfill_missing_with_glo, import_elevation_csv

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
    assert stored_version.climb == 34.4
    assert stored_route.climb == 34.4
    assert metadata["elevation"]["source_name"] == "国内合规高程供应商"
    assert metadata["elevation"]["license_id"] == "contract-2026-001"
    assert metadata["elevation"]["accuracy_m"] == 5.0

    def unexpected_glo_query(_coords):
        raise AssertionError("已授权逐点海拔不能被 canonical GLO 回填覆盖")

    assert backfill_missing_with_glo(
        db,
        query_func=unexpected_glo_query,
        dry_run=False,
    ) == 0
    db.refresh(stored_version)
    assert stored_version.elevation_grid_snapshot is None


def test_build_route_elevation_result_uses_fixed_grid_and_keeps_full_route_points():
    from app.elevation.route_elevation import build_route_elevation_result

    calls = []

    def fake_query(coords):
        calls.append(coords)
        result = []
        for _lat, lon in coords:
            if lon <= 112.55:
                result.append(700.0 + (lon - 112.5) / 0.05 * 25.5)
            else:
                result.append(725.5 - (lon - 112.55) / 0.05 * 4.5)
        return result

    result = build_route_elevation_result(
        [[112.5, 37.8], [112.55, 37.85], [112.6, 37.9]],
        query_func=fake_query,
    )

    assert len(calls) == 1
    _assert_fixed_grid_query(calls[0])
    assert result.snapshot == [[112.5, 37.8, 700.1], [112.55, 37.85, 725.3], [112.6, 37.9, 721.0]]
    assert result.profile[0] == [0.0, 700.1]
    assert result.profile[-1][1] == 721.0
    assert result.climb == 25.3
    assert result.point_count == 3
    assert result.elevation_grid is not None
    assert len(result.elevation_grid) == len(calls[0])
    assert result.elevation_grid[0][0] == 0.0


def test_build_route_elevation_result_rejects_invalid_elevation_values():
    from app.elevation.route_elevation import build_route_elevation_result

    def fake_query(coords):
        values = [700.0 for _coord in coords]
        values[len(values) // 2] = float("nan")
        return values

    try:
        build_route_elevation_result(
            [[112.5, 37.8], [112.6, 37.9]],
            query_func=fake_query,
        )
    except ValueError as exc:
        assert "异常高度" in str(exc)
    else:
        raise AssertionError("异常海拔不能写进路书海拔结果")


def test_build_route_elevation_result_rejects_over_1000km_before_allocating_grid():
    from app.elevation.route_elevation import (
        RouteElevationInputError,
        build_route_elevation_result,
    )

    calls = []

    def fake_query(coords):
        calls.append(coords)
        return [0.0 for _coord in coords]

    with pytest.raises(RouteElevationInputError, match="1000 公里"):
        build_route_elevation_result(
            [[112.0, 30.0], [112.0, 40.0]],
            query_func=fake_query,
        )

    assert calls == []


@pytest.mark.parametrize(
    "points, message",
    [
        ([[112.0, 90.0], [112.1, 89.9]], "经纬度范围"),
        ([[180.0, 30.0], [179.9, 30.1]], "经纬度范围"),
        ([[179.9, 30.0], [-179.9, 30.0]], "日期变更线"),
    ],
)
def test_build_route_elevation_result_rejects_dem_boundary_or_dateline_routes(
    points,
    message,
):
    from app.elevation.route_elevation import (
        RouteElevationInputError,
        build_route_elevation_result,
    )

    with pytest.raises(RouteElevationInputError, match=message):
        build_route_elevation_result(points, query_func=lambda _coords: [])


def test_write_route_elevation_result_preserves_draw_metadata(db):
    from app.elevation.route_elevation import RouteElevationResult
    from app.route_book.elevation_workflow import write_route_elevation_result
    from app.route_book.models import RouteVersion

    route, version = _route_with_current_version(db)
    version.navigation_metadata_json = json.dumps(
        {
            "draw": {
                "tool": "route_draw_v0",
                "snap_provider": "tencent_direction",
                "segment_count": 1,
            }
        },
        ensure_ascii=False,
    )
    db.add(version)
    db.commit()

    write_route_elevation_result(
        db,
        route=route,
        version=version,
        result=RouteElevationResult(
            snapshot=[[112.5, 37.8, 701.2], [112.6, 37.9, 735.8]],
            profile=[[0.0, 701.2], [14.1, 735.8]],
            climb=34.6,
            point_count=2,
        ),
        source_name="Copernicus DEM GLO-30 Public",
        license_id="Copernicus DEM Licence",
        accuracy_m=4.0,
        method="glo30_meaningful_ascent_v1",
        timestamp_field="generated_at",
        extra_metadata={"horizontal_resolution_m": 30.0},
    )
    db.commit()

    stored_version = db.query(RouteVersion).filter(RouteVersion.id == version.id).one()
    metadata = json.loads(stored_version.navigation_metadata_json)
    assert metadata["draw"] == {
        "tool": "route_draw_v0",
        "snap_provider": "tencent_direction",
        "segment_count": 1,
    }
    assert metadata["elevation"]["method"] == "glo30_meaningful_ascent_v1"


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
            _assert_fixed_grid_query(coords)
            return _linear_elevations(coords)

        updated = backfill_route_version_elevation(
            db,
            version.id,
            query_func=fake_query,
            source_name="Copernicus DEM GLO-30 Public",
            license_id="Copernicus DEM Licence",
            accuracy_m=4.0,
            dry_run=False,
        )

        stored_route = db.query(RouteBook).filter(RouteBook.id == route.id).one()
        stored_version = db.query(RouteVersion).filter(RouteVersion.id == version.id).one()
        stored_guide = db.query(RouteGuide).filter(RouteGuide.id == guide.id).one()
        profile = json.loads(stored_version.elevation_profile)
        metadata = json.loads(stored_version.navigation_metadata_json)

        assert updated is True
        assert json.loads(stored_version.elevation_points_snapshot) == [[112.5, 37.8, 701.3], [112.6, 37.9, 735.7]]
        assert stored_version.climb == 34.4
        assert stored_route.climb == 34.4
        assert json.loads(stored_route.elevation_profile) == profile
        assert json.loads(stored_guide.elevation_profile) == profile
        assert metadata["elevation"]["method"] == "glo30_meaningful_ascent_v1"
        assert metadata["elevation"]["source_name"] == "Copernicus DEM GLO-30 Public"
        assert metadata["elevation"]["processing_grid_m"] == 20.0
        assert metadata["elevation"]["dataset_id"] == "COP-DEM_GLO-30-DGED"
        assert metadata["elevation"]["vertical_datum"] == "EGM2008 (EPSG:3855)"
        assert metadata["elevation"]["grid_registration"] == "RasterPixelIsPoint"
    finally:
        _drop_route_guides_table(db)


def test_backfill_missing_with_glo_updates_only_missing_current_versions(db):
    from app.route_book.models import RouteVersion
    from scripts.backfill_route_elevation import backfill_missing_with_glo

    route, version = _route_with_current_version(db)

    def fake_query(coords):
        _assert_fixed_grid_query(coords)
        return _linear_elevations(coords)

    updated = backfill_missing_with_glo(
        db,
        query_func=fake_query,
        source_name="Copernicus DEM GLO-30 Public",
        license_id="Copernicus DEM Licence",
        accuracy_m=4.0,
        dry_run=False,
    )

    stored_version = db.query(RouteVersion).filter(RouteVersion.id == version.id).one()
    metadata = json.loads(stored_version.navigation_metadata_json)

    assert updated == 1
    assert json.loads(stored_version.elevation_points_snapshot) == [[112.5, 37.8, 701.3], [112.6, 37.9, 735.7]]
    assert route.id == stored_version.route_book_id
    assert metadata["elevation"]["method"] == "glo30_meaningful_ascent_v1"


def test_backfill_missing_with_glo_refreshes_all_product_visible_route_meetups(db):
    from app.meetup.models import Meetup
    from scripts.backfill_route_elevation import backfill_missing_with_glo

    route, _version = _route_with_current_version(db)
    now = datetime.now(timezone.utc)
    linked_meetups = [
        _route_meetup(
            db,
            route.id,
            status="DRAFT",
            start_time=now - timedelta(days=1),
        ),
        _route_meetup(
            db,
            route.id,
            status="OPEN",
            start_time=now + timedelta(days=1),
        ),
        _route_meetup(
            db,
            route.id,
            status="OPEN",
            start_time=now - timedelta(hours=1),
        ),
        _route_meetup(
            db,
            route.id,
            status="COMPLETED",
            start_time=now - timedelta(days=1),
        ),
        _route_meetup(
            db,
            route.id,
            status="CANCELLED",
            start_time=now + timedelta(days=1),
        ),
    ]
    db.commit()
    meetup_ids = [meetup.id for meetup in linked_meetups]

    updated = backfill_missing_with_glo(
        db,
        query_func=_linear_elevations,
        dry_run=False,
    )

    refreshed = db.query(Meetup).filter(Meetup.id.in_(meetup_ids)).all()
    assert updated == 1
    assert {meetup.snapshot_climb for meetup in refreshed} == {34.4}


def test_backfill_missing_with_glo_repairs_meetup_for_already_trusted_route(db):
    from app.meetup.models import Meetup
    from scripts.backfill_route_elevation import backfill_missing_with_glo

    route, _version = _route_with_current_version(db)
    assert backfill_missing_with_glo(
        db,
        query_func=_linear_elevations,
        dry_run=False,
    ) == 1
    future_meetup = _route_meetup(
        db,
        route.id,
        status="OPEN",
        start_time=datetime.now(timezone.utc) + timedelta(days=1),
    )
    db.commit()
    meetup_id = future_meetup.id

    def unexpected_query(_coords):
        raise AssertionError("可信 GLO 路线不应重复查询底图")

    updated = backfill_missing_with_glo(
        db,
        query_func=unexpected_query,
        dry_run=False,
    )

    stored_meetup = db.query(Meetup).filter(Meetup.id == meetup_id).one()
    assert updated == 0
    assert stored_meetup.snapshot_climb == 34.4


def test_backfill_missing_with_glo_repairs_legacy_glo_route_without_canonical_grid(db):
    from app.route_book.models import RouteVersion
    from scripts.backfill_route_elevation import backfill_missing_with_glo

    _route, version = _route_with_current_version(db)
    assert backfill_missing_with_glo(
        db,
        query_func=_linear_elevations,
        dry_run=False,
    ) == 1
    version.elevation_grid_snapshot = None
    db.add(version)
    db.commit()

    calls = []

    def recording_query(coords):
        calls.append(coords)
        return _linear_elevations(coords)

    updated = backfill_missing_with_glo(
        db,
        query_func=recording_query,
        dry_run=False,
    )

    stored = db.query(RouteVersion).filter(RouteVersion.id == version.id).one()
    assert updated == 1
    assert len(calls) == 1
    assert stored.elevation_grid_snapshot is not None


def test_backfill_missing_with_glo_tolerates_database_without_meetups_table(db):
    from scripts.backfill_route_elevation import backfill_missing_with_glo

    _route_with_current_version(db)
    db.execute(text("DROP TABLE meetups"))
    db.commit()

    updated = backfill_missing_with_glo(
        db,
        query_func=_linear_elevations,
        dry_run=False,
    )

    assert updated == 1


def test_backfill_missing_with_glo_keeps_successful_routes_when_one_route_fails(db):
    from app.route_book.models import RouteVersion
    from scripts.backfill_route_elevation import backfill_missing_with_glo

    first_route, first_version = _route_with_current_version(db)
    second_route, second_version = _route_with_current_version(db)
    calls = 0

    def one_success_one_failure(coords):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("simulated tile failure")
        return _linear_elevations(coords)

    with pytest.raises(RuntimeError, match=str(second_route.id)):
        backfill_missing_with_glo(
            db,
            query_func=one_success_one_failure,
            dry_run=False,
        )

    db.expire_all()
    stored_first = db.query(RouteVersion).filter(RouteVersion.id == first_version.id).one()
    stored_second = db.query(RouteVersion).filter(RouteVersion.id == second_version.id).one()
    assert first_route.id != second_route.id
    assert stored_first.elevation_points_snapshot is not None
    assert stored_second.elevation_points_snapshot is None


def test_backfill_missing_with_glo_isolates_reference_line_precheck_failure(db, monkeypatch):
    from app.route_book.models import RouteVersion
    from scripts import backfill_route_elevation as script

    first_route, first_version = _route_with_current_version(db)
    second_route, second_version = _route_with_current_version(db)
    original_parser = script._points_from_wkt
    parse_calls = 0

    def one_valid_one_invalid_reference_line(value):
        nonlocal parse_calls
        parse_calls += 1
        # 实际写入由 elevation_workflow 的解析器负责；这里第二次就是下一条的预检查。
        if parse_calls == 2:
            raise ValueError("simulated invalid reference line")
        return original_parser(value)

    monkeypatch.setattr(script, "_points_from_wkt", one_valid_one_invalid_reference_line)

    with pytest.raises(RuntimeError, match=str(second_route.id)):
        script.backfill_missing_with_glo(
            db,
            query_func=_linear_elevations,
            dry_run=False,
        )

    db.expire_all()
    stored_first = db.query(RouteVersion).filter(RouteVersion.id == first_version.id).one()
    stored_second = db.query(RouteVersion).filter(RouteVersion.id == second_version.id).one()
    assert first_route.id != second_route.id
    assert stored_first.elevation_grid_snapshot is not None
    assert stored_second.elevation_grid_snapshot is None


def test_backfill_missing_with_glo_overwrites_complete_untrusted_snapshot(db):
    from app.route_book.models import RouteVersion
    from scripts.backfill_route_elevation import backfill_missing_with_glo

    _route, version = _route_with_current_version(db)
    version.elevation_points_snapshot = "[[112.5,37.8,1.0],[112.6,37.9,2.0]]"
    version.navigation_metadata_json = None
    db.add(version)
    db.commit()

    def fake_query(coords):
        _assert_fixed_grid_query(coords)
        return _linear_elevations(coords)

    updated = backfill_missing_with_glo(
        db,
        query_func=fake_query,
        source_name="Copernicus DEM GLO-30 Public",
        license_id="Copernicus DEM Licence",
        accuracy_m=4.0,
        dry_run=False,
    )

    stored_version = db.query(RouteVersion).filter(RouteVersion.id == version.id).one()
    metadata = json.loads(stored_version.navigation_metadata_json)

    assert updated == 1
    assert json.loads(stored_version.elevation_points_snapshot) == [[112.5, 37.8, 701.3], [112.6, 37.9, 735.7]]
    assert metadata["elevation"]["method"] == "glo30_meaningful_ascent_v1"
    assert metadata["elevation"]["horizontal_resolution_m"] == 30.0


def test_backfill_missing_with_glo_dry_run_rolls_back(db):
    from app.route_book.models import RouteVersion
    from scripts.backfill_route_elevation import backfill_missing_with_glo

    _route, version = _route_with_current_version(db)

    def fake_query(coords):
        return _linear_elevations(coords)

    updated = backfill_missing_with_glo(
        db,
        query_func=fake_query,
        dry_run=True,
    )

    stored_version = db.query(RouteVersion).filter(RouteVersion.id == version.id).one()
    assert updated == 1
    assert stored_version.elevation_points_snapshot is None
    assert stored_version.elevation_grid_snapshot is None
    assert stored_version.navigation_metadata_json is None


def test_virtual_gpx_experiment_runs_import_glo_fill_export_loop():
    from scripts.experiment_route_glo_export import run_experiment

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
    assert all(item["gpx_ele_count"] == item["export_point_count"] for item in report["items"])
    assert all(item["tcx_altitude_count"] == item["export_point_count"] for item in report["items"])
