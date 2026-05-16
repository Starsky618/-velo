"""Sprint 6 task-3：activities.city 字段历史回填脚本（一次性，幂等）。

干啥：
    sprint6_activity_city 迁移给 activities 表加了 city 字段，新解析的活动
    走 worker hook（worker.py / import_scheduler.py）会自动写 city。但**老活动**
    的 city 列都是 NULL —— "我的"页"城市征服墙"会漏算用户骑过的城市。
    本脚本：对所有 simplified_track IS NOT NULL 且 city IS NULL 的活动，
    从轨迹起点反推城市枚举（6 城 + unknown），写回 DB。

幂等语义：
    跳过式幂等 —— 只动 city IS NULL 的行。已写过的不动（防重跑覆盖人工修改）。

跑法：
    # 干跑：只列出待回填条数 / 不写
    python3 -m scripts.backfill_activity_city --dry-run

    # 真跑：写 DB
    python3 -m scripts.backfill_activity_city

NULL vs 'unknown' 语义（红线 / 与 worker hook _set_activity_city 对齐）：
    - simplified_track is None / 空 / 起点 lat lon 缺失 → **不写**（保持 NULL）
    - 6 城内 → 写 6 城之一
    - 中国但不在 6 城 → 写 'unknown'（infer_city_from_coords 自然返）
    一致原则：worker hook 不会写 'unknown' 给"无坐标"，回填也不能写
    （否则同样"无坐标"的两条活动一条 NULL 一条 unknown，业务层无法区分）。

限速保护：
    5 条 / 秒（time.sleep(0.2)），100 用户量级 ≈ 1000-5000 条 activity，
    总耗时 3-15 分钟。不打外部 API（infer_city_from_coords 是纯函数 / 仅 DB UPDATE），
    限速主要为防 DB 压力 + 给运维查看进度的呼吸空间。

进度：
    每条 commit + 打印 activity_id / city。失败一行 rollback 该行 / 不影响其他。
"""

from __future__ import annotations

import argparse
import time

from app.activity.models import Activity
from app.common.geo import infer_city_from_coords
from app.database import SessionLocal


def main(dry_run: bool) -> None:
    db = SessionLocal()
    try:
        # 只回填没写过 city 的活动（幂等保护 / 不覆盖已有值）。
        # 顺手过滤 status='completed'（task-3 三审 Important）：failed / processing 状态
        # 的 activity 不进 city-medals 聚合（service 层 status 守卫）/ 回填它们的 city 浪费
        # DB 写入 + 让"NULL = 从未推断"语义稍微变松。完成态才回填。
        activities = (
            db.query(Activity)
            .filter(
                Activity.status == "completed",
                Activity.simplified_track.isnot(None),
                Activity.city.is_(None),
            )
            .all()
        )

        print(f"找到 {len(activities)} 条待回填 activity")
        if dry_run:
            print("--dry-run 模式 / 不写 DB")
            return

        success = 0
        skipped = 0
        failed = 0
        for a in activities:
            try:
                track = a.simplified_track or []
                if not track:
                    # 空轨迹 → 保持 NULL（v0.4 / 与 worker hook 一致）
                    # NULL = 从未推断过 / unknown = 推断过但不在 6 城 / 不可混淆
                    skipped += 1
                    continue
                first = track[0]
                lat = first.get("lat")
                lon = first.get("lon")
                # truthiness 陷阱 #1：0.0 是合法纬度（赤道），用 `is None`
                if lat is None or lon is None:
                    # 坐标缺失 → 保持 NULL
                    skipped += 1
                    continue
                a.city = infer_city_from_coords(lat, lon)  # 6 城之一 或 'unknown'
                db.commit()
                success += 1
                print(f"activity_id={a.id} city={a.city}")
            except Exception as e:
                db.rollback()
                failed += 1
                print(f"activity_id={a.id} 失败：{e}")
            time.sleep(0.2)  # 5 条 / 秒 限速

        print(
            f"\n完成 / success={success} / skipped={skipped} (空 track 或坐标缺失) "
            f"/ failed={failed}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Sprint 6 task-3：回填 activities.city 历史数据。"
            "默认 dry-run（只统计 / 不写 DB）/ 加 --apply 才真写。"
        )
    )
    # 安全默认：裸跑 = dry-run / 加 --apply 才真写。
    # 不用 --dry-run flag（store_true 默认 False = 裸跑真写库 / Codex + 集成审抓的运维风险）。
    # task 卡红线第 6 条"默认 dry-run / 真跑传 flag"——本写法字面落实。
    parser.add_argument(
        "--apply",
        action="store_true",
        help="真写 DB（不传 --apply 默认 dry-run / 只列待回填条数）",
    )
    args = parser.parse_args()
    main(dry_run=not args.apply)
