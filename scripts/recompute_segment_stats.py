"""赛段坡度数据回填脚本——重算 max_gradient + difficulty（v2 算法，2026-05-14）。

为什么写这个：
v1 算法 `calculate_max_gradient` 用 trackpoints 原始海拔算 100m 滑窗最陡，
对 GPS 海拔噪声（±15m）没有压制，导致 11km 平路赛段被误算成 26.1%
（生产 segment id=24 "夜骑清徐" 实证）。

v2 算法加了海拔中位数预平滑 + 25% cap，详 app/segment/algorithms.py:59。
本脚本对所有现有赛段重算 max_gradient，连带刷新 difficulty 评级。

跑法：
    # 干跑（默认，只打印不写 DB）
    python3 -m scripts.recompute_segment_stats

    # 真跑（写 DB）
    python3 -m scripts.recompute_segment_stats --apply

幂等：每次重算覆盖，纯函数输出，重跑无副作用。
风险：difficulty 评级可能跳变（如 extreme → medium），前端用户能看到。
这是预期效果——以前虚胖、现在真实。

不动的字段：
- elevation_profile：生产 24 条全有数据，from-gpx 路径创建时已算好
- elevation_gain / elevation_loss / avg_gradient：用 trackpoint 噪声数据重算
  反而引入新偏差（这些是积分式累加，对噪声不敏感），保持原值更稳

数据源（跟 scripts/backfill_phase5.py 同款）：
赛段 reference_line 50m 半径内所有 trackpoints —— 多用户多次骑行的聚合，
点密度高（5-10m/点），新 v2 算法在这种数据上能压住噪声。
"""

from __future__ import annotations

import argparse
import logging
import sys

from geoalchemy2 import Geography
from sqlalchemy import cast, func, select

from app.activity.models import Trackpoint
from app.database import SessionLocal
from app.segment.algorithms import calculate_difficulty, calculate_max_gradient
from app.segment.models import Segment


logger = logging.getLogger(__name__)


def recompute_one_segment(db, seg: Segment) -> tuple[float | None, str | None]:
    """重算单条赛段的 max_gradient / difficulty，返回新值（不写 DB）。

    无 trackpoint 时返 (None, 原 difficulty)，调用方决定要不要写。
    """
    # 用 scalar_subquery 让 reference_line 走 SQL 列引用（不走 Python EWKB hex 字符串路径）
    # 详见 backfill_phase5.py:51 注释——这是踩坑实证后的正解
    ref_line_subq = (
        select(Segment.reference_line)
        .where(Segment.id == seg.id)
        .scalar_subquery()
    )
    tps = (
        db.query(Trackpoint)
        .filter(
            Trackpoint.geom.isnot(None),
            func.ST_DWithin(
                cast(Trackpoint.geom, Geography),
                cast(ref_line_subq, Geography),
                50,
            ),
        )
        .order_by(Trackpoint.activity_id, Trackpoint.seq)
        .all()
    )

    if not tps:
        return None, seg.difficulty

    new_max_grad = calculate_max_gradient(tps)
    new_difficulty = calculate_difficulty(
        seg.distance,
        seg.elevation_gain if seg.elevation_gain is not None else 0.0,
        new_max_grad,
    )
    return new_max_grad, new_difficulty


def recompute_all(db, apply_changes: bool) -> dict:
    """遍历所有赛段，干跑模式只打印，真跑模式写 DB。

    stats 字段说明（4 个互斥 bucket 加起来必须等于 total）：
    - updated：真跑模式下成功写入 DB 的赛段数
    - would_update：干跑模式下检测到需要更新的赛段数（真跑会变成 updated）
    - unchanged：检测到无需更新的赛段数（新旧值差异 < 0.1% 且 difficulty 不变）
    - no_tps：无 trackpoint 数据可用 / 跳过
    - failed：异常 / 跳过
    """
    segments = db.query(Segment).all()
    stats = {
        "total": len(segments),
        "updated": 0,
        "would_update": 0,
        "unchanged": 0,
        "no_tps": 0,
        "failed": 0,
    }

    logger.info("扫描 %d 条赛段（apply=%s）", len(segments), apply_changes)
    logger.info("%-4s %-30s %10s %10s %10s %10s", "id", "name", "old_grad", "new_grad", "old_diff", "new_diff")

    for seg in segments:
        try:
            new_grad, new_diff = recompute_one_segment(db, seg)
            old_grad = seg.max_gradient
            old_diff = seg.difficulty

            if new_grad is None:
                stats["no_tps"] += 1
                logger.info(
                    "%-4d %-30s %10s %10s %10s %10s [无 trackpoint 跳过]",
                    seg.id, (seg.name or "")[:30],
                    f"{old_grad:.1f}" if old_grad is not None else "-",
                    "-", old_diff or "-", "-",
                )
                continue

            changed = (
                old_grad is None
                or abs((new_grad or 0) - (old_grad or 0)) > 0.1
                or new_diff != old_diff
            )
            tag = " [变化]" if changed else ""
            logger.info(
                "%-4d %-30s %10s %10.1f %10s %10s%s",
                seg.id, (seg.name or "")[:30],
                f"{old_grad:.1f}" if old_grad is not None else "-",
                new_grad,
                old_diff or "-", new_diff or "-",
                tag,
            )

            if changed:
                if apply_changes:
                    # SAVEPOINT 隔离：必须 flush 把 ORM 改动推到嵌套点，
                    # 否则一条 seg 失败会让本次所有改动全回滚（详 backfill_phase5.py:50 同 pattern）
                    with db.begin_nested():
                        seg.max_gradient = new_grad
                        seg.difficulty = new_diff
                        db.flush()
                    stats["updated"] += 1
                else:
                    stats["would_update"] += 1
            else:
                stats["unchanged"] += 1

        except Exception:
            logger.exception("recompute segment id=%s failed", seg.id)
            stats["failed"] += 1

    if apply_changes:
        db.commit()
        logger.info("真跑完成：%s", stats)
    else:
        logger.info("干跑完成（未写 DB）：%s", stats)
        if stats["would_update"] > 0:
            logger.info(
                "有 %d 条需要更新，加 --apply 真跑：python3 -m scripts.recompute_segment_stats --apply",
                stats["would_update"],
            )

    return stats


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="重算所有赛段的 max_gradient + difficulty（v2 算法）。"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="真跑模式（写 DB）。不加 = 干跑模式（默认，只打印对比）",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    db = SessionLocal()
    try:
        stats = recompute_all(db, apply_changes=args.apply)
        return 0 if stats["failed"] == 0 else 1
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    sys.exit(main())
