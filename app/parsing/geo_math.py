"""
地理计算工具箱——"尺子和量角器"。

这个文件提供骑行数据处理中最基础的地理计算能力：
- 两点之间的球面距离（haversine）
- 累计爬升（去噪后的高度差求和）
- 两点间速度（距离÷时间）
- 逐点累计距离（从起点开始逐段累加）

好比你拿着一把尺子和一个量角器，在地球仪上量两个图钉之间的弧线距离。
这些计算是所有解析器共用的基础工具，GPX 解析器和统计计算器都会调用它们。

注意事项：
- 这是纯函数模块，不碰数据库、不碰文件系统
- 只依赖 types.py 中的 Trackpoint 类型定义
- 速度单位统一 m/s，异常阈值 33.3 m/s（≈120 km/h）
- 爬升去噪阈值默认 2m，滤除 GPS 高程传感器的抖动噪声
"""

import math

from app.parsing.types import Trackpoint


# ==================== 常量 ====================

# 地球平均半径（米），用于 haversine 公式
# 地球不是完美的球（赤道半径比极半径大 21km），但对骑行距离来说误差 <0.3%
EARTH_RADIUS = 6371000

# 爬升去噪阈值（米）：相邻两点高差小于这个值不算爬升
# GPS 高程传感器有 ±3-10m 的随机抖动，不过滤的话平路也会"累计爬升 200m"
ELEVATION_THRESHOLD = 2.0

# 速度异常阈值（m/s）：超过这个速度视为 GPS 漂移，不是真实骑行速度
# 公路骑行正常极限约 80 km/h，120 km/h 留了很大余量
MAX_SPEED_MS = 120.0 / 3.6  # 120 km/h → 33.33 m/s


# ==================== 核心函数 ====================


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    计算两个经纬度坐标之间的球面距离（米）。

    haversine 公式是计算地球上两点距离的经典方法。
    想象地球是一个完美的球，沿着球面走的最短路径叫"大圆距离"，
    这个公式算的就是这个距离。

    参数：
        lat1, lon1: 第一个点的纬度、经度（度）
        lat2, lon2: 第二个点的纬度、经度（度）

    返回：
        两点之间的球面距离（米）

    精度说明：对于骑行距离（几十到几百公里），误差 <0.3%，完全够用。
    """
    # 角度转弧度（三角函数需要弧度制输入）
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    # haversine 公式核心：先算半正矢值 a，再算角距离 c
    a = (math.sin(dlat / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)
    c = 2 * math.asin(math.sqrt(a))

    return EARTH_RADIUS * c


def calculate_elevation_gain(
    trackpoints: list[Trackpoint],
    threshold: float = ELEVATION_THRESHOLD,
) -> float:
    """
    计算轨迹的累计爬升（米），带去噪。

    只累加"上坡"部分（后一个点比前一个点高），而且高差要超过阈值才算。
    这是因为 GPS 高程传感器不太准，平路骑行时海拔读数也会上下跳动，
    不过滤的话一段 50km 的平路可能"爬升 200m"，明显不合理。

    好比你爬楼梯，只数"往上走的台阶数"，忽略脚步的轻微起伏。

    参数：
        trackpoints: 轨迹点列表（按时间顺序排列）
        threshold: 去噪阈值（米），默认 2m，相邻两点高差小于此值不计入

    返回：
        累计爬升（米）
    """
    total = 0.0

    for i in range(1, len(trackpoints)):
        prev_ele = trackpoints[i - 1].ele
        curr_ele = trackpoints[i].ele

        # 两个点都有海拔数据才能算高差
        if prev_ele is not None and curr_ele is not None:
            diff = curr_ele - prev_ele
            # 只累加正值（上坡）且超过去噪阈值的部分
            if diff > threshold:
                total += diff

    return total


def calculate_speed(
    tp_prev: Trackpoint,
    tp_curr: Trackpoint,
) -> float | None:
    """
    计算两个相邻轨迹点之间的瞬时速度（m/s）。

    公式很简单：速度 = 距离 ÷ 时间。
    但需要处理几种异常情况：
    1. 缺少时间戳 → 无法算，返回 None
    2. 时间差为零（同一秒的两个点）→ 无法算，返回 None
    3. 速度超过 33.3 m/s（120 km/h）→ GPS 漂移，返回 None

    参数：
        tp_prev: 前一个轨迹点
        tp_curr: 当前轨迹点

    返回：
        速度（m/s），异常情况返回 None
    """
    # 必须有时间戳才能算速度
    if tp_prev.time is None or tp_curr.time is None:
        return None

    dt = (tp_curr.time - tp_prev.time).total_seconds()
    if dt <= 0:
        return None

    dist = haversine(tp_prev.lat, tp_prev.lon, tp_curr.lat, tp_curr.lon)
    speed = dist / dt

    # 超过阈值视为 GPS 漂移（传感器偶尔跳一个远点）
    if speed > MAX_SPEED_MS:
        return None

    return speed


def calculate_cumulative_distances(trackpoints: list[Trackpoint]) -> list[float]:
    """
    计算逐点累计距离（米），用于 GPX 数据补算 distance 字段。

    FIT 和 Strava 自带每个点的累计距离，但 GPX 没有，
    需要从第一个点开始，逐段用 haversine 累加。

    好比你走路时每走一步就在计步器上加一个数：
    第 0 步 = 0m，第 1 步 = 0.8m，第 2 步 = 1.5m……

    注意：本函数不做速度异常过滤（不跳过 GPS 漂移点），
    调用方如需过滤，应结合 calculate_speed() 自行判断。

    参数：
        trackpoints: 轨迹点列表（按时间顺序排列）

    返回：
        长度与 trackpoints 相同的列表，每个元素是从起点到该点的累计距离（米）。
        第一个元素固定是 0.0。
    """
    if not trackpoints:
        return []

    distances = [0.0]
    cumulative = 0.0

    for i in range(1, len(trackpoints)):
        prev = trackpoints[i - 1]
        curr = trackpoints[i]

        seg_dist = haversine(prev.lat, prev.lon, curr.lat, curr.lon)
        cumulative += seg_dist
        distances.append(cumulative)

    return distances
