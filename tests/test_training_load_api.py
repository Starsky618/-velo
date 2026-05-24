"""Sprint 10 task-4：训练负荷曲线 API 测试。"""

from datetime import timedelta

from app.training.models import DailyTrainingLoad
from scripts.backfill_daily_training_load import _today_bj


def _insert_daily_load(
    db,
    user_id: int,
    *,
    day_offset: int,
    ctl: float,
    atl: float,
    tss_today: float,
    weekly_tss: int,
    status_band: str = "ok",
):
    date = _today_bj() + timedelta(days=day_offset)
    db.add(
        DailyTrainingLoad(
            user_id=user_id,
            date=date,
            ctl=ctl,
            atl=atl,
            tsb=ctl - atl,
            tss_today=tss_today,
            weekly_tss=weekly_tss,
            status_band=status_band,
        )
    )
    db.commit()
    return date


def _seed_daily_loads(db, user_id: int, days: int):
    for index in range(days):
        day_offset = -(days - 1 - index)
        ctl = 40.0 + index
        atl = 35.0 + index
        status_band = "fresh" if index == days - 1 else "ok"
        _insert_daily_load(
            db,
            user_id,
            day_offset=day_offset,
            ctl=ctl,
            atl=atl,
            tss_today=60.0 + index,
            weekly_tss=300 + index,
            status_band=status_band,
        )


def test_training_load_30d_returns_30_points(client, db, test_user, auth_header, monkeypatch):
    """用户打开 30 天 tab，一次请求拿到 30 个画图点和顶部状态卡。"""
    # 本 test 专注曲线渲染逻辑 / 不测覆盖率门槛 / mock 覆盖率达标（门槛单独 test）
    import app.training.service as training_service
    monkeypatch.setattr(training_service, "_recent_tss_coverage", lambda *a, **k: 1.0)
    _seed_daily_loads(db, test_user.id, 30)

    resp = client.get("/api/training/load?range=30d", headers=auth_header)

    assert resp.status_code == 200
    data = resp.json()
    assert data["range"] == "30d"
    assert len(data["points"]) == 30
    assert data["points"][-1]["date"] == str(_today_bj())
    assert data["summary"]["current_ctl"] == 69.0
    assert data["summary"]["current_atl"] == 64.0
    assert data["summary"]["current_tsb"] == 5.0
    assert data["summary"]["current_status_band"] == "fresh"
    assert data["summary"]["current_status_label"] == "状态饱满"
    assert data["summary"]["weekly_tss"] == 329
    assert data["summary"]["data_complete"] is True


def test_training_load_supports_90d_and_1y_ranges(client, db, test_user, auth_header):
    """切 90 天或全年 tab 时，后端按 range 返回对应长度。"""
    _seed_daily_loads(db, test_user.id, 365)

    resp_90d = client.get("/api/training/load?range=90d", headers=auth_header)
    resp_1y = client.get("/api/training/load?range=1y", headers=auth_header)

    assert resp_90d.status_code == 200
    assert resp_1y.status_code == 200
    assert len(resp_90d.json()["points"]) == 90
    assert len(resp_1y.json()["points"]) == 365


def test_training_load_no_records_returns_empty_points(client, auth_header):
    """新用户没有账本时，不画假曲线，只返回空 points 和全 0 summary。"""
    resp = client.get("/api/training/load?range=30d", headers=auth_header)

    assert resp.status_code == 200
    data = resp.json()
    assert data["points"] == []
    assert data["summary"] == {
        "current_ctl": 0.0,
        "current_atl": 0.0,
        "current_tsb": 0.0,
        "current_status_band": "ok",
        "current_status_label": "状态 OK",
        "tss_today": 0.0,
        "weekly_tss": 0,
        "data_complete": False,
        "insufficient_power_data": False,
    }


def test_training_load_invalid_range_returns_422(client, auth_header):
    """range 只接受 30d / 90d / 1y，防止前端拼错悄悄返回假数据。"""
    resp = client.get("/api/training/load?range=7d", headers=auth_header)

    assert resp.status_code == 422


def test_training_load_requires_login(client):
    """训练负荷是个人训练账本，没有 token 时必须 401。"""
    resp = client.get("/api/training/load?range=30d")

    assert resp.status_code == 401


def test_training_load_does_not_leak_other_user_data(client, db, test_user, auth_header):
    """只能看到自己的训练负荷，不能串到别人的账本。"""
    from app.user.models import User

    other = User(openid="training_load_other")
    db.add(other)
    db.commit()
    db.refresh(other)
    _insert_daily_load(
        db,
        other.id,
        day_offset=0,
        ctl=99.0,
        atl=88.0,
        tss_today=120.0,
        weekly_tss=777,
        status_band="fresh",
    )

    resp = client.get("/api/training/load?range=30d", headers=auth_header)

    assert resp.status_code == 200
    data = resp.json()
    assert data["points"] == []
    assert data["summary"]["current_ctl"] == 0.0


def test_training_load_rounds_floats_to_one_decimal(client, db, test_user, auth_header):
    """接口层统一给小程序 1 位小数，避免前端拿到一串长小数。"""
    _insert_daily_load(
        db,
        test_user.id,
        day_offset=0,
        ctl=65.34,
        atl=78.19,
        tss_today=95.55,
        weekly_tss=451,
        status_band="tired",
    )

    resp = client.get("/api/training/load?range=30d", headers=auth_header)

    point = resp.json()["points"][0]
    summary = resp.json()["summary"]
    assert point["ctl"] == 65.3
    assert point["atl"] == 78.2
    assert point["tsb"] == -12.9
    assert point["tss_today"] == 95.6
    assert summary["current_status_label"] == "累"


def test_training_load_13_days_history_is_incomplete(client, db, test_user, auth_header):
    """历史少于 14 天时，返回真实已有点，不补成 30 天假完整曲线。"""
    _seed_daily_loads(db, test_user.id, 13)

    resp = client.get("/api/training/load?range=30d", headers=auth_header)

    data = resp.json()
    assert len(data["points"]) == 13
    assert data["summary"]["data_complete"] is False


def test_training_load_fills_missing_day_with_natural_decay(client, db, test_user, auth_header, monkeypatch):
    """历史足够时，窗口内缺日要补 0 TSS，并让 CTL/ATL 自然衰减。"""
    import app.training.service as training_service
    monkeypatch.setattr(training_service, "_recent_tss_coverage", lambda *a, **k: 1.0)
    _seed_daily_loads(db, test_user.id, 14)
    missing_date = _today_bj() - timedelta(days=1)
    db.query(DailyTrainingLoad).filter_by(user_id=test_user.id, date=missing_date).delete()
    db.commit()

    resp = client.get("/api/training/load?range=30d", headers=auth_header)

    data = resp.json()
    point_by_date = {point["date"]: point for point in data["points"]}
    missing_point = point_by_date[str(missing_date)]
    assert len(data["points"]) == 30
    assert missing_point["tss_today"] == 0.0
    assert missing_point["ctl"] > 0.0
    assert missing_point["atl"] > 0.0
    assert missing_point["status_band"] in {"fresh", "ok", "tired", "overreached"}


def test_training_load_insufficient_power_coverage_hides_curve(client, db, test_user, auth_header, monkeypatch):
    """最近 42 天 TSS 覆盖率 < 50% 时不展示 PMC：data_complete=false + insufficient_power_data=true（防 CTL 失真误导）。"""
    import app.training.service as training_service
    monkeypatch.setattr(training_service, "_recent_tss_coverage", lambda *a, **k: 0.3)
    _seed_daily_loads(db, test_user.id, 30)  # 历史够长（>14 天）/ 但功率覆盖率不足

    resp = client.get("/api/training/load?range=30d", headers=auth_header)

    data = resp.json()
    assert resp.status_code == 200
    assert data["summary"]["data_complete"] is False
    assert data["summary"]["insufficient_power_data"] is True


def test_training_load_sufficient_power_coverage_shows_curve(client, db, test_user, auth_header, monkeypatch):
    """覆盖率 >= 50% + 历史够长 → 正常展示完整曲线。"""
    import app.training.service as training_service
    monkeypatch.setattr(training_service, "_recent_tss_coverage", lambda *a, **k: 0.8)
    _seed_daily_loads(db, test_user.id, 30)

    resp = client.get("/api/training/load?range=30d", headers=auth_header)

    data = resp.json()
    assert data["summary"]["data_complete"] is True
    assert data["summary"]["insufficient_power_data"] is False
    assert len(data["points"]) == 30
