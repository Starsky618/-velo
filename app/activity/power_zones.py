"""
功率区间计算器——"训练强度分析仪"。

根据用户的 FTP（功能阈值功率）和轨迹中的功率数据，
计算骑行时间在 6 个强度区间（Z1-Z6）的分布。

好比把速度表盘分成 6 个颜色段：
绿色（恢复）→ 蓝色（耐力）→ 黄色（节奏）→ 橙色（阈值）→ 红色（VO2max）→ 紫色（无氧）
骑行者通过查看自己在每个颜色段待了多久，来判断训练强度是否合理。

这是纯函数模块：只做计算，不碰数据库。
从 gpx_parser.py 拆分出来，保持单文件 <500 行的健康度。

注意事项：
- 调用方负责判断用户是否设了 FTP，未设 FTP 时不应调用此函数
- power 为 None 的轨迹点不参与计算
- 时间差归入前一个点的功率对应区间
"""

# 6 个功率区间的定义（基于 FTP 百分比）
_POWER_ZONES = [
    {"zone": "Z1", "name": "恢复",    "min_pct": 0.0,  "max_pct": 0.55},
    {"zone": "Z2", "name": "耐力",    "min_pct": 0.55, "max_pct": 0.75},
    {"zone": "Z3", "name": "节奏",    "min_pct": 0.75, "max_pct": 0.90},
    {"zone": "Z4", "name": "阈值",    "min_pct": 0.90, "max_pct": 1.05},
    {"zone": "Z5", "name": "VO2max", "min_pct": 1.05, "max_pct": 1.20},
    {"zone": "Z6", "name": "无氧",    "min_pct": 1.20, "max_pct": None},  # 无上限
]


def calculate_power_zones(trackpoints: list[dict], ftp: int) -> list[dict] | None:
    """
    根据用户 FTP 和轨迹中的功率数据，计算骑行时间在 6 个强度区间的分布。

    好比体检报告的分项评分：你的骑行总成绩已经算好了，
    这个函数把它按"恢复/耐力/节奏/阈值/VO2max/无氧"六个档位拆开，
    看你在每个档位各待了多少时间、占比多少。

    参数：
        trackpoints: parse_gpx() 输出的轨迹点列表（需要 power 和 time 字段）
        ftp: 用户的 FTP（功能阈值功率，单位 W）

    返回：
        6 个区间的列表，每个包含 zone/name/min_w/max_w/seconds/percent
        如果轨迹中没有任何功率数据，返回 None
    """
    if len(trackpoints) < 2 or ftp <= 0:
        return None

    # 初始化每个区间的累计时间（秒）
    zone_seconds = [0] * 6
    total_power_seconds = 0

    # 遍历相邻轨迹点，把每段时间归入对应功率区间
    for i in range(1, len(trackpoints)):
        prev_tp = trackpoints[i - 1]
        curr_tp = trackpoints[i]

        # 前一个点必须有功率数据，两个点都必须有时间戳
        if prev_tp["power"] is None or prev_tp["time"] is None or curr_tp["time"] is None:
            continue

        # 计算两点之间的时间差（秒）
        dt = (curr_tp["time"] - prev_tp["time"]).total_seconds()
        if dt <= 0:
            continue

        # 按前一个点的功率值，判断属于哪个区间
        power_w = prev_tp["power"]
        zone_idx = _get_zone_index(power_w, ftp)

        zone_seconds[zone_idx] += dt
        total_power_seconds += dt

    # 没有任何有效的功率数据 → 返回 None
    if total_power_seconds == 0:
        return None

    # 组装输出
    # min_w 规则：Z1 从 0 开始，后续每个区间的 min_w = 前一个区间 max_w + 1
    # 这样相邻区间不重叠，比如 Z1(0-129), Z2(130-176)
    result = []
    for i, zone_def in enumerate(_POWER_ZONES):
        # max_w：区间上限（Z6 无上限，为 None）
        max_w = int(ftp * zone_def["max_pct"]) if zone_def["max_pct"] is not None else None

        # min_w：Z1 从 0 开始，其余从前一个区间上限+1 开始
        if i == 0:
            min_w = 0
        else:
            min_w = result[i - 1]["max_w"] + 1

        # 百分比 = 该区间秒数 / 总有功率秒数 * 100，四舍五入到整数
        seconds = round(zone_seconds[i])
        percent = round(seconds / total_power_seconds * 100)

        result.append({
            "zone": zone_def["zone"],
            "name": zone_def["name"],
            "min_w": min_w,
            "max_w": max_w,
            "seconds": seconds,
            "percent": percent,
        })

    return result


def _get_zone_index(power_w: int, ftp: int) -> int:
    """
    根据功率值和 FTP，判断属于哪个功率区间（返回 0-5 的索引）。

    从高到低检查：先看是不是 Z6（最高），再看 Z5……最后兜底 Z1。
    """
    ratio = power_w / ftp
    if ratio >= 1.20:
        return 5  # Z6 无氧
    elif ratio >= 1.05:
        return 4  # Z5 VO2max
    elif ratio >= 0.90:
        return 3  # Z4 阈值
    elif ratio >= 0.75:
        return 2  # Z3 节奏
    elif ratio >= 0.55:
        return 1  # Z2 耐力
    else:
        return 0  # Z1 恢复


# ═══════════════════════════════════════════════════════════════════════════
# 功率曲线（v5 Sprint 2 task-2.B.1 新增）
#
# 与上方 calculate_power_zones 的关系：
# - calculate_power_zones：上传时算"6 个强度区间各待了多久"（GPX parser dict 入参）
# - calculate_power_curve：用户主动看时算"1s/5s/.../20min 各档最大平均功率"
#   （Trackpoint ORM 对象入参——detector 和 service 都从 DB 读取，不走 GPX parser）
#
# 两个函数 API 不一致是有意的：上游数据格式不同。GPX 上传时用 dict，DB 查询用 ORM。
# 各自接现成的格式，不互相强转换。
# ═══════════════════════════════════════════════════════════════════════════

# 6 档时长档位（行业标准 / Strava）：1s / 5s / 30s / 1min / 5min / 20min
_DEFAULT_POWER_CURVE_WINDOWS = [1, 5, 30, 60, 300, 1200]


def calculate_power_curve(
    trackpoints: list,
    windows_sec: list[int] | None = None,
) -> dict:
    """
    时长分桶最大平均功率曲线——"功率擂台赛"。

    把单次骑行想象成一段连续的功率折线图。这个函数对每个时长档位（1 秒 / 5 秒 / ……）
    在折线上滑动一个窗口，找出窗口内"平均功率"最高的那一段——
    就像问"你在这次骑行里，连续 5 分钟功率最高的一段平均输出了多少瓦"。
    Strava 的 power curve 图就是这么算的。

    算法：对每个 window（秒），找连续 N 个 trackpoints（N ≈ window）的最大平均功率。
    假设 trackpoints 大致 1Hz 采样（GPX 标准）。非均匀采样精度受影响。

    陷阱 #1（truthiness）：power=0 是合法值（休息段就是 0W），用 `tp.power is not None`，
    **不能写 `tp.power or 0`**——后者会把 0 当 None 兜底，吞掉合法 0 值。

    ⚠️ 不允许跨 activity 拼接 trackpoints：本函数语义是"单次骑行内的滑窗最大平均"。
    跨 N 次骑行算 period 最佳，必须对每个 activity 独立调本函数，再取 per-window max——
    见 calculate_power_curve_from_activities。直接拼 list 会让"5min 最佳"出现跨日合并的虚假极值。

    参数：
        trackpoints: list[Trackpoint] 单个 activity 内、按 seq / created_at 升序，
            含 power（int|None，单位 W）属性。可空。
        windows_sec: list[int] 时长档位（秒）。None 用默认 6 档 [1,5,30,60,300,1200]。

    返回：
        dict[int → float] window_sec → max_avg_power_W。空入参或全 None 返全 0。
    """
    if windows_sec is None:
        windows_sec = list(_DEFAULT_POWER_CURVE_WINDOWS)

    if not trackpoints:
        return {w: 0.0 for w in windows_sec}

    # 排序保险：调用方未排序时也能正常算。按 seq 升序对应"骑行时间顺序"。
    tps = sorted(trackpoints, key=lambda tp: tp.seq)
    powers = [tp.power if tp.power is not None else 0 for tp in tps]
    n = len(powers)

    if n == 0:
        return {w: 0.0 for w in windows_sec}

    # 前缀和加速 O(n) per window：prefix[i] = powers[0..i-1] 之和
    # 任意 [i, i+window) 的平均 = (prefix[i+window] - prefix[i]) / window
    prefix = [0.0] * (n + 1)
    for i in range(n):
        prefix[i + 1] = prefix[i] + powers[i]

    result = {}
    for window in windows_sec:
        if window > n:
            # 数据点不足一个 window → fallback 用全部数据平均
            # 例：只有 30 秒数据但要算 1200 秒 window，就算这 30 秒的整体平均
            result[window] = prefix[n] / n if n > 0 else 0.0
            continue

        max_avg = 0.0
        for i in range(n - window + 1):
            avg = (prefix[i + window] - prefix[i]) / window
            if avg > max_avg:
                max_avg = avg
        result[window] = max_avg

    return result


def calculate_power_curve_from_activities(
    activities_trackpoints: list[list],
    windows_sec: list[int] | None = None,
) -> dict:
    """
    跨 N 个 activity 的时长分桶最大平均功率曲线——"period 内的最佳曲线"。

    场景：算"上月你 5 分钟最佳功率多少？" → 上月可能有 12 次骑行，每次都有自己的曲线。
    这个函数对每次骑行独立算 calculate_power_curve，再对每档 window 取所有骑行里的 max。
    比如 5 分钟 window：A 骑行最佳 240W、B 骑行最佳 220W → 上月 5 分钟最佳 = 240W。

    ⚠️ 禁止跨 activity 拼接 trackpoints：原跨 activity 拼接的算法语义错误
    （activity A 末尾 + activity B 开头算 5min 平均会拼接出虚假窗口——
    这两段实际相隔几天，平均成"一段连续功率"违反"5min 最佳"的语义）。
    必须每个 activity 独立算后再取 max，这样才是真实的"单次骑行最佳"。

    参数：
        activities_trackpoints: list[list[Trackpoint]]，每个内层 list 是
            **单 activity** 的 trackpoints（绝不允许内层是多 activity 拼接）
        windows_sec: list[int] 时长档位（秒）。None 用默认 6 档。

    返回：
        dict[int → float] window_sec → max_avg_power_W（取所有 activity 的 per-window max）
    """
    if windows_sec is None:
        windows_sec = list(_DEFAULT_POWER_CURVE_WINDOWS)

    if not activities_trackpoints:
        return {w: 0.0 for w in windows_sec}

    result = {w: 0.0 for w in windows_sec}
    for tps in activities_trackpoints:
        if not tps:
            continue
        curve = calculate_power_curve(tps, windows_sec)
        for w in windows_sec:
            if curve[w] > result[w]:
                result[w] = curve[w]

    return result
