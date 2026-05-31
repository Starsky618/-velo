"""
约骑业务逻辑——把路线图纸变成可发布、可取消、可查看的约骑活动。

操作注意事项：DRAFT 可以反复改并重算路线快照；OPEN 之后快照冻结，只能按状态机取消或完成。
输入/输出数据流：router 传入当前用户和表单字段；service 写 meetups/participants，返回 ORM 对象给 API 层翻译。
"""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.meetup.models import Meetup, MeetupMedia, MeetupParticipant
from app.route_book.models import RouteBook
from app.segment.models import Segment
from app.storage.local import LocalStorage


logger = logging.getLogger(__name__)
_storage = LocalStorage()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_aware(value: datetime) -> datetime:
    """把测试或 SQLite 里可能丢时区的时间补回 UTC。"""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _ensure_time_order(start: datetime, end: datetime) -> None:
    """预计结束必须晚于开始。DB 有 ck_meetups_time_order 兜底，但 service 层显式校验
    能在真 PG CHECK 报错前就返回友好的 422，而不是让 IntegrityError 穿透成 500。"""
    if end <= start:
        raise HTTPException(status_code=422, detail="estimated_end_time 必须晚于 start_time")


def _snapshot_from_route(db: Session, segment_id: int | None, route_book_id: int | None) -> dict:
    """从 segment 或 route_book 抄一份发布卡片快照，像给路线拍照留档。"""
    if (segment_id is None) == (route_book_id is None):
        raise HTTPException(status_code=422, detail="segment_id 和 route_book_id 必须二选一")

    if segment_id is not None:
        segment = db.query(Segment).filter(Segment.id == segment_id).first()
        if segment is None:
            raise HTTPException(status_code=404, detail="segment not found")
        return {
            "snapshot_route_name": segment.name,
            "snapshot_distance": segment.distance,
            "snapshot_climb": segment.elevation_gain,
            "snapshot_city": segment.city or "unknown",
        }

    route = db.query(RouteBook).filter(RouteBook.id == route_book_id).first()
    if route is None:
        raise HTTPException(status_code=404, detail="route_book not found")
    return {
        "snapshot_route_name": route.name,
        "snapshot_distance": route.distance,
        "snapshot_climb": route.climb,
        "snapshot_city": route.city or "unknown",
    }


def _draft_exists_error(existing: Meetup | None) -> HTTPException:
    detail = {
        "code": "draft_exists",
        "existing_draft_id": existing.id if existing is not None else None,
        "message": "你已有 1 个草稿，是否覆盖？",
    }
    return HTTPException(status_code=409, detail=detail)


def _load_and_authorize_meetup(
    db: Session,
    meetup_id: int,
    current_user_id: int,
    *,
    require_creator: bool = False,
    require_status: list[str] | None = None,
    check_time_cutoff: bool = False,
) -> Meetup:
    """读取约骑并执行权限/状态/时间门禁，像门卫一次查完票和身份。"""
    meetup = (
        db.query(Meetup)
        .filter(Meetup.id == meetup_id)
        .with_for_update()
        .populate_existing()
        .first()
    )
    if meetup is None:
        raise HTTPException(status_code=404, detail="meetup not found")
    if require_creator and meetup.creator_id != current_user_id:
        raise HTTPException(status_code=403, detail="not creator")
    if require_status and meetup.status not in require_status:
        if meetup.status == "CANCELLED":
            raise HTTPException(status_code=410, detail="meetup cancelled")
        raise HTTPException(status_code=409, detail=f"invalid status: {meetup.status}")
    if check_time_cutoff:
        cutoff = _ensure_aware(meetup.start_time) - timedelta(minutes=30, seconds=30)
        if _now_utc() > cutoff:
            raise HTTPException(status_code=410, detail="meetup cutoff passed")
    return meetup


def create_meetup(
    db: Session,
    current_user_id: int,
    segment_id: int | None,
    route_book_id: int | None,
    start_time: datetime,
    estimated_end_time: datetime,
    meeting_point: str,
    pace_level: str,
    max_participants: int,
    description: str | None,
) -> Meetup:
    existing = db.query(Meetup).filter(Meetup.creator_id == current_user_id, Meetup.status == "DRAFT").first()
    if existing is not None:
        raise _draft_exists_error(existing)

    start_aware = _ensure_aware(start_time)
    end_aware = _ensure_aware(estimated_end_time)
    _ensure_time_order(start_aware, end_aware)

    snapshot = _snapshot_from_route(db, segment_id, route_book_id)
    meetup = Meetup(
        creator_id=current_user_id,
        status="DRAFT",
        segment_id=segment_id,
        route_book_id=route_book_id,
        start_time=start_aware,
        estimated_end_time=end_aware,
        meeting_point=meeting_point,
        pace_level=pace_level,
        max_participants=max_participants,
        description=description,
        **snapshot,
    )
    db.add(meetup)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if "uq_meetups_creator_draft" in str(exc.orig):
            existing = db.query(Meetup).filter(Meetup.creator_id == current_user_id, Meetup.status == "DRAFT").first()
            raise _draft_exists_error(existing)
        raise
    db.refresh(meetup)
    return meetup


def update_meetup(db: Session, meetup_id: int, current_user_id: int, **changes) -> Meetup:
    meetup = _load_and_authorize_meetup(
        db,
        meetup_id,
        current_user_id,
        require_creator=True,
        require_status=["DRAFT"],
    )
    route_changed = "segment_id" in changes or "route_book_id" in changes
    if route_changed:
        snapshot = _snapshot_from_route(db, changes.get("segment_id"), changes.get("route_book_id"))
        for key, value in snapshot.items():
            setattr(meetup, key, value)
        meetup.segment_id = changes.get("segment_id")
        meetup.route_book_id = changes.get("route_book_id")

    for key in ("start_time", "estimated_end_time", "meeting_point", "pace_level", "max_participants", "description"):
        if key in changes:
            value = changes[key]
            if key in {"start_time", "estimated_end_time"} and value is not None:
                value = _ensure_aware(value)
            setattr(meetup, key, value)

    # 改完时间后用最终值校验顺序（用户可能只改了 start 或只改了 end 导致颠倒）
    _ensure_time_order(_ensure_aware(meetup.start_time), _ensure_aware(meetup.estimated_end_time))

    db.commit()
    db.refresh(meetup)
    return meetup


def publish_meetup(db: Session, meetup_id: int, current_user_id: int) -> Meetup:
    meetup = _load_and_authorize_meetup(
        db,
        meetup_id,
        current_user_id,
        require_creator=True,
        require_status=["DRAFT"],
    )
    meetup.status = "OPEN"
    existing = db.query(MeetupParticipant).filter_by(meetup_id=meetup.id, user_id=current_user_id).first()
    if existing is None:
        db.add(MeetupParticipant(meetup_id=meetup.id, user_id=current_user_id, is_creator=True))
    db.commit()
    db.refresh(meetup)
    return meetup


def cancel_meetup(db: Session, meetup_id: int, current_user_id: int) -> Meetup:
    meetup = _load_and_authorize_meetup(
        db,
        meetup_id,
        current_user_id,
        require_creator=True,
        require_status=["OPEN"],
        check_time_cutoff=True,
    )
    meetup.status = "CANCELLED"
    meetup.cancelled_at = _now_utc()
    db.commit()
    db.refresh(meetup)
    return meetup


def delete_draft_meetup(db: Session, meetup_id: int, current_user_id: int) -> None:
    meetup = _load_and_authorize_meetup(
        db,
        meetup_id,
        current_user_id,
        require_creator=True,
        require_status=["DRAFT"],
    )
    # 先收集媒体文件路径：CASCADE 会删 meetup_media 行，但 storage 物理文件要单独删，否则留孤儿文件（spec §8.4）。
    # 草稿阶段也可能已传媒体（POST media 只要求 creator 不限状态）。
    file_ids = [
        row.file_id
        for row in db.query(MeetupMedia.file_id).filter(MeetupMedia.meetup_id == meetup.id).all()
        if row.file_id
    ]
    db.delete(meetup)
    db.commit()
    # commit 后再删 storage（DB 是 source of truth）：删失败只记日志不阻塞用户，孤儿文件留定期清理 v2。
    for file_id in file_ids:
        try:
            _storage.delete(file_id)
        except OSError as e:
            logger.warning("删草稿清理媒体文件失败 file_id=%s: %s", file_id, e)


def get_my_draft(db: Session, current_user_id: int) -> Meetup | None:
    return db.query(Meetup).filter(Meetup.creator_id == current_user_id, Meetup.status == "DRAFT").first()


def list_meetups(
    db: Session,
    status: str | None = None,
    city: str | None = None,
    date_range: str | None = None,
    pace: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    base = db.query(Meetup)
    if status:
        base = base.filter(Meetup.status == status)
    if city:
        base = base.filter(Meetup.snapshot_city == city)
    if pace:
        base = base.filter(Meetup.pace_level == pace)
    if date_range:
        try:
            start_text, end_text = date_range.split(",", 1)
            start_dt = _ensure_aware(datetime.fromisoformat(start_text))
            end_dt = _ensure_aware(datetime.fromisoformat(end_text))
        except ValueError:
            raise HTTPException(status_code=422, detail="date_range 格式应为 '开始ISO,结束ISO'")
        base = base.filter(Meetup.start_time >= start_dt, Meetup.start_time <= end_dt)

    total = base.count()
    items = (
        base.order_by(Meetup.start_time.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    meetup_ids = [meetup.id for meetup in items]
    participants_count = {}
    first_media = {}

    if meetup_ids:
        # 用 SQL GROUP BY COUNT 聚合，不把全部 participant 行拉回内存（spec §6.1 R3-I6 N+1 修复模板）
        count_rows = (
            db.query(MeetupParticipant.meetup_id, func.count(MeetupParticipant.id))
            .filter(MeetupParticipant.meetup_id.in_(meetup_ids))
            .group_by(MeetupParticipant.meetup_id)
            .all()
        )
        participants_count = {meetup_id: count for meetup_id, count in count_rows}

        media_rows = (
            db.query(MeetupMedia.meetup_id, MeetupMedia.file_id)
            .filter(MeetupMedia.meetup_id.in_(meetup_ids), MeetupMedia.seq == 0)
            .all()
        )
        first_media = {row.meetup_id: row.file_id for row in media_rows}

    return {
        "items": items,
        "total": total,
        "participants_count": participants_count,
        "first_media": first_media,
    }


def get_meetup_detail(db: Session, meetup_id: int) -> Meetup:
    meetup = db.query(Meetup).filter(Meetup.id == meetup_id).first()
    if meetup is None:
        raise HTTPException(status_code=404, detail="meetup not found")
    return meetup


def count_participants(db: Session, meetup_id: int) -> int:
    """查单个约骑当前参与人数。

    为什么单独抽出来：列表页用 SQL GROUP BY 批量聚合人数（见 list_meetups），
    但详情、发布、取消这些"返回单条约骑"的端点之前没查人数、用了默认 0，
    结果同一个已发布约骑——列表显示 1 人、详情显示 0 人。
    详情页是用户决定加不加入的关键页，显示"0 人参加"会直接劝退。
    所以这三个端点统一调本函数，和列表页保持同一口径（COUNT 参与记录）。
    """
    return (
        db.query(func.count(MeetupParticipant.id))
        .filter(MeetupParticipant.meetup_id == meetup_id)
        .scalar()
        or 0
    )


def join_meetup(db: Session, meetup_id: int, current_user_id: int) -> dict:
    meetup = _load_and_authorize_meetup(
        db,
        meetup_id,
        current_user_id,
        require_status=["OPEN"],
        check_time_cutoff=True,
    )
    existing = db.query(MeetupParticipant).filter_by(meetup_id=meetup.id, user_id=current_user_id).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="already_joined")

    count = count_participants(db, meetup.id)
    if count >= meetup.max_participants:
        raise HTTPException(status_code=409, detail="meetup_full")

    db.add(MeetupParticipant(meetup_id=meetup.id, user_id=current_user_id, is_creator=False))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if "uq_meetup_participant_user" in str(exc.orig):
            raise HTTPException(status_code=409, detail="already_joined")
        raise
    db.refresh(meetup)
    return {"meetup": meetup, "participants_count": count + 1}


def leave_meetup(db: Session, meetup_id: int, current_user_id: int) -> dict:
    meetup = _load_and_authorize_meetup(
        db,
        meetup_id,
        current_user_id,
        require_status=["OPEN"],
        check_time_cutoff=True,
    )
    participant = db.query(MeetupParticipant).filter_by(meetup_id=meetup.id, user_id=current_user_id).first()
    if participant is None:
        raise HTTPException(status_code=409, detail="not_joined")

    count = count_participants(db, meetup.id)
    db.delete(participant)
    db.commit()
    db.refresh(meetup)
    return {"meetup": meetup, "participants_count": max(0, count - 1)}
