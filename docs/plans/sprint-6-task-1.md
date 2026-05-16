# Sprint 6 Task-1 — User.bio 字段（一行短签名）

> 所属：Sprint 6（"我的"页基础落地 / 共 6 task）
> 这是第 1 个 task / 地基层（task-2 数据徽章 / task-4 前端 profile 都依赖此）
> 上下文：2026-05-15 brainstorm Tim 拍签名形态 = 一行短签名（≤ 30 字 / 短签名定位 / 不做长简介）
> v0.2（2026-05-16）：修 v0.1 双审 Critical / field_validator 同时挂 2 个 request schema / 真实类名替换

---

## ─────── 给 Tim 看（你审这层就够）───────

### 干啥用

后端 User 表加一格"短签名"字段（bio）—— 让用户能写一行话告诉骑友"我是谁"。

这次只动后端：建字段 + 迁移 + 改 schema + 改 endpoint 让它能存能读。**前端怎么显示 / 在哪显示 / 怎么编辑 留给 task-4**。

### 用户故事

**故事 A — 写签名**
小明打开"我的"页 → 点头像下方的"签名"区域 → 输入"成都老登 / 公路党 / FTP 220W" → 保存 → 后端把这行字存到 User.bio → 下次打开"我的"页 / 别人点他头像看 user 页 / 都能看到这行字。

**故事 B — 签名上限**
小红写得太多："我从 2020 年开始骑车 / 起点是杭州龙井 / 喜欢长距离爬坡..." 输了 50 字 → 后端拒收（"签名不能超过 30 个字符"）→ 让她精简。

**故事 C — 看别人**
CCF 第一次点小明的头像 → 进 user 页 → 立刻看到"成都老登 / 公路党 / FTP 220W" 这行字 → 5 秒判断"这是个 220W 的成都本地老炮"→ 决定要不要约骑 / 关注。

**故事 D — 老用户兼容**
v5 期之前已经注册的用户 / 不用做任何事 / bio 默认 NULL / 前端整块隐藏即可。需要的时候自己去填。

### 怎么算做对了

- ✓ 新用户 PATCH /me 入 bio = "成都老登" → 后端存 DB → GET /profile 返这行字
- ✓ 用户 PATCH /me 入 31 字 bio → 后端拒收（422 错误）
- ✓ 用户 PUT /profile 入 bio = "..." → 同样存 DB（PUT + PATCH 两条路径都通）
- ✓ 用户 PATCH /me 入 bio = null（清空）→ DB 写 NULL → GET 返 null
- ✓ 别人 GET /api/user/{user_id}/profile → 也能看到对方 bio（**新增字段自他对称**）
- ✓ 老用户 bio 默认 NULL / 一切既有接口照旧不报错
- ✗ 任何 bio 含换行 / 控制字符通过 → 是 bug（PUT 和 PATCH 两条路径都不能漏）
- ✗ bio 出现在不该看到的 endpoint（如 /api/user/active 活跃列表）→ 是 bug（白名单泄漏）

### 这次**不做**的事

- 前端 profile 页改造（task-4）
- 前端编辑 UI / 弹窗 / 字符计数器（task-4）
- 多行长简介 / Markdown / @ 用户 / 表情图标（永不做 / 短签名定位）
- 敏感词过滤（100 用户量级 / 真出问题再说）

### 估时

0.5 天（含 Claude 双审 + Codex 异源审）

---

## ─────── 折叠：执行 subagent 看的技术细节 ───────

<details>
<summary>展开</summary>

### 起手必跑：现状 grep（事实表已实证 / 但执行时再 grep 防 stale）

> PRD § 0.1 已列真实事实表 / subagent 执行前重新 grep 验证防文件 drift。

```bash
# User 模型字段确认（PRD § 0.1 已实证 / 复查）
rg "Column" app/user/models.py

# schemas 真实类名 + 字段引用
rg "^class|nickname|avatar_url" app/user/schemas.py

# 最新迁移 head
rg "^revision = |^down_revision = " migrations/versions/sprint5_activity_privacy.py

# 看他人 profile 白名单（必须加 bio）
rg "_PROFILE_RESPONSE_KEYS" app/user/service_social.py

# 现有 4 处 user endpoint（前缀 /api/user 单数）
rg "@router\.(put|patch|get|post)" app/user/router.py
```

### 现状（PRD § 0.1 事实表已确认）

- User 模型字段（`app/user/models.py:27-119`）：id / openid / nickname / avatar_url / ftp / weight / bike_type / weekly_goal / is_admin / strava_athlete_id / strava_access_token / strava_refresh_token / strava_token_expires_at / mute_notifications / city / created_at / updated_at
- schemas 真实类名（`app/user/schemas.py`）：`UserProfile`（GET /profile / L46-59）/ `UserProfileUpdate`（PUT /profile body / L62-77）/ `UserPatchRequest`（PATCH /me body / L171-182）/ `UserProfileResponse`（others / L192-212）
- 白名单 `_PROFILE_RESPONSE_KEYS`（`app/user/service_social.py:71-75`）：9 字段
- Router 前缀 `/api/user`（单数 / `app/user/router.py:23`）
- 最新迁移 head：`sprint5_activity_privacy`（`migrations/versions/sprint5_activity_privacy.py:12`）

### 新字段

```python
# app/user/models.py User 类追加
bio = Column(String(60), nullable=True)
# 60 字节容量留足 30 中文 utf8mb4 冗余
# nullable=True：默认 NULL / 旧用户兼容 / 前端 wx:if 不渲染
# 无 default：插入 / 更新时由 schema / endpoint 控制
```

### Alembic 迁移

文件：`migrations/versions/sprint6_user_bio.py`

```python
"""sprint6_user_bio

Revision ID: sprint6_user_bio
Revises: sprint5_activity_privacy
Create Date: 2026-05-16
"""

from alembic import op
import sqlalchemy as sa

revision = "sprint6_user_bio"
down_revision = "sprint5_activity_privacy"  # PRD § 0.1 事实表实证 / 当前 head
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('bio', sa.String(60), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'bio')
```

**部署纪律**：
- 在 PostgreSQL + SQLite 都跑通 `upgrade head` + `downgrade -1`
- 不需 backfill（NULL 默认即可）

### schemas 4 处更新（`app/user/schemas.py` / 真实类名）

```python
# 1. UserProfile（GET /profile self / L46-59）追加：
bio: Optional[str] = None

# 2. UserProfileUpdate（PUT /profile body / L62-77）追加：
bio: Optional[str] = Field(None, max_length=30)
# max_length=30 = Unicode codepoint 上限（Pydantic v2 按 codepoint 算）

# 3. UserProfileResponse（others / L192-212）追加：
bio: Optional[str] = None
# 看他人也有 bio / **新增字段自他对称**

# 4. UserPatchRequest（PATCH /me body / L171-182）追加：
bio: Optional[str] = Field(None, max_length=30)
# 同样 max_length=30 限制
```

### field_validator 同时挂 2 个 request schema（v0.2 Critical 修）

**红线**：换行 / 控制字符校验必须在 `UserProfileUpdate`（PUT /profile）+ `UserPatchRequest`（PATCH /me）**两个 request body schema 都挂**。漏一个 = 那条路径被绕过校验 = bug。

抽共享 validator helper / 两个 schema 都引用：

```python
from pydantic import field_validator

def _reject_newline_and_control(v: Optional[str]) -> Optional[str]:
    """共享：bio 校验拒收换行 / 控制字符。"""
    if v is None:
        return v
    if any(c in v for c in "\n\r\t\x00"):
        raise ValueError("签名不能含换行或控制字符")
    return v


class UserProfileUpdate(BaseModel):
    # ... 现有字段
    bio: Optional[str] = Field(None, max_length=30)

    @field_validator("bio")
    @classmethod
    def _validate_bio(cls, v):
        return _reject_newline_and_control(v)


class UserPatchRequest(BaseModel):
    # ... 现有字段 city
    bio: Optional[str] = Field(None, max_length=30)

    @field_validator("bio")
    @classmethod
    def _validate_bio(cls, v):
        return _reject_newline_and_control(v)
```

### 看他人白名单（`app/user/service_social.py:71-75`）

```python
# 现状（9 字段 / 实证）：
_PROFILE_RESPONSE_KEYS = {
    "id", "nickname", "avatar_url", "city", "bike_type",
    "total_distance_km", "total_elevation_m", "activity_count",
    "current_month_summary",
}

# v0.2 改：用 `|=` 集合追加运算符 / 不要整体重写（防丢字段）
_PROFILE_RESPONSE_KEYS |= {"bio"}
```

**红线**：白名单是单一真相源 / 改这里 mental check"会泄漏哪些字段"/ Codex 异源审重点扫。

### endpoint 改动（`app/user/router.py` / 前缀 `/api/user` 单数）

4 处 endpoint 通过 schemas 自动接受 / 返回 bio（schemas 改完 endpoint 不用改代码）：

- GET /api/user/profile → response_model=`UserProfile`（已加 bio）
- PUT /api/user/profile → 接受 `UserProfileUpdate`（已加 bio）+ 返 UserProfile
- PATCH /api/user/me → 接受 `UserPatchRequest`（已加 bio）+ 返 UserProfile
- GET /api/user/{user_id}/profile → response_model=`UserProfileResponse`（已加 bio）

但 service 层（`service_auth.update_user_profile` / `service.update_user_city` 等）需确保 bio 被读取 / 更新 / 不被白名单过滤掉。

### service 层改动

**`service_auth.update_user_profile`**（处理 PUT /profile + PATCH /me 共用更新逻辑 / 实证 service_auth.py:167）：
```python
# 现有逻辑遍历 update_data 字典 setattr User
# update_data 含 bio = "..." 时自动写入
# 但 bio = "" 应转 NULL（避免空字符串污染）：
if "bio" in update_data and update_data["bio"] == "":
    update_data["bio"] = None
```

**`service_social.get_user_profile_for_others`**：
- 不需改 / 白名单 `|=` 追加 bio 后自动透出

### 测试要求（tests/test_user.py 或同位）

pytest 用例（最少 7 条）：

1. **PATCH 新建签名**：PATCH /api/user/me bio = "成都老登 / 公路党 / FTP 220W" → 200 + DB 写入 + GET /api/user/profile.bio == 输入值
2. **PUT 同效**：PUT /api/user/profile bio = "..." → 同上效果
3. **超长拒收**：PATCH /api/user/me bio = "x" * 31 → 422
4. **PUT 超长拒收**：PUT /api/user/profile bio = "x" * 31 → 422（防 PUT 路径漏护）
5. **清空 bio**：PATCH bio = null → DB.bio is NULL
6. **空字符串转 NULL**：PATCH bio = "" → DB.bio is NULL
7. **换行拒收两条路径**：PATCH bio = "line1\nline2" → 422 / PUT 同测 → 422（v0.2 Critical 修 / 两路径都不漏）
8. **看他人含 bio**：GET /api/user/{user_id}/profile.bio == 对方 bio（新字段自他对称）

**额外检查**（防回归）：
- GET /api/user/active 不返 bio（防白名单泄漏）
- 既有 9 字段 + bio = 10 字段 / 不允许覆写丢字段（`|=` 追加红线）
- 既有 profile pytest 全部不破坏（≥ 既有 case 数）

### 双审顺序（CLAUDE.md "三重审判"）

1. **Claude A 忠 PRD**：对照 sprint-6-prd.md § 3.1 task-1 验收标准 / 字段名 / 类名 / 长度上限 / 两路径校验
2. **Claude B 集成审**：白名单 `|=` 追加是否覆盖既有 9 字段 / bio 是否泄漏到 active / 检查 user_id 跨用户访问路径
3. **Codex 异源审**：调用 `codex:codex-rescue` / 重点扫"两个 request schema validator 是否都挂" + "PUT vs PATCH 路径校验对齐" + "白名单泄漏"

### 依赖 / 顺序

- 依赖：无（地基 task）
- 阻塞：task-2（badges 字段加入 schemas / `|=` 追加 / 与 bio 同位）/ task-4（前端 profile 改造）

### 部署 SOP（commit 后必跑）

按 memory `feedback_deploy_must_curl_verify_not_just_docker_ps.md` 5 步：

1. 本地 `git push origin main`
2. 远端 `git pull`
3. **改 schema 必清 Redis cache**（profile / user 相关 key 全清 / 防 ResponseValidationError）
4. `docker compose up -d --build`（不是 restart）
5. curl verify：
   - `curl -X PATCH /api/user/me -H "Authorization: Bearer $TOKEN" -d '{"bio":"测试"}'` → 200
   - `curl /api/user/profile` → 含 bio 字段
   - `curl /api/user/1/profile` → 含 bio 字段（自他对称）

</details>
