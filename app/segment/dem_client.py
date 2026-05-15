"""
DEM 海拔查询客户端——"把 GPS 海拔换成真实地形海拔"。

为什么需要这个：
GPS 海拔精度 ±10-15m（物理限制）。velo 上 11km 平路赛段"夜骑清徐"
GPS 测得坡度 26.1% 假数据 —— 实际真实坡度 0.018%。任何平滑算法
都洗不掉 GPS 系统偏差，必须**换数据源**。

DEM（Digital Elevation Model 数字高程模型）是测绘卫星扫描后做出来的
地表海拔数据库。SRTM 是 NASA 公开的全球 DEM 数据集。

类比：GPS 是"自己用气压计估摸海拔"，DEM 是"查地图精确海拔"。

数据源（2026-05-15 切换 / Tim 拍合规自托管）：
本模块用 SRTM.py 库 + CGIAR-CSI 90m DEM 数据。第一次查某区域时
自动从 CGIAR-CSI 镜像下载该 tile（~10-50MB）到容器本地 .cache/srtm/，
后续查询命中本地缓存零网络开销。

为什么切换：
- 之前用 opentopodata.org 公共 REST API：数据在境外 + 服务挂了无法建赛段
- 现在 SRTM.py 库懒下载：数据从 CGIAR-CSI 一次拉到本地容器后**不再依赖外网**
- CGIAR-CSI 无需任何账号（NASA Earthdata 30m 才要账号）
- 精度从 30m 退到 90m：但赛段坡度计算（500m 滑窗）下两者精度差异 < 1%，
  且 90m 数据更平滑，反而能压住 30m 像素级噪声

调用方式：
    from app.segment.dem_client import query_elevations
    elevations = query_elevations([(37.685, 112.505), (37.638, 112.404)])
    # → [768, 766]  单位：米；个别点查不到返 None

操作注意事项：
- 缓存目录在 container 内 /root/.cache/srtm（默认）—— docker volume 持久化避免每次重启重下
- 首次查询某新位置耗时 1-10s（下载 tile 10-50MB），后续查询毫秒级
- 失败时返 None（保留位置 / 不破坏调用方索引），DEMServiceError 仅在严重错误抛
"""

from __future__ import annotations

import logging
from typing import Iterable

import srtm


logger = logging.getLogger(__name__)

# CGIAR-CSI SRTM 90m 数据（srtm3=True 表示 3 弧秒 = 约 90m / srtm1=False 跳过需账号的 30m）
# 模块级单例：第一次调用时初始化（含缓存目录扫描），后续复用避免重复 IO
_dem_data = None


def _get_dem():
    """懒初始化 SRTM 数据访问器（CGIAR-CSI 90m / 无需账号）。"""
    global _dem_data
    if _dem_data is None:
        _dem_data = srtm.get_data(srtm1=False, srtm3=True)
    return _dem_data


class DEMServiceError(Exception):
    """DEM 查询致命错误（库初始化失败 / 容器无网络初次下载失败）。

    调用方拿到这个异常时应该决定：
    - 创建 segment 时：raise 给 admin（让人知道服务不可用）
    - 回填脚本：log + 跳过这条 segment 保留原 GPS 海拔

    注意：单点查不到（如点在海上 / DEM 数据空洞）**不抛异常**，返 None。
    """


def query_elevations(
    points: Iterable[tuple[float, float]],
    dem_url: str | None = None,  # 兼容旧接口签名 / SRTM.py 模式下忽略
) -> list[float | None]:
    """
    批量查 GPS 坐标对应的 DEM 海拔，返回与输入等长的海拔数组。

    类比："给我这一串路口的真实地面高度" —— 输入坐标点序列，
    输出每个点的 DEM 海拔（米）。

    单个点查不到（在海里 / DEM 数据空洞）→ 该位置返 None，
    调用方需要决定怎么处理（fallback 到 GPS 还是跳过）。

    参数：
        points: [(lat, lon), (lat, lon), ...]  纬度在前经度在后
        dem_url: 历史接口签名兼容字段，库模式下忽略

    返回：
        list[float | None] 与 points 等长；单位米；查不到该位置返 None

    异常：
        DEMServiceError: 库初始化失败 / 严重错误才抛
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
            # 单点失败不破坏整批 / 记 warning + 该位置返 None
            logger.warning("DEM 单点查询失败 lat=%s lon=%s: %s", lat, lon, exc)
            results.append(None)

    return results
