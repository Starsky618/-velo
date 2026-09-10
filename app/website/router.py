"""Public, non-persistent GLO-30 profile preview for the Taiyuan website map."""
from __future__ import annotations

import logging
from threading import BoundedSemaphore

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.elevation.dem_client import DEMServiceError, query_elevations
from app.elevation.route_elevation import ROUTE_ELEVATION_METHOD, build_route_elevation_result
from app.middleware.rate_limit import check_rate_limit_by_ip
from app.parsing.geo_math import haversine

router = APIRouter(prefix="/api/website", tags=["website"])
logger = logging.getLogger(__name__)
_slots = BoundedSemaphore(2)


class ElevationPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    points: list[tuple[float, float]] = Field(min_length=2, max_length=2000)

    @field_validator("points")
    @classmethod
    def validate_region(cls, points):
        if any(not (112.0 <= lon < 113.0 and 37.4 <= lat <= 38.2) for lon, lat in points):
            raise ValueError("请在太原及周边绘制路线")
        distance = sum(haversine(a[1], a[0], b[1], b[0]) for a, b in zip(points, points[1:]))
        if not 10 <= distance <= 120_000:
            raise ValueError("演示路线长度需在 10 米至 120 公里之间")
        return points


class ElevationPreviewResponse(BaseModel):
    source: str
    method: str
    distance_m: float
    climb_m: float
    descent_m: float
    profile: list[tuple[float, float]]
    elevations_m: list[float]


@router.post("/elevation-preview", response_model=ElevationPreviewResponse)
def elevation_preview(payload: ElevationPreviewRequest, request: Request):
    check_rate_limit_by_ip(request, "website-elevation-preview", limit=12, window_sec=300)
    if not _slots.acquire(blocking=False):
        raise HTTPException(status_code=503, detail="海拔服务繁忙，请稍后再试")
    try:
        result = build_route_elevation_result(
            payload.points,
            query_func=lambda points: query_elevations(points, timeout_seconds=20),
        )
        distance = sum(haversine(a[1], a[0], b[1], b[0]) for a, b in zip(payload.points, payload.points[1:]))
        return ElevationPreviewResponse(
            source="Copernicus GLO-30",
            method=ROUTE_ELEVATION_METHOD,
            distance_m=round(distance, 1),
            climb_m=result.climb,
            descent_m=result.descent,
            profile=result.profile,
            elevations_m=[point[2] for point in result.snapshot],
        )
    except (DEMServiceError, ValueError):
        logger.exception("website elevation preview failed points=%d", len(payload.points))
        raise HTTPException(status_code=503, detail="海拔暂时未能计算，请稍后重试")
    finally:
        _slots.release()
