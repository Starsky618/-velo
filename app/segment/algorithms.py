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


def _smooth_elevations(
    elevations: list[float | None], window: int = 15,
) -> list[float | None]:
    """
    对海拔序列做移动中位数平滑，过滤 GPS 海拔尖刺。

    为什么用中位数不用均值：
    GPS 海拔噪声常是孤立尖刺（某一点突然跳 10-15m），均值会被尖刺拉偏，
    中位数对孤立异常点不敏感——好比 11 个评委里有 1 个乱打分，
    取中位数那个评委不受影响，取均值整体被拉跑。

    为什么 window=15（保守选择）：
    velo 轨迹点平均间距 5-10m，window=15 跨距约 75-150m。
    - 单点尖刺：几乎完美压制（1 个 +15m 异常 in 15 个 ±0m 邻居 → 中位数 ≈ 真值）
    - 连续随机噪声：**仅部分压制**——平滑窗口跨度 75-150m，跟 100m 算坡度窗口
      只能部分重叠（实测 26.1% 仅降到 10-15%）。
      要彻底压到 < 5% 需要 window ≥ 41，但会平掉 200m 短陡坡 → 不可接受
    - 真陡坡保护：window=15 对 200m+ 持续陡坡几乎无损失

    诚实声明（spec 审实测）：
    本算法是"尖刺压制器"不是"全噪声消除器"。对生产 segment 24 "夜骑清徐"
    （v1=26.1%），v2 + window=15 预期降到 ~10-15% 区间（difficulty 从 extreme → hard）。
    最后 cap 25% 是兜底，不是常态修复。

    彻底压到接近真实坡度（如夜骑清徐真实 ≈ 0.5%）需要 Step 3 引入"多用户骑行
    数据群体融合"——同一赛段被骑 N 次后同位置取群体中位数 → GPS 噪声平均到接近 0。
    现单用户阶段算法极限即此。

    None 处理：
    窗口内全部 None → 当前点保持 None（GPS 整段没记高度）。
    部分 None → 只用有数据的点算中位数。

    参数：
        elevations: 原始海拔序列（list[float | None]）
        window: 滑窗大小，应为奇数；偶数会取下中位数；默认 15
    返回：
        list[float | None] 与输入等长的平滑后序列
    """
    n = len(elevations)
    if n == 0:
        return []
    half = window // 2
    smoothed: list[float | None] = []
    for i in range(n):
        left = max(0, i - half)
        right = min(n, i + half + 1)
        vals = [e for e in elevations[left:right] if e is not None]
        if not vals:
            smoothed.append(None)
        else:
            vals.sort()
            smoothed.append(vals[len(vals) // 2])
    return smoothed


def calculate_max_gradient(
    trackpoints: list,
    smooth_window: int = 15,
    cap_pct: float = 25.0,
) -> float:
    """
    从一段轨迹找出"最陡的 100 米"，返回该段坡度百分比。

    算法（v2 / 2026-05-14 加 GPS 噪声压制）：
    0. **先把海拔序列做移动中位数平滑**——压掉 GPS 单点尖刺（详 _smooth_elevations）
    1. 算累计距离数组 cumulative_dist[i] = 从起点到第 i 个点的总距离（米）
    2. 双指针滑窗：i 起点向后推 j 直到 cumulative_dist[j] - cumulative_dist[i] >= 100m
    3. 每个 (i, j) 窗口用 **平滑后的海拔** 算 |海拔差| / 实际距离 * 100
    4. 取所有窗口最大值，最后 cap 在 cap_pct（默认 25%，业界 sanity 上限）

    为什么 v1 不够：
    v1 直接用原始 trackpoints 海拔算窗口坡度——问题在 backfill 路径下，
    某条赛段会汇集 N 个用户的全部 trackpoint（密度 5-10m / 海拔噪声 ±15m），
    只要任一对相邻 100m 窗口起点低估 + 终点高估 → 立刻算出 26% 假坡度。
    生产真踩过这个坑（segment 24 "夜骑清徐" 11km 平路报 26.1%）。

    为什么 cap 25%：
    国际自行车联盟（UCI）公路赛事最陡爬坡极少超过 20%。25% 是世界顶级硬核路段
    的上限（如比利时阿登 Koppenberg / Mur de Huy），更陡的几乎都是越野山路。
    超过 25% 几乎可断定 GPS 噪声，cap 掉是 safety net 而非常态修复。

    参数：
        trackpoints: list[Trackpoint] 按 seq 升序，每个有 latitude / longitude / elevation 属性
        smooth_window: 海拔平滑窗口大小（点数），默认 15
        cap_pct: 坡度上限百分比，超过此值 cap 掉，默认 25.0
    返回：
        float 最大坡度百分比（0 到 cap_pct）；下面情况返 0.0：
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

    # 海拔预平滑：先做一遍，下面所有窗口都用平滑后的值
    raw_elevations = [tp.elevation for tp in trackpoints]
    smoothed_elevations = _smooth_elevations(raw_elevations, window=smooth_window)

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

        ele_start = smoothed_elevations[i]
        ele_end = smoothed_elevations[j]
        if ele_start is None or ele_end is None:
            continue

        actual_dist = cumulative_dist[j] - cumulative_dist[i]
        if actual_dist <= 0:
            continue

        gradient = abs(ele_end - ele_start) / actual_dist * 100
        if gradient > max_grad:
            max_grad = gradient

    # Cap 在 25%——超出几乎可断定 GPS 噪声残留（最后一道防线）
    if max_grad > cap_pct:
        max_grad = cap_pct

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
