"""把人工复核通过的路段 bundle 原子发布为正式 Segment。

这个入口只消费 ``ingest-velo-road-segments`` 产出的 schema v1 verified bundle。
腾讯算路、GLO-30 海拔和地图人工复核都必须在发布前完成；发布过程不再访问外部服务，
只校验不可变证据并在一个数据库事务里写入 Segment、来源、人工判断和路线认知白名单。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import re
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlparse

from geoalchemy2 import WKTElement
import numpy as np
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.elevation.route_elevation import (
    ROUTE_ELEVATION_METHOD,
    _meaningful_ascent,
    route_elevation_metadata,
)
from app.route_cognition.geometry_hash import (
    SEGMENT_GEOMETRY_NORMALIZATION_VERSION,
    hash_segment_geometry_wkt,
)
from app.route_cognition.models import JudgmentRun, SegmentGeometrySource
from app.route_cognition.services.segment_eligibility import (
    SegmentGeometrySourceInput,
    admit_provenance_verified_segment,
)
from app.segment._geo_utils import _haversine, _sample_elevation_profile
from app.segment.algorithms import calculate_difficulty, calculate_max_gradient
from app.segment.exceptions import SegmentOverlapError
from app.segment.models import Segment
from app.user.cities import ALL_CITY_CODES_WITH_UNKNOWN
from app.user.models import User


PUBLICATION_CONTRACT_VERSION = "verified_segment_bundle_v1"
SOURCE_FILE_PREFIX = f"{PUBLICATION_CONTRACT_VERSION}:"
HAUSDORFF_OVERLAP_THRESHOLD_DEG = 0.0005
REVERSE_ENDPOINT_TOLERANCE_M = 100.0
REVERSE_DIRECTION_MARGIN_M = 25.0


class VerifiedSegmentBundleError(ValueError):
    """bundle 不是可发布的、未被篡改的人工复核结果。"""


@dataclass(frozen=True)
class ValidatedVerifiedSegmentBundle:
    candidate_id: str
    bundle_hash: str
    source_file_id: str
    name: str
    city: str
    direction: str
    source_url: str
    observed_at: datetime
    reviewed_at: datetime
    reviewer_name: str
    review_note: str
    geometry_wkt: str
    geometry_hash: str
    points: list[list[float]]
    elevation_snapshot: list[list[float]]
    elevation_profile: list[list[float]]
    distance_m: float
    elevation_gain_m: float
    elevation_loss_m: float
    average_gradient_pct: float
    maximum_gradient_pct: float
    bundle: dict[str, Any]


@dataclass(frozen=True)
class SegmentPublicationResult:
    status: str
    candidate_id: str
    segment_id: int
    geometry_hash: str
    source_file_id: str


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise VerifiedSegmentBundleError(f"{label} 必须是对象")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VerifiedSegmentBundleError(f"{label} 不能为空")
    return value.strip()


def _finite(value: object, label: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool):
        raise VerifiedSegmentBundleError(f"{label} 必须是数字")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise VerifiedSegmentBundleError(f"{label} 必须是数字") from exc
    if not math.isfinite(number) or (minimum is not None and number < minimum):
        raise VerifiedSegmentBundleError(f"{label} 数值无效")
    return number


def _timestamp(value: object, label: str) -> datetime:
    raw = _text(value, label)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise VerifiedSegmentBundleError(f"{label} 必须是 ISO-8601 时间") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise VerifiedSegmentBundleError(f"{label} 必须带时区")
    return parsed.astimezone(timezone.utc)


def _canonical_json_hash(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _canonical_wkt(points: list[list[float]]) -> str:
    return "LINESTRING(" + ",".join(
        f"{point[0]:.8f} {point[1]:.8f}" for point in points
    ) + ")"


def _validated_points(value: object, label: str, *, dimensions: int) -> list[list[float]]:
    if not isinstance(value, list) or len(value) < 3:
        raise VerifiedSegmentBundleError(f"{label} 至少需要 3 个点")
    result: list[list[float]] = []
    for index, raw in enumerate(value):
        if not isinstance(raw, list) or len(raw) < dimensions:
            raise VerifiedSegmentBundleError(f"{label}[{index}] 格式错误")
        lon = _finite(raw[0], f"{label}[{index}][0]")
        lat = _finite(raw[1], f"{label}[{index}][1]")
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise VerifiedSegmentBundleError(f"{label}[{index}] 坐标越界")
        point = [lon, lat]
        if dimensions == 3:
            point.append(_finite(raw[2], f"{label}[{index}][2]"))
        result.append(point)
    return result


def _validate_strava_segment_url(value: object) -> str:
    source_url = _text(value, "popularity_observation.source_url")
    parsed = urlparse(source_url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not (
        host == "strava.com" or host.endswith(".strava.com")
    ):
        raise VerifiedSegmentBundleError("source_url 必须是 Strava 页面")
    if re.search(r"/segments/\d+(?:/|$)", parsed.path) is None or "/api/" in parsed.path:
        raise VerifiedSegmentBundleError("source_url 必须是具体 Strava 赛段页面而非 API")
    return source_url


def validate_verified_segment_bundle(bundle: object) -> ValidatedVerifiedSegmentBundle:
    """纯校验：不访问数据库，也不调用腾讯或 DEM。"""
    root = _mapping(bundle, "bundle")
    if root.get("schema_version") != 1:
        raise VerifiedSegmentBundleError("只支持 schema_version=1")
    if root.get("status") != "verified" or root.get("publication_eligible") is not True:
        raise VerifiedSegmentBundleError("bundle 必须是 publication_eligible 的 verified 结果")

    segment = _mapping(root.get("segment"), "segment")
    name = _text(segment.get("name"), "segment.name")
    city = _text(segment.get("city"), "segment.city")
    if city not in set(ALL_CITY_CODES_WITH_UNKNOWN):
        raise VerifiedSegmentBundleError("segment.city 不在当前城市枚举")
    direction = _text(segment.get("direction"), "segment.direction")

    provenance = _mapping(root.get("provenance"), "provenance")
    input_sha256 = _text(provenance.get("input_sha256"), "provenance.input_sha256")
    if re.fullmatch(r"[0-9a-f]{64}", input_sha256) is None:
        raise VerifiedSegmentBundleError("provenance.input_sha256 格式错误")
    candidate_id = _text(root.get("candidate_id"), "candidate_id")
    expected_candidate_id = hashlib.sha256(
        f"{name}:{input_sha256}".encode("utf-8")
    ).hexdigest()[:24]
    if candidate_id != expected_candidate_id:
        raise VerifiedSegmentBundleError("candidate_id 与 name/input_sha256 不一致")
    if provenance.get("strava_api_used") is not False:
        raise VerifiedSegmentBundleError("bundle 必须明确未调用 Strava API")

    hard = _mapping(root.get("hard_knowledge"), "hard_knowledge")
    geometry = _mapping(hard.get("geometry"), "hard_knowledge.geometry")
    if geometry.get("source") != "tencent_directions":
        raise VerifiedSegmentBundleError("geometry.source 必须是 tencent_directions")
    if geometry.get("routing_profile") not in {"bicycling", "driving"}:
        raise VerifiedSegmentBundleError("geometry.routing_profile 无效")
    if geometry.get("coordinate_system") != "wgs84":
        raise VerifiedSegmentBundleError("geometry 必须是 WGS-84")
    if geometry.get("normalization_version") != SEGMENT_GEOMETRY_NORMALIZATION_VERSION:
        raise VerifiedSegmentBundleError("geometry normalization_version 已漂移")

    points = _validated_points(
        geometry.get("points"), "hard_knowledge.geometry.points", dimensions=2
    )
    if geometry.get("point_count") != len(points):
        raise VerifiedSegmentBundleError("geometry.point_count 与 points 不一致")
    geometry_wkt = _canonical_wkt(points)
    if geometry.get("wkt") != geometry_wkt:
        raise VerifiedSegmentBundleError("geometry.wkt 不是当前规范形式")
    geometry_hash = _text(geometry.get("geometry_hash"), "geometry.geometry_hash")
    if hash_segment_geometry_wkt(geometry_wkt) != geometry_hash:
        raise VerifiedSegmentBundleError("geometry_hash 与 WKT 不一致")

    elevation = _mapping(hard.get("elevation"), "hard_knowledge.elevation")
    if elevation.get("method") != ROUTE_ELEVATION_METHOD:
        raise VerifiedSegmentBundleError("elevation.method 与当前生产算法不一致")
    if elevation.get("metadata") != route_elevation_metadata():
        raise VerifiedSegmentBundleError("elevation.metadata 与当前生产算法不一致")
    snapshot = _validated_points(
        elevation.get("snapshot"), "hard_knowledge.elevation.snapshot", dimensions=3
    )
    if len(snapshot) != len(points) or elevation.get("point_count") != len(points):
        raise VerifiedSegmentBundleError("elevation snapshot 与 geometry 点数不一致")
    for index, (point, elevated) in enumerate(zip(points, snapshot)):
        if abs(point[0] - elevated[0]) > 1e-5 or abs(point[1] - elevated[1]) > 1e-5:
            raise VerifiedSegmentBundleError(f"elevation.snapshot[{index}] 坐标与 geometry 不一致")
    profile_raw = elevation.get("profile")
    if not isinstance(profile_raw, list) or not profile_raw:
        raise VerifiedSegmentBundleError("elevation.profile 不能为空")
    profile: list[list[float]] = []
    for index, raw in enumerate(profile_raw):
        if not isinstance(raw, list) or len(raw) < 2:
            raise VerifiedSegmentBundleError(f"elevation.profile[{index}] 格式错误")
        profile.append(
            [
                _finite(raw[0], f"elevation.profile[{index}][0]", minimum=0),
                _finite(raw[1], f"elevation.profile[{index}][1]"),
            ]
        )
    profile_distances_m = np.asarray([point[0] * 1000.0 for point in profile], dtype=float)
    profile_elevations_m = np.asarray([point[1] for point in profile], dtype=float)
    if profile_distances_m[0] != 0 or np.any(np.diff(profile_distances_m) <= 0):
        raise VerifiedSegmentBundleError("elevation.profile 距离必须从 0 严格递增")

    metrics = _mapping(hard.get("metrics"), "hard_knowledge.metrics")
    distance_m = _finite(metrics.get("distance_m"), "metrics.distance_m", minimum=1)
    elevation_gain_m = _finite(
        metrics.get("elevation_gain_m"), "metrics.elevation_gain_m", minimum=0
    )
    elevation_loss_m = _finite(
        metrics.get("elevation_loss_m"), "metrics.elevation_loss_m", minimum=0
    )
    average_gradient_pct = _finite(
        metrics.get("average_gradient_pct"), "metrics.average_gradient_pct"
    )
    maximum_gradient_pct = _finite(
        metrics.get("maximum_gradient_pct"), "metrics.maximum_gradient_pct", minimum=0
    )
    measured_distance = sum(
        _haversine(left[1], left[0], right[1], right[0])
        for left, right in zip(points, points[1:])
    )
    if abs(measured_distance - distance_m) > max(0.5, measured_distance * 0.0002):
        raise VerifiedSegmentBundleError("metrics.distance_m 与 geometry 实测距离不一致")
    if abs(profile_distances_m[-1] - measured_distance) > max(1.0, measured_distance * 0.001):
        raise VerifiedSegmentBundleError("elevation.profile 末端距离与 geometry 不一致")
    if (
        abs(profile_elevations_m[0] - snapshot[0][2]) > 2.0
        or abs(profile_elevations_m[-1] - snapshot[-1][2]) > 2.0
    ):
        raise VerifiedSegmentBundleError("elevation.profile 起终点与 snapshot 不一致")
    # profile 是最多 100 点的展示降采样，snapshot 则只覆盖腾讯原始轨迹点；两者
    # 都是同一条 20m 成品剖面的投影。先确认两份证据彼此一致，再用它们约束指标。
    snapshot_distances_m = np.asarray(
        [0.0]
        + list(
            np.cumsum(
                [
                    _haversine(left[1], left[0], right[1], right[0])
                    for left, right in zip(points, points[1:])
                ]
            )
        ),
        dtype=float,
    )
    snapshot_elevations_m = np.asarray([point[2] for point in snapshot], dtype=float)
    interpolated_snapshot = np.interp(
        profile_distances_m,
        snapshot_distances_m,
        snapshot_elevations_m,
    )
    if np.any(np.abs(interpolated_snapshot - profile_elevations_m) > 12.0):
        raise VerifiedSegmentBundleError("elevation.profile 与 elevation.snapshot 不一致")
    snapshot_climb = float(_meaningful_ascent(snapshot_elevations_m, snapshot_distances_m))
    snapshot_descent = float(_meaningful_ascent(-snapshot_elevations_m, snapshot_distances_m))
    profile_climb = float(_meaningful_ascent(profile_elevations_m, profile_distances_m))
    profile_descent = float(_meaningful_ascent(-profile_elevations_m, profile_distances_m))
    # 正式指标来自未降采样的 20m 成品剖面。bundle 同时保存原腾讯轨迹点上的
    # snapshot 和最多 100 点的成品 profile；两者都可能因采样间隔遗漏小峰谷，
    # 但不会凭空产生完整网格不存在的累计起伏。取两种投影中保留较多的一种做
    # 下界核对，既能覆盖石岭关这类稀疏腾讯轨迹，也能继续拦截指标篡改。
    projected_climb = max(snapshot_climb, profile_climb)
    projected_descent = max(snapshot_descent, profile_descent)
    if abs(projected_climb - elevation_gain_m) > max(5.0, elevation_gain_m * 0.08):
        raise VerifiedSegmentBundleError("metrics.elevation_gain_m 与 elevation.snapshot 不一致")
    if abs(projected_descent - elevation_loss_m) > max(5.0, elevation_loss_m * 0.08):
        raise VerifiedSegmentBundleError("metrics.elevation_loss_m 与 elevation.snapshot 不一致")
    product_avg_gradient = (snapshot[-1][2] - snapshot[0][2]) / measured_distance * 100
    if abs(product_avg_gradient - average_gradient_pct) > 0.02:
        raise VerifiedSegmentBundleError("metrics.average_gradient_pct 与 elevation snapshot 不一致")
    product_trackpoints = [
        SimpleNamespace(latitude=lat, longitude=lon, elevation=ele)
        for lon, lat, ele in snapshot
    ]
    product_max_gradient = float(calculate_max_gradient(product_trackpoints))
    if abs(product_max_gradient - maximum_gradient_pct) > 0.02:
        raise VerifiedSegmentBundleError("metrics.maximum_gradient_pct 与当前 Segment 算法不一致")

    popularity = _mapping(root.get("popularity_observation"), "popularity_observation")
    if popularity.get("source_type") != "strava_public_page":
        raise VerifiedSegmentBundleError("popularity_observation.source_type 无效")
    source_url = _validate_strava_segment_url(popularity.get("source_url"))
    observed_at = _timestamp(popularity.get("observed_at"), "popularity_observation.observed_at")
    for field in ("athlete_count", "effort_count", "star_count"):
        value = popularity.get(field)
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
            raise VerifiedSegmentBundleError(f"popularity_observation.{field} 必须是非负整数或 null")

    gates = _mapping(root.get("quality_gates"), "quality_gates")
    required_gates = (
        "target_identity_match",
        "gpx_independent_coordinates",
        "tencent_route_generated",
        "tencent_distance_match",
        "elevation_complete",
        "endpoint_match",
        "direction_match",
        "shape_match",
        "warnings_reviewed",
    )
    if any(gates.get(gate) != "passed" for gate in required_gates):
        raise VerifiedSegmentBundleError("所有发布质量门禁必须为 passed")

    review = _mapping(root.get("review"), "review")
    if review.get("verdict") != "accept":
        raise VerifiedSegmentBundleError("review.verdict 必须是 accept")
    reviewer_name = _text(review.get("reviewer"), "review.reviewer")
    review_note = _text(review.get("note"), "review.note")
    reviewed_at = _timestamp(review.get("reviewed_at"), "review.reviewed_at")
    if review.get("reviewed_geometry_hash") != geometry_hash:
        raise VerifiedSegmentBundleError("reviewed_geometry_hash 与当前 geometry 不一致")
    for field in ("endpoint_match", "direction_match", "shape_match", "warnings_reviewed"):
        if review.get(field) != "yes":
            raise VerifiedSegmentBundleError(f"review.{field} 必须是 yes")

    bundle_hash = _canonical_json_hash(root)
    return ValidatedVerifiedSegmentBundle(
        candidate_id=candidate_id,
        bundle_hash=bundle_hash,
        source_file_id=f"{SOURCE_FILE_PREFIX}{candidate_id}",
        name=name,
        city=city,
        direction=direction,
        source_url=source_url,
        observed_at=observed_at,
        reviewed_at=reviewed_at,
        reviewer_name=reviewer_name,
        review_note=review_note,
        geometry_wkt=geometry_wkt,
        geometry_hash=geometry_hash,
        points=points,
        elevation_snapshot=snapshot,
        elevation_profile=profile,
        distance_m=measured_distance,
        elevation_gain_m=elevation_gain_m,
        elevation_loss_m=elevation_loss_m,
        average_gradient_pct=product_avg_gradient,
        maximum_gradient_pct=product_max_gradient,
        bundle=root,
    )


def _existing_publication(
    db: Session,
    validated: ValidatedVerifiedSegmentBundle,
) -> SegmentPublicationResult | None:
    source = (
        db.query(SegmentGeometrySource)
        .filter(SegmentGeometrySource.source_file_id == validated.source_file_id)
        .first()
    )
    if source is None:
        return None
    quality_metrics = source.quality_metrics_json or {}
    if (
        source.source_content_hash != validated.bundle_hash
        or quality_metrics.get("reviewed_geometry_hash") != validated.geometry_hash
    ):
        raise VerifiedSegmentBundleError("同 candidate_id 已发布，但 bundle 或 geometry hash 冲突")
    return SegmentPublicationResult(
        status="already_published",
        candidate_id=validated.candidate_id,
        segment_id=source.segment_id,
        geometry_hash=source.geometry_hash,
        source_file_id=validated.source_file_id,
    )


def _blocking_overlap_segment_id(db: Session, geometry_wkt: str) -> int | None:
    """返回同向/方向不明的重复赛段；明确反向的同路赛段允许共存。

    Hausdorff 距离不区分折线方向，所以单独用它会把“偏桥沟爬坡”和
    “偏桥沟下坡”误判成一条赛段。只有新线起点贴近旧线终点、且新线终点
    贴近旧线起点，并明显优于同向配对时，才把该重叠解释为反方向。
    环线或很短、端点无法区分方向的线仍保守阻断。
    """
    if db.bind is None or db.bind.dialect.name != "postgresql":
        return None
    overlaps = (
        db.execute(
            text(
                """
                WITH candidate AS (
                    SELECT ST_GeomFromText(:wkt, 4326) AS geom
                )
                SELECT
                    segments.id AS segment_id,
                    ST_DistanceSphere(
                        ST_StartPoint(segments.reference_line),
                        ST_StartPoint(candidate.geom)
                    ) AS same_start_m,
                    ST_DistanceSphere(
                        ST_EndPoint(segments.reference_line),
                        ST_EndPoint(candidate.geom)
                    ) AS same_end_m,
                    ST_DistanceSphere(
                        ST_StartPoint(segments.reference_line),
                        ST_EndPoint(candidate.geom)
                    ) AS reverse_start_m,
                    ST_DistanceSphere(
                        ST_EndPoint(segments.reference_line),
                        ST_StartPoint(candidate.geom)
                    ) AS reverse_end_m
                FROM segments, candidate
                WHERE ST_HausdorffDistance(
                    segments.reference_line,
                    candidate.geom
                ) < :threshold
                ORDER BY segments.id
                """
            ),
            {"wkt": geometry_wkt, "threshold": HAUSDORFF_OVERLAP_THRESHOLD_DEG},
        )
        .mappings()
        .all()
    )
    for overlap in overlaps:
        same_total = float(overlap["same_start_m"]) + float(overlap["same_end_m"])
        reverse_start = float(overlap["reverse_start_m"])
        reverse_end = float(overlap["reverse_end_m"])
        reverse_total = reverse_start + reverse_end
        is_unambiguous_reverse = (
            reverse_start <= REVERSE_ENDPOINT_TOLERANCE_M
            and reverse_end <= REVERSE_ENDPOINT_TOLERANCE_M
            and reverse_total + REVERSE_DIRECTION_MARGIN_M < same_total
        )
        if not is_unambiguous_reverse:
            return int(overlap["segment_id"])
    return None


def preflight_verified_segment_bundle(
    db: Session,
    bundle: object,
) -> SegmentPublicationResult | ValidatedVerifiedSegmentBundle:
    """只读预检；返回已发布结果或可发布的冻结对象。"""
    validated = validate_verified_segment_bundle(bundle)
    existing = _existing_publication(db, validated)
    if existing is not None:
        return existing
    overlap_id = _blocking_overlap_segment_id(db, validated.geometry_wkt)
    if overlap_id is not None:
        raise SegmentOverlapError(f"verified bundle 与已有赛段 id={overlap_id} 同向高度重叠")
    return validated


def publish_verified_segment_bundle(
    db: Session,
    *,
    bundle: object,
    reviewer_user_id: int,
) -> SegmentPublicationResult:
    """在调用方事务中发布一条 bundle；本函数不 commit。"""
    validated = validate_verified_segment_bundle(bundle)
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": validated.source_file_id},
        )
    existing = _existing_publication(db, validated)
    if existing is not None:
        return existing

    reviewer = db.query(User).filter(User.id == reviewer_user_id).first()
    if reviewer is None or reviewer.is_admin is not True:
        raise VerifiedSegmentBundleError("reviewer_user_id 必须对应当前管理员")
    overlap_id = _blocking_overlap_segment_id(db, validated.geometry_wkt)
    if overlap_id is not None:
        raise SegmentOverlapError(f"verified bundle 与已有赛段 id={overlap_id} 同向高度重叠")

    elevation_profile = _sample_elevation_profile(
        [{"ele": point[1]} for point in validated.elevation_profile],
        target_count=80,
    )
    difficulty = calculate_difficulty(
        validated.distance_m,
        validated.elevation_gain_m,
        validated.maximum_gradient_pct,
    )
    segment = Segment(
        name=validated.name,
        description=f"方向：{validated.direction}",
        distance=validated.distance_m,
        elevation_gain=validated.elevation_gain_m,
        elevation_loss=validated.elevation_loss_m,
        avg_gradient=round(validated.average_gradient_pct, 1),
        elevation_profile=json.dumps(elevation_profile, ensure_ascii=False),
        start_lat=validated.points[0][1],
        start_lon=validated.points[0][0],
        end_lat=validated.points[-1][1],
        end_lon=validated.points[-1][0],
        reference_line=WKTElement(validated.geometry_wkt, srid=4326),
        match_tolerance=50.0,
        min_match_ratio=0.8,
        difficulty=difficulty,
        max_gradient=validated.maximum_gradient_pct,
        city=validated.city,
    )
    db.add(segment)
    db.flush()
    published_geometry_wkt = (
        db.query(func.ST_AsText(Segment.reference_line))
        .filter(Segment.id == segment.id)
        .scalar()
    )
    if not published_geometry_wkt:
        raise VerifiedSegmentBundleError("Segment 写入后无法回读 reference_line")
    published_geometry_hash = hash_segment_geometry_wkt(published_geometry_wkt)

    judgment = JudgmentRun(
        run_type="human_review",
        status="succeeded",
        trigger_type="verified_segment_bundle_publication",
        segment_id=segment.id,
        engine_name=PUBLICATION_CONTRACT_VERSION,
        engine_version="1",
        params_json={
            "candidate_id": validated.candidate_id,
            "reviewer_name": validated.reviewer_name,
            "observed_at": validated.observed_at.isoformat(),
        },
        input_hash=validated.bundle_hash,
        confidence=1.0,
        confidence_method="explicit_human_map_review",
        confidence_state="human_accepted",
        result_summary_json={
            "candidate_id": validated.candidate_id,
            "reviewed_geometry_hash": validated.geometry_hash,
            "published_geometry_hash": published_geometry_hash,
            "source_url": validated.source_url,
            "review_note": validated.review_note,
        },
        missing_data_json=[],
        contradiction_json=[],
        created_by_user_id=reviewer_user_id,
        created_by_service="verified_segment_bundle_publisher",
        started_at=validated.reviewed_at,
        finished_at=validated.reviewed_at,
    )
    db.add(judgment)
    db.flush()

    admit_provenance_verified_segment(
        db,
        segment_id=segment.id,
        accepted_judgment_run_id=judgment.id,
        reviewer_id=reviewer_user_id,
        source_input=SegmentGeometrySourceInput(
            source_type="map_reconstruction",
            source_file_id=validated.source_file_id,
            source_url=validated.source_url,
            source_content_hash=validated.bundle_hash,
            original_coordinate_system="gcj02",
            geometry_hash=published_geometry_hash,
            normalization_version=SEGMENT_GEOMETRY_NORMALIZATION_VERSION,
            quality_status="verified",
            quality_metrics_json={
                "publication_contract_version": PUBLICATION_CONTRACT_VERSION,
                "candidate_id": validated.candidate_id,
                "bundle_hash": validated.bundle_hash,
                "reviewed_geometry_hash": validated.geometry_hash,
                "published_geometry_hash": published_geometry_hash,
                "verified_bundle": validated.bundle,
            },
        ),
        review_note=validated.review_note,
        reviewed_at=validated.reviewed_at,
    )
    db.flush()
    return SegmentPublicationResult(
        status="published",
        candidate_id=validated.candidate_id,
        segment_id=segment.id,
        geometry_hash=published_geometry_hash,
        source_file_id=validated.source_file_id,
    )
