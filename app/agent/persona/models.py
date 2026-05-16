"""
Persona Engine ORM 模型——"NPC 文案系统的 3 本台账"。

三张表（持久层 / Alembic 迁移 persona_engine_init.py 建表）：
1. persona_outputs（文案发送台账）：NPC 给哪个用户说了什么场景的什么话 / 何时说的
2. persona_templates（模板池）：46+ 条精金模板候选 / 按场景分类 / 可启用禁用
3. persona_feedback（用户反馈占位）：用户对 NPC 文案的反应（like / dislike / dismiss）/
   v1.0+ 才真用 / 本 Sprint 仅建表占位

类比：小区物业的"老登发言记录簿"：
- persona_outputs = 流水账：哪天哪个住户被老登 cue 了一句什么
- persona_templates = 老登的"金句库"：50 句备选 / 用哪句看场合
- persona_feedback = "住户对老登态度记录"：以后住户可能投票哪句话最戳

注意事项（ADR-009 + 宪法 § 7 防火墙 / 违反 = REJECT）：
- 本文件 import `app.database.Base` / 不反向 import 业务 service
- FK 只 reference users.id / activities.id / 不修改它们
- text_snapshot 字段（v0.4 修 / Claude A+B 共识 C1）：写入时同时存模板渲染后的完整文案，
  避免 endpoint 查询时再 JOIN persona_templates（防 N+1 + 防模板未来改字段污染历史记录）
- timezone=True 必须（CLAUDE.md 陷阱 #2 / 防 naive vs aware 比较 TypeError）
"""

from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime,
    ForeignKey, Index, text,
)

from app.database import Base


class PersonaOutput(Base):
    """
    NPC 文案发送台账——"老登给谁说了什么话的流水记录"。

    每条记录 = 一次 NPC 文案展示。endpoint 按 (user_id, scene_type, shown_at)
    联合索引快速查"该用户最近这个场景的最新 NPC 文案"。

    幂等保护：去重逻辑在 service 层（cache.py），表层不加 UNIQUE
    （允许同用户同场景多次记录 / 时间窗内由 cache 控制不渲染重复）。
    """

    __tablename__ = "persona_outputs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
    )
    # 场景类型（PR / 普通骑行 / 连骑 / 沉寂 / 极端数据 / 空状态 / 跨时间镜像 等 7 大类）
    scene_type = Column(String(32), nullable=False)
    # 渲染时选中的模板 id（不加 FK 让模板表可独立增删 / 不污染历史台账）
    template_id = Column(Integer, nullable=False)
    # 文案快照（v0.4 修 C1）：模板渲染后的完整字符串
    # 写入时 freeze / 未来即使模板改了或删了 / 历史台账仍可读
    text_snapshot = Column(Text, nullable=False)
    # 文案展示给用户的时间（tz-aware / 防 naive 比较踩坑）
    shown_at = Column(
        DateTime(timezone=True), nullable=False,
    )
    # 关联骑行活动（可选 / 空状态 / 跨时间镜像场景可能无 activity）
    # ondelete="SET NULL"：activity 被删（用户删 / Strava webhook 删）时
    # 历史台账保留 + activity_id 置 NULL（防 PG NO ACTION 让删活动 500 / Codex C1）
    activity_id = Column(
        Integer,
        ForeignKey("activities.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        # endpoint 查询主索引：按 (user, scene) 倒序 shown_at 拿最新
        Index(
            "ix_persona_outputs_user_scene_shown",
            "user_id", "scene_type", "shown_at",
        ),
    )


class PersonaTemplate(Base):
    """
    NPC 模板池——"老登的金句库"。

    46+ 条精金文案候选 / 按场景分类 / 副线 cycle 扩到 158 条。
    weight 控制同场景内候选权重 / active 控制启用 / 禁用（Tim 临时下线某条不删表）。
    """

    __tablename__ = "persona_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # 场景大类（与 PersonaOutput.scene_type 同一枚举）
    scene_type = Column(String(32), nullable=False)
    # 场景细分段位（萌新 / 入门 / 进阶 / 老登 / NULL=不限）
    segment = Column(String(32), nullable=True)
    # 模板原文（含 {distance} / {pr_delta} / {city} 等占位符）
    template_text = Column(Text, nullable=False)
    # 选模板权重（同场景同 segment 内按 weight 加权随机 / 默认 1）
    weight = Column(Integer, server_default=text("1"))
    # 启用开关（Tim 临时下线某条 = active=false / 不删表）
    active = Column(Boolean, server_default=text("true"))

    __table_args__ = (
        # 选模板主索引：按 (scene, active) 过滤候选池
        Index(
            "ix_persona_templates_scene_active",
            "scene_type", "active",
        ),
    )


class PersonaFeedback(Base):
    """
    NPC 文案反馈占位——"住户对老登发言的态度记录"。

    v1.0+ 才真用（v0.1 Sprint 仅建表占位 / 不暴露 endpoint）。
    未来用于：用户长按某句 NPC 文案 → like / dislike / dismiss → 反哺模板权重。
    """

    __tablename__ = "persona_feedback"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
    )
    output_id = Column(
        Integer,
        ForeignKey("persona_outputs.id"),
        nullable=False,
    )
    # 反应类型：'like' / 'dislike' / 'dismiss'（应用层枚举 / 表层不加 CHECK 防未来扩枚举锁死）
    reaction = Column(String(16), nullable=False)
    created_at = Column(
        DateTime(timezone=True), nullable=False,
    )
