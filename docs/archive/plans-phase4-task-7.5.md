# 任务 7.5：import-progress stalled + Redis 限速

> 修 Critical-07：scheduler 挂起时前端无限轮询——加 "stalled" 视图层判定让前端停轮询。
> 修 Important I11：import-progress 无限速——加 Redis 1s/user 限流。

---

## 🎯 目标（一句话）

把 `GET /api/strava/import-progress` 从"只吐 active / completed / paused 这三种"升级成"加一种 stalled（5 分钟无更新视为卡死）"——让前端有明确信号停轮询；同时加 Redis 1 秒 1 次的限速避免被前端误伤。

---

## ⛓ 前置依赖

- **task-7.1**（`strava_imports.updated_at` 必须已迁移为 `TIMESTAMP WITH TIME ZONE`。本任务用 `datetime.now(UTC) - updated_at` 做相减，naive 和 aware 相减会 TypeError）

## 📥 输入契约

**现有代码事实核对**：

| 项目 | 位置 | 现状 |
|------|------|------|
| router 端点 | `app/strava/router.py:191-201` | `GET /import-progress` → `service.get_import_progress(db, user_id)` |
| service 函数 | `app/strava/service.py:514-...` | 现返 `{status, message, ...}` 结构（没有 view_status） |
| StravaImport.status 值域 | `'active' / 'paused' / 'completed'` | 参考 spec §0.1 代码侧事实表 |
| Redis 客户端 | `app/strava/client.py` | 已存在 `_redis`（任务 7.2 也用） |

## 📤 输出契约

| 产出 | 接口/签名 | 说明 |
|------|---------|------|
| 响应字段 `view_status` | `'none' / 'active' / 'stalled' / 'paused' / 'completed'` | 视图层判定，不写库 |
| 响应字段 `db_status` | 原 StravaImport.status | 诊断用（和 view_status 区分开） |
| 响应字段 `total / completed / tier1_completed` | 整数 | 进度条渲染用 |
| Redis 限速键 | `rl:imp-prog:{user_id}` | 1s TTL、SET NX，触发限速返 429 |

---

## 🛠 完整代码

### 1. 改 `app/strava/service.py` 的 `get_import_progress`

**替换现有实现**（`service.py:514` 起），改为：

```python
def get_import_progress(db: Session, user_id: int) -> dict:
    """
    查询 Strava 导入进度。v4 重构——从"算百分比"改为"吐视图状态"。

    为什么叫 view_status 不叫 status：
        StravaImport.status（数据库值）只有三种：active / paused / completed。
        "卡死" 不是一个数据库状态——而是"active 但 updated_at 5 分钟没动"，
        属于视图层派生态。起两个不同的名字避免口径混乱。

    前端约定：
    - view_status == 'completed' / 'paused' / 'stalled' → 停止轮询
    - view_status == 'active' → 继续轮询（3s 一次）
    - view_status == 'none' → 未发起过导入，不轮询

    Args:
        db: SQLAlchemy Session
        user_id: 当前用户 ID

    Returns:
        {
          "view_status": "none" / "active" / "stalled" / "paused" / "completed",
          "db_status": None / "active" / "paused" / "completed",
          "total": 0,
          "completed": 0,
          "tier1_completed": 0,
        }
    """
    from datetime import datetime, timezone, timedelta
    from app.strava.models import StravaImport

    imp = (
        db.query(StravaImport)
        .filter_by(user_id=user_id)
        .order_by(StravaImport.created_at.desc())
        .first()
    )

    if imp is None:
        return {
            "view_status": "none",
            "db_status": None,
            "total": 0,
            "completed": 0,
            "tier1_completed": 0,
        }

    # view_status 默认 = db_status（active / paused / completed 三种）
    view_status = imp.status

    # Critical-07：active 状态下 5 分钟无更新 → stalled
    # 前提：task-7.1 已迁移 updated_at 为 timezone=True，否则下一行 TypeError
    if imp.status == "active":
        staleness = datetime.now(timezone.utc) - imp.updated_at
        if staleness > timedelta(minutes=5):
            view_status = "stalled"
            logger.warning(
                "import stalled user_id=%d import_id=%d 过期 %.0f 秒",
                user_id, imp.id, staleness.total_seconds(),
            )

    return {
        "view_status": view_status,
        "db_status": imp.status,
        "total": imp.total_activities or 0,
        "completed": imp.tier2_completed or 0,
        "tier1_completed": imp.tier1_completed or 0,
    }
```

> **删掉什么**：原来的 percent 计算（tier1_pct + tier2_pct）本任务**删除**——前端直接用 `completed / total` 自己算百分比更直观。删除理由：减少后端-前端对"进度语义"的认知负担，老口径的分层百分比没有实际用户价值。

### 2. 改 `app/strava/router.py` 加限速

找到 `@router.get("/import-progress")`（`router.py:191-201`），**替换为**：

```python
from fastapi import HTTPException
from app.strava.client import _redis


@router.get("/import-progress")
def get_import_progress(
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    查询 Strava 导入进度——前端显示进度条用。

    限速：1 秒 1 次/用户。
    理由：前端正常轮询是 3s 一次，1s 限速只挡住误开发或恶意刷屏，
    正常业务完全在阈值内。触发返 429。

    Redis 不可用时：降级放行（限速不应阻断核心功能）。
    """
    # ---- Redis 限速（1s/user）----
    # 用 SET NX + EX 原子操作：key 不存在时设置成功（放行），已存在则失败（限速）
    try:
        rl_key = f"rl:imp-prog:{user_id}"
        allowed = _redis.set(rl_key, "1", ex=1, nx=True)
        if not allowed:
            raise HTTPException(status_code=429, detail="请求过于频繁，请 1 秒后再试")
    except HTTPException:
        raise  # 限流触发正常抛
    except Exception:
        # Redis 不可用 → 降级放行（日志记录即可）
        logger.warning("Redis 限速失败，放行 user_id=%d", user_id)

    return service.get_import_progress(db, user_id)
```

**注意 import**：
- `_redis` 从 `app.strava.client` 导入——该实例已在 `client.py:59` 暴露，直接 `from app.strava.client import _redis` 即可（已验证）
- **router.py 顶部必须有 logger**——现有代码没有声明，本任务用到 `logger.warning`。在 import 区追加：
  ```python
  import logging
  logger = logging.getLogger(__name__)
  ```
  （如果 task-7.4 / 7.3 先合入已加了就不用重复）

---

## 🧪 测试

**文件**：`tests/strava/test_import_progress.py`（新建）

```python
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.strava import service
from app.strava.models import StravaImport


# ---------- service.get_import_progress 单测 ----------

def test_view_status_none_when_no_import(db, user_factory):
    user = user_factory()
    res = service.get_import_progress(db, user.id)
    assert res["view_status"] == "none"
    assert res["db_status"] is None
    assert res["total"] == 0


def test_view_status_active_when_recently_updated(db, user_factory):
    user = user_factory()
    imp = StravaImport(
        user_id=user.id,
        strava_athlete_id=99001,
        status="active",
        total_activities=100,
        tier1_completed=20,
        tier2_completed=5,
    )
    # updated_at 默认是 func.now()，新建记录 staleness 接近 0
    db.add(imp)
    db.commit()

    res = service.get_import_progress(db, user.id)
    assert res["view_status"] == "active"
    assert res["total"] == 100
    assert res["completed"] == 5
    assert res["tier1_completed"] == 20


def test_view_status_stalled_when_updated_at_5min_ago(db, user_factory):
    user = user_factory()
    stale_time = datetime.now(timezone.utc) - timedelta(minutes=6)
    imp = StravaImport(
        user_id=user.id,
        strava_athlete_id=99001,
        status="active",
        total_activities=100,
    )
    db.add(imp)
    db.commit()

    # 手动改 updated_at 到 6 分钟前（绕开 ORM 的 onupdate）
    db.execute(
        StravaImport.__table__.update()
        .where(StravaImport.id == imp.id)
        .values(updated_at=stale_time)
    )
    db.commit()

    res = service.get_import_progress(db, user.id)
    assert res["view_status"] == "stalled"
    assert res["db_status"] == "active"  # 数据库态不变，视图态派生


def test_view_status_completed_passthrough(db, user_factory):
    user = user_factory()
    db.add(StravaImport(
        user_id=user.id,
        strava_athlete_id=99001,
        status="completed",
        total_activities=50,
        tier2_completed=50,
    ))
    db.commit()

    res = service.get_import_progress(db, user.id)
    assert res["view_status"] == "completed"
    assert res["db_status"] == "completed"


def test_view_status_paused_passthrough(db, user_factory):
    user = user_factory()
    db.add(StravaImport(
        user_id=user.id,
        strava_athlete_id=99001,
        status="paused",
    ))
    db.commit()

    res = service.get_import_progress(db, user.id)
    assert res["view_status"] == "paused"


# ---------- router 限速单测 ----------

def test_rate_limit_blocks_second_call_within_1s(client_with_auth, monkeypatch):
    """第一次放行，第二次（1 秒内）被 429。"""
    from app.strava import router as strava_router

    redis_mock = MagicMock()
    # 第一次 set nx 返 True，第二次返 False（模拟 key 已存在）
    redis_mock.set.side_effect = [True, False]
    monkeypatch.setattr(strava_router, "_redis", redis_mock)

    resp1 = client_with_auth.get("/api/strava/import-progress")
    assert resp1.status_code == 200

    resp2 = client_with_auth.get("/api/strava/import-progress")
    assert resp2.status_code == 429


def test_rate_limit_degrades_when_redis_down(client_with_auth, monkeypatch):
    """Redis 抛异常 → 降级放行（不阻断用户）。"""
    from app.strava import router as strava_router

    redis_mock = MagicMock()
    redis_mock.set.side_effect = Exception("redis down")
    monkeypatch.setattr(strava_router, "_redis", redis_mock)

    resp = client_with_auth.get("/api/strava/import-progress")
    assert resp.status_code == 200
```

**手工验证**：

```bash
# 1. 模拟 stalled
sudo docker compose exec db psql -U velo -d velo -c \
  "UPDATE strava_imports SET status='active', updated_at=NOW() - INTERVAL '6 minutes' WHERE user_id=1;"

# 2. 调接口（带 JWT）
curl -H "Authorization: Bearer TOKEN" https://DOMAIN/api/strava/import-progress
# 应返回 {"view_status": "stalled", "db_status": "active", ...}

# 3. 限速测试：快速双击
for i in 1 2 3; do
  curl -H "Authorization: Bearer TOKEN" https://DOMAIN/api/strava/import-progress
  echo ""
done
# 第 1 次 200，2/3 应有 429
```

---

## 📦 Commit 指令

```bash
git add app/strava/service.py \
        app/strava/router.py \
        tests/strava/test_import_progress.py

git commit -m "$(cat <<'EOF'
feat(strava): 任务 7.5 import-progress stalled + 限速（修 C7 + I11）

service.get_import_progress 重构：
- 新增 view_status 字段：none/active/stalled/paused/completed
- 保留 db_status 字段：诊断用，区分数据库态和视图态
- active 状态下 updated_at 超 5 分钟 → 视图态 stalled
- 删掉老的 percent 算法（前端直接用 completed/total 自己算）

router.get_import_progress 加限速：
- Redis 1s/user SET NX，触发返 429
- Redis 不可用降级放行（日志警告）

前端约定（spec §2.8）：
- view_status=active → 3s 轮询
- view_status in [completed, paused, stalled] → 停轮询
- view_status=none → 不轮询

测试：5 个 service 用例 + 2 个 router 限速用例。
EOF
)"
```

---

## ✅ 自检三问

**1. 10 分钟挑战**：讲清这次改动干了什么？

> 两件事。第一，给 `/import-progress` 接口加了一种新状态 "stalled"——当数据库说"正在导入"但 5 分钟没动过，我们就判定 scheduler 卡死了，前端看到 stalled 就停轮询、给个"重试"按钮。第二，给这个接口加了个 1 秒 1 次的限速，防前端误开发疯狂轮询。

**2. 崩溃场景**：如果 Redis 挂了会怎样？

> 限速那里 try/except 兜底 → 降级放行，用户请求正常过。进度查询本身不依赖 Redis（读 DB），所以 Redis 全挂也不影响功能，只是没了限速。这符合 CLAUDE.md 第 6 条"限流不应阻断功能"。

**3. 边界纪律**：有没有做 spec 没要求的"顺手优化"？

> 没有。严格 §2.8 范围。没有顺手把限速扩到其他 Strava 接口（/status、/sync 各有不同限速语义）、没有改 scheduler 的 tick 逻辑（那是 task-7.6 / 7.9 的事）、没有给 `StravaImport.status` 加 CHECK 约束（虽然值域该约束，但不在本任务 spec）。
