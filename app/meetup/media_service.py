"""
约骑媒体业务逻辑——处理封面图、视频和 storage 清理。

操作注意事项：数据库记录是相册里是否存在这张图的唯一依据；storage 只负责存/删文件，不能反过来决定业务状态。
输入/输出数据流：router 传入上传文件字节和当前用户，service 写 meetup_media，再调用 storage，最后返回媒体 ORM 行。
"""

import html
import logging

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.meetup.models import MeetupMedia
from app.meetup.service import _load_and_authorize_meetup
from app.storage.local import LocalStorage


logger = logging.getLogger(__name__)
_storage = LocalStorage()

_MEDIA_RULES = {
    "image/jpeg": ("image", 5 * 1024 * 1024, ".jpg"),
    "image/png": ("image", 5 * 1024 * 1024, ".png"),
    "image/webp": ("image", 5 * 1024 * 1024, ".webp"),
    "video/mp4": ("video", 50 * 1024 * 1024, ".mp4"),
}


def upload_meetup_media(
    db: Session,
    meetup_id: int,
    current_user_id: int,
    filename: str,
    content_type: str,
    file_bytes: bytes,
    caption: str | None,
) -> MeetupMedia:
    meetup = _load_and_authorize_meetup(db, meetup_id, current_user_id, require_creator=True)
    if content_type not in _MEDIA_RULES:
        raise HTTPException(status_code=415, detail="unsupported media type")
    media_type, max_size, ext = _MEDIA_RULES[content_type]
    if len(file_bytes) > max_size:
        raise HTTPException(status_code=413, detail="media too large")

    safe_caption = html.escape(caption) if caption else None
    if safe_caption is not None and len(safe_caption) > 128:
        raise HTTPException(status_code=422, detail="caption too long")
    # 序号取"现存最大序号 + 1"，不能用 count()：删掉中间某张后行数会和现存序号撞车
    # （例如 seq=0,1,2 删 1 后 count()=2，与现存 seq=2 重复），导致排序错乱、换封面失效。
    max_seq = db.query(func.max(MeetupMedia.seq)).filter(MeetupMedia.meetup_id == meetup.id).scalar()
    next_seq = (max_seq + 1) if max_seq is not None else 0
    media = MeetupMedia(
        meetup_id=meetup.id,
        uploader_id=current_user_id,
        type=media_type,
        file_id="pending",
        caption=safe_caption,
        seq=next_seq,
    )
    db.add(media)
    db.flush()

    try:
        file_id = _storage.upload(file_bytes, f"meetup-{meetup.id}-media-{media.id}{ext}")
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="media upload failed")

    media.file_id = file_id
    db.commit()
    db.refresh(media)
    return media


def delete_meetup_media(db: Session, meetup_id: int, media_id: int, current_user_id: int) -> None:
    media = db.query(MeetupMedia).filter(MeetupMedia.id == media_id).first()
    if media is None or media.meetup_id != meetup_id:
        raise HTTPException(status_code=404, detail="media not found")

    meetup = _load_and_authorize_meetup(db, meetup_id, current_user_id)
    if media.uploader_id != current_user_id and meetup.creator_id != current_user_id:
        raise HTTPException(status_code=403, detail="not allowed")

    file_id = media.file_id
    db.delete(media)
    db.commit()
    try:
        _storage.delete(file_id)
    except Exception:
        logger.warning("meetup media storage delete failed file_id=%s", file_id, exc_info=True)
