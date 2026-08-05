import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_DIR = ROOT / "contracts" / "agent_v0"
VALID_FIXTURES = CONTRACT_DIR / "fixtures" / "valid"
INVALID_FIXTURES = CONTRACT_DIR / "fixtures" / "invalid"

SCHEMA_FILES = {
    "common": "common.schema.json",
    "context_manifest": "context_manifest.schema.json",
    "session_state": "session_state.schema.json",
    "agent_run": "agent_run.schema.json",
    "map_event": "map_event.schema.json",
    "map_action": "map_action.schema.json",
    "agent_action": "agent_action.schema.json",
}

A2_2_SCHEMA_FILES = {
    name: filename
    for name, filename in SCHEMA_FILES.items()
    if name not in {"common", "context_manifest"}
}

EXPECTED_SCHEMA_IDS = {
    name: f"https://schemas.velo.invalid/agent_v0/{filename}"
    for name, filename in A2_2_SCHEMA_FILES.items()
}

VALID_FIXTURE_SCHEMAS = {
    "agent_run_created.json": "agent_run",
    "session_state_clarification_r3.json": "session_state",
    "agent_action_ask_clarification.json": "agent_action",
    "agent_run_clarification_paused.json": "agent_run",
    "session_state_clarification_r4.json": "session_state",
    "agent_run_clarification_resume.json": "agent_run",
    "agent_action_resume_clarification.json": "agent_action",
    "session_state_candidates_before.json": "session_state",
    "map_action_fit_bounds.json": "map_action",
    "session_state_fit_bounds_r2.json": "session_state",
    "map_action_show_candidate_set.json": "map_action",
    "agent_action_propose_tool_call.json": "agent_action",
    "agent_action_present_candidates.json": "agent_action",
    "agent_run_candidate_completed.json": "agent_run",
    "session_state_candidates_presented.json": "session_state",
    "map_event_plan_confirmed.json": "map_event",
    "session_state_plan_selected.json": "session_state",
}

INVALID_FIXTURE_SCHEMAS = {
    "session_state_selected_plan_not_candidate.json": "session_state",
    "agent_run_budget_over_limit.json": "agent_run",
    "map_event_raw_coordinates.json": "map_event",
    "map_action_unknown_frontend_command.json": "map_action",
    "agent_action_direct_external_effect.json": "agent_action",
}

FORBIDDEN_TOOL_NAMES = {
    "raw_tencent_api",
    "raw_provider",
    "raw_sql",
    "orm_write",
    "shell",
    "direct_gpx_generator",
    "publish_traversal",
    "accept_claim",
    "activate_dynamic_state",
    "world.publish",
}

FORBIDDEN_FIXTURE_KEYS = {
    "lat",
    "latitude",
    "lng",
    "lon",
    "longitude",
    "coordinates",
    "bbox",
    "raw_trackpoints",
    "raw_provider_payload",
    "tool_arguments",
    "approval_grant",
    "side_effect_ledger",
    "canonical_write",
    "export_artifact",
    "full_transcript",
    "runtime",
}

FORBIDDEN_METADATA_KEY_FRAGMENTS = {
    "approval",
    "coordinate",
    "effect",
    "fact",
    "lat",
    "lng",
    "lon",
    "payload",
    "provenance",
    "state",
    "status",
    "tool",
    "validation",
}


def load_json(path):
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture(scope="module")
def schemas():
    return {
        name: load_json(CONTRACT_DIR / filename)
        for name, filename in SCHEMA_FILES.items()
    }


@pytest.fixture(scope="module")
def local_registry(schemas):
    unexpected_retrievals = []

    def reject_external_retrieval(uri):
        unexpected_retrievals.append(uri)
        raise AssertionError(f"schema attempted non-local retrieval: {uri}")

    registry = Registry(retrieve=reject_external_retrieval)
    resources = [
        (schema["$id"], Resource.from_contents(schema))
        for schema in schemas.values()
    ]
    return registry.with_resources(resources), unexpected_retrievals


def validator_for(schema_name, schemas, local_registry):
    registry, _ = local_registry
    return Draft202012Validator(
        schemas[schema_name],
        registry=registry,
        format_checker=FormatChecker(),
    )


def validation_errors(schema_name, instance, schemas, local_registry):
    return sorted(
        validator_for(schema_name, schemas, local_registry).iter_errors(instance),
        key=lambda error: list(error.absolute_path),
    )


def walk_refs(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "$ref":
                yield child
            yield from walk_refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_refs(child)


def walk_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_keys(child)


def nested_error_messages(error):
    yield error.message
    for child in error.context:
        yield from nested_error_messages(child)


def parse_rfc3339(value):
    assert isinstance(value, str) and "T" in value
    normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    assert parsed.tzinfo is not None and parsed.utcoffset() is not None
    return parsed


def revision_key(revision_ref):
    object_ref = revision_ref["object_ref"]
    return (
        object_ref["object_id"],
        object_ref["object_type"],
        revision_ref["revision"],
        revision_ref.get("content_hash"),
    )


def candidate_key(candidate):
    return candidate["candidate_ref"], revision_key(candidate["plan_revision_ref"])


def assert_unique(items, field):
    values = [item[field] for item in items]
    assert len(values) == len(set(values)), f"duplicate {field} values"


def assert_environment(instance):
    expected_fixture_only = instance["environment"] == "test"
    assert instance["fixture_only"] is expected_fixture_only
    for key in instance["metadata"]:
        normalized = key.lower().replace("_", "-")
        assert not any(
            fragment in normalized for fragment in FORBIDDEN_METADATA_KEY_FRAGMENTS
        ), key


def assert_cross_contract_environment(*instances, manifest=None):
    artifacts = [instance for instance in instances if instance is not None]
    assert artifacts
    for artifact in artifacts:
        assert_environment(artifact)
    environments = {artifact["environment"] for artifact in artifacts}
    fixture_flags = {artifact["fixture_only"] for artifact in artifacts}
    assert len(environments) == 1
    assert len(fixture_flags) == 1
    if manifest is not None:
        assert manifest["packet_environment"] == next(iter(environments))


def assert_display_target_exists(target, session):
    candidate_refs = {item["candidate_ref"] for item in session["candidate_plans"]}
    anchor_refs = {item["anchor_ref"] for item in session["map_state"]["anchors"]}
    world_refs = {item["object_id"] for item in session["focused_world_refs"]}
    warning_refs = set(session["map_state"]["presentation"]["warning_scope_refs"])
    if target["target_kind"] == "candidate_plan":
        assert target["target_ref"] in candidate_refs
    elif target["target_kind"] == "anchor":
        assert target["target_ref"] in anchor_refs
    elif target["target_kind"] == "world_object":
        assert target["target_ref"] in world_refs
    elif target["target_kind"] == "warning":
        assert target["target_ref"] in warning_refs
    elif target["target_kind"] == "plan_leg":
        assert session.get("focused_plan_leg", {}).get("leg_ref") == target["target_ref"]


def assert_session_semantics(session):
    assert_environment(session)
    created_at = parse_rfc3339(session["created_at"])
    updated_at = parse_rfc3339(session["updated_at"])
    assert created_at <= updated_at
    if "expires_at" in session:
        assert updated_at < parse_rfc3339(session["expires_at"])
    if session["status"] in {"expired", "cancelled"}:
        assert "pending_user_decision" not in session

    assert all(ref["object_type"] != "rider" for ref in session["focused_world_refs"])
    candidates = session["candidate_plans"]
    assert 0 <= len(candidates) <= 3
    assert_unique(candidates, "candidate_ref")
    assert_unique(candidates, "display_order")
    plan_revisions = [revision_key(item["plan_revision_ref"]) for item in candidates]
    assert len(plan_revisions) == len(set(plan_revisions)), "duplicate plan revision"
    candidate_map = {item["candidate_ref"]: item for item in candidates}
    for candidate in candidates:
        if (
            candidate["session_fit_status"] == "current"
            and candidate["presentation_state"] == "visible"
        ):
            assert "validation_result_ref" in candidate

    if "active_candidate_ref" in session:
        active = candidate_map[session["active_candidate_ref"]]
        assert active["session_fit_status"] == "current"
        assert active["presentation_state"] != "hidden"
        assert "validation_result_ref" in active

    if "selected_plan" in session:
        selected = session["selected_plan"]
        candidate = candidate_map[selected["candidate_ref"]]
        assert candidate["session_fit_status"] == "current"
        assert candidate["presentation_state"] != "hidden"
        assert "validation_result_ref" in candidate
        assert selected["selected_by_event_type"] == "plan_confirmed"
        assert revision_key(selected["plan_revision_ref"]) == revision_key(
            candidate["plan_revision_ref"]
        )

    if "focused_plan_leg" in session:
        assert revision_key(session["focused_plan_leg"]["plan_revision_ref"]) in {
            revision_key(item["plan_revision_ref"]) for item in candidates
        }

    anchors = session["map_state"]["anchors"]
    assert_unique(anchors, "anchor_ref")
    assert sum(item["anchor_role"] == "origin" for item in anchors) <= 1
    assert sum(item["anchor_role"] == "destination" for item in anchors) <= 1
    for anchor in anchors:
        assert anchor["location_handle"]["exact_coordinates_exposed"] is False

    selection = session["map_state"].get("elevation_selection")
    if selection:
        assert selection["from_fraction"] <= selection["to_fraction"]

    map_state = session["map_state"]
    available_bounds_refs = map_state["available_bounds_refs"]
    assert len(available_bounds_refs) == len(set(available_bounds_refs))
    viewport = map_state["viewport"]
    assert viewport["bounds_ref"] in available_bounds_refs
    if viewport["source_kind"] == "initial":
        assert session["session_revision"] == 1

    presentation = session["map_state"]["presentation"]
    visible_refs = set(presentation["visible_candidate_refs"])
    assert visible_refs <= set(candidate_map)
    for candidate_ref in visible_refs:
        candidate = candidate_map[candidate_ref]
        assert candidate["session_fit_status"] == "current"
        assert candidate["presentation_state"] == "visible"
        assert "validation_result_ref" in candidate
    for collection_name in ("highlighted_targets", "dimmed_targets"):
        for target in presentation[collection_name]:
            assert_display_target_exists(target, session)
    focused_refs = {
        (ref["object_id"], ref["object_type"]) for ref in session["focused_world_refs"]
    }
    for ref in presentation["shown_area_refs"]:
        assert ref["object_type"] == "cycling_area"
        assert (ref["object_id"], ref["object_type"]) in focused_refs

    assert_unique(session["assumptions"], "assumption_id")
    assert_unique(session["unknowns"], "unknown_id")


def assert_run_semantics(run):
    assert_environment(run)
    started_at = parse_rfc3339(run["started_at"])
    checkpoint_at = parse_rfc3339(run["last_checkpoint_at"])
    assert started_at <= checkpoint_at
    deadline_at = parse_rfc3339(run["budget"]["limits"]["wall_clock_deadline"])
    assert started_at < deadline_at
    if "ended_at" in run:
        assert checkpoint_at <= parse_rfc3339(run["ended_at"])

    limits = run["budget"]["limits"]
    consumed = run["budget"]["consumed"]
    pairs = (
        ("model_turns", "max_model_turns"),
        ("tool_calls", "max_tool_calls"),
        ("plan_generations", "max_plan_generations"),
        ("tokens", "token_limit"),
        ("cost_micros", "cost_limit_micros"),
    )
    for consumed_name, limit_name in pairs:
        if consumed_name in consumed or limit_name in limits:
            assert consumed_name in consumed and limit_name in limits
            assert consumed[consumed_name] <= limits[limit_name], consumed_name

    retry_counters = run["budget"]["tool_retry_counters"]
    assert_unique(retry_counters, "tool_name")
    assert all(
        item["retries"] <= limits["max_same_tool_retries"]
        for item in retry_counters
    )
    if run["trigger"]["trigger_type"] == "resume":
        assert len(run["action_proposal_refs"]) <= consumed["model_turns"]
    else:
        assert len(run["action_proposal_refs"]) == consumed["model_turns"]
    assert len(run["tool_call_refs"]) <= consumed["tool_calls"]
    assert len(run["context_manifest_refs"]) == consumed["model_turns"]

    commit = run["session_commit"]
    assert commit["expected_base_revision"] == run["base_session_revision"]
    if commit["commit_status"] == "committed":
        assert commit["committed_revision"] == run["base_session_revision"] + 1
    else:
        assert "committed_revision" not in commit
    if commit["commit_status"] in {"rejected_stale", "reconciliation_required"}:
        assert run.get("stop_reason") in {"deterministic_error", "cancelled"}
    if run.get("stop_reason") == "completed":
        assert commit["commit_status"] == "committed"

    status = run["run_status"]
    execution_ref_fields = (
        "context_manifest_refs",
        "action_proposal_refs",
        "tool_call_refs",
        "observation_refs",
    )
    if status == "created":
        assert run["current_step"] == "receive_event"
        assert all(value == 0 for value in consumed.values())
        assert all(not run[field] for field in execution_ref_fields)
        assert not retry_counters
        assert commit["commit_status"] == "not_attempted"
        assert "stop_reason" not in run
        assert "pending_gate" not in run
        assert "ended_at" not in run
    if status == "running":
        assert commit["commit_status"] == "not_attempted"
        assert "stop_reason" not in run
        assert "pending_gate" not in run
        assert "ended_at" not in run
    if "pending_gate" in run:
        gate_at = parse_rfc3339(run["pending_gate"]["created_at"])
        assert started_at <= gate_at <= checkpoint_at

    if run.get("stop_reason") == "budget_exceeded":
        exhausted = any(
            consumed.get(consumed_name) == limits.get(limit_name)
            for consumed_name, limit_name in pairs
            if consumed_name in consumed and limit_name in limits
        )
        deadline_reached = checkpoint_at >= parse_rfc3339(limits["wall_clock_deadline"])
        assert exhausted or deadline_reached


def assert_resume_semantics(parent, child, current_session, child_action=None):
    assert_run_semantics(parent)
    assert_run_semantics(child)
    assert child["run_id"] != parent["run_id"]
    assert child["trigger"]["trigger_type"] == "resume"
    assert child["trigger"]["resumed_from_run_ref"] == parent["run_id"]
    assert child["session_id"] == parent["session_id"]
    assert child["run_lineage_ref"] == parent["run_lineage_ref"]
    assert child["base_session_revision"] == current_session["session_revision"]
    assert child["session_id"] == current_session["session_id"]
    if parent["session_commit"]["commit_status"] == "committed":
        committed_revision = parent["session_commit"]["committed_revision"]
        assert current_session["session_revision"] >= committed_revision
        assert child["base_session_revision"] >= committed_revision
    assert child["budget"]["limits"] == parent["budget"]["limits"]
    parent_consumed = parent["budget"]["consumed"]
    child_consumed = child["budget"]["consumed"]
    assert set(parent_consumed) <= set(child_consumed)
    for counter, value in parent_consumed.items():
        assert child_consumed[counter] >= value, counter
    parent_retries = {
        item["tool_name"]: item["retries"]
        for item in parent["budget"]["tool_retry_counters"]
    }
    child_retries = {
        item["tool_name"]: item["retries"]
        for item in child["budget"]["tool_retry_counters"]
    }
    assert set(parent_retries) <= set(child_retries)
    for tool_name, retries in parent_retries.items():
        assert child_retries[tool_name] >= retries
    if child_action is not None:
        assert child_action["run_id"] == child["run_id"]
        assert child_action["base_session_revision"] == child["base_session_revision"]
        assert_agent_action_semantics(child_action, child, current_session)
    assert (
        len(parent["action_proposal_refs"]) + len(child["action_proposal_refs"])
        == child["budget"]["consumed"]["model_turns"]
    )


def assert_event_semantics(event, session):
    assert_cross_contract_environment(event, session)
    assert event["session_id"] == session["session_id"]
    assert event["base_session_revision"] == session["session_revision"]
    assert parse_rfc3339(session["created_at"]) <= parse_rfc3339(event["occurred_at"])
    payload = event["payload"]
    candidates = {item["candidate_ref"]: item for item in session["candidate_plans"]}
    if event["event_type"] == "ride_object_selected":
        assert payload["object_ref"] == payload["revision_ref"]["object_ref"]
    if event["event_type"] in {"candidate_switched", "leg_selected", "plan_confirmed"}:
        candidate = candidates[payload["candidate_ref"]]
        assert candidate["session_fit_status"] == "current"
        assert candidate["presentation_state"] != "hidden"
        assert "validation_result_ref" in candidate
        assert revision_key(candidate["plan_revision_ref"]) == revision_key(
            payload["plan_revision_ref"]
        )
        if event["event_type"] == "plan_confirmed":
            assert "validation_result_ref" in candidate
    if event["event_type"] == "elevation_range_selected":
        assert payload["from_fraction"] <= payload["to_fraction"]
    if event["event_type"] == "viewport_changed":
        assert payload["bounds_ref"] in session["map_state"]["available_bounds_refs"]
    if event["event_type"] == "anchor_removed":
        anchors = {
            (item["anchor_ref"], item["anchor_role"])
            for item in session["map_state"]["anchors"]
        }
        assert (payload["anchor_ref"], payload["anchor_role"]) in anchors
    if event["event_type"] in {"origin_pinned", "destination_pinned"}:
        assert payload["anchor"]["source_event_ref"] == event["event_id"]
        if "replaces_anchor_ref" in payload:
            assert payload["replaces_anchor_ref"] in {
                item["anchor_ref"] for item in session["map_state"]["anchors"]
            }


def assert_map_action_batch(map_actions, session, parent_action=None, run=None):
    assert_cross_contract_environment(session, parent_action, run, *map_actions)
    assert [item["sequence"] for item in map_actions] == list(
        range(1, len(map_actions) + 1)
    )
    assert_unique(map_actions, "map_action_id")
    candidates = {item["candidate_ref"]: item for item in session["candidate_plans"]}
    for map_action in map_actions:
        assert_environment(map_action)
        assert map_action["reducer_required"] is True
        assert map_action["session_id"] == session["session_id"]
        assert map_action["base_session_revision"] == session["session_revision"]
        if parent_action:
            assert map_action["source_agent_action_ref"] == parent_action["action_id"]
            assert parse_rfc3339(parent_action["proposed_at"]) <= parse_rfc3339(
                map_action["issued_at"]
            )
        if run:
            assert parse_rfc3339(map_action["issued_at"]) <= parse_rfc3339(
                run["last_checkpoint_at"]
            )
        payload = map_action["payload"]
        if map_action["action_type"] == "fit_bounds":
            assert payload["bounds_ref"] in session["map_state"]["available_bounds_refs"]
        elif map_action["action_type"] == "show_area":
            assert payload["area_ref"] in session["focused_world_refs"]
        elif map_action["action_type"] == "highlight_object":
            assert payload["object_ref"] in session["focused_world_refs"]
        elif map_action["action_type"] == "show_candidate_set":
            displays = payload["candidates"]
            assert_unique(displays, "candidate_ref")
            assert_unique(displays, "display_order")
            plan_keys = [revision_key(item["plan_revision_ref"]) for item in displays]
            assert len(plan_keys) == len(set(plan_keys))
            for display in displays:
                candidate = candidates[display["candidate_ref"]]
                assert candidate["session_fit_status"] == "current"
                assert display["validation_result_ref"] == candidate["validation_result_ref"]
                assert revision_key(display["plan_revision_ref"]) == revision_key(
                    candidate["plan_revision_ref"]
                )
        elif map_action["action_type"] == "show_anchor":
            assert payload["anchor"] in session["map_state"]["anchors"]
        elif map_action["action_type"] == "highlight_plan_leg":
            focused_leg = session["focused_plan_leg"]
            assert payload["leg_ref"] == focused_leg["leg_ref"]
            assert revision_key(payload["plan_revision_ref"]) == revision_key(
                focused_leg["plan_revision_ref"]
            )
        elif map_action["action_type"] == "dim_objects":
            for target in payload["targets"]:
                assert_display_target_exists(target, session)
        elif map_action["action_type"] == "show_warning_scope":
            assert payload["warning_ref"] in session["map_state"]["presentation"][
                "warning_scope_refs"
            ]
            assert_display_target_exists(payload["target"], session)


def assert_agent_action_semantics(action, run, session, selection_event=None):
    assert_cross_contract_environment(session, run, action, *action["map_actions"])
    assert action["proposal_only"] is True
    assert action["run_id"] == run["run_id"]
    assert action["session_id"] == run["session_id"] == session["session_id"]
    assert action["base_session_revision"] == run["base_session_revision"]
    assert action["base_session_revision"] == session["session_revision"]
    assert action["model_turn_index"] <= run["budget"]["consumed"]["model_turns"]
    assert action["action_id"] in run["action_proposal_refs"]
    proposed_at = parse_rfc3339(action["proposed_at"])
    assert parse_rfc3339(run["started_at"]) <= proposed_at
    assert proposed_at <= parse_rfc3339(run["last_checkpoint_at"])
    if action["action_type"] == "ask_clarifying_question" and "choices" in action["payload"]:
        assert_unique(action["payload"]["choices"], "choice_id")
    if action["action_type"] == "propose_tool_call":
        assert not action["map_actions"]
    if action["action_type"] in {"ask_clarifying_question", "no_result"}:
        unknown_refs = {item["unknown_id"] for item in session["unknowns"]}
        assert set(action["payload"]["blocking_unknown_refs"]) <= unknown_refs
    if action["action_type"] == "present_valid_candidates":
        session_candidates = {
            item["candidate_ref"]: item for item in session["candidate_plans"]
        }
        assert_unique(action["payload"]["candidates"], "candidate_ref")
        payload_plan_keys = [
            revision_key(item["plan_revision_ref"])
            for item in action["payload"]["candidates"]
        ]
        assert len(payload_plan_keys) == len(set(payload_plan_keys))
        payload_keys = set()
        for candidate_ref in action["payload"]["candidates"]:
            candidate = session_candidates[candidate_ref["candidate_ref"]]
            assert candidate["session_fit_status"] == "current"
            assert candidate_ref["validation_result_ref"] == candidate["validation_result_ref"]
            assert revision_key(candidate_ref["plan_revision_ref"]) == revision_key(
                candidate["plan_revision_ref"]
            )
            payload_keys.add(candidate_key(candidate_ref))
        displayed_keys = {
            candidate_key(item)
            for map_action in action["map_actions"]
            if map_action["action_type"] == "show_candidate_set"
            for item in map_action["payload"]["candidates"]
        }
        assert payload_keys == displayed_keys
    if action["action_type"] == "finalize_response":
        if action["payload"]["outcome_kind"] == "plan_selected":
            assert selection_event is not None
            assert_plan_selection_provenance(session, selection_event)
    assert_map_action_batch(action["map_actions"], session, action, run)


def assert_session_transition(before, after, base_revision):
    assert_cross_contract_environment(before, after)
    assert before["session_id"] == after["session_id"]
    assert before["session_revision"] == base_revision
    assert after["session_revision"] == base_revision + 1
    assert parse_rfc3339(before["updated_at"]) <= parse_rfc3339(after["updated_at"])
    assert_session_semantics(before)
    assert_session_semantics(after)


def assert_plan_selection_provenance(selected_session, event):
    assert_cross_contract_environment(selected_session, event)
    selected = selected_session["selected_plan"]
    candidates = {
        item["candidate_ref"]: item for item in selected_session["candidate_plans"]
    }
    candidate = candidates[selected["candidate_ref"]]
    assert event["event_id"] == selected["selected_by_user_event_ref"]
    assert event["actor"] == "user"
    assert event["event_type"] == "plan_confirmed"
    assert selected["selected_by_event_type"] == "plan_confirmed"
    assert event["session_id"] == selected_session["session_id"]
    assert parse_rfc3339(selected_session["created_at"]) <= parse_rfc3339(
        event["occurred_at"]
    )
    assert event["base_session_revision"] == selected_session["session_revision"] - 1
    assert event["payload"]["candidate_ref"] == selected["candidate_ref"]
    assert revision_key(event["payload"]["plan_revision_ref"]) == revision_key(
        selected["plan_revision_ref"]
    )
    assert parse_rfc3339(selected["selected_at"]) == parse_rfc3339(
        event["occurred_at"]
    )
    assert selected_session["last_map_event_ref"] == event["event_id"]
    assert candidate["session_fit_status"] == "current"
    assert candidate["presentation_state"] != "hidden"
    assert "validation_result_ref" in candidate


def assert_plan_selection_transition(before, event, after):
    assert event["event_type"] == "plan_confirmed"
    assert_event_semantics(event, before)
    assert_session_transition(before, after, event["base_session_revision"])
    assert parse_rfc3339(event["occurred_at"]) <= parse_rfc3339(after["updated_at"])
    assert_plan_selection_provenance(after, event)
    selected = after["selected_plan"]
    assert selected["candidate_ref"] == event["payload"]["candidate_ref"]
    assert revision_key(selected["plan_revision_ref"]) == revision_key(
        event["payload"]["plan_revision_ref"]
    )
    assert selected["selected_by_user_event_ref"] == event["event_id"]


def assert_fit_bounds_transition(before, map_action, after):
    assert map_action["action_type"] == "fit_bounds"
    assert_map_action_batch([map_action], before)
    assert_session_transition(before, after, map_action["base_session_revision"])
    expected = deepcopy(before)
    expected["session_revision"] += 1
    expected["updated_at"] = map_action["issued_at"]
    expected["map_state"]["viewport"]["bounds_ref"] = map_action["payload"][
        "bounds_ref"
    ]
    expected["map_state"]["viewport"]["source_kind"] = "map_action"
    expected["map_state"]["viewport"]["source_ref"] = map_action["map_action_id"]
    expected["map_state"]["presentation"]["last_map_action_refs"].append(
        map_action["map_action_id"]
    )
    assert after == expected


def assert_viewport_event_transition(before, event, after):
    assert event["event_type"] == "viewport_changed"
    assert_event_semantics(event, before)
    assert_session_transition(before, after, event["base_session_revision"])
    expected = deepcopy(before)
    expected["session_revision"] += 1
    expected["updated_at"] = event["occurred_at"]
    expected["last_map_event_ref"] = event["event_id"]
    expected["map_state"]["viewport"] = {
        "bounds_ref": event["payload"]["bounds_ref"],
        "zoom_level": event["payload"]["zoom_level"],
        "source_kind": "map_event",
        "source_ref": event["event_id"],
    }
    assert after == expected


def make_event(session, event_type, payload, sequence=99):
    return {
        "schema_version": "0.1.0",
        "environment": "test",
        "fixture_only": True,
        "event_id": f"map-event.mutation-{event_type}-{sequence}",
        "client_event_id": f"client-event.mutation-{event_type}-{sequence}",
        "session_id": session["session_id"],
        "base_session_revision": session["session_revision"],
        "event_sequence": sequence,
        "occurred_at": "2026-08-03T20:16:00+08:00",
        "actor": "user",
        "source_surface": "route_map",
        "event_type": event_type,
        "payload": payload,
        "metadata": {"x-fixture": True},
    }


def load_valid(name):
    return load_json(VALID_FIXTURES / name)


def load_invalid(name):
    return load_json(INVALID_FIXTURES / name)


def semantic_validator_for(schema_name):
    return {
        "session_state": assert_session_semantics,
        "agent_run": assert_run_semantics,
    }.get(schema_name)


def test_five_schemas_are_valid_draft_2020_12_with_stable_ids(schemas):
    assert set(A2_2_SCHEMA_FILES) == set(EXPECTED_SCHEMA_IDS)
    for name in A2_2_SCHEMA_FILES:
        schema = schemas[name]
        Draft202012Validator.check_schema(schema)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["$id"] == EXPECTED_SCHEMA_IDS[name]


def test_all_a2_2_schema_references_are_local(schemas):
    allowed_files = set(SCHEMA_FILES.values())
    for name in A2_2_SCHEMA_FILES:
        for ref in walk_refs(schemas[name]):
            assert not ref.startswith(("http://", "https://"))
            if not ref.startswith("#"):
                assert ref.split("#", 1)[0] in allowed_files


@pytest.mark.parametrize("fixture_name,schema_name", VALID_FIXTURE_SCHEMAS.items())
def test_valid_a2_2_fixtures_conform(
    fixture_name, schema_name, schemas, local_registry
):
    instance = load_valid(fixture_name)
    assert not validation_errors(schema_name, instance, schemas, local_registry)
    semantic_validator = semantic_validator_for(schema_name)
    if semantic_validator:
        semantic_validator(instance)


@pytest.mark.parametrize("fixture_name,schema_name", INVALID_FIXTURE_SCHEMAS.items())
def test_invalid_fixtures_fail_for_the_named_reason(
    fixture_name, schema_name, schemas, local_registry
):
    instance = load_invalid(fixture_name)
    errors = validation_errors(schema_name, instance, schemas, local_registry)
    if fixture_name == "session_state_selected_plan_not_candidate.json":
        assert not errors
        with pytest.raises((AssertionError, KeyError), match="candidate|missing"):
            assert_session_semantics(instance)
    elif fixture_name == "agent_run_budget_over_limit.json":
        assert not errors
        with pytest.raises(AssertionError, match="model_turns"):
            assert_run_semantics(instance)
    else:
        assert errors
        messages = "\n".join(
            message for error in errors for message in nested_error_messages(error)
        )
        expected_token = {
            "map_event_raw_coordinates.json": "coordinates",
            "map_action_unknown_frontend_command.json": "run_frontend_command",
            "agent_action_direct_external_effect.json": "direct_external_effect",
        }[fixture_name]
        assert expected_token in messages


@pytest.mark.parametrize("schema_name", A2_2_SCHEMA_FILES)
@pytest.mark.parametrize(
    "environment,fixture_only",
    [
        ("test", False),
        ("shadow", True),
        ("production", True),
    ],
)
def test_environment_fixture_combinations_fail_closed(
    schema_name, environment, fixture_only, schemas, local_registry
):
    representative = {
        "session_state": "session_state_clarification_r3.json",
        "agent_run": "agent_run_clarification_paused.json",
        "map_event": "map_event_plan_confirmed.json",
        "map_action": "map_action_show_candidate_set.json",
        "agent_action": "agent_action_ask_clarification.json",
    }[schema_name]
    instance = load_valid(representative)
    instance["environment"] = environment
    instance["fixture_only"] = fixture_only
    assert validation_errors(schema_name, instance, schemas, local_registry)


@pytest.mark.parametrize("schema_name", A2_2_SCHEMA_FILES)
def test_shadow_and_production_non_fixture_shapes_are_allowed(
    schema_name, schemas, local_registry
):
    representative = {
        "session_state": "session_state_clarification_r3.json",
        "agent_run": "agent_run_clarification_paused.json",
        "map_event": "map_event_plan_confirmed.json",
        "map_action": "map_action_show_candidate_set.json",
        "agent_action": "agent_action_ask_clarification.json",
    }[schema_name]
    for environment in ("shadow", "production"):
        instance = load_valid(representative)
        instance["environment"] = environment
        instance["fixture_only"] = False
        assert not validation_errors(schema_name, instance, schemas, local_registry)


def test_context_manifest_session_and_run_are_cross_bound():
    manifest = load_json(VALID_FIXTURES / "context_manifest.json")
    session = load_valid("session_state_candidates_before.json")
    run = load_valid("agent_run_candidate_completed.json")
    assert manifest["session_id"] == session["session_id"] == run["session_id"]
    assert manifest["session_revision"] == session["session_revision"]
    assert manifest["session_revision"] == run["base_session_revision"]
    assert manifest["run_id"] == run["run_id"]
    assert manifest["packet_environment"] == session["environment"] == run["environment"]
    assert manifest["manifest_id"] in run["context_manifest_refs"]
    assert_cross_contract_environment(session, run, manifest=manifest)


def test_test_session_and_shadow_run_are_individually_valid_but_cross_invalid(
    schemas, local_registry
):
    session = load_valid("session_state_clarification_r3.json")
    run = load_valid("agent_run_clarification_paused.json")
    run["environment"] = "shadow"
    run["fixture_only"] = False
    assert not validation_errors("session_state", session, schemas, local_registry)
    assert not validation_errors("agent_run", run, schemas, local_registry)
    with pytest.raises(AssertionError):
        assert_cross_contract_environment(session, run)


def test_test_run_and_production_action_are_individually_valid_but_cross_invalid(
    schemas, local_registry
):
    session = load_valid("session_state_clarification_r3.json")
    run = load_valid("agent_run_clarification_paused.json")
    action = load_valid("agent_action_ask_clarification.json")
    action["environment"] = "production"
    action["fixture_only"] = False
    assert not validation_errors("agent_action", action, schemas, local_registry)
    with pytest.raises(AssertionError):
        assert_agent_action_semantics(action, run, session)


def test_test_action_and_shadow_nested_map_action_are_cross_invalid(
    schemas, local_registry
):
    session = load_valid("session_state_candidates_before.json")
    run = load_valid("agent_run_candidate_completed.json")
    action = load_valid("agent_action_present_candidates.json")
    action["map_actions"][0]["environment"] = "shadow"
    action["map_actions"][0]["fixture_only"] = False
    assert not validation_errors("agent_action", action, schemas, local_registry)
    with pytest.raises(AssertionError):
        assert_agent_action_semantics(action, run, session)


def test_test_session_and_production_event_are_cross_invalid(
    schemas, local_registry
):
    session = load_valid("session_state_candidates_presented.json")
    event = load_valid("map_event_plan_confirmed.json")
    event["environment"] = "production"
    event["fixture_only"] = False
    assert not validation_errors("map_event", event, schemas, local_registry)
    with pytest.raises(AssertionError):
        assert_event_semantics(event, session)


@pytest.mark.parametrize(
    "proposed_at",
    ["2026-08-03T19:38:59+08:00", "2026-08-03T19:41:01+08:00"],
)
def test_agent_action_time_must_stay_within_run(proposed_at):
    session = load_valid("session_state_clarification_r3.json")
    run = load_valid("agent_run_clarification_paused.json")
    action = load_valid("agent_action_ask_clarification.json")
    action["proposed_at"] = proposed_at
    with pytest.raises(AssertionError):
        assert_agent_action_semantics(action, run, session)


def test_nested_map_action_cannot_precede_agent_action():
    session = load_valid("session_state_candidates_before.json")
    run = load_valid("agent_run_candidate_completed.json")
    action = load_valid("agent_action_present_candidates.json")
    action["map_actions"][0]["issued_at"] = "2026-08-03T20:09:59+08:00"
    with pytest.raises(AssertionError):
        assert_agent_action_semantics(action, run, session)


def test_pending_gate_time_must_stay_within_run():
    run = load_valid("agent_run_clarification_paused.json")
    run["pending_gate"]["created_at"] = "2026-08-03T19:38:59+08:00"
    with pytest.raises(AssertionError):
        assert_run_semantics(run)


def test_map_event_cannot_precede_session_creation():
    session = load_valid("session_state_candidates_presented.json")
    event = load_valid("map_event_plan_confirmed.json")
    event["occurred_at"] = "2026-08-03T19:59:59+08:00"
    with pytest.raises(AssertionError):
        assert_event_semantics(event, session)


def test_created_run_fixture_is_pre_execution_and_valid(schemas, local_registry):
    run = load_valid("agent_run_created.json")
    assert not validation_errors("agent_run", run, schemas, local_registry)
    assert_run_semantics(run)
    assert run["context_manifest_refs"] == []
    assert run["session_commit"]["commit_status"] == "not_attempted"


@pytest.mark.parametrize(
    "mutation",
    ["context", "model_turn", "action", "tool", "observation", "commit"],
)
def test_created_run_cannot_claim_execution_or_commit(
    mutation, schemas, local_registry
):
    run = load_valid("agent_run_created.json")
    if mutation == "context":
        run["context_manifest_refs"] = ["context-manifest.invalid-created"]
    elif mutation == "model_turn":
        run["budget"]["consumed"]["model_turns"] = 1
    elif mutation == "action":
        run["action_proposal_refs"] = ["agent-action.invalid-created"]
    elif mutation == "tool":
        run["tool_call_refs"] = ["tool-call.invalid-created"]
    elif mutation == "observation":
        run["observation_refs"] = ["observation.invalid-created"]
    else:
        run["session_commit"] = {
            "commit_status": "committed",
            "expected_base_revision": 3,
            "committed_revision": 4,
        }
    assert validation_errors("agent_run", run, schemas, local_registry)
    with pytest.raises(AssertionError):
        assert_run_semantics(run)


def test_running_run_cannot_claim_committed_session(schemas, local_registry):
    run = load_valid("agent_run_clarification_resume.json")
    run["session_commit"] = {
        "commit_status": "committed",
        "expected_base_revision": 4,
        "committed_revision": 5,
    }
    assert validation_errors("agent_run", run, schemas, local_registry)
    with pytest.raises(AssertionError):
        assert_run_semantics(run)


@pytest.mark.parametrize("delta", [-1, 1])
def test_context_manifest_count_must_equal_model_turns(delta):
    run = load_valid("agent_run_candidate_completed.json")
    if delta < 0:
        run["context_manifest_refs"] = []
    else:
        run["context_manifest_refs"].append("context-manifest.invalid-extra")
    with pytest.raises(AssertionError):
        assert_run_semantics(run)


@pytest.mark.parametrize("deadline_relation", ["equal", "earlier"])
def test_run_deadline_must_be_strictly_after_started_at(deadline_relation):
    run = load_valid("agent_run_created.json")
    run["budget"]["limits"]["wall_clock_deadline"] = run["started_at"]
    if deadline_relation == "earlier":
        run["budget"]["limits"]["wall_clock_deadline"] = (
            "2026-08-03T19:38:29+08:00"
        )
    with pytest.raises(AssertionError):
        assert_run_semantics(run)


def test_clarification_scenario_commits_waiting_session_revision():
    before = load_valid("session_state_clarification_r3.json")
    action = load_valid("agent_action_ask_clarification.json")
    run = load_valid("agent_run_clarification_paused.json")
    after = load_valid("session_state_clarification_r4.json")
    assert_agent_action_semantics(action, run, before)
    assert_session_transition(before, after, 3)
    assert run["run_status"] == "paused"
    assert run["stop_reason"] == "waiting_for_user"
    assert run["session_commit"]["committed_revision"] == after["session_revision"]
    assert after["pending_user_decision"]["requested_by_agent_action_ref"] == action[
        "action_id"
    ]


def test_stale_run_and_action_cannot_target_newer_session_revision():
    action = load_valid("agent_action_ask_clarification.json")
    run = load_valid("agent_run_clarification_paused.json")
    current_session = load_valid("session_state_clarification_r4.json")
    with pytest.raises(AssertionError):
        assert_agent_action_semantics(action, run, current_session)


@pytest.mark.parametrize("candidate_count", [0, 1, 2, 3])
def test_session_allows_zero_through_three_candidates(
    candidate_count, schemas, local_registry
):
    session = load_valid("session_state_candidates_presented.json")
    candidates = deepcopy(session["candidate_plans"])
    if candidate_count == 0:
        session["candidate_plans"] = []
        session.pop("active_candidate_ref", None)
        session["map_state"]["presentation"]["visible_candidate_refs"] = []
        session["map_state"]["presentation"]["highlighted_targets"] = []
    elif candidate_count == 1:
        session["candidate_plans"] = candidates[:1]
        session["map_state"]["presentation"]["visible_candidate_refs"] = [
            candidates[0]["candidate_ref"]
        ]
    elif candidate_count == 2:
        session["candidate_plans"] = candidates
    else:
        third = deepcopy(candidates[1])
        third["candidate_ref"] = "candidate.fixture-c"
        third["plan_revision_ref"]["object_ref"]["object_id"] = "ride-plan.fixture-c"
        third["validation_result_ref"] = "validation.fixture-c-r1"
        third["display_order"] = 3
        session["candidate_plans"] = candidates + [third]
        session["map_state"]["presentation"]["visible_candidate_refs"].append(
            third["candidate_ref"]
        )
    assert not validation_errors("session_state", session, schemas, local_registry)
    assert_session_semantics(session)


def test_session_rejects_four_candidates(schemas, local_registry):
    session = load_valid("session_state_candidates_presented.json")
    for index in (3, 4):
        candidate = deepcopy(session["candidate_plans"][0])
        candidate["candidate_ref"] = f"candidate.fixture-{index}"
        candidate["plan_revision_ref"]["object_ref"]["object_id"] = (
            f"ride-plan.fixture-{index}"
        )
        candidate["validation_result_ref"] = f"validation.fixture-{index}"
        candidate["display_order"] = index
        session["candidate_plans"].append(candidate)
    assert validation_errors("session_state", session, schemas, local_registry)


def test_current_visible_candidate_requires_validation(schemas, local_registry):
    session = load_valid("session_state_candidates_presented.json")
    session["candidate_plans"][0].pop("validation_result_ref")
    assert validation_errors("session_state", session, schemas, local_registry)


@pytest.mark.parametrize("fit_status", ["stale", "invalid"])
def test_stale_or_invalid_candidate_cannot_be_active_or_selected(fit_status):
    session = load_valid("session_state_plan_selected.json")
    selected_ref = session["selected_plan"]["candidate_ref"]
    candidate = next(
        item for item in session["candidate_plans"] if item["candidate_ref"] == selected_ref
    )
    candidate["session_fit_status"] = fit_status
    with pytest.raises(AssertionError):
        assert_session_semantics(session)


def test_selected_plan_revision_must_match_candidate():
    session = load_valid("session_state_plan_selected.json")
    session["selected_plan"]["plan_revision_ref"]["revision"] = 2
    with pytest.raises(AssertionError):
        assert_session_semantics(session)


def test_duplicate_candidate_plan_order_and_revision_are_rejected():
    session = load_valid("session_state_candidates_presented.json")
    duplicate = deepcopy(session["candidate_plans"][0])
    duplicate["candidate_ref"] = "candidate.fixture-duplicate"
    duplicate["display_order"] = 2
    session["candidate_plans"].append(duplicate)
    with pytest.raises(AssertionError, match="display_order|plan revision"):
        assert_session_semantics(session)


@pytest.mark.parametrize("anchor_role", ["origin", "destination"])
def test_session_allows_at_most_one_origin_and_destination(anchor_role):
    session = load_valid("session_state_candidates_presented.json")
    anchor = next(
        item for item in session["map_state"]["anchors"] if item["anchor_role"] == anchor_role
    )
    duplicate = deepcopy(anchor)
    duplicate["anchor_ref"] = f"anchor.fixture-duplicate-{anchor_role}"
    session["map_state"]["anchors"].append(duplicate)
    with pytest.raises(AssertionError):
        assert_session_semantics(session)


def test_session_elevation_fraction_order_is_semantic():
    session = load_valid("session_state_candidates_presented.json")
    session["map_state"]["elevation_selection"] = {
        "target_kind": "plan_leg",
        "target_ref": "leg.fixture-a-core",
        "from_fraction": 0.8,
        "to_fraction": 0.2,
        "selected_by_event_ref": "map-event.fixture-elevation-001",
    }
    with pytest.raises(AssertionError):
        assert_session_semantics(session)


@pytest.mark.parametrize(
    "created_at,updated_at,expires_at",
    [
        (
            "2026-08-03T20:00:00+08:00",
            "2026-08-03T19:59:59+08:00",
            "2026-08-03T23:00:00+08:00",
        ),
        (
            "2026-08-03T20:00:00+08:00",
            "2026-08-03T21:00:00+08:00",
            "2026-08-03T21:00:00+08:00",
        ),
    ],
)
def test_session_time_order_fail_closed(created_at, updated_at, expires_at):
    session = load_valid("session_state_clarification_r3.json")
    session["created_at"] = created_at
    session["updated_at"] = updated_at
    session["expires_at"] = expires_at
    with pytest.raises(AssertionError):
        assert_session_semantics(session)


@pytest.mark.parametrize("status", ["expired", "cancelled"])
def test_terminal_session_cannot_retain_pending_decision(
    status, schemas, local_registry
):
    session = load_valid("session_state_clarification_r4.json")
    session["status"] = status
    assert validation_errors("session_state", session, schemas, local_registry)


@pytest.mark.parametrize(
    "mutation",
    [
        "model_turns",
        "tool_calls",
        "plan_generations",
        "tokens",
        "retry_counter",
        "action_ref_count",
        "tool_ref_count",
    ],
)
def test_run_budget_and_reference_counts_fail_closed(mutation):
    run = load_valid("agent_run_candidate_completed.json")
    if mutation == "model_turns":
        run["budget"]["consumed"]["model_turns"] = 5
    elif mutation == "tool_calls":
        run["budget"]["consumed"]["tool_calls"] = 7
    elif mutation == "plan_generations":
        run["budget"]["consumed"]["plan_generations"] = 4
    elif mutation == "tokens":
        run["budget"]["consumed"]["tokens"] = 12001
    elif mutation == "retry_counter":
        run["budget"]["tool_retry_counters"][0]["retries"] = 3
    elif mutation == "action_ref_count":
        run["budget"]["consumed"]["model_turns"] = 0
    else:
        run["budget"]["consumed"]["tool_calls"] = 0
    with pytest.raises(AssertionError):
        assert_run_semantics(run)


@pytest.mark.parametrize(
    "mutation",
    [
        "running_with_stop_reason",
        "paused_without_gate",
        "paused_with_completed",
        "stopped_without_ended_at",
        "stopped_with_pending_gate",
    ],
)
def test_run_status_stop_reason_combinations_are_schema_closed(
    mutation, schemas, local_registry
):
    run = load_valid("agent_run_clarification_paused.json")
    if mutation == "running_with_stop_reason":
        run["run_status"] = "running"
    elif mutation == "paused_without_gate":
        run.pop("pending_gate")
    elif mutation == "paused_with_completed":
        run["stop_reason"] = "completed"
    elif mutation == "stopped_without_ended_at":
        run["run_status"] = "stopped"
        run["stop_reason"] = "completed"
        run.pop("pending_gate")
    else:
        run["run_status"] = "stopped"
        run["stop_reason"] = "completed"
        run["ended_at"] = run["last_checkpoint_at"]
    assert validation_errors("agent_run", run, schemas, local_registry)


def test_budget_exceeded_requires_real_exhaustion():
    run = load_valid("agent_run_candidate_completed.json")
    run["stop_reason"] = "budget_exceeded"
    run["budget"]["limits"]["wall_clock_deadline"] = "2026-08-03T20:30:00+08:00"
    with pytest.raises(AssertionError):
        assert_run_semantics(run)


def test_budget_exceeded_accepts_counter_or_deadline_evidence():
    run = load_valid("agent_run_candidate_completed.json")
    run["stop_reason"] = "budget_exceeded"
    run["budget"]["consumed"]["tokens"] = run["budget"]["limits"]["token_limit"]
    assert_run_semantics(run)
    run["budget"]["consumed"]["tokens"] = 2400
    run["budget"]["limits"]["wall_clock_deadline"] = run["last_checkpoint_at"]
    assert_run_semantics(run)


def test_committed_session_revision_must_be_base_plus_one():
    run = load_valid("agent_run_candidate_completed.json")
    run["session_commit"]["committed_revision"] = 3
    with pytest.raises(AssertionError):
        assert_run_semantics(run)


def test_completed_run_requires_committed_session():
    run = load_valid("agent_run_candidate_completed.json")
    run["session_commit"] = {
        "commit_status": "not_attempted",
        "expected_base_revision": 1,
    }
    with pytest.raises(AssertionError):
        assert_run_semantics(run)


def test_rejected_stale_run_cannot_claim_completed():
    run = load_valid("agent_run_candidate_completed.json")
    run["session_commit"] = {
        "commit_status": "rejected_stale",
        "expected_base_revision": 1,
    }
    with pytest.raises(AssertionError):
        assert_run_semantics(run)


def test_reconciliation_required_is_a_formal_non_completed_commit_state(schemas, local_registry):
    run = load_valid("agent_run_candidate_completed.json")
    run["stop_reason"] = "deterministic_error"
    run["session_commit"] = {
        "commit_status": "reconciliation_required",
        "expected_base_revision": 1,
    }
    assert not validation_errors("agent_run", run, schemas, local_registry)
    assert_run_semantics(run)
    run["stop_reason"] = "completed"
    with pytest.raises(AssertionError):
        assert_run_semantics(run)


def test_run_time_order_uses_timezone_aware_rfc3339():
    run = load_valid("agent_run_candidate_completed.json")
    run["started_at"] = "2026-08-03T20:00:00+08:00"
    run["last_checkpoint_at"] = "2026-08-03T12:01:00+00:00"
    run["ended_at"] = "2026-08-03T11:59:00+00:00"
    with pytest.raises(AssertionError):
        assert_run_semantics(run)


def test_resume_child_preserves_budget_lineage(schemas, local_registry):
    parent = load_valid("agent_run_clarification_paused.json")
    child = load_valid("agent_run_clarification_resume.json")
    current_session = load_valid("session_state_clarification_r4.json")
    child_action = load_valid("agent_action_resume_clarification.json")
    assert not validation_errors("agent_run", child, schemas, local_registry)
    assert not validation_errors("agent_action", child_action, schemas, local_registry)
    assert_resume_semantics(parent, child, current_session, child_action)


@pytest.mark.parametrize("base_revision", [3, 5])
def test_resume_child_must_bind_exact_current_session_revision(base_revision):
    parent = load_valid("agent_run_clarification_paused.json")
    child = load_valid("agent_run_clarification_resume.json")
    current_session = load_valid("session_state_clarification_r4.json")
    child["base_session_revision"] = base_revision
    child["session_commit"]["expected_base_revision"] = base_revision
    with pytest.raises(AssertionError):
        assert_resume_semantics(parent, child, current_session)


@pytest.mark.parametrize(
    "mutation",
    [
        "session",
        "lineage",
        "limits",
        "model_turns",
        "tool_calls",
        "plan_generations",
        "tokens",
        "cost_micros",
        "retry",
    ],
)
def test_resume_child_cannot_reset_or_change_budget_lineage(mutation):
    parent = load_valid("agent_run_clarification_paused.json")
    child = load_valid("agent_run_clarification_resume.json")
    current_session = load_valid("session_state_clarification_r4.json")
    if mutation == "session":
        child["session_id"] = "planning-session.other"
    elif mutation == "lineage":
        child["run_lineage_ref"] = "run-lineage.other"
    elif mutation == "limits":
        child["budget"]["limits"]["max_model_turns"] = 5
    elif mutation == "model_turns":
        child["budget"]["consumed"]["model_turns"] = 0
        child["action_proposal_refs"] = []
        child["context_manifest_refs"] = []
    elif mutation == "tool_calls":
        parent["budget"]["consumed"]["tool_calls"] = 1
        parent["tool_call_refs"] = ["tool-call.fixture-parent-001"]
        child["budget"]["consumed"]["tool_calls"] = 0
        child["tool_call_refs"] = []
    elif mutation == "plan_generations":
        parent["budget"]["consumed"]["plan_generations"] = 1
        child["budget"]["consumed"]["plan_generations"] = 0
    elif mutation == "tokens":
        child["budget"]["consumed"]["tokens"] = 800
    elif mutation == "cost_micros":
        parent["budget"]["limits"]["cost_limit_micros"] = 10000
        parent["budget"]["consumed"]["cost_micros"] = 100
        child["budget"]["limits"]["cost_limit_micros"] = 10000
        child["budget"]["consumed"]["cost_micros"] = 90
    else:
        parent["budget"]["tool_retry_counters"] = [
            {"tool_name": "planning.resolve_location", "retries": 1}
        ]
        child["budget"]["tool_retry_counters"] = [
            {"tool_name": "planning.resolve_location", "retries": 0}
        ]
    with pytest.raises(AssertionError):
        assert_resume_semantics(parent, child, current_session)


def test_resume_child_action_must_bind_child_base_revision():
    parent = load_valid("agent_run_clarification_paused.json")
    child = load_valid("agent_run_clarification_resume.json")
    current_session = load_valid("session_state_clarification_r4.json")
    child_action = load_valid("agent_action_resume_clarification.json")
    child_action["base_session_revision"] = 3
    with pytest.raises(AssertionError):
        assert_resume_semantics(parent, child, current_session, child_action)


def test_non_resume_trigger_cannot_fake_parent_run(schemas, local_registry):
    run = load_valid("agent_run_clarification_paused.json")
    run["trigger"]["resumed_from_run_ref"] = "agent-run.fake-parent"
    assert validation_errors("agent_run", run, schemas, local_registry)


def test_candidate_presentation_scenario_uses_one_validated_map_batch():
    before = load_valid("session_state_candidates_before.json")
    action = load_valid("agent_action_present_candidates.json")
    standalone = load_valid("map_action_show_candidate_set.json")
    run = load_valid("agent_run_candidate_completed.json")
    after = load_valid("session_state_candidates_presented.json")
    assert action["map_actions"] == [standalone]
    assert_agent_action_semantics(action, run, before)
    assert_session_transition(before, after, 1)
    assert run["session_commit"]["committed_revision"] == after["session_revision"]
    assert "selected_plan" not in after
    assert set(after["map_state"]["presentation"]["visible_candidate_refs"]) == {
        "candidate.fixture-a",
        "candidate.fixture-b",
    }


def test_fit_bounds_changes_viewport_to_known_bounds():
    before = load_valid("session_state_candidates_before.json")
    map_action = load_valid("map_action_fit_bounds.json")
    after = load_valid("session_state_fit_bounds_r2.json")
    assert map_action["payload"]["bounds_ref"] != before["map_state"]["viewport"][
        "bounds_ref"
    ]
    assert_fit_bounds_transition(before, map_action, after)


def test_fit_bounds_transition_requires_next_session_revision():
    before = load_valid("session_state_candidates_before.json")
    map_action = load_valid("map_action_fit_bounds.json")
    after = load_valid("session_state_fit_bounds_r2.json")
    after["session_revision"] = 3
    with pytest.raises(AssertionError):
        assert_fit_bounds_transition(before, map_action, after)


def test_fit_bounds_rejects_unresolved_bounds_ref():
    session = load_valid("session_state_candidates_before.json")
    map_action = load_valid("map_action_fit_bounds.json")
    map_action["payload"]["bounds_ref"] = "bounds.fixture-not-resolved"
    with pytest.raises(AssertionError):
        assert_map_action_batch([map_action], session)


def test_fit_bounds_after_viewport_must_apply_requested_bounds():
    before = load_valid("session_state_candidates_before.json")
    map_action = load_valid("map_action_fit_bounds.json")
    after = load_valid("session_state_fit_bounds_r2.json")
    after["map_state"]["viewport"]["bounds_ref"] = before["map_state"]["viewport"][
        "bounds_ref"
    ]
    with pytest.raises(AssertionError):
        assert_fit_bounds_transition(before, map_action, after)


@pytest.mark.parametrize("mutation", ["kind", "ref"])
def test_fit_bounds_viewport_source_must_match_map_action(mutation):
    before = load_valid("session_state_candidates_before.json")
    map_action = load_valid("map_action_fit_bounds.json")
    after = load_valid("session_state_fit_bounds_r2.json")
    if mutation == "kind":
        after["map_state"]["viewport"]["source_kind"] = "map_event"
    else:
        after["map_state"]["viewport"]["source_ref"] = "map-action.other"
    with pytest.raises(AssertionError):
        assert_fit_bounds_transition(before, map_action, after)


def test_viewport_changed_event_records_map_event_source():
    before = load_valid("session_state_candidates_before.json")
    event = make_event(
        before,
        "viewport_changed",
        {"bounds_ref": "bounds.fixture-candidate-detail-002", "zoom_level": 12},
    )
    after = deepcopy(before)
    after["session_revision"] += 1
    after["updated_at"] = event["occurred_at"]
    after["last_map_event_ref"] = event["event_id"]
    after["map_state"]["viewport"] = {
        "bounds_ref": event["payload"]["bounds_ref"],
        "zoom_level": event["payload"]["zoom_level"],
        "source_kind": "map_event",
        "source_ref": event["event_id"],
    }
    assert_viewport_event_transition(before, event, after)
    after["map_state"]["viewport"]["source_kind"] = "map_action"
    with pytest.raises(AssertionError):
        assert_viewport_event_transition(before, event, after)


@pytest.mark.parametrize("target", ["available", "viewport"])
def test_bounds_refs_cannot_embed_coordinates(target, schemas, local_registry):
    session = load_valid("session_state_candidates_before.json")
    coordinate_value = {"coordinates": [112.5, 37.8]}
    if target == "available":
        session["map_state"]["available_bounds_refs"].append(coordinate_value)
    else:
        session["map_state"]["viewport"]["bounds_ref"] = coordinate_value
    assert validation_errors("session_state", session, schemas, local_registry)


def test_show_candidate_set_rejects_empty_or_four(schemas, local_registry):
    map_action = load_valid("map_action_show_candidate_set.json")
    map_action["payload"]["candidates"] = []
    assert validation_errors("map_action", map_action, schemas, local_registry)
    map_action = load_valid("map_action_show_candidate_set.json")
    for index in (3, 4):
        candidate = deepcopy(map_action["payload"]["candidates"][0])
        candidate["candidate_ref"] = f"candidate.fixture-{index}"
        candidate["plan_revision_ref"]["object_ref"]["object_id"] = (
            f"ride-plan.fixture-{index}"
        )
        candidate["validation_result_ref"] = f"validation.fixture-{index}"
        candidate["display_order"] = index
        map_action["payload"]["candidates"].append(candidate)
    assert validation_errors("map_action", map_action, schemas, local_registry)


def test_present_candidates_rejects_empty_or_four(schemas, local_registry):
    action = load_valid("agent_action_present_candidates.json")
    action["payload"]["candidates"] = []
    assert validation_errors("agent_action", action, schemas, local_registry)
    action = load_valid("agent_action_present_candidates.json")
    for index in (3, 4):
        candidate = deepcopy(action["payload"]["candidates"][0])
        candidate["candidate_ref"] = f"candidate.fixture-{index}"
        candidate["plan_revision_ref"]["object_ref"]["object_id"] = (
            f"ride-plan.fixture-{index}"
        )
        candidate["validation_result_ref"] = f"validation.fixture-{index}"
        action["payload"]["candidates"].append(candidate)
    assert validation_errors("agent_action", action, schemas, local_registry)


def test_candidate_switched_changes_focus_not_selection(schemas, local_registry):
    before = load_valid("session_state_candidates_presented.json")
    target = before["candidate_plans"][1]
    event = make_event(
        before,
        "candidate_switched",
        {
            "candidate_ref": target["candidate_ref"],
            "plan_revision_ref": deepcopy(target["plan_revision_ref"]),
        },
    )
    event["source_surface"] = "candidate_panel"
    assert not validation_errors("map_event", event, schemas, local_registry)
    assert_event_semantics(event, before)
    after = deepcopy(before)
    after["session_revision"] += 1
    after["updated_at"] = event["occurred_at"]
    after["last_map_event_ref"] = event["event_id"]
    after["active_candidate_ref"] = target["candidate_ref"]
    assert_session_transition(before, after, event["base_session_revision"])
    assert "selected_plan" not in before
    assert "selected_plan" not in after


def test_plan_confirmed_user_event_creates_traceable_selection():
    before = load_valid("session_state_candidates_presented.json")
    event = load_valid("map_event_plan_confirmed.json")
    after = load_valid("session_state_plan_selected.json")
    assert_plan_selection_transition(before, event, after)


def test_selected_plan_user_event_ref_cannot_point_to_agent_action():
    before = load_valid("session_state_candidates_presented.json")
    event = load_valid("map_event_plan_confirmed.json")
    after = load_valid("session_state_plan_selected.json")
    after["selected_plan"]["selected_by_user_event_ref"] = (
        "agent-action.fixture-present-candidates-001"
    )
    with pytest.raises(AssertionError):
        assert_plan_selection_transition(before, event, after)


def test_selection_event_candidate_must_match_selected_plan():
    before = load_valid("session_state_candidates_presented.json")
    event = load_valid("map_event_plan_confirmed.json")
    after = load_valid("session_state_plan_selected.json")
    candidate = before["candidate_plans"][0]
    event["payload"] = {
        "candidate_ref": candidate["candidate_ref"],
        "plan_revision_ref": deepcopy(candidate["plan_revision_ref"]),
    }
    with pytest.raises(AssertionError):
        assert_plan_selection_transition(before, event, after)


def test_selection_event_plan_revision_must_match_selected_plan():
    before = load_valid("session_state_candidates_presented.json")
    event = load_valid("map_event_plan_confirmed.json")
    after = load_valid("session_state_plan_selected.json")
    event["payload"]["plan_revision_ref"]["revision"] = 2
    with pytest.raises(AssertionError):
        assert_plan_selection_transition(before, event, after)


def test_selection_event_must_target_immediately_previous_revision():
    before = load_valid("session_state_candidates_presented.json")
    event = load_valid("map_event_plan_confirmed.json")
    after = load_valid("session_state_plan_selected.json")
    event["base_session_revision"] = 1
    with pytest.raises(AssertionError):
        assert_plan_selection_transition(before, event, after)


def test_selected_at_must_equal_plan_confirmed_occurred_at():
    before = load_valid("session_state_candidates_presented.json")
    event = load_valid("map_event_plan_confirmed.json")
    after = load_valid("session_state_plan_selected.json")
    after["selected_plan"]["selected_at"] = "2026-08-03T20:14:01+08:00"
    with pytest.raises(AssertionError):
        assert_plan_selection_transition(before, event, after)


def test_plan_confirmed_cannot_target_hidden_candidate():
    before = load_valid("session_state_candidates_presented.json")
    event = load_valid("map_event_plan_confirmed.json")
    target = next(
        item
        for item in before["candidate_plans"]
        if item["candidate_ref"] == event["payload"]["candidate_ref"]
    )
    target["presentation_state"] = "hidden"
    with pytest.raises(AssertionError):
        assert_event_semantics(event, before)


def test_active_candidate_cannot_be_hidden():
    session = load_valid("session_state_candidates_presented.json")
    active = next(
        item
        for item in session["candidate_plans"]
        if item["candidate_ref"] == session["active_candidate_ref"]
    )
    active["presentation_state"] = "hidden"
    with pytest.raises(AssertionError):
        assert_session_semantics(session)


def test_selected_by_event_type_is_fixed_by_schema(schemas, local_registry):
    session = load_valid("session_state_plan_selected.json")
    session["selected_plan"]["selected_by_event_type"] = "candidate_switched"
    assert validation_errors("session_state", session, schemas, local_registry)


def test_candidate_switch_event_cannot_create_selected_plan():
    before = load_valid("session_state_candidates_presented.json")
    event = load_valid("map_event_plan_confirmed.json")
    event["event_type"] = "candidate_switched"
    after = load_valid("session_state_plan_selected.json")
    with pytest.raises(AssertionError):
        assert_plan_selection_transition(before, event, after)


@pytest.mark.parametrize("event_type,anchor_role", [("origin_pinned", "origin"), ("destination_pinned", "destination")])
def test_anchor_change_invalidates_candidates_and_selection(
    event_type, anchor_role, schemas, local_registry
):
    before = load_valid("session_state_plan_selected.json")
    old_anchor = next(
        item for item in before["map_state"]["anchors"] if item["anchor_role"] == anchor_role
    )
    event = make_event(before, event_type, {}, sequence=100)
    replacement = {
        "anchor_ref": f"anchor.fixture-replaced-{anchor_role}",
        "anchor_role": anchor_role,
        "location_handle": {
            "place_ref": f"place.fixture-replaced-{anchor_role}",
            "display_label": f"更新后的{anchor_role}区域",
            "precision": "point_ref_hidden",
            "exact_coordinates_exposed": False,
        },
        "source_event_ref": event["event_id"],
    }
    event["payload"] = {
        "anchor": replacement,
        "replaces_anchor_ref": old_anchor["anchor_ref"],
    }
    assert not validation_errors("map_event", event, schemas, local_registry)
    assert_event_semantics(event, before)

    after = deepcopy(before)
    after["session_revision"] += 1
    after["status"] = "open"
    after["updated_at"] = event["occurred_at"]
    after["last_map_event_ref"] = event["event_id"]
    after["map_state"]["anchors"] = [
        replacement if item["anchor_role"] == anchor_role else item
        for item in after["map_state"]["anchors"]
    ]
    for candidate in after["candidate_plans"]:
        candidate["session_fit_status"] = "stale"
        candidate["presentation_state"] = "dimmed"
    after.pop("active_candidate_ref")
    after.pop("selected_plan")
    after["map_state"]["presentation"]["visible_candidate_refs"] = []
    after["map_state"]["presentation"]["highlighted_targets"] = []
    assert_session_transition(before, after, event["base_session_revision"])
    assert all(
        candidate["session_fit_status"] == "stale"
        for candidate in after["candidate_plans"]
    )
    assert "active_candidate_ref" not in after
    assert "selected_plan" not in after


def test_stale_map_event_and_map_action_cannot_apply():
    current = load_valid("session_state_plan_selected.json")
    event = load_valid("map_event_plan_confirmed.json")
    with pytest.raises(AssertionError):
        assert_event_semantics(event, current)
    map_action = load_valid("map_action_show_candidate_set.json")
    with pytest.raises(AssertionError):
        assert_map_action_batch([map_action], current)


def test_ride_object_event_revision_must_match_object():
    session = load_valid("session_state_candidates_presented.json")
    event = make_event(
        session,
        "ride_object_selected",
        {
            "object_ref": {
                "object_id": "route.fixture-plan-focus-a",
                "object_type": "named_route",
            },
            "revision_ref": {
                "object_ref": {
                    "object_id": "route.fixture-plan-focus-b",
                    "object_type": "named_route",
                },
                "revision": 1,
            },
            "selection_source": "map",
        },
    )
    with pytest.raises(AssertionError):
        assert_event_semantics(event, session)


def test_elevation_event_fraction_order_is_semantic():
    session = load_valid("session_state_candidates_presented.json")
    event = make_event(
        session,
        "elevation_range_selected",
        {
            "target_kind": "plan_leg",
            "target_ref": "leg.fixture-a-core",
            "from_fraction": 0.9,
            "to_fraction": 0.1,
        },
    )
    event["source_surface"] = "elevation_panel"
    with pytest.raises(AssertionError):
        assert_event_semantics(event, session)


def test_anchor_removed_must_reference_current_anchor():
    session = load_valid("session_state_candidates_presented.json")
    event = make_event(
        session,
        "anchor_removed",
        {"anchor_ref": "anchor.missing", "anchor_role": "waypoint"},
    )
    with pytest.raises(AssertionError):
        assert_event_semantics(event, session)


def test_map_event_payloads_are_discriminated(schemas, local_registry):
    event = load_valid("map_event_plan_confirmed.json")
    event["event_type"] = "viewport_changed"
    assert validation_errors("map_event", event, schemas, local_registry)


@pytest.mark.parametrize("mutation", ["sequence", "id", "session", "revision", "source"])
def test_nested_map_action_batch_identity_and_sequence_fail_closed(mutation):
    action = load_valid("agent_action_present_candidates.json")
    session = load_valid("session_state_candidates_before.json")
    first = action["map_actions"][0]
    second = deepcopy(first)
    second["map_action_id"] = "map-action.fixture-show-candidates-002"
    second["sequence"] = 2
    action["map_actions"].append(second)
    if mutation == "sequence":
        second["sequence"] = 3
    elif mutation == "id":
        second["map_action_id"] = first["map_action_id"]
    elif mutation == "session":
        second["session_id"] = "planning-session.other"
    elif mutation == "revision":
        second["base_session_revision"] = 2
    else:
        second["source_agent_action_ref"] = "agent-action.other"
    with pytest.raises(AssertionError):
        assert_map_action_batch(action["map_actions"], session, action)


def test_map_action_candidate_set_must_match_session_validation():
    map_action = load_valid("map_action_show_candidate_set.json")
    session = load_valid("session_state_candidates_before.json")
    map_action["payload"]["candidates"][0]["validation_result_ref"] = (
        "validation.fixture-wrong"
    )
    with pytest.raises(AssertionError):
        assert_map_action_batch([map_action], session)


def test_highlight_plan_leg_must_match_session_focused_leg():
    session = load_valid("session_state_candidates_before.json")
    candidate = session["candidate_plans"][0]
    session["focused_plan_leg"] = {
        "plan_revision_ref": deepcopy(candidate["plan_revision_ref"]),
        "leg_ref": "leg.fixture-a-core",
    }
    map_action = load_valid("map_action_show_candidate_set.json")
    map_action["action_type"] = "highlight_plan_leg"
    map_action["payload"] = {
        "plan_revision_ref": deepcopy(candidate["plan_revision_ref"]),
        "leg_ref": "leg.fixture-a-core",
        "highlight_role": "primary",
    }
    assert_map_action_batch([map_action], session)
    map_action["payload"]["leg_ref"] = "leg.fixture-missing"
    with pytest.raises(AssertionError):
        assert_map_action_batch([map_action], session)


def test_present_candidate_payload_and_map_set_must_match():
    action = load_valid("agent_action_present_candidates.json")
    run = load_valid("agent_run_candidate_completed.json")
    session = load_valid("session_state_candidates_before.json")
    action["map_actions"][0]["payload"]["candidates"].pop()
    with pytest.raises(AssertionError):
        assert_agent_action_semantics(action, run, session)


def test_present_candidate_duplicate_ref_is_rejected_semantically():
    action = load_valid("agent_action_present_candidates.json")
    duplicate = deepcopy(action["payload"]["candidates"][0])
    duplicate["plan_revision_ref"]["object_ref"]["object_id"] = "ride-plan.fixture-c"
    action["payload"]["candidates"].append(duplicate)
    run = load_valid("agent_run_candidate_completed.json")
    session = load_valid("session_state_candidates_before.json")
    with pytest.raises(AssertionError, match="candidate_ref"):
        assert_agent_action_semantics(action, run, session)


def test_agent_action_run_session_and_turn_binding_fail_closed():
    action = load_valid("agent_action_ask_clarification.json")
    run = load_valid("agent_run_clarification_paused.json")
    session = load_valid("session_state_clarification_r3.json")
    for field, value in (
        ("run_id", "agent-run.other"),
        ("session_id", "planning-session.other"),
        ("base_session_revision", 2),
        ("model_turn_index", 2),
        ("action_id", "agent-action.unregistered"),
    ):
        mutated = deepcopy(action)
        mutated[field] = value
        with pytest.raises(AssertionError):
            assert_agent_action_semantics(mutated, run, session)


def test_agent_cannot_finalize_plan_selection_without_user_event():
    action = load_valid("agent_action_ask_clarification.json")
    action["action_type"] = "finalize_response"
    action["payload"] = {
        "response_ref": "response.fixture-invalid-selection",
        "outcome_kind": "plan_selected",
        "user_safe_message": "已选择候选。",
        "supporting_refs": ["candidate.fixture-a"],
    }
    run = load_valid("agent_run_clarification_paused.json")
    session = load_valid("session_state_clarification_r3.json")
    with pytest.raises(AssertionError):
        assert_agent_action_semantics(action, run, session)


def test_agent_can_report_plan_selected_only_after_user_event():
    action = load_valid("agent_action_present_candidates.json")
    action["action_type"] = "finalize_response"
    action["payload"] = {
        "response_ref": "response.fixture-selection",
        "outcome_kind": "plan_selected",
        "user_safe_message": "已记录你明确选择的候选 B。",
        "supporting_refs": [
            "candidate.fixture-b",
            "map-event.fixture-plan-confirmed-002",
        ],
    }
    action["map_actions"] = []
    action["base_session_revision"] = 3
    run = load_valid("agent_run_candidate_completed.json")
    run["base_session_revision"] = 3
    run["session_commit"]["expected_base_revision"] = 3
    run["session_commit"]["committed_revision"] = 4
    session = load_valid("session_state_plan_selected.json")
    event = load_valid("map_event_plan_confirmed.json")
    assert_agent_action_semantics(action, run, session, event)


def test_no_result_is_valid_and_not_an_empty_candidate_success(
    schemas, local_registry
):
    action = load_valid("agent_action_ask_clarification.json")
    action["action_type"] = "no_result"
    action["payload"] = {
        "reason_code": "insufficient_information",
        "user_safe_message": "信息不足，暂时不能给出可验证候选。",
        "blocking_unknown_refs": ["unknown.fixture-location-destination-001"],
        "suggested_next_step": "clarify_intent",
    }
    assert not validation_errors("agent_action", action, schemas, local_registry)
    run = load_valid("agent_run_clarification_paused.json")
    session = load_valid("session_state_clarification_r3.json")
    assert_agent_action_semantics(action, run, session)


def test_propose_tool_call_is_ref_only_and_cannot_embed_tool_identity(
    schemas, local_registry
):
    action = load_valid("agent_action_propose_tool_call.json")
    assert not validation_errors("agent_action", action, schemas, local_registry)
    action["payload"]["tool_name"] = "planning.retrieve_world_context"
    assert validation_errors("agent_action", action, schemas, local_registry)


@pytest.mark.parametrize("answer_mode", ["single_choice", "multi_choice"])
def test_choice_answer_modes_require_two_to_six_unique_choices(
    answer_mode, schemas, local_registry
):
    action = load_valid("agent_action_ask_clarification.json")
    action["payload"]["answer_mode"] = answer_mode
    action["payload"]["choices"] = [
        {"choice_id": "choice.fixture-a", "user_safe_label": "选项 A"},
        {"choice_id": "choice.fixture-b", "user_safe_label": "选项 B"},
    ]
    assert not validation_errors("agent_action", action, schemas, local_registry)
    action["payload"]["choices"] = action["payload"]["choices"][:1]
    assert validation_errors("agent_action", action, schemas, local_registry)


def test_non_choice_answer_mode_cannot_smuggle_choices(schemas, local_registry):
    action = load_valid("agent_action_ask_clarification.json")
    action["payload"]["choices"] = [
        {"choice_id": "choice.fixture-a", "user_safe_label": "选项 A"},
        {"choice_id": "choice.fixture-b", "user_safe_label": "选项 B"},
    ]
    assert validation_errors("agent_action", action, schemas, local_registry)


def test_duplicate_choice_ids_are_rejected_semantically():
    action = load_valid("agent_action_ask_clarification.json")
    action["payload"]["answer_mode"] = "single_choice"
    action["payload"]["choices"] = [
        {"choice_id": "choice.fixture-a", "user_safe_label": "选项 A"},
        {"choice_id": "choice.fixture-a", "user_safe_label": "选项 B"},
    ]
    run = load_valid("agent_run_clarification_paused.json")
    session = load_valid("session_state_clarification_r3.json")
    with pytest.raises(AssertionError):
        assert_agent_action_semantics(action, run, session)


def test_request_confirmation_cannot_express_exact_approval_or_effect(
    schemas, local_registry
):
    action = load_valid("agent_action_ask_clarification.json")
    action["action_type"] = "request_confirmation"
    action["payload"] = {
        "confirmation_ref": "confirmation.fixture-invalid-effect",
        "confirmation_kind": "export_confirmation",
        "target_refs": ["candidate.fixture-a"],
        "exact_summary": "导出路线",
        "user_safe_question": "确认导出吗？",
    }
    assert validation_errors("agent_action", action, schemas, local_registry)


def test_finalize_response_cannot_claim_external_effect(schemas, local_registry):
    action = load_valid("agent_action_ask_clarification.json")
    action["action_type"] = "finalize_response"
    action["payload"] = {
        "response_ref": "response.fixture-invalid-effect",
        "outcome_kind": "export_created",
        "user_safe_message": "已导出。",
        "supporting_refs": [],
    }
    assert validation_errors("agent_action", action, schemas, local_registry)


def test_metadata_cannot_carry_coordinates_or_frontend_command(
    schemas, local_registry
):
    session = load_valid("session_state_clarification_r3.json")
    session["metadata"]["x-coordinates"] = "112.5,37.8"
    assert validation_errors("session_state", session, schemas, local_registry)
    map_action = load_valid("map_action_show_candidate_set.json")
    map_action["metadata"]["x-frontend-command"] = {"name": "execute"}
    assert validation_errors("map_action", map_action, schemas, local_registry)


@pytest.mark.parametrize(
    "metadata_key",
    [
        "x-session-status",
        "x-validation-result",
        "x-tool-payload",
        "x-approval-state",
        "x-provenance-ref",
        "x-side-effect",
    ],
)
def test_metadata_cannot_become_a_second_state_or_effect_channel(metadata_key):
    session = load_valid("session_state_clarification_r3.json")
    session["metadata"][metadata_key] = "forbidden"
    with pytest.raises(AssertionError, match=metadata_key):
        assert_session_semantics(session)


def test_payload_cannot_carry_coordinates_or_frontend_command(
    schemas, local_registry
):
    event = load_valid("map_event_plan_confirmed.json")
    event["payload"]["coordinates"] = [112.5, 37.8]
    assert validation_errors("map_event", event, schemas, local_registry)
    map_action = load_valid("map_action_show_candidate_set.json")
    map_action["payload"]["frontend_command"] = "execute"
    assert validation_errors("map_action", map_action, schemas, local_registry)


def test_valid_fixtures_never_embed_forbidden_private_or_runtime_material():
    for fixture_name in VALID_FIXTURE_SCHEMAS:
        instance = load_valid(fixture_name)
        normalized_keys = {key.lower().replace("-", "_") for key in walk_keys(instance)}
        assert not (normalized_keys & FORBIDDEN_FIXTURE_KEYS), fixture_name
        serialized = json.dumps(instance, ensure_ascii=False).lower()
        for forbidden_text in (
            "raw provider",
            "raw_provider",
            "raw track",
            "full transcript",
            "approval grant",
            "side-effect ledger",
            "canonical write",
            "export artifact",
            "agent runtime",
            "typescript shadow service",
            "openai agents sdk",
            "linestring(",
            "polygon((",
            "featurecollection",
        ):
            assert forbidden_text not in serialized, (fixture_name, forbidden_text)


def test_all_map_location_handles_keep_exact_coordinates_hidden():
    for fixture_name in VALID_FIXTURE_SCHEMAS:
        instance = load_valid(fixture_name)

        def visit(value):
            if isinstance(value, dict):
                if "location_handle" in value:
                    assert value["location_handle"]["exact_coordinates_exposed"] is False
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(instance)


def test_session_is_working_state_not_transcript_or_world_fact_copy(
    schemas, local_registry
):
    session = load_valid("session_state_clarification_r3.json")
    for forbidden_field in ("messages", "chat_history", "world_facts", "memory_body"):
        mutated = deepcopy(session)
        mutated[forbidden_field] = []
        assert validation_errors("session_state", mutated, schemas, local_registry)


def test_map_action_is_declarative_and_reducer_required(schemas, local_registry):
    map_action = load_valid("map_action_show_candidate_set.json")
    map_action["reducer_required"] = False
    assert validation_errors("map_action", map_action, schemas, local_registry)
    map_action = load_valid("map_action_show_candidate_set.json")
    map_action["payload"]["style"] = {"color": "red"}
    assert validation_errors("map_action", map_action, schemas, local_registry)


def test_agent_action_is_always_proposal_only(schemas, local_registry):
    action = load_valid("agent_action_present_candidates.json")
    action["proposal_only"] = False
    assert validation_errors("agent_action", action, schemas, local_registry)


def test_schema_resolution_never_uses_network(schemas, local_registry):
    for fixture_name, schema_name in VALID_FIXTURE_SCHEMAS.items():
        assert not validation_errors(
            schema_name, load_valid(fixture_name), schemas, local_registry
        )
    _, unexpected_retrievals = local_registry
    assert unexpected_retrievals == []
