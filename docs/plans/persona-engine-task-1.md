# Persona Engine Task-1 — 模块脚手架 + 3 张 persona_* 表迁移

> 所属：Persona Engine Sprint / 6 task 中的第 1 个 / 地基层
> 上下文：2026-05-16 Tim 拍 / 宪法 § 7.4 模块结构 v0.1 / ADR-009 子工程位置
> **共用约束 / SOP / 双审 / 部署**：详见 `persona-engine-handoff.md`

---

## ─────── 给 Tim 看（你审这层就够）───────

### 干啥用

建好 NPC 文案系统的"空房子"——新建 `app/agent/persona/` 文件夹（暂时全空 / 等后续 task 填）+ 数据库新建 3 张 `persona_*` 表 + 写一份"资产清单"（MANIFEST.md / 让未来"想拔时知道拔哪些"）。

本 task 完成后 **velo 没有任何可见变化** —— 纯基础设施 / 用户感受不到。

### 用户故事

无（内部工程任务 / 没有用户场景）。

### 怎么算做对了

- ✓ `app/agent/persona/` 目录 + 5 个空骨架文件创建
- ✓ Alembic 迁移在 PG + SQLite 都能 upgrade + downgrade 干净跑通
- ✓ 3 张 `persona_*` 表 schema 正确 + 索引在
- ✓ `MANIFEST.md` v0.1 写好
- ✓ 不破坏既有任何 pytest
- ✗ 任何 NPC 文案逻辑 / 模板入库 / 业务接入泄漏到本 task = 是 bug（留 task-2~5）

### 这次**不做**的事

- 模板入库（task-2）
- 决策算法（task-3）
- 业务接入（task-4）
- 前端展示（task-5）

### 估时

0.5 天（含 Claude 双审 + Codex 异源审）

---

## ─────── 折叠：技术细节 ───────

<details>
<summary>展开</summary>

### 防火墙红线

参 `persona-engine-handoff.md` § 1 全部 5 条。本 task 重点：
- § 1.1 ADR-009 边界声明：`__init__.py` 顶部必含
- § 1.2 命名前缀：表名 / 迁移 / 测试文件全 `persona_*`
- § 1.3 数据隔离：3 张表独立 / FK 只能 reference users / activities / 不能修改它们
- § 1.5 MANIFEST 初版必写

### 起手必跑

参 handoff § 2.1 通用 grep。

### 目录结构

```
app/agent/persona/
├── __init__.py             # ADR-009 边界声明 + 宪法 reference
├── trigger_router.py       # 空骨架 docstring（task-3 填）
├── template_lib.py         # 空骨架 docstring（task-2 填）
├── filters.py              # 空骨架 docstring（task-3 填）
├── cache.py                # 空骨架 docstring（task-3 填）
├── service.py              # 空骨架 docstring（task-3 主入口）
└── MANIFEST.md             # 资产清单 v0.1
```

### `__init__.py` 模板（沿用 `app/agent/__init__.py` 风格）

```python
"""
NPC 文案系统子模块（Persona Engine / ADR-009 第 2 个 agent 子工程）。

干啥用：
- 给业务模块（worker / endpoint）调 generate_persona_output(event) 返 NPC 文案
- 输入参数 dict + DB session / 不反向 import 业务模块 service

操作注意（ADR-009 + 宪法 § 7.2 硬约束）：
- 本模块**不反向 import** 业务模块（user / activity / segment / notification 的 service 都禁）
- 只读 Activity / User ORM model + 写 persona_outputs / persona_feedback model
- agent 是叶子节点 —— 业务模块依赖它，不反过来
- 任何子模块抛 unhandled exception → service 顶层 catch / 返 None / 不传染调用方事务

数据流：
- 入：PersonaEvent dict / DB session
- 出：Optional[str]（46 条固定模板之一 / 或 None 表示该场景无文案）

参考：docs/agent-rules/persona-constitution.md（Persona 宪法 v0.1）
"""
```

### Alembic 迁移：`migrations/versions/persona_engine_init.py`

```python
"""persona_engine_init

Revision ID: persona_engine_init
Revises: <最新 head>  # 实施前 grep 验证
"""

from alembic import op
import sqlalchemy as sa

revision = "persona_engine_init"
down_revision = "sprint6_activity_city"  # v0.2 修 / 当前真 head（grep 实证）/ 实施前 ls migrations/versions/ 重新确认


def upgrade() -> None:
    # persona_outputs
    op.create_table(
        "persona_outputs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("scene_type", sa.String(32), nullable=False),
        sa.Column("template_id", sa.Integer, nullable=False),
        sa.Column("text_snapshot", sa.Text, nullable=False),  # v0.4 修 / Claude A+B 共识 C1 / 文案快照 / 避免 endpoint JOIN
        sa.Column("shown_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activity_id", sa.Integer, sa.ForeignKey("activities.id"), nullable=True),
    )
    op.create_index(
        "ix_persona_outputs_user_scene_shown", "persona_outputs",
        ["user_id", "scene_type", "shown_at"],
    )

    # persona_templates
    op.create_table(
        "persona_templates",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("scene_type", sa.String(32), nullable=False),
        sa.Column("segment", sa.String(32), nullable=True),
        sa.Column("template_text", sa.Text, nullable=False),
        sa.Column("weight", sa.Integer, server_default="1"),
        sa.Column("active", sa.Boolean, server_default=sa.text("true")),
    )
    op.create_index(
        "ix_persona_templates_scene_active", "persona_templates",
        ["scene_type", "active"],
    )

    # persona_feedback（v1.0+ 才用 / 本 Sprint 建表占位）
    op.create_table(
        "persona_feedback",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("output_id", sa.Integer, sa.ForeignKey("persona_outputs.id"), nullable=False),
        sa.Column("reaction", sa.String(16), nullable=False),  # 'like'/'dislike'/'dismiss'
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("persona_feedback")
    op.drop_index("ix_persona_templates_scene_active", "persona_templates")
    op.drop_table("persona_templates")
    op.drop_index("ix_persona_outputs_user_scene_shown", "persona_outputs")
    op.drop_table("persona_outputs")
```

### ORM 模型（`app/agent/models.py` 追加 / 不覆盖 SegmentAiDraft）

```python
class PersonaOutput(Base):
    __tablename__ = "persona_outputs"
    # 字段映射略

class PersonaTemplate(Base):
    __tablename__ = "persona_templates"

class PersonaFeedback(Base):
    __tablename__ = "persona_feedback"
```

### MANIFEST.md v0.1（按宪法 § 7.5.2 模板）

```markdown
# Persona Engine 资产清单 v0.1

> 强制规则：每加一处 persona 资产 → 必须更新本清单（PR review 红线）

## 后端代码
- app/agent/persona/ — 整目录
- app/agent/__init__.py — 子工程 reference（task-1 加）
- app/agent/models.py — PersonaOutput / PersonaTemplate / PersonaFeedback（task-1 加）

## 数据库
- migrations/versions/persona_engine_init.py
- 表：persona_outputs / persona_templates / persona_feedback

## 文档
- docs/agent-rules/persona-constitution.md
- docs/prd/persona-engine-sprint-prd.md
- docs/plans/persona-engine-task-1.md ~ task-6.md + handoff.md

## 前端
（task-5 后追加 PERSONA_START/END 标记位）

## 配置
- env: 暂无 PERSONA_* 配置（v0.5+ 接 LLM 时加）

## 拔出测试
- scripts/persona_pluck_dryrun.sh（task-6 实施）
```

### 测试要求（`tests/test_persona_module_init.py` 新建）

最少 4 条 pytest：

1. `from app.agent.persona import trigger_router, template_lib, filters, cache, service` → 全 import 成功
2. `__init__.py` docstring 含 "ADR-009" + "宪法" 关键字 → 防未来删边界声明
3. Alembic upgrade head → 3 表存在 / 索引存在（PG + SQLite 都测）
4. Alembic downgrade -1 → 3 表全没

**不破坏**：既有 user / activity / segment / agent / strava pytest 全过。

### 双审 focus

参 handoff § 2.3 + § 2.4 通用 reviewer prompt。本 task **重点扫**：
- ADR-009 边界声明是否真在 `__init__.py` 顶部
- 命名前缀 100% 守住（3 表名 + 迁移文件名 + 测试文件名）
- MANIFEST v0.1 齐全
- migration head 链不断

### 依赖

- 依赖：无（地基 / 可和 Sprint 6 并跑）
- 阻塞：task-2 / task-3 / task-4 全等本 task

### 部署 verify（按 handoff § 2.2 5 步 + 本 task 特有）

```bash
docker compose exec api python -c "from app.agent.persona import service; print('OK')"
docker compose exec api alembic current  # 应显示 persona_engine_init
docker compose exec db psql -U postgres -c "\d persona_outputs"
docker compose exec db psql -U postgres -c "\d persona_templates"
docker compose exec db psql -U postgres -c "\d persona_feedback"
```

</details>
