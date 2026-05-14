"""
DEM 海拔查询客户端 —— "把 GPS 海拔换成真实地形海拔"。

为什么需要这个：
GPS 海拔精度 ±10-15m（物理限制）。velo 上 11km 平路赛段"夜骑清徐"
GPS 测得坡度 26.1% 假数据 —— 实际真实坡度 0.018%。任何平滑算法
都洗不掉 GPS 系统偏差，必须**换数据源**。

DEM（Digital Elevation Model 数字高程模型）是测绘卫星扫描后做出来的
地表海拔数据库。SRTM 30m 是 NASA 公开的全球 DEM，中国平原区精度
~5m RMSE，对骑行赛段足够准。

类比：GPS 是"自己用气压计估摸海拔"，DEM 是"查地图精确海拔"。

数据源：
opentopodata.org 公共 API（免费 / SRTM 30m / 全球覆盖）。
长期 velo 用户量上来后会自托管 opentopodata 容器（避免 rate limit）。

调用方式：
    from app.segment.dem_client import query_elevations
    elevations = query_elevations([(37.685, 112.505), (37.638, 112.404)])
    # → [768.0, 766.0]  单位：米

操作注意事项：
- 公共 API 批量限制：每次最多 100 点（API 文档实证）
- 超过 100 点的查询自动分批发送
- 失败时 retry 一次；二次失败抛 DEMServiceError，调用方决定要不要 fallback
- 短期生产用公共 API；env DEM_SERVICE_URL 可指向自托管 opentopodata 容器
"""

from __future__ import annotations

import logging
import os
import time
from typing import Iterable

import httpx


logger = logging.getLogger(__name__)

# opentopodata 公共 API（免费 / SRTM 30m）。
# 生产可设 DEM_SERVICE_URL 指向自托管容器 http://dem:5000/v1/srtm30m
DEFAULT_DEM_URL = os.getenv(
    "DEM_SERVICE_URL",
    "https://api.opentopodata.org/v1/srtm30m",
)

# 公共 API 批量限制：每请求最多 100 点（文档实证）。
# 自托管限制更松，但保持同值方便迁移。
MAX_BATCH_SIZE = 100

# HTTP 超时：单次请求最长 30 秒。
# 公共 API 测得 100 点 latency ~1-2 秒，30 秒兜底足够。
HTTP_TIMEOUT_S = 30.0

# 失败重试间隔（秒）。公共 API 偶发 502/503 / 网络抖动 / 立即重试通常成功。
RETRY_DELAY_S = 1.0


class DEMServiceError(Exception):
    """DEM 查询失败（外部服务挂 / 网络断 / 响应格式异常）。

    调用方拿到这个异常时应该决定：
    - 创建 segment 时：raise 给 admin（让人知道服务不可用）
    - 回填脚本：log + 跳过这条 segment 保留原 GPS 海拔
    """


def query_elevations(
    points: Iterable[tuple[float, float]],
    dem_url: str | None = None,
) -> list[float | None]:
    """
    批量查 GPS 坐标对应的 DEM 海拔，返回与输入等长的海拔数组。

    类比："给我这一串路口的真实地面高度" —— 输入坐标点序列，
    输出每个点的 DEM 海拔（米）。

    超过 100 点自动分批；失败重试一次；二次失败抛 DEMServiceError。
    单个点查不到（在海里 / DEM 数据空洞）→ 该位置返 None，
    调用方需要决定怎么处理（fallback 到 GPS 还是跳过）。

    参数：
        points: [(lat, lon), (lat, lon), ...]  纬度在前经度在后
        dem_url: 可选，覆盖默认 DEM 服务地址；默认读 env DEM_SERVICE_URL

    返回：
        list[float | None] 与 points 等长；单位米；查不到该位置返 None

    异常：
        DEMServiceError: 整批查询失败（服务不可达 / 超时 / 响应格式异常）
    """
    url = dem_url or DEFAULT_DEM_URL
    points_list = list(points)
    if not points_list:
        return []

    results: list[float | None] = []
    # 分批发送：每批最多 MAX_BATCH_SIZE 点
    for batch_start in range(0, len(points_list), MAX_BATCH_SIZE):
        batch = points_list[batch_start : batch_start + MAX_BATCH_SIZE]
        batch_elevations = _query_one_batch(batch, url)
        results.extend(batch_elevations)

    return results


def _query_one_batch(
    batch: list[tuple[float, float]], url: str,
) -> list[float | None]:
    """单批（≤ 100 点）查询，失败重试一次。"""
    # opentopodata API 格式：locations=lat1,lon1|lat2,lon2|...
    locations_param = "|".join(f"{lat},{lon}" for lat, lon in batch)

    last_exc: Exception | None = None
    for attempt in (1, 2):
        try:
            # trust_env=False：禁用 httpx 自动读 ALL_PROXY/HTTPS_PROXY 环境变量。
            # 生产服务器（114.132.190.245）若挂了 SOCKS 代理（运维翻墙常见），
            # 默认 trust_env=True 会让 httpx 走 socks5://，没装 socksio 包 → ImportError。
            # DEM 调用是直连公共 API（无翻墙必要 / 直连大陆能通），显式绕过代理继承。
            response = httpx.get(
                url,
                params={"locations": locations_param},
                timeout=HTTP_TIMEOUT_S,
                trust_env=False,
            )
            response.raise_for_status()
            data = response.json()
            if data.get("status") != "OK":
                raise DEMServiceError(
                    f"DEM API 返回非 OK 状态：{data.get('status')} / {data.get('error', '')}"
                )
            # 按返回顺序提取 elevation；可能为 None（DEM 空洞 / 海上）
            return [item.get("elevation") for item in data.get("results", [])]
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            last_exc = exc
            logger.warning(
                "DEM 查询失败 attempt=%d / %d 点 / %s",
                attempt, len(batch), exc,
            )
            if attempt < 2:
                time.sleep(RETRY_DELAY_S)

    raise DEMServiceError(f"DEM 批量查询连续 2 次失败：{last_exc}") from last_exc
