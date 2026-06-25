"""
路书导出生成器——把路线版本底片翻译成码表能读的 GPX/TCX 文件。

这个文件只负责“造文件”，不判断谁能下载、也不碰存储。
输入是一条 route_versions.reference_line_snapshot，输出是二进制 XML 和点数。
"""

from dataclasses import dataclass
from typing import Literal
from xml.sax.saxutils import escape

from app.route_book.models import _preview_points_from_wkb, _preview_points_from_wkt


ExportFormat = Literal["gpx", "tcx"]


@dataclass(frozen=True)
class GeneratedRouteExport:
    """一次导出的文件结果——像刚打印出来的一张路线纸。"""

    content: bytes
    point_count: int
    content_type: str
    extension: ExportFormat


def generate_route_export(
    *,
    route_name: str,
    reference_line_snapshot: object,
    export_format: ExportFormat,
) -> GeneratedRouteExport:
    """
    从路线版本底片生成 GPX 或 TCX。

    V0 只有二维线条：经度、纬度。这里故意不补海拔和转弯提示，
    避免把“不完整的数据”伪装成“精准导航文件”。
    """
    points = _points_from_reference_line(reference_line_snapshot)
    if len(points) < 2:
        raise ValueError("导出至少需要 2 个坐标点")

    if export_format == "gpx":
        content = _build_gpx(route_name, points)
        return GeneratedRouteExport(
            content=content,
            point_count=len(points),
            content_type="application/gpx+xml",
            extension="gpx",
        )
    if export_format == "tcx":
        content = _build_tcx(route_name, points)
        return GeneratedRouteExport(
            content=content,
            point_count=len(points),
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


def _build_gpx(route_name: str, points: list[list[float]]) -> bytes:
    name = escape(route_name)
    trkpts = "\n".join(
        f'      <trkpt lat="{_coord(lat)}" lon="{_coord(lon)}"></trkpt>'
        for lon, lat in points
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


def _build_tcx(route_name: str, points: list[list[float]]) -> bytes:
    name = escape(route_name)
    trackpoints = "\n".join(
        f"""        <Trackpoint>
          <Position>
            <LatitudeDegrees>{_coord(lat)}</LatitudeDegrees>
            <LongitudeDegrees>{_coord(lon)}</LongitudeDegrees>
          </Position>
        </Trackpoint>"""
        for lon, lat in points
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


def _coord(value: float) -> str:
    text = f"{float(value):.8f}".rstrip("0").rstrip(".")
    return "0" if text == "-0" else text
