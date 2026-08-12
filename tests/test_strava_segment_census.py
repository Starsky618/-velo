from datetime import datetime, timezone
import os
from uuid import uuid4

import pytest
import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from app.route_cognition.strava_census import (
    Bounds,
    compare_passes,
    enumerate_source_visible_segments,
    fetch_segment_observation,
    parse_duration_seconds,
)
from app.strava.client import (
    StravaClient,
    StravaRateLimitError,
    reserve_strava_read_attempt,
)
from app.route_cognition.xishan_region import POLYGON_LON_LAT
from scripts.census_strava_segments import (
    CensusAttemptGovernor,
    _commit_census_transaction,
    _post_commit_result,
    _request_status,
)


class FakeExploreClient:
    def __init__(self, root: Bounds):
        self.root = root
        self.calls = []

    def explore_segments(self, bounds):
        self.calls.append(bounds)
        if bounds == self.root.as_tuple():
            return {"segments": [{"id": value} for value in range(1, 11)]}
        south, west, _north, _east = bounds
        segment_id = int(round((south + west) * 1000))
        return {"segments": [{"id": segment_id}]}


def test_saturated_explore_cell_is_split_and_deduplicated():
    root = Bounds(37.0, 112.0, 38.0, 113.0)
    client = FakeExploreClient(root)

    result = enumerate_source_visible_segments(client, root, max_depth=1)

    assert result.request_count == 5
    assert len(result.cells) == 5
    assert not result.saturated_cells
    assert not result.errors
    assert set(range(1, 11)).issubset(result.segment_ids)


def test_still_full_at_max_depth_is_not_hidden():
    root = Bounds(37.0, 112.0, 38.0, 113.0)
    client = FakeExploreClient(root)

    result = enumerate_source_visible_segments(client, root, max_depth=0)

    assert result.request_count == 1
    assert result.saturated_cells == [root.key(0)]
    assert result.cells[0]["status"] == "saturated"


def test_pass_comparison_reports_both_directions():
    root = Bounds(37.0, 112.0, 38.0, 113.0)

    class FixedClient:
        def __init__(self, values):
            self.values = values

        def explore_segments(self, _bounds):
            return {"segments": [{"id": value} for value in self.values]}

    first = enumerate_source_visible_segments(FixedClient([1, 2]), root, max_depth=0)
    second = enumerate_source_visible_segments(FixedClient([2, 3]), root, max_depth=0)

    assert compare_passes(first, second) == {
        "identical": False,
        "only_in_pass_1": [1],
        "only_in_pass_2": [3],
    }


class FakeDetailClient:
    def get_segment_detail(self, segment_id):
        return {
            "id": segment_id,
            "name": "桃花沟爬坡",
            "activity_type": "Ride",
            "distance": 1234.5,
            "average_grade": 4.2,
            "maximum_grade": 11.0,
            "total_elevation_gain": 55.0,
            "elevation_high": 1000.0,
            "elevation_low": 945.0,
            "athlete_count": 99,
            "effort_count": 188,
            "star_count": 7,
            "start_latlng": [37.8, 112.3],
            "end_latlng": [37.81, 112.31],
            "xoms": {"kom": "16:32", "qom": "1:02:03", "overall": "16:32"},
            "created_at": "2020-01-02T03:04:05Z",
            "updated_at": "2026-01-02T03:04:05Z",
        }

    def get_segment_latlng_stream(self, _segment_id):
        return {
            "latlng": {
                "data": [[37.8, 112.3], [37.81, 112.31]],
                "original_size": 2,
                "resolution": "high",
            },
            "distance": {"data": [0, 1234.5], "original_size": 2},
        }


def test_observation_keeps_exact_geometry_but_discards_extra_streams():
    observed_at = datetime(2026, 8, 13, tzinfo=timezone.utc)
    result = fetch_segment_observation(
        FakeDetailClient(),
        25967365,
        {"id": 25967365, "name": "summary"},
        seen_passes={"1": ["a"], "2": ["a"]},
        root_bounds=Bounds(37.65, 112.23, 38.02, 112.46),
        region_polygon=POLYGON_LON_LAT,
        observed_at=observed_at,
    )

    assert result["detail_status"] == "complete"
    assert result["geometry_status"] == "complete"
    assert result["geometry_point_count"] == 2
    assert result["geometry_original_size"] == 2
    assert result["source_line_wkt"] == (
        "LINESTRING (112.3000000 37.8000000, 112.3100000 37.8100000)"
    )
    assert result["query_bounds_relation"] == "inside"
    assert result["region_membership"] == "crosses"
    assert result["elevation_gain_m"] == 55.0
    assert result["kom_time_s"] == 992
    assert result["qom_time_s"] == 3723
    assert "distance_stream" not in result
    assert result["failure_json"] is None


def test_observation_accepts_legacy_elevation_difference():
    client = FakeDetailClient()
    original = client.get_segment_detail

    def legacy_detail(segment_id):
        detail = original(segment_id)
        detail["elevation_difference"] = detail.pop("total_elevation_gain")
        return detail

    client.get_segment_detail = legacy_detail
    result = fetch_segment_observation(
        client,
        25967365,
        {},
        seen_passes={"1": ["a"]},
        root_bounds=Bounds(37.65, 112.23, 38.02, 112.49),
        region_polygon=POLYGON_LON_LAT,
        observed_at=datetime.now(timezone.utc),
    )

    assert result["elevation_gain_m"] == 55.0


def test_observation_preserves_zero_total_elevation_gain():
    client = FakeDetailClient()
    original = client.get_segment_detail

    def flat_detail(segment_id):
        detail = original(segment_id)
        detail["total_elevation_gain"] = 0
        detail["elevation_difference"] = 55.0
        return detail

    client.get_segment_detail = flat_detail
    result = fetch_segment_observation(
        client,
        25967365,
        {},
        seen_passes={"1": ["a"]},
        root_bounds=Bounds(37.65, 112.23, 38.02, 112.49),
        region_polygon=POLYGON_LON_LAT,
        observed_at=datetime.now(timezone.utc),
    )

    assert result["elevation_gain_m"] == 0.0


def test_incomplete_stream_is_explicit_failure():
    client = FakeDetailClient()
    client.get_segment_latlng_stream = lambda _segment_id: {
        "latlng": {
            "data": [[37.8, 112.3], [37.81, 112.31]],
            "original_size": 3,
            "resolution": "high",
        }
    }
    result = fetch_segment_observation(
        client,
        25967365,
        {},
        seen_passes={"1": ["a"]},
        root_bounds=Bounds(37.65, 112.23, 38.02, 112.46),
        region_polygon=POLYGON_LON_LAT,
        observed_at=datetime.now(timezone.utc),
    )

    assert result["geometry_status"] == "failed"
    assert result["source_line_wkt"] is None
    assert "geometry" in result["failure_json"]


def test_duration_parser_rejects_invalid_values():
    assert parse_duration_seconds("16:32") == 992
    assert parse_duration_seconds("1:02:03") == 3723
    assert parse_duration_seconds("1:99") is None
    assert parse_duration_seconds(None) is None


def test_strava_client_uses_official_segment_endpoints():
    client = object.__new__(StravaClient)
    calls = []
    client._request = lambda method, path, params=None: calls.append(
        (method, path, params)
    ) or {}

    client.explore_segments((37.65, 112.23, 38.02, 112.46))
    client.get_segment_detail(123)
    client.get_segment_latlng_stream(123)

    assert calls == [
        (
            "GET",
            "/segments/explore",
            {
                "bounds": "37.6500000,112.2300000,38.0200000,112.4600000",
                "activity_type": "riding",
            },
        ),
        ("GET", "/segments/123", None),
        (
            "GET",
            "/segments/123/streams",
            {"keys": "latlng", "key_by_type": "true"},
        ),
    ]


def test_strava_retry_passes_same_attempt_governor(monkeypatch):
    attempts = []
    user = type("User", (), {"id": 7, "strava_access_token": "token"})()
    monkeypatch.setattr(
        "app.strava.client.ensure_valid_token",
        lambda _db, _user_id: (user, "token"),
    )
    responses = iter(
        [httpx.Response(500, json={}), httpx.Response(200, json={"ok": True})]
    )
    monkeypatch.setattr("app.strava.client.httpx.request", lambda *a, **k: next(responses))
    client = StravaClient(object(), user, attempt_governor=lambda: attempts.append(1))

    assert client._request("GET", "/segments/1") == {"ok": True}
    assert len(attempts) == 2


def test_shared_strava_rate_limit_reserves_both_counters_atomically(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "app.strava.client._redis.eval",
        lambda *args: calls.append(args) or [1, 12, 7],
    )

    reserve_strava_read_attempt(fail_closed=True)

    assert len(calls) == 1
    assert calls[0][1] == 2
    assert calls[0][4] == 2000
    assert calls[0][5] == 200


def test_shared_strava_rate_limit_rejects_full_window(monkeypatch):
    monkeypatch.setattr(
        "app.strava.client._redis.eval",
        lambda *_args: [0, 500, 200],
    )

    with pytest.raises(StravaRateLimitError, match="配额已满"):
        reserve_strava_read_attempt(fail_closed=True)


def test_census_governor_reserves_before_counting(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "scripts.census_strava_segments.reserve_strava_read_attempt",
        lambda **kwargs: calls.append(kwargs),
    )
    governor = CensusAttemptGovernor(4.6, 2)
    governor.before_http_attempt()

    assert governor.attempted_request_count == 1
    assert governor.blocked_request_count == 0
    assert len(calls) == 1


def test_census_governor_fails_closed_when_redis_is_unavailable(monkeypatch):
    def fail(**_kwargs):
        raise ConnectionError("redis down")

    monkeypatch.setattr(
        "scripts.census_strava_segments.reserve_strava_read_attempt",
        fail,
    )
    governor = CensusAttemptGovernor(4.6, 2)

    with pytest.raises(RuntimeError, match="未获共享配额"):
        governor.before_http_attempt()
    assert governor.attempted_request_count == 0


def test_request_status_is_incomplete_for_failed_or_blocked_calls():
    governor = CensusAttemptGovernor(4.6, 2)
    governor.begin_logical_request()
    governor.fail_logical_request(blocked=False)

    assert _request_status(governor) == "incomplete"
    assert governor.planned_request_count == 1
    assert governor.failed_request_count == 1

    governor = CensusAttemptGovernor(4.6, 2)
    governor.begin_logical_request()
    governor.fail_logical_request(blocked=True)

    assert _request_status(governor) == "incomplete"
    assert governor.blocked_request_count == 1


def test_request_status_is_complete_only_when_all_planned_calls_succeed():
    governor = CensusAttemptGovernor(4.6, 2)
    governor.begin_logical_request()
    governor.finish_logical_request()

    assert _request_status(governor) == "complete"
    assert governor.succeeded_request_count == governor.planned_request_count == 1


def test_post_commit_readback_failure_is_not_reported_as_uncommitted(monkeypatch):
    monkeypatch.setattr(
        "scripts.census_strava_segments._readback_batch",
        lambda _batch_id: (_ for _ in ()).throw(ConnectionError("readback down")),
    )

    result = _post_commit_result("xishan-test")

    assert result["database_status"] == "committed_outcome_unknown"
    assert result["batch_id"] == "xishan-test"
    assert "--readback-batch-id xishan-test" in result["reconcile_with"]


def test_commit_ack_failure_is_reported_as_outcome_unknown():
    class CountQuery:
        def filter(self, *_args):
            return self

        def scalar(self):
            return 3

    class CommitAckLostSession:
        def flush(self):
            return None

        def query(self, *_args):
            return CountQuery()

        def commit(self):
            raise ConnectionError("commit ack lost")

        def rollback(self):
            return None

    result = _commit_census_transaction(
        CommitAckLostSession(),
        batch_id="xishan-ack-lost",
        expected_observation_count=3,
    )

    assert result["database_status"] == "committed_outcome_unknown"
    assert result["batch_id"] == "xishan-ack-lost"
    assert "--readback-batch-id xishan-ack-lost" in result["reconcile_with"]


def test_postgres_census_snapshots_are_append_only():
    database_url = os.getenv("VELO_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("仅在 CI 的临时 PostgreSQL/PostGIS 上验证不可变触发器")
    engine = create_engine(database_url)
    batch_id = f"test-{uuid4().hex}"
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
                    unique_segment_count,
                    included_segment_count, outside_segment_count,
                    unknown_membership_count,
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
                    2, 2, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                    '{}'::jsonb, ST_GeomFromText('POLYGON((112 37,113 37,113 38,112 38,112 37))', 4326),
                    '[]'::jsonb, '{}'::jsonb, false,
                    now(), now()
                )
                """
            ),
            {"id": batch_id},
        )
        trigger_names = connection.execute(
            text(
                """
                SELECT tgname FROM pg_trigger
                WHERE NOT tgisinternal
                  AND tgrelid IN (
                      'segment_census_batches'::regclass,
                      'segment_source_observations'::regclass
                  )
                """
            )
        ).scalars().all()
    assert set(trigger_names) == {
        "trg_segment_census_batches_append_only",
        "trg_segment_census_batches_no_truncate",
        "trg_segment_source_observations_append_only",
        "trg_segment_source_observations_no_truncate",
    }
    with pytest.raises(DBAPIError, match="append-only"):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE segment_census_batches "
                    "SET run_status='completed_with_errors' WHERE id=:id"
                ),
                {"id": batch_id},
            )
