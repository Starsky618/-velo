"""赛段坡度数据回填脚本——用统一 GLO-30 成品链替换历史海拔。

为什么写这个：
原算法用 GPS 海拔，精度 ±10-15m，造成 11km 平路赛段被算成 26.1% 假坡度
（生产 segment id=24 "夜骑清徐" 实证）。GPS 噪声系统偏差无法通过平滑消除，
当前从统一入口读取 Copernicus GLO-30，并复用路书的固定物理网格和有效爬升算法。

实测验证（DEM 地形源）：
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
- 规划海拔：app.elevation.dem_client（Copernicus GLO-30 COG，本地持久缓存）
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from types import SimpleNamespace

from sqlalchemy import inspect, text

from app.database import SessionLocal
from app.elevation.route_elevation import build_route_elevation_result
from app.meetup.models import Meetup
from app.segment.algorithms import calculate_difficulty, calculate_max_gradient
from app.segment.dem_client import DEMServiceError, query_elevations
from app.segment.models import Segment


logger = logging.getLogger(__name__)

# 沿赛段参考线等距采样点数。
# 400 个坐标只负责把 PostGIS 参考线还原成足够细的折线；真正的海拔查询仍会在
# route_elevation 中按约 20m 的固定物理网格重采样。存储曲线压到 80 点供前端绘图。
DENSE_SAMPLE_COUNT = 400
PROFILE_SAMPLE_COUNT = 80


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
        elevation_result = build_route_elevation_result(
            [[lon, lat] for lat, lon in coords],
            query_func=query_elevations,
        )
    except (DEMServiceError, ValueError) as exc:
        logger.warning("segment id=%s DEM 查询失败：%s", seg.id, exc)
        return None

    shaped_elevations = [point[2] for point in elevation_result.snapshot]
    elevation_gain = elevation_result.climb
    elevation_loss = elevation_result.descent

    # 平均坡度按成品剖面的起终点净高差计算；有效爬升/下降会过滤微起伏，不能
    # 再拿二者相减冒充净高差。
    avg_gradient = (
        round((shaped_elevations[-1] - shaped_elevations[0]) / seg.distance * 100, 1)
        if seg.distance and seg.distance > 0
        else 0.0
    )

    # max_gradient 保留赛段原有 500m 窗口，但输入改为统一成品剖面。
    points = [
        SimpleNamespace(latitude=coords[i][0], longitude=coords[i][1], elevation=shaped_elevations[i])
        for i in range(len(coords))
    ]
    new_max_grad = calculate_max_gradient(points, window_m=500.0)

    new_difficulty = calculate_difficulty(seg.distance, elevation_gain, new_max_grad)

    profile_values = [point[1] for point in elevation_result.profile]
    if len(profile_values) <= PROFILE_SAMPLE_COUNT:
        filled_profile = [round(value, 1) for value in profile_values]
    else:
        indexes = [
            round(index * (len(profile_values) - 1) / (PROFILE_SAMPLE_COUNT - 1))
            for index in range(PROFILE_SAMPLE_COUNT)
        ]
        filled_profile = [round(profile_values[index], 1) for index in indexes]

    return {
        "elevation_profile": filled_profile,
        "elevation_gain": round(elevation_gain, 1),
        "elevation_loss": round(elevation_loss, 1),
        "avg_gradient": avg_gradient,
        "max_gradient": new_max_grad,
        "difficulty": new_difficulty,
    }


def _refresh_linked_segment_meetup_snapshots(
    db,
    segment_id: int,
    climb: float | None,
) -> int:
    """同步所有仍可被产品 API 读取的约骑，彻底移除旧海拔结果。"""
    if not inspect(db.connection()).has_table("meetups"):
        return 0

    return (
        db.query(Meetup)
        .filter(Meetup.segment_id == segment_id)
        .update({Meetup.snapshot_climb: climb}, synchronize_session=False)
    )


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

            try:
                old_profile = json.loads(seg.elevation_profile) if seg.elevation_profile else None
            except (TypeError, json.JSONDecodeError):
                old_profile = None
            changed = (
                old_grad is None
                or abs(new_grad - (old_grad or 0)) > 0.1
                or new_diff != old_diff
                or old_avg is None
                or abs(new_avg - (old_avg or 0)) > 0.05
                or seg.elevation_gain is None
                or abs(new_values["elevation_gain"] - (seg.elevation_gain or 0)) > 0.05
                or seg.elevation_loss is None
                or abs(new_values["elevation_loss"] - (seg.elevation_loss or 0)) > 0.05
                or old_profile != new_values["elevation_profile"]
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

            if apply_changes:
                # 即使赛段值已经一致，也要修复仍持有旧爬升的约骑快照。
                # SAVEPOINT 把赛段与引用它的约骑作为同一个原子更新单元。
                with db.begin_nested():
                    if changed:
                        seg.elevation_profile = json.dumps(new_values["elevation_profile"])
                        seg.elevation_gain = new_values["elevation_gain"]
                        seg.elevation_loss = new_values["elevation_loss"]
                        seg.avg_gradient = new_values["avg_gradient"]
                        seg.max_gradient = new_grad
                        seg.difficulty = new_diff
                    _refresh_linked_segment_meetup_snapshots(
                        db,
                        seg.id,
                        new_values["elevation_gain"],
                    )
                    db.flush()
                if changed:
                    stats["updated"] += 1
                else:
                    stats["unchanged"] += 1
            else:
                if changed:
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
