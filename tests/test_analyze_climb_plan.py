"""离线 ClimbPlan 重放脚本合同。"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from scripts.analyze_climb_plan import analyze


ROOT = Path(__file__).resolve().parents[1]


def _payload():
    profile = [[distance, 600 + distance * 0.06] for distance in range(0, 5_001, 100)]
    return {
        "schema_version": "climb_plan_input_v1",
        "route_key": "synthetic-steady-cat3",
        "geometry_hash": hashlib.sha256(b"synthetic-steady-cat3").hexdigest(),
        "traversal": "forward",
        "source": {
            "method": "authorized_barometric_profile_v1",
            "horizontal_resolution_m": 5,
            "residual_mad_m": 2,
        },
        "profile": profile,
        "smoothing_variants": {"80m": profile, "150m": profile},
        "rider_profile": {
            "ftp_w": 280,
            "rider_mass_kg": 70,
            "bike_type": "road",
            "power_curve_w": {"300": 340, "1200": 290, "3600": 255},
        },
    }


def test_analyze_climb_plan_builds_hash_chained_route_and_rider_result():
    result = analyze(_payload())
    assert result["schema_version"] == "climb_plan_result_v1"
    assert result["climb_plan"]["composition"]["sequence_label"] == "Cat 3"
    assert result["climb_plan"]["source"]["residual_mad_m"] == 2
    assert result["climb_plan"]["climbs"][0]["shape_tags"] == ["steady"]
    assert result["rider_plan"]["basis"] == "ftp_weight_power_curve"
    result_hash = result.pop("result_sha256")
    canonical = json.dumps(
        result,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert result_hash == hashlib.sha256(canonical).hexdigest()


def test_analyze_climb_plan_cli_writes_replayable_json(tmp_path):
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "result.json"
    input_path.write_text(json.dumps(_payload()), encoding="utf-8")
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "analyze_climb_plan.py"),
            str(input_path),
            "--output",
            str(output_path),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(output_path.read_text(encoding="utf-8")) == analyze(_payload())


def test_repository_late_wall_control_artifact_replays_exactly():
    artifact_dir = ROOT / "data" / "research" / "climb_plans"
    payload = json.loads(
        (artifact_dir / "synthetic_aoshen_late_wall_control_v1_input.json").read_text(
            encoding="utf-8"
        )
    )
    frozen = json.loads(
        (artifact_dir / "synthetic_aoshen_late_wall_control_v1_result.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["evidence_status"] == "synthetic_control_not_real_elevation_profile"
    assert analyze(payload) == frozen
    climb = frozen["climb_plan"]["climbs"][0]
    assert climb["category"] == "2"
    assert climb["shape_tags"] == ["late_wall"]
    assert climb["category_status"] == "candidate"
