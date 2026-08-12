from datetime import datetime, timezone
from pathlib import Path
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from app.elevation.route_elevation import ROUTE_ELEVATION_METHOD, RouteElevationResult
from app.route_cognition.census_models import SegmentElevationFact
from app.route_cognition.segment_elevation_facts import (
    SOURCE_GEOMETRY_NORMALIZATION_VERSION,
    build_segment_elevation_fact,
    canonical_source_line_wkt,
    points_from_linestring_wkt,
    source_geometry_hash,
)
from scripts.backfill_segment_elevation_facts import (
    _audit_source_incomplete_items,
    _commit_fact_batch,
    _partition_source_rows,
    _post_commit_result,
    compute_fact_batch,
    main,
    readback_fact_batch,
)


def _result_for(points):
    elevations = [100.0, 125.0, 150.0]
    return RouteElevationResult(
        snapshot=[[*point, elevations[index]] for index, point in enumerate(points)],
        profile=[[0.0, 100.0], [1.0, 125.0], [2.0, 150.0]],
        climb=50.0,
        descent=0.0,
        point_count=len(points),
    )


def test_source_geometry_hash_is_stable_across_postgis_wkt_formatting():
    compact = points_from_linestring_wkt(
        "LINESTRING(112.3 37.8,112.31 37.81,112.32 37.82)"
    )
    padded = points_from_linestring_wkt(
        " LINESTRING (112.3000000 37.8000000, 112.3100000 37.8100000, 112.3200000 37.8200000) "
    )

    assert compact == padded
    assert canonical_source_line_wkt(compact) == (
        "LINESTRING (112.3000000 37.8000000, 112.3100000 37.8100000, "
        "112.3200000 37.8200000)"
    )
    assert source_geometry_hash(compact) == source_geometry_hash(padded)


def test_complete_fact_separates_profile_ascent_net_change_and_gradient():
    fact = build_segment_elevation_fact(
        source_observation_id=7,
        source_segment_id="25967365",
        source_line_wkt=(
            "LINESTRING(112.3 37.8,112.31 37.81,112.32 37.82)"
        ),
        source_point_count=3,
        source_distance_m=2800.0,
        elevation_builder=_result_for,
        computed_at=datetime(2026, 8, 13, tzinfo=timezone.utc),
    )

    assert fact["fact_status"] == "complete"
    assert fact["algorithm_version"] == ROUTE_ELEVATION_METHOD
    assert (
        fact["geometry_normalization_version"]
        == SOURCE_GEOMETRY_NORMALIZATION_VERSION
    )
    assert fact["elevation_point_count"] == fact["source_point_count"] == 3
    assert fact["climb_m"] == 50.0
    assert fact["descent_m"] == 0.0
    assert fact["net_elevation_change_m"] == 50.0
    assert fact["average_gradient_pct"] > 0
    assert fact["maximum_gradient_pct"] >= 0
    assert fact["maximum_gradient_window_m"] > 0
    assert fact["method_metadata_json"]["method"] == ROUTE_ELEVATION_METHOD
    assert fact["quality_flags_json"]["absolute_elevation_status"] == (
        "not_tested_no_absolute_reference"
    )
    assert fact["failure_json"] is None


def test_dem_failure_is_a_saved_fact_outcome_not_a_missing_row():
    def fail(_points):
        raise ConnectionError("tile unavailable")

    fact = build_segment_elevation_fact(
        source_observation_id=8,
        source_segment_id="40127007",
        source_line_wkt=(
            "LINESTRING(112.3 37.8,112.31 37.81,112.32 37.82)"
        ),
        source_point_count=3,
        source_distance_m=1000.0,
        elevation_builder=fail,
    )

    assert fact["fact_status"] == "failed"
    assert len(fact["source_geometry_hash"]) == 64
    assert fact["elevation_snapshot_json"] is None
    assert fact["derived_distance_m"] is None
    assert fact["failure_json"] == {
        "stage": "glo30_elevation",
        "error": "ConnectionError:tile unavailable",
    }
    assert fact["quality_flags_json"]["source_distance_status"] == (
        "anomaly_over_5pct"
    )


def test_geometry_eligibility_does_not_depend_on_detail_status():
    observation = SimpleNamespace(
        id=9,
        source_segment_id="40127008",
        detail_status="failed",
        geometry_status="complete",
        geometry_point_count=3,
    )
    rows = [
        (
            observation,
            "LINESTRING(112.3 37.8,112.31 37.81,112.32 37.82)",
        )
    ]

    eligible, incomplete = _partition_source_rows(rows)

    assert eligible == rows
    assert incomplete == []


def test_zero_length_source_geometry_is_incomplete_before_fact_building():
    observation = SimpleNamespace(
        id=10,
        source_segment_id="40127009",
        detail_status="complete",
        geometry_status="complete",
        geometry_point_count=2,
    )

    eligible, incomplete = _partition_source_rows(
        [(observation, "LINESTRING(112.3 37.8,112.3 37.8)")]
    )

    assert eligible == []
    assert incomplete[0]["source_segment_id"] == "40127009"
    assert incomplete[0]["reasons"][0].startswith("geometry_invalid:ValueError:")


def test_nullable_jsonb_fact_columns_bind_python_none_as_sql_null():
    for name in (
        "elevation_snapshot_json",
        "elevation_profile_json",
        "failure_json",
    ):
        assert SegmentElevationFact.__table__.c[name].type.none_as_null is True


def test_source_incomplete_account_binds_observation_id_segment_id_and_reasons():
    valid_ids, valid_errors = _audit_source_incomplete_items(
        [
            {
                "source_observation_id": 7,
                "source_segment_id": "25967365",
                "reasons": ["geometry_status:failed"],
            }
        ],
        {7: "25967365"},
    )
    invalid_ids, invalid_errors = _audit_source_incomplete_items(
        [
            {
                "source_observation_id": 7,
                "source_segment_id": "wrong",
                "reasons": [],
            }
        ],
        {7: "25967365"},
    )

    assert valid_ids == {7}
    assert valid_errors == []
    assert invalid_ids == {7}
    assert invalid_errors == [
        "item_0:source_segment_id_mismatch",
        "item_0:invalid_reasons",
    ]


@pytest.mark.parametrize(
    "value",
    [
        "POINT(112.3 37.8)",
        "LINESTRING Z(112.3 37.8 900,112.4 37.9 950)",
        "LINESTRING(112.3 37.8)",
    ],
)
def test_source_geometry_parser_rejects_non_2d_complete_lines(value):
    with pytest.raises(ValueError):
        points_from_linestring_wkt(value)


def test_migration_has_short_revision_and_append_only_fact_tables():
    path = Path("migrations/versions/20260813_seg_elev_facts.py")
    migration = path.read_text(encoding="utf-8")

    assert len("20260813_seg_elev_facts") <= 32
    assert 'down_revision = "20260813_seg_census"' in migration
    assert "segment_elevation_fact_batches" in migration
    assert "segment_elevation_facts" in migration
    assert "reject_segment_census_mutation" in migration
    assert "complete_count + failed_count = eligible_geometry_count" in migration
    assert "uq_segment_elev_fact_batch_observation" in migration
    assert "uq_segment_elev_fact_batch_attempt" in migration
    assert "input_observation_set_hash" in migration


def test_cli_returns_nonzero_when_an_attempt_has_failures(monkeypatch, capsys):
    monkeypatch.setattr(
        "scripts.backfill_segment_elevation_facts._parse_args",
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(
        "scripts.backfill_segment_elevation_facts.run",
        lambda _args: {
            "database_status": "committed_and_read_back",
            "run_status": "completed_with_failures",
        },
    )

    assert main() == 4
    assert "completed_with_failures" in capsys.readouterr().out


def test_post_commit_readback_failure_reports_unknown_not_uncommitted(monkeypatch):
    monkeypatch.setattr(
        "scripts.backfill_segment_elevation_facts.readback_fact_batch",
        lambda _db, _batch_id: (_ for _ in ()).throw(ConnectionError("readback down")),
    )

    result = _post_commit_result(object(), "xishan-fact-test")

    assert result["database_status"] == "committed_outcome_unknown"
    assert result["batch_id"] == "xishan-fact-test"
    assert "--readback-batch-id xishan-fact-test" in result["reconcile_with"]


def test_postgres_elevation_fact_tables_are_append_only():
    database_url = os.getenv("VELO_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("仅在 CI 的临时 PostgreSQL/PostGIS 上验证事实表不可变触发器")
    engine = create_engine(database_url)
    census_id = f"test-{uuid4().hex}"
    fact_batch_id = f"fact-{uuid4().hex}"
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO segment_census_batches (
                    id, region_key, region_version, source_platform,
                    activity_type, protocol_version, visibility_context,
                    root_south, root_west, root_north, root_east, max_depth,
                    run_status, enumeration_status, request_status,
                    snapshot_status, detail_status, geometry_status,
                    leaderboard_status, planned_request_count,
                    attempted_request_count, succeeded_request_count,
                    failed_request_count, blocked_request_count,
                    unique_segment_count, included_segment_count,
                    outside_segment_count, unknown_membership_count,
                    detail_complete_count, geometry_complete_count,
                    leaderboard_complete_count, saturated_cell_count, error_count,
                    region_definition_json, region_polygon,
                    pass_summaries_json, pass_diff_json, raw_response_retained,
                    started_at, finished_at
                ) VALUES (
                    :id, 'test', 'test_v1', 'strava', 'riding', 'test_v1',
                    'test', 37, 112, 38, 113, 0, 'completed',
                    'source_visible_complete', 'complete', 'complete',
                    'not_collected', 'not_collected', 'not_collected',
                    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                    '{}'::jsonb,
                    ST_GeomFromText('POLYGON((112 37,113 37,113 38,112 38,112 37))', 4326),
                    '[]'::jsonb, '{}'::jsonb, false, now(), now()
                )
                """
            ),
            {"id": census_id},
        )
        connection.execute(
            text(
                """
                INSERT INTO segment_elevation_fact_batches (
                    id, census_batch_id, scope, algorithm_version,
                    geometry_normalization_version, attempt_number,
                    input_observation_set_hash, run_status,
                    input_observation_count, eligible_geometry_count,
                    source_incomplete_count, source_incomplete_json,
                    complete_count, failed_count, started_at, finished_at
                ) VALUES (
                    :id, :census_id, 'inside_or_crosses',
                    'glo30_meaningful_ascent_v1',
                    'strava_source_line_lonlat_7dp_v1', 1,
                    repeat('0', 64), 'completed_with_failures',
                    1, 0, 1,
                    '[{"source_observation_id":1,"source_segment_id":"1",'
                    '"reasons":["test"]}]'::jsonb,
                    0, 0, now(), now()
                )
                """
            ),
            {"id": fact_batch_id, "census_id": census_id},
        )
        trigger_names = connection.execute(
            text(
                """
                SELECT tgname FROM pg_trigger
                WHERE NOT tgisinternal
                  AND tgrelid IN (
                      'segment_elevation_fact_batches'::regclass,
                      'segment_elevation_facts'::regclass
                  )
                """
            )
        ).scalars().all()
    assert set(trigger_names) == {
        "trg_segment_elevation_fact_batches_append_only",
        "trg_segment_elevation_fact_batches_no_truncate",
        "trg_segment_elevation_facts_append_only",
        "trg_segment_elevation_facts_no_truncate",
    }
    with pytest.raises(DBAPIError, match="append-only"):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE segment_elevation_fact_batches "
                    "SET run_status='completed' WHERE id=:id"
                ),
                {"id": fact_batch_id},
            )


def test_postgres_fact_writer_accounts_every_selected_observation():
    database_url = os.getenv("VELO_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("仅在 CI 的临时 PostgreSQL/PostGIS 上验证事实 writer 与回读")
    engine = create_engine(database_url)
    census_id = f"test-{uuid4().hex}"
    failed_batch_id = f"fact-failed-{uuid4().hex}"
    fact_batch_id = f"fact-complete-{uuid4().hex}"
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO segment_census_batches (
                    id, region_key, region_version, source_platform,
                    activity_type, protocol_version, visibility_context,
                    root_south, root_west, root_north, root_east, max_depth,
                    run_status, enumeration_status, request_status,
                    snapshot_status, detail_status, geometry_status,
                    leaderboard_status, planned_request_count,
                    attempted_request_count, succeeded_request_count,
                    failed_request_count, blocked_request_count,
                    unique_segment_count, included_segment_count,
                    outside_segment_count, unknown_membership_count,
                    detail_complete_count, geometry_complete_count,
                    leaderboard_complete_count, saturated_cell_count, error_count,
                    region_definition_json, region_polygon,
                    pass_summaries_json, pass_diff_json, raw_response_retained,
                    started_at, finished_at
                ) VALUES (
                    :id, 'test', 'test_v1', 'strava', 'riding', 'test_v1',
                    'test', 37, 112, 38, 113, 0, 'completed',
                    'source_visible_complete', 'complete', 'complete',
                    'complete', 'complete', 'not_collected',
                    0, 0, 0, 0, 0, 1, 1, 0, 0, 1, 1, 0, 0, 0,
                    '{}'::jsonb,
                    ST_GeomFromText('POLYGON((112 37,113 37,113 38,112 38,112 37))', 4326),
                    '[]'::jsonb, '{}'::jsonb, false, now(), now()
                )
                """
            ),
            {"id": census_id},
        )
        connection.execute(
            text(
                """
                INSERT INTO segment_source_observations (
                    census_batch_id, source_platform, source_segment_id,
                    source_url, source_name, observed_at, activity_type,
                    distance_m, start_lat, start_lon, end_lat, end_lon,
                    source_line, geometry_point_count, geometry_original_size,
                    geometry_resolution, query_bounds_relation, region_membership,
                    seen_passes_json, detail_status, geometry_status,
                    leaderboard_status
                ) VALUES (
                    :batch_id, 'strava', '25967365',
                    'https://www.strava.com/segments/25967365', '测试赛段', now(),
                    'Ride', 2800.0, 37.8, 112.3, 37.82, 112.32,
                    ST_GeomFromText(
                        'LINESTRING(112.3 37.8,112.31 37.81,112.32 37.82)',
                        4326
                    ),
                    3, 3, 'high', 'inside', 'inside',
                    '{"1":["cell"],"2":["cell"]}'::jsonb,
                    'complete', 'complete', 'not_collected'
                )
                """
            ),
            {"batch_id": census_id},
        )
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    db = Session()
    try:
        failed_batch, failed_facts = compute_fact_batch(
            db,
            census_batch_id=census_id,
            batch_id=failed_batch_id,
            attempt_number=1,
            elevation_builder=lambda _points: (_ for _ in ()).throw(
                ConnectionError("temporary tile failure")
            ),
        )
        assert failed_batch.run_status == "completed_with_failures"
        assert failed_batch.failed_count == 1
        assert _commit_fact_batch(db, failed_batch, failed_facts) is None
        failed_result = readback_fact_batch(db, failed_batch_id)
        assert failed_result["database_status"] == "committed_and_read_back"
        assert failed_result["elevation_fact_batch_status"] == "incomplete"

        batch, facts = compute_fact_batch(
            db,
            census_batch_id=census_id,
            batch_id=fact_batch_id,
            attempt_number=2,
            elevation_builder=_result_for,
        )
        assert batch.input_observation_count == 1
        assert batch.eligible_geometry_count == 1
        assert batch.complete_count == 1
        assert batch.failed_count == 0
        assert _commit_fact_batch(db, batch, facts) is None

        result = readback_fact_batch(db, fact_batch_id)
        assert result["database_status"] == "committed_and_read_back"
        assert result["stored_fact_count"] == 1
        assert result["distinct_observation_count"] == 1
        assert result["distinct_source_id_count"] == 1
        assert result["point_mismatch_count"] == 0
        assert result["method_mismatch_count"] == 0
        assert result["attempt_number"] == 2
        assert result["exact_observation_set_match"] is True
        assert result["elevation_fact_batch_status"] == "complete"
        assert result["single_segment_foundation_status"] == (
            "not_certified_axes_reported_separately"
        )
        sql_null = db.execute(
            text(
                "SELECT failure_json IS NULL "
                "FROM segment_elevation_facts WHERE fact_batch_id=:batch_id"
            ),
            {"batch_id": fact_batch_id},
        ).scalar_one()
        assert sql_null is True
        failed_sql_nulls = db.execute(
            text(
                "SELECT elevation_snapshot_json IS NULL, "
                "elevation_profile_json IS NULL, failure_json IS NOT NULL "
                "FROM segment_elevation_facts WHERE fact_batch_id=:batch_id"
            ),
            {"batch_id": failed_batch_id},
        ).one()
        assert tuple(failed_sql_nulls) == (True, True, True)

        db.execute(
            text(
                """
                INSERT INTO segment_source_observations (
                    census_batch_id, source_platform, source_segment_id,
                    source_url, source_name, observed_at, activity_type,
                    distance_m, start_lat, start_lon, end_lat, end_lon,
                    source_line, geometry_point_count, geometry_original_size,
                    geometry_resolution, query_bounds_relation, region_membership,
                    seen_passes_json, detail_status, geometry_status,
                    leaderboard_status
                ) VALUES (
                    :batch_id, 'strava', '40127007',
                    'https://www.strava.com/segments/40127007', '后插赛段', now(),
                    'Ride', 2800.0, 37.8, 112.3, 37.82, 112.32,
                    ST_GeomFromText(
                        'LINESTRING(112.3 37.8,112.31 37.81,112.32 37.82)',
                        4326
                    ),
                    3, 3, 'high', 'inside', 'inside',
                    '{"1":["cell"],"2":["cell"]}'::jsonb,
                    'complete', 'complete', 'not_collected'
                )
                """
            ),
            {"batch_id": census_id},
        )
        db.commit()
        drifted_result = readback_fact_batch(db, fact_batch_id)
        assert drifted_result["database_status"] == "readback_mismatch"
        assert drifted_result["exact_observation_set_match"] is False
    finally:
        db.close()
