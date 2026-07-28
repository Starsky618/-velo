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
    _global_pixel,
    _map_coords_to_wgs84,
    _render_tile_png,
    _raw_points_must_split,
    _tile_bounds_gcj02,
    _wgs84_to_map_coords,
    get_user_heatmap_tile,
)
from app.activity.models import Activity, Trackpoint
from app.user.models import User


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
    assert alpha[max(0, bend_y - 2):bend_y + 3, max(0, bend_x - 2):bend_x + 3].max() > 0


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
        "heatmap:raster:v1:user_42:g7:year_all:color_orange:z12:"
    )


@pytest.mark.parametrize(
    ("zoom", "x", "y", "color"),
    [(2, 0, 0, "orange"), (12, -1, 0, "orange"), (12, 0, 0, "green")],
)
def test_tile_rejects_invalid_coordinates_and_color(zoom, x, y, color):
    with pytest.raises(InvalidHeatmapTile):
        get_user_heatmap_tile(Mock(), 1, zoom, x, y, color=color)


def test_postgis_tile_query_renders_raw_trackpoints(tile_pg_session_factory, tile_real_redis):
    """CI 的真实 PostGIS 临时库验证空间索引表达式和原始点查询合同。"""
    db = tile_pg_session_factory()
    marker = uuid.uuid4().hex
    user = User(openid=f"heatmap_tile_{marker}", nickname="heatmap tile test")
    db.add(user)
    db.flush()
    activity = Activity(
        user_id=user.id,
        title=f"heatmap tile {marker}",
        status="completed",
        activity_type="cycling",
        started_at=datetime(2025, 5, 1, tzinfo=timezone.utc),
        simplified_track=[],
    )
    db.add(activity)
    db.flush()
    gcj = np.array(
        [[112.548, 37.848], [112.55, 37.85], [112.552, 37.852]],
        dtype=np.float64,
    )
    wgs = xyconvert.gcj2wgs(gcj)
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
            png = get_user_heatmap_tile(
                db, user.id, zoom, x, y, year=2025, color="red"
            )
        alpha = np.asarray(Image.open(BytesIO(png)).convert("RGBA"))[:, :, 3]
        assert alpha.max() > 0
    finally:
        for key in tile_real_redis.scan_iter(match=f"heatmap:raster:v1:user_{user.id}:*"):
            tile_real_redis.delete(key)
        db.query(Trackpoint).filter(Trackpoint.activity_id == activity.id).delete()
        db.query(Activity).filter(Activity.id == activity.id).delete()
        db.query(User).filter(User.id == user.id).delete()
        db.commit()
        db.close()
