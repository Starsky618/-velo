"""
GPX 解析器——"成绩单批改员"。

把骑行码表导出的 GPX 文件（一大堆 XML 标签）翻译成结构化的骑行数据：
轨迹点列表 + 统计摘要（距离、时间、速度、爬升、心率、功率等）。

这是一个纯函数模块：只做计算，不碰数据库、不碰网络。
输入 GPX 字节流，输出一个字典，就像一台"翻译机"。

好比你交了一份手写的骑行日记（GPX），这个模块负责把它整理成
打印版的成绩单（结构化数据），方便后续存档和展示。

注意事项：
- 不 import 任何数据库模块、不 import User/Activity 模型
- 卡路里计算中的 weight 由调用方传入，本模块不访问用户数据
- 心率/功率/踏频从 GPX extensions 尝试提取，取不到为 None
- 爬升去噪阈值 2m、速度异常阈值 120km/h，都是经验值
"""

import math

import gpxpy
import gpxpy.gpx


class GPXParseError(Exception):
    """GPX 解析失败时的自定义异常"""
    pass


# ==================== 地理计算工具 ====================

# 地球平均半径（米），用于 haversine 公式
_EARTH_RADIUS = 6371000

# 爬升去噪阈值：相邻两点高差小于 2m 不算爬升，排除 GPS 高程抖动
_ELEVATION_THRESHOLD = 2.0

# 速度异常阈值：相邻两点算出的速度超过 120km/h，视为 GPS 漂移
# 公路骑行正常速度一般不超过 80km/h，120km/h 是留了很大余量的上限
_MAX_SPEED_KMH = 120.0


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    计算两个经纬度坐标之间的球面距离（米）。

    haversine 公式是计算地球上两点距离的经典方法。
    想象地球是一个完美的球，沿着球面走的最短路径叫"大圆距离"，
    这个公式算的就是这个距离。

    精度说明：对于骑行距离（几十到几百公里），误差 <0.3%，完全够用。
    """
    # 角度转弧度（三角函数需要弧度制输入）
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    # haversine 公式的核心：先算半正矢值 a，再算角距离 c
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))

    return _EARTH_RADIUS * c


# ==================== 扩展字段提取 ====================

def _get_extension_value(point, tag_names: list[str]) -> int | None:
    """
    从 GPX trackpoint 的 extensions 中提取传感器数据（心率/功率/踏频）。

    不同品牌的码表（Garmin、Wahoo、igpsport 等）用的 XML 标签名不完全一样，
    所以传入一个候选标签名列表，依次尝试匹配。
    gpxpy 已经帮我们处理了大部分命名空间问题。
    """
    if point.extensions is None:
        return None

    for ext in point.extensions:
        # 递归搜索所有子节点
        for elem in ext.iter():
            # 去掉命名空间前缀，只比较标签本名
            # 例如 "{http://ns.garmin.com}hr" → "hr"
            local_name = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            if local_name in tag_names and elem.text:
                try:
                    return int(float(elem.text))
                except (ValueError, TypeError):
                    continue
    return None


# ==================== 核心解析函数 ====================

def parse_gpx(content: bytes | str, weight: float = 70.0) -> dict:
    """
    解析 GPX 文件，返回结构化的骑行数据。

    参数：
        content: GPX 文件内容（bytes 或 str）
        weight: 骑行者体重（kg），用于无功率时估算卡路里，默认 70kg

    返回：
        包含 trackpoints、统计摘要、splits 的字典（格式见 spec）

    异常：
        GPXParseError: 文件格式错误或无轨迹数据
    """

    # ===== 第一步：XML 解析 =====
    # 如果是 bytes，先解码为 str
    if isinstance(content, bytes):
        # 跳过可能存在的 BOM（Byte Order Mark，某些编辑器会在文件头加这个标记）
        if content.startswith(b"\xef\xbb\xbf"):
            content = content[3:]
        content = content.decode("utf-8")
    else:
        # str 类型也可能有 BOM 字符（Unicode 版本的 BOM）
        if content.startswith("\ufeff"):
            content = content[1:]

    try:
        gpx = gpxpy.parse(content)
    except Exception:
        raise GPXParseError("文件格式错误")

    # ===== 第二步：提取所有轨迹点 =====
    raw_points = []
    for track in gpx.tracks:
        for segment in track.segments:
            for point in segment.points:
                raw_points.append(point)

    if not raw_points:
        raise GPXParseError("文件无轨迹数据")

    # 从 GPX 元数据中提取标题（可能为 None）
    title = gpx.tracks[0].name if gpx.tracks and gpx.tracks[0].name else None

    # ===== 第三步：逐点计算距离、爬升、速度 =====
    trackpoints = []        # 输出的结构化轨迹点列表
    total_distance = 0.0    # 累计距离（米）
    total_elevation = 0.0   # 累计爬升（米）
    max_speed = 0.0         # 最大速度（km/h）

    # 传感器数据的标签名候选列表
    # 不同品牌码表用不同的标签名，列出常见的候选
    hr_tags = ["hr", "heartrate", "HeartRate"]
    cad_tags = ["cad", "cadence", "Cadence"]
    power_tags = ["power", "Power", "watts", "Watts", "pwr"]

    for i, point in enumerate(raw_points):
        # 提取传感器数据
        hr = _get_extension_value(point, hr_tags)
        cad = _get_extension_value(point, cad_tags)
        power = _get_extension_value(point, power_tags)

        tp = {
            "seq": i,
            "lat": point.latitude,
            "lon": point.longitude,
            "ele": point.elevation,          # 可能为 None
            "time": point.time,              # 可能为 None
            "hr": hr,
            "cad": cad,
            "power": power,
        }
        trackpoints.append(tp)

        # 从第二个点开始，计算与前一个点的距离和高差
        if i > 0:
            prev = raw_points[i - 1]

            # 两点之间的水平距离
            seg_dist = _haversine(prev.latitude, prev.longitude,
                                  point.latitude, point.longitude)

            # 速度异常检测：有时间戳才能算速度
            if point.time and prev.time:
                seg_time = (point.time - prev.time).total_seconds()
                if seg_time > 0:
                    seg_speed_kmh = (seg_dist / seg_time) * 3.6
                    if seg_speed_kmh > _MAX_SPEED_KMH:
                        # GPS 漂移，这段距离不计入总距离
                        continue
                    if seg_speed_kmh > max_speed:
                        max_speed = seg_speed_kmh

            total_distance += seg_dist

            # 爬升计算：只累加正爬升，且去噪（高差 >2m 才算）
            if point.elevation is not None and prev.elevation is not None:
                ele_diff = point.elevation - prev.elevation
                if ele_diff > _ELEVATION_THRESHOLD:
                    total_elevation += ele_diff

    # ===== 第四步：计算总时间和平均速度 =====
    started_at = trackpoints[0]["time"]
    finished_at = trackpoints[-1]["time"]

    # 有时间戳才能算时间和速度
    if started_at and finished_at:
        duration = int((finished_at - started_at).total_seconds())
        avg_speed = (total_distance / duration) * 3.6 if duration > 0 else 0.0
    else:
        duration = None
        avg_speed = None
        max_speed = None

    # ===== 第五步：传感器数据统计（心率/功率/踏频）=====
    # 只统计有值的点，None 的点不参与均值计算
    hr_values = [tp["hr"] for tp in trackpoints if tp["hr"] is not None]
    power_values = [tp["power"] for tp in trackpoints if tp["power"] is not None]
    cad_values = [tp["cad"] for tp in trackpoints if tp["cad"] is not None]

    avg_hr = round(sum(hr_values) / len(hr_values), 1) if hr_values else None
    max_hr = max(hr_values) if hr_values else None
    avg_power = round(sum(power_values) / len(power_values), 1) if power_values else None
    max_power = max(power_values) if power_values else None
    avg_cadence = round(sum(cad_values) / len(cad_values), 1) if cad_values else None

    # ===== 第六步：卡路里估算 =====
    calories = None
    if duration and duration > 0:
        if avg_power is not None:
            # 有功率：基于功率的精确估算
            # 公式：avg_power(W) * duration(s) / 1000 * 3.6 * 0.25（25%机械效率）
            calories = round(avg_power * duration / 1000 * 3.6 * 0.25, 1)
        else:
            # 无功率：粗估，假设骑行 MET=8（中等强度）
            # 公式：duration(h) * weight(kg) * 8 MET
            calories = round(duration / 3600 * weight * 8, 1)

    # ===== 第七步：每 10km 分段统计 =====
    splits = _calculate_splits(trackpoints, raw_points, total_distance)

    # ===== 组装结果 =====
    return {
        "title": title,
        "started_at": started_at,
        "finished_at": finished_at,
        "distance": round(total_distance, 1),
        "duration": duration,
        "elevation_gain": round(total_elevation, 1),
        "avg_speed": round(avg_speed, 1) if avg_speed is not None else None,
        "max_speed": round(max_speed, 1) if max_speed is not None else None,
        "avg_power": avg_power,
        "max_power": max_power,
        "avg_hr": avg_hr,
        "max_hr": max_hr,
        "avg_cadence": avg_cadence,
        "calories": calories,
        "trackpoints": trackpoints,
        "splits": splits,
    }


# ==================== 分段统计 ====================

def _calculate_splits(trackpoints: list[dict], raw_points: list, total_distance: float) -> list[dict]:
    """
    每 10km 切一刀，计算每段的平均速度、功率、心率、爬升。

    好比马拉松的分段计时：每到一个 10km 标记点，记录这段的用时和配速，
    帮助选手分析自己"前半程快还是后半程快"。

    最后一段可能不足 10km，标注为 "40-48.2"（实际距离）。
    """
    if len(trackpoints) < 2:
        return []

    splits = []
    split_km = 10.0                 # 每段 10km
    cumulative_dist = 0.0           # 当前累计距离（米）
    split_start_dist = 0.0          # 当前分段起点的累计距离
    split_start_idx = 0             # 当前分段起点在 trackpoints 中的索引

    for i in range(1, len(trackpoints)):
        prev_pt = raw_points[i - 1]
        curr_pt = raw_points[i]

        seg_dist = _haversine(prev_pt.latitude, prev_pt.longitude,
                              curr_pt.latitude, curr_pt.longitude)

        # 速度异常检查（与主循环一致）
        if curr_pt.time and prev_pt.time:
            seg_time = (curr_pt.time - prev_pt.time).total_seconds()
            if seg_time > 0 and (seg_dist / seg_time) * 3.6 > _MAX_SPEED_KMH:
                continue

        cumulative_dist += seg_dist

        # 检查是否跨过了下一个 10km 标记点
        next_split_m = (len(splits) + 1) * split_km * 1000
        if cumulative_dist >= next_split_m:
            split = _make_split(
                trackpoints, split_start_idx, i + 1,
                split_start_dist, next_split_m,
                len(splits), split_km,
            )
            splits.append(split)
            split_start_dist = next_split_m
            split_start_idx = i

    # 最后一段（可能不足 10km）
    if split_start_idx < len(trackpoints) - 1:
        last_dist_km = round((cumulative_dist - split_start_dist) / 1000, 1)
        if last_dist_km > 0:
            start_km = len(splits) * split_km
            split = _make_split(
                trackpoints, split_start_idx, len(trackpoints),
                split_start_dist, cumulative_dist,
                len(splits), last_dist_km, is_last=True,
            )
            splits.append(split)

    return splits


def _make_split(
    trackpoints: list[dict],
    start_idx: int, end_idx: int,
    start_dist: float, end_dist: float,
    split_num: int, split_km: float,
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

    # 分段标签：如 "0-10", "10-20", "40-48.2"
    start_label = int(split_num * 10) if not is_last else round(split_num * 10, 1)
    end_label = round(start_label + split_km, 1)
    # 整数标签去掉小数点
    if start_label == int(start_label):
        start_label = int(start_label)
    if end_label == int(end_label):
        end_label = int(end_label)
    km_label = f"{start_label}-{end_label}"

    # 分段时间（秒）
    seg_speed = None
    if (len(segment_points) >= 2
            and segment_points[0]["time"] is not None
            and segment_points[-1]["time"] is not None):
        seg_time = (segment_points[-1]["time"] - segment_points[0]["time"]).total_seconds()
        if seg_time > 0:
            seg_speed = round((seg_dist / seg_time) * 3.6, 1)

    # 分段内传感器均值（None 的点不参与）
    powers = [p["power"] for p in segment_points if p["power"] is not None]
    hrs = [p["hr"] for p in segment_points if p["hr"] is not None]

    seg_avg_power = round(sum(powers) / len(powers), 1) if powers else None
    seg_avg_hr = round(sum(hrs) / len(hrs), 1) if hrs else None

    # 分段爬升
    seg_elevation = 0.0
    for j in range(1, len(segment_points)):
        prev_ele = segment_points[j - 1]["ele"]
        curr_ele = segment_points[j]["ele"]
        if prev_ele is not None and curr_ele is not None:
            diff = curr_ele - prev_ele
            if diff > _ELEVATION_THRESHOLD:
                seg_elevation += diff

    return {
        "km": km_label,
        "avg_speed": seg_speed,
        "avg_power": seg_avg_power,
        "avg_hr": seg_avg_hr,
        "elevation_gain": round(seg_elevation, 1),
    }
