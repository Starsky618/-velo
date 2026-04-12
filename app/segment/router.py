"""
赛段模块的 API 路由——"赛道服务台"。

五个窗口各有分工：
1. POST /api/segments — 管理员创建赛段（"赛事审批窗口"）
2. GET /api/segments — 查赛段列表（"赛道目录查询机"）
3. GET /api/segments/{id} — 查赛段详情 + TOP20 排行榜
4. GET /api/segments/{id}/leaderboard — 完整排行榜（分页+车型过滤）
5. GET /api/user/efforts — 当前用户的所有赛段成绩

注意事项：
- 所有路由函数用 def（同步），禁止 async def
- 创建赛段需要管理员权限，排行榜公开，用户成绩需登录
- 用户成绩接口路径是 /api/user/efforts，通过单独的 user_effort_router 挂载
- 不直接操作数据库，所有业务逻辑交给 service 层
"""

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.segment import schemas, service

# 创建路由器，所有赛段相关接口都挂在 /api/segments 下
router = APIRouter(prefix="/api/segments", tags=["segment"])


@router.post("", response_model=schemas.SegmentResponse)
def create_segment(
    req: schemas.SegmentCreateRequest,
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    创建赛段——管理员专用。

    管理员提交一组 GPS 坐标点（至少 2 个），
    后端自动计算距离、爬升，生成 PostGIS 赛段线条。
    普通用户调用会收到 403 错误。
    """
    # 把 Pydantic 对象转成 dict 列表传给 service
    points = [p.model_dump() for p in req.reference_points]

    try:
        segment = service.create_segment(
            db=db,
            user_id=user_id,
            name=req.name,
            reference_points=points,
            description=req.description,
            match_tolerance=req.match_tolerance,
            min_match_ratio=req.min_match_ratio,
            coordinate_system=req.coordinate_system,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 距离：米 → 公里，保留 2 位小数（手动构造响应，避免 ORM 脏数据问题）
    # elevation_profile 存储为 JSON 字符串，返回前反序列化成列表
    return schemas.SegmentResponse(
        id=segment.id,
        name=segment.name,
        description=segment.description,
        distance=round(segment.distance / 1000.0, 2),
        elevation_gain=segment.elevation_gain,
        elevation_loss=segment.elevation_loss,
        avg_gradient=segment.avg_gradient,
        elevation_profile=json.loads(segment.elevation_profile) if segment.elevation_profile else None,
        start_lat=segment.start_lat,
        start_lon=segment.start_lon,
        end_lat=segment.end_lat,
        end_lon=segment.end_lon,
        match_tolerance=segment.match_tolerance,
        min_match_ratio=segment.min_match_ratio,
        created_at=segment.created_at,
    )


@router.delete("/{segment_id}", status_code=204)
def delete_segment(
    segment_id: int,
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    删除赛段——管理员专用。

    删除赛段及其所有成绩记录。不可恢复。
    """
    try:
        service.delete_segment(db, segment_id, user_id)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("", response_model=schemas.SegmentListResponse)
def list_segments(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    near_lat: float | None = Query(None, ge=-90, le=90),
    near_lon: float | None = Query(None, ge=-180, le=180),
    radius: float = Query(50000, gt=0, le=500000),
    db: Session = Depends(get_db),
):
    """
    查询赛段列表（分页）。

    支持附近搜索：传入 near_lat + near_lon + radius（默认 50km，上限 500km），
    返回指定半径内的赛段。不传坐标则返回所有赛段。
    不需要登录——赛段目录对所有人公开。
    """
    # near_lat 和 near_lon 必须成对出现，只传一个没有意义
    if (near_lat is None) != (near_lon is None):
        raise HTTPException(status_code=400, detail="near_lat和near_lon必须同时提供")

    items, total = service.get_segment_list(
        db, page, page_size, near_lat, near_lon, radius,
    )
    return schemas.SegmentListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{segment_id}", response_model=schemas.SegmentDetailResponse)
def get_segment(
    segment_id: int,
    db: Session = Depends(get_db),
):
    """
    查看赛段详情 + 排行榜前 20 名。

    不需要登录——排行榜是公开的，任何人都能查看。
    """
    try:
        detail = service.get_segment_detail(db, segment_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return detail


@router.get("/{segment_id}/leaderboard", response_model=schemas.LeaderboardResponse)
def get_leaderboard(
    segment_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    bike_type: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """
    查看赛段完整排行榜（分页）。

    比详情接口的 TOP20 更完整：支持翻页查看所有成绩，
    还能按车型过滤（只看公路车、砾石车等）。
    不需要登录——排行榜公开。
    """
    try:
        items, total = service.get_leaderboard(
            db, segment_id, page, page_size, bike_type,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return schemas.LeaderboardResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


# ==================== 用户赛段成绩 ====================
# 这个接口路径是 /api/user/efforts，不在 /api/segments 下，
# 所以用单独的路由器挂载（在 main.py 中注册）。

user_effort_router = APIRouter(prefix="/api/user", tags=["segment"])


@user_effort_router.get("/efforts", response_model=schemas.UserEffortsResponse)
def get_user_efforts(
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    查看当前用户在所有赛段的成绩。

    好比运动员查自己的"全赛道成绩单"：
    在哪些赛道跑过、用时多少、排第几。
    需要登录——只能查自己的成绩。
    """
    items = service.get_user_efforts(db, user_id)
    return schemas.UserEffortsResponse(items=items)


# ==================== 活动途经赛段（Task 4.6） ====================
# 路径是 /api/activities/{id}/segments，不在 /api/segments 下，
# 注册在 segment 模块是因为依赖方向正确（Segment 依赖 Activity）。

activity_segment_router = APIRouter(prefix="/api/activities", tags=["segment"])


@activity_segment_router.get(
    "/{activity_id}/segments",
    response_model=schemas.ActivitySegmentsResponse,
)
def get_activity_segments(
    activity_id: int,
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    查看某次骑行途经的所有赛段成绩。

    骑行完成后查看"这次骑了哪些赛道、排第几、有没有刷新个人最佳"。
    只能查看自己的活动，查别人的返回 403。
    """
    try:
        items = service.get_activity_segments(db, activity_id, user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    return schemas.ActivitySegmentsResponse(items=items)
