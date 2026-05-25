"""
训练结构 API 服务像一个只读取号窗口：查当前用户最近 6 周有功率区间的骑行，再交给纯函数翻译成页面数据。

操作注意事项：这个文件不写数据库、不改训练负荷账本，只复用 service.py 的北京时间工具，避免同一扇日历门有两套钥匙。
输入/输出数据流：输入是当前 user_id 和 range；输出是 `/api/training/distribution` 的完整响应 dict。
"""

from datetime import timedelta

from sqlalchemy.orm import Session

from app.activity.models import Activity
from app.training.distribution import aggregate_power_zones, build_training_distribution_payload, normalize_power_zones
from app.training.service import _bj_day_start_utc, _today_bj


WINDOW_DAYS = 42


def get_training_distribution_response(db: Session, user_id: int, range: str = "6w", exclude_zero: bool = True) -> dict:
    """获取当前用户最近 6 周训练结构。"""
    if range != "6w":
        raise ValueError("training distribution range only supports 6w")

    today = _today_bj()
    start_day = today - timedelta(days=WINDOW_DAYS - 1)
    end_day = today + timedelta(days=1)
    start_utc = _bj_day_start_utc(start_day)
    end_utc = _bj_day_start_utc(end_day)

    activities = (
        db.query(Activity.power_zones)
        .filter(
            Activity.user_id == user_id,
            Activity.status == "completed",
            Activity.activity_type == "cycling",
            Activity.duplicate_of.is_(None),
            Activity.started_at.isnot(None),
            Activity.started_at >= start_utc,
            Activity.started_at < end_utc,
            Activity.power_zones.isnot(None),
        )
        .all()
    )
    zone_sets = []
    for row in activities:
        normalized = normalize_power_zones(row.power_zones)
        if normalized:
            zone_sets.append(normalized)
    stats = aggregate_power_zones(zone_sets, exclude_zero=exclude_zero)
    payload = build_training_distribution_payload(stats)
    return {
        "range": range,
        "window_days": WINDOW_DAYS,
        **payload,
    }
