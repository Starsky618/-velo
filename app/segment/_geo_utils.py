"""
赛段几何计算工具函数——"地图上的数学工具箱"。

这里存放两个纯计算函数，专门处理 GPS 坐标相关的数学运算：
- _haversine：算两点之间的球面距离（好比在篮球表面量弧线）
- _sample_elevation_profile：从密集坐标点里等距采样海拔值（好比照片缩略图）

这两个函数从 service.py 中提取出来，原因是 service.py 超过了 500 行红线。

注意事项：
- 这是"纯函数"模块：只接受参数、返回结果，不碰数据库、不碰文件系统
- 函数名前面的下划线（_）是 Python 约定：表示"仅供本包内部使用"
- 模块文件名前缀 _geo_utils 中的下划线同理：内部实现，不作为公开 API
"""

import math


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    计算两个 GPS 坐标点之间的球面距离（单位：米）。

    地球不是平面，不能用勾股定理算距离。
    Haversine 公式把地球当成球体，用球面三角学算弧线距离。
    好比在篮球表面两点之间量弧线，而不是直线穿球心。

    参数都是"度"（degree），函数内部转"弧度"（radian）再计算。
    """
    R = 6371000  # 地球平均半径（米）
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (math.sin(d_phi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _sample_elevation_profile(
    points: list[dict], target_count: int = 80,
) -> list[float]:
    """
    从参考路线中等距采样海拔值，生成海拔缩略图数组。

    好比"每隔固定步数拍一张照片"——不管路有多长，最终都只保留约 80 张。
    点数不超过 80 个时直接原样返回，不做采样（没必要）。
    点数超过 80 时，按等差间隔从头到尾均匀取 80 个，保证曲线形状。

    参数 target_count：目标采样点数，默认 80（前端画曲线够用，传输量小）。
    """
    n = len(points)
    # 点数未超上限，直接返回所有点的海拔（保留 1 位小数，减少传输体积）
    if n <= target_count:
        return [round(p["ele"], 1) for p in points]
    # 用浮点步长均匀采样，避免整除带来的端点偏差
    step = (n - 1) / (target_count - 1)
    return [round(points[int(i * step)]["ele"], 1) for i in range(target_count)]
