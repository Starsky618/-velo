"""
腾讯地图路线规划客户端——把腾讯算出来的骑行路线翻译成 Velo 能存的点串。

干啥用：后端拿起点/终点调用腾讯 WebServiceAPI 的骑行路线规划，返回距离、路线点和
同一次响应里的导航步骤证据。
操作注意事项：SK 只在服务端参与签名，不能返回给前端；腾讯返回 GCJ-02，入库前由 service 转 WGS-84。
输入输出：输入 GCJ-02 起终点坐标 → 输出路线摘要、points 和 steps，points 仍是 GCJ-02。
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
    if not isinstance(polyline, list) or len(polyline) < 4 or len(polyline) % 2 != 0:
        raise TencentMapError("腾讯路线点串格式异常")

    lat = _finite_number(polyline[0], "腾讯路线点串坐标")
    lon = _finite_number(polyline[1], "腾讯路线点串坐标")
    _ensure_finite_lat_lon(lat, lon)
    points = [{"lat": lat, "lon": lon}]

    for i in range(2, len(polyline), 2):
        lat += _finite_number(polyline[i], "腾讯路线点串偏移量") / 1_000_000
        lon += _finite_number(polyline[i + 1], "腾讯路线点串偏移量") / 1_000_000
        _ensure_finite_lat_lon(lat, lon)
        points.append({"lat": lat, "lon": lon})

    return points


def _finite_number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TencentMapError(f"{field_name}不是有效数字")
    number = float(value)
    if not math.isfinite(number):
        raise TencentMapError(f"{field_name}不是有效数字")
    return number


def _non_negative_number(value: Any, field_name: str) -> float:
    number = _finite_number(value, field_name)
    if number < 0:
        raise TencentMapError(f"{field_name}不能为负数")
    return number


def _optional_string(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TencentMapError(f"{field_name}格式异常")
    return value


def _optional_provenance_string(value: Any) -> str | None:
    """诊断字段不属于正式算路契约；标量漂移不能拖垮一条有效路线。"""
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    text = str(value).strip()
    return text or None


def _normalize_optional_poi(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise TencentMapError(f"{field_name}必须是非空字符串")
    return value.strip()


def _normalize_steps(
    raw_steps: Any,
    *,
    raw_polyline_length: int,
) -> list[dict[str, Any]]:
    if raw_steps is None:
        return []
    if not isinstance(raw_steps, list):
        raise TencentMapError("腾讯路线 steps 格式异常")

    normalized: list[dict[str, Any]] = []
    for step_index, raw_step in enumerate(raw_steps):
        label = f"腾讯路线第 {step_index + 1} 个 step"
        if not isinstance(raw_step, dict):
            raise TencentMapError(f"{label}格式异常")

        raw_span = raw_step.get("polyline_idx")
        if not isinstance(raw_span, list) or len(raw_span) != 2:
            raise TencentMapError(f"{label} 的 polyline_idx 格式异常")
        raw_start, raw_end = raw_span
        if (
            isinstance(raw_start, bool)
            or isinstance(raw_end, bool)
            or not isinstance(raw_start, int)
            or not isinstance(raw_end, int)
            or raw_start < 0
            or raw_end < raw_start
            or raw_start % 2 != 0
            or raw_end % 2 != 1
            or raw_end >= raw_polyline_length
        ):
            raise TencentMapError(f"{label} 的 polyline_idx 越界或未对齐坐标对")

        normalized.append(
            {
                "instruction": _optional_string(raw_step.get("instruction"), f"{label}.instruction"),
                # polyline_idx 是腾讯压缩前一维数组的原始下标，不是点编号。
                "polyline_idx": [raw_start, raw_end],
                "point_start": raw_start // 2,
                "point_end": raw_end // 2,
                "road_name": _optional_string(raw_step.get("road_name"), f"{label}.road_name"),
                "dir_desc": _optional_string(raw_step.get("dir_desc"), f"{label}.dir_desc"),
                "distance": _non_negative_number(raw_step.get("distance"), f"{label}.distance"),
                "act_desc": _optional_string(raw_step.get("act_desc"), f"{label}.act_desc"),
                # road_class 未出现在腾讯骑行正式字段表中，只保留原值，不在此派生任何判断。
                "road_class": raw_step.get("road_class"),
            }
        )
    return normalized


def plan_tencent_bicycling_route(
    start: tuple[float, float],
    end: tuple[float, float],
    timeout_sec: float = 8.0,
    *,
    from_poi: str | None = None,
    to_poi: str | None = None,
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
    from_poi = _normalize_optional_poi(from_poi, "from_poi")
    to_poi = _normalize_optional_poi(to_poi, "to_poi")

    params = {
        "added_fields": "ferry_count",
        "from": f"{start_lat},{start_lon}",
        "to": f"{end_lat},{end_lon}",
        "key": settings.TENCENT_MAP_KEY,
        "output": "json",
    }
    if from_poi is not None:
        params["from_poi"] = from_poi
    if to_poi is not None:
        params["to_poi"] = to_poi
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

    if not isinstance(data, dict):
        raise TencentMapError("腾讯地图返回格式异常")
    if data.get("status") != 0:
        message = data.get("message") or "腾讯地图路线规划失败"
        raise TencentMapError(str(message))

    result = data.get("result")
    if not isinstance(result, dict):
        raise TencentMapError("腾讯地图缺少路线结果")
    routes = result.get("routes")
    if not isinstance(routes, list):
        raise TencentMapError("腾讯地图 routes 格式异常")
    if not routes:
        raise TencentMapError("腾讯地图没有返回可用路线")

    route = routes[0]
    if not isinstance(route, dict):
        raise TencentMapError("腾讯地图路线格式异常")
    raw_polyline = route.get("polyline")
    points = _decode_polyline(raw_polyline)
    steps = _normalize_steps(route.get("steps"), raw_polyline_length=len(raw_polyline))
    ferry_count_raw = route.get("ferry_count")
    ferry_count: int | None = None
    if ferry_count_raw is not None:
        ferry_count_number = _non_negative_number(ferry_count_raw, "腾讯路线 ferry_count")
        if not ferry_count_number.is_integer():
            raise TencentMapError("腾讯路线 ferry_count 必须是整数")
        ferry_count = int(ferry_count_number)
    duration = route.get("duration")
    _non_negative_number(duration, "腾讯路线 duration")

    return {
        "distance": _non_negative_number(route.get("distance"), "腾讯路线 distance"),
        # 保留旧调用方看到的 int/float 形状，但返回前已做严格数值校验。
        "duration": duration,
        "points": points,
        "mode": _optional_string(route.get("mode"), "腾讯路线 mode"),
        "direction": _optional_string(route.get("direction"), "腾讯路线 direction"),
        "ferry_count": ferry_count,
        "request_id": _optional_provenance_string(data.get("request_id")),
        "steps": steps,
    }
