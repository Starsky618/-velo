"""
骑行活动模块的业务逻辑层——真正干活的地方。

和 User 模块的 service.py 一样的角色：
router 是前台接待员（接请求、回结果），service 是后台办事员（处理业务、操作数据库）。

注意事项：
- 所有数据库操作在这里完成，router 层不直接操作数据库
- 文件存储通过 StorageBackend 抽象层操作，不直接碰文件系统
- 队列操作通过 rq 完成，不直接碰 Redis
"""

import hashlib
import logging
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.activity import power_curve, timeseries
from app.activity.models import Activity, Trackpoint
from app.activity.power_curve import DurationOutOfRange  # noqa: F401 — router 通过 service.DurationOutOfRange 引用
from app.activity.worker import parse_activity
from app.config import settings
from app.queue import redis_conn as _redis_conn, default_queue as _queue
from app.storage.local import LocalStorage

# 存储后端实例（当前用本地存储，将来切云存储只改这一行）
_storage = LocalStorage()
_logger = logging.getLogger(__name__)

# v5 task-0.8：_redis_conn / _queue 沿用旧别名，避免本文件 caller 大改
# Redis 连接和 Queue 实例从 app.queue 单一源拿（禁止本地 Redis.from_url）

# 文件大小上限：50MB
_MAX_FILE_SIZE = 50 * 1024 * 1024

# 轨迹点数量上限：50000 个点 ≈ 14 小时连续记录（1 秒/点）
# 超大轨迹解析时内存峰值可达 400MB+，4G 服务器上会触发 OOM
_MAX_TRACKPOINTS = 50_000

# Worker 解析超时阈值：10 分钟（600 秒）
# 超过这个时间还在 processing，说明 Worker 卡死了，标记为 failed
_PROCESSING_TIMEOUT = 10 * 60


# 支持的文件类型
_ALLOWED_EXTENSIONS = {".gpx", ".fit"}


def _can_view_activity(activity: Activity, viewer_user_id: int | None) -> bool:
    """
    判断一条骑行对当前查看者是否可见。

    可以把它想成宿舍门禁：
    - 房主本人永远能进
    - 老房间没有装门禁卡，沿用旧规则，默认开放
    - 装了门禁卡后，只有 public 才让其他人进
    """
    if viewer_user_id == activity.user_id:
        return True
    if activity.privacy is None:
        return True
    return activity.privacy.visibility == "public"


def _apply_activity_privacy_mask(activity: Activity, viewer_user_id: int | None) -> None:
    """
    task-4.6：他人看 owner 隐藏的功率/心率字段时，把字段挖空成 None。

    前端 wxml 用 `wx:if="{{activity.avg_power}}"` 判断显示——字段为 None 时整个功率卡片
    会自动消失（跟没装功率计的骑行一模一样的 UX / 跟踏频字段处理同 pattern）。

    本人查看自己的活动时不挖空（始终完整）。privacy=None（老 activity 无配置）也不挖。

    必须在 db.expunge 之后调用：expunge 后 session 不再追踪此对象，
    改属性不会被意外 flush 进 DB。expunge 之前修改 = 污染原始数据。
    """
    if viewer_user_id == activity.user_id:
        return
    privacy = activity.privacy
    if privacy is None:
        return

    if privacy.hide_power:
        activity.avg_power = None
        activity.max_power = None
        activity.normalized_power = None
        # splits 是 JSONB list of dicts / 每条含 avg_power → 挖空 each
        if activity.splits:
            for split in activity.splits:
                if isinstance(split, dict):
                    split.pop("avg_power", None)
        # task-4.6 Codex 异源审 C1：power_zones 必须挖！
        # 注释曾说"不含直接功率值"是错的——实证 power_zones.py:43-104 返
        # [{zone, name, min_w, max_w, seconds, percent}]，min_w/max_w 直接暴露功率
        # 区间（Zone 5 min_w=280 → 别人直接知道 FTP ≈ 280W），违反"跟没装功率计一样"目标。
        activity.power_zones = None
        # task-3 (sprint9)：power_per_kg / IF / TSS / snapshot_ftp 同样泄露功率信息 → 一并挖空
        # power_per_kg = avg_power / weight 反推 avg_power / IF + TSS 反推 NP / snapshot_ftp 暴露 FTP
        if hasattr(activity, "power_per_kg"):
            activity.power_per_kg = None
        activity.intensity_factor = None
        activity.tss = None
        activity.snapshot_ftp = None
        # task-3 sprint9 Codex 异源审 Important（2026-05-20 抓的）：calories 同样反推
        # GPX 路径 stats_calculator.py:226：calories = avg_power × duration × 0.0009
        # → 反推 avg_power = calories / (duration × 0.0009)
        # Strava 路径 calories 也基于功率算法（has_sensors 守卫已守）/ 同样反推风险
        activity.calories = None

    if privacy.hide_heartrate:
        activity.avg_hr = None
        activity.max_hr = None
        if activity.splits:
            for split in activity.splits:
                if isinstance(split, dict):
                    split.pop("avg_hr", None)

    # task-4.6 Codex 异源审 I1：他人查看时不返 privacy 元数据
    # 否则 hide_power=true 被对方看见 → 暴露"主动隐藏"信号（跟"没功率计"伪装目标矛盾）
    # owner 看自己时上面已 return / 这里只对他人生效
    activity.privacy = None


def validate_ride_file(filename: str, file_bytes: bytes) -> None:
    """
    校验上传的骑行文件是否合法（支持 .gpx 和 .fit）。

    四道关卡，任一不通过就抛 ValueError：
    1. 文件名必须以 .gpx 或 .fit 结尾
    2. 文件大小不能超过 50MB
    3. 文件内容格式检查（GPX 查 XML 头，FIT 查二进制魔术字节）
    4. GPX 额外做轨迹点预检（FIT 是二进制，无法字节扫描计数）

    好比快递收件窗口的验收流程：
    先看包裹标签对不对 → 再称重量超没超 → 最后打开看里面是不是该有的东西。
    """
    # 关卡 1：后缀检查
    ext = _get_file_extension(filename)
    if ext not in _ALLOWED_EXTENSIONS:
        raise ValueError("只接受 .gpx 或 .fit 文件")

    # 关卡 2：大小检查
    if len(file_bytes) > _MAX_FILE_SIZE:
        raise ValueError("文件大小不能超过50MB")

    # 关卡 3 + 4：按文件类型做内容检查
    if ext == ".gpx":
        _validate_gpx_content(file_bytes)
    elif ext == ".fit":
        _validate_fit_content(file_bytes)


def _validate_gpx_content(file_bytes: bytes) -> None:
    """GPX 文件内容校验：XML 头 + 轨迹点预检。"""
    # 内容检查（读前 256 字节，跳过 BOM）
    header = file_bytes[:256]
    if header.startswith(b"\xef\xbb\xbf"):
        header = header[3:]
    header_str = header.decode("utf-8", errors="ignore").strip().lower()

    if not (header_str.startswith("<?xml") or header_str.startswith("<gpx")):
        raise ValueError("文件内容不是有效的GPX格式")

    # 轨迹点数量预检（轻量字节扫描，不解析 XML）
    trkpt_count = file_bytes.count(b"<trkpt")
    if trkpt_count > _MAX_TRACKPOINTS:
        raise ValueError(
            f"轨迹点过多（{trkpt_count} 个，上限 {_MAX_TRACKPOINTS} 个，约 14 小时骑行）"
        )


def _validate_fit_content(file_bytes: bytes) -> None:
    """FIT 文件内容校验：检查文件头魔术字节。"""
    # FIT 文件头：第 8-11 字节应为 ".FIT" 签名（ASCII）
    # 最小 FIT 文件约 12 字节（头部），过短一定不是有效文件
    if len(file_bytes) < 12:
        raise ValueError("文件过小，不是有效的 FIT 文件")

    # FIT 文件头的第 8-11 字节固定为 ".FIT"
    # 有些文件头是 12 字节，有些是 14 字节，但签名位置固定在 8-11
    header_size = file_bytes[0]
    if header_size < 12:
        raise ValueError("FIT 文件头长度异常")

    signature = file_bytes[8:12]
    if signature != b".FIT":
        raise ValueError("文件内容不是有效的 FIT 格式")


def _get_file_extension(filename: str) -> str:
    """提取文件扩展名（小写）。"""
    if not filename:
        return ""
    dot_idx = filename.rfind(".")
    if dot_idx < 0:
        return ""
    return filename[dot_idx:].lower()


def upload_ride(db: Session, user_id: int, filename: str, file_bytes: bytes) -> Activity:
    """
    处理骑行文件上传的完整流程（支持 .gpx 和 .fit）。

    步骤：
    1. 计算文件哈希 → 检查是否重复
    2. 存储文件 → 拿到 file_url
    3. 创建 Activity 记录（status=pending）
    4. 把解析任务扔进队列

    返回新建的 Activity 对象（前端用 activity_id 查进度）。
    如果是重复文件，直接返回已有记录，不重新创建。
    """
    # 第一步：计算文件 SHA-256 哈希（64 字符十六进制）
    # SHA-256 好比给文件做"指纹"——只要文件内容完全相同，指纹就一定相同。
    # 哪怕只改了一个字节，指纹就会完全不同，因此可以用来精准判断是否重复。
    file_hash = hashlib.sha256(file_bytes).hexdigest()

    # 第二步：检查是否已有同文件（同用户 + 同哈希 = 重复上传）
    # 同一用户传了同样的 GPX 文件 → 直接返回已有记录，不重新创建，也不报错
    existing = db.query(Activity).filter_by(
        user_id=user_id, file_hash=file_hash
    ).first()
    if existing:
        return existing  # 秒返已有记录，不报错、不创建新记录

    # 第三步：存储文件
    try:
        file_url = _storage.upload(file_bytes, filename)
    except Exception:
        raise RuntimeError("文件上传失败")

    # 第四步：创建数据库记录
    activity = Activity(
        user_id=user_id,
        file_url=file_url,
        file_hash=file_hash,
        status="pending",
    )
    db.add(activity)

    # 并发兜底：如果两个请求同时通过了应用层检查（都没查到已有记录），
    # 数据库的 UNIQUE(user_id, file_hash) 约束会让第二个 INSERT 抛异常。
    # 就像同时有两个人去领最后一张号码牌，第一个人拿到，第二个人就拿不到——
    # 数据库层面确保了只有一条记录能被真正写进去，保证数据一致性。
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # 捕获到唯一约束冲突，说明另一个并发请求已经抢先写入了，
        # 查出已有记录返回即可，不向上抛错（对用户来说这不是错误）
        existing = db.query(Activity).filter_by(
            user_id=user_id, file_hash=file_hash
        ).first()
        if existing:
            return existing
        raise  # 不是哈希冲突的 IntegrityError（如外键错误），重新抛出让上层处理

    db.refresh(activity)

    # 第五步：入队列，让 Worker 异步解析
    # job_timeout=120：Worker 最多允许跑 2 分钟，超时强制终止，防止 Worker 进程卡死
    _queue.enqueue(parse_activity, activity.id, job_timeout=120)

    return activity


# ========== 任务 3.7：活动查询 ==========

def get_activity_list(db: Session, user_id: int, page: int, page_size: int) -> tuple[list[Activity], int]:
    """
    获取当前用户的活动列表（分页，按创建时间倒序）。

    返回 (活动列表, 总条数)。
    距离单位转换（米→公里）在这里做，router 层拿到的就是最终数据。
    """
    # Sprint 5 task-2 dedupe：列表查询过滤掉已标 duplicate 的（个人页只显示主活动 / 详情查询不过滤）
    # Sprint 7 Fix 5：列表 endpoint 加双重防御过滤——
    # 即使 webhook / scheduler 路径漏过滤让非骑行 / 半成品活动进 DB，
    # 列表层拦住不显示给用户。activity_type='cycling' + status='completed' 联合过滤：
    # 历史脏数据（5-14 Morning Run 等）也被这里挡住，等脏数据清理 SQL 收尾。
    # count 时序：必须在过滤后 count（集成审 Important-5），不然分页页码不准
    # （比如总 100 条但 cycling completed 只 80 条，前端按 100 算页数会出空页）。
    query = (
        db.query(Activity)
        .filter_by(user_id=user_id)
        .filter(Activity.duplicate_of.is_(None))
        .filter(Activity.activity_type == "cycling")
        .filter(Activity.status == "completed")
    )
    total = query.count()

    items = (
        query
        # 按真实骑行时间倒序（不是 created_at = 导入到 DB 时间）。
        # Tim 2026-05-06 真用回归发现：v4 时拉的 30 条 created_at 集中在 v4 测试日 / A1 后新拉
        # 11 条 created_at 集中在 2026-05-05 / 但骑行时间是 2025-10 ~ 2026-05 混合的，
        # 按 created_at 排会让所有 v4 老导入沉到底，违反"最近骑行"用户预期。
        # nullslast() 兜底：极少数 strava 活动 started_at NULL 时降级到 created_at 排序。
        .order_by(Activity.started_at.desc().nullslast(), Activity.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    # 距离：米 → 公里，保留 2 位小数
    # 先用 expunge 让对象脱离 Session，再改属性，
    # 避免修改后的公里值被意外 commit 回数据库覆盖原始米值
    # task-4.6：spec 要求 list 也按隐私挖空（防御 / owner 看自己永远完整）
    for item in items:
        _ = item.privacy  # force load 防 expunge 后 mask 函数访问 .privacy 炸 DetachedInstanceError
        db.expunge(item)
        if item.distance is not None:
            item.distance = round(item.distance / 1000.0, 2)
        # 当前路由只返当前用户自己的活动（user_id 既是 owner 又是 viewer）→ mask 内部直接 return
        # 留这一行是 spec 要求的防御编码：未来若开放 explore 看他人活动列表也不会漏挖
        _apply_activity_privacy_mask(item, user_id)

    return items, total


def get_activity_detail(db: Session, activity_id: int, user_id: int) -> Activity:
    """
    获取单个活动的完整详情。
    只允许查看自己的活动，否则抛异常。
    """
    activity = db.query(Activity).filter_by(id=activity_id).first()
    if activity is None:
        raise ValueError("活动不存在")
    if not _can_view_activity(activity, user_id):
        raise ValueError("活动不存在")

    # task-4.6：强制 load privacy relationship（_ = activity.privacy 触发 lazy load）
    # 否则 expunge 后 Pydantic 序列化时访问 .privacy 会 DetachedInstanceError
    _ = activity.privacy

    # task-3 (sprint9): 算 W/kg 给详情页 / 后端算 / 前端不算
    # Activity 模型没有 user relationship，必须单独 query User 拿 weight 字段。
    # 守卫四件套：avg_power 非 None / owner 用户存在 / user.weight 非 None / weight > 0
    # 任一不满足 → power_per_kg = None / 前端 wx:if 让整块消失（不显示"-"占位）
    from app.user.models import User
    owner = db.query(User).filter_by(id=activity.user_id).first()
    if (
        activity.avg_power is not None
        and owner is not None
        and owner.weight is not None
        and owner.weight > 0
    ):
        # Pydantic from_attributes 模式下 / 在 ORM 实例加临时属性也能被 schema 读
        # 保 2 位小数 / 例 3.5 W/kg
        activity.power_per_kg = round(activity.avg_power / owner.weight, 2)
    else:
        activity.power_per_kg = None

    # 脱离 Session 后再做单位转换，防止公里值被意外写回数据库
    db.expunge(activity)
    if activity.distance is not None:
        activity.distance = round(activity.distance / 1000.0, 2)

    # task-4.6：他人查看时按 hide_power / hide_heartrate 挖空功率/心率字段
    _apply_activity_privacy_mask(activity, user_id)

    return activity


def update_activity(db: Session, activity_id: int, user_id: int, title: str) -> Activity:
    """
    编辑活动信息（目前只支持改标题）。
    只允许编辑自己的活动。
    """
    activity = db.query(Activity).filter_by(id=activity_id).first()
    if activity is None:
        raise ValueError("活动不存在")
    if activity.user_id != user_id:
        raise PermissionError("无权编辑此活动")

    activity.title = title
    db.commit()
    db.refresh(activity)

    # 脱离 Session 后再做单位转换
    db.expunge(activity)
    if activity.distance is not None:
        activity.distance = round(activity.distance / 1000.0, 2)

    return activity


def update_activity_privacy(
    db: Session,
    activity_id: int,
    user_id: int,
    visibility: str | None = None,
    hide_power: bool | None = None,
    hide_heartrate: bool | None = None,
) -> "ActivityPrivacy":
    """
    更新一条骑行的隐私设置（task-4.6）——3 个字段可选改，None 表示不改。

    仅 owner 可改自己的活动隐私（违规 → PermissionError → 403）。
    upsert 模式：若已有 privacy 行就 update，没有就 insert。
    """
    from app.activity.models import ActivityPrivacy

    activity = db.query(Activity).filter_by(id=activity_id).first()
    if activity is None:
        raise ValueError("活动不存在")
    if activity.user_id != user_id:
        raise PermissionError("无权修改此活动")

    privacy = activity.privacy
    if privacy is None:
        # 第一次设隐私 → 创建新行（其余字段走 model 默认值 public/false/false）
        privacy = ActivityPrivacy(activity_id=activity_id)
        db.add(privacy)
        activity.privacy = privacy  # 让 relationship 立刻可见 / 测试方便

    if visibility is not None:
        privacy.visibility = visibility
    if hide_power is not None:
        privacy.hide_power = hide_power
    if hide_heartrate is not None:
        privacy.hide_heartrate = hide_heartrate

    db.commit()
    db.refresh(privacy)
    if visibility is not None:
        # 可见性变化后推进热图 generation，避免他人继续拿到旧的私密轨迹瓦片。
        # Redis 故障不能反向让隐私设置保存失败；旧 PNG 仍会在 1h TTL 后自然过期。
        try:
            from app.user.service_social import invalidate_heatmap_cache
            invalidate_heatmap_cache(user_id)
        except Exception:
            # 公开瓦片还绑定数据库隐私指纹，因此不会 fail-open；保留日志供 Redis 修复。
            _logger.exception("failed to invalidate heatmap after privacy update", extra={"user_id": user_id})
    return privacy


def delete_activity(db: Session, activity_id: int, user_id: int) -> None:
    """
    删除活动：级联删除 trackpoints + 删除存储的 GPX 文件。
    只允许删除自己的活动。
    """
    activity = db.query(Activity).filter_by(id=activity_id).first()
    if activity is None:
        raise ValueError("活动不存在")
    if activity.user_id != user_id:
        raise PermissionError("无权删除此活动")

    # segment_efforts 的 activity_id 外键已设置 ON DELETE CASCADE（见 segment/models.py），
    # 删除活动时数据库会自动级联删除关联的赛段成绩记录，无需手动处理

    # 删除存储的 GPX 文件（忽略删除失败，文件可能已被清理）
    try:
        _storage.delete(activity.file_url)
    except Exception:
        pass

    # 删除数据库记录（trackpoints 通过外键 ON DELETE CASCADE 自动级联删除）
    db.delete(activity)
    db.commit()

    # 删除成功后立即清热图；失败只影响最多 1h 的展示缓存，不能反向让删除 API 失败。
    try:
        from app.user.service_social import invalidate_heatmap_cache
        invalidate_heatmap_cache(user_id)
    except Exception:
        pass


def get_activity_status(db: Session, activity_id: int, user_id: int) -> Activity:
    """
    获取活动的解析状态（供前端轮询）。
    只允许查看自己的活动。

    超时保护（方案 A）：
    如果活动卡在 processing 超过 10 分钟，自动标记为 failed。
    这是轻量级方案——只在用户轮询时触发判断，不需要额外的定时任务。
    未来流量大了可以叠加定时扫描方案，两者不冲突。
    """
    activity = db.query(Activity).filter_by(id=activity_id).first()
    if activity is None:
        raise ValueError("活动不存在")
    if not _can_view_activity(activity, user_id):
        raise ValueError("活动不存在")

    # 超时保护：processing 超过 10 分钟视为失败
    # updated_at 在 Worker 开始解析时会被更新为 processing 的时间戳，
    # 如果距今超过 10 分钟还没完成，说明 Worker 卡死或崩溃了
    # task-0.1 双审 Critical 1 修复：activities.updated_at 已迁 tz-aware，
    # 删 .replace(tzinfo=None)，否则 naive - aware = TypeError processing 详情页全 500
    if activity.status == "processing" and activity.updated_at:
        now_utc = datetime.now(timezone.utc)
        elapsed = now_utc - activity.updated_at
        if elapsed.total_seconds() > _PROCESSING_TIMEOUT:
            activity.status = "failed"
            activity.error_message = "解析超时，请重新上传"
            db.commit()

    return activity


def _activity_power_is_hidden(activity: Activity, viewer_user_id: int | None) -> bool:
    """
    判断当前查看者是否应该看不到功率。

    本人永远能看自己的原始功率；别人看公开活动时，如果 owner 打开 hide_power，
    曲线也必须像“没装功率计”一样消失，不能通过曲线反推出真实功率。

    这是 timeseries 和功率曲线两条路径共用的单一隐私真相源。
    """
    return (
        viewer_user_id != activity.user_id
        and activity.privacy is not None
        and activity.privacy.hide_power
    )


def get_activity_timeseries(
    db: Session, activity_id: int, user_id: int, max_points: int = 1200
) -> dict:
    """
    获取骑行的时序数据——从原始轨迹点中按距离采样，返回前端可直接画图的数组。

    类比：原始 trackpoints 好比一段 4K 视频（每帧都有），
    而前端图表是一条可以用手滑的时间尺。
    这个函数不是简单按点数抽帧，而是按骑行距离插“小旗”：
    短骑小旗更密，长骑小旗更疏，让用户滑动时读到接近瞬时的值。

    内存预估：50000 行 x 7 列 ≈ 15MB，cum_distances ≈ 0.4MB，
    输出列表 ≈ 2.4MB。峰值 ~18MB，受 _MAX_TRACKPOINTS 上限保护。
    """
    # ── 权限检查 ──
    activity = db.query(Activity).filter_by(id=activity_id).first()
    if activity is None:
        raise ValueError("活动不存在")
    if not _can_view_activity(activity, user_id):
        raise ValueError("活动不存在")
    if activity.status != "completed":
        raise ValueError("活动尚未解析完成")

    # ── 查询轨迹点（只取需要的列，不加载 geom 大字段，节省内存） ──
    rows = (
        db.query(
            Trackpoint.seq,
            Trackpoint.latitude,
            Trackpoint.longitude,
            Trackpoint.elevation,
            Trackpoint.timestamp,
            Trackpoint.heart_rate,
            Trackpoint.power,
            Trackpoint.cadence,
            Trackpoint.speed,
            Trackpoint.distance,
        )
        .filter(Trackpoint.activity_id == activity_id)
        .order_by(Trackpoint.seq)
        .all()
    )

    total = len(rows)
    if total < 2:
        raise ValueError("轨迹点不足，无法生成时序数据")

    # 三步流水线：算距离 → 按距离采样 → 构建数组
    cum_dist = timeseries._distance_values(rows)
    total_distance_m = cum_dist[-1] if cum_dist and cum_dist[-1] > 0 else float(activity.distance or 0)
    sample_step_m = timeseries._target_sample_step_m(total_distance_m)
    indices = timeseries._sample_indices_by_distance(cum_dist, sample_step_m, max_points)
    data = timeseries._build_timeseries_arrays(rows, indices, cum_dist, sample_step_m)

    # task-4.6：他人查看时按 hide_power / hide_heartrate 把对应时序数组挖空成 None
    # 前端 detail.js 检测 powers=null → hasPowerChart=false → 功率曲线卡片整块消失
    # hide_power 的判定走 _activity_power_is_hidden 单一真相源，避免 timeseries 和功率曲线两份实现漂移
    if _activity_power_is_hidden(activity, user_id):
        data["powers"] = None
    if (
        user_id != activity.user_id
        and activity.privacy is not None
        and activity.privacy.hide_heartrate
    ):
        data["heart_rates"] = None

    return data


def _load_activity_for_power_curve(db: Session, activity_id: int, user_id: int) -> Activity:
    """功率曲线和 timeseries 共用的活动门禁：存在、可见、已完成。"""
    activity = db.query(Activity).filter_by(id=activity_id).first()
    if activity is None:
        raise ValueError("活动不存在")
    if not _can_view_activity(activity, user_id):
        raise ValueError("活动不存在")
    if activity.status != "completed":
        raise ValueError("活动尚未解析完成")
    return activity


def _query_power_curve_rows(db: Session, activity_id: int):
    """
    只取功率曲线需要的轻量列。

    distance 暂不参与计算，但保留在查询里：后续如果要在气泡里提示“这段发生在第几公里”，
    不需要再改查询边界。
    """
    return (
        db.query(
            Trackpoint.seq,
            Trackpoint.timestamp,
            Trackpoint.power,
            Trackpoint.distance,
        )
        .filter(Trackpoint.activity_id == activity_id)
        .order_by(Trackpoint.seq)
        .all()
    )


def _empty_effort_response(duration_sec: int) -> dict:
    """精确 effort 接口的统一空态——隐私挡板和无功率两条路径共用。"""
    return {
        "has_power": False,
        "duration_sec": duration_sec,
        "best_power_w": None,
        "start_sec": None,
        "end_sec": None,
    }


def get_activity_power_curve(
    db: Session, activity_id: int, user_id: int, max_points: int = 1000
) -> dict:
    """
    获取单次骑行的功率-持续时间曲线。

    这是详情页里的“体能指纹”：横轴是持续多久，纵轴是这条骑行里该时长的最佳平均功率。
    """
    activity = _load_activity_for_power_curve(db, activity_id, user_id)
    rows = _query_power_curve_rows(db, activity_id)
    max_duration_sec = power_curve._activity_elapsed_seconds(rows)

    if _activity_power_is_hidden(activity, user_id):
        return power_curve._empty_activity_power_curve(max_duration_sec)

    power_by_second, has_power = power_curve._power_seconds_from_rows(rows, max_duration_sec)
    if not has_power or not power_by_second:
        return power_curve._empty_activity_power_curve(max_duration_sec)

    return power_curve._build_power_curve_result(power_by_second, max_points)


def get_activity_power_curve_effort(
    db: Session, activity_id: int, user_id: int, duration_sec: int
) -> dict:
    """
    精确查询某个持续时长下的最佳平均功率。

    前端拖动时可以先看抽样曲线；手指停住后调这个接口，让气泡读数精确到分秒。
    """
    activity = _load_activity_for_power_curve(db, activity_id, user_id)
    rows = _query_power_curve_rows(db, activity_id)
    max_duration_sec = power_curve._activity_elapsed_seconds(rows)

    # duration 范围校验前置到 early return 之前，避免 hide_power / no-power 两条空响应路径
    # 把"duration 超出活动长度"伪装成 200 空响应，而正常路径却 raise 400——行为不一致就成 bug。
    # 空活动（max_duration_sec=0）跳过 > 检查，让下面的 no-power early return 走 200 空响应；
    # 但 < 1 是参数本身非法（router Query(ge=1) 已挡，service 层守住对称性）。
    if duration_sec < 1:
        raise DurationOutOfRange("持续时间必须大于 0 秒")
    if max_duration_sec > 0 and duration_sec > max_duration_sec:
        raise DurationOutOfRange("持续时间超出活动长度")

    if _activity_power_is_hidden(activity, user_id):
        return _empty_effort_response(duration_sec)

    power_by_second, has_power = power_curve._power_seconds_from_rows(rows, max_duration_sec)
    if not has_power or not power_by_second:
        return _empty_effort_response(duration_sec)

    return power_curve._best_power_effort_from_prefix(
        power_curve._prefix_power(power_by_second), duration_sec
    )
