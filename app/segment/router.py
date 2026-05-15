"""
赛段模块的 API 路由——"赛道服务台"。

六个窗口各有分工：
1. POST /api/segments — 管理员创建赛段（"赛事审批窗口"）
2. GET /api/segments — 查赛段列表（"赛道目录查询机"，v5 加 search/city/difficulty 三筛选卡）
3. GET /api/segments/{id} — 查赛段详情 + TOP20 排行榜（v5 响应加 max_gradient/city/difficulty）
4. GET /api/segments/{id}/leaderboard — 完整排行榜（分页+车型过滤）
5. GET /api/segments/{id}/efforts/me — 即时反馈（v5 新增 / "骑完看进步"对比）
6. GET /api/user/efforts — 当前用户的所有赛段成绩

注意事项：
- 所有路由函数用 def（同步），禁止 async def
- 创建赛段需要管理员权限；列表/详情/排行榜公开（PRD §B-P02：发现性内容匿名可看）
- 即时反馈需登录（看自己的成绩对比）
- 用户成绩接口路径是 /api/user/efforts，通过单独的 user_effort_router 挂载
- 不直接操作数据库，所有业务逻辑交给 service 层
"""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, get_optional_user
from app.segment import schemas, service
from app.segment.exceptions import SegmentOverlapError
from app.segment.models import Segment

# 创建路由器，所有赛段相关接口都挂在 /api/segments 下
router = APIRouter(prefix="/api/segments", tags=["segment"])
logger = logging.getLogger(__name__)


@router.post("", response_model=schemas.SegmentResponse, deprecated=True)
def create_segment(
    req: schemas.SegmentCreateRequest,
    response: Response,
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    [DEPRECATED 2026-05-05] 创建赛段——迁到 POST /api/admin/segments/from-gpx。

    管理员提交一组 GPS 坐标点（至少 2 个），
    后端自动计算距离、爬升，生成 PostGIS 赛段线条。
    普通用户调用会收到 403 错误。
    """
    # DEPRECATED: task-3.B.2 切完 segment-creator.html 后删除旧入口。
    logger.warning(
        "DEPRECATED endpoint POST /api/segments called by user_id=%s. "
        "Migrate to /api/admin/segments/from-gpx.",
        user_id,
    )
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = "Tue, 30 Jun 2026 00:00:00 GMT"

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
    except SegmentOverlapError as e:
        # task-3.A.6 修补副作用：service 加 Hausdorff 查重后老 endpoint 也要翻译 409
        # 否则 segment-creator.html 用户上传重复赛段会得 500（产品保护硬约束）
        raise HTTPException(status_code=409, detail=str(e))

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


# TODO(sunset 2026-11-03): 半年兼容期后删除旧路径，只保留 /api/admin/segments/{segment_id}。
# 旧路径不引入 app.admin.dependencies.require_admin，避免 segment -> admin 反向依赖。
# 权限由 service.delete_segment 内部兜底，普通用户 403 已由 tests/test_admin_router.py 覆盖。
@router.delete("/{segment_id}", status_code=204, deprecated=True)
def delete_segment(
    segment_id: int,
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    删除赛段——管理员专用（deprecated，保留给旧工具兼容）。

    新后台入口是 DELETE /api/admin/segments/{segment_id}。
    旧路径兼容至 2026-11-03，避免已有内部脚本突然 404。
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
    # v5 task-1.A.3 新增 3 筛选 Query：
    # search 模糊搜赛段名（≥ 2 字防 a/b 单字误触发全表扫）
    # city 是 7 枚举（6 主城 + unknown），用 pattern 严格校验防脏数据
    # difficulty 是 4 枚举，同理
    search: str | None = Query(None, min_length=2, max_length=64,
                               description="赛段名模糊搜索，≥ 2 字"),
    city: str | None = Query(
        None,
        pattern="^(beijing|shanghai|hangzhou|shenzhen|chengdu|taiyuan|unknown)$",
        description="城市枚举（PRD 6 主城 + unknown）",
    ),
    difficulty: str | None = Query(
        None,
        pattern="^(easy|medium|hard|extreme)$",
        description="难度枚举（4 档）",
    ),
    db: Session = Depends(get_db),
    # 第二轮双审 B1-B3 + Tim 2026-04-28 拍：保持公开，不加 get_current_user
):
    """
    查询赛段列表（分页 + 附近搜索 + v5 三筛选）。

    支持附近搜索：传入 near_lat + near_lon + radius（默认 50km，上限 500km），
    返回指定半径内的赛段。不传坐标则返回所有赛段。

    v5 三筛选叠加：search 模糊搜名 + city 精确等值 + difficulty 精确等值，
    都可同时传，service 层会一起 AND 到 SQL where。

    不需要登录——赛段目录对所有人公开（PRD §B-P02 发现性内容）。
    """
    # near_lat 和 near_lon 必须成对出现，只传一个没有意义
    if (near_lat is None) != (near_lon is None):
        raise HTTPException(status_code=400, detail="near_lat和near_lon必须同时提供")

    items, total = service.get_segment_list(
        db, page, page_size, near_lat, near_lon, radius,
        search=search, city=city, difficulty=difficulty,
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
    current_user_id: int | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """
    查看赛段详情 + 排行榜前 20 名。

    不需要登录——排行榜是公开的，任何人都能查看。

    登录用户额外效果（task-4.1）：能在 TOP20 中看到自己的私密成绩
    + is_private_self 标记；他人和未登录看不到任何人的私密成绩。
    """
    try:
        detail = service.get_segment_detail(db, segment_id, current_user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return detail


@router.get("/{segment_id}/leaderboard", response_model=schemas.LeaderboardResponse)
def get_leaderboard(
    segment_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    bike_type: str | None = Query(None),
    current_user_id: int | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """
    查看赛段完整排行榜（分页）。

    比详情接口的 TOP20 更完整：支持翻页查看所有成绩，
    还能按车型过滤（只看公路车、砾石车等）。
    不需要登录——排行榜公开（任何人能看 top）。

    Sprint 4 D7 hotfix：登录用户额外返 my_rank + my_elapsed_time，
    让前端在 top 10 外也能精确展示"我排第几"，不用 # 占位。
    用 get_optional_user 而不是 get_current_user：未登录不抛 401 / 走 None 分支。
    """
    try:
        items, total, my_rank, my_elapsed_time = service.get_leaderboard(
            db, segment_id, page, page_size, bike_type, current_user_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return schemas.LeaderboardResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        my_rank=my_rank,
        my_elapsed_time=my_elapsed_time,
    )


@router.get(
    "/{segment_id}/efforts/me",
    response_model=schemas.EffortCompareResponse,
)
def get_my_effort_compare(
    segment_id: int = Path(..., ge=1),
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    即时反馈——"骑完看进步"对比（v5 task-1.A.3 / spec §4.1）。

    用户骑完一段赛段，前端调这里拿对比数据：
    "这次 26 分钟、上次 28 分钟、PR 25 分钟"——给用户看进步。
    需要登录（看自己的）。

    路径 404 由本 router 显式查 segment 存在性（spec §3.2.1 + 第二轮双审 B1-B4：
    service 不抛 404，无 effort 时返"首次访问"6 字段兜底；router 负责 segment 存在校验）。
    """
    # 显式 404 校验：用 db.get(Segment, ...) 主键查询（SQLAlchemy 2.0 推荐）
    # 防 service 拿到无效 segment_id 仍返兜底，前端误以为"赛段存在但用户没骑过"
    seg = db.get(Segment, segment_id)
    if seg is None:
        raise HTTPException(status_code=404, detail="赛段不存在")

    return service.get_my_effort_with_compare(db, segment_id, user_id)


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

    需登录。本人始终可看；他人活动按 visibility 判定（public 可看 / private 返 404）。
    rank 计算自动排除他人私密 effort，与主排行榜一致。
    """
    try:
        items = service.get_activity_segments(db, activity_id, user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return schemas.ActivitySegmentsResponse(items=items)
