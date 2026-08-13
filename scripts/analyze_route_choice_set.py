#!/usr/bin/env python3
"""Replay one region's hard-data route choices through the generic harness."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.route_cognition.route_pattern_assembly import assemble_choice_set
from app.route_cognition.route_heat import rank_heat_candidates
from app.route_cognition.transit_paths import canonical_sha256


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return payload


def index_run_files(
    paths: Sequence[Path], *, key_field: str, label: str
) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for path in paths:
        payload = read_json(path)
        key = payload.get(key_field)
        if not isinstance(key, str) or not key:
            raise ValueError(f"{path} is missing {label} key {key_field}")
        if key in indexed:
            raise ValueError(f"duplicate {label} key: {key}")
        indexed[key] = payload
    return indexed


def replay_route_choice_set(
    *,
    choice_spec: dict[str, Any],
    source_slice: dict[str, Any],
    selection_snapshot: dict[str, Any],
    module_runs: dict[str, dict[str, Any]],
    transit_runs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    result = assemble_choice_set(
        choice_spec,
        source_slice=source_slice,
        selection_snapshot=selection_snapshot,
        module_runs=module_runs,
        transit_runs=transit_runs,
    )
    candidate_specs = {
        str(item["candidate_id"]): item for item in choice_spec["candidates"]
    }
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for candidate in result["candidates"]:
        definition = candidate_specs[str(candidate["candidate_id"])]
        intent = definition.get("rider_intent")
        if not isinstance(intent, str) or not intent:
            continue
        key = (str(candidate["comparison_scope"]), intent)
        groups.setdefault(key, []).append(candidate)
    if groups:
        result["ranking_groups"] = []
        for (scope, intent), candidates in sorted(groups.items()):
            ranking = rank_heat_candidates(candidates)
            result["ranking_groups"].append(
                {"comparison_scope": scope, "rider_intent": intent, **ranking}
            )
        result["ranking_status"] = "ranked_within_same_scope_and_rider_intent"
        result["result_sha256"] = canonical_sha256(
            {key: value for key, value in result.items() if key != "result_sha256"}
        )
    return result


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def result_summary(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "complete",
        "result_sha256": result["result_sha256"],
        "candidates": [
            {
                "candidate_id": item["candidate_id"],
                "assembly_status": item["assembly_status"],
                "heat_vector": item.get("heat_vector"),
            }
            for item in result["candidates"]
        ],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--choice-spec", type=Path, required=True)
    parser.add_argument("--source-slice", type=Path, required=True)
    parser.add_argument("--selection-snapshot", type=Path, required=True)
    parser.add_argument("--module-run", type=Path, action="append", default=[])
    parser.add_argument("--transit-run", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = replay_route_choice_set(
        choice_spec=read_json(args.choice_spec),
        source_slice=read_json(args.source_slice),
        selection_snapshot=read_json(args.selection_snapshot),
        module_runs=index_run_files(
            args.module_run, key_field="module_key", label="mountain module"
        ),
        transit_runs=index_run_files(
            args.transit_run, key_field="transit_key", label="transit"
        ),
    )
    write_json_atomic(args.output, result)
    print(json.dumps(result_summary(result), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
