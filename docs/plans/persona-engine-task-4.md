# Persona Engine Task-4 — 业务接入（worker hook + endpoint + scheduler）

> 所属：Persona Engine Sprint / 6 task 中的第 4 个 / 业务接入层
> 上下文：宪法 § 7.2 四不规则（不阻塞主流程 / 不传染失败）
> **共用约束 / SOP / 双审**：详见 `persona-engine-handoff.md`

---

## ─────── 给 Tim 看 ───────

### 干啥用

把 NPC 接到 velo 的"耳朵和眼睛"——

- **用户上传 GPX → NPC 知道**（worker hook）
- **用户一周没骑 → NPC 知道**（后台 scheduler 扫描）
- **用户达成里程碑 / 节气日 → NPC 知道**（后台 scheduler 扫描）
- **前端来问"现在该说什么" → endpoint 返当前 NPC 文案**

本 task 完成后 NPC 后端**完全可用** —— 前端调 endpoint 就能拿文案 / 但还没真在小程序里显示（task-5）。

### 用户故事

**故事 A — 上传完听到 NPC 反应**
小明骑完 100km / 上传 GPX → worker 后台解析完 → NPC 算出"前 1% 的一天。"（PR 场景）→ 写进 persona_outputs / 小明打开 velo 看到这句话。

**故事 B — 一周没骑被关心**
小明出差 8 天没骑 → 后台 scanner 每日 02:00 跑 / 发现他沉寂 → 写"最近去哪儿了。"到 persona_outputs / 小明回来打开 velo 看到。

**故事 C — 上传炸了 NPC 不传染**
某天后端 persona service 因 bug 抛错 → activity worker 仍正常完成 / 小明上传成功 / 只是没看到 NPC 文案（宪法 § 7.2 "不传染失败"）。

### 怎么算做对了

- ✓ 上传 PR 活动 → persona_outputs 写入 1 条 PR 场景文案
- ✓ 上传普通 80km 活动 → persona_outputs 写入 1 条段位场景文案
- ✓ 模拟沉寂 8 天 + 跑 silence scanner → persona_outputs 写入 1 条沉寂场景文案
- ✓ endpoint GET /api/persona/output?scene_type=profile_open 返合法响应
- ✓ **worker hook 故意抛 exception → activity 仍正常 completed**（CRITICAL / 拔出测试）
- ✗ NPC 失败让用户上传失败 = 灾难性 bug

### 这次**不做**的事

- 推送通知（push notification）→ 本 Sprint 仅在用户打开 velo 时拿文案
- WebSocket 实时推送 → 用 polling / 不上 ws
- 用户反馈机制（点赞 / 踩）→ v1.0+

### 估时

1.5 天

---

## ─────── 折叠：技术细节 ───────

<details>
<summary>展开</summary>

### 防火墙红线（CRITICAL）

参 handoff § 1。本 task **最关键**：
- § 1.4 失败隔离：worker hook **必须** `db.begin_nested()` SAVEPOINT 包裹（CLAUDE.md 陷阱 #13）
- § 1.1 ADR-009：worker 调 persona service 时打包参数 dict / 不让 service 反向 import 业务模块

### worker hook（`app/activity/worker.py` 加 NPC hook）

在 city hook / detector hook 同级位置加（参 PRD § 0.1 真实代码事实表 worker.py:165-250）：

**worker.py 顶部 import**（v0.2 修 / Claude B 抓 I-6 / 防 UnboundLocalError 陷阱 #19）：

```python
# worker.py 顶部 / 模块级 import / 不在函数内 import（防 UnboundLocalError）
from app.agent.persona import service as persona_service
from app.agent.persona.trigger_router import PersonaEvent
from datetime import datetime, timezone, timedelta  # v0.4 修 / Claude B I1 / timedelta 提到顶部 / 防函数内漏 import 触发 NameError
from sqlalchemy.exc import SQLAlchemyError
```

**worker hook 主体**（在 activity 完成 / heatmap cache 清理后追加）：

```python
try:
    nested_persona = db.begin_nested()  # SAVEPOINT 隔离（陷阱 #13）
    try:
        # 打包参数 dict（不让 persona 反向 import 业务 service）
        weekly_count = _query_weekly_count(user_id, db)
        is_pr = _detect_pr(activity, user_id, db)

        # 1) 上传活动 event（PR / 段位 / 极端）
        event = PersonaEvent(
            type="activity_uploaded",
            activity_data={
                "id": activity.id,
                "distance": activity.distance,
                "elevation_gain": activity.elevation_gain,
                "duration": activity.duration,
                "moving_time": activity.moving_time,
                "started_at": activity.started_at,
                "avg_speed_kmh": (activity.avg_speed * 3.6) if activity.avg_speed else None,  # v0.5 修 / 与 trigger_router 消费侧字段名 + 单位对齐（trigger_router 读 avg_speed_kmh）
                "avg_power": activity.avg_power,
                "normalized_power": activity.normalized_power,
                "is_pr": is_pr,
                "is_rain": False,  # 暂无天气数据 / 留 v1.0
            },
            user_data={
                "user_id": user_id,
                "total_distance_m": _query_total_distance(user_id, db),
                "weekly_count": weekly_count,
                "last_activity_days": 0,  # 刚上传
            },
            timestamp=datetime.now(timezone.utc),
        )
        result = persona_service.generate_persona_output(event, db)
        logger.info(f"persona output for activity {activity.id}: {result!r}")  # v0.2 修 / Claude B 抓 C3 / 让真用回归可 grep 验证

        # 2) v0.2 修 / Claude A 抓 C3 / 连骑高频 event 发射
        # 本周第 5+ 次上传时 / 额外发 consecutive_high_detected event
        if weekly_count >= 5:
            consecutive_event = PersonaEvent(
                type="consecutive_high_detected",
                user_data={"user_id": user_id, "weekly_count": weekly_count},
                timestamp=datetime.now(timezone.utc),
            )
            ch_result = persona_service.generate_persona_output(consecutive_event, db)
            logger.info(f"persona consecutive_high for user {user_id}: {ch_result!r}")

        db.flush()
        nested_persona.commit()
    except Exception as e:
        nested_persona.rollback()
        logger.warning(f"persona hook failed (activity_id={activity.id}, ignored): {e}")
except SQLAlchemyError as e:
    # SAVEPOINT 创建本身失败 → 日志记录 / 不传染
    logger.warning(f"persona SAVEPOINT failed (activity_id={activity.id}): {e}")
```

**红线**：persona 任何失败必须被 try/except 包裹 + nested.rollback() 回滚 SAVEPOINT / 绝对不能让 activity 主流程 fail。

**v0.3 修 / Claude B 抓 I4 / SAVEPOINT 外层 catch 改 Exception**：
```python
# 错误（v0.2）：except SQLAlchemyError as e
# 正确（v0.3）：except Exception as e
# 理由：begin_nested 失败可能是 ImportError / RuntimeError 等非 SQLAlchemyError
except Exception as e:
    logger.warning(f"persona SAVEPOINT failed (activity_id={activity.id}): {e}")
```

### v0.3 新增：3 个 worker hook helper 函数（Claude A 抓 I-new-4）

```python
def _query_weekly_count(user_id: int, db: Session) -> int:
    """查本周用户上传 activity 数（本周 = 周一 00:00 北京时间 起到现在）。

    v0.4 修 / Codex I4 + Claude B I1 / 用 ZoneInfo 替代 fixed offset / 防未来扩展多时区炸
    （timedelta + datetime 已在 worker.py 顶部 import / 不再函数内重复 import）
    """
    from zoneinfo import ZoneInfo  # Python 3.9+ stdlib
    BJ_TZ = ZoneInfo("Asia/Shanghai")
    now_bj = datetime.now(BJ_TZ)
    week_start_bj = (now_bj - timedelta(days=now_bj.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    week_start_utc = week_start_bj.astimezone(timezone.utc)
    return db.query(Activity).filter(
        Activity.user_id == user_id,
        Activity.started_at >= week_start_utc,
        Activity.activity_type == "cycling",
    ).count()


def _detect_pr(activity: Activity, user_id: int, db: Session) -> bool:
    """检测 activity 是否是 PR（任一字段打破历史 max）。

    PR 字段：distance / elevation_gain / duration / normalized_power（任一 max）
    历史 max = 该用户除本 activity 外的最大值
    """
    from sqlalchemy import func
    others = db.query(
        func.max(Activity.distance),
        func.max(Activity.elevation_gain),
        func.max(Activity.duration),
        func.max(Activity.normalized_power),
    ).filter(
        Activity.user_id == user_id,
        Activity.id != activity.id,
        Activity.activity_type == "cycling",
    ).first()
    if others is None or all(v is None for v in others):
        return True  # 第一条活动 = PR
    max_distance, max_elev, max_duration, max_np = others
    if activity.distance and max_distance and activity.distance > max_distance:
        return True
    if activity.elevation_gain and max_elev and activity.elevation_gain > max_elev:
        return True
    if activity.duration and max_duration and activity.duration > max_duration:
        return True
    if activity.normalized_power and max_np and activity.normalized_power > max_np:
        return True
    return False


def _query_total_distance(user_id: int, db: Session) -> int:
    """查用户累计 cycling 距离（米）。"""
    from sqlalchemy import func
    total = db.query(func.sum(Activity.distance)).filter(
        Activity.user_id == user_id,
        Activity.activity_type == "cycling",
    ).scalar()
    return int(total or 0)
```

### endpoint：`app/agent/persona/router.py`（新建）

```python
from fastapi import APIRouter, Depends, Query
from app.dependencies import get_current_user, get_db
from app.agent.persona import service as persona_service
from app.agent.persona.trigger_router import PersonaEvent

router = APIRouter(prefix="/api/persona", tags=["persona"])


# v0.4 修 / Pydantic v2 from_attributes + 字段对齐 ORM
class PersonaOutputResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)  # v0.4 修 / Claude A I3 + B I4 / ORM 序列化
    template_text: Optional[str]  # 来自 ORM text_snapshot 字段（FastAPI 自动映射）
    scene_type: str
    created_at: Optional[datetime]


class PersonaOutputItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    text_snapshot: str  # v0.4 修 / 字段名对齐 ORM persona_outputs.text_snapshot
    scene_type: str
    activity_id: Optional[int]
    shown_at: datetime


class PersonaRecentResponse(BaseModel):
    items: list[PersonaOutputItem]


@router.get("/output", response_model=PersonaOutputResponse)
def get_persona_output(
    scene_type: str = Query(..., regex="^[a-z_]+$"),
    activity_id: Optional[int] = Query(None),  # v0.2 修 / Claude A I-3 + Claude B I-9
    target_user_id: Optional[int] = Query(None),  # v0.4 修 / Codex I1 / user 看他人页时传被看者 id
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """前端按 scene_type + 可选 activity_id + 可选 target_user_id 拿 NPC 文案。

    - target_user_id=None → 看自己（self profile / detail / upload）
    - target_user_id != None → 看他人（user_page_open / 拿被看者的 NPC 输出）
    - activity_id 用于 detail 页精准拿当前活动的 NPC 文案 / 防串别 activity
    - 前端语义 scene_type（profile_open / user_page_open / activity_upload）走 service 退化逻辑
    """
    query_user_id = target_user_id if target_user_id is not None else user_id
    output = persona_service.get_latest_output_for_scene(
        db, query_user_id, scene_type, activity_id=activity_id
    )
    return PersonaOutputResponse(
        template_text=output.text_snapshot if output else None,  # v0.4 修 / 读 text_snapshot 不读 template_text
        scene_type=scene_type,
        created_at=output.shown_at if output else None,
    )


@router.get("/recent", response_model=PersonaRecentResponse)
def get_recent_outputs(
    limit: int = Query(10, ge=1, le=50),
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """前端拿用户最近 N 条 NPC 文案历史。"""
    outputs = persona_service.get_recent_outputs(db, user_id, limit)
    return PersonaRecentResponse(items=outputs)
```

**挂载到 `app/main.py`**（v0.2 修 / Claude B 抓 I-7 / 加进验收）：

```python
# app/main.py 顶部 import 区追加
from app.agent.persona.router import router as persona_router

# app.include_router 区追加
app.include_router(persona_router)
```

**验收**：`curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/persona/output?scene_type=profile_open` 返 200（不返 404 / 不返 5xx）。

### scheduler 容器 + 脚本（v0.2 修 / Claude B 抓 C5）

**docker-compose.yml 新增 `persona-scanner` 容器**（仿 cleanup 容器模式）：

```yaml
persona-scanner:
  build: .
  command: |
    bash -c "
      while true; do
        python scripts/persona_silence_scanner.py || true
        python scripts/persona_milestone_scanner.py || true
        sleep 86400  # 24h（v0.3 修 / 先跑后睡）
      done
    "
  depends_on:
    - db
    - redis
  # v0.4 修 / Claude B I2 / env_file 改为 environment 显式声明 / 最小权限 + 风格一致
  environment:
    DATABASE_URL: postgresql://velo:${DB_PASSWORD}@db:5432/velo
    REDIS_URL: redis://redis:6379/0
  restart: unless-stopped
```

**`scripts/persona_silence_scanner.py`**（一次性扫一遍 / 由 persona-scanner 容器 sleep 86400 循环调用）：

```python
"""扫所有 last_activity_days ≥ 7 的用户 / 发 silence_detected event 给 persona."""

from app.database import SessionLocal
from app.agent.persona import service as persona_service
from app.agent.persona.trigger_router import PersonaEvent

def scan():
    with SessionLocal() as db:
        users = _query_silent_users(db, days_threshold=7)
        for user in users:
            event = PersonaEvent(
                type="silence_detected",
                user_data={"user_id": user.id, "last_activity_days": user.days_since_last},
                timestamp=datetime.now(timezone.utc),
            )
            try:
                persona_service.generate_persona_output(event, db)
            except Exception as e:
                logger.warning(f"silence scanner skip user={user.id}: {e}")
                continue
            db.commit()
```

**`scripts/persona_milestone_scanner.py`**（每日 00:30 跑）：扫节气 / 周年 / 累计跨阈值。

注册到 cron / 或 RQ scheduler。

### 测试要求（`tests/test_persona_worker_hook.py` + `test_persona_endpoint.py` + `test_persona_scanner.py`）

最少 9 条 pytest：

1. **PR worker hook**：activity 完成 + 是 PR → persona_outputs 写入 1 条 scene_type='pr' 文案
2. **段位 worker hook**：activity 完成 + 非 PR + 80km + user 老登 → persona_outputs 写入 1 条 segment_distance/veteran_normal
3. **极端优先 worker hook**：activity 夜骑 → persona_outputs 写 extreme/night（不是 segment_distance）
4. **worker hook 失败兜底**（CRITICAL）：故意让 persona_service 抛 Exception → activity.status 仍是 'completed' / 不影响 detector / city / heatmap
5. **endpoint /output 返合法**：先插 persona_outputs / GET /api/persona/output?scene_type=pr → 返该条
6. **endpoint /output 返 null**：用户无 persona_outputs → 返 template_text=null（不返 404）
7. **endpoint /recent 分页**：GET /api/persona/recent?limit=5 → 返 5 条
8. **silence scanner**：mock 用户 last_activity 8 天前 → 跑 scanner → persona_outputs 写入 silence
9. **milestone scanner**：mock 用户累计 10000km / 跑 scanner → persona_outputs 写入 surprise/milestone

### 双审 focus

参 handoff § 2.3 + § 2.4。本 task **重点扫**：
- worker hook 是否真用 SAVEPOINT 隔离（rollback 不传染外层）
- endpoint 抛错是否被 service 顶层兜底返 200 + null（不返 5xx）
- scheduler 单个用户失败是否 continue 不让批次 fail
- 跨模块 reverse import 检测（activity worker 调 persona service / persona service **不能反向调** activity service）

### 依赖

- 依赖：task-3（service api）
- 阻塞：task-5（前端调 endpoint）

### 部署 verify

```bash
# endpoint 真用
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/persona/output?scene_type=profile_open"
# → 200 + {"template_text": ..., "scene_type": "profile_open", "created_at": ...}

# scheduler 跑一次
docker compose exec api python scripts/persona_silence_scanner.py
docker compose exec db psql -c "SELECT count(*) FROM persona_outputs WHERE scene_type='silence'"

# worker hook 真用：上传一条测试 activity → 看 persona_outputs 是否多 1 条
```

</details>
