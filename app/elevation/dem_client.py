"""Copernicus GLO-30 海拔查询客户端。

路线规划统一使用 GLO-30 中心线高度。瓦片来自 Copernicus 在 AWS Open Data
发布的 1° COG GeoTIFF，首次命中时下载到本地持久化缓存，之后离线复用。

本模块只回答“给定坐标的 GLO-30 高度”；20m 重采样、平滑和有效爬升累计在
``app.elevation.route_elevation`` 中完成。ALOS、FIT 与获授权的 Strava 赛段数据
保留为离线校准/拟合证据，不在请求时与 GLO 做固定平均。
"""

from __future__ import annotations

from collections import defaultdict
from contextvars import ContextVar
from functools import lru_cache
import fcntl
import logging
import math
import os
from pathlib import Path
import time
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
# 总下载时限不是 httpx 的单次 read timeout。只要上游持续零星返回字节，单次
# read timeout 会不断重新计时；必须另设墙钟时限，避免一个冷瓦片占住线程数小时。
GLO30_DOWNLOAD_TIMEOUT_SECONDS = 120.0
GLO30_DOWNLOAD_READ_TIMEOUT_SECONDS = 15.0
GLO30_LOCK_WAIT_TIMEOUT_SECONDS = 5.0
GLO30_QUERY_TIMEOUT_SECONDS = 120.0

_query_deadline: ContextVar[float | None] = ContextVar("glo30_query_deadline", default=None)


class DEMServiceError(Exception):
    """GLO-30 瓦片缺失、下载失败或文件损坏。"""


class _RestartPartialDownload(Exception):
    """旧断点与远端对象失配，需要在同一把锁内清零重试一次。"""


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
    deadline = time.monotonic() + GLO30_QUERY_TIMEOUT_SECONDS
    deadline_token = _query_deadline.set(deadline)
    try:
        for (south, west), items in grouped.items():
            if time.monotonic() >= deadline:
                raise DEMServiceError(
                    f"GLO-30 路线海拔查询超过 {GLO30_QUERY_TIMEOUT_SECONDS:.0f} 秒总时限"
                )
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
                except Exception as exc:
                    logger.warning("GLO-30 单点查询失败 lat=%s lon=%s: %s", lat, lon, exc)
    finally:
        _query_deadline.reset(deadline_token)
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
        _acquire_tile_lock(lock_file, tile_id)
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


def _acquire_tile_lock(lock_file, tile_id: str) -> None:
    """同瓦片只允许一个下载者；后来者快速失败，不能占满 API 线程。"""
    deadline = time.monotonic() + GLO30_LOCK_WAIT_TIMEOUT_SECONDS
    while True:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise DEMServiceError(f"GLO-30 瓦片正在下载 {tile_id}，请稍后重试")
            time.sleep(min(0.05, remaining))


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


def _download_tile(url: str, destination: Path, *, _allow_partial_restart: bool = True) -> None:
    temporary = destination.with_suffix(".part")
    if not temporary.exists():
        # 兼容部署前旧代码留下的 .part-<pid>；选最大的一份继续下载，避免冷瓦片
        # 已经走了几十分钟却在重启后从零开始。
        legacy_parts = list(destination.parent.glob(f"{destination.stem}.part-*"))
        if legacy_parts:
            max(legacy_parts, key=lambda path: path.stat().st_size).replace(temporary)

    offset = temporary.stat().st_size if temporary.exists() else 0
    request_headers = {"Range": f"bytes={offset}-"} if offset else {}
    now = time.monotonic()
    deadline = now + GLO30_DOWNLOAD_TIMEOUT_SECONDS
    query_deadline = _query_deadline.get()
    if query_deadline is not None:
        deadline = min(deadline, query_deadline)
    if deadline <= now:
        raise DEMServiceError(
            f"GLO-30 路线海拔查询超过 {GLO30_QUERY_TIMEOUT_SECONDS:.0f} 秒总时限"
        )
    try:
        with httpx.stream(
            "GET",
            url,
            headers=request_headers,
            follow_redirects=True,
            timeout=httpx.Timeout(
                connect=10.0,
                read=GLO30_DOWNLOAD_READ_TIMEOUT_SECONDS,
                write=GLO30_DOWNLOAD_READ_TIMEOUT_SECONDS,
                pool=10.0,
            ),
        ) as response:
            status_code = getattr(response, "status_code", 200)
            response_headers = getattr(response, "headers", {})
            expected_size = None
            write_mode = "wb"
            if offset and status_code == 206:
                content_range = response_headers.get("Content-Range", "")
                try:
                    byte_range, total_text = content_range.removeprefix("bytes ").split("/", 1)
                    range_start = int(byte_range.split("-", 1)[0])
                    expected_size = int(total_text)
                except (AttributeError, TypeError, ValueError):
                    raise DEMServiceError(f"GLO-30 断点续传响应异常：{content_range or 'missing'}")
                if range_start != offset:
                    raise DEMServiceError(
                        f"GLO-30 断点续传位置不一致：期望 {offset}，收到 {range_start}"
                    )
                write_mode = "ab"
            elif offset and status_code == 416:
                content_range = response_headers.get("Content-Range", "")
                try:
                    expected_size = int(content_range.rsplit("/", 1)[1])
                except (IndexError, TypeError, ValueError):
                    raise DEMServiceError("GLO-30 断点续传范围无效")
                if offset == expected_size:
                    temporary.replace(destination)
                    return
                raise _RestartPartialDownload(
                    f"GLO-30 临时文件大小异常：本地 {offset}，远端 {expected_size}"
                )
            else:
                # 上游若忽略 Range 返回 200，必须覆盖临时文件，不能把完整文件追加两次。
                response.raise_for_status()
                content_length = response_headers.get("Content-Length")
                if content_length is not None:
                    expected_size = int(content_length)

            response.raise_for_status()
            with temporary.open(write_mode) as output:
                for chunk in response.iter_bytes():
                    if time.monotonic() >= deadline:
                        raise DEMServiceError(
                            f"GLO-30 瓦片下载超过 {GLO30_DOWNLOAD_TIMEOUT_SECONDS:.0f} 秒总时限"
                        )
                    output.write(chunk)
        downloaded_size = temporary.stat().st_size
        if downloaded_size == 0:
            raise DEMServiceError(f"GLO-30 下载得到空文件：{url}")
        if expected_size is not None and downloaded_size != expected_size:
            raise DEMServiceError(
                f"GLO-30 下载未完成：已缓存 {downloaded_size}/{expected_size} 字节，可稍后续传"
            )
        temporary.replace(destination)
    except _RestartPartialDownload as exc:
        # 416 且本地大小不等于远端对象，说明旧 partial 已失配。只允许清零重试一次，
        # 否则同一坏 offset 会永久毒化共享缓存，让每次请求都重复 503。
        temporary.unlink(missing_ok=True)
        if _allow_partial_restart:
            _download_tile(url, destination, _allow_partial_restart=False)
            return
        raise DEMServiceError(str(exc)) from exc
    except Exception as exc:
        # 非空临时文件保留用于下一次 Range 续传；空文件没有复用价值。
        if temporary.exists() and temporary.stat().st_size == 0:
            temporary.unlink(missing_ok=True)
        if isinstance(exc, DEMServiceError):
            raise
        cached_size = temporary.stat().st_size if temporary.exists() else 0
        progress = f"（已缓存 {cached_size} 字节，可稍后续传）" if cached_size else ""
        raise DEMServiceError(f"GLO-30 瓦片下载失败 {url}：{exc}{progress}") from exc


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
