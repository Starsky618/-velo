"""跨路线域复用的稳定线条指纹。"""

from __future__ import annotations

import hashlib


SEGMENT_GEOMETRY_NORMALIZATION_VERSION = "route_cognition_segment_geometry_v1"


def stable_line_hash(reference_line_wkt: str) -> str:
    """忽略多余空白后计算 SHA-256，作为标准几何的并发/审计指纹。"""
    normalized = " ".join(reference_line_wkt.strip().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
