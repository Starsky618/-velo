"""Sprint 10 task-1：验证 daily_training_load 这张训练负荷日账本的表合同。"""

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import Date, Float, Integer, String, inspect
from sqlalchemy.exc import IntegrityError

from app.training.models import DailyTrainingLoad
from app.user.models import User


def test_daily_training_load_columns_match_contract():
    """字段合同测试：后续回填、接口、worker 都靠这些列名对接。"""
    columns = DailyTrainingLoad.__table__.c

    assert set(columns.keys()) == {
        "id",
        "user_id",
        "date",
        "ctl",
        "atl",
        "tsb",
        "tss_today",
        "weekly_tss",
        "status_band",
        "updated_at",
    }

    assert isinstance(columns.id.type, Integer)
    assert columns.id.primary_key is True

    assert isinstance(columns.user_id.type, Integer)
    assert columns.user_id.nullable is False

    assert isinstance(columns.date.type, Date)
    assert columns.date.nullable is False

    for metric_name in ("ctl", "atl", "tsb", "tss_today"):
        metric_col = columns[metric_name]
        assert isinstance(metric_col.type, Float)
        assert metric_col.nullable is False

    assert isinstance(columns.weekly_tss.type, Integer)
    assert columns.weekly_tss.nullable is False

    assert isinstance(columns.status_band.type, String)
    assert columns.status_band.type.length == 20
    assert columns.status_band.nullable is False

    assert columns.updated_at.nullable is False


def test_daily_training_load_crud_roundtrip(db):
    """CRUD 测试：像试着写一页账本再翻回来，证明 ORM 能正常读写。"""
    user = User(openid="dtl_crud_user", nickname="daily load")
    db.add(user)
    db.flush()

    row = DailyTrainingLoad(
        user_id=user.id,
        date=date(2026, 5, 25),
        ctl=65.3,
        atl=78.1,
        tsb=-12.8,
        tss_today=95.5,
        weekly_tss=450,
        status_band="tired",
        updated_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.commit()

    loaded = (
        db.query(DailyTrainingLoad)
        .filter_by(user_id=user.id, date=date(2026, 5, 25))
        .first()
    )

    assert loaded is not None
    assert loaded.ctl == pytest.approx(65.3)
    assert loaded.atl == pytest.approx(78.1)
    assert loaded.tsb == pytest.approx(-12.8)
    assert loaded.tss_today == pytest.approx(95.5)
    assert loaded.weekly_tss == 450
    assert loaded.status_band == "tired"


def test_daily_training_load_unique_user_date_rejected(db):
    """唯一约束测试：同一个用户同一天只能有一页训练负荷账本。"""
    user = User(openid="dtl_unique_user", nickname="daily load")
    db.add(user)
    db.flush()

    first = DailyTrainingLoad(
        user_id=user.id,
        date=date(2026, 5, 25),
        ctl=10.0,
        atl=20.0,
        tsb=-10.0,
        tss_today=80.0,
        weekly_tss=80,
        status_band="ok",
        updated_at=datetime.now(timezone.utc),
    )
    duplicate = DailyTrainingLoad(
        user_id=user.id,
        date=date(2026, 5, 25),
        ctl=11.0,
        atl=21.0,
        tsb=-10.0,
        tss_today=90.0,
        weekly_tss=90,
        status_band="ok",
        updated_at=datetime.now(timezone.utc),
    )

    db.add_all([first, duplicate])
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_daily_training_load_index_exists(db):
    """索引测试：训练日历页按 user_id + date 查 365 天时，要走这条路。"""
    indexes = inspect(db.bind).get_indexes("daily_training_load")
    index_names = {item["name"] for item in indexes}

    assert "idx_dtl_user_date" in index_names


def test_daily_training_load_status_band_check_declared():
    """状态枚举测试：防止 fresh/ok/tired/overreached 四档在 DB 层漂移。"""
    constraints = DailyTrainingLoad.__table__.constraints
    check_names = {constraint.name for constraint in constraints}

    assert "ck_daily_training_load_status_band" in check_names


def test_daily_training_load_invalid_status_band_rejected(db):
    """DB 实测：非法状态不能写入，避免未来前后端脑补第五档。"""
    user = User(openid="dtl_invalid_status_user", nickname="daily load")
    db.add(user)
    db.flush()

    row = DailyTrainingLoad(
        user_id=user.id,
        date=date(2026, 5, 25),
        ctl=10.0,
        atl=20.0,
        tsb=-10.0,
        tss_today=80.0,
        weekly_tss=80,
        status_band="sleepy",
        updated_at=datetime.now(timezone.utc),
    )
    db.add(row)

    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
