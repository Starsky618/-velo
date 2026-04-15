"""
坐标系归一化器——"GPS 纠偏仪"。

中国地图有一套特殊的坐标加密（GCJ-02，俗称"火星坐标"），
在 GPS 标准坐标（WGS84）基础上做了随机偏移，偏移量 100-600 米。
如果不纠偏，轨迹画在地图上就会"飘"到隔壁马路甚至河里。

这个模块的职责：检查 ParseResult 的坐标系标签，
如果是 GCJ-02 就把所有坐标点转换成 WGS84，确保数据库里全是标准坐标。

好比进口商品过海关：检查原产地标签，如果是"火星产"就转换成"地球标准"。
大多数骑行数据（码表导出）都是 WGS84，这个模块直接放行、零开销。
只有中国手机 App（行者/Keep/咕咚）导出的 GPX 才需要实际转换。

注意事项：
- 不修改原始输入（frozen dataclass 保证），而是创建新的 ParseResult
- xyconvert 使用 NumPy 向量化，50000 点转换 < 10ms
- 转换精度 < 0.5 米，远在 50m 赛段匹配容差之内
- simplified_track（前端地图用的简化轨迹）也需要同步转换
"""

import numpy as np
import xyconvert
from dataclasses import replace

from app.parsing.types import (
    CoordSystem,
    ParseResult,
    Trackpoint,
)


def normalize(result: ParseResult) -> ParseResult:
    """
    坐标系归一化——确保输出的 ParseResult 坐标全部是 WGS84。

    如果已经是 WGS84 → 原样返回（零开销，大多数情况走这里）。
    如果是 GCJ-02 → 创建新的 ParseResult，所有坐标转为 WGS84。

    参数：
        result: 解析器输出的 ParseResult（可能是 GCJ-02 坐标）

    返回：
        坐标系为 WGS84 的 ParseResult（可能是原对象，也可能是新对象）
    """
    if result.metadata.coord_system == CoordSystem.WGS84:
        return result

    # ===== GCJ-02 → WGS84 转换 =====

    # 1. 转换轨迹点坐标
    new_trackpoints = _convert_trackpoints(result.trackpoints)

    # 2. 转换简化轨迹坐标（前端地图用）
    new_simplified = _convert_simplified_track(result.simplified_track)

    # 3. 更新元数据中的坐标系标签
    # dataclasses.replace 只改指定字段，其余自动透传，未来加字段也不会漏
    new_metadata = replace(result.metadata, coord_system=CoordSystem.WGS84)

    # 4. 组装新的 ParseResult（frozen，不能改旧的，只能创建新的）
    # summary / power_zones 直传不重算：GCJ-02 偏移是区域性的，
    # 同一条路线上相邻点偏移方向和大小极为接近，haversine 两点距离误差 < 0.1%，
    # speed、distance、elevation_gain 等统计值无需基于转换后坐标重算。
    return replace(
        result,
        trackpoints=new_trackpoints,
        metadata=new_metadata,
        simplified_track=new_simplified,
    )


def _convert_trackpoints(trackpoints: list[Trackpoint]) -> list[Trackpoint]:
    """
    批量转换轨迹点坐标：GCJ-02 → WGS84。

    用 xyconvert + NumPy 向量化处理，比逐点转换快 50-70 倍。
    转换后创建新的 Trackpoint 对象（frozen 不可变，只能新建）。
    """
    if not trackpoints:
        return []

    # 提取所有坐标为 numpy 数组，xyconvert 要求 [经度, 纬度] 列顺序
    coords = np.array(
        [[tp.lon, tp.lat] for tp in trackpoints],
        dtype=np.float64,
    )

    # 批量转换（核心操作，50000 点 < 10ms）
    wgs_coords = xyconvert.gcj2wgs(coords)

    # 用转换后的坐标创建新的 Trackpoint 列表
    new_trackpoints = []
    for i, tp in enumerate(trackpoints):
        new_trackpoints.append(Trackpoint(
            seq=tp.seq,
            lat=float(wgs_coords[i, 1]),   # 纬度在第 2 列
            lon=float(wgs_coords[i, 0]),   # 经度在第 1 列
            ele=tp.ele,                     # 海拔不受坐标系影响
            time=tp.time,
            hr=tp.hr,
            cad=tp.cad,
            power=tp.power,
            speed=tp.speed,
            distance=tp.distance,
        ))

    return new_trackpoints


def _convert_simplified_track(
    simplified: list[dict] | None,
) -> list[dict] | None:
    """
    批量转换简化轨迹坐标：GCJ-02 → WGS84。

    简化轨迹是给前端地图画线用的，格式 [{lat, lon, ele}, ...]，
    也需要同步转换，否则地图上的线和实际轨迹点位置不一致。
    """
    if not simplified:
        return simplified

    # 提取坐标为 numpy 数组
    coords = np.array(
        [[pt["lon"], pt["lat"]] for pt in simplified],
        dtype=np.float64,
    )

    # 批量转换
    wgs_coords = xyconvert.gcj2wgs(coords)

    # 创建新的 dict 列表（保留 ele 不变）
    return [
        {
            "lat": float(wgs_coords[i, 1]),
            "lon": float(wgs_coords[i, 0]),
            "ele": pt.get("ele"),
        }
        for i, pt in enumerate(simplified)
    ]
