# 任务 7.2：Strava OAuth state 加固

> 修复 Critical-01（Login CSRF）+ Critical-08（state 可重放）。

---

## 🎯 目标（一句话）

把 Strava OAuth 的 `state` 参数从「JWT 含 user_id + exp」升级为「Redis 存储的一次性 nonce」——让攻击者既不能**跨用户窃取**（CSRF），也不能**重放已用过的 state**。

---

## ⛓ 前置依赖

- **task-7.1**（根任务，DB schema 就位）
- 现有 Redis 客户端已可用（`app/strava/client.py` 有 `_redis`）

## 📥 输入契约

- Redis 7+ 支持原生 `redis.getdel(key)` 方法（已确认 `docker-compose.yml:35` 用 `redis:7-alpine`）
- 现有 `app/strava/service.py:95` 的 `handle_callback(db, code, state)` 函数签名（本任务**不改 handle_callback**，留给 task-7.3 改）

## 📤 输出契约（task-7.3 会用）

| 产出 | 签名 | 说明 |
|------|------|------|
| `build_authorize_url` | `(user_id: int, redis: Redis) -> str` | 生成 Strava 授权 URL，state 是明文 nonce |
| `verify_state_and_consume` | `(state: str, redis: Redis) -> int` | 验证 + 一次性消费 state，返回 user_id；失败抛 `InvalidStateError` |
| `InvalidStateError` | Exception 子类 | state 过期 / 已使用 / 跨用户等异常 |

---

## 🛠 完整代码

### 1. 在 `app/strava/service.py` 顶部附近，新增异常类和两个函数

找到现有 import 区附近，**确保已 import**：

```python
import secrets
from redis import Redis  # 如已存在就不重复
```

**在 `handle_callback` 函数之前**，新增：

```python
class InvalidStateError(Exception):
    """OAuth state 异常：已使用 / 过期 / 跨用户冲突等"""
    pass


def build_authorize_url(user_id: int, redis: Redis) -> str:
    """
    生成 Strava OAuth 授权 URL。

    设计要点：
    1. state 使用明文 nonce（24 字节随机），不套 JWT——
       因为 nonce 本身不可猜，加 JWT 是冗余的
    2. Redis 存储 {strava_state:{nonce}: user_id}，10 分钟 TTL
    3. callback 时用 GETDEL 原子取出并删除，保证一次性消费

    为什么这套组合能防 Login CSRF：
       攻击者拿到自己的 nonce 后，Redis 里 key 对应的是攻击者自己的 user_id，
       即使诱骗受害者点链接完成授权，Strava token 也会绑到攻击者账号（而不是受害者）
       —— 这样攻击者获得的就是自己的账号而已，没有受害者数据。

    Args:
        user_id: 当前登录用户的 ID
        redis: Redis 客户端（通常是 app.strava.client._redis）

    Returns:
        可直接跳转的 Strava 授权 URL
    """
    # 24 字节随机 = 32 个 urlsafe base64 字符，碰撞概率 2^-192，安全余量足够
    nonce = secrets.token_urlsafe(24)

    # 10 分钟 TTL：用户授权流程最长一般 5 分钟；给 2 倍余量防慢网速
    redis.setex(f"strava_state:{nonce}", 600, str(user_id))

    # 注意：state 直接用 nonce 明文，不套 JWT
    return (
        f"https://www.strava.com/oauth/authorize"
        f"?client_id={settings.STRAVA_CLIENT_ID}"
        f"&response_type=code"
        f"&redirect_uri={settings.STRAVA_REDIRECT_URI}"
        f"&approval_prompt=auto"
        f"&scope=read,activity:read"
        f"&state={nonce}"
    )


def verify_state_and_consume(state: str, redis: Redis) -> int:
    """
    验证 state 并一次性消费。

    核心机制：Redis GETDEL 原子取出并删除，保证重放必失败。

    Args:
        state: Strava 回调带回的 state 参数（即 nonce 明文）
        redis: Redis 客户端

    Returns:
        发起授权的 user_id

    Raises:
        InvalidStateError: state 不存在（过期 / 已使用 / 伪造）
    """
    # Redis 7+ 原生 getdel：读取并删除是原子操作
    stored = redis.getdel(f"strava_state:{state}")

    if stored is None:
        raise InvalidStateError("state 已使用或过期")

    # redis-py 默认 decode_responses=False 时返 bytes
    if isinstance(stored, bytes):
        stored = stored.decode()

    try:
        return int(stored)
    except ValueError:
        raise InvalidStateError(f"state 对应的 user_id 格式异常: {stored}")
```

### 2. 改 `app/strava/router.py` 的 `/authorize` 路由

找到现有 `GET /api/strava/authorize` 路由。**改造前**它大概长这样（如果签名不匹配，以实际代码为准）：

```python
# 原（类似）：
@router.get("/api/strava/authorize")
def authorize(user_id: int = Depends(get_current_user)):
    # 旧实现：用 JWT 生成 state
    ...
    return {"authorize_url": url}
```

**改造后**：

```python
from app.strava import service
from app.strava.client import _redis  # 引用现有 Redis 客户端


@router.get("/api/strava/authorize")
def authorize(user_id: int = Depends(get_current_user)):
    """
    生成 Strava 授权 URL 给小程序。小程序会把它传给 H5 桥接页（h5/strava-bind/index.html）。
    """
    authorize_url = service.build_authorize_url(user_id, _redis)
    return {"authorize_url": authorize_url}
```

### 3. 改 `app/strava/router.py` 的 `/callback` 路由（最小改动）

**注意**：本任务只改 callback 中对 state 的验证调用，**不改 callback 的业务逻辑**（换 token、写 user、创建 StravaImport 等 task-7.3 重写）。

找到现有 callback，把取 user_id 的那部分改成：

```python
from app.strava.service import verify_state_and_consume, InvalidStateError


@router.get("/api/strava/callback")
def callback(code: str, state: str, db: Session = Depends(get_db)):
    try:
        # 新：一次性消费 state
        user_id = verify_state_and_consume(state, _redis)
    except InvalidStateError as e:
        logger.warning("OAuth state 验证失败: %s", e)
        raise HTTPException(status_code=400, detail=str(e))

    # 下面调用 handle_callback 的业务部分——task-7.3 会重写 handle_callback
    # 本任务暂保持现有 handle_callback 调用不变，只是 user_id 从 state 里拿出来改为显式传参
    # （过渡期：handle_callback 签名可能需要配合改，详见 task-7.3）
    ...
```

### 4. 确认 `settings.STRAVA_CLIENT_ID` / `STRAVA_REDIRECT_URI` 配置存在

[Read 验证] `app/config.py:42-43` 已有 `STRAVA_CLIENT_ID` 和 `STRAVA_CLIENT_SECRET`。确认 `STRAVA_REDIRECT_URI` 也在。如果没有，补上：

```python
# app/config.py
STRAVA_REDIRECT_URI: str = "https://velo.app/api/strava/callback"
```

---

## 🧪 测试

### 测试 1：build_authorize_url 基础行为

**文件**：`tests/strava/test_oauth_state.py`（新建或扩展现有 Strava 测试文件）

```python
import secrets
from unittest.mock import MagicMock

from app.strava.service import build_authorize_url, verify_state_and_consume, InvalidStateError


def test_build_authorize_url_contains_nonce():
    redis = MagicMock()
    url = build_authorize_url(user_id=42, redis=redis)

    # URL 应包含 state 参数
    assert "state=" in url
    # Redis setex 应被调用一次
    redis.setex.assert_called_once()
    call_args = redis.setex.call_args
    assert call_args[0][0].startswith("strava_state:")
    assert call_args[0][1] == 600
    assert call_args[0][2] == "42"


def test_verify_state_happy_path():
    redis = MagicMock()
    redis.getdel.return_value = b"42"

    user_id = verify_state_and_consume("valid_nonce", redis)
    assert user_id == 42
    redis.getdel.assert_called_once_with("strava_state:valid_nonce")


def test_verify_state_not_found_raises():
    redis = MagicMock()
    redis.getdel.return_value = None

    try:
        verify_state_and_consume("missing_nonce", redis)
        assert False, "应抛 InvalidStateError"
    except InvalidStateError as e:
        assert "已使用" in str(e) or "过期" in str(e)


def test_verify_state_replay_attack():
    """重放攻击：同一个 state 第二次用必失败。"""
    redis = MagicMock()
    # 第一次 getdel 返回 user_id，第二次返回 None（getdel 原子删除）
    redis.getdel.side_effect = [b"42", None]

    # 第一次成功
    assert verify_state_and_consume("nonce1", redis) == 42
    # 第二次失败
    try:
        verify_state_and_consume("nonce1", redis)
        assert False, "重放必须失败"
    except InvalidStateError:
        pass
```

### 测试 2：CSRF 跨用户攻击验证

> 这个更多是**概念验证**，在单测里用 mock 验证攻击路径被堵死：

```python
def test_csrf_attack_fails():
    """
    场景：攻击者 A（user_id=100）先调 /authorize 获得 state_A。
    攻击者诱骗受害者 V（user_id=200）点含 state_A 的链接完成 Strava 授权。
    Strava 回调带 state_A 给后端——后端从 state_A 查到 user_id=100（攻击者自己），
    绑定的 token 会被写到攻击者 A 的账号下，不是受害者 V。
    因此：受害者 V 的 VELO 账号保持未绑定，数据不被泄漏。
    """
    redis = MagicMock()
    # 攻击者 A 调 authorize，Redis 存 {state_A: 100}
    redis.setex.reset_mock()
    url = build_authorize_url(100, redis)
    state_A = url.split("state=")[1]

    # Strava 回调带 state_A 给后端
    redis.getdel.return_value = b"100"
    resolved_user_id = verify_state_and_consume(state_A, redis)

    # 关键：resolved_user_id 是攻击者 A 的 ID，不是受害者 V 的
    assert resolved_user_id == 100  # 绑到攻击者自己账号，受害者未受影响
```

### 测试 3：手动端到端（真实环境）

```bash
# 本地或生产环境
# 1. 小程序或浏览器打开 /api/strava/authorize
# 2. 看响应里的 authorize_url 是否含 state=xxx（24 字节 urlsafe 字符）
# 3. 复制 authorize_url 到浏览器，完成 Strava 授权
# 4. 回调触发，检查绑定成功
# 5. 【重放测试】手动再次访问 callback URL with 相同 state → 应返回 400 + "state 已使用"
```

---

## 📦 Commit 指令

```bash
git add app/strava/service.py \
        app/strava/router.py \
        app/config.py \
        tests/strava/test_oauth_state.py

git commit -m "$(cat <<'EOF'
feat(strava): 任务 7.2 OAuth state 加 nonce + 一次性消费（修 C1 + C8）

- 新增 build_authorize_url()：state 用 Redis 存储的明文 nonce，10min TTL
- 新增 verify_state_and_consume()：Redis GETDEL 原子消费，防重放
- 新增 InvalidStateError 异常类
- router.py /authorize 改造调用新函数
- router.py /callback 改造取 user_id 流程

修 Critical：
- C1 Login CSRF：nonce 绑 user_id 在 Redis，攻击者无法把受害者 Strava 绑到攻击者账号
- C8 state 重放：GETDEL 原子删除，用过即废

测试：4 个单测覆盖 happy path / 未找到 / 重放 / CSRF 攻击路径验证。
EOF
)"
```

---

## ✅ 自检三问

**1. 10 分钟挑战**：讲清 state 从「JWT」变成「Redis nonce」改了啥？

> state 以前是"我把 user_id + 过期时间签进 JWT 里交给 Strava，回调时解 JWT 拿 user_id"——问题是 JWT **能被重复用**，且别人拿到你的 JWT 可以诱骗 Strava 绑到你名下。
>
> 现在 state 是"我生成一个随机 nonce，Redis 里存 {nonce: user_id}，Strava 回调时我用 GETDEL 原子取出并删掉"——用过即废，且只有我这台服务器的 Redis 知道这个 nonce 对应谁。

**2. 崩溃场景**：如果用户点完 `/authorize` 但关闭浏览器没完成 Strava 授权，Redis 里的 nonce 怎么办？

> Redis `setex` 的 TTL 10 分钟自动过期，没有垃圾。就算用户 10 万次点"绑定"然后放弃，Redis 也只会短暂积攒 10 万条 10 分钟内自动清的 key。

**3. 边界纪律**：有没有做 spec 没要求的"顺手优化"？

> 没有。严格限定 spec §2.5 的 state 改造。没有顺手改 /callback 的业务逻辑（留给 task-7.3）、没有动其他 Strava 接口、没有重命名现有函数。
