"""
用户社交层子模块——"门面 + 名片 + 探索"。

干啥用：
    - 用户骑行热图（个人页"我去过哪儿"地图卡）→ get_user_heatmap
    - 用户改主城市（settings 页）→ update_user_city
    - 看他人主页（点击骑友头像）→ get_user_profile_for_others
    - 探索 tab"骑友" section（活跃用户列表 + 搜索）→ get_active_users
    - 上传新 activity 时清热图缓存（invalidate_heatmap_cache / worker hook 调）

类比：
    朋友圈"我的"页 + 别人主页 + 通讯录"最近联系"——
    - 我的热图：我足迹的地图（get_user_heatmap）
    - 我的名片：别人点开我看到的（get_user_profile_for_others）
    - 通讯录"最近活跃骑友"（get_active_users）
    - 改我的城市标签（update_user_city）

操作注意（关键）：
    - **看他人严格白名单**（_PROFILE_RESPONSE_KEYS / spec R3-I3）：拦截 efforts / activities /
      heatmap / strava_* / openid / mute_notifications / 任何 token；机制不是自觉 / dict 推导式
      生效 / 未来误加敏感字段也不会泄漏；防回退测试用 _filter_profile_keys helper 反向构造
    - **分层 cache key**：无 city 与按 city 路径分别缓存；v4 再按 card/full/viewport 隔离，
      invalidate_heatmap_cache 同时清新旧 key，避免历史大对象残留
    - **GCJ-02 坐标转换在前端**：后端返 WGS-84 原始坐标 [lon, lat]；前端拿到后转 GCJ-02 给腾讯地图
      （陷阱 #31 / D31 决策）；不要在后端转 / 否则坐标双重转换
    - **simplified_track polyline 起点定 city**：infer_city_from_coords 是 common.geo 纯函数
      （spec §1.3）；纯函数不依赖 DB / 可独立测
    - **Sprint 4 D7 决策**：profile 默认公开（无隐私开关 / requester_user_id 留 v6 隐私开关预留位）
    - **Sprint 4 D-P08 红线**：看自己 = 看他人（字段集合完全一致）
    - **Sprint 5 task-3 NEW**：get_active_users 用 INNER JOIN activities 自然过滤无活动用户
      + escape SQL wildcard 防 % / _ 通配符注入 + NULL 排序兼容 PG/SQLite

数据流：
    入：user_id（self / target） + 可选 city / search query
    出：热图 dict / 用户对象 / 看他人 dict（白名单严格） / 活跃用户列表
    边界：DB activities + users + simplified_track JSON / Redis cache / common.geo 纯函数

不允许：
    - import service_stats（保持单向依赖）
    - 在白名单内放敏感字段（_PROFILE_RESPONSE_KEYS 改动前 review 红线）
    - 直接调 Activity ORM 修改字段（只读聚合 / 写操作在 worker）

v5 task-user-split-001：从 service.py 834 行拆出（commit TBD）。
"""

import json as _json
import math as _math
import time as _time
import zlib as _zlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import desc
from sqlalchemy import func as _func
from sqlalchemy.orm import Session

from app.activity.models import Activity as _Activity
from app.common.geo import infer_city_from_coords as _infer_city_from_coords
from app.user.models import User

# 北京时间偏移量（UTC+8）——看他人主页"本月汇总"按北京时间划月
# Q1 a 决策：与 service_stats 各自独立复制（DRY 违反但 0 跨依赖）
BEIJING_TZ = timezone(timedelta(hours=8))

_HEATMAP_CACHE_TTL_SEC = 3600
_HEATMAP_VIEWPORT_CACHE_TTL_SEC = 900
_HEATMAP_CACHE_PREFIX = "heatmap:v4:user_"
_HEATMAP_GENERATION_PREFIX = "heatmap:generation:user_"
_HEATMAP_PREVIOUS_V3_CACHE_PREFIX = "heatmap:v3:user_"
_HEATMAP_PREVIOUS_CACHE_PREFIX = "heatmap:v2:user_"
_HEATMAP_LEGACY_CACHE_PREFIX = "heatmap:user_"
_HEATMAP_POINTS_PER_ACTIVITY = 64
_HEATMAP_TOTAL_POINT_BUDGET = 9_000
_HEATMAP_CARD_POINTS_PER_ACTIVITY = 24
_HEATMAP_CARD_TOTAL_POINT_BUDGET = 4_000
_HEATMAP_VIEWPORT_MAX_SPAN_LON = 20.0
_HEATMAP_VIEWPORT_MAX_SPAN_LAT = 15.0
_HEATMAP_VIEWPORT_SOURCE_POINT_BUDGET = 72_000
_HEATMAP_VIEWPORT_SOURCE_POINTS_PER_ACTIVITY = 320
_HEATMAP_VIEWPORT_MAX_CACHE_KEYS = 12
_HEATMAP_COMPRESSED_CACHE_PREFIX = b"z1:"
_HEATMAP_SOURCE_BUILD_LOCK_TTL_SEC = 10
_HEATMAP_SOURCE_BUILD_POLL_SEC = 0.05
# _VALID_USER_CITIES 已废弃（Tim 2026-05-17 真用拍放宽 user.city 到任意中文）
# 历史 6 城枚举只剩 activity.city（worker 推断起点 / ck_activities_city CHECK 仍生效）
# update_user_city 现仅校验长度 + strip / 不再卡 6 城

# 看他人主页严格白名单（PRD 5.A.2 / D-P08 红线 / spec R3-I3 强制生效）
# 加新字段前先 review：是否泄漏 token / openid / mute_notifications / 任何隐私字段？
# Sprint 4 codex 异源审 2026-05-06 砍 ftp（P1-4）：
#     FTP 是骑手生理数据 / Strava 也允许独立隐私层 / Tim "默认公开"是页面层 ≠ 字段层
_PROFILE_RESPONSE_KEYS = {
    "id", "nickname", "avatar_url", "city", "bike_type",
    "total_distance_km", "total_elevation_m", "activity_count",
    "current_month_summary",
}
# Sprint 6 task-1：骑手签名加入白名单。
# 用 `|=` 追加而不是整体重写——保留既有 9 字段不变，未来 review diff 一眼看出只是"加 bio"。
# bio 默认公开（Sprint 4 D7 / 跟 city 一样在页面层公开 / 不属敏感生理数据）。
_PROFILE_RESPONSE_KEYS |= {"bio"}
# Sprint 6 task-2：身份徽章列表加入白名单（11 字段）。
# 同样用 `|=` 追加（红线 / 不整体重写 / 防 v0.1 Critical 复发）。
# badges 是真实骑行数据自动算出的 / 默认公开 / 自他对称返同样字段集。
_PROFILE_RESPONSE_KEYS |= {"badges"}


class InvalidHeatmapViewport(ValueError):
    """热图视野参数非法；router 只把这类可预期输入错误映射为 422。"""


def _get_redis_client():
    """延迟导入 redis_conn—— 让纯单元测试不依赖 Redis 启动（task-0.8 单一连接源 / Q1 a 独立复制 / 与 service_stats 一致）。"""
    from app.queue import redis_conn
    return redis_conn


def _decode_heatmap_cache(cached: object, *, expected_generation: int | None = None) -> dict | None:
    raw = cached if isinstance(cached, bytes) else str(cached).encode()
    if raw.startswith(_HEATMAP_COMPRESSED_CACHE_PREFIX):
        raw = _zlib.decompress(raw[len(_HEATMAP_COMPRESSED_CACHE_PREFIX):])
    decoded = _json.loads(raw.decode())
    if isinstance(decoded, dict) and "_heatmap_generation" in decoded and "value" in decoded:
        if expected_generation is not None and decoded["_heatmap_generation"] != expected_generation:
            return None
        return decoded["value"]
    # 兼容部署前的 v4 缓存；一旦 generation 递增，旧格式就不能再复活。
    if expected_generation not in (None, 0):
        return None
    return decoded


def _encode_heatmap_cache(
    value: dict,
    *,
    compress: bool = False,
    generation: int | None = None,
) -> bytes:
    payload = (
        {"_heatmap_generation": generation, "value": value}
        if generation is not None
        else value
    )
    raw = _json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    if compress:
        return _HEATMAP_COMPRESSED_CACHE_PREFIX + _zlib.compress(raw, level=6)
    return raw


def _store_heatmap_cache(
    redis_client,
    key: str,
    value: dict,
    ttl: int,
    *,
    compress: bool = False,
    generation: int | None = None,
) -> None:
    redis_client.setex(
        key,
        ttl,
        _encode_heatmap_cache(value, compress=compress, generation=generation),
    )


def _heatmap_cache_generation(redis_client, user_id: int) -> int:
    raw = redis_client.get(f"{_HEATMAP_GENERATION_PREFIX}{user_id}")
    if raw is None:
        return 0
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def _claim_heatmap_source_build(
    redis_client,
    source_cache_key: str,
    generation: int,
) -> tuple[bool, dict | None]:
    """同一用户同一图层冷启动只让一个请求扫描 PostgreSQL，其他请求短暂等源层。"""
    lock_key = f"{source_cache_key}:build:generation_{generation}"
    if redis_client.set(
        lock_key,
        "1",
        nx=True,
        ex=_HEATMAP_SOURCE_BUILD_LOCK_TTL_SEC,
    ):
        return True, None
    max_polls = int(
        (_HEATMAP_SOURCE_BUILD_LOCK_TTL_SEC * 2)
        / _HEATMAP_SOURCE_BUILD_POLL_SEC
    )
    for _ in range(max_polls):
        cached_source = redis_client.get(source_cache_key)
        if cached_source is not None:
            source = _decode_heatmap_cache(
                cached_source,
                expected_generation=generation,
            )
            if source is not None:
                return False, source
        # 首个 builder 崩溃时，租约到期后也只允许一个等待者接棒，避免并发惊群扫 PG。
        if redis_client.set(
            lock_key,
            "1",
            nx=True,
            ex=_HEATMAP_SOURCE_BUILD_LOCK_TTL_SEC,
        ):
            return True, None
        _time.sleep(_HEATMAP_SOURCE_BUILD_POLL_SEC)
    # 两个完整租约都没有产出源层时才故障降级，避免地图永久卡住。
    return True, None


def _trim_heatmap_viewport_cache(redis_client, user_id: int, current_key: str) -> None:
    """每个用户最多保留少量视野格，防连续拖图把 Redis 堆满大对象。"""
    pattern = f"{_HEATMAP_CACHE_PREFIX}{user_id}:detail_viewport:*"
    keys = list(redis_client.scan_iter(match=pattern))
    if len(keys) <= _HEATMAP_VIEWPORT_MAX_CACHE_KEYS:
        return
    current_bytes = current_key.encode()
    victims = [key for key in keys if key != current_key and key != current_bytes]
    overflow = len(keys) - _HEATMAP_VIEWPORT_MAX_CACHE_KEYS
    if overflow > 0 and victims:
        redis_client.delete(*victims[:overflow])


def _heatmap_viewport_source_cache_key(
    user_id: int,
    city: str | None,
    year: int | None,
    generation: int = 0,
) -> str:
    parts = [f"{_HEATMAP_CACHE_PREFIX}{user_id}", "detail_viewport_source"]
    if city is not None:
        parts.append(f"city_{city}")
    parts.append(f"year_{year}" if year is not None else "year_all")
    if generation > 0:
        parts.append(f"generation_{generation}")
    return ":".join(parts)


def _heatmap_result_from_source(
    source: dict,
    *,
    detail: str,
    city: str | None,
    year: int | None,
    viewport: tuple | None,
) -> dict:
    source_tracks = source.get("tracks") or []
    if detail == "full":
        tracks = _build_heatmap_tracks_from_source(
            source_tracks,
            per_activity_limit=_HEATMAP_POINTS_PER_ACTIVITY,
            total_point_budget=_HEATMAP_TOTAL_POINT_BUDGET,
        )
        activity_count = len(tracks)
    else:
        tracks, activity_count = _build_heatmap_viewport_tracks(source_tracks, viewport)
    return {
        "city": city,
        "tracks": tracks,
        "activity_count": activity_count,
        "available_years": source.get("available_years") or [],
        "selected_year": year,
    }


def _store_heatmap_result_cache(
    redis_client,
    user_id: int,
    cache_key: str,
    detail: str,
    result: dict,
    generation: int,
) -> None:
    is_viewport = detail == "viewport"
    _store_heatmap_cache(
        redis_client,
        cache_key,
        result,
        _HEATMAP_VIEWPORT_CACHE_TTL_SEC if is_viewport else _HEATMAP_CACHE_TTL_SEC,
        compress=is_viewport,
        generation=generation,
    )
    if is_viewport:
        _trim_heatmap_viewport_cache(redis_client, user_id, cache_key)


def _filter_profile_keys(raw_response: dict) -> dict:
    """
    白名单过滤——"门口的安检员"。

    把 raw_response（含可能的敏感字段）过一遍 _PROFILE_RESPONSE_KEYS 白名单，
    只放白名单内的字段出去。

    抽成独立函数的目的是**让防回退测试能直接构造含敏感字段的输入**：
    如果有人删掉 dict 推导式 / 把白名单改成黑名单 / 误加敏感字段进白名单
    → 单测 `test_filter_profile_keys_strips_sensitive_fields` 立即失败。

    防回退要点（codex 异源审 Important / 2026-04-30）：
    单纯断言 `set(result.keys()) == 白名单` 防不住推导式被删——因为 raw_response
    本身就字面只列白名单字段，删推导式 result 也不变。本 helper 让测试**反向**
    构造含敏感字段的输入，dict 推导式被删时立即被抓。
    """
    return {k: v for k, v in raw_response.items() if k in _PROFILE_RESPONSE_KEYS}


def _build_heatmap_preview_track(
    track: object,
    point_limit: int = _HEATMAP_POINTS_PER_ACTIVITY,
) -> list[list[float]]:
    """生成热图地图需要的显示精度轨迹，避免下发活动原始点集。

    Strava 的个人热图先在服务端按地图层级聚合，客户端只取显示所需的数据。
    VELO 当前数据量不需要完整瓦片服务；这里采用同一原则的轻量版本：个人页
    卡片与全屏地图各有固定点预算，服务端一次遍历选关键拐点 + Redis 缓存。

    点数上限由调用方按 card/full 决定。293 条活动的全屏上限约 9000 点，
    而不是把数据库里约 44 万个 simplified_track 点（实测响应 6.7 MB）再次传到手机。
    """
    if not isinstance(track, list):
        return []

    clean: list[dict] = []
    for point in track:
        normalized = _normalize_heatmap_source_point(point)
        if normalized is not None:
            clean.append(normalized)

    if len(clean) < 2:
        return []

    reduced = _select_heatmap_key_points(clean, max(2, point_limit))

    # 5 位小数约 1 米，远高于 327x240 卡片的像素分辨率；继续保留更多小数只增流量。
    return [[round(float(p["lon"]), 5), round(float(p["lat"]), 5)] for p in reduced]


def _normalize_heatmap_source_point(point: object) -> dict | None:
    """校验数据库轨迹点并统一为有限、合法的 WGS-84 坐标。"""
    try:
        if isinstance(point, dict):
            lat = float(point.get("lat"))
            lon = float(point.get("lon"))
            ele = point.get("ele")
        elif isinstance(point, (list, tuple)) and len(point) >= 2:
            lon = float(point[0])
            lat = float(point[1])
            ele = None
        else:
            return None
    except (TypeError, ValueError):
        return None
    if not (_math.isfinite(lat) and _math.isfinite(lon)):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return {"lat": lat, "lon": lon, "ele": ele}


def _has_heatmap_line(track: object) -> bool:
    """快速判断活动是否至少有两个可画点，超大历史库抽样前先排除坏数据。"""
    if not isinstance(track, list):
        return False
    valid_count = 0
    for point in track:
        if _normalize_heatmap_source_point(point) is not None:
            valid_count += 1
            if valid_count >= 2:
                return True
    return False


def _select_heatmap_key_points(points: list[dict], limit: int) -> list[dict]:
    """用 LTTB 面积法一次遍历选关键拐点，O(n) 且严格不超过 limit。

    simplified_track 本身已是活动详情级 DP 轨迹；热图卡只需从中挑出最能代表
    形状变化的点。相比再次跑多轮 DP 二分，293 条长轨迹的冷缓存生成从几十秒
    降到亚秒级，同时比固定步长更不容易漏掉短促急弯。
    """
    if len(points) <= limit:
        return points
    if limit < 3:
        return [points[0], points[-1]][:limit]

    sampled = [points[0]]
    bucket_size = (len(points) - 2) / (limit - 2)
    selected_index = 0

    for bucket in range(limit - 2):
        next_start = int((bucket + 1) * bucket_size) + 1
        next_end = min(int((bucket + 2) * bucket_size) + 1, len(points))
        if next_start >= len(points) - 1:
            avg_lon = float(points[-1]["lon"])
            avg_lat = float(points[-1]["lat"])
        else:
            next_points = points[next_start:next_end] or [points[-1]]
            avg_lon = sum(float(p["lon"]) for p in next_points) / len(next_points)
            avg_lat = sum(float(p["lat"]) for p in next_points) / len(next_points)

        range_start = int(bucket * bucket_size) + 1
        range_end = min(int((bucket + 1) * bucket_size) + 1, len(points) - 1)
        anchor = points[selected_index]
        anchor_lon = float(anchor["lon"])
        anchor_lat = float(anchor["lat"])
        cos_lat = _math.cos(anchor_lat * _math.pi / 180)
        best_area = -1.0
        best_index = range_start

        for index in range(range_start, max(range_start + 1, range_end)):
            point = points[index]
            lon = float(point["lon"])
            lat = float(point["lat"])
            area = abs(
                (anchor_lon - avg_lon) * cos_lat * (lat - anchor_lat)
                - (anchor_lon - lon) * cos_lat * (avg_lat - anchor_lat)
            )
            if area > best_area:
                best_area = area
                best_index = index

        sampled.append(points[best_index])
        selected_index = best_index

    sampled.append(points[-1])
    return sampled


def _heatmap_activity_buckets(activity: object) -> list[tuple[int, int]]:
    """返回轨迹实际覆盖的约 50km 网格，抽样时不只看活动起点。"""
    track = getattr(activity, "simplified_track", activity if isinstance(activity, list) else None)
    buckets: dict[tuple[int, int], None] = {}
    if isinstance(track, list):
        for point in track:
            normalized = _normalize_heatmap_source_point(point)
            if normalized is not None:
                key = (_math.floor(normalized["lat"] * 2), _math.floor(normalized["lon"] * 2))
                buckets[key] = None
    return list(buckets)


def _select_heatmap_preview_activities(activities: list, limit: int) -> list:
    """在固定轨迹上限内做地理分桶轮询，避免只保留常骑城市而漏掉旅行足迹。"""
    # 始终先排除单点/非法轨迹，再计算整张卡的动态点预算；否则即使没有触发
    # 1 万条抽样，坏活动也会把正常轨迹从 64 点无谓压到 2 点。
    activities = [
        activity for activity in activities
        if _has_heatmap_line(
            getattr(activity, "simplified_track", activity if isinstance(activity, list) else None)
        )
    ]
    if len(activities) <= limit:
        return activities

    bucket_members: dict[tuple[int, int], list] = {}
    for activity in activities:
        for bucket in _heatmap_activity_buckets(activity):
            bucket_members.setdefault(bucket, []).append(activity)

    selected = []
    selected_ids = set()
    # 稀有覆盖桶优先：一条从北京出发、终点到远端的新路线即使排在第 10001 条，
    # 也会因为覆盖了稀有桶而先进入代表集。
    for _, members in sorted(bucket_members.items(), key=lambda item: len(item[1])):
        candidate = next((activity for activity in members if id(activity) not in selected_ids), None)
        if candidate is not None:
            selected.append(candidate)
            selected_ids.add(id(candidate))
            if len(selected) == limit:
                return selected

    # 地理覆盖已保住后，用原顺序填满剩余预算，尽量保留常骑区域的叠加密度。
    for activity in activities:
        if id(activity) in selected_ids:
            continue
        selected.append(activity)
        selected_ids.add(id(activity))
        if len(selected) == limit:
            break
    return selected


def _heatmap_points_per_activity(
    activity_count: int,
    per_activity_limit: int = _HEATMAP_POINTS_PER_ACTIVITY,
    total_point_budget: int = _HEATMAP_TOTAL_POINT_BUDGET,
) -> int:
    """按展示层级限制每条活动点数，同时锁住整张地图总点数。"""
    if activity_count <= 0:
        return per_activity_limit
    return max(2, min(per_activity_limit, total_point_budget // activity_count))


def _heatmap_viewport_budget(zoom: int) -> tuple[int, int]:
    """当前视野越小，允许的轨迹精度越高，但单次响应始终低于 6 MB 旧方案。"""
    if zoom <= 10:
        return 24_000, 128
    if zoom <= 12:
        return 30_000, 192
    return 36_000, 320


def _normalize_heatmap_viewport(
    west: float | None,
    south: float | None,
    east: float | None,
    north: float | None,
    zoom: int | None,
) -> tuple[float, float, float, float, int]:
    """校验并向外吸附视野边界，让小幅拖动能命中同一份 Redis 缓存。"""
    values = (west, south, east, north)
    if zoom is None or any(value is None for value in values):
        raise InvalidHeatmapViewport("viewport detail requires west/south/east/north/zoom")
    try:
        finite = all(_math.isfinite(float(value)) for value in values)
    except (TypeError, ValueError):
        finite = False
    if not finite:
        raise InvalidHeatmapViewport("invalid heatmap viewport")

    west_value = float(west)
    south_value = float(south)
    east_value = float(east)
    north_value = float(north)
    zoom_value = int(zoom)
    if not (3 <= zoom_value <= 20):
        raise InvalidHeatmapViewport("invalid heatmap zoom")
    if not (-180 <= west_value < east_value <= 180 and -90 <= south_value < north_value <= 90):
        raise InvalidHeatmapViewport("invalid heatmap viewport")
    if (
        east_value - west_value > _HEATMAP_VIEWPORT_MAX_SPAN_LON
        or north_value - south_value > _HEATMAP_VIEWPORT_MAX_SPAN_LAT
    ):
        raise InvalidHeatmapViewport("heatmap viewport is too large")

    if zoom_value <= 10:
        cell = 0.1
    elif zoom_value <= 12:
        cell = 0.05
    elif zoom_value <= 14:
        cell = 0.01
    else:
        cell = 0.005

    bucket_west = max(-180.0, _math.floor(west_value / cell) * cell - cell)
    bucket_south = max(-90.0, _math.floor(south_value / cell) * cell - cell)
    bucket_east = min(180.0, _math.ceil(east_value / cell) * cell + cell)
    bucket_north = min(90.0, _math.ceil(north_value / cell) * cell + cell)
    return (
        round(bucket_west, 5),
        round(bucket_south, 5),
        round(bucket_east, 5),
        round(bucket_north, 5),
        zoom_value,
    )


def _point_in_heatmap_viewport(point: dict, viewport: tuple[float, float, float, float, int]) -> bool:
    west, south, east, north, _ = viewport
    return west <= float(point["lon"]) <= east and south <= float(point["lat"]) <= north


def _heatmap_segment_intersects_viewport(
    start: dict,
    end: dict,
    viewport: tuple[float, float, float, float, int],
) -> bool:
    """Liang-Barsky 线段裁剪判断；两个端点都在屏幕外时也不能漏掉穿屏轨迹。"""
    if _point_in_heatmap_viewport(start, viewport) or _point_in_heatmap_viewport(end, viewport):
        return True
    west, south, east, north, _ = viewport
    x1 = float(start["lon"])
    y1 = float(start["lat"])
    dx = float(end["lon"]) - x1
    dy = float(end["lat"]) - y1
    t_min = 0.0
    t_max = 1.0
    for p, q in (
        (-dx, x1 - west),
        (dx, east - x1),
        (-dy, y1 - south),
        (dy, north - y1),
    ):
        if abs(p) < 1e-12:
            if q < 0:
                return False
            continue
        ratio = q / p
        if p < 0:
            if ratio > t_max:
                return False
            t_min = max(t_min, ratio)
        else:
            if ratio < t_min:
                return False
            t_max = min(t_max, ratio)
    return True


def _clip_heatmap_track_to_viewport(
    track: object,
    viewport: tuple[float, float, float, float, int],
) -> list[list[dict]]:
    """保留视野内连续轨迹，并带上进出边界相邻点，避免屏幕边缘突然断线。"""
    if not isinstance(track, list):
        return []
    clean = []
    for raw_point in track:
        point = _normalize_heatmap_source_point(raw_point)
        if point is not None:
            clean.append(point)
    if len(clean) < 2:
        return []

    segments: list[list[dict]] = []
    current: list[dict] = []
    for start, end in zip(clean, clean[1:]):
        if _heatmap_segment_intersects_viewport(start, end, viewport):
            if not current:
                current = [start]
            elif current[-1] != start:
                if len(current) >= 2:
                    segments.append(current)
                current = [start]
            if current[-1] != end:
                current.append(end)
        elif current:
            if len(current) >= 2:
                segments.append(current)
            current = []
    if len(current) >= 2:
        segments.append(current)

    # GPS 漂点或跨城活动不能在当前视野里画出一条横穿地图的假直线。
    drawable: list[list[dict]] = []
    for segment in segments:
        split: list[dict] = []
        for point in segment:
            if split:
                a = {"longitude": float(split[-1]["lon"]), "latitude": float(split[-1]["lat"])}
                b = {"longitude": float(point["lon"]), "latitude": float(point["lat"])}
                if _heatmap_distance_km(a, b) > 40:
                    if len(split) >= 2:
                        drawable.append(split)
                    split = []
            split.append(point)
        if len(split) >= 2:
            drawable.append(split)
    return drawable


def _heatmap_distance_km(a: dict, b: dict) -> float:
    """服务端热图切段使用的球面距离，字段格式与前端 prepared point 一致。"""
    to_rad = _math.pi / 180
    lat1 = float(a["latitude"]) * to_rad
    lat2 = float(b["latitude"]) * to_rad
    d_lat = (float(b["latitude"]) - float(a["latitude"])) * to_rad
    d_lon = (float(b["longitude"]) - float(a["longitude"])) * to_rad
    sin_lat = _math.sin(d_lat / 2)
    sin_lon = _math.sin(d_lon / 2)
    h = sin_lat * sin_lat + _math.cos(lat1) * _math.cos(lat2) * sin_lon * sin_lon
    return 6371 * 2 * _math.atan2(_math.sqrt(h), _math.sqrt(max(0, 1 - h)))


def _build_heatmap_viewport_tracks(
    activities: list,
    viewport: tuple[float, float, float, float, int],
) -> tuple[list[list[list[float]]], int]:
    """只生成当前视野需要的折线；总览清晰度约为旧 9000 点方案的 2.7 倍。"""
    segments: list[tuple[int, list[dict]]] = []
    for activity_index, activity in enumerate(activities):
        source_track = getattr(activity, "simplified_track", activity)
        activity_segments = _clip_heatmap_track_to_viewport(source_track, viewport)
        segments.extend((activity_index, segment) for segment in activity_segments)
    if not segments:
        return [], 0

    total_budget, per_segment_limit = _heatmap_viewport_budget(viewport[4])
    if len(segments) * 2 > total_budget:
        segments = sorted(segments, key=lambda item: len(item[1]), reverse=True)[: total_budget // 2]
    point_limit = _heatmap_points_per_activity(
        len(segments),
        per_activity_limit=per_segment_limit,
        total_point_budget=total_budget,
    )

    result = []
    rendered_activity_ids = set()
    for activity_index, segment in segments:
        reduced = _select_heatmap_key_points(segment, point_limit)
        if len(reduced) >= 2:
            result.append([
                [round(float(point["lon"]), 5), round(float(point["lat"]), 5)]
                for point in reduced
            ])
            rendered_activity_ids.add(activity_index)
    return result, len(rendered_activity_ids)


def _build_heatmap_viewport_source(activities: list) -> list[list[list[float]]]:
    """一次生成可复用的高精度源层；后续拖图不再反复读取 6 MB JSONB。"""
    max_tracks = _HEATMAP_VIEWPORT_SOURCE_POINT_BUDGET // 2
    selected = _select_heatmap_preview_activities(activities, max_tracks)
    point_limit = _heatmap_points_per_activity(
        len(selected),
        per_activity_limit=_HEATMAP_VIEWPORT_SOURCE_POINTS_PER_ACTIVITY,
        total_point_budget=_HEATMAP_VIEWPORT_SOURCE_POINT_BUDGET,
    )
    tracks = []
    for activity in selected:
        track = _build_heatmap_preview_track(activity.simplified_track, point_limit)
        if track:
            tracks.append(track)
    return tracks


def _build_heatmap_tracks_from_source(
    source_tracks: list,
    *,
    per_activity_limit: int,
    total_point_budget: int,
) -> list[list[list[float]]]:
    """从已缓存的高精度源层派生 card/full，避免同一次打开又读一遍 PostgreSQL。"""
    drawable = _select_heatmap_preview_activities(
        source_tracks,
        total_point_budget // 2,
    )
    point_limit = _heatmap_points_per_activity(
        len(drawable),
        per_activity_limit=per_activity_limit,
        total_point_budget=total_point_budget,
    )
    tracks = []
    for track in drawable:
        preview = _build_heatmap_preview_track(track, point_limit)
        if preview:
            tracks.append(preview)
    return tracks


def _heatmap_activity_year(activity: object) -> int | None:
    """按北京时间返回活动年份；旧数据缺 started_at 时不进入年份筛选。"""
    started_at = getattr(activity, "started_at", None)
    if not isinstance(started_at, datetime):
        return None
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    return started_at.astimezone(BEIJING_TZ).year


def get_user_heatmap(
    db: Session,
    user_id: int,
    city: str | None = None,
    year: int | None = None,
    detail: str = "full",
    *,
    west: float | None = None,
    south: float | None = None,
    east: float | None = None,
    north: float | None = None,
    zoom: int | None = None,
) -> dict:
    """
    用户骑行热图——"我去过哪些地方"。

    把用户的骑行轨迹生成**地图显示精度数据**并保留 activity 边界，前端交给
    原生地图 polyline 图层；真实道路底图、拖动和缩放由地图组件负责。

    detail 三档：
    - card：个人页交互预览，最多 4000 点 / 每活动最多 24 点
    - full：全屏首屏总览，最多 9000 点 / 每活动最多 64 点
    - viewport：按当前视野和缩放级别裁切，最多 2.4 万到 3.6 万点

    这对应 Strava 的层级细节思想：小视图不下载全屏精度，避免历史数据再次
    阻塞小程序；总览两档通过地理分桶保留稀有旅行区域，而不是只截常骑城市。

    city 参数（v3 polish / Sprint 4 task-4.2 v3）：
    - city is None → 返回该用户**所有** completed activities 的轨迹（不按城市筛 /
      response.city 也是 None）。前端"全部"视图走这条路径，一次性看跨城市足迹。
    - city 有值 → 保留旧行为：按 simplified_track 起点城市筛
      （infer_city_from_coords 是 common.geo 纯函数 / spec §1.3）。

    D27 v2 polish（Sprint 4 task-4.2 v2）：从扁平 multipoint.coordinates
    改为 tracks: list[list[[lon,lat]]] —— 保留 activity 边界让前端画 polyline，
    不再用 markers 点 / 视觉接近 ride.fitcard.app 80%。

    year 可选：不传返回全部年份，传入后只返回对应自然年活动；响应始终带
    available_years，供全屏地图的年份图层控制使用。

    v4 cache 同时区分 city / year / detail；viewport 先生成 7.2 万点以内的压缩源层，
    后续拖图不再读全量 JSONB。视野结果按边界和 zoom 分桶、TTL 15 分钟且每用户最多 12 份；
    源层和总览 TTL 1 小时。

    陷阱守卫：
    - 陷阱 #5（redis-py 7+ 默认返 bytes）→ json.loads 前 decode
    - `if cached is not None`（CLAUDE.md 陷阱 #1 / 与 power_curve 一致）

    返回结构：
        {
          "city": "beijing" | None,        # 透传入参 / 不传时为 None
          "tracks": [
            [[lon, lat], [lon, lat], ...],  # activity 1 的轨迹
            [[lon, lat], [lon, lat], ...],  # activity 2 的轨迹
            ...
          ],
          "activity_count": 12,
          "available_years": [2026, 2025],
          "selected_year": 2026 | None
        }
    """
    if detail not in {"card", "full", "viewport"}:
        raise InvalidHeatmapViewport(f"invalid heatmap detail: {detail}")

    viewport = None
    if detail == "viewport":
        viewport = _normalize_heatmap_viewport(west, south, east, north, zoom)

    redis_client = _get_redis_client()
    cache_generation = _heatmap_cache_generation(redis_client, user_id)
    cache_parts = [f"{_HEATMAP_CACHE_PREFIX}{user_id}", f"detail_{detail}"]
    if city is not None:
        cache_parts.append(f"city_{city}")
    cache_parts.append(f"year_{year}" if year is not None else "year_all")
    if viewport is not None:
        viewport_key = ":".join(str(value).replace("-", "m").replace(".", "p") for value in viewport)
        cache_parts.append(f"viewport_{viewport_key}")
    if cache_generation > 0:
        cache_parts.append(f"generation_{cache_generation}")
    cache_key = ":".join(cache_parts)
    cached = redis_client.get(cache_key)
    if cached is not None:
        decoded_cache = _decode_heatmap_cache(cached, expected_generation=cache_generation)
        if decoded_cache is not None:
            return decoded_cache

    source_cache_key = None
    if detail in {"full", "viewport"}:
        source_cache_key = _heatmap_viewport_source_cache_key(
            user_id,
            city,
            year,
            cache_generation,
        )
        cached_source = redis_client.get(source_cache_key)
        if cached_source is not None:
            source = _decode_heatmap_cache(
                cached_source,
                expected_generation=cache_generation,
            )
        else:
            source = None
        if source is not None:
            result = _heatmap_result_from_source(
                source,
                detail=detail,
                city=city,
                year=year,
                viewport=viewport,
            )
            _store_heatmap_result_cache(
                redis_client,
                user_id,
                cache_key,
                detail,
                result,
                cache_generation,
            )
            return result

        _, waited_source = _claim_heatmap_source_build(
            redis_client,
            source_cache_key,
            cache_generation,
        )
        if waited_source is not None:
            result = _heatmap_result_from_source(
                waited_source,
                detail=detail,
                city=city,
                year=year,
                viewport=viewport,
            )
            _store_heatmap_result_cache(
                redis_client,
                user_id,
                cache_key,
                detail,
                result,
                cache_generation,
            )
            return result

    # 查该用户所有 completed activities + 有 simplified_track 的
    # Sprint 5 task-2 dedupe：跳过 duplicate 防 heatmap 同轨迹双显
    activity_filters = (
        _Activity.user_id == user_id,
        _Activity.status == "completed",
        _Activity.duplicate_of.is_(None),
        _Activity.activity_type == "cycling",  # Sprint 7 Fix 7：防非骑行污染热力图
        _Activity.simplified_track.isnot(None),
    )
    activities_query = db.query(_Activity.simplified_track, _Activity.started_at).filter(*activity_filters)
    prefetched_available_years = None
    if detail in {"full", "viewport"} and year is not None and city is None:
        # 年份全屏首帧与视野共用源层；先轻量读取年份列表，再把大 JSONB 查询下推到所选年。
        year_rows = db.query(_Activity.started_at).filter(*activity_filters).all()
        prefetched_available_years = sorted(
            {
                activity_year
                for row in year_rows
                if (activity_year := _heatmap_activity_year(row)) is not None
            },
            reverse=True,
        )
        start_bj = datetime(year, 1, 1, tzinfo=BEIJING_TZ)
        end_bj = datetime(year + 1, 1, 1, tzinfo=BEIJING_TZ)
        activities_query = activities_query.filter(
            _Activity.started_at >= start_bj.astimezone(timezone.utc),
            _Activity.started_at < end_bj.astimezone(timezone.utc),
        )
    activities = activities_query.all()

    # 城市筛分支：
    # - city is None → 不筛 / 全部 completed activities（含 simplified_track）都算
    # - city 有值 → 按起点城市筛（B2A-2 修复反向依赖 / infer_city_from_coords 纯函数）
    filtered = []
    for a in activities:
        track = a.simplified_track
        if not track or len(track) == 0:
            continue
        if city is None:
            filtered.append(a)
            continue
        first_pt = track[0]
        lat = first_pt.get("lat")
        lon = first_pt.get("lon")
        if _infer_city_from_coords(lat, lon) == city:
            filtered.append(a)

    available_years = (
        prefetched_available_years
        if prefetched_available_years is not None
        else sorted(
            {activity_year for a in filtered if (activity_year := _heatmap_activity_year(a)) is not None},
            reverse=True,
        )
    )
    if year is not None:
        filtered = [a for a in filtered if _heatmap_activity_year(a) == year]

    source_tracks = None
    if detail in {"full", "viewport"}:
        source_tracks = _build_heatmap_viewport_source(filtered)
        source = {"tracks": source_tracks, "available_years": available_years}
        source_cache_key = source_cache_key or _heatmap_viewport_source_cache_key(
            user_id,
            city,
            year,
            cache_generation,
        )
        _store_heatmap_cache(
            redis_client,
            source_cache_key,
            source,
            _HEATMAP_CACHE_TTL_SEC,
            compress=True,
            generation=cache_generation,
        )

    if detail == "viewport":
        tracks, visible_activity_count = _build_heatmap_viewport_tracks(source_tracks, viewport)
        result = {
            "city": city,
            "tracks": tracks,
            "activity_count": visible_activity_count,
            "available_years": available_years,
            "selected_year": year,
        }
        _store_heatmap_result_cache(
            redis_client,
            user_id,
            cache_key,
            detail,
            result,
            cache_generation,
        )
        return result

    if detail == "card":
        per_activity_limit = _HEATMAP_CARD_POINTS_PER_ACTIVITY
        total_point_budget = _HEATMAP_CARD_TOTAL_POINT_BUDGET
    else:
        per_activity_limit = _HEATMAP_POINTS_PER_ACTIVITY
        total_point_budget = _HEATMAP_TOTAL_POINT_BUDGET

    if detail == "full" and source_tracks is not None:
        tracks = _build_heatmap_tracks_from_source(
            source_tracks,
            per_activity_limit=per_activity_limit,
            total_point_budget=total_point_budget,
        )
        result = {
            "city": city,
            "tracks": tracks,
            "activity_count": len(tracks),
            "available_years": available_years,
            "selected_year": year,
        }
        _store_heatmap_result_cache(
            redis_client,
            user_id,
            cache_key,
            detail,
            result,
            cache_generation,
        )
        return result

    max_tracks = total_point_budget // 2
    preview_activities = _select_heatmap_preview_activities(filtered, max_tracks)
    point_limit = _heatmap_points_per_activity(
        len(preview_activities),
        per_activity_limit=per_activity_limit,
        total_point_budget=total_point_budget,
    )
    tracks = []
    valid_count = 0
    for a in preview_activities:
        track_points = _build_heatmap_preview_track(a.simplified_track, point_limit)
        if track_points:
            tracks.append(track_points)
            valid_count += 1

    result = {
        "city": city,
        "tracks": tracks,
        "activity_count": valid_count,  # 跟 tracks 长度一致 / 不数被跳过的单点 activity
        "available_years": available_years,
        "selected_year": year,
    }

    _store_heatmap_result_cache(
        redis_client,
        user_id,
        cache_key,
        detail,
        result,
        cache_generation,
    )
    return result


def update_user_city(db: Session, user_id: int, city) -> User:
    """
    用户主动改家乡标签——"用户在 picker 里选省+市"。

    Sprint 6 task-4 hotfix（Tim 2026-05-17）：user.city 放宽到任意中文
    （picker mode="region" 选省+市拼接 / 如"山西-太原"）/ 不再限 6 城枚举。

    动作：
    1. 接受 city = None（清空）/ 或 ≤ 32 字符任意中文
    2. 去前后空白 / 空串等价 NULL
    3. 找到 user 行（不存在抛 ValueError）
    4. 改字段并 commit
    5. 清 heatmap 缓存（兼容历史 / 现在前端 heatmap-card 不传 city / 但清掉无害）

    抛错：
    - city 超长 → ValueError（schema 层 max_length=32 拦先了 / 这里再兜底）
    - user 不存在 → ValueError("user not found: <id>")
    """
    # 接受 None / 字符串 / 其他类型拒
    if city is not None:
        if not isinstance(city, str):
            raise ValueError(f"invalid city type: {type(city).__name__}")
        # 去前后空白 / 空串等价 NULL（与 bio 同款归一化）
        city = city.strip()
        if not city:
            city = None
        elif len(city) > 32:
            raise ValueError(f"city too long: {len(city)} > 32")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise ValueError(f"user not found: {user_id}")

    user.city = city
    db.commit()

    # 失效该用户所有 heatmap 缓存（含按 city 和无 city 两种 key 形态 / D27 v3 polish 修 Critical）
    invalidate_heatmap_cache(user_id)

    return user


def invalidate_heatmap_cache(user_id: int) -> None:
    """
    清掉用户全部 heatmap 缓存——"通知账房先生热图重算"。

    覆盖 v4 视野缓存、v3 地图缓存、v2 静态卡片缓存和旧版全量缓存的全部形态。

    场景：
    - 用户上传新 activity completed → worker hook 调本函数 → 下次刷个人页拿最新轨迹
    - 用户改主城（update_user_city）→ 调本函数 → 防旧 city 缓存延续

    why scan_iter 配合 delete：scan_iter 不阻塞 / delete 单 key 直删 / 两者组合覆盖两种 key 形态。

    ⚠ 调用方：app/activity/worker.py:198 + 本文件 update_user_city / 拆分时通过 service.py 转导出 0 改动
    """
    redis_client = _get_redis_client()
    # 先推进 generation：即使旧请求在扫描删除后才写回，它的缓存包也不会再被新请求接受。
    redis_client.incr(f"{_HEATMAP_GENERATION_PREFIX}{user_id}")
    # 新 v3 地图缓存 + v2 静态卡片缓存 + 旧全量缓存一起失效；旧 key 会在自然 TTL 后消失，
    # 双删保证上传新活动时不会留下历史大对象。
    for prefix in (
        _HEATMAP_CACHE_PREFIX,
        _HEATMAP_PREVIOUS_V3_CACHE_PREFIX,
        _HEATMAP_PREVIOUS_CACHE_PREFIX,
        _HEATMAP_LEGACY_CACHE_PREFIX,
    ):
        redis_client.delete(f"{prefix}{user_id}")
        for key in redis_client.scan_iter(match=f"{prefix}{user_id}:*"):
            redis_client.delete(key)


def get_user_profile_for_others(
    db: Session,
    target_user_id: int,
    requester_user_id: int,
) -> dict:
    """
    返回他人用户主页字段——"别人能看到我什么"。

    PRD 5.A.2 / D-P08 红线："看自己 = 看他人"——返回字段集合**完全一致**，
    不区分 self 还是 others。requester_user_id 参数只是 v6 隐私开关预留位。

    严格 RESPONSE_KEYS 白名单（spec R3-I3 强制生效）：
    - 通过：id / nickname / avatar_url / city / bike_type +
      total_distance_km / total_elevation_m / activity_count / current_month_summary
    - 拦截：ftp / efforts / activities / heatmap / strava_* / openid / mute_notifications / 任何 token
      （ftp 是骑手生理数据 / Sprint 4 codex 异源审 2026-05-06 砍掉 P1-4 / 实际白名单不含）
    - 这是机制不是自觉——白名单 dict 推导式生效，未来误加敏感字段也不会泄漏

    时区约定：current_month 按北京时间 UTC+8 划月（CLAUDE.md / 与 power_curve / detector 一致）

    抛错：target_user_id 不存在 → ValueError("用户不存在")
    """
    target = db.query(User).filter(User.id == target_user_id).first()
    if not target:
        raise ValueError("用户不存在")

    # 累计统计（COUNT / SUM 一次性聚合，比 N+1 查询省）
    totals = (
        db.query(
            _func.coalesce(_func.sum(_Activity.distance), 0).label("total_distance"),
            _func.coalesce(_func.sum(_Activity.elevation_gain), 0).label("total_elevation"),
            _func.count(_Activity.id).label("activity_count"),
        )
        .filter(
            _Activity.user_id == target_user_id,
            _Activity.status == "completed",
            _Activity.duplicate_of.is_(None),  # Sprint 5 task-2 dedupe：profile stats 跳过 duplicate
            _Activity.activity_type == "cycling",  # Sprint 7 Fix 7：他人主页总里程/活动数只算骑行
        )
        .first()
    )

    # 当月汇总（北京时间划月）
    now_bj = datetime.now(timezone.utc).astimezone(BEIJING_TZ)
    first_of_month_bj = now_bj.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    first_of_month_utc = first_of_month_bj.astimezone(timezone.utc)

    current_month = (
        db.query(
            _func.coalesce(_func.sum(_Activity.distance), 0).label("m_distance"),
            _func.coalesce(_func.sum(_Activity.elevation_gain), 0).label("m_elevation"),
            _func.coalesce(_func.avg(_Activity.avg_power), 0).label("m_avg_power"),
        )
        .filter(
            _Activity.user_id == target_user_id,
            _Activity.status == "completed",
            _Activity.duplicate_of.is_(None),  # Sprint 5 task-2 dedupe：月度 stats 跳过 duplicate
            _Activity.activity_type == "cycling",  # Sprint 7 Fix 7：他人主页月度统计只算骑行
            _Activity.started_at >= first_of_month_utc,
        )
        .first()
    )

    raw_response = {
        "id": target.id,
        "nickname": target.nickname,
        "avatar_url": target.avatar_url,
        "city": target.city,
        "bio": target.bio,  # Sprint 6 task-1：骑手签名（公开 / 白名单内）
        "ftp": target.ftp,
        "bike_type": target.bike_type,
        "total_distance_km": round((totals.total_distance or 0) / 1000.0, 2),
        "total_elevation_m": round(totals.total_elevation or 0, 1),
        "activity_count": totals.activity_count or 0,
        "current_month_summary": {
            "distance_km": round((current_month.m_distance or 0) / 1000.0, 2),
            "elevation_m": round(current_month.m_elevation or 0, 1),
            "avg_power_w": round(current_month.m_avg_power or 0, 1),
        },
        # Sprint 6 task-2：身份徽章列表（top 3 / 真实骑行数据自动算 / 自他对称）
        "badges": get_user_badges(db, target_user_id),
    }
    # 白名单严格生效（R3-I3 防回退 / 防止未来手滑加敏感字段静默泄漏）
    return _filter_profile_keys(raw_response)


# ===== Sprint 5 task-3：探索 tab 骑友 section service =====


def get_active_users(
    db: Session,
    exclude_user_id: int,
    limit: int = 10,
    search: str | None = None,
) -> list[dict]:
    """
    返回最近活跃用户列表（按 last_activity_at desc）/ 支持按 nickname 模糊搜索。

    设计思路：
    - INNER JOIN activities：自然过滤无 activity 用户（不需 LEFT JOIN + HAVING IS NOT NULL）
    - duplicate_of IS NULL：跟其他列表查询一致 / 跳过 dedup 重复
    - is_admin = False：admin 后台账号不出现在骑友列表
    - exclude_user_id：当前用户自己不显示在自己的"骑友"section
    - GROUP BY 用户字段：每个 user 一条聚合（不是 N×M 笛卡尔）
    - ORDER BY MAX(started_at) DESC：最近骑车的在前
    - search：nickname ILIKE %q% / 跟 segment search 一致 pattern（service_query.py:57）

    类比朋友圈"最近活跃" —— 看到谁刚刚动态多就放在前面。
    搜索时仍按活跃度排序（不按相关性 / MVP 简化）。

    参数：
        db: SQLAlchemy Session
        exclude_user_id: 当前登录用户 id（排除自己）
        limit: 返回条数上限（默认 10）
        search: nickname 模糊搜索关键词（None 或空字符串 = 不搜）

    返回：
        list[dict]：每条含 id / nickname / avatar_url / city / total_distance_km / activity_count / last_activity_at
    """
    last_activity_label = _func.max(_Activity.started_at).label("last_activity_at")

    query = (
        db.query(
            User.id,
            User.nickname,
            User.avatar_url,
            User.city,
            _func.coalesce(_func.sum(_Activity.distance), 0).label("total_distance_m"),
            _func.count(_Activity.id).label("activity_count"),
            last_activity_label,
        )
        .join(_Activity, _Activity.user_id == User.id)
        .filter(
            User.is_admin.is_(False),
            User.id != exclude_user_id,
            _Activity.status == "completed",
            _Activity.duplicate_of.is_(None),
            _Activity.activity_type == "cycling",  # Sprint 7 Fix 7：探索页活跃骑友只算骑行
        )
    )

    # search 过滤（nickname ILIKE %q% / 跟 segment search 同 pattern）
    # codex review Important 修：escape SQL wildcard（% 和 _）防用户输入 % 匹配所有 nickname / _ 匹配任意单字符
    # SQLAlchemy ilike 不自动 escape wildcard / 必须显式处理 + 配 escape='\'
    if search:
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.filter(User.nickname.ilike(f"%{escaped}%", escape="\\"))

    rows = (
        query
        .group_by(User.id, User.nickname, User.avatar_url, User.city)
        # ORDER BY MAX(started_at) DESC NULLS LAST：codex 抓的 Important 防 PG/SQLite NULL 排序行为不一致
        # 虽 INNER JOIN + status=completed 隐含 started_at NOT NULL（completed activity 一定有起骑时间），
        # 但 nullable=True 列上加 NULLS LAST 是防御性兜底，未来 schema 改动不会突然引入排序漂移
        .order_by(desc(last_activity_label).nullslast())
        .limit(limit)
        .all()
    )

    return [
        {
            "id": r.id,
            "nickname": r.nickname,
            "avatar_url": r.avatar_url,
            "city": r.city,
            "total_distance_km": round(float(r.total_distance_m) / 1000.0, 2),
            "activity_count": r.activity_count,
            "last_activity_at": r.last_activity_at,
        }
        for r in rows
    ]


# ===== Sprint 6 task-2：身份徽章聚合 + 计算 =====
#
# 数据流：
#   _aggregate_badges_input(db, user_id) — 单次 SQL 拉齐 5 维输入（防 N+1）
#       ↓
#   compute_badges(**inputs)（badges.py / 纯函数 / 不碰 DB）
#       ↓
#   返回 top 3 list[dict]
#
# 为什么"聚合"和"计算"分两层：
#   - 聚合层（service）：碰 DB / 知道字段名 / 跟着 schema 走
#   - 计算层（badges.py）：纯函数 / 易测 / 改规则不动 SQL
# 类比：厨房分"备菜员（切配）"和"厨师（炒）"——职责分清，未来换菜单（规则）只动厨师，
# 不用让备菜员重新学进货。


def _aggregate_badges_input(db: Session, user_id: int) -> dict:
    """聚合 badges.compute_badges 需要的全部输入字段（单次 SQL / 防 N+1）。

    数据来源：
    - users 表：ftp / city（看自己 ORM 拿）
    - activities 表：累计 distance / elevation_gain（completed + 非 duplicate）
    - segment_efforts JOIN segments：top 5 山名频次（group_by + count + 稳定排序）

    红线：
    - Activity 字段名 = distance / elevation_gain（不是 distance_m / elevation_gain_m）
    - 过滤 status == "completed" + duplicate_of IS NULL（Sprint 5 dedupe 兼容）
    - 山名稳定排序：count desc + segment_id asc（与 badges.py 内部 tie-breaker 一致 / 避免不同 DB 行为差异）
    """
    # 用 Session.get(Model, pk)——SQLA 2.0 推荐主键查询 API / 走 identity map / 快
    # 不用 db.query(User).get() 是因为后者在 2.0 已是 LegacyAPIWarning。
    # 类比："凭身份证号去户籍处取档案" vs "翻完整本户口本找名字" —— 主键查询一击即中。
    user = db.get(User, user_id)
    if user is None:
        # 异常路径：调用方（如 get_user_profile_for_others）会自己 raise ValueError("用户不存在")
        # 这里返回"空"输入让 compute_badges 返 []，不抛异常（防御性 / 不会 500）
        return {
            "ftp": None,
            "total_distance_m": 0.0,
            "total_elevation_m": 0.0,
            "city": None,
            "top_segments": [],
        }

    # ----- 累计距离 / 爬升（一次 SQL）-----
    stats = (
        db.query(
            _func.coalesce(_func.sum(_Activity.distance), 0).label("total_distance"),
            _func.coalesce(_func.sum(_Activity.elevation_gain), 0).label("total_elevation"),
        )
        .filter(
            _Activity.user_id == user_id,
            _Activity.status == "completed",
            _Activity.duplicate_of.is_(None),  # Sprint 5 dedupe：跳过 duplicate 防双倍计数
            _Activity.activity_type == "cycling",  # Sprint 7 Fix 7：总里程勋章只算骑行
        )
        .one()
    )

    # ----- 山名 top 5 频次（一次 SQL / group_by + count）-----
    # 延迟 import 避免模块循环依赖（segment 模块可能反向引用 user）
    from app.segment.models import Segment, SegmentEffort

    top_segments_rows = (
        db.query(
            SegmentEffort.segment_id,
            Segment.name.label("segment_name"),
            _func.count().label("cnt"),
        )
        .join(Segment, SegmentEffort.segment_id == Segment.id)
        .filter(SegmentEffort.user_id == user_id)
        .group_by(SegmentEffort.segment_id, Segment.name)
        # 稳定排序：count desc + segment_id asc（与 compute_badges 内部 tie-breaker 完全一致）
        .order_by(_func.count().desc(), SegmentEffort.segment_id.asc())
        .limit(5)
        .all()
    )

    return {
        "ftp": user.ftp,
        "total_distance_m": float(stats.total_distance or 0),
        "total_elevation_m": float(stats.total_elevation or 0),
        "city": user.city,
        "top_segments": [
            {
                "segment_id": r.segment_id,
                "segment_name": r.segment_name,
                "count": int(r.cnt),
            }
            for r in top_segments_rows
        ],
    }


def get_city_medals(db: Session, user_id: int) -> dict:
    """计算用户的城市征服勋章列表（Sprint 6 task-3 / 自他对称的统一入口）。

    干啥：聚合用户哪几个城市骑过 completed 活动 / 返已点亮列表 + 全 6 城 medal 数组。
    自他对称（D-P08 红线 / 与 get_user_badges 同模式）：看自己 = 看他人字段集合一致。

    过滤规则（不可漏）：
        - activities.status == 'completed'  —— 排除 pending / processing / failed
        - activities.duplicate_of IS NULL    —— Sprint 5 task-2 dedupe 排除重复行
        - activities.city IS NOT NULL        —— 排除"从未推断过"的旧数据
        - activities.city IN VALID_CITY_CODES —— 排除 'unknown' + 任何脏数据
          （白名单 in() 比黑名单 != 'unknown' 更安全 / 未来加新城自动跟随 cities.py）

    性能：单条 GROUP BY SQL / partial index 命中（idx_activities_user_city_completed）/
    1000 条 activity 用户聚合 < 100ms。

    参数：
        db: SQLAlchemy Session
        user_id: 目标用户 ID（self 或 others）

    返回：dict 形态与 schemas.CityMedalsResponse 字段集完全一致。

    抛错：本函数不抛 / 用户不存在时返 unlocked=[] / count=0（查不存在用户的 404 由 router 层兜）。
    """
    # 延迟 import 避免模块加载期循环（cities.py → geo.py 一条链）
    from app.user.cities import CITY_LABELS, VALID_CITY_CODES

    # 单条 SQL / GROUP BY / partial index 命中 / 不引入 N+1
    unlocked_rows = (
        db.query(_Activity.city)
        .filter(
            _Activity.user_id == user_id,
            _Activity.status == "completed",
            _Activity.duplicate_of.is_(None),  # Sprint 5 task-2 dedupe
            _Activity.activity_type == "cycling",  # Sprint 7 Fix 7：城市勋章只算骑行
            _Activity.city.isnot(None),  # 排除从未推断过
            _Activity.city.in_(VALID_CITY_CODES),  # 排除 unknown / 脏数据 / 白名单
        )
        .group_by(_Activity.city)
        .all()
    )

    # set 去重 + sorted 给前端稳定顺序（虽然 GROUP BY 本身已去重，再 set 一次防多列查询误用）
    unlocked = sorted({row[0] for row in unlocked_rows})

    medals = [
        {"city": code, "label": CITY_LABELS[code], "unlocked": code in unlocked}
        for code in VALID_CITY_CODES
    ]

    return {
        "unlocked": unlocked,
        "unlocked_count": len(unlocked),
        "total": len(VALID_CITY_CODES),  # 6
        "medals": medals,
    }


def get_user_badges(db: Session, user_id: int) -> list[dict]:
    """计算指定用户的身份徽章列表（top 3 / 自他对称的统一入口）。

    本函数在 router / get_user_profile_for_others / 任何需要 badges 的入口都共用——
    保证看自己 vs 看他人字段集合完全一致（D-P08 红线）。

    返回值是 list[{"type": str, "label": str}]，与 schemas.Badge 字段集一致。
    """
    # 延迟 import 避免模块加载期循环（badges.py → cities.py → geo.py 一条链）
    from app.user.badges import compute_badges

    inputs = _aggregate_badges_input(db, user_id)
    return compute_badges(**inputs)
