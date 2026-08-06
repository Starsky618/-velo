"""RiderCapabilitySnapshot v0 API contract tests.

The snapshot is an observational, privacy-safe projection for route planning.
It must never expose raw tracks or turn sparse history into false precision.
"""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from app.activity.models import Activity
from app.user.models import User
from jsonschema import Draft202012Validator, FormatChecker


def _ride(
    db,
    user_id: int,
    *,
    days_ago: int,
    distance_km: float,
    moving_minutes: int,
    elevation_gain: float | None,
    data_source: str | None = "fit",
    status: str = "completed",
    activity_type: str = "cycling",
    duplicate_of: int | None = None,
) -> Activity:
    activity = Activity(
        user_id=user_id,
        title="Rider capability test ride",
        status=status,
        activity_type=activity_type,
        duplicate_of=duplicate_of,
        distance=distance_km * 1000,
        moving_time=moving_minutes * 60,
        duration=moving_minutes * 60,
        elevation_gain=elevation_gain,
        data_source=data_source,
        started_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
    )
    db.add(activity)
    db.commit()
    db.refresh(activity)
    return activity


def test_rider_capability_requires_login(client):
    response = client.get("/api/training/rider-capability")

    assert response.status_code == 401


def test_rider_capability_empty_history_fails_closed(client, auth_header):
    response = client.get("/api/training/rider-capability", headers=auth_header)

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "0.1.0"
    assert payload["window_days"] == 42
    assert payload["source_activity_count"] == 0
    assert payload["data_complete"] is False
    assert payload["confidence"] == "insufficient"
    assert payload["freshness"] == "none"
    assert payload["typical_distance_km"] is None
    assert payload["upper_observed_distance_km"] is None
    assert payload["typical_duration_minutes"] is None
    assert payload["typical_climb_m_per_km"] is None
    assert payload["reason_codes"] == ["no_usable_activities"]
    assert payload["privacy"] == {
        "exact_coordinates_included": False,
        "raw_activity_tracks_included": False,
        "health_metrics_included": False,
    }


def test_rider_capability_builds_transparent_recent_envelope(
    client, db, test_user, auth_header
):
    _ride(db, test_user.id, days_ago=1, distance_km=10, moving_minutes=60, elevation_gain=100, data_source="gpx")
    _ride(db, test_user.id, days_ago=2, distance_km=20, moving_minutes=120, elevation_gain=100, data_source="fit")
    _ride(db, test_user.id, days_ago=3, distance_km=30, moving_minutes=180, elevation_gain=300, data_source="strava")
    _ride(db, test_user.id, days_ago=4, distance_km=40, moving_minutes=240, elevation_gain=800, data_source=None)

    response = client.get("/api/training/rider-capability", headers=auth_header)

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_activity_count"] == 4
    assert payload["excluded_activity_count"] == 0
    assert payload["elevation_activity_count"] == 4
    assert payload["data_complete"] is True
    assert payload["confidence"] == "medium"
    assert payload["freshness"] == "fresh"
    assert payload["typical_distance_km"] == 25.0
    assert payload["upper_observed_distance_km"] == 32.5
    assert payload["typical_duration_minutes"] == 150
    assert payload["typical_climb_m_per_km"] == 10.0
    assert payload["source_types"] == ["fit", "gpx", "strava", "unknown"]
    assert payload["reason_codes"] == []
    assert payload["source_revision"].startswith("activity-history:sha256:")
    assert payload["snapshot_id"].startswith("rider-capability:")


def test_rider_capability_filters_other_users_and_bad_route_evidence(
    client, db, test_user, auth_header
):
    other = User(openid="rider_capability_other")
    db.add(other)
    db.commit()
    db.refresh(other)

    _ride(db, test_user.id, days_ago=1, distance_km=30, moving_minutes=120, elevation_gain=300)
    _ride(db, test_user.id, days_ago=2, distance_km=2, moving_minutes=20, elevation_gain=20)
    _ride(db, test_user.id, days_ago=3, distance_km=20, moving_minutes=0, elevation_gain=100)
    _ride(db, test_user.id, days_ago=1, distance_km=99, moving_minutes=300, elevation_gain=900, status="failed")
    _ride(db, test_user.id, days_ago=1, distance_km=88, moving_minutes=300, elevation_gain=800, activity_type="running")
    _ride(db, test_user.id, days_ago=1, distance_km=77, moving_minutes=300, elevation_gain=700, duplicate_of=1)
    _ride(db, test_user.id, days_ago=50, distance_km=66, moving_minutes=300, elevation_gain=600)
    _ride(db, other.id, days_ago=1, distance_km=120, moving_minutes=360, elevation_gain=1200)

    response = client.get("/api/training/rider-capability", headers=auth_header)

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_activity_count"] == 1
    assert payload["excluded_activity_count"] == 2
    assert payload["confidence"] == "low"
    assert payload["data_complete"] is False
    assert payload["typical_distance_km"] == 30.0
    assert payload["reason_codes"] == [
        "too_few_usable_activities",
        "insufficient_elevation_history",
    ]


def test_rider_capability_does_not_invent_climb_profile_from_sparse_elevation(
    client, db, test_user, auth_header
):
    _ride(db, test_user.id, days_ago=1, distance_km=20, moving_minutes=60, elevation_gain=None)
    _ride(db, test_user.id, days_ago=2, distance_km=30, moving_minutes=90, elevation_gain=None)
    _ride(db, test_user.id, days_ago=3, distance_km=40, moving_minutes=120, elevation_gain=400)

    response = client.get("/api/training/rider-capability", headers=auth_header)

    assert response.status_code == 200
    payload = response.json()
    assert payload["confidence"] == "medium"
    assert payload["typical_climb_m_per_km"] is None
    assert payload["elevation_activity_count"] == 1
    assert payload["reason_codes"] == ["insufficient_elevation_history"]


def test_rider_capability_requires_enough_fresh_history_for_high_confidence(
    client, db, test_user, auth_header
):
    for days_ago in range(1, 9):
        _ride(
            db,
            test_user.id,
            days_ago=days_ago,
            distance_km=20 + days_ago,
            moving_minutes=60 + days_ago,
            elevation_gain=200 + days_ago,
        )

    payload = client.get("/api/training/rider-capability", headers=auth_header).json()

    assert payload["source_activity_count"] == 8
    assert payload["confidence"] == "high"
    assert payload["data_complete"] is True
    assert payload["freshness"] == "fresh"


def test_rider_capability_stale_history_cannot_claim_high_confidence(
    client, db, test_user, auth_header
):
    for days_ago in range(20, 28):
        _ride(
            db,
            test_user.id,
            days_ago=days_ago,
            distance_km=20 + days_ago,
            moving_minutes=60 + days_ago,
            elevation_gain=200 + days_ago,
        )

    payload = client.get("/api/training/rider-capability", headers=auth_header).json()

    assert payload["source_activity_count"] == 8
    assert payload["confidence"] == "low"
    assert payload["data_complete"] is False
    assert payload["freshness"] == "stale"
    assert payload["reason_codes"] == ["history_stale"]


def test_rider_capability_matches_language_neutral_agent_contract(
    client, db, test_user, auth_header
):
    _ride(db, test_user.id, days_ago=1, distance_km=25, moving_minutes=75, elevation_gain=250)
    _ride(db, test_user.id, days_ago=2, distance_km=35, moving_minutes=105, elevation_gain=350)
    _ride(db, test_user.id, days_ago=3, distance_km=45, moving_minutes=135, elevation_gain=450)
    payload = client.get("/api/training/rider-capability", headers=auth_header).json()
    schema_path = Path(__file__).resolve().parents[1] / "contracts" / "agent_v0" / "rider_capability_snapshot.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(payload),
        key=lambda error: list(error.path),
    )

    assert errors == []
