"""
FIT 解析器——"第二个翻译官"。

FIT（Flexible and Interoperable Data Transfer）是 Garmin 定义的二进制骑行数据格式。
所有品牌码表（佳明/iGPSport/迈金/Wahoo/Bryton）都支持导出 FIT 文件。
相比 GPX（XML 文本格式），FIT 更紧凑、字段更丰富——自带速度、距离、坡度等，
不需要我们自己算。

好比 GPX 是手写的骑行日记（要自己数总里程），
FIT 是码表自动打印的完整报告（距离、速度、功率全部现成）。

数据流：
  FIT 字节流 → garmin-fit-sdk 解码 → record_mesgs（逐点数据）
  + session_mesgs（摘要统计）→ 组装 Trackpoint 列表 + ActivitySummary
  → simplify_track 简化轨迹 → 组装 ParseResult

注意事项：
- 纯函数模块，不碰数据库、不碰文件系统
- 坐标单位 semicircles → 度：× (180 / 2^31)
- FIT 的 enhanced_speed / enhanced_altitude 优先于旧版字段（精度更高）
- session 摘要是设备端计算的，比我们后算的准，优先使用
- 坐标系固定 WGS84（所有码表硬件都用 GPS 标准坐标）
- 轨迹点上限 50000（内存保护）
"""

from datetime import datetime, timezone

from garmin_fit_sdk import Decoder, Stream

from app.activity.power_zones import calculate_power_zones
from app.activity.simplify import simplify_track
from app.parsing.types import (
    ActivitySummary,
    CoordSystem,
    DataSource,
    ParseMetadata,
    ParseResult,
    Trackpoint,
)


# ==================== 常量 ====================

# semicircles → 度的转换系数
# FIT 用 32 位有符号整数存坐标（semicircles），精度约 0.00001 度（~1.1 米）
_SEMI_TO_DEG = 180.0 / (2 ** 31)

# 轨迹点数量上限（与 GPX 解析器一致）
_MAX_TRACKPOINTS = 50_000


# ==================== 异常类 ====================


class FITParseError(Exception):
    """FIT 解析失败时的自定义异常"""
    pass


# ==================== 核心类 ====================


class FITParser:
    """
    FIT 翻译官——把 FIT 二进制文件翻译成统一的 ParseResult 格式。

    遵循 RideParser Protocol 接口：parse(content, **kwargs) -> ParseResult。
    """

    def parse(self, content: bytes, **kwargs) -> ParseResult:
        """
        解析 FIT 文件，返回统一格式的 ParseResult。

        参数：
            content: FIT 文件字节流
            **kwargs:
                weight (float): 骑行者体重（kg），默认 70，用于卡路里兜底估算
                ftp (int): 用户 FTP，有值时计算功率区间
                file_hash (str): 文件 SHA-256 哈希

        返回：
            ParseResult（坐标固定 WGS84，无需坐标归一化）

        异常：
            FITParseError: 文件格式错误、无轨迹数据、非骑行活动、轨迹点过多
        """
        ftp = kwargs.get("ftp")
        file_hash = kwargs.get("file_hash")

        # ===== 1. FIT 解码 =====
        messages = _decode_fit(content)

        # ===== 2. 提取逐点数据 =====
        record_mesgs = messages.get("record_mesgs", [])
        if not record_mesgs:
            raise FITParseError("文件无轨迹数据")

        if len(record_mesgs) > _MAX_TRACKPOINTS:
            raise FITParseError(
                f"轨迹点过多（{len(record_mesgs)}），上限 {_MAX_TRACKPOINTS}"
            )

        trackpoints = _build_trackpoints(record_mesgs)

        if not trackpoints:
            raise FITParseError("文件无有效轨迹点（所有点缺少坐标）")

        # ===== 3. 运动类型校验 =====
        session_mesgs = messages.get("session_mesgs", [])
        if session_mesgs:
            sport = _safe_get(session_mesgs[0], "sport")
            # convert_types_to_strings=True 下 sport 是字符串如 "cycling"
            if sport and sport not in ("cycling", "e_biking"):
                raise FITParseError(f"非骑行活动（sport={sport}）")

        # ===== 4. 提取摘要（设备端计算，优先使用）=====
        summary = _build_summary(session_mesgs, trackpoints)

        # ===== 5. 元数据 =====
        file_id_mesgs = messages.get("file_id_mesgs", [])
        creator = _extract_creator(file_id_mesgs)
        # FIT 文件通常没有用户自定义标题，设为 None 让 Worker 兜底
        title = None

        metadata = ParseMetadata(
            source=DataSource.FIT,
            coord_system=CoordSystem.WGS84,  # 码表硬件固定 WGS84
            title=title,
            creator=creator,
            file_hash=file_hash,
        )

        # ===== 5. 轨迹简化 =====
        tp_dicts = [
            {"lat": tp.lat, "lon": tp.lon, "ele": tp.ele}
            for tp in trackpoints
        ]
        simplified = simplify_track(tp_dicts)

        # ===== 6. 功率区间（可选）=====
        power_zones = None
        if ftp and ftp > 0:
            pz_dicts = [
                {"power": tp.power, "time": tp.time}
                for tp in trackpoints
            ]
            power_zones = calculate_power_zones(pz_dicts, ftp)

        # ===== 7. 组装 =====
        return ParseResult(
            trackpoints=trackpoints,
            summary=summary,
            metadata=metadata,
            simplified_track=simplified,
            power_zones=power_zones,
        )


# ==================== 内部函数 ====================


def _decode_fit(content: bytes) -> dict:
    """
    用 garmin-fit-sdk 解码 FIT 二进制文件。

    apply_scale_and_offset=True：自动把原始整数转成物理量
    （如海拔 raw/5-500 → 米，速度 raw/1000 → m/s）。
    但坐标 semicircles 不在自动转换范围内，需要手动转。

    convert_datetimes_to_dates=True：自动把 Garmin epoch 转为 Python datetime。
    """
    try:
        stream = Stream.from_byte_array(content)
        decoder = Decoder(stream)

        if not decoder.is_fit():
            raise FITParseError("文件格式错误：不是有效的 FIT 文件")

        messages, errors = decoder.read(
            apply_scale_and_offset=True,
            convert_datetimes_to_dates=True,
            convert_types_to_strings=True,
            expand_sub_fields=True,
            expand_components=True,
        )

        if errors:
            raise FITParseError(f"FIT 解码错误：{errors[0]}")

        return messages

    except FITParseError:
        raise
    except Exception as e:
        raise FITParseError(f"FIT 文件解码失败：{e}")


def _build_trackpoints(record_mesgs: list) -> list[Trackpoint]:
    """
    从 FIT record 消息列表构建 Trackpoint 列表。

    FIT 的 record 消息自带速度和距离（设备端实时计算），
    不需要像 GPX 那样自己用 haversine 后算。
    但坐标需要从 semicircles 转成度。
    """
    trackpoints = []
    seq = 0

    for record in record_mesgs:
        # 坐标：semicircles → 度（FIT 特有单位）
        raw_lat = _safe_get(record, "position_lat")
        raw_lon = _safe_get(record, "position_long")

        # 跳过无坐标的点（室内骑行台等场景）
        if raw_lat is None or raw_lon is None:
            continue

        # semicircles 可能已被 SDK 转为浮点（取决于版本），也可能是整数
        lat = float(raw_lat) * _SEMI_TO_DEG if abs(float(raw_lat)) > 180 else float(raw_lat)
        lon = float(raw_lon) * _SEMI_TO_DEG if abs(float(raw_lon)) > 180 else float(raw_lon)

        # 海拔：优先 enhanced（分辨率 0.2m），兜底普通版（分辨率 1m）
        # 用 is not None 而非 or，因为 or 会把 0.0（海平面）误判为 falsy
        ele_raw = _safe_get(record, "enhanced_altitude")
        ele = ele_raw if ele_raw is not None else _safe_get(record, "altitude")
        if ele is not None:
            ele = float(ele)

        # 速度：优先 enhanced（m/s），兜底普通版
        speed_raw = _safe_get(record, "enhanced_speed")
        speed = speed_raw if speed_raw is not None else _safe_get(record, "speed")
        if speed is not None:
            speed = float(speed)

        # 距离：累计米（设备端计算）
        distance = _safe_get(record, "distance")
        if distance is not None:
            distance = float(distance)

        # 时间戳：SDK 自动转为 Python datetime
        time = _safe_get(record, "timestamp")
        if time is not None and not isinstance(time, datetime):
            time = None  # 异常值保护

        # 传感器数据
        hr = _safe_get_int(record, "heart_rate")
        cad = _safe_get_int(record, "cadence")
        power = _safe_get_int(record, "power")

        trackpoints.append(Trackpoint(
            seq=seq,
            lat=lat,
            lon=lon,
            ele=ele,
            time=time,
            hr=hr,
            cad=cad,
            power=power,
            speed=speed,
            distance=distance,
        ))
        seq += 1

    return trackpoints


def _build_summary(
    session_mesgs: list,
    trackpoints: list[Trackpoint],
) -> ActivitySummary:
    """
    从 FIT session 消息构建统计摘要。

    FIT 的 session 消息包含设备端计算的统计数据（比我们后算的准）：
    - 距离、时间、爬升都是设备端实时累加的
    - 平均/最大速度、功率、心率也是设备端维护的
    - 标准化功率（NP）只有设备能算，我们后端算不了

    如果某些字段缺失（低端码表可能不报告全部字段），用 trackpoints 兜底。
    """
    session = session_mesgs[0] if session_mesgs else {}

    # 距离（米）
    distance = _safe_get_float(session, "total_distance")
    if distance is None and trackpoints:
        # 兜底：用最后一个 trackpoint 的累计距离
        distance = trackpoints[-1].distance or 0.0

    # 全程耗时（秒，含停车）= elapsed_time
    # 优先 session 的 total_elapsed_time（含设备暂停的真实时间）
    # 兜底 1：total_timer_time（旧 fit_parser 用过的字段，部分老码表只报这个）
    # 兜底 2：首尾时间戳差
    duration = _safe_get_int(session, "total_elapsed_time")
    if duration is None:
        duration = _safe_get_int(session, "total_timer_time")
    if duration is None:
        if trackpoints and trackpoints[0].time and trackpoints[-1].time:
            duration = int((trackpoints[-1].time - trackpoints[0].time).total_seconds())

    # 移动时间（秒，去掉停车段）= moving_time
    # FIT 的 total_timer_time 就是设备启停时间（暂停码表时不计入）= Strava moving_time 含义
    moving_time = _safe_get_int(session, "total_timer_time")
    if moving_time is None:
        moving_time = duration  # 设备未报告 → 视为全程移动

    # 爬升（米）——用 is not None 而非 or，防止 0.0（平路）被误判
    elevation_gain_raw = _safe_get_float(session, "total_ascent")
    elevation_gain = elevation_gain_raw if elevation_gain_raw is not None else 0.0

    # 速度（m/s）——SDK 开启 apply_scale_and_offset 后已是 m/s
    avg_speed_raw = _safe_get_float(session, "enhanced_avg_speed")
    avg_speed = avg_speed_raw if avg_speed_raw is not None else _safe_get_float(session, "avg_speed")
    max_speed_raw = _safe_get_float(session, "enhanced_max_speed")
    max_speed = max_speed_raw if max_speed_raw is not None else _safe_get_float(session, "max_speed")

    # 功率（W）
    avg_power = _safe_get_float(session, "avg_power")
    max_power = _safe_get_int(session, "max_power")
    normalized_power = _safe_get_int(session, "normalized_power")

    # 心率（bpm）
    avg_hr = _safe_get_float(session, "avg_heart_rate")
    max_hr = _safe_get_int(session, "max_heart_rate")

    # 踏频（rpm）
    avg_cadence = _safe_get_float(session, "avg_cadence")

    # 卡路里
    calories = _safe_get_float(session, "total_calories")

    # 时间
    started_at = trackpoints[0].time if trackpoints else None
    finished_at = trackpoints[-1].time if trackpoints else None

    return ActivitySummary(
        distance=round(distance, 1) if distance is not None else 0.0,
        duration=duration,
        moving_time=moving_time,
        elevation_gain=round(elevation_gain, 1),
        avg_speed=round(avg_speed, 2) if avg_speed is not None else None,
        max_speed=round(max_speed, 2) if max_speed is not None else None,
        avg_power=round(avg_power, 1) if avg_power is not None else None,
        max_power=max_power,
        avg_hr=round(avg_hr, 1) if avg_hr is not None else None,
        max_hr=max_hr,
        avg_cadence=round(avg_cadence, 1) if avg_cadence is not None else None,
        calories=round(calories, 1) if calories is not None else None,
        started_at=started_at,
        finished_at=finished_at,
        splits=None,  # FIT 不自带 splits，且设备端摘要足够，不做分段
        normalized_power=normalized_power,
    )


def _extract_creator(file_id_mesgs: list) -> str | None:
    """从 file_id 消息中提取设备制造商/产品名。"""
    if not file_id_mesgs:
        return None

    file_id = file_id_mesgs[0]
    manufacturer = _safe_get(file_id, "manufacturer")
    product = _safe_get(file_id, "garmin_product") or _safe_get(file_id, "product")

    parts = [str(p) for p in [manufacturer, product] if p is not None]
    return " ".join(parts) if parts else None


# ==================== 安全取值辅助函数 ====================
# FIT 消息的字段可能不存在、可能是 None、可能是非预期类型，
# 这组函数统一做安全提取 + 类型转换。


def _safe_get(record: dict, key: str):
    """安全取值，不存在返回 None。"""
    if not isinstance(record, dict):
        return None
    return record.get(key)


def _safe_get_float(record: dict, key: str) -> float | None:
    """安全取浮点值。"""
    val = _safe_get(record, key)
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _safe_get_int(record: dict, key: str) -> int | None:
    """安全取整数值。"""
    val = _safe_get(record, key)
    if val is None:
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None
