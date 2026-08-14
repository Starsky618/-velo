"""补充整轴抓取必须保持 exact-two、零区域枚举边界。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ingest_exact_strava_climb_axes import (
    _apply,
    _load_spec,
    _polygon,
    _polygon_wkt,
)


ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "data/research/xishan_supplemental_exact_climb_ingest_v1.json"


def test_exact_ingest_spec_names_only_two_missing_full_axes():
    spec = _load_spec(SPEC)
    assert spec["batch_id"] == "xishan-exact-climbs-20260814-v1"
    assert [row["source_segment_id"] for row in spec["segments"]] == [
        "34856789",
        "37687861",
    ]
    assert "no explore enumeration" in spec["request_boundary"]


def test_exact_ingest_bounds_create_closed_polygon():
    spec = _load_spec(SPEC)
    from scripts.ingest_exact_strava_climb_axes import _bounds

    bounds = _bounds(spec)
    polygon = _polygon(bounds)
    assert len(polygon) == 5
    assert polygon[0] == polygon[-1]
    assert _polygon_wkt(bounds).startswith("POLYGON ((")


def test_exact_ingest_never_claims_region_enumeration_complete():
    source = (
        ROOT / "scripts/ingest_exact_strava_climb_axes.py"
    ).read_text(encoding="utf-8")
    assert 'enumeration_status="indeterminate"' in source
    assert 'enumeration_status="source_visible_complete"' not in source


def test_exact_ingest_rejects_scope_expansion(tmp_path):
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    spec["segments"].append(
        {
            "source_segment_id": "999",
            "expected_name": "scope drift",
            "future_module_key": "scope_drift",
        }
    )
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    with pytest.raises(ValueError, match="two unique"):
        _load_spec(path)


def test_second_strava_segment_failure_opens_no_write_transaction(monkeypatch):
    spec = _load_spec(SPEC)
    sessions = []

    class BootstrapSession:
        writes = 0

        def get(self, _model, _key):
            return None

        def add(self, _value):
            self.writes += 1

        def close(self):
            pass

    def session_factory():
        session = BootstrapSession()
        sessions.append(session)
        return session

    calls = 0

    def fetch(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("second complete stream failed")
        return {
            "detail_status": "complete",
            "geometry_status": "complete",
            "region_membership": "inside",
        }

    monkeypatch.setattr("scripts.ingest_exact_strava_climb_axes.SessionLocal", session_factory)
    monkeypatch.setattr(
        "scripts.ingest_exact_strava_climb_axes._select_strava_user",
        lambda _db, _user_id: type("User", (), {"id": 2})(),
    )
    monkeypatch.setattr(
        "scripts.ingest_exact_strava_climb_axes.ShortLivedStravaClient",
        lambda *_args: object(),
    )
    monkeypatch.setattr(
        "scripts.ingest_exact_strava_climb_axes.fetch_segment_observation",
        fetch,
    )

    with pytest.raises(RuntimeError, match="second complete stream failed"):
        _apply(spec, user_id=2, interval_seconds=5.2)

    assert calls == 2
    assert len(sessions) == 1
    assert sessions[0].writes == 0
