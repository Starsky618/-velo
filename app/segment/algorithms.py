"""
赛段算法纯函数——"赛道的三把测量尺"。

放三个不碰数据库、不碰文件系统的纯函数：
1. _haversine_distance：两个 GPS 点的地表实际距离（米）
2. calculate_max_gradient：一段轨迹里最陡的 100 米滑窗坡度（%）
3. calculate_difficulty：综合距离/爬升/最陡坡度 → 4 档难度枚举

为什么这 3 个住单独文件，不进 service.py：
- service.py 是"编排层"——管 CRUD、查 DB、调用各路函数串起业务流程
- 这 3 个是"纯算法"——只接收原始参数返回纯数据，无副作用
- 职责完全不同，混在一起会让 service.py 越来越臃肿（CLAUDE.md 健康度规则）
- 项目其他纯函数也都各居其室：matcher.py / simplify.py / power_zones.py / detector.py
  这次新增延续这个习惯

算法相关的"业务编排"（比如调用算法后写 DB / 缓存失效）住 service.py，
本文件只管"给我数据，我返计算结果"，调用方负责其他事。

操作注意事项：
- 这里**不允许 import 任何 ORM / DB / Redis / 文件系统**（破纯函数承诺）
- _haversine_distance 加下划线前缀表示"模块内部用"，外部调用方应当用 service 里
  的高阶函数；如果某天发现某模块也需要算 GPS 距离，再把它升级成公开 API
"""

import math


def _haversine_distance(
    lat1: float, lon1: float, lat2: float, lon2: float,
) -> float:
    """
    两个 GPS 坐标的地表直线距离（米）。haversine 球面三角公式。

    可以理解成"用地球当一个完美球面，两点之间走最短弧线的长度"。
    比直接 sqrt((lat2-lat1)² + (lon2-lon1)²) 准——后者把地球当平面，
    经纬度本身是角度不是米，远距离会越算越偏。

    参数：lat / lon 都是十进制度数（不是 dms），如 30.2741, 120.1551
    返回：距离米。理论可超 20000km，但本项目最长一条赛段也就几十 km。
    """
    R = 6_371_000.0  # 地球平均半径（米）
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    # 浮点误差兜底：理论上 0 <= a <= 1，但近对跖点（地球两侧对称点）
    # 浮点累计可能让 a 微超 1.0（实测 a=1.0000000000000002），
    # 接下来 sqrt(1-a) 会传入负数 → ValueError: math domain error。
    # 用 min(a, 1.0) 钳位，对正常坐标无任何影响（因 a 本来就 <= 1）。
    a = min(a, 1.0)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def calculate_max_gradient(trackpoints: list) -> float:
    """
    从一段轨迹找出"最陡的 100 米"，返回该段坡度百分比。

    算法：
    1. 算累计距离数组 cumulative_dist[i] = 从起点到第 i 个点的总距离（米）
    2. 双指针滑窗：i 起点向后推 j 直到 cumulative_dist[j] - cumulative_dist[i] >= 100m
    3. 每个 (i, j) 窗口算 |海拔差| / 实际距离 * 100，取所有窗口最大值

    为什么用"100m 滑窗"不取"两个相邻点"：
    相邻轨迹点可能间距 5-10m，海拔差 1m → 算出 10-20% 假坡度（GPS 噪声放大）。
    100m 窗口平滑掉噪声，反映"持续陡坡"的真实强度。

    参数：
        trackpoints: list[Trackpoint] 按 seq 升序，每个有 latitude / longitude / elevation 属性
    返回：
        float 最大坡度百分比（0 到 ~30）；下面情况返 0.0：
        - 列表为空或只 1 个点（无法形成窗口）
        - 全部点海拔为 None（GPS 没记录高度）
        - 所有窗口海拔相同（纯水平骑行）

    陷阱 #1（CLAUDE.md）：elevation 用 `is None` 检查，不要 `if ele`——
    0.0 米是合法海拔（沿海地区），truthiness 会误判
    """
    if len(trackpoints) < 2:
        return 0.0

    WINDOW_M = 100.0  # 100 米滑窗

    # 累计距离：从第 0 个点开始算到每个点
    cumulative_dist = [0.0]
    for i in range(1, len(trackpoints)):
        d = _haversine_distance(
            trackpoints[i - 1].latitude, trackpoints[i - 1].longitude,
            trackpoints[i].latitude, trackpoints[i].longitude,
        )
        cumulative_dist.append(cumulative_dist[-1] + d)

    max_grad = 0.0
    j = 0
    for i in range(len(trackpoints)):
        # j 单调推进，找到第一个让窗口距离 >= 100m 的 j
        # 因为 i 也在递增，前面 j 走过的不用重来 → 整体 O(n) 不是 O(n²)
        while (
            j < len(trackpoints)
            and cumulative_dist[j] - cumulative_dist[i] < WINDOW_M
        ):
            j += 1
        if j >= len(trackpoints):
            break

        ele_start = trackpoints[i].elevation
        ele_end = trackpoints[j].elevation
        if ele_start is None or ele_end is None:
            continue

        actual_dist = cumulative_dist[j] - cumulative_dist[i]
        if actual_dist <= 0:
            continue

        gradient = abs(ele_end - ele_start) / actual_dist * 100
        if gradient > max_grad:
            max_grad = gradient

    return max_grad


def calculate_difficulty(
    distance_m: float,
    elevation_gain_m: float,
    max_gradient_pct: float,
) -> str:
    """
    综合"距离 + 总爬升 + 最陡坡度" 三个指标，输出 4 档难度评级。

    PRD §3.1 定性偏好（按 Tim 实际骑行经验拍板）：
    - extreme：max_gradient > 15% 或 总爬升 > 1500m
              直观："90% 普通骑手要走着上山"
    - hard：   max_gradient > 10% 或 总爬升 > 800m
              直观："FTP 200W 以下会被拉爆"
    - medium： max_gradient > 5%  或 总爬升 > 300m
              直观："中级骑手能完成但有挑战"
    - easy：   其他
              直观："新手友好，热身用"

    判定顺序从严到松——一旦命中 extreme 就不会被降级到 hard。
    用 "或" 不用 "且"：一条 5km 平路有一段 20% 短陡坡，整段评 'extreme' 才合理
    （骑过那段你会哭），不能因为"总爬升不到 1500m"就给 medium。

    返回值：'easy' / 'medium' / 'hard' / 'extreme'（CHECK 约束 §2.1，DB 层兜底）
    """
    if max_gradient_pct > 15 or elevation_gain_m > 1500:
        return "extreme"
    if max_gradient_pct > 10 or elevation_gain_m > 800:
        return "hard"
    if max_gradient_pct > 5 or elevation_gain_m > 300:
        return "medium"
    return "easy"
