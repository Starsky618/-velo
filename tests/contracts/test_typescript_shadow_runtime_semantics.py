import json
import subprocess
from pathlib import Path

import pytest

from tests.contracts.test_agent_v0_session_run_map_action_contracts import (
    assert_run_semantics,
)
from tests.contracts.test_agent_v0_tool_contracts import (
    assert_attempt_chain,
)


ROOT = Path(__file__).resolve().parents[2]


def _emit_trace(scenario: str = "normal") -> dict:
    completed = subprocess.run(
        [
            "node",
            "--experimental-strip-types",
            "agent_runtime/consumer/cli/emit-runtime-trace.ts",
            scenario,
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_typescript_shadow_passes_existing_agent_run_semantics():
    trace = _emit_trace()
    assert_run_semantics(trace["agent_run"])


def test_typescript_shadow_cross_artifact_identity_is_consistent():
    trace = _emit_trace()
    run = trace["agent_run"]
    manifests = trace["context_manifests"]
    actions = trace["actions"]
    calls = trace["tool_calls"]
    results = trace["tool_results"]

    assert run["context_manifest_refs"] == [item["manifest_id"] for item in manifests]
    assert run["action_proposal_refs"] == [item["action_id"] for item in actions]
    assert run["tool_call_refs"] == [item["tool_call_id"] for item in calls]
    assert run["observation_refs"] == [item["observation_id"] for item in results]
    assert [item["model_turn_index"] for item in actions] == list(range(1, len(actions) + 1))

    presentation_manifest = manifests[-1]
    presentation = actions[-1]
    assert presentation["action_type"] == "present_valid_candidates"
    assert presentation_manifest["plan_revision_refs"] == [
        item["plan_revision_ref"] for item in presentation["payload"]["candidates"]
    ]
    assert {
        "tool.observation.candidate_plan_set",
        "plan.candidate_summaries",
        "plan.validation_summaries",
    } <= set(presentation_manifest["included_sections"])

    hashes_by_packet = {}
    packet_refs = [
        ref
        for manifest in manifests
        for ref in manifest["source_packet_refs"]
    ] + [
        ref
        for result in results
        for ref in result["result_refs"]
        if ref.get("packet_type")
    ]
    for ref in packet_refs:
        identity = (ref["packet_type"], ref["packet_id"], ref["source_revision"])
        hashes_by_packet.setdefault(identity, set()).add(ref["content_hash"])
    assert all(len(hashes) == 1 for hashes in hashes_by_packet.values())


@pytest.mark.parametrize("scenario", ["model-timeout", "tool-timeout", "commit-timeout"])
def test_typescript_shadow_failure_traces_pass_existing_agent_run_semantics(scenario):
    trace = _emit_trace(scenario)
    assert_run_semantics(trace["agent_run"])
    assert trace["agent_run"]["stop_reason"] == "budget_exceeded"
    assert trace["agent_run"]["session_commit"]["commit_status"] == "not_attempted"
    assert len(trace["actions"]) == trace["agent_run"]["budget"]["consumed"]["model_turns"]


def test_typescript_shadow_tool_timeout_has_one_terminal_observation():
    trace = _emit_trace("tool-timeout")
    assert len(trace["tool_calls"]) == len(trace["tool_results"]) == 1
    result = trace["tool_results"][0]
    assert result["result_status"] == "timed_out"
    assert result["result_finality"] == "TERMINAL"
    assert result["domain_reason_code"] == "RUN_DEADLINE_EXCEEDED"
    registry = json.loads((ROOT / "contracts/agent_v0/tool_registry.v0.json").read_text())
    assert_attempt_chain(trace["tool_calls"][0], trace["tool_results"], registry, trace["agent_run"])


def test_typescript_shadow_preserves_commit_receipt_after_irreversible_deadline_crossing():
    trace = _emit_trace("commit-after-deadline")
    assert_run_semantics(trace["agent_run"])
    assert trace["agent_run"]["stop_reason"] == "budget_exceeded"
    assert trace["agent_run"]["session_commit"] == {
        "commit_status": "committed",
        "expected_base_revision": 1,
        "committed_revision": 2,
    }


def test_typescript_shadow_uses_formal_reconciliation_status():
    trace = _emit_trace("commit-reconciliation")
    assert_run_semantics(trace["agent_run"])
    assert trace["agent_run"]["stop_reason"] == "deterministic_error"
    assert trace["agent_run"]["session_commit"] == {
        "commit_status": "reconciliation_required",
        "expected_base_revision": 1,
    }
