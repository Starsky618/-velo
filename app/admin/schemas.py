"""admin 模块请求/响应格式。"""

from datetime import datetime

from pydantic import BaseModel


class CurationPoolItem(BaseModel):
    """候选池列表的一行，给后台 H5 勾选精选赛段用。"""

    id: int
    segment_id: int
    segment_name: str
    segment_city: str
    segment_difficulty: str
    pool_score: float
    pool_reason: str | None = None
    selected_for_v5: bool
    selected_by_user_id: int | None = None
    selected_at: datetime | None = None


class CurationPoolListResponse(BaseModel):
    """候选池分页响应。"""

    items: list[CurationPoolItem]
    total: int
    selected_count: int


class CurationPoolPatchRequest(BaseModel):
    """候选池勾选请求。"""

    selected_for_v5: bool
