from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.route_cognition.transit_paths import canonical_sha256
from scripts.analyze_route_choice_set import index_run_files, main, replay_route_choice_set


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_generic_cli_replays_a_region_without_region_specific_flags(
    tmp_path: Path,
) -> None:
    source = {"observations": []}
    source["slice_sha256"] = canonical_sha256(source)
    selection = {
        "source_slice_sha256": source["slice_sha256"],
        "included_bindings": [],
        "included_count": 0,
        "included_binding_sha256": canonical_sha256([]),
    }
    selection["snapshot_sha256"] = canonical_sha256(selection)
    choice = {
        "choice_set_key": "new-region-holdout",
        "source_slice_sha256": source["slice_sha256"],
        "selection_snapshot_sha256": selection["snapshot_sha256"],
        "heat_snapshot_cohort": "same-cohort",
        "candidates": [],
    }
    paths = {
        "source": tmp_path / "source.json",
        "selection": tmp_path / "selection.json",
        "choice": tmp_path / "choice.json",
        "output": tmp_path / "output.json",
    }
    _write(paths["source"], source)
    _write(paths["selection"], selection)
    _write(paths["choice"], choice)

    assert main(
        [
            "--choice-spec",
            str(paths["choice"]),
            "--source-slice",
            str(paths["source"]),
            "--selection-snapshot",
            str(paths["selection"]),
            "--output",
            str(paths["output"]),
        ]
    ) == 0
    result = json.loads(paths["output"].read_text(encoding="utf-8"))
    assert result["choice_set_key"] == "new-region-holdout"
    assert result["candidates"] == []
    assert result["database_write_count"] == 0
    assert result["network_request_count"] == 0


def test_generic_cli_rejects_duplicate_run_keys(tmp_path: Path) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    _write(first, {"module_key": "same"})
    _write(second, {"module_key": "same"})

    with pytest.raises(ValueError, match="duplicate mountain module key"):
        index_run_files(
            [first, second], key_field="module_key", label="mountain module"
        )


def test_generic_replay_ranks_only_declared_scope_and_intent(monkeypatch) -> None:
    assembled = {
        "candidates": [
            {
                "candidate_id": "a",
                "comparison_scope": "short",
                "hard_failure_codes": [],
                "heat_vector": {
                    "evidence_coverage": 1.0,
                    "conditional_support_lower_bound": 2.0,
                    "uncertainty": 0.0,
                    "repeat_proxy": 2.0,
                    "intent_proxy": 1.0,
                    "projection_quality_coverage": 1.0,
                },
            },
            {
                "candidate_id": "b",
                "comparison_scope": "short",
                "hard_failure_codes": [],
                "heat_vector": {
                    "evidence_coverage": 0.5,
                    "conditional_support_lower_bound": 1.0,
                    "uncertainty": 0.0,
                    "repeat_proxy": 1.0,
                    "intent_proxy": 1.0,
                    "projection_quality_coverage": 0.5,
                },
            },
        ],
        "ranking_status": "not_ranked_across_distinct_rider_jobs",
        "result_sha256": "old",
    }
    monkeypatch.setattr(
        "scripts.analyze_route_choice_set.assemble_choice_set",
        lambda *args, **kwargs: assembled,
    )
    spec = {
        "candidates": [
            {"candidate_id": "a", "rider_intent": "popular_reliable"},
            {"candidate_id": "b", "rider_intent": "popular_reliable"},
        ]
    }

    result = replay_route_choice_set(
        choice_spec=spec,
        source_slice={},
        selection_snapshot={},
        module_runs={},
        transit_runs={},
    )

    assert result["ranking_status"] == "ranked_within_same_scope_and_rider_intent"
    assert result["ranking_groups"][0]["ranked_candidate_ids"] == ["a"]
    assert result["result_sha256"] != "old"
