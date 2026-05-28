"""
功率曲线纯计算模块——“拿一把尺子沿整条骑行滑，找平均功率最高的那一段”。

这个文件只做数学。不查 DB、不读文件、不调外部 API。所有函数只接收基础数据
（list / dict / 整数），返回基础数据。和 power_zones.py / simplify.py 同一类
——纯函数模块，service.py 负责把 DB row 喂进来、把结果端给 router。

对外接口（service.py 用到的）：
- DurationOutOfRange         —— router 用它把 400 和 404 分开
- _POWER_CURVE_BENCHMARKS_SEC —— Strava 常见成绩时长（5s/15s/30s/...）
- _sample_indices             —— 等间隔挑 N 个索引，timeseries 也用
- _empty_activity_power_curve —— 没功率时的统一空响应
- _activity_elapsed_seconds   —— 从轨迹首尾 timestamp 算 elapsed 秒数
- _power_seconds_from_rows    —— 把稀疏 trackpoint 还原成“每秒一个功率”的数组
- _prefix_power               —— 前缀和，O(1) 查任意窗口总功率
- _best_power_effort_from_prefix —— 给定持续时长，找最佳平均功率的那一段
- _candidate_power_curve_durations / _downsample_durations / _build_power_curve_result
  —— 把秒级数组打包成前端能直接画图的响应

操作注意事项：
- 函数命名带下划线 = 对 router / 测试外部"包内私有"——service.py 作为同包中间层可以直接调用，
  router 不应该绕过 service 直接 import 这里的下划线函数
- 改这里的逻辑必须更新 tests/test_activity_power_curve_analysis.py
- **删除本模块前**：_sample_indices 被 service._sample_indices_by_distance 借用（timeseries 路径），
  必须先把它迁回 service.py 或 sampling helper 模块，否则 timeseries 整条路径会 NameError
"""

from __future__ import annotations


class DurationOutOfRange(ValueError):
    """duration_sec 不合法（≤0 或超出活动总长）——router 据此返回 400 而不是 404。"""


# Strava Best Efforts 常见功率时长点。
# 曲线本身支持任意秒数；这些点只是前端直接标注和快速读取的“路标”。
_POWER_CURVE_BENCHMARKS_SEC = [
    5, 15, 30, 60, 120, 180, 300, 480, 600, 900, 1200, 1800, 2700, 3600, 7200
]


def _sample_indices(total: int, max_points: int) -> list[int]:
    """
    等间隔采样——从 total 个点中选出 max_points 个的索引。
    确保首尾点都包含。点数不足时全部保留。
    """
    if total <= max_points:
        return list(range(total))
    return [round(i * (total - 1) / (max_points - 1)) for i in range(max_points)]


def _empty_activity_power_curve(max_duration_sec: int = 0) -> dict:
    """构造“没有可展示功率”的统一返回，避免各入口各写一版空态。"""
    return {
        "has_power": False,
        "max_duration_sec": max(0, int(max_duration_sec or 0)),
        "points": [],
        "benchmarks": {},
        "resolution_label": "无功率数据",
    }


def _activity_elapsed_seconds(rows) -> int:
    """
    计算这条 activity 的 elapsed time 秒数。

    只用 trackpoint 首尾 timestamp。

    这张图的承诺是“从原始点重算本次 activity”，所以最长可查询时长也必须来自原始点。
    activity.duration 可能来自上游摘要字段；一旦它比轨迹点更长，就会给曲线尾部补一段假 0W。
    """
    timestamps = [row.timestamp for row in rows if row.timestamp is not None]
    if len(timestamps) >= 2:
        span = int((timestamps[-1] - timestamps[0]).total_seconds())
        if span > 0:
            return span
    return 0


def _power_seconds_from_rows(rows, max_duration_sec: int) -> tuple[list[int], bool]:
    """
    把稀疏 trackpoints 还原成“每 1 秒一个功率”的数组。

    类比把几张关键帧补成一段视频：
    - 相邻点间隔 0~60 秒：认为前一个点的功率覆盖这段时间。
    - 间隔大于 60 秒：像码表睡着了，中间填 0W，避免伪造持续输出。
    - power=None：按 0W 进入平均值，但 has_power 仍只看原始点有没有真实功率。
    """
    if max_duration_sec <= 0:
        return [], False

    timestamps = [row.timestamp for row in rows if row.timestamp is not None]
    if len(timestamps) < 2:
        return [], any(row.power is not None for row in rows)

    start_ts = timestamps[0]
    seconds = [0] * max_duration_sec
    has_power = any(row.power is not None for row in rows)

    for idx in range(1, len(rows)):
        prev = rows[idx - 1]
        curr = rows[idx]
        if prev.timestamp is None or curr.timestamp is None:
            continue

        start = int((prev.timestamp - start_ts).total_seconds())
        end = int((curr.timestamp - start_ts).total_seconds())
        if end <= start:
            continue

        start = max(0, min(start, max_duration_sec))
        end = max(0, min(end, max_duration_sec))
        if end <= start:
            continue

        gap = (curr.timestamp - prev.timestamp).total_seconds()
        value = int(prev.power) if (prev.power is not None and 0 < gap <= 60) else 0
        for sec in range(start, end):
            seconds[sec] = value

    return seconds, has_power


def _prefix_power(power_by_second: list[int]) -> list[float]:
    """前缀和：prefix[i] 表示前 i 秒的功率总和，用来 O(1) 查任意窗口总功率。"""
    prefix = [0.0] * (len(power_by_second) + 1)
    for idx, value in enumerate(power_by_second):
        prefix[idx + 1] = prefix[idx] + value
    return prefix


def _best_power_effort_from_prefix(prefix: list[float], duration_sec: int) -> dict:
    """
    查某个持续时长下的最佳平均功率。

    例：duration_sec=4080，就是拿一把 1小时08分 的尺子沿整条骑行逐秒滑动，
    找平均功率最高的那一段，并返回这段从第几秒开始。

    duration_sec 不合法（≤0 或超长）时抛 DurationOutOfRange——
    router 据此分流 400（参数错），而不是 404（活动不存在）。
    """
    total_sec = len(prefix) - 1
    if duration_sec < 1:
        raise DurationOutOfRange("持续时间必须大于 0 秒")
    if total_sec < 1:
        return {
            "has_power": False,
            "duration_sec": duration_sec,
            "best_power_w": None,
            "start_sec": None,
            "end_sec": None,
        }
    if duration_sec > total_sec:
        raise DurationOutOfRange("持续时间超出活动长度")

    best_sum = None
    best_start = 0
    for start in range(0, total_sec - duration_sec + 1):
        window_sum = prefix[start + duration_sec] - prefix[start]
        if best_sum is None or window_sum > best_sum:
            best_sum = window_sum
            best_start = start

    best_power = (best_sum or 0.0) / duration_sec
    return {
        "has_power": True,
        "duration_sec": duration_sec,
        "best_power_w": round(best_power, 1),
        "start_sec": best_start,
        "end_sec": best_start + duration_sec,
    }


def _candidate_power_curve_durations(max_duration_sec: int) -> list[int]:
    """
    生成画曲线用的“聪明时长刻度”。

    不是所有骑行都返回每一秒：短时段密、长时段稀，外加强制保留 Strava 常见成绩点。
    前端若要任意秒数的最终读数，再调精确 effort 接口。
    """
    if max_duration_sec <= 0:
        return []

    durations = {1, max_duration_sec}

    def add_range(start: int, end: int, step: int) -> None:
        capped_end = min(end, max_duration_sec)
        if start > capped_end:
            return
        durations.update(range(start, capped_end + 1, step))

    add_range(1, 20 * 60, 1)
    add_range(20 * 60 + 5, 60 * 60, 5)
    add_range(60 * 60 + 15, 2 * 60 * 60, 15)
    add_range(2 * 60 * 60 + 30, 4 * 60 * 60, 30)
    add_range(4 * 60 * 60 + 60, max_duration_sec, 60)

    for benchmark in _POWER_CURVE_BENCHMARKS_SEC:
        if benchmark <= max_duration_sec:
            durations.add(benchmark)

    return sorted(durations)


def _downsample_durations(durations: list[int], max_points: int, max_duration_sec: int) -> list[int]:
    """
    把候选时长压到前端可承受的点数，同时保留关键 benchmark。

    这和 timeseries 的按距离抽样是同一思想：图上点数有限，但关键路标不能丢。
    """
    if len(durations) <= max_points:
        return durations

    keep = {1, max_duration_sec}
    keep.update(b for b in _POWER_CURVE_BENCHMARKS_SEC if b <= max_duration_sec)
    if len(keep) >= max_points:
        return sorted(keep)[:max_points]

    rest = [duration for duration in durations if duration not in keep]
    budget = max_points - len(keep)
    if budget > 0 and rest:
        positions = _sample_indices(len(rest), budget)
        keep.update(rest[pos] for pos in positions)
    return sorted(keep)


def _build_power_curve_result(power_by_second: list[int], max_points: int) -> dict:
    """用秒级功率数组生成前端画图响应。"""
    max_duration_sec = len(power_by_second)
    prefix = _prefix_power(power_by_second)
    durations = _candidate_power_curve_durations(max_duration_sec)
    durations = _downsample_durations(durations, max_points, max_duration_sec)

    points = [
        {
            key: value
            for key, value in _best_power_effort_from_prefix(prefix, duration).items()
            if key != "has_power"
        }
        for duration in durations
    ]

    benchmarks = {}
    for duration in _POWER_CURVE_BENCHMARKS_SEC:
        if duration > max_duration_sec:
            continue
        effort = _best_power_effort_from_prefix(prefix, duration)
        benchmarks[str(duration)] = {k: v for k, v in effort.items() if k != "has_power"}

    return {
        "has_power": True,
        "max_duration_sec": max_duration_sec,
        "points": points,
        "benchmarks": benchmarks,
        "resolution_label": f"智能 {len(points)} 点 / 支持精确到秒查询",
    }
