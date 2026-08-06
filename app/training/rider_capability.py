"""Build a privacy-safe route-history envelope for the current rider.

The service reads only compact Activity summary columns.  It does not inspect
raw tracks, power, heart rate or another rider's records, and it never writes
back to Activity/User.  The result is observational evidence for a route
planning context; it is not a training prescription or a health assessment.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import math
from time import perf_counter

from sqlalchemy.orm import Session

from app.activity.models import Activity
from app.training import schemas


logger = logging.getLogger(__name__)

WINDOW_DAYS = 42
FRESH_DAYS = 14
MIN_ROUTE_DISTANCE_M = 5_000.0
MIN_ACTIVITIES_FOR_PROFILE = 3
MIN_ACTIVITIES_FOR_HIGH_CONFIDENCE = 8
MIN_ELEVATION_ACTIVITIES = 3


@dataclass(frozen=True)
class _ActivitySample:
    activity_id: int
    started_at: datetime
    distance_m: float
    duration_s: int
    elevation_gain_m: float | None
    data_source: str


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _percentile(values: list[float], quantile: float) -> float:
    """Linear percentile with deterministic behavior for tiny samples."""
    if not values:
        raise ValueError("percentile requires at least one value")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower_index = math.floor(position)
    upper_index = math.ceil(position)
    if lower_index == upper_index:
        return ordered[lower_index]
    weight = position - lower_index
    return ordered[lower_index] * (1 - weight) + ordered[upper_index] * weight


def _duration_seconds(moving_time: int | None, duration: int | None) -> int | None:
    if moving_time is not None and moving_time > 0:
        return int(moving_time)
    if duration is not None and duration > 0:
        return int(duration)
    return None


def _normalize_source(value: str | None) -> str:
    if value is None or value.strip() == "":
        return "unknown"
    return value.strip().lower()


def _source_revision(rows: list[object]) -> str:
    normalized = [
        {
            "id": int(row.id),
            "started_at": _aware_utc(row.started_at).isoformat(),
            "distance": row.distance,
            "moving_time": row.moving_time,
            "duration": row.duration,
            "elevation_gain": row.elevation_gain,
            "data_source": row.data_source,
        }
        for row in rows
    ]
    digest = hashlib.sha256(
        json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"activity-history:sha256:{digest}"


def _usable_samples(rows: list[object]) -> list[_ActivitySample]:
    samples: list[_ActivitySample] = []
    for row in rows:
        duration_s = _duration_seconds(row.moving_time, row.duration)
        if row.distance is None or float(row.distance) < MIN_ROUTE_DISTANCE_M or duration_s is None:
            continue
        elevation = None
        if row.elevation_gain is not None and float(row.elevation_gain) >= 0:
            elevation = float(row.elevation_gain)
        samples.append(
            _ActivitySample(
                activity_id=int(row.id),
                started_at=_aware_utc(row.started_at),
                distance_m=float(row.distance),
                duration_s=duration_s,
                elevation_gain_m=elevation,
                data_source=_normalize_source(row.data_source),
            )
        )
    return samples


def get_rider_capability_snapshot(
    db: Session,
    user_id: int,
    *,
    now: datetime | None = None,
) -> schemas.RiderCapabilitySnapshotResponse:
    started = perf_counter()
    calculated_at = _aware_utc(now or datetime.now(timezone.utc))
    window_start = calculated_at - timedelta(days=WINDOW_DAYS)

    rows = (
        db.query(
            Activity.id,
            Activity.started_at,
            Activity.distance,
            Activity.moving_time,
            Activity.duration,
            Activity.elevation_gain,
            Activity.data_source,
        )
        .filter(
            Activity.user_id == user_id,
            Activity.status == "completed",
            Activity.activity_type == "cycling",
            Activity.duplicate_of.is_(None),
            Activity.started_at.isnot(None),
            Activity.started_at >= window_start,
            Activity.started_at <= calculated_at,
        )
        .order_by(Activity.started_at.asc(), Activity.id.asc())
        .all()
    )
    revision = _source_revision(rows)
    samples = _usable_samples(rows)
    source_count = len(samples)
    elevation_samples = [sample for sample in samples if sample.elevation_gain_m is not None]

    if not samples:
        confidence: schemas.RiderCapabilityConfidence = "insufficient"
        freshness: schemas.RiderCapabilityFreshness = "none"
        latest_activity_at = None
        reason_codes: list[schemas.RiderCapabilityReasonCode] = ["no_usable_activities"]
    else:
        latest_activity_at = max(sample.started_at for sample in samples)
        freshness = "fresh" if calculated_at - latest_activity_at <= timedelta(days=FRESH_DAYS) else "stale"
        if source_count < MIN_ACTIVITIES_FOR_PROFILE or freshness == "stale":
            confidence = "low"
        elif source_count >= MIN_ACTIVITIES_FOR_HIGH_CONFIDENCE:
            confidence = "high"
        else:
            confidence = "medium"
        reason_codes = []
        if source_count < MIN_ACTIVITIES_FOR_PROFILE:
            reason_codes.append("too_few_usable_activities")
        if freshness == "stale":
            reason_codes.append("history_stale")
        if len(elevation_samples) < MIN_ELEVATION_ACTIVITIES:
            reason_codes.append("insufficient_elevation_history")

    distances_km = [sample.distance_m / 1000 for sample in samples]
    durations_minutes = [sample.duration_s / 60 for sample in samples]
    climb_density = [
        sample.elevation_gain_m / (sample.distance_m / 1000)
        for sample in elevation_samples
        if sample.elevation_gain_m is not None
    ]

    response = schemas.RiderCapabilitySnapshotResponse(
        schema_version="0.1.0",
        snapshot_id=f"rider-capability:{revision.rsplit(':', 1)[-1][:24]}",
        generated_at=calculated_at,
        source_revision=revision,
        window_days=WINDOW_DAYS,
        source_activity_count=source_count,
        excluded_activity_count=len(rows) - source_count,
        elevation_activity_count=len(elevation_samples),
        data_complete=confidence in {"medium", "high"},
        confidence=confidence,
        freshness=freshness,
        latest_activity_at=latest_activity_at,
        typical_distance_km=round(_percentile(distances_km, 0.5), 1) if distances_km else None,
        upper_observed_distance_km=round(_percentile(distances_km, 0.75), 1) if distances_km else None,
        typical_duration_minutes=int(round(_percentile(durations_minutes, 0.5))) if durations_minutes else None,
        typical_climb_m_per_km=(
            round(_percentile(climb_density, 0.5), 1)
            if len(climb_density) >= MIN_ELEVATION_ACTIVITIES
            else None
        ),
        source_types=sorted({sample.data_source for sample in samples}),
        reason_codes=reason_codes,
        privacy=schemas.RiderCapabilityPrivacy(),
    )
    logger.info(
        "rider_capability_snapshot confidence=%s source_activity_count=%s excluded_activity_count=%s "
        "elevation_activity_count=%s duration_ms=%.1f",
        response.confidence,
        response.source_activity_count,
        response.excluded_activity_count,
        response.elevation_activity_count,
        (perf_counter() - started) * 1000,
    )
    return response
