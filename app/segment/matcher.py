"""
GPS 精确匹配算法——"赛道裁判"���

判断一条骑行轨��是否经过了某条赛段，好比田径比赛的电子计时系统：
1. 选手跑过起点 → 触发计时（找到 start_index）
2. 选手跑���终点 → 停止计时��找到 end_index）
3. 检查有没有抄近路 → 覆盖率校验（大部分轨迹点都在赛道附近才算数）
4. 算出用时 → elapsed_time

这是一个"纯函数"模块——只做数学计算，不碰数据库、不碰网络、不碰文件。
好比一个只带计算器和卷尺的裁判：你把数据给我，我算完把结果还你。

核心概念：
- haversine 距离：地球表面两点之间的弧线距离（考虑地球曲率）
- tolerance（容差）：轨迹点距赛道参考线多近才算"在赛道上"，默认 50 米
- match_ratio（覆盖率）：轨迹点中有多大比例在容差内才算匹配成���，默认 80%
- 点到折线距离：轨迹点到参考线（由多段线段组成）的最短距离

注意事项：
- trackpoints 必须有 time 字段（无时间戳直接返回不��配）
- 多次经过同一赛段取第一次（找到起点后从起点之后找终点）
- 所有距离计算用 haversine，单位是米
- 本模块无任何外部依赖，可独立测试
"""

import math
from datetime import datetime


# ==================== haversine 距离 ====================

def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    计算两个 GPS 坐标点���间的距离（米）。

    Haversine 公式把地球当成球体，用球面三角学算弧线距离。
    好比在篮球表面两点之间量弧线，而不是直线穿球心。
    """
    R = 6371000  # 地球平均半径（米）
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (math.sin(d_phi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ==================== 点到线段的距离 ====================

def _point_to_segment_distance(
    plat: float, plon: float,
    alat: float, alon: float,
    blat: float, blon: float,
) -> float:
    """
    计算一个点 P 到一条线段 AB 的最短距离（米）。

    原理好比"从你站的位置到一条马路的最近距离"：
    - 如果你正对着马路（投影点落在马路上），最近距离就是垂直距离
    - 如果你在马路端头之外��最近距离就是到端点的距离

    算法步骤：
    1. 用经纬度近似转换为平面坐标（在小范围内误差可忽略）
    2. 计算点 P 在��段 AB 上的投影参数 t（0~1 之间表示投影在线段上）
    3. 找到投影点坐标
    4. 用 haversine 算点 P 到投影点的真实球面距离
    """
    # 经纬度差值近似转换为平面距离的比例
    # 经度的"价值"随纬度变化：赤道上 1 度经度约 111km，北极是 0
    # cos(mid_lat) 就是这个缩放因子
    mid_lat = math.radians((plat + alat + blat) / 3.0)
    cos_lat = max(math.cos(mid_lat), 1e-10)  # 防止极高纬度时 cos→0 导致除零

    # 把经纬度差值转成"伪平面坐标"（单位不重要，只需要比例正确）
    ax = (alon - plon) * cos_lat
    ay = alat - plat
    bx = (blon - plon) * cos_lat
    by = blat - plat

    # 线段 AB 的方向向量
    dx = bx - ax
    dy = by - ay
    seg_len_sq = dx * dx + dy * dy

    if seg_len_sq < 1e-18:
        # A 和 B 重合（线段长度为 0），直接算点到 A 的距离
        return _haversine(plat, plon, alat, alon)

    # 计算投影参数 t：P 在 AB 方向上的投影位置
    # t=0 → 投影在 A 点，t=1 → 投影在 B 点，0<t<1 → 投影在线段上
    t = ((0 - ax) * dx + (0 - ay) * dy) / seg_len_sq
    t = max(0.0, min(1.0, t))  # 限制在 [0, 1]，超出部分取端点

    # 投影点的经纬度（从伪平面坐标反算回来）
    proj_lon = plon + (ax + t * dx) / cos_lat
    proj_lat = plat + (ay + t * dy)

    return _haversine(plat, plon, proj_lat, proj_lon)


# ==================== 点到折线的距��� ====================

def _point_to_polyline_distance(
    plat: float, plon: float,
    coords: list[tuple[float, float]],
) -> float:
    """
    计算一个点到一条折线（由多个线段组成）的最短距离（米���。

    折线就是参考路线——一串坐标点连成的曲线。
    这个函数把折线拆成一段段线段，分别算距离，取最小值。
    好比问"从你家到一条蜿蜒的河最近有多远"——
    把河分成一截截直线，算到每截的距离，最短的那个就是答案。
    """
    min_dist = float("inf")
    for i in range(len(coords) - 1):
        dist = _point_to_segment_distance(
            plat, plon,
            coords[i][0], coords[i][1],
            coords[i + 1][0], coords[i + 1][1],
        )
        if dist < min_dist:
            min_dist = dist
    return min_dist


# ==================== 核心匹配函数 ====================

def match_segment(
    trackpoints: list[dict],
    segment_start: tuple[float, float],
    segment_end: tuple[float, float],
    reference_coords: list[tuple[float, float]],
    match_tolerance: float = 50.0,
    min_match_ratio: float = 0.8,
    endpoint_tolerance: float = 50.0,
    auto_pause_threshold: float = 0.5,
) -> dict:
    """
    判断一条骑行轨迹是否经过了某条赛段。

    参数：
    - trackpoints：骑行轨迹点列表，每个点是 {lat, lon, time, seq}
      lat/lon 为必填（浮点数），time 是 datetime 对象，seq 是轨迹点的序号（整数）。
      注意：数据库 Trackpoint 模型的字段名是 latitude/longitude/timestamp，
      调用方需要映射为 lat/lon/time 再传入（见 Task 4.4 的 service 层）。
    - segment_start���赛段起点坐标 (lat, lon)
    - segment_end：赛段终点坐标 (lat, lon)
    - reference_coords：赛段参考路线坐标列表 [(lat, lon), ...]
    - match_tolerance：匹配容差（米），轨迹点距参考线多近算"在赛道上"
    - min_match_ratio：最低覆盖率，轨迹点中至少多大比例在容差内

    返回：
    - 匹配成功：{matched: True, start_index: int, end_index: int, elapsed_time: int}
    - 匹配失败：{matched: False}

    算法四步走���
    1. 找起点：遍历轨迹点，找到距赛段起点最近且在 tolerance 内的点
    2. ���终点：从起点之后，找到距赛���终点最近且�� tolerance 内的点
    3. ��盖验证：起点到终点之���的轨迹点，算有多少在参考线 tolerance 内
    4. 算用时：end 的 time - start 的 time
    """
    # 防御：轨迹点太少或参考路线太短
    if len(trackpoints) < 2 or len(reference_coords) < 2:
        return {"matched": False}

    # ========== 第 1 步：找起点 ==========
    # 遍历轨迹点，找��一个在 tolerance 内的点作为起点。
    # "多次经过取第一次"：如果骑手两次经过赛段起点区域，取第一次。
    # 好比跑步比赛——第一次越过起跑线就开始计时，不管你之后有没有折返再经过。
    start_idx = -1
    for i, pt in enumerate(trackpoints):
        dist = _haversine(pt["lat"], pt["lon"], segment_start[0], segment_start[1])
        if dist <= endpoint_tolerance:
            start_idx = i
            break

    # 没有任何轨迹点在起点容差范围内 → 骑手没经过赛段起点
    if start_idx == -1:
        return {"matched": False}

    # ========== 第 2 步：找终点 ==========
    # 从起点之后的轨迹点中，找距赛段终点最近的那个（在 tolerance 内）。
    # "从起点之后"保证了方向性——不能反着骑也算。
    # 终点取"最近"而非"第一个"：骑手经过终点区域时，可能有多个点在范围内，
    # 取最接近终点的那个点更精确（减少 GPS 漂移误差对计时的影响）。
    best_end_dist = float("inf")
    end_idx = -1
    for i in range(start_idx + 1, len(trackpoints)):
        pt = trackpoints[i]
        dist = _haversine(pt["lat"], pt["lon"], segment_end[0], segment_end[1])
        if dist < best_end_dist:
            best_end_dist = dist
            end_idx = i

    # 终点不在容差范围内 → 骑手没到达赛段终点
    if best_end_dist > endpoint_tolerance:
        return {"matched": False}

    # ========== 第 3 步：覆盖验证 ==========
    # 检查起点到终点之间的轨迹点，有多少"贴着赛道"走
    # 这一步防止骑���从起点走捷径直达终点，中间根本没沿赛道骑
    segment_points = trackpoints[start_idx:end_idx + 1]
    if len(segment_points) < 2:
        return {"matched": False}

    within_count = 0
    for pt in segment_points:
        dist = _point_to_polyline_distance(
            pt["lat"], pt["lon"], reference_coords,
        )
        if dist <= match_tolerance:
            within_count += 1

    match_ratio = within_count / len(segment_points)
    if match_ratio < min_match_ratio:
        return {"matched": False}

    # ========== 第 4 步：计算 Moving Time（速度 + 时间双条件） ==========
    # 只有"连续低速超过 30 秒"才判定为停车并扣除，偶尔减速不扣。
    #
    # 好比裁判判罚标准：
    # - 骑手在陡坡上蠕行（1~2 km/h 持续几秒然后加速）→ 不扣，人家在拼命骑
    # - 骑手停在路边等红灯（0.5 km/h 持续 40 秒）→ 扣除，确实停了
    #
    # 算法：先给每个时间段标记"快/慢"，然后找出所有"连续慢速 ≥ 30 秒"的区间，
    # 只扣除这些区间的时间。
    PAUSE_DURATION = 30  # 连续低速超过 30 秒才算停车

    # 第一遍：计算每个相邻点对的时间和速度
    intervals = []  # [(dt, is_slow), ...]
    for i in range(start_idx, end_idx):
        t1 = trackpoints[i].get("time")
        t2 = trackpoints[i + 1].get("time")

        if not isinstance(t1, datetime) or not isinstance(t2, datetime):
            continue

        dt = (t2 - t1).total_seconds()
        if dt <= 0:
            continue

        dist = _haversine(
            trackpoints[i]["lat"], trackpoints[i]["lon"],
            trackpoints[i + 1]["lat"], trackpoints[i + 1]["lon"],
        )
        speed_kmh = (dist / dt) * 3.6

        intervals.append((dt, speed_kmh < auto_pause_threshold))

    if not intervals:
        return {"matched": False}

    # 第二遍：找连续低速区间，只扣除累计 ≥ 30 秒的
    # 从头扫描，遇到连续的 is_slow=True 段就累加时间，
    # 直到遇到一个 is_slow=False 的段，检查累计是否 ≥ 30 秒。
    total_time = 0.0    # 总时间
    paused_time = 0.0   # 扣除的停车时间
    slow_streak = 0.0   # 当前连续低速累计秒数

    for dt, is_slow in intervals:
        total_time += dt
        if is_slow:
            slow_streak += dt
        else:
            # 连续低速结束，检查是否够长
            if slow_streak >= PAUSE_DURATION:
                paused_time += slow_streak
            slow_streak = 0.0

    # 处理末尾的连续低速段
    if slow_streak >= PAUSE_DURATION:
        paused_time += slow_streak

    moving_time = total_time - paused_time

    if moving_time <= 0:
        return {"matched": False}

    elapsed_time = int(moving_time)

    return {
        "matched": True,
        "start_index": trackpoints[start_idx]["seq"],
        "end_index": trackpoints[end_idx]["seq"],
        "elapsed_time": elapsed_time,
    }
