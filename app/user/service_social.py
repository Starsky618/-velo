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
    - **双 cache key 形态**：无 city 与按 city 路径分别缓存；v2 前缀隔离旧全量响应，
      invalidate_heatmap_cache 同时清新旧 key，避免历史大对象残留
    - **GCJ-02 坐标转换在前端**：后端返 WGS-84 原始坐标 [lon, lat]；前端拿到后转 GCJ-02 给高德地图
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
_HEATMAP_CACHE_PREFIX = "heatmap:v2:user_"
_HEATMAP_LEGACY_CACHE_PREFIX = "heatmap:user_"
_HEATMAP_POINTS_PER_ACTIVITY = 64
_HEATMAP_TOTAL_POINT_BUDGET = 20_000
_HEATMAP_MAX_PREVIEW_TRACKS = _HEATMAP_TOTAL_POINT_BUDGET // 2
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


def _get_redis_client():
    """延迟导入 redis_conn—— 让纯单元测试不依赖 Redis 启动（task-0.8 单一连接源 / Q1 a 独立复制 / 与 service_stats 一致）。"""
    from app.queue import redis_conn
    return redis_conn


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
    """生成固定尺寸热图卡需要的显示精度轨迹，避免下发活动原始点集。

    Strava 的个人热图先在服务端按瓦片/像素聚合，客户端只取当前视野的热图块。
    VELO 当前只有 327x240 的静态卡片，完整瓦片服务过重；这里采用同一原则的
    小型版本：服务端一次遍历选关键拐点 + 坐标定精度 + Redis 缓存。

    每条活动最多 64 个关键点，整张卡最多 2 万点。293 条活动的上限约 1.9 万点，
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

    reduced = _select_heatmap_key_points(clean, max(2, min(point_limit, _HEATMAP_POINTS_PER_ACTIVITY)))

    # 5 位小数约 1 米，远高于 327x240 卡片的像素分辨率；继续保留更多小数只增流量。
    return [[round(float(p["lon"]), 5), round(float(p["lat"]), 5)] for p in reduced]


def _normalize_heatmap_source_point(point: object) -> dict | None:
    """校验数据库轨迹点并统一为有限、合法的 WGS-84 坐标。"""
    if not isinstance(point, dict):
        return None
    try:
        lat = float(point.get("lat"))
        lon = float(point.get("lon"))
    except (TypeError, ValueError):
        return None
    if not (_math.isfinite(lat) and _math.isfinite(lon)):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return {"lat": lat, "lon": lon, "ele": point.get("ele")}


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
    track = getattr(activity, "simplified_track", None)
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
        if _has_heatmap_line(getattr(activity, "simplified_track", None))
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


def _heatmap_points_per_activity(activity_count: int) -> int:
    """把用户整张卡的输出锁在 2 万点内，而不是让 64×活动数无限增长。"""
    if activity_count <= 0:
        return _HEATMAP_POINTS_PER_ACTIVITY
    return max(2, min(_HEATMAP_POINTS_PER_ACTIVITY, _HEATMAP_TOTAL_POINT_BUDGET // activity_count))


def get_user_heatmap(db: Session, user_id: int, city: str | None = None) -> dict:
    """
    用户骑行热图——"我去过哪些地方"。

    把用户的骑行轨迹生成**显示精度预览**并保留 activity 边界，前端拿来画
    polyline 路径线（每条 activity 一条线）+ 多条 opacity 叠加形成热力效果。
    不把 simplified_track 全量下发：固定 327x240 卡片看不到亚像素细节，巨量 JSON
    只会拖慢网络、解析和小程序逻辑层。整张响应另有 2 万点硬预算；极端超过
    1 万条活动时按地理桶选代表轨迹，优先保留所有骑行区域的可见性。

    city 参数（v3 polish / Sprint 4 task-4.2 v3）：
    - city is None → 返回该用户**所有** completed activities 的轨迹（不按城市筛 /
      response.city 也是 None）。前端"全部"视图走这条路径，一次性看跨城市足迹。
    - city 有值 → 保留旧行为：按 simplified_track 起点城市筛
      （infer_city_from_coords 是 common.geo 纯函数 / spec §1.3）。

    D27 v2 polish（Sprint 4 task-4.2 v2）：从扁平 multipoint.coordinates
    改为 tracks: list[list[[lon,lat]]] —— 保留 activity 边界让前端画 polyline，
    不再用 markers 点 / 视觉接近 ride.fitcard.app 80%。

    Redis 缓存 TTL 1h，v2 key 隔离旧版 6.7 MB 全量缓存：
    - 无 city 路径：`heatmap:v2:user_{user_id}`
    - 有 city 路径：`heatmap:v2:user_{user_id}:city_{city}`
    update_user_city 清缓存通过 invalidate_heatmap_cache 双清：按 city 路径 +
    无 city 路径两种形态都清（D27 v3 polish Critical 修 / 保证改主城后下次拿最新轨迹）。

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
          "activity_count": 12
        }
    """
    # cache key 设计：city is None 走无 city 后缀的独立 v2 key；有 city 追加 city 后缀。
    # v2 前缀确保发布后不会命中旧版全量轨迹缓存。
    if city is None:
        cache_key = f"{_HEATMAP_CACHE_PREFIX}{user_id}"
    else:
        cache_key = f"{_HEATMAP_CACHE_PREFIX}{user_id}:city_{city}"
    redis_client = _get_redis_client()
    cached = redis_client.get(cache_key)
    if cached is not None:
        return _json.loads(cached.decode() if isinstance(cached, bytes) else cached)

    # 查该用户所有 completed activities + 有 simplified_track 的
    # Sprint 5 task-2 dedupe：跳过 duplicate 防 heatmap 同轨迹双显
    activities = (
        db.query(_Activity)
        .filter(
            _Activity.user_id == user_id,
            _Activity.status == "completed",
            _Activity.duplicate_of.is_(None),
            _Activity.activity_type == "cycling",  # Sprint 7 Fix 7：防非骑行污染热力图
            _Activity.simplified_track.isnot(None),
        )
        .all()
    )

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

    # 保留 activity 边界 / 每个 activity 输出一条显示精度轨迹。
    # 除每活动 64 点上限外，再限制整张卡最多 2 万点。超过 1 万条活动时按
    # 地理桶轮询选代表轨迹，优先保住稀有旅行区域，而不是只截最近/常骑城市。
    preview_activities = _select_heatmap_preview_activities(filtered, _HEATMAP_MAX_PREVIEW_TRACKS)
    point_limit = _heatmap_points_per_activity(len(preview_activities))
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
    }

    redis_client.setex(cache_key, _HEATMAP_CACHE_TTL_SEC, _json.dumps(result))
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

    覆盖 v2 显示精度缓存和旧版全量缓存的无 city / 按 city 两种形态。

    场景：
    - 用户上传新 activity completed → worker hook 调本函数 → 下次刷个人页拿最新轨迹
    - 用户改主城（update_user_city）→ 调本函数 → 防旧 city 缓存延续

    why scan_iter 配合 delete：scan_iter 不阻塞 / delete 单 key 直删 / 两者组合覆盖两种 key 形态。

    ⚠ 调用方：app/activity/worker.py:198 + 本文件 update_user_city / 拆分时通过 service.py 转导出 0 改动
    """
    redis_client = _get_redis_client()
    # 新 v2 预览缓存 + 旧全量缓存一起失效；旧 key 会在自然 TTL 后消失，
    # 双删保证上传新活动时不会留下历史大对象。
    for prefix in (_HEATMAP_CACHE_PREFIX, _HEATMAP_LEGACY_CACHE_PREFIX):
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
