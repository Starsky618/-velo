"""
用户模块的业务逻辑层——真正干活的地方。

如果 router.py 是前台接待员（接收请求、返回结果），
那 service.py 就是后台办事员（处理业务、操作数据库）。

前台不直接碰数据库，所有脏活累活都交给这里。
这样做的好处：前台只管接客，后台只管办事，各司其职，方便测试和替换。

注意事项：
- 所有数据库操作都在这里完成，router 层不直接操作数据库
- 距离单位转换（米→公里）也在这里做，router 层拿到的就是最终数据
- 不要在这里 import router 或 schemas（避免循环依赖）
"""

from datetime import datetime, timedelta, timezone

import httpx
import jwt
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from app.config import settings
from app.user.models import User

# 北京时间偏移量（UTC+8）
# 统计"本周""本月"等时间范围时，要用用户所在时区的零点做分界，
# 而不是 UTC 零点。比如周一凌晨 0 点北京时间 = 周日下午 4 点 UTC。
BEIJING_TZ = timezone(timedelta(hours=8))

# JWT 配置
# HS256 是一种对称加密算法——用同一把钥匙签名和验证
# 对 MVP 阶段完全够用，简单可靠
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_DAYS = 7


def wx_code_to_openid(code: str) -> str:
    """
    拿微信授权 code 去微信服务器换取用户的 openid。

    流程就像：用户拿着一张"临时号码牌"（code）来前台，
    前台打电话给微信总部确认："这个号码牌是真的吗？对应哪个用户？"
    微信总部回复："是真的，这个人的身份编号是 xxx（openid）。"

    code 是一次性的，用过就作废，5分钟内有效。
    """
    # 调用微信 jscode2session 接口
    # 网络异常（超时、连接失败等）统一包装为 ValueError，
    # 让 router 层能用同一个 except ValueError 捕获所有错误
    try:
        resp = httpx.get(
            "https://api.weixin.qq.com/sns/jscode2session",
            params={
                "appid": settings.WX_APPID,
                "secret": settings.WX_SECRET,
                "js_code": code,
                "grant_type": "authorization_code",
            },
            timeout=10,
        )
        data = resp.json()
    except httpx.HTTPError:
        raise ValueError("微信授权失败")

    # 微信返回 errcode 表示出错
    if "errcode" in data and data["errcode"] != 0:
        # errcode 40029 表示 code 过期或无效
        if data["errcode"] == 40029:
            raise ValueError("code已过期，请重新授权")
        raise ValueError("微信授权失败")

    openid = data.get("openid")
    if not openid:
        raise ValueError("微信授权失败")

    return openid


def get_or_create_user(db: Session, openid: str) -> tuple[User, bool]:
    """
    用 openid 查找用户，找到就返回，找不到就新建一个。

    返回值是一个元组：(用户对象, 是否是新用户)
    就像小区门卫查花名册：名字在册就放行，不在册就登记一个新住户。
    """
    user = db.query(User).filter_by(openid=openid).first()
    if user:
        return user, False

    # 新用户：只记录 openid，其他信息（昵称、头像等）后续通过编辑资料填写
    user = User(openid=openid)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user, True


def create_token(user_id: int) -> str:
    """
    给用户签发一张 JWT "通行证"。

    JWT 就像一张带防伪标记的临时工牌：
    - 上面写着你的工号（user_id）和有效期（7天）
    - 盖了公司的章（用 JWT_SECRET 签名）
    - 任何人拿到这张工牌都能看到上面的信息，但没有公章就伪造不了
    """
    expire = datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRE_DAYS)
    payload = {
        "sub": str(user_id),  # sub 是 JWT 标准字段，表示"这张证属于谁"
        "exp": expire,        # 过期时间，到期后自动作废
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> int:
    """
    验证并解析 JWT，返回 user_id。

    就像门卫检查工牌：看防伪标记对不对、有没有过期。
    通过了就放行（返回工号），不通过就拦下（抛异常）。
    """
    payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[JWT_ALGORITHM])
    user_id_str = payload.get("sub")
    if user_id_str is None:
        raise ValueError("无效凭证")
    return int(user_id_str)


# ========== 任务 2.4：用户资料 ==========

def get_user_by_id(db: Session, user_id: int) -> User:
    """
    根据 user_id 查找用户。
    找不到说明数据异常（JWT 里的 id 在数据库里不存在），直接抛异常。
    """
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        raise ValueError("用户不存在")
    return user


def update_user_profile(db: Session, user_id: int, update_data: dict) -> User:
    """
    更新用户资料。

    只更新前端传过来的字段，没传的保持不变。
    就像修改住户档案：只改你说要改的栏目，其他栏目原样保留。
    """
    user = get_user_by_id(db, user_id)

    # 遍历要更新的字段，逐个修改
    for field, value in update_data.items():
        setattr(user, field, value)

    db.commit()
    db.refresh(user)
    return user


# ========== 任务 2.5：骑行统计 ==========

def _get_period_start(period: str) -> datetime | None:
    """
    根据统计范围，计算起始时间点（北京时间零点，转为 UTC）。

    比如 period="week"：找到本周一的北京时间 00:00:00，再转成 UTC 存储时间。
    period="all" 返回 None，表示不加时间条件。
    """
    # 先拿当前北京时间
    now_bj = datetime.now(BEIJING_TZ)

    if period == "week":
        # weekday() 返回 0=周一, 6=周日
        # 先把时分秒归零得到"今天零点"，再往前退 weekday 天得到本周一零点
        # 例：北京时间 2026-04-08 周三 → weekday()=2 → 退2天 → 2026-04-06 周一 00:00 UTC+8
        today_start = now_bj.replace(hour=0, minute=0, second=0, microsecond=0)
        monday = today_start - timedelta(days=now_bj.weekday())
        return monday.astimezone(timezone.utc)
    elif period == "month":
        first_day = now_bj.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return first_day.astimezone(timezone.utc)
    elif period == "year":
        first_day = now_bj.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        return first_day.astimezone(timezone.utc)
    else:
        # period == "all"
        return None


def get_user_stats(db: Session, user_id: int, period: str) -> dict:
    """
    聚合用户的骑行统计数据。

    直接用 SQL 查 activities 表，不 import Activity 模块的任何代码。
    这样 User 模块保持独立，不依赖 Activity 模块的实现细节。

    好比物业管理处直接看门禁刷卡记录统计出入次数，
    不需要去问住户"你今天进出了几次"。
    """
    # 构建 SQL：从 activities 表聚合已完成的骑行记录
    period_start = _get_period_start(period)

    # activities 表在 Task 3.1 才会创建，在此之前查询会报 ProgrammingError。
    # 捕获这个异常，返回全零数据，避免 500 错误。
    try:
        if period_start is not None:
            sql = text("""
                SELECT
                    COALESCE(SUM(distance), 0)       AS distance,
                    COUNT(*)                         AS rides,
                    COALESCE(SUM(elevation_gain), 0) AS elevation_gain,
                    COALESCE(SUM(duration), 0)       AS duration
                FROM activities
                WHERE user_id = :user_id
                  AND status = 'completed'
                  AND started_at >= :period_start
            """)
            row = db.execute(sql, {"user_id": user_id, "period_start": period_start}).fetchone()
        else:
            # period == "all"：不加时间条件
            sql = text("""
                SELECT
                    COALESCE(SUM(distance), 0)       AS distance,
                    COUNT(*)                         AS rides,
                    COALESCE(SUM(elevation_gain), 0) AS elevation_gain,
                    COALESCE(SUM(duration), 0)       AS duration
                FROM activities
                WHERE user_id = :user_id
                  AND status = 'completed'
            """)
            row = db.execute(sql, {"user_id": user_id}).fetchone()

        distance_m = float(row.distance)
        rides = int(row.rides)
        elevation_gain = float(row.elevation_gain)
        duration = int(row.duration)
    except ProgrammingError:
        # activities 表尚未创建，回滚事务（ProgrammingError 会让当前事务失效），返回全零
        db.rollback()
        distance_m = 0.0
        rides = 0
        elevation_gain = 0.0
        duration = 0

    # 距离：米 → 公里，保留 1 位小数
    distance_km = round(distance_m / 1000.0, 1)

    # 获取用户的周目标
    # 防御性处理：server_default 在 ORM 创建后 refresh 才生效，极端情况可能为 None
    user = get_user_by_id(db, user_id)
    weekly_goal = float(user.weekly_goal) if user.weekly_goal is not None else 200.0

    # 完成百分比：distance_km / weekly_goal * 100，向下取整
    goal_percent = int(distance_km / weekly_goal * 100) if weekly_goal > 0 else 0

    return {
        "period": period,
        "distance": distance_km,
        "rides": rides,
        "elevation_gain": elevation_gain,  # 爬升单位是米，直接返回，不做转换
        "duration": duration,
        "weekly_goal": weekly_goal,
        "goal_percent": goal_percent,
    }


# ========== task-2.C.2：功率曲线 service + Redis 缓存 ==========
#
# 用户视角：进个人主页"功率曲线"卡片 → 看到"5min 最佳 240W"等 7 档时长（D26 v2 polish）。
# 后端路径：
#   1. cache 命中 → 直接返（毫秒级）
#   2. cache miss → 查 period 内 activities → 跨 activity 算曲线 → 写 cache → 返
#   3. 用户上传新 activity → invalidate_power_curve_cache(user_id) → 清所有 period 缓存
#
# Redis key 结构：power_curve:user_{user_id}:period_{period}（TTL 1h）

import json as _json
from app.activity.models import Activity, Trackpoint
from app.activity.power_zones import calculate_power_curve_from_activities

# 1h 缓存。短了 cache 命中率不达标（PRD 要求 > 80%），长了用户上传后看不到"刚才骑行"
# 影响曲线（虽然 invalidate 会清，但万一 invalidate 失败 → 1h 自然过期兜底）
_POWER_CURVE_CACHE_TTL_SEC = 3600

# Redis key 前缀（统一在此声明，scan 和 set 都引用）
_POWER_CURVE_CACHE_PREFIX = "power_curve:user_"


def _get_redis_client():
    """延迟导入 redis_conn—— 让纯单元测试不依赖 Redis 启动（task-0.8 单一连接源）。"""
    from app.queue import redis_conn
    return redis_conn


def _power_curve_period_window(period: str) -> tuple[datetime, datetime]:
    """
    计算 period 时间窗口 — 滚动窗口型（D16 v0.3 / Sprint 4 task-pre-4.2 升级）。

    period 枚举（5 档 / PowerCurvePeriod）：
    - last_30_days  → 今天往前数 30 天
    - last_90_days  → 今天往前数 90 天
    - last_180_days → 今天往前数 180 天
    - last_365_days → 今天往前数 365 天（"近一年"）
    - all_time      → 1970-01-01 起全部数据

    返回 (start_utc, end_utc) tuple，用于 DB 查询。

    why 滚动窗口而非自然历法切片：
    - 自然历法（this_month）：5 月 1 号那天看只有 1 天数据 / 5 月 31 号那天看 31 天
    - 滚动窗口（last_30_days）：任何时间打开都是稳定 N 天 / 进步对比直观

    时区约定：start/end 都按 UTC 计算（datetime.now(UTC) - timedelta(days=N)），
    不需要按北京时间划月——滚动窗口对时区不敏感（差 8 小时 vs N 天的尺度可忽略）。
    """
    from datetime import timedelta

    now_utc = datetime.now(timezone.utc)

    rolling_days = {
        "last_30_days": 30,
        "last_90_days": 90,
        "last_180_days": 180,
        "last_365_days": 365,
    }

    if period in rolling_days:
        start = now_utc - timedelta(days=rolling_days[period])
        return start, now_utc

    if period == "all_time":
        return datetime(1970, 1, 1, tzinfo=timezone.utc), now_utc

    raise ValueError(f"unknown period: {period}")


def get_user_power_curve(
    db: Session, user_id: int, period: str = "last_30_days"
) -> dict:
    """
    用户功率曲线（按 period 切片）+ Redis 缓存——"用户的训练成绩单"。

    把用户最近一段时间的所有骑行数据放在一起，算 7 档时长（D26 v2 polish）：
    0s 瞬时最大 / 3s / 30s / 1min / 5min / 20min / 1h —— 各自的最佳平均功率。
    比如 5 分钟：最近 30 天内你最好 5 分钟的平均输出多少瓦——这是衡量
    持续输出能力的核心指标，也是用户拿来跟自己历史 / 跟朋友对比的"成绩单"。

    period 切片是滚动窗口型（D16 v0.3 / Sprint 4 task-pre-4.2 升级）：
    last_30_days / last_90_days / last_180_days / last_365_days / all_time。
    缓存 key: power_curve:user_{user_id}:period_{period}，TTL 1h。

    返回 dict：
        {"period": "last_30_days", "buckets": {1: 850.0, 5: 720.0, ..., 1200: 220.0}}

    陷阱守卫：
    - redis-py 7+ 默认返 bytes（陷阱 #5）→ json.loads 前需 decode
    - 跨 activity 必须用 calculate_power_curve_from_activities 不要直接拼 trackpoints
      （陷阱：跨日合并出现虚假 5min 极值）
    - 时区：滚动窗口对时区不敏感 / 用 datetime.now(timezone.utc) 不用 utcnow（陷阱 #2）
    """
    # 1. Cache lookup
    cache_key = f"{_POWER_CURVE_CACHE_PREFIX}{user_id}:period_{period}"
    redis_client = _get_redis_client()
    cached = redis_client.get(cache_key)
    if cached is not None:
        # redis-py 7+ 默认返 bytes
        # 用 is not None 不用 truthy（CLAUDE.md 陷阱 #1）：理论上不会缓存空字符串，
        # 但严谨防御 —— 假设未来有人写 setex(..., "") 不会被错当 cache miss
        return _json.loads(cached.decode() if isinstance(cached, bytes) else cached)

    # 2. period 时间窗口（提前算 / 失败抛 ValueError）
    start, end = _power_curve_period_window(period)

    # 3. 查 period 内 completed activities + trackpoints（按 activity 分组）
    # 禁止跨 activity 拼接 trackpoints —— 用 from_activities 取 per-window max
    activity_ids = (
        db.query(Activity.id)
        .filter(
            Activity.user_id == user_id,
            Activity.status == "completed",
            Activity.started_at >= start,
            Activity.started_at < end,
        )
        .all()
    )

    activities_trackpoints = []
    for (act_id,) in activity_ids:
        tps = (
            db.query(Trackpoint)
            .filter(Trackpoint.activity_id == act_id)
            .order_by(Trackpoint.seq)
            .all()
        )
        activities_trackpoints.append(tps)

    # 4. 计算（每 activity 独立算后取 per-window max）
    # calculate_power_curve_from_activities 返 dict[int → float]
    # service 层统一转成 str key —— 因为：
    #   a) cache miss 路径若返 int key，写入 Redis 后 json.dumps 转 str，
    #      下次 cache hit 反序列化得 str key → 调用方两次拿到不同类型 dict
    #   b) FastAPI JSON 序列化也会把 dict int key 转 str → 前端拿到的本来就是 str
    # 统一在 service 层转换，让上下游类型稳定 + 与 JSON 协议一致
    curve_int_key = calculate_power_curve_from_activities(activities_trackpoints)
    curve = {str(k): v for k, v in curve_int_key.items()}
    result = {"period": period, "buckets": curve}

    # 5. Cache SET
    redis_client.setex(cache_key, _POWER_CURVE_CACHE_TTL_SEC, _json.dumps(result))
    return result


def invalidate_power_curve_cache(user_id: int) -> None:
    """
    清除用户 power_curve 全部 period 缓存——"通知账房先生重新算账"。

    场景：用户上传新 activity → 最近 30/90/180/365 天最佳功率可能变化 → 缓存的曲线作废。
    用 scan_iter 找所有 period（last_30_days / last_90_days / ... / all_time）
    对应的 key，逐个删。

    why scan_iter 不直接 keys：keys 命令在大 Redis 上会阻塞数十秒（生产事故级），
    scan_iter 是 cursor 模式不阻塞，对全库友好。

    why 不只删几个固定 period：未来加新 period（如 last_7_days / last_quarter）时本函数
    自动覆盖；硬编码列表会漏。
    """
    pattern = f"{_POWER_CURVE_CACHE_PREFIX}{user_id}:*"
    redis_client = _get_redis_client()
    for key in redis_client.scan_iter(match=pattern):
        redis_client.delete(key)


# ========== task-2.C.2 余下 3 函数：heatmap + update_city + profile_for_others ==========
#
# 与 power_curve 的关系：
# - power_curve 是"训练成绩单"（看自己进步 / 数据由 trackpoints 重新计算 + 缓存）
# - heatmap 是"我去过哪儿"（按城市筛 simplified_track 起点 / 聚合所有点位）
# - profile_for_others 是"别人怎么看我"（严格白名单字段 / 不返 efforts/strava_token 等）
# - update_user_city 是"用户手动改主城市"（settings 改完顺手清掉旧 heatmap 缓存）
#
# 6 主城枚举（与 segments.city 一致）：beijing / shanghai / hangzhou / shenzhen / chengdu / taiyuan
# 加 'unknown' 兜底：用户填了"我不在这 6 城" → 'unknown'，与 NULL（未填写）语义不同

from sqlalchemy import func as _func

from app.activity.models import Activity as _Activity
from app.common.geo import infer_city_from_coords as _infer_city_from_coords

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


def get_user_heatmap(db: Session, user_id: int, city: str) -> dict:
    """
    用户在指定城市的骑行热图——"我在这座城里去过哪些地方"。

    把用户在该城市的所有骑行轨迹**保留 activity 边界**返回 list of tracks，
    前端拿来画 polyline 路径线（每条 activity 一条线）+ 多条 opacity 0.5 重叠
    自然形成"骑过越多越亮"的热力效果。
    城市筛选基于 simplified_track 起点（activity 表无 start_lat/lon 字段）。

    D27 v2 polish（Sprint 4 task-4.2 v2）：从扁平 multipoint.coordinates
    改为 tracks: list[list[[lon,lat]]] —— 保留 activity 边界让前端画 polyline，
    不再用 markers 点 / 视觉接近 ride.fitcard.app 80%。

    Redis 缓存 TTL 1h（用户上传新活动后 update_user_city 不会触发清缓存——
    清缓存职责由 worker hook 或 update_user_city 承担）。

    陷阱守卫：
    - 陷阱 #5（redis-py 7+ 默认返 bytes）→ json.loads 前 decode
    - `if cached is not None`（CLAUDE.md 陷阱 #1 / 与 power_curve 一致）

    返回结构：
        {
          "city": "beijing",
          "tracks": [
            [[lon, lat], [lon, lat], ...],  # activity 1 的轨迹
            [[lon, lat], [lon, lat], ...],  # activity 2 的轨迹
            ...
          ],
          "activity_count": 12
        }
    """
    cache_key = f"{_HEATMAP_CACHE_PREFIX}{user_id}:city_{city}"
    redis_client = _get_redis_client()
    cached = redis_client.get(cache_key)
    if cached is not None:
        return _json.loads(cached.decode() if isinstance(cached, bytes) else cached)

    # 查该用户所有 completed activities + 有 simplified_track 的
    activities = (
        db.query(_Activity)
        .filter(
            _Activity.user_id == user_id,
            _Activity.status == "completed",
            _Activity.simplified_track.isnot(None),
        )
        .all()
    )

    # 起点城市筛（infer_city_from_coords 是 common.geo 纯函数 / spec §1.3 / B2A-2 修复反向依赖）
    filtered = []
    for a in activities:
        track = a.simplified_track
        if not track or len(track) == 0:
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

    # 失效该用户所有 city 的热图缓存（pattern: heatmap:user_{id}:*）
    pattern = f"{_HEATMAP_CACHE_PREFIX}{user_id}:*"
    redis_client = _get_redis_client()
    for key in redis_client.scan_iter(match=pattern):
        redis_client.delete(key)

    return user


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
    - 通过：id / nickname / avatar_url / city / ftp / bike_type +
      total_distance_km / total_elevation_m / activity_count / current_month_summary
    - 拦截：efforts / activities / heatmap / strava_* / openid / mute_notifications / 任何 token
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
