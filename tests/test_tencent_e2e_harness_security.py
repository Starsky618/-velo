"""腾讯真链路验收器自身不能误连、误删或吞掉凭据日志。"""

from __future__ import annotations

from fnmatch import fnmatch
import hashlib
import io
import json

import pytest

from scripts import verify_tencent_route_evidence_e2e as verifier


@pytest.fixture(autouse=True)
def _enable_explicit_e2e_gate(monkeypatch):
    monkeypatch.setenv("VELO_LIVE_TENCENT_E2E", "1")


def test_isolation_guard_accepts_only_explicit_local_targets():
    verifier._guard_isolated_services(
        "postgresql://e2e:secret@127.0.0.1:15432/velo_e2e_safe",
        "redis://127.0.0.1:16379/15",
    )


@pytest.mark.parametrize(
    ("database_url", "redis_url"),
    [
        (
            "postgresql://e2e:secret@127.0.0.1:15432/velo_e2e_safe?dbname=velo",
            "redis://127.0.0.1:16379/15",
        ),
        (
            "postgresql://e2e:secret@127.0.0.1:15432/velo_e2e_safe",
            "redis://127.0.0.1:16379/15?db=0",
        ),
    ],
)
def test_isolation_guard_rejects_driver_query_overrides(database_url, redis_url):
    with pytest.raises(verifier.VerificationError):
        verifier._guard_isolated_services(database_url, redis_url)


def test_server_log_scanner_rejects_actual_secret_and_signed_tencent_url():
    with pytest.raises(verifier.VerificationError):
        verifier._assert_server_log_safe(
            io.BytesIO(b"provider request used tencent-secret-marker"),
            ["tencent-secret-marker"],
        )

    with pytest.raises(verifier.VerificationError):
        verifier._assert_server_log_safe(
            io.BytesIO(b"GET https://apis.map.qq.com/ws/place/v1?key=redacted&sig=redacted"),
            [],
        )

    verifier._assert_server_log_safe(io.BytesIO(b"Tencent request failed status=503"), ["not-present"])


class _FakeRedis:
    def __init__(self, initial: dict[str, bytes | str] | None = None):
        self.values = dict(initial or {})

    def dbsize(self):
        return len(self.values)

    def set(self, key, value, *, ex=None, nx=False):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    def get(self, key):
        if isinstance(key, bytes):
            key = key.decode("utf-8")
        return self.values.get(key)

    def delete(self, *keys):
        for key in keys:
            if isinstance(key, bytes):
                key = key.decode("utf-8")
            self.values.pop(key, None)

    def scan_iter(self, *, match):
        for key in tuple(self.values):
            if fnmatch(key, match):
                yield key.encode("utf-8")


def test_redis_claim_refuses_nonempty_database_without_deleting_data():
    redis = _FakeRedis({"foreign": b"keep-me"})

    with pytest.raises(verifier.VerificationError):
        verifier._claim_redis_db(redis)

    assert redis.values == {"foreign": b"keep-me"}


def test_redis_release_deletes_only_owned_user_keys_and_preserves_foreign_data():
    redis = _FakeRedis()
    owner = verifier._claim_redis_db(redis)
    redis.values.update(
        {
            "rl:route-book:u:7": b"1",
            "route_snap_receipt_quota:v1:7:1": b"quota",
            "route_snap_receipt:v1:owned": json.dumps({"current_user_id": 7}).encode(),
            "route_snap_receipt:v1:foreign": json.dumps({"current_user_id": 8}).encode(),
        }
    )

    with pytest.raises(verifier.VerificationError):
        verifier._release_redis_db(redis, owner, 7)

    assert redis.values == {
        "route_snap_receipt:v1:foreign": json.dumps({"current_user_id": 8}).encode()
    }


def _write_route_fixture(tmp_path, *, sha256: str | None = None, second_part_start_m: float = 100.0):
    source = tmp_path / "source-profile.csv"
    source.write_text("chainage_m,elevation_m\n0,700\n300,900\n", encoding="utf-8")
    source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    fixture = {
        "schema": verifier.ROUTE_FIXTURE_SCHEMA,
        "sample_id": "fixture-sample-001",
        "purpose": "冻结三段腾讯路线证据，不读取高程答案选锚点",
        "source_profile_csv": source.name,
        "source_profile_sha256": sha256 or source_sha256,
        "target_start_m": 0,
        "target_end_m": 300,
        "coordinate_system": "gcj02",
        "anchor_policy": {
            "source": "linear interpolation on frozen WGS84 chainage, then WGS84 to GCJ02",
            "spacing_m": 100,
            "answers_used": False,
            "revision": 0,
        },
        "parts": [
            {
                "anchor_chainages_m": [0, 100],
                "points_gcj02": [[112.0, 37.0], [112.1, 37.1]],
            },
            {
                "anchor_chainages_m": [second_part_start_m, 200],
                "points_gcj02": [[112.1, 37.1], [112.2, 37.2]],
            },
            {
                "anchor_chainages_m": [200, 300],
                "points_gcj02": [[112.2, 37.2], [112.3, 37.3]],
            },
        ],
        "hard_boundaries": [
            "最终必须 coverage_complete=true、geometry_exact=true、route_line_hash=line_hash",
            "artifact 不得携带常数 DEM 结果",
        ],
    }
    fixture_path = tmp_path / "route-fixture.json"
    fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
    return fixture_path, fixture


def test_route_fixture_strictly_validates_source_sha_parts_and_anchor_chainages(tmp_path, monkeypatch):
    monkeypatch.setattr(verifier, "ROOT", tmp_path)
    fixture_path, fixture = _write_route_fixture(tmp_path)

    loaded = verifier._load_route_fixture(fixture_path)

    assert loaded["sample_id"] == fixture["sample_id"]
    assert loaded["source_profile_csv"] == "source-profile.csv"
    assert len(loaded["parts"]) == 3
    assert loaded["parts"][1]["anchor_chainages_m"] == [100.0, 200.0]
    assert loaded["anchor_policy"]["answers_used"] is False
    assert loaded["hard_boundaries"] == fixture["hard_boundaries"]


@pytest.mark.parametrize("failure", ["bad_hash", "bad_chainage"])
def test_route_fixture_rejects_bad_source_hash_or_disconnected_chainage(tmp_path, monkeypatch, failure):
    monkeypatch.setattr(verifier, "ROOT", tmp_path)
    if failure == "bad_hash":
        fixture_path, _fixture = _write_route_fixture(tmp_path, sha256="0" * 64)
    else:
        fixture_path, _fixture = _write_route_fixture(tmp_path, second_part_start_m=101)

    with pytest.raises(verifier.VerificationError):
        verifier._load_route_fixture(fixture_path)


def test_route_fixture_rejects_anchor_policy_that_used_answers(tmp_path, monkeypatch):
    monkeypatch.setattr(verifier, "ROOT", tmp_path)
    fixture_path, fixture = _write_route_fixture(tmp_path)
    fixture["anchor_policy"]["answers_used"] = True
    fixture_path.write_text(json.dumps(fixture), encoding="utf-8")

    with pytest.raises(verifier.VerificationError):
        verifier._load_route_fixture(fixture_path)


def test_route_fixture_rejects_revision_after_r2(tmp_path, monkeypatch):
    monkeypatch.setattr(verifier, "ROOT", tmp_path)
    fixture_path, fixture = _write_route_fixture(tmp_path)
    fixture["anchor_policy"]["revision"] = 3
    fixture_path.write_text(json.dumps(fixture), encoding="utf-8")

    with pytest.raises(verifier.VerificationError, match="只允许 0、1、2"):
        verifier._load_route_fixture(fixture_path)


def test_anchor_retention_accepts_ordered_rdp_subsequence_and_exposes_dropped_chainage():
    part = {
        "anchor_chainages_m": [90000.0, 95000.0, 100000.0, 105000.0],
        "points_gcj02": [
            [118.69, 29.48],
            [118.73, 29.51],
            [118.78, 29.52],
            [118.81, 29.55],
        ],
    }

    summary = verifier._anchor_retention_summary(
        part,
        [part["points_gcj02"][0], part["points_gcj02"][2], part["points_gcj02"][3]],
        part_index=0,
    )

    assert summary == {
        "input_anchor_count": 4,
        "retained_anchor_count": 3,
        "input_anchor_chainages_m": [90000.0, 95000.0, 100000.0, 105000.0],
        "retained_anchor_chainages_m": [90000.0, 100000.0, 105000.0],
        "dropped_anchor_chainages_m": [95000.0],
    }


@pytest.mark.parametrize(
    "returned",
    [
        [[118.73, 29.51], [118.81, 29.55]],
        [[118.69, 29.48], [119.0, 30.0], [118.81, 29.55]],
        [[118.69, 29.48], [118.78, 29.52]],
    ],
)
def test_anchor_retention_rejects_missing_endpoints_or_non_input_anchor(returned):
    part = {
        "anchor_chainages_m": [90000.0, 95000.0, 100000.0, 105000.0],
        "points_gcj02": [
            [118.69, 29.48],
            [118.73, 29.51],
            [118.78, 29.52],
            [118.81, 29.55],
        ],
    }

    with pytest.raises(verifier.VerificationError):
        verifier._anchor_retention_summary(part, returned, part_index=0)


def test_artifact_recursively_drops_identity_receipt_and_signed_request_fields():
    tainted = {
        "schema": verifier.ROUTE_ARTIFACT_SCHEMA,
        "request_id": "provider-id",
        "nested": {
            "routing_receipt": "opaque-secret",
            "current_user_id": 7,
            "openid": "private-openid",
            "key": "map-key",
            "sk": "map-sk",
            "sig": "signature",
            "url": "https://apis.map.qq.com/ws?key=secret",
            "road_name": "东方红隧道",
        },
        "items": [{"request_ids": ["provider-id"], "chainage_start_m": 1.0}],
    }

    safe = verifier._strip_artifact_secrets(tainted)

    serialized = json.dumps(safe, ensure_ascii=False)
    for marker in (
        "request_id",
        "request_ids",
        "receipt",
        "current_user_id",
        "openid",
        "map-key",
        "map-sk",
        "signature",
        "apis.map.qq.com",
    ):
        assert marker not in serialized
    assert safe["nested"]["road_name"] == "东方红隧道"
    assert safe["items"][0]["chainage_start_m"] == 1.0
    verifier._assert_artifact_safe(safe)


def test_artifact_rejects_constant_dem_elevation_payload():
    with pytest.raises(verifier.VerificationError):
        verifier._assert_artifact_safe(
            {
                "schema": verifier.ROUTE_ARTIFACT_SCHEMA,
                "elevation": {"profile_points": [700.0, 700.0]},
            }
        )


def test_safe_routing_artifact_keeps_structure_chainage_but_not_request_ids():
    routing = {
        "schema": "route_routing_evidence_v1",
        "provider": "tencent",
        "profile": "bicycling",
        "source": "manual_draw_snap_receipts",
        "route_line_hash": "line-hash",
        "provider_segment_count": 1,
        "coverage_complete": True,
        "covered_distance_m": 100.0,
        "route_distance_m": 100.0,
        "coverage_ratio": 1.0,
        "geometry_exact": True,
        "request_ids": ["secret-request"],
        "segments": [
            {
                "provider": "tencent",
                "profile": "bicycling",
                "route_point_start": 0,
                "route_point_end": 2,
                "route_chainage_start_m": 0.0,
                "route_chainage_end_m": 100.0,
                "request_id": "secret-request",
                "provider_calls": [
                    {
                        "call_index": 0,
                        "request_id": "secret-request",
                        "route_point_start": 0,
                        "route_point_end": 2,
                        "route_chainage_start_m": 0.0,
                        "route_chainage_end_m": 100.0,
                    }
                ],
                "unverified_join_gaps": [],
            }
        ],
        "steps": [
            {
                "segment_index": 0,
                "road_name": "东方红隧道",
                "route_point_start": 0,
                "route_point_end": 2,
                "chainage_start_m": 0.0,
                "chainage_end_m": 100.0,
                "request_id": "secret-request",
            }
        ],
    }

    safe = verifier._safe_routing_artifact(routing)

    assert safe["segments"][0]["provider_calls"][0]["route_chainage_end_m"] == 100.0
    assert safe["steps"][0]["road_name"] == "东方红隧道"
    assert "request_ids" not in safe
    assert "request_id" not in safe["segments"][0]
    assert "request_id" not in safe["steps"][0]


@pytest.mark.parametrize("field", ["coverage_complete", "geometry_exact"])
def test_saved_route_integrity_fails_closed_when_routing_is_not_exact(field):
    line_hash = "a" * 64
    routing = {
        "provider_segment_count": 3,
        "coverage_complete": True,
        "geometry_exact": True,
        "route_line_hash": line_hash,
        "segments": [{}, {}, {}],
    }
    routing[field] = False

    with pytest.raises(verifier.VerificationError):
        verifier._require_saved_route_integrity(
            routing,
            expected_part_count=3,
            line_hash=line_hash,
        )


def test_atomic_artifact_write_never_overwrites_existing_file(tmp_path):
    artifact_path = tmp_path / "artifact.json"
    first = {"schema": verifier.ROUTE_ARTIFACT_SCHEMA, "sample_id": "first"}
    second = {"schema": verifier.ROUTE_ARTIFACT_SCHEMA, "sample_id": "second"}

    verifier._atomic_write_json_new(artifact_path, first)
    original_bytes = artifact_path.read_bytes()

    with pytest.raises(verifier.VerificationError):
        verifier._atomic_write_json_new(artifact_path, second)

    assert artifact_path.read_bytes() == original_bytes
    assert json.loads(original_bytes)["sample_id"] == "first"


def test_main_without_optional_fixture_preserves_default_run_output(monkeypatch, capsys):
    expected = {
        "status": "pass",
        "scope": "tencent_place_direction_receipt_tcp_http_postgis",
        "elevation_query": "stubbed_constant_for_isolation",
    }
    monkeypatch.setattr(verifier, "run", lambda: dict(expected))

    exit_code = verifier.main([])

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == expected


def test_main_writes_artifact_only_after_fixture_run_returns(monkeypatch, tmp_path, capsys):
    fixture_path = tmp_path / "fixture.json"
    artifact_path = tmp_path / "artifact.json"
    events = []
    fixture = {"sample_id": "sample"}
    artifact = {"schema": verifier.ROUTE_ARTIFACT_SCHEMA, "sample_id": "sample"}
    original_atomic_write = verifier._atomic_write_json_new

    monkeypatch.setattr(verifier, "_load_route_fixture", lambda _path: fixture)

    def fake_run(received_fixture):
        assert received_fixture is fixture
        events.append("run_returned")
        return {"status": "pass", "_saved_routeversion_artifact": artifact}

    def recording_atomic_write(path, payload):
        events.append("artifact_write")
        original_atomic_write(path, payload)

    monkeypatch.setattr(verifier, "run", fake_run)
    monkeypatch.setattr(verifier, "_atomic_write_json_new", recording_atomic_write)

    exit_code = verifier.main(
        ["--route-fixture", str(fixture_path), "--artifact-out", str(artifact_path)]
    )

    assert exit_code == 0
    assert events == ["run_returned", "artifact_write"]
    assert json.loads(artifact_path.read_text(encoding="utf-8")) == artifact
    assert json.loads(capsys.readouterr().out)["saved_routeversion_artifact"]["written"] is True
