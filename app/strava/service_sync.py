"""
Strava 同步子模块——"海关 + 行李托运"。

干啥用：
    - Strava 主动推 webhook 通知（新活动 / 删除 / 撤销授权）
    - 用户点"手动同步"按钮按需拉最近 30 条活动
    - 查询导入进度（前端轮询用）

类比：
    海关 + 行李托运处：
    - 入境班机进站（webhook create/update）→ 给每件行李挂"运送中"标签（_create_importing_activity）
    - 旅客撤销报关（athlete delete）→ 暂停所有运送任务（_handle_athlete_deauthorize）
    - 旅客主动来问"我的箱子到了几件"（handle_manual_sync）
    - 查询行李进度（get_import_progress）

操作注意：
    - **冷却 5 分钟**：手动同步每用户 5min 一次（Redis NX EX 原子）避免烧光每日 1000 API 额度
    - **dedupe**：strava_activity_id 已存在则跳过（IntegrityError 兜底防并发竞态）
    - **view_status vs db_status**：active 但 5 分钟无 update → stalled（视图层派生态 / DB 不存）
    - **私有 _handle_athlete_deauthorize**：撤销授权时不删 Activity 记录（用户可能还想看）/ 仅暂停 strava_imports + 清 token
    - **私有 _create_importing_activity**：webhook 和 manual_sync 都用 / 只建骨架不拉详情

数据流：
    入：webhook payload / user_id（manual sync 触发）/ user_id（progress 查询）
    出：None（webhook）/ {new_activities, message}（manual sync）/ {view_status, db_status, total, ...}（progress）
    边界：直接读写 user / activity / strava_imports 表 + Redis 冷却 key + 调 StravaClient 拉远端

不允许：
    - import service_oauth / service_token（保持单向依赖 / token 刷新由 StravaClient 内部调）
    - 加同步类型的"新模式"（如批量补传）不该塞这文件 / 走独立子模块

v5 task-strava-split-001：从 service.py 906 行拆出（commit TBD）。
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.user.models import User

logger = logging.getLogger(__name__)


def handle_webhook_event(db: Session, payload: dict) -> None:
    """
    处理 Strava Webhook 事件——Strava 主动告诉我们"有新活动了"。

    好比快递通知：你订了个包裹，快递到了柜子里，菜鸟驿站发短信通知你去取。
    Strava 就是菜鸟驿站，这个函数就是处理短信的逻辑。

    事件类型：
    - activity create/update → 入 RQ 队列拉详情+轨迹
    - activity delete → 删除对应 Activity
    - athlete delete → 用户撤销授权，清除 Strava token
    """
    object_type = payload.get("object_type")
    aspect_type = payload.get("aspect_type")
    object_id = payload.get("object_id")
    owner_id = payload.get("owner_id")

    logger.info(
        "收到 Strava Webhook object_type=%s aspect_type=%s object_id=%s owner_id=%s",
        object_type, aspect_type, object_id, owner_id,
    )

    # 忽略非活动事件（athlete update 等）
    if object_type == "athlete":
        if aspect_type == "delete":
            # 用户在 Strava 端撤销了授权
            _handle_athlete_deauthorize(db, owner_id)
        return

    if object_type != "activity":
        return

    # 找到对应的系统用户
    user = db.query(User).filter_by(strava_athlete_id=owner_id).first()
    if user is None:
        logger.info("Webhook 找不到用户 owner_id=%s，忽略", owner_id)
        return

    if aspect_type == "delete":
        # 用户在 Strava 上删了这条活动
        # 安全校验：确认这条 Activity 属于 owner_id 对应的用户，防止伪造 delete 事件
        from app.activity.models import Activity
        activity = db.query(Activity).filter_by(
            strava_activity_id=object_id, user_id=user.id
        ).first()
        if activity:
            db.delete(activity)
            db.commit()
            logger.info("删除 Strava 活动 strava_id=%s activity_id=%d", object_id, activity.id)
        return

    # Sprint 8 Fix 2：webhook 拆 create / update 独立路径 + RQ worker 异步处理
    # webhook payload 只含 strava_activity_id（不含 type）/ 必须 worker 拉详情后才能守卫
    # type，所以 type 守卫在 worker_strava._process_strava_main 内做。
    if aspect_type == "create":
        # 先建 importing 骨架（活动列表立刻有 / 哪怕详情还没拉）
        # spec 字面要求 if created: 守卫——重复 webhook（Strava 偶尔重发）或
        # scheduler tier1 已建骨架时 / created=False / 不重复 enqueue 防 RQ 队列污染
        created = _create_importing_activity(db, user, object_id)
        if created:
            from app.queue import default_queue
            default_queue.enqueue(
                "app.strava.worker_strava.process_strava_webhook_create",
                user.id, object_id, job_timeout=120,
            )
    elif aspect_type == "update":
        # update 不建骨架（worker 自己判断 activity 是否存在 / 不存在则当 create 处理）
        from app.queue import default_queue
        default_queue.enqueue(
            "app.strava.worker_strava.process_strava_webhook_update",
            user.id, object_id, job_timeout=120,
        )


def _handle_athlete_deauthorize(db: Session, owner_id) -> None:
    """
    用户在 Strava 端撤销授权——清空 token + 暂停导入任务。

    不清理 importing 状态的 Activity（保留骨架让用户看到不完整的记录），
    但暂停 strava_imports 任务，防止调度器继续尝试（token 已失效）。
    """
    user = db.query(User).filter_by(strava_athlete_id=owner_id).first()
    if user is None:
        return

    logger.warning("用户撤销 Strava 授权 user_id=%d owner_id=%s", user.id, owner_id)

    # 暂停该用户的所有 active 导入任务
    from app.strava.models import StravaImport
    active_imports = (
        db.query(StravaImport)
        .filter_by(user_id=user.id, status="active")
        .all()
    )
    for imp in active_imports:
        imp.status = "paused"

    # 清空 Strava 字段
    user.strava_athlete_id = None
    user.strava_access_token = None
    user.strava_refresh_token = None
    user.strava_token_expires_at = None
    db.commit()


def unbind_strava(db: Session, user_id: int) -> None:
    """
    主动解绑 Strava——用户在 velo 设置页点"解绑"时调用。

    与 _handle_athlete_deauthorize 的行为对齐（Sprint 6 task-5 v0.3 集成审 Critical）：
    主动解绑（velo 端发起）与被动撤销（Strava 端发起 webhook）效果一致——
    清 4 个 token 字段 + 暂停 active 导入任务 + 保留历史活动。

    清空 User 表 4 字段：
        - strava_athlete_id（BigInteger / unique / **不是 strava_user_id**）
        - strava_access_token
        - strava_refresh_token
        - strava_token_expires_at

    同事务把该用户所有 active 的 strava_imports → paused：
        - 防调度器下一 tick 继续 pick 该 active job 白消耗 API
        - 防重新绑定后 active 行对新 token 继续导入触发 dedupe 冲突
        completed / paused 行**状态不变**（只动 active）

    不做的事：
        - **不删 activities**（已导入的历史活动保留 / 用户可能还想看）
        - **不删 strava_imports 行**（只改 status）
        - **不调 Strava API 主动撤销授权**（用户自行去 Strava 后台撤销 / 简化设计）

    并发场景：解绑时 worker 正用旧 token 同步 → token 清空后 worker 下次调用
    拿到 NULL → ensure_valid_token 抛 UnboundStravaError → handle_strava_api_call 容错
    跳过（在 service_token.py 已实现 / 不在本函数 scope）。

    类比：办了张健身卡（access_token）但不想去了——
    去前台把卡注销了（清字段）+ 让教练别再给你打电话约课（pause 导入任务）+
    历史训练记录保留在档案柜（活动不删）+ 你也没主动告诉健身房集团总部去销户
    （不调 Strava API）。
    """
    # 用 .first() 不用 .one()（CLAUDE.md 陷阱 #4 / 三审 Critical 修 / 与 _handle_athlete_deauthorize 既有 pattern 对齐）：
    # .one() 在 user 不存在时抛 NoResultFound / FastAPI 无全局 handler → 500 而不是 404
    # 概率小但真实场景（JWT 有效但用户已被 admin purge / 数据不一致）
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise ValueError(f"用户不存在 user_id={user_id}")

    # Sprint 6 task-5 三审 Important 修（B 集成审独占）：解绑时 importing 骨架活动→failed
    # 防止用户主页永久"加载中"显示——worker 已拿不到 token / 这些骨架不会再被填充。
    # 同事务一起改 / 与 active imports → paused 同 pattern。
    from app.activity.models import Activity
    importing_count = (
        db.query(Activity)
        .filter(
            Activity.user_id == user_id,
            Activity.status == "importing",
        )
        .update({Activity.status: "failed"}, synchronize_session=False)
    )
    if importing_count > 0:
        logger.info(
            "用户主动解绑 自动把 %d 个 importing 骨架活动转 failed user_id=%d",
            importing_count, user_id,
        )

    # 先暂停 active 导入任务（顺序与 _handle_athlete_deauthorize 401 分支一致：
    # 先 pause 让调度器停下 / 再清 token / 保证即使后续 commit 中途异常，
    # 调度器也不会拿旧 token 继续空跑）
    from app.strava.models import StravaImport
    paused_count = (
        db.query(StravaImport)
        .filter(
            StravaImport.user_id == user_id,
            StravaImport.status == "active",
        )
        .update({StravaImport.status: "paused"}, synchronize_session=False)
    )
    if paused_count > 0:
        logger.info(
            "用户主动解绑 自动 pause %d 个 active 导入任务 user_id=%d",
            paused_count, user_id,
        )

    # 清空所有 Strava 字段
    user.strava_athlete_id = None
    user.strava_access_token = None
    user.strava_refresh_token = None
    user.strava_token_expires_at = None

    db.commit()
    logger.info("用户主动解绑 Strava user_id=%d", user_id)


def _create_importing_activity(db: Session, user: User, strava_activity_id) -> bool:
    """
    为单条 Strava 活动创建 importing 状态的骨架记录。

    实际的详情+轨迹拉取由调度器（import_scheduler）周期性处理，
    这里只创建骨架——让用户尽快在列表中看到"有新活动在导入"。

    去重：先查 strava_activity_id 是否已存在，已存在则跳过。
    返回 True 表示创建了新活动，False 表示跳过。
    """
    from app.activity.models import Activity

    # 去重检查
    existing = db.query(Activity).filter_by(strava_activity_id=strava_activity_id).first()
    if existing:
        logger.info("跳过已存在的 Strava 活动 strava_id=%s", strava_activity_id)
        return False

    # 创建骨架 Activity（详情由调度器或 Worker 异步填充）
    activity = Activity(
        user_id=user.id,
        status="importing",
        file_url=None,
        data_source="strava",
        strava_activity_id=strava_activity_id,
    )

    try:
        db.add(activity)
        db.commit()
    except IntegrityError:
        db.rollback()
        logger.info("跳过已存在的 Strava 活动（并发） strava_id=%s", strava_activity_id)
        return False

    logger.info(
        "Webhook 创建 importing 活动 strava_id=%s activity_id=%d user_id=%d",
        strava_activity_id, activity.id, user.id,
    )
    return True


def handle_manual_sync(db: Session, user_id: int) -> dict:
    """
    手动同步——用户点"同步 Strava"按钮时调用。

    每次调用消耗 1 次 Strava API 额度（全 App 共享每天 1000 次），
    所以加了 5 分钟冷却时间，防止用户疯狂点同步按钮烧光额度。

    拉取最近 30 条活动，新的入库，已有的跳过。
    返回新发现了几条。
    """
    from app.strava.client import StravaClient
    from app.activity.models import Activity
    # Sprint 7 Fix 6：复用 import_scheduler 抽好的 _is_cycling 双字段守卫
    # 同一来源避免两处复制粘贴 _CYCLING_TYPES（_is_cycling 内部引用）
    from app.strava.import_scheduler import _is_cycling
    # v5 task-0.8：Redis 走 app.queue 单一源
    # 局部 import 理由：与本函数已有的 StravaClient 局部 import 风格一致
    # （client 必须局部 import 因 client.py 顶部反向依赖 service.ensure_valid_token
    # 形成循环；redis_conn 没循环但放局部便于测试 patch app.queue.redis_conn 拦截）
    from app.queue import redis_conn

    user = db.query(User).filter_by(id=user_id).first()
    if not user or user.strava_athlete_id is None:
        raise ValueError("未绑定 Strava")

    # 冷却时间检查：每个用户 5 分钟内只能同步一次，防止烧光 API 额度
    # Redis SET NX + EX 原子操作：键不存在时设置成功（首次同步），键存在时设置失败（冷却中）
    try:
        cooldown_key = f"strava:sync_cooldown:{user_id}"
        if not redis_conn.set(cooldown_key, "1", ex=300, nx=True):
            raise ValueError("同步太频繁，请 5 分钟后再试")
    except ValueError:
        raise  # 冷却时间错误正常抛出
    except Exception:
        # Redis 不可用时降级放行（限流不应阻断功能）
        logger.warning("Redis 不可用，同步冷却检查跳过")

    client = StravaClient(db, user)
    activities = client.get_athlete_activities(per_page=30)

    new_count = 0
    for act in activities:
        strava_id = act.get("id")
        if strava_id is None:
            continue

        # Sprint 7 Fix 6：手动同步守卫——非骑行活动一律跳过，不建 velo 骨架。
        # 和 import_scheduler.py:_run_tier1 守卫同源（Fix 3 抽的 _is_cycling helper）。
        # 用户场景：Tim 点"立即同步"按钮 → 拉到 Strava 最近 30 条 → 跑步/徒步直接跳过 →
        # 只有骑行进 velo 数据库。manual_sync 这条独立路径必须有自己的守卫，不能依赖
        # tier1（scheduler 路径），不然手动同步会重新污染列表。
        if not _is_cycling(act):
            logger.info("manual_sync 跳过非骑行活动 strava_id=%s type=%s",
                        strava_id, act.get("type"))
            continue

        created = _create_importing_activity(db, user, strava_id)
        if created:
            # 补充骨架字段（列表 API 返回了名称和距离）
            activity = db.query(Activity).filter_by(strava_activity_id=strava_id).first()
            if activity:
                activity.title = act.get("name")
                activity.distance = act.get("distance")
                start_date_str = act.get("start_date")
                if start_date_str:
                    try:
                        activity.started_at = datetime.fromisoformat(
                            start_date_str.replace("Z", "+00:00")
                        )
                    except (ValueError, AttributeError):
                        pass
                db.commit()
            new_count += 1

    # v4 I10：若该用户有 active StravaImport，同步累加 tier1_completed
    # 避免手动 sync 创建的骨架活动没计入进度 → 前端显示 "0/X" 直到调度器接手
    # 只在循环后做一次批量更新（而非循环内每条 +1），减少 DB round-trip
    if new_count > 0:
        from app.strava.models import StravaImport
        active_import = (
            db.query(StravaImport)
            .filter(
                StravaImport.user_id == user_id,
                StravaImport.status == "active",
            )
            .with_for_update()
            .first()
        )
        if active_import:
            active_import.tier1_completed = (active_import.tier1_completed or 0) + new_count
            # total_activities 可能还是 None（首次绑定后 tier1 尚未跑完）——不动它
            db.commit()
            logger.info(
                "手动 sync 联动更新 tier1_completed user_id=%d +%d 到 %d",
                user_id, new_count, active_import.tier1_completed,
            )

    logger.info("手动同步完成 user_id=%d new=%d", user_id, new_count)
    return {
        "new_activities": new_count,
        "message": f"发现 {new_count} 条新骑行，正在导入" if new_count > 0
                   else "没有新的骑行活动",
    }


def get_import_progress(db: Session, user_id: int) -> dict:
    """
    查询 Strava 导入进度。v4 重构——从"算百分比"改为"吐视图状态"。

    为什么叫 view_status 不叫 status：
        StravaImport.status（数据库值）只有三种：active / paused / completed。
        "卡死" 不是一个数据库状态——而是"active 但 updated_at 5 分钟没动"，
        属于视图层派生态。起两个不同的名字避免口径混乱。

    前端约定（spec §2.8）：
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
    # 前提：task-7.1 已迁移 updated_at 为 timezone=True（PostgreSQL 生产环境）。
    # 防御：SQLite 测试环境不保留 tz，读出的 updated_at 可能是 naive——
    # 此时当作 UTC 处理（数据库一律存 UTC，这是项目约定）。
    if imp.status == "active":
        updated_at = imp.updated_at
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        staleness = datetime.now(timezone.utc) - updated_at
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
