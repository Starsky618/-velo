"""
腾讯地点检索客户端——把“蒙山大佛”这种地名翻译成 Velo 能相信的坐标。

干啥用：路线百科冷启动前，先用腾讯地点服务查真实地点，避免 AI 只凭名字猜方位。
操作注意事项：SK 只参与服务端签名，不能打印、不能返回；腾讯返回 GCJ-02，本模块同时保留
供应商原生坐标和转换后的 WGS-84，避免后续路线请求丢失 POI 身份或反复转换坐标。
输入输出：输入地名和城市范围 → 输出第一个命中地点的身份、分类、行政区和坐标；查不到返回 None。
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

_TENCENT_SUGGEST_PATH = "/ws/place/v1/suggestion"
_TENCENT_SUGGEST_URL = "https://apis.map.qq.com" + _TENCENT_SUGGEST_PATH

# 实时联想一屏给几条：太多滚不动、太少像没搜到，8 条与地图类 App 惯例一致
_SUGGEST_LIMIT = 8


def _ensure_place_lat_lon(lat: float, lon: float) -> None:
    if not math.isfinite(lat) or not math.isfinite(lon):
        raise TencentMapError("腾讯地点坐标包含非有限数字")
    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        raise TencentMapError("腾讯地点坐标越界")


def _optional_text(value: Any) -> str | None:
    """把腾讯偶发的数字/字符串类型漂移收敛成稳定的字符串。"""
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    text = str(value).strip()
    return text or None


def _place_field(place: dict[str, Any], name: str) -> str | None:
    """行政区字段在 search/suggestion 中可能位于顶层或 ad_info。"""
    value = _optional_text(place.get(name))
    if value is not None:
        return value
    ad_info = place.get("ad_info")
    if isinstance(ad_info, dict):
        return _optional_text(ad_info.get(name))
    return None


def _place_coordinates(place: dict[str, Any]) -> tuple[float, float, float, float]:
    location = place.get("location")
    if not isinstance(location, dict):
        raise TencentMapError("腾讯地点检索结果缺少可用坐标")
    try:
        gcj_lat = float(location["lat"])
        gcj_lon = float(location["lng"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TencentMapError("腾讯地点检索结果缺少可用坐标") from exc

    _ensure_place_lat_lon(gcj_lat, gcj_lon)
    lat, lon = gcj02_to_wgs84(gcj_lat, gcj_lon)
    _ensure_place_lat_lon(lat, lon)
    return gcj_lat, gcj_lon, lat, lon


def _normalize_place(
    place: dict[str, Any],
    *,
    keyword: str,
    source: str,
) -> dict[str, Any]:
    gcj_lat, gcj_lon, lat, lon = _place_coordinates(place)
    return {
        "keyword": keyword,
        "title": _optional_text(place.get("title")) or keyword,
        "address": _optional_text(place.get("address")),
        "lat": lat,
        "lon": lon,
        "source": source,
        "provider_poi_id": _optional_text(place.get("id")),
        "category": _optional_text(place.get("category")),
        "category_code": _optional_text(place.get("category_code")),
        "type": _optional_text(place.get("type")),
        "adcode": _place_field(place, "adcode"),
        "province": _place_field(place, "province"),
        "city": _place_field(place, "city"),
        "district": _place_field(place, "district"),
        "gcj_lat": gcj_lat,
        "gcj_lon": gcj_lon,
    }


def _normalize_sub_pois(place: dict[str, Any], *, keyword: str) -> list[dict[str, Any]]:
    raw_sub_pois = place.get("sub_pois") or []
    if not isinstance(raw_sub_pois, list):
        return []

    normalized: list[dict[str, Any]] = []
    for sub_poi in raw_sub_pois:
        if not isinstance(sub_poi, dict):
            continue
        try:
            normalized.append(
                _normalize_place(
                    sub_poi,
                    keyword=keyword,
                    source="tencent_sub_place",
                )
            )
        except TencentMapError:
            # 子点坏坐标不应让主 POI 整个失败。
            continue
    return normalized


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
    调腾讯地点检索，把城市里的地名查成可回传腾讯的 POI 与双坐标。

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
        "added_fields": "category_code",
        "get_subpois": "1",
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
        raise TencentMapError(f"腾讯地点检索请求失败：HTTP {status_code}") from None
    except httpx.HTTPError:
        raise TencentMapError("腾讯地点检索请求失败") from None
    except ValueError as exc:
        raise TencentMapError("腾讯地点检索返回了无法解析的 JSON") from exc

    if not isinstance(data, dict):
        raise TencentMapError("腾讯地点检索返回格式异常")
    if data.get("status") != 0:
        message = data.get("message") or "腾讯地点检索失败"
        raise TencentMapError(str(message))

    place = _first_place(data)
    if place is None:
        return None

    result = _normalize_place(place, keyword=keyword, source="tencent_place")
    result["sub_pois"] = _normalize_sub_pois(place, keyword=keyword)
    return result


def suggest_places(keyword: str, region: str = "太原") -> list[dict[str, Any]]:
    """
    调腾讯地点联想（suggestion），给"边输边搜"的下拉列表喂候选。

    和 search_place 的分工：search_place 是"我确定要查这个名字，给我最准的一个"
    （route skill 线裁判用）；suggest_places 是"我才打了两个字，把最像的几个都给我挑"
    （约骑集合点搜索框用）。region_fix=1 把结果锁死在城市内，防同名地点跑省外。
    同时返回 WGS-84 和腾讯原生 GCJ-02；现有调用方仍可继续只读 lat/lon。
    单条坐标坏了只丢那条不炸整列——联想列表少一条无感，500 一次全废。
    """
    keyword = keyword.strip()
    region = region.strip()
    if not keyword:
        raise TencentMapError("地点关键词不能为空")
    if not region:
        raise TencentMapError("地点联想城市不能为空")
    if not settings.TENCENT_MAP_KEY or not settings.TENCENT_MAP_SK:
        raise TencentMapConfigError("TENCENT_MAP_KEY / TENCENT_MAP_SK 未配置")

    params = {
        "keyword": keyword,
        "region": region,
        "region_fix": "1",
        # 腾讯文档：page_size 与 page_index 必须成对出现，单传 page_size 契约不完整
        "page_index": "1",
        "page_size": str(_SUGGEST_LIMIT),
        "added_fields": "category_code",
        "key": settings.TENCENT_MAP_KEY,
        "output": "json",
    }
    params["sig"] = _build_sig(_TENCENT_SUGGEST_PATH, params, settings.TENCENT_MAP_SK)

    try:
        response = httpx.get(_TENCENT_SUGGEST_URL, params=params, timeout=8.0)
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response is not None else "unknown"
        raise TencentMapError(f"腾讯地点联想请求失败：HTTP {status_code}") from None
    except httpx.HTTPError:
        raise TencentMapError("腾讯地点联想请求失败") from None
    except ValueError as exc:
        raise TencentMapError("腾讯地点联想返回了无法解析的 JSON") from exc

    if not isinstance(data, dict):
        raise TencentMapError("腾讯地点联想返回格式异常")
    if data.get("status") != 0:
        message = data.get("message") or "腾讯地点联想失败"
        raise TencentMapError(str(message))

    places = data.get("data") or []
    if not isinstance(places, list):
        raise TencentMapError("腾讯地点联想结果格式异常")

    suggestions: list[dict[str, Any]] = []
    for place in places[:_SUGGEST_LIMIT]:
        if not isinstance(place, dict):
            continue
        try:
            suggestions.append(
                _normalize_place(
                    place,
                    keyword=keyword,
                    source="tencent_suggestion",
                )
            )
        except TencentMapError:
            continue
    return suggestions
