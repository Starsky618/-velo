"""路线导出底座测试——先把“谁能拿到哪一版路线文件”钉牢。"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import CheckConstraint, ForeignKeyConstraint


_TRUSTED_ELEVATION_METADATA = (
    "{\"elevation\":{\"method\":\"glo30_meaningful_ascent_v1\","
    "\"source_name\":\"Copernicus DEM GLO-30 Public\","
    "\"license_id\":\"Copernicus DEM Licence\","
    "\"accuracy_m\":4.0,"
    "\"horizontal_resolution_m\":30.0,"
    "\"processing_grid_m\":20.0,"
    "\"median_filter_points\":3,"
    "\"smoothing_sigma_m\":100.0,"
    "\"ascent_prominence_m\":3.0,"
    "\"ascent_minimum_span_m\":100.0,"
    "\"maximum_processing_distance_m\":1000000.0,"
    "\"dataset_id\":\"COP-DEM_GLO-30-DGED\","
    "\"vertical_datum\":\"EGM2008 (EPSG:3855)\","
    "\"grid_registration\":\"RasterPixelIsPoint\","
    "\"point_count\":2}}"
)


def _trusted_elevation_metadata_with_grid(*, point_count: int, grid_point_count: int) -> str:
    import json

    metadata = json.loads(_TRUSTED_ELEVATION_METADATA)
    elevation = metadata["elevation"]
    elevation["point_count"] = point_count
    elevation["elevation_grid_schema"] = "distance_elevation_v1"
    elevation["elevation_grid_point_count"] = grid_point_count
    return json.dumps(metadata)


def _check_sql(table, name: str) -> str:
    checks = [
        constraint
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint) and constraint.name == name
    ]
    assert checks
    return str(checks[0].sqltext)


def _composite_fk(table, name: str) -> ForeignKeyConstraint:
    fks = [
        constraint
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint) and constraint.name == name
    ]
    assert fks
    return fks[0]


def test_route_export_job_model_is_version_bound_and_v1_only():
    from app.route_book.models import RouteExportJob

    columns = RouteExportJob.__table__.c
    assert {
        "id",
        "route_book_id",
        "route_version_id",
        "requester_id",
        "target_platform",
        "export_format",
        "export_mode",
        "status",
        "simplification_strategy_json",
        "target_constraints_json",
        "include_course_points",
        "error_code",
        "error_message",
        "created_at",
        "started_at",
        "finished_at",
    } <= set(columns.keys())
    assert columns.route_book_id.nullable is False
    assert columns.route_version_id.nullable is False
    assert str(columns.export_mode.server_default.arg) == "download_file"
    assert str(columns.status.server_default.arg) == "queued"
    assert str(columns.include_course_points.server_default.arg).lower() == "false"

    format_sql = _check_sql(RouteExportJob.__table__, "ck_route_export_jobs_format")
    assert "gpx" in format_sql
    assert "tcx" in format_sql
    assert "fit" not in format_sql.lower()

    mode_sql = _check_sql(RouteExportJob.__table__, "ck_route_export_jobs_mode")
    assert "download_file" in mode_sql
    assert "manual_upload" in mode_sql
    assert "platform_sync" not in mode_sql

    status_sql = _check_sql(RouteExportJob.__table__, "ck_route_export_jobs_status")
    for status in ("queued", "running", "succeeded", "failed", "cancelled"):
        assert status in status_sql

    course_points_sql = _check_sql(RouteExportJob.__table__, "ck_route_export_jobs_no_course_points")
    assert "include_course_points" in course_points_sql
    assert "false" in course_points_sql.lower()

    fk = _composite_fk(RouteExportJob.__table__, "fk_route_export_jobs_route_version_book")
    assert {element.parent.name for element in fk.elements} == {"route_version_id", "route_book_id"}

    index_names = {index.name for index in RouteExportJob.__table__.indexes}
    assert {
        "idx_route_export_jobs_route_version",
        "idx_route_export_jobs_route_book",
        "idx_route_export_jobs_requester",
        "idx_route_export_jobs_status_created",
        "idx_route_export_jobs_format",
    } <= index_names


def test_route_export_artifact_model_keeps_internal_file_id_and_version_binding():
    from app.route_book.models import RouteExportArtifact

    columns = RouteExportArtifact.__table__.c
    assert {
        "id",
        "export_job_id",
        "route_book_id",
        "route_version_id",
        "format",
        "file_id",
        "file_size",
        "content_hash",
        "input_point_count",
        "output_point_count",
        "generated_at",
        "expires_at",
        "metadata_json",
    } <= set(columns.keys())
    assert columns.export_job_id.nullable is False
    assert columns.route_book_id.nullable is False
    assert columns.route_version_id.nullable is False
    assert columns.file_id.nullable is False

    format_sql = _check_sql(RouteExportArtifact.__table__, "ck_route_export_artifacts_format")
    assert "gpx" in format_sql
    assert "tcx" in format_sql
    assert "fit" not in format_sql.lower()

    fk = _composite_fk(RouteExportArtifact.__table__, "fk_route_export_artifacts_route_version_book")
    assert {element.parent.name for element in fk.elements} == {"route_version_id", "route_book_id"}

    index_names = {index.name for index in RouteExportArtifact.__table__.indexes}
    assert {
        "idx_route_export_artifacts_job",
        "idx_route_export_artifacts_route_version",
        "idx_route_export_artifacts_route_book",
        "idx_route_export_artifacts_content_hash",
        "idx_route_export_artifacts_expires",
    } <= index_names


def test_export_generator_builds_gpx_with_required_elevation_snapshot():
    from app.route_book.export_generator import generate_route_export

    generated = generate_route_export(
        route_name="天龙山<>路书",
        reference_line_snapshot="SRID=4326;LINESTRING(112.5 37.8, 112.6 37.9)",
        elevation_points_snapshot="[[112.5,37.8,701.2],[112.6,37.9,735.8]]",
        elevation_metadata_json=_TRUSTED_ELEVATION_METADATA,
        export_format="gpx",
    )

    text = generated.content.decode("utf-8")
    assert generated.point_count == 2
    assert generated.content_type == "application/gpx+xml"
    assert "<gpx" in text
    assert "<trk>" in text
    assert "<trkseg>" in text
    assert '<trkpt lat="37.8" lon="112.5">' in text
    assert '<trkpt lat="37.9" lon="112.6">' in text
    assert "<ele>701.2</ele>" in text
    assert "<ele>735.8</ele>" in text
    assert "<TrainingCenterDatabase" not in text


def test_gpx_export_preserves_route_result_climb():
    import json
    import math
    from xml.etree import ElementTree

    import numpy as np

    from app.elevation.dem_client import (
        GLO30_HORIZONTAL_RESOLUTION_M,
        GLO30_LICENSE_ID,
        GLO30_SOURCE_NAME,
        GLO30_VERTICAL_ACCURACY_M,
    )
    from app.elevation.route_elevation import (
        ROUTE_ELEVATION_METHOD,
        _cumulative_distances,
        _meaningful_ascent,
        build_route_elevation_result,
        route_elevation_metadata,
    )
    from app.route_book.export_generator import generate_route_export

    points = [[112.5, 37.8], [112.55, 37.8]]

    def fake_query(coords):
        # 约 4.4km 的宽缓单峰；山峰位于稀疏参考线两端之间。
        return [
            800.0 + 100.0 * math.sin(math.pi * ((lon - 112.5) / 0.05)) ** 2
            for _lat, lon in coords
        ]

    route_result = build_route_elevation_result(points, query_func=fake_query)
    metadata = {
        "elevation": {
            "method": ROUTE_ELEVATION_METHOD,
            "source_name": GLO30_SOURCE_NAME,
            "license_id": GLO30_LICENSE_ID,
            "accuracy_m": GLO30_VERTICAL_ACCURACY_M,
            "horizontal_resolution_m": GLO30_HORIZONTAL_RESOLUTION_M,
            "point_count": route_result.point_count,
            "elevation_grid_schema": "distance_elevation_v1",
            "elevation_grid_point_count": len(route_result.elevation_grid),
            **route_elevation_metadata(),
        }
    }
    generated = generate_route_export(
        route_name="合成单峰路线",
        reference_line_snapshot="SRID=4326;LINESTRING(112.5 37.8, 112.55 37.8)",
        elevation_points_snapshot=json.dumps(route_result.snapshot),
        elevation_grid_snapshot=json.dumps(
            {
                "schema": "distance_elevation_v1",
                "line_hash": "synthetic-line",
                "points": route_result.elevation_grid,
            }
        ),
        reference_line_hash="synthetic-line",
        elevation_metadata_json=json.dumps(metadata),
        export_format="gpx",
    )

    root = ElementTree.fromstring(generated.content)
    namespace = {"gpx": "http://www.topografix.com/GPX/1/1"}
    exported_points = [
        [
            float(node.attrib["lon"]),
            float(node.attrib["lat"]),
            float(node.find("gpx:ele", namespace).text),
        ]
        for node in root.findall(".//gpx:trkpt", namespace)
    ]
    assert len(exported_points) == len(route_result.elevation_grid)
    assert exported_points[0][:2] == points[0]
    assert exported_points[-1][:2] == points[-1]
    assert all(point[1] == 37.8 for point in exported_points)
    exported_distances = np.asarray(
        _cumulative_distances([(point[0], point[1]) for point in exported_points]),
        dtype=float,
    )
    exported_climb = _meaningful_ascent(
        np.asarray([point[2] for point in exported_points], dtype=float),
        exported_distances,
    )

    assert route_result.climb > 90.0
    tolerance_m = max(5.0, route_result.climb * 0.005)
    assert abs(route_result.climb - exported_climb) <= tolerance_m, (
        f"页面爬升 {route_result.climb}m，导出 GPX 复算 {exported_climb}m，"
        f"差值超过 {tolerance_m}m"
    )


def test_export_generator_rejects_canonical_grid_not_bound_to_reference_line():
    import json

    import pytest

    from app.elevation.route_elevation import build_route_elevation_result, route_distance_m
    from app.route_book.export_generator import generate_route_export

    points = [[112.5, 37.8], [112.55, 37.8]]
    distance = route_distance_m(points)
    result = build_route_elevation_result(
        points,
        query_func=lambda coords: [
            800.0 + 50.0 * index / (len(coords) - 1)
            for index, _coord in enumerate(coords)
        ],
    )
    metadata = _trusted_elevation_metadata_with_grid(
        point_count=2,
        grid_point_count=len(result.elevation_grid),
    )
    base = {
        "schema": "distance_elevation_v1",
        "line_hash": "wrong-line",
        "points": result.elevation_grid,
    }
    with pytest.raises(ValueError, match="canonical"):
        generate_route_export(
            route_name="错绑网格",
            reference_line_snapshot="SRID=4326;LINESTRING(112.5 37.8, 112.55 37.8)",
            elevation_points_snapshot="[[112.5,37.8,800.0],[112.55,37.8,850.0]]",
            elevation_grid_snapshot=json.dumps(base),
            reference_line_hash="expected-line",
            elevation_metadata_json=metadata,
            export_format="gpx",
        )

    base["line_hash"] = "expected-line"
    base["points"][-1][0] = round(distance + 100.0, 3)
    with pytest.raises(ValueError, match="canonical"):
        generate_route_export(
            route_name="越界网格",
            reference_line_snapshot="SRID=4326;LINESTRING(112.5 37.8, 112.55 37.8)",
            elevation_points_snapshot="[[112.5,37.8,800.0],[112.55,37.8,850.0]]",
            elevation_grid_snapshot=json.dumps(base),
            reference_line_hash="expected-line",
            elevation_metadata_json=metadata,
            export_format="gpx",
        )


def test_canonical_grid_parser_rejects_incomplete_or_unphysical_values():
    import copy
    import json
    import math

    from app.elevation.route_elevation import build_route_elevation_result, route_distance_m
    from app.route_book.elevation_quality import parse_complete_elevation_grid

    route_points = [[112.5, 37.8], [112.55, 37.8]]
    distance = route_distance_m(route_points)
    result = build_route_elevation_result(
        route_points,
        query_func=lambda coords: [800.0 + index * 0.1 for index, _coord in enumerate(coords)],
    )
    valid = result.elevation_grid
    metadata = _trusted_elevation_metadata_with_grid(
        point_count=2,
        grid_point_count=len(valid),
    )
    valid_payload = json.dumps(
        {
            "schema": "distance_elevation_v1",
            "line_hash": "expected-line",
            "points": valid,
        }
    )
    assert parse_complete_elevation_grid(
        valid_payload,
        expected_line_hash="expected-line",
        expected_distance_m=distance,
        metadata_json=metadata,
    ) is not None

    wrong_start = copy.deepcopy(valid)
    wrong_start[0][0] = 1.0
    duplicate_chainage = copy.deepcopy(valid)
    duplicate_chainage[1][0] = duplicate_chainage[0][0]
    nan_elevation = copy.deepcopy(valid)
    nan_elevation[-1][1] = math.nan
    impossible_elevation = copy.deepcopy(valid)
    impossible_elevation[-1][1] = 9001.0
    wrong_spacing = copy.deepcopy(valid)
    wrong_spacing[len(wrong_spacing) // 2][0] += 1.0
    extra_coordinate_columns = copy.deepcopy(valid)
    extra_coordinate_columns[1].extend([112.5, 37.8])
    invalid_grids = [
        wrong_start,
        duplicate_chainage,
        nan_elevation,
        impossible_elevation,
        valid[:-1],
        wrong_spacing,
        extra_coordinate_columns,
    ]
    for points in invalid_grids:
        payload = json.dumps(
            {
                "schema": "distance_elevation_v1",
                "line_hash": "expected-line",
                "points": points,
            }
        )
        assert parse_complete_elevation_grid(
            payload,
            expected_line_hash="expected-line",
            expected_distance_m=distance,
            metadata_json=metadata,
        ) is None

    bad_metadata = json.loads(metadata)
    bad_metadata["elevation"]["elevation_grid_point_count"] -= 1
    assert parse_complete_elevation_grid(
        valid_payload,
        expected_line_hash="expected-line",
        expected_distance_m=distance,
        metadata_json=json.dumps(bad_metadata),
    ) is None


def test_canonical_export_preserves_sharp_turn_and_out_and_back_vertices():
    import json
    from xml.etree import ElementTree

    from app.elevation.route_elevation import build_route_elevation_result
    from app.route_book.export_generator import generate_route_export

    routes = [
        [[112.5, 37.8], [112.5001, 37.8], [112.5001, 37.8002]],
        [[112.5, 37.8], [112.5002, 37.8], [112.5, 37.8]],
    ]
    namespace = {"gpx": "http://www.topografix.com/GPX/1/1"}
    for route_points in routes:
        result = build_route_elevation_result(
            route_points,
            query_func=lambda coords: [800.0 for _coord in coords],
        )
        line_hash = "sharp-turn-line"
        reference_line = "SRID=4326;LINESTRING(" + ", ".join(
            f"{lon} {lat}" for lon, lat in route_points
        ) + ")"
        generated = generate_route_export(
            route_name="急弯保真探针",
            reference_line_snapshot=reference_line,
            elevation_points_snapshot=json.dumps(result.snapshot),
            elevation_grid_snapshot=json.dumps(
                {
                    "schema": "distance_elevation_v1",
                    "line_hash": line_hash,
                    "points": result.elevation_grid,
                }
            ),
            reference_line_hash=line_hash,
            elevation_metadata_json=_trusted_elevation_metadata_with_grid(
                point_count=len(route_points),
                grid_point_count=len(result.elevation_grid),
            ),
            export_format="gpx",
        )
        root = ElementTree.fromstring(generated.content)
        exported = [
            [float(node.attrib["lon"]), float(node.attrib["lat"])]
            for node in root.findall(".//gpx:trkpt", namespace)
        ]

        cursor = 0
        for expected in route_points:
            matching_index = next(
                (
                    index
                    for index in range(cursor, len(exported))
                    if abs(exported[index][0] - expected[0]) <= 1e-8
                    and abs(exported[index][1] - expected[1]) <= 1e-8
                ),
                None,
            )
            assert matching_index is not None
            cursor = matching_index + 1


def test_export_generator_rejects_elevation_coordinates_that_do_not_match_route():
    from app.route_book.export_generator import generate_route_export

    try:
        generate_route_export(
            route_name="坐标错配探针",
            reference_line_snapshot="SRID=4326;LINESTRING(112.5 37.8, 112.6 37.9)",
            elevation_points_snapshot="[[120,30,701.2],[121,31,735.8]]",
            elevation_metadata_json=_TRUSTED_ELEVATION_METADATA,
            export_format="gpx",
        )
    except ValueError as exc:
        assert "坐标" in str(exc)
    else:
        raise AssertionError("海拔快照不属于参考线时必须拒绝导出，不能改写路线坐标")


def test_export_generator_rejects_gpx_without_complete_elevation_snapshot():
    from app.route_book.export_generator import generate_route_export

    for snapshot in (None, "[[112.5,37.8,701.2],[112.6,37.9,null]]", "[[112.5,37.8,701.2]]"):
        try:
            generate_route_export(
                route_name="奥申",
                reference_line_snapshot="SRID=4326;LINESTRING(112.5 37.8, 112.6 37.9)",
                elevation_points_snapshot=snapshot,
                elevation_metadata_json=_TRUSTED_ELEVATION_METADATA,
                export_format="gpx",
            )
        except ValueError as exc:
            assert "海拔" in str(exc)
        else:
            raise AssertionError("缺完整逐点海拔时不该生成码表文件")


def test_export_generator_rejects_complete_but_untrusted_elevation_snapshot():
    from app.route_book.export_generator import generate_route_export

    try:
        generate_route_export(
            route_name="旧 GPX 海拔",
            reference_line_snapshot="SRID=4326;LINESTRING(112.5 37.8, 112.6 37.9)",
            elevation_points_snapshot="[[112.5,37.8,701.2],[112.6,37.9,735.8]]",
            elevation_metadata_json=None,
            export_format="gpx",
        )
    except ValueError as exc:
        assert "统一海拔源" in str(exc)
    else:
        raise AssertionError("缺可信海拔来源时不该生成码表文件")


def test_export_generator_builds_tcx_with_required_elevation_snapshot():
    from app.route_book.export_generator import generate_route_export

    generated = generate_route_export(
        route_name="汾河训练线",
        reference_line_snapshot="SRID=4326;LINESTRING(112.5 37.8, 112.6 37.9)",
        elevation_points_snapshot="[[112.5,37.8,701.2],[112.6,37.9,735.8]]",
        elevation_metadata_json=_TRUSTED_ELEVATION_METADATA,
        export_format="tcx",
    )

    text = generated.content.decode("utf-8")
    assert generated.point_count == 2
    assert generated.content_type == "application/vnd.garmin.tcx+xml"
    assert "<TrainingCenterDatabase" in text
    assert "<Courses>" in text
    assert "<Course>" in text
    assert "<Trackpoint>" in text
    assert "<LatitudeDegrees>37.8</LatitudeDegrees>" in text
    assert "<LongitudeDegrees>112.5</LongitudeDegrees>" in text
    assert "<AltitudeMeters>701.2</AltitudeMeters>" in text
    assert "<AltitudeMeters>735.8</AltitudeMeters>" in text
    assert "<CoursePoint>" not in text


def test_export_generator_rejects_routes_with_too_few_points():
    from app.route_book.export_generator import generate_route_export

    try:
        generate_route_export(
            route_name="坏路线",
            reference_line_snapshot="SRID=4326;LINESTRING(112.5 37.8)",
            export_format="gpx",
        )
    except ValueError as exc:
        assert "至少需要 2 个坐标点" in str(exc)
    else:
        raise AssertionError("单点路线不该生成可下载文件")


def test_route_export_permissions_keep_private_and_unlisted_routes_closed():
    from app.route_book.export_service import can_export_route

    owner_id = 11
    stranger_id = 22
    private_route = SimpleNamespace(
        id=1,
        creator_id=owner_id,
        visibility="private",
        publish_status="draft",
    )
    public_route = SimpleNamespace(
        id=2,
        creator_id=owner_id,
        visibility="public",
        publish_status="published",
    )
    unlisted_route = SimpleNamespace(
        id=3,
        creator_id=owner_id,
        visibility="unlisted",
        publish_status="published",
    )

    assert can_export_route(private_route, current_user_id=owner_id)
    assert can_export_route(private_route, current_user_id=stranger_id, is_admin=True)
    assert not can_export_route(private_route, current_user_id=stranger_id)
    assert can_export_route(public_route, current_user_id=stranger_id)
    assert can_export_route(public_route, current_user_id=None)
    assert not can_export_route(unlisted_route, current_user_id=stranger_id)

    valid_share = SimpleNamespace(
        route_book_id=unlisted_route.id,
        status="active",
        can_export=True,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    view_only_share = SimpleNamespace(
        route_book_id=unlisted_route.id,
        status="active",
        can_export=False,
        expires_at=None,
    )
    expired_share = SimpleNamespace(
        route_book_id=unlisted_route.id,
        status="active",
        can_export=True,
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    assert can_export_route(unlisted_route, current_user_id=stranger_id, share_link=valid_share)
    assert not can_export_route(unlisted_route, current_user_id=None, share_link=valid_share)
    assert not can_export_route(unlisted_route, current_user_id=stranger_id, share_link=view_only_share)
    assert not can_export_route(unlisted_route, current_user_id=stranger_id, share_link=expired_share)


def test_artifact_download_permission_never_exposes_someone_elses_file_id():
    from app.route_book.export_service import can_download_export_artifact

    artifact = SimpleNamespace(
        id=101,
        export_job_id=201,
        route_book_id=7,
        route_version_id=9,
        format="gpx",
        file_id="exports/secret-route.gpx",
        expires_at=None,
    )
    job = SimpleNamespace(
        id=201,
        requester_id=33,
        route_book_id=7,
        route_version_id=9,
        export_format="gpx",
    )
    route = SimpleNamespace(id=7, creator_id=44, visibility="private", publish_status="draft")
    wrong_route = SimpleNamespace(id=8, creator_id=44, visibility="private", publish_status="draft")

    assert can_download_export_artifact(artifact, current_user_id=33, job=job, route=route)
    assert not can_download_export_artifact(artifact, current_user_id=33, job=job, route=wrong_route)
    assert not can_download_export_artifact(artifact, current_user_id=44, job=job, route=route)
    assert can_download_export_artifact(artifact, current_user_id=55, job=job, route=route, is_admin=True)
    assert not can_download_export_artifact(artifact, current_user_id=55, job=job, route=route)
    assert not can_download_export_artifact(artifact, current_user_id=None, job=job, route=route)


def test_artifact_download_rejects_artifact_job_version_or_format_mismatch():
    from app.route_book.export_service import can_download_export_artifact

    route = SimpleNamespace(id=7, creator_id=44, visibility="public", publish_status="published")
    artifact = SimpleNamespace(
        id=101,
        export_job_id=201,
        route_book_id=7,
        route_version_id=9,
        format="gpx",
        file_id="exports/secret-route.gpx",
        expires_at=None,
    )
    job = SimpleNamespace(
        id=201,
        requester_id=None,
        route_book_id=7,
        route_version_id=9,
        export_format="gpx",
    )

    assert can_download_export_artifact(artifact, current_user_id=None, job=job, route=route)

    wrong_job_id = SimpleNamespace(**{**job.__dict__, "id": 202})
    wrong_route_id = SimpleNamespace(**{**job.__dict__, "route_book_id": 8})
    wrong_version = SimpleNamespace(**{**job.__dict__, "route_version_id": 10})
    wrong_format = SimpleNamespace(**{**job.__dict__, "export_format": "tcx"})

    assert not can_download_export_artifact(artifact, current_user_id=None, job=wrong_job_id, route=route)
    assert not can_download_export_artifact(artifact, current_user_id=None, job=wrong_route_id, route=route)
    assert not can_download_export_artifact(artifact, current_user_id=None, job=wrong_version, route=route)
    assert not can_download_export_artifact(artifact, current_user_id=None, job=wrong_format, route=route)


def test_batch3_migration_creates_export_tables_without_share_or_fit_scope():
    migration = Path("migrations/versions/20260618_route_exports.py")
    assert migration.exists()
    text = migration.read_text(encoding="utf-8")

    assert "op.create_table" in text
    assert '"route_export_jobs"' in text
    assert '"route_export_artifacts"' in text
    assert "route_share_links" not in text
    assert "platform_sync" not in text
    assert "'fit'" not in text
