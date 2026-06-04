"""
约骑业务逻辑——把路线图纸变成可发布、可取消、可查看的约骑活动。

操作注意事项：DRAFT 可以反复改并重算路线快照；OPEN 之后快照冻结，只能按状态机取消或完成。
输入/输出数据流：router 传入当前用户和表单字段；service 写 meetups/participants，返回 ORM 对象给 API 层翻译。
"""

import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.meetup.models import Meetup, MeetupMedia, MeetupParticipant
from app.meetup.schemas import InviteeSummary
from app.route_book.models import RouteBook
from app.segment.models import Segment
from app.storage.local import LocalStorage
from app.user.models import User


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


def _delete_meetup_row_and_collect_files(db: Session, meetup_id: int) -> list[str]:
    """只删除约骑相关数据库行并收集文件名，像先把相册目录抄下来再搬走柜子。"""
    meetup = db.query(Meetup).filter(Meetup.id == meetup_id).first()
    if meetup is None:
        return []
    file_ids = [
        row.file_id
        for row in db.query(MeetupMedia.file_id).filter(MeetupMedia.meetup_id == meetup.id).all()
        if row.file_id
    ]
    db.query(MeetupMedia).filter(MeetupMedia.meetup_id == meetup.id).delete(synchronize_session=False)
    db.delete(meetup)
    return file_ids


def _cleanup_meetup_storage(file_ids: list[str]) -> None:
    """commit 后再删物理文件；DB 已经收好摊，storage 清理失败只记账等待后续清理。"""
    for file_id in file_ids:
        try:
            _storage.delete(file_id)
        except Exception:
            logger.warning("清理约骑媒体文件失败 file_id=%s", file_id, exc_info=True)


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
    cancelled_returns_410: bool = False,
) -> Meetup:
    """读取约骑并执行权限/状态/时间门禁，像门卫一次查完票和身份。

    cancelled_returns_410：只有 join/leave 才把"约骑已取消"当 410 返回（spec 错误码要求）。
    delete/update/cancel 不传这个开关——它们遇到已取消的约骑按"状态不匹配"统一走 409
    （spec：删非 DRAFT 约骑返 409）。这样 join 需要的 410 不会渗透到其他端点、改坏它们的错误码。"""
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
        if cancelled_returns_410 and meetup.status == "CANCELLED":
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
    supply_point: str | None = None,
    audience_tags: list[str] | None = None,
    visibility: str = "public",
    eligibility_note: str | None = None,
    safety_note: str | None = None,
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
        supply_point=supply_point,
        audience_tags=audience_tags or [],
        visibility=visibility,
        eligibility_note=eligibility_note,
        safety_note=safety_note,
        share_token=secrets.token_urlsafe(32),
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

    for key in (
        "start_time",
        "estimated_end_time",
        "meeting_point",
        "pace_level",
        "max_participants",
        "description",
        "supply_point",
        "audience_tags",
        "visibility",
        "eligibility_note",
        "safety_note",
    ):
        if key in changes:
            value = changes[key]
            if key in {"start_time", "estimated_end_time"} and value is not None:
                value = _ensure_aware(value)
            if key == "audience_tags" and value is None:
                value = []
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
        db.add(MeetupParticipant(meetup_id=meetup.id, user_id=current_user_id, is_creator=True, joined_at=_now_utc()))
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
    file_ids = _delete_meetup_row_and_collect_files(db, meetup.id)
    db.commit()
    # commit 后再删 storage（DB 是 source of truth）：删失败只记日志不阻塞用户，孤儿文件留定期清理 v2。
    _cleanup_meetup_storage(file_ids)


def get_my_draft(db: Session, current_user_id: int) -> Meetup | None:
    return db.query(Meetup).filter(Meetup.creator_id == current_user_id, Meetup.status == "DRAFT").first()


def _assemble_list_result(db: Session, base, page: int, page_size: int) -> dict:
    """分页 + 聚合人数/首图。公开列表 list_meetups 和"我的约骑"list_my_meetups 共用，
    避免两套聚合逻辑漂移（人数走 GROUP BY 防 N+1；首图按 (seq,id) 取最小、和详情页同口径）。"""
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
        count_rows = (
            db.query(MeetupParticipant.meetup_id, func.count(MeetupParticipant.id))
            .filter(MeetupParticipant.meetup_id.in_(meetup_ids))
            .group_by(MeetupParticipant.meetup_id)
            .all()
        )
        participants_count = {meetup_id: count for meetup_id, count in count_rows}
        media_rows = (
            db.query(MeetupMedia.meetup_id, MeetupMedia.file_id)
            .filter(MeetupMedia.meetup_id.in_(meetup_ids))
            .order_by(MeetupMedia.meetup_id, MeetupMedia.seq.asc(), MeetupMedia.id.asc())
            .all()
        )
        for row in media_rows:
            if row.meetup_id not in first_media:
                first_media[row.meetup_id] = row.file_id
    return {
        "items": items,
        "total": total,
        "participants_count": participants_count,
        "first_media": first_media,
    }


def list_meetups(
    db: Session,
    status: str | None = None,
    city: str | None = None,
    date_range: str | None = None,
    pace: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    base = db.query(Meetup).filter(Meetup.visibility == "public")
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

    return _assemble_list_result(db, base, page, page_size)


def list_my_meetups(db: Session, current_user_id: int, role: str, page: int = 1, page_size: int = 20) -> dict:
    """个人页"我的约骑"。
    role=created：我发起的（含草稿/已取消，便于发起人管理全部）；
    role=joined：我加入别人的（排除自己发起的——发起人 publish 会自动占位，否则会和"我发起的"重复）。"""
    if role == "created":
        base = db.query(Meetup).filter(Meetup.creator_id == current_user_id)
    elif role == "joined":
        base = (
            db.query(Meetup)
            .join(MeetupParticipant, MeetupParticipant.meetup_id == Meetup.id)
            .filter(MeetupParticipant.user_id == current_user_id, Meetup.creator_id != current_user_id)
        )
    else:
        raise HTTPException(status_code=422, detail="role 必须是 created 或 joined")
    return _assemble_list_result(db, base, page, page_size)


def _assert_invite_only_access(
    db: Session,
    meetup: Meetup,
    current_user_id: int | None,
    token: str | None,
) -> None:
    """私圈约骑的门票检查：发起人、已加入者、或拿到分享口令的人才能进。"""
    if meetup.visibility != "invite_only":
        return
    if current_user_id is not None and meetup.creator_id == current_user_id:
        return
    if current_user_id is not None and is_participant(db, meetup.id, current_user_id):
        return
    if token is not None and meetup.share_token is not None and secrets.compare_digest(token, meetup.share_token):
        return
    raise HTTPException(status_code=404, detail="meetup not found")


def get_meetup_detail(
    db: Session,
    meetup_id: int,
    current_user_id: int | None = None,
    token: str | None = None,
) -> Meetup:
    meetup = db.query(Meetup).filter(Meetup.id == meetup_id).first()
    if meetup is None:
        raise HTTPException(status_code=404, detail="meetup not found")
    _assert_invite_only_access(db, meetup, current_user_id, token)
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


def is_participant(db: Session, meetup_id: int, user_id: int) -> bool:
    """当前用户是否已加入该约骑（含发起人 publish 时自动占的位）。
    详情接口用它告诉前端：该显示"退出"还是"加入"。"""
    return (
        db.query(MeetupParticipant.id)
        .filter(MeetupParticipant.meetup_id == meetup_id, MeetupParticipant.user_id == user_id)
        .first()
        is not None
    )


def get_first_media_file_id(db: Session, meetup_id: int) -> str | None:
    """查约骑卡片首图，保证列表页和详情页看到同一张封面。"""
    row = (
        db.query(MeetupMedia.file_id)
        .filter(MeetupMedia.meetup_id == meetup_id)
        .order_by(MeetupMedia.seq.asc(), MeetupMedia.id.asc())
        .first()
    )
    return row.file_id if row is not None else None


def list_participants(
    db: Session,
    meetup_id: int,
    current_user_id: int,
    token: str | None = None,
) -> list[InviteeSummary]:
    meetup = db.query(Meetup).filter(Meetup.id == meetup_id).first()
    if meetup is None:
        raise HTTPException(status_code=404, detail="meetup not found")
    _assert_invite_only_access(db, meetup, current_user_id, token)

    rows = (
        db.query(MeetupParticipant, User)
        .join(User, User.id == MeetupParticipant.user_id)
        .filter(MeetupParticipant.meetup_id == meetup.id)
        .order_by(MeetupParticipant.joined_at.asc(), MeetupParticipant.id.asc())
        .all()
    )
    return [
        InviteeSummary(
            user_id=user.id,
            nickname=user.nickname or None,
            avatar_url=user.avatar_url,
            is_creator=participant.is_creator is True,
            joined_at=participant.joined_at,
        )
        for participant, user in rows
    ]


def join_meetup(db: Session, meetup_id: int, current_user_id: int, token: str | None = None) -> dict:
    meetup = _load_and_authorize_meetup(
        db,
        meetup_id,
        current_user_id,
        require_status=["OPEN"],
        check_time_cutoff=True,
        cancelled_returns_410=True,
    )
    _assert_invite_only_access(db, meetup, current_user_id, token)
    existing = db.query(MeetupParticipant).filter_by(meetup_id=meetup.id, user_id=current_user_id).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="already_joined")

    count = count_participants(db, meetup.id)
    if count >= meetup.max_participants:
        raise HTTPException(status_code=409, detail="meetup_full")

    db.add(MeetupParticipant(meetup_id=meetup.id, user_id=current_user_id, is_creator=False, joined_at=_now_utc()))
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
        cancelled_returns_410=True,
    )
    # 发起人不能退出自己发起的约骑：要退只能取消整个约骑（走 cancel 端点）。
    # 否则约骑还挂在他名下、参与列表却没有他 = 没人负责的幽灵约骑（下游 task7 自动完成 / task8 赛段卡都会踩）。
    if meetup.creator_id == current_user_id:
        raise HTTPException(status_code=403, detail="creator_cannot_leave")
    participant = db.query(MeetupParticipant).filter_by(meetup_id=meetup.id, user_id=current_user_id).first()
    if participant is None:
        raise HTTPException(status_code=409, detail="not_joined")

    count = count_participants(db, meetup.id)
    db.delete(participant)
    db.commit()
    db.refresh(meetup)
    return {"meetup": meetup, "participants_count": max(0, count - 1)}
