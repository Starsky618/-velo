"""admin 模块请求/响应格式。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

AiDraftStatus = Literal["pending", "human_edited", "approved", "rejected"]


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


class AiDraftResponse(BaseModel):
    """AI 草稿审核列表的一行，给后台 H5 审稿台使用。"""

    id: int
    segment_id: int
    segment_name: str
    ai_draft_text: str
    human_edited_text: str | None = None
    status: AiDraftStatus
    editor_user_id: int | None = None
    updated_at: datetime


class AiDraftListResponse(BaseModel):
    """AI 草稿审核分页响应。"""

    items: list[AiDraftResponse]
    total: int


class AiDraftPatchRequest(BaseModel):
    """AI 草稿编辑请求。"""

    human_edited_text: str | None = None
    status: AiDraftStatus | None = None
