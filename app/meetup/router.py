"""
约骑 API 路由——列表、详情、草稿、发布、取消和删除的 HTTP 服务台。

操作注意事项：路由只做参数校验和 HTTP 翻译，不复制 service 状态机，避免前台和后台各有一套规则。
输入/输出数据流：输入是 JWT 用户和 JSON 请求；输出是 `MeetupResponse` 或 `MeetupListResponse`。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.meetup import schemas, service


router = APIRouter(prefix="/api/meetups", tags=["meetup"])


def _response(meetup, participants_count=0, first_media_file_id=None) -> schemas.MeetupResponse:
    """把 ORM 行翻译成 API 卡片，像把后台单据整理成前台可读票面。"""
    return schemas.MeetupResponse(
        id=meetup.id,
        creator_id=meetup.creator_id,
        status=meetup.status,
        segment_id=meetup.segment_id,
        route_book_id=meetup.route_book_id,
        snapshot_route_name=meetup.snapshot_route_name,
        snapshot_distance=meetup.snapshot_distance,
        snapshot_climb=meetup.snapshot_climb,
        snapshot_city=meetup.snapshot_city,
        start_time=meetup.start_time,
        estimated_end_time=meetup.estimated_end_time,
        meeting_point=meetup.meeting_point,
        pace_level=meetup.pace_level,
        max_participants=meetup.max_participants,
        description=meetup.description,
        participants_count=participants_count,
        first_media_file_id=first_media_file_id,
        created_at=meetup.created_at,
        cancelled_at=meetup.cancelled_at,
        completed_at=meetup.completed_at,
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
    return _response(meetup) if meetup is not None else None


@router.get("/{meetup_id}", response_model=schemas.MeetupResponse)
def get_meetup(meetup_id: int, db: Session = Depends(get_db)):
    return _response(service.get_meetup_detail(db, meetup_id))


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
        max_participants=req.max_participants,
        description=req.description,
    )
    return _response(meetup)


@router.patch("/{meetup_id}", response_model=schemas.MeetupResponse)
def update_meetup(
    meetup_id: int,
    req: schemas.MeetupPatchRequest,
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    changes = req.model_dump(exclude_unset=True)
    return _response(service.update_meetup(db, meetup_id, current_user_id, **changes))


@router.post("/{meetup_id}/publish", response_model=schemas.MeetupResponse)
def publish_meetup(meetup_id: int, current_user_id: int = Depends(get_current_user), db: Session = Depends(get_db)):
    return _response(service.publish_meetup(db, meetup_id, current_user_id), participants_count=1)


@router.post("/{meetup_id}/cancel", response_model=schemas.MeetupResponse)
def cancel_meetup(meetup_id: int, current_user_id: int = Depends(get_current_user), db: Session = Depends(get_db)):
    return _response(service.cancel_meetup(db, meetup_id, current_user_id))


@router.delete("/{meetup_id}", status_code=204)
def delete_meetup(meetup_id: int, current_user_id: int = Depends(get_current_user), db: Session = Depends(get_db)):
    service.delete_draft_meetup(db, meetup_id, current_user_id)
