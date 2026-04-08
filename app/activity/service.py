"""
骑行活动模块的业务逻辑层——真正干活的地方。

和 User 模块的 service.py 一样的角色：
router 是前台接待员（接请求、回结果），service 是后台办事员（处理业务、操作数据库）。

注意事项：
- 所有数据库操作在这里完成，router 层不直接操作数据库
- 文件存储通过 StorageBackend 抽象层操作，不直接碰文件系统
- 队列操作通过 rq 完成，不直接碰 Redis
"""

from redis import Redis
from rq import Queue
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


def upload_gpx(db: Session, user_id: int, filename: str, file_bytes: bytes) -> Activity:
    """
    处理 GPX 文件上传的完整流程。

    步骤：
    1. 存储文件 → 拿到 file_url
    2. 创建 Activity 记录（status=pending）
    3. 把解析任务扔进队列

    返回新建的 Activity 对象（前端用 activity_id 查进度）。
    """
    # 第一步：存储文件
    try:
        file_url = _storage.upload(file_bytes, filename)
    except Exception:
        raise RuntimeError("文件上传失败")

    # 第二步：创建数据库记录
    activity = Activity(
        user_id=user_id,
        file_url=file_url,
        status="pending",  # 显式赋值，不依赖 server_default（SQLite 测试兼容）
    )
    db.add(activity)
    db.commit()
    db.refresh(activity)

    # 第三步：入队列，让 Worker 异步解析
    _queue.enqueue(parse_activity, activity.id)

    return activity
