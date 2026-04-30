"""
本地开发种子数据脚本——给 dev stack 一份"够测 task-1.A.2 的最小数据集"。

干啥用：
- task-1.A.2 测三件事都需要真实数据：from-activity（需 trackpoints）/
  即时反馈（需同一 segment 多次 effort 且 started_at 乱序）/ 搜索筛选（需多 city/difficulty）
- 不调外部 API，只往 PG 插数据；幂等可重跑

幂等策略：openid 唯一 → upsert by openid；segment 用 name 检测，赛段已存在则全部跳过。
重置：docker compose -f docker-compose.dev.yml down -v && up -d 后重跑。

调用：docker compose -p velo-dev -f docker-compose.dev.yml exec api python -m scripts.seed_dev_data
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text

from app.activity.models import Activity, Trackpoint
from app.database import SessionLocal
from app.segment.models import Segment, SegmentEffort
from app.user.models import User


UTC = timezone.utc


# ---------- 1. 用户 ---------- #

def upsert_users(db) -> tuple[User, User]:
    """admin（建赛段 / 测 from-activity）+ 普通 user（测即时反馈）。"""
    admin = db.scalar(select(User).where(User.openid == "dev_admin"))
    if admin is None:
        admin = User(
            openid="dev_admin",
            nickname="开发管理员",
            is_admin=True,
            ftp=260,
            weight=70.0,
            bike_type="road",
            city="beijing",
        )
        db.add(admin)
        db.flush()
        print(f"  + admin user id={admin.id}")
    else:
        print(f"  · admin user id={admin.id}（已存在跳过）")

    normal = db.scalar(select(User).where(User.openid == "dev_user_1"))
    if normal is None:
        normal = User(
            openid="dev_user_1",
            nickname="普通骑手",
            is_admin=False,
            ftp=200,
            weight=68.0,
            bike_type="road",
            city="beijing",
        )
        db.add(normal)
        db.flush()
        print(f"  + normal user id={normal.id}")
    else:
        print(f"  · normal user id={normal.id}（已存在跳过）")

    return admin, normal


# ---------- 2. 赛段 ---------- #

# 7 条赛段：覆盖 6 主城 + unknown / 4 难度
# reference_line 用简短 LINESTRING（4-5 个坐标点），起终点 ±0.05 度（约 5km）
SEGMENTS_SEED = [
    {
        "name": "望京坡 - dev",
        "city": "beijing",
        "difficulty": "hard",
        "start_lat": 39.99, "start_lon": 116.48,
        "end_lat": 39.95, "end_lon": 116.52,
        "distance": 5200.0,
        "elevation_gain": 180.0,
        "max_gradient": 8.5,
    },
    {
        "name": "北海公园环线 - dev",
        "city": "beijing",
        "difficulty": "easy",
        "start_lat": 39.92, "start_lon": 116.39,
        "end_lat": 39.93, "end_lon": 116.40,
        "distance": 1800.0,
        "elevation_gain": 15.0,
        "max_gradient": 1.2,
    },
    {
        "name": "浦东外环 - dev",
        "city": "shanghai",
        "difficulty": "medium",
        "start_lat": 31.22, "start_lon": 121.50,
        "end_lat": 31.18, "end_lon": 121.55,
        "distance": 7400.0,
        "elevation_gain": 35.0,
        "max_gradient": 2.0,
    },
    {
        "name": "梅家坞 - dev",
        "city": "hangzhou",
        "difficulty": "hard",
        "start_lat": 30.20, "start_lon": 120.10,
        "end_lat": 30.18, "end_lon": 120.13,
        "distance": 4100.0,
        "elevation_gain": 220.0,
        "max_gradient": 9.0,
    },
    {
        "name": "梧桐山 - dev",
        "city": "shenzhen",
        "difficulty": "extreme",
        "start_lat": 22.58, "start_lon": 114.22,
        "end_lat": 22.56, "end_lon": 114.25,
        "distance": 6300.0,
        "elevation_gain": 720.0,
        "max_gradient": 14.0,
    },
    {
        "name": "二环路 - dev",
        "city": "chengdu",
        "difficulty": "easy",
        "start_lat": 30.66, "start_lon": 104.06,
        "end_lat": 30.69, "end_lon": 104.09,
        "distance": 3500.0,
        "elevation_gain": 12.0,
        "max_gradient": 0.8,
    },
    {
        "name": "汾河西岸 - dev",
        "city": "taiyuan",
        "difficulty": "medium",
        "start_lat": 37.85, "start_lon": 112.55,
        "end_lat": 37.88, "end_lon": 112.56,
        "distance": 4200.0,
        "elevation_gain": 60.0,
        "max_gradient": 3.0,
    },
]


def upsert_segments(db) -> list[Segment]:
    """7 条赛段；按 name 检测幂等。"""
    out: list[Segment] = []
    for s in SEGMENTS_SEED:
        existing = db.scalar(select(Segment).where(Segment.name == s["name"]))
        if existing is not None:
            print(f"  · segment '{s['name']}' 已存在 id={existing.id}（跳过）")
            out.append(existing)
            continue
        # PostGIS LINESTRING 字符串：起点 → 终点 简单两点直线
        wkt = (
            f"LINESTRING({s['start_lon']} {s['start_lat']}, "
            f"{s['end_lon']} {s['end_lat']})"
        )
        seg = Segment(
            name=s["name"],
            description=f"种子数据 / {s['city']} / {s['difficulty']}",
            distance=s["distance"],
            elevation_gain=s["elevation_gain"],
            max_gradient=s["max_gradient"],
            avg_gradient=round(s["elevation_gain"] / s["distance"] * 100, 2),
            start_lat=s["start_lat"], start_lon=s["start_lon"],
            end_lat=s["end_lat"], end_lon=s["end_lon"],
            reference_line=func.ST_GeomFromText(wkt, 4326),
            difficulty=s["difficulty"],
            city=s["city"],
        )
        db.add(seg)
        db.flush()
        print(f"  + segment id={seg.id} name='{s['name']}' city={s['city']}")
        out.append(seg)
    return out


# ---------- 3. activity + trackpoints（给 from-activity 测试用）---------- #

def upsert_admin_activity(db, admin: User) -> Activity:
    """admin 名下 1 条 activity：60 个 trackpoint 直线，从北京 39.95,116.40 起步。"""
    existing = db.scalar(
        select(Activity).where(
            Activity.user_id == admin.id,
            Activity.title == "[seed] admin 测试骑行",
        )
    )
    if existing is not None:
        print(f"  · admin activity 已存在 id={existing.id}（跳过）")
        return existing

    started = datetime(2026, 4, 1, 8, 0, tzinfo=UTC)
    activity = Activity(
        user_id=admin.id,
        title="[seed] admin 测试骑行",
        status="completed",
        distance=8000.0,
        duration=1800,
        elevation_gain=120.0,
        avg_speed=16.0,
        max_speed=42.0,
        started_at=started,
        finished_at=started + timedelta(seconds=1800),
        data_source="gpx",
        activity_type="cycling",
    )
    db.add(activity)
    db.flush()

    # 60 个轨迹点：lat 从 39.95 → 40.05（约 11km），ele 渐变 0 → 120 米
    for i in range(60):
        lat = 39.95 + i * 0.0017
        lon = 116.40 + i * 0.0008
        ele = i * 2.0
        ts = started + timedelta(seconds=i * 30)
        wkt = f"POINT({lon} {lat})"
        tp = Trackpoint(
            activity_id=activity.id,
            seq=i,
            latitude=lat,
            longitude=lon,
            elevation=ele,
            timestamp=ts,
            heart_rate=130 + i % 20,
            cadence=85,
            power=180 + (i % 30),
            speed=4.5,
            distance=i * 130.0,
            geom=func.ST_GeomFromText(wkt, 4326),
        )
        db.add(tp)
    db.flush()
    print(f"  + admin activity id={activity.id} + 60 trackpoints")
    return activity


# ---------- 4. 普通 user 的两条 effort（即时反馈测试用）---------- #

def upsert_normal_efforts(db, normal: User, segments: list[Segment]) -> None:
    """
    在 segments[0]（望京坡）上给 normal user 留 2 条 effort，
    Activity.started_at 故意乱序（先骑早 effort 时间晚 vs 先骑晚 effort 时间早），
    给 task-1.A.2 测 join Activity ORDER BY started_at 用。
    """
    seg = segments[0]
    existing = db.scalar(
        select(func.count(SegmentEffort.id)).where(
            SegmentEffort.segment_id == seg.id,
            SegmentEffort.user_id == normal.id,
        )
    )
    if existing >= 2:
        print(f"  · normal user 在 seg id={seg.id} 已有 {existing} 条 effort（跳过）")
        return

    # 用 admin activity 已经写入的 trackpoint 之外，再造 normal 自己的两条 activity
    # activity_late = 后骑（started_at 晚），但 created_at / id 早
    # activity_early = 早骑（started_at 早），但 created_at / id 晚
    started_late = datetime(2026, 4, 20, 9, 0, tzinfo=UTC)
    started_early = datetime(2026, 4, 10, 9, 0, tzinfo=UTC)

    a_late = Activity(
        user_id=normal.id,
        title="[seed] normal 后骑（先入库）",
        status="completed",
        distance=5400.0, duration=1100, elevation_gain=190.0,
        avg_speed=17.6, max_speed=38.0,
        started_at=started_late,
        finished_at=started_late + timedelta(seconds=1100),
        data_source="gpx", activity_type="cycling",
    )
    a_early = Activity(
        user_id=normal.id,
        title="[seed] normal 早骑（后入库）",
        status="completed",
        distance=5300.0, duration=1300, elevation_gain=185.0,
        avg_speed=14.7, max_speed=35.0,
        started_at=started_early,
        finished_at=started_early + timedelta(seconds=1300),
        data_source="gpx", activity_type="cycling",
    )
    db.add(a_late)
    db.flush()
    db.add(a_early)
    db.flush()

    # 两条 effort：早骑成绩好（1100s vs 1300s 反过来——later started 的成绩是 1100s 较快）
    # 即"按 Activity.started_at 排序"时，第 1 条 = early(1300s)，第 2 条 = late(1100s)
    # PR 是历史最佳 = 1100s（与时序无关）
    e_late = SegmentEffort(
        segment_id=seg.id, activity_id=a_late.id, user_id=normal.id,
        elapsed_time=1100, avg_speed=17.6, avg_power=205.0,
        start_index=0, end_index=40,
    )
    e_early = SegmentEffort(
        segment_id=seg.id, activity_id=a_early.id, user_id=normal.id,
        elapsed_time=1300, avg_speed=14.7, avg_power=185.0,
        start_index=0, end_index=40,
    )
    db.add(e_late)
    db.add(e_early)
    db.flush()
    print(
        f"  + normal user 在 seg id={seg.id} 留 2 条 effort："
        f"early started={started_early.date()}/1300s, late started={started_late.date()}/1100s"
    )


# ---------- main ---------- #

def main() -> None:
    db = SessionLocal()
    try:
        # 顺手验证 PostGIS 已装（缺扩展 alembic upgrade head 也会装，这只是双保险）
        db.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))

        print("[1/4] users")
        admin, normal = upsert_users(db)
        print("[2/4] segments")
        segments = upsert_segments(db)
        print("[3/4] admin activity + trackpoints")
        upsert_admin_activity(db, admin)
        print("[4/4] normal user efforts（乱序 started_at）")
        upsert_normal_efforts(db, normal, segments)

        db.commit()
        print("\n✅ 种子数据写入完成")
        print(f"   admin user_id = {admin.id}（is_admin=True）")
        print(f"   normal user_id = {normal.id}")
        print(f"   {len(segments)} segments / 1 admin activity (60 tp) / 2 normal efforts")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
