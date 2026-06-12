"""
约骑 API 路由——列表、详情、草稿、发布、取消和删除的 HTTP 服务台。

操作注意事项：路由只做参数校验和 HTTP 翻译，不复制 service 状态机，避免前台和后台各有一套规则。
输入/输出数据流：输入是 JWT 用户和 JSON 请求；输出是 `MeetupResponse` 或 `MeetupListResponse`。
"""

import logging
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, get_optional_user
from app.meetup import media_service, schemas, service
from app.middleware.rate_limit import check_rate_limit_by_user
from app.route_book.tencent_direction import TencentMapConfigError, TencentMapError


router = APIRouter(prefix="/api/meetups", tags=["meetup"])
logger = logging.getLogger(__name__)


def _response(meetup, participants_count=0, first_media_file_id=None, current_user_id=None, db=None) -> schemas.MeetupResponse:
    """把 ORM 行翻译成 API 卡片，像把后台单据整理成前台可读票面。

    current_user_id + db：算当前请求者视角的 is_creator / has_joined（详情页角色按钮用）。
    列表页不传（避免每条都查一次 has_joined 造成 N+1），默认都 False。"""
    is_creator = current_user_id is not None and meetup.creator_id == current_user_id
    has_joined = (
        current_user_id is not None and db is not None and service.is_participant(db, meetup.id, current_user_id)
    )
    return schemas.MeetupResponse(
        id=meetup.id,
        creator_id=meetup.creator_id,
        status=meetup.status,
        segment_id=meetup.segment_id,
        route_book_id=meetup.route_book_id,
        snapshot_route_name=meetup.snapshot_route_name,
        # 距离 DB 存米 → API 返 km（和赛段 API /1000 同口径）；爬升保持米（前端按米显示，单位一致）
        snapshot_distance=round(meetup.snapshot_distance / 1000, 2),
        snapshot_climb=meetup.snapshot_climb,
        snapshot_city=meetup.snapshot_city,
        start_time=meetup.start_time,
        estimated_end_time=meetup.estimated_end_time,
        meeting_point=meetup.meeting_point,
        pace_level=meetup.pace_level,
        recommended_power_label=meetup.recommended_power_label,
        average_speed_range=meetup.average_speed_range,
        max_participants=meetup.max_participants,
        description=meetup.description,
        supply_point=meetup.supply_point,
        audience_tags=meetup.audience_tags or [],
        visibility=meetup.visibility,
        eligibility_note=meetup.eligibility_note,
        safety_note=meetup.safety_note,
        share_token=meetup.share_token if is_creator else None,
        participants_count=participants_count,
        first_media_file_id=first_media_file_id,
        is_creator=is_creator,
        has_joined=has_joined,
        created_at=meetup.created_at,
        cancelled_at=meetup.cancelled_at,
        completed_at=meetup.completed_at,
    )


def _live_response(db: Session, meetup, participants_count=None, current_user_id=None) -> schemas.MeetupResponse:
    """单条约骑响应统一查人数和首图，避免列表页、详情页、操作返回口径分裂。
    current_user_id 透传给 _response 算角色标记（is_creator / has_joined）。"""
    if participants_count is None:
        participants_count = service.count_participants(db, meetup.id)
    return _response(
        meetup,
        participants_count=participants_count,
        first_media_file_id=service.get_first_media_file_id(db, meetup.id),
        current_user_id=current_user_id,
        db=db,
    )


@router.get("", response_model=schemas.MeetupListResponse)
def list_meetups(
    status: schemas.MeetupStatus | None = None,
    city: schemas.City | None = None,
    date_range: str | None = None,
    pace: schemas.PaceLevel | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    result = service.list_meetups(
        db,
        status=status,
        city=city,
        date_range=date_range,
        pace=pace,
        page=page,
        page_size=page_size,
    )
    items = [
        _response(
            meetup,
            participants_count=result["participants_count"].get(meetup.id, 0),
            first_media_file_id=result["first_media"].get(meetup.id),
        )
        for meetup in result["items"]
    ]
    return schemas.MeetupListResponse(items=items, total=result["total"], page=page, page_size=page_size)


@router.get("/my-draft", response_model=schemas.MeetupResponse | None)
def get_my_draft(current_user_id: int = Depends(get_current_user), db: Session = Depends(get_db)):
    meetup = service.get_my_draft(db, current_user_id)
    return _live_response(db, meetup, current_user_id=current_user_id) if meetup is not None else None


@router.get("/mine", response_model=schemas.MeetupListResponse)
def get_my_meetups(
    role: Literal["created", "joined"] = Query("created"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # 个人页"我的约骑"：created=我发起的 / joined=我加入别人的。必须登录（看自己的约骑）。
    # 注意路由顺序：本端点在 /{meetup_id} 之前注册，否则 "mine" 会被当成 meetup_id。
    result = service.list_my_meetups(db, current_user_id, role, page=page, page_size=page_size)
    items = [
        _response(
            meetup,
            participants_count=result["participants_count"].get(meetup.id, 0),
            first_media_file_id=result["first_media"].get(meetup.id),
        )
        for meetup in result["items"]
    ]
    # "我的约骑"两个 tab 的角色是确定的：created tab 每条都是我发起的、joined tab 每条都是我加入别人的
    # （见 service.list_my_meetups 的过滤条件）。按 role 批量置标记，省掉逐条查 has_joined 的 N+1，
    # 也修掉了之前没传 current_user_id 给 _response 导致 is_creator/has_joined 永远 False、
    # 个人页卡片按钮状态全错的 bug（该显示"取消/退出"却显示"加入"）。
    for item in items:
        if role == "created":
            item.is_creator = True
        else:
            item.has_joined = True
    return schemas.MeetupListResponse(items=items, total=result["total"], page=page, page_size=page_size)


@router.get("/favorite-places", response_model=list[schemas.MeetupFavoritePlaceOut])
def list_favorite_places(
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return [service.favorite_place_response(place) for place in service.list_favorite_places(db, current_user_id)]


@router.post("/favorite-places", response_model=schemas.MeetupFavoritePlaceOut)
def save_favorite_place(
    req: schemas.MeetupFavoritePlaceIn,
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    place = service.save_favorite_place(
        db,
        current_user_id,
        name=req.name,
        address=req.address,
        latitude=req.latitude,
        longitude=req.longitude,
        coordinate_system=req.coordinate_system,
    )
    return service.favorite_place_response(place)


@router.delete("/favorite-places/{place_id}", status_code=204)
def delete_favorite_place(
    place_id: int,
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service.delete_favorite_place(db, current_user_id, place_id)


@router.get("/place-search", response_model=schemas.MeetupPlaceSearchOut | None)
def search_meetup_place(
    keyword: str = Query(..., min_length=1, max_length=80),
    region: str = Query("太原", min_length=1, max_length=32),
    current_user_id: int = Depends(get_current_user),
):
    check_rate_limit_by_user(
        current_user_id,
        "meetup-place-search",
        limit=30,
        window_sec=300,
    )
    try:
        return service.search_meetup_place(keyword, region)
    except TencentMapConfigError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except TencentMapError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/{meetup_id}/participants", response_model=list[schemas.InviteeSummary])
def list_participants(
    meetup_id: int,
    token: str | None = Query(None),
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return service.list_participants(db, meetup_id, current_user_id, token=token)


@router.get("/{meetup_id}/report", response_model=schemas.MeetupReportOut)
def get_meetup_report(
    meetup_id: int,
    token: str | None = Query(None),
    current_user_id: int | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    service.get_meetup_detail(db, meetup_id, current_user_id=current_user_id, token=token)
    return service.get_meetup_report(db, meetup_id, current_user_id=current_user_id, token=token, prechecked=True)


@router.get("/{meetup_id}", response_model=schemas.MeetupResponse)
def get_meetup(
    meetup_id: int,
    token: str | None = Query(None),
    source: str = Query("direct"),
    current_user_id: int | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    # 详情仍 public（游客能看），但带 token 时算 is_creator/has_joined 给前端显示角色按钮
    meetup = service.get_meetup_detail(db, meetup_id, current_user_id=current_user_id, token=token)
    # 五环节传感器（D8）：像门口计数器，只记录真正过了详情门禁的人。
    # viewer 三态：anon=未登录，participant=已报名，guest=登录了但没报名。
    if current_user_id is None:
        viewer = "anon"
    else:
        viewer = "participant" if service.is_participant(db, meetup_id, current_user_id) else "guest"
    logger.info(
        "SENSOR view meetup_id=%s viewer=%s token=%s source=%s",
        meetup_id,
        viewer,
        token,
        source,
    )
    return _live_response(db, meetup, current_user_id=current_user_id)


@router.post("", response_model=schemas.MeetupResponse)
def create_meetup(
    req: schemas.MeetupCreateRequest,
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    meetup = service.create_meetup(
        db,
        current_user_id=current_user_id,
        segment_id=req.segment_id,
        route_book_id=req.route_book_id,
        start_time=req.start_time,
        estimated_end_time=req.estimated_end_time,
        meeting_point=req.meeting_point,
        pace_level=req.pace_level,
        recommended_power_label=req.recommended_power_label,
        average_speed_range=req.average_speed_range,
        max_participants=req.max_participants,
        description=req.description,
        supply_point=req.supply_point,
        audience_tags=req.audience_tags,
        visibility=req.visibility,
        eligibility_note=req.eligibility_note,
        safety_note=req.safety_note,
    )
    return _live_response(db, meetup, participants_count=0, current_user_id=current_user_id)


@router.patch("/{meetup_id}", response_model=schemas.MeetupResponse)
def update_meetup(
    meetup_id: int,
    req: schemas.MeetupPatchRequest,
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    changes = req.model_dump(exclude_unset=True)
    return _live_response(db, service.update_meetup(db, meetup_id, current_user_id, **changes), current_user_id=current_user_id)


@router.post("/{meetup_id}/publish", response_model=schemas.MeetupResponse)
def publish_meetup(meetup_id: int, current_user_id: int = Depends(get_current_user), db: Session = Depends(get_db)):
    meetup = service.publish_meetup(db, meetup_id, current_user_id)
    return _live_response(db, meetup, current_user_id=current_user_id)


@router.post("/{meetup_id}/cancel", response_model=schemas.MeetupResponse)
def cancel_meetup(meetup_id: int, current_user_id: int = Depends(get_current_user), db: Session = Depends(get_db)):
    meetup = service.cancel_meetup(db, meetup_id, current_user_id)
    return _live_response(db, meetup, current_user_id=current_user_id)


@router.post("/{meetup_id}/join", response_model=schemas.MeetupResponse)
def join_meetup(
    meetup_id: int,
    token: str | None = Query(None),
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = service.join_meetup(db, meetup_id, current_user_id, token=token)
    return _live_response(db, result["meetup"], participants_count=result["participants_count"], current_user_id=current_user_id)


@router.delete("/{meetup_id}/leave", response_model=schemas.MeetupResponse)
def leave_meetup(meetup_id: int, current_user_id: int = Depends(get_current_user), db: Session = Depends(get_db)):
    result = service.leave_meetup(db, meetup_id, current_user_id)
    return _live_response(db, result["meetup"], participants_count=result["participants_count"], current_user_id=current_user_id)


@router.get("/{meetup_id}/media", response_model=list[schemas.MeetupMediaResponse])
def list_media(
    meetup_id: int,
    token: str | None = Query(None),
    current_user_id: int | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    # 照片墙数据源：public 详情页所有人能看；invite_only 私圈照片也必须过口令门禁，
    # 否则猜连号 id 能绕过 /media 看到私圈约骑的照片。复用 get_meetup_detail 的门卫
    # （不符合返回 404），通过才返回媒体列表（按 seq 升序）。
    service.get_meetup_detail(db, meetup_id, current_user_id=current_user_id, token=token)
    return [media_service.media_response(m) for m in media_service.list_meetup_media(db, meetup_id)]


@router.post("/{meetup_id}/media", response_model=schemas.MeetupMediaResponse)
def upload_media(
    meetup_id: int,
    caption: str | None = Form(None),
    file: UploadFile = File(...),
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    media = media_service.upload_meetup_media(
        db,
        meetup_id=meetup_id,
        current_user_id=current_user_id,
        filename=file.filename or "upload",
        content_type=file.content_type or "",
        file_bytes=file.file.read(),
        caption=caption,
    )
    return media_service.media_response(media)


@router.delete("/{meetup_id}/media/{media_id}", status_code=204)
def delete_media(
    meetup_id: int,
    media_id: int,
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    media_service.delete_meetup_media(db, meetup_id, media_id, current_user_id)


@router.delete("/{meetup_id}", status_code=204)
def delete_meetup(meetup_id: int, current_user_id: int = Depends(get_current_user), db: Session = Depends(get_db)):
    service.delete_draft_meetup(db, meetup_id, current_user_id)
