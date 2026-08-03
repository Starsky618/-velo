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
    "map_action": "map_action.schema.json",
    "agent_action": "agent_action.schema.json",
    "tool_registry": "tool_registry.schema.json",
    "tool_call": "tool_call.schema.json",
    "tool_result": "tool_result.schema.json",
}

A2_3A_SCHEMA_FILES = {
    "tool_registry": "tool_registry.schema.json",
    "tool_call": "tool_call.schema.json",
    "tool_result": "tool_result.schema.json",
}

VALID_FIXTURE_SCHEMAS = {
    "context_manifest_candidate_presentation_turn_2.json": "context_manifest",
    "agent_action_propose_tool_call.json": "agent_action",
    "tool_call_generate_candidate_plans.json": "tool_call",
    "tool_result_generate_candidate_plans_succeeded.json": "tool_result",
    "tool_result_resolve_ride_object_ambiguous.json": "tool_result",
    "tool_result_generate_candidate_plans_no_result.json": "tool_result",
    "tool_result_generate_candidate_plans_timed_out.json": "tool_result",
    "tool_result_generate_candidate_plans_disconnected.json": "tool_result",
    "tool_result_generate_candidate_plans_retry_succeeded.json": "tool_result",
    "tool_result_validate_plan_succeeded.json": "tool_result",
    "tool_result_validate_plan_failed.json": "tool_result",
    "tool_result_prepare_export_succeeded.json": "tool_result",
    "tool_result_revise_plan_succeeded.json": "tool_result",
}

INVALID_SHAPE_FIXTURES = {
    "tool_call_embedded_arguments_or_coordinates.json": "tool_call",
    "tool_call_claims_approval_or_execution.json": "tool_call",
    "tool_result_raw_provider_payload.json": "tool_result",
    "tool_result_success_without_typed_ref.json": "tool_result",
    "tool_result_failure_with_success_ref.json": "tool_result",
    "tool_result_prepare_export_artifact.json": "tool_result",
    "tool_result_retry_same_call_marked_terminal.json": "tool_result",
    "tool_result_revise_plan_non_ride_plan_revision.json": "tool_result",
}

EXPECTED_TOOL_MAPPING = {
    "planning.resolve_ride_object": {
        "capability_id": "world.resolve",
        "effect_scope": "READ",
        "approval_mode": "NONE",
        "purpose_code": "resolve_ride_object",
        "input_kind": "ride_object_resolution_request",
        "observation_kind": "ride_object_resolution",
        "provider_access": "NONE",
    },
    "planning.retrieve_rider_context": {
        "capability_id": "user_context.read_authorized",
        "effect_scope": "READ",
        "approval_mode": "NONE",
        "purpose_code": "retrieve_rider_context",
        "input_kind": "rider_context_request",
        "observation_kind": "rider_context_packet",
        "provider_access": "NONE",
    },
    "planning.retrieve_world_context": {
        "capability_id": "world.read",
        "effect_scope": "READ",
        "approval_mode": "NONE",
        "purpose_code": "retrieve_world_context",
        "input_kind": "world_context_request",
        "observation_kind": "world_fact_packet",
        "provider_access": "NONE",
    },
    "planning.generate_candidate_plans": {
        "capability_id": "plan.draft.create",
        "effect_scope": "PROVIDER_QUERY",
        "approval_mode": "EXPLICIT_INTENT",
        "purpose_code": "generate_candidate_plans",
        "input_kind": "candidate_plan_generation_request",
        "observation_kind": "candidate_plan_set",
        "provider_access": "DOMAIN_MEDIATED",
    },
    "planning.revise_plan": {
        "capability_id": "plan.draft.revise",
        "effect_scope": "SESSION",
        "approval_mode": "NONE",
        "purpose_code": "revise_plan",
        "input_kind": "ride_plan_revision_request",
        "observation_kind": "ride_plan_revision",
        "provider_access": "NONE",
    },
    "planning.validate_plan": {
        "capability_id": "plan.validate",
        "effect_scope": "READ",
        "approval_mode": "NONE",
        "purpose_code": "validate_plan",
        "input_kind": "ride_plan_validation_request",
        "observation_kind": "plan_validation",
        "provider_access": "NONE",
    },
    "planning.compare_plans": {
        "capability_id": "plan.compare",
        "effect_scope": "READ",
        "approval_mode": "NONE",
        "purpose_code": "compare_plans",
        "input_kind": "plan_comparison_request",
        "observation_kind": "plan_comparison",
        "provider_access": "NONE",
    },
    "planning.prepare_export": {
        "capability_id": "export.prepare",
        "effect_scope": "READ",
        "approval_mode": "NONE",
        "purpose_code": "prepare_export",
        "input_kind": "export_preview_request",
        "observation_kind": "export_preview",
        "provider_access": "NONE",
    },
}

FORBIDDEN_TOOL_NAMES = {
    "raw_tencent_api",
    "raw_tencent_direction",
    "raw_provider",
    "raw_sql",
    "orm_write",
    "shell",
    "arbitrary_network",
    "write_geometry",
    "direct_gpx_generator",
    "create_route_export",
    "publish_traversal",
    "accept_claim",
    "activate_dynamic_state",
    "world.publish",
    "claim.accept",
    "route.activate",
    "user_data.admin_read",
    "planning.select_plan",
    "export.commit",
    "contribution.submit",
    "memory.save",
    "saved_place.create",
}

FORBIDDEN_CALL_KEYS = {
    "approved",
    "approval_grant",
    "approval_request_id",
    "proposed_effect_id",
    "effect_identity",
    "effect_status",
    "execution_status",
    "executed",
    "committed",
    "ledger",
    "idempotency_key",
    "provider_request",
    "provider_payload",
    "raw_arguments",
    "arguments",
    "coordinates",
    "latitude",
    "longitude",
    "lat",
    "lon",
    "lng",
    "polyline",
    "sql",
    "orm",
    "shell",
}

FORBIDDEN_METADATA_FRAGMENTS = {
    "approval",
    "capability",
    "canonical",
    "coordinate",
    "effect",
    "execution",
    "external-effect",
    "provider",
    "real-network",
    "result-status",
    "tool-name",
}

AUTHORITATIVE_CALL_FIELDS = (
    "schema_version",
    "environment",
    "fixture_only",
    "run_id",
    "session_id",
    "base_session_revision",
    "model_turn_index",
    "requested_by_agent_action_ref",
    "tool_registry_id",
    "tool_registry_version",
    "tool_name",
    "tool_version",
    "capability_id",
    "purpose_code",
    "input",
    "expected_observation_kind",
    "proposal_only",
    "proposed_at",
)

STATUS_RULES = {
    "succeeded": ("TOOL_SUCCEEDED", {"NOT_APPLICABLE"}, 1, None),
    "ambiguous": ("TOOL_AMBIGUOUS", {"ASK_USER"}, 2, None),
    "no_result": ("TOOL_NO_RESULT", {"DO_NOT_RETRY", "REVISE_REQUEST"}, 0, 0),
    "timed_out": (
        "TOOL_TIMEOUT",
        {"RETRY_SAME_CALL", "DO_NOT_RETRY", "DEFER"},
        0,
        0,
    ),
    "disconnected": (
        "TOOL_DISCONNECTED",
        {"RETRY_SAME_CALL", "DO_NOT_RETRY", "DEFER"},
        0,
        0,
    ),
    "failed": ("TOOL_HARD_FAIL", {"DO_NOT_RETRY", "REVISE_REQUEST"}, 0, 0),
}

DOMAIN_REASON_RULES = {
    ("succeeded", "TERMINAL", "NOT_APPLICABLE"): None,
    ("ambiguous", "TERMINAL", "ASK_USER"): None,
    ("no_result", "TERMINAL", "DO_NOT_RETRY"): {
        "NO_MATCHING_RESULT",
        "INSUFFICIENT_WORLD_DATA",
    },
    ("no_result", "TERMINAL", "REVISE_REQUEST"): {
        "NO_MATCHING_RESULT",
        "INSUFFICIENT_WORLD_DATA",
    },
    ("timed_out", "INTERMEDIATE", "RETRY_SAME_CALL"): {
        "TOOL_ATTEMPT_TIMEOUT"
    },
    ("timed_out", "TERMINAL", "DO_NOT_RETRY"): {"TOOL_ATTEMPT_TIMEOUT"},
    ("timed_out", "TERMINAL", "DEFER"): {"RUN_DEADLINE_EXCEEDED"},
    ("disconnected", "INTERMEDIATE", "RETRY_SAME_CALL"): {
        "DOMAIN_SERVICE_DISCONNECTED"
    },
    ("disconnected", "TERMINAL", "DO_NOT_RETRY"): {
        "DOMAIN_SERVICE_DISCONNECTED"
    },
    ("disconnected", "TERMINAL", "DEFER"): {
        "DOMAIN_SERVICE_DISCONNECTED"
    },
    ("failed", "TERMINAL", "DO_NOT_RETRY"): {
        "DETERMINISTIC_VALIDATION_REJECTED",
        "DOMAIN_SERVICE_FAILURE",
    },
    ("failed", "TERMINAL", "REVISE_REQUEST"): {
        "DETERMINISTIC_VALIDATION_REJECTED",
        "DOMAIN_SERVICE_FAILURE",
    },
}


def load_json(path):
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def load_valid(name):
    return load_json(VALID_FIXTURES / name)


def load_invalid(name):
    return load_json(INVALID_FIXTURES / name)


def parse_rfc3339(value):
    normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    assert parsed.tzinfo is not None and parsed.utcoffset() is not None
    return parsed


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


def validation_errors(schema_name, instance, schemas, local_registry):
    registry, _ = local_registry
    validator = Draft202012Validator(
        schemas[schema_name],
        registry=registry,
        format_checker=FormatChecker(),
    )
    return sorted(validator.iter_errors(instance), key=lambda error: list(error.path))


def tool_map(registry):
    return {tool["tool_name"]: tool for tool in registry["tools"]}


def assert_metadata_non_authoritative(metadata):
    normalized = {key.lower().replace("_", "-") for key in metadata}
    for key in normalized:
        assert not any(fragment in key for fragment in FORBIDDEN_METADATA_FRAGMENTS), key


def assert_registry_semantics(registry):
    assert registry["default_decision"] == "DENY"
    assert registry["state_owner"] == "deterministic_control_plane"
    assert registry["registry_scope"] == "online_static_planning"
    assert registry["created_at"] == "2026-08-04T03:03:00+08:00"
    tools = registry["tools"]
    names = [tool["tool_name"] for tool in tools]
    identities = [(tool["tool_name"], tool["tool_version"]) for tool in tools]
    assert len(names) == len(set(names)) == 8
    assert len(identities) == len(set(identities)) == 8
    assert set(names) == set(EXPECTED_TOOL_MAPPING)
    assert not (set(names) & FORBIDDEN_TOOL_NAMES)
    assert "planning.select_plan" not in names
    assert "export.commit" not in names

    policy = registry["environment_policy"]
    assert policy["test"] == {
        "execution_mode": "FAKE_ONLY",
        "real_network_allowed": False,
        "real_external_effect_allowed": False,
    }
    assert policy["shadow"] == {
        "execution_mode": "RECORDED_OR_FAKE_ONLY",
        "real_network_allowed": False,
        "real_external_effect_allowed": False,
    }
    assert policy["production"] == {
        "execution_mode": "DETERMINISTIC_DOMAIN_SERVICE_ONLY",
        "agent_direct_network_allowed": False,
        "agent_direct_database_allowed": False,
        "agent_direct_storage_allowed": False,
    }

    for tool in tools:
        expected = EXPECTED_TOOL_MAPPING[tool["tool_name"]]
        for field, value in expected.items():
            assert tool[field] == value, (tool["tool_name"], field)
        assert tool["execution_owner"] == "deterministic_domain_plane"
        assert tool["tool_version"] == registry["registry_version"]
        if tool["tool_name"] == "planning.generate_candidate_plans":
            assert tool["reversibility"] == "IRREVERSIBLE_EXTERNAL_DISCLOSURE"
        elif tool["tool_name"] == "planning.revise_plan":
            assert tool["reversibility"] == "REVERSIBLE_SESSION_ARTIFACT"
        else:
            assert tool["reversibility"] == "NO_PERSISTENT_EFFECT"
        assert tool["model_exposure"] == {
            "opaque_input_refs_only": True,
            "typed_observation_only": True,
            "raw_provider_payload_exposed": False,
            "exact_coordinates_exposed": False,
            "direct_database_handle_exposed": False,
            "direct_storage_handle_exposed": False,
        }
        assert tool["timeout_policy"] == {
            "owner": "deterministic_run_controller",
            "bounded_by_run_deadline": True,
        }
        assert tool["retry_policy"] == {
            "owner": "deterministic_run_controller",
            "bounded_by_run_budget": True,
            "model_may_extend": False,
            "effect_reconciliation_required": (
                tool["tool_name"] == "planning.generate_candidate_plans"
            ),
        }
        effect = tool["effect_contract"]
        assert effect["produces_external_artifact"] is False
        assert effect["writes_canonical_world"] is False
        assert effect["writes_personal_asset"] is False
        assert effect["produces_session_artifact"] is (
            tool["tool_name"]
            in {"planning.generate_candidate_plans", "planning.revise_plan"}
        )
        expected_disclosure = (
            "MINIMIZED_DOMAIN_MEDIATED"
            if tool["tool_name"] == "planning.generate_candidate_plans"
            else "NONE"
        )
        assert effect["external_provider_disclosure"] == expected_disclosure
        if tool["tool_name"] == "planning.generate_candidate_plans":
            assert (
                "EXTERNAL_PROVIDER_MINIMIZED_DISCLOSURE"
                in tool["data_classifications"]
            )
        else:
            assert (
                "EXTERNAL_PROVIDER_MINIMIZED_DISCLOSURE"
                not in tool["data_classifications"]
            )
        dedupe = tool["request_deduplication"]
        assert dedupe["identity_field"] == "tool_call_id"
        if tool["tool_name"] in {
            "planning.generate_candidate_plans",
            "planning.revise_plan",
        }:
            assert dedupe["mode"] == "REQUIRED_FOR_RETRY"
            assert dedupe["same_tool_call_id_required_for_retry"] is True
        else:
            assert dedupe["mode"] == "OPTIONAL"
    assert tool_map(registry)["planning.prepare_export"]["effect_contract"] == {
        "produces_external_artifact": False,
        "writes_canonical_world": False,
        "writes_personal_asset": False,
        "produces_session_artifact": False,
        "external_provider_disclosure": "NONE",
    }
    assert_metadata_non_authoritative(registry["metadata"])


def assert_call_semantics(call, registry, action=None, run=None, session=None):
    registered = tool_map(registry)
    assert call["tool_name"] in registered
    definition = registered[call["tool_name"]]
    assert call["tool_registry_id"] == registry["registry_id"]
    assert call["tool_registry_version"] == registry["registry_version"]
    for field in ("tool_version", "capability_id", "purpose_code"):
        assert call[field] == definition[field]
    assert call["input"]["input_kind"] == definition["input_kind"]
    assert call["expected_observation_kind"] == definition["observation_kind"]
    assert call["proposal_only"] is True
    assert not (set(walk_keys(call)) & FORBIDDEN_CALL_KEYS)
    assert_metadata_non_authoritative(call["metadata"])

    if action is not None:
        assert action["action_type"] == "propose_tool_call"
        assert action["payload"] == {"tool_call_ref": call["tool_call_id"]}
        assert call["requested_by_agent_action_ref"] == action["action_id"]
        for field in (
            "environment",
            "fixture_only",
            "run_id",
            "session_id",
            "base_session_revision",
            "model_turn_index",
        ):
            assert call[field] == action[field]
        assert parse_rfc3339(action["proposed_at"]) <= parse_rfc3339(
            call["proposed_at"]
        )
        assert action["map_actions"] == []
    if run is not None:
        assert call["tool_call_id"] in run["tool_call_refs"]
        assert call["requested_by_agent_action_ref"] in run["action_proposal_refs"]
        assert call["run_id"] == run["run_id"]
        assert call["model_turn_index"] <= run["budget"]["consumed"]["model_turns"]
        assert parse_rfc3339(run["started_at"]) <= parse_rfc3339(call["proposed_at"])
        assert parse_rfc3339(call["proposed_at"]) <= parse_rfc3339(
            run["last_checkpoint_at"]
        )
    if session is not None:
        assert call["session_id"] == session["session_id"]
        assert call["base_session_revision"] == session["session_revision"]
    artifacts = [item for item in (action, run, session) if item is not None]
    for artifact in artifacts:
        assert call["environment"] == artifact["environment"]
        assert call["fixture_only"] is artifact["fixture_only"]


def assert_immutable_tool_call_identity(calls):
    requests_by_id = {}
    for call in calls:
        request = {field: call[field] for field in AUTHORITATIVE_CALL_FIELDS}
        previous = requests_by_id.setdefault(call["tool_call_id"], request)
        assert request == previous


def result_ref_kinds(result):
    return {
        ref.get(
            "contract_kind",
            ref.get(
                "packet_type",
                (
                    "ride_plan_revision"
                    if ref.get("object_ref", {}).get("object_type") == "ride_plan"
                    else "non_ride_plan_revision"
                ),
            ),
        )
        for ref in result["result_refs"]
    }


def assert_result_semantics(result, call, registry, run=None, session=None):
    definition = tool_map(registry)[call["tool_name"]]
    for field in (
        "environment",
        "fixture_only",
        "tool_call_id",
        "run_id",
        "session_id",
        "base_session_revision",
        "tool_registry_id",
        "tool_registry_version",
        "tool_name",
        "tool_version",
        "capability_id",
    ):
        assert result[field] == call[field], field
    assert result["observation_kind"] == call["expected_observation_kind"]
    assert result["observation_kind"] == definition["observation_kind"]
    assert result["observation_only"] is True
    assert result["raw_provider_payload_exposed"] is False
    assert result["exact_coordinates_exposed"] is False
    assert result["canonical_fact_claimed"] is False
    assert result["attempt_index"] >= 1
    assert_metadata_non_authoritative(result["metadata"])
    assert not (set(walk_keys(result)) & {"provider_payload", "coordinates", "latitude", "longitude", "lat", "lon", "lng", "polyline"})

    expected_code, retry_values, min_refs, max_refs = STATUS_RULES[
        result["result_status"]
    ]
    assert result["result_code"] == expected_code
    assert result["retry_disposition"] in retry_values
    assert len(result["result_refs"]) >= min_refs
    if max_refs is not None:
        assert len(result["result_refs"]) <= max_refs
        assert "domain_reason_code" in result

    reason_key = (
        result["result_status"],
        result["result_finality"],
        result["retry_disposition"],
    )
    assert reason_key in DOMAIN_REASON_RULES
    allowed_reasons = DOMAIN_REASON_RULES[reason_key]
    if allowed_reasons is None:
        assert "domain_reason_code" not in result
    else:
        assert result["domain_reason_code"] in allowed_reasons
    if result["retry_disposition"] == "RETRY_SAME_CALL":
        assert result["result_finality"] == "INTERMEDIATE"
    if result["result_finality"] == "INTERMEDIATE":
        assert result["result_status"] in {"timed_out", "disconnected"}
        assert result["retry_disposition"] == "RETRY_SAME_CALL"

    allowed_ref_kinds = {
        "ride_object_resolution": {"ride_object_resolution"},
        "rider_context_packet": {"rider_context_packet"},
        "world_fact_packet": {"world_fact_packet"},
        "candidate_plan_set": {"candidate_plan_set"},
        "ride_plan_revision": {"ride_plan_revision"},
        "plan_validation": {"plan_validation"},
        "plan_comparison": {"plan_comparison"},
        "export_preview": {"export_preview"},
    }[result["observation_kind"]]
    assert result_ref_kinds(result) <= allowed_ref_kinds
    if result["tool_name"] == "planning.prepare_export" and result["result_status"] == "succeeded":
        assert result_ref_kinds(result) == {"export_preview"}
    if result["tool_name"] == "planning.validate_plan" and result["result_status"] == "succeeded":
        assert result_ref_kinds(result) == {"plan_validation"}
    assert parse_rfc3339(call["proposed_at"]) <= parse_rfc3339(result["observed_at"])
    if run is not None:
        assert result["observation_id"] in run["observation_refs"]
        assert parse_rfc3339(result["observed_at"]) <= parse_rfc3339(
            run["last_checkpoint_at"]
        )
    if session is not None:
        assert result["session_id"] == session["session_id"]
        assert result["base_session_revision"] == session["session_revision"]


def assert_attempt_chain(call, results, registry, run):
    assert results
    assert call["tool_name"] in tool_map(registry)
    assert_immutable_tool_call_identity([call])
    assert all(result["tool_call_id"] == call["tool_call_id"] for result in results)
    assert [result["attempt_index"] for result in results] == list(
        range(1, len(results) + 1)
    )
    assert len({result["attempt_index"] for result in results}) == len(results)
    assert len({result["observation_id"] for result in results}) == len(results)
    observed_times = [parse_rfc3339(result["observed_at"]) for result in results]
    assert observed_times == sorted(observed_times)

    terminal_positions = [
        index
        for index, result in enumerate(results)
        if result["result_finality"] == "TERMINAL"
    ]
    assert len(terminal_positions) <= 1
    if terminal_positions:
        assert terminal_positions == [len(results) - 1]
    if run["run_status"] == "stopped":
        assert len(terminal_positions) == 1
    else:
        assert run["run_status"] in {"running", "paused"}

    for result in results:
        assert_result_semantics(result, call, registry)
    assert run["tool_call_refs"] == [call["tool_call_id"]]
    assert run["observation_refs"] == [
        result["observation_id"] for result in results
    ]
    assert run["budget"]["consumed"]["tool_calls"] == len(results)
    assert len(run["tool_call_refs"]) <= run["budget"]["consumed"]["tool_calls"]
    retry_entries = {
        item["tool_name"]: item["retries"]
        for item in run["budget"]["tool_retry_counters"]
    }
    assert retry_entries[call["tool_name"]] == len(results) - 1
    assert (
        retry_entries[call["tool_name"]]
        <= run["budget"]["limits"]["max_same_tool_retries"]
    )
    assert run["budget"]["consumed"]["tool_calls"] <= run["budget"]["limits"][
        "max_tool_calls"
    ]


def call_for_result(result, registry):
    definition = tool_map(registry)[result["tool_name"]]
    return {
        "schema_version": "0.1.0",
        "environment": result["environment"],
        "fixture_only": result["fixture_only"],
        "tool_call_id": result["tool_call_id"],
        "run_id": result["run_id"],
        "session_id": result["session_id"],
        "base_session_revision": result["base_session_revision"],
        "model_turn_index": 1,
        "requested_by_agent_action_ref": "agent-action.fixture-outcome-001",
        "tool_registry_id": registry["registry_id"],
        "tool_registry_version": registry["registry_version"],
        "tool_name": result["tool_name"],
        "tool_version": definition["tool_version"],
        "capability_id": definition["capability_id"],
        "purpose_code": definition["purpose_code"],
        "input": {
            "input_kind": definition["input_kind"],
            "input_ref": "tool-input.fixture-outcome-001",
            "input_revision": 1,
            "input_schema_version": "0.1.0",
            "target_revision_refs": [],
        },
        "expected_observation_kind": definition["observation_kind"],
        "proposed_at": "2026-08-03T20:09:30+08:00",
        "proposal_only": True,
        "metadata": {"x-fixture": True},
    }


def integrated_scenario():
    manifest_turn_1 = load_valid("context_manifest.json")
    manifest_turn_2 = load_valid(
        "context_manifest_candidate_presentation_turn_2.json"
    )
    return {
        "registry": load_json(CONTRACT_DIR / "tool_registry.v0.json"),
        "session": load_valid("session_state_candidates_before.json"),
        "run": load_valid("agent_run_candidate_completed.json"),
        "manifest_turn_1": manifest_turn_1,
        "manifest_turn_2": manifest_turn_2,
        "proposal": load_valid("agent_action_propose_tool_call.json"),
        "call": load_valid("tool_call_generate_candidate_plans.json"),
        "result": load_valid("tool_result_generate_candidate_plans_succeeded.json"),
        "presentation": load_valid("agent_action_present_candidates.json"),
    }


def revision_ref_keys(refs):
    return {json.dumps(ref, sort_keys=True) for ref in refs}


def assert_integrated_scenario(scenario):
    registry = scenario["registry"]
    session = scenario["session"]
    run = scenario["run"]
    manifests = [scenario["manifest_turn_1"], scenario["manifest_turn_2"]]
    actions = [scenario["proposal"], scenario["presentation"]]
    call = scenario["call"]
    result = scenario["result"]

    assert_registry_semantics(registry)
    assert run["budget"]["consumed"]["model_turns"] == 2
    assert run["budget"]["consumed"]["tool_calls"] == 1
    assert run["budget"]["consumed"]["plan_generations"] == 1
    assert run["context_manifest_refs"] == [item["manifest_id"] for item in manifests]
    assert run["action_proposal_refs"] == [item["action_id"] for item in actions]
    assert len(run["action_proposal_refs"]) == run["budget"]["consumed"]["model_turns"]
    assert run["tool_call_refs"] == [call["tool_call_id"]]
    assert run["observation_refs"] == [result["observation_id"]]
    assert run["budget"]["tool_retry_counters"] == [
        {"tool_name": "planning.generate_candidate_plans", "retries": 0}
    ]
    assert_attempt_chain(call, [result], registry, run)

    for manifest in manifests:
        assert manifest["packet_environment"] == session["environment"]
        assert manifest["session_id"] == session["session_id"]
        assert manifest["run_id"] == run["run_id"]
        assert manifest["session_revision"] == session["session_revision"]
        assert manifest["tool_registry_version"] == registry["registry_version"]
    assert [action["model_turn_index"] for action in actions] == [1, 2]
    assert_call_semantics(call, registry, actions[0], run, session)
    assert_result_semantics(result, call, registry, run, session)
    assert actions[1]["action_type"] == "present_valid_candidates"
    assert actions[1]["model_turn_index"] == 2
    assert all(
        candidate["validation_result_ref"]
        for candidate in actions[1]["payload"]["candidates"]
    )
    presented_plan_refs = [
        candidate["plan_revision_ref"]
        for candidate in actions[1]["payload"]["candidates"]
    ]
    assert revision_ref_keys(manifests[1]["plan_revision_refs"]) == (
        revision_ref_keys(presented_plan_refs)
    )
    assert manifests[0]["plan_revision_refs"] == []
    assert {
        "tool.observation.candidate_plan_set",
        "plan.candidate_summaries",
        "plan.validation_summaries",
    } <= set(manifests[1]["included_sections"])
    assert call["tool_name"] == "planning.generate_candidate_plans"
    assert len(manifests) == run["budget"]["consumed"]["model_turns"]
    assert parse_rfc3339(run["started_at"]) <= parse_rfc3339(
        manifests[0]["compiled_at"]
    )
    assert parse_rfc3339(manifests[0]["compiled_at"]) <= parse_rfc3339(
        actions[0]["proposed_at"]
    )
    assert parse_rfc3339(actions[0]["proposed_at"]) <= parse_rfc3339(
        call["proposed_at"]
    )
    assert parse_rfc3339(call["proposed_at"]) <= parse_rfc3339(
        result["observed_at"]
    )
    assert parse_rfc3339(result["observed_at"]) <= parse_rfc3339(
        manifests[1]["compiled_at"]
    )
    assert parse_rfc3339(manifests[1]["compiled_at"]) <= parse_rfc3339(
        actions[1]["proposed_at"]
    )
    assert parse_rfc3339(actions[1]["proposed_at"]) <= parse_rfc3339(
        run["last_checkpoint_at"]
    )


def test_three_schemas_are_valid_draft_2020_12_with_exact_ids(schemas):
    for name, filename in A2_3A_SCHEMA_FILES.items():
        schema = schemas[name]
        Draft202012Validator.check_schema(schema)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["$id"] == f"https://schemas.velo.invalid/agent_v0/{filename}"
        assert schema["additionalProperties"] is False


def test_schema_references_are_local_and_network_retrieval_is_rejected(
    schemas, local_registry
):
    allowed = set(SCHEMA_FILES.values())
    for name in A2_3A_SCHEMA_FILES:
        for ref in walk_refs(schemas[name]):
            assert not ref.startswith(("http://", "https://"))
            if not ref.startswith("#"):
                assert ref.split("#", 1)[0] in allowed
    for fixture_name, schema_name in VALID_FIXTURE_SCHEMAS.items():
        assert not validation_errors(
            schema_name, load_valid(fixture_name), schemas, local_registry
        )
    assert local_registry[1] == []


def test_registry_fixture_conforms_and_has_exact_semantics(schemas, local_registry):
    registry = load_json(CONTRACT_DIR / "tool_registry.v0.json")
    assert not validation_errors("tool_registry", registry, schemas, local_registry)
    assert_registry_semantics(registry)


def test_provider_query_effect_policy_preserves_irreversible_disclosure():
    tools = tool_map(load_json(CONTRACT_DIR / "tool_registry.v0.json"))
    generate = tools["planning.generate_candidate_plans"]
    assert {
        "effect_scope": generate["effect_scope"],
        "provider_access": generate["provider_access"],
        "reversibility": generate["reversibility"],
        "external_provider_disclosure": generate["effect_contract"][
            "external_provider_disclosure"
        ],
        "effect_reconciliation_required": generate["retry_policy"][
            "effect_reconciliation_required"
        ],
    } == {
        "effect_scope": "PROVIDER_QUERY",
        "provider_access": "DOMAIN_MEDIATED",
        "reversibility": "IRREVERSIBLE_EXTERNAL_DISCLOSURE",
        "external_provider_disclosure": "MINIMIZED_DOMAIN_MEDIATED",
        "effect_reconciliation_required": True,
    }
    assert generate["effect_contract"]["produces_session_artifact"] is True

    revise = tools["planning.revise_plan"]
    assert revise["reversibility"] == "REVERSIBLE_SESSION_ARTIFACT"
    assert revise["effect_contract"]["external_provider_disclosure"] == "NONE"
    no_persistent_effect = set(tools) - {
        "planning.generate_candidate_plans",
        "planning.revise_plan",
    }
    assert len(no_persistent_effect) == 6
    for tool_name in no_persistent_effect:
        assert tools[tool_name]["reversibility"] == "NO_PERSISTENT_EFFECT"
        assert (
            tools[tool_name]["effect_contract"]["external_provider_disclosure"]
            == "NONE"
        )
        assert (
            tools[tool_name]["retry_policy"]["effect_reconciliation_required"]
            is False
        )


def test_non_provider_tool_cannot_claim_provider_disclosure():
    registry = load_json(CONTRACT_DIR / "tool_registry.v0.json")
    tool_map(registry)["planning.retrieve_world_context"]["effect_contract"][
        "external_provider_disclosure"
    ] = "MINIMIZED_DOMAIN_MEDIATED"
    with pytest.raises(AssertionError):
        assert_registry_semantics(registry)


@pytest.mark.parametrize("fixture_name,schema_name", VALID_FIXTURE_SCHEMAS.items())
def test_valid_tool_fixtures_conform(
    fixture_name, schema_name, schemas, local_registry
):
    assert not validation_errors(
        schema_name, load_valid(fixture_name), schemas, local_registry
    )


@pytest.mark.parametrize("fixture_name,schema_name", INVALID_SHAPE_FIXTURES.items())
def test_invalid_shape_fixtures_fail_schema(
    fixture_name, schema_name, schemas, local_registry
):
    assert validation_errors(
        schema_name, load_invalid(fixture_name), schemas, local_registry
    )


def test_mismatched_identity_fixture_is_shape_valid_but_semantically_invalid(
    schemas, local_registry
):
    registry = load_json(CONTRACT_DIR / "tool_registry.v0.json")
    call = load_valid("tool_call_generate_candidate_plans.json")
    result = load_invalid("tool_result_mismatched_tool_identity.json")
    assert not validation_errors("tool_result", result, schemas, local_registry)
    with pytest.raises(AssertionError):
        assert_result_semantics(result, call, registry)


def test_full_session_run_action_call_result_presentation_scenario(
    schemas, local_registry
):
    scenario = integrated_scenario()
    for manifest_name in ("manifest_turn_1", "manifest_turn_2"):
        assert not validation_errors(
            "context_manifest", scenario[manifest_name], schemas, local_registry
        )
    for action_name in ("proposal", "presentation"):
        assert not validation_errors(
            "agent_action", scenario[action_name], schemas, local_registry
        )
    assert not validation_errors("tool_call", scenario["call"], schemas, local_registry)
    assert not validation_errors(
        "tool_result", scenario["result"], schemas, local_registry
    )
    assert_integrated_scenario(scenario)


@pytest.mark.parametrize(
    "field,value",
    [
        ("run_id", "agent-run.other"),
        ("session_id", "planning-session.other"),
        ("environment", "shadow"),
        ("fixture_only", False),
        ("base_session_revision", 2),
        ("model_turn_index", 2),
        ("tool_registry_version", "0.2.0"),
        ("tool_version", "0.2.0"),
        ("capability_id", "plan.compare"),
        ("purpose_code", "compare_plans"),
        ("expected_observation_kind", "plan_comparison"),
    ],
)
def test_call_cross_contract_mutations_fail_closed(field, value):
    scenario = integrated_scenario()
    scenario["call"][field] = value
    with pytest.raises(AssertionError):
        assert_integrated_scenario(scenario)


def test_wrong_input_kind_fails_registry_binding():
    scenario = integrated_scenario()
    scenario["call"]["input"]["input_kind"] = "plan_comparison_request"
    with pytest.raises(AssertionError):
        assert_integrated_scenario(scenario)


@pytest.mark.parametrize(
    "field_path,value",
    [
        (("input", "input_ref"), "candidate-plan-request.fixture-other"),
        (("input", "input_revision"), 2),
        (
            ("input", "target_revision_refs"),
            [
                {
                    "object_ref": {
                        "object_id": "ride-plan.fixture-other",
                        "object_type": "ride_plan",
                    },
                    "revision": 2,
                }
            ],
        ),
        (("tool_name",), "planning.compare_plans"),
        (("capability_id",), "plan.compare"),
        (("base_session_revision",), 2),
        (("expected_observation_kind",), "plan_comparison"),
    ],
)
def test_same_tool_call_id_cannot_change_authoritative_request(
    field_path, value
):
    original = load_valid("tool_call_generate_candidate_plans.json")
    retried = deepcopy(original)
    target = retried
    for key in field_path[:-1]:
        target = target[key]
    target[field_path[-1]] = value
    with pytest.raises(AssertionError):
        assert_immutable_tool_call_identity([original, retried])


def test_same_tool_call_id_accepts_identical_request_snapshot():
    call = load_valid("tool_call_generate_candidate_plans.json")
    assert_immutable_tool_call_identity([call, deepcopy(call)])


def test_action_and_call_bidirectional_ref_mismatch_fails():
    scenario = integrated_scenario()
    scenario["proposal"]["payload"]["tool_call_ref"] = "tool-call.other"
    with pytest.raises(AssertionError):
        assert_integrated_scenario(scenario)
    scenario = integrated_scenario()
    scenario["call"]["requested_by_agent_action_ref"] = "agent-action.other"
    with pytest.raises(AssertionError):
        assert_integrated_scenario(scenario)


@pytest.mark.parametrize("tool_name", ["planning.unregistered", "raw_tencent_api"])
def test_unregistered_or_forbidden_raw_tool_fails_closed(tool_name):
    scenario = integrated_scenario()
    scenario["call"]["tool_name"] = tool_name
    with pytest.raises(AssertionError):
        assert_integrated_scenario(scenario)


def test_forbidden_raw_registry_tool_is_shape_valid_but_semantically_rejected(
    schemas, local_registry
):
    registry = load_invalid("tool_registry_forbidden_raw_tool.json")
    assert not validation_errors("tool_registry", registry, schemas, local_registry)
    assert "raw_tencent_api" in {
        tool["tool_name"] for tool in registry["tools"]
    }
    with pytest.raises(AssertionError):
        assert_registry_semantics(registry)


def test_context_manifest_registry_version_mismatch_fails():
    scenario = integrated_scenario()
    scenario["manifest_turn_2"]["tool_registry_version"] = "0.2.0"
    with pytest.raises(AssertionError):
        assert_integrated_scenario(scenario)


@pytest.mark.parametrize("candidate_index", [0, 1])
def test_turn_two_manifest_must_include_each_presented_plan(candidate_index):
    scenario = integrated_scenario()
    scenario["manifest_turn_2"]["plan_revision_refs"].pop(candidate_index)
    with pytest.raises(AssertionError):
        assert_integrated_scenario(scenario)


def test_turn_two_manifest_wrong_plan_revision_fails_closed():
    scenario = integrated_scenario()
    scenario["manifest_turn_2"]["plan_revision_refs"][0]["revision"] = 2
    with pytest.raises(AssertionError):
        assert_integrated_scenario(scenario)


def test_turn_two_manifest_cannot_be_compiled_before_tool_result():
    scenario = integrated_scenario()
    scenario["manifest_turn_2"]["compiled_at"] = "2026-08-03T20:09:40+08:00"
    with pytest.raises(AssertionError):
        assert_integrated_scenario(scenario)


def test_presentation_cannot_reference_plan_absent_from_turn_context():
    scenario = integrated_scenario()
    scenario["presentation"]["payload"]["candidates"][0]["plan_revision_ref"][
        "object_ref"
    ]["object_id"] = "ride-plan.fixture-not-in-context"
    with pytest.raises(AssertionError):
        assert_integrated_scenario(scenario)


def test_turn_one_and_turn_two_manifest_order_cannot_be_reversed():
    scenario = integrated_scenario()
    scenario["manifest_turn_1"], scenario["manifest_turn_2"] = (
        scenario["manifest_turn_2"],
        scenario["manifest_turn_1"],
    )
    with pytest.raises(AssertionError):
        assert_integrated_scenario(scenario)


def test_manifest_count_must_equal_consumed_model_turns():
    scenario = integrated_scenario()
    scenario["run"]["budget"]["consumed"]["model_turns"] = 3
    with pytest.raises(AssertionError):
        assert_integrated_scenario(scenario)


@pytest.mark.parametrize(
    "field,value",
    [
        ("run_id", "agent-run.other"),
        ("session_id", "planning-session.other"),
        ("environment", "shadow"),
        ("fixture_only", False),
        ("base_session_revision", 2),
        ("tool_registry_version", "0.2.0"),
        ("tool_version", "0.2.0"),
        ("capability_id", "plan.compare"),
        ("observation_kind", "plan_comparison"),
    ],
)
def test_result_cross_contract_mutations_fail_closed(field, value):
    scenario = integrated_scenario()
    scenario["result"][field] = value
    with pytest.raises(AssertionError):
        assert_integrated_scenario(scenario)


@pytest.mark.parametrize("ref_kind", ["call", "result", "source_action"])
def test_run_must_register_call_result_and_source_action(ref_kind):
    scenario = integrated_scenario()
    if ref_kind == "call":
        scenario["run"]["tool_call_refs"] = []
    elif ref_kind == "result":
        scenario["run"]["observation_refs"] = []
    else:
        scenario["run"]["action_proposal_refs"][0] = "agent-action.other"
    with pytest.raises(AssertionError):
        assert_integrated_scenario(scenario)


@pytest.mark.parametrize("time_value", ["before_request", "after_checkpoint"])
def test_result_time_must_follow_request_and_precede_checkpoint(time_value):
    scenario = integrated_scenario()
    scenario["result"]["observed_at"] = (
        "2026-08-03T20:09:34+08:00"
        if time_value == "before_request"
        else "2026-08-03T20:11:01+08:00"
    )
    with pytest.raises(AssertionError):
        assert_integrated_scenario(scenario)


def test_duplicate_registry_identity_fails_closed():
    registry = load_json(CONTRACT_DIR / "tool_registry.v0.json")
    registry["tools"][-1] = deepcopy(registry["tools"][0])
    with pytest.raises(AssertionError):
        assert_registry_semantics(registry)


@pytest.mark.parametrize("field", ["arguments", "coordinates"])
def test_call_input_cannot_embed_arguments_or_coordinates(
    field, schemas, local_registry
):
    call = load_valid("tool_call_generate_candidate_plans.json")
    call["input"][field] = {} if field == "arguments" else [112.5, 37.8]
    assert validation_errors("tool_call", call, schemas, local_registry)


@pytest.mark.parametrize("field", ["approved", "executed", "idempotency_key"])
def test_call_cannot_claim_approval_execution_or_effect_identity(
    field, schemas, local_registry
):
    call = load_valid("tool_call_generate_candidate_plans.json")
    call[field] = True if field != "idempotency_key" else "effect.fixture"
    assert validation_errors("tool_call", call, schemas, local_registry)


def test_raw_provider_payload_and_coordinates_are_rejected(
    schemas, local_registry
):
    result = load_valid("tool_result_generate_candidate_plans_succeeded.json")
    result["provider_payload"] = {"status": 0}
    assert validation_errors("tool_result", result, schemas, local_registry)
    result = load_valid("tool_result_generate_candidate_plans_succeeded.json")
    result["coordinates"] = [112.5, 37.8]
    assert validation_errors("tool_result", result, schemas, local_registry)


@pytest.mark.parametrize(
    "fixture_name",
    [
        "tool_result_success_without_typed_ref.json",
        "tool_result_failure_with_success_ref.json",
    ],
)
def test_status_and_success_ref_combinations_fail_shape(
    fixture_name, schemas, local_registry
):
    assert validation_errors(
        "tool_result", load_invalid(fixture_name), schemas, local_registry
    )


def test_ambiguous_requires_two_choices(schemas, local_registry):
    result = load_valid("tool_result_resolve_ride_object_ambiguous.json")
    result["result_refs"].pop()
    assert validation_errors("tool_result", result, schemas, local_registry)


@pytest.mark.parametrize(
    "fixture_name,bad_retry",
    [
        ("tool_result_generate_candidate_plans_succeeded.json", "RETRY_SAME_CALL"),
        ("tool_result_resolve_ride_object_ambiguous.json", "DO_NOT_RETRY"),
        ("tool_result_generate_candidate_plans_no_result.json", "ASK_USER"),
        ("tool_result_generate_candidate_plans_timed_out.json", "REVISE_REQUEST"),
        ("tool_result_validate_plan_failed.json", "RETRY_SAME_CALL"),
    ],
)
def test_invalid_retry_dispositions_fail_shape(
    fixture_name, bad_retry, schemas, local_registry
):
    result = load_valid(fixture_name)
    result["retry_disposition"] = bad_retry
    assert validation_errors("tool_result", result, schemas, local_registry)


def test_retry_same_call_cannot_be_terminal(schemas, local_registry):
    invalid = load_invalid("tool_result_retry_same_call_marked_terminal.json")
    assert invalid["retry_disposition"] == "RETRY_SAME_CALL"
    assert invalid["result_finality"] == "TERMINAL"
    assert validation_errors("tool_result", invalid, schemas, local_registry)


def test_succeeded_result_cannot_be_intermediate(schemas, local_registry):
    result = load_valid("tool_result_generate_candidate_plans_succeeded.json")
    result["result_finality"] = "INTERMEDIATE"
    assert validation_errors("tool_result", result, schemas, local_registry)


@pytest.mark.parametrize(
    "fixture_name,bad_reason",
    [
        (
            "tool_result_generate_candidate_plans_succeeded.json",
            "NO_MATCHING_RESULT",
        ),
        (
            "tool_result_resolve_ride_object_ambiguous.json",
            "NO_MATCHING_RESULT",
        ),
        (
            "tool_result_generate_candidate_plans_no_result.json",
            "DOMAIN_SERVICE_FAILURE",
        ),
        (
            "tool_result_generate_candidate_plans_timed_out.json",
            "DOMAIN_SERVICE_FAILURE",
        ),
        (
            "tool_result_generate_candidate_plans_disconnected.json",
            "NO_MATCHING_RESULT",
        ),
        (
            "tool_result_validate_plan_failed.json",
            "TOOL_ATTEMPT_TIMEOUT",
        ),
    ],
)
def test_domain_reason_is_status_specific_and_fails_closed(
    fixture_name, bad_reason, schemas, local_registry
):
    result = load_valid(fixture_name)
    result["domain_reason_code"] = bad_reason
    assert validation_errors("tool_result", result, schemas, local_registry)


@pytest.mark.parametrize(
    "finality,retry_disposition,reason",
    [
        ("TERMINAL", "DO_NOT_RETRY", "TOOL_ATTEMPT_TIMEOUT"),
        ("TERMINAL", "DEFER", "RUN_DEADLINE_EXCEEDED"),
    ],
)
def test_terminal_timeout_reason_depends_on_retry_disposition(
    finality, retry_disposition, reason, schemas, local_registry
):
    result = load_valid("tool_result_generate_candidate_plans_timed_out.json")
    result.update(
        {
            "result_finality": finality,
            "retry_disposition": retry_disposition,
            "domain_reason_code": reason,
        }
    )
    assert not validation_errors("tool_result", result, schemas, local_registry)


def test_disconnected_retry_must_be_intermediate(schemas, local_registry):
    result = load_valid(
        "tool_result_generate_candidate_plans_disconnected.json"
    )
    result.update(
        {
            "result_finality": "INTERMEDIATE",
            "retry_disposition": "RETRY_SAME_CALL",
        }
    )
    assert not validation_errors("tool_result", result, schemas, local_registry)
    result["result_finality"] = "TERMINAL"
    assert validation_errors("tool_result", result, schemas, local_registry)


def test_revise_plan_success_returns_only_ride_plan_revision(
    schemas, local_registry
):
    registry = load_json(CONTRACT_DIR / "tool_registry.v0.json")
    result = load_valid("tool_result_revise_plan_succeeded.json")
    assert not validation_errors("tool_result", result, schemas, local_registry)
    assert result["result_refs"][0]["object_ref"]["object_type"] == "ride_plan"
    assert_result_semantics(result, call_for_result(result, registry), registry)


def test_named_non_ride_plan_revision_fixture_is_rejected(
    schemas, local_registry
):
    result = load_invalid("tool_result_revise_plan_non_ride_plan_revision.json")
    assert result["result_refs"][0]["object_ref"]["object_type"] == "route_book"
    assert validation_errors("tool_result", result, schemas, local_registry)


@pytest.mark.parametrize(
    "object_type", ["route_book", "route_version", "rider", "traversal"]
)
def test_revise_plan_rejects_other_revision_object_types(
    object_type, schemas, local_registry
):
    result = load_valid("tool_result_revise_plan_succeeded.json")
    result["result_refs"][0]["object_ref"]["object_type"] = object_type
    assert validation_errors("tool_result", result, schemas, local_registry)


def test_revise_plan_rejects_contract_artifact_kind_mismatch(
    schemas, local_registry
):
    registry = load_json(CONTRACT_DIR / "tool_registry.v0.json")
    result = load_valid("tool_result_revise_plan_succeeded.json")
    result["result_refs"] = [
        {
            "contract_kind": "plan_validation",
            "contract_id": "plan-validation.fixture-wrong-for-revision",
            "contract_revision": 1,
            "schema_version": "0.1.0",
        }
    ]
    assert not validation_errors("tool_result", result, schemas, local_registry)
    with pytest.raises(AssertionError):
        assert_result_semantics(result, call_for_result(result, registry), registry)


def test_prepare_export_cannot_return_artifact_or_plan_revision(
    schemas, local_registry
):
    registry = load_json(CONTRACT_DIR / "tool_registry.v0.json")
    invalid = load_invalid("tool_result_prepare_export_artifact.json")
    assert validation_errors("tool_result", invalid, schemas, local_registry)
    result = load_valid("tool_result_prepare_export_succeeded.json")
    result["result_refs"] = [
        {
            "object_ref": {
                "object_id": "ride-plan.fixture-a",
                "object_type": "ride_plan",
            },
            "revision": 1,
        }
    ]
    assert not validation_errors("tool_result", result, schemas, local_registry)
    with pytest.raises(AssertionError):
        assert_result_semantics(result, call_for_result(result, registry), registry)


@pytest.mark.parametrize("environment", ["test", "shadow"])
def test_test_and_shadow_policy_cannot_claim_real_network_or_effect(
    environment, schemas, local_registry
):
    registry = load_json(CONTRACT_DIR / "tool_registry.v0.json")
    key = "real_network_allowed"
    registry["environment_policy"][environment][key] = True
    assert validation_errors("tool_registry", registry, schemas, local_registry)
    registry = load_json(CONTRACT_DIR / "tool_registry.v0.json")
    registry["environment_policy"][environment]["real_external_effect_allowed"] = True
    assert validation_errors("tool_registry", registry, schemas, local_registry)


@pytest.mark.parametrize(
    "artifact_name,metadata_key",
    [
        ("registry", "x-approval-mode"),
        ("call", "x-capability-id"),
        ("call", "x-tool-name"),
        ("result", "x-result-status"),
        ("result", "x-external-effect"),
    ],
)
def test_metadata_cannot_override_authoritative_semantics(
    artifact_name, metadata_key
):
    scenario = integrated_scenario()
    scenario[artifact_name]["metadata"][metadata_key] = "override"
    with pytest.raises(AssertionError):
        assert_integrated_scenario(scenario)


def retry_scenario():
    registry = load_json(CONTRACT_DIR / "tool_registry.v0.json")
    timeout = load_valid("tool_result_generate_candidate_plans_timed_out.json")
    succeeded = load_valid(
        "tool_result_generate_candidate_plans_retry_succeeded.json"
    )
    call = call_for_result(timeout, registry)
    run = deepcopy(load_valid("agent_run_candidate_completed.json"))
    run.update(
        {
            "run_id": timeout["run_id"],
            "session_id": timeout["session_id"],
            "base_session_revision": timeout["base_session_revision"],
            "context_manifest_refs": ["context-manifest.fixture-retry-turn-1"],
            "action_proposal_refs": [call["requested_by_agent_action_ref"]],
            "tool_call_refs": [call["tool_call_id"]],
            "observation_refs": [
                timeout["observation_id"],
                succeeded["observation_id"],
            ],
            "started_at": "2026-08-03T20:09:00+08:00",
            "last_checkpoint_at": "2026-08-03T20:10:40+08:00",
            "ended_at": "2026-08-03T20:10:40+08:00",
        }
    )
    run["budget"]["consumed"].update(
        {"model_turns": 1, "tool_calls": 2, "plan_generations": 1}
    )
    run["budget"]["tool_retry_counters"] = [
        {"tool_name": call["tool_name"], "retries": 1}
    ]
    return {
        "registry": registry,
        "call": call,
        "results": [timeout, succeeded],
        "run": run,
    }


def assert_retry_scenario(scenario):
    assert_attempt_chain(
        scenario["call"],
        scenario["results"],
        scenario["registry"],
        scenario["run"],
    )


def test_one_immutable_call_can_timeout_then_succeed_on_second_attempt(
    schemas, local_registry
):
    scenario = retry_scenario()
    for result in scenario["results"]:
        assert not validation_errors(
            "tool_result", result, schemas, local_registry
        )
    assert not validation_errors(
        "agent_run", scenario["run"], schemas, local_registry
    )
    assert_retry_scenario(scenario)
    assert [item["attempt_index"] for item in scenario["results"]] == [1, 2]
    assert [
        item["result_finality"] for item in scenario["results"]
    ] == ["INTERMEDIATE", "TERMINAL"]
    assert scenario["run"]["budget"]["consumed"]["tool_calls"] == 2
    assert scenario["run"]["budget"]["tool_retry_counters"] == [
        {"tool_name": "planning.generate_candidate_plans", "retries": 1}
    ]
    assert len(scenario["run"]["tool_call_refs"]) == 1
    assert len(scenario["run"]["observation_refs"]) == 2
    assert scenario["run"]["budget"]["consumed"]["model_turns"] == 1
    assert len(scenario["run"]["action_proposal_refs"]) == 1


@pytest.mark.parametrize(
    "first_index,second_index",
    [(2, 3), (1, 1), (1, 3)],
    ids=["starts_at_two", "duplicate", "gap"],
)
def test_attempt_indices_must_start_at_one_and_be_contiguous(
    first_index, second_index
):
    scenario = retry_scenario()
    scenario["results"][0]["attempt_index"] = first_index
    scenario["results"][1]["attempt_index"] = second_index
    with pytest.raises(AssertionError):
        assert_retry_scenario(scenario)


def test_attempt_timestamps_cannot_move_backwards():
    scenario = retry_scenario()
    scenario["results"][1]["observed_at"] = "2026-08-03T20:09:59+08:00"
    with pytest.raises(AssertionError):
        assert_retry_scenario(scenario)


def test_one_call_cannot_have_two_terminal_results():
    scenario = retry_scenario()
    scenario["results"][0].update(
        {
            "result_finality": "TERMINAL",
            "retry_disposition": "DO_NOT_RETRY",
        }
    )
    with pytest.raises(AssertionError):
        assert_retry_scenario(scenario)


def test_no_result_may_not_follow_a_terminal_result():
    scenario = retry_scenario()
    extra = deepcopy(scenario["results"][0])
    extra.update(
        {
            "observation_id": "observation.fixture-illegal-after-terminal-001",
            "attempt_index": 3,
            "observed_at": "2026-08-03T20:10:35+08:00",
        }
    )
    scenario["results"].append(extra)
    scenario["run"]["observation_refs"].append(extra["observation_id"])
    scenario["run"]["budget"]["consumed"]["tool_calls"] = 3
    scenario["run"]["budget"]["tool_retry_counters"][0]["retries"] = 2
    with pytest.raises(AssertionError):
        assert_retry_scenario(scenario)


def test_stopped_run_cannot_end_with_only_intermediate_result():
    scenario = retry_scenario()
    scenario["results"] = scenario["results"][:1]
    scenario["run"]["observation_refs"] = scenario["run"][
        "observation_refs"
    ][:1]
    scenario["run"]["budget"]["consumed"]["tool_calls"] = 1
    scenario["run"]["budget"]["tool_retry_counters"][0]["retries"] = 0
    with pytest.raises(AssertionError):
        assert_retry_scenario(scenario)


def test_running_run_may_temporarily_wait_with_only_intermediate_result():
    scenario = retry_scenario()
    scenario["results"] = scenario["results"][:1]
    scenario["run"]["run_status"] = "running"
    scenario["run"].pop("stop_reason")
    scenario["run"].pop("ended_at")
    scenario["run"]["session_commit"] = {
        "commit_status": "not_committed",
        "expected_base_revision": 1,
    }
    scenario["run"]["observation_refs"] = scenario["run"][
        "observation_refs"
    ][:1]
    scenario["run"]["budget"]["consumed"]["tool_calls"] = 1
    scenario["run"]["budget"]["tool_retry_counters"][0]["retries"] = 0
    assert_retry_scenario(scenario)


def test_retry_count_cannot_exceed_run_budget():
    scenario = retry_scenario()
    scenario["run"]["budget"]["limits"]["max_same_tool_retries"] = 0
    with pytest.raises(AssertionError):
        assert_retry_scenario(scenario)


def test_all_outcome_fixtures_follow_registry_identity_and_result_rules():
    registry = load_json(CONTRACT_DIR / "tool_registry.v0.json")
    for fixture_name in VALID_FIXTURE_SCHEMAS:
        if not fixture_name.startswith("tool_result_"):
            continue
        result = load_valid(fixture_name)
        call = call_for_result(result, registry)
        assert_call_semantics(call, registry)
        assert_result_semantics(result, call, registry)


def test_registry_and_valid_fixtures_expose_no_raw_or_effectful_capability():
    registry = load_json(CONTRACT_DIR / "tool_registry.v0.json")
    exposed_registry_identities = json.dumps(
        [
            {
                "tool_name": tool["tool_name"],
                "capability_id": tool["capability_id"],
                "purpose_code": tool["purpose_code"],
            }
            for tool in registry["tools"]
        ],
        ensure_ascii=False,
    ).lower()
    for forbidden in FORBIDDEN_TOOL_NAMES:
        assert forbidden not in exposed_registry_identities
    assert (
        "app.route_book.export_workflow.create_route_export"
        not in exposed_registry_identities
    )
    for fixture_name in VALID_FIXTURE_SCHEMAS:
        serialized = json.dumps(load_valid(fixture_name), ensure_ascii=False).lower()
        for forbidden in (
            "raw_tencent_api",
            "raw_provider_payload\": true",
            "export_artifact",
            "download_url",
            "storage_ref",
            "idempotency_key",
            "approval_request_id",
            "proposed_effect_id",
        ):
            assert forbidden not in serialized, (fixture_name, forbidden)
