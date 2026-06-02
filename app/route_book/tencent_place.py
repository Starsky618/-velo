"""
腾讯地点检索客户端——把“蒙山大佛”这种地名翻译成 Velo 能相信的坐标。

干啥用：路线百科冷启动前，先用腾讯地点服务查真实地点，避免 AI 只凭名字猜方位。
操作注意事项：SK 只参与服务端签名，不能打印、不能返回；腾讯返回 GCJ-02，本模块直接转成 WGS-84。
输入输出：输入地名和城市范围 → 输出第一个命中地点的 WGS-84 经纬度；查不到返回 None。
"""

from __future__ import annotations

import math
from typing import Any

import httpx

from app.config import settings
from app.route_book.tencent_direction import TencentMapConfigError, TencentMapError, _build_sig
from app.segment.coord_convert import gcj02_to_wgs84


_TENCENT_PLACE_PATH = "/ws/place/v1/search"
_TENCENT_PLACE_URL = "https://apis.map.qq.com" + _TENCENT_PLACE_PATH


def _ensure_place_lat_lon(lat: float, lon: float) -> None:
    if not math.isfinite(lat) or not math.isfinite(lon):
        raise TencentMapError("腾讯地点坐标包含非有限数字")
    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        raise TencentMapError("腾讯地点坐标越界")


def _first_place(data: dict[str, Any]) -> dict[str, Any] | None:
    places = data.get("data") or []
    if not places:
        return None
    if not isinstance(places, list):
        raise TencentMapError("腾讯地点检索结果格式异常")
    first = places[0]
    if not isinstance(first, dict):
        raise TencentMapError("腾讯地点检索结果格式异常")
    return first


def search_place(keyword: str, region: str = "太原") -> dict[str, Any] | None:
    """
    调腾讯地点检索，把城市里的地名查成 WGS-84 坐标。

    boundary=region(太原,0) 像给搜索框加“只在太原这本电话簿里找”的限制，
    避免“蒙山”跑到广西、山东等同名地点。
    """
    keyword = keyword.strip()
    region = region.strip()
    if not keyword:
        raise TencentMapError("地点关键词不能为空")
    if not region:
        raise TencentMapError("地点检索城市不能为空")
    if not settings.TENCENT_MAP_KEY or not settings.TENCENT_MAP_SK:
        raise TencentMapConfigError("TENCENT_MAP_KEY / TENCENT_MAP_SK 未配置")

    params = {
        "keyword": keyword,
        "boundary": f"region({region},0)",
        "key": settings.TENCENT_MAP_KEY,
        "output": "json",
    }
    params["sig"] = _build_sig(_TENCENT_PLACE_PATH, params, settings.TENCENT_MAP_SK)

    try:
        response = httpx.get(_TENCENT_PLACE_URL, params=params, timeout=8.0)
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response is not None else "unknown"
        raise TencentMapError(f"腾讯地点检索请求失败：HTTP {status_code}") from exc
    except httpx.HTTPError as exc:
        raise TencentMapError("腾讯地点检索请求失败") from exc
    except ValueError as exc:
        raise TencentMapError("腾讯地点检索返回了无法解析的 JSON") from exc

    if data.get("status") != 0:
        message = data.get("message") or "腾讯地点检索失败"
        raise TencentMapError(str(message))

    place = _first_place(data)
    if place is None:
        return None

    location = place.get("location") or {}
    try:
        gcj_lat = float(location["lat"])
        gcj_lon = float(location["lng"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TencentMapError("腾讯地点检索结果缺少可用坐标") from exc

    _ensure_place_lat_lon(gcj_lat, gcj_lon)
    lat, lon = gcj02_to_wgs84(gcj_lat, gcj_lon)
    _ensure_place_lat_lon(lat, lon)

    return {
        "keyword": keyword,
        "title": place.get("title") or keyword,
        "address": place.get("address"),
        "lat": lat,
        "lon": lon,
        "source": "tencent_place",
    }
