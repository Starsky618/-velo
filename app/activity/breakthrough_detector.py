"""Sprint 9 task-8：FTP Breakthrough 自动检测器。

这个文件干什么？
----------------
用户每次上传 / 同步一条新活动，worker 解析完成后调用本模块：
跑一遍 eFTP 估算（CP 3-param 模型），如果估算结果明显高于当前 ftp，
就写一条 BreakthroughEvent 行（status=pending），等用户下次进 settings 页弹窗确认。

类比：你健身房的私教看了你这一周的训练记录，跟你说"哥们儿，你的有氧水平涨了
10%，下次该把功率档调高一档"。本模块就是那个私教。

逻辑（按 brainstorm 共识 / 单层无预过滤）：
  1. 取 user.ftp（如为 None / 0 → 跳过：没基准 ftp 没法比突破）
  2. 调 estimate_ftp_for_user 算新 eFTP
  3. 如新 eFTP > user.ftp × 1.05 → 写 BreakthroughEvent (status=pending)
  4. 防抖：用户已有 pending → 老 pending 标 expired / 用最新覆盖

阈值 1.05 由来：
  - 太低（如 1.02）→ 误报多（estimator 自身误差就 ±2%）
  - 太高（如 1.10）→ 错过真突破
  - 1.05 = 经验值（Codex 异源审定）/ 后续可调

兜底：
  - estimate_ftp_for_user 抛异常 → try/except 兜底 / 返 None
  - 任何 DB 异常 → 调用方用 SAVEPOINT 隔离 / 不传染 activity.status='completed'

输入/输出数据流：
----------------
- 入参：db Session + user ORM + activity ORM
- 出参：BreakthroughEvent（如触发）/ 或 None（不触发 / 异常）
- 依赖：app.activity.ftp_estimator.estimate_ftp_for_user / BreakthroughEvent ORM
- 调用方：worker.py / worker_strava.py（GPX/FIT + Strava 三条路径同源接入）
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.activity.ftp_estimator import estimate_ftp_for_user
from app.activity.models import Activity, BreakthroughEvent
from app.user.models import User


logger = logging.getLogger(__name__)


# 阈值：新 eFTP > 当前 ftp × 此值 → 触发突破事件
# 1.05 = 5% 提升 / 高于 estimator 自身 ±2% 误差带 / 低于"假突破"风险（如热身没充分时低估）
BREAKTHROUGH_THRESHOLD = 1.05

# 过期时长：用户 7 天没处理 → 自动 expired / 不再弹窗
EXPIRES_DAYS = 7


def detect_breakthrough(
    db: Session, user: User, activity: Activity
) -> BreakthroughEvent | None:
    """检测当前活动是否触发 ftp breakthrough。

    入参：
        db: SQLAlchemy Session（由调用方管理事务）
        user: User ORM 对象（需用 user.ftp / user.id）
        activity: Activity ORM 对象（需用 activity.id 记录触发源头）

    返：
        BreakthroughEvent ORM（如触发，已加入 session 但未 commit）
        None（user.ftp 为空 / 阈值未到 / estimator 失败）

    设计要点：
    --------
    1. 不调 db.commit() —— 由 caller 用 SAVEPOINT 包住决定提交/回滚
       （与 _set_activity_city / detect_5min_power_progress 同 pattern）
    2. 防抖：写新 event 前把已有 pending 标 expired
       （Codex 异源审 / 防同一周连发 3 次弹窗骚扰）
    3. try/except 兜底：任何异常都返 None / 不抛出
       （worker 主流程依赖这点保证 activity.status='completed' 不被回退）
    """
    # 1. 没基准 ftp 没法比突破（用户从没填过 / estimator 还没建议过）
    #    truthiness 陷阱 #1：ftp=0 也算"没基准"（业务上不合理但防御性挡掉）
    if user.ftp is None or user.ftp <= 0:
        return None

    try:
        # 2. 跑 estimator 算新 eFTP
        result = estimate_ftp_for_user(db, user.id)
        if result.ftp is None:
            # 数据不足 / 拟合失败 → estimator 返 ftp=None / 不触发
            return None

        # 3. 阈值判断：必须 > ftp × 1.05 才算突破
        # FTP 估算接口给用户看的 suggested_ftp 会加 5W 产品偏移；突破检测要看 raw_ftp，
        # 否则一次普通浮动会被“开心 +5W”推过阈值，误弹突破。
        comparison_ftp = result.raw_ftp if result.raw_ftp is not None else result.ftp
        if comparison_ftp <= user.ftp * BREAKTHROUGH_THRESHOLD:
            return None

        # 4. 防抖：把该用户已有 pending 标 expired / 用最新覆盖
        #    bulk update：一条 SQL 改全部 pending → expired
        #    （即使有多条历史 pending 也一次清掉 / 不留尾巴）
        now = datetime.now(timezone.utc)
        db.query(BreakthroughEvent).filter(
            BreakthroughEvent.user_id == user.id,
            BreakthroughEvent.status == "pending",
        ).update({"status": "expired"}, synchronize_session=False)

        # 5. 写新 pending 事件
        event = BreakthroughEvent(
            user_id=user.id,
            activity_id=activity.id,
            old_ftp=user.ftp,
            suggested_ftp=result.ftp,
            status="pending",
            expires_at=now + timedelta(days=EXPIRES_DAYS),
        )
        db.add(event)
        db.flush()  # 让 event.id 立即可见（给 caller 日志用）
        logger.info(
            "breakthrough detected user_id=%s activity_id=%s old_ftp=%s suggested=%s",
            user.id, activity.id, user.ftp, result.ftp,
        )
        return event

    except Exception:
        # 任何异常都不传染：estimator scipy 失败 / DB 抖动 / 其他
        # logger.exception 打 traceback（feedback_logger_warning_error_narrative_trap 教训）
        logger.exception(
            "detect_breakthrough failed user_id=%s activity_id=%s",
            user.id, activity.id,
        )
        return None
