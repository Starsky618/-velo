"""只读 Strava 公开赛段观察目录。

运行时几何替换只能选择已入目录的观察记录，不能在同一个请求里自报来源距离。
目录通过代码评审进入镜像，并把来源身份、目标赛段和可信基线哈希绑定在一起。
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
import math
from pathlib import Path
import re
from urllib.parse import urlsplit

from app.common.geometry_hash import stable_line_hash
from app.segment._geo_utils import _haversine


SOURCE_OBSERVATION_CATALOG_VERSION = "segment_source_observations_v1"
_CATALOG_PATH = Path(__file__).with_name("data") / "source_observations_v1.json"


class SegmentSourceObservationError(ValueError):
    """来源观察不存在、失效或与目标赛段不一致。"""


@dataclass(frozen=True)
class SegmentSourceObservation:
    observation_id: str
    source_segment_id: str
    source_url: str
    observed_distance_m: float
    observed_at: str
    target_segment_id: int
    target_segment_names: tuple[str, ...]
    expected_start_lat: float
    expected_start_lon: float
    expected_end_lat: float
    expected_end_lon: float
    endpoint_tolerance_m: float
    trusted_baseline_geometry_hash: str
    catalog_version: str = SOURCE_OBSERVATION_CATALOG_VERSION


def parse_strava_segment_id(source_url: str) -> str:
    """只接受没有用户信息、query 或 fragment 的 HTTPS 公开赛段页。"""
    parsed = urlsplit(source_url.strip())
    try:
        port = parsed.port
    except ValueError:
        port = -1
    host = (parsed.hostname or "").lower()
    match = re.fullmatch(r"/segments/([1-9][0-9]*)/?", parsed.path)
    if (
        (host != "strava.com" and not host.endswith(".strava.com"))
        or match is None
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or parsed.scheme.lower() != "https"
    ):
        raise SegmentSourceObservationError("来源必须是精确的 Strava HTTPS 赛段页")
    return match.group(1)


@lru_cache(maxsize=1)
def source_observation_catalog() -> dict[str, SegmentSourceObservation]:
    raw = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
    if raw.get("catalog_version") != SOURCE_OBSERVATION_CATALOG_VERSION:
        raise SegmentSourceObservationError("赛段来源观察目录版本不受支持")
    observations: dict[str, SegmentSourceObservation] = {}
    for item in raw.get("observations", []):
        observation = SegmentSourceObservation(
            observation_id=item["observation_id"],
            source_segment_id=str(item["source_segment_id"]),
            source_url=item["source_url"],
            observed_distance_m=float(item["observed_distance_m"]),
            observed_at=item["observed_at"],
            target_segment_id=int(item["target_segment_id"]),
            target_segment_names=tuple(item["target_segment_names"]),
            expected_start_lat=float(item["expected_start_wgs84"]["lat"]),
            expected_start_lon=float(item["expected_start_wgs84"]["lon"]),
            expected_end_lat=float(item["expected_end_wgs84"]["lat"]),
            expected_end_lon=float(item["expected_end_wgs84"]["lon"]),
            endpoint_tolerance_m=float(item["endpoint_tolerance_m"]),
            trusted_baseline_geometry_hash=item["trusted_baseline_geometry_hash"],
        )
        if observation.observation_id in observations:
            raise SegmentSourceObservationError("赛段来源观察 ID 重复")
        if parse_strava_segment_id(observation.source_url) != observation.source_segment_id:
            raise SegmentSourceObservationError("来源 URL 与 Strava segment id 不一致")
        numeric_values = (
            observation.observed_distance_m,
            observation.expected_start_lat,
            observation.expected_start_lon,
            observation.expected_end_lat,
            observation.expected_end_lon,
            observation.endpoint_tolerance_m,
        )
        if not all(math.isfinite(value) for value in numeric_values):
            raise SegmentSourceObservationError("来源观察含非有限数字")
        if (
            observation.observed_distance_m <= 0
            or observation.endpoint_tolerance_m <= 0
            or observation.target_segment_id <= 0
        ):
            raise SegmentSourceObservationError("来源观察的目标、距离或端点容差无效")
        if re.fullmatch(r"[0-9a-f]{64}", observation.trusted_baseline_geometry_hash) is None:
            raise SegmentSourceObservationError("来源观察的可信基线哈希无效")
        observations[observation.observation_id] = observation
    return observations


def resolve_source_observation(
    observation_id: str,
    *,
    segment_id: int,
    segment_name: str,
    current_wkt: str,
    current_start_lat: float,
    current_start_lon: float,
    current_end_lat: float,
    current_end_lon: float,
) -> SegmentSourceObservation:
    """选择目录项，并机械确认它绑定的是当前 segment 和可信基线。"""
    observation = source_observation_catalog().get(observation_id)
    if observation is None:
        raise SegmentSourceObservationError("来源观察不存在或尚未通过代码评审")
    if segment_id != observation.target_segment_id:
        raise SegmentSourceObservationError("来源观察未绑定当前目标 segment id")
    if segment_name not in observation.target_segment_names:
        raise SegmentSourceObservationError("来源观察未绑定当前目标赛段")
    if stable_line_hash(current_wkt) != observation.trusted_baseline_geometry_hash:
        raise SegmentSourceObservationError("当前标准线不是该来源观察绑定的可信基线")
    numeric_values = (
        current_start_lat,
        current_start_lon,
        current_end_lat,
        current_end_lon,
    )
    if not all(math.isfinite(value) for value in numeric_values):
        raise SegmentSourceObservationError("当前赛段端点含非有限数字")
    start_shift_m = _haversine(
        current_start_lat,
        current_start_lon,
        observation.expected_start_lat,
        observation.expected_start_lon,
    )
    end_shift_m = _haversine(
        current_end_lat,
        current_end_lon,
        observation.expected_end_lat,
        observation.expected_end_lon,
    )
    if max(start_shift_m, end_shift_m) > observation.endpoint_tolerance_m:
        raise SegmentSourceObservationError("来源观察与当前赛段边界不一致")
    return observation
