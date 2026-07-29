from io import BytesIO
import math
from datetime import datetime, timezone
import os
import uuid
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
    _OVERVIEW_SOURCE_CACHE,
    _get_overview_segments_cached,
    _global_pixel,
    _limit_vector_segments,
    _map_coords_to_wgs84,
    _load_overview_segments,
    _render_tile_png,
    _raw_points_must_split,
    _sample_overview_segment,
    _tile_bounds_gcj02,
    _tile_query_bounds_wgs84,
    _trim_vector_cache,
    _wgs84_to_map_coords,
    get_user_heatmap_tile,
    get_user_heatmap_viewport,
)
from app.activity.models import Activity, ActivityPrivacy, Trackpoint
from app.user.models import User
from app.user.service_social import get_user_heatmap


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
    points = [(112.0 + index * 0.00001, 37.8) for index in range(1000)]
    points[503] = (points[503][0], 37.82)

    sampled = _sample_overview_segment(points)

    assert len(sampled) == 320
    assert points[503] in sampled


def test_vector_lod_keeps_sharp_bend_and_respects_total_budget():
    points = [(112.0 + index * 0.00001, 37.8) for index in range(8000)]
    points[4003] = (points[4003][0], 37.82)

    prepared = _limit_vector_segments({7: [points]}, zoom=10, latitude=37.8)

    assert sum(len(segment) for _, segment in prepared) <= 6000
    assert points[4003] in prepared[0][1]


def test_vector_viewport_cache_reuses_compressed_result_without_second_db_scan():
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
            "app.user.service_heatmap_tiles._load_raw_segments_for_bounds",
            return_value=source,
        ) as loader,
    ):
        first = get_user_heatmap_viewport(db, 42, viewport)
        encoded = redis.setex.call_args.args[2]
        redis.get.side_effect = [b"9", encoded]
        second = get_user_heatmap_viewport(db, 42, viewport)

    assert first == second
    assert first["activity_count"] == 1
    assert first["available_years"] == [2025]
    assert first["tracks"] == [[[112.5, 37.8], [112.51, 37.83], [112.52, 37.82]]]
    assert loader.call_count == 1
    assert redis.setex.call_args.args[0].startswith(
        "heatmap:vector:v1:user_42:g9:year_all:audience_owner:"
    )


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
        get_user_heatmap_viewport(Mock(), 42, viewport)


def test_vector_cache_is_capped_per_user_after_continuous_pan():
    redis = Mock()
    redis.scan_iter.return_value = [
        f"heatmap:vector:v1:user_42:view_{index}".encode()
        for index in range(18)
    ]
    current = "heatmap:vector:v1:user_42:view_17"

    _trim_vector_cache(redis, 42, current)

    assert redis.delete.call_count == 1
    assert len(redis.delete.call_args.args) == 2
    assert current.encode() not in redis.delete.call_args.args


def test_tile_cache_uses_heatmap_generation_and_avoids_second_db_render():
    redis = Mock()
    redis.get.side_effect = [b"7", None, b"7", b"png"]
    with (
        patch("app.user.service_heatmap_tiles._get_redis_client", return_value=redis),
        patch("app.user.service_heatmap_tiles._load_raw_segments", return_value={}) as loader,
        patch("app.user.service_heatmap_tiles._render_tile_png", return_value=b"png") as renderer,
    ):
        first = get_user_heatmap_tile(Mock(), 42, 12, 3328, 1582, color="orange")
        second = get_user_heatmap_tile(Mock(), 42, 12, 3328, 1582, color="orange")

    assert first == second == b"png"
    assert loader.call_count == 1
    assert renderer.call_count == 1
    assert redis.setex.call_args.args[0].startswith(
        "heatmap:raster:v1:user_42:g7:year_all:audience_owner:color_orange:z12:"
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
        patch("app.user.service_heatmap_tiles._load_raw_segments", return_value={}),
        patch("app.user.service_heatmap_tiles._render_tile_png", return_value=b"png") as renderer,
    ):
        get_user_heatmap_tile(
            Mock(), 42, 12, 3328, 1582, include_private=False
        )
        get_user_heatmap_tile(
            Mock(), 42, 12, 3328, 1582, include_private=False
        )

    assert renderer.call_count == 2
    keys = [call.args[0] for call in redis.setex.call_args_list]
    assert any("privacy_1-1-before" in key for key in keys)
    assert any("privacy_1-0-after" in key for key in keys)


def test_overview_source_redis_cache_avoids_repeated_postgis_scan_across_process_ttl():
    redis = Mock()
    redis.get.return_value = None
    source = {1: [[(112.5, 37.8), (112.6, 37.9)]]}
    _OVERVIEW_SOURCE_CACHE.clear()
    with (
        patch("app.user.service_heatmap_tiles._load_overview_segments", return_value=source) as loader,
        patch("app.user.service_heatmap_tiles._segments_to_gcj02", side_effect=lambda value: value),
    ):
        first = _get_overview_segments_cached(
            Mock(), 42, None, True, 7, None, redis
        )
        encoded = redis.setex.call_args.args[2]
        _OVERVIEW_SOURCE_CACHE.clear()
        redis.get.return_value = encoded
        second = _get_overview_segments_cached(
            Mock(), 42, None, True, 7, None, redis
        )

    assert first == second == source
    assert loader.call_count == 1
    assert redis.setex.call_args.args[0].startswith(
        "heatmap:raster:v1:source:user_42:g7:year_all:audience_owner"
    )
    _OVERVIEW_SOURCE_CACHE.clear()


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
