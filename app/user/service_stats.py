"""
用户骑行统计 + 功率曲线子模块——"训练成绩单"。

干啥用：
    - 个人主页"本周/本月骑了多少 km / 多少次 / 多少爬升"汇总（get_user_stats）
    - 功率曲线 7 档时长各自最佳平均功率（get_user_power_curve / 滚动窗口型 period）
    - 上传新 activity 时清功率曲线缓存（invalidate_power_curve_cache / worker hook 调）

类比：
    健身房教练给学员每周末出的"训练总结报告"——
    - 本周骑了 X 公里、爬升 Y 米（get_user_stats）
    - 各时长档位（0s / 3s / 30s / 1min / 5min / 20min / 1h）你最强的瓦数（get_user_power_curve）
    - 上传新一次骑行 = 训练记录更新 = 旧的曲线作废 → 通知教练重算（invalidate）

操作注意（关键）：
    - **裸 SQL 防反向依赖**：get_user_stats 用 `text("SELECT...")` 不 import Activity ORM
      保持 user 模块对 activity 模块的依赖最小化（v0 时代设计 choice / 拆分时不改风格）
    - **滚动窗口对时区不敏感**：last_30_days = now_utc - timedelta(days=30)
      不需按北京时间划月（差 8 小时 vs N 天的尺度可忽略 / D16 v0.3）
    - **N+1 hotfix 实证**：power_curve 用 IN 查询 + only 3 字段（2026-05-09 修 / all_time 24s → 1-2s）
    - **Sprint 5 task-2 dedupe**：所有聚合查询都加 `duplicate_of IS NULL` 跳过重复活动
    - **跨子文件依赖**：get_user_stats 调 service_auth.get_user_by_id 拿 weekly_goal
      （Q2 a 决策 / 严格单向 / service_auth 不反向 import 本文件）
    - **Redis cache TTL 1h**：短了命中率 < PRD 80%；长了用户刚上传看不到刚才骑行
    - **JSON int key 转 str**：cache miss 路径 dict {1: 850.0} 写 Redis 后 json.dumps 转 str
      下次 hit 反序列化得 str key → 统一 service 层转 str 让上下游类型稳定

数据流：
    入：user_id + period（week / month / year / all 或 last_30_days...）
    出：dict {distance, rides, elevation_gain, ...} / dict {period, buckets}
    边界：DB activities + Trackpoint 表 / Redis cache / calculate_power_curve_from_activities 算法包

不允许：
    - import service_social（保持单向依赖）
    - 在 stats 内部直接调 Activity ORM 修改字段（只读聚合 / 写操作在 worker）

v5 task-user-split-001：从 service.py 834 行拆出（commit TBD）。
"""

import json as _json
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from app.activity.models import Activity, Trackpoint
from app.activity.power_zones import calculate_power_curve_from_activities
from app.user.service_auth import get_user_by_id

# 北京时间偏移量（UTC+8）
# 统计"本周""本月"等时间范围时，要用用户所在时区的零点做分界，
# 而不是 UTC 零点。比如周一凌晨 0 点北京时间 = 周日下午 4 点 UTC。
# Q1 a 决策：与 service_social 各自独立复制（DRY 违反但 0 跨依赖）
BEIJING_TZ = timezone(timedelta(hours=8))

# 1h 缓存。短了 cache 命中率不达标（PRD 要求 > 80%），长了用户上传后看不到"刚才骑行"
# 影响曲线（虽然 invalidate 会清，但万一 invalidate 失败 → 1h 自然过期兜底）
_POWER_CURVE_CACHE_TTL_SEC = 3600

# Redis key 前缀（统一在此声明，scan 和 set 都引用）
_POWER_CURVE_CACHE_PREFIX = "power_curve:user_"


def _get_redis_client():
    """延迟导入 redis_conn—— 让纯单元测试不依赖 Redis 启动（task-0.8 单一连接源 / Q1 a 独立复制 / 与 service_social 一致）。"""
    from app.queue import redis_conn
    return redis_conn


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
                    COALESCE(SUM(COALESCE(moving_time, duration)), 0) AS duration
                FROM activities
                WHERE user_id = :user_id
                  AND status = 'completed'
                  AND duplicate_of IS NULL
                  AND activity_type = 'cycling'
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
                    COALESCE(SUM(COALESCE(moving_time, duration)), 0) AS duration
                FROM activities
                WHERE user_id = :user_id
                  AND status = 'completed'
                  AND duplicate_of IS NULL
                  AND activity_type = 'cycling'
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

    # 距离：米 → 公里，保留 2 位小数
    distance_km = round(distance_m / 1000.0, 2)

    # 获取用户的周目标（跨子文件 import service_auth.get_user_by_id / Q2 a）
    # 防御性处理：server_default 在 ORM 创建后 refresh 才生效，极端情况可能为 None
    user = get_user_by_id(db, user_id)
    weekly_goal = float(user.weekly_goal) if user.weekly_goal is not None else 200.0

    # 完成百分比：distance_km / weekly_goal * 100，向下取整
    goal_percent = int(distance_km / weekly_goal * 100) if weekly_goal > 0 else 0

    return {
        "period": period,
        "distance": distance_km,
        "rides": rides,
        # 爬升单位是米 / 浮点 SUM 后会出 73205.29999999999 这种尾巴 / round 后转 int 真整数
        # Tim 2026-05-11 拍 / schema 配套从 float → int 才能 JSON 真返 73205 不带 .0
        # 防回退：曾经因 schema float 漏改 / 还显示 .0 / 锁住未来 reviewer 不要回退
        "elevation_gain": int(round(elevation_gain)),
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
            Activity.duplicate_of.is_(None),  # Sprint 5 task-2 dedupe：power-curve 跳过 duplicate
            Activity.activity_type == "cycling",  # Sprint 7 Fix 7：防非骑行污染功率曲线
            Activity.started_at >= start,
            Activity.started_at < end,
        )
        .all()
    )

    # P0 hotfix（2026-05-09 / 修 N+1 + 大数据传输）：
    # 旧版：236 个 activity × 单独 SQL 查 trackpoints = N+1 = 24 秒（all_time）
    # 新版：1 次 IN 查询 + only 查 calculate_power_curve 用到的 3 字段（activity_id / seq / power）
    # - SQL 数量：237 → 2（拿 ids + 拿 trackpoints）
    # - 数据量：每行 200 字节(全字段)→ ~16 字节(3 字段)/ 减 92%
    # - 预期延迟：all_time 24s → 1-2s
    flat_act_ids = [aid for (aid,) in activity_ids]
    activities_trackpoints = []
    if flat_act_ids:
        from itertools import groupby
        # ORDER BY activity_id, seq —— 让 groupby 按 activity_id 分组 + 组内已 seq 升序
        all_tps = (
            db.query(Trackpoint.activity_id, Trackpoint.seq, Trackpoint.power)
            .filter(Trackpoint.activity_id.in_(flat_act_ids))
            .order_by(Trackpoint.activity_id, Trackpoint.seq)
            .all()
        )
        # SQLAlchemy Row 对象支持属性访问（.seq / .power）/ calculate_power_curve 不需改
        for _, group_iter in groupby(all_tps, key=lambda r: r.activity_id):
            activities_trackpoints.append(list(group_iter))

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


def get_cached_user_power_curve(
    user_id: int,
    period: str = "last_30_days",
) -> dict | None:
    """只读 request-safe 功率曲线缓存；miss 时不在 HTTP 详情链同步重算。"""
    from app.queue import request_redis_conn

    cache_key = f"{_POWER_CURVE_CACHE_PREFIX}{user_id}:period_{period}"
    cached = request_redis_conn.get(cache_key)
    if cached is None:
        return None
    parsed = _json.loads(cached.decode() if isinstance(cached, bytes) else cached)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("buckets"), dict):
        return None
    return parsed


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

    ⚠ 调用方：app/activity/worker.py:198 / 拆分时通过 service.py 转导出 0 改动
    """
    pattern = f"{_POWER_CURVE_CACHE_PREFIX}{user_id}:*"
    redis_client = _get_redis_client()
    for key in redis_client.scan_iter(match=pattern):
        redis_client.delete(key)
