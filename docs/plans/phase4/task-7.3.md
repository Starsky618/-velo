# 任务 7.3：callback 防重复绑定 + 换号清理

> 修复 Critical-02（重复绑定堆积）+ Important I6（换号不清旧账号）。

> ⚠ **和 task-7.2 合并执行**：同一 subagent 连续实施 7.2 + 7.3，合并为**一个 commit**（用本任务的 commit 消息提交）。跳过 7.2 的独立 commit。
>
> **另外，task-7.3 同步把 `get_strava_status` 响应扩展字段**：当前响应是 `{connected: bool, athlete_id: int|null}`。为让前端 task-7.10 读 `res.bound` 方便（对齐 spec §2.6 "handle_callback 返 bound=True"语义），把 `get_strava_status` 改为同时返 `bound` 和 `connected`（两者值相同，bound 是 connected 的别名）——向后兼容：老前端用 connected 不变，新前端用 bound。

---

## 🎯 目标（一句话）

重写 `handle_callback` 函数——让 Strava OAuth 回调**对各种边界情况有清晰处理**：首次绑定、重复绑定、换号、被他人占用；同时修掉"每次 callback 都新建 StravaImport"的历史漏洞。

---

## ⛓ 前置依赖

- **task-7.1**（DB schema 就位，`StravaImport.status` 值域是 active/paused/completed）
- **task-7.2**（`verify_state_and_consume` / `InvalidStateError` 已存在）

## 📥 输入契约（本任务依赖 task-7.2 产出）

| 来源 | 签名 | 本任务怎么用 |
|------|------|------------|
| `app.strava.service.verify_state_and_consume(state, redis) -> int` | 返回 user_id | callback 入口调用，替代旧 JWT 解 state |
| `app.strava.service.InvalidStateError` | Exception | callback 层捕获转 400 响应 |

## 📤 输出契约（task-7.6 会用）

| 产出 | 签名 | 说明 |
|------|------|------|
| `_cleanup_old_athlete_activities` | `(db: Session, user_id: int, old_athlete_id: int) -> int` | 换号时清旧 athlete 的 importing 活动 |
| `BoundByOtherUserError` | Exception | 该 Strava 账号已绑到其他 VELO 账号 |
| 重写后的 `handle_callback` | `(db, code, state, redis) -> dict` | **注意签名新增 redis 参数** |

---

## 🛠 完整代码

### 1. 在 `app/strava/service.py` 添加新异常类

在已有的 `InvalidStateError` 旁边（task-7.2 产出的）：

```python
class BoundByOtherUserError(Exception):
    """该 Strava 账号已被其他 VELO 账号绑定"""
    pass
```

### 1.5 同步修改 `get_strava_status`（新增 bound 字段别名）

找到现有 `app/strava/service.py` 的 `get_strava_status`（大约在 `:215-222`），把返回结构扩展：

```python
def get_strava_status(db: Session, user_id: int) -> dict:
    user = db.query(User).filter_by(id=user_id).first()
    connected = user is not None and user.strava_athlete_id is not None
    return {
        # 老字段保留——向后兼容现有调用方
        "connected": connected,
        "athlete_id": user.strava_athlete_id if connected else None,
        # 新增——task-7.10 前端要用 res.bound 做判断
        "bound": connected,
    }
```

### 2. 新增清理函数 `_cleanup_old_athlete_activities`

```python
def _cleanup_old_athlete_activities(db: Session, user_id: int, old_athlete_id: int) -> int:
    """
    换号场景：把旧 athlete 还在导入中的活动标为 failed。

    为什么这么做：
        用户从 Strava 账号 A 切到账号 B 时，调度器之前为账号 A 创建的
        "importing 骨架活动"（只有元信息、还没拉轨迹的占位）失去意义——
        再让调度器用账号 B 的 token 去拉账号 A 的活动，会 403 / 404。
        提前把它们置 failed 能避免生产环境一堆无意义的失败日志。

    注意：不删除历史已 completed 活动（用户可能还想看）。

    Args:
        db: SQLAlchemy session（调用方负责 commit）
        user_id: 当前用户 id
        old_athlete_id: 旧的 Strava athlete_id（传入用于日志）

    Returns:
        被标 failed 的活动数量
    """
    from app.activity.models import Activity  # 避免循环 import

    count = (
        db.query(Activity)
        .filter(
            Activity.user_id == user_id,
            Activity.data_source == "strava",
            Activity.status == "importing",  # Strava 活动的中间状态
        )
        .update(
            {
                Activity.status: "failed",
                Activity.error_message: f"换号绑定：旧 athlete {old_athlete_id} 的导入中断",
            },
            synchronize_session=False,
        )
    )
    logger.info(
        "换号清理 user_id=%d old_athlete_id=%d 清了 %d 条 importing 活动",
        user_id, old_athlete_id, count,
    )
    return count
```

### 3. 重写 `handle_callback` 函数

这是本任务核心。完整替换 `app/strava/service.py:95` 的旧版本：

```python
def handle_callback(db: Session, code: str, state: str, redis: Redis) -> dict:
    """
    Strava OAuth 回调处理。v4 重构要点：

    1. state 一次性消费（verify_state_and_consume）
    2. user 行锁（避免并发 callback 竞态）
    3. **UNIQUE 冲突检测必须在清理旧活动之前**（顺序不能换，否则会误伤自家数据）
    4. 换号清理（_cleanup_old_athlete_activities）
    5. StravaImport 防重复：覆盖 active + paused 两种未完成态

    Args:
        db: SQLAlchemy session
        code: Strava 回调带回的 authorization_code
        state: 本次授权的 state（nonce）
        redis: Redis 客户端

    Returns:
        {"bound": True, "athlete_id": int}

    Raises:
        InvalidStateError: state 失效
        ValueError: 用户不存在 / Strava 响应异常
        BoundByOtherUserError: 该 athlete 已被他人绑定
    """
    import httpx
    from datetime import datetime, timezone
    from app.strava.models import StravaImport
    from app.user.models import User

    # ---- Step 1：一次性消费 state ----
    user_id = verify_state_and_consume(state, redis)

    # ---- Step 2：换 token（内联，不抽新函数——参考现有 service.py:124-177）----
    try:
        resp = httpx.post(
            STRAVA_TOKEN_URL,
            data={
                "client_id": settings.STRAVA_CLIENT_ID,
                "client_secret": settings.STRAVA_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
            },
            timeout=10,
        )
    except httpx.HTTPError:
        logger.error("Strava token 请求网络错误 user_id=%d", user_id)
        raise ValueError("Strava 授权失败")

    if resp.status_code != 200:
        logger.error(
            "Strava token 请求失败 user_id=%d status=%d body=%s",
            user_id, resp.status_code, resp.text[:200],
        )
        raise ValueError("Strava 授权失败")

    try:
        data = resp.json()
    except Exception:
        raise ValueError("Strava 返回非 JSON 响应")

    athlete = data.get("athlete")
    if not athlete or "id" not in athlete:
        raise ValueError("Strava 返回数据缺少 athlete 字段")
    for key in ("access_token", "refresh_token", "expires_at"):
        if key not in data:
            raise ValueError(f"Strava 返回数据缺少 {key} 字段")

    new_athlete_id = athlete["id"]

    # ---- Step 3：user 行锁 + NoResultFound 兜底 ----
    # 为什么用 .first() 而不是 .one()：
    #   .one() 遇到用户不存在会抛 NoResultFound，前端收到 500；
    #   .first() + 显式 raise ValueError 更可控，前端收到 400
    user = (
        db.query(User)
        .filter(User.id == user_id)
        .with_for_update()
        .first()
    )
    if not user:
        raise ValueError(f"用户 {user_id} 不存在")

    # ---- Step 4：UNIQUE 冲突检测（必须在清理之前，顺序不可换）----
    # 如果该 Strava 账号已被其他 VELO 账号绑定，直接拒绝；
    # 不往下走，避免误清自家数据后再被 UNIQUE 挡下（造成数据损失）
    other = (
        db.query(User)
        .filter(
            User.strava_athlete_id == new_athlete_id,
            User.id != user_id,
        )
        .first()
    )
    if other:
        logger.warning(
            "Strava 账号占用 user_id=%d 试图绑定 athlete=%d 但被 user_id=%d 占用",
            user_id, new_athlete_id, other.id,
        )
        raise BoundByOtherUserError("该 Strava 账号已被其他 VELO 账号绑定")

    # ---- Step 5：换号时清理旧 athlete 的 importing 活动 ----
    if user.strava_athlete_id and user.strava_athlete_id != new_athlete_id:
        _cleanup_old_athlete_activities(db, user.id, user.strava_athlete_id)

    # ---- Step 6：写入新 token（expires_at 内联解析，不抽新函数）----
    user.strava_athlete_id = new_athlete_id
    user.strava_access_token = data["access_token"]
    user.strava_refresh_token = data["refresh_token"]
    user.strava_token_expires_at = datetime.fromtimestamp(
        data["expires_at"], tz=timezone.utc,
    )
    db.flush()

    # ---- Step 7：StravaImport 防重复（覆盖 active + paused 两种未完成态）----
    # 为什么检查 paused 而不只是 active：
    #   若上次导入因 token 失效被标 paused，新 callback 若只查 active
    #   会再建一条新 active 任务 → paused+active 并存，调度器混乱
    existing = (
        db.query(StravaImport)
        .filter(
            StravaImport.user_id == user_id,
            StravaImport.status.in_(["active", "paused"]),
        )
        .with_for_update()
        .first()
    )

    if existing:
        # 已有未完成任务 → 复用（若是 paused 重新置 active 让调度器接手）
        if existing.status == "paused":
            existing.status = "active"
            logger.info("复用并激活 paused 导入任务 user_id=%d import_id=%d", user_id, existing.id)
        else:
            logger.info("复用已有 active 导入任务 user_id=%d import_id=%d", user_id, existing.id)
    else:
        # 没有未完成任务 → 新建
        # strava_athlete_id 是 NOT NULL，必须带上
        db.add(StravaImport(
            user_id=user_id,
            strava_athlete_id=new_athlete_id,
            status="active",
        ))
        logger.info("创建新 Strava 导入任务 user_id=%d athlete_id=%d", user_id, new_athlete_id)

    db.commit()
    return {"bound": True, "athlete_id": new_athlete_id}
```

### 4. 改 `app/strava/router.py` 的 callback（替换 task-7.2 的过渡版）

**先确保 router.py 顶部有**：

```python
import logging
logger = logging.getLogger(__name__)
```

没有则加上——否则下面的 `logger.warning/error` 调用会 NameError。

```python
from app.strava.service import (
    verify_state_and_consume,
    handle_callback,
    InvalidStateError,
    BoundByOtherUserError,
)
from app.strava.client import _redis


@router.get("/api/strava/callback", response_class=HTMLResponse)
def callback(code: str, state: str, db: Session = Depends(get_db)):
    """
    Strava OAuth 回调接收点。返回 HTML 页面告诉用户关窗口返回小程序。
    """
    try:
        result = handle_callback(db, code, state, _redis)
    except InvalidStateError as e:
        logger.warning("state 验证失败: %s", e)
        return HTMLResponse(
            content=f"<h2>授权失败</h2><p>{e}</p><p>请返回小程序重新发起绑定。</p>",
            status_code=400,
        )
    except BoundByOtherUserError as e:
        return HTMLResponse(
            content=f"<h2>绑定失败</h2><p>{e}</p>",
            status_code=409,
        )
    except ValueError as e:
        logger.error("handle_callback ValueError: %s", e)
        return HTMLResponse(
            content=f"<h2>授权失败</h2><p>{e}</p>",
            status_code=400,
        )

    return HTMLResponse(
        content="<h2>绑定成功</h2><p>请关闭此窗口返回小程序。</p>",
        status_code=200,
    )
```

---

## 🧪 测试

### 测试 1：首次绑定（happy path）

**文件**：`tests/strava/test_callback.py`

```python
from unittest.mock import patch, MagicMock
from app.strava.service import handle_callback


@patch("app.strava.service.httpx.post")
def test_first_time_bind(mock_post, db, redis_mock, user_factory):
    user = user_factory(strava_athlete_id=None)  # 未绑定
    redis_mock.getdel.return_value = str(user.id).encode()

    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {
        "access_token": "at_xxx",
        "refresh_token": "rt_yyy",
        "expires_at": 1800000000,
        "athlete": {"id": 99001},
    }

    result = handle_callback(db, code="c1", state="nonce1", redis=redis_mock)

    assert result["bound"] is True
    assert result["athlete_id"] == 99001

    db.refresh(user)
    assert user.strava_athlete_id == 99001
    assert user.strava_access_token == "at_xxx"

    # 验证新建了 active StravaImport
    from app.strava.models import StravaImport
    imp = db.query(StravaImport).filter_by(user_id=user.id).first()
    assert imp is not None
    assert imp.status == "active"
```

### 测试 2：重复绑定（已有 active 任务）

```python
@patch("app.strava.service.httpx.post")
def test_rebind_reuses_active_task(mock_post, db, redis_mock, user_factory):
    user = user_factory(strava_athlete_id=99001)
    # 已有 active 任务
    from app.strava.models import StravaImport
    existing = StravaImport(user_id=user.id, strava_athlete_id=99001, status="active")
    db.add(existing)
    db.commit()
    initial_import_id = existing.id

    redis_mock.getdel.return_value = str(user.id).encode()
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {
        "access_token": "at_new",
        "refresh_token": "rt_new",
        "expires_at": 1800000000,
        "athlete": {"id": 99001},  # 同一 athlete
    }

    handle_callback(db, code="c2", state="nonce2", redis=redis_mock)

    # 应复用已有 import，不新建
    imports = db.query(StravaImport).filter_by(user_id=user.id).all()
    assert len(imports) == 1
    assert imports[0].id == initial_import_id
```

### 测试 3：重新激活 paused 任务

```python
@patch("app.strava.service.httpx.post")
def test_rebind_reactivates_paused(mock_post, db, redis_mock, user_factory):
    user = user_factory(strava_athlete_id=99001)
    from app.strava.models import StravaImport
    db.add(StravaImport(user_id=user.id, strava_athlete_id=99001, status="paused"))
    db.commit()

    redis_mock.getdel.return_value = str(user.id).encode()
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {
        "access_token": "at", "refresh_token": "rt",
        "expires_at": 1800000000, "athlete": {"id": 99001},
    }

    handle_callback(db, code="c3", state="n3", redis=redis_mock)

    from app.strava.models import StravaImport
    imp = db.query(StravaImport).filter_by(user_id=user.id).first()
    assert imp.status == "active"  # paused → active
```

### 测试 4：换号（athlete_id 变了）

```python
@patch("app.strava.service.httpx.post")
def test_switch_athlete_cleans_old(mock_post, db, redis_mock, user_factory, activity_factory):
    user = user_factory(strava_athlete_id=99001)
    # 老账号的 importing 活动
    old_act = activity_factory(user_id=user.id, status="importing", data_source="strava")
    # 已完成的活动（不应被动）
    done_act = activity_factory(user_id=user.id, status="completed", data_source="strava")

    redis_mock.getdel.return_value = str(user.id).encode()
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {
        "access_token": "at", "refresh_token": "rt",
        "expires_at": 1800000000, "athlete": {"id": 99002},  # 新 athlete
    }

    handle_callback(db, code="c4", state="n4", redis=redis_mock)

    db.refresh(old_act)
    db.refresh(done_act)
    assert old_act.status == "failed"      # 被清理
    assert done_act.status == "completed"  # 不动
```

### 测试 5：UNIQUE 冲突（被他人占用）

```python
def test_athlete_owned_by_other_user_rejects(db, redis_mock, user_factory):
    attacker = user_factory(strava_athlete_id=99001)  # 已绑定
    victim = user_factory(strava_athlete_id=None)
    redis_mock.getdel.return_value = str(victim.id).encode()

    with patch("app.strava.service.httpx.post") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "access_token": "at", "refresh_token": "rt",
            "expires_at": 1800000000, "athlete": {"id": 99001},  # 想绑已占用的
        }

        from app.strava.service import BoundByOtherUserError
        try:
            handle_callback(db, code="c5", state="n5", redis=redis_mock)
            assert False, "应抛 BoundByOtherUserError"
        except BoundByOtherUserError:
            pass

    # 受害者 token 不应被写入
    db.refresh(victim)
    assert victim.strava_athlete_id is None
```

### 测试 6：顺序验证 —— UNIQUE 在 cleanup 前

这是本任务**最关键**的测试——验证 v1 审判抓到的顺序问题在 v2 已修。

```python
def test_unique_check_before_cleanup(db, redis_mock, user_factory, activity_factory):
    """
    场景：user 已绑定 athlete=A，现在试图绑 athlete=B（新账号），
    但 athlete=B 已被其他 user 占用。
    期望：抛 BoundByOtherUserError 且 user 的 importing 活动**不被清理**。
    """
    attacker = user_factory(strava_athlete_id=99002)
    user = user_factory(strava_athlete_id=99001)
    old_act = activity_factory(user_id=user.id, status="importing", data_source="strava")

    redis_mock.getdel.return_value = str(user.id).encode()
    with patch("app.strava.service.httpx.post") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "access_token": "at", "refresh_token": "rt",
            "expires_at": 1800000000, "athlete": {"id": 99002},
        }

        from app.strava.service import BoundByOtherUserError
        try:
            handle_callback(db, code="c6", state="n6", redis=redis_mock)
        except BoundByOtherUserError:
            pass

    db.refresh(old_act)
    assert old_act.status == "importing"  # 没被错误清理（v1 bug 修复验证）
```

---

## 📦 Commit 指令

```bash
git add app/strava/service.py app/strava/router.py tests/strava/test_callback.py

git commit -m "$(cat <<'EOF'
feat(strava): 任务 7.3 callback 防重复绑定 + 换号清理（修 C2 + I6）

重写 handle_callback：
- 使用 task-7.2 的 verify_state_and_consume
- user 行锁（SELECT FOR UPDATE）
- UNIQUE 冲突检测置于清理之前（避免被占用场景误伤自家数据）
- 换号场景 → _cleanup_old_athlete_activities（清 importing 活动）
- StravaImport 防重复：覆盖 active+paused（paused 自动重激活）
- 新建 StravaImport 时带 strava_athlete_id（NOT NULL 要求）

新增：
- _cleanup_old_athlete_activities() 函数
- BoundByOtherUserError 异常

Activity 状态值对齐 'importing'（非 pending/processing），data_source='strava'。

测试：6 个用例覆盖 happy / 复用 / 重激活 / 换号 / UNIQUE 冲突 / 顺序验证。
EOF
)"
```

---

## ✅ 自检三问

**1. 10 分钟挑战**：讲清 callback 改了啥？

> 三件事：
> 1. **顺序更正**：UNIQUE 检测必须先于清理旧活动（上一版本会误伤数据）
> 2. **活动状态值对齐**：Strava 活动中间态是 'importing'（非 pending/processing）
> 3. **防重复升级**：StravaImport 查询覆盖 active+paused，paused 自动重激活

**2. 崩溃场景**：Step 3 之后崩了怎么办？

> db.commit() 在最后——中间任何步骤崩了，整个事务 rollback，user 字段和 StravaImport 记录都不会半写。唯一副作用：state 已被 verify_state_and_consume 消耗掉（这是设计内的——失败就让用户重新发起授权）。

**3. 边界纪律**：有没有做 spec 没要求的"顺手优化"？

> 没有。严格 spec §2.6 范围。没有顺手改 refresh_token 逻辑（留 task-7.6）、没有动 Webhook（task-7.4）、没有重构 handle_manual_sync（task-7.6）。
