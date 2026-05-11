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
    - **双 cache key 形态**：无 city 路径 `heatmap:user_{id}` vs 按 city 路径
      `heatmap:user_{id}:city_{city}`；invalidate_heatmap_cache 必须双删（v3 polish Critical 修）
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
_HEATMAP_CACHE_PREFIX = "heatmap:user_"
_VALID_USER_CITIES = {
    "beijing", "shanghai", "hangzhou", "shenzhen", "chengdu", "taiyuan", "unknown",
}

# 看他人主页严格白名单（PRD 5.A.2 / D-P08 红线 / spec R3-I3 强制生效）
# 加新字段前先 review：是否泄漏 token / openid / mute_notifications / 任何隐私字段？
# Sprint 4 codex 异源审 2026-05-06 砍 ftp（P1-4）：
#     FTP 是骑手生理数据 / Strava 也允许独立隐私层 / Tim "默认公开"是页面层 ≠ 字段层
_PROFILE_RESPONSE_KEYS = {
    "id", "nickname", "avatar_url", "city", "bike_type",
    "total_distance_km", "total_elevation_m", "activity_count",
    "current_month_summary",
}


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


def get_user_heatmap(db: Session, user_id: int, city: str | None = None) -> dict:
    """
    用户骑行热图——"我去过哪些地方"。

    把用户的所有骑行轨迹**保留 activity 边界**返回 list of tracks，
    前端拿来画 polyline 路径线（每条 activity 一条线）+ 多条 opacity 0.5 重叠
    自然形成"骑过越多越亮"的热力效果。

    city 参数（v3 polish / Sprint 4 task-4.2 v3）：
    - city is None → 返回该用户**所有** completed activities 的轨迹（不按城市筛 /
      response.city 也是 None）。前端"全部"视图走这条路径，一次性看跨城市足迹。
    - city 有值 → 保留旧行为：按 simplified_track 起点城市筛
      （infer_city_from_coords 是 common.geo 纯函数 / spec §1.3）。

    D27 v2 polish（Sprint 4 task-4.2 v2）：从扁平 multipoint.coordinates
    改为 tracks: list[list[[lon,lat]]] —— 保留 activity 边界让前端画 polyline，
    不再用 markers 点 / 视觉接近 ride.fitcard.app 80%。

    Redis 缓存 TTL 1h，**两套独立 cache key**：
    - 无 city 路径：`heatmap:user_{user_id}` （新增 / v3 polish）
    - 有 city 路径：`heatmap:user_{user_id}:city_{city}` （保留旧 key 不变 / 兼容）
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
    # cache key 设计：city is None 走"无 city 后缀"的独立 key —— 与按 city 筛的 key 形态
    # 不同（`heatmap:user_{id}` vs `heatmap:user_{id}:city_{city}`），
    # 让 update_user_city 的 `heatmap:user_{id}:*` 失效 pattern 不会误命中无 city 的 key。
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

    # 保留 activity 边界 / 每个 activity 输出一条独立轨迹（D27 v2 polish）
    # 前端画 polyline 时一条 activity 一条 polyline / 多条重叠 opacity 0.5 自然成热力
    # ⚠ 单点 activity 跳过：polyline 至少 2 点才能成线 / 单点会被前端 _convertToPolylines 跳过
    # 后端同步过滤防"activity_count > 0 但 polylines 空 / 用户看到地图无线条"假象（Codex 异源审 Important）
    tracks = []
    valid_count = 0
    for a in filtered:
        track_points = []
        for pt in a.simplified_track:
            lat = pt.get("lat")
            lon = pt.get("lon")
            if lat is not None and lon is not None:
                track_points.append([lon, lat])  # GeoJSON 顺序 [lon, lat]
        if len(track_points) >= 2:  # 至少 2 点才能成 polyline
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
    用户主动改主城市——"用户在 settings 页选了一个城市"。

    动作：
    1. 校验 city ∈ 7 主城枚举（含 'unknown' / 含 NULL 表示清空）
    2. 找到 user 行（不存在抛 ValueError，不是 404）
    3. 改字段并 commit
    4. 清掉该用户所有 city 的 heatmap 缓存（用户改主城后旧缓存作废）

    陷阱守卫：
    - 陷阱 #4（.one() vs .first()）：用 .first() + 显式 ValueError
    - 接受 city=None 表示"清空选择"，与 nullable=True 一致

    抛错：
    - city 非法 → ValueError("invalid city: <值>")
    - user 不存在 → ValueError("user not found: <id>")
    """
    if city is not None and city not in _VALID_USER_CITIES:
        raise ValueError(f"invalid city: {city}")

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

    覆盖两种 cache key 形态（D27 v3 polish 加无 city 路径后必须双删 / Codex 异源审 Critical 修）：
    1. `heatmap:user_{id}` —— 无 city 路径（v3 新增 / 显示用户全部 activity 轨迹）
    2. `heatmap:user_{id}:city_{city}` —— 按 city 路径（v2 保留 / 兼容旧）

    场景：
    - 用户上传新 activity completed → worker hook 调本函数 → 下次刷个人页拿最新轨迹
    - 用户改主城（update_user_city）→ 调本函数 → 防旧 city 缓存延续

    why scan_iter 配合 delete：scan_iter 不阻塞 / delete 单 key 直删 / 两者组合覆盖两种 key 形态。

    ⚠ 调用方：app/activity/worker.py:198 + 本文件 update_user_city / 拆分时通过 service.py 转导出 0 改动
    """
    redis_client = _get_redis_client()
    # 1. 无 city 路径直接 delete（不需 scan / key 形态固定）
    no_city_key = f"{_HEATMAP_CACHE_PREFIX}{user_id}"
    redis_client.delete(no_city_key)
    # 2. 按 city 路径用 scan_iter（多个 city 各一个 key）
    pattern = f"{_HEATMAP_CACHE_PREFIX}{user_id}:*"
    for key in redis_client.scan_iter(match=pattern):
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
            _Activity.started_at >= first_of_month_utc,
        )
        .first()
    )

    raw_response = {
        "id": target.id,
        "nickname": target.nickname,
        "avatar_url": target.avatar_url,
        "city": target.city,
        "ftp": target.ftp,
        "bike_type": target.bike_type,
        "total_distance_km": round((totals.total_distance or 0) / 1000.0, 1),
        "total_elevation_m": round(totals.total_elevation or 0, 1),
        "activity_count": totals.activity_count or 0,
        "current_month_summary": {
            "distance_km": round((current_month.m_distance or 0) / 1000.0, 1),
            "elevation_m": round(current_month.m_elevation or 0, 1),
            "avg_power_w": round(current_month.m_avg_power or 0, 1),
        },
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
            "total_distance_km": round(float(r.total_distance_m) / 1000.0, 1),
            "activity_count": r.activity_count,
            "last_activity_at": r.last_activity_at,
        }
        for r in rows
    ]
