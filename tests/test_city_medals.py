"""Sprint 6 task-3：城市勋章 endpoint + worker hook + backfill 主测试文件。

测试矩阵（与 task 卡 L362-376 14 条对齐）：

聚合 / endpoint 层（SQLite + ORM）：
  1. 用户骑过 beijing + shanghai → unlocked = ["beijing", "shanghai"] / count = 2
  2. 用户无活动 → unlocked = [] / count = 0 / total = 6
  3. activity.city = 'unknown' → 不计入解锁
  4. activity.city = NULL → 不计入解锁 / 不报错（NULL vs unknown 语义验证）
 12. 自他对称：GET /me/city-medals === GET /{user_id}/city-medals
 13. 看不存在用户：GET /{999}/city-medals → 404
 14. 性能：1000 条 activities 聚合 < 100ms

worker hook 层（_set_activity_city helper 行为）：
  7. GPX 上传 → activity.city 写入
  8. FIT 上传 → activity.city 写入（与 GPX 共 helper / 但独立 case 防回退）
  9. Strava 导入 → activity.city 写入（import_scheduler 路径真接入）
 10. 空 track / 坐标缺失 → city = NULL（不是 'unknown' / 红线）

backfill 层（脚本干跑）：
 11. backfill --dry-run：列 row 数 / 不真写

CHECK 约束（PG 层 / 5, 6）走 tests/test_activity_city_field.py（dialect 守卫 skip SQLite）。
"""

import time
from unittest.mock import MagicMock, patch

import pytest

from app.activity.models import Activity
from app.user.cities import VALID_CITY_CODES
from app.user.service_social import get_city_medals
from tests.conftest import _activities_table


# ============================================================
# 聚合层测试（case 1-4 / 12-14）
# ============================================================


def _insert_activity(db, user_id, city=None, status="completed", duplicate_of=None):
    """直接通过 SQL 插入 activity 行（绕过 ORM 让 SQLite 测试不依赖 PG 专有类型）。"""
    db.execute(
        _activities_table.insert().values(
            user_id=user_id,
            title=f"test_{city}",
            status=status,
            file_url=f"test_{city}.gpx",
            distance=10000.0,
            city=city,
            duplicate_of=duplicate_of,
        )
    )
    db.commit()


def test_case1_user_rode_beijing_shanghai_returns_2(db, test_user):
    """case-1：用户骑过 beijing + shanghai → unlocked=["beijing", "shanghai"] / count=2。"""
    _insert_activity(db, test_user.id, city="beijing")
    _insert_activity(db, test_user.id, city="shanghai")

    result = get_city_medals(db, test_user.id)

    assert result["unlocked"] == ["beijing", "shanghai"]  # sorted
    assert result["unlocked_count"] == 2
    assert result["total"] == 6
    assert len(result["medals"]) == 6
    # beijing / shanghai 应 unlocked
    by_city = {m["city"]: m for m in result["medals"]}
    assert by_city["beijing"]["unlocked"] is True
    assert by_city["shanghai"]["unlocked"] is True
    # 其他 4 城应 locked
    assert by_city["hangzhou"]["unlocked"] is False
    assert by_city["shenzhen"]["unlocked"] is False
    assert by_city["chengdu"]["unlocked"] is False
    assert by_city["taiyuan"]["unlocked"] is False


def test_case2_no_activities_returns_empty(db, test_user):
    """case-2：用户无活动 → unlocked=[] / count=0 / total=6。"""
    result = get_city_medals(db, test_user.id)

    assert result["unlocked"] == []
    assert result["unlocked_count"] == 0
    assert result["total"] == 6
    # 6 城全 locked
    assert all(m["unlocked"] is False for m in result["medals"])
    # 字段集合稳定（防 schema 漂移）
    assert {m["city"] for m in result["medals"]} == set(VALID_CITY_CODES)


def test_case3_city_unknown_not_counted(db, test_user):
    """case-3：activity.city='unknown' → 不计入解锁（业务规则：unknown 不算"征服"）。"""
    _insert_activity(db, test_user.id, city="unknown")
    _insert_activity(db, test_user.id, city="unknown")

    result = get_city_medals(db, test_user.id)

    assert result["unlocked"] == []
    assert result["unlocked_count"] == 0


def test_case4_city_null_not_counted_and_no_error(db, test_user):
    """case-4：activity.city=NULL → 不计入解锁 / 不报错（NULL vs unknown 语义）。"""
    _insert_activity(db, test_user.id, city=None)
    _insert_activity(db, test_user.id, city=None)

    result = get_city_medals(db, test_user.id)

    assert result["unlocked"] == []
    assert result["unlocked_count"] == 0


def test_case3and4_combined_null_unknown_and_real_city(db, test_user):
    """复合场景：NULL + unknown + 真城市混合 → 只算真城市（白名单严格生效）。"""
    _insert_activity(db, test_user.id, city=None)
    _insert_activity(db, test_user.id, city="unknown")
    _insert_activity(db, test_user.id, city="beijing")

    result = get_city_medals(db, test_user.id)

    assert result["unlocked"] == ["beijing"]
    assert result["unlocked_count"] == 1


def test_aggregation_filters_pending_status(db, test_user):
    """过滤规则：pending 状态不计入（只算 completed）/ duplicate_of IS NOT NULL 不计入。"""
    _insert_activity(db, test_user.id, city="beijing", status="completed")
    _insert_activity(db, test_user.id, city="shanghai", status="pending")  # 未完成
    # duplicate 活动应排除
    _insert_activity(db, test_user.id, city="hangzhou", status="completed", duplicate_of=1)

    result = get_city_medals(db, test_user.id)

    assert result["unlocked"] == ["beijing"]
    assert result["unlocked_count"] == 1


# ============================================================
# router 层 / 自他对称 / 404 测试（case 12-13）
# ============================================================


def test_case12_self_others_symmetric_returns_same_fields(client, auth_header, test_user, db):
    """case-12：GET /me/city-medals 和 GET /{user_id}/city-medals 字段集合完全一致。"""
    _insert_activity(db, test_user.id, city="beijing")

    resp_self = client.get("/api/user/me/city-medals", headers=auth_header)
    resp_others = client.get(f"/api/user/{test_user.id}/city-medals", headers=auth_header)

    assert resp_self.status_code == 200
    assert resp_others.status_code == 200
    # 字段集合 + 值完全一致（自他对称 D-P08 红线）
    assert resp_self.json() == resp_others.json()


def test_case13_nonexistent_user_returns_404(client, auth_header):
    """case-13：GET /{999}/city-medals 不存在的用户 → 404。"""
    resp = client.get("/api/user/999999/city-medals", headers=auth_header)
    assert resp.status_code == 404


def test_endpoint_requires_auth(client):
    """无 token → 401。"""
    resp = client.get("/api/user/me/city-medals")
    assert resp.status_code == 401


def test_endpoint_response_schema(client, auth_header, test_user, db):
    """response schema 完整（unlocked / unlocked_count / total / medals 4 字段）。"""
    _insert_activity(db, test_user.id, city="chengdu")

    resp = client.get("/api/user/me/city-medals", headers=auth_header)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"unlocked", "unlocked_count", "total", "medals"}
    assert body["unlocked"] == ["chengdu"]
    assert body["total"] == 6
    # 每格 medal 字段集稳定
    for medal in body["medals"]:
        assert set(medal.keys()) == {"city", "label", "unlocked"}


# ============================================================
# 性能测试（case 14）
# ============================================================


def test_case14_perf_1000_activities_under_100ms(db, test_user):
    """case-14：1000 条 activities 聚合 < 100ms（功能性能 smoke test）。

    ⚠️ 本测试在 SQLite 内存表跑 / 无 partial index（PG-only / 走 dialect 守卫）/
    **不能证明 PG 生产环境真命中 idx_activities_user_city_completed**（Codex 异源审 Important）。
    只能证明 service 层 SQL 写法在小规模下不退化到 N+1。

    真 PG partial index 命中验证留 tech-debt P3（docs/tech-debt.md）/
    后续在 dev stack 用真 PG `EXPLAIN ANALYZE` 验证 / 或部署后真用回归打 1000 真活动确认 p99。
    """
    cities = ["beijing", "shanghai", "hangzhou", "shenzhen", "chengdu", "taiyuan"]
    # 批量插入 1000 条（轮流分配到 6 城）
    db.execute(
        _activities_table.insert(),
        [
            {
                "user_id": test_user.id,
                "title": f"perf_{i}",
                "status": "completed",
                "file_url": f"perf_{i}.gpx",
                "distance": 10000.0,
                "city": cities[i % 6],
            }
            for i in range(1000)
        ],
    )
    db.commit()

    start = time.perf_counter()
    result = get_city_medals(db, test_user.id)
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert result["unlocked_count"] == 6  # 6 城全解锁
    assert elapsed_ms < 100, f"聚合耗时 {elapsed_ms:.2f}ms 超过 100ms"


# ============================================================
# Worker hook 层（case 7-10）
# ============================================================


class _FakeActivity:
    """轻量 fake / 不依赖 ORM 表 / 直接验证 _set_activity_city 是否写 .city 字段。"""

    def __init__(self):
        self.city = None
        self.simplified_track = None


def test_case7_gpx_upload_hook_writes_city():
    """case-7：GPX 上传 worker → _set_activity_city 写 activity.city。

    GPX/FIT 共一个 worker 函数（worker.py / _do_parse），起点北京坐标应写 city='beijing'。
    """
    from app.activity.worker import _set_activity_city

    act = _FakeActivity()
    # 北京天安门坐标（39.9, 116.4）/ infer_city_from_coords 返 'beijing'
    track = [{"lat": 39.9, "lon": 116.4, "ele": 50}]
    _set_activity_city(act, track)
    assert act.city == "beijing"


def test_case8_fit_upload_hook_writes_city():
    """case-8：FIT 上传 → _set_activity_city 写 city（与 GPX 共 helper）。

    FIT 走同一 worker._do_parse / 同一 helper / 验证 simplified_track 起点上海坐标 → 'shanghai'。
    """
    from app.activity.worker import _set_activity_city

    act = _FakeActivity()
    # 上海陆家嘴坐标（31.23, 121.47）
    track = [{"lat": 31.23, "lon": 121.47, "ele": 10}]
    _set_activity_city(act, track)
    assert act.city == "shanghai"


def test_case9_strava_import_path_hook_integrated():
    """case-9：Strava 导入路径 worker hook 接入（防回退 / source-level）。

    红线 v0.4：import_scheduler.py 必须真调 _set_activity_city / 不能漏。

    本测试 = source-level grep + helper 单测（case-9b）的双层防护：
    - case-9：grep 源码确认 import_scheduler.py 真出现 _set_activity_city 调用
    - case-9b：直调 helper 验证杭州坐标 → 'hangzhou' 等真实行为
    完整 e2e（从 _run_tier2 跑到 hook 真触发）成本高 / 需 mock 5-7 上游依赖 +
    假 Strava activity setup / 当前留 tech-debt P3（见 docs/tech-debt.md）/
    task-6 真用回归（小明真 Strava 同步看 city 是否点亮）兜底覆盖。
    """
    import inspect

    from app.strava import import_scheduler

    source = inspect.getsource(import_scheduler)
    assert "_set_activity_city" in source, (
        "import_scheduler.py 必须调用 _set_activity_city / 漏接入 = "
        "Strava 同步活动 city 永远 NULL → city-medals 漏算"
    )


def test_case9b_strava_helper_works_with_real_coords():
    """case-9b：Strava 路径同样调 _set_activity_city helper / 杭州坐标 → 'hangzhou'。

    模拟 Strava 同步过来的 activity 起点（杭州西湖坐标），验证 helper 行为统一。
    """
    from app.activity.worker import _set_activity_city

    act = _FakeActivity()
    # 杭州西湖坐标（30.25, 120.15）
    track = [{"lat": 30.25, "lon": 120.15, "ele": 20}]
    _set_activity_city(act, track)
    assert act.city == "hangzhou"


def test_case10_empty_track_keeps_null():
    """case-10a：simplified_track 为 None / 空 list → activity.city = NULL（不是 'unknown'）。

    红线：NULL vs 'unknown' 不可混淆。
    - NULL = "从未推断过"（空 track / 旧数据）
    - unknown = "推断过但不在 6 城"
    """
    from app.activity.worker import _set_activity_city

    act = _FakeActivity()
    _set_activity_city(act, None)
    assert act.city is None  # 不写 / 保持 NULL

    act2 = _FakeActivity()
    _set_activity_city(act2, [])
    assert act2.city is None  # 不写 / 保持 NULL


def test_case10b_missing_lat_lon_keeps_null():
    """case-10b：起点 lat/lon 缺失 → 保持 NULL（不写 'unknown'）。"""
    from app.activity.worker import _set_activity_city

    act = _FakeActivity()
    # lat 缺失
    _set_activity_city(act, [{"lon": 116.4, "ele": 50}])
    assert act.city is None

    act2 = _FakeActivity()
    # lon 缺失
    _set_activity_city(act2, [{"lat": 39.9, "ele": 50}])
    assert act2.city is None

    act3 = _FakeActivity()
    # lat/lon 都为 None
    _set_activity_city(act3, [{"lat": None, "lon": None}])
    assert act3.city is None


def test_case10c_coords_outside_6_cities_writes_unknown():
    """case-10c 对照：坐标在中国但不在 6 城 → 写 'unknown'（非 NULL）。

    与 case-10a/b 对照：有坐标推断过 → unknown / 无坐标 → NULL。语义严格区分。
    """
    from app.activity.worker import _set_activity_city

    act = _FakeActivity()
    # 南京坐标（32.06, 118.79）/ 不在 6 城 box / infer_city_from_coords 返 'unknown'
    _set_activity_city(act, [{"lat": 32.06, "lon": 118.79}])
    assert act.city == "unknown"


def test_case10d_lat_lon_zero_is_valid():
    """truthiness 陷阱 #1 防御：lat=0.0 / lon=0.0 是合法值（赤道 / 本初子午线交点）。

    helper 必须用 `is None` 不能 `if lat:` —— 0.0 truthy 会被误判为缺失。
    几内亚湾外海（0.0, 0.0）不在 6 城 → unknown / 但 helper 应推断不漏。
    """
    from app.activity.worker import _set_activity_city

    act = _FakeActivity()
    _set_activity_city(act, [{"lat": 0.0, "lon": 0.0}])
    assert act.city == "unknown"  # 推断过（不是 None）


def test_helper_exception_keeps_null():
    """异常容错：helper 任何异常都不阻断 / activity.city 保持 NULL。

    模拟 simplified_track 是非法类型（字符串 / 不是 list）/ helper 应 try/except 兜底。
    """
    from app.activity.worker import _set_activity_city

    act = _FakeActivity()
    # 传入非法 track（不是 list/None）/ helper 进入 try → first_pt = track[0] 可能成功 .get / 看场景
    # 这里用更明确的非法：传 "not a list"
    _set_activity_city(act, "not_a_list")  # type: ignore[arg-type]
    # helper 内部异常 try/except 兜底 / city 应保持 None
    assert act.city is None


# ============================================================
# Backfill 脚本（case 11）
# ============================================================


def test_case11_backfill_dry_run_lists_no_write(db, test_user, capsys):
    """case-11：backfill --dry-run 列出 row 数 / 不真写。

    通过 SessionLocal monkeypatch 让 backfill 跑在测试 db 上 / 验证 city 字段不变。
    """
    # 准备 2 条 simplified_track 不为 NULL 但 city 为 NULL 的活动（待回填）
    import json

    track_beijing = json.dumps([{"lat": 39.9, "lon": 116.4}])
    track_shanghai = json.dumps([{"lat": 31.23, "lon": 121.47}])
    db.execute(
        _activities_table.insert().values(
            user_id=test_user.id,
            title="待回填-1",
            status="completed",
            file_url="bf1.gpx",
            simplified_track=track_beijing,
            city=None,
        )
    )
    db.execute(
        _activities_table.insert().values(
            user_id=test_user.id,
            title="待回填-2",
            status="completed",
            file_url="bf2.gpx",
            simplified_track=track_shanghai,
            city=None,
        )
    )
    db.commit()

    # monkeypatch SessionLocal 让 backfill 用我们的测试 db
    from scripts import backfill_activity_city

    with patch.object(backfill_activity_city, "SessionLocal", return_value=db):
        # 关键：保留 db.close()，让脚本"close 后"测试还能用 / 用 MagicMock 把 close 屏蔽
        original_close = db.close
        db.close = MagicMock()  # type: ignore[assignment]
        try:
            backfill_activity_city.main(dry_run=True)
        finally:
            db.close = original_close  # type: ignore[assignment]

    captured = capsys.readouterr()
    # 应列出待回填条数 + 明确 dry-run 字样
    assert "找到 2 条" in captured.out
    assert "dry-run" in captured.out.lower()

    # 验证 city 字段没被改（dry-run 不真写）
    from sqlalchemy import select

    rows = db.execute(
        select(_activities_table.c.city).where(
            _activities_table.c.user_id == test_user.id
        )
    ).fetchall()
    assert all(r[0] is None for r in rows)
