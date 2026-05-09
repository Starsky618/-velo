"""
轨迹简化器——"照片压缩机"。

原始 GPX 轨迹可能有几万个点，全传给前端太重了（几 MB 的 JSON）。
这个模块用 Douglas-Peucker 算法把轨迹"瘦身"到约 800 个点，
肉眼几乎看不出区别，但数据量缩小了 10-50 倍。

算法原理：
想象你用一根橡皮筋连接轨迹的起点和终点，
然后找离橡皮筋最远的那个点——如果远到"一眼就能看出弯了"（超过阈值 epsilon），
就把这个点保留，然后递归处理两半段。
如果最远的点也离橡皮筋很近（不超过 epsilon），说明这段轨迹接近直线，
中间的点全扔掉也不影响形状。

epsilon 越大 → 扔掉的点越多 → 输出越少
epsilon 越小 → 保留的点越多 → 输出越多
所以通过二分搜索 epsilon，可以让输出点数接近目标值（±20%）。

注意事项：
- 这是纯函数，不碰数据库
- 输出只保留 lat/lon/ele（绘图三要素），不含时间和传感器数据
- 输入点数 < target_count 时直接返回，不做多余操作
- 始终保留首尾两个点（轨迹的起点和终点不能丢）
"""

import math


def simplify_track(trackpoints: list[dict], target_count: int = 1500) -> list[dict]:
    """
    对轨迹点做 Douglas-Peucker 简化，返回精简后的坐标列表。

    参数：
        trackpoints: parse_gpx() 输出的轨迹点列表（需要 lat, lon, ele 字段）
        target_count: 目标点数，默认 1500（v3 polish hotfix v5 / 800 → 1500）
            提高动机：山区 track 跳点频率是城市 10x+（curl 实测 user 2 山区 >500m segment=76）
            提高到 1500 后山区跳点频率 ~减半 / 实线比例 87% → 93% / 视觉更"贴道"
            数据量代价：simplified_track JSON 增 ~80% / setData 5MB → 9MB（仍 < 微信软上限）

    返回：
        [{lat, lon, ele}, ...] 精简列表，点数接近 target_count（±20%）
    """
    # 提取绘图三要素，丢弃时间和传感器数据
    points = [
        {"lat": tp["lat"], "lon": tp["lon"], "ele": tp.get("ele")}
        for tp in trackpoints
    ]

    # 点数已经够少，不需要简化
    if len(points) <= target_count:
        return points

    # 二分搜索 epsilon，让简化后的点数接近 target_count（±20%）
    lo = 0.0
    # 上界用 bounding box 对角线，比 _max_distance 更健壮。
    # _max_distance 只算首尾连线的最大偏移，在绕圈赛（轨迹折叠）场景可能偏小，
    # 导致二分搜索无法把点数降到目标范围。对角线一定 >= 任何子段内的点线距离。
    hi = _bounding_box_diagonal(points)
    # 容差范围：target_count 的 ±20%
    min_count = int(target_count * 0.8)
    max_count = int(target_count * 1.2)

    # 最多搜索 50 轮，精度足够了（2^50 ≈ 10^15）
    # 跟踪最接近目标的结果，而不是最后一轮（DP 有跳变特性，最后一轮不一定最好）
    best_result = points
    best_diff = abs(len(points) - target_count)

    for _ in range(50):
        mid = (lo + hi) / 2
        simplified = _douglas_peucker(points, mid)
        count = len(simplified)

        if min_count <= count <= max_count:
            # 在目标范围内，直接返回
            return simplified

        # 记录离目标最近的结果
        diff = abs(count - target_count)
        if diff < best_diff:
            best_diff = diff
            best_result = simplified

        if count > max_count:
            # 点太多，加大 epsilon（扔掉更多点）
            lo = mid
        else:
            # 点太少，减小 epsilon（保留更多点）
            hi = mid

    # 50 轮后仍未精确命中范围，返回最接近目标的结果
    return best_result


def _douglas_peucker(points: list[dict], epsilon: float) -> list[dict]:
    """
    标准 Douglas-Peucker 算法（迭代版，避免深递归栈溢出）。

    用栈模拟递归：每次取一段轨迹，找离首尾连线最远的点，
    如果距离 > epsilon 就在该点处切开，两半段入栈继续处理。
    """
    n = len(points)
    if n <= 2:
        return points

    # keep[i] = True 表示第 i 个点被保留
    keep = [False] * n
    keep[0] = True      # 首点必须保留
    keep[n - 1] = True  # 尾点必须保留

    # 用栈代替递归：栈中存放待处理的区间 (start, end)
    stack = [(0, n - 1)]

    while stack:
        start, end = stack.pop()
        if end - start < 2:
            continue

        # 在 [start+1, end-1] 范围内找离 start-end 连线最远的点
        max_dist = 0.0
        max_idx = start
        for i in range(start + 1, end):
            d = _point_to_line_distance(points[i], points[start], points[end])
            if d > max_dist:
                max_dist = d
                max_idx = i

        # 如果最远距离 > epsilon，保留该点并递归处理两半段
        if max_dist > epsilon:
            keep[max_idx] = True
            stack.append((start, max_idx))
            stack.append((max_idx, end))

    return [points[i] for i in range(n) if keep[i]]


def _point_to_line_distance(point: dict, line_start: dict, line_end: dict) -> float:
    """
    计算一个点到一条线段的垂直距离。

    这里用的是简化版的平面距离（经纬度直接当平面坐标），
    对于骑行轨迹（局部范围，非跨大洋）精度完全够用。
    如果要更精确可以用球面距离，但计算量会大很多，DP 简化不需要这个精度。
    """
    # 线段的方向向量
    dx = line_end["lon"] - line_start["lon"]
    dy = line_end["lat"] - line_start["lat"]

    # 线段长度的平方（避免开方，提升性能）
    line_len_sq = dx * dx + dy * dy

    if line_len_sq == 0:
        # 首尾重合，距离就是点到首点的距离
        return math.sqrt(
            (point["lon"] - line_start["lon"]) ** 2
            + (point["lat"] - line_start["lat"]) ** 2
        )

    # 点在线段上的投影位置（0=首点，1=尾点）
    t = ((point["lon"] - line_start["lon"]) * dx
         + (point["lat"] - line_start["lat"]) * dy) / line_len_sq

    # 限制在 [0, 1] 范围内（投影落在线段外时，取线段端点）
    t = max(0.0, min(1.0, t))

    # 投影点的坐标
    proj_lon = line_start["lon"] + t * dx
    proj_lat = line_start["lat"] + t * dy

    # 点到投影点的距离
    return math.sqrt((point["lon"] - proj_lon) ** 2 + (point["lat"] - proj_lat) ** 2)


def _bounding_box_diagonal(points: list[dict]) -> float:
    """
    计算所有点构成的 bounding box（最小外接矩形）的对角线长度。
    用作二分搜索 epsilon 的上界——任何子段内点到线段的距离都不会超过这个值。

    比 _max_distance（首尾连线最大偏移）更健壮：
    在绕圈赛等轨迹折叠场景中，首尾连线偏移可能很小，
    但 bounding box 对角线能正确反映轨迹的空间范围。
    """
    if len(points) <= 1:
        return 0.0
    lats = [p["lat"] for p in points]
    lons = [p["lon"] for p in points]
    return math.sqrt((max(lats) - min(lats)) ** 2 + (max(lons) - min(lons)) ** 2)
