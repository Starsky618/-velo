"""
路书导出生成器——把路线版本底片翻译成码表能读的 GPX/TCX 文件。

这个文件只负责“造文件”，不判断谁能下载、也不碰存储；但它会确认海拔来源可信，
避免后续代码绕开下载工作流，直接把旧 GPX 的脏海拔打印进码表文件。
输入是一条 route_versions.reference_line_snapshot 和可信海拔底片，输出二进制 XML 和点数。
"""

from dataclasses import dataclass
import math
from typing import Literal
from xml.sax.saxutils import escape

from app.route_book.elevation_quality import has_trusted_route_elevation, parse_complete_elevation_snapshot
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
    elevation_metadata_json: str | None = None,
    export_format: ExportFormat,
) -> GeneratedRouteExport:
    """
    从路线版本底片生成 GPX 或 TCX。

    码表导入会信任 GPX/TCX 中的海拔。缺逐点海拔时不能导出二维线，
    避免让目标 App 自行补算出偏差很大的爬升。
    """
    points = _points_from_reference_line(reference_line_snapshot)
    if len(points) < 2:
        raise ValueError("导出至少需要 2 个坐标点")
    export_points = parse_complete_elevation_snapshot(elevation_points_snapshot, expected_count=len(points))
    if export_points is None:
        raise ValueError("这条路线还没有可用海拔数据")
    if not has_trusted_route_elevation(
        elevation_points_snapshot,
        metadata_json=elevation_metadata_json,
        expected_count=len(points),
    ):
        raise ValueError("这条路线还没有用 VELO 统一海拔源生成可导出的逐点海拔")
    export_points = _elevation_on_reference_line(points, export_points)
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


def _finite_coord(value: object) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _elevation_on_reference_line(
    reference_points: list[list[float]],
    elevation_points: list[list[float]],
) -> list[list[float]]:
    """经纬度只认参考线；海拔快照只能补第三列，不能替换路线。"""
    merged: list[list[float]] = []
    for reference, elevation in zip(reference_points, elevation_points):
        if not (
            math.isclose(reference[0], elevation[0], rel_tol=0.0, abs_tol=1e-7)
            and math.isclose(reference[1], elevation[1], rel_tol=0.0, abs_tol=1e-7)
        ):
            raise ValueError("逐点海拔快照坐标与路线参考线不一致，拒绝导出")
        merged.append([reference[0], reference[1], elevation[2]])
    return merged


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
