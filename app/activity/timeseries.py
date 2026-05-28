"""
时序数据纯计算模块——把原始轨迹点抽样成"前端能直接画图的数组"。

这个文件只做数学和数组打包。不查 DB、不读文件、不调外部 API。所有函数只接收基础
数据（list / dict / ORM row 的字段读取），返回基础数据。和 power_curve.py / power_zones.py
/ simplify.py 同一类——纯函数模块，service.py 负责把 DB row 喂进来、把结果端给 router。

类比：原始 trackpoints 是 4K 视频（每秒几十帧），这里的工作是把它转码成
"距离 X 轴 + 7 条曲线"的可滑动图表。短骑像近距离微距图，长骑像广角全景图。

对外接口（service.get_activity_timeseries 用到的）：
- _distance_values             —— 优先用 DB 距离 / 老数据回退 GPS 累加
- _target_sample_step_m         —— 按总距离决定每米抽多密
- _sample_indices_by_distance   —— 按距离插"路边小旗"（不是按数组序号抽）
- _build_timeseries_arrays      —— 把采样点打包成 distances / elevations / speeds / powers 等数组

操作注意事项：
- 函数命名带下划线 = 对 router / 测试外部"包内私有"——service.py 作为同包中间层可直接调用，
  router 不该绕过 service 直接 import 这里的下划线函数
- 改这里的逻辑必须更新 tests/test_activity_timeseries_pointer.py
- _sample_indices_by_distance 依赖 power_curve._sample_indices（通用抽样工具）；
  power_curve.py 和本模块都不能反过来 import 这边
"""

from __future__ import annotations

from app.activity import power_curve
from app.parsing.geo_math import haversine


# GPS 抖动过滤阈值：骑行不可能超过 120 km/h。
# 单一真相源在 app.parsing.geo_math.MAX_SPEED_MS（120 km/h 换算 m/s）；
# 这里保留 km/h 表示是因为下面 _build_timeseries_arrays 算的 speed 字段是 km/h，
# 直接比较省一次单位换算。改限速时两处需同步。
_MAX_CYCLING_SPEED_KMH = 120


def _target_sample_step_m(total_distance_m: float) -> float:
    """
    按骑行总距离决定"手指每滑一格大概跳多少米"。

    可以把它想成地图缩放：
    - 10km 小地图可以把路灯都画出来，所以 50m 一个点
    - 100km 长骑要看整体节奏，200m 一个点更像 Strava 的分析图
    - 200km+ 超长骑再粗一点，避免前端塞太多点导致图变卡
    """
    if total_distance_m <= 20_000:
        return 50.0
    if total_distance_m <= 80_000:
        return 100.0
    if total_distance_m <= 180_000:
        return 200.0
    return float(min(500.0, max(300.0, total_distance_m / 1000.0)))


def _resolution_label(sample_step_m: float) -> str:
    """把采样距离翻译成人能读懂的标签。"""
    if sample_step_m < 1000:
        return f"约 {int(round(sample_step_m))}m/点"
    return f"约 {round(sample_step_m / 1000, 1)}km/点"


def _cumulative_distances(rows) -> list[float]:
    """
    预计算所有轨迹点的累计距离（米），返回等长数组。

    对全量点逐点累加（而非只算采样点之间的直线距离），
    因为采样点之间可能隔了几十个原始点，直线会"抄近路"，
    比实际骑行距离短。逐点累加才准确。

    内存：50000 个 float ≈ 0.4MB，安全。
    """
    n = len(rows)
    cum = [0.0] * n
    for i in range(1, n):
        cum[i] = cum[i - 1] + haversine(
            rows[i - 1].latitude, rows[i - 1].longitude,
            rows[i].latitude, rows[i].longitude,
        )
    return cum


def _distance_values(rows) -> list[float]:
    """
    优先使用数据库里的累计距离；老数据没有 distance 时再回退 GPS 逐点计算。

    Strava/FIT 已经给了更稳定的 distance stream，这就像码表自己记的里程；
    老 GPX 没有这列时，我们才用经纬度现场补算。
    """
    distances = []
    for row in rows:
        if row.distance is None:
            return _cumulative_distances(rows)
        distances.append(float(row.distance))

    if len(distances) < 2 or distances[-1] <= 0:
        return _cumulative_distances(rows)

    for idx in range(1, len(distances)):
        if distances[idx] < distances[idx - 1]:
            return _cumulative_distances(rows)
    return distances


def _sample_indices_by_distance(
    cum_distances: list[float], sample_step_m: float, max_points: int
) -> list[int]:
    """
    按累计距离抽样，而不是按数组序号抽样。

    用户手指滑图时关心的是"我骑到第几公里发生了什么"，不是"这是第几个原始点"。
    所以这里像在路边每隔一段距离插一面小旗，前端手指会吸附到最近的小旗。
    """
    total = len(cum_distances)
    if total <= 2:
        return list(range(total))

    sampled = [0]
    next_target = sample_step_m
    for idx in range(1, total):
        if cum_distances[idx] + 1e-6 >= next_target:
            sampled.append(idx)
            while next_target <= cum_distances[idx] + 1e-6:
                next_target += sample_step_m

    if sampled[-1] != total - 1:
        sampled.append(total - 1)

    if len(sampled) <= max_points:
        return sampled

    reduced_positions = power_curve._sample_indices(len(sampled), max_points)
    return [sampled[pos] for pos in reduced_positions]


def _build_timeseries_arrays(rows, sampled_indices, cum_distances, sample_step_m) -> dict:
    """
    从采样点构建前端可直接画图的数组。

    每个采样点提取：距离、海拔、速度、功率、心率、踏频。
    速度优先使用 Trackpoint.speed（码表/Strava 已平滑的瞬时速度），
    老数据没有 speed 时再用相邻采样点距离差/时间差补算。
    无传感器数据的字段整个数组返回 None（而非数组里填 None）。
    """
    distances, times, original_indices, elevations, speeds = [], [], [], [], []
    powers_list, hr_list, cadence_list = [], [], []
    has_power = has_hr = has_cadence = False
    start_ts = rows[0].timestamp

    for pos, idx in enumerate(sampled_indices):
        row = rows[idx]
        dist_m = cum_distances[idx]

        # 速度：优先取逐点 speed。可以把它理解为码表当时显示的"瞬时速度"。
        speed = None
        if row.speed is not None:
            speed = round(float(row.speed) * 3.6, 1)
            if speed > _MAX_CYCLING_SPEED_KMH:
                speed = None
        elif pos > 0:
            prev_idx = sampled_indices[pos - 1]
            prev_row = rows[prev_idx]
            if row.timestamp and prev_row.timestamp:
                dist_diff = dist_m - cum_distances[prev_idx]
                time_diff = (row.timestamp - prev_row.timestamp).total_seconds()
                if time_diff > 0:
                    speed = round((dist_diff / time_diff) * 3.6, 1)
                    if speed > _MAX_CYCLING_SPEED_KMH:
                        speed = None

        distances.append(round(dist_m / 1000, 3))
        if start_ts and row.timestamp:
            times.append(int((row.timestamp - start_ts).total_seconds()))
        else:
            times.append(None)
        original_indices.append(int(row.seq) if row.seq is not None else int(idx))
        elevations.append(round(row.elevation, 1) if row.elevation is not None else None)
        speeds.append(speed)

        if row.power is not None:
            has_power = True
        powers_list.append(float(row.power) if row.power is not None else None)

        if row.heart_rate is not None:
            has_hr = True
        hr_list.append(float(row.heart_rate) if row.heart_rate is not None else None)

        if row.cadence is not None:
            has_cadence = True
        cadence_list.append(float(row.cadence) if row.cadence is not None else None)

    return {
        "distances": distances,
        "times": times,
        "original_indices": original_indices,
        "sample_step_m": sample_step_m,
        "resolution_label": _resolution_label(sample_step_m),
        "elevations": elevations,
        "speeds": speeds,
        "powers": powers_list if has_power else None,
        "heart_rates": hr_list if has_hr else None,
        "cadences": cadence_list if has_cadence else None,
    }
