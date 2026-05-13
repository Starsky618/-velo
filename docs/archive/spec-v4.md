# VELO v4 技术规格文档 — 前端反馈环闭合 + Strava 集成加固

> **写给读者的开场白**
>
> VELO 第 4 期核心目标：**把后端早就做好的"成就数据"（通知、荣誉、Strava 同步）真正送到用户眼前**。
>
> 前三期把后厨搭起来了，菜都做好了，但一直没有服务员把菜端到顾客桌上。第 4 期就是装修大堂、派服务员、顺手修补后厨早就发现但一直没修的漏洞。
>
> 本期特别把 Step 5 故障分析里抓出的 8 条 Critical 级风险明确写入 spec，逐条给出防御代码位置，不留后账。
>
> **本 spec 是 v1 修订版**：v0 草案经 Step 7 双重审判抓出 12 条 Critical（多数是"凭记忆写 spec"的虚构引用）。本版已全部修正，所有代码引用均基于实际 Read / grep 核实。
>
> **本期工期估计**：1 周编码 + 2 天测试/部署。

---

## 0. 架构总览

### 0.1 代码侧事实表（Pre-write check 结果 · 必读）

⚠ **本节是 v0 → v1 修订的关键新增**。spec 里所有涉及"现有代码"的引用，都先对齐到下面这张事实表。以后别再凭记忆写。

| 类别 | 事实 | 证据（文件:行号）|
|------|------|-----------------|
| **StravaImport.status 值域** | 只有三个值：`'active'`（进行中）/ `'paused'`（暂停/卡死）/ `'completed'`（完成）。**无 pending / running / stalled / done** | `app/strava/models.py:14-31` 注释 + `:73` server_default='active' |
| **StravaImport.updated_at 类型** | naive datetime（`DateTime` 无 `timezone=True`）。和 `datetime.now(UTC)` 相减会 TypeError。**注**：同表 `cursor_before` 已用 `DateTime(timezone=True)`，本期仅 `updated_at` 需迁移 | `app/strava/models.py:77` 周围 |
| **Notification 字段** | event_type / segment_id / activity_id / effort_id / elapsed_time / rank / rival_user_id / expires_at / created_at。**无 is_read 字段**（本期需要新建） | `app/notification/models.py:45-99` |
| **event_type 值域** | CHECK 约束：`'pr'` / `'kom'` / `'kom_lost'` | `app/notification/models.py:95` |
| **Notification 外键策略** | segment_id 是 `ondelete="CASCADE", nullable=False`；activity_id 是 `ondelete="CASCADE", nullable=True`。**要改 SET NULL 必须先 drop 外键 + alter nullable** | `app/notification/models.py:49-59` |
| **_CYCLING_TYPES 集合** | 现有代码已有 5 种：`{"Ride", "VirtualRide", "EBikeRide", "Handcycle", "Velomobile"}` | `app/strava/import_scheduler.py:43` |
| **Strava OAuth 核心函数** | `handle_callback(db, code, state)` —— 不是 handle_oauth_callback。现有逻辑把 code→token 交换内联在此函数 | `app/strava/service.py:95` |
| **其他现有 Strava 函数** | `ensure_valid_token(db, user, force=False)` / `handle_manual_sync(db, user_id)` / `run_import_tick()` | `service.py:225, 445` + `import_scheduler.py:46` |
| **Strava 响应 athlete 结构** | token 响应中 athlete 嵌套：`data["athlete"]["id"]` | `app/strava/service.py:156-166` |
| **User Strava 字段** | `strava_athlete_id`（BigInt, UNIQUE）/ `strava_access_token` / `strava_refresh_token` / `strava_token_expires_at`（有 timezone） | `app/user/models.py:74-79` |
| **Redis 版本** | Redis 7-alpine（支持原生 `redis.getdel(key)`） | `docker-compose.yml:35` |
| **已装但未用的调度库** | `rq-scheduler>=0.13.1` 已在 requirements.txt。**本期决定不用**（只一个 tick 函数，用常驻脚本更直观），见 §4.1 | requirements.txt |
| **Caddyfile 当前结构** | 监听 `:80`，无域名块（域名未备案）。加 H5 路由要加在现有 `:80 {...}` 块内 | `Caddyfile:7` |
| **部署缺失** | 无 scheduler 容器（docker-compose.yml 无此服务），即 `run_import_tick()` **从未被调度** | `docker-compose.yml:17-107` |
| **部署现有服务** | db / redis / api / worker / cleanup / caddy（6 个） | `docker-compose.yml:18-113` |

### 0.2 设计原则

1. **单向数据流铁律**：前端只从后端拿数据展示（GET），状态变更只能由后端执行（前端发 POST/PUT 表达意图）
2. **前端是消费者、后端是生产者**：本期没有新增任何业务逻辑，只是**把已有数据端到用户眼前**
3. **骨架终态 + 肌肉分期**：埋下 3 颗种子（activity_type、Strava 过滤已存在、解析器分流）支撑未来多运动扩展
4. **Critical 风险前置**：8 条 Critical 全部本期修完，不允许带进第 5 期
5. **代码引用必查**：spec 里所有字段名、函数名、状态值，写之前都 grep / Read 核实（v0 教训）

### 0.3 数据流全景（5 个核心流）

```
流 1：首页小红点显示
  小程序 onShow 
    └→ 读本地免打扰开关（wx.getStorageSync）
       ├→ true → 跳过不亮
       └→ false → GET /api/notifications?unread_only=true&page_size=1
                   └→ 后端查 notifications WHERE user_id AND is_read=false AND expires_at>now()
                      └→ 返回 { unread_count: N, items: [最近一条] }
                         └→ 小程序在首页右上角铃铛旁画红点

流 2：通知列表查看 + 标已读
  小程序进"通知"页 
    ├→ GET /api/notifications?page=1&page_size=20 （拿列表）
    └→ POST /api/notifications/mark-all-read （标已读，并行）
       └→ 后端 UPDATE notifications SET is_read=true 
             WHERE user_id=X AND is_read=false
          └→ 返回 { marked: 3 }
             └→ 前端清红点状态

流 3：点单条通知跳转
  读通知字段（event_type ∈ {'pr','kom','kom_lost'}, segment_id, activity_id）
    └→ 所有类型都跳赛段详情页：/pages/segment?id=segment_id
    └→ 上游实体已被删（外键 SET NULL）→ 显示"该记录已失效"兜底

流 4：Strava 绑定
  Step A：小程序 GET /api/strava/authorize
    └→ 后端生成 nonce（写 Redis，10min TTL），返回 authorize_url
       格式：https://www.strava.com/oauth/authorize?client_id=X&redirect_uri=Y&state={nonce}
    └→ 小程序 navigateTo web-view，src = velo-h5-domain/strava/bind?url=ENCODED_AUTHORIZE_URL
       └→ H5 显示"前往 Strava 授权"按钮

  Step B：用户点按钮
    └→ window.location.href = authorize_url （跳 Strava）
       └→ 用户在 Strava 登录、点"允许"

  Step C：Strava 回调 GET /api/strava/callback?code=X&state={nonce}
    └→ 后端（顺序严格按下列步骤，顺序不可调换）：
       1. Redis GETDEL strava_state:{nonce} → 取出 user_id，命中即删（一次性）
       2. 用 code 换 access_token/refresh_token（内联 httpx 请求）
       3. SELECT user FOR UPDATE（行锁）
       4. 🔑 UNIQUE 冲突检测（必须先查）：
          该 athlete_id 是否已被其他 user 绑定？若是 → 直接抛错，不往下走
          （这一步必须在清理之前，否则"别人占用 + 清自家活动"会误伤数据）
       5. 换号清理：若 user.strava_athlete_id 存在且 != 新 athlete_id → 调 _cleanup_old_athlete_activities
          （仅清 Strava 来源 + status='importing' 的活动，不动 completed 历史）
       6. UPDATE users SET strava_* = ...（含 datetime.fromtimestamp(expires_at, tz=UTC)）
       7. SELECT StravaImport WHERE user_id AND status='active' FOR UPDATE
          - 存在 → 复用
          - 不存在 → INSERT status='active'
       8. 返回 HTML "绑定成功，请关闭窗口返回小程序"

  Step D：用户关闭 web-view 回小程序
    └→ Profile 页 onShow → GET /api/strava/status
       └→ 返回 { bound: true, athlete_name: 'Ming Li', import_status: 'active' }

流 5：Strava 导入进度轮询
  Profile 页 setInterval(3s) → GET /api/strava/import-progress
    └→ 后端读 strava_imports 表（按 created_at DESC 取最新一条），判断：
       - imp.status == 'active' AND (now() - imp.updated_at) > 5min 
         → 视为 stalled（仅视图层判定，不改库状态）
       - imp.status == 'completed' → 视为完成
       - 其他 → 正常 active
    └→ 前端根据 view_status：
       - 'completed' / 'stalled' / 'paused' → 清 setInterval
       - 'stalled' → 提示"导入似乎卡住了，请拉我重试"
       - 'active' → 显示进度条
    └→ 页 onHide/onUnload → clearInterval（防泄漏）
```

### 0.4 新增/改动项目结构

```
app/
├── notification/
│   ├── router.py       （改：加 mark-all-read + GET 加 unread_only 参数）
│   ├── service.py      （改：加 mark_all_read() 函数、unread_count 查询）
│   └── models.py       （改：加 is_read 字段）    ⚠ v0 遗漏
├── strava/
│   ├── service.py      （改：state 改 nonce 明文 + Redis 一次性；handle_callback 防重复绑 + 行锁；加 _cleanup_old_athlete_activities）
│   ├── router.py       （改：import-progress 加 stalled 判定、webhook 改 subscription_id 校验）
│   └── import_scheduler.py （改：tier1 连续 2 次空才判完成；对齐 _CYCLING_TYPES 5 种（已对齐，文档同步））
├── activity/
│   ├── models.py       （改：加 activity_type 字段）
│   └── worker.py       （改：解析器入口加 activity_type 分流）
├── user/
│   └── models.py       （改：加 mute_notifications 字段）   ⚠ v0 项目结构漏列
└── main.py             （无改动）

scheduler.py            （新建：根目录脚本，常驻进程 tick）

miniprogram/
├── pages/
│   ├── notification/   （新建：通知中心页）
│   ├── honor/          （新建：荣誉页）
│   ├── home/           （改：onShow 查未读、右上角加铃铛+红点、点铃铛跳通知页）
│   └── profile/        （改：加 Strava 绑定组件 + 免打扰开关 + 跳转入口）
└── utils/
    └── polling.js      （新建：统一的轮询管理工具，自动清理）

h5/                     （新建目录，静态托管）
└── strava-bind/
    └── index.html      （Strava 授权桥接页）

migrations/versions/
└── phase4_frontend_consume.py   （新增迁移，合一个文件）

docker-compose.yml      （改：加 scheduler 服务块）
Caddyfile               （改：现有 :80 块加 /strava/bind H5 路由）
```

### 0.5 模块依赖方向（单向，禁止反向 import）

```
前端:  notification/honor/home/profile
           │
           ↓ HTTP GET/POST
        后端 API
           │
           ↓
  notification ← auto_match ← strava.import_scheduler
       ↑
       └───── segment ← activity ← user
```

---

## 1. 数据模型改动

### 1.1 notifications 表新增 is_read 字段（修 Critical-01）

**必做原因**：v0 草案的整个"标已读/首页红点"逻辑建立在这个字段上，但 v3 建库时**根本没加**这个字段。

**字段定义**：

```python
# app/notification/models.py
is_read = Column(
    Boolean,
    nullable=False,
    server_default='false',
    comment='是否已读。用户进通知列表页后由 mark-all-read 接口置为 true'
)
```

**部分索引**（支撑首页红点高频查询）：

```sql
CREATE INDEX idx_notifications_user_unread 
    ON notifications (user_id, expires_at) 
    WHERE is_read = FALSE;
```

### 1.2 activities 表新增 activity_type 字段（种子 1）

**目的**：为未来多运动扩展留门。

**字段定义**：

```python
# app/activity/models.py
activity_type = Column(
    String(20), 
    nullable=False, 
    server_default='cycling',
    comment='活动类型：cycling（骑行）/ running / hiking（预留）'
)
```

**Alembic 迁移策略（简化为一步）**：

```python
# PostgreSQL 11+ 加列时带 server_default 不会重写全表，老数据自动拿默认值
op.add_column('activities', sa.Column(
    'activity_type', sa.String(20), 
    nullable=False, server_default='cycling'
))
```

**索引**：不加（本期只有一个值，查询不过滤）。

### 1.3 users 表新增 mute_notifications 字段（免打扰种子）

**目的**：为未来跨设备免打扰同步留门。**本期不参与业务逻辑**，仅作为字段存在。

```python
# app/user/models.py
mute_notifications = Column(
    Boolean, 
    nullable=True,   # NULL 表示"未设置"，区别于 False（"未静音"）
    server_default=None,
    comment='免打扰开关预留字段。本期仅留字段，实际开关存前端本地'
)
```

**关键约束**：
- 前端本期**不读不写这个字段**（开关状态仍在 `wx.getStorageSync`）
- 未来跨设备同步时改为"以后端为准"
- **truthiness 陷阱警示**：未来任何读这字段的代码必须显式写 `if user.mute_notifications is True`

### 1.4 strava_imports 表 updated_at 改 TIMESTAMP WITH TIME ZONE（修 Critical-03）

**必做原因**：现有 `updated_at` 是 naive datetime，§2.8 stalled 判定要 `datetime.now(UTC) - updated_at`，naive 减 aware 会 TypeError。

**迁移**：

```python
op.alter_column(
    'strava_imports', 'updated_at',
    type_=sa.DateTime(timezone=True),
    postgresql_using="updated_at AT TIME ZONE 'UTC'"
)
```

### 1.5 notifications 外键改 ON DELETE SET NULL（修 Important-I4）

**必做原因**：现有 segment_id 是 `CASCADE + nullable=False`，但 v4 希望"赛段被删时通知保留但指向 NULL"。

**三步迁移（缺一不可）**：

```python
# Step 1: drop 现有外键
# 注意：phase3 建表时用 sa.ForeignKey 内联未指定 name，
# 所以 PostgreSQL 自动生成的约束名遵循 <table>_<column>_fkey 规则
op.drop_constraint('notifications_segment_id_fkey', 'notifications', type_='foreignkey')
op.drop_constraint('notifications_activity_id_fkey', 'notifications', type_='foreignkey')

# Step 2: alter nullable（segment_id 原本 NOT NULL）
op.alter_column('notifications', 'segment_id', nullable=True)

# Step 3: 重建外键
op.create_foreign_key(
    'notifications_segment_id_fkey', 'notifications', 'segments',
    ['segment_id'], ['id'], ondelete='SET NULL'
)
op.create_foreign_key(
    'notifications_activity_id_fkey', 'notifications', 'activities',
    ['activity_id'], ['id'], ondelete='SET NULL'
)
```

**前端配套**：§3.1 通知点击跳转时要兜 segment_id / activity_id 为 NULL 的情况 → 显示"该记录已失效"。

### 1.6 Alembic 迁移脚本结构

**文件**：`migrations/versions/phase4_frontend_consume.py`

合并以上 5 项改动：
1. notifications 加 is_read 字段 + 部分索引
2. activities 加 activity_type 字段
3. users 加 mute_notifications 字段
4. strava_imports.updated_at 改 timezone=True
5. notifications 外键 drop → alter nullable → 重建 SET NULL

**回滚策略**：每步都要写 downgrade，上线前本地完整跑一次 upgrade / downgrade / upgrade。

---

## 2. 后端改动

### 2.1 新增接口 POST /api/notifications/mark-all-read

**位置**：`app/notification/router.py`（扩展） + `app/notification/service.py`（新增函数）

**service.py 新增函数**：

```python
def mark_all_read(db: Session, user_id: int) -> int:
    """
    把当前用户所有未读通知标为已读。
    SQL 层面带 WHERE is_read=false，接口天然幂等。
    """
    count = (
        db.query(Notification)
        .filter(
            Notification.user_id == user_id,
            Notification.is_read == False,   # 显式 == False 而非 truthiness
        )
        .update({Notification.is_read: True}, synchronize_session=False)
    )
    db.commit()
    return count
```

**router.py 加路由**：

```python
@notification_router.post("/mark-all-read")
def mark_all_read(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user),
):
    marked = service.mark_all_read(db, user_id)
    return {"marked": marked}
```

**响应**：`{"marked": 3}`

### 2.2 扩展 GET /api/notifications（unread_only + unread_count）

**新增查询参数**：`unread_only: bool = False`（默认 False，向后兼容）

**响应结构变化**：
```json
{
  "items": [...],
  "total": 42,
  "unread_count": 3,     // 新增：未读总数，无论 unread_only 是否为 True 都返回
  "page": 1,
  "page_size": 20
}
```

**service.py 改动**：

```python
def get_notifications(
    db, user_id, page, page_size, unread_only: bool = False
) -> dict:
    query = db.query(Notification).filter(
        Notification.user_id == user_id,
        Notification.expires_at > func.now(),
    )
    if unread_only:
        query = query.filter(Notification.is_read == False)
    
    total = query.count()
    items = query.order_by(Notification.created_at.desc()).offset(...).limit(...).all()
    
    # unread_count 独立查询（走部分索引，极快）
    unread_count = (
        db.query(func.count(Notification.id))
        .filter(
            Notification.user_id == user_id,
            Notification.is_read == False,
            Notification.expires_at > func.now(),
        )
        .scalar()
    )
    
    return {"items": items, "total": total, "unread_count": unread_count, ...}
```

### 2.3 Strava 拉取骑行过滤（已存在）

**事实核查**：`app/strava/import_scheduler.py:43` 已有 `_CYCLING_TYPES = {"Ride", "VirtualRide", "EBikeRide", "Handcycle", "Velomobile"}`，`:313` 已过滤。**本期无需改动代码**，spec 原 §2.3 描述的 `CYCLING_TYPES = ('Ride', 'VirtualRide')` 是对现有集合的错误收窄——抛弃这个改动。

**本期动作**：仅在 §0.1 代码侧事实表中记录当前集合即可，不做变更。

### 2.4 解析器入口加 activity_type 分流（种子 3）

**位置**：`app/activity/worker.py` 的 `parse_activity` 入口

**改动**：

```python
def parse_activity(activity_id: int):
    activity = db.get(Activity, activity_id)
    
    # 🌱 种子 3：运动类型分流
    if activity.activity_type == 'cycling':
        _parse_cycling(activity)
    else:
        # 本期不支持其他运动类型
        activity.status = 'failed'
        activity.error_message = f'暂不支持的运动类型: {activity.activity_type}'
        db.commit()
        logger.warning(f'活动 {activity_id} 运动类型 {activity.activity_type} 暂不支持')
        return
```

### 2.5 OAuth state 改 nonce 明文 + Redis 一次性消费（修 Critical-01 + Critical-08）

**v0 错误**：用 JWT 包装 state 增加冗余。**v1 简化**：nonce 本身是不可猜测的随机串，Redis 存 `{nonce: user_id}`，明文返给 Strava 即可。

**service.py 新增函数**：

```python
import secrets
from redis import Redis

def build_authorize_url(user_id: int, redis: Redis) -> str:
    """
    生成 Strava OAuth 授权 URL。state 直接用 nonce，不套 JWT。
    nonce 写 Redis 10min TTL，callback 时 GETDEL 一次性消费。
    """
    nonce = secrets.token_urlsafe(24)   # 32 字节随机
    redis.setex(f'strava_state:{nonce}', 600, str(user_id))
    
    return (
        f'https://www.strava.com/oauth/authorize'
        f'?client_id={settings.STRAVA_CLIENT_ID}'
        f'&response_type=code'
        f'&redirect_uri={settings.STRAVA_REDIRECT_URI}'
        f'&approval_prompt=auto'
        f'&scope=read,activity:read'  # ⚠️ 历史档案 / 2026-05-11 已升级 read_all / 见 changelog
        f'&state={nonce}'   # 直接 nonce 明文
    )


class InvalidStateError(Exception):
    pass


def verify_state_and_consume(state: str, redis: Redis) -> int:
    """
    验证 state 并一次性消费。失败抛 InvalidStateError。
    Redis 7+ 支持原生 getdel 方法。
    """
    stored = redis.getdel(f'strava_state:{state}')
    if stored is None:
        raise InvalidStateError('state 已使用或过期')
    
    # redis-py 默认返 bytes，需 decode
    return int(stored.decode() if isinstance(stored, bytes) else stored)
```

**防御效果**：
- ✅ Login CSRF：nonce 本身不可猜，攻击者无法预测受害者的 nonce
- ✅ 重放：getdel 原子删除，用过即废

### 2.6 handle_callback 改造防重复绑定（修 Critical-02 + Important I6）

**位置**：`app/strava/service.py` 现有 `handle_callback` 函数（注意：不是 `handle_oauth_callback`）

**改造**：

```python
def handle_callback(db: Session, code: str, state: str, redis: Redis) -> dict:
    """
    Strava OAuth 回调。v4 改造：
    1. state 一次性消费（verify_state_and_consume）
    2. 换 token（内联，保留现有 service.py:124-177 的完整逻辑）
    3. user 行锁 + NoResultFound 兜底（用 .first()）
    4. UNIQUE 冲突检测——必须在清理旧活动之前（避免"被他人占用时误伤自家数据"）
    5. 换号时清理旧 athlete 的 importing 活动
    6. StravaImport 防重复（active 状态已存在则复用）
    """
    user_id = verify_state_and_consume(state, redis)
    
    # ---- 第 2 步：换 token（内联，不抽函数。参考现有 service.py:124-177）----
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
        logger.error("Strava token 请求失败 user_id=%d status=%d", user_id, resp.status_code)
        raise ValueError("Strava 授权失败")
    
    data = resp.json()
    athlete = data.get("athlete")
    if not athlete or "id" not in athlete:
        raise ValueError("Strava 返回数据缺少 athlete 字段")
    for key in ("access_token", "refresh_token", "expires_at"):
        if key not in data:
            raise ValueError(f"Strava 返回数据缺少 {key} 字段")
    
    new_athlete_id = athlete["id"]
    
    # ---- 第 3 步：user 行锁 ----
    user = (
        db.query(User)
        .filter(User.id == user_id)
        .with_for_update()
        .first()
    )
    if not user:
        raise ValueError(f"用户 {user_id} 不存在")
    
    # ---- 第 4 步：UNIQUE 冲突检测（必须在清理之前，顺序不可换）----
    # 如果该 Strava 账号已被其他 VELO 账号绑定，直接拒绝，避免错误清理自家数据
    other = (
        db.query(User)
        .filter(
            User.strava_athlete_id == new_athlete_id,
            User.id != user_id,
        )
        .first()
    )
    if other:
        raise BoundByOtherUserError("该 Strava 账号已被其他 VELO 账号绑定")
    
    # ---- 第 5 步：换号时清理旧 athlete 的 importing 活动 ----
    if user.strava_athlete_id and user.strava_athlete_id != new_athlete_id:
        _cleanup_old_athlete_activities(db, user.id, user.strava_athlete_id)
    
    # ---- 第 6 步：写入 token（expires_at 内联解析，不抽函数）----
    user.strava_athlete_id = new_athlete_id
    user.strava_access_token = data["access_token"]
    user.strava_refresh_token = data["refresh_token"]
    user.strava_token_expires_at = datetime.fromtimestamp(
        data["expires_at"], tz=timezone.utc
    )
    db.flush()
    
    # ---- 第 7 步：StravaImport 防重复 ----
    # 覆盖 active + paused 两种未完成态（否则 paused 时新回调会再建一条 active，并存记录）
    # strava_athlete_id 是 NOT NULL，创建时必须带上
    existing = (
        db.query(StravaImport)
        .filter(
            StravaImport.user_id == user_id,
            StravaImport.status.in_(["active", "paused"]),
        )
        .with_for_update()
        .first()
    )
    
    if not existing:
        db.add(StravaImport(
            user_id=user_id,
            strava_athlete_id=new_athlete_id,
            status="active",
        ))
    
    db.commit()
    return {"bound": True, "athlete_id": new_athlete_id}


def _cleanup_old_athlete_activities(db: Session, user_id: int, old_athlete_id: int) -> int:
    """
    换号场景：把旧 athlete 还在导入中的活动置 failed。
    Strava 来源活动的中间状态值 = 'importing'（对齐 import_scheduler.py:219）。
    不删除历史已 completed 活动（用户可能还想看）。
    返回标记数量。
    """
    count = (
        db.query(Activity)
        .filter(
            Activity.user_id == user_id,
            Activity.data_source == "strava",
            Activity.status == "importing",
        )
        .update(
            {
                Activity.status: 'failed',
                Activity.error_message: f'换号绑定：旧 athlete {old_athlete_id} 的导入中断',
            },
            synchronize_session=False,
        )
    )
    return count
```

**异常类定义**（新增到 service.py 或 exceptions.py）：
```python
class BoundByOtherUserError(Exception):
    """该 Strava 账号已被其他 VELO 账号绑定"""
    pass
```

### 2.7 Webhook 改用 subscription_id + verify_token 校验（修 Critical-04）

**v0 错误**：`STRAVA_WEBHOOK_IP_RANGES` 只有占位段，Strava 官方**不保证 IP 稳定**。按 v0 实现会把合法回调 403 拒绝。

**v1 方案**：用 Strava 订阅的 `verify_token`（初次订阅时双方约定）+ payload 里的 `subscription_id` 双重校验。

**位置**：`app/strava/router.py` 的 `POST /api/strava/webhook`

```python
# 环境变量（docker-compose.yml 已有）：STRAVA_WEBHOOK_VERIFY_TOKEN + STRAVA_WEBHOOK_SUBSCRIPTION_ID

@router.post('/api/strava/webhook')
async def strava_webhook(
    request: Request,
    body: dict = Body(...),
):
    """
    Strava Webhook 事件接收。
    Strava 不提供 HMAC 签名，依靠：
    1. payload.subscription_id == 本系统订阅的 subscription_id（初次订阅时记录）
    2. HTTPS 传输保证来源不可伪造（Caddy 强制 TLS）
    """
    # 兜底：配置未声明或为空时直接拒绝（防 AttributeError / int(""))
    expected_sub_id = getattr(settings, 'STRAVA_WEBHOOK_SUBSCRIPTION_ID', None)
    if not expected_sub_id:
        logger.error('Webhook 未配置 STRAVA_WEBHOOK_SUBSCRIPTION_ID')
        raise HTTPException(503, '未配置订阅 ID')
    
    if body.get('subscription_id') != int(expected_sub_id):
        logger.warning(f'Webhook subscription_id 不匹配: 收到={body.get("subscription_id")}, 期望={expected_sub_id}')
        raise HTTPException(403, 'Forbidden')
    
    # 原有处理逻辑（现有代码保留）
    ...
```

**初次订阅**：手动跑一次 `curl -X POST "https://www.strava.com/api/v3/push_subscriptions" -F client_id=X -F client_secret=Y -F callback_url=Z -F verify_token=VERIFY_TOKEN`，记下返回的 `id` 作为 `STRAVA_WEBHOOK_SUBSCRIPTION_ID` 环境变量。

### 2.8 import-progress 加 stalled 判定（修 Critical-07 + Important I6）

**位置**：`app/strava/router.py` 的 `GET /api/strava/import-progress`

**关键修正**：
- StravaImport.status 值域是 `active/paused/completed`（不是 running/pending）
- `updated_at` 要先在 §1.4 迁移为 timezone=True 后才能和 `datetime.now(UTC)` 相减

```python
@router.get('/api/strava/import-progress')
def get_import_progress(
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    imp = (
        db.query(StravaImport)
        .filter(StravaImport.user_id == user_id)
        .order_by(StravaImport.created_at.desc())
        .first()
    )
    
    if imp is None:
        return {'view_status': 'none', 'total': 0, 'completed': 0}
    
    # view_status：仅视图层判定（不写库）
    view_status = imp.status   # active / paused / completed
    
    # Critical #7：active 状态下 5 分钟无更新视为 stalled
    if imp.status == 'active':
        staleness = datetime.now(timezone.utc) - imp.updated_at
        if staleness > timedelta(minutes=5):
            view_status = 'stalled'
    
    return {
        'view_status': view_status,
        'db_status': imp.status,
        'total': imp.total_activities or 0,
        'completed': imp.tier2_completed or 0,
        'tier1_completed': imp.tier1_completed or 0,
    }
```

**完成判断统一口径**：前端根据 `view_status` 判（'completed' / 'stalled' / 'paused' 停轮询），**不算术比较 `completed == total`**（避免口径混乱）。

### 2.9 其他 Important 对策（一句话 + 位置）

> 编号对齐 §6.2 风险表（I7~I11 指向这里，I1~I6 指向别的章节）。

| # | 对策 | 文件 |
|---|------|------|
| I7 | refresh 失败同步 pause active imports | `service.py` `ensure_valid_token` 401 分支内加 `UPDATE strava_imports SET status='paused' WHERE user_id AND status='active'` |
| I8 | 刷 token 加行锁 | `service.py` refresh 前 `SELECT user FOR UPDATE` |
| I9 | tier1 连续 2 次空返回才判完成 | `import_scheduler.py` `_run_tier1` 加 `consecutive_empty` 计数器 |
| I10 | handle_manual_sync 更新 tier1_completed | `service.py:445` 写入后追加更新 |
| I11 | import-progress 加 Redis 1s/user 限速 | `router.py` 加 `RateLimiter(key=f'rl:imp-prog:{user_id}', window=1s, limit=1)` |

---

## 3. 前端改动（小程序）

### 3.1 通知中心页（新建 `pages/notification/`）

**入口位置**：**首页右上角铃铛🔔图标**（不是放在"我的"页）。理由：对齐 Strava / 微信 / 抖音等主流 App 的"消息在顶部右上角"肌肉记忆；且通知是"活数据"，应在首页直接暴露。

**功能**：
- onLoad 并行发两个请求：`GET /api/notifications?page=1&page_size=20` + `POST /api/notifications/mark-all-read`
- **UI 视觉化已读**：进页立即把所有条目渲染为已读样式，**不等 mark-all-read 返回**（避免 I2 描述的"请求顺序不定引起的闪烁"）
- 列表按时间倒序，每条显示：event_type 图标 + 标题 + 副标题 + 时间
- 点击跳 `/pages/segment?id=segment_id`
- segment_id 为 NULL（外键 SET NULL 后）→ 显示"该记录已失效"不跳转
- 下拉刷新 / 滚动到底加载下一页
- 空态 / 错误态

### 3.2 荣誉页（新建 `pages/honor/`）

**入口位置**：**"我的"页**（保持在个人身份语境下——荣誉是"相对静态的身份标签"，和头像、累计里程、设置放一起合理）。

**功能**：
- onLoad 调 `GET /api/user/honors`（已存在）
- 分两 tab：🏆 KOM（我是第一） / 🥇 前十
- 每条点击跳 `/pages/segment?id=X`
- 空态展示"去排行榜看看"按钮

### 3.3 首页小红点（放在右上角铃铛旁）

**位置决策**：小红点**只放一个位置——首页右上角铃铛🔔图标右上角**。不放底部 tabBar（原 v2 设计已废弃）。

理由：
- 用户默认落地页就是首页，打开即可见
- 和 Strava / 微信 / 抖音的红点位置完全一致，零学习成本
- 小程序 tabBar 红点 API 较繁琐；首页自画一个小圆点更简单可控
- 不分两处避免用户困惑"为啥有时候两个红点"

**文件**：`miniprogram/pages/home/home.js` + `home.wxml`

**WXML 片段**（铃铛按钮带红点）：

```xml
<view class="header">
  <text class="title">VELO</text>
  <view class="notification-icon" bindtap="goNotificationPage">
    <image src="/assets/bell.svg" mode="aspectFit" />
    <view class="red-dot" wx:if="{{unreadCount > 0}}"></view>
  </view>
</view>
```

**JS 逻辑**：

```js
onShow: async function() {
  const muted = wx.getStorageSync('mute_notifications') === true
  if (muted) {
    this.setData({ unreadCount: 0 })
    return
  }
  try {
    const res = await api.get('/api/notifications', { unread_only: true, page_size: 1 })
    this.setData({ unreadCount: res.unread_count })
  } catch (e) {
    console.warn('未读数查询失败', e)
  }
},

goNotificationPage() {
  wx.navigateTo({ url: '/pages/notification/notification' })
}
```

### 3.4 设置页免打扰开关

**文件**：`miniprogram/pages/profile/settings.js`

```js
onToggleMute(e) {
  const muted = e.detail.value === true   // 显式 boolean
  wx.setStorageSync('mute_notifications', muted)
  // 不做其他动作：用户切回首页时，home.js onShow 会读本地 mute_notifications
  //   开 → 不查询未读数、不显示红点
  //   关 → 正常查询、正常显示红点
}
```

### 3.5 Profile 页 Strava 绑定组件

**状态**：
- 未绑 → [绑定 Strava] 按钮
- 已绑 + active → 昵称 + "正在导入 23/87" 进度条
- 已绑 + completed → 昵称 + "上次同步时间"
- 已绑 + stalled → 昵称 + "导入似乎卡住了，[重试]"

**数据流**：
- onShow 调 `/status`
- 如果 view_status == 'active' 启动 3s 轮询 `/import-progress`
- onHide/onUnload 清定时器（防前端定时器泄漏，参照 §6.3 Minor）

### 3.6 Strava 授权 H5 页（新建 `h5/strava-bind/index.html`）

小程序 web-view 只能加载白名单域名，不能直接打开 strava.com，需要咱家 H5 作为跳板。

```html
<!DOCTYPE html>
<html>
<head><title>绑定 Strava</title><meta charset="utf-8"></head>
<body>
  <h2>即将跳转到 Strava 授权</h2>
  <button id="go">前往 Strava 授权</button>
  <script>
    const params = new URLSearchParams(location.search);
    const authorizeUrl = params.get('url');
    document.getElementById('go').onclick = () => { location.href = authorizeUrl; };
  </script>
</body>
</html>
```

---

## 4. 部署改动

### 4.1 scheduler 服务新增（修 Critical-03）

**v0 错误**：bash `while true; python -c "..."` 冷启 Python + 不经 sys.path 初始化。

**v1 方案**：根目录新建 `scheduler.py`，学习 `worker.py` 的模式。

**scheduler.py**（根目录，新建）：

```python
"""
Strava 导入调度器——常驻进程，每 30s tick 一次。

不用 rq-scheduler 是因为 rq-scheduler 需要额外配置且我们只有一个 tick 函数。
当未来有多个周期任务时再迁移到 rq-scheduler。
"""
import time
import logging
from app.strava.import_scheduler import run_import_tick

logging.basicConfig(level=logging.INFO, format='%(asctime)s [scheduler] %(message)s')
logger = logging.getLogger(__name__)


def main():
    logger.info('Strava scheduler 启动')
    while True:
        try:
            run_import_tick()
        except Exception as e:
            logger.exception(f'tick 失败: {e}')
        time.sleep(30)


if __name__ == '__main__':
    main()
```

**docker-compose.yml 新增服务块**：

```yaml
  # ===== Strava 导入调度器 =====
  scheduler:
    build: .
    command: python scheduler.py
    restart: unless-stopped
    environment:
      DATABASE_URL: postgresql://velo:${DB_PASSWORD}@db:5432/velo
      REDIS_URL: redis://redis:6379/0
      STRAVA_CLIENT_ID: ${STRAVA_CLIENT_ID}
      STRAVA_CLIENT_SECRET: ${STRAVA_CLIENT_SECRET}
    depends_on:
      - db
      - redis
    volumes:
      - uploads:/app/uploads
```

**本地开发说明**：
- scheduler.py 放在项目根目录（和 worker.py 同级）
- 本地运行必须 `cd /Users/.../velo && python scheduler.py`（当前目录必须是根目录，否则 `from app.strava.import_scheduler import ...` 会 ImportError）
- Docker 部署靠 `WORKDIR=/app` 兜底（见 Dockerfile），无需手动设 PYTHONPATH

**验证**：

```bash
sudo docker compose up -d scheduler
sudo docker compose logs scheduler --tail 30
# 应看到每 30s 一次的 tick 日志
```

### 4.2 Caddyfile 加 H5 路由（修 Minor）

**现状**：Caddyfile 监听 `:80`，无域名块。H5 路由加在现有 `:80 {...}` 块内。

**新增**：

```caddy
:80 {
  # ... 原有反向代理配置保留 ...
  
  # Strava 绑定 H5（静态文件）
  handle_path /strava/bind/* {
    root * /var/www/h5/strava-bind
    file_server
  }
}
```

**配套**：Docker 挂载 H5 目录 `./h5:/var/www/h5` 到 caddy 容器。

---

## 5. 数据流快速索引

本节不重复绘图（详见 §0.3 五个数据流），仅列出快速定位索引：

| 场景 | 数据流 | 后端实现 | 前端实现 |
|------|--------|---------|---------|
| 打开 App 看红点 | §0.3 流 1 | §2.2 `unread_count` 查询 | §3.3 home onShow |
| 看通知列表 | §0.3 流 2 | §2.1 `mark_all_read` + §2.2 | §3.1 通知中心页 |
| 点通知跳赛段 | §0.3 流 3 | 无（复用现有 /segments） | §3.1 点击逻辑 |
| 绑定 Strava | §0.3 流 4 | §2.5 state + §2.6 callback + §2.7 webhook | §3.5 + §3.6 |
| 看导入进度 | §0.3 流 5 | §2.8 import-progress stalled | §3.5 轮询 |

---

## 6. 已知风险与防护

### 6.1 Critical 风险对策表（8 条 全部本期修完）

| # | 风险 | 对策位置 |
|---|------|---------|
| C1 | OAuth state Login CSRF + 无一次性消费 | §2.5（简化为 nonce 明文 + Redis getdel） |
| C2 | 重复绑定堆积 StravaImport | §2.6（行锁 + status=='active' 判断） |
| C3 | `updated_at` naive datetime | §1.4 迁移为 timezone=True |
| C4 | Webhook 无来源校验 | §2.7 subscription_id + verify_token |
| C5 | mute_notifications truthiness 陷阱 | §1.3 规范 + §3.3/3.4 显式 `=== true` |
| C6 | `type == 'X' or 'Y'` 永真 | §2.3 已确认现有代码已用集合写法，无需改 |
| C7 | scheduler 挂起前端永远轮询 | §2.8 stalled 视图层判定 |
| C8 | state 可重放（Referer / 日志泄漏后被二次使用）| 与 C1 对策同一 Redis 语义（GETDEL 原子消费），§2.5 一次改造同时覆盖 CSRF + 重放 |

### 6.2 Important 风险对策表（11 条 本期实现）

| # | 对策 | 位置 |
|---|------|------|
| I1 | notifications 加 is_read 字段 + 部分索引 | §1.1 |
| I2 | 通知列表和 mark-all-read 顺序不定 → UI 视觉化已读 | §3.1 |
| I3 | mark-all-read 幂等 | §2.1 显式 `== False` |
| I4 | notifications 外键改 SET NULL + 前端兜底 | §1.5 + §3.1 |
| I5 | 用户关 web-view 过快，callback 未完 | 前端 view_status == 'none' 时轮询一次 |
| I6 | 换号绑定清理旧 athlete 活动 | §2.6 `_cleanup_old_athlete_activities` |
| I7 | refresh 失败 pause imports | §2.9 I7 |
| I8 | 并发刷 token 覆盖 | §2.9 I8 |
| I9 | tier1 偶发空返回 | §2.9 I9 |
| I10 | 手动 sync 不联动进度 | §2.9 I10 |
| I11 | import-progress 限速 | §2.9 I11 |

### 6.3 Minor 风险（本期不修，记录）

- 前端 setInterval 泄漏（onHide 清理已覆盖）
- notification.segment_id=0 脏数据（主键 >=1，不会出现）
- web-view 中途关闭（UX 自愈，文档说明）
- detect_events 异常吞异常（日志已足够）
- tier2 started_at NULL 排序（边界）
- Webhook paused 记录堆积（定期清理）
- 其他 6 条详见完整故障分析报告（附录 A 指向）

### 6.4 本期明确不做（未来期）

1. **多运动支持**（跑步/徒步/滑雪）—— 本期仅埋种子
2. **微信服务消息推送** —— 第 5 期
3. **通知按类型筛选** —— 100+ 用户规模再做
4. **跨设备免打扰同步** —— 字段已留，逻辑未来写
5. **通知详情二级页** —— 本期直接跳赛段详情
6. **按条标读** —— 本期只支持"全部标读"
7. **荣誉页历史趋势图** —— 只显示当前状态

---

## 7. 任务拆分（11 个任务，按依赖顺序）

> 任务编号用 §7.x，和章节号 §0-9 不冲突。

### 任务 7.1：Alembic 迁移 + 模型改动

- 新增迁移 `phase4_frontend_consume.py` 合五个改动（§1.1~1.5）
- 改 `models.py`：notification 加 is_read、activity 加 activity_type、user 加 mute_notifications
- 本地跑 upgrade / downgrade / upgrade 验证幂等
- 老数据手工检查：33 条 activity 的 activity_type 应自动填 'cycling'

### 任务 7.2：Strava OAuth state 加固（Critical-01 + Critical-08）

- service.py 加 `build_authorize_url` + `verify_state_and_consume` + `InvalidStateError`
- 改 `handle_callback` 调用 verify_state_and_consume
- 测试：伪造 state / 重放 / 跨用户

### 任务 7.3：Strava callback 防重复绑定 + 换号清理（Critical-02 + Important I6）

- service.py 改造 `handle_callback`（§2.6 完整实现）
- 新增 `_cleanup_old_athlete_activities` + `BoundByOtherUserError`
- 测试：重复授权 / 换号 / UNIQUE 冲突

### 任务 7.4：Webhook subscription_id 校验（Critical-04）

- router.py webhook 加校验
- 环境变量加 `STRAVA_WEBHOOK_SUBSCRIPTION_ID`：在 **app/config.py + .env.example + docker-compose.yml 三处都要加**（否则 `settings.STRAVA_WEBHOOK_SUBSCRIPTION_ID` 访问会报错）
- webhook 代码先判 `if not settings.STRAVA_WEBHOOK_SUBSCRIPTION_ID: raise HTTPException(503, '未配置订阅 ID')`，防 `int("")` 崩溃
- 部署文档写"初次订阅"步骤（curl 命令创建 subscription，记下返回的 id 填入环境变量）
- 测试：正确 subscription_id / 错误 / 未配置 三种场景

### 任务 7.5：import-progress stalled + 限速（Critical-07 + I11）

- router.py `get_import_progress` 改造
- 加 Redis 限速 1s/user
- 测试：正常 / 5 分钟无更新 / completed

### 任务 7.6：Strava 现有函数加固（Important I7/I8/I9/I10）

- `ensure_valid_token` 401 分支 pause imports
- `_refresh_token` 加 SELECT FOR UPDATE
- `_run_tier1` 连续 2 次空才判完成
- `handle_manual_sync` 更新 tier1_completed

### 任务 7.7：解析器入口分流（种子 3）

- `activity/worker.py` 改造 parse_activity
- 测试：activity_type='cycling' / 'running'（应 failed）

### 任务 7.8：新增通知接口 + 扩展 GET

- service.py `mark_all_read()` 函数
- router.py `POST /notifications/mark-all-read` + 扩展 GET 加 unread_only
- 测试：幂等、unread_count、混合已读/未读

### 任务 7.9：scheduler 容器部署（Critical-03）

- 根目录新建 `scheduler.py`
- docker-compose.yml 加 scheduler 服务块
- 本地验证 tick 日志
- 生产部署 + 验进度开始推进

### 任务 7.10：小程序前端页面开发

- pages/notification（通知中心）
- pages/honor（荣誉页）
- home.js / home.wxml 改造（onShow 查未读 + 右上角铃铛红点 + 点铃铛跳通知页）
- profile/settings.js（免打扰开关）
- profile/components/StravaBind（绑定组件）
- h5/strava-bind/index.html（Strava 跳转桥接页）
- Caddyfile 加 H5 路由（§4.2）
- 端到端手工测试 + 回归

### 任务 7.11：集成测试 + 收尾

- 后端单元测试 + 集成测试全绿
- Strava OAuth 真实端到端测试（绑定 / 换号 / 进度 / stalled）
- 小程序开发者工具手工回归
- **防黑盒化机制 1**：更新 `docs/architecture-guide.md`
- **防黑盒化机制 2**：回答"黑盒度体检三问"
- 更新 `docs/changelog.md`

---

## 8. 测试策略

### 8.1 后端单元测试

| 模块 | 关键用例 |
|------|---------|
| notification.service | mark_all_read 幂等 / unread_count 边界 / `is_read == False` |
| strava.service | state 伪造/重放/跨用户 / callback 重复绑/换号/UNIQUE 冲突 |
| strava.import_scheduler | tier1 连续空 / tier2 NULL 排序 |
| activity.worker | activity_type 分流（cycling 正常 / running 置 failed）|

### 8.2 后端集成测试

- **OAuth 端到端**：mock Strava token endpoint，走完 authorize → callback → status 全链路
- **导入进度 端到端**：mock Strava list+detail，走完 tick → 进度推进 → completed
- **stalled 恢复**：手动让 updated_at 过期 5 分钟 → 查接口返回 view_status='stalled'

### 8.3 前端手工测试清单

- 首页红点：已读/未读/免打扰开/关 4 种状态
- 通知页：进入立即视觉化已读、列表刷新、空态、下拉刷新、分页
- 荣誉页：两 tab 切换、点击跳转、空态
- Strava 绑定：未绑 → 点按钮 → H5 → Strava → 回小程序 → 已绑定
- 免打扰：开启后首页无红点、通知页强制查询、重启 App 状态保持
- 进度轮询：绑定后看到进度、离开 Profile 页轮询停止、stalled 提示

### 8.4 Strava 真实环境 E2E

- 绑定账号 A → 导入完成 → 切账号 B → 老账号 importing 活动置 failed、B 开始导入
- 绑定后立即关闭 web-view 再打开 App → 看到正确状态
- Strava 429 限流 → scheduler 自动退避、进度正常继续

---

## 9. 未来扩展预留

### 9.1 多运动（第 5 或 6 期）

已埋 3 颗种子：
1. ✅ `activities.activity_type` 字段
2. ✅ Strava 拉取已按 `_CYCLING_TYPES` 过滤
3. ✅ 解析器入口分流

未来加跑步只需：新增 `_parse_running()` + Strava 过滤加 `RUNNING_TYPES` 集合 + 前端加运动 tab。

### 9.2 跨设备免打扰同步

已埋：`users.mute_notifications` 字段。未来改前端从"本地读"为"后端 API 读写"。迁移路径：应用启动时一次性把本地值同步到后端，之后以后端为准。

### 9.3 微信服务消息推送（第 5 期）

独立规划。需要申请微信模板消息资质、引导订阅、新增 push 模块。

### 9.4 通知按类型筛选（100+ 用户规模再做）

前端加 event_type tab（全部 / PR / KOM / 前十），后端 GET /notifications 加 `event_type` 参数过滤。

### 9.5 积分 + 骑行等级系统（网易云音乐式激励，第 5 或 6 期）

**产品方向**：给用户做游戏化激励——每次骑行、破 PR、拿 KOM 都涨积分，积分累积到阈值升级骑行等级。类似网易云音乐的 "Lv 10 黑胶 VIP"。

**为什么留到未来做**：
- 真实用户少于 10 人时激励机制无意义（自己给自己发积分没仪式感）
- 需要先让用户在 VELO 的反馈环（通知 + 荣誉）里稳定活跃一段时间，再加这一层更强刺激
- 建议前置条件：活跃用户 ≥ 30 人、平均每周上传活动 ≥ 2 次

**架构预留**：

后端（工作量不大）：
- `users` 表加 `score INT NOT NULL DEFAULT 0` 字段（总积分）
- `users` 表加 `level INT NOT NULL DEFAULT 1` 字段（冗余字段，便于排序）
- 新增 `score_logs` 表：每次积分变动记录一行（事件类型、积分增量、关联 activity_id 等）
- 新增接口 `GET /api/user/score`：返回积分、等级、距离下一级还差多少
- 积分累加逻辑挂在现有 `auto_match` 和 `detect_events` 之后（和通知共用触发点）

前端（工作量大头）：
- "我的"页荣誉墙上方加"等级卡片"（头像 + Lv N + 进度条）
- 积分变动动画（骑完车弹"+30 积分"飘字）
- 升级时全屏庆祝特效
- 积分规则文案设计

**积分规则（产品初稿）**：
- 每公里骑行：+1 分
- 破自己 PR：+30 分
- 进入赛段前十：+50 分
- 拿 KOM：+200 分
- 连续 N 天骑行：额外奖励

**等级映射（参考网易云）**：Lv1（0-99）/ Lv2（100-299）/ Lv3（300-599）...非线性递增。

---

## 附录 A：本期 Critical 风险追溯

8 条来自 Step 5 故障分析（双 agent 并行审视），2026-04-17。

Step 7 双重审判三轮时间线：
- 第一轮（v0 → v1）：Agent 1 抓 15 条 + Agent 2 抓 15 条，合 12 条 Critical
- 第二轮（v1 → v2）：Agent 1 抓 9 条 + Agent 2 抓 10 条，合 7 条 Critical
- 第三轮（v2 → v3）：Agent 1 抓 8 条 + Agent 2 抓 4 条，合 1 条 Critical（本版已修）

完整三轮审判原始记录见 `docs/plans/2026-04-17-phase4-audit.md`（待整理归档）。

## 附录 B：本期涉及的 CLAUDE.md 硬规则（执行时必遵）

1. **故障思维**（§6.4 清单每项过一遍）
2. **truthiness 陷阱**（`is True` / `== False`，本期 §1.3/§2.1/§3.3/§3.4 均显式应用）
3. **SAVEPOINT**（循环中 flush 后可能 rollback 的用 `db.begin_nested()`，本期主要是 Strava 批量导入已在 v2 实现）
4. **状态机前置校验**（Activity / StravaImport 状态变更前 assert）
5. **防黑盒化**（§7.11 硬性任务，含 architecture-guide 刷新 + 体检三问）
6. **代码健康度**（单文件 ≤300 行黄灯 / 500 行红灯，收尾时体检）
7. **证据分级**：spec 里所有代码引用必须预读验证，见本 spec §0.1 代码侧事实表（本期建立的工程约束）

---

**本文档状态**：v4（Step 8 Starsky 审阅后的 UX 微调版）
**最后更新**：2026-04-17

**修订记录**：
- v0（2026-04-17）：草案，第一轮双审判抓 12 条 Critical（虚构字段/函数/状态值为主）
- v1（2026-04-17）：修 v0 + 新增 §0.1 代码侧事实表；第二轮审判又抓 7 条 Critical（"内联逻辑抽函数"伪装成的虚构）
- v2（2026-04-17）：修 v1 + 一系列编号统一和文档结构修补；第三轮审判抓 1 条 Critical + 1 条 Important + 1 条 Minor
- v3（2026-04-17）：修 v2 剩余问题，Critical=0
- v4（2026-04-17）：Step 8 Starsky 审阅后 UX 微调——通知入口从"我的"页改到首页右上角铃铛、小红点位置同步改到铃铛旁（不放 tabBar）、荣誉入口保留在"我的"页；§9 新增积分+骑行等级系统未来扩展

**下一步**：Step 9 实施计划
