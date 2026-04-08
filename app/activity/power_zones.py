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
