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

import numpy as np

from app.elevation.route_elevation import (
    ROUTE_ELEVATION_METHOD,
    interpolate_route_points,
    route_distance_m,
    route_vertex_chainages_m,
)
from app.route_book.elevation_quality import (
    declares_elevation_grid,
    has_elevation_metadata_method,
    has_trusted_route_elevation,
    parse_complete_elevation_grid,
    parse_complete_elevation_snapshot,
)
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
    elevation_grid_snapshot: str | None = None,
    reference_line_hash: str | None = None,
    elevation_metadata_json: str | None = None,
    export_format: ExportFormat,
) -> GeneratedRouteExport:
    """
    从路线版本底片生成 GPX 或 TCX。

    码表导入会信任 GPX/TCX 中的海拔。缺逐点海拔时不能导出二维线，
    避免让目标 App 自行补算出偏差很大的爬升。
    """
    points, sparse_elevation_points, elevation_grid = _validated_route_elevation(
        reference_line_snapshot=reference_line_snapshot,
        elevation_points_snapshot=elevation_points_snapshot,
        elevation_grid_snapshot=elevation_grid_snapshot,
        reference_line_hash=reference_line_hash,
        elevation_metadata_json=elevation_metadata_json,
    )
    if elevation_grid is None:
        export_points = _elevation_on_reference_line(points, sparse_elevation_points)
    else:
        export_grid = _grid_with_reference_vertices(points, elevation_grid)
        coordinates = interpolate_route_points(
            points,
            [item[0] for item in export_grid],
        )
        export_points = [
            [lon, lat, item[1]]
            for (lon, lat), item in zip(coordinates, export_grid)
        ]
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


def has_exportable_route_elevation(
    *,
    reference_line_snapshot: object,
    elevation_points_snapshot: str | None,
    elevation_grid_snapshot: str | None,
    reference_line_hash: str | None,
    elevation_metadata_json: str | None,
) -> bool:
    """详情页和真实导出共用同一道完整性门，避免按钮可点但创建时才失败。"""
    try:
        _validated_route_elevation(
            reference_line_snapshot=reference_line_snapshot,
            elevation_points_snapshot=elevation_points_snapshot,
            elevation_grid_snapshot=elevation_grid_snapshot,
            reference_line_hash=reference_line_hash,
            elevation_metadata_json=elevation_metadata_json,
        )
    except ValueError:
        return False
    return True


def _validated_route_elevation(
    *,
    reference_line_snapshot: object,
    elevation_points_snapshot: str | None,
    elevation_grid_snapshot: str | None,
    reference_line_hash: str | None,
    elevation_metadata_json: str | None,
) -> tuple[list[list[float]], list[list[float]], list[list[float]] | None]:
    points = _points_from_reference_line(reference_line_snapshot)
    if len(points) < 2:
        raise ValueError("导出至少需要 2 个坐标点")
    sparse_elevation_points = parse_complete_elevation_snapshot(
        elevation_points_snapshot,
        expected_count=len(points),
    )
    if sparse_elevation_points is None:
        raise ValueError("这条路线还没有可用海拔数据")
    if not has_trusted_route_elevation(
        elevation_points_snapshot,
        metadata_json=elevation_metadata_json,
        expected_count=len(points),
    ):
        raise ValueError("这条路线还没有用 VELO 统一海拔源生成可导出的逐点海拔")
    is_glo = has_elevation_metadata_method(
        elevation_metadata_json,
        methods=frozenset({ROUTE_ELEVATION_METHOD}),
        expected_count=len(points),
    )
    if not is_glo:
        return points, sparse_elevation_points, None
    if elevation_grid_snapshot is None:
        if declares_elevation_grid(elevation_metadata_json):
            raise ValueError("路线声明了 canonical 海拔网格但数据缺失")
        return points, sparse_elevation_points, None

    elevation_grid = parse_complete_elevation_grid(
        elevation_grid_snapshot,
        expected_line_hash=reference_line_hash or "",
        expected_distance_m=route_distance_m(points),
        metadata_json=elevation_metadata_json,
    )
    if elevation_grid is None:
        raise ValueError("路线 canonical 海拔网格损坏或不属于当前参考线")
    return points, sparse_elevation_points, elevation_grid


def _grid_with_reference_vertices(
    points: list[list[float]],
    elevation_grid: list[list[float]],
) -> list[list[float]]:
    """合并成品网格与原参考线顶点；密集点不能把急弯、发卡弯直接切掉。"""
    candidates = [(float(item[0]), False) for item in elevation_grid]
    candidates.extend((chainage, True) for chainage in route_vertex_chainages_m(points))
    candidates.sort(key=lambda item: item[0])

    merged: list[tuple[float, bool]] = []
    for chainage, is_vertex in candidates:
        if merged and abs(chainage - merged[-1][0]) <= 0.001:
            if is_vertex:
                merged[-1] = (chainage, True)
            continue
        merged.append((chainage, is_vertex))

    canonical_distances = np.asarray([item[0] for item in elevation_grid], dtype=float)
    canonical_elevations = np.asarray([item[1] for item in elevation_grid], dtype=float)
    merged_distances = np.asarray([item[0] for item in merged], dtype=float)
    merged_elevations = np.interp(
        merged_distances,
        canonical_distances,
        canonical_elevations,
    )
    return [
        [float(distance), round(float(elevation), 1)]
        for distance, elevation in zip(merged_distances, merged_elevations)
    ]


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
