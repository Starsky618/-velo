"""
NPC 文案 endpoint（Persona Engine task-4）。

干啥用：
- GET /api/persona/output：前端按场景拿当前 NPC 文案（profile 打开 / 详情页打开 / 上传完）
- GET /api/persona/recent：前端拿用户最近 N 条 NPC 历史

类比：前端按"老登在不在 / 说啥了"问后端 / 后端从 persona_outputs 台账查最新一条返。

操作注意（宪法 § 7.2 失败隔离）：
- service 内部失败 → service 顶层 catch 返 None / endpoint 返 200 + template_text=null
- **绝不返 5xx 让前端崩**（用户看不到 NPC 文案是降级体验 / 看到 5xx 是灾难）

接口契约：
- /output：GET ?scene_type=X [&activity_id=Y] [&target_user_id=Z]
  - target_user_id 默认 None = 看自己 / 不为 None = 看他人 NPC 输出（user_page_open 场景）
  - 返 {"template_text": str|null, "scene_type": str, "created_at": datetime|null}
- /recent：GET ?limit=10 → {"items": [{...}, ...]}
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.agent.persona import service as persona_service


router = APIRouter(prefix="/api/persona", tags=["persona"])


# ─── Pydantic 响应 schema ───


class PersonaOutputResponse(BaseModel):
    """单条 NPC 文案响应 / endpoint /output 用。

    字段映射注意（handoff § 0 残留 Important）：
    - template_text 不是 ORM 字段名 / 是手工从 ORM.text_snapshot 映射
    - 这里不用 from_attributes / endpoint 手工构造 dict 避免字段名歧义
    """
    template_text: Optional[str] = None
    scene_type: str
    created_at: Optional[datetime] = None


class PersonaOutputItem(BaseModel):
    """单条 NPC 历史 item / endpoint /recent 用 / 字段名对齐 ORM 让 from_attributes 自动映射。"""
    model_config = ConfigDict(from_attributes=True)

    text_snapshot: str
    scene_type: str
    activity_id: Optional[int] = None
    shown_at: datetime


class PersonaRecentResponse(BaseModel):
    """NPC 历史列表响应。"""
    items: list[PersonaOutputItem]


# ─── Endpoint 实现 ───


@router.get("/output", response_model=PersonaOutputResponse)
def get_persona_output(
    scene_type: str = Query(..., pattern="^[a-z_]+$"),
    activity_id: Optional[int] = Query(None),
    target_user_id: Optional[int] = Query(None),
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PersonaOutputResponse:
    """前端按 scene_type [+ activity_id] [+ target_user_id] 拿 NPC 文案。

    场景：
    - target_user_id=None → 看自己 NPC 输出（profile_open / activity 详情 / upload 完）
    - target_user_id != None → 看他人 NPC 输出（user_page_open 看他人 profile）
    - activity_id 用于详情页精准拿当前活动的 NPC / 防串到别 activity
    - scene_type 含前端语义（profile_open / user_page_open / activity_upload）走 service 退化逻辑

    永不返 5xx / 任何失败 → 200 + template_text=null（宪法 §7.2 不传染失败）。
    """
    query_user_id = target_user_id if target_user_id is not None else user_id
    output = persona_service.get_latest_output_for_scene(
        db, query_user_id, scene_type, activity_id=activity_id,
    )
    return PersonaOutputResponse(
        template_text=output.text_snapshot if output else None,
        scene_type=scene_type,
        created_at=output.shown_at if output else None,
    )


@router.get("/recent", response_model=PersonaRecentResponse)
def get_recent_outputs_endpoint(
    limit: int = Query(10, ge=1, le=50),
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PersonaRecentResponse:
    """拿用户最近 N 条 NPC 文案历史（倒序 / 默认 10 条 / 上限 50）。

    给"我的 NPC 历史"展示页用 / 失败返空 items 不报错。
    """
    outputs = persona_service.get_recent_outputs(db, user_id, limit)
    return PersonaRecentResponse(items=outputs)
