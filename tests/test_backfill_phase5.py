from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import scripts.backfill_phase5 as backfill

class _Attr:
    def __init__(self, name):
        self.name = name

    def __eq__(self, other):
        return ("eq", self.name, other)

    def __ge__(self, other):
        return ("ge", self.name, other)

    def is_(self, other):
        return ("is", self.name, other)

    def isnot(self, other):
        return ("isnot", self.name, other)


class _FakeSegment:
    pass


class _FakeTrackpoint:
    geom = _Attr("geom")
    activity_id = _Attr("activity_id")
    seq = _Attr("seq")


class _FakeUser:
    id = _Attr("id")
    city = _Attr("city")


class _FakeActivity:
    user_id = _Attr("user_id")
    started_at = _Attr("started_at")
    status = _Attr("status")


class _Query:
    def __init__(self, rows):
        self.rows = list(rows)
        self.predicates = []

    def filter(self, *predicates):
        self.predicates.extend(predicates)
        return self

    def order_by(self, *args):
        return self

    def all(self):
        rows = self.rows
        for predicate in self.predicates:
            rows = [row for row in rows if _matches(row, predicate)]
        return rows


class _Nested:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        self.db.nested_count += 1

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeDb:
    def __init__(self, segments=None, trackpoint_batches=None, users=None, activities=None):
        self.segments = segments or []
        self.trackpoint_batches = list(trackpoint_batches or [])
        self.users = users or []
        self.activities = activities or []
        self.commit_count = 0
        self.close_count = 0
        self.nested_count = 0

    def query(self, model):
        if model is _FakeSegment:
            return _Query(self.segments)
        if model is _FakeTrackpoint:
            return _Query(self.trackpoint_batches.pop(0))
        if model is _FakeUser:
            return _Query(self.users)
        if model is _FakeActivity:
            return _Query(self.activities)
        raise AssertionError(f"unexpected query model: {model!r}")

    def begin_nested(self):
        return _Nested(self)

    def commit(self):
        self.commit_count += 1

    def close(self):
        self.close_count += 1


def _segment(seg_id, lat, lon, *, distance=1000.0, elevation_gain=0.0):
    return SimpleNamespace(
        id=seg_id,
        distance=distance,
        elevation_gain=elevation_gain,
        start_lat=lat,
        start_lon=lon,
        reference_line=f"line-{seg_id}",
    )


def _matches(row, predicate):
    if not isinstance(predicate, tuple) or len(predicate) != 3:
        return True
    op, name, expected = predicate
    actual = getattr(row, name)
    if op == "eq":
        return actual == expected
    if op == "ge":
        return actual is not None and actual >= expected
    if op == "is":
        return actual is expected
    if op == "isnot":
        return actual is not expected
    return True


@pytest.fixture(autouse=True)
def _patch_models(monkeypatch):
    monkeypatch.setattr(backfill, "Segment", _FakeSegment)
    monkeypatch.setattr(backfill, "Trackpoint", _FakeTrackpoint)
    monkeypatch.setattr(backfill, "User", _FakeUser)
    monkeypatch.setattr(backfill, "Activity", _FakeActivity)
    monkeypatch.setattr(backfill, "cast", lambda value, target: ("cast", value, target))
    monkeypatch.setattr(backfill, "Geography", object)
    monkeypatch.setattr(
        backfill,
        "func",
        SimpleNamespace(ST_DWithin=lambda *args: ("ST_DWithin", args)),
    )


def test_backfill_segments_updates_each_segment_and_commits_once(monkeypatch):
    seg1 = _segment(1, 39.9, 116.4, distance=1200.0, elevation_gain=100.0)
    seg2 = _segment(2, 37.87, 112.55, distance=900.0, elevation_gain=None)
    db = _FakeDb(
        segments=[seg1, seg2],
        trackpoint_batches=[
            [SimpleNamespace(id=1, geom=object())],
            [SimpleNamespace(id=2, geom=object())],
        ],
    )
    gradients = iter([12.5, 0.0])
    monkeypatch.setattr(backfill, "calculate_max_gradient", lambda tps: next(gradients))

    failed = backfill.backfill_segments(db)

    assert failed == []
    assert seg1.max_gradient == 12.5
    assert seg1.difficulty == "hard"
    assert seg1.city == "beijing"
    assert seg2.max_gradient == 0.0
    assert seg2.difficulty == "easy"
    assert seg2.city == "taiyuan"
    assert db.nested_count == 2
    assert db.commit_count == 1


def test_backfill_segments_keeps_going_when_one_segment_fails(monkeypatch):
    seg1 = _segment(1, 39.9, 116.4, distance=1200.0, elevation_gain=100.0)
    seg2 = _segment(2, 37.87, 112.55, distance=900.0)
    db = _FakeDb(
        segments=[seg1, seg2],
        trackpoint_batches=[
            [SimpleNamespace(id=1, geom=object())],
            [SimpleNamespace(id=2, geom=object())],
        ],
    )
    calls = {"count": 0}

    def _calculate_max_gradient(trackpoints):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("boom")
        return 4.0

    monkeypatch.setattr(backfill, "calculate_max_gradient", _calculate_max_gradient)

    failed = backfill.backfill_segments(db)

    assert failed == [1]
    assert not hasattr(seg1, "difficulty")
    assert seg2.max_gradient == 4.0
    assert seg2.difficulty == "easy"
    assert seg2.city == "taiyuan"
    assert db.nested_count == 2
    assert db.commit_count == 1


def test_backfill_users_city_uses_recent_then_all_time_then_null():
    now = datetime.now(timezone.utc)
    user_recent = SimpleNamespace(id=1, city=None)
    user_all_time = SimpleNamespace(id=2, city=None)
    user_no_activity = SimpleNamespace(id=3, city=None)
    user_existing = SimpleNamespace(id=4, city="taiyuan")
    db = _FakeDb(
        users=[user_recent, user_all_time, user_no_activity, user_existing],
        activities=[
            SimpleNamespace(
                user_id=1,
                status="completed",
                started_at=now - timedelta(days=2),
                simplified_track=[{"lat": 31.23, "lon": 121.47}],
            ),
            SimpleNamespace(
                user_id=1,
                status="completed",
                started_at=now - timedelta(days=3),
                simplified_track=[{"lat": 31.2, "lon": 121.5}],
            ),
            SimpleNamespace(
                user_id=1,
                status="completed",
                started_at=now - timedelta(days=4),
                simplified_track=[{"lat": 39.9, "lon": 116.4}],
            ),
            SimpleNamespace(
                user_id=2,
                status="completed",
                started_at=now - timedelta(days=3),
                simplified_track=[{"lat": 0.0, "lon": 0.0}],
            ),
            SimpleNamespace(
                user_id=2,
                status="completed",
                started_at=now - timedelta(days=80),
                simplified_track=[{"lat": 30.66, "lon": 104.07}],
            ),
            SimpleNamespace(
                user_id=4,
                status="completed",
                started_at=now - timedelta(days=1),
                simplified_track=[{"lat": 39.9, "lon": 116.4}],
            ),
        ],
    )

    stats = backfill.backfill_users_city(db)

    assert user_recent.city == "shanghai"
    assert user_all_time.city == "chengdu"
    assert user_no_activity.city is None
    assert user_existing.city == "taiyuan"
    assert stats["updated"] == 2
    assert stats["unchanged_null"] == 1
    assert stats["skipped_existing"] == 1
    assert db.commit_count == 1


@pytest.mark.parametrize(
    ("argv", "expected_calls"),
    [
        (["backfill_phase5.py"], ["segments", "users"]),
        (["backfill_phase5.py", "--users"], ["users"]),
    ],
)
def test_main_selects_backfill_scope_and_closes_session(monkeypatch, argv, expected_calls):
    db = _FakeDb()
    calls = []
    monkeypatch.setattr(backfill, "SessionLocal", lambda: db)
    monkeypatch.setattr(backfill, "backfill_segments", lambda session: calls.append("segments") or [])
    monkeypatch.setattr(
        backfill,
        "backfill_users_city",
        lambda session: calls.append("users") or {"updated": 0},
    )
    monkeypatch.setattr(backfill.sys, "argv", argv)

    exit_code = backfill.main()

    assert exit_code == 0
    assert calls == expected_calls
    assert db.close_count == 1


def test_main_returns_nonzero_when_segments_failed(monkeypatch):
    db = _FakeDb()
    monkeypatch.setattr(backfill, "SessionLocal", lambda: db)
    monkeypatch.setattr(backfill, "backfill_segments", lambda session: [42])
    monkeypatch.setattr(backfill, "backfill_users_city", lambda session: {"updated": 0})
    monkeypatch.setattr(backfill.sys, "argv", ["backfill_phase5.py", "--segments"])

    assert backfill.main() == 1
    assert db.close_count == 1
