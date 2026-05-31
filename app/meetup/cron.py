"""
约骑定时任务——后台夜班保安，把已经结束的 OPEN 约骑自动标成 COMPLETED。

操作注意事项：只碰 OPEN 且 estimated_end_time 已到的活动，DRAFT/CANCELLED 不能被顺手改掉。
输入/输出数据流：scheduler 定时调用本文件；本文件自建 DB 会话，写 meetups.status/completed_at，返回本轮改了几条。
"""

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.meetup.models import Meetup


logger = logging.getLogger(__name__)


def complete_due_meetups(db: Session) -> int:
    """把已过预计结束时间的 OPEN 约骑收尾，像活动结束后自动把牌子翻到"已完成"。"""
    now = datetime.now(timezone.utc)
    rows = (
        db.query(Meetup)
        .filter(Meetup.status == "OPEN", Meetup.estimated_end_time <= now)
        .all()
    )
    for meetup in rows:
        meetup.status = "COMPLETED"
        meetup.completed_at = now
    db.commit()
    return len(rows)


def run_meetup_complete_tick() -> int:
    """给 scheduler 调的外壳：自己借数据库钥匙，用完一定归还。"""
    db = SessionLocal()
    try:
        changed = complete_due_meetups(db)
        if changed:
            logger.info("meetup complete tick changed=%s", changed)
        return changed
    finally:
        db.close()
