"""
统计计算器——"成绩单计算器"。

GPX 文件只有原始轨迹点，没有统计摘要（总距离、平均速度、爬升等），
需要我们自己从轨迹点逐个计算出来。这个模块就是干这件事的。

好比你参加一场没有计时芯片的马拉松，只有手机记录了每隔几秒的 GPS 位置。
赛后你拿着这些位置数据，自己算总距离、配速、爬升——这就是这个模块做的事。

FIT 和 Strava 自带摘要数据（设备端或服务端已经算好），不走这个模块。
只有 GPX 需要用这个"计算器"。

模块内提供 3 个函数：
1. calculate_summary：从轨迹点算出完整的 ActivitySummary（成绩单）
2. calculate_splits：每 10km 切一刀，算出每段的配速/功率/心率/爬升
3. calculate_calories：卡路里估算（有功率用功率公式，无功率用粗估法）

注意事项：
- 纯函数模块，不碰数据库、不碰文件系统
- 依赖 types.py（数据结构）和 geo_math.py（距离/爬升计算）
- 速度单位统一 m/s（不是 km/h），包括 splits 里的 avg_speed
- 输入的 trackpoints 应该已经填好 speed 和 distance（GPX 解析器负责填）
"""

from app.parsing.geo_math import (
    calculate_elevation_gain,
    haversine,
)
from app.parsing.types import ActivitySummary, Trackpoint


# ==================== 核心函数 ====================


def calculate_summary(
    trackpoints: list[Trackpoint],
    weight: float = 70.0,
) -> ActivitySummary:
    """
    从轨迹点计算完整的统计摘要——GPX 专用的"成绩单生成器"。

    FIT 文件自带设备端计算的摘要（更准），Strava 自带服务端计算的摘要，
    都不需要走这个函数。只有 GPX（纯轨迹数据，没有摘要）才需要。

    参数：
        trackpoints: 轨迹点列表（已填好 speed 和 distance 字段）
        weight: 骑行者体重（kg），用于卡路里估算，默认 70kg

    返回：
        ActivitySummary — 完整的统计摘要

    异常：
        ValueError: trackpoints 为空列表时抛出
    """
    if not trackpoints:
        raise ValueError("trackpoints 不能为空列表，无法生成统计摘要")

    # ===== 1. 总距离 =====
    # 取最后一个有 distance 值的点，就是从起点到终点的总距离
    total_distance = _get_total_distance(trackpoints)

    # ===== 2. 时间 =====
    started_at = trackpoints[0].time
    finished_at = trackpoints[-1].time

    if started_at and finished_at:
        duration = int((finished_at - started_at).total_seconds())
    else:
        duration = None

    # ===== 3. 爬升 =====
    elevation_gain = calculate_elevation_gain(trackpoints)

    # ===== 4. 速度统计 =====
    # avg_speed 用"总距离÷总时间"（与旧版 gpx_parser 一致），
    # 不用逐点速度平均——后者会被停车点拉偏，且非等时采样导致权重不均
    avg_speed: float | None = None
    max_speed: float | None = None

    if duration and duration > 0 and total_distance > 0:
        avg_speed = round(total_distance / duration, 2)  # m/s

    # max_speed 从逐点速度取最大值（已被 geo_math.calculate_speed 过滤过 GPS 漂移）
    speed_values = [tp.speed for tp in trackpoints if tp.speed is not None]
    if speed_values:
        max_speed = round(max(speed_values), 2)

    # ===== 5. 传感器统计（心率/功率/踏频）=====
    hr_values = [tp.hr for tp in trackpoints if tp.hr is not None]
    power_values = [tp.power for tp in trackpoints if tp.power is not None]
    cad_values = [tp.cad for tp in trackpoints if tp.cad is not None]

    avg_hr = round(sum(hr_values) / len(hr_values), 1) if hr_values else None
    max_hr = max(hr_values) if hr_values else None
    avg_power = round(sum(power_values) / len(power_values), 1) if power_values else None
    max_power = max(power_values) if power_values else None
    avg_cadence = round(sum(cad_values) / len(cad_values), 1) if cad_values else None

    # ===== 6. 卡路里 =====
    calories = calculate_calories(avg_power, duration, weight)

    # ===== 7. 分段统计 =====
    splits = calculate_splits(trackpoints)

    # ===== 8. 移动时间 =====
    # 去掉停车段（速度 < 1 m/s ≈ 3.6 km/h）的有效骑行时间
    moving_time = _calculate_moving_time(trackpoints, duration)

    # ===== 组装成绩单 =====
    return ActivitySummary(
        distance=round(total_distance, 1),
        duration=duration,
        moving_time=moving_time,
        elevation_gain=round(elevation_gain, 1),
        avg_speed=avg_speed,
        max_speed=max_speed,
        avg_power=avg_power,
        max_power=max_power,
        avg_hr=avg_hr,
        max_hr=max_hr,
        avg_cadence=avg_cadence,
        calories=calories,
        started_at=started_at,
        finished_at=finished_at,
        splits=splits if splits else None,
        normalized_power=None,  # GPX 无法计算标准化功率，只有 FIT 自带
    )


def calculate_splits(
    trackpoints: list[Trackpoint],
    split_km: float = 10.0,
) -> list[dict]:
    """
    每 N 公里切一刀，计算每段的配速、功率、心率、爬升。

    好比马拉松的分段计时：每到一个 10km 标记点，记录这段的用时和配速，
    帮助选手分析自己"前半程快还是后半程快"。

    新版改进：直接读 Trackpoint.distance（累计距离），不再自己算 haversine，
    因为 GPX 解析器在创建 Trackpoint 时已经算好了（而且已过滤 GPS 漂移）。

    参数：
        trackpoints: 轨迹点列表（需要 .distance 字段已填充）
        split_km: 分段长度（km），默认 10km

    返回：
        分段统计列表，每段包含 {km, avg_speed, avg_power, avg_hr, elevation_gain}
        最后一段可能不足 split_km，标注为 "40-48.2"（实际距离）
    """
    if len(trackpoints) < 2:
        return []

    # 检查是否有距离数据（GPX 解析器应该已经填好了）
    if trackpoints[-1].distance is None:
        return _calculate_splits_fallback(trackpoints, split_km)

    splits = []
    split_start_idx = 0
    split_start_dist = 0.0
    split_m = split_km * 1000  # 分段长度（米）

    for i, tp in enumerate(trackpoints):
        if tp.distance is None:
            continue

        # 检查是否跨过了下一个分段标记点
        next_split_m = (len(splits) + 1) * split_m
        if tp.distance >= next_split_m:
            split = _make_split(
                trackpoints, split_start_idx, i + 1,
                split_start_dist, next_split_m,
                len(splits), split_km,
            )
            splits.append(split)
            split_start_dist = next_split_m
            split_start_idx = i

    # 最后一段（可能不足 split_km）
    total_dist = trackpoints[-1].distance
    if total_dist is not None and split_start_idx < len(trackpoints) - 1:
        last_dist_km = round((total_dist - split_start_dist) / 1000, 1)
        if last_dist_km > 0:
            split = _make_split(
                trackpoints, split_start_idx, len(trackpoints),
                split_start_dist, total_dist,
                len(splits), last_dist_km, is_last=True,
            )
            splits.append(split)

    return splits


def calculate_calories(
    avg_power: float | None,
    duration: int | None,
    weight: float,
) -> float | None:
    """
    卡路里估算——两种方法二选一。

    方法 1（有功率计）：基于功率的精确估算
        公式：avg_power(W) × duration(s) ÷ 1000 × 3.6 × 0.25
        其中 0.25 是人体骑行的平均机械效率（约 25%，即身体消耗 4 焦耳能量
        才能产生 1 焦耳的踏板输出功率，其余 75% 变成了热量）

    方法 2（无功率计）：基于 MET 的粗估
        公式：duration(h) × weight(kg) × 8
        MET=8 是中等强度骑行的代谢当量（安静坐着 MET=1）

    参数：
        avg_power: 平均功率（W），无功率计为 None
        duration: 骑行时长（秒），无时间戳为 None
        weight: 骑行者体重（kg）

    返回：
        估算卡路里（kcal），无法计算时返回 None
    """
    if duration is None or duration <= 0:
        return None

    if avg_power is not None:
        # 有功率：精确估算
        return round(avg_power * duration / 1000 * 3.6 * 0.25, 1)
    else:
        # 无功率：MET 粗估
        return round(duration / 3600 * weight * 8, 1)


# ==================== 内部辅助函数 ====================


def _calculate_moving_time(
    trackpoints: list[Trackpoint],
    duration: int | None,
) -> int | None:
    """
    移动时间——去掉停车段的有效骑行时间（秒）。

    标准 Strava 口径：相邻两点平均速度 ≥ 1 m/s（≈ 3.6 km/h）视为"在动"，
    累加这段时间差；< 1 m/s 视为停车（等红灯 / 拍照 / 喝水）不计入。

    特殊情况：
    - trackpoints 没有 speed 数据（老 GPX 文件未经速度补全）→ 返回 duration
      （视为全程在动，前端显示和"全程耗时"相同）
    - 相邻两点时间差 > 60 秒：可能是 GPS 信号丢失或设备 sleep，
      此段不计入移动时间（保守过滤）

    参数：
        trackpoints: 已填好 speed 字段的轨迹点
        duration: 全程耗时（秒），fallback 用

    返回：
        移动时间（秒）。无 trackpoints 或无 duration 时返回 None。
    """
    if not trackpoints or duration is None:
        return None

    has_speed = any(tp.speed is not None for tp in trackpoints)
    if not has_speed:
        return duration

    moving_threshold = 1.0  # m/s，Strava 主流标准
    moving_seconds = 0.0

    for i in range(1, len(trackpoints)):
        prev = trackpoints[i - 1]
        curr = trackpoints[i]
        if prev.time is None or curr.time is None:
            continue

        # 相邻两点速度均值（None 视为 0，等同停下）
        v_prev = prev.speed if prev.speed is not None else 0.0
        v_curr = curr.speed if curr.speed is not None else 0.0
        avg_v = (v_prev + v_curr) / 2

        if avg_v >= moving_threshold:
            delta = (curr.time - prev.time).total_seconds()
            # 防 GPS 信号丢失 / 设备 sleep 大 gap 污染统计
            if 0 < delta < 60:
                moving_seconds += delta

    return int(moving_seconds)


def _get_total_distance(trackpoints: list[Trackpoint]) -> float:
    """
    从轨迹点列表中取总距离。

    优先取最后一个点的 .distance（累计距离），
    如果没有则用 haversine 逐段累加作为兜底。
    """
    if not trackpoints:
        return 0.0

    # 优先：最后一个点的累计距离
    last_dist = trackpoints[-1].distance
    if last_dist is not None:
        return last_dist

    # 兜底：自己算 haversine 逐段累加
    total = 0.0
    for i in range(1, len(trackpoints)):
        prev = trackpoints[i - 1]
        curr = trackpoints[i]
        total += haversine(prev.lat, prev.lon, curr.lat, curr.lon)
    return total


def _make_split(
    trackpoints: list[Trackpoint],
    start_idx: int,
    end_idx: int,
    start_dist: float,
    end_dist: float,
    split_num: int,
    split_km: float,
    is_last: bool = False,
) -> dict:
    """
    计算单个分段的统计数据。

    参数：
        trackpoints: 全量轨迹点列表
        start_idx, end_idx: 这个分段在 trackpoints 中的起止索引
        start_dist, end_dist: 这个分段的起止累计距离（米）
        split_num: 第几个分段（从 0 开始）
        split_km: 这个分段的长度（km），最后一段可能 <10
        is_last: 是否是最后一段
    """
    segment_points = trackpoints[start_idx:end_idx]
    seg_dist = end_dist - start_dist  # 米

    # 分段标签：直接用实际起止距离算，如 "0-10", "10-20", "40-48.2"
    # 不依赖 split_num × 常量，这样无论分段长度是 5km 还是 10km 都正确
    start_km = start_dist / 1000
    end_km = end_dist / 1000
    # 整数标签去掉小数点（"10" 而不是 "10.0"）
    start_label = int(start_km) if start_km == int(start_km) else round(start_km, 1)
    end_label = int(end_km) if end_km == int(end_km) else round(end_km, 1)
    km_label = f"{start_label}-{end_label}"

    # 分段速度（m/s）：用分段距离÷分段时间
    seg_speed = None
    if (len(segment_points) >= 2
            and segment_points[0].time is not None
            and segment_points[-1].time is not None):
        seg_time = (segment_points[-1].time - segment_points[0].time).total_seconds()
        if seg_time > 0:
            seg_speed = round(seg_dist / seg_time, 2)  # m/s

    # 分段内传感器均值（None 的点不参与）
    powers = [p.power for p in segment_points if p.power is not None]
    hrs = [p.hr for p in segment_points if p.hr is not None]

    seg_avg_power = round(sum(powers) / len(powers), 1) if powers else None
    seg_avg_hr = round(sum(hrs) / len(hrs), 1) if hrs else None

    # 分段爬升（复用 geo_math 的计算，保持去噪逻辑一致）
    seg_elevation = calculate_elevation_gain(segment_points)

    return {
        "km": km_label,
        "avg_speed": seg_speed,
        "avg_power": seg_avg_power,
        "avg_hr": seg_avg_hr,
        "elevation_gain": round(seg_elevation, 1),
    }


def _calculate_splits_fallback(
    trackpoints: list[Trackpoint],
    split_km: float,
) -> list[dict]:
    """
    当 Trackpoint.distance 未填充时的兜底方案——自己用 haversine 算距离。

    正常流程不应走到这里（GPX 解析器应该填好 distance），
    但作为防御性编程保留此路径。
    """
    if len(trackpoints) < 2:
        return []

    splits = []
    cumulative_dist = 0.0
    split_start_dist = 0.0
    split_start_idx = 0
    split_m = split_km * 1000

    for i in range(1, len(trackpoints)):
        prev = trackpoints[i - 1]
        curr = trackpoints[i]

        seg_dist = haversine(prev.lat, prev.lon, curr.lat, curr.lon)
        cumulative_dist += seg_dist

        next_split_m = (len(splits) + 1) * split_m
        if cumulative_dist >= next_split_m:
            split = _make_split(
                trackpoints, split_start_idx, i + 1,
                split_start_dist, next_split_m,
                len(splits), split_km,
            )
            splits.append(split)
            split_start_dist = next_split_m
            split_start_idx = i

    # 最后一段
    if split_start_idx < len(trackpoints) - 1:
        last_dist_km = round((cumulative_dist - split_start_dist) / 1000, 1)
        if last_dist_km > 0:
            split = _make_split(
                trackpoints, split_start_idx, len(trackpoints),
                split_start_dist, cumulative_dist,
                len(splits), last_dist_km, is_last=True,
            )
            splits.append(split)

    return splits
