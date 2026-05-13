# 任务 3.A.1：admin 模块框架（dependencies + router 骨架）

## 🎯 目标

新建 `app/admin/` 模块基础设施：
- `__init__.py` 包标识
- `dependencies.py` 含 `require_admin` FastAPI dependency（基于 User.is_admin 字段）
- `router.py` 含 `/api/admin/*` 路由前缀骨架（具体 endpoint 由 3.A.2-3.A.5 串行追加）
- `service.py` 空骨架（admin 编排逻辑由 3.A.2+ 追加）
- 把现有 DELETE /api/segments/{id} 迁移到 admin router

## ⛓ 前置依赖

task-2.C.2（user 模块完成，is_admin 字段使用方式确认）。

## 📤 输出契约

| 文件 | 用途 |
|---|---|
| `app/admin/__init__.py` | 包 |
| `app/admin/dependencies.py` | `require_admin(...) -> User` 抛 403 if not is_admin |
| `app/admin/router.py` | `/api/admin/*` 前缀路由（骨架） |
| `app/admin/service.py` | 空骨架（3.A.2+ 追加 enqueue / orchestration 逻辑） |

## 🧱 现状

- `app/admin/` 目录**不存在**（v5 新建）
- `app/user/models.py:62` `is_admin = Column(Boolean, server_default='false')`（spec §0.1 已查实，注释"只能手动改库"）
- `app/segment/router.py:84` 现有 `DELETE /api/segments/{id}` —— v5 迁到 admin router 保前缀一致

## 🛠 完整代码

### 1. `app/admin/__init__.py`

```python
"""管理后台模块（v5 新建）。

边界：
- 所有 /api/admin/* endpoint 集中在此
- 调用其他模块 service public API 编排（候选池 + AI 草稿 + segment + activity）
- 禁止业务用户访问（require_admin 依赖把关）
"""
```

### 2. `app/admin/dependencies.py`

```python
from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user  # 沿用现有 JWT 解析，返回 user_id
from app.user.models import User


def require_admin(
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """确认当前登录用户是 admin，否则抛 403。
    
    is_admin 字段只能手动改库（app/user/models.py:62 注释），
    避免 admin 提权风险。

    实现修正：真实 get_current_user 返回 int user_id，不返回 User，
    所以这里自查 users 表后再返回 User。
    """
    user = db.query(User).filter_by(id=user_id).first()
    if not user or user.is_admin is not True:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限",
        )
    return user
```

### 3. `app/admin/router.py`（骨架）

```python
from fastapi import APIRouter

router = APIRouter(prefix="/api/admin", tags=["admin"])

# 3.A.2 追加：候选池 endpoints (GET /curation-pool, PATCH /curation-pool/{id})
# 3.A.3 追加：AI 草稿审核 endpoints (POST /ai/segment-drafts/{id}/generate, GET /ai/segment-drafts, PATCH /ai/segment-drafts/{id})
# 3.A.4 追加：批量管理 endpoints (GET /segments, PATCH /segments/{id})
# 3.A.5 追加：from-activity endpoint (POST /segments/from-activity)
# 本任务追加：DELETE /segments/{id}（从 app/segment/router.py:84 迁移）


from app.admin.dependencies import require_admin
from sqlalchemy.orm import Session
from app.database import get_db
from app.segment import service as segment_service


@router.delete("/segments/{segment_id}", status_code=204)
def delete_segment_admin(
    segment_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """admin 删 segment（CASCADE 删 segment_efforts / drafts / curation_pool 行）。"""
    segment_service.delete_segment(db, segment_id, admin.id)
    return None
```

### 4. `app/admin/service.py`（空骨架）

```python
"""admin 编排逻辑（候选池审核同步触发 AI / approved 时同步 segments.description 等）。

3.A.2+ 追加具体函数。
"""
```

### 5. `app/main.py` 注册 admin router

```python
from app.admin.router import router as admin_router
app.include_router(admin_router)
```

### 6. 移除 `app/segment/router.py:84` DELETE endpoint

```python
# 保留现有 @router.delete("/{segment_id}") 块
# 加 deprecated=True，半年后移除
```

> 兼容方案（Tim 已拍板）：原 DELETE 保留但加 `deprecated=True`；实现采用“双挂载到同一 service”而不是重定向，少一跳且客户端无感。

## ✅ 测试

```python
# tests/test_admin_dependencies.py
def test_require_admin_grants_admin_user(): ...
def test_require_admin_rejects_normal_user_403(): ...
def test_require_admin_rejects_anonymous_401(): ...

# tests/test_admin_router.py
def test_delete_segment_admin_only(client, admin_user, normal_user):
    res = client.delete(f"/api/admin/segments/{seg.id}", headers=normal_user.auth)
    assert res.status_code == 403
    res = client.delete(f"/api/admin/segments/{seg.id}", headers=admin_user.auth)
    assert res.status_code == 204
```

## 📝 commit

```
feat(admin): 任务 3.A.1 admin 模块框架

新建 app/admin/__init__.py / dependencies.py / router.py / service.py
- require_admin dependency 基于 User.is_admin
- /api/admin/* 路由前缀注册
- DELETE /api/segments/{id} 迁移至 /api/admin/segments/{id}（保留旧路径 deprecated）
- main.py 注册 admin router
```

## 🔍 自检三问

1. **权限边界**：require_admin 是否在所有后续 endpoint 上 `Depends`？  
   → 是。3.A.2-3.A.5 每个 endpoint 都 Depends(require_admin)。骨架先建好这个 dep 函数复用。

2. **DELETE 路径迁移兼容**：现有客户端（小程序 / 内部脚本）调 DELETE /api/segments/{id} 会 404 吗？  
   → 用 deprecated + 双挂载兼容半年。Tim 已拍保留兼容，旧路径继续调用同一 service。

3. **is_admin 提权风险**：require_admin 仅校验 User.is_admin 字段，无二次校验（如 IP 白名单）—— 接受吗？  
   → v5 接受。is_admin 只能手动改库，无 endpoint 提权路径。未来 v6+ 加 admin token / 双因素可选。
