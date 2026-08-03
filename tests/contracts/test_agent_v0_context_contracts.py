import hashlib
import json
from copy import deepcopy
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
    "predicate_registry": "predicate_registry.schema.json",
    "rider_context": "rider_context_packet.schema.json",
    "world_fact": "world_fact_packet.schema.json",
    "context_manifest": "context_manifest.schema.json",
}

EXPECTED_SCHEMA_IDS = {
    name: f"https://schemas.velo.invalid/agent_v0/{filename}"
    for name, filename in SCHEMA_FILES.items()
}

REQUIRED_WORLD_PREDICATES = {
    "metric.distance_m",
    "metric.climb_m",
    "metric.descent_m",
    "metric.moving_time_range_s",
    "route.surface_type",
    "route.unpaved_distance_m",
    "route.bicycle_access",
    "route.traffic_exposure",
    "route.climb_rhythm",
    "route.technical_descent",
    "route.supply_availability",
    "route.shade_exposure",
    "route.wind_exposure",
    "route.night_suitability",
    "route.group_ride_suitability",
    "route.exit_option",
    "route.local_name",
    "route.scenic_character",
    "dynamic.closure",
    "dynamic.construction",
    "dynamic.surface_damage",
    "dynamic.supply_closed",
}

FORBIDDEN_COORDINATE_KEYS = {
    "lat",
    "latitude",
    "lng",
    "lon",
    "longitude",
    "coordinates",
    "exact_coordinates",
    "raw_trackpoints",
}


def load_json(path: Path):
    with path.open(encoding="utf-8") as handle:
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
    validator = validator_for(schema_name, schemas, local_registry)
    return sorted(validator.iter_errors(instance), key=lambda error: list(error.absolute_path))


def path_text(error):
    return "/".join(str(part) for part in error.absolute_path)


def predicate_map(registry_document):
    return {
        definition["predicate_id"]: definition
        for definition in registry_document["predicates"]
    }


def assert_unique_predicate_ids(registry_document):
    predicate_ids = [item["predicate_id"] for item in registry_document["predicates"]]
    duplicates = sorted(
        predicate_id
        for predicate_id in set(predicate_ids)
        if predicate_ids.count(predicate_id) > 1
    )
    assert not duplicates, f"duplicate predicate_id values: {duplicates}"


def walk_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_keys(child)


def walk_refs(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "$ref":
                yield child
            yield from walk_refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_refs(child)


def walk_object_refs(value):
    if isinstance(value, dict):
        if set(value) == {"object_id", "object_type"}:
            yield value
        for child in value.values():
            yield from walk_object_refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_object_refs(child)


def assert_unique_values(items, field_name):
    values = [
        json.dumps(item[field_name], sort_keys=True)
        if isinstance(item[field_name], (dict, list))
        else item[field_name]
        for item in items
    ]
    assert len(values) == len(set(values)), f"duplicate {field_name} values"


def typed_value_unit(value):
    if value["value_kind"] == "number":
        return value["unit_code"]
    if value["value_kind"] == "number_range":
        return value["number_range_value"]["unit_code"]
    return None


def assert_rider_semantics(packet, definitions):
    assert packet["source_revision"]
    assert all(
        handle["exact_coordinates_exposed"] is False
        for handle in packet["saved_place_handles"]
    )
    assert all(value is False for value in packet["privacy"].values())
    for preference in packet["explicit_preferences"]:
        assert preference["predicate_id"] in definitions
        definition = definitions[preference["predicate_id"]]
        assert preference["value"]["value_kind"] == definition["value_kind"]
        if definition["value_kind"] == "enum":
            assert preference["value"]["enum_value"] in definition["enum_values"]
        unit_code = typed_value_unit(preference["value"])
        if unit_code is not None:
            assert unit_code in definition["unit_codes"]


def assert_world_semantics(world_packet, definitions):
    assert all(
        object_ref["object_type"] != "rider"
        for object_ref in walk_object_refs(world_packet)
    )
    assert set(world_packet["query_context"]["requested_predicate_ids"]) <= set(
        definitions
    )
    assert_unique_values(world_packet["objects"], "object_ref")
    assert_unique_values(world_packet["traversals"], "traversal_ref")
    assert_unique_values(world_packet["relations"], "relation_id")
    assert_unique_values(world_packet["facts"], "fact_id")
    assert_unique_values(world_packet["dynamic_states"], "state_id")
    assert_unique_values(world_packet["advisories"], "advisory_id")
    assert_unique_values(world_packet["unknowns"], "unknown_id")
    assert_unique_values(world_packet["provenance_index"], "provenance_id")

    provenance_ids = {
        item["provenance_id"] for item in world_packet["provenance_index"]
    }
    provenance_types = {
        item["provenance_id"]: item["provenance_type"]
        for item in world_packet["provenance_index"]
    }
    object_refs = {
        (item["object_ref"]["object_id"], item["object_ref"]["object_type"])
        for item in world_packet["objects"]
    }
    traversal_refs = {
        (
            item["traversal_ref"]["object_id"],
            item["traversal_ref"]["object_type"],
        )
        for item in world_packet["traversals"]
    }
    known_refs = object_refs | traversal_refs
    fact_ids = {item["fact_id"] for item in world_packet["facts"]}

    for focus_ref in world_packet["query_context"]["focus_refs"]:
        assert focus_ref["object_type"] != "rider"
        assert (focus_ref["object_id"], focus_ref["object_type"]) in known_refs

    for item in (
        world_packet["relations"]
        + world_packet["facts"]
        + world_packet["dynamic_states"]
        + world_packet["advisories"]
    ):
        scope = item["scope"]
        subject_ref = scope["subject_ref"]
        assert (subject_ref["object_id"], subject_ref["object_type"]) in known_refs
        if "traversal_ref" in scope:
            traversal_ref = scope["traversal_ref"]
            assert (
                traversal_ref["object_id"],
                traversal_ref["object_type"],
            ) in traversal_refs
        if "spatial_interval" in scope:
            interval_ref = scope["spatial_interval"]["interval_ref"]
            assert (
                interval_ref["object_id"],
                interval_ref["object_type"],
            ) in object_refs

    for item in world_packet["objects"]:
        assert item["object_ref"]["object_type"] != "rider"
        assert item["object_ref"] == item["revision_ref"]["object_ref"]

    for item in world_packet["traversals"]:
        assert item["traversal_ref"]["object_type"] == "traversal"
        parent_key = (
            item["parent_object_ref"]["object_id"],
            item["parent_object_ref"]["object_type"],
        )
        assert parent_key in object_refs
        assert set(item["metric_fact_refs"]) <= fact_ids
        if "path_ref" in item:
            path_key = (item["path_ref"]["object_id"], item["path_ref"]["object_type"])
            assert path_key in object_refs

    for item in world_packet["facts"]:
        predicate_id = item["predicate_id"]
        assert predicate_id in definitions, f"unknown predicate_id: {predicate_id}"
        definition = definitions[predicate_id]
        assert item["subject_ref"] == item["scope"]["subject_ref"]
        subject_key = (
            item["subject_ref"]["object_id"],
            item["subject_ref"]["object_type"],
        )
        assert subject_key in known_refs
        assert item["subject_ref"]["object_type"] in definition["allowed_subject_types"]
        assert item["value"]["value_kind"] == definition["value_kind"]

        if definition["value_kind"] == "enum":
            assert item["value"]["enum_value"] in definition["enum_values"]
        unit_code = typed_value_unit(item["value"])
        if unit_code is not None:
            assert unit_code in definition["unit_codes"]

        requirements = definition["scope_requirements"]
        if requirements["traversal_scope"]:
            assert "traversal_ref" in item["scope"]
        if requirements["direction_scope"]:
            assert "direction" in item["scope"]
        if requirements["spatial_scope"] == "required":
            assert "spatial_interval" in item["scope"]
        if requirements["time_window"] == "required":
            assert "time_window" in item["scope"]
        if "traversal_ref" in item["scope"]:
            traversal_key = (
                item["scope"]["traversal_ref"]["object_id"],
                item["scope"]["traversal_ref"]["object_type"],
            )
            assert traversal_key in traversal_refs

        assert item["claim_kind"] == definition["category"]
        assert item["fact_status"] in definition["allowed_fact_statuses"]
        assert item["freshness"]["policy_ref"] == definition["freshness_policy"][
            "policy_ref"
        ]
        assert item["freshness"]["freshness_status"] in definition[
            "freshness_policy"
        ]["expected_statuses"]
        requirement = definition["evidence_requirement"]
        if requirement == "calculation_required":
            assert item.get("calculation_run_ref") in provenance_ids
            assert provenance_types[item["calculation_run_ref"]] == "calculation_run"
        elif requirement == "evidence_required":
            assert item.get("evidence_refs")
        else:
            assert item.get("evidence_refs") or item.get("calculation_run_ref")

        if item.get("calculation_run_ref"):
            assert item["calculation_run_ref"] in provenance_ids
            assert provenance_types[item["calculation_run_ref"]] == "calculation_run"

        for provenance_ref in item.get("evidence_refs", []):
            assert provenance_ref in provenance_ids
            assert provenance_types[provenance_ref] == "evidence"

    for item in world_packet["dynamic_states"]:
        definition = definitions[item["state_type"]]
        subject_ref = item["scope"]["subject_ref"]
        subject_key = (subject_ref["object_id"], subject_ref["object_type"])
        assert subject_key in known_refs
        assert subject_ref["object_type"] in definition["allowed_subject_types"]
        assert item["status"] in definition["enum_values"]
        assert item["freshness"]["policy_ref"] == definition["freshness_policy"][
            "policy_ref"
        ]
        assert item["freshness"]["freshness_status"] in definition[
            "freshness_policy"
        ]["expected_statuses"]
        requirements = definition["scope_requirements"]
        if requirements["traversal_scope"]:
            assert "traversal_ref" in item["scope"]
        if requirements["direction_scope"]:
            assert "direction" in item["scope"]
        if requirements["spatial_scope"] == "required":
            assert "spatial_interval" in item["scope"]
        if requirements["time_window"] == "required":
            assert "time_window" in item["scope"]
        if "traversal_ref" in item["scope"]:
            traversal_key = (
                item["scope"]["traversal_ref"]["object_id"],
                item["scope"]["traversal_ref"]["object_type"],
            )
            assert traversal_key in traversal_refs
        for evidence_ref in item["evidence_refs"]:
            assert evidence_ref in provenance_ids
            assert provenance_types[evidence_ref] == "evidence"

    for relation in world_packet["relations"]:
        relation_subject = relation["scope"]["subject_ref"]
        assert (
            relation_subject["object_id"],
            relation_subject["object_type"],
        ) in known_refs
        for ref_name in ("from_ref", "to_ref"):
            ref = relation[ref_name]
            assert (ref["object_id"], ref["object_type"]) in known_refs
        for provenance_ref in relation["provenance_refs"]:
            assert provenance_ref in provenance_ids
            assert provenance_types[provenance_ref] in {"source", "evidence"}

    for advisory in world_packet["advisories"]:
        assert advisory["advisory_type"] in definitions
        definition = definitions[advisory["advisory_type"]]
        subject_ref = advisory["scope"]["subject_ref"]
        assert (subject_ref["object_id"], subject_ref["object_type"]) in known_refs
        assert subject_ref["object_type"] in definition["allowed_subject_types"]
        assert advisory["verification_status"] in {"unverified", "reported", "contested"}
        assert advisory["usage_policy"] in {"advisory_only", "unknown_only"}
        assert any(
            provenance_types[provenance_ref] == "contribution"
            for provenance_ref in advisory["provenance_refs"]
        )
        if "traversal_ref" in advisory["scope"]:
            traversal_ref = advisory["scope"]["traversal_ref"]
            assert (
                traversal_ref["object_id"],
                traversal_ref["object_type"],
            ) in traversal_refs
        for provenance_ref in advisory["provenance_refs"]:
            assert provenance_ref in provenance_ids

    for item in world_packet["unknowns"]:
        assert item["predicate_id"] in definitions
        subject_ref = item["subject_ref"]
        assert (subject_ref["object_id"], subject_ref["object_type"]) in known_refs

    limits = world_packet["packet_limits"]
    assert limits["facts_included"] == len(world_packet["facts"])
    assert limits["facts_included"] <= limits["fact_limit"]
    assert limits["truncated"] is (limits["facts_omitted"] > 0)


def assert_manifest_semantics(manifest):
    assert_unique_values(manifest["source_packet_refs"], "packet_id")
    packet_files = {
        "rider-context.fixture.rider-001.1": (
            "rider_context_packet",
            VALID_FIXTURES / "rider_context_packet.json",
        ),
        "world-fact.fixture.tianlongshan-linear-climb.1": (
            "world_fact_packet",
            VALID_FIXTURES / "world_fact_tianlongshan_linear_climb.json",
        ),
        "world-fact.fixture.fenhe-dual-bank.1": (
            "world_fact_packet",
            VALID_FIXTURES / "world_fact_fenhe_dual_bank_corridor.json",
        ),
    }
    for packet_ref in manifest["source_packet_refs"]:
        expected_packet_type, source_path = packet_files[packet_ref["packet_id"]]
        source_packet = load_json(source_path)
        assert packet_ref["packet_type"] == expected_packet_type
        assert manifest["packet_environment"] == source_packet["packet_environment"]
        assert packet_ref["schema_version"] == source_packet["schema_version"]
        assert packet_ref["source_revision"] == source_packet["source_revision"]
        assert packet_ref["content_hash"] == hashlib.sha256(source_path.read_bytes()).hexdigest()

    budget = manifest["token_budget"]
    assert budget["used"] == sum(item["tokens"] for item in manifest["token_counts"])
    assert budget["used"] + budget["reserved_for_response"] <= budget["budget"]


def test_schemas_are_draft_2020_12_and_have_stable_ids(schemas):
    assert len({schema["$id"] for schema in schemas.values()}) == len(schemas)
    for name, schema in schemas.items():
        Draft202012Validator.check_schema(schema)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["$id"] == EXPECTED_SCHEMA_IDS[name]
        if name == "common":
            assert schema["$defs"]["schema_version"]["const"] == "0.1.0"
        else:
            assert "schema_version" in schema["properties"]


def test_predicate_registry_is_valid_unique_and_complete(schemas, local_registry):
    registry_document = load_json(CONTRACT_DIR / "predicate_registry.v0.json")
    validator_for("predicate_registry", schemas, local_registry).validate(registry_document)
    assert registry_document["schema_version"] == "0.1.0"
    assert registry_document["registry_version"] == "0.1.0"
    assert_unique_predicate_ids(registry_document)

    definitions = predicate_map(registry_document)
    assert set(definitions) == REQUIRED_WORLD_PREDICATES

    for definition in definitions.values():
        if definition["directionality"] == "direction_specific":
            assert definition["scope_requirements"]["traversal_scope"] is True
            assert definition["scope_requirements"]["direction_scope"] is True
        if definition["category"] == "time_bound_dynamic_state":
            assert definition["scope_requirements"]["time_window"] == "required"
            assert definition["freshness_policy"]["time_bound"] is True
            assert definition["freshness_policy"]["max_age_s"] is not None


@pytest.mark.parametrize(
    ("fixture_name", "schema_name"),
    [
        ("rider_context_packet.json", "rider_context"),
        ("world_fact_tianlongshan_linear_climb.json", "world_fact"),
        ("world_fact_fenhe_dual_bank_corridor.json", "world_fact"),
        ("context_manifest.json", "context_manifest"),
    ],
)
def test_valid_fixtures_conform(fixture_name, schema_name, schemas, local_registry):
    fixture = load_json(VALID_FIXTURES / fixture_name)
    validator_for(schema_name, schemas, local_registry).validate(fixture)
    assert fixture["schema_version"] == "0.1.0"


@pytest.mark.parametrize(
    ("schema_name", "fixture_path"),
    [
        ("predicate_registry", CONTRACT_DIR / "predicate_registry.v0.json"),
        ("rider_context", VALID_FIXTURES / "rider_context_packet.json"),
        (
            "world_fact",
            VALID_FIXTURES / "world_fact_tianlongshan_linear_climb.json",
        ),
        ("context_manifest", VALID_FIXTURES / "context_manifest.json"),
    ],
)
def test_schema_version_other_than_0_1_0_is_rejected(
    schema_name, fixture_path, schemas, local_registry
):
    fixture = load_json(fixture_path)
    fixture["schema_version"] = "0.2.0"
    errors = validation_errors(schema_name, fixture, schemas, local_registry)
    assert any(
        path_text(error) == "schema_version" and error.validator == "const"
        for error in errors
    )


@pytest.mark.parametrize(
    ("fixture_name", "schema_name", "expected_path", "expected_validator"),
    [
        (
            "rider_context_exact_coordinates.json",
            "rider_context",
            "saved_place_handles/0",
            "additionalProperties",
        ),
        (
            "world_fact_accepted_without_provenance.json",
            "world_fact",
            "facts/0",
            "anyOf",
        ),
        (
            "world_fact_unverified_as_fact.json",
            "world_fact",
            "facts/0/fact_status",
            "enum",
        ),
        (
            "world_fact_dynamic_without_validity.json",
            "world_fact",
            "dynamic_states/0",
            "required",
        ),
        (
            "context_manifest_missing_source_revision.json",
            "context_manifest",
            "source_packet_refs/0",
            "required",
        ),
    ],
)
def test_invalid_fixtures_fail_at_the_expected_boundary(
    fixture_name,
    schema_name,
    expected_path,
    expected_validator,
    schemas,
    local_registry,
):
    fixture = load_json(INVALID_FIXTURES / fixture_name)
    errors = validation_errors(schema_name, fixture, schemas, local_registry)
    assert errors, f"{fixture_name} unexpectedly validated"
    assert any(
        path_text(error) == expected_path and error.validator == expected_validator
        for error in errors
    ), [
        {"path": path_text(error), "validator": error.validator, "message": error.message}
        for error in errors
    ]


def test_duplicate_predicate_fixture_is_rejected_by_registry_invariant(
    schemas, local_registry
):
    fixture = load_json(INVALID_FIXTURES / "predicate_registry_duplicate_id.json")
    validator_for("predicate_registry", schemas, local_registry).validate(fixture)
    with pytest.raises(AssertionError, match="duplicate predicate_id"):
        assert_unique_predicate_ids(fixture)


def test_valid_packets_never_embed_exact_coordinates_or_raw_trackpoints():
    for fixture_path in sorted(VALID_FIXTURES.glob("*.json")):
        normalized_keys = {
            key.lower().replace("-", "_").removeprefix("x_")
            for key in walk_keys(load_json(fixture_path))
        }
        forbidden = FORBIDDEN_COORDINATE_KEYS.intersection(normalized_keys)
        assert not forbidden, f"{fixture_path.name} exposes forbidden keys: {forbidden}"


def test_rider_metadata_and_section_authorization_cannot_bypass_privacy(
    schemas, local_registry
):
    packet = load_json(VALID_FIXTURES / "rider_context_packet.json")
    validator = validator_for("rider_context", schemas, local_registry)

    coordinate_metadata = deepcopy(packet)
    coordinate_metadata["metadata"] = {
        "x-home-lat": 37.7749,
        "x-home-longitude": 112.5627,
    }
    errors = sorted(validator.iter_errors(coordinate_metadata), key=lambda error: list(error.path))
    assert errors
    assert any(path_text(error) == "metadata" for error in errors)

    unauthorized_saved_place = deepcopy(packet)
    unauthorized_saved_place["authorization"]["allowed_sections"].remove(
        "saved_place_handles"
    )
    errors = sorted(
        validator.iter_errors(unauthorized_saved_place),
        key=lambda error: list(error.path),
    )
    assert errors
    assert any("authorization/allowed_sections" in path_text(error) for error in errors)


def test_rider_fixture_uses_versioned_opaque_and_registered_context():
    packet = load_json(VALID_FIXTURES / "rider_context_packet.json")
    definitions = predicate_map(load_json(CONTRACT_DIR / "predicate_registry.v0.json"))
    assert_rider_semantics(packet, definitions)


def test_world_packets_use_registry_predicates_scopes_and_provenance():
    definitions = predicate_map(load_json(CONTRACT_DIR / "predicate_registry.v0.json"))
    world_paths = sorted(VALID_FIXTURES.glob("world_fact_*.json"))
    assert {path.name for path in world_paths} == {
        "world_fact_tianlongshan_linear_climb.json",
        "world_fact_fenhe_dual_bank_corridor.json",
    }
    for fixture_path in world_paths:
        packet = load_json(fixture_path)
        assert packet["fixture_only"] is True
        assert packet["query_context"]["synthetic_fixture_data"] is True
        assert packet["unknowns"], f"{fixture_path.name} must expose missing information"
        assert_world_semantics(packet, definitions)

    primary_shapes = {
        load_json(fixture_path)["objects"][0]["route_shape"]
        for fixture_path in world_paths
    }
    assert primary_shapes == {"linear_climb", "corridor"}


def test_tianlongshan_and_fenhe_fixtures_cover_distinct_world_structures():
    tianlongshan = load_json(
        VALID_FIXTURES / "world_fact_tianlongshan_linear_climb.json"
    )
    assert {item["object_ref"]["object_type"] for item in tianlongshan["objects"]} >= {
        "named_route",
        "climb",
    }
    assert any(
        traversal["direction"] == "forward"
        for traversal in tianlongshan["traversals"]
    )
    assert {fact["predicate_id"] for fact in tianlongshan["facts"]} >= {
        "metric.distance_m",
        "metric.climb_m",
        "route.climb_rhythm",
    }

    fenhe = load_json(VALID_FIXTURES / "world_fact_fenhe_dual_bank_corridor.json")
    relation_types = {relation["relation_type"] for relation in fenhe["relations"]}
    assert relation_types >= {
        "parallel_bank_of",
        "starts_at",
        "turnaround_at",
        "exit_to",
    }
    assert fenhe["dynamic_states"] or fenhe["advisories"]
    assert fenhe["packet_limits"]["facts_included"] == len(fenhe["facts"])


def test_unverified_rider_report_is_advisory_not_canonical_fact():
    packet = load_json(VALID_FIXTURES / "world_fact_tianlongshan_linear_climb.json")
    assert all(fact["fact_status"] != "unverified" for fact in packet["facts"])
    assert any(
        advisory["verification_status"] == "reported"
        and advisory["usage_policy"] == "advisory_only"
        for advisory in packet["advisories"]
    )


def test_context_manifest_records_revisions_omissions_and_token_budget():
    manifest = load_json(VALID_FIXTURES / "context_manifest.json")
    assert manifest["session_revision"]
    assert manifest["predicate_registry_version"] == "0.1.0"
    assert manifest["omitted_sections"]
    assert manifest["privacy_redactions"]
    assert manifest["source_of_truth"] is False
    assert_manifest_semantics(manifest)


def test_cross_contract_semantic_mutations_are_rejected(schemas, local_registry):
    definitions = predicate_map(load_json(CONTRACT_DIR / "predicate_registry.v0.json"))
    packet = load_json(VALID_FIXTURES / "world_fact_tianlongshan_linear_climb.json")

    rider_packet = load_json(VALID_FIXTURES / "rider_context_packet.json")
    unregistered_preference = deepcopy(rider_packet)
    unregistered_preference["explicit_preferences"][0]["predicate_id"] = (
        "route.unregistered"
    )
    with pytest.raises(AssertionError):
        assert_rider_semantics(unregistered_preference, definitions)

    bad_unit = deepcopy(packet)
    bad_unit["facts"][0]["value"]["unit_code"] = "km"
    with pytest.raises(AssertionError):
        assert_world_semantics(bad_unit, definitions)

    bad_dynamic_status = deepcopy(packet)
    bad_dynamic_status["dynamic_states"][0]["status"] = "banana"
    with pytest.raises(AssertionError):
        assert_world_semantics(bad_dynamic_status, definitions)

    mismatched_scope = deepcopy(packet)
    mismatched_scope["facts"][0]["scope"]["subject_ref"] = {
        "object_id": "climb.tianlongshan-main-001",
        "object_type": "climb",
    }
    with pytest.raises(AssertionError):
        assert_world_semantics(mismatched_scope, definitions)

    dangling_fact_ref = deepcopy(packet)
    dangling_fact_ref["traversals"][0]["metric_fact_refs"].append("fact.missing")
    with pytest.raises(AssertionError):
        assert_world_semantics(dangling_fact_ref, definitions)

    duplicate_fact = deepcopy(packet)
    duplicate_fact["facts"].append(deepcopy(duplicate_fact["facts"][0]))
    with pytest.raises(AssertionError, match="duplicate fact_id"):
        assert_world_semantics(duplicate_fact, definitions)

    mismatched_revision = deepcopy(packet)
    mismatched_revision["objects"][0]["revision_ref"]["object_ref"] = {
        "object_id": "route.other",
        "object_type": "named_route",
    }
    with pytest.raises(AssertionError):
        assert_world_semantics(mismatched_revision, definitions)

    contribution_as_evidence = deepcopy(packet)
    contribution_as_evidence["facts"][2]["evidence_refs"] = [
        "provenance.fixture-rider-report"
    ]
    with pytest.raises(AssertionError):
        assert_world_semantics(contribution_as_evidence, definitions)

    evidence_as_calculation = deepcopy(packet)
    evidence_as_calculation["facts"][0]["calculation_run_ref"] = (
        "provenance.fixture-review"
    )
    with pytest.raises(AssertionError):
        assert_world_semantics(evidence_as_calculation, definitions)

    advisory_without_contribution_provenance = deepcopy(packet)
    advisory_without_contribution_provenance["advisories"][0]["provenance_refs"] = [
        "provenance.fixture-review"
    ]
    with pytest.raises(AssertionError):
        assert_world_semantics(advisory_without_contribution_provenance, definitions)

    rider_in_world = deepcopy(packet)
    rider_in_world["objects"].append(
        {
            "object_ref": {
                "object_id": "rider.fixture-forbidden",
                "object_type": "rider",
            },
            "revision_ref": {
                "object_ref": {
                    "object_id": "rider.fixture-forbidden",
                    "object_type": "rider",
                },
                "revision": "fixture-r1",
            },
            "display_name": "Forbidden rider object",
            "aliases": [],
            "route_shape": "loop",
        }
    )
    assert validation_errors("world_fact", rider_in_world, schemas, local_registry)
    with pytest.raises(AssertionError):
        assert_world_semantics(rider_in_world, definitions)

    rider_focus = deepcopy(packet)
    rider_focus["query_context"]["focus_refs"].append(
        {"object_id": "rider.fixture-forbidden", "object_type": "rider"}
    )
    assert validation_errors("world_fact", rider_focus, schemas, local_registry)
    with pytest.raises(AssertionError):
        assert_world_semantics(rider_focus, definitions)

    rider_spatial_interval = deepcopy(packet)
    rider_spatial_interval["facts"][0]["scope"]["spatial_interval"] = {
        "interval_ref": {
            "object_id": "rider.fixture-forbidden",
            "object_type": "rider",
        },
        "from_fraction": 0,
        "to_fraction": 1,
    }
    assert validation_errors(
        "world_fact", rider_spatial_interval, schemas, local_registry
    )
    with pytest.raises(AssertionError):
        assert_world_semantics(rider_spatial_interval, definitions)

    rider_relation_traversal = deepcopy(packet)
    rider_relation_traversal["relations"][0]["scope"]["traversal_ref"] = {
        "object_id": "rider.fixture-forbidden",
        "object_type": "rider",
    }
    assert validation_errors(
        "world_fact", rider_relation_traversal, schemas, local_registry
    )
    with pytest.raises(AssertionError):
        assert_world_semantics(rider_relation_traversal, definitions)

    dangling_path = deepcopy(packet)
    dangling_path["traversals"][0]["path_ref"] = {
        "object_id": "path.fixture-missing",
        "object_type": "path",
    }
    with pytest.raises(AssertionError):
        assert_world_semantics(dangling_path, definitions)

    manifest = load_json(VALID_FIXTURES / "context_manifest.json")
    over_budget = deepcopy(manifest)
    over_budget["token_budget"]["reserved_for_response"] += 1
    with pytest.raises(AssertionError):
        assert_manifest_semantics(over_budget)

    wrong_packet_type = deepcopy(manifest)
    wrong_packet_type["source_packet_refs"][0]["packet_type"] = "world_fact_packet"
    with pytest.raises(AssertionError):
        assert_manifest_semantics(wrong_packet_type)

    wrong_manifest_environment = deepcopy(manifest)
    wrong_manifest_environment["packet_environment"] = "production"
    with pytest.raises(AssertionError):
        assert_manifest_semantics(wrong_manifest_environment)


def test_all_schema_references_resolve_without_network(schemas, local_registry):
    registry, unexpected_retrievals = local_registry
    for schema in schemas.values():
        resolver = registry.resolver(base_uri=schema["$id"])
        for ref in walk_refs(schema):
            resolver.lookup(ref)

    instances = [
        ("predicate_registry", load_json(CONTRACT_DIR / "predicate_registry.v0.json")),
        ("rider_context", load_json(VALID_FIXTURES / "rider_context_packet.json")),
        (
            "world_fact",
            load_json(VALID_FIXTURES / "world_fact_tianlongshan_linear_climb.json"),
        ),
        ("context_manifest", load_json(VALID_FIXTURES / "context_manifest.json")),
    ]
    for schema_name, instance in instances:
        Draft202012Validator(
            schemas[schema_name],
            registry=registry,
            format_checker=FormatChecker(),
        ).validate(instance)
    assert unexpected_retrievals == []
