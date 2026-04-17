# 任务 7.4：Webhook subscription_id 校验

> 修 Critical-04：Webhook 端点当前裸奔——无来源校验，任意人伪造 `POST /api/strava/webhook` 都能触发后续 `service.handle_webhook_event(db, payload)` 逻辑。

---

## 🎯 目标（一句话）

给 `POST /api/strava/webhook` 加一道门——只接受 Strava 官方订阅发来的事件（靠 payload 里的 `subscription_id` 匹配我们初次订阅时记下的 ID）。

---

## ⛓ 前置依赖

**无**。可以和 7.2/7.3/7.5/7.7/7.8 并行。

## 📥 输入契约

**现有代码事实核对**（预读已完成）：

| 项目 | 位置 | 事实 |
|------|------|------|
| webhook POST 路由 | `app/strava/router.py:147-164` | 现名 `webhook_receive`，函数签名 `(payload: dict, db: Session)` |
| webhook GET 路由 | `app/strava/router.py:126-144` | `webhook_verify`，用 `settings.STRAVA_WEBHOOK_VERIFY_TOKEN`（本任务不改）|
| Settings 类 | `app/config.py:15-51` | 已有 `STRAVA_WEBHOOK_VERIFY_TOKEN`，**无 `STRAVA_WEBHOOK_SUBSCRIPTION_ID`** |
| api 服务 env | `docker-compose.yml:45-54` | 已传 `STRAVA_WEBHOOK_VERIFY_TOKEN`，**未传 SUBSCRIPTION_ID** |
| .env.example | 项目根目录 | 需预读确认现状 |

## 📤 输出契约

| 产出 | 说明 |
|------|------|
| `STRAVA_WEBHOOK_SUBSCRIPTION_ID` 环境变量 | 三处同步：`app/config.py` / `.env.example` / `docker-compose.yml` |
| `POST /api/strava/webhook` 加两层校验 | 未配置 → 503；subscription_id 不匹配 → 403 |
| 订阅操作手册 | 写在本任务的"部署说明"小节——首次部署生产要跑一次 curl 创建订阅 |

---

## 🛠 完整代码

### 1. `app/config.py` 加字段

找到 `Settings` 类内部、`STRAVA_WEBHOOK_VERIFY_TOKEN` 定义旁边，**加一行**：

```python
# Webhook 订阅 ID——初次订阅 Strava Push Subscription 时 Strava 返回的 id
# 用于 Webhook 事件真伪校验（payload 里带，不匹配则拒收）
# 未配置时 POST /webhook 会返 503，防止裸奔
STRAVA_WEBHOOK_SUBSCRIPTION_ID: str = ""
```

> **为什么用 str 而不用 int**：Strava 官方返回的 id 是整数，但环境变量本身是字符串，留 str 方便未配置时的空值判定（`if not xxx`），接口里再 `int(...)` 转换一次即可。

### 2. `.env.example` 加一行

先读现状，找到 `STRAVA_WEBHOOK_VERIFY_TOKEN=` 这一行，在它**下面**加：

```
# Strava Webhook 订阅 ID
# 初次部署时手动跑 curl 创建订阅（见 docs/plans/phase4/task-7.4.md 部署说明），
# 把返回的 id 填这里。未配置 POST /webhook 会返 503
STRAVA_WEBHOOK_SUBSCRIPTION_ID=
```

### 3. `docker-compose.yml` `api` 服务加 env 传递

在 `services.api.environment` 下，`STRAVA_WEBHOOK_VERIFY_TOKEN:` 那行**下面**加一行：

```yaml
      STRAVA_WEBHOOK_VERIFY_TOKEN: ${STRAVA_WEBHOOK_VERIFY_TOKEN}
      STRAVA_WEBHOOK_SUBSCRIPTION_ID: ${STRAVA_WEBHOOK_SUBSCRIPTION_ID}   # 新增
```

### 4. `app/strava/router.py` 改造 `webhook_receive`

替换 `@router.post("/webhook")` 这段函数（当前 `router.py:147-164`）：

```python
from fastapi import HTTPException


@router.post("/webhook")
def webhook_receive(
    payload: dict,
    db: Session = Depends(get_db),
):
    """
    Webhook 事件接收——Strava 有新活动时主动推送到这里。

    v4 加固：用 payload.subscription_id 校验来源真实性。
    Strava 不提供 HMAC 签名（官方文档已确认），所以靠两点联合防伪：
    1. subscription_id：初次订阅时 Strava 返回的唯一 id（伪造者不知道）
    2. HTTPS：Caddy 强制 TLS，传输层防中间人

    为什么不用 IP 白名单：
        Strava 官方不承诺 Webhook 发送方 IP 稳定，维护 IP 表会误杀合法回调。
    为什么不用自定义 header 密钥：
        Strava 不支持在 Webhook 里加自定义 header。

    状态码约定：
    - 未配置 SUBSCRIPTION_ID: 503（系统未就绪，应由运维修 env）
    - subscription_id 不匹配: 403（伪造，拒收）
    - 正常: 200（Strava 要求 2 秒内响应，业务处理走 service 内部队列）
    """
    # ---- 第 1 道门：配置兜底 ----
    # getattr 兜底防止 AttributeError（万一未来 Settings 没声明这字段）
    expected_sub_id_str = getattr(settings, "STRAVA_WEBHOOK_SUBSCRIPTION_ID", "")
    if not expected_sub_id_str:
        # 注意：判空用 `not`，因为环境变量默认值是 "" 空串——空串是合法未配置态
        logger.error("Webhook 未配置 STRAVA_WEBHOOK_SUBSCRIPTION_ID")
        raise HTTPException(status_code=503, detail="Webhook 订阅未配置")

    try:
        expected_sub_id = int(expected_sub_id_str)
    except ValueError:
        # 配置了但格式不对（比如被填了非数字）——同样视为未配置
        logger.error(
            "STRAVA_WEBHOOK_SUBSCRIPTION_ID 格式非法: %r", expected_sub_id_str
        )
        raise HTTPException(status_code=503, detail="Webhook 订阅配置格式错误")

    # ---- 第 2 道门：payload 校验 ----
    incoming_sub_id = payload.get("subscription_id")
    if incoming_sub_id != expected_sub_id:
        logger.warning(
            "Webhook subscription_id 不匹配: 收到=%r 期望=%d",
            incoming_sub_id, expected_sub_id,
        )
        raise HTTPException(status_code=403, detail="Forbidden")

    # ---- 真实事件：走原有处理逻辑 ----
    service.handle_webhook_event(db, payload)

    # Strava 要求 Webhook 端点始终返回 200
    return {"status": "ok"}
```

**import 补充**（文件顶部确认已有 / 没有则加）：

```python
import logging
logger = logging.getLogger(__name__)
```

### 5. GET /webhook（订阅验证端点）**不改**

理由：GET 端点已有 `hub_verify_token` 校验（`router.py:141`），且只在**初次订阅**时被 Strava 调用一次，风险面和 POST 不同。本任务专注 POST。

---

## 🚀 部署说明（运维必读）

> 这节**写进 task commit 的最后一行说明里**，因为初次部署生产要手动跑一次。

### 第一次部署：创建 Strava Push Subscription

Strava 不像企业微信有后台界面——订阅关系靠 API 创建。

```bash
# 1. 在生产服务器上跑一次（替换大写部分）：
curl -X POST "https://www.strava.com/api/v3/push_subscriptions" \
  -F client_id=YOUR_CLIENT_ID \
  -F client_secret=YOUR_CLIENT_SECRET \
  -F callback_url=https://YOUR_DOMAIN/api/strava/webhook \
  -F verify_token=YOUR_VERIFY_TOKEN

# 2. Strava 会先 GET /api/strava/webhook 验证 verify_token（现有代码已处理）
# 3. 验证通过后返回类似：
#    {"id": 123456, "application_id": ...}
# 4. 把返回的 id（这里是 123456）填到 .env：
#    STRAVA_WEBHOOK_SUBSCRIPTION_ID=123456
# 5. 重启 api 容器：
#    sudo docker compose restart api
```

### 查看现有订阅

```bash
curl -G "https://www.strava.com/api/v3/push_subscriptions" \
  -d client_id=YOUR_CLIENT_ID \
  -d client_secret=YOUR_CLIENT_SECRET
```

### 删除订阅（换域名时用）

```bash
curl -X DELETE "https://www.strava.com/api/v3/push_subscriptions/${SUB_ID}" \
  -F client_id=YOUR_CLIENT_ID \
  -F client_secret=YOUR_CLIENT_SECRET
```

---

## 🧪 测试

**文件**：`tests/strava/test_webhook.py`（新建）

```python
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def test_webhook_rejects_when_not_configured(monkeypatch):
    """配置空串时返 503。"""
    monkeypatch.setattr(settings, "STRAVA_WEBHOOK_SUBSCRIPTION_ID", "")

    client = TestClient(app)
    resp = client.post("/api/strava/webhook", json={"subscription_id": 12345})
    assert resp.status_code == 503
    assert "未配置" in resp.json()["detail"]


def test_webhook_rejects_malformed_config(monkeypatch):
    """配置非数字也视为未配置（503）。"""
    monkeypatch.setattr(settings, "STRAVA_WEBHOOK_SUBSCRIPTION_ID", "abc")

    client = TestClient(app)
    resp = client.post("/api/strava/webhook", json={"subscription_id": 12345})
    assert resp.status_code == 503


def test_webhook_rejects_wrong_subscription_id(monkeypatch):
    """subscription_id 不匹配返 403。"""
    monkeypatch.setattr(settings, "STRAVA_WEBHOOK_SUBSCRIPTION_ID", "999")

    client = TestClient(app)
    resp = client.post("/api/strava/webhook", json={"subscription_id": 12345})
    assert resp.status_code == 403


def test_webhook_accepts_matching_subscription_id(monkeypatch):
    """subscription_id 匹配则走 service 并返 200。"""
    monkeypatch.setattr(settings, "STRAVA_WEBHOOK_SUBSCRIPTION_ID", "12345")

    # mock handle_webhook_event 防止真实 DB 调用
    from app.strava import service
    calls = []
    monkeypatch.setattr(
        service, "handle_webhook_event",
        lambda db, payload: calls.append(payload),
    )

    client = TestClient(app)
    resp = client.post(
        "/api/strava/webhook",
        json={"subscription_id": 12345, "object_type": "activity"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    assert len(calls) == 1
    assert calls[0]["subscription_id"] == 12345


def test_webhook_handles_missing_subscription_id_in_payload(monkeypatch):
    """payload 里没 subscription_id（伪造者漏填）也拦下。"""
    monkeypatch.setattr(settings, "STRAVA_WEBHOOK_SUBSCRIPTION_ID", "12345")

    client = TestClient(app)
    resp = client.post("/api/strava/webhook", json={"object_type": "activity"})
    assert resp.status_code == 403
```

**手工验证**（生产部署后）：

```bash
# 1. 无 env 配置下测试（应 503）
curl -X POST https://YOUR_DOMAIN/api/strava/webhook \
  -H "Content-Type: application/json" \
  -d '{"subscription_id": 12345}'

# 2. 配好 env 后，带错 id 测试（应 403）
curl -X POST https://YOUR_DOMAIN/api/strava/webhook \
  -H "Content-Type: application/json" \
  -d '{"subscription_id": 99999999}'

# 3. 带正确 id 测试（应 200）
curl -X POST https://YOUR_DOMAIN/api/strava/webhook \
  -H "Content-Type: application/json" \
  -d '{"subscription_id": REAL_ID, "object_type": "activity", "aspect_type": "create"}'
```

---

## 📦 Commit 指令

```bash
git add app/config.py \
        app/strava/router.py \
        docker-compose.yml \
        .env.example \
        tests/strava/test_webhook.py

git commit -m "$(cat <<'EOF'
feat(strava): 任务 7.4 Webhook subscription_id 校验（修 C4）

为 POST /api/strava/webhook 加双门校验：
- 第 1 道门：STRAVA_WEBHOOK_SUBSCRIPTION_ID 未配置或格式非法 → 503
- 第 2 道门：payload.subscription_id 不匹配 → 403

改动文件：
- app/config.py 加字段 STRAVA_WEBHOOK_SUBSCRIPTION_ID（str）
- .env.example 加示例行 + 操作说明
- docker-compose.yml api.environment 加传递
- app/strava/router.py webhook_receive 加两层校验

初次部署生产需跑 curl 创建 Strava Push Subscription（详见 task 文档部署说明），
把返回的 id 填到 .env 的 STRAVA_WEBHOOK_SUBSCRIPTION_ID 变量。

测试：5 个用例覆盖未配置 / 格式非法 / 不匹配 / 匹配 / payload 漏字段。
EOF
)"
```

---

## ✅ 自检三问

**1. 10 分钟挑战**：讲清 Webhook 加了什么校验？

> 原先 Webhook 裸奔——谁都能 POST 过来触发业务。现在加两道门：
> - 第 1 道：我们自己的 env 没配 SUBSCRIPTION_ID → 直接 503（系统未就绪）
> - 第 2 道：请求 payload 里带的 subscription_id 和我们记的对不上 → 403（是伪造）
>
> ID 怎么来的？首次部署跑一次 curl 向 Strava 订阅，Strava 返回一个 id，写进 .env。

**2. 崩溃场景**：如果 subscription_id 校验通过但 `service.handle_webhook_event` 抛异常怎么办？

> 异常会冒泡到 FastAPI，变成 500 → Strava 那边判定失败，按 Strava 文档最多重试 3 次（间隔分钟级）。要是一直失败，Strava 会把订阅标 unreachable（官方文档描述 "permanent failure"）。应对：`service.handle_webhook_event` 内部该吞的吞（已有实现见现有代码）；真崩溃也不怕，**第 2 期 scheduler 的定时拉取是兜底**——新活动最终还是会被拉到。

**3. 边界纪律**：有没有做 spec 没要求的"顺手优化"？

> 没有。严格 spec §2.7 范围：
> - 没改 GET /webhook 的 verify_token 逻辑（虽然也能加 subscription_id，但 GET 是一次性订阅验证，风险面和 POST 不同）
> - 没重写 `service.handle_webhook_event`（现有代码本任务不碰）
> - 没加 Redis 限速（webhook 不是用户端接口，Strava 官方限流足够）
