"""
AI 草稿 RQ 异步任务入口（v5 task-1.B.1 / 5.B.2）。

干啥用：
- admin 触发 AI 草稿生成的统一入口（POST /admin/segments/{id}/ai-drafts +
  PATCH /admin/curation-pool/{id} selected=true 两条路径都 enqueue 这个 task）
- 调 segment_writer.generate_segment_draft 拿 50-100 字草稿
- UPSERT segment_ai_drafts（segment_id UNIQUE / pending 状态才覆盖 / 不覆盖人工编辑）

操作注意（关键设计决策）：
- **禁止 admin 同步调用 generate_segment_draft**——LLM 单次 3-8s 会阻塞 endpoint
  必须走 ai_drafts_queue.enqueue 走 RQ worker 异步路径
- **幂等保证**：UPSERT by segment_id UNIQUE + IntegrityError 兜底
  并发 worker 同时跑同一 segment_id → 第二个 catch IntegrityError 跳过不抛
- **状态机保护**：已存在 + status='pending' 才覆盖；human_edited / approved / rejected
  都不动（防 admin 编辑被覆盖丢失）
- **失败不抛**：generate 返空字符串 → skip UPSERT + warn，不阻塞 RQ task 退出
  RQ 重试 2 次浪费 DeepSeek 配额，admin 后台手动重发更可控

数据流：
- 入：segment_id（int / RQ enqueue 通过 ai_drafts_queue 派发）
- 中：DB session → 查 Segment props → 调 segment_writer → 拿 ai_text → UPSERT
- 出：副作用写 segment_ai_drafts 一行（成功）/ 无副作用（失败/skip）
"""

import logging

from sqlalchemy.exc import IntegrityError

from app.agent.segment_writer import generate_segment_draft
from app.database import SessionLocal
from app.segment.models import Segment, SegmentAiDraft
from app.user.models import User  # noqa: F401  worker 进程必须 import User 让 SQLAlchemy 注册 users 表 mapper / 否则 segment_ai_drafts.editor_user_id FK 解析时炸 NoReferencedTableError


logger = logging.getLogger(__name__)


def generate_segment_draft_task(segment_id: int) -> None:
    """
    RQ async task：给指定 segment 生成 AI 草稿并 UPSERT segment_ai_drafts。

    设计思路：
    - 同步函数（RQ worker 在自己进程调）/ 不 raise 异常给 RQ
    - 强制检查清单 #2 幂等：UPSERT + IntegrityError 兜底，并发 worker 安全
    - 强制检查清单 #1 进程被 kill：DB session 用 try/finally 保证 close

    参数：
        segment_id: int / Segment 主键

    返回：
        None / 副作用写 segment_ai_drafts 表

    异常路径（全部内部消化不抛）：
        - segment_id 不存在 → logger.error + return
        - generate 返空字符串 → logger.warning + return
        - 已有 draft 但 status != 'pending' → logger.info + return
        - DB IntegrityError（并发冲突）→ rollback + logger.warning + return
    """
    db = SessionLocal()
    try:
        # 第 1 步：查 Segment / 不存在直接 skip
        # 用 .first() 不用 .one()（陷阱 #4：one 抛 NoResultFound 会被 RQ 当 task 失败重试）
        seg = db.query(Segment).filter(Segment.id == segment_id).first()
        if seg is None:
            logger.error(
                f"generate_segment_draft_task: segment_id={segment_id} 不存在，skip"
            )
            return

        # 第 2 步：组装 prompt 参数
        # 兜底用 '未知' / 0 防 truthiness 陷阱（陷阱 #1）
        # —— city 可能 NULL（虽然 NOT NULL 默认 'unknown'，但模型可能未来允许 NULL）
        # —— elevation_gain / max_gradient 可能 NULL（max_gradient 字段本就 nullable）
        segment_props = {
            "name": seg.name,
            "city": seg.city or "未知",
            "distance_km": round((seg.distance or 0) / 1000, 1),
            "elevation_gain_m": int(seg.elevation_gain or 0),
            "max_gradient_pct": round(seg.max_gradient or 0, 1),
            "difficulty": seg.difficulty or "未知",
        }

        # 第 3 步：调 LLM
        # 失败 / 空 / 无 key 都返空字符串（segment_writer 内部已兜底所有异常）
        ai_text = generate_segment_draft(segment_props)
        if not ai_text:
            logger.warning(
                f"AI 返回空草稿，segment_id={segment_id}，跳过 UPSERT"
            )
            return

        # 第 4 步：UPSERT
        # 已存在 → 仅 status='pending' 覆盖（不破坏 human_edited / approved / rejected）
        # 不存在 → 新建 status='pending'
        # 类比：草稿盒里如果已经有审稿过的稿件，AI 不能擅自覆盖
        existing = (
            db.query(SegmentAiDraft)
            .filter(SegmentAiDraft.segment_id == segment_id)
            .first()
        )
        if existing is not None:
            if existing.status == "pending":
                existing.ai_draft_text = ai_text
            else:
                logger.info(
                    f"draft segment_id={segment_id} status={existing.status}，跳过覆盖"
                )
                return
        else:
            draft = SegmentAiDraft(
                segment_id=segment_id,
                ai_draft_text=ai_text,
                status="pending",
            )
            db.add(draft)

        # 第 5 步：commit / 并发冲突兜底
        # IntegrityError 场景：另一 worker 已抢先插入同 segment_id
        # （UNIQUE constraint 触发）→ rollback + warn 不抛，让本 worker 优雅退出
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            logger.warning(
                f"draft segment_id={segment_id} 并发插入冲突（UNIQUE），跳过"
            )
    finally:
        # 强制检查清单 #1：进程被 kill 也保证 DB session close
        # 不写在 try 里避免 except 路径漏 close
        db.close()
