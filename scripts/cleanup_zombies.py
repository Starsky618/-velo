"""
僵尸活动回收脚本——"快递站仓库巡检员"。

由 cron 每 5 分钟调用一次，负责三件事：
1. processing 僵尸：Worker 崩溃后卡在 processing 超过 10 分钟 → 标记 failed
2. pending 僵尸：Redis 宕机导致入队失败，卡在 pending 超过 30 分钟 → 重新入队
3. 孤儿文件：磁盘上有文件但数据库无对应记录（超过 1 小时）→ 删除

为什么不在 API 或 Worker 里做？
- API 依赖用户请求触发，没人访问就没扫描
- Worker 全挂时最需要扫描，但它自己也挂了
- 独立 cron 脚本不受其他服务影响，跑完就退出，不常驻内存
"""

import logging
import os
import sys
import time
from pathlib import Path

from redis import Redis
from rq import Queue
from sqlalchemy import text

# 项目根目录加入 Python 路径，让 import app.xxx 生效
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings
from app.database import SessionLocal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [cleanup] %(message)s",
)
logger = logging.getLogger(__name__)

# 超时阈值
PROCESSING_TIMEOUT_MINUTES = 10
PENDING_TIMEOUT_MINUTES = 30
ORPHAN_FILE_AGE_HOURS = 1


def cleanup_processing_zombies(db) -> int:
    """
    processing 超过 10 分钟的活动 → 标记 failed。
    Worker 崩溃、被 OOM Killer 杀死、服务器重启等场景会产生这类僵尸。
    返回清理数量。
    """
    result = db.execute(
        text(
            "UPDATE activities "
            "SET status = 'failed', "
            "    error_message = '解析超时（系统自动回收）', "
            "    updated_at = now() "
            "WHERE status = 'processing' "
            "  AND updated_at < now() - make_interval(mins => :minutes)"
        ),
        {"minutes": PROCESSING_TIMEOUT_MINUTES},
    )
    count = result.rowcount
    if count > 0:
        db.commit()
        logger.info(f"清理 {count} 个 processing 僵尸")
    return count


def rescue_pending_zombies(db) -> int:
    """
    pending 超过 30 分钟的活动 → 尝试重新入队。
    Redis 宕机导致 enqueue 失败时会产生这类僵尸。
    给系统第二次机会，而不是甩锅给用户。
    Redis 不可用时静默跳过，下次再试。
    返回成功重新入队数量。
    """
    rows = db.execute(
        text(
            "SELECT id FROM activities "
            "WHERE status = 'pending' "
            "  AND created_at < now() - make_interval(mins => :minutes)"
        ),
        {"minutes": PENDING_TIMEOUT_MINUTES},
    ).fetchall()

    if not rows:
        return 0

    # 尝试连接 Redis 并重新入队
    try:
        redis_conn = Redis.from_url(settings.REDIS_URL)
        queue = Queue("velo", connection=redis_conn)
    except Exception as e:
        logger.warning(f"Redis 连接失败，跳过 pending 僵尸回收: {e}")
        return 0

    from app.activity.worker import parse_activity

    rescued = 0
    for row in rows:
        activity_id = row[0]
        try:
            queue.enqueue(parse_activity, activity_id, job_timeout=120)
            rescued += 1
            logger.info(f"重新入队 activity_id={activity_id}")
        except Exception as e:
            logger.warning(f"入队失败 activity_id={activity_id}: {e}")

    return rescued


def cleanup_orphan_files(db) -> int:
    """
    扫描上传目录，清理超过 1 小时且数据库无对应记录的孤儿文件。
    1 小时阈值防止误删正在上传中的文件（正常上传几秒内完成）。
    返回清理数量。
    """
    upload_dir = Path(settings.UPLOAD_DIR)
    if not upload_dir.exists():
        return 0

    cutoff = time.time() - ORPHAN_FILE_AGE_HOURS * 3600
    cleaned = 0

    for filepath in upload_dir.iterdir():
        if not filepath.is_file():
            continue
        # 文件修改时间早于 1 小时前才处理
        if filepath.stat().st_mtime > cutoff:
            continue

        # 检查数据库中是否有引用此文件的 Activity
        # file_url 存的是相对路径，需要匹配
        filename = filepath.name
        exists = db.execute(
            text("SELECT 1 FROM activities WHERE file_url LIKE :pattern LIMIT 1"),
            {"pattern": f"%{filename}"},
        ).fetchone()

        if exists is None:
            filepath.unlink()
            cleaned += 1
            logger.info(f"删除孤儿文件: {filename}")

    return cleaned


def main():
    """脚本入口：依次执行三项清理，任一失败不影响其他。"""
    db = SessionLocal()
    try:
        cleanup_processing_zombies(db)
        rescue_pending_zombies(db)
        cleanup_orphan_files(db)
    except Exception as e:
        logger.error(f"清理脚本异常: {e}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    main()
