"""
worker 软目标监控 + 飞书告警（v5 task-1.C.1 / spec §3.8）。

干啥用：
- 扫 activities 表里 status='processing' 状态超过 4 分钟（软告警阈值）的记录
- 推飞书机器人告警让我们三人手机能收到
- 沿用 v4 _PROCESSING_TIMEOUT = 10 min 硬上限不改（worker 自愈仍走原机制）

操作注意（关键设计）：
- **只读不写**：scan 不改 activities.status / 不改 _PROCESSING_TIMEOUT
- **告警不阻断**：飞书 webhook 5xx / 网络异常 → catch 后 logger.error，仍返 stuck_id 列表
- **未配 webhook 兜底**：dev / CI 没配 FEISHU_BOT_WEBHOOK → 跳过推送但仍返 stuck list
  （task 卡 §测试 第 5 条要求 / 避免空 URL 反复抛 exception 刷日志）
- **告警风暴**：v5 简化版接受同一 activity 每 60s 重发；v6 可加去重缓存

数据流：
- 入：SQLAlchemy Session
- 中：查 status='processing' AND updated_at < now-4min → 渲染告警文本 → httpx.post
- 出：list[int] 触发告警的 activity_id（空表示无 stuck）

部署：docker-compose monitor 容器 `while true; sleep 60; python -m app.monitor.processing_health`
"""

import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy.orm import Session

from app.activity.models import Activity
from app.config import settings


logger = logging.getLogger(__name__)


# 软告警阈值：4 分钟（PRD 5.7.1 拍 / v4 硬上限 10min 的 80%）
# 类比家里水管 —— 水流变慢预警发短信，真堵死才停水修
WARN_THRESHOLD_SEC = 4 * 60


def scan_processing_health(db: Session) -> list[int]:
    """
    扫 processing 状态卡住超 4 分钟的 activities + 推飞书告警。

    设计思路：
    - 软告警不阻断 / 不修复 —— 让我们手动去查为啥卡（可能 worker 死了 / DeepSeek 限流 / 等）
    - 硬上限 10min 由 v4 worker 现有机制自愈（标 failed），不在本函数管
    - 类比汽车仪表盘 —— 黄灯先亮提醒，红灯才停车

    参数：
        db: SQLAlchemy Session

    返回：
        list[int] 触发告警的 activity_id 列表（空 = 一切正常）

    异常路径（全部内部消化）：
        - 飞书 webhook 抛异常 → logger.error + 仍返 stuck_id 列表（让 cron 退码反映状态）
        - FEISHU_BOT_WEBHOOK 未配 → logger.warning + 跳过推送但仍返 list
    """
    # 第 1 步：找 stuck 的 activities
    # tz-aware UTC（陷阱 #2：Activity.updated_at DB 列已 tz-aware，本端也用 aware 防 TypeError）
    now = datetime.now(timezone.utc)
    warn_cutoff = now - timedelta(seconds=WARN_THRESHOLD_SEC)

    stuck_activities = (
        db.query(Activity)
        .filter(
            Activity.status == "processing",
            Activity.updated_at < warn_cutoff,
        )
        .all()
    )

    # 第 2 步：无 stuck 直接返空，省一次 webhook 调用
    if not stuck_activities:
        return []

    # 第 3 步：渲染告警文本
    # 包含 elapsed 秒数让接告警的人能直观看出"卡了多久"
    msg = (
        f"⚠️ velo worker 处理告警\n"
        f"以下 activities 处理超过 {WARN_THRESHOLD_SEC // 60} 分钟未完成：\n"
        + "\n".join(
            f"  - id={a.id} user_id={a.user_id} "
            f"elapsed={(now - a.updated_at).total_seconds():.0f}s"
            for a in stuck_activities
        )
    )

    stuck_ids = [a.id for a in stuck_activities]

    # 第 4 步：推飞书（无 webhook 则跳过 / 异常 catch 不抛）
    # 跳过分支：dev / CI 没配 webhook 时直接返 list 不走 httpx
    # （避免空 URL 反复抛 InvalidURL exception 刷 error 日志噪音）
    if not settings.FEISHU_BOT_WEBHOOK:
        logger.warning(
            f"FEISHU_BOT_WEBHOOK 未配置，发现 {len(stuck_ids)} 条卡住的 activity 但跳过推送"
        )
        return stuck_ids

    try:
        # codex 异源审 2026-04-30 抓 Important：httpx.post 默认遇 5xx 不抛
        # spec §3.8 字面只 try httpx.post 是隐性盲区——飞书 502 直接静默成功
        # 必须 raise_for_status() 显式让 4xx/5xx 抛 HTTPStatusError，再 catch 记 error
        response = httpx.post(
            settings.FEISHU_BOT_WEBHOOK,
            json={"msg_type": "text", "content": {"text": msg}},
            timeout=5,
        )
        response.raise_for_status()
    except Exception as exc:
        # 飞书挂了不阻断 —— 业务正常跑，告警这条路断就断
        # catch 范围含：网络异常 / 超时 / HTTPStatusError(4xx/5xx) / SDK 升级新异常
        # HTTPStatusError 文本会包含带签名的 webhook URL，只记异常类型和状态码。
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        logger.error(
            "feishu webhook failed error_type=%s status_code=%s",
            type(exc).__name__,
            status_code,
        )

    return stuck_ids


def main() -> int:
    """
    命令行入口（docker-compose monitor 容器 `while true; sleep 60` 调用）。

    返回退码：0 = 一切正常 / 1 = 有 stuck activity（cron 监控可用退码识别）
    """
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        stuck = scan_processing_health(db)
        return 0 if not stuck else 1
    finally:
        db.close()


if __name__ == "__main__":
    import sys
    sys.exit(main())
