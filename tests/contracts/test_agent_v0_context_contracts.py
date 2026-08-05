import hashlib
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
    "route.local_name",
    "route.scenic_character",
    "dynamic.closure",
    "dynamic.construction",
    "dynamic.surface_damage",
    "dynamic.supply_closed",
}

ROUTE_SHAPE_OWNER_TYPES = {
    "cycling_area",
    "named_route",
    "named_line",
    "climb",
    "classic_ride",
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


def relation_type_values():
    schema = load_json(CONTRACT_DIR / SCHEMA_FILES["world_fact"])
    return set(schema["$defs"]["relation_type"]["enum"])


def assert_registry_semantics(registry_document):
    assert_unique_predicate_ids(registry_document)
    for definition in registry_document["predicates"]:
        assert definition["predicate_id"] != "route.exit_option"
        assert definition["category"] != "relation"
        assert "unknown" not in definition.get("enum_values", [])
        assert "unknown" not in definition["freshness_policy"]["expected_statuses"]


def parse_rfc3339_timestamp(value):
    assert isinstance(value, str) and "T" in value
    normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    assert parsed.tzinfo is not None and parsed.utcoffset() is not None
    return parsed


def assert_time_window_ordered(time_window):
    assert parse_rfc3339_timestamp(time_window["start"]) < parse_rfc3339_timestamp(
        time_window["end"]
    )


def assert_validity_ordered(value, *, require_both=False):
    if require_both:
        assert "valid_from" in value and "valid_until" in value
    if "valid_from" in value and "valid_until" in value:
        assert parse_rfc3339_timestamp(value["valid_from"]) < parse_rfc3339_timestamp(
            value["valid_until"]
        )


def assert_typed_value_semantics(value, definition, *, forbid_unknown_enum=False):
    assert value["value_kind"] == definition["value_kind"]
    if value["value_kind"] == "enum":
        if forbid_unknown_enum:
            assert value["enum_value"] != "unknown"
        assert value["enum_value"] in definition["enum_values"]
    unit_code = typed_value_unit(value)
    if unit_code is not None:
        assert unit_code in definition["unit_codes"]
    if value["value_kind"] == "number_range":
        number_range = value["number_range_value"]
        assert number_range["minimum"] <= number_range["maximum"]


def assert_scope_requirements(scope, definition):
    requirements = definition["scope_requirements"]
    if requirements["traversal_scope"]:
        assert "traversal_ref" in scope
    if requirements["direction_scope"]:
        assert "direction" in scope
    if requirements["spatial_scope"] == "required":
        assert "spatial_interval" in scope
    if requirements["time_window"] == "required":
        assert "time_window" in scope


def focus_route_shapes(world_packet):
    objects_by_ref = {
        (item["object_ref"]["object_id"], item["object_ref"]["object_type"]): item
        for item in world_packet["objects"]
    }
    shapes = set()
    for focus_ref in world_packet["query_context"]["focus_refs"]:
        focus_key = (focus_ref["object_id"], focus_ref["object_type"])
        if focus_ref["object_type"] in ROUTE_SHAPE_OWNER_TYPES:
            assert focus_key in objects_by_ref
            assert "route_shape" in objects_by_ref[focus_key]
            shapes.add(objects_by_ref[focus_key]["route_shape"])
    return shapes


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
    relation_types = relation_type_values()
    query_context = world_packet["query_context"]
    if world_packet["packet_environment"] == "test":
        assert world_packet["fixture_only"] is True
        assert query_context["synthetic_fixture_data"] is True
    else:
        assert world_packet["fixture_only"] is False
        assert query_context["synthetic_fixture_data"] is False

    assert all(
        object_ref["object_type"] != "rider"
        for object_ref in walk_object_refs(world_packet)
    )
    assert set(query_context["requested_predicate_ids"]) <= set(definitions)
    assert set(query_context["requested_relation_types"]) <= relation_types
    if "time_window" in query_context:
        assert_time_window_ordered(query_context["time_window"])
    assert_unique_values(world_packet["objects"], "object_ref")
    assert_unique_values(world_packet["traversals"], "traversal_ref")
    assert_unique_values(world_packet["relations"], "relation_id")
    assert_unique_values(world_packet["facts"], "fact_id")
    assert_unique_values(world_packet["dynamic_states"], "state_id")
    assert_unique_values(world_packet["advisories"], "advisory_id")
    assert_unique_values(world_packet["unknowns"], "unknown_id")
    assert_unique_values(world_packet["provenance_index"], "provenance_id")
    omission_keys = [
        (item["request_kind"], item["request_id"])
        for item in world_packet["request_omissions"]
    ]
    assert len(omission_keys) == len(set(omission_keys))

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
    traversal_directions = {
        (
            item["traversal_ref"]["object_id"],
            item["traversal_ref"]["object_type"],
        ): item["direction"]
        for item in world_packet["traversals"]
    }
    known_refs = object_refs | traversal_refs
    fact_ids = {item["fact_id"] for item in world_packet["facts"]}

    for focus_ref in world_packet["query_context"]["focus_refs"]:
        assert focus_ref["object_type"] != "rider"
        assert (focus_ref["object_id"], focus_ref["object_type"]) in known_refs
    focus_route_shapes(world_packet)

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
            traversal_key = (
                traversal_ref["object_id"],
                traversal_ref["object_type"],
            )
            assert traversal_key in traversal_refs
            if "direction" in scope:
                assert scope["direction"] == traversal_directions[traversal_key]
        if "spatial_interval" in scope:
            spatial_interval = scope["spatial_interval"]
            interval_ref = spatial_interval["interval_ref"]
            assert (
                interval_ref["object_id"],
                interval_ref["object_type"],
            ) in object_refs
            assert spatial_interval["from_fraction"] <= spatial_interval["to_fraction"]
        if "time_window" in scope:
            assert_time_window_ordered(scope["time_window"])

    for item in world_packet["objects"]:
        assert item["object_ref"]["object_type"] != "rider"
        assert item["object_ref"] == item["revision_ref"]["object_ref"]
        if item["object_ref"]["object_type"] not in ROUTE_SHAPE_OWNER_TYPES:
            assert "route_shape" not in item

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
        assert_typed_value_semantics(
            item["value"], definition, forbid_unknown_enum=True
        )
        assert_scope_requirements(item["scope"], definition)
        if "traversal_ref" in item["scope"]:
            traversal_key = (
                item["scope"]["traversal_ref"]["object_id"],
                item["scope"]["traversal_ref"]["object_type"],
            )
            assert traversal_key in traversal_refs

        assert item["claim_kind"] == definition["category"]
        assert item["fact_status"] in definition["allowed_fact_statuses"]
        assert item["freshness"]["freshness_status"] != "unknown"
        assert item["freshness"]["policy_ref"] == definition["freshness_policy"][
            "policy_ref"
        ]
        assert item["freshness"]["freshness_status"] in definition[
            "freshness_policy"
        ]["expected_statuses"]
        assert_validity_ordered(item["freshness"])
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
        assert item["state_type"] in definitions
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
        assert_scope_requirements(item["scope"], definition)
        assert_validity_ordered(item)
        assert_validity_ordered(
            item["freshness"],
            require_both=definition["freshness_policy"]["time_bound"],
        )
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
        assert relation["relation_type"] in relation_types
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
        assert_typed_value_semantics(advisory["reported_value"], definition)
        assert_scope_requirements(advisory["scope"], definition)
        assert advisory["freshness"]["policy_ref"] == definition[
            "freshness_policy"
        ]["policy_ref"]
        assert advisory["freshness"]["freshness_status"] in definition[
            "freshness_policy"
        ]["expected_statuses"]
        assert advisory["observed_at"] == advisory["freshness"]["observed_at"]
        assert_validity_ordered(
            advisory["freshness"],
            require_both=definition["freshness_policy"]["time_bound"],
        )
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
        has_predicate = "predicate_id" in item
        has_relation = "relation_type" in item
        assert has_predicate is not has_relation
        if has_predicate:
            assert item["predicate_id"] in definitions
        else:
            assert item["relation_type"] in relation_types
        subject_ref = item["subject_ref"]
        assert (subject_ref["object_id"], subject_ref["object_type"]) in known_refs

    requested_predicates = set(query_context["requested_predicate_ids"])
    requested_relations = set(query_context["requested_relation_types"])
    predicate_responses = {
        item["predicate_id"] for item in world_packet["facts"]
    } | {item["state_type"] for item in world_packet["dynamic_states"]} | {
        item["advisory_type"] for item in world_packet["advisories"]
    } | {
        item["predicate_id"]
        for item in world_packet["unknowns"]
        if "predicate_id" in item
    }
    relation_responses = {
        item["relation_type"] for item in world_packet["relations"]
    } | {
        item["relation_type"]
        for item in world_packet["unknowns"]
        if "relation_type" in item
    }
    omitted_predicates = set()
    omitted_relations = set()
    for omission in world_packet["request_omissions"]:
        if omission["request_kind"] == "predicate":
            assert omission["request_id"] in requested_predicates
            assert omission["request_id"] not in predicate_responses
            omitted_predicates.add(omission["request_id"])
        else:
            assert omission["request_id"] in requested_relations
            assert omission["request_id"] not in relation_responses
            omitted_relations.add(omission["request_id"])
    assert requested_predicates <= predicate_responses | omitted_predicates
    assert requested_relations <= relation_responses | omitted_relations

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
    assert_registry_semantics(registry_document)

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


def test_registry_rejects_unknown_enum_and_freshness_regressions(
    schemas, local_registry
):
    registry_document = load_json(CONTRACT_DIR / "predicate_registry.v0.json")

    enum_unknown = deepcopy(registry_document)
    predicate_map(enum_unknown)["route.surface_type"]["enum_values"].append("unknown")
    assert validation_errors(
        "predicate_registry", enum_unknown, schemas, local_registry
    )
    with pytest.raises(AssertionError):
        assert_registry_semantics(enum_unknown)

    freshness_unknown = deepcopy(registry_document)
    predicate_map(freshness_unknown)["route.surface_type"]["freshness_policy"][
        "expected_statuses"
    ].append("unknown")
    assert validation_errors(
        "predicate_registry", freshness_unknown, schemas, local_registry
    )
    with pytest.raises(AssertionError):
        assert_registry_semantics(freshness_unknown)


def test_registry_rejects_relation_category_and_exit_option_regressions(
    schemas, local_registry
):
    registry_document = load_json(CONTRACT_DIR / "predicate_registry.v0.json")

    relation_category = deepcopy(registry_document)
    relation_category["predicates"][0]["category"] = "relation"
    assert validation_errors(
        "predicate_registry", relation_category, schemas, local_registry
    )
    with pytest.raises(AssertionError):
        assert_registry_semantics(relation_category)

    exit_option = deepcopy(registry_document)
    exit_definition = deepcopy(predicate_map(exit_option)["route.local_name"])
    exit_definition["predicate_id"] = "route.exit_option"
    exit_option["predicates"].append(exit_definition)
    validator_for("predicate_registry", schemas, local_registry).validate(exit_option)
    with pytest.raises(AssertionError):
        assert_registry_semantics(exit_option)


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

    primary_shapes = set().union(
        *(focus_route_shapes(load_json(fixture_path)) for fixture_path in world_paths)
    )
    assert primary_shapes == {"linear_climb", "corridor"}


def test_formal_facts_cannot_encode_missing_values_as_unknown(
    schemas, local_registry
):
    packet = load_json(VALID_FIXTURES / "world_fact_tianlongshan_linear_climb.json")
    definitions = predicate_map(load_json(CONTRACT_DIR / "predicate_registry.v0.json"))
    fact_index = next(
        index
        for index, fact in enumerate(packet["facts"])
        if fact["predicate_id"] == "route.climb_rhythm"
    )

    enum_unknown = deepcopy(packet)
    enum_unknown["facts"][fact_index]["value"]["enum_value"] = "unknown"
    definitions_with_unknown = deepcopy(definitions)
    definitions_with_unknown["route.climb_rhythm"]["enum_values"].append("unknown")
    assert validation_errors("world_fact", enum_unknown, schemas, local_registry)
    with pytest.raises(AssertionError):
        assert_world_semantics(enum_unknown, definitions_with_unknown)

    freshness_unknown = deepcopy(packet)
    freshness_unknown["facts"][fact_index]["freshness"][
        "freshness_status"
    ] = "unknown"
    definitions_with_unknown = deepcopy(definitions)
    definitions_with_unknown["route.climb_rhythm"]["freshness_policy"][
        "expected_statuses"
    ].append("unknown")
    assert validation_errors("world_fact", freshness_unknown, schemas, local_registry)
    with pytest.raises(AssertionError):
        assert_world_semantics(freshness_unknown, definitions_with_unknown)


def test_missing_fact_can_be_represented_by_explicit_unknown(schemas, local_registry):
    packet = load_json(VALID_FIXTURES / "world_fact_tianlongshan_linear_climb.json")
    definitions = predicate_map(load_json(CONTRACT_DIR / "predicate_registry.v0.json"))
    missing_fact = deepcopy(packet)
    missing_fact["facts"] = [
        fact
        for fact in missing_fact["facts"]
        if fact["predicate_id"] != "route.climb_rhythm"
    ]
    missing_fact["packet_limits"]["facts_included"] -= 1
    missing_fact["unknowns"].append(
        {
            "unknown_id": "unknown.tianlongshan-climb-rhythm",
            "subject_ref": {
                "object_id": "climb.tianlongshan-main-001",
                "object_type": "climb",
            },
            "predicate_id": "route.climb_rhythm",
            "reason_code": "no_reliable_value",
            "blocking": False,
            "user_safe_summary": "当前没有可靠的爬坡节奏事实。",
        }
    )
    validator_for("world_fact", schemas, local_registry).validate(missing_fact)
    assert_world_semantics(missing_fact, definitions)


def test_focus_route_shape_is_required_independent_of_object_order(
    schemas, local_registry
):
    packet = load_json(VALID_FIXTURES / "world_fact_fenhe_dual_bank_corridor.json")
    definitions = predicate_map(load_json(CONTRACT_DIR / "predicate_registry.v0.json"))

    missing_focus_shape = deepcopy(packet)
    del missing_focus_shape["objects"][0]["route_shape"]
    validator_for("world_fact", schemas, local_registry).validate(missing_focus_shape)
    with pytest.raises(AssertionError):
        assert_world_semantics(missing_focus_shape, definitions)

    reordered = deepcopy(packet)
    reordered["objects"].reverse()
    validator_for("world_fact", schemas, local_registry).validate(reordered)
    assert_world_semantics(reordered, definitions)
    assert focus_route_shapes(reordered) == {"corridor"}


@pytest.mark.parametrize("object_type", ["road_section", "destination"])
def test_non_route_shape_owners_reject_route_shape(
    object_type, schemas, local_registry
):
    packet = load_json(VALID_FIXTURES / "world_fact_fenhe_dual_bank_corridor.json")
    definitions = predicate_map(load_json(CONTRACT_DIR / "predicate_registry.v0.json"))
    invalid_owner = deepcopy(packet)
    target = next(
        item
        for item in invalid_owner["objects"]
        if item["object_ref"]["object_type"] == object_type
    )
    target["route_shape"] = "corridor"
    assert validation_errors("world_fact", invalid_owner, schemas, local_registry)
    with pytest.raises(AssertionError):
        assert_world_semantics(invalid_owner, definitions)


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
        "metric.moving_time_range_s",
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


@pytest.mark.parametrize("missing_field", ["reported_value", "freshness"])
def test_advisory_requires_typed_value_and_freshness(
    missing_field, schemas, local_registry
):
    packet = load_json(VALID_FIXTURES / "world_fact_tianlongshan_linear_climb.json")
    invalid = deepcopy(packet)
    del invalid["advisories"][0][missing_field]
    errors = validation_errors("world_fact", invalid, schemas, local_registry)
    assert any(
        path_text(error) == "advisories/0" and error.validator == "required"
        for error in errors
    )


def test_advisory_registry_value_and_scope_mutations_are_rejected():
    definitions = predicate_map(load_json(CONTRACT_DIR / "predicate_registry.v0.json"))
    tianlongshan = load_json(
        VALID_FIXTURES / "world_fact_tianlongshan_linear_climb.json"
    )
    fenhe = load_json(VALID_FIXTURES / "world_fact_fenhe_dual_bank_corridor.json")

    bad_enum = deepcopy(tianlongshan)
    bad_enum["advisories"][0]["reported_value"]["enum_value"] = "banana"
    with pytest.raises(AssertionError):
        assert_world_semantics(bad_enum, definitions)

    bad_unit = deepcopy(tianlongshan)
    advisory = bad_unit["advisories"][0]
    advisory["advisory_type"] = "metric.distance_m"
    advisory["reported_value"] = {
        "value_kind": "number",
        "number_value": 42,
        "unit_code": "km",
    }
    advisory["freshness"] = {
        "freshness_status": "static",
        "observed_at": advisory["observed_at"],
        "policy_ref": "freshness.computed_revision.v1",
    }
    with pytest.raises(AssertionError):
        assert_world_semantics(bad_unit, definitions)

    missing_traversal = deepcopy(tianlongshan)
    del missing_traversal["advisories"][0]["scope"]["traversal_ref"]
    with pytest.raises(AssertionError):
        assert_world_semantics(missing_traversal, definitions)

    missing_direction = deepcopy(tianlongshan)
    del missing_direction["advisories"][0]["scope"]["direction"]
    with pytest.raises(AssertionError):
        assert_world_semantics(missing_direction, definitions)

    missing_spatial_scope = deepcopy(fenhe)
    del missing_spatial_scope["advisories"][0]["scope"]["spatial_interval"]
    with pytest.raises(AssertionError):
        assert_world_semantics(missing_spatial_scope, definitions)

    missing_time_scope = deepcopy(fenhe)
    del missing_time_scope["advisories"][0]["scope"]["time_window"]
    with pytest.raises(AssertionError):
        assert_world_semantics(missing_time_scope, definitions)


def test_advisory_freshness_mutations_are_rejected():
    definitions = predicate_map(load_json(CONTRACT_DIR / "predicate_registry.v0.json"))
    tianlongshan = load_json(
        VALID_FIXTURES / "world_fact_tianlongshan_linear_climb.json"
    )
    fenhe = load_json(VALID_FIXTURES / "world_fact_fenhe_dual_bank_corridor.json")

    wrong_policy = deepcopy(tianlongshan)
    wrong_policy["advisories"][0]["freshness"]["policy_ref"] = (
        "freshness.dynamic_72h.v1"
    )
    with pytest.raises(AssertionError):
        assert_world_semantics(wrong_policy, definitions)

    wrong_status = deepcopy(tianlongshan)
    wrong_status["advisories"][0]["freshness"]["freshness_status"] = "current"
    with pytest.raises(AssertionError):
        assert_world_semantics(wrong_status, definitions)

    missing_validity = deepcopy(fenhe)
    del missing_validity["advisories"][0]["freshness"]["valid_until"]
    with pytest.raises(AssertionError):
        assert_world_semantics(missing_validity, definitions)

    reversed_validity = deepcopy(fenhe)
    reversed_validity["advisories"][0]["freshness"]["valid_from"] = (
        "2026-08-06T08:00:00+08:00"
    )
    with pytest.raises(AssertionError):
        assert_world_semantics(reversed_validity, definitions)

    mismatched_observation = deepcopy(tianlongshan)
    mismatched_observation["advisories"][0]["observed_at"] = (
        "2026-07-29T09:00:00+08:00"
    )
    with pytest.raises(AssertionError):
        assert_world_semantics(mismatched_observation, definitions)


def test_relation_type_has_one_schema_definition():
    schema = load_json(CONTRACT_DIR / "world_fact_packet.schema.json")
    relation_ref = {"$ref": "#/$defs/relation_type"}
    assert schema["$defs"]["query_context"]["properties"][
        "requested_relation_types"
    ]["items"] == relation_ref
    assert schema["$defs"]["relation"]["properties"]["relation_type"] == relation_ref
    assert schema["$defs"]["world_unknown_item"]["properties"][
        "relation_type"
    ] == relation_ref


def test_requested_predicate_and_relation_need_explicit_responses():
    definitions = predicate_map(load_json(CONTRACT_DIR / "predicate_registry.v0.json"))
    packet = load_json(VALID_FIXTURES / "world_fact_fenhe_dual_bank_corridor.json")

    missing_predicate_response = deepcopy(packet)
    missing_predicate_response["facts"] = [
        fact
        for fact in missing_predicate_response["facts"]
        if fact["predicate_id"] != "route.group_ride_suitability"
    ]
    missing_predicate_response["packet_limits"]["facts_included"] -= 1
    with pytest.raises(AssertionError):
        assert_world_semantics(missing_predicate_response, definitions)

    missing_relation_response = deepcopy(packet)
    missing_relation_response["relations"] = [
        relation
        for relation in missing_relation_response["relations"]
        if relation["relation_type"] != "exit_to"
    ]
    with pytest.raises(AssertionError):
        assert_world_semantics(missing_relation_response, definitions)


def test_relation_request_accepts_typed_unknown_or_typed_omission(
    schemas, local_registry
):
    definitions = predicate_map(load_json(CONTRACT_DIR / "predicate_registry.v0.json"))
    packet = load_json(VALID_FIXTURES / "world_fact_fenhe_dual_bank_corridor.json")

    relation_unknown = deepcopy(packet)
    relation_unknown["relations"] = [
        relation
        for relation in relation_unknown["relations"]
        if relation["relation_type"] != "exit_to"
    ]
    relation_unknown["unknowns"].append(
        {
            "unknown_id": "unknown.fenhe-exit-relation",
            "subject_ref": {
                "object_id": "route.fenhe-dual-bank-001",
                "object_type": "named_route",
            },
            "relation_type": "exit_to",
            "reason_code": "no_reliable_relation",
            "blocking": False,
            "user_safe_summary": "当前没有可靠的退出关系。",
        }
    )
    validator_for("world_fact", schemas, local_registry).validate(relation_unknown)
    assert_world_semantics(relation_unknown, definitions)

    relation_omission = deepcopy(packet)
    relation_omission["relations"] = [
        relation
        for relation in relation_omission["relations"]
        if relation["relation_type"] != "exit_to"
    ]
    relation_omission["request_omissions"].append(
        {
            "request_kind": "relation",
            "request_id": "exit_to",
            "reason": "token_budget",
            "user_safe_summary": "受 token 预算限制，本次未投影退出关系。",
        }
    )
    validator_for("world_fact", schemas, local_registry).validate(relation_omission)
    assert_world_semantics(relation_omission, definitions)


def test_request_omission_and_world_unknown_are_fail_closed(
    schemas, local_registry
):
    definitions = predicate_map(load_json(CONTRACT_DIR / "predicate_registry.v0.json"))
    packet = load_json(VALID_FIXTURES / "world_fact_fenhe_dual_bank_corridor.json")

    unrequested_omission = deepcopy(packet)
    unrequested_omission["request_omissions"].append(
        {
            "request_kind": "predicate",
            "request_id": "route.local_name",
            "reason": "privacy",
            "user_safe_summary": "未请求项不能声明 omission。",
        }
    )
    validator_for("world_fact", schemas, local_registry).validate(
        unrequested_omission
    )
    with pytest.raises(AssertionError):
        assert_world_semantics(unrequested_omission, definitions)

    response_and_omission = deepcopy(packet)
    response_and_omission["request_omissions"].append(
        {
            "request_kind": "relation",
            "request_id": "exit_to",
            "reason": "token_budget",
            "user_safe_summary": "已有响应的请求不能同时声明完整 omission。",
        }
    )
    validator_for("world_fact", schemas, local_registry).validate(
        response_and_omission
    )
    with pytest.raises(AssertionError):
        assert_world_semantics(response_and_omission, definitions)

    both_unknown_kinds = deepcopy(packet)
    both_unknown_kinds["unknowns"][0]["relation_type"] = "exit_to"
    assert validation_errors(
        "world_fact", both_unknown_kinds, schemas, local_registry
    )
    with pytest.raises(AssertionError):
        assert_world_semantics(both_unknown_kinds, definitions)

    neither_unknown_kind = deepcopy(packet)
    del neither_unknown_kind["unknowns"][0]["predicate_id"]
    assert validation_errors(
        "world_fact", neither_unknown_kind, schemas, local_registry
    )
    with pytest.raises(AssertionError):
        assert_world_semantics(neither_unknown_kind, definitions)


def test_number_spatial_and_time_order_mutations_are_rejected():
    definitions = predicate_map(load_json(CONTRACT_DIR / "predicate_registry.v0.json"))
    packet = load_json(VALID_FIXTURES / "world_fact_tianlongshan_linear_climb.json")

    reversed_number_range = deepcopy(packet)
    moving_time_fact = next(
        fact
        for fact in reversed_number_range["facts"]
        if fact["predicate_id"] == "metric.moving_time_range_s"
    )
    moving_time_fact["value"]["number_range_value"]["minimum"] = 10801
    moving_time_fact["value"]["number_range_value"]["maximum"] = 7200
    with pytest.raises(AssertionError):
        assert_world_semantics(reversed_number_range, definitions)

    reversed_spatial_interval = deepcopy(packet)
    spatial_interval = reversed_spatial_interval["dynamic_states"][0]["scope"][
        "spatial_interval"
    ]
    spatial_interval["from_fraction"] = 0.8
    spatial_interval["to_fraction"] = 0.2
    with pytest.raises(AssertionError):
        assert_world_semantics(reversed_spatial_interval, definitions)

    equal_time_window = deepcopy(packet)
    time_window = equal_time_window["dynamic_states"][0]["scope"]["time_window"]
    time_window["end"] = time_window["start"]
    with pytest.raises(AssertionError):
        assert_world_semantics(equal_time_window, definitions)

    reversed_time_window = deepcopy(packet)
    time_window = reversed_time_window["dynamic_states"][0]["scope"]["time_window"]
    time_window["start"] = "2026-08-05T00:00:00+08:00"
    with pytest.raises(AssertionError):
        assert_world_semantics(reversed_time_window, definitions)

    equal_dynamic_validity = deepcopy(packet)
    dynamic_state = equal_dynamic_validity["dynamic_states"][0]
    dynamic_state["valid_until"] = dynamic_state["valid_from"]
    with pytest.raises(AssertionError):
        assert_world_semantics(equal_dynamic_validity, definitions)

    reversed_dynamic_validity = deepcopy(packet)
    reversed_dynamic_validity["dynamic_states"][0]["valid_from"] = (
        "2026-08-05T00:00:00+08:00"
    )
    with pytest.raises(AssertionError):
        assert_world_semantics(reversed_dynamic_validity, definitions)


def test_time_order_uses_timezone_aware_rfc3339_comparison():
    definitions = predicate_map(load_json(CONTRACT_DIR / "predicate_registry.v0.json"))
    packet = load_json(VALID_FIXTURES / "world_fact_tianlongshan_linear_climb.json")
    timezone_crossing = deepcopy(packet)
    timezone_crossing["query_context"]["time_window"] = {
        "start": "2026-08-03T23:00:00+08:00",
        "end": "2026-08-03T16:30:00+00:00",
    }
    assert_world_semantics(timezone_crossing, definitions)


@pytest.mark.parametrize(
    ("packet_environment", "fixture_only", "synthetic_fixture_data"),
    [
        ("production", True, False),
        ("production", False, True),
        ("shadow", True, False),
        ("shadow", False, True),
        ("test", False, True),
        ("test", True, False),
    ],
)
def test_packet_environment_combinations_fail_closed(
    packet_environment,
    fixture_only,
    synthetic_fixture_data,
    schemas,
    local_registry,
):
    definitions = predicate_map(load_json(CONTRACT_DIR / "predicate_registry.v0.json"))
    packet = load_json(VALID_FIXTURES / "world_fact_tianlongshan_linear_climb.json")
    invalid = deepcopy(packet)
    invalid["packet_environment"] = packet_environment
    invalid["fixture_only"] = fixture_only
    invalid["query_context"]["synthetic_fixture_data"] = synthetic_fixture_data
    assert validation_errors("world_fact", invalid, schemas, local_registry)
    with pytest.raises(AssertionError):
        assert_world_semantics(invalid, definitions)


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
