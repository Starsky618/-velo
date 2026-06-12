"""
约骑定时任务——后台夜班保安，负责"收尾"和"收卷"两件事。

操作注意事项：收尾只碰 OPEN 且 estimated_end_time 已到的活动；收卷只扫 OPEN/COMPLETED 约骑，
DRAFT/CANCELLED 不能被顺手改掉或挂活动。
输入/输出数据流：scheduler 定时调用本文件；本文件自建 DB 会话，写 meetups.status/completed_at
或 meetup_activities 关联行，返回本轮改了几条。
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.activity.models import Activity
from app.database import SessionLocal
from app.meetup.models import Meetup, MeetupActivity, MeetupParticipant


logger = logging.getLogger(__name__)

# 补传截止：约骑出发时刻起 7 天。
# 可以把它想成"交卷箱开放 7 天"：骑完第 3 天才上传也能被收卷，
# 但太久以前的约骑不再反复扫描，避免后台一直翻旧账。
ATTACH_WINDOW_DAYS = 7

# 晚动身宽限：出发后多少小时内开始骑都算本场（D2 修订 / 2026-06-13 Tim 拍）。
# 旧规则"同北京日历日"会让 23:30 出发的夜骑、骑友 00:05 才动身时格子永远灰；
# 改成锚定"骑行开始时间离约骑出发多近"后，跨午夜不掉格，
# 而第二天早上的无关骑行（同日规则反而会误挂的）也被天然挡住。
ATTACH_LATE_START_HOURS = 6


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


def attach_meetup_activities(db: Session) -> int:
    """把约骑当天骑完的活动自动挂到约骑上——战报格子的"点灯人"。

    设计思路：
    - 方向：由 meetup 侧定时扫描 activity，activity 上传链路不用反过来认识 meetup。
    - 窗口（D2 修订 2026-06-13）：骑行开始时间 ∈ [出发前 30 分钟, 出发后 6 小时]。
      锚的是"动身时间离约骑出发多近"，所以跨午夜夜骑不掉格、骑多久都不掉窗。
    - 一人一格：每人每场只挂最早一条候选骑行，数据库 UNIQUE 再兜最后一道门。
    - 截止：出发后 7 天内还会补扫，照顾晚上传文件的人。
    """
    now = datetime.now(timezone.utc)
    attached = 0
    meetups = (
        db.query(Meetup)
        .filter(
            Meetup.status.in_(["OPEN", "COMPLETED"]),
            Meetup.start_time >= now - timedelta(days=ATTACH_WINDOW_DAYS),
        )
        .all()
    )
    for meetup in meetups:
        participants = db.query(MeetupParticipant).filter_by(meetup_id=meetup.id).all()
        for participant in participants:
            # 快路径：本场本人已有格子就跳过。
            # 两个条件都要写，就像查考场座位必须同时报"哪场考试 + 哪个学生"；
            # 只看 user_id 会把另一场约骑的格子误当成本场格子。
            exists = (
                db.query(MeetupActivity.id)
                .filter(
                    MeetupActivity.meetup_id == meetup.id,
                    MeetupActivity.user_id == participant.user_id,
                )
                .first()
            )
            if exists is not None:
                continue

            # 窗口直接在 SQL 上界收口（出发后 6 小时内动身才算本场），
            # 不再有"同北京日"的 Python 二次判定——见 ATTACH_LATE_START_HOURS 注释。
            candidates = (
                db.query(Activity)
                .filter(
                    Activity.user_id == participant.user_id,
                    Activity.status == "completed",
                    Activity.started_at.isnot(None),
                    Activity.started_at >= meetup.start_time - timedelta(minutes=30),
                    Activity.started_at <= meetup.start_time + timedelta(hours=ATTACH_LATE_START_HOURS),
                )
                .order_by(Activity.started_at.asc())
                .all()
            )
            match = candidates[0] if candidates else None
            if match is None:
                continue

            meetup_id = meetup.id
            user_id = participant.user_id
            activity_id = match.id
            db.add(MeetupActivity(meetup_id=meetup_id, activity_id=activity_id, user_id=user_id))
            try:
                db.commit()
            except IntegrityError:
                # 并发 tick 像两个收卷员同时伸手拿同一份卷子。
                # UNIQUE 会让其中一个拿不到；正确动作是回滚这一小步，继续收其他人的卷子。
                db.rollback()
                continue
            attached += 1
            logger.info(
                "SENSOR attach meetup_id=%s user_id=%s activity_id=%s",
                meetup_id,
                user_id,
                activity_id,
            )
    return attached


def run_meetup_attach_tick() -> int:
    """给 scheduler 调的外壳：自己借数据库钥匙，用完一定归还。"""
    db = SessionLocal()
    try:
        return attach_meetup_activities(db)
    finally:
        db.close()
