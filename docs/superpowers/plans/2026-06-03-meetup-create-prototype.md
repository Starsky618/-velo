# 发起约骑新原型 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **唯一真相源:** `docs/superpowers/specs/2026-06-03-meetup-create-prototype-design.md`。字段名、接口、校验规则、错误码以它为准；本文件只把实施拆成 TDD 步骤，不改产品方向。

**Goal:** 把两张已过三审的发起约骑原型接到真实前后端：新增 6 个 `meetups` 字段、发布前总览、草稿恢复、私圈口令、骑友列表接口和发布过期拦截。

**Architecture:** 后端只扩 `meetups` 这张约骑自己的表，不碰 `users` / `activities` / `segments` 核心表。私圈约骑不靠“藏在列表外”假装安全，而是靠后端生成的 `share_token` 口令；公开列表只看 `public`，发起人自己的草稿和历史不被过滤。前端不新增聚合接口，图二总览由草稿表单、路书 `preview_points`、骑友列表接口和本地常量组装。

**Tech Stack:** FastAPI 同步路由 + SQLAlchemy 2.0 + Alembic + PostgreSQL/PostGIS + pytest + 微信小程序静态合同测试。

---

## 读前证据

- [✓ grep] 现有 `meetups` 表还没有 6 个新字段；字段集中在 `app/meetup/models.py:33-52`，CHECK 写法在 `app/meetup/models.py:62-85`。
- [✓ grep] `MeetupCreateRequest` / `MeetupPatchRequest` / `MeetupResponse` 现在只覆盖旧字段，且 `extra="forbid"`；见 `app/meetup/schemas.py:19-78`。
- [✓ grep] `publish_meetup` 现在只查 creator + DRAFT，没有传 `check_time_cutoff=True`；见 `app/meetup/service.py:219-233`。
- [✓ grep] `update_meetup` 现在只循环 6 个旧字段，新字段会被静默丢弃；见 `app/meetup/service.py:204-209`。
- [✓ grep] 公开列表从 `base = db.query(Meetup)` 起步，尚未过滤 `visibility`；见 `app/meetup/service.py:310-335`。
- [✓ grep] 详情和 join 路由现在不接 `token`；见 `app/meetup/router.py:152-160`、`app/meetup/router.py:207-210`。
- [✓ grep] 小程序创建页 `onLoad` 只初始化时间和路线，不恢复草稿；见 `miniprogram/pages/meetup-create/meetup-create.js:140-143`。
- [✓ grep] api helper 真名是 `getMyMeetupDraft`；见 `miniprogram/utils/api.js:375-377`。

---

## Task 1: 数据层加 6 列

**用户会经历什么:** 陈哥填“补给点 / 适合谁 / 可见范围 / 报名门槛 / 安全提示”后，这些内容不再只是前端临时状态，退出再回来也不会丢；私圈链接的口令也有地方存。

**Files:**
- Modify: `app/meetup/models.py`
- Create: `migrations/versions/20260603_meetup_create_prototype_fields.py`
- Modify: `tests/conftest.py`
- Test: `tests/test_meetup_api.py`

- [ ] **Step 1: 写红灯测试，证明模型列和 SQLite 测试表还没同步**

Add to `tests/test_meetup_api.py`:

```python
from sqlalchemy import text


def test_meetup_create_prototype_columns_are_declared_in_model_and_test_table(db):
    expected = {
        "supply_point",
        "audience_tags",
        "visibility",
        "eligibility_note",
        "safety_note",
        "share_token",
    }

    model_columns = set(Meetup.__table__.columns.keys())
    sqlite_columns = {row[1] for row in db.execute(text("PRAGMA table_info(meetups)")).fetchall()}

    assert expected <= model_columns
    assert expected <= sqlite_columns
```

- [ ] **Step 2: 跑红灯**

Run:

```bash
pytest tests/test_meetup_api.py::test_meetup_create_prototype_columns_are_declared_in_model_and_test_table -q
```

Expected:

```text
FAILED tests/test_meetup_api.py::test_meetup_create_prototype_columns_are_declared_in_model_and_test_table
AssertionError
```

The failure is correct because the 6 columns do not exist yet.

- [ ] **Step 3: 写最小数据层实现**

Patch `app/meetup/models.py`:

```python
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    text,
)
```

Add these columns after `description`:

```python
    supply_point = Column(String(128), nullable=True)
    audience_tags = Column(JSON, nullable=False, server_default=text("'[]'"))
    visibility = Column(String(16), nullable=False, server_default="public")
    eligibility_note = Column(String(100), nullable=True)
    safety_note = Column(String(200), nullable=True)
    share_token = Column(String(43), nullable=True)
```

Add this CHECK in `__table_args__` next to the other enum checks:

```python
        CheckConstraint(
            "visibility IN ('public', 'invite_only')",
            name="ck_meetups_visibility",
        ),
```

Create `migrations/versions/20260603_meetup_create_prototype_fields.py`:

```python
"""Add meetup create prototype fields.

Revision ID: 20260603_meetup_create_fields
Revises: 20260602_tencent_route_book
Create Date: 2026-06-03
"""

from alembic import op
import sqlalchemy as sa


revision = "20260603_meetup_create_fields"
down_revision = "20260602_tencent_route_book"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """给发起约骑新原型补上可持久化的组织者字段。"""
    op.add_column("meetups", sa.Column("supply_point", sa.String(length=128), nullable=True))
    op.add_column(
        "meetups",
        sa.Column("audience_tags", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    op.add_column(
        "meetups",
        sa.Column("visibility", sa.String(length=16), nullable=False, server_default="public"),
    )
    op.add_column("meetups", sa.Column("eligibility_note", sa.String(length=100), nullable=True))
    op.add_column("meetups", sa.Column("safety_note", sa.String(length=200), nullable=True))
    op.add_column("meetups", sa.Column("share_token", sa.String(length=43), nullable=True))
    op.create_check_constraint(
        "ck_meetups_visibility",
        "meetups",
        "visibility IN ('public', 'invite_only')",
    )


def downgrade() -> None:
    """回滚发起约骑新原型字段。"""
    op.drop_constraint("ck_meetups_visibility", "meetups", type_="check")
    op.drop_column("meetups", "share_token")
    op.drop_column("meetups", "safety_note")
    op.drop_column("meetups", "eligibility_note")
    op.drop_column("meetups", "visibility")
    op.drop_column("meetups", "audience_tags")
    op.drop_column("meetups", "supply_point")
```

Patch `_meetups_table` in `tests/conftest.py` after `description`:

```python
    Column("supply_point", String(128)),
    Column("audience_tags", JSON, nullable=False, default=list),
    Column("visibility", String(16), nullable=False, default="public"),
    Column("eligibility_note", String(100)),
    Column("safety_note", String(200)),
    Column("share_token", String(43)),
```

- [ ] **Step 4: 跑绿灯**

Run:

```bash
pytest tests/test_meetup_api.py::test_meetup_create_prototype_columns_are_declared_in_model_and_test_table -q
```

Expected:

```text
1 passed
```

- [ ] **Step 5: 跑本 task 回归**

Run:

```bash
pytest tests/test_meetup_api.py -q
```

Expected:

```text
... passed
```

- [ ] **Step 6: commit**

```bash
git add app/meetup/models.py migrations/versions/20260603_meetup_create_prototype_fields.py tests/conftest.py tests/test_meetup_api.py
git commit -m "feat(meetup): task1 add create prototype fields"
```

---

## Task 2: schema 和 service 接住新字段

**用户会经历什么:** 陈哥保存或修改草稿时，新字段会真的来回保存；他作为发起人能拿到私圈分享口令，别人看同一张卡片时拿不到这个口令。

**Files:**
- Modify: `app/meetup/schemas.py`
- Modify: `app/meetup/service.py`
- Modify: `app/meetup/router.py`
- Test: `tests/test_meetup_api.py`

- [ ] **Step 1: 写红灯测试，覆盖 create / patch / list / forbid**

Add to `tests/test_meetup_api.py`:

```python
def test_create_returns_social_fields_and_creator_only_share_token(client, db, auth_header):
    segment = _segment(db)
    payload = _payload(segment.id)
    payload.update({
        "supply_point": "天龙山景区口",
        "audience_tags": ["climb_steady", "female_friendly", "climb_steady"],
        "visibility": "public",
        "eligibility_note": "报名需有 5 次骑行记录",
        "safety_note": "头盔必戴 · 遵守交规 · 量力而行",
    })

    create_res = client.post("/api/meetups", json=payload, headers=auth_header)

    assert create_res.status_code == 200
    body = create_res.json()
    assert body["supply_point"] == "天龙山景区口"
    assert body["audience_tags"] == ["climb_steady", "female_friendly"]
    assert body["visibility"] == "public"
    assert body["eligibility_note"] == "报名需有 5 次骑行记录"
    assert body["safety_note"] == "头盔必戴 · 遵守交规 · 量力而行"
    assert isinstance(body["share_token"], str)
    assert len(body["share_token"]) >= 32

    other_header = _auth_header_for(db, "social-fields-other")
    detail_res = client.get(f"/api/meetups/{body['id']}", headers=other_header)
    assert detail_res.status_code == 200
    assert detail_res.json()["share_token"] is None


def test_patch_updates_social_fields_instead_of_silently_dropping_them(client, db, auth_header):
    segment = _segment(db)
    meetup_id = client.post("/api/meetups", json=_payload(segment.id), headers=auth_header).json()["id"]

    patch_res = client.patch(
        f"/api/meetups/{meetup_id}",
        json={
            "supply_point": "晋祠补水",
            "audience_tags": ["photography"],
            "visibility": "invite_only",
            "eligibility_note": "能稳定骑完 60km",
            "safety_note": "山路多弯 · 控制下坡车速 · 保持车距",
        },
        headers=auth_header,
    )

    assert patch_res.status_code == 200
    body = patch_res.json()
    assert body["supply_point"] == "晋祠补水"
    assert body["audience_tags"] == ["photography"]
    assert body["visibility"] == "invite_only"
    assert body["eligibility_note"] == "能稳定骑完 60km"
    assert body["safety_note"] == "山路多弯 · 控制下坡车速 · 保持车距"


def test_public_list_hides_invite_only_but_mine_keeps_owner_items(client, db, auth_header):
    seg_public = _segment(db)
    public_id = client.post("/api/meetups", json=_payload(seg_public.id), headers=auth_header).json()["id"]
    client.post(f"/api/meetups/{public_id}/publish", headers=auth_header)

    seg_private = _segment(db)
    private_payload = _payload(seg_private.id)
    private_payload["visibility"] = "invite_only"
    private_id = client.post("/api/meetups", json=private_payload, headers=auth_header).json()["id"]
    client.post(f"/api/meetups/{private_id}/publish", headers=auth_header)

    public_list = client.get("/api/meetups?status=OPEN")
    mine = client.get("/api/meetups/mine?role=created", headers=auth_header)

    public_ids = [item["id"] for item in public_list.json()["items"]]
    mine_ids = [item["id"] for item in mine.json()["items"]]
    assert public_id in public_ids
    assert private_id not in public_ids
    assert public_id in mine_ids
    assert private_id in mine_ids


def test_social_field_validation_and_share_token_forbid(client, db, auth_header):
    segment = _segment(db)
    bad_tag = _payload(segment.id)
    bad_tag["audience_tags"] = ["not_a_real_tag"]
    assert client.post("/api/meetups", json=bad_tag, headers=auth_header).status_code == 422

    too_long = _payload(segment.id)
    too_long["safety_note"] = "x" * 201
    assert client.post("/api/meetups", json=too_long, headers=auth_header).status_code == 422

    meetup_id = client.post("/api/meetups", json=_payload(segment.id), headers=auth_header).json()["id"]
    forbidden = client.patch(
        f"/api/meetups/{meetup_id}",
        json={"share_token": "frontend-must-not-send-this"},
        headers=auth_header,
    )
    assert forbidden.status_code == 422

    bad_patch_tag = client.patch(
        f"/api/meetups/{meetup_id}",
        json={"audience_tags": ["not_a_real_tag"]},
        headers=auth_header,
    )
    assert bad_patch_tag.status_code == 422
```

- [ ] **Step 2: 跑红灯**

Run:

```bash
pytest tests/test_meetup_api.py::test_create_returns_social_fields_and_creator_only_share_token tests/test_meetup_api.py::test_patch_updates_social_fields_instead_of_silently_dropping_them tests/test_meetup_api.py::test_public_list_hides_invite_only_but_mine_keeps_owner_items tests/test_meetup_api.py::test_social_field_validation_and_share_token_forbid -q
```

Expected:

```text
FAILED ... response field missing / extra_forbidden / KeyError
```

The failure is correct because schemas and service do not yet know these fields.

- [ ] **Step 3: 写 schema 最小实现**

Patch `app/meetup/schemas.py`:

```python
from pydantic import BaseModel, ConfigDict, Field, field_validator
```

Add below `PaceLevel`:

```python
MeetupVisibility = Literal["public", "invite_only"]
AUDIENCE_TAG_VALUES = {
    "climb_steady",
    "high_intensity",
    "leisure",
    "photography",
    "female_friendly",
    "newbie_caution",
}


def _validate_audience_tags(value: list[str]) -> list[str]:
    """去重 + 白名单校验。create / patch 两个校验器共用一个模块级纯函数——
    不要在 patch 里直接调被 @field_validator 装饰过的方法（Pydantic v2 下那样调不稳）。"""
    deduped: list[str] = []
    for tag in value:
        if tag not in AUDIENCE_TAG_VALUES:
            raise ValueError("audience_tags 包含非法标签")
        if tag not in deduped:
            deduped.append(tag)
    if len(deduped) > 6:
        raise ValueError("audience_tags 最多 6 个")
    return deduped
```

Add this mixin before `MeetupCreateRequest`:

```python
class MeetupSocialFields(BaseModel):
    """发起约骑新原型里，组织者可以自己填写的展示字段。"""

    supply_point: str | None = Field(None, max_length=128)
    audience_tags: list[str] = Field(default_factory=list)
    visibility: MeetupVisibility = "public"
    eligibility_note: str | None = Field(None, max_length=100)
    safety_note: str | None = Field(None, max_length=200)

    @field_validator("audience_tags")
    @classmethod
    def validate_audience_tags(cls, value: list[str]) -> list[str]:
        return _validate_audience_tags(value)
```

Change class declarations:

```python
class MeetupCreateRequest(MeetupSocialFields):
```

```python
class MeetupPatchRequest(BaseModel):
```

Add to `MeetupPatchRequest`:

```python
    supply_point: str | None = Field(None, max_length=128)
    audience_tags: list[str] | None = None
    visibility: MeetupVisibility | None = None
    eligibility_note: str | None = Field(None, max_length=100)
    safety_note: str | None = Field(None, max_length=200)

    @field_validator("audience_tags")
    @classmethod
    def validate_patch_audience_tags(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        return _validate_audience_tags(value)
```

Add to `MeetupResponse`:

```python
    supply_point: str | None = None
    audience_tags: list[str] = Field(default_factory=list)
    visibility: MeetupVisibility = "public"
    eligibility_note: str | None = None
    safety_note: str | None = None
    share_token: str | None = None
```

- [ ] **Step 4: 写 service / router 最小实现**

Patch `app/meetup/service.py`:

```python
import secrets
```

Extend `create_meetup` signature:

```python
    description: str | None,
    supply_point: str | None = None,
    audience_tags: list[str] | None = None,
    visibility: str = "public",
    eligibility_note: str | None = None,
    safety_note: str | None = None,
```

Add fields inside `Meetup(...)`:

```python
        supply_point=supply_point,
        audience_tags=audience_tags or [],
        visibility=visibility,
        eligibility_note=eligibility_note,
        safety_note=safety_note,
        share_token=secrets.token_urlsafe(32),
```

Replace the hard-coded update loop with:

```python
    editable_fields = (
        "start_time",
        "estimated_end_time",
        "meeting_point",
        "pace_level",
        "max_participants",
        "description",
        "supply_point",
        "audience_tags",
        "visibility",
        "eligibility_note",
        "safety_note",
    )
    for key in editable_fields:
        if key in changes:
            value = changes[key]
            if key in {"start_time", "estimated_end_time"} and value is not None:
                value = _ensure_aware(value)
            setattr(meetup, key, value)
```

Change `list_meetups` base query:

```python
    base = db.query(Meetup).filter(Meetup.visibility == "public")
```

Patch `app/meetup/router.py` `_response`:

```python
        supply_point=meetup.supply_point,
        audience_tags=meetup.audience_tags or [],
        visibility=meetup.visibility,
        eligibility_note=meetup.eligibility_note,
        safety_note=meetup.safety_note,
        share_token=meetup.share_token if is_creator else None,
```

Patch `create_meetup` route call:

```python
        description=req.description,
        supply_point=req.supply_point,
        audience_tags=req.audience_tags,
        visibility=req.visibility,
        eligibility_note=req.eligibility_note,
        safety_note=req.safety_note,
```

- [ ] **Step 5: 跑绿灯**

Run:

```bash
pytest tests/test_meetup_api.py::test_create_returns_social_fields_and_creator_only_share_token tests/test_meetup_api.py::test_patch_updates_social_fields_instead_of_silently_dropping_them tests/test_meetup_api.py::test_public_list_hides_invite_only_but_mine_keeps_owner_items tests/test_meetup_api.py::test_social_field_validation_and_share_token_forbid -q
```

Expected:

```text
4 passed
```

- [ ] **Step 6: 跑本 task 回归**

Run:

```bash
pytest tests/test_meetup_api.py -q
```

Expected:

```text
... passed
```

- [ ] **Step 7: commit**

```bash
git add app/meetup/schemas.py app/meetup/service.py app/meetup/router.py tests/test_meetup_api.py
git commit -m "feat(meetup): task2 persist create prototype fields"
```

---

## Task 3: 私圈口令门禁 + 骑友列表接口

**用户会经历什么:** 私圈约骑不会因为别人猜到连续 id 就被看见或报名；被分享的人带着链接能进来；发起人和已加入的人不用一直带口令也能看。

**Files:**
- Modify: `app/meetup/schemas.py`
- Modify: `app/meetup/service.py`
- Modify: `app/meetup/router.py`
- Test: `tests/test_meetup_api.py`

- [ ] **Step 1: 写红灯测试，覆盖 invite_only 三个入口和 participants**

Add to `tests/test_meetup_api.py`:

```python
def test_invite_only_requires_token_for_detail_join_and_participants(client, db, auth_header):
    segment = _segment(db)
    payload = _payload(segment.id)
    payload["visibility"] = "invite_only"
    create_body = client.post("/api/meetups", json=payload, headers=auth_header).json()
    meetup_id = create_body["id"]
    token = create_body["share_token"]
    client.post(f"/api/meetups/{meetup_id}/publish", headers=auth_header)
    outsider = _auth_header_for(db, "invite-only-outsider")

    assert client.get(f"/api/meetups/{meetup_id}", headers=outsider).status_code == 404
    assert client.post(f"/api/meetups/{meetup_id}/join", headers=outsider).status_code == 404
    assert client.get(f"/api/meetups/{meetup_id}/participants", headers=outsider).status_code == 404

    assert client.get(f"/api/meetups/{meetup_id}?token={token}", headers=outsider).status_code == 200
    assert client.post(f"/api/meetups/{meetup_id}/join?token={token}", headers=outsider).status_code == 200
    assert client.get(f"/api/meetups/{meetup_id}/participants", headers=outsider).status_code == 200


def test_invite_only_creator_can_open_without_token(client, db, auth_header):
    segment = _segment(db)
    payload = _payload(segment.id)
    payload["visibility"] = "invite_only"
    body = client.post("/api/meetups", json=payload, headers=auth_header).json()
    client.post(f"/api/meetups/{body['id']}/publish", headers=auth_header)

    detail = client.get(f"/api/meetups/{body['id']}", headers=auth_header)
    participants = client.get(f"/api/meetups/{body['id']}/participants", headers=auth_header)

    assert detail.status_code == 200
    assert participants.status_code == 200


def test_public_meetup_participants_return_user_summary(client, db, auth_header):
    segment = _segment(db)
    meetup_id = client.post("/api/meetups", json=_payload(segment.id), headers=auth_header).json()["id"]
    client.post(f"/api/meetups/{meetup_id}/publish", headers=auth_header)
    other_header = _auth_header_for(db, "participants-other")
    client.post(f"/api/meetups/{meetup_id}/join", headers=other_header)

    res = client.get(f"/api/meetups/{meetup_id}/participants", headers=auth_header)

    assert res.status_code == 200
    items = res.json()
    assert len(items) == 2
    assert items[0]["user_id"] is not None
    assert "nickname" in items[0]
    assert "avatar_url" in items[0]
    assert items[0]["is_creator"] is True
    assert items[0]["joined_at"] is not None


def test_participants_requires_login_and_missing_meetup_404(client, auth_header):
    assert client.get("/api/meetups/1/participants").status_code == 401
    assert client.get("/api/meetups/999999/participants", headers=auth_header).status_code == 404
```

- [ ] **Step 2: 跑红灯**

Run:

```bash
pytest tests/test_meetup_api.py::test_invite_only_requires_token_for_detail_join_and_participants tests/test_meetup_api.py::test_invite_only_creator_can_open_without_token tests/test_meetup_api.py::test_public_meetup_participants_return_user_summary tests/test_meetup_api.py::test_participants_requires_login_and_missing_meetup_404 -q
```

Expected:

```text
FAILED ... /participants returns 404
FAILED ... invite_only detail/join returns 200 without token
```

- [ ] **Step 3: 加 `InviteeSummary` schema**

Patch `app/meetup/schemas.py` after `MeetupListResponse`:

```python
class InviteeSummary(BaseModel):
    """发布前总览和详情页用的已加入骑友摘要。"""

    model_config = ConfigDict(extra="forbid")

    user_id: int
    nickname: str | None = None
    avatar_url: str | None = None
    is_creator: bool
    joined_at: datetime | None = None
```

- [ ] **Step 4: 加 service 门禁和 participants 查询**

Patch `app/meetup/service.py` imports:

```python
from app.user.models import User
```

Add helper after `is_participant`:

```python
def _check_invite_visibility(db: Session, meetup: Meetup, current_user_id: int | None, token: str | None) -> None:
    """私圈约骑像带口令的房间：不是发起人、不是已进房的人，就必须拿对口令。"""
    if meetup.visibility != "invite_only":
        return
    if current_user_id is not None and meetup.creator_id == current_user_id:
        return
    if current_user_id is not None and is_participant(db, meetup.id, current_user_id):
        return
    if token and meetup.share_token and token == meetup.share_token:
        return
    raise HTTPException(status_code=404, detail="meetup not found")
```

Change `get_meetup_detail` signature and body:

```python
def get_meetup_detail(db: Session, meetup_id: int, current_user_id: int | None = None, token: str | None = None) -> Meetup:
    meetup = db.query(Meetup).filter(Meetup.id == meetup_id).first()
    if meetup is None:
        raise HTTPException(status_code=404, detail="meetup not found")
    _check_invite_visibility(db, meetup, current_user_id, token)
    return meetup
```

Change `join_meetup` signature and add the gate after `_load_and_authorize_meetup`:

```python
def join_meetup(db: Session, meetup_id: int, current_user_id: int, token: str | None = None) -> dict:
    meetup = _load_and_authorize_meetup(
        db,
        meetup_id,
        current_user_id,
        require_status=["OPEN"],
        check_time_cutoff=True,
        cancelled_returns_410=True,
    )
    _check_invite_visibility(db, meetup, current_user_id, token)
```

Add participants service:

```python
def list_participants(db: Session, meetup_id: int, current_user_id: int, token: str | None = None) -> list[dict]:
    meetup = db.query(Meetup).filter(Meetup.id == meetup_id).first()
    if meetup is None:
        raise HTTPException(status_code=404, detail="meetup not found")
    _check_invite_visibility(db, meetup, current_user_id, token)
    rows = (
        db.query(MeetupParticipant, User)
        .join(User, User.id == MeetupParticipant.user_id)
        .filter(MeetupParticipant.meetup_id == meetup_id)
        .order_by(MeetupParticipant.joined_at.asc(), MeetupParticipant.id.asc())
        .all()
    )
    return [
        {
            "user_id": user.id,
            "nickname": user.nickname,
            "avatar_url": user.avatar_url,
            "is_creator": participant.is_creator,
            "joined_at": participant.joined_at,
        }
        for participant, user in rows
    ]
```

- [ ] **Step 5: 接 router 参数和新路由**

Patch `app/meetup/router.py` detail:

```python
def get_meetup(
    meetup_id: int,
    token: str | None = Query(None),
    current_user_id: int | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    meetup = service.get_meetup_detail(db, meetup_id, current_user_id=current_user_id, token=token)
    return _live_response(db, meetup, current_user_id=current_user_id)
```

Add this route before `@router.get("/{meetup_id}", ...)`:

```python
@router.get("/{meetup_id}/participants", response_model=list[schemas.InviteeSummary])
def list_participants(
    meetup_id: int,
    token: str | None = Query(None),
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return service.list_participants(db, meetup_id, current_user_id, token=token)
```

Patch join route:

```python
def join_meetup(
    meetup_id: int,
    token: str | None = Query(None),
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = service.join_meetup(db, meetup_id, current_user_id, token=token)
    return _live_response(db, result["meetup"], participants_count=result["participants_count"], current_user_id=current_user_id)
```

- [ ] **Step 6: 跑绿灯**

Run:

```bash
pytest tests/test_meetup_api.py::test_invite_only_requires_token_for_detail_join_and_participants tests/test_meetup_api.py::test_invite_only_creator_can_open_without_token tests/test_meetup_api.py::test_public_meetup_participants_return_user_summary tests/test_meetup_api.py::test_participants_requires_login_and_missing_meetup_404 -q
```

Expected:

```text
4 passed
```

- [ ] **Step 7: 跑本 task 回归**

Run:

```bash
pytest tests/test_meetup_api.py -q
```

Expected:

```text
... passed
```

- [ ] **Step 8: commit**

```bash
git add app/meetup/schemas.py app/meetup/service.py app/meetup/router.py tests/test_meetup_api.py
git commit -m "feat(meetup): task3 protect invite only meetups"
```

---

## Task 4: 发布前总览页和补给点

**用户会经历什么:** 陈哥在图一填完路线、时间、集合点、补给点和照片，点“发布约骑”后不是立刻上线，而是先看到别人将看到的发布前总览；他在这里勾选适合谁、设置可见范围和门槛，再点确认发布。

**Files:**
- Modify: `miniprogram/pages/meetup-create/meetup-create.js`
- Modify: `miniprogram/pages/meetup-create/meetup-create.wxml`
- Modify: `miniprogram/pages/meetup-create/meetup-create.wxss`
- Test: `tests/test_meetup_miniprogram_static.py`

- [ ] **Step 1: 写红灯静态测试**

Add to `tests/test_meetup_miniprogram_static.py`:

```python
def test_create_page_has_preview_step_and_social_fields():
    js = _read(MINI / "pages" / "meetup-create" / "meetup-create.js")
    wxml = _read(MINI / "pages" / "meetup-create" / "meetup-create.wxml")

    assert "preview" in js
    assert "onTapGoPreview" in js
    assert "onConfirmPublish" in js
    assert "toggleAudienceTag" in js
    assert "onVisibilityChange" in js
    assert "applySafetyTemplate" in js
    assert "supply_point" in js and "supply_point" in wxml
    assert "audience_tags" in js and "audience_tags" in wxml
    assert "eligibility_note" in js and "eligibility_note" in wxml
    assert "safety_note" in js and "safety_note" in wxml
    assert "visibility" in js and "visibility" in wxml
    assert "recommended_power_label" in js
    assert "average_speed_range" in js
    assert "VELO 反骚扰机制" in wxml
    assert 'open-type="share"' in wxml              # 继续邀请走微信原生转发
    assert "form.audience_tags.indexOf" not in wxml  # WXML 不能调数组方法，选中态须在 JS 算


def test_pace_display_table_covers_all_four_pace_levels():
    js = _read(MINI / "pages" / "meetup-create" / "meetup-create.js")

    for pace in ("relaxed", "cruise", "training", "race"):
        assert pace in js
    assert "不限功率" in js
    assert "FTP 160W+ 更舒服" in js
    assert "FTP 220W+" in js
    assert "FTP 280W+" in js
```

- [ ] **Step 2: 跑红灯**

Run:

```bash
pytest tests/test_meetup_miniprogram_static.py::test_create_page_has_preview_step_and_social_fields tests/test_meetup_miniprogram_static.py::test_pace_display_table_covers_all_four_pace_levels -q
```

Expected:

```text
FAILED ... assert 'preview' in js
```

- [ ] **Step 3: 写 JS 状态和派生展示**

Patch `miniprogram/pages/meetup-create/meetup-create.js` above `Page({`:

```javascript
const PACE_DISPLAY = {
  relaxed: { pace_label: '轻松慢骑', recommended_power_label: '不限功率', average_speed_range: '15-18 km/h' },
  cruise: { pace_label: '稳爬不竞速', recommended_power_label: 'FTP 160W+ 更舒服', average_speed_range: '17-22 km/h' },
  training: { pace_label: '高强度拉练', recommended_power_label: 'FTP 220W+', average_speed_range: '25-30 km/h' },
  race: { pace_label: '竞速冲刺', recommended_power_label: 'FTP 280W+', average_speed_range: '30+ km/h' },
}

const AUDIENCE_OPTIONS = [
  { value: 'climb_steady', label: '稳爬不竞速' },
  { value: 'high_intensity', label: '高强度拉练' },
  { value: 'leisure', label: '休闲骑游' },
  { value: 'photography', label: '摄影打卡' },
  { value: 'female_friendly', label: '女性友好' },
  { value: 'newbie_caution', label: '新手慎选' },
]

const SAFETY_TEMPLATES = [
  '头盔必戴 · 遵守交规 · 量力而行',
  '新手友好 · 全程收队 · 不拉爆',
  '强度拉练 · 请自备补给 · 跟不上自行返回',
  '山路多弯 · 控制下坡车速 · 保持车距',
]
```

Patch `data`:

```javascript
    steps: ['route', 'details', 'media', 'publish', 'preview'],
    // audienceOptions 带 selected 标志：WXML 不能调 .indexOf()，选中态在 JS 侧算好
    audienceOptions: AUDIENCE_OPTIONS.map(function (o) { return { value: o.value, label: o.label, selected: false } }),
    safetyTemplates: SAFETY_TEMPLATES,
    visibilityOptions: [
      { value: 'public', label: '本城可见' },
      { value: 'invite_only', label: '私圈可见' },
    ],
    invitees: [],
    shareToken: '',
    routeDistanceText: '',
    routeClimbText: '',
    estimatedDurationText: '',
    recommendedPowerLabel: PACE_DISPLAY.cruise.recommended_power_label,
    averageSpeedRange: PACE_DISPLAY.cruise.average_speed_range,
```

Patch `form`:

```javascript
      supply_point: '',
      audience_tags: [],
      visibility: 'public',
      eligibility_note: '',
      safety_note: SAFETY_TEMPLATES[0],
```

Add methods:

```javascript
  updatePreviewDerived: function () {
    var pace = PACE_DISPLAY[this.data.form.pace_level] || PACE_DISPLAY.cruise
    var start = new Date(this.data.form.start_time)
    var end = new Date(this.data.form.estimated_end_time)
    var duration = ''
    if (Number.isFinite(start.getTime()) && Number.isFinite(end.getTime()) && end > start) {
      var minutes = Math.round((end - start) / 60000)
      duration = Math.floor(minutes / 60) + ':' + String(minutes % 60).padStart(2, '0')
    }
    this.setData({
      recommendedPowerLabel: pace.recommended_power_label,
      averageSpeedRange: pace.average_speed_range,
      estimatedDurationText: duration,
    })
  },

  onTapGoPreview: function () {
    var that = this
    if (!this.data.meetupId) {
      wx.showToast({ title: '草稿丢失，请退回重试', icon: 'none' })
      return
    }
    this.updatePreviewDerived()
    api.updateMeetup(this.data.meetupId, Object.assign({}, this.data.form, {
      max_participants: Number(this.data.form.max_participants),
    })).then(function (draft) {
      that.setData({ currentStep: 'preview', meetupId: draft.id, shareToken: draft.share_token || that.data.shareToken || '' })
      if (api.getMeetupParticipants) {
        api.getMeetupParticipants(draft.id).then(function (items) {
          that.setData({ invitees: items || [] })
        }).catch(function () {
          that.setData({ invitees: [] })
        })
      }
    }).catch(function (err) {
      wx.showToast({ title: (err && err.message) || '保存失败', icon: 'none' })
    })
  },

  // WXML 不支持 .indexOf()，"哪些标签选中"必须在 JS 侧算成 selected 标志再 setData
  syncAudienceOptions: function (tags) {
    var chosen = tags || []
    return AUDIENCE_OPTIONS.map(function (o) {
      return { value: o.value, label: o.label, selected: chosen.indexOf(o.value) >= 0 }
    })
  },

  toggleAudienceTag: function (event) {
    var value = event.currentTarget.dataset.value
    var tags = (this.data.form.audience_tags || []).slice()
    var index = tags.indexOf(value)
    if (index >= 0) {
      tags.splice(index, 1)
    } else {
      tags.push(value)
    }
    this.setData({ 'form.audience_tags': tags, audienceOptions: this.syncAudienceOptions(tags) })
  },

  onVisibilityChange: function (event) {
    var index = Number(event.detail.value)
    var option = this.data.visibilityOptions[index] || this.data.visibilityOptions[0]
    this.setData({ 'form.visibility': option.value })
  },

  applySafetyTemplate: function (event) {
    var index = Number(event.currentTarget.dataset.index)
    this.setData({ 'form.safety_note': this.data.safetyTemplates[index] || this.data.safetyTemplates[0] })
  },

  onConfirmPublish: function () {
    var that = this
    if (this.data.submitting) return
    if (!this.data.meetupId) {
      wx.showToast({ title: '草稿丢失，请退回重试', icon: 'none' })
      return
    }
    this.setData({ submitting: true })
    api.updateMeetup(this.data.meetupId, {
      audience_tags: this.data.form.audience_tags,
      visibility: this.data.form.visibility,
      eligibility_note: this.data.form.eligibility_note,
      safety_note: this.data.form.safety_note,
    }).then(function () {
      return api.publishMeetup(that.data.meetupId)
    }).then(function (meetup) {
      wx.redirectTo({ url: '/pages/meetup-detail/meetup-detail?id=' + meetup.id })
    }).catch(function (err) {
      wx.showToast({ title: (err && err.message) || '发布失败', icon: 'none' })
    }).finally(function () {
      that.setData({ submitting: false })
    })
  },
```

Change `nextStep` media branch:

```javascript
    if (this.data.currentStep === 'media') {
      this.setData({ currentStep: 'publish' })
    }
```

Change `prevStep`:

```javascript
    if (this.data.currentStep === 'preview') {
      this.setData({ currentStep: 'publish' })
    } else if (this.data.currentStep === 'publish') {
      this.setData({ currentStep: 'media' })
```

- [ ] **Step 4: 写 WXML 最小结构**

Patch `miniprogram/pages/meetup-create/meetup-create.wxml`.

Add supply point in details after meeting point:

```xml
    <view class="field">
      <text>补给点</text>
      <input value="{{form.supply_point}}" data-field="supply_point" bindinput="updateField" placeholder="例如：天龙山景区口" />
    </view>
```

Change publish button:

```xml
    <button wx:if="{{currentStep !== 'publish' && currentStep !== 'preview'}}" class="primary" bindtap="nextStep">下一步</button>
    <button wx:elif="{{currentStep === 'publish'}}" class="primary" bindtap="onTapGoPreview">发布约骑</button>
    <button wx:else class="primary" loading="{{submitting}}" disabled="{{submitting}}" bindtap="onConfirmPublish">确认并发布约骑</button>
```

Add preview panel after publish panel:

```xml
  <view wx:elif="{{currentStep === 'preview'}}" class="panel preview">
    <view class="summary">
      <view class="summary-title">{{selectedRouteName}}</view>
      <view class="summary-row"><text>预计时长</text><text>{{estimatedDurationText}}</text></view>
      <view class="summary-row"><text>推荐功率</text><text>{{recommendedPowerLabel}}</text></view>
      <view class="summary-row"><text>预计均速</text><text>{{averageSpeedRange}}</text></view>
      <view wx:if="{{form.supply_point}}" class="summary-row"><text>补给点</text><text>{{form.supply_point}}</text></view>
    </view>

    <view class="summary">
      <view class="section-title">适合谁</view>
      <view class="tag-grid">
        <view wx:for="{{audienceOptions}}" wx:key="value" class="tag {{item.selected ? 'selected' : ''}}" data-value="{{item.value}}" bindtap="toggleAudienceTag">{{item.label}}</view>
      </view>
    </view>

    <view class="summary">
      <view class="summary-row">
        <text>可见范围</text>
        <picker mode="selector" range="{{visibilityOptions}}" range-key="label" bindchange="onVisibilityChange">
          <view>{{form.visibility === 'invite_only' ? '私圈可见' : '本城可见'}}</view>
        </picker>
      </view>
      <view class="field compact">
        <text>报名门槛</text>
        <textarea value="{{form.eligibility_note}}" data-field="eligibility_note" bindinput="updateField" placeholder="例如：能稳定骑完 60km" />
      </view>
      <view class="field compact">
        <text>安全提示</text>
        <textarea value="{{form.safety_note}}" data-field="safety_note" bindinput="updateField" />
      </view>
      <view class="template-list">
        <view wx:for="{{safetyTemplates}}" wx:key="*this" data-index="{{index}}" bindtap="applySafetyTemplate">{{item}}</view>
      </view>
    </view>

    <view class="summary">
      <view class="invite-head">
        <view class="section-title">已加入骑友</view>
        <button class="invite-share" open-type="share">继续邀请</button>
      </view>
      <view wx:if="{{invitees.length === 0}}" class="media-empty">发布后发起人会自动加入</view>
      <view wx:else class="invitee-list">
        <view wx:for="{{invitees}}" wx:key="user_id">{{item.nickname || 'VELO 骑友'}}<text wx:if="{{item.is_creator}}">组织者</text></view>
      </view>
    </view>

    <view class="anti-harass">VELO 反骚扰机制已开启</view>
  </view>
```

- [ ] **Step 5: 写 WXSS 最小样式**

Patch `miniprogram/pages/meetup-create/meetup-create.wxss`:

```css
.tag-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 12rpx;
}

.tag,
.template-list view,
.anti-harass {
  padding: 14rpx 18rpx;
  border-radius: 12rpx;
  background: #f3f4f6;
  color: #374151;
  font-size: 24rpx;
  line-height: 34rpx;
}

.tag.selected {
  background: #111827;
  color: #fff;
}

.compact {
  padding: 0;
  margin-top: 16rpx;
}

.template-list {
  display: flex;
  flex-direction: column;
  gap: 10rpx;
  margin-top: 12rpx;
}

.invitee-list {
  display: flex;
  flex-direction: column;
  gap: 10rpx;
  font-size: 26rpx;
  color: #111827;
}

.invitee-list text {
  margin-left: 12rpx;
  color: #ff2d55;
  font-size: 22rpx;
}

.invite-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.invite-share {
  margin: 0;
  padding: 0 18rpx;
  line-height: 56rpx;
  font-size: 24rpx;
  color: #ff2d55;
  background: #fff;
  border: 1rpx solid #ff2d55;
  border-radius: 28rpx;
}
```

- [ ] **Step 6: 跑绿灯**

Run:

```bash
pytest tests/test_meetup_miniprogram_static.py::test_create_page_has_preview_step_and_social_fields tests/test_meetup_miniprogram_static.py::test_pace_display_table_covers_all_four_pace_levels -q
```

Expected:

```text
2 passed
```

- [ ] **Step 7: 跑本 task 回归**

Run:

```bash
pytest tests/test_meetup_miniprogram_static.py -q
```

Expected:

```text
... passed
```

- [ ] **Step 8: commit**

```bash
git add miniprogram/pages/meetup-create/meetup-create.js miniprogram/pages/meetup-create/meetup-create.wxml miniprogram/pages/meetup-create/meetup-create.wxss tests/test_meetup_miniprogram_static.py
git commit -m "feat(meetup): task4 add publish preview step"
```

---

## Task 5: 草稿恢复 + 微信转发邀请

**用户会经历什么:** 陈哥填到一半退出，重新打开“发起约骑”能接着填；私圈发布后点微信转发，链接会带 `token`，朋友能进，陌生人猜 id 进不来。

**Files:**
- Modify: `miniprogram/pages/meetup-create/meetup-create.js`
- Modify: `miniprogram/utils/api.js`
- Test: `tests/test_meetup_miniprogram_static.py`

- [ ] **Step 1: 写红灯静态测试**

Add to `tests/test_meetup_miniprogram_static.py`:

```python
def test_create_page_restores_draft_and_share_path_carries_invite_token():
    js = _read(MINI / "pages" / "meetup-create" / "meetup-create.js")
    api = _read(MINI / "utils" / "api.js")

    assert "restoreDraft" in js
    assert "api.getMyMeetupDraft" in js
    assert "loadMedia()" in js
    assert "buildRoutePreview" in js
    assert "onShareAppMessage" in js
    assert "share_token" in js
    assert "shareToken" in js
    assert "token=" in js
    assert "getMeetupParticipants" in api
    assert "getMeetupDetail: function (meetupId, token)" in api
    assert "joinMeetup: function (meetupId, token)" in api
```

- [ ] **Step 2: 跑红灯**

Run:

```bash
pytest tests/test_meetup_miniprogram_static.py::test_create_page_restores_draft_and_share_path_carries_invite_token -q
```

Expected:

```text
FAILED ... assert 'restoreDraft' in js
```

- [ ] **Step 3: 扩 api helper 支持 token 和 participants**

⚠ `getMeetupDetail`（📊 api.js:358）和 `joinMeetup`（📊 api.js:399）**已存在**——必须**替换这两处现有定义的函数体**（加 `token` 参数），不要新增同名键（JS 对象字面量重复键 = 旧定义被静默覆盖 + 死代码）。`getMeetupParticipants` 是全新增。

Patch `miniprogram/utils/api.js`:

```javascript
  getMeetupDetail: function (meetupId, token) {
    return request('/api/meetups/' + meetupId + buildQuery(token ? { token: token } : {}), 'GET')
  },

  getMeetupParticipants: function (meetupId, token) {
    return request('/api/meetups/' + meetupId + '/participants' + buildQuery(token ? { token: token } : {}), 'GET')
  },

  joinMeetup: function (meetupId, token) {
    return request('/api/meetups/' + meetupId + '/join' + buildQuery(token ? { token: token } : {}), 'POST', {})
  },
```

Keep existing call sites working by making `token` optional.

- [ ] **Step 4: 写草稿恢复和分享实现**

Patch `miniprogram/pages/meetup-create/meetup-create.js` `onLoad`:

```javascript
  onLoad: function () {
    this.initDefaultTime()
    this.loadRoutes()
    this.restoreDraft()
  },
```

Add methods:

```javascript
  restoreDraft: function () {
    var that = this
    api.getMyMeetupDraft().then(function (draft) {
      if (!draft) return
      var start = splitLocal(new Date(draft.start_time))
      var end = splitLocal(new Date(draft.estimated_end_time))
      that.setData({
        meetupId: draft.id,
        selectedSegmentId: draft.segment_id || null,
        selectedRouteBookId: draft.route_book_id || null,
        selectedRouteName: draft.snapshot_route_name || '',
        startDate: start.date,
        startTime: start.time,
        endDate: end.date,
        endTime: end.time,
        form: {
          start_time: draft.start_time,
          estimated_end_time: draft.estimated_end_time,
          meeting_point: draft.meeting_point || '',
          pace_level: draft.pace_level || 'cruise',
          max_participants: draft.max_participants || 6,
          description: draft.description || '',
          supply_point: draft.supply_point || '',
          audience_tags: draft.audience_tags || [],
          visibility: draft.visibility || 'public',
          eligibility_note: draft.eligibility_note || '',
          safety_note: draft.safety_note || SAFETY_TEMPLATES[0],
        },
        shareToken: draft.share_token || '',
        audienceOptions: that.syncAudienceOptions(draft.audience_tags || []),
      })
      that.updatePreviewDerived()
      that.loadMedia()
      that.restoreRoutePreview(draft.route_book_id)
    }).catch(function () {
      // 恢复草稿失败不阻塞发起流程，用户仍可新建。
    })
  },

  restoreRoutePreview: function (routeBookId) {
    var that = this
    if (!routeBookId || !api.getRouteBookDetail) return
    api.getRouteBookDetail(routeBookId).then(function (routeBook) {
      that.setData(buildRoutePreview(routeBook.preview_points))
    }).catch(function () {
      that.setData(buildRoutePreview([]))
    })
  },

  onShareAppMessage: function () {
    var path = '/pages/meetup-detail/meetup-detail?id=' + this.data.meetupId
    if (this.data.form.visibility === 'invite_only' && this.data.shareToken) {
      path += '&token=' + encodeURIComponent(this.data.shareToken)
    }
    return {
      title: this.data.selectedRouteName || 'VELO 约骑',
      path: path,
    }
  },
```

If `api.getRouteBookDetail` does not exist yet, add it:

```javascript
  getRouteBookDetail: function (routeBookId) {
    return request('/api/route-books/' + routeBookId, 'GET')
  },
```

Patch `onTapGoPreview` and `onConfirmPublish` success branches so the latest `share_token` is kept outside `form`:

```javascript
      that.setData({ currentStep: 'preview', meetupId: draft.id, shareToken: draft.share_token || that.data.shareToken || '' })
```

- [ ] **Step 5: 跑绿灯**

Run:

```bash
pytest tests/test_meetup_miniprogram_static.py::test_create_page_restores_draft_and_share_path_carries_invite_token -q
```

Expected:

```text
1 passed
```

- [ ] **Step 6: 跑本 task 回归**

Run:

```bash
pytest tests/test_meetup_miniprogram_static.py -q
```

Expected:

```text
... passed
```

- [ ] **Step 7: commit**

```bash
git add miniprogram/pages/meetup-create/meetup-create.js miniprogram/utils/api.js tests/test_meetup_miniprogram_static.py
git commit -m "feat(meetup): task5 restore drafts and share invites"
```

---

## Task 6: 发布截止校验 + 最终测试收口

**用户会经历什么:** 陈哥不会把一个已经过了报名截止线的草稿发布出去；最终交付前，两条自动测试命令能证明后端接口和小程序连接点都没有断。

**Files:**
- Modify: `app/meetup/service.py`
- Modify: `tests/test_meetup_api.py`
- Modify: `tests/test_meetup_miniprogram_static.py`

- [ ] **Step 1: 写 publish cutoff 红灯测试**

Add to `tests/test_meetup_api.py`:

```python
def test_publish_rejects_draft_after_registration_cutoff(client, db, auth_header, monkeypatch):
    fixed_now = datetime(2026, 6, 3, 10, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("app.meetup.service._now_utc", lambda: fixed_now)
    segment = _segment(db)
    start = fixed_now + timedelta(minutes=29)
    payload = _payload(segment.id)
    payload["start_time"] = start.isoformat()
    payload["estimated_end_time"] = (start + timedelta(hours=2)).isoformat()
    meetup_id = client.post("/api/meetups", json=payload, headers=auth_header).json()["id"]

    res = client.post(f"/api/meetups/{meetup_id}/publish", headers=auth_header)

    assert res.status_code == 410


def test_publish_allows_draft_before_registration_cutoff(client, db, auth_header, monkeypatch):
    fixed_now = datetime(2026, 6, 3, 10, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("app.meetup.service._now_utc", lambda: fixed_now)
    segment = _segment(db)
    start = fixed_now + timedelta(minutes=31)
    payload = _payload(segment.id)
    payload["start_time"] = start.isoformat()
    payload["estimated_end_time"] = (start + timedelta(hours=2)).isoformat()
    meetup_id = client.post("/api/meetups", json=payload, headers=auth_header).json()["id"]

    res = client.post(f"/api/meetups/{meetup_id}/publish", headers=auth_header)

    assert res.status_code == 200
    assert res.json()["status"] == "OPEN"
```

- [ ] **Step 2: 跑红灯**

Run:

```bash
pytest tests/test_meetup_api.py::test_publish_rejects_draft_after_registration_cutoff tests/test_meetup_api.py::test_publish_allows_draft_before_registration_cutoff -q
```

Expected:

```text
FAILED tests/test_meetup_api.py::test_publish_rejects_draft_after_registration_cutoff
assert 200 == 410
```

- [ ] **Step 3: 写 publish 最小实现**

Patch `app/meetup/service.py` inside `publish_meetup`:

```python
    meetup = _load_and_authorize_meetup(
        db,
        meetup_id,
        current_user_id,
        require_creator=True,
        require_status=["DRAFT"],
        check_time_cutoff=True,
    )
```

- [ ] **Step 4: 跑 publish 绿灯**

Run:

```bash
pytest tests/test_meetup_api.py::test_publish_rejects_draft_after_registration_cutoff tests/test_meetup_api.py::test_publish_allows_draft_before_registration_cutoff -q
```

Expected:

```text
2 passed
```

- [ ] **Step 5: 写最终静态收口测试**

Add to `tests/test_meetup_miniprogram_static.py`:

```python
def test_meetup_create_prototype_static_contract_has_no_placeholder_or_old_publish_shortcut():
    js = _read(MINI / "pages" / "meetup-create" / "meetup-create.js")
    wxml = _read(MINI / "pages" / "meetup-create" / "meetup-create.wxml")

    assert "'--'" not in js
    assert "onConfirmPublish" in js
    assert "api.publishMeetup(this.data.meetupId)" in js
    assert "api.updateMeetup(this.data.meetupId" in js
    assert "bindtap=\"onPublish\"" not in wxml
    assert "确认并发布约骑" in wxml
```

- [ ] **Step 6: 跑最终验收命令**

Run:

```bash
pytest tests/test_meetup_api.py tests/test_meetup_miniprogram_static.py -q
```

Expected:

```text
... passed
```

- [ ] **Step 7: 手动真用回归清单写进交付报告**

Run these with real mini-program + real PostgreSQL before claiming ship:

```text
1. 草稿恢复：填到照片步退出，重进后路线、照片、补给点、social 字段都回来。
2. 私圈分享：invite_only 分享链接带 token；另一账号不带 token 猜 id 访问详情 / join / participants 都是 404。
3. 公开列表：public 能刷到，invite_only 不出现在公开约骑列表，但发起人 mine 里能看到。
4. 过期发布：start_time 进入 start-30m30s 截止线后，确认发布返回 410。
5. 连点发布：第二次点击不产生重复发布，后端仍只有一条 creator participant。
```

Expected:

```text
5 条都通过；若任一失败，停下修复，不进入 commit / deploy。
```

- [ ] **Step 8: commit**

```bash
git add app/meetup/service.py tests/test_meetup_api.py tests/test_meetup_miniprogram_static.py
git commit -m "feat(meetup): task6 enforce publish cutoff"
```

---

## Final Verification

Implementation branch complete only after:

```bash
pytest tests/test_meetup_api.py tests/test_meetup_miniprogram_static.py -q
git status --short
```

Expected:

```text
... passed
```

`git status --short` should show no unstaged implementation changes except intentional docs / delivery notes.

## Self-Review

1. **Spec coverage:** 6 列(T1) / schema+service round-trip(T2) / invite_only token + participants(T3) / 图二总览(T4) / 草稿恢复+分享(T5) / publish cutoff+最终验收(T6) 对应设计文档 §7.7 和 §8。
2. **No placeholders:** 本文件不使用 TBD / TODO / “类似上一 task”；每个 task 都有真实测试代码、最小实现代码、命令、预期输出和 commit。
3. **边界:** 不改核心表 `users` / `activities` / `segments`；只读 `User.nickname/avatar_url` 做 participants 摘要；不修改两张 HTML 原型。

---

## 异源审修订记录（2026-06-03 / Claude 异源审 Codex 写的 plans）

Codex Desktop 写完 → Claude 异源审，抓到 4 个"静态测试绿 / 真机·PATCH·api.js 才翻车"的实现细节 bug（grep 实证），已补进对应 task：

| # | 级别 | 问题 | 修法 | 落点 |
|---|---|---|---|---|
| 1 | Important | WXML 不支持 `.indexOf()`，"适合谁"标签选中态真机不亮（静态测试查不出）| 选中态在 JS 算成 `selected` 标志（`syncAudienceOptions`），WXML 只读标志 + 测试断言 wxml 无 `.indexOf` | Task 4 Step 3/4/F + Task 5 restoreDraft |
| 2 | Important | `getMeetupDetail`(📊 api.js:358) / `joinMeetup`(📊 api.js:399) 已存在，"新增"会重复键 | Step 3 加"必须替换现有定义"明确指令 | Task 5 Step 3 |
| 3 | Important | PATCH 标签校验直接调 `@field_validator` 装饰的方法（Pydantic v2 脆弱）+ 无测试 | 抽模块级 `_validate_audience_tags` 两处共用 + 补 PATCH 非法标签 422 测试 | Task 2 Step 1/3 |
| 4 | Important | "继续邀请"按钮没真接上（微信不能用代码弹转发框）| preview 页加 `<button open-type="share">继续邀请</button>` + WXSS + 测试断言 | Task 4 Step 4/5/F |

附带 minor：conftest `default=[]` → `default=list`（SQLAlchemy 可变默认值陷阱）。

**结论**：4 条均为 plan 文档级局部修，不动方向 / 不动设计文档。修订后可进执行（subagent-driven 或 executing-plans）。
