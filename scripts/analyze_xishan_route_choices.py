#!/usr/bin/env python3
"""Compatibility CLI for the frozen four-choice Xishan replay."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.analyze_route_choice_set import (
    index_run_files,
    read_json,
    replay_route_choice_set,
    result_summary,
    write_json_atomic,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--choice-spec", type=Path, required=True)
    parser.add_argument("--source-slice", type=Path, required=True)
    parser.add_argument("--selection-snapshot", type=Path, required=True)
    parser.add_argument("--hengling-module-run", type=Path, required=True)
    parser.add_argument("--hengling-taohuagou-transit-run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = replay_route_choice_set(
        choice_spec=read_json(args.choice_spec),
        source_slice=read_json(args.source_slice),
        selection_snapshot=read_json(args.selection_snapshot),
        module_runs=index_run_files(
            [args.hengling_module_run],
            key_field="module_key",
            label="mountain module",
        ),
        transit_runs=index_run_files(
            [args.hengling_taohuagou_transit_run],
            key_field="transit_key",
            label="transit",
        ),
    )
    write_json_atomic(args.output, result)
    print(json.dumps(result_summary(result), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
