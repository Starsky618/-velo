"""
路书导出生成器——把路线版本底片翻译成码表能读的 GPX/TCX 文件。

这个文件只负责“造文件”，不判断谁能下载、也不碰存储。
输入是一条 route_versions.reference_line_snapshot，输出是二进制 XML 和点数。
"""

from dataclasses import dataclass
import json
import math
from typing import Literal
from xml.sax.saxutils import escape

from app.route_book.models import _preview_points_from_wkb, _preview_points_from_wkt


ExportFormat = Literal["gpx", "tcx"]


@dataclass(frozen=True)
class GeneratedRouteExport:
    """一次导出的文件结果——像刚打印出来的一张路线纸。"""

    content: bytes
    point_count: int
    elevation_point_count: int
    content_type: str
    extension: ExportFormat


def generate_route_export(
    *,
    route_name: str,
    reference_line_snapshot: object,
    elevation_points_snapshot: str | None = None,
    export_format: ExportFormat,
) -> GeneratedRouteExport:
    """
    从路线版本底片生成 GPX 或 TCX。

    如果路线版本有逐点海拔底片，导出必须优先使用它；没有时才退回二维线。
    这里仍然不生成转弯提示，避免把不完整的数据伪装成完整导航。
    """
    points = _points_from_reference_line(reference_line_snapshot)
    elevations = _elevations_from_snapshot(elevation_points_snapshot, reference_points=points)
    export_points = [
        [lon, lat, ele]
        for (lon, lat), ele in zip(points, elevations or [None] * len(points))
    ]
    if len(export_points) < 2:
        raise ValueError("导出至少需要 2 个坐标点")
    elevation_point_count = sum(1 for _lon, _lat, ele in export_points if ele is not None)

    if export_format == "gpx":
        content = _build_gpx(route_name, export_points)
        return GeneratedRouteExport(
            content=content,
            point_count=len(export_points),
            elevation_point_count=elevation_point_count,
            content_type="application/gpx+xml",
            extension="gpx",
        )
    if export_format == "tcx":
        content = _build_tcx(route_name, export_points)
        return GeneratedRouteExport(
            content=content,
            point_count=len(export_points),
            elevation_point_count=elevation_point_count,
            content_type="application/vnd.garmin.tcx+xml",
            extension="tcx",
        )
    raise ValueError("只支持导出 gpx 或 tcx")


def count_exportable_elevation_points(
    *,
    reference_line_snapshot: object,
    elevation_points_snapshot: str | None,
) -> int:
    """数一数这张路线底片里有多少个能安全带进导出文件的海拔点。"""
    points = _points_from_reference_line(reference_line_snapshot)
    elevations = _elevations_from_snapshot(elevation_points_snapshot, reference_points=points)
    if not elevations:
        return 0
    return sum(1 for ele in elevations if ele is not None)


def _points_from_reference_line(value: object) -> list[list[float]]:
    if value is None:
        return []
    if isinstance(value, str):
        return _preview_points_from_wkt(value)

    data = getattr(value, "data", value)
    if isinstance(data, str):
        points = _preview_points_from_wkt(data)
        if points:
            return points
    return _preview_points_from_wkb(data)


def _elevations_from_snapshot(value: str | None, *, reference_points: list[list[float]]) -> list[float | None] | None:
    if not value:
        return None
    try:
        raw_points = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(raw_points, list) or len(raw_points) != len(reference_points):
        return None

    elevations: list[float | None] = []
    has_elevation = False
    for raw, reference in zip(raw_points, reference_points):
        if not isinstance(raw, list) or len(raw) < 3:
            return None
        lon = _finite_coord(raw[0])
        lat = _finite_coord(raw[1])
        if lon is None or lat is None or not _same_point(lon, lat, reference):
            return None
        ele = _finite_coord(raw[2])
        if ele is not None:
            has_elevation = True
        elevations.append(ele)
    return elevations if has_elevation else None


def _same_point(lon: float, lat: float, reference: list[float]) -> bool:
    # 高程快照只能当“同一点的高度标签”使用；坐标对不上时宁可不带高度，也不能把路线画偏。
    tolerance = 1e-6
    return abs(lon - reference[0]) <= tolerance and abs(lat - reference[1]) <= tolerance


def _finite_coord(value: object) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _build_gpx(route_name: str, points: list[list[float | None]]) -> bytes:
    name = escape(route_name)
    trkpts = "\n".join(
        _gpx_trackpoint(lon, lat, ele)
        for lon, lat, ele in points
    )
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="VELO" xmlns="http://www.topografix.com/GPX/1/1">
  <metadata>
    <name>{name}</name>
  </metadata>
  <trk>
    <name>{name}</name>
    <trkseg>
{trkpts}
    </trkseg>
  </trk>
</gpx>
"""
    return xml.encode("utf-8")


def _gpx_trackpoint(lon: float | None, lat: float | None, ele: float | None) -> str:
    if ele is None:
        return f'      <trkpt lat="{_coord(lat)}" lon="{_coord(lon)}"></trkpt>'
    return f"""      <trkpt lat="{_coord(lat)}" lon="{_coord(lon)}">
        <ele>{_coord(ele)}</ele>
      </trkpt>"""


def _build_tcx(route_name: str, points: list[list[float | None]]) -> bytes:
    name = escape(route_name)
    trackpoints = "\n".join(
        _tcx_trackpoint(lon, lat, ele)
        for lon, lat, ele in points
    )
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">
  <Courses>
    <Course>
      <Name>{name}</Name>
      <Track>
{trackpoints}
      </Track>
    </Course>
  </Courses>
</TrainingCenterDatabase>
"""
    return xml.encode("utf-8")


def _tcx_trackpoint(lon: float | None, lat: float | None, ele: float | None) -> str:
    altitude = "" if ele is None else f"\n          <AltitudeMeters>{_coord(ele)}</AltitudeMeters>"
    return f"""        <Trackpoint>
          <Position>
            <LatitudeDegrees>{_coord(lat)}</LatitudeDegrees>
            <LongitudeDegrees>{_coord(lon)}</LongitudeDegrees>
          </Position>{altitude}
        </Trackpoint>"""


def _coord(value: float | None) -> str:
    text = f"{float(value):.8f}".rstrip("0").rstrip(".")
    return "0" if text == "-0" else text
