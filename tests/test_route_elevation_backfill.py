import csv
import json


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
