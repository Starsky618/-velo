"""历史 activity 重复回扫清理（一次性 / 幂等 / dry-run + apply 两模式）。

干啥用：
- Sprint 5 task-2 dedupe 上线前的老 activity 没跑过算法 / 同骑行多份导出全裸奔在 DB
  （典型场景：早期 GPX 直传 + 后来接入 Strava OAuth 时 backfill = 同一骑行两份）
- 本脚本扫全库找疑似重复 pair / 按完整度评分 + data_source 偏好选主 / DELETE 副侧
- segment_efforts FK CASCADE → 自动跟删（防排行榜双倍计数）
- trackpoints / activity_privacy FK CASCADE → 自动跟删
- notifications / persona_outputs FK SET NULL → 老引用变 NULL（NPC / 通知文案保留 audit）
- activities.duplicate_of FK SET NULL → 我之前手工标的副本被删时自动"浮上来"

跑法：
    python -m scripts.historical_dedupe_cleanup                # dry-run 默认 / 只看不动
    python -m scripts.historical_dedupe_cleanup --apply        # 真删 / 不可逆
    python -m scripts.historical_dedupe_cleanup --user-id 2    # 单用户

选主规则（与实时 dedupe_service.py 修法 A "旧主新副" 不同 / 历史场景有不同考量）：
- compute_completeness_score 高的留主（公式 = 3 传感器 + trackpoint/1000 cap 5）
- tie 时按 data_source 偏好：strava (3) > gpx/fit (2) > NULL (1) > 其他 (0)
- 完全 tie 时 fallback 按 id 旧的留主（与 dedupe_service.py 默认对齐）

幂等：
- 跳过 status != 'completed' / 已标 duplicate_of / 非 cycling
- 跳过缺关键字段（started_at / distance / duration / simplified_track）
- 每个 pair 用 SAVEPOINT 隔离 / 单 pair 失败不阻断其他

风险：
- 这是 DELETE 生产数据的不可逆操作 / 必须 dry-run 确认后再 --apply
- 删的是活动主体 + 它的所有 effort/trackpoint/privacy / 老引用 notification/persona 变 NULL
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Optional

from sqlalchemy import text

# 显式 import 所有外键关联 ORM（memory feedback_standalone_script_orm_loading.md）：
# standalone 进程不走 FastAPI 启动 / 必须 import 所有外键关联表的 ORM
# 否则 SQLAlchemy 找不到关联表会报 "could not find table"
from app.activity.dedupe import (
    ActivityScoreData,
    ActivitySig,
    compute_completeness_score,
    is_potential_duplicate,
)
from app.activity.models import Activity, ActivityPrivacy, Trackpoint  # noqa: F401
from app.agent.persona.models import PersonaFeedback, PersonaOutput, PersonaTemplate  # noqa: F401
from app.database import SessionLocal
from app.notification.models import Notification  # noqa: F401
from app.segment.models import Segment, SegmentEffort  # noqa: F401
from app.user.models import User


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [historical_dedupe_cleanup] %(message)s",
)
logger = logging.getLogger(__name__)


# data_source 偏好（tiebreaker 用 / 数字越大越优先留主）
# Strava 最权威（有完整 athlete 上下文 + normalized 传感器算法）
# GPX/FIT 是用户主动上传的真实导出（保留）
# NULL 是早期版本数据缺 data_source 字段标记的活动 / 优先级最低
DATA_SOURCE_PRIORITY = {
    "strava": 3,
    "gpx": 2,
    "fit": 2,
    None: 1,
    "": 1,
}


# 2026-05-20 手工 SQL 标记的 4 对（旧主新副反方向 / 让脚本重判）：
# 当时按 dedupe_service.py 修法 A 默认 "旧主新副"，但历史回扫场景应该按 data_source
# 偏好（Strava > NULL/GPX），所以脚本启动时撤销这批旧标记让算法重新决策。
RECENT_MANUAL_MARKS_TO_REVERT = [151, 168, 160, 144]


def _build_sig(a: Activity) -> Optional[ActivitySig]:
    """从 ORM 构造 ActivitySig。缺关键字段（时间 / 距离 / 时长 / 起点）返 None 跳过。"""
    if a.started_at is None or a.distance is None or a.duration is None:
        return None
    track = a.simplified_track
    if not track or len(track) == 0:
        return None
    first = track[0]
    lat = first.get("lat")
    lon = first.get("lon")
    if lat is None or lon is None:
        return None
    return ActivitySig(
        started_at=a.started_at,
        distance=a.distance,
        duration=a.duration,
        start_lat=lat,
        start_lon=lon,
    )


def _build_score(a: Activity, tp_count: int) -> ActivityScoreData:
    """从 ORM 构造 completeness 评分输入。"""
    return ActivityScoreData(
        avg_power=a.avg_power,
        avg_hr=a.avg_hr,
        avg_cadence=a.avg_cadence,
        trackpoint_count=tp_count,
    )


def _pick_main(
    a: Activity, b: Activity, score_a: float, score_b: float
) -> tuple[Activity, Activity]:
    """决定 (主, 副)：score 高的留主 / tie 用 data_source 偏好 / 再 tie 按 id 旧的留主。

    类比：双胞胎选谁当户主——先看体检全面度（score），平分再看身份证含金量（data_source），
    还平再按出生顺序（id）—— 早的为主 / 跟 dedupe_service.py 默认对齐方便回滚审计。
    """
    if score_a > score_b:
        return a, b
    if score_b > score_a:
        return b, a
    # score tie - 用 data_source 偏好
    pri_a = DATA_SOURCE_PRIORITY.get(a.data_source, 0)
    pri_b = DATA_SOURCE_PRIORITY.get(b.data_source, 0)
    if pri_a > pri_b:
        return a, b
    if pri_b > pri_a:
        return b, a
    # 完全 tie - fallback 按 id 旧的留主
    if a.id < b.id:
        return a, b
    return b, a


def scan_user(db, user_id: int) -> list[tuple[Activity, Activity, dict]]:
    """扫单个用户找所有疑似重复 pair。

    限制：a 找到第一个副本就 break / 假设疑似重复 ≤ 2 份（实际历史数据全是 2 份）
    三胞胎场景下漏第三份 / 下次再跑会被独立 pair 抓 / 长期收敛。
    """
    activities = (
        db.query(Activity)
        .filter(
            Activity.user_id == user_id,
            Activity.status == "completed",
            Activity.activity_type == "cycling",
            Activity.duplicate_of.is_(None),
        )
        .order_by(Activity.started_at)
        .all()
    )

    pairs: list[tuple[Activity, Activity, dict]] = []
    used: set[int] = set()  # 已分配为副本的 id 不再参与下一轮

    for i, a in enumerate(activities):
        if a.id in used:
            continue
        sig_a = _build_sig(a)
        if sig_a is None:
            continue
        for b in activities[i + 1:]:
            if b.id in used:
                continue
            sig_b = _build_sig(b)
            if sig_b is None:
                continue
            if not is_potential_duplicate(sig_a, sig_b):
                continue
            # 找到候选 pair - 算 score 选主
            tp_a = db.query(Trackpoint).filter_by(activity_id=a.id).count()
            tp_b = db.query(Trackpoint).filter_by(activity_id=b.id).count()
            score_a = compute_completeness_score(_build_score(a, tp_a))
            score_b = compute_completeness_score(_build_score(b, tp_b))
            main, dup = _pick_main(a, b, score_a, score_b)
            score_main, score_dup = (score_a, score_b) if main is a else (score_b, score_a)
            # 数副侧关联 - 给汇报用
            effort_count = db.query(SegmentEffort).filter_by(activity_id=dup.id).count()
            tp_count = db.query(Trackpoint).filter_by(activity_id=dup.id).count()
            notif_count = db.query(Notification).filter_by(activity_id=dup.id).count()
            persona_count = db.query(PersonaOutput).filter_by(activity_id=dup.id).count()
            pairs.append((main, dup, {
                "score_main": score_main,
                "score_dup": score_dup,
                "effort_count": effort_count,
                "tp_count": tp_count,
                "notif_count": notif_count,
                "persona_count": persona_count,
            }))
            used.add(dup.id)
            # 如果 a 反向变成了副本 - 把 a 也 used + 跳出 / 否则 a 继续找别的副本
            if main is not a:
                used.add(a.id)
                break
            # main is a - a 可继续找别的副本（三胞胎场景）/ 但实际 break 简化
            break

    return pairs


def main() -> None:
    parser = argparse.ArgumentParser(description="历史 activity 重复回扫清理")
    parser.add_argument(
        "--apply", action="store_true",
        help="真删 + commit / 默认 dry-run 只看不动 DB",
    )
    parser.add_argument(
        "--user-id", type=int, default=None,
        help="只扫单个用户（默认全库扫 / 所有有活动的用户）",
    )
    parser.add_argument(
        "--no-revert-manual-marks", action="store_true",
        help="不撤销 2026-05-20 手工标的 4 对（默认会撤销让算法重判）",
    )
    args = parser.parse_args()

    mode = "APPLY 真删" if args.apply else "DRY-RUN 只看不动"
    logger.info(f"=== 历史 dedupe 清理 mode={mode} ===")

    db = SessionLocal()
    try:
        # 第 0 步：撤销 2026-05-20 手工 SQL 标的 4 条（旧主新副反方向）
        # 让脚本重判这 4 对 / 应用 data_source 偏好规则
        if not args.no_revert_manual_marks:
            result = db.execute(text(
                "UPDATE activities SET duplicate_of = NULL "
                "WHERE id = ANY(:ids) AND duplicate_of IS NOT NULL"
            ), {"ids": RECENT_MANUAL_MARKS_TO_REVERT})
            logger.info(
                f"第 0 步：撤销 2026-05-20 手工标记 / 影响 {result.rowcount} 条 "
                f"(dry-run 退出自动回滚 / apply 在最后 commit 持久化)"
            )

        # 第 1 步：确定要扫的用户范围
        if args.user_id:
            user_ids = [args.user_id]
        else:
            user_ids = [u.id for u in db.query(User).all()]
        logger.info(f"第 1 步：扫描 {len(user_ids)} 个用户")

        # 第 2 步：扫每个用户找 pair + 汇报决策
        total_pairs = 0
        total_effort = 0
        total_tp = 0
        total_notif = 0
        total_persona = 0

        for uid in user_ids:
            pairs = scan_user(db, uid)
            if not pairs:
                continue
            logger.info(f"\n--- user_id={uid} 找到 {len(pairs)} 对疑似重复 ---")
            for main, dup, info in pairs:
                started_str = main.started_at.strftime("%Y-%m-%d %H:%M") if main.started_at else "?"
                km_str = f"{main.distance/1000:.1f}km" if main.distance else "?"
                logger.info(
                    f"  PAIR: keep id={main.id} (score={info['score_main']:.2f} "
                    f"src={main.data_source or 'NULL'}) | "
                    f"DELETE id={dup.id} (score={info['score_dup']:.2f} "
                    f"src={dup.data_source or 'NULL'}) | "
                    f"{started_str} {km_str} | "
                    f"cascade: effort={info['effort_count']} tp={info['tp_count']} "
                    f"notif={info['notif_count']}(NULL) persona={info['persona_count']}(NULL)"
                )
                total_pairs += 1
                total_effort += info["effort_count"]
                total_tp += info["tp_count"]
                total_notif += info["notif_count"]
                total_persona += info["persona_count"]

                # 第 3 步（仅 apply）：真删副侧
                if args.apply:
                    try:
                        with db.begin_nested():
                            db.delete(dup)
                            db.flush()
                        logger.info(f"    APPLY: DELETED activity id={dup.id}")
                    except Exception as e:
                        logger.exception(f"    APPLY FAIL id={dup.id}: {e} / 跳过继续")
                        continue

        # 第 4 步：commit / dry-run 退出自动 rollback
        if args.apply:
            db.commit()
            logger.info("\n=== APPLY 完成 / DB 已持久化 ===")
        else:
            logger.info("\n=== DRY-RUN 不动 DB / Session 关闭自动 rollback ===")

        logger.info(
            f"汇总：{total_pairs} 对疑似重复 / "
            f"将删 effort={total_effort} tp={total_tp} / "
            f"将 SET NULL notif={total_notif} persona={total_persona}"
        )
    except Exception:
        db.rollback()
        logger.exception("脚本异常 / 整体回滚")
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
