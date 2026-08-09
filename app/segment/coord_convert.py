"""
坐标系转换工具——"翻译官"。

中国的地图有一个特殊规定：所有国内地图服务（腾讯、高德、百度）
必须使用一种叫 GCJ-02 的加密坐标系，它在 GPS 原始坐标（WGS-84）
基础上加了一个非线性偏移，偏移量 100~700 米不等。

这就导致一个问题：
- 骑行码表/手机 GPS 记录的轨迹 → WGS-84（真实位置）
- 管理员在腾讯地图上画赛段取的坐标 → GCJ-02（偏移位置）

如果不转换，赛段匹配时两套坐标对不上，偏差 100~700 米，
而 matcher 的默认容差才 50 米，匹配必定失败。

这个模块就是"翻译官"：把 GCJ-02 坐标翻译成 WGS-84，
让赛段参考线和骑行轨迹说同一种"语言"。

这是一个纯函数模块——只做数学计算，不碰数据库、不碰网络、不碰文件。
转换算法是公开的，精度在 1 米以内，完全满足骑行场景。

注意事项：
- 中国境外的坐标不需要转换（GCJ-02 偏移只在中国境内生效）
- WGS-84 传入时应跳过转换（coordinate_system="wgs84"），避免反向偏移
- 本模块无任何外部依赖，可独立测试
"""

import math


# ==================== GCJ-02 偏移参数 ====================
# 这两个参数来自 GCJ-02 的椭球体定义，是国测局公开的常量。
# _a 是地球长半轴（赤道半径），_ee 是第一偏心率的平方。
# 好比描述一个"略扁的篮球"的尺寸参数。

_A = 6378245.0                    # 长半轴（米）
_EE = 0.00669342162296594323      # 第一偏心率平方


# ==================== 边界判断 ====================

def _is_in_china(lat: float, lon: float) -> bool:
    """
    粗略判断坐标是否在中国境内。

    GCJ-02 偏移只在中国大陆范围内生效。
    境外坐标（比如日本、东南亚）的 GCJ-02 和 WGS-84 完全相同，
    所以境外坐标不需要转换，直接原样返回。

    这里用一个粗略的矩形框判断（不精确到边境线，但够用）。
    """
    return 73.66 < lon < 135.05 and 3.86 < lat < 53.55


# ==================== 偏移量计算 ====================
# GCJ-02 的偏移不是简单的"往东移 300 米"，而是一个跟经纬度有关的
# 复杂非线性函数。好比一张橡皮地图被不均匀地拉扯——
# 不同位置的拉扯方向和力度都不一样。

def _transform_lat(x: float, y: float) -> float:
    """计算纬度方向的偏移量（内部辅助函数）。"""
    ret = (-100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y
           + 0.1 * x * y + 0.2 * math.sqrt(abs(x)))
    ret += ((20.0 * math.sin(6.0 * x * math.pi)
             + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0)
    ret += ((20.0 * math.sin(y * math.pi)
             + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0)
    ret += ((160.0 * math.sin(y / 12.0 * math.pi)
             + 320.0 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0)
    return ret


def _transform_lon(x: float, y: float) -> float:
    """计算经度方向的偏移量（内部辅助函数）。"""
    ret = (300.0 + x + 2.0 * y + 0.1 * x * x
           + 0.1 * x * y + 0.1 * math.sqrt(abs(x)))
    ret += ((20.0 * math.sin(6.0 * x * math.pi)
             + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0)
    ret += ((20.0 * math.sin(x * math.pi)
             + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0)
    ret += ((150.0 * math.sin(x / 12.0 * math.pi)
             + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0)
    return ret


# ==================== 核心转换函数 ====================

def gcj02_to_wgs84(lat: float, lon: float) -> tuple[float, float]:
    """
    将单个 GCJ-02 坐标转换为 WGS-84 坐标。

    转换原理（逆向偏移法）：
    GCJ-02 = WGS-84 + 偏移量(lat, lon)
    所以 WGS-84 ≈ GCJ-02 - 偏移量(lat, lon)

    实际操作：
    1. 用 GCJ-02 坐标算出偏移量（dlat, dlon）
    2. GCJ-02 坐标 = 原始坐标 + 偏移量 → 原始坐标 = GCJ-02 - 偏移量
    3. 精度在 1 米以内，骑行场景完全够用

    返回：(lat_wgs84, lon_wgs84)
    """
    # 境外坐标不偏移，直接返回
    if not _is_in_china(lat, lon):
        return lat, lon

    # 计算偏移量
    dlat = _transform_lat(lon - 105.0, lat - 35.0)
    dlon = _transform_lon(lon - 105.0, lat - 35.0)

    # 用椭球体参数修正偏移量
    # 纬度越高（越靠近极地），同样的经度差对应的地面距离越短，需要修正
    rad_lat = lat / 180.0 * math.pi
    magic = math.sin(rad_lat)
    magic = 1 - _EE * magic * magic
    sqrt_magic = math.sqrt(magic)

    dlat = (dlat * 180.0) / ((_A * (1 - _EE)) / (magic * sqrt_magic) * math.pi)
    dlon = (dlon * 180.0) / (_A / sqrt_magic * math.cos(rad_lat) * math.pi)

    # 逆向：GCJ-02 坐标减去偏移量 = WGS-84 坐标
    # 数学技巧：gcj_lat = wgs_lat + dlat → wgs_lat = gcj_lat - dlat
    # 等价写法：wgs = gcj * 2 - (gcj + d) = gcj - d
    mg_lat = lat + dlat
    mg_lon = lon + dlon
    return lat * 2 - mg_lat, lon * 2 - mg_lon


def wgs84_to_gcj02(lat: float, lon: float) -> tuple[float, float]:
    """将 WGS-84 坐标转换为腾讯算路使用的 GCJ-02。"""
    if not math.isfinite(lat) or not math.isfinite(lon):
        raise ValueError("坐标必须是有限数字")
    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        raise ValueError("坐标越界")
    if not _is_in_china(lat, lon):
        return lat, lon

    dlat = _transform_lat(lon - 105.0, lat - 35.0)
    dlon = _transform_lon(lon - 105.0, lat - 35.0)
    rad_lat = lat / 180.0 * math.pi
    magic = math.sin(rad_lat)
    magic = 1 - _EE * magic * magic
    sqrt_magic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((_A * (1 - _EE)) / (magic * sqrt_magic) * math.pi)
    dlon = (dlon * 180.0) / (_A / sqrt_magic * math.cos(rad_lat) * math.pi)
    return lat + dlat, lon + dlon


def convert_points_to_wgs84(
    points: list[dict],
    coordinate_system: str = "gcj02",
) -> list[dict]:
    """
    批量转换坐标点列表。

    参数：
    - points：坐标点列表，每个点是 {"lat": float, "lon": float, "ele": float|None}
    - coordinate_system："gcj02" 需要转换，"wgs84" 原样返回

    返回：转换后的坐标点列表（新列表，不修改原数据）

    使用场景：
    管理员在腾讯地图上画赛段 → 坐标是 GCJ-02 → 调用此函数转成 WGS-84 → 存库
    开发者直接传 WGS-84 坐标 → coordinate_system="wgs84" → 跳过转换
    """
    if coordinate_system not in ("gcj02", "wgs84"):
        raise ValueError(f"不支持的坐标系: {coordinate_system}，只支持 gcj02 或 wgs84")

    if coordinate_system == "wgs84":
        return points

    converted = []
    for p in points:
        new_lat, new_lon = gcj02_to_wgs84(p["lat"], p["lon"])
        new_point = {"lat": new_lat, "lon": new_lon}
        if p.get("ele") is not None:
            new_point["ele"] = p["ele"]
        converted.append(new_point)

    return converted
