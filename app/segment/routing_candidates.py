"""腾讯 driving 候选记录的确定性摘要。"""

from __future__ import annotations

import hashlib
import json
import math

from app.common.geometry_hash import stable_line_hash
from app.segment.models import SegmentRoutingCandidate


class SegmentRoutingCandidateIntegrityError(ValueError):
    """候选记录被污染、不是腾讯 driving 或已被消费。"""


def _canonical_record_payload(candidate: SegmentRoutingCandidate) -> dict:
    return {
        "segment_id": candidate.segment_id,
        "routing_provider": candidate.routing_provider,
        "routing_mode": candidate.routing_mode,
        "control_points": json.loads(candidate.control_points_json),
        "reference_line_wkt": candidate.reference_line_wkt,
        "geometry_hash": candidate.geometry_hash,
        "provider_distance_m": candidate.provider_distance_m,
        "measured_distance_m": candidate.measured_distance_m,
    }


def routing_candidate_record_hash(candidate: SegmentRoutingCandidate) -> str:
    encoded = json.dumps(
        _canonical_record_payload(candidate),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_routing_candidate_record(
    candidate: SegmentRoutingCandidate,
    *,
    expected_segment_id: int,
    require_ready: bool,
) -> None:
    numeric_values = (candidate.provider_distance_m, candidate.measured_distance_m)
    if not all(math.isfinite(value) and value > 0 for value in numeric_values):
        raise SegmentRoutingCandidateIntegrityError("腾讯候选距离无效")
    if candidate.segment_id != expected_segment_id:
        raise SegmentRoutingCandidateIntegrityError("腾讯候选未绑定当前赛段")
    if candidate.routing_provider != "tencent" or candidate.routing_mode != "driving":
        raise SegmentRoutingCandidateIntegrityError("候选不是服务端腾讯 driving 产物")
    if require_ready and candidate.status != "ready":
        raise SegmentRoutingCandidateIntegrityError("腾讯候选已被消费或不可用")
    if stable_line_hash(candidate.reference_line_wkt) != candidate.geometry_hash:
        raise SegmentRoutingCandidateIntegrityError("腾讯候选折线哈希不一致")
    try:
        actual_record_hash = routing_candidate_record_hash(candidate)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SegmentRoutingCandidateIntegrityError("腾讯候选记录无法验签") from exc
    if actual_record_hash != candidate.record_hash:
        raise SegmentRoutingCandidateIntegrityError("腾讯候选记录摘要不一致")
