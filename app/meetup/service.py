"""
约骑业务逻辑——把路线图纸变成可发布、可取消、可查看的约骑活动。

操作注意事项：DRAFT 可以反复改并重算路线快照；OPEN 之后快照冻结，只能按状态机取消或完成。
输入/输出数据流：router 传入当前用户和表单字段；service 写 meetups/participants，返回 ORM 对象给 API 层翻译。
"""

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.meetup.models import Meetup, MeetupMedia, MeetupParticipant
from app.route_book.models import RouteBook
from app.segment.models import Segment


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_aware(value: datetime) -> datetime:
    """把测试或 SQLite 里可能丢时区的时间补回 UTC。"""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


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
        raise HTTPException(status_code=409, detail=f"invalid status: {meetup.status}")
    if check_time_cutoff:
        cutoff = _ensure_aware(meetup.start_time) - timedelta(minutes=30, seconds=30)
        if _now_utc() >= cutoff:
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

    snapshot = _snapshot_from_route(db, segment_id, route_book_id)
    meetup = Meetup(
        creator_id=current_user_id,
        status="DRAFT",
        segment_id=segment_id,
        route_book_id=route_book_id,
        start_time=_ensure_aware(start_time),
        estimated_end_time=_ensure_aware(estimated_end_time),
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
    db.delete(meetup)
    db.commit()


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
        start_text, end_text = date_range.split(",", 1)
        start_dt = _ensure_aware(datetime.fromisoformat(start_text))
        end_dt = _ensure_aware(datetime.fromisoformat(end_text))
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
        rows = (
            db.query(MeetupParticipant.meetup_id, MeetupParticipant.id)
            .filter(MeetupParticipant.meetup_id.in_(meetup_ids))
            .all()
        )
        for row in rows:
            participants_count[row.meetup_id] = participants_count.get(row.meetup_id, 0) + 1

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
