"""赛段坡度数据回填脚本——用 DEM 查表替换历史 GPS 海拔（v3 / 2026-05-14）。

为什么写这个：
原算法用 GPS 海拔，精度 ±10-15m，造成 11km 平路赛段被算成 26.1% 假坡度
（生产 segment id=24 "夜骑清徐" 实证）。GPS 噪声系统偏差无法通过平滑消除，
业界共识必须换数据源——从 SRTM 30m DEM 查表替换。

实测验证（DEM 公共 API）：
- 夜骑清徐起点 768m / 终点 766m → 11km 平路真实坡度 0.018% ✓
- 天龙山网红公路 起点 831m / 终点 1357m → 真实 max ~10-13% ✓

跑法：
    # 干跑（默认，只打印不写 DB）
    python3 -m scripts.recompute_segment_stats

    # 真跑（写 DB）
    python3 -m scripts.recompute_segment_stats --apply

幂等：每次重算覆盖，纯函数 + DEM 查表，重跑无副作用。
风险：difficulty 评级会大幅跳变（多数 extreme 变 medium/easy），前端用户能看到。
这是预期效果——以前 GPS 假数据虚胖，现在 DEM 真实。

回填的字段：
- elevation_profile：用 reference_line 沿线等距采样 80 点 → DEM 查表 → 覆盖
- elevation_gain / loss / avg_gradient：基于 DEM 重算累计上升 / 下降 / 平均坡度
- max_gradient：基于 DEM 海拔走 100m 滑窗
- difficulty：用新 max_gradient + elevation_gain 重判

数据源：
- 等距采样 lat/lon：PostGIS ST_LineInterpolatePoint
- DEM 海拔：opentopodata 公共 API（SRTM 30m）
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from types import SimpleNamespace

from sqlalchemy import text

from app.database import SessionLocal
from app.segment._geo_utils import _haversine
from app.segment.algorithms import calculate_difficulty, calculate_max_gradient
from app.segment.dem_client import DEMServiceError, query_elevations
from app.segment.models import Segment


logger = logging.getLogger(__name__)

# 沿赛段参考线等距采样点数。
# 算 max_gradient 用 400 点密采样（10km 赛段 = 25m 间距，100m 滑窗跨 4 点 / 平滑窗口跨 375m 重叠率 71% / 能压住 DEM 山区噪声 ±20m）
# 存 elevation_profile 仍用 80 点（前端画曲线够 / 每 5 取 1）
DENSE_SAMPLE_COUNT = 400
PROFILE_SAMPLE_COUNT = 80
PROFILE_STRIDE = DENSE_SAMPLE_COUNT // PROFILE_SAMPLE_COUNT  # = 5


def sample_reference_line_coords(
    db, segment_id: int, n: int = DENSE_SAMPLE_COUNT,
) -> list[tuple[float, float]]:
    """用 PostGIS ST_LineInterpolatePoint 沿赛段参考线等距采样 n 个点。

    类比：拿一根有刻度的卷尺贴着赛段折线铺开，每 1/(n-1) 处采一个坐标。
    返回 [(lat, lon), ...] 顺序按沿线方向。

    n 默认 400 点用于算 max_gradient。前端 elevation_profile 用 80 点从中等步距取。
    """
    rows = db.execute(
        text("""
            SELECT
                ST_Y(ST_LineInterpolatePoint(reference_line, frac)) AS lat,
                ST_X(ST_LineInterpolatePoint(reference_line, frac)) AS lon
            FROM (
                SELECT generate_series(0, :n - 1)::float / :denom AS frac
            ) AS fractions,
            segments
            WHERE segments.id = :seg_id
            ORDER BY frac
        """),
        {"n": n, "denom": float(n - 1), "seg_id": segment_id},
    ).fetchall()
    return [(float(r.lat), float(r.lon)) for r in rows]


def recompute_one_segment(db, seg: Segment, skip_dem: bool = False) -> dict | None:
    """重算单条赛段所有坡度相关字段，返回新值字典（不写 DB）。

    返 None 表示 DEM 查询失败或采样不到点 / 跳过这条 segment。
    skip_dem=True 时跳过真 HTTP 调用（干跑模式 / 节省 rate limit）。
    """
    coords = sample_reference_line_coords(db, seg.id)
    if len(coords) < 2:
        logger.warning("segment id=%s 沿线采样不到点", seg.id)
        return None

    if skip_dem:
        # 干跑模式：跳过 DEM HTTP 调用（spec 审 I3 + codex 重叠）。
        # 用占位值返回，让 caller 知道"would query N 点"但不真消费 rate limit。
        return {"_dry_run_would_query": len(coords)}

    try:
        dem_elevations = query_elevations(coords)
    except DEMServiceError as exc:
        logger.warning("segment id=%s DEM 查询失败：%s", seg.id, exc)
        return None

    # 用 DEM 海拔 + 实际坐标距离重算所有字段
    total_dist = 0.0
    elevation_gain = 0.0
    elevation_loss = 0.0
    for i in range(1, len(coords)):
        total_dist += _haversine(
            coords[i - 1][0], coords[i - 1][1],
            coords[i][0], coords[i][1],
        )
        prev_ele = dem_elevations[i - 1]
        curr_ele = dem_elevations[i]
        if prev_ele is not None and curr_ele is not None:
            diff = curr_ele - prev_ele
            if diff > 0:
                elevation_gain += diff
            else:
                elevation_loss += abs(diff)

    # avg_gradient 用 seg.distance（reference_line 真实长度）算，不用 total_dist。
    # total_dist 是 400 点直线累计 < reference_line 折线真长度，两者用不同距离会让
    # 用户拿 DB 显示的 gain/loss/dist 自己算 avg 算不回 DB 的 avg（不自洽 bug / Tim 2026-05-15 抓）
    avg_gradient = (
        round((elevation_gain - elevation_loss) / seg.distance * 100, 1)
        if seg.distance and seg.distance > 0
        else 0.0
    )

    # max_gradient：构造轻量对象给 calculate_max_gradient（同 from-activity 路径做法）
    # window_m=500：DEM 数据（30m 像素 ±20m 噪声）用 100m 窗口会被单像素跳变放大成假陡坡。
    # 500m 跨 ~17 个 30m 像素，噪声稀释。Strava 业界公开做法（rolling 500m）。
    points = [
        SimpleNamespace(latitude=coords[i][0], longitude=coords[i][1], elevation=dem_elevations[i])
        for i in range(len(coords))
    ]
    new_max_grad = calculate_max_gradient(points, window_m=500.0)

    new_difficulty = calculate_difficulty(seg.distance, elevation_gain, new_max_grad)

    # elevation_profile：从 400 点密采样里每 5 个取 1 个 → 80 点存 DB（前端画曲线够用）
    # None 位置用上一个有效值兜底，长度严格 80（前端按等距假设画图）
    sparse_elevations = dem_elevations[::PROFILE_STRIDE][:PROFILE_SAMPLE_COUNT]
    filled_profile: list[float] = []
    last_valid: float | None = None
    for ele in sparse_elevations:
        if ele is not None:
            filled_profile.append(round(ele, 1))
            last_valid = ele
        elif last_valid is not None:
            filled_profile.append(round(last_valid, 1))
        else:
            filled_profile.append(0.0)

    return {
        "elevation_profile": filled_profile,
        "elevation_gain": round(elevation_gain, 1),
        "elevation_loss": round(elevation_loss, 1),
        "avg_gradient": avg_gradient,
        "max_gradient": new_max_grad,
        "difficulty": new_difficulty,
    }


def recompute_all(db, apply_changes: bool) -> dict:
    """遍历所有赛段，干跑模式只统计 + 不发 DEM HTTP，真跑模式调 DEM + 写 DB。"""
    segments = db.query(Segment).all()
    stats = {
        "total": len(segments),
        "updated": 0,
        "would_update": 0,
        "would_query_points": 0,
        "unchanged": 0,
        "failed": 0,
    }

    logger.info("扫描 %d 条赛段（apply=%s / DEM 调用=%s）", len(segments), apply_changes, apply_changes)
    if apply_changes:
        logger.info(
            "%-4s %-30s %10s %10s %10s %10s",
            "id", "name", "old_grad", "new_grad", "old_diff", "new_diff",
        )

    for seg in segments:
        try:
            new_values = recompute_one_segment(db, seg, skip_dem=not apply_changes)
            if new_values is None:
                stats["failed"] += 1
                continue

            # 干跑模式：跳过真 DEM / 只统计需要查多少点
            if "_dry_run_would_query" in new_values:
                stats["would_update"] += 1
                stats["would_query_points"] += new_values["_dry_run_would_query"]
                continue

            old_grad = seg.max_gradient
            old_diff = seg.difficulty
            old_avg = seg.avg_gradient
            new_grad = new_values["max_gradient"]
            new_diff = new_values["difficulty"]
            new_avg = new_values["avg_gradient"]

            changed = (
                old_grad is None
                or abs(new_grad - (old_grad or 0)) > 0.1
                or new_diff != old_diff
                or old_avg is None
                or abs(new_avg - (old_avg or 0)) > 0.05
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
                    # SAVEPOINT 隔离：flush 把 ORM 改动推到嵌套点（防一条失败带翻整批）
                    with db.begin_nested():
                        seg.elevation_profile = json.dumps(new_values["elevation_profile"])
                        seg.elevation_gain = new_values["elevation_gain"]
                        seg.elevation_loss = new_values["elevation_loss"]
                        seg.avg_gradient = new_values["avg_gradient"]
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
        logger.info("干跑完成（未写 DB / 未发 DEM HTTP）：%s", stats)
        if stats["would_update"] > 0:
            logger.info(
                "预计回填 %d 条赛段（消耗 %d 个 DEM 查询点），加 --apply 真跑：python3 -m scripts.recompute_segment_stats --apply",
                stats["would_update"], stats["would_query_points"],
            )

    return stats


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="用 DEM 海拔重算所有赛段的坡度数据（v3 算法）。"
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
