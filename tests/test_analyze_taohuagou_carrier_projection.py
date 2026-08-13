from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

from scripts.analyze_taohuagou_carrier_projection import (
    _load_inputs,
    build_run,
    write_artifacts,
)
import scripts.analyze_taohuagou_carrier_projection as runner


REPO_ROOT = Path(__file__).resolve().parents[1]
CARRIER_PATH = REPO_ROOT / "data/research/taohuagou_carrier_candidate_v1.json"
SLICE_PATH = REPO_ROOT / "data/research/taohuagou_projection_slice_v1.json"


def test_real_taohuagou_slice_is_deterministic_and_keeps_shadow_boundary():
    carrier, slice_input = _load_inputs(CARRIER_PATH, SLICE_PATH)

    first = build_run(carrier, slice_input)
    replay = build_run(carrier, slice_input)

    assert first == replay
    assert first["evidence_status"] == "research_shadow"
    assert first["observation_count"] == 7
    assert first["database_write_count"] == 0
    assert first["network_request_count"] == 0
    assert sum(first["projection_status_counts"].values()) == 7
    assert first["accepted_projection_count"] + first[
        "abstained_projection_count"
    ] == 7
    assert "唯一骑手" in first["boundary"]
    assert all(
        projection["result"]["evidence_status"] == "research_shadow"
        for projection in first["projections"]
    )
    observed = [
        cell
        for cell in first["directed_evidence"]["cells"]
        if cell["support_state"] == "observed"
    ]
    unobserved = [
        cell
        for cell in first["directed_evidence"]["cells"]
        if cell["support_state"] == "unobserved"
    ]
    assert observed
    assert unobserved
    assert all(
        cell["reach_union_lower_bound"] <= cell["reach_union_upper_bound"]
        for cell in observed
    )
    assert all(
        cell["reach_union_lower_bound"] is None
        and cell["reach_union_upper_bound"] is None
        for cell in unobserved
    )
    assert first["directed_evidence_support_state_counts"] == {
        "observed": len(observed),
        "unobserved": len(unobserved),
    }
    assert first["parameter_promotion_status"] == "research_probe_unpromoted"
    assert first["evidence_eligibility"] == "shadow_only_not_route_ranking_input"
    assert set(first["projection_direction_counts"]) <= {
        "forward",
        "reverse",
        "indeterminate",
    }


def test_written_artifact_hashes_bind_exact_bytes(tmp_path):
    carrier, slice_input = _load_inputs(CARRIER_PATH, SLICE_PATH)
    result = build_run(carrier, slice_input)

    paths = write_artifacts(
        tmp_path,
        result=result,
        carrier_path=CARRIER_PATH,
        slice_path=SLICE_PATH,
    )
    manifest = json.loads(Path(paths["manifest"]).read_text(encoding="utf-8"))
    current = json.loads(Path(paths["current"]).read_text(encoding="utf-8"))

    assert manifest["projection_artifact_sha256"] == hashlib.sha256(
        Path(paths["projections"]).read_bytes()
    ).hexdigest()
    assert manifest["evidence_artifact_sha256"] == hashlib.sha256(
        Path(paths["directed_evidence"]).read_bytes()
    ).hexdigest()
    assert manifest["carrier_input_sha256"] == hashlib.sha256(
        CARRIER_PATH.read_bytes()
    ).hexdigest()
    assert manifest["slice_input_sha256"] == hashlib.sha256(
        SLICE_PATH.read_bytes()
    ).hexdigest()
    assert current["run_sha256"] == result["run_sha256"]
    assert Path(paths["manifest"]).parent.name == current["generation_sha256"]
    assert Path(paths["manifest"]).parent.parent.name == "generations"


def test_generation_write_failure_does_not_change_current_pointer(
    tmp_path, monkeypatch
):
    carrier, slice_input = _load_inputs(CARRIER_PATH, SLICE_PATH)
    result = build_run(carrier, slice_input)
    baseline = write_artifacts(
        tmp_path,
        result=result,
        carrier_path=CARRIER_PATH,
        slice_path=SLICE_PATH,
    )
    current_before = Path(baseline["current"]).read_bytes()
    original_write = runner._write_generation_file
    call_count = 0

    def fail_second_file(path, content):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise OSError("injected generation write failure")
        original_write(path, content)

    changed = {**result, "schema_version": "failure-injection-generation"}
    changed.pop("run_sha256")
    changed["run_sha256"] = runner._canonical_sha256(changed)
    monkeypatch.setattr(runner, "_write_generation_file", fail_second_file)

    try:
        write_artifacts(
            tmp_path,
            result=changed,
            carrier_path=CARRIER_PATH,
            slice_path=SLICE_PATH,
        )
    except OSError as exc:
        assert "injected" in str(exc)
    else:
        raise AssertionError("failure injection did not interrupt generation")

    assert Path(baseline["current"]).read_bytes() == current_before
    assert not list((tmp_path / "generations").glob(".*"))


def test_offline_runner_import_does_not_activate_database_or_dem_clients():
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "import scripts.analyze_taohuagou_carrier_projection; "
                "blocked={'app.database','app.elevation.dem_client','httpx','scipy'}; "
                "loaded=sorted(blocked.intersection(sys.modules)); "
                "assert not loaded, loaded"
            ),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )

    assert probe.returncode == 0, probe.stderr
