"""
DEM 海拔查询客户端——像查地形地图一样，把经纬度换成地面高度。

操作注意事项：本文件只负责“查高度”，不负责决定写进哪张表。赛段、路书、后续路线
工具都应该从这里取海拔，避免每个功能自己偷偷接一条不同的数据源。

输入输出：输入 [(lat, lon), ...]，返回同样长度的海拔数组；查不到的单点返回 None，
严重服务故障才抛 DEMServiceError。
"""

from __future__ import annotations

import logging
from typing import Iterable

import srtm


logger = logging.getLogger(__name__)

# CGIAR-CSI SRTM 90m 数据（srtm3=True 表示 3 弧秒 = 约 90m / srtm1=False 跳过需账号的 30m）
_dem_data = None


def _get_dem():
    """懒初始化 SRTM 数据访问器；像第一次打开地图要加载瓦片，后面就直接用缓存。"""
    global _dem_data
    if _dem_data is None:
        _dem_data = srtm.get_data(srtm1=False, srtm3=True)
    return _dem_data


class DEMServiceError(Exception):
    """DEM 查询致命错误：例如库初始化失败、首次下载地形瓦片失败。"""


def query_elevations(
    points: Iterable[tuple[float, float]],
    dem_url: str | None = None,
) -> list[float | None]:
    """
    批量查询经纬度对应的 DEM 海拔。

    points 的顺序是纬度在前、经度在后：[(lat, lon), ...]。dem_url 是历史兼容参数，
    SRTM 本地缓存模式不使用它。
    """
    points_list = list(points)
    if not points_list:
        return []

    try:
        dem = _get_dem()
    except Exception as exc:
        raise DEMServiceError(f"SRTM 数据访问器初始化失败：{exc}") from exc

    results: list[float | None] = []
    for lat, lon in points_list:
        try:
            ele = dem.get_elevation(lat, lon)
            results.append(float(ele) if ele is not None else None)
        except Exception as exc:
            logger.warning("DEM 单点查询失败 lat=%s lon=%s: %s", lat, lon, exc)
            results.append(None)
    return results
