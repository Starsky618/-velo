"""把腾讯同一次算路返回的道路步骤，可靠地绑定到 VELO 的路线版本。"""

from __future__ import annotations

import base64
import binascii
from datetime import datetime, timezone
import hashlib
import hmac
import json
import math
import re
import secrets
import time
from typing import Any

from app.config import settings
from app.parsing.geo_math import haversine


EVIDENCE_SCHEMA = "tencent_bicycling_evidence_v1"
RECEIPT_SCHEMA = "tencent_snap_receipt_v1"
ROUTING_SCHEMA = "route_routing_evidence_v1"
MAX_RECEIPT_BYTES = 512
MAX_RECEIPT_PAYLOAD_BYTES = 256 * 1024
MAX_TOTAL_EVIDENCE_BYTES = 512 * 1024
ENDPOINT_MATCH_TOLERANCE_M = 5.0
MAX_RECONSTRUCTED_ROUTE_POINTS = 5000
RECEIPT_TTL_SEC = 24 * 60 * 60
RECEIPT_KEY_PREFIX = "route_snap_receipt:v1:"
RECEIPT_QUOTA_KEY_PREFIX = "route_snap_receipt_quota:v1:"
MAX_RECEIPTS_PER_USER_BUCKET = 500
MAX_RECEIPT_BYTES_PER_USER_BUCKET = 32 * 1024 * 1024

_STORE_RECEIPT_LUA = """
local used_bytes = tonumber(redis.call('HGET', KEYS[2], 'bytes') or '0')
local used_count = tonumber(redis.call('HGET', KEYS[2], 'count') or '0')
local payload_bytes = string.len(ARGV[1])
if used_bytes + payload_bytes > tonumber(ARGV[3]) or used_count + 1 > tonumber(ARGV[4]) then
  return 0
end
redis.call('HINCRBY', KEYS[2], 'bytes', payload_bytes)
redis.call('HINCRBY', KEYS[2], 'count', 1)
redis.call('EXPIRE', KEYS[2], tonumber(ARGV[2]) + 3600)
redis.call('SETEX', KEYS[1], tonumber(ARGV[2]), ARGV[1])
return 1
"""


class RoutingEvidenceError(ValueError):
    """贴路凭据损坏、被篡改，或无法对应到待保存路线。"""


class RoutingEvidenceUnavailableError(RuntimeError):
    """Redis 暂时无法保存或读取贴路凭据；此时智能贴路必须失败关闭。"""


class RoutingEvidenceQuotaError(ValueError):
    """单用户短期贴路证据达到共享 Redis 的安全上限。"""


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (binascii.Error, ValueError, TypeError) as exc:
        raise RoutingEvidenceError("贴路凭据格式异常") from exc
    if _b64encode(decoded) != value:
        raise RoutingEvidenceError("贴路凭据格式异常")
    return decoded


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RoutingEvidenceError("腾讯道路证据无法序列化") from exc


def _signature(message: bytes) -> bytes:
    key = settings.JWT_SECRET.encode("utf-8")
    return hmac.new(key, b"velo-routing-receipt-v1\0" + message, hashlib.sha256).digest()


def _get_redis_client():
    from app.queue import redis_conn

    return redis_conn


def _receipt_token(receipt_id: str) -> str:
    message = f"r1.{receipt_id}".encode("ascii")
    return f"r1.{receipt_id}.{_b64encode(_signature(message))}"


def store_snap_receipt(
    evidence: dict[str, Any],
    *,
    current_user_id: int,
    redis_client=None,
) -> str:
    """完整腾讯几何留在服务端 Redis；前端只拿几十字节的 opaque receipt。"""
    payload = _canonical_json(
        {
            "schema": RECEIPT_SCHEMA,
            "current_user_id": int(current_user_id),
            "evidence": evidence,
        }
    )
    if len(payload) > MAX_RECEIPT_PAYLOAD_BYTES:
        raise RoutingEvidenceError("这段贴路信息太长，请缩短后分段保存")
    receipt_id = secrets.token_urlsafe(24)
    client = redis_client or _get_redis_client()
    receipt_key = f"{RECEIPT_KEY_PREFIX}{receipt_id}"
    try:
        if hasattr(client, "eval"):
            bucket = int(time.time()) // RECEIPT_TTL_SEC
            quota_key = f"{RECEIPT_QUOTA_KEY_PREFIX}{int(current_user_id)}:{bucket}"
            stored = client.eval(
                _STORE_RECEIPT_LUA,
                2,
                receipt_key,
                quota_key,
                payload,
                RECEIPT_TTL_SEC,
                MAX_RECEIPT_BYTES_PER_USER_BUCKET,
                MAX_RECEIPTS_PER_USER_BUCKET,
            )
            if int(stored or 0) != 1:
                raise RoutingEvidenceQuotaError("智能贴路草稿过多，请先保存已有路线或改用 Manual Mode")
        else:
            # 仅供最小测试替身；生产 redis-py 必须走上面的原子脚本。
            client.setex(receipt_key, RECEIPT_TTL_SEC, payload)
    except RoutingEvidenceQuotaError:
        raise
    except Exception as exc:
        raise RoutingEvidenceUnavailableError("贴路凭据暂时无法保存，请稍后重试或切 Manual Mode") from exc
    return _receipt_token(receipt_id)


def load_snap_receipt(
    token: str,
    *,
    current_user_id: int,
    redis_client=None,
) -> dict[str, Any]:
    evidence, _payload_bytes = _load_snap_receipt_with_size(
        token,
        current_user_id=current_user_id,
        redis_client=redis_client,
    )
    return evidence


def _load_snap_receipt_with_size(
    token: str,
    *,
    current_user_id: int,
    redis_client=None,
) -> tuple[dict[str, Any], int]:
    if not isinstance(token, str) or not token or len(token.encode("utf-8")) > MAX_RECEIPT_BYTES:
        raise RoutingEvidenceError("贴路凭据格式异常")
    parts = token.split(".")
    if (
        len(parts) != 3
        or parts[0] != "r1"
        or re.fullmatch(r"[A-Za-z0-9_-]{32}", parts[1]) is None
        or re.fullmatch(r"[A-Za-z0-9_-]{43}", parts[2]) is None
    ):
        raise RoutingEvidenceError("贴路凭据格式异常")
    message = f"r1.{parts[1]}".encode("ascii")
    if not hmac.compare_digest(_signature(message), _b64decode(parts[2])):
        raise RoutingEvidenceError("贴路凭据已失效，请重新贴路")
    client = redis_client or _get_redis_client()
    try:
        raw = client.get(f"{RECEIPT_KEY_PREFIX}{parts[1]}")
    except Exception as exc:
        raise RoutingEvidenceUnavailableError("贴路凭据暂时无法读取，请稍后重试") from exc
    if raw is None:
        raise RoutingEvidenceError("贴路凭据已过期，请重新贴路")
    payload_bytes = len(raw if isinstance(raw, bytes) else str(raw).encode("utf-8"))
    if payload_bytes > MAX_RECEIPT_PAYLOAD_BYTES:
        raise RoutingEvidenceError("贴路凭据内容过大")
    try:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        payload = json.loads(raw)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RoutingEvidenceError("贴路凭据内容损坏") from exc
    if not isinstance(payload, dict) or payload.get("schema") != RECEIPT_SCHEMA:
        raise RoutingEvidenceError("贴路凭据版本不兼容")
    if payload.get("current_user_id") != int(current_user_id):
        raise RoutingEvidenceError("贴路凭据不属于当前用户")
    evidence = payload.get("evidence")
    if not isinstance(evidence, dict) or evidence.get("schema") != EVIDENCE_SCHEMA:
        raise RoutingEvidenceError("腾讯道路证据版本不兼容")
    return evidence, payload_bytes


def _point(value: Any, label: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise RoutingEvidenceError(f"{label}格式异常")
    try:
        lon, lat = float(value[0]), float(value[1])
    except (TypeError, ValueError) as exc:
        raise RoutingEvidenceError(f"{label}格式异常") from exc
    if not math.isfinite(lon) or not math.isfinite(lat) or not (-180 <= lon <= 180) or not (-90 <= lat <= 90):
        raise RoutingEvidenceError(f"{label}越界")
    return [lon, lat]


def _points(values: Any, label: str) -> list[list[float]]:
    if not isinstance(values, list) or len(values) < 2:
        raise RoutingEvidenceError(f"{label}至少需要两个点")
    return [_point(value, f"{label}第 {index + 1} 个点") for index, value in enumerate(values)]


def _chainages(points: list[list[float]]) -> list[float]:
    result = [0.0]
    for previous, current in zip(points, points[1:]):
        result.append(result[-1] + haversine(previous[1], previous[0], current[1], current[0]))
    if result[-1] <= 0:
        raise RoutingEvidenceError("腾讯路线长度无效")
    return result


def _optional_number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _geometry_hash(points: list[list[float]]) -> str:
    rounded = [[round(point[0], 7), round(point[1], 7)] for point in points]
    return hashlib.sha256(_canonical_json(rounded)).hexdigest()


def build_tencent_evidence(
    planned: dict[str, Any],
    points_lonlat: list[list[float]],
    *,
    observed_at: str | None = None,
) -> dict[str, Any]:
    """把腾讯临时数组索引换成这次路线内的米制位置，脱离原始数组后仍能解释。"""
    points = _points(points_lonlat, "腾讯路线")
    chainages = _chainages(points)
    raw_steps = planned.get("steps") or []
    if not isinstance(raw_steps, list):
        raise RoutingEvidenceError("腾讯路线 steps 格式异常")

    steps = []
    for index, raw_step in enumerate(raw_steps):
        if not isinstance(raw_step, dict):
            raise RoutingEvidenceError(f"腾讯第 {index + 1} 个道路步骤格式异常")
        point_start = raw_step.get("point_start")
        point_end = raw_step.get("point_end")
        if (
            isinstance(point_start, bool)
            or isinstance(point_end, bool)
            or not isinstance(point_start, int)
            or not isinstance(point_end, int)
            or point_start < 0
            or point_end < point_start
            or point_end >= len(points)
        ):
            raise RoutingEvidenceError(f"腾讯第 {index + 1} 个道路步骤索引越界")
        steps.append(
            {
                "provider_step_index": index,
                "provider_call_index": raw_step.get("provider_call_index"),
                "instruction": raw_step.get("instruction"),
                "road_name": raw_step.get("road_name"),
                "dir_desc": raw_step.get("dir_desc"),
                "act_desc": raw_step.get("act_desc"),
                "distance_m": _optional_number(raw_step.get("distance")),
                "provider_polyline_idx": raw_step.get("polyline_idx"),
                "provider_point_start": point_start,
                "provider_point_end": point_end,
                "provider_chainage_start_m": round(chainages[point_start], 3),
                "provider_chainage_end_m": round(chainages[point_end], 3),
                # 官方骑行契约没有定义 road_class；只保存原值，不参与判断。
                "road_class_raw": raw_step.get("road_class"),
            }
        )

    return {
        "schema": EVIDENCE_SCHEMA,
        "provider": "tencent",
        "profile": "bicycling",
        "observed_at": observed_at or datetime.now(timezone.utc).isoformat(),
        "request_id": planned.get("request_id"),
        "request_ids": planned.get("request_ids"),
        "mode": planned.get("mode"),
        "direction": planned.get("direction"),
        "provider_distance_m": _optional_number(planned.get("distance")),
        "duration_min": _optional_number(planned.get("duration")),
        "ferry_count": planned.get("ferry_count"),
        "provider_calls": planned.get("provider_calls"),
        "unverified_join_gaps": planned.get("unverified_join_gaps"),
        "geometry_distance_m": round(chainages[-1], 3),
        "geometry_point_count": len(points),
        "geometry_hash": _geometry_hash(points),
        # receipt 必须携带完整腾讯几何；save 端据此重建正式路线，不能只凭起终点猜中间形状。
        "geometry_gcj02": points,
        "start_gcj02": points[0],
        "end_gcj02": points[-1],
        "steps": steps,
    }


def _distance_between(a: list[float], b: list[float]) -> float:
    return haversine(a[1], a[0], b[1], b[0])


def _bind_evidence_exact(
    evidence: dict[str, Any],
    route_points: list[list[float]],
    route_chainages: list[float],
    point_offset: int,
) -> dict[str, Any]:
    provider_point_count = evidence.get("geometry_point_count")
    if not isinstance(provider_point_count, int) or provider_point_count < 2:
        raise RoutingEvidenceError("腾讯道路证据点数无效")
    start_index = point_offset
    end_index = point_offset + provider_point_count - 1
    if point_offset < 0 or end_index >= len(route_points):
        raise RoutingEvidenceError("腾讯道路证据无法绑定到正式路线")

    bound_calls = []
    for raw_call in evidence.get("provider_calls") or []:
        if not isinstance(raw_call, dict):
            raise RoutingEvidenceError("腾讯子请求证据格式异常")
        local_start = raw_call.get("provider_point_start")
        local_end = raw_call.get("provider_point_end")
        if (
            not isinstance(local_start, int)
            or not isinstance(local_end, int)
            or local_start < 0
            or local_end < local_start
            or local_end >= provider_point_count
        ):
            raise RoutingEvidenceError("腾讯子请求点位格式异常")
        bound_calls.append(
            {
                **raw_call,
                "route_point_start": point_offset + local_start,
                "route_point_end": point_offset + local_end,
                "route_chainage_start_m": round(route_chainages[point_offset + local_start], 3),
                "route_chainage_end_m": round(route_chainages[point_offset + local_end], 3),
            }
        )

    bound_join_gaps = []
    for raw_gap in evidence.get("unverified_join_gaps") or []:
        if not isinstance(raw_gap, dict):
            raise RoutingEvidenceError("腾讯子路线连接缺口格式异常")
        local_start = raw_gap.get("provider_point_start")
        local_end = raw_gap.get("provider_point_end")
        if (
            not isinstance(local_start, int)
            or not isinstance(local_end, int)
            or local_start < 0
            or local_end <= local_start
            or local_end >= provider_point_count
        ):
            raise RoutingEvidenceError("腾讯子路线连接缺口点位格式异常")
        bound_join_gaps.append(
            {
                **raw_gap,
                "route_point_start": point_offset + local_start,
                "route_point_end": point_offset + local_end,
                "route_chainage_start_m": round(route_chainages[point_offset + local_start], 3),
                "route_chainage_end_m": round(route_chainages[point_offset + local_end], 3),
            }
        )

    bound_steps = []
    for raw_step in evidence.get("steps") or []:
        if not isinstance(raw_step, dict):
            raise RoutingEvidenceError("腾讯道路步骤格式异常")
        local_start_index = raw_step.get("provider_point_start")
        local_end_index = raw_step.get("provider_point_end")
        if (
            not isinstance(local_start_index, int)
            or not isinstance(local_end_index, int)
            or local_start_index < 0
            or local_end_index < local_start_index
            or local_end_index >= provider_point_count
        ):
            raise RoutingEvidenceError("腾讯道路步骤点位格式异常")
        step_start_index = point_offset + local_start_index
        step_end_index = point_offset + local_end_index
        step = dict(raw_step)
        step["route_point_start"] = step_start_index
        step["route_point_end"] = step_end_index
        step["chainage_start_m"] = round(route_chainages[step_start_index], 3)
        step["chainage_end_m"] = round(route_chainages[step_end_index], 3)
        bound_steps.append(step)

    return {
        **{
            key: value
            for key, value in evidence.items()
            if key not in {"steps", "geometry_gcj02", "provider_calls", "unverified_join_gaps"}
        },
        "provider_calls": bound_calls or None,
        "unverified_join_gaps": bound_join_gaps or None,
        "route_point_start": start_index,
        "route_point_end": end_index,
        "route_chainage_start_m": round(route_chainages[start_index], 3),
        "route_chainage_end_m": round(route_chainages[end_index], 3),
        "steps": bound_steps,
    }


def _routing_metadata(
    segments: list[dict[str, Any]],
    *,
    line_hash: str,
    source: str,
    route_point_count: int,
    route_distance_m: float,
) -> dict[str, Any]:
    steps = []
    for segment_index, segment in enumerate(segments):
        for step in segment.get("steps") or []:
            steps.append({"segment_index": segment_index, **step})
    duration_values = [segment.get("duration_min") for segment in segments]
    ferry_values = [segment.get("ferry_count") for segment in segments]
    spans = []
    for segment in segments:
        provider_calls = segment.get("provider_calls")
        span_sources = provider_calls if provider_calls else [segment]
        for span in span_sources:
            spans.append(
                (
                    int(span["route_point_start"]),
                    int(span["route_point_end"]),
                    float(span["route_chainage_start_m"]),
                    float(span["route_chainage_end_m"]),
                )
            )
    spans.sort()
    coverage_complete = bool(spans) and spans[0][0] == 0 and spans[-1][1] == route_point_count - 1
    covered_distance_m = 0.0
    previous_end_index = None
    previous_end_chainage = None
    for start_index, end_index, start_chainage, end_chainage in spans:
        if previous_end_index is not None and start_index > previous_end_index:
            coverage_complete = False
        if previous_end_chainage is None or start_chainage >= previous_end_chainage:
            covered_distance_m += max(0.0, end_chainage - start_chainage)
        elif end_chainage > previous_end_chainage:
            covered_distance_m += end_chainage - previous_end_chainage
        previous_end_index = max(previous_end_index or 0, end_index)
        previous_end_chainage = max(previous_end_chainage or 0.0, end_chainage)
    coverage_ratio = min(1.0, covered_distance_m / route_distance_m) if route_distance_m > 0 else 0.0
    geometry_exact = all(
        not segment.get("unverified_join_gaps")
        and float(segment.get("route_part_join_adjustment_m") or 0.0) == 0.0
        for segment in segments
    )
    return {
        "schema": ROUTING_SCHEMA,
        "provider": "tencent",
        "profile": "bicycling",
        "source": source,
        "route_line_hash": line_hash,
        "provider_segment_count": len(segments),
        "coverage_complete": coverage_complete,
        "covered_distance_m": round(covered_distance_m, 3),
        "route_distance_m": round(route_distance_m, 3),
        "coverage_ratio": round(coverage_ratio, 6),
        "geometry_exact": geometry_exact,
        "duration_min": (
            round(sum(float(value) for value in duration_values), 3)
            if coverage_complete and all(value is not None for value in duration_values)
            else None
        ),
        "ferry_count": (
            sum(int(value) for value in ferry_values)
            if coverage_complete and all(value is not None for value in ferry_values)
            else None
        ),
        "segments": segments,
        "steps": steps,
    }


def routing_metadata_for_direct_route(
    planned: dict[str, Any],
    *,
    provider_points_lonlat: list[list[float]],
    route_points_lonlat: list[list[float]],
    line_hash: str,
    from_poi: str | None = None,
    to_poi: str | None = None,
    from_poi_context: dict[str, Any] | None = None,
    to_poi_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    evidence = build_tencent_evidence(planned, provider_points_lonlat)
    route_points = _points(route_points_lonlat, "正式路线")
    if evidence.get("geometry_point_count") != len(route_points):
        raise RoutingEvidenceError("腾讯路线坐标转换后点数不一致")
    segment = _bind_evidence_exact(evidence, route_points, _chainages(route_points), 0)
    segment["from_poi"] = from_poi
    segment["to_poi"] = to_poi
    # ID 真正回传给了腾讯算路；其余地点字段来自小程序回显，只能当诊断上下文，不能当分类真值。
    segment["from_poi_context"] = (
        {"source": "client_echo", "verified": False, "data": from_poi_context}
        if from_poi_context is not None
        else None
    )
    segment["to_poi_context"] = (
        {"source": "client_echo", "verified": False, "data": to_poi_context}
        if to_poi_context is not None
        else None
    )
    route_chainages = _chainages(route_points)
    return _routing_metadata(
        [segment],
        line_hash=line_hash,
        source="tencent_direction",
        route_point_count=len(route_points),
        route_distance_m=route_chainages[-1],
    )


def reconstruct_route_from_segments(
    route_segments: list[dict[str, Any]],
    *,
    current_user_id: int,
) -> tuple[list[list[float]], list[dict[str, Any]]]:
    """验证 receipt 后重建完整 GCJ 路线；snap 段绝不采用客户端重画的中间点。"""
    if not isinstance(route_segments, list) or not route_segments:
        raise RoutingEvidenceError("route_segments 必须是非空数组")

    total_evidence_bytes = 0
    receipt_cache: dict[str, tuple[dict[str, Any], int]] = {}
    reconstructed: list[list[float]] = []
    bindings: list[dict[str, Any]] = []
    for segment_index, segment in enumerate(route_segments):
        if not isinstance(segment, dict):
            raise RoutingEvidenceError(f"第 {segment_index + 1} 个路线片段格式异常")
        mode = segment.get("mode")
        if mode == "snap":
            token = segment.get("routing_receipt")
            if not isinstance(token, str):
                raise RoutingEvidenceError(f"第 {segment_index + 1} 个贴路片段缺少凭据")
            try:
                cached = receipt_cache.get(token)
                if cached is None:
                    cached = _load_snap_receipt_with_size(token, current_user_id=current_user_id)
                    receipt_cache[token] = cached
                evidence, evidence_bytes = cached
            except RoutingEvidenceError as exc:
                raise RoutingEvidenceError(f"第 {segment_index + 1} 个贴路片段：{exc}") from exc
            # 同一 receipt 重复使用仍会重复写入正式路线元数据，因此按出现次数累计。
            total_evidence_bytes += evidence_bytes
            if total_evidence_bytes > MAX_TOTAL_EVIDENCE_BYTES:
                raise RoutingEvidenceError("腾讯道路证据总量过大，请拆分路线")
            segment_points = _points(evidence.get("geometry_gcj02"), "腾讯贴路线")
            if _geometry_hash(segment_points) != evidence.get("geometry_hash"):
                raise RoutingEvidenceError("腾讯贴路线几何校验失败")
        elif mode == "freehand":
            evidence = None
            segment_points = _points(segment.get("points"), "自由画路线")
        else:
            raise RoutingEvidenceError(f"第 {segment_index + 1} 个路线片段模式异常")

        join_adjustment_m = 0.0
        if not reconstructed:
            point_offset = 0
            reconstructed.extend(segment_points)
        else:
            join_adjustment_m = _distance_between(reconstructed[-1], segment_points[0])
            if join_adjustment_m > ENDPOINT_MATCH_TOLERANCE_M:
                raise RoutingEvidenceError(f"第 {segment_index + 1} 个路线片段没有接上上一段")
            point_offset = len(reconstructed) - 1
            reconstructed.extend(segment_points[1:])
        if evidence is not None:
            bindings.append(
                {
                    "segment_index": segment_index,
                    "point_offset": point_offset,
                    "join_adjustment_m": join_adjustment_m,
                    "evidence": evidence,
                }
            )
        if len(reconstructed) > MAX_RECONSTRUCTED_ROUTE_POINTS:
            raise RoutingEvidenceError("路线点过多，请拆分保存")

    if len(reconstructed) < 2:
        raise RoutingEvidenceError("路线至少需要两个点")
    return reconstructed, bindings


def routing_metadata_for_reconstructed_route(
    bindings: list[dict[str, Any]],
    *,
    route_points_lonlat: list[list[float]],
    line_hash: str,
) -> dict[str, Any] | None:
    if not bindings:
        return None
    route_points = _points(route_points_lonlat, "正式路线")
    route_chainages = _chainages(route_points)
    segments = []
    for binding in bindings:
        evidence = binding.get("evidence")
        point_offset = binding.get("point_offset")
        if not isinstance(evidence, dict) or not isinstance(point_offset, int):
            raise RoutingEvidenceError("路线证据绑定格式异常")
        segment = _bind_evidence_exact(evidence, route_points, route_chainages, point_offset)
        segment["draw_segment_index"] = binding.get("segment_index")
        segment["route_part_join_adjustment_m"] = round(float(binding.get("join_adjustment_m") or 0.0), 3)
        segments.append(segment)
    return _routing_metadata(
        segments,
        line_hash=line_hash,
        source="manual_draw_snap_receipts",
        route_point_count=len(route_points),
        route_distance_m=route_chainages[-1],
    )
