"""跨路线域复用的稳定线条指纹。"""

from __future__ import annotations

import hashlib


SEGMENT_GEOMETRY_NORMALIZATION_VERSION = "route_cognition_segment_geometry_v1"
STRAVA_SOURCE_GEOMETRY_NORMALIZATION_VERSION = (
    "strava_source_line_lonlat_7dp_v1"
)


def stable_line_hash(reference_line_wkt: str) -> str:
    """忽略多余空白后计算 SHA-256，作为标准几何的并发/审计指纹。"""
    normalized = " ".join(reference_line_wkt.strip().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def canonical_strava_source_line_wkt(points: list[list[float]]) -> str:
    """按 census 的 7dp 合同序列化完整 Strava 来源线。"""

    return "LINESTRING (" + ", ".join(
        f"{float(lon):.7f} {float(lat):.7f}" for lon, lat in points
    ) + ")"


def strava_source_geometry_hash(points: list[list[float]]) -> str:
    """不加载数据库或海拔模块即可复现来源线事实 hash。"""

    return stable_line_hash(canonical_strava_source_line_wkt(points))
