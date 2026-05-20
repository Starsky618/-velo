"""Sprint 9 task-4 单元测试：首次填 ftp 触发回填该用户所有 snapshot_ftp=NULL 活动。

测试范围：
- 首次填 ftp / snapshot_ftp IS NULL 活动 → snapshot_ftp 写入新 ftp
- 活动有 NP + duration → 同时算 IF / TSS（共享 calculate_intensity_metrics）
- 已有 snapshot_ftp 的活动 跳过（幂等语义 / 不覆盖历史 snapshot）

power_zones 回算路径（依赖 trackpoints 表）走真 PG 集成测试覆盖 / 这里
预填 power_zones 非 NULL 让纯函数 calculate_power_zones 重算分支被跳过——
SQLite conftest 没建 trackpoints 表，本测试只验证 service 主路径。
"""
import json
from datetime import datetime, timezone

from sqlalchemy import select

from app.activity.backfill_ftp import backfill_user_snapshot_ftp
from app.activity.models import Activity
from tests.conftest import _activities_table


def _insert_activity(
    db,
    user_id: int,
    *,
    snapshot_ftp: int | None = None,
    normalized_power: float | None = None,
    duration: int | None = 3600,
    status: str = "completed",
    activity_type: str = "cycling",
    power_zones: str | None = "[]",  # 非 NULL 让 backfill 跳过 trackpoint 查询分支
) -> int:
    """fixture helper：插一条 activity 返回 id。"""
    result = db.execute(
        _activities_table.insert().values(
            user_id=user_id,
            status=status,
            activity_type=activity_type,
            distance=10000.0,
            duration=duration,
            normalized_power=normalized_power,
            snapshot_ftp=snapshot_ftp,
            power_zones=power_zones,
            started_at=datetime(2026, 5, 1, 10, 0, 0, tzinfo=timezone.utc),
        )
    )
    db.commit()
    return result.inserted_primary_key[0]


class TestBackfillFtp:
    def test_first_time_fill_writes_snapshot_ftp(self, db, test_user):
        """首次填 ftp / 该用户所有 snapshot_ftp NULL 活动 → snapshot_ftp 写入新 ftp 值"""
        # 旧活动 snapshot_ftp 是 NULL（用户当时没填 ftp）
        activity_id = _insert_activity(db, test_user.id, snapshot_ftp=None)

        stats = backfill_user_snapshot_ftp(db, user_id=test_user.id, new_ftp=220)

        # ORM 查回填后的状态
        activity = db.query(Activity).filter_by(id=activity_id).first()
        assert activity.snapshot_ftp == 220
        assert stats["total"] == 1

    def test_first_time_fill_calculates_if_tss(self, db, test_user):
        """活动有 NP → 回填同时算 IF/TSS（共享 calculate_intensity_metrics）"""
        # NP=200 / FTP=220 / 1h → IF≈0.909 / TSS≈82.6（与 test_intensity_metrics 同基准）
        activity_id = _insert_activity(
            db, test_user.id,
            snapshot_ftp=None,
            normalized_power=200.0,
            duration=3600,
        )

        stats = backfill_user_snapshot_ftp(db, user_id=test_user.id, new_ftp=220)

        activity = db.query(Activity).filter_by(id=activity_id).first()
        assert activity.snapshot_ftp == 220
        assert activity.intensity_factor == 0.909
        assert activity.tss == 82.6
        assert stats["if_tss_filled"] == 1

    def test_already_has_snapshot_ftp_not_touched(self, db, test_user):
        """已有 snapshot_ftp 的活动 不被回填覆盖（跳过式幂等）"""
        # 历史活动当时 snapshot 锁了 ftp=200
        activity_id = _insert_activity(db, test_user.id, snapshot_ftp=200)

        # 用户改 ftp 到 240 / backfill 应跳过这条
        stats = backfill_user_snapshot_ftp(db, user_id=test_user.id, new_ftp=240)

        activity = db.query(Activity).filter_by(id=activity_id).first()
        assert activity.snapshot_ftp == 200  # 原值不动
        assert stats["total"] == 0  # 没有 NULL 活动可回填
