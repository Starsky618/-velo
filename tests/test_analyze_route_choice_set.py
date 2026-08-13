from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.route_cognition.transit_paths import canonical_sha256
from scripts.analyze_route_choice_set import index_run_files, main


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
