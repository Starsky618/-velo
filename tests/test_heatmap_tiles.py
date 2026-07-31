from io import BytesIO
from concurrent.futures import ThreadPoolExecutor
import json
import math
from datetime import datetime, timezone
import os
from threading import Event
import uuid
import zlib
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
import xyconvert

from app.user.service_heatmap_tiles import (
    InvalidHeatmapTile,
    _OVERVIEW_MAP_CACHE,
    _OVERVIEW_SOURCE_CACHE,
    _claim_derived_cache_build,
    _clip_vector_segments_to_bounds,
    _DETAIL_SOURCE_CHUNK_CACHE,
    _available_heatmap_years_cached,
    _get_detail_segments_cached_for_bounds,
    _get_overview_segments_cached,
    _get_overview_map_segments_cached,
    _global_pixel,
    _limit_vector_segments,
    _map_coords_to_wgs84,
    _load_overview_segments,
    _partition_detail_segments,
    _render_tile_png,
    _raw_points_must_split,
    _sample_overview_segment,
    _tile_bounds_gcj02,
    _tile_query_bounds_wgs84,
    _trim_vector_cache,
    _vector_point_budget_for_zoom,
    _wgs84_to_map_coords,
    build_user_heatmap_detail_source,
    get_user_heatmap_tile,
    get_user_heatmap_viewport,
)
from app.activity.models import Activity, ActivityPrivacy, Trackpoint
from app.user.models import User
from app.user.service_social import (
    HeatmapSnapshotChanged,
    _encode_heatmap_cache,
    enqueue_heatmap_cache_prewarm,
    get_user_heatmap,
    prewarm_heatmap_cache_task,
)


@pytest.fixture(scope="module")
def tile_pg_engine():
    database_url = (
        os.getenv("VELO_TEST_DATABASE_URL")
        or os.getenv("DATABASE_URL")
        or "postgresql://velo:velo@localhost:5435/velo"
    )
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        pytest.skip(f"dev stack PostgreSQL 不可用: {exc}")
    yield engine
    engine.dispose()


@pytest.fixture()
def tile_pg_session_factory(tile_pg_engine):
    return sessionmaker(bind=tile_pg_engine, autocommit=False, autoflush=False)


@pytest.fixture(scope="module")
def tile_real_redis():
    from app.queue import redis_conn

    try:
        redis_conn.ping()
    except Exception as exc:
        pytest.skip(f"dev stack Redis 不可用: {exc}")
    yield redis_conn


def _tile_for(lon: float, lat: float, zoom: int) -> tuple[int, int]:
    count = 1 << zoom
    x = int((lon + 180) / 360 * count)
    radians = math.radians(lat)
    y = int((1 - math.asinh(math.tan(radians)) / math.pi) / 2 * count)
    return x, y


def test_tile_bounds_match_web_mercator_coordinate():
    zoom = 12
    x, y = _tile_for(112.55, 37.85, zoom)
    west, south, east, north = _tile_bounds_gcj02(zoom, x, y)

    assert west < 112.55 < east
    assert south < 37.85 < north


def test_coordinate_conversion_matches_miniprogram_and_preserves_foreign_routes():
    coords = np.array([[112.55, 37.85], [-122.4194, 37.7749]], dtype=np.float64)
    map_coords = _wgs84_to_map_coords(coords)

    assert not np.allclose(map_coords[0], coords[0])
    assert np.allclose(map_coords[1], coords[1])
    assert np.allclose(_map_coords_to_wgs84(map_coords), coords, atol=2e-5)


def test_high_zoom_query_buffer_keeps_points_across_tile_edge():
    zoom = 18
    x, y = _tile_for(112.55, 37.85, zoom)
    west, south, east, north = _tile_query_bounds_wgs84(zoom, x, y)

    assert east - west > 0.008
    assert north - south > 0.008


def test_raw_jump_filter_does_not_invent_route_across_recording_gap():
    start_time = datetime(2025, 1, 1, tzinfo=timezone.utc)
    assert _raw_points_must_split(
        (112.5, 37.8),
        (112.52, 37.82),
        start_time,
        start_time.replace(minute=2),
    )
    assert not _raw_points_must_split(
        (112.5, 37.8),
        (112.5001, 37.8001),
        start_time,
        start_time.replace(second=2),
    )


def test_raw_gap_keeps_legitimate_sparse_points_when_time_and_speed_are_plausible():
    start_time = datetime(2025, 1, 1, tzinfo=timezone.utc)

    assert not _raw_points_must_split(
        (112.5000, 37.8000),
        (112.5068, 37.8000),
        start_time,
        start_time.replace(second=30),
    )


def test_raster_tile_preserves_bend_and_uses_strong_nontransparent_color():
    zoom = 14
    x, y = _tile_for(112.55, 37.85, zoom)
    west, south, east, north = _tile_bounds_gcj02(zoom, x, y)
    # 先在地图使用的 GCJ-02 空间构造明显折角，再转回数据库 WGS-84 输入。
    gcj = np.array(
        [
            [west + (east - west) * 0.2, south + (north - south) * 0.2],
            [west + (east - west) * 0.5, south + (north - south) * 0.8],
            [west + (east - west) * 0.8, south + (north - south) * 0.2],
        ],
        dtype=np.float64,
    )
    wgs = xyconvert.gcj2wgs(gcj)
    png = _render_tile_png(
        {1: [[(float(point[0]), float(point[1])) for point in wgs]]},
        zoom,
        x,
        y,
        "red",
    )
    image = Image.open(BytesIO(png)).convert("RGBA")
    alpha = np.asarray(image)[:, :, 3]
    bend_global = _global_pixel(float(gcj[1, 0]), float(gcj[1, 1]), zoom)
    bend_x = int(round(bend_global[0] - x * 512))
    bend_y = int(round(bend_global[1] - y * 512))

    assert image.size == (512, 512)
    assert alpha.max() >= 240
    assert alpha[alpha > 0].min() >= 210
    assert alpha[max(0, bend_y - 2):bend_y + 3, max(0, bend_x - 2):bend_x + 3].max() > 0


def test_overview_sampling_preserves_sharp_bend_instead_of_uniformly_dropping_it():
    points = [(112.0 + index * 0.00001, 37.8) for index in range(2000)]
    points[1003] = (points[1003][0], 37.82)

    sampled = _sample_overview_segment(points)

    assert len(sampled) == 1000
    assert points[1003] in sampled


def test_detail_source_partition_keeps_bend_and_boundary_neighbors():
    source = {
        7: [[
            (112.4999, 37.8000),
            (112.5000, 37.8010),
            (112.5001, 37.8000),
        ]]
    }

    chunks = _partition_detail_segments(source)

    assert chunks
    stored_segments = [
        segment
        for chunk in chunks.values()
        for segment in chunk[7]
    ]
    assert any((112.5000, 37.8010) in segment for segment in stored_segments)
    assert all(len(segment) >= 2 for segment in stored_segments)


def test_detail_source_builds_manifest_last_and_serves_bounds_without_postgis():
    source = {
        7: [[
            (112.4999, 37.8000),
            (112.5000, 37.8010),
            (112.5001, 37.8000),
        ]]
    }
    stored = {}
    writes = []

    class Pipeline:
        def setex(self, key, ttl, value):
            writes.append((key, ttl, value))
            return self

        def execute(self):
            for key, _ttl, value in writes:
                stored[key] = value

    class Redis:
        def __init__(self):
            stored["heatmap:generation:user_42"] = b"9"

        def pipeline(self, transaction=False):
            assert transaction is False
            return Pipeline()

        def get(self, key):
            return stored.get(key)

        def mget(self, keys):
            return [stored.get(key) for key in keys]

        def delete(self, *keys):
            for key in keys:
                stored.pop(key, None)

    redis = Redis()
    _DETAIL_SOURCE_CHUNK_CACHE.clear()
    with patch(
        "app.user.service_heatmap_tiles._load_detail_segments",
        return_value=source,
    ):
        stats = build_user_heatmap_detail_source(
            Mock(),
            42,
            generation=9,
            activity_fingerprint="data-v1",
            redis_client=redis,
        )

    assert stats["tile_count"] >= 1
    assert stats["point_count"] >= 3
    assert writes[-1][0].endswith(":manifest")
    loaded = _get_detail_segments_cached_for_bounds(
        redis,
        42,
        9,
        "data-v1",
        None,
        True,
        None,
        112.49,
        37.79,
        112.51,
        37.81,
    )
    assert loaded == source
    _DETAIL_SOURCE_CHUNK_CACHE.clear()


def test_detail_source_reclaims_chunks_if_generation_changes_during_build():
    redis = Mock()
    pipeline = redis.pipeline.return_value
    redis.get.return_value = b"10"
    with patch(
        "app.user.service_heatmap_tiles._load_detail_segments",
        return_value={7: [[(112.5, 37.8), (112.6, 37.9)]]},
    ):
        build_user_heatmap_detail_source(
            Mock(),
            42,
            generation=9,
            activity_fingerprint="data-v1",
            redis_client=redis,
        )

    pipeline.execute.assert_called_once_with()
    assert redis.delete.call_count == 1
    assert any(str(key).endswith(":manifest") for key in redis.delete.call_args.args)


def test_prewarm_enqueue_coalesces_by_user_and_generation():
    queue = Mock()
    queue.fetch_job.return_value = None
    queued_job = Mock()
    queue.enqueue.return_value = queued_job

    with patch("app.queue.heatmap_prewarm_queue", queue):
        result = enqueue_heatmap_cache_prewarm(42, 7)

    assert result is queued_job
    queue.fetch_job.assert_called_once_with("heatmap-prewarm-v3-user-42-g7")
    queue.enqueue.assert_called_once()
    call = queue.enqueue.call_args
    assert call.args == (
        "app.user.service_social.prewarm_heatmap_cache_task",
        42,
        7,
    )
    assert call.kwargs["job_id"] == "heatmap-prewarm-v3-user-42-g7"
    assert call.kwargs["job_timeout"] == 300
    assert call.kwargs["result_ttl"] == 7 * 86400
    assert call.kwargs["failure_ttl"] == 3600
    assert call.kwargs["retry"].max == 2
    assert call.kwargs["retry"].intervals == [10, 60]


def test_prewarm_task_skips_generation_that_was_already_superseded():
    redis = Mock()
    redis.get.return_value = b"8"

    with (
        patch("app.user.service_social._get_redis_client", return_value=redis),
        patch("app.database.SessionLocal") as session_factory,
    ):
        result = prewarm_heatmap_cache_task(42, 7)

    assert result == {
        "status": "stale",
        "expected_generation": 7,
        "current_generation": 8,
    }
    session_factory.assert_not_called()


def test_prewarm_task_builds_current_owner_meta_and_closes_session():
    redis = Mock()
    redis.get.side_effect = [b"7", b"7"]
    db = Mock()

    with (
        patch("app.user.service_social._get_redis_client", return_value=redis),
        patch("app.database.SessionLocal", return_value=db),
        patch(
            "app.user.service_social.get_user_heatmap",
            return_value={"activity_count": 293},
        ) as build,
        patch(
            "app.user.service_social._heatmap_activity_fingerprint",
            return_value="data-v1",
        ),
        patch(
            "app.user.service_heatmap_tiles.build_user_heatmap_detail_source",
            return_value={
                "tile_count": 131,
                "point_count": 700_000,
                "compressed_bytes": 8_000_000,
            },
        ) as detail_build,
    ):
        result = prewarm_heatmap_cache_task(42, 7)

    assert result == {
        "status": "warmed",
        "generation": 7,
        "activity_count": 293,
        "detail_tile_count": 131,
        "detail_point_count": 700_000,
        "detail_compressed_bytes": 8_000_000,
    }
    build.assert_called_once_with(
        db,
        42,
        None,
        None,
        "meta",
        include_private=True,
    )
    detail_build.assert_called_once_with(
        db,
        42,
        year=None,
        include_private=True,
        generation=7,
        activity_fingerprint="data-v1",
        redis_client=redis,
    )
    db.close.assert_called_once_with()


def test_vector_lod_keeps_sharp_bend_and_respects_total_budget():
    points = [(112.0 + index * 0.00001, 37.8) for index in range(8000)]
    points[4003] = (points[4003][0], 37.82)

    prepared = _limit_vector_segments(
        {7: [points]},
        zoom=10,
        latitude=37.8,
        total_point_budget=6_000,
    )

    assert sum(len(segment) for _, segment in prepared) <= 6000
    assert points[4003] in prepared[0][1]


def test_vector_preview_budget_grows_with_zoom_without_returning_to_6000_point_damage():
    assert _vector_point_budget_for_zoom(9) == 12_000
    assert _vector_point_budget_for_zoom(11) == 12_000
    assert _vector_point_budget_for_zoom(12) == 12_000
    assert _vector_point_budget_for_zoom(13) == 12_000
    assert _vector_point_budget_for_zoom(14) == 14_000


def test_cached_overview_source_clips_to_viewport_and_keeps_crossing_segment():
    source = {
        7: [
            [(112.0, 37.8), (112.5, 37.8), (113.0, 37.8)],
            [(114.0, 39.0), (114.1, 39.1)],
        ]
    }

    clipped = _clip_vector_segments_to_bounds(source, 112.4, 37.7, 112.6, 37.9)

    assert clipped == {7: [[(112.0, 37.8), (112.5, 37.8), (113.0, 37.8)]]}


def test_available_heatmap_years_cache_avoids_per_block_trackpoint_query():
    redis = Mock()
    redis.get.return_value = b"[2026,2025]"
    db = Mock()

    years = _available_heatmap_years_cached(
        db,
        42,
        True,
        9,
        "data-v1",
        None,
        redis,
    )

    assert years == [2026, 2025]
    db.query.assert_not_called()
    redis.setex.assert_not_called()


def test_vector_viewport_cache_reuses_overview_source_without_second_db_scan():
    redis = Mock()
    redis.get.side_effect = [b"9", None]
    db = Mock()
    (
        db.query.return_value
        .join.return_value
        .filter.return_value
        .distinct.return_value
        .all.return_value
    ) = [(datetime(2025, 5, 1, tzinfo=timezone.utc),)]
    source = {7: [[(112.5, 37.8), (112.51, 37.83), (112.52, 37.82)]]}
    viewport = (112.4, 37.7, 112.7, 38.0, 11)
    with (
        patch("app.user.service_heatmap_tiles._get_redis_client", return_value=redis),
        patch(
            "app.user.service_heatmap_tiles._get_overview_segments_cached",
            return_value=source,
        ) as overview_loader,
        patch("app.user.service_heatmap_tiles._load_raw_segments_for_bounds") as raw_loader,
        patch(
            "app.user.service_heatmap_tiles._heatmap_activity_fingerprint",
            return_value="data-v1",
        ),
    ):
        first = get_user_heatmap_viewport(
            db, 42, viewport, activity_fingerprint="data-v1"
        )
        encoded = redis.setex.call_args.args[2]
        redis.get.side_effect = [b"9", encoded]
        second = get_user_heatmap_viewport(
            db, 42, viewport, activity_fingerprint="data-v1"
        )

    assert first == second
    assert first["activity_count"] == 1
    assert first["generation"] == 9
    assert first["available_years"] == [2025]
    assert first["tracks"] == [[[112.5, 37.8], [112.51, 37.83], [112.52, 37.82]]]
    assert overview_loader.call_count == 1
    assert raw_loader.call_count == 0
    assert redis.setex.call_args.args[0].startswith(
        "heatmap:vector:v3:user_42:g9:data_data-v1:year_all:audience_owner:"
    )
    redis.expire.assert_any_call(redis.setex.call_args.args[0], 900)
    redis.zadd.assert_called()


def test_high_zoom_vector_viewport_falls_back_to_raw_when_detail_source_is_missing():
    redis = Mock()
    redis.get.side_effect = [b"9", None]
    db = Mock()
    (
        db.query.return_value
        .join.return_value
        .filter.return_value
        .distinct.return_value
        .all.return_value
    ) = [(datetime(2025, 5, 1, tzinfo=timezone.utc),)]
    source = {7: [[(112.5, 37.8), (112.5001, 37.8002), (112.5002, 37.8)]]}
    with (
        patch("app.user.service_heatmap_tiles._get_redis_client", return_value=redis),
        patch(
            "app.user.service_heatmap_tiles._load_raw_segments_for_bounds",
            return_value=source,
        ) as raw_loader,
        patch(
            "app.user.service_heatmap_tiles._enqueue_detail_source_prewarm_if_needed",
        ) as enqueue_prewarm,
        patch("app.user.service_heatmap_tiles._get_overview_segments_cached") as overview_loader,
        patch(
            "app.user.service_heatmap_tiles._heatmap_activity_fingerprint",
            return_value="data-v1",
        ),
    ):
        result = get_user_heatmap_viewport(
            db,
            42,
            (112.49, 37.79, 112.51, 37.81, 14),
            activity_fingerprint="data-v1",
        )

    assert result["tracks"] == [
        [[112.5, 37.8], [112.5001, 37.8002], [112.5002, 37.8]]
    ]
    assert raw_loader.call_count == 1
    enqueue_prewarm.assert_called_once_with(42, 9, None, True)
    assert overview_loader.call_count == 0


def test_high_zoom_vector_viewport_uses_prebuilt_detail_source_without_postgis():
    redis = Mock()
    redis.get.side_effect = [b"9", None]
    db = Mock()
    (
        db.query.return_value
        .join.return_value
        .filter.return_value
        .distinct.return_value
        .all.return_value
    ) = [(datetime(2025, 5, 1, tzinfo=timezone.utc),)]
    source = {7: [[(112.5, 37.8), (112.5001, 37.8002), (112.5002, 37.8)]]}
    with (
        patch("app.user.service_heatmap_tiles._get_redis_client", return_value=redis),
        patch(
            "app.user.service_heatmap_tiles._get_detail_segments_cached_for_bounds",
            return_value=source,
        ) as detail_loader,
        patch("app.user.service_heatmap_tiles._load_raw_segments_for_bounds") as raw_loader,
        patch(
            "app.user.service_heatmap_tiles._heatmap_activity_fingerprint",
            return_value="data-v1",
        ),
    ):
        result = get_user_heatmap_viewport(
            db,
            42,
            (112.49, 37.79, 112.51, 37.81, 14),
            activity_fingerprint="data-v1",
        )

    assert result["tracks"] == [
        [[112.5, 37.8], [112.5001, 37.8002], [112.5002, 37.8]]
    ]
    assert detail_loader.call_count == 1
    assert raw_loader.call_count == 0


def test_vector_cache_waiter_reuses_builder_result_without_duplicate_query():
    expected = {"tracks": [[[112.5, 37.8], [112.6, 37.9]]]}
    encoded = zlib.compress(
        json.dumps(expected, separators=(",", ":")).encode(),
        level=6,
    )
    redis = Mock()
    redis.set.return_value = False
    redis.get.return_value = encoded

    lock, waited = _claim_derived_cache_build(
        redis,
        "heatmap:vector:v3:user_42:g7:test",
        lambda raw: json.loads(zlib.decompress(raw).decode()),
    )

    assert lock is None
    assert waited == expected


@pytest.mark.parametrize(
    "viewport",
    [
        (112.7, 37.7, 112.4, 38.0, 11),
        (112.4, 38.0, 112.7, 37.7, 11),
        (112.4, 37.7, 112.7, 38.0, 2),
        (112.4, 37.7, 112.7, 38.0, 21),
    ],
)
def test_vector_viewport_rejects_invalid_bounds_and_zoom(viewport):
    with pytest.raises(InvalidHeatmapTile):
        get_user_heatmap_viewport(
            Mock(), 42, viewport, activity_fingerprint="data-v1"
        )


def test_vector_cache_is_capped_per_user_after_continuous_pan():
    redis = Mock()
    keys = [
        f"heatmap:vector:v3:user_42:view_{index}".encode()
        for index in range(18)
    ]
    redis.scan_iter.return_value = keys
    redis.zscore.return_value = None
    redis.zrange.return_value = keys
    current = "heatmap:vector:v3:user_42:view_17"

    _trim_vector_cache(redis, 42, current)

    assert redis.delete.call_count == 1
    assert len(redis.delete.call_args.args) == 2
    assert redis.delete.call_args.args == (
        b"heatmap:vector:v3:user_42:view_0",
        b"heatmap:vector:v3:user_42:view_1",
    )
    assert current.encode() not in redis.delete.call_args.args


def test_tile_cache_uses_heatmap_generation_and_avoids_second_db_render():
    redis = Mock()
    redis.get.side_effect = [b"7", None, b"7", b"png"]
    with (
        patch("app.user.service_heatmap_tiles._get_redis_client", return_value=redis),
        patch("app.user.service_heatmap_tiles._get_overview_segments_cached", return_value={}) as loader,
        patch("app.user.service_heatmap_tiles._render_tile_png", return_value=b"png") as renderer,
        patch(
            "app.user.service_heatmap_tiles._heatmap_activity_fingerprint",
            return_value="data-v1",
        ),
    ):
        first = get_user_heatmap_tile(
            Mock(), 42, 12, 3328, 1582, color="orange", activity_fingerprint="data-v1"
        )
        second = get_user_heatmap_tile(
            Mock(), 42, 12, 3328, 1582, color="orange", activity_fingerprint="data-v1"
        )

    assert first == second == b"png"
    assert loader.call_count == 1
    assert renderer.call_count == 1
    assert redis.setex.call_args.args[1] == 86400
    assert redis.setex.call_args.args[0].startswith(
        "heatmap:raster:v2:user_42:g7:data_data-v1:year_all:audience_owner:color_orange:z12:"
    )


def test_public_tile_cache_changes_when_privacy_fingerprint_changes():
    redis = Mock()
    redis.get.side_effect = [b"3", None, b"3", None]
    with (
        patch("app.user.service_heatmap_tiles._get_redis_client", return_value=redis),
        patch(
            "app.user.service_heatmap_tiles._public_heatmap_privacy_fingerprint",
            side_effect=["1-1-before", "1-0-after"],
        ),
        patch("app.user.service_heatmap_tiles._get_overview_segments_cached", return_value={}),
        patch("app.user.service_heatmap_tiles._render_tile_png", return_value=b"png") as renderer,
        patch(
            "app.user.service_heatmap_tiles._heatmap_activity_fingerprint",
            return_value="data-v1",
        ),
    ):
        get_user_heatmap_tile(
            Mock(), 42, 12, 3328, 1582, include_private=False,
            activity_fingerprint="data-v1",
        )
        get_user_heatmap_tile(
            Mock(), 42, 12, 3328, 1582, include_private=False,
            activity_fingerprint="data-v1",
        )

    assert renderer.call_count == 2
    keys = [call.args[0] for call in redis.setex.call_args_list]
    assert any("privacy_1-1-before" in key for key in keys)
    assert any("privacy_1-0-after" in key for key in keys)


def test_tile_cache_retries_when_activity_snapshot_changes_during_cache_read():
    redis = Mock()
    redis.get.side_effect = [b"7", b"stale", b"7", b"fresh"]

    with (
        patch("app.user.service_heatmap_tiles._get_redis_client", return_value=redis),
        patch(
            "app.user.service_heatmap_tiles._heatmap_activity_fingerprint",
            side_effect=["old", "new", "new", "new"],
        ),
    ):
        result = get_user_heatmap_tile(Mock(), 42, 12, 3328, 1582)

    assert result == b"fresh"
    read_keys = [call.args[0] for call in redis.get.call_args_list]
    assert any(":data_old:" in str(key) for key in read_keys)
    assert any(":data_new:" in str(key) for key in read_keys)


def test_meta_cache_retries_when_activity_snapshot_changes_during_cache_read():
    redis = Mock()
    stale = _encode_heatmap_cache(
        {"activity_count": 2, "tracks": []},
        generation=7,
    )
    fresh = _encode_heatmap_cache(
        {"activity_count": 1, "tracks": []},
        generation=7,
    )
    redis.get.side_effect = [b"7", stale, b"7", fresh]

    with (
        patch("app.user.service_social._get_redis_client", return_value=redis),
        patch(
            "app.user.service_social._heatmap_activity_fingerprint",
            side_effect=["old", "new", "new", "new"],
        ),
    ):
        result = get_user_heatmap(Mock(), 42, detail="meta")

    assert result["activity_count"] == 1
    assert result["cache_version"] == "g7-dnew"
    read_keys = [call.args[0] for call in redis.get.call_args_list]
    assert any(":data_old:" in str(key) for key in read_keys)
    assert any(":data_new:" in str(key) for key in read_keys)


def test_tile_releases_old_build_lease_before_aba_retry():
    redis = Mock()
    redis.get.side_effect = [b"7", None, b"7", None, b"7", b"final"]
    first_lease = Mock()
    second_lease = Mock()
    claim_count = 0

    def claim(*_args, **_kwargs):
        nonlocal claim_count
        claim_count += 1
        if claim_count == 1:
            return first_lease, None
        assert first_lease.release.call_count == 1
        return second_lease, None

    with (
        patch("app.user.service_heatmap_tiles._get_redis_client", return_value=redis),
        patch(
            "app.user.service_heatmap_tiles._heatmap_activity_fingerprint",
            side_effect=["A", "B", "B", "A", "A", "A"],
        ),
        patch(
            "app.user.service_heatmap_tiles._claim_derived_cache_build",
            side_effect=claim,
        ),
        patch("app.user.service_heatmap_tiles._get_overview_segments_cached", return_value={}),
        patch(
            "app.user.service_heatmap_tiles._render_tile_png",
            side_effect=[b"first", b"second"],
        ),
    ):
        result = get_user_heatmap_tile(Mock(), 42, 12, 3328, 1582)

    assert result == b"final"
    assert first_lease.release.call_count == 1
    assert second_lease.release.call_count == 1


def test_tile_snapshot_retry_exhaustion_raises_typed_retryable_error():
    redis = Mock()
    redis.get.side_effect = [b"7", b"A", b"7", b"B", b"7", b"A"]

    with (
        patch("app.user.service_heatmap_tiles._get_redis_client", return_value=redis),
        patch(
            "app.user.service_heatmap_tiles._heatmap_activity_fingerprint",
            side_effect=["A", "B", "B", "A", "A", "B"],
        ),
        pytest.raises(HeatmapSnapshotChanged),
    ):
        get_user_heatmap_tile(Mock(), 42, 12, 3328, 1582)


def test_overview_source_redis_cache_avoids_repeated_postgis_scan_across_process_ttl():
    redis = Mock()
    redis.get.return_value = None
    source = {1: [[(112.5, 37.8), (112.6, 37.9)]]}
    _OVERVIEW_SOURCE_CACHE.clear()
    with (
        patch("app.user.service_heatmap_tiles._load_overview_segments", return_value=source) as loader,
        patch(
            "app.user.service_heatmap_tiles._segments_to_gcj02",
            side_effect=AssertionError("Redis overview source must stay WGS-84"),
        ),
    ):
        first = _get_overview_segments_cached(
                Mock(), 42, None, True, 7, None, redis, "data-v1"
        )
        encoded = redis.setex.call_args.args[2]
        _OVERVIEW_SOURCE_CACHE.clear()
        redis.get.return_value = encoded
        second = _get_overview_segments_cached(
                Mock(), 42, None, True, 7, None, redis, "data-v1"
        )

    assert first == second == source
    assert loader.call_count == 1
    assert redis.setex.call_args.args[1] == 7 * 86400
    assert redis.setex.call_args.args[0].startswith(
        "heatmap:raster:v2:source:user_42:g7:data_data-v1:year_all:audience_owner"
    )
    _OVERVIEW_SOURCE_CACHE.clear()


def test_overview_source_waiter_reuses_cross_process_builder_result():
    source = [[7, [[[112.5, 37.8], [112.6, 37.9]]]]]
    encoded = zlib.compress(json.dumps(source, separators=(",", ":")).encode())
    redis = Mock()
    redis.get.side_effect = [None, None, encoded]
    redis.set.return_value = False
    _OVERVIEW_SOURCE_CACHE.clear()

    with (
        patch(
            "app.user.service_heatmap_tiles._load_overview_segments",
            side_effect=AssertionError("waiter must not scan PostgreSQL"),
        ),
        patch("app.user.service_heatmap_tiles.sleep"),
    ):
        result = _get_overview_segments_cached(
            Mock(), 42, None, True, 7, None, redis, "data-v1"
        )

    assert result == {7: [[(112.5, 37.8), (112.6, 37.9)]]}
    assert redis.set.call_count >= 2
    _OVERVIEW_SOURCE_CACHE.clear()


def test_overview_build_for_one_user_does_not_block_another_user():
    first_started = Event()
    release_first = Event()
    redis = Mock()
    redis.get.return_value = None
    redis.set.return_value = True
    _OVERVIEW_SOURCE_CACHE.clear()

    def load(_db, user_id, _year, _include_private):
        if user_id == 101:
            first_started.set()
            assert release_first.wait(2)
        return {user_id: [[(112.5, 37.8), (112.6, 37.9)]]}

    with (
        patch("app.user.service_heatmap_tiles._load_overview_segments", side_effect=load),
        ThreadPoolExecutor(max_workers=2) as executor,
    ):
        first = executor.submit(
            _get_overview_segments_cached,
            Mock(), 101, None, True, 7, None, redis, "data-v1",
        )
        assert first_started.wait(1)
        second = executor.submit(
            _get_overview_segments_cached,
            Mock(), 202, None, True, 7, None, redis, "data-v1",
        )
        try:
            assert second.result(timeout=0.5) == {
                202: [[(112.5, 37.8), (112.6, 37.9)]]
            }
        finally:
            release_first.set()
        assert first.result(timeout=1) == {
            101: [[(112.5, 37.8), (112.6, 37.9)]]
        }
    _OVERVIEW_SOURCE_CACHE.clear()


def test_overview_pg_failure_releases_renewing_redis_lease():
    redis = Mock()
    redis.get.return_value = None
    redis.set.return_value = True
    _OVERVIEW_SOURCE_CACHE.clear()

    with (
        patch(
            "app.user.service_heatmap_tiles._load_overview_segments",
            side_effect=RuntimeError("postgres failed"),
        ),
        pytest.raises(RuntimeError, match="postgres failed"),
    ):
        _get_overview_segments_cached(
                Mock(), 303, None, True, 7, None, redis, "data-v1"
        )

    assert redis.eval.call_count == 1
    assert "redis.call('del'" in redis.eval.call_args.args[0]
    _OVERVIEW_SOURCE_CACHE.clear()


def test_overview_map_conversion_is_reused_across_neighbor_tiles():
    source = {7: [[(112.5, 37.8), (112.6, 37.9)]]}
    converted = {7: [[(112.506, 37.801), (112.606, 37.901)]]}
    _OVERVIEW_MAP_CACHE.clear()

    with patch(
        "app.user.service_heatmap_tiles._segments_to_gcj02",
        return_value=converted,
    ) as converter:
        first = _get_overview_map_segments_cached(
                source, 42, None, True, 7, None, "data-v1"
        )
        second = _get_overview_map_segments_cached(
                source, 42, None, True, 7, None, "data-v1"
        )

    assert first == second == converted
    assert converter.call_count == 1
    _OVERVIEW_MAP_CACHE.clear()


@pytest.mark.parametrize(
    ("zoom", "x", "y", "color"),
    [(2, 0, 0, "orange"), (12, -1, 0, "orange"), (12, 0, 0, "green")],
)
def test_tile_rejects_invalid_coordinates_and_color(zoom, x, y, color):
    with pytest.raises(InvalidHeatmapTile):
        get_user_heatmap_tile(Mock(), 1, zoom, x, y, color=color)


def test_postgis_tile_query_renders_raw_trackpoints(tile_pg_session_factory, tile_real_redis):
    """真实 PostGIS 验证空间索引，并保证私密原始 GPS 只对本人可见。"""
    db = tile_pg_session_factory()
    marker = uuid.uuid4().hex
    user = User(openid=f"heatmap_tile_{marker}", nickname="heatmap tile test")
    db.add(user)
    db.flush()
    gcj = np.array(
        [
            [112.548, 37.848],
            [112.55, 37.85],
            [112.552, 37.852],
            [112.57, 37.86],
            [112.571, 37.861],
        ],
        dtype=np.float64,
    )
    wgs = xyconvert.gcj2wgs(gcj)
    activity = Activity(
        user_id=user.id,
        title=f"heatmap tile {marker}",
        status="completed",
        activity_type="cycling",
        started_at=datetime(2025, 5, 1, tzinfo=timezone.utc),
        simplified_track=[
            {"lon": float(point[0]), "lat": float(point[1])} for point in wgs
        ],
    )
    db.add(activity)
    db.flush()
    db.add(ActivityPrivacy(activity_id=activity.id, visibility="private"))
    for seq, point in enumerate(wgs):
        db.add(Trackpoint(
            activity_id=activity.id,
            seq=seq,
            longitude=float(point[0]),
            latitude=float(point[1]),
            geom=f"SRID=4326;POINT({float(point[0])} {float(point[1])})",
        ))
    db.commit()
    zoom = 13
    x, y = _tile_for(112.55, 37.85, zoom)
    try:
        with patch("app.user.service_heatmap_tiles._get_redis_client", return_value=tile_real_redis):
            public_png = get_user_heatmap_tile(
                db,
                user.id,
                zoom,
                x,
                y,
                year=2025,
                color="red",
                include_private=False,
            )
            owner_png = get_user_heatmap_tile(
                db,
                user.id,
                zoom,
                x,
                y,
                year=2025,
                color="red",
                include_private=True,
            )
        public_alpha = np.asarray(Image.open(BytesIO(public_png)).convert("RGBA"))[:, :, 3]
        owner_alpha = np.asarray(Image.open(BytesIO(owner_png)).convert("RGBA"))[:, :, 3]
        assert public_alpha.max() == 0
        assert owner_alpha.max() > 0

        owner_segments = _load_overview_segments(db, user.id, 2025, True)
        public_segments = _load_overview_segments(db, user.id, 2025, False)
        assert [len(segment) for segment in owner_segments[activity.id]] == [2, 2]
        assert public_segments == {}

        overview_zoom = 9
        overview_x, overview_y = _tile_for(112.56, 37.855, overview_zoom)
        overview_png = _render_tile_png(
            owner_segments,
            overview_zoom,
            overview_x,
            overview_y,
            "red",
        )
        overview_alpha = np.asarray(
            Image.open(BytesIO(overview_png)).convert("RGBA")
        )[:, :, 3]
        jump_midpoint = (gcj[2] + gcj[3]) / 2
        midpoint_global = _global_pixel(
            float(jump_midpoint[0]), float(jump_midpoint[1]), overview_zoom
        )
        midpoint_x = int(round(midpoint_global[0] - overview_x * 512))
        midpoint_y = int(round(midpoint_global[1] - overview_y * 512))
        assert overview_alpha[
            midpoint_y - 2:midpoint_y + 3,
            midpoint_x - 2:midpoint_x + 3,
        ].max() == 0

        with patch("app.user.service_social._get_redis_client", return_value=tile_real_redis):
            public_overview = get_user_heatmap(
                db, user.id, None, 2025, "full", include_private=False
            )
            owner_overview = get_user_heatmap(
                db, user.id, None, 2025, "full", include_private=True
            )
        assert public_overview["activity_count"] == 0
        assert owner_overview["activity_count"] == 1
    finally:
        for key in tile_real_redis.scan_iter(match=f"heatmap:*user_{user.id}:*"):
            tile_real_redis.delete(key)
        db.query(Trackpoint).filter(Trackpoint.activity_id == activity.id).delete()
        db.query(Activity).filter(Activity.id == activity.id).delete()
        db.query(User).filter(User.id == user.id).delete()
        db.commit()
        db.close()
