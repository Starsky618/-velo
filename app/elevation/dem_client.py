"""Copernicus GLO-30 海拔查询客户端。

路线规划统一使用 GLO-30 中心线高度。瓦片来自 Copernicus 在 AWS Open Data
发布的 1° COG GeoTIFF，首次命中时下载到本地持久化缓存，之后离线复用。

本模块只回答“给定坐标的 GLO-30 高度”；20m 重采样、平滑和有效爬升累计在
``app.elevation.route_elevation`` 中完成。ALOS、FIT 与获授权的 Strava 赛段数据
保留为离线校准/拟合证据，不在请求时与 GLO 做固定平均。
"""

from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
import fcntl
import logging
import math
import os
from pathlib import Path
from typing import Iterable

import httpx
import numpy as np
from PIL import Image


logger = logging.getLogger(__name__)

GLO30_SOURCE_NAME = "Copernicus DEM GLO-30 Public"
GLO30_LICENSE_ID = "Copernicus DEM Licence"
# 4m 是数据集官方给出的 90% absolute vertical linear error，不是对每个道路点
# 作出的 ±4m 产品承诺；道路、桥梁、隧道等结构仍由 VELO 的回归门单独评估。
GLO30_VERTICAL_ACCURACY_M = 4.0
GLO30_HORIZONTAL_RESOLUTION_M = 30.0
GLO30_DATASET_ID = "COP-DEM_GLO-30-DGED"
GLO30_VERTICAL_DATUM = "EGM2008 (EPSG:3855)"
GLO30_GRID_REGISTRATION = "RasterPixelIsPoint"
GLO30_BASE_URL = "https://copernicus-dem-30m.s3.amazonaws.com"
GLO30_DEFAULT_CACHE_DIR = "/var/cache/velo/glo30"
GLO30_DOWNLOAD_TIMEOUT_SECONDS = 120.0


class DEMServiceError(Exception):
    """GLO-30 瓦片缺失、下载失败或文件损坏。"""


def query_elevations(
    points: Iterable[tuple[float, float]],
    dem_url: str | None = None,
) -> list[float | None]:
    """批量查询 ``[(lat, lon), ...]``，返回同顺序的 GLO-30 高度。"""
    points_list = list(points)
    if not points_list:
        return []

    results: list[float | None] = [None] * len(points_list)
    grouped: dict[tuple[int, int], list[tuple[int, float, float]]] = defaultdict(list)
    for index, (raw_lat, raw_lon) in enumerate(points_list):
        try:
            lat = float(raw_lat)
            lon = float(raw_lon)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(lat) or not math.isfinite(lon):
            continue
        if not (-90.0 < lat < 90.0 and -180.0 <= lon < 180.0):
            continue
        grouped[_tile_key(lat, lon)].append((index, lat, lon))

    base_url = (dem_url or os.environ.get("GLO30_BASE_URL") or GLO30_BASE_URL).rstrip("/")
    cache_dir = Path(os.environ.get("GLO30_CACHE_DIR", GLO30_DEFAULT_CACHE_DIR))
    for (south, west), items in grouped.items():
        try:
            tile = _load_tile(south, west, str(cache_dir), base_url)
        except Exception as exc:
            if isinstance(exc, DEMServiceError):
                raise
            raise DEMServiceError(
                f"GLO-30 瓦片加载失败 {_tile_id(south, west)}：{exc}"
            ) from exc
        for index, lat, lon in items:
            try:
                value = _sample_tile(tile, south=south, west=west, lat=lat, lon=lon)
                results[index] = value if math.isfinite(value) else None
            except Exception:
                logger.exception("GLO-30 单点查询失败 lat=%s lon=%s", lat, lon)
    return results


def _tile_id(south: int, west: int) -> str:
    northing = f"N{south:02d}_00" if south >= 0 else f"S{abs(south):02d}_00"
    easting = f"E{west:03d}_00" if west >= 0 else f"W{abs(west):03d}_00"
    return f"Copernicus_DSM_COG_10_{northing}_{easting}_DEM"


def _tile_key(lat: float, lon: float) -> tuple[int, int]:
    """返回 PixelIsPoint 瓦片键；整数纬线属于其南侧瓦片的第 0 行。"""
    return math.ceil(lat) - 1, math.floor(lon)


def _tile_url(base_url: str, south: int, west: int) -> str:
    tile_id = _tile_id(south, west)
    return f"{base_url}/{tile_id}/{tile_id}.tif"


@lru_cache(maxsize=1)
def _load_tile(south: int, west: int, cache_dir_value: str, base_url: str) -> np.ndarray:
    cache_dir = Path(cache_dir_value)
    cache_dir.mkdir(parents=True, exist_ok=True)
    tile_id = _tile_id(south, west)
    path = cache_dir / f"{tile_id}.tif"
    lock_path = cache_dir / f"{tile_id}.lock"

    with lock_path.open("a+b") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        if not path.exists():
            _download_tile(_tile_url(base_url, south, west), path)
        try:
            return _read_tile(path)
        except DEMServiceError as initial_error:
            # 已存在但无法解码/校验的缓存不能永久毒化该瓦片。在同一把
            # 跨进程锁内只删除并重下一次，避免多个 worker 同时修复或无限重试。
            logger.warning("GLO-30 缓存损坏，将重新下载一次 %s: %s", path.name, initial_error)
            path.unlink(missing_ok=True)
            try:
                _download_tile(_tile_url(base_url, south, west), path)
                return _read_tile(path)
            except Exception as recovery_error:
                # 不保留二次仍无效的文件，下次请求可从干净状态重试。
                path.unlink(missing_ok=True)
                raise DEMServiceError(
                    f"GLO-30 瓦片重新下载修复失败 {path.name}：{recovery_error}"
                ) from recovery_error


def _read_tile(path: Path) -> np.ndarray:
    """读取并验证一个已缓存的 GLO-30 TIFF。"""
    try:
        with Image.open(path) as image:
            values = np.asarray(image, dtype=np.float32).copy()
    except Exception as exc:
        raise DEMServiceError(f"GLO-30 瓦片损坏 {path.name}：{exc}") from exc
    if values.ndim != 2 or min(values.shape) < 2:
        raise DEMServiceError(f"GLO-30 瓦片尺寸异常 {path.name}: {values.shape}")
    return values


def _download_tile(url: str, destination: Path) -> None:
    temporary = destination.with_suffix(f".part-{os.getpid()}")
    try:
        with httpx.stream(
            "GET",
            url,
            follow_redirects=True,
            timeout=GLO30_DOWNLOAD_TIMEOUT_SECONDS,
        ) as response:
            response.raise_for_status()
            with temporary.open("wb") as output:
                for chunk in response.iter_bytes():
                    output.write(chunk)
        if temporary.stat().st_size == 0:
            raise DEMServiceError(f"GLO-30 下载得到空文件：{url}")
        temporary.replace(destination)
    except Exception as exc:
        temporary.unlink(missing_ok=True)
        if isinstance(exc, DEMServiceError):
            raise
        raise DEMServiceError(f"GLO-30 瓦片下载失败 {url}：{exc}") from exc


def _sample_tile(
    tile: np.ndarray,
    *,
    south: int,
    west: int,
    lat: float,
    lon: float,
) -> float:
    """按实验脚本和官方 DGED 的 RasterPixelIsPoint 语义做双线性采样。"""
    height, width = tile.shape
    row = (south + 1.0 - lat) * height
    col = (lon - west) * width
    row = min(max(row, 0.0), height - 1.000001)
    col = min(max(col, 0.0), width - 1.000001)
    row0 = int(math.floor(row))
    col0 = int(math.floor(col))
    row1 = min(row0 + 1, height - 1)
    col1 = min(col0 + 1, width - 1)
    row_weight = row - row0
    col_weight = col - col0
    return float(
        tile[row0, col0] * (1.0 - row_weight) * (1.0 - col_weight)
        + tile[row1, col0] * row_weight * (1.0 - col_weight)
        + tile[row0, col1] * (1.0 - row_weight) * col_weight
        + tile[row1, col1] * row_weight * col_weight
    )
