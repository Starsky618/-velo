"""
腾讯地图路线规划客户端——把腾讯算出来的骑行路线翻译成 Velo 能存的点串。

干啥用：后端拿起点/终点调用腾讯 WebServiceAPI 的骑行路线规划，返回距离和路线点。
操作注意事项：SK 只在服务端参与签名，不能返回给前端；腾讯返回 GCJ-02，入库前由 service 转 WGS-84。
输入输出：输入 GCJ-02 起终点坐标 → 输出 {"distance", "duration", "points"}，points 仍是 GCJ-02。
"""

from __future__ import annotations

import hashlib
import math
from typing import Any

import httpx

from app.config import settings


_TENCENT_DIRECTION_PATH = "/ws/direction/v1/bicycling/"
_TENCENT_DIRECTION_URL = "https://apis.map.qq.com" + _TENCENT_DIRECTION_PATH


class TencentMapError(ValueError):
    """腾讯地图返回不可用结果时抛出，让 router 翻译成 422。"""


class TencentMapConfigError(RuntimeError):
    """服务端还没配置腾讯地图密钥时抛出，让 router 翻译成 503。"""


class TencentMapServiceUnavailableError(RuntimeError):
    """腾讯地图服务暂时不可用时抛出，让 router 翻译成 503。"""


def _ensure_finite_lat_lon(lat: float, lon: float) -> None:
    if not math.isfinite(lat) or not math.isfinite(lon):
        raise TencentMapError("腾讯路线坐标包含非有限数字")
    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        raise TencentMapError("腾讯路线坐标越界")


def _build_sig(path: str, params: dict[str, str], secret_key: str) -> str:
    """
    计算腾讯 WebServiceAPI 的 GET 签名。

    腾讯要求把参数按 key 升序拼成未 URL 编码的 query，再接 SK 做 md5。
    可以把它想成“账单验算”：双方拿同一张明细表按同一顺序相加，结果一致才放行。
    """
    query = "&".join(f"{key}={params[key]}" for key in sorted(params))
    return hashlib.md5(f"{path}?{query}{secret_key}".encode("utf-8")).hexdigest()


def _decode_polyline(polyline: list[int | float]) -> list[dict[str, float]]:
    """
    解压腾讯路线点串。

    腾讯返回的 polyline 前两个数字是第一个点的绝对纬经度，后续数字是相对上一个点的
    百万分之一度偏移量。像记账时第一行写余额，后面只写“+6 分 / -3 分”。
    """
    if len(polyline) < 4 or len(polyline) % 2 != 0:
        raise TencentMapError("腾讯路线点串格式异常")

    lat = float(polyline[0])
    lon = float(polyline[1])
    _ensure_finite_lat_lon(lat, lon)
    points = [{"lat": lat, "lon": lon}]

    for i in range(2, len(polyline), 2):
        lat += float(polyline[i]) / 1_000_000
        lon += float(polyline[i + 1]) / 1_000_000
        _ensure_finite_lat_lon(lat, lon)
        points.append({"lat": lat, "lon": lon})

    return points


def plan_tencent_bicycling_route(
    start: tuple[float, float],
    end: tuple[float, float],
    timeout_sec: float = 8.0,
) -> dict[str, Any]:
    """
    调腾讯骑行路线规划。

    start/end 均是 (lat, lon)，与腾讯 API 的“纬度在前，经度在后”一致。
    """
    if not settings.TENCENT_MAP_KEY or not settings.TENCENT_MAP_SK:
        raise TencentMapConfigError("TENCENT_MAP_KEY / TENCENT_MAP_SK 未配置")

    start_lat, start_lon = start
    end_lat, end_lon = end
    _ensure_finite_lat_lon(start_lat, start_lon)
    _ensure_finite_lat_lon(end_lat, end_lon)
    timeout_sec = float(timeout_sec)
    if not math.isfinite(timeout_sec) or timeout_sec <= 0:
        raise TencentMapError("腾讯地图 timeout 配置异常")

    params = {
        "from": f"{start_lat},{start_lon}",
        "to": f"{end_lat},{end_lon}",
        "key": settings.TENCENT_MAP_KEY,
        "output": "json",
    }
    params["sig"] = _build_sig(_TENCENT_DIRECTION_PATH, params, settings.TENCENT_MAP_SK)

    try:
        response = httpx.get(_TENCENT_DIRECTION_URL, params=params, timeout=timeout_sec)
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPError:
        # HTTPStatusError 的文本包含完整请求 URL，而 URL 里有 key 和 sig；不能透传给 API 响应或日志。
        raise TencentMapServiceUnavailableError("腾讯地图请求失败，请稍后重试") from None
    except ValueError as exc:
        raise TencentMapError("腾讯地图返回了无法解析的 JSON") from exc

    if data.get("status") != 0:
        message = data.get("message") or "腾讯地图路线规划失败"
        raise TencentMapError(str(message))

    routes = (((data.get("result") or {}).get("routes")) or [])
    if not routes:
        raise TencentMapError("腾讯地图没有返回可用路线")

    route = routes[0]
    points = _decode_polyline(route.get("polyline") or [])
    return {
        "distance": float(route.get("distance") or 0),
        "duration": route.get("duration"),
        "points": points,
    }
