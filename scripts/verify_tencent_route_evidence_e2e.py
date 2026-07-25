#!/usr/bin/env python3
"""在隔离 PostGIS/Redis 上验收真实腾讯地点与骑行证据链。

这不是海拔精度实验。为了只验证腾讯证据能否完整穿过真 TCP HTTP、Redis 和
PostGIS，脚本会在独立 Uvicorn 进程内把 DEM 查询替换成常数海拔；正式业务代码
和数据库不会被修改。

安全门：
- 必须显式设置 ``VELO_LIVE_TENCENT_E2E=1``；
- PostgreSQL 必须是本机、数据库名必须以 ``velo_e2e_`` 开头；
- PostgreSQL/Redis URL 禁止 query 参数覆盖最终连接目标；
- Redis 必须是本机 ``16379/15`` 且运行前为空；脚本只删除自己创建的 key。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time
from typing import Any
from urllib.parse import urlsplit
import uuid

import httpx
from sqlalchemy import create_engine, func, text
from sqlalchemy.orm import sessionmaker


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


REDIS_OWNER_KEY = "velo_tencent_e2e_owner:v1"
ROUTE_FIXTURE_SCHEMA = "tencent-saved-routeversion-fixture-v1"
ROUTE_ARTIFACT_SCHEMA = "tencent-saved-routeversion-evidence-v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAMPLE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

_ARTIFACT_SECRET_KEYS = {
    "request_id",
    "request_ids",
    "routing_receipt",
    "receipt",
    "receipts",
    "current_user_id",
    "user_id",
    "user",
    "openid",
    "key",
    "sk",
    "sig",
    "url",
}
_ARTIFACT_ELEVATION_KEYS = {
    "elevation",
    "elevation_grid",
    "elevation_grid_snapshot",
    "elevation_profile",
    "profile_points",
    "climb",
    "climbs",
    "grid",
}

_ROUTING_ROOT_FIELDS = (
    "schema",
    "provider",
    "profile",
    "source",
    "route_line_hash",
    "provider_segment_count",
    "coverage_complete",
    "covered_distance_m",
    "route_distance_m",
    "coverage_ratio",
    "geometry_exact",
    "duration_min",
    "ferry_count",
)
_ROUTING_SEGMENT_FIELDS = (
    "schema",
    "provider",
    "profile",
    "mode",
    "direction",
    "provider_distance_m",
    "duration_min",
    "ferry_count",
    "geometry_distance_m",
    "geometry_point_count",
    "geometry_hash",
    "route_point_start",
    "route_point_end",
    "route_chainage_start_m",
    "route_chainage_end_m",
    "draw_segment_index",
    "route_part_join_adjustment_m",
)
_ROUTING_CALL_FIELDS = (
    "call_index",
    "distance_m",
    "duration_min",
    "ferry_count",
    "mode",
    "direction",
    "provider_point_start",
    "provider_point_end",
    "route_point_start",
    "route_point_end",
    "route_chainage_start_m",
    "route_chainage_end_m",
)
_ROUTING_GAP_FIELDS = (
    "after_provider_call_index",
    "before_provider_call_index",
    "provider_point_start",
    "provider_point_end",
    "distance_m",
    "route_point_start",
    "route_point_end",
    "route_chainage_start_m",
    "route_chainage_end_m",
)
_ROUTING_STEP_FIELDS = (
    "segment_index",
    "provider_step_index",
    "provider_call_index",
    "instruction",
    "road_name",
    "dir_desc",
    "act_desc",
    "distance_m",
    "provider_polyline_idx",
    "provider_point_start",
    "provider_point_end",
    "provider_chainage_start_m",
    "provider_chainage_end_m",
    "road_class_raw",
    "route_point_start",
    "route_point_end",
    "chainage_start_m",
    "chainage_end_m",
)


class VerificationError(RuntimeError):
    """端到端验收没有满足明确不变量。"""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def _canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise VerificationError("数据无法序列化为严格 JSON") from exc


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    _require(actual == expected, f"{label} 字段必须恰好为 {sorted(expected)}")


def _fixture_number(value: Any, label: str) -> float:
    _require(not isinstance(value, bool) and isinstance(value, (int, float)), f"{label} 必须是数字")
    number = float(value)
    _require(math.isfinite(number), f"{label} 必须是有限数字")
    return number


def _fixture_point(value: Any, label: str) -> list[float]:
    _require(isinstance(value, list) and len(value) == 2, f"{label} 必须是 [lon, lat]")
    lon = _fixture_number(value[0], f"{label}.lon")
    lat = _fixture_number(value[1], f"{label}.lat")
    _require(70.0 <= lon <= 140.0 and 0.0 <= lat <= 60.0, f"{label} 不在中国 GCJ02 合理范围")
    return [lon, lat]


def _same_fixture_point(left: list[float], right: list[float]) -> bool:
    return abs(left[0] - right[0]) <= 1e-7 and abs(left[1] - right[1]) <= 1e-7


def _retained_anchor_indices(
    input_points: list[list[float]],
    returned_points: Any,
    *,
    part_index: int,
) -> list[int]:
    """证明生产 RDP 只删除了 via anchors，没有重排或凭空增加锚点。"""

    _require(isinstance(returned_points, list) and len(returned_points) >= 2, f"fixture 第 {part_index + 1} 段返回锚点不足")
    normalized_returned = [
        _fixture_point(point, f"fixture 第 {part_index + 1} 段腾讯返回锚点[{index}]")
        for index, point in enumerate(returned_points)
    ]
    _require(_same_fixture_point(normalized_returned[0], input_points[0]), f"fixture 第 {part_index + 1} 段首锚点被删除或漂移")
    _require(_same_fixture_point(normalized_returned[-1], input_points[-1]), f"fixture 第 {part_index + 1} 段尾锚点被删除或漂移")

    retained = [0]
    next_input_index = 1
    for returned_index, returned in enumerate(normalized_returned[1:-1], start=1):
        match = next(
            (
                input_index
                for input_index in range(next_input_index, len(input_points) - 1)
                if _same_fixture_point(returned, input_points[input_index])
            ),
            None,
        )
        _require(match is not None, f"fixture 第 {part_index + 1} 段返回锚点[{returned_index}] 不是输入锚点的有序子序列")
        retained.append(match)
        next_input_index = match + 1
    retained.append(len(input_points) - 1)
    _require(len(retained) == len(normalized_returned), f"fixture 第 {part_index + 1} 段锚点映射数量异常")
    return retained


def _anchor_retention_summary(part: dict[str, Any], returned_points: Any, *, part_index: int) -> dict[str, Any]:
    retained_indices = _retained_anchor_indices(part["points_gcj02"], returned_points, part_index=part_index)
    retained_index_set = set(retained_indices)
    chainages = part["anchor_chainages_m"]
    return {
        "input_anchor_count": len(chainages),
        "retained_anchor_count": len(retained_indices),
        "input_anchor_chainages_m": list(chainages),
        "retained_anchor_chainages_m": [chainages[index] for index in retained_indices],
        "dropped_anchor_chainages_m": [
            chainage
            for index, chainage in enumerate(chainages)
            if index not in retained_index_set
        ],
    }


def _load_route_fixture(path: Path) -> dict[str, Any]:
    """加载可手写的冻结路线分段；任何模糊字段都失败关闭。"""

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerificationError("route fixture 无法读取为 JSON") from exc
    _require(isinstance(raw, dict), "route fixture 顶层必须是对象")
    _exact_keys(
        raw,
        {
            "schema",
            "sample_id",
            "purpose",
            "source_profile_csv",
            "source_profile_sha256",
            "target_start_m",
            "target_end_m",
            "coordinate_system",
            "anchor_policy",
            "parts",
            "hard_boundaries",
        },
        "route fixture",
    )
    _require(raw["schema"] == ROUTE_FIXTURE_SCHEMA, "route fixture schema 不兼容")
    sample_id = raw["sample_id"]
    _require(isinstance(sample_id, str) and _SAMPLE_ID_RE.fullmatch(sample_id) is not None, "sample_id 格式异常")
    purpose = raw["purpose"]
    _require(isinstance(purpose, str) and 1 <= len(purpose) <= 500, "purpose 必须是 1 到 500 字符")
    _require(raw["coordinate_system"] == "gcj02", "coordinate_system 必须是 gcj02")

    anchor_policy = raw["anchor_policy"]
    _require(isinstance(anchor_policy, dict), "anchor_policy 必须是对象")
    _exact_keys(anchor_policy, {"source", "spacing_m", "answers_used", "revision"}, "anchor_policy")
    anchor_source = anchor_policy["source"]
    _require(isinstance(anchor_source, str) and 1 <= len(anchor_source) <= 300, "anchor_policy.source 格式异常")
    anchor_spacing_m = _fixture_number(anchor_policy["spacing_m"], "anchor_policy.spacing_m")
    _require(anchor_spacing_m > 0.0, "anchor_policy.spacing_m 必须大于 0")
    _require(anchor_policy["answers_used"] is False, "anchor_policy.answers_used 必须严格为 false")
    anchor_revision = anchor_policy["revision"]
    _require(
        not isinstance(anchor_revision, bool)
        and isinstance(anchor_revision, int)
        and 0 <= anchor_revision <= 2,
        "anchor_policy.revision 只允许 0、1、2；r2 失败后禁止继续递归加 anchor",
    )

    hard_boundaries = raw["hard_boundaries"]
    _require(isinstance(hard_boundaries, list) and 1 <= len(hard_boundaries) <= 20, "hard_boundaries 必须包含 1 到 20 条")
    _require(
        all(isinstance(boundary, str) and 1 <= len(boundary) <= 500 for boundary in hard_boundaries),
        "hard_boundaries 每条必须是 1 到 500 字符",
    )
    _require(len(set(hard_boundaries)) == len(hard_boundaries), "hard_boundaries 不允许重复")

    source_profile_csv = raw["source_profile_csv"]
    _require(isinstance(source_profile_csv, str) and source_profile_csv.endswith(".csv"), "source_profile_csv 必须是仓库内相对 CSV 路径")
    source_relative = Path(source_profile_csv)
    _require(not source_relative.is_absolute(), "source_profile_csv 不允许绝对路径")
    source_path = (ROOT / source_relative).resolve()
    try:
        normalized_source = source_path.relative_to(ROOT.resolve()).as_posix()
    except ValueError as exc:
        raise VerificationError("source_profile_csv 不允许逃出仓库") from exc
    _require(source_path.is_file(), "source_profile_csv 不存在")
    _require(source_path.stat().st_size <= 100 * 1024 * 1024, "source_profile_csv 超过 100MiB")
    source_sha256 = raw["source_profile_sha256"]
    _require(isinstance(source_sha256, str) and _SHA256_RE.fullmatch(source_sha256) is not None, "source_profile_sha256 格式异常")
    _require(_sha256_file(source_path) == source_sha256, "source_profile_sha256 与文件不一致")

    target_start_m = _fixture_number(raw["target_start_m"], "target_start_m")
    target_end_m = _fixture_number(raw["target_end_m"], "target_end_m")
    _require(0.0 <= target_start_m < target_end_m, "target_start_m/target_end_m 范围异常")
    parts = raw["parts"]
    _require(isinstance(parts, list) and 3 <= len(parts) <= 20, "parts 必须包含 3 到 20 段")

    normalized_parts: list[dict[str, Any]] = []
    previous_end_chainage: float | None = None
    previous_end_point: list[float] | None = None
    for part_index, raw_part in enumerate(parts):
        _require(isinstance(raw_part, dict), f"parts[{part_index}] 必须是对象")
        _exact_keys(raw_part, {"anchor_chainages_m", "points_gcj02"}, f"parts[{part_index}]")
        raw_chainages = raw_part["anchor_chainages_m"]
        raw_points = raw_part["points_gcj02"]
        _require(isinstance(raw_chainages, list), f"parts[{part_index}].anchor_chainages_m 必须是数组")
        _require(isinstance(raw_points, list), f"parts[{part_index}].points_gcj02 必须是数组")
        _require(2 <= len(raw_points) <= 11, f"parts[{part_index}] 必须包含 2 到 11 个锚点")
        _require(len(raw_chainages) == len(raw_points), f"parts[{part_index}] chainage 与坐标数量不一致")
        chainages = [
            _fixture_number(value, f"parts[{part_index}].anchor_chainages_m[{index}]")
            for index, value in enumerate(raw_chainages)
        ]
        points = [
            _fixture_point(value, f"parts[{part_index}].points_gcj02[{index}]")
            for index, value in enumerate(raw_points)
        ]
        _require(all(left < right for left, right in zip(chainages, chainages[1:])), f"parts[{part_index}] chainage 必须严格递增")
        _require(
            all(abs((right - left) - anchor_spacing_m) <= 0.001 for left, right in zip(chainages, chainages[1:])),
            f"parts[{part_index}] chainage 间隔不符合 anchor_policy.spacing_m",
        )
        if previous_end_chainage is None:
            _require(abs(chainages[0] - target_start_m) <= 0.001, "第一段必须从 target_start_m 开始")
        else:
            _require(abs(chainages[0] - previous_end_chainage) <= 0.001, f"parts[{part_index}] chainage 没有接上上一段")
            _require(previous_end_point is not None and _same_fixture_point(points[0], previous_end_point), f"parts[{part_index}] GCJ02 起点没有接上上一段")
        previous_end_chainage = chainages[-1]
        previous_end_point = points[-1]
        normalized_parts.append(
            {
                "anchor_chainages_m": chainages,
                "points_gcj02": points,
            }
        )
    _require(previous_end_chainage is not None and abs(previous_end_chainage - target_end_m) <= 0.001, "最后一段必须结束于 target_end_m")

    return {
        "schema": ROUTE_FIXTURE_SCHEMA,
        "sample_id": sample_id,
        "purpose": purpose,
        "source_profile_csv": normalized_source,
        "source_profile_sha256": source_sha256,
        "target_start_m": target_start_m,
        "target_end_m": target_end_m,
        "coordinate_system": "gcj02",
        "anchor_policy": {
            "source": anchor_source,
            "spacing_m": anchor_spacing_m,
            "answers_used": False,
            "revision": anchor_revision,
        },
        "parts": normalized_parts,
        "hard_boundaries": list(hard_boundaries),
    }


def _is_artifact_secret_key(key: str) -> bool:
    normalized = key.strip().lower().replace("-", "_")
    return normalized in _ARTIFACT_SECRET_KEYS or "receipt" in normalized


def _strip_artifact_secrets(value: Any) -> Any:
    """最后一道递归 fail-safe；正式 artifact 仍由逐字段白名单构造。"""

    if isinstance(value, dict):
        return {
            key: _strip_artifact_secrets(item)
            for key, item in value.items()
            if not _is_artifact_secret_key(str(key))
        }
    if isinstance(value, list):
        return [_strip_artifact_secrets(item) for item in value]
    return value


def _assert_artifact_safe(value: Any, *, protected_markers: list[str] | None = None) -> None:
    def visit(item: Any) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                normalized = str(key).strip().lower().replace("-", "_")
                _require(not _is_artifact_secret_key(str(key)), "artifact 含受禁止的身份、receipt 或腾讯请求字段")
                _require(normalized not in _ARTIFACT_ELEVATION_KEYS, "artifact 混入常数 DEM 海拔、爬升或网格结果")
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    serialized = _canonical_json_bytes(value)
    lowered = serialized.lower()
    _require(b"apis.map.qq.com" not in lowered, "artifact 含腾讯请求 URL")
    _require(b"?key=" not in lowered and b"&key=" not in lowered, "artifact 含腾讯 key URL")
    _require(b"?sig=" not in lowered and b"&sig=" not in lowered, "artifact 含腾讯 sig URL")
    for marker in protected_markers or []:
        if marker:
            _require(marker.encode("utf-8") not in serialized, "artifact 含受保护凭据")


def _safe_json_scalar_or_list(value: Any, label: str) -> Any:
    _require(not isinstance(value, dict), f"{label} 不允许嵌套对象")
    copied = json.loads(_canonical_json_bytes(value))
    return copied


def _copy_safe_fields(source: dict[str, Any], fields: tuple[str, ...], label: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field in fields:
        if field in source:
            result[field] = _safe_json_scalar_or_list(source[field], f"{label}.{field}")
    return result


def _safe_routing_artifact(routing: dict[str, Any]) -> dict[str, Any]:
    """只暴露判断道路结构所需字段；原始请求标识和 receipt 永远不进入 artifact。"""

    safe = _copy_safe_fields(routing, _ROUTING_ROOT_FIELDS, "routing")
    raw_segments = routing.get("segments") or []
    _require(isinstance(raw_segments, list) and bool(raw_segments), "routing.segments 必须是非空数组")
    safe_segments = []
    for index, segment in enumerate(raw_segments):
        _require(isinstance(segment, dict), f"routing.segments[{index}] 不是对象")
        safe_segment = _copy_safe_fields(segment, _ROUTING_SEGMENT_FIELDS, f"routing.segments[{index}]")
        raw_calls = segment.get("provider_calls") or []
        _require(isinstance(raw_calls, list), f"routing.segments[{index}].provider_calls 不是数组")
        safe_calls = []
        for call_index, call in enumerate(raw_calls):
            _require(isinstance(call, dict), f"routing.segments[{index}].provider_calls[{call_index}] 不是对象")
            safe_calls.append(
                _copy_safe_fields(call, _ROUTING_CALL_FIELDS, f"routing.segments[{index}].provider_calls[{call_index}]")
            )
        safe_segment["provider_calls"] = safe_calls
        raw_gaps = segment.get("unverified_join_gaps") or []
        _require(isinstance(raw_gaps, list), f"routing.segments[{index}].unverified_join_gaps 不是数组")
        safe_gaps = []
        for gap_index, gap in enumerate(raw_gaps):
            _require(isinstance(gap, dict), f"routing.segments[{index}].unverified_join_gaps[{gap_index}] 不是对象")
            safe_gaps.append(
                _copy_safe_fields(gap, _ROUTING_GAP_FIELDS, f"routing.segments[{index}].unverified_join_gaps[{gap_index}]")
            )
        safe_segment["unverified_join_gaps"] = safe_gaps
        safe_segments.append(safe_segment)
    safe["segments"] = safe_segments
    raw_steps = routing.get("steps") or []
    _require(isinstance(raw_steps, list) and bool(raw_steps), "routing.steps 必须是非空数组")
    safe_steps = []
    for index, step in enumerate(raw_steps):
        _require(isinstance(step, dict), f"routing.steps[{index}] 不是对象")
        safe_steps.append(_copy_safe_fields(step, _ROUTING_STEP_FIELDS, f"routing.steps[{index}]"))
    safe["steps"] = safe_steps
    safe = _strip_artifact_secrets(safe)
    _assert_artifact_safe(safe)
    return safe


def _atomic_write_json_new(path: Path, payload: dict[str, Any]) -> None:
    """同文件系统临时文件 + hard-link 提交，竞争时也绝不覆盖已有 artifact。"""

    _assert_artifact_safe(payload)
    path = path.expanduser().absolute()
    if path.exists() or path.is_symlink():
        raise VerificationError("artifact 已存在，拒绝覆盖")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(_canonical_json_bytes(payload) + b"\n")
            output.flush()
            os.fsync(output.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise VerificationError("artifact 已存在，拒绝覆盖") from exc
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def _guard_isolated_services(database_url: str, redis_url: str) -> None:
    if os.getenv("VELO_LIVE_TENCENT_E2E") != "1":
        raise VerificationError("必须显式设置 VELO_LIVE_TENCENT_E2E=1")

    database = urlsplit(database_url)
    database_name = database.path.lstrip("/")
    _require(database.scheme.startswith("postgresql"), "只允许 PostgreSQL")
    _require(database.hostname in {"127.0.0.1", "localhost"}, "PostgreSQL 必须在本机")
    _require(database_name.startswith("velo_e2e_"), "数据库名必须以 velo_e2e_ 开头")
    _require(not database.query and not database.fragment, "PostgreSQL URL 不允许 query 或 fragment")

    redis = urlsplit(redis_url)
    _require(redis.scheme in {"redis", "rediss"}, "REDIS_URL 格式异常")
    _require(redis.hostname in {"127.0.0.1", "localhost"}, "Redis 必须在本机")
    _require(redis.port == 16379 and redis.path == "/15", "只允许使用 VELO dev Redis 的 DB 15")
    _require(not redis.query and not redis.fragment, "Redis URL 不允许 query 或 fragment")


def _claim_redis_db(redis_client) -> str:
    """独占一座空的 E2E 逻辑库；绝不清空未知 key。"""

    _require(redis_client.dbsize() == 0, "Redis DB 15 不是空库，拒绝运行以免误删其他数据")
    owner = uuid.uuid4().hex
    claimed = redis_client.set(REDIS_OWNER_KEY, owner, ex=60 * 60, nx=True)
    _require(bool(claimed), "Redis DB 15 已被另一轮验收占用")
    if redis_client.dbsize() != 1:
        redis_client.delete(REDIS_OWNER_KEY)
        raise VerificationError("占用 Redis DB 15 时出现未知 key，已停止且未清空")
    return owner


def _release_redis_db(redis_client, owner: str, user_id: int | None) -> None:
    """仅删除本轮用户的限流、配额、receipt 和 ownership key。"""

    current_owner = redis_client.get(REDIS_OWNER_KEY)
    if isinstance(current_owner, bytes):
        current_owner = current_owner.decode("utf-8", errors="replace")
    _require(current_owner == owner, "Redis E2E ownership 已丢失，拒绝删除任何 key")

    owned_keys: set[bytes | str] = {REDIS_OWNER_KEY}
    if user_id is not None:
        owned_keys.update(redis_client.scan_iter(match=f"rl:*:u:{user_id}"))
        owned_keys.update(redis_client.scan_iter(match=f"route_snap_receipt_quota:v1:{user_id}:*"))
        for key in redis_client.scan_iter(match="route_snap_receipt:v1:*"):
            raw = redis_client.get(key)
            try:
                payload = json.loads(raw) if raw is not None else {}
            except (TypeError, ValueError):
                continue
            if payload.get("current_user_id") == user_id:
                owned_keys.add(key)

    if owned_keys:
        redis_client.delete(*owned_keys)
    _require(redis_client.dbsize() == 0, "Redis DB 15 留有非本轮 key；已保留未知数据并判定验收失败")


def _e2e_port() -> int:
    try:
        port = int(os.getenv("VELO_E2E_PORT", "18001"))
    except ValueError as exc:
        raise VerificationError("VELO_E2E_PORT 必须是整数") from exc
    _require(1024 <= port <= 65535, "VELO_E2E_PORT 必须是非特权 TCP 端口")
    return port


def _require_free_port(port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError as exc:
            raise VerificationError(f"本机端口 {port} 已被占用") from exc


def _start_server(port: int, log_file) -> subprocess.Popen[bytes]:
    env = os.environ.copy()
    env["VELO_E2E_PORT"] = str(port)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--serve"],
        cwd=ROOT,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )


def _wait_for_server(process: subprocess.Popen[bytes], base_url: str) -> None:
    deadline = time.monotonic() + 20.0
    last_reason = "尚未监听"
    with httpx.Client(base_url=base_url, timeout=0.5, trust_env=False) as client:
        while time.monotonic() < deadline:
            return_code = process.poll()
            if return_code is not None:
                raise VerificationError(f"隔离 API 进程提前退出，exit={return_code}")
            try:
                response = client.get("/health")
                if response.status_code == 200 and response.json() == {"status": "ok"}:
                    return
                last_reason = f"health HTTP {response.status_code}"
            except (httpx.HTTPError, ValueError) as exc:
                last_reason = exc.__class__.__name__
            time.sleep(0.1)
    raise VerificationError(f"隔离 API 20 秒内未就绪：{last_reason}")


def _stop_server(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _assert_server_log_safe(log_file, protected_markers: list[str]) -> None:
    """扫描真实子进程日志，但错误信息本身不回显任何日志或凭据。"""

    log_file.flush()
    log_file.seek(0)
    data = log_file.read()
    lowered = data.lower()
    for marker in protected_markers:
        if marker and marker.encode("utf-8") in data:
            raise VerificationError("隔离 API 日志包含受保护凭据")
    if b"apis.map.qq.com" in lowered and any(
        token in lowered for token in (b"?key=", b"&key=", b"?sig=", b"&sig=")
    ):
        raise VerificationError("隔离 API 日志包含腾讯签名请求 URL")


def _http_json(response, label: str, expected_status: int = 200) -> Any:
    if response.status_code != expected_status:
        raise VerificationError(f"{label} HTTP {response.status_code}")
    try:
        return response.json()
    except ValueError as exc:
        raise VerificationError(f"{label} 没有返回 JSON") from exc


def _pick_place(items: list[dict[str, Any]], keyword: str) -> dict[str, Any]:
    _require(bool(items), f"腾讯地点联想没有返回 {keyword}")
    place = next((item for item in items if item.get("title") == keyword), items[0])
    _require(bool(place.get("provider_poi_id")), f"{keyword} 缺少腾讯 POI ID")
    _require(bool(place.get("category_code")), f"{keyword} 缺少腾讯分类编码")
    _require(place.get("gcj_lat") is not None and place.get("gcj_lon") is not None, f"{keyword} 缺少 GCJ 坐标")
    return place


def _endpoint_context(place: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "provider_poi_id",
        "title",
        "address",
        "category",
        "category_code",
        "type",
        "adcode",
        "province",
        "city",
        "district",
        "gcj_lat",
        "gcj_lon",
    )
    return {field: place.get(field) for field in fields if place.get(field) is not None}


def _routing_metadata(version, db, *, expected_source: str) -> tuple[dict[str, Any], int]:
    metadata = json.loads(version.navigation_metadata_json or "{}")
    routing = metadata.get("routing")
    _require(isinstance(routing, dict), "RouteVersion 缺少 routing metadata")
    _require(routing.get("source") == expected_source, "routing source 不匹配")
    _require(routing.get("route_line_hash") == version.line_hash, "routing 没有绑定当前 line_hash")
    _require(isinstance(metadata.get("elevation"), dict), "海拔写回覆盖了 routing metadata")

    point_count = db.execute(
        text("SELECT ST_NPoints(reference_line_snapshot) FROM route_versions WHERE id = :version_id"),
        {"version_id": version.id},
    ).scalar_one()
    _require(point_count == version.point_count, "PostGIS 点数与 RouteVersion.point_count 不一致")

    segments = routing.get("segments") or []
    steps = routing.get("steps") or []
    _require(bool(segments), "routing segments 为空")
    _require(bool(steps), "腾讯真实响应没有保留下 steps")
    previous_start = -1.0
    for step in steps:
        start_index = step.get("route_point_start")
        end_index = step.get("route_point_end")
        start_m = float(step.get("chainage_start_m"))
        end_m = float(step.get("chainage_end_m"))
        _require(isinstance(start_index, int) and isinstance(end_index, int), "step 点位索引不是整数")
        _require(0 <= start_index <= end_index < point_count, "step 点位索引越界")
        _require(0 <= start_m <= end_m <= float(routing["route_distance_m"]) + 0.01, "step chainage 越界")
        _require(start_m >= previous_start, "step chainage 顺序倒退")
        previous_start = start_m

    grid = json.loads(version.elevation_grid_snapshot or "{}")
    _require(grid.get("line_hash") == version.line_hash, "海拔网格没有绑定当前 line_hash")
    return routing, int(point_count)


def _postgis_reference_line(db, version_id: int) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            SELECT
                ST_AsGeoJSON(reference_line_snapshot, 9, 0) AS reference_line_geojson,
                line_hash,
                point_count,
                distance
            FROM route_versions
            WHERE id = :version_id
            """
        ),
        {"version_id": version_id},
    ).mappings().one()
    try:
        geojson = json.loads(row["reference_line_geojson"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise VerificationError("PostGIS reference_line 无法读取为 GeoJSON") from exc
    _require(isinstance(geojson, dict) and geojson.get("type") == "LineString", "PostGIS reference_line 不是 LineString")
    raw_coordinates = geojson.get("coordinates")
    _require(isinstance(raw_coordinates, list) and len(raw_coordinates) >= 2, "PostGIS reference_line 坐标不足")
    coordinates = []
    for index, point in enumerate(raw_coordinates):
        _require(isinstance(point, list) and len(point) >= 2, f"PostGIS reference_line 第 {index + 1} 点格式异常")
        lon = _fixture_number(point[0], f"reference_line[{index}].lon")
        lat = _fixture_number(point[1], f"reference_line[{index}].lat")
        _require(-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0, "PostGIS reference_line 坐标越界")
        coordinates.append([lon, lat])
    _require(len(coordinates) == int(row["point_count"]), "PostGIS GeoJSON 点数与 point_count 不一致")
    return {
        "coordinates": coordinates,
        "coordinate_sha256": hashlib.sha256(_canonical_json_bytes(coordinates)).hexdigest(),
        "line_hash": row["line_hash"],
        "point_count": int(row["point_count"]),
        "distance_m": round(float(row["distance"]), 3),
    }


def _require_saved_route_integrity(
    routing: dict[str, Any],
    *,
    expected_part_count: int,
    line_hash: str,
) -> list[dict[str, Any]]:
    segments = routing.get("segments") or []
    _require(isinstance(segments, list) and len(segments) == expected_part_count, "fixture RouteVersion segment 数量与 parts 不一致")
    _require(routing.get("provider_segment_count") == expected_part_count, "fixture provider_segment_count 漂移")
    _require(routing.get("coverage_complete") is True, "fixture RouteVersion routing coverage 不完整")
    _require(routing.get("geometry_exact") is True, "fixture RouteVersion 存在未验证几何连接")
    _require(isinstance(line_hash, str) and _SHA256_RE.fullmatch(line_hash) is not None, "fixture RouteVersion line_hash 格式异常")
    _require(routing.get("route_line_hash") == line_hash, "fixture routing route_line_hash 没有绑定最终版本")
    return segments


def _run_saved_route_fixture(
    *,
    fixture: dict[str, Any],
    client: httpx.Client,
    headers: dict[str, str],
    db,
    redis_conn,
    current_user_id: int,
    route_version_model,
    receipt_key_prefix: str,
) -> dict[str, Any]:
    """把冻结的多个 source-profile 分段逐段贴路，再一次性保存成一条 RouteVersion。"""

    receipts: list[str] = []
    preview_summaries: list[dict[str, Any]] = []
    for part_index, part in enumerate(fixture["parts"]):
        points = part["points_gcj02"]
        preview_body = _http_json(
            client.post(
                "/api/route-books/manual-drawn/snap-preview",
                json={"coordinate_system": "gcj02", "mode": "snap", "points": points},
                headers=headers,
            ),
            f"fixture 第 {part_index + 1} 段贴路预览",
        )
        _require(preview_body.get("coordinate_system") == "gcj02", f"fixture 第 {part_index + 1} 段坐标系漂移")
        _require(preview_body.get("mode") == "snap", f"fixture 第 {part_index + 1} 段没有走 snap")
        returned_anchors = preview_body.get("anchor_points")
        retention = _anchor_retention_summary(part, returned_anchors, part_index=part_index)
        retained_anchor_count = retention["retained_anchor_count"]
        _require(
            preview_body.get("segment_count") == retained_anchor_count - 1,
            f"fixture 第 {part_index + 1} 段 segment_count 与生产保留锚点不一致",
        )
        receipt = preview_body.get("routing_receipt")
        _require(isinstance(receipt, str) and len(receipt.encode("utf-8")) <= 512, f"fixture 第 {part_index + 1} 段 receipt 不是短 token")
        receipt_parts = receipt.split(".")
        _require(len(receipt_parts) == 3, f"fixture 第 {part_index + 1} 段 receipt 格式异常")
        receipt_raw = redis_conn.get(f"{receipt_key_prefix}{receipt_parts[1]}")
        _require(receipt_raw is not None, f"fixture 第 {part_index + 1} 段没有写入 Redis")
        try:
            receipt_payload = json.loads(receipt_raw)
        except (TypeError, ValueError) as exc:
            raise VerificationError(f"fixture 第 {part_index + 1} 段 Redis evidence 损坏") from exc
        _require(receipt_payload.get("current_user_id") == current_user_id, f"fixture 第 {part_index + 1} 段 Redis ownership 错误")
        evidence = receipt_payload.get("evidence")
        _require(isinstance(evidence, dict), f"fixture 第 {part_index + 1} 段 Redis evidence 缺失")
        _require(evidence.get("geometry_point_count") == len(preview_body.get("snapped_points") or []), f"fixture 第 {part_index + 1} 段几何点数漂移")
        _require(
            len(evidence.get("provider_calls") or []) == retained_anchor_count - 1,
            f"fixture 第 {part_index + 1} 段 provider call 边界丢失",
        )
        _require(bool(evidence.get("steps")), f"fixture 第 {part_index + 1} 段腾讯 steps 为空")
        receipts.append(receipt)
        preview_summaries.append(
            {
                "part_index": part_index,
                **retention,
                "provider_call_count": len(evidence.get("provider_calls") or []),
                "snapped_point_count": int(evidence["geometry_point_count"]),
                "step_count": len(evidence.get("steps") or []),
                "distance_m": round(float(preview_body["distance_m"]), 3),
            }
        )
    _require(len(receipts) >= 3, "fixture 必须产生至少三个独立 snap 凭据")

    save_payload = {
        "name": f"腾讯 RouteVersion 证据 {fixture['sample_id']}",
        "client_request_id": f"tencent-fixture-{uuid.uuid4().hex}",
        "coordinate_system": "gcj02",
        # route_parts 存在时服务端只信 Redis 中的腾讯原线；这里仅满足稳定请求 schema。
        "points": [fixture["parts"][0]["points_gcj02"][0], fixture["parts"][-1]["points_gcj02"][-1]],
        "draw_metadata": {
            "tool": "tencent_saved_routeversion_e2e_v1",
            "snap_provider": "tencent_bicycling",
            "segment_count": len(receipts),
            "freehand_segment_count": 0,
        },
        "route_parts": [
            {"mode": "snap", "routing_receipt": receipt, "points": []}
            for receipt in receipts
        ],
    }
    saved_body = _http_json(
        client.post("/api/route-books/manual-drawn", json=save_payload, headers=headers),
        "fixture 多段正式保存",
    )
    reread_body = _http_json(
        client.get(f"/api/route-books/{saved_body['id']}", headers=headers),
        "fixture 正式路线 HTTP 重读",
    )
    _require(reread_body["id"] == saved_body["id"], "fixture HTTP 重读返回错误路线")
    _require(reread_body["current_version_id"] == saved_body["current_version_id"], "fixture HTTP 重读版本漂移")
    _require(reread_body["preview_points"] == saved_body["preview_points"], "fixture HTTP 重读预览几何漂移")

    db.expire_all()
    version = db.query(route_version_model).filter(route_version_model.id == saved_body["current_version_id"]).one()
    routing, point_count = _routing_metadata(version, db, expected_source="manual_draw_snap_receipts")
    segments = _require_saved_route_integrity(
        routing,
        expected_part_count=len(fixture["parts"]),
        line_hash=version.line_hash,
    )
    for segment_index, segment in enumerate(segments):
        _require(segment.get("draw_segment_index") == segment_index, "fixture segment 顺序漂移")
        _require(bool(segment.get("steps")), f"fixture 第 {segment_index + 1} 个正式 segment 丢失 steps")
    reference_line = _postgis_reference_line(db, version.id)
    _require(reference_line["line_hash"] == version.line_hash, "PostGIS 重读 line_hash 漂移")
    _require(reference_line["point_count"] == point_count, "PostGIS 重读 point_count 漂移")
    _require(_sha256_file(ROOT / fixture["source_profile_csv"]) == fixture["source_profile_sha256"], "live 运行期间 source profile CSV 发生变化")

    safe_routing = _safe_routing_artifact(routing)
    artifact = {
        "schema": ROUTE_ARTIFACT_SCHEMA,
        "sample_id": fixture["sample_id"],
        "purpose": fixture["purpose"],
        "source_profile_csv": fixture["source_profile_csv"],
        "source_profile_sha256": fixture["source_profile_sha256"],
        "target_start_m": fixture["target_start_m"],
        "target_end_m": fixture["target_end_m"],
        "coordinate_system": fixture["coordinate_system"],
        "anchor_policy": fixture["anchor_policy"],
        "hard_boundaries": fixture["hard_boundaries"],
        "fixture_sha256": hashlib.sha256(_canonical_json_bytes(fixture)).hexdigest(),
        "snap_parts": preview_summaries,
        "saved_routeversion": {
            "coordinate_system": "wgs84",
            "reference_line_coordinates": reference_line["coordinates"],
            "coordinate_sha256": reference_line["coordinate_sha256"],
            "line_hash": reference_line["line_hash"],
            "point_count": reference_line["point_count"],
            "distance_m": reference_line["distance_m"],
            "routing": safe_routing,
        },
        "integrity": {
            "source_profile_sha_verified": True,
            "snap_preview_count": len(receipts),
            "formal_snap_part_count": len(segments),
            "http_get_round_trip": True,
            "http_version_stable": True,
            "http_preview_geometry_stable": True,
            "postgis_reference_line_reread": True,
            "postgis_point_count_matches": reference_line["point_count"] == point_count,
            "route_line_hash_bound": routing.get("route_line_hash") == reference_line["line_hash"],
            "step_chainage_validated": True,
            "routing_coverage_complete": True,
            "routing_geometry_exact": True,
        },
    }
    artifact = _strip_artifact_secrets(artifact)
    _assert_artifact_safe(artifact)
    return artifact


def _place(client: httpx.Client, headers: dict[str, str], keyword: str) -> dict[str, Any]:
    body = _http_json(
        client.get(
            "/api/meetups/place-suggestions",
            params={"keyword": keyword, "region": "太原"},
            headers=headers,
        ),
        f"地点联想 {keyword}",
    )
    _require(isinstance(body, list), f"地点联想 {keyword} 响应不是数组")
    return _pick_place(body, keyword)


def run(route_fixture: dict[str, Any] | None = None) -> dict[str, Any]:
    database_url = os.environ.get("DATABASE_URL", "")
    redis_url = os.environ.get("REDIS_URL", "")
    _guard_isolated_services(database_url, redis_url)
    port = _e2e_port()
    _require_free_port(port)

    # 配置必须在下面这些 app import 之前由调用方注入。父进程不导入 app.main，
    # 防止本轮再次退化成 ASGI 进程内调用。
    from app.config import settings
    from app.queue import redis_conn
    from app.route_book.models import RouteBook, RouteBookSaveRequest, RouteVersion
    from app.route_book.routing_evidence import RECEIPT_KEY_PREFIX
    from app.user.models import User
    from app.user.service import create_token

    _require(bool(settings.TENCENT_MAP_KEY and settings.TENCENT_MAP_SK), "腾讯 KEY/SK 未配置")
    redis_owner: str | None = None
    engine = None
    db = None
    user_id: int | None = None
    server_process: subprocess.Popen[bytes] | None = None
    server_log = None

    try:
        redis_conn.ping()
        redis_owner = _claim_redis_db(redis_conn)
        engine = create_engine(database_url, pool_pre_ping=True)
        Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        db = Session()
        server_log = tempfile.TemporaryFile(mode="w+b")

        user = User(
            openid=f"tencent_e2e_{uuid.uuid4().hex}",
            nickname="Tencent evidence E2E",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        user_id = user.id
        headers = {"Authorization": f"Bearer {create_token(user_id)}"}

        server_process = _start_server(port, server_log)
        base_url = f"http://127.0.0.1:{port}"
        _wait_for_server(server_process, base_url)
        with httpx.Client(
            base_url=base_url,
            timeout=httpx.Timeout(45.0, connect=5.0),
            trust_env=False,
        ) as client:
            jin_ci = _place(client, headers, "晋祠博物馆")
            tian_long_shan = _place(client, headers, "天龙山景区")
            tai_shan = _place(client, headers, "太山景区")

            direct_payload = {
                "name": "腾讯 POI 直连 E2E",
                "coordinate_system": "gcj02",
                "from_lat": jin_ci["gcj_lat"],
                "from_lon": jin_ci["gcj_lon"],
                "to_lat": tai_shan["gcj_lat"],
                "to_lon": tai_shan["gcj_lon"],
                "from_poi": jin_ci["provider_poi_id"],
                "to_poi": tai_shan["provider_poi_id"],
                "from_poi_context": _endpoint_context(jin_ci),
                "to_poi_context": _endpoint_context(tai_shan),
            }
            direct_body = _http_json(
                client.post("/api/route-books/tencent-direction", json=direct_payload, headers=headers),
                "腾讯 POI 直连保存",
            )

            direct_version = db.query(RouteVersion).filter(RouteVersion.id == direct_body["current_version_id"]).one()
            direct_routing, direct_point_count = _routing_metadata(
                direct_version,
                db,
                expected_source="tencent_direction",
            )
            direct_segment = direct_routing["segments"][0]
            _require(direct_segment.get("from_poi") == jin_ci["provider_poi_id"], "起点 POI ID 入库丢失")
            _require(direct_segment.get("to_poi") == tai_shan["provider_poi_id"], "终点 POI ID 入库丢失")
            _require(direct_segment["from_poi_context"]["verified"] is False, "客户端 POI 上下文被误标为已验证")
            _require(direct_segment["to_poi_context"]["verified"] is False, "客户端 POI 上下文被误标为已验证")

            raw_points = [
                [jin_ci["gcj_lon"], jin_ci["gcj_lat"]],
                [tian_long_shan["gcj_lon"], tian_long_shan["gcj_lat"]],
                [tai_shan["gcj_lon"], tai_shan["gcj_lat"]],
            ]
            preview_body = _http_json(
                client.post(
                    "/api/route-books/manual-drawn/snap-preview",
                    json={"coordinate_system": "gcj02", "mode": "snap", "points": raw_points},
                    headers=headers,
                ),
                "多锚点贴路预览",
            )
            _require(preview_body["segment_count"] == 2, "三锚点没有形成两个腾讯子请求")
            _require(len(preview_body["snapped_points"]) > len(raw_points), "腾讯原始路线几何没有展开")
            receipt = preview_body.get("routing_receipt")
            _require(isinstance(receipt, str) and len(receipt.encode("utf-8")) <= 512, "receipt 不是短 token")
            receipt_id = receipt.split(".")[1]
            receipt_key = f"{RECEIPT_KEY_PREFIX}{receipt_id}"
            receipt_raw = redis_conn.get(receipt_key)
            _require(receipt_raw is not None, "真实 Redis 没有保存 receipt")
            receipt_ttl = redis_conn.ttl(receipt_key)
            _require(0 < receipt_ttl <= 24 * 60 * 60, "receipt TTL 不在 24 小时窗口")
            receipt_payload = json.loads(receipt_raw)
            evidence = receipt_payload["evidence"]
            _require(receipt_payload.get("current_user_id") == user_id, "receipt 没有绑定用户")
            _require(evidence.get("geometry_point_count") == len(preview_body["snapped_points"]), "Redis 几何点数与预览不一致")
            _require(len(evidence.get("provider_calls") or []) == 2, "两个腾讯子请求没有逐个留证")
            _require(bool(evidence.get("steps")), "Redis receipt 没有保存腾讯 steps")

            # 客户端故意提交一条完全不相干的假线；正式路线必须只取 receipt 中的腾讯原线。
            save_payload = {
                "name": "腾讯多锚点 receipt E2E",
                "client_request_id": f"tencent-e2e-{uuid.uuid4().hex}",
                "coordinate_system": "gcj02",
                "points": [[80.0, 20.0], [81.0, 21.0]],
                "draw_metadata": {
                    "tool": "route_draw_v0_e2e",
                    "snap_provider": "tencent_bicycling",
                    "segment_count": 1,
                    "freehand_segment_count": 0,
                },
                "route_parts": [{"mode": "snap", "routing_receipt": receipt, "points": []}],
            }
            saved_body = _http_json(
                client.post("/api/route-books/manual-drawn", json=save_payload, headers=headers),
                "receipt 正式保存",
            )
            reread_body = _http_json(
                client.get(f"/api/route-books/{saved_body['id']}", headers=headers),
                "正式路线 HTTP 重读",
            )
            _require(reread_body["id"] == saved_body["id"], "HTTP 重读返回了错误路线")
            _require(reread_body["current_version_id"] == saved_body["current_version_id"], "HTTP 重读版本漂移")
            _require(reread_body["preview_points"] == saved_body["preview_points"], "HTTP 重读路线几何漂移")
            manual_version = db.query(RouteVersion).filter(RouteVersion.id == saved_body["current_version_id"]).one()
            manual_routing, manual_point_count = _routing_metadata(
                manual_version,
                db,
                expected_source="manual_draw_snap_receipts",
            )
            manual_segment = manual_routing["segments"][0]
            _require(len(manual_segment.get("provider_calls") or []) == 2, "正式版本丢失腾讯子请求边界")
            _require(manual_point_count == evidence["geometry_point_count"], "正式版本没有采用 receipt 原始几何")
            start_lon = db.execute(
                text("SELECT ST_X(ST_StartPoint(reference_line_snapshot)) FROM route_versions WHERE id = :version_id"),
                {"version_id": manual_version.id},
            ).scalar_one()
            _require(start_lon > 110.0, "正式版本错误采用了客户端伪造点串")

            join_gaps = manual_segment.get("unverified_join_gaps") or []
            if join_gaps:
                _require(manual_routing.get("geometry_exact") is False, "未验证连接缺口被误标为精确几何")
                _require(manual_routing.get("coverage_complete") is False, "未验证连接缺口被误标为完整覆盖")
            else:
                _require(manual_routing.get("geometry_exact") is True, "无连接缺口却没有标记精确几何")
                _require(manual_routing.get("coverage_complete") is True, "无连接缺口却没有完整覆盖")

            redis_conn.delete(receipt_key)
            replay_body = _http_json(
                client.post("/api/route-books/manual-drawn", json=save_payload, headers=headers),
                "receipt 丢失后的已保存请求重放",
            )
            _require(replay_body["id"] == saved_body["id"], "幂等重放创建了第二条路线")

            expired_payload = dict(save_payload)
            expired_payload["client_request_id"] = f"tencent-e2e-expired-{uuid.uuid4().hex}"
            expired_response = client.post(
                "/api/route-books/manual-drawn",
                json=expired_payload,
                headers=headers,
            )
            expired_body = _http_json(expired_response, "receipt 丢失后的新保存", expected_status=422)
            _require(expired_body.get("detail", {}).get("code") == "routing_receipt_invalid", "receipt 失效没有结构化错误码")

            _require(db.query(RouteBook).filter(RouteBook.creator_id == user_id).count() == 2, "端到端流程产生了多余路线")
            _require(db.query(RouteBookSaveRequest).filter(RouteBookSaveRequest.creator_id == user_id).count() == 1, "失败保存污染了幂等表")
            version_count = (
                db.query(func.count(RouteVersion.id))
                .join(RouteBook, RouteVersion.route_book_id == RouteBook.id)
                .filter(RouteBook.creator_id == user_id)
                .scalar()
            )
            _require(version_count == 2, "端到端流程产生了多余 RouteVersion")

            saved_routeversion_artifact = None
            if route_fixture is not None:
                saved_routeversion_artifact = _run_saved_route_fixture(
                    fixture=route_fixture,
                    client=client,
                    headers=headers,
                    db=db,
                    redis_conn=redis_conn,
                    current_user_id=user_id,
                    route_version_model=RouteVersion,
                    receipt_key_prefix=RECEIPT_KEY_PREFIX,
                )
                _assert_artifact_safe(
                    saved_routeversion_artifact,
                    protected_markers=[settings.TENCENT_MAP_KEY, settings.TENCENT_MAP_SK],
                )
                _require(db.query(RouteBook).filter(RouteBook.creator_id == user_id).count() == 3, "fixture 流程没有且只创建一条额外路线")
                _require(db.query(RouteBookSaveRequest).filter(RouteBookSaveRequest.creator_id == user_id).count() == 2, "fixture 流程没有且只创建一条额外幂等记录")
                fixture_version_count = (
                    db.query(func.count(RouteVersion.id))
                    .join(RouteBook, RouteVersion.route_book_id == RouteBook.id)
                    .filter(RouteBook.creator_id == user_id)
                    .scalar()
                )
                _require(fixture_version_count == 3, "fixture 流程没有且只创建一条额外 RouteVersion")

            result = {
                "status": "pass",
                "scope": "tencent_place_direction_receipt_tcp_http_postgis",
                "elevation_query": "stubbed_constant_for_isolation",
                "transport": "independent_uvicorn_tcp_http",
                "places": 3,
                "direct_route": {
                    "distance_m": round(float(direct_body["distance"]), 3),
                    "point_count": direct_point_count,
                    "step_count": len(direct_routing["steps"]),
                    "line_hash_bound": True,
                    "poi_identity_bound": True,
                },
                "multi_anchor_route": {
                    "provider_call_count": 2,
                    "distance_m": round(float(saved_body["distance"]), 3),
                    "point_count": manual_point_count,
                    "step_count": len(manual_routing["steps"]),
                    "receipt_payload_bytes": len(receipt_raw),
                    "receipt_ttl_sec": receipt_ttl,
                    "coverage_complete": manual_routing["coverage_complete"],
                    "geometry_exact": manual_routing["geometry_exact"],
                    "unverified_join_gap_count": len(join_gaps),
                    "line_hash_bound": True,
                },
                "failure_recovery": {
                    "saved_replay_idempotent": True,
                    "unsaved_missing_receipt_http": 422,
                    "unsaved_missing_receipt_code": "routing_receipt_invalid",
                },
                "persistence_reread": {
                    "http_get_round_trip": True,
                    "version_stable": True,
                    "preview_geometry_stable": True,
                },
                "security": {
                    "server_log_credentials_absent": True,
                    "redis_cleanup_uses_ownership": True,
                },
            }
            if saved_routeversion_artifact is not None:
                result["_saved_routeversion_artifact"] = saved_routeversion_artifact
            return result
    finally:
        _stop_server(server_process)
        cleanup_error: Exception | None = None
        if server_log is not None:
            try:
                _assert_server_log_safe(
                    server_log,
                    [settings.TENCENT_MAP_KEY, settings.TENCENT_MAP_SK],
                )
            except Exception as exc:
                cleanup_error = exc
            server_log.close()
        if db is not None:
            db.close()
        if engine is not None:
            engine.dispose()
        if redis_owner is not None:
            try:
                _release_redis_db(redis_conn, redis_owner, user_id)
            except Exception as exc:
                if cleanup_error is None:
                    cleanup_error = exc
        if cleanup_error is not None:
            raise cleanup_error


def serve() -> int:
    """只供父验收进程启动的隔离 API 子进程入口。"""

    database_url = os.environ.get("DATABASE_URL", "")
    redis_url = os.environ.get("REDIS_URL", "")
    _guard_isolated_services(database_url, redis_url)
    port = _e2e_port()

    from app.main import app
    from app.route_book import service
    import uvicorn

    # 本轮只验腾讯证据链；常数值仍会走海拔工厂和 metadata 合并，但不访问 DEM。
    service.query_elevations = lambda coordinates: [700.0 for _coordinate in coordinates]
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="验收真实腾讯路线证据链")
    parser.add_argument("--route-fixture", type=Path, help="冻结的多段 GCJ02 route fixture JSON")
    parser.add_argument("--artifact-out", type=Path, help="只创建、不覆盖的脱敏 RouteVersion artifact")
    args = parser.parse_args(argv)
    if (args.route_fixture is None) != (args.artifact_out is None):
        parser.error("--route-fixture 与 --artifact-out 必须同时提供")
    return args


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parse_args(argv)
        route_fixture = None
        if args.route_fixture is not None:
            if args.artifact_out.exists():
                raise VerificationError("artifact 已存在，拒绝覆盖")
            route_fixture = _load_route_fixture(args.route_fixture)
        result = run() if route_fixture is None else run(route_fixture)
        artifact = result.pop("_saved_routeversion_artifact", None)
        if args.artifact_out is not None:
            _require(isinstance(artifact, dict), "live run 没有生成 saved RouteVersion artifact")
            _atomic_write_json_new(args.artifact_out, artifact)
            result["saved_routeversion_artifact"] = {
                "schema": ROUTE_ARTIFACT_SCHEMA,
                "written": True,
            }
        else:
            _require(artifact is None, "默认验收意外生成 artifact")
    except Exception as exc:
        result = {
            "status": "fail",
            "error_type": exc.__class__.__name__,
            "reason": str(exc),
        }
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return 1
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(serve() if "--serve" in sys.argv[1:] else main())
