# Sprint 7 Hotfix v5 — Strava 自动同步

> **状态**：v5 / Codex 三轮 + Claude 双审 + 真 POST 测试 ground truth + 自检嘴跳修正 + Codex round 3 3 Critical + 4 Important 全收敛
> **5 重 HTTPS 实证**已锁：Strava 接受 HTTP IP callback
> **完成判定**：Tim Strava 上传 → 7-15 秒（webhook 路径）or 10 分钟兜底（scheduler 路径）→ velo 列表自动出现 + 跑步永不入库 + 历史脏数据消失 + 总里程 / 城市勋章 / 热力图 / 排行榜不再被非骑行污染

---

## 0. 数据流全景图（一图看完）

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              你的真实使用场景                                       │
│  你骑完车 → Strava App 上传 → ⏱️ 等几秒到 1 分钟 → 打开 velo → 看到完整新活动     │
│  你点过同步按钮的次数：永远 0                                                       │
└─────────────────────────────────────────────────────────────────────────────────┘

═══════════════════════════════════════════════════════════════════════════════════
  正常路径（webhook 门铃 / 主路径 / 7-15 秒）
═══════════════════════════════════════════════════════════════════════════════════

  Strava 服务器
       │ 用户上传 → Strava 决定推送
       │ ⏱️ 5-10 秒（不可控 / Strava 端）
       ▼
  POST http://114.132.190.245/api/strava/webhook
       │ payload: {object_id, owner_id, subscription_id, aspect_type: "create"}
       ▼
  ┌──────────────────────────────────────────────┐
  │ velo api 容器 / router.py:215 webhook_receive │
  │  1. 校验 subscription_id（v4 task-7.4 防伪造） │
  │  2. 找 user by owner_id                       │
  │  3. _create_importing_activity (建 4 字段骨架) │
  │  4. default_queue.enqueue(...)  ← v4 新加      │
  │  5. return 200 给 Strava                      │
  │  ⏱️ < 200ms                                   │
  └─────────────┬────────────────────────────────┘
                │ enqueue 推任务到 Redis Queue "velo"
                ▼
  ┌─────────────────────┐
  │  Redis "velo" queue │ ← app/queue.py:59 default_queue
  │  [task1, task2, ...] │
  └─────────────┬───────┘
                │ worker 进程一直在监听 / dequeue
                │ ⏱️ < 200ms
                ▼
  ┌────────────────────────────────────────────────────────────┐
  │ worker 容器 / process_strava_webhook_create (v4 新文件)      │
  │  1. 抢锁 importing → processing                              │
  │  2. 调 Strava /activities/{id} 拉详情 (~1-3s)                │
  │  3. type / sport_type 守卫 → 非骑行 db.delete + return       │
  │  4. distance < 5km → db.delete（你拍 A 列表只显完整骑行）     │
  │  5. 调 Strava /streams 拉轨迹 (~1-3s)                        │
  │  6. save_parse_result 写 DB (~100-500ms)                    │
  │  7. 5 套 hook：city / heatmap / power_curve / 5min / persona│
  │  8. status = 'completed'                                    │
  └─────────────┬──────────────────────────────────────────────┘
                │ 写 DB
                ▼
  PostgreSQL activities + trackpoints + segment_efforts 表

                ▼ 你下次打开 velo 列表 endpoint 读 → 看到新活动卡片


═══════════════════════════════════════════════════════════════════════════════════
  兜底路径（scheduler 闹钟 / 平行独立 / 10 分钟内补救）
═══════════════════════════════════════════════════════════════════════════════════

  scheduler 容器（一直在跑 / 9 days Up）
       │ 每 15 秒 tick → run_import_tick()
       ▼
  ┌─────────────────────────────────────────────────────────┐
  │ _do_tick:                                                │
  │  1. _reactivate_idle_imports (v4 新加)                   │
  │     ↳ 扫 status='completed' AND updated_at > 10 分钟前   │
  │     ↳ 重置 status='active' + cursor_before=None +        │
  │        total_activities=None + tier1_completed=0         │
  │  2. _check_stale_imports (老 / 僵尸 24h 检测)            │
  │  3. _pick_next_task (按 status='active' 轮转)            │
  │  4. tier1 拉 list / type 守卫（v4 新加）/ 建骨架          │
  │  5. tier2 拉详情 / 守卫 / save / 5 套 hook (v4 修)        │
  └─────────────┬──────────────────────────────────────────┘
                │ 同样写 DB
                ▼
  PostgreSQL  ← webhook 路径 / 兜底路径 共用同一张表 / 通过
              strava_activity_id UNIQUE dedupe 防重复

═══════════════════════════════════════════════════════════════════════════════════
  故障自愈（独立 cleanup / 5 分钟扫一次）
═══════════════════════════════════════════════════════════════════════════════════

  cleanup 容器（一直在跑 / 13 days Up）
       │ 每 5 分钟 cleanup_stuck_activities
       ▼
   扫 activity.status='processing' 且 updated_at > 10 分钟没动
       ↓
   置 status='failed' (防 worker OOM 重启遗留卡死)

═══════════════════════════════════════════════════════════════════════════════════
  数据层防御（不依赖路径 / 任何脏数据进来都拦住）
═══════════════════════════════════════════════════════════════════════════════════

  你看到的页面          ← 加 activity_type='cycling' 过滤
  ────────────────
  列表 endpoint         ← Fix 5：activity/service.py:256
  个人统计 / 总里程     ← Fix 7：user/service_stats.py 3 处 SQL
  城市勋章 / heatmap    ← Fix 7：user/service_social.py 3 处 ORM
  dedupe 查重           ← Fix 7：activity/dedupe_service.py:127
  5min 功率进步检测     ← Fix 7：notification/progress_detector.py:115

  + 一次性脏数据清理 SQL（删历史 Strava Run / Hike / 空骨架）
  + DELETE notifications 显式先做（FK 是 SET NULL 不是 CASCADE）
  + redis-cli DEL heatmap:user_* 清缓存
```

---

## 1. 用户报的现象（一句话）

- **Bug A**：你 2026-05-18 上传的 55 km 公开 Evening Ride（strava_activity_id=18555652101）velo 永远拉不到
- **Bug B**：velo 列表里多出一条 5-14 Morning Run（type=Run / 0.96 km），点开数据全空

---

## 2. 真根因（含巧合解释）

**Bug A**：3 条同步通路全断
- webhook：`.env` 缺 `STRAVA_WEBHOOK_SUBSCRIPTION_ID` + handler 不 enqueue worker（只建骨架）
- scheduler 周期重启：原代码任务 completed 后无重置机制
- manual_sync：你拒绝点

**Bug B**：tier1 不过滤 type → Morning Run 被建空骨架 → activity_type 默认 'cycling'（`models.py:99-104` server_default）→ tier2 短距离分支 status='completed' + return 不回填 → 详情页按 cycling 渲染 → 全空

**为什么跑步进得来骑行进不来 = 时间窗错位**：5-16 你重绑 Strava 触发 import_id=6 窗口恰好覆盖 5-14 Morning Run；5-18 Evening Ride 在窗口之后没任何路径补拉。

---

## 3. v5 vs v3 关键变化（3 轮 Codex + spec/集成双审 + 自检 + 真 POST 实证 全收敛）

| 类型 | 来源 | 修订 |
|---|---|---|
| 🔴 Critical | Codex round 1 | Fix 4 重置时同步清 `total_activities=None + tier1_completed=0`（防 `_is_tier1_complete` 死循环） |
| 🔴 Critical | Codex round 1 | Fix 2 拆 create / update 独立路径 + `_wipe_activity_derived_data`（防 trackpoints 重复插入） |
| 🔴 Critical | Codex round 2 | 脏数据 SQL 先 `DELETE notifications WHERE activity_id IN (...)`（FK SET NULL 不是 CASCADE） |
| 🔴 Critical | 自检新发现 | **`activities.duplicate_of` FK 也是 SET NULL**（`models.py:121`）→ DELETE 主活动会让 dedupe 引用变 NULL → 重复活动重新出现。清理 SQL 前 SELECT 验证 |
| 🔴 Critical | spec 审 | Fix 2 update 路径 `_try_lock_importing` 锁条件 bug：update 路径**绕过此 helper**，直接重置状态走主流程 |
| 🔴 Critical | 集成审 | Fix 7 文件清单扩展：service_stats.py 三处 + service_social.py 三处 + dedupe_service.py + progress_detector.py 全加 `activity_type='cycling'` |
| 🔴 Critical | **Codex round 3** | **Fix 2 worker_strava 主流程补 dedupe + 赛段匹配**（save_parse_result 不触发 / 漏会导致新 Strava 骑行不进赛段 / 反馈链断 / 已 Edit 补） |
| 🔴 Critical | **Codex round 3** | **`PersonaEvent.from_activity_upload(activity)` 不存在**（凭印象写错 / 真实是手工构造）+ **补 user.city 推断**（GPX worker 350-390 段 v4 漏 / 已 Edit 补完整 5 段 hook） |
| 🔴 Critical | **Codex round 3** | **Fix 7 漏 3 处 social 聚合**：service_social.py:320-324 + 339-344 + 417-422（profile total/月度 + active_users）/ 表从 8 扩到 **11 处** |
| 🟠 Important | 集成审 | Fix 5 `total = query.count()` 时序：过滤先于 count |
| 🟠 Important | 集成审 | `_reactivate_idle_imports` 需 `(status, updated_at)` 复合索引（grep migrations 确认 / 100 用户量级以下不阻塞） |
| 🟠 Important | 集成审 | 脏数据 SQL 后 `redis-cli DEL heatmap:user_*` 清 1h TTL 缓存残留 |
| 🟠 Important | 集成审 | worker.py **不**加 `from app.strava import worker_strava`（RQ 动态 import 自动解析 / 不必要预热） |
| 🟠 Important | **Codex round 3** | **Fix 1 注册脚本 fallback 完整化**（GET 失败 / POST already exists / POST 无 id 三种 case 都 fail 不写 .env） |
| 🟠 Important | **Codex round 3** | **webhook vs scheduler 短距离行为统一**：webhook 也保留骨架 + 回填 `activity_type='other'`（不 db.delete）/ 列表 / stats 11 处过滤拦住 |
| 🟠 Important | **Codex round 3** | **脏数据 SQL Step 2 注释改正**：duplicate_of 自引用语义错；非空则停止删除人工决定 |
| 🟢 嘴跳修正 | 自检 | 之前回答 Tim "低耦合"时说"v4 用脏数据替代不改 stats / social" 是误读。**加 SQL `WHERE activity_type='cycling'` 过滤本身不破坏功能**（对 cycling 数据零行为变化）属于"加防御"不是"改正常逻辑"。保留改 stats / social 路径 + 不抽 helper / 不动 GPX worker |
| 🟢 真测 | 自检 | 真 POST `/push_subscriptions` 测试：Strava 返回 `"GET to callback URL does not return 200"`（不是"must be HTTPS"）→ HTTP 接受 + Strava 真去 GET HTTP callback handshake |

---

## 4. 修法清单（7 处 / 全部 file:line 锁定）

### Fix 1：注册 Strava push subscription + 补 .env

写一次性脚本 `scripts/strava_webhook_register.py`（**含完整 fallback / Codex round 3 Important-1**）：

```python
# Step 1: GET 现有 subscription
r_get = httpx.get(URL, params={...})
if r_get.status_code != 200:
    fail("GET subscriptions 失败，停止 / 不写 .env")  # 网络 / 凭证 / API 异常
existing = r_get.json()
if existing:  # 非空
    sub_id = existing[0]["id"]
    write_env(sub_id)
    return

# Step 2: POST 新建
r_post = httpx.post(URL, data={...})
if r_post.status_code == 201:
    sub = r_post.json()
    if "id" not in sub:
        fail("POST 响应无 id 字段 / 视为失败不写 .env")
    write_env(sub["id"])
    return

# Step 3: POST 失败 fallback
if r_post.status_code == 400 and "already exists" in r_post.text.lower():
    # Strava 服务端有但 GET 拿不到（同步延迟 / 边界 case）→ 再 GET 一次
    r_recheck = httpx.get(URL, params={...})
    if r_recheck.status_code == 200 and r_recheck.json():
        write_env(r_recheck.json()[0]["id"])
        return
    fail("POST already exists 但 GET 仍拿不到 / 需要 Strava 后台手动清理")

fail(f"POST 失败 status={r_post.status_code} body={r_post.text[:200]}")
```

每个 fail 路径**绝对不写 .env**（防误激活 + 留可追溯日志）。

部署：`docker compose up -d --build api` 让新 env 生效。

**副作用**：在 Strava 端创建一个 subscription。Tim 点头才跑。

### Fix 2：webhook handler 改 + 新增 worker_strava.py

**改 `service_sync.py:97-99`**：

```python
if aspect_type == "create":
    created = _create_importing_activity(db, user, object_id)
    if created:
        from app.queue import default_queue
        default_queue.enqueue(
            "app.strava.worker_strava.process_strava_webhook_create",
            user.id, object_id, job_timeout=120,
        )
elif aspect_type == "update":
    from app.queue import default_queue
    default_queue.enqueue(
        "app.strava.worker_strava.process_strava_webhook_update",
        user.id, object_id, job_timeout=120,
    )
```

**新建 `app/strava/worker_strava.py`**：

```python
"""Strava webhook 异步处理 worker（v4 / Sprint 7 hotfix）。

拆 create / update 独立路径：
- create：抢 importing → 拉详情 → save → hooks
- update：清派生数据 → 重新走 create 主流程（不复用 _try_lock_importing 因状态已 processing）
"""
from datetime import datetime, timezone
from sqlalchemy import update as sql_update
from sqlalchemy.sql import func
from app.database import SessionLocal
from app.activity.models import Activity, Trackpoint
from app.user.models import User
from app.strava.client import StravaClient
from app.strava.import_scheduler import _CYCLING_TYPES, _MIN_DISTANCE_METERS
from app.parsing.strava_adapter import from_streams
from app.parsing.coord_normalizer import normalize
from app.activity.worker import save_parse_result, _set_activity_city
from app.segment.models import SegmentEffort
from app.notification.models import Notification
import logging

logger = logging.getLogger(__name__)


def _is_cycling(detail_or_list_item: dict) -> bool:
    """type 主 + sport_type 备（防 Strava 把 GravelRide 设为 type=Workout）"""
    t = detail_or_list_item.get("type", "")
    s = detail_or_list_item.get("sport_type", "")
    return t in _CYCLING_TYPES or s in _CYCLING_TYPES


def process_strava_webhook_create(user_id: int, strava_activity_id: int) -> None:
    """create 事件：抢 importing 锁 + 跑主流程。"""
    db = SessionLocal()
    try:
        # 1. 原子抢锁 importing → processing
        result = db.execute(
            sql_update(Activity)
            .where(
                Activity.strava_activity_id == strava_activity_id,
                Activity.status == "importing",
            )
            .values(status="processing", updated_at=func.now())
            .returning(Activity.id)
        )
        row = result.fetchone()
        db.commit()
        if row is None:
            logger.info("webhook create 抢锁失败（已被处理）strava_id=%d", strava_activity_id)
            return
        _process_strava_main(db, user_id, strava_activity_id)
    finally:
        db.close()


def process_strava_webhook_update(user_id: int, strava_activity_id: int) -> None:
    """update 事件：
    - activity 不存在 → 当 create 处理
    - activity 已 completed → 清派生数据 + 重置 status → 走主流程
    - activity importing / processing → 让 create 路径 / 自愈处理（避免并发）
    """
    db = SessionLocal()
    try:
        activity = db.query(Activity).filter_by(
            strava_activity_id=strava_activity_id
        ).first()
        if activity is None:
            user = db.query(User).filter_by(id=user_id).first()
            if user and user.strava_athlete_id is not None:
                from app.strava.service_sync import _create_importing_activity
                _create_importing_activity(db, user, strava_activity_id)
                # 重入抢锁
                process_strava_webhook_create(user_id, strava_activity_id)
            return

        if activity.status in ("importing", "processing"):
            # create worker 已在处理 / 5min cleanup 会兜底 / 此次 update 跳过
            logger.info("update 跳过：activity 已在处理中 strava_id=%d", strava_activity_id)
            return

        if activity.status != "completed":
            logger.info("update 跳过：activity 状态 %s 不处理", activity.status)
            return

        # completed 路径：清派生 + 重置 → 主流程
        _wipe_activity_derived_data(db, activity)
        activity.status = "processing"
        activity.updated_at = datetime.now(timezone.utc)
        db.commit()
        _process_strava_main(db, user_id, strava_activity_id)
    finally:
        db.close()


def _process_strava_main(db, user_id: int, strava_activity_id: int) -> None:
    """主流程：拉详情 + 守卫 + 拉轨迹 + save + 5 套 hook。"""
    activity = db.query(Activity).filter_by(
        strava_activity_id=strava_activity_id
    ).first()
    user = db.query(User).filter_by(id=user_id).first()
    if activity is None or user is None or user.strava_athlete_id is None:
        return

    client = StravaClient(db, user)  # 真签名：db + User 对象

    try:
        detail = client.get_activity_detail(strava_activity_id)
    except Exception as e:
        activity.status = "failed"
        activity.error_message = str(e)[:200]
        db.commit()
        return

    # 非骑行：保留骨架 + 回填 activity_type 真实值（与 scheduler tier2 一致 / Codex round 3 Important-2 统一）
    # 列表 / stats / heatmap 11 处过滤会拦住不显示
    if not _is_cycling(detail):
        strava_type = detail.get("type", "")
        _type_lower = strava_type.lower()
        if "run" in _type_lower:
            activity.activity_type = "running"
        elif "hike" in _type_lower or "walk" in _type_lower:
            activity.activity_type = "hiking"
        else:
            activity.activity_type = "other"
        activity.status = "completed"
        db.commit()
        logger.info("非骑行保留骨架（列表层过滤拦住）strava_id=%d type=%s mapped=%s",
                    strava_activity_id, strava_type, activity.activity_type)
        return

    # 短距离：保留骨架 + 回填 other（与 scheduler tier2 短距离一致 / Codex round 3 Important-2 统一）
    if (detail.get("distance") or 0) < _MIN_DISTANCE_METERS:
        activity.activity_type = "other"
        activity.status = "completed"
        db.commit()
        logger.info("短距离保留骨架 strava_id=%d distance=%.0f",
                    strava_activity_id, detail.get("distance") or 0)
        return

    try:
        streams = client.get_activity_streams(strava_activity_id)
    except Exception as e:
        activity.status = "failed"
        activity.error_message = str(e)[:200]
        db.commit()
        return

    ftp = int(user.ftp) if user.ftp else None
    parse_result = normalize(from_streams(streams, detail, ftp=ftp))
    save_parse_result(db, activity, parse_result)
    activity.status = "completed"

    # dedupe（GPX 上传 vs Strava 同步同一骑行 / 防双份）/ SAVEPOINT 隔离
    # 对照 import_scheduler.py:438-446 真实 pattern
    is_duplicate = False
    try:
        from app.activity.dedupe_service import find_and_mark_duplicate
        nested_dup = db.begin_nested()
        try:
            marked_id = find_and_mark_duplicate(db, activity)
            is_duplicate = marked_id is not None
            db.flush()
            nested_dup.commit()
        except Exception:
            nested_dup.rollback()
    except Exception:
        pass

    # post-parse hooks（is_duplicate=True 时跳过 / 与 GPX worker 同 pattern）
    if not is_duplicate:
        _strava_post_parse_hooks(db, activity)

    db.commit()

    # 赛段匹配（在 commit 之后 / 与 import_scheduler.py:461-470 同 pattern / auto_match 内部自己管事务）
    if not is_duplicate:
        try:
            from app.segment.auto_match import match_activity_against_segments
            match_activity_against_segments(activity.id, db)
        except Exception:
            logger.exception("赛段匹配失败 activity_id=%d strava_id=%d",
                            activity.id, strava_activity_id)


def _strava_post_parse_hooks(db, activity) -> None:
    """完整复制 GPX worker (app/activity/worker.py:313-460) 5 套 hook + 每个 SAVEPOINT。

    顺序严格对照 GPX worker（5 段 / 失败不阻断 status='completed'）：
    1. detect_5min_power_progress (5min 功率进步通知)
    2. invalidate caches (heatmap + power_curve)
    3. _set_activity_city (activity.city / 起点城市)
    4. user.city 推断 (worker.py:350-390 / 仅 user.city 为 None 时)
    5. persona engine NPC (worker.py:392-460 / 手工构造 PersonaEvent 不是 .from_activity_upload)
    """
    from datetime import datetime, timezone

    # 1. detect_5min_power_progress
    try:
        from app.notification.progress_detector import detect_5min_power_progress
        nested = db.begin_nested()
        try:
            detect_5min_power_progress(db, activity.user_id, activity.id)
            db.flush()
            nested.commit()
        except Exception:
            nested.rollback()
    except Exception:
        pass

    # 2. invalidate caches (Redis / 失败不阻断 / 无 SAVEPOINT 因不动 DB)
    try:
        from app.user.service import invalidate_power_curve_cache, invalidate_heatmap_cache
        invalidate_power_curve_cache(activity.user_id)
        invalidate_heatmap_cache(activity.user_id)
    except Exception:
        pass

    # 3. activity.city (起点城市 / SAVEPOINT 隔离)
    try:
        nested = db.begin_nested()
        try:
            _set_activity_city(activity, activity.simplified_track)
            db.flush()
            nested.commit()
        except Exception:
            nested.rollback()
    except Exception:
        pass

    # 4. user.city 推断 (Codex round 3 Critical-2 补 / GPX worker.py:350-390 完整对照)
    try:
        from app.common.geo import infer_city_from_coords
        nested_user_city = db.begin_nested()
        try:
            user = (
                db.query(User)
                .filter(User.id == activity.user_id)
                .with_for_update()
                .populate_existing()
                .first()
            )
            if user is not None and user.city is None and activity.simplified_track:
                track = activity.simplified_track
                if len(track) > 0:
                    first_pt = track[0]
                    lat = first_pt.get("lat")
                    lon = first_pt.get("lon")
                    if lat is not None and lon is not None:
                        user.city = infer_city_from_coords(lat, lon)
            db.flush()
            nested_user_city.commit()
        except Exception:
            nested_user_city.rollback()
    except Exception:
        pass

    # 5. persona NPC (Codex round 3 Critical-2 修正：手工构造 PersonaEvent / 不是 .from_activity_upload)
    # 严格对照 GPX worker.py:402-470 / 含 activity_uploaded + consecutive_high_detected 双路
    try:
        from app.agent.persona import service as persona_service
        from app.agent.persona.trigger_router import PersonaEvent
        # 反向 import GPX worker 的 helper（_前缀 Python underscore 是约定不强制 private）
        # 替代是把它们抽到共享模块 / 但会动 GPX worker import → 违反 Tim 低耦合
        from app.activity.worker import _query_weekly_count, _detect_pr, _query_total_distance

        nested_persona = db.begin_nested()
        try:
            db.flush()  # 让本 activity 进 session 可见 / 影响 weekly_count
            weekly_count = _query_weekly_count(activity.user_id, db)
            is_pr = _detect_pr(activity, activity.user_id, db)
            total_distance_m = _query_total_distance(activity.user_id, db)

            upload_event = PersonaEvent(
                type="activity_uploaded",
                activity_data={
                    "id": activity.id,
                    "distance": activity.distance,
                    "elevation_gain": activity.elevation_gain,
                    "duration": activity.duration,
                    "moving_time": activity.moving_time,
                    "started_at": activity.started_at,
                    "avg_speed_kmh": (activity.avg_speed * 3.6) if activity.avg_speed else None,
                    "avg_power": activity.avg_power,
                    "normalized_power": activity.normalized_power,
                    "is_pr": is_pr,
                    "is_rain": False,
                },
                user_data={
                    "user_id": activity.user_id,
                    "total_distance_m": total_distance_m,
                    "weekly_count": weekly_count,
                    "last_activity_days": 0,
                },
                timestamp=datetime.now(timezone.utc),
            )
            persona_service.generate_persona_output(upload_event, db)

            if weekly_count >= 5:
                ch_event = PersonaEvent(
                    type="consecutive_high_detected",
                    user_data={
                        "user_id": activity.user_id,
                        "weekly_count": weekly_count,
                    },
                    timestamp=datetime.now(timezone.utc),
                )
                persona_service.generate_persona_output(ch_event, db)

            db.flush()
            nested_persona.commit()
        except Exception:
            nested_persona.rollback()
    except Exception:
        pass


def _wipe_activity_derived_data(db, activity) -> None:
    """update 路径清派生数据（防 save_parse_result 重复插 trackpoints / segment_efforts 残留）。

    清理：trackpoints / segment_efforts / notifications + activity 派生字段
    保留：user.city / persona_outputs / Redis cache（hook 会重 invalidate）
    """
    db.query(Trackpoint).filter_by(activity_id=activity.id).delete(synchronize_session=False)
    db.query(SegmentEffort).filter_by(activity_id=activity.id).delete(synchronize_session=False)
    db.query(Notification).filter_by(activity_id=activity.id).delete(synchronize_session=False)
    activity.simplified_track = None
    activity.splits = None
    activity.power_zones = None
    db.flush()
```

**`_CYCLING_TYPES` 和 `_MIN_DISTANCE_METERS`** 已存在 `import_scheduler.py:45`，import 即可。

**RQ 反射 import**：worker.py **不需要**预先 import worker_strava（RQ 通过字符串路径动态 importlib / 集成审 Important-2 确认）。

### Fix 3：tier1 / tier2 加 _is_cycling 守卫（双保险）

**`import_scheduler.py`**：

1. 顶层抽 `_is_cycling(activity_dict)` helper（worker_strava 已用 / 这里同源）：

```python
def _is_cycling(act: dict) -> bool:
    t = act.get("type", "")
    s = act.get("sport_type", "")
    return t in _CYCLING_TYPES or s in _CYCLING_TYPES
```

2. **`_run_tier1` 循环 :242-264**：cursor 推进**之后**、dedupe **之前**加：

```python
if not _is_cycling(act):
    logger.info("tier1 跳过非骑行 strava_id=%s", strava_id)
    continue
```

3. **`_run_tier2` :380**：改成调 helper（spec 审 Important-1）：

```python
# 原：if strava_activity_type not in _CYCLING_TYPES:
if not _is_cycling(detail):
    ...
```

4. **短距离 + 非骑行分支保留 `status='completed'` + 补 activity_type 回填**：
   - 短距离分支 :354-362 加 `activity.activity_type = "cycling"`（回填 / 不破坏 tier2_skipped 累计）
     - **修订**（v5 集成审 reviewer Important-1 / Tim 拍）：tier1 `_is_cycling` 守卫已保证短距离分支接到的活动 100% 是骑行。原 v5 草稿写 "other" 是 spec 自身遗漏 tier1 守卫前提 / 会让 <5km 通勤短骑行被 Fix 5/7 数据层过滤后从列表/总里程消失。改 "cycling" 让用户的真骑行不论长短都进 velo。
   - 非骑行分支 :380-394 已有回填 / 不动
   - **不改成 db.delete**（v3 一度提议改 / spec 审 Important-4 指出会破坏 tier2_skipped 语义）

### Fix 4：scheduler 周期重启 idle import_task（v4 完整版）

**`import_scheduler.py:_do_tick`** 开头加：

```python
def _do_tick(db) -> None:
    _reactivate_idle_imports(db)      # v4 新增
    _check_stale_imports(db)           # 原 24h 僵尸扫描
    import_task = _pick_next_task(db)
    ...


def _reactivate_idle_imports(db) -> None:
    """周期重启 idle 用户的 import_task / 兜底 webhook 漏接。

    Codex Critical 1 修法：必须同步清 total_activities + tier1_completed + cursor_before，
    否则 _is_tier1_complete 仍返 true 死循环。

    频率：10 分钟 / 用户。Strava 100/15min 配额对 1 用户余量足够。
    50+ 用户量级需要切 webhook 优先（写 §6 backlog）。
    """
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
    idle = (
        db.query(StravaImport)
        .filter(StravaImport.status == "completed",
                StravaImport.updated_at < cutoff)
        .order_by(StravaImport.updated_at.desc())
        .all()
    )
    seen = set()
    reactivated = 0
    for task in idle:
        if task.user_id in seen:
            continue
        seen.add(task.user_id)
        task.status = "active"
        task.cursor_before = None       # 让 tier1 从最新开始
        task.total_activities = None     # 让 _is_tier1_complete 返 false
        task.tier1_completed = 0         # 累计重置（前端进度卡片若展示会倒退 / spec 审 Important-2 / 100 用户量级以下可接受 / backlog 升级展示方案）
        reactivated += 1
    if reactivated:
        db.commit()
        logger.info("周期重启 %d 个 idle 导入任务", reactivated)
```

**索引检查**（集成审 Important-3）：
- grep `Index.*StravaImport\|status.*updated_at` 在 migrations/ 看是否已有复合索引
- 100 用户量级以下不阻塞，记 backlog

### Fix 5：列表 endpoint 加双重过滤（v4 / 时序修正）

**`app/activity/service.py:256 get_activity_list`** 改 query 顺序：

```python
query = (
    db.query(Activity)
    .filter_by(user_id=user_id)
    .filter(Activity.duplicate_of.is_(None))
    .filter(Activity.activity_type == "cycling")       # v4 新增
    .filter(Activity.status == "completed")            # v4 新增
)
total = query.count()  # 集成审 Important-5：count 必须在过滤后
items = query.order_by(...).offset(...).limit(...).all()
```

### Fix 6：handle_manual_sync 加 _is_cycling 守卫

**`service_sync.py:298-310`** 循环开头加：

```python
for act in activities:
    strava_id = act.get("id")
    if strava_id is None:
        continue
    if not _is_cycling(act):                # v4 新增 / 从 import_scheduler import
        logger.info("manual_sync 跳过非骑行 strava_id=%s", strava_id)
        continue
    created = _create_importing_activity(db, user, strava_id)
    ...
```

### Fix 7：数据层 11 处全加 activity_type='cycling'（集成审 + Codex round 3 Critical-3）

| 文件 | 行 | 类型 | 用途 | 改动 |
|---|---|---|---|---|
| `app/user/service_stats.py` | 124 | 裸 SQL (period) | 用户统计 / 本周本月本年 | `AND activity_type = 'cycling'` |
| `app/user/service_stats.py` | 139 | 裸 SQL (all-time) | 用户统计 / 全部 | `AND activity_type = 'cycling'` |
| `app/user/service_stats.py` | 274 | ORM (power_curve) | 功率曲线 | `.filter(Activity.activity_type == "cycling")` |
| `app/user/service_social.py` | 168 | ORM (heatmap) | 热力图 | `.filter(Activity.activity_type == "cycling")` |
| `app/user/service_social.py` | **320-324** | ORM (profile total/count) | **他人主页总里程 / 活动数（Codex round 3 抓 / spec/集成审漏）** | `.filter(Activity.activity_type == "cycling")` |
| `app/user/service_social.py` | **339-344** | ORM (profile 月度) | **他人主页月度统计** | `.filter(Activity.activity_type == "cycling")` |
| `app/user/service_social.py` | **417-422** | ORM (get_active_users) | **探索页活跃骑友** | `.filter(Activity.activity_type == "cycling")` |
| `app/user/service_social.py` | 509 | ORM (badges) | 总里程勋章 | `.filter(Activity.activity_type == "cycling")` |
| `app/user/service_social.py` | 582 | ORM (city medals) | 城市勋章 | `.filter(Activity.activity_type == "cycling")` |
| `app/activity/dedupe_service.py` | 127 | ORM | GPX vs Strava 同骑行 dedupe 查重 | `.filter(Activity.activity_type == "cycling")` |
| `app/notification/progress_detector.py` | 115 | ORM | 5min 功率进步检测 | `.filter(Activity.activity_type == "cycling")` |

**11 处全改 / 一次性扫干净 / 未来产生任何非骑行 completed 活动都被数据层 11 层拦住**。

**Codex round 3 抓的 3 处 social 漏点**（粗体 line 320-324 + 339-344 + 417-422）独立验证：grep `Activity.status == "completed"` + 这三个函数定义确认真无 activity_type 过滤。

### 脏数据清理 SQL（部署后跑一次 / FK 防御版）

```sql
-- Step 1: SELECT 验证目标行（dry-run）
SELECT id, strava_activity_id, title, activity_type, distance, started_at
FROM activities
WHERE data_source = 'strava'
  AND status = 'completed'
  AND (activity_type != 'cycling' OR simplified_track IS NULL);
-- 预期：至少 Morning Run id=421 / Tim 部署前肉眼确认范围

-- Step 2: 检查是否被 duplicate_of 引用（FK SET NULL 风险）
SELECT id, duplicate_of
FROM activities
WHERE duplicate_of IN (
    SELECT id FROM activities
    WHERE data_source = 'strava'
      AND status = 'completed'
      AND (activity_type != 'cycling' OR simplified_track IS NULL)
);
-- 期望空。**如非空 → 停止删除！** 不要自引用 duplicate_of → 自己的 id（语义错 + 仍被 IS NULL 过滤）
-- 正确处理：人工逐条决定保留哪份 canonical / 重跑 dedupe / 或单独处理被引用的主活动
-- 然后才能跑 Step 3-5（Codex round 3 Important-3）

-- Step 3: 先 DELETE notifications（FK SET NULL 不是 CASCADE）
DELETE FROM notifications
WHERE activity_id IN (
    SELECT id FROM activities
    WHERE data_source = 'strava'
      AND status = 'completed'
      AND (activity_type != 'cycling' OR simplified_track IS NULL)
);

-- Step 4: DELETE activities（CASCADE 自动清 trackpoints / segment_efforts / activity_privacy）
DELETE FROM activities
WHERE data_source = 'strava'
  AND status = 'completed'
  AND (activity_type != 'cycling' OR simplified_track IS NULL);

-- Step 5: 清 Redis heatmap 缓存（集成审 Important）
-- redis-cli KEYS "heatmap:user_*" | xargs redis-cli DEL
-- redis-cli KEYS "power_curve:user_*" | xargs redis-cli DEL
```

---

## 5. 实施顺序（中间状态都安全）

```
1. Fix 4 scheduler 兜底先（先建保险网）
2. Fix 3 tier1 / tier2 守卫（防新数据继续污染）
3. Fix 6 manual_sync 守卫（同上）
4. Fix 7 数据层 8 处过滤（防御纵深）
5. Fix 5 list 端点过滤
6. 脏数据 SQL（在生产手动跑 / 含 redis-cli DEL）
7. Fix 1 注册 subscription（停下来给 Tim 看脚本输出 + 点头 / 真生产副作用）
8. Fix 2 worker_strava.py + handler 改 enqueue
9. 部署 + 真用回归 4 场景
```

每步 commit + 跑相应 pytest。完成后 commit 前再派 Codex 审真 diff。

---

## 6. 真用回归 4 场景（Tim 24h 内必跑）

1. **webhook create**：Strava 上传新 ≥5km 公开骑行 → 30s 内 velo 列表出现 + 详情完整
2. **webhook update**：Strava 改活动名 → 30s 内 velo 列表标题更新 / trackpoints 不翻倍
3. **scheduler 兜底**：临时 DELETE subscription（Fix 1 脚本反向）+ 上传新活动 → 10 分钟内自动出现 / 然后恢复 subscription
4. **跑步不入库**：Strava 上传一条跑步 → webhook 收到 + worker 删活动日志 + velo 列表永不出现

---

## 7. 次要风险（sprint 8 backlog）

| # | 内容 | 不修理由 |
|---|---|---|
| 7.1 | token DB expires_at refresh 后没回写 | 续期机制有效 / 一行代码 |
| 7.2 | webhook HMAC X-Strava-Signature 升级（subscription_id → HMAC） | 主路径 5 重证据 + subscription_id 校验已足 / 安全升级独立 task |
| 7.3 | 域名备案 + HTTPS（含 OAuth callback 也升级） | HTTP 已 5 重实证 / 安全升级独立 |
| 7.4 | 50+ 用户量级切 webhook 优先关 scheduler 周期重启 | 当前 1 真用户 / 资源压力 0 |
| 7.5 | `tier1_completed` 前端进度卡片倒退（如展示） | 当前前端无此页面 / 有展示再加恢复值字段 |
| 7.6 | StravaImport `(status, updated_at)` 复合索引 | 100 用户量级以下不阻塞 |
| 7.7 | webhook create + update 并发竞争（worker 在跑 update 又来）| 当前用 `status in (importing, processing)` 跳过 update 兜底 / 5min cleanup 自愈兜底 / sprint 8 加 with_for_update 行锁 |

---

## 8. EOF
