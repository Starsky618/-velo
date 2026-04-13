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
from datetime import datetime, timezone

from redis import Redis
from rq import Queue
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.activity.models import Activity
from app.activity.worker import parse_activity
from app.config import settings
from app.storage.local import LocalStorage

# 存储后端实例（当前用本地存储，将来切云存储只改这一行）
_storage = LocalStorage()

# Redis 队列连接（与 worker.py 共用同一个队列名 "ridemap"）
_redis_conn = Redis.from_url(settings.REDIS_URL)
_queue = Queue("ridemap", connection=_redis_conn)

# 文件大小上限：50MB
_MAX_FILE_SIZE = 50 * 1024 * 1024

# 轨迹点数量上限：50000 个点 ≈ 14 小时连续记录（1 秒/点）
# 超大轨迹解析时内存峰值可达 400MB+，4G 服务器上会触发 OOM
_MAX_TRACKPOINTS = 50_000

# Worker 解析超时阈值：10 分钟（600 秒）
# 超过这个时间还在 processing，说明 Worker 卡死了，标记为 failed
_PROCESSING_TIMEOUT = 10 * 60


def validate_gpx_file(filename: str, file_bytes: bytes) -> None:
    """
    校验上传的文件是否是合法的 GPX。

    三道关卡，任一不通过就抛 ValueError：
    1. 文件名必须以 .gpx 结尾
    2. 文件大小不能超过 50MB
    3. 文件内容必须以 XML 或 GPX 标签开头

    好比快递收件窗口的验收流程：
    先看包裹标签对不对 → 再称重量超没超 → 最后打开看里面是不是该有的东西。
    """
    # 关卡 1：后缀检查
    if not filename.lower().endswith(".gpx"):
        raise ValueError("只接受.gpx文件")

    # 关卡 2：大小检查
    if len(file_bytes) > _MAX_FILE_SIZE:
        raise ValueError("文件大小不能超过50MB")

    # 关卡 3：内容检查（读前 256 字节，跳过 BOM）
    header = file_bytes[:256]
    if header.startswith(b"\xef\xbb\xbf"):
        header = header[3:]
    header_str = header.decode("utf-8", errors="ignore").strip().lower()

    if not (header_str.startswith("<?xml") or header_str.startswith("<gpx")):
        raise ValueError("文件内容不是有效的GPX格式")

    # 关卡 4：轨迹点数量预检（轻量字节扫描，不解析 XML）
    # GPX 中每个轨迹点以 <trkpt 标签开头，数标签数 ≈ 数轨迹点数
    # 纯字节扫描 50MB 耗时毫秒级，不建 DOM 树，不吃额外内存
    trkpt_count = file_bytes.count(b"<trkpt")
    if trkpt_count > _MAX_TRACKPOINTS:
        raise ValueError(
            f"轨迹点过多（{trkpt_count} 个，上限 {_MAX_TRACKPOINTS} 个，约 14 小时骑行）"
        )


def upload_gpx(db: Session, user_id: int, filename: str, file_bytes: bytes) -> Activity:
    """
    处理 GPX 文件上传的完整流程。

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
    query = db.query(Activity).filter_by(user_id=user_id)
    total = query.count()

    items = (
        query
        .order_by(Activity.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    # 距离：米 → 公里，保留 1 位小数
    # 先用 expunge 让对象脱离 Session，再改属性，
    # 避免修改后的公里值被意外 commit 回数据库覆盖原始米值
    for item in items:
        db.expunge(item)
        if item.distance is not None:
            item.distance = round(item.distance / 1000.0, 1)

    return items, total


def get_activity_detail(db: Session, activity_id: int, user_id: int) -> Activity:
    """
    获取单个活动的完整详情。
    只允许查看自己的活动，否则抛异常。
    """
    activity = db.query(Activity).filter_by(id=activity_id).first()
    if activity is None:
        raise ValueError("活动不存在")
    if activity.user_id != user_id:
        raise PermissionError("无权查看此活动")

    # 脱离 Session 后再做单位转换，防止公里值被意外写回数据库
    db.expunge(activity)
    if activity.distance is not None:
        activity.distance = round(activity.distance / 1000.0, 1)

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
        activity.distance = round(activity.distance / 1000.0, 1)

    return activity


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
    if activity.user_id != user_id:
        raise PermissionError("无权查看此活动")

    # 超时保护：processing 超过 10 分钟视为失败
    # updated_at 在 Worker 开始解析时会被更新为 processing 的时间戳，
    # 如果距今超过 10 分钟还没完成，说明 Worker 卡死或崩溃了
    # 用 datetime.now(timezone.utc) 替代已弃用的 datetime.utcnow()（Python 3.12+）
    if activity.status == "processing" and activity.updated_at:
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        elapsed = now_utc - activity.updated_at
        if elapsed.total_seconds() > _PROCESSING_TIMEOUT:
            activity.status = "failed"
            activity.error_message = "解析超时，请重新上传"
            db.commit()

    return activity
