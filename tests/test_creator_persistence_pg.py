"""Creator persistence v0 against a real isolated PostgreSQL database."""

from concurrent.futures import ThreadPoolExecutor
import importlib
import json
import os
from pathlib import Path
import subprocess
from threading import Barrier
import uuid

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, func, inspect, select, text, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.creator_persistence.canonical import canonical_json, content_hash
from app.creator_persistence.models import (
    CreatorEvidenceItem,
    CreatorJudgment,
    CreatorJudgmentContradiction,
    CreatorJudgmentDecision,
    CreatorSource,
    CreatorWorkspace,
    CreatorWorkspaceEvent,
)
from app.creator_persistence.router import create_creator_internal_router
from app.creator_persistence.service import (
    CAPABILITY_BY_EVENT_TYPE,
    CreatorAppendConflictError,
    CreatorAuthorizationError,
    CreatorPersistenceService,
    CreatorPrincipal,
    CreatorProjectionError,
    CreatorProjectionRevisionMismatchError,
    CreatorStaleRevisionError,
)


FULL = CreatorPrincipal(
    principal_id="test:creator-runtime",
    product="creator",
    environment="test",
    scopes=("context.read_private", *tuple(dict.fromkeys(CAPABILITY_BY_EVENT_TYPE.values()))),
)
AGENT = CreatorPrincipal(
    principal_id="test:creator-agent",
    product="creator",
    environment="test",
    scopes=tuple(scope for scope in FULL.scopes if scope != "judgment.decide"),
)
REVIEWER = CreatorPrincipal(
    principal_id="test:tim-reviewer",
    product="creator",
    environment="test",
    scopes=("context.read_private", "conversation.record", "judgment.decide"),
)


@pytest.fixture(scope="module")
def pg_engine():
    database_url = os.getenv("VELO_TEST_DATABASE_URL")
    required = os.getenv("VELO_REQUIRE_POSTGRES_TESTS") == "1"
    if not database_url:
        if required:
            pytest.fail("CI 必须提供 VELO_TEST_DATABASE_URL", pytrace=False)
        pytest.skip("仅在显式隔离的 VELO_TEST_DATABASE_URL 上运行")
    engine = None
    try:
        engine = create_engine(database_url, pool_pre_ping=True)
        with engine.connect() as connection:
            connection.execute(select(1))
        if "creator_workspace_events" not in inspect(engine).get_table_names():
            pytest.fail("Creator migration 尚未在隔离 PostgreSQL 执行", pytrace=False)
    except (SQLAlchemyError, ImportError) as exc:
        if engine is not None:
            engine.dispose()
        if required:
            pytest.fail(f"CI 隔离 PostgreSQL 不可用: {exc}", pytrace=False)
        pytest.skip(f"隔离 PostgreSQL 不可用: {exc}")
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def service(pg_engine):
    return CreatorPersistenceService(sessionmaker(bind=pg_engine, autocommit=False, autoflush=False))


def _workspace(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def _event(workspace_id: str, revision: int, event_id: str, event_type: str, minute: int, **payload):
    return {
        "schema_version": 1,
        "event_id": event_id,
        "workspace_id": workspace_id,
        "base_revision": revision,
        "occurred_at": f"2026-08-06T01:{minute:02d}:00.000Z",
        "type": event_type,
        **payload,
    }


def _start(service: CreatorPersistenceService, workspace_id: str):
    event = _event(
        workspace_id, 0, "event:start", "creator.workspace_started", 0,
        mission="保存来源与 Tim 判断，跨进程重放仍一致",
    )
    return service.append(event, FULL), event


def _source_sequence(service: CreatorPersistenceService, workspace_id: str, *, prefix: str = "source"):
    source = _event(
        workspace_id, 1, f"event:{prefix}", "creator.source_ingested", 1,
        source_ref=f"{prefix}:conversation", source_kind="conversation",
        content_hash=content_hash(f"{prefix}-material"),
        immutable_ref=f"sha256-object:{prefix}", provenance_ref=f"test:{prefix}",
    )
    rights = _event(
        workspace_id, 2, f"event:{prefix}:rights", "creator.rights_checked", 2,
        rights_check_id=f"rights:{prefix}", source_ref=f"{prefix}:conversation",
        decision="allowed", policy_ref="policy:test-v1", reason="隔离测试材料允许内部使用。",
    )
    service.append(source, FULL)
    service.append(rights, FULL)
    return source, rights


def test_canonical_hash_matches_typescript_for_unicode_and_numbers(tmp_path):
    value = {
        "z": 1.0,
        "中文": "天龙山",
        "number_boundaries": [0.000001, 0.0000001, 1.25e-5, 1e20, 1e21, -0.0],
        "nested": [True, None, {"b": 2, "a": "x"}],
    }
    value_path = tmp_path / "canonical-value.json"
    value_path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    script = (
        "import{readFile}from'node:fs/promises';"
        "import{canonicalJson,contentHash}from'./agent_runtime/shared/canonical.ts';"
        "const v=JSON.parse(await readFile(process.argv[1],'utf8'));"
        "process.stdout.write(JSON.stringify({json:canonicalJson(v),hash:contentHash(v)}));"
    )
    result = subprocess.run(
        ["node", "--experimental-strip-types", "--input-type=module", "-e", script, str(value_path)],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, check=True,
    )
    typescript = json.loads(result.stdout)
    assert typescript == {"json": canonical_json(value), "hash": content_hash(value)}


def test_migration_upgrade_downgrade_upgrade_round_trip(pg_engine):
    schema = f"creator_migration_{uuid.uuid4().hex}"
    migration = importlib.import_module("migrations.versions.20260806_creator_pg_v0")
    expected = {
        "creator_workspaces", "creator_workspace_events", "creator_sources", "creator_rights_checks", "creator_source_messages",
        "creator_source_message_subjects", "creator_evidence_items", "creator_judgments",
        "creator_judgment_turns", "creator_judgment_evidence", "creator_judgment_decisions",
        "creator_judgment_contradictions", "creator_judgment_contradiction_resolutions",
    }
    with pg_engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        with pg_engine.begin() as connection:
            connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()
            assert set(inspect(connection).get_table_names(schema=schema)) == expected
            migration.downgrade()
            assert inspect(connection).get_table_names(schema=schema) == []
            migration.upgrade()
            assert set(inspect(connection).get_table_names(schema=schema)) == expected
            migration.downgrade()
    finally:
        with pg_engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


def test_event_truth_is_physically_append_only_and_downgrade_refuses_data(pg_engine):
    schema = f"creator_append_only_{uuid.uuid4().hex}"
    migration = importlib.import_module("migrations.versions.20260806_creator_pg_v0")
    with pg_engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        with pg_engine.begin() as connection:
            connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()
            connection.execute(text(
                "INSERT INTO creator_workspaces (id, mission, current_revision) VALUES ('ws', 'mission', 1)"
            ))
            connection.execute(text("""
                INSERT INTO creator_workspace_events (
                    workspace_id, revision, event_id, event_type, schema_version, base_revision,
                    occurred_at, principal_id, principal_product, principal_environment,
                    authorized_capability, payload_json, payload_sha256
                ) VALUES (
                    'ws', 1, 'event:start', 'creator.workspace_started', 1, 0,
                    '2026-08-06T01:00:00Z', 'test', 'creator', 'test', 'workspace.create',
                    '{}', 'sha256:0000000000000000000000000000000000000000000000000000000000000000'
                )
            """))
        with pg_engine.begin() as connection:
            connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
            migration.op = Operations(MigrationContext.configure(connection))
            with pytest.raises(RuntimeError, match="拒绝"):
                migration.downgrade()
            with pytest.raises(SQLAlchemyError, match="append-only"):
                connection.execute(text(
                    "UPDATE creator_workspace_events SET principal_id = 'forged' WHERE workspace_id = 'ws'"
                ))
        with pg_engine.begin() as connection:
            connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
            with pytest.raises(SQLAlchemyError, match="append-only"):
                connection.execute(text("TRUNCATE creator_workspace_events CASCADE"))
    finally:
        with pg_engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


def test_concurrent_same_bootstrap_converges_without_orphan(service, pg_engine):
    workspace_id = _workspace("creator-bootstrap")
    event = _event(
        workspace_id, 0, "event:start", "creator.workspace_started", 0,
        mission="concurrent bootstrap",
    )
    barrier = Barrier(2)

    def append_once():
        barrier.wait(timeout=10)
        return service.append(event, FULL)

    with ThreadPoolExecutor(max_workers=2) as executor:
        receipts = list(executor.map(lambda _index: append_once(), range(2)))
    assert [receipt.committed_revision for receipt in receipts] == [1, 1]
    with pg_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(CreatorWorkspace).where(CreatorWorkspace.id == workspace_id)) == 1
        assert connection.scalar(select(func.count()).select_from(CreatorWorkspaceEvent).where(CreatorWorkspaceEvent.workspace_id == workspace_id)) == 1


def test_second_bootstrap_for_existing_workspace_is_a_conflict(service, pg_engine):
    workspace_id = _workspace("creator-bootstrap-conflict")
    _start(service, workspace_id)
    conflicting = _event(
        workspace_id, 0, "event:different-start", "creator.workspace_started", 0,
        mission="must not replace the existing workspace mission",
    )
    with pytest.raises(CreatorStaleRevisionError, match="already exists"):
        service.append(conflicting, FULL)
    with pg_engine.connect() as connection:
        assert connection.scalar(select(CreatorWorkspace.mission).where(
            CreatorWorkspace.id == workspace_id
        )) == "保存来源与 Tim 判断，跨进程重放仍一致"
        assert connection.scalar(select(func.count()).select_from(CreatorWorkspaceEvent).where(
            CreatorWorkspaceEvent.workspace_id == workspace_id
        )) == 1


def test_concurrent_distinct_writers_use_revision_cas(service, pg_engine):
    workspace_id = _workspace("creator-cas")
    _start(service, workspace_id)
    events = [
        _event(
            workspace_id, 1, f"event:source:{index}", "creator.source_ingested", 1,
            source_ref=f"source:{index}", source_kind="conversation",
            content_hash=content_hash(f"source-{index}"), immutable_ref=f"object:{index}", provenance_ref=f"test:{index}",
        )
        for index in (1, 2)
    ]
    barrier = Barrier(2)

    def append_once(event):
        barrier.wait(timeout=10)
        try:
            return ("committed", service.append(event, FULL).committed_revision)
        except CreatorStaleRevisionError:
            return ("stale", None)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(append_once, events))
    assert sorted(outcome[0] for outcome in outcomes) == ["committed", "stale"]
    with pg_engine.connect() as connection:
        assert connection.scalar(select(CreatorWorkspace.current_revision).where(CreatorWorkspace.id == workspace_id)) == 2
        assert connection.scalar(select(func.count()).select_from(CreatorWorkspaceEvent).where(CreatorWorkspaceEvent.workspace_id == workspace_id)) == 2
    assert service.read_projection_records(workspace_id, 2, FULL)["records"] == service.read_records(workspace_id, FULL)


def test_event_idempotency_conflict_and_projection_failure_roll_back(service, pg_engine):
    workspace_id = _workspace("creator-rollback")
    _start(service, workspace_id)
    source = _event(
        workspace_id, 1, "event:source", "creator.source_ingested", 1,
        source_ref="source:one", source_kind="conversation", content_hash=content_hash("one"),
        immutable_ref="object:one", provenance_ref="test:one",
    )
    first = service.append(source, FULL)
    second = service.append(source, FULL)
    assert first == second
    with pytest.raises(CreatorAppendConflictError):
        service.append({**source, "provenance_ref": "test:changed"}, FULL)

    duplicate_projection = _event(
        workspace_id, 2, "event:source-duplicate", "creator.source_ingested", 2,
        source_ref="source:one", source_kind="conversation", content_hash=content_hash("duplicate"),
        immutable_ref="object:duplicate", provenance_ref="test:duplicate",
    )
    with pytest.raises(CreatorProjectionError):
        service.append(duplicate_projection, FULL)
    with pg_engine.connect() as connection:
        assert connection.scalar(select(CreatorWorkspace.current_revision).where(CreatorWorkspace.id == workspace_id)) == 2
        assert connection.scalar(select(func.count()).select_from(CreatorWorkspaceEvent).where(CreatorWorkspaceEvent.workspace_id == workspace_id)) == 2


def test_commit_then_connection_loss_converges_by_exact_event_id(service, pg_engine):
    workspace_id = _workspace("creator-reconcile")
    event = _event(
        workspace_id, 0, "event:start", "creator.workspace_started", 0,
        mission="commit receipt reconciliation",
    )

    def commit_then_disconnect():
        service.append(event, FULL)
        raise ConnectionError("simulated connection loss after commit")

    with pytest.raises(ConnectionError, match="after commit"):
        commit_then_disconnect()
    reconciled = service.append(event, FULL)
    assert reconciled.committed_revision == 1
    with pg_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(CreatorWorkspaceEvent).where(
            CreatorWorkspaceEvent.workspace_id == workspace_id,
            CreatorWorkspaceEvent.event_id == event["event_id"],
        )) == 1


def test_rights_check_identity_cannot_be_reused_after_current_projection_changes(service, pg_engine):
    workspace_id = _workspace("creator-rights-id")
    _start(service, workspace_id)
    _source, first_rights = _source_sequence(service, workspace_id)
    second = _event(
        workspace_id, 3, "event:rights:second", "creator.rights_checked", 3,
        rights_check_id="rights:second", source_ref="source:conversation", decision="forbidden",
        policy_ref="policy:test-v2", reason="第二次检查撤销权限。",
    )
    service.append(second, FULL)
    reused = _event(
        workspace_id, 4, "event:rights:reused", "creator.rights_checked", 4,
        rights_check_id=first_rights["rights_check_id"], source_ref="source:conversation", decision="allowed",
        policy_ref="policy:test-v3", reason="不得复用第一次检查身份。",
    )
    with pytest.raises(CreatorProjectionError):
        service.append(reused, FULL)
    with pg_engine.connect() as connection:
        assert connection.scalar(select(CreatorWorkspace.current_revision).where(CreatorWorkspace.id == workspace_id)) == 4
        source = connection.execute(select(
            CreatorSource.rights_check_id, CreatorSource.rights_decision, CreatorSource.rights_event_revision
        ).where(CreatorSource.workspace_id == workspace_id)).one()
        assert source == ("rights:second", "forbidden", 4)


def test_python_boundary_rejects_events_typescript_cannot_cold_replay(service, pg_engine):
    workspace_id = _workspace("creator-poison")
    with pytest.raises(CreatorProjectionError, match="Unicode scalar"):
        service.append(_event(
            _workspace("creator-surrogate"), 0, "event:surrogate", "creator.workspace_started", 0,
            mission="bad\ud800text",
        ), FULL)
    with pytest.raises(CreatorProjectionError, match="unsafe"):
        service.append(_event(
            "creator/unsafe", 0, "event:unsafe", "creator.workspace_started", 0, mission="unsafe"
        ), FULL)
    _start(service, workspace_id)
    _source_sequence(service, workspace_id)
    bad_instant = _event(
        workspace_id, 3, "event:bad-instant", "creator.conversation_turn_recorded", 3,
        turn_id="turn:bad-instant", source_ref="source:conversation", source_message_ref="message:bad-instant",
        source_role="user", actor="tim", authorship_basis="direct_unquoted_message", raw_text="精确原文",
        content_hash=content_hash("精确原文"), subject_refs=["route:tianlongshan"],
    )
    bad_instant["occurred_at"] = "2026-08-06T01:03:00Z"
    with pytest.raises(CreatorProjectionError, match="canonical UTC"):
        service.append(bad_instant, REVIEWER)
    bad_hash = {**bad_instant, "occurred_at": "2026-08-06T01:03:00.000Z", "event_id": "event:bad-turn-hash"}
    bad_hash["content_hash"] = content_hash("不是这条原文")
    with pytest.raises(CreatorProjectionError, match="content_hash mismatch"):
        service.append(bad_hash, REVIEWER)

    service.append(_event(
        workspace_id, 3, "event:evidence", "creator.evidence_recorded", 3,
        evidence_id="evidence:guide", source_ref="source:conversation", subject_ref="route:tianlongshan",
        raw_observation="天龙山结构证据", observed_at="2026-08-01T00:00:00.000Z",
    ), AGENT)
    proposal = _proposal_event(
        workspace_id, 4, "event:bad-context", "judgment:bad-context", "上下文必须可重放。",
        "evidence:guide", 4,
    )
    proposal["context_as_of"] = "2026-08-06T01:04:00Z"
    proposal["context_request_hash"] = content_hash({
        "task": proposal["context_task"], "subject_refs": proposal["context_subject_refs"],
        "as_of": proposal["context_as_of"], "max_pending_turns": proposal["context_max_pending_turns"],
        "max_evidence": proposal["context_max_evidence"],
    })
    with pytest.raises(CreatorProjectionError, match="context_as_of"):
        service.append(proposal, AGENT)
    invalid_budget = {
        **proposal,
        "event_id": "event:bad-budget",
        "context_as_of": "2026-08-06T01:04:00.000Z",
        "context_max_evidence": -1,
    }
    invalid_budget["context_request_hash"] = content_hash({
        "task": invalid_budget["context_task"], "subject_refs": invalid_budget["context_subject_refs"],
        "as_of": invalid_budget["context_as_of"], "max_pending_turns": invalid_budget["context_max_pending_turns"],
        "max_evidence": invalid_budget["context_max_evidence"],
    })
    with pytest.raises(CreatorProjectionError, match="context_max_evidence"):
        service.append(invalid_budget, AGENT)

    unsorted_refs = {
        **proposal,
        "event_id": "event:unsorted-refs",
        "proposal_id": "judgment:unsorted-refs",
        "context_as_of": "2026-08-06T01:04:00.000Z",
        "evidence_refs": ["evidence:z", "evidence:a"],
    }
    with pytest.raises(CreatorProjectionError, match="evidence_refs must use JavaScript UTF-16 sort order"):
        service.append(unsorted_refs, AGENT)

    safe_number = {
        **proposal,
        "event_id": "event:safe-number",
        "proposal_id": "judgment:safe-number",
        "context_as_of": "2026-08-06T01:04:00.000Z",
        # JavaScript sorts strings by UTF-16 code units: the surrogate pair
        # for U+10000 precedes the BMP private-use U+E000 character.
        "context_subject_refs": ["\U00010000", "\ue000"],
        "typed_value": 2**53 - 1,
    }
    safe_number["context_request_hash"] = content_hash({
        "task": safe_number["context_task"], "subject_refs": safe_number["context_subject_refs"],
        "as_of": safe_number["context_as_of"], "max_pending_turns": safe_number["context_max_pending_turns"],
        "max_evidence": safe_number["context_max_evidence"],
    })
    service.append(safe_number, AGENT)
    unsafe_number = {
        **safe_number,
        "event_id": "event:unsafe-number",
        "proposal_id": "judgment:unsafe-number",
        "base_revision": 5,
        "typed_value": 2**53 + 1,
    }
    with pytest.raises(CreatorProjectionError, match="safe integer range"):
        service.append(unsafe_number, AGENT)
    unsafe_string = {
        **safe_number,
        "event_id": "event:unsafe-string",
        "proposal_id": "judgment:unsafe-string",
        "base_revision": 5,
        "typed_value": "bad\ud800text",
    }
    with pytest.raises(CreatorProjectionError, match="Unicode scalar"):
        service.append(unsafe_string, AGENT)
    with pg_engine.connect() as connection:
        assert connection.scalar(select(CreatorWorkspace.current_revision).where(CreatorWorkspace.id == workspace_id)) == 5
        assert connection.scalar(select(func.count()).select_from(CreatorWorkspaceEvent).where(
            CreatorWorkspaceEvent.workspace_id == workspace_id
        )) == 5


def _proposal_event(workspace_id: str, revision: int, event_id: str, proposal_id: str, statement: str, evidence_id: str, minute: int, **extra):
    request = {
        "task": "判断天龙山路线结构", "subject_refs": ["route:tianlongshan"],
        "as_of": f"2026-08-06T01:{minute:02d}:00.000Z", "max_pending_turns": 20, "max_evidence": 30,
    }
    return _event(
        workspace_id, revision, event_id, "creator.judgment_proposed", minute,
        proposal_id=proposal_id, judgment_key="route.tianlongshan.structure", subject_ref="route:tianlongshan",
        statement=statement, statement_hash=content_hash(statement), typed_value="linear_core_climb",
        temporality="slow_changing", review_at="2027-01-01T00:00:00.000Z",
        context_compiler_version="creator-context-v0", context_request_hash=content_hash(request),
        context_task=request["task"], context_subject_refs=request["subject_refs"], context_as_of=request["as_of"],
        context_max_pending_turns=20, context_max_evidence=30, context_hash=content_hash({"fixture": proposal_id}),
        model_ref="shadow:test", source_turn_refs=[], evidence_refs=[evidence_id],
        reason="真实证据支持该判断。", **extra,
    )


def _append_exact_decision_loop(service: CreatorPersistenceService, workspace_id: str):
    _start(service, workspace_id)
    _source_sequence(service, workspace_id)
    evidence = _event(
        workspace_id, 3, "event:evidence", "creator.evidence_recorded", 3,
        evidence_id="evidence:guide", source_ref="source:conversation", subject_ref="route:tianlongshan",
        raw_observation="坡不算陡，但够长。", observed_at="2026-08-01T00:00:00.000Z",
    )
    service.append(evidence, AGENT)
    statement = "天龙山是一条以长距离耐力爬升为核心的路线认知对象。"
    proposal = _proposal_event(workspace_id, 4, "event:proposal", "judgment:v1", statement, "evidence:guide", 4)
    service.append(proposal, AGENT)
    exact_turn = _event(
        workspace_id, 5, "event:review-turn", "creator.conversation_turn_recorded", 5,
        turn_id="turn:confirm-v1", source_ref="source:conversation", source_message_ref="message:confirm-v1",
        source_role="user", actor="tim", authorship_basis="direct_unquoted_message", raw_text="确认第一版判断",
        content_hash=content_hash("确认第一版判断"), subject_refs=["route:tianlongshan"],
        interaction={"kind": "judgment_response", "proposal_id": "judgment:v1", "statement_hash": content_hash(statement), "response": "tim_confirmed"},
    )
    service.append(exact_turn, REVIEWER)
    decision = _event(
        workspace_id, 6, "event:decision", "creator.judgment_responded", 6,
        decision_id="decision:v1", proposal_id="judgment:v1", response_turn_ref="turn:confirm-v1",
        response="tim_confirmed", expected_statement_hash=content_hash(statement),
    )
    return statement, decision


def test_exact_tim_decision_binding_and_authenticated_receipt(service, pg_engine):
    workspace_id = _workspace("creator-decision")
    statement, decision = _append_exact_decision_loop(service, workspace_id)
    with pytest.raises(CreatorAuthorizationError):
        service.append(decision, AGENT)

    plain_turn = _event(
        workspace_id, 6, "event:plain-turn", "creator.conversation_turn_recorded", 6,
        turn_id="turn:plain", source_ref="source:conversation", source_message_ref="message:plain",
        source_role="user", actor="tim", authorship_basis="direct_unquoted_message", raw_text="我同意",
        content_hash=content_hash("我同意"), subject_refs=["route:tianlongshan"],
    )
    service.append(plain_turn, REVIEWER)
    prose_decision = {
        **decision,
        "base_revision": 7,
        "event_id": "event:prose-decision",
        "occurred_at": "2026-08-06T01:07:30.000Z",
        "response_turn_ref": "turn:plain",
    }
    with pytest.raises(CreatorProjectionError):
        service.append(prose_decision, REVIEWER)

    decision = {
        **decision,
        "base_revision": 7,
        "occurred_at": "2026-08-06T01:08:00.000Z",
    }
    wrong_proposal = {
        **decision,
        "event_id": "event:wrong-proposal",
        "proposal_id": "judgment:missing",
    }
    with pytest.raises(CreatorProjectionError):
        service.append(wrong_proposal, REVIEWER)
    bad_hash = {**decision, "expected_statement_hash": content_hash(statement + " changed")}
    with pytest.raises(CreatorProjectionError):
        service.append(bad_hash, REVIEWER)
    receipt = service.append(decision, REVIEWER)
    assert receipt.committed_revision == 8
    with pg_engine.connect() as connection:
        stored = connection.execute(
            select(CreatorJudgment.status, CreatorJudgmentDecision.reviewer_principal_id)
            .join(
                CreatorJudgmentDecision,
                (CreatorJudgmentDecision.workspace_id == CreatorJudgment.workspace_id)
                & (CreatorJudgmentDecision.proposal_id == CreatorJudgment.proposal_id),
            )
            .where(CreatorJudgment.workspace_id == workspace_id)
        ).one()
        assert stored == ("tim_confirmed", REVIEWER.principal_id)
        assert connection.scalar(select(CreatorWorkspace.current_revision).where(CreatorWorkspace.id == workspace_id)) == 8


def test_replacement_keeps_old_current_until_exact_confirmation(service, pg_engine):
    workspace_id = _workspace("creator-replacement")
    _statement, first_decision = _append_exact_decision_loop(service, workspace_id)
    service.append(first_decision, REVIEWER)
    service.append(_event(
        workspace_id, 7, "event:contradiction", "creator.judgment_contradiction_recorded", 8,
        contradiction_id="contradiction:v1", judgment_id="judgment:v1", contradicting_ref="evidence:guide",
        reason="新证据要求形成更精确的替代判断。",
    ), AGENT)
    service.append(_event(
        workspace_id, 8, "event:needs-more", "creator.judgment_contradiction_resolved", 9,
        resolution_id="resolution:needs-more", contradiction_id="contradiction:v1",
        resolution="needs_more_evidence", resolution_ref="evidence:guide", reason="先继续收集证据。",
    ), AGENT)
    assert service.read_projection_digest(workspace_id, FULL)["unresolved_contradiction_refs"] == ["contradiction:v1"]
    replacement_statement = "天龙山是线性、核心爬坡、半开放的路线认知对象。"
    replacement = _proposal_event(
        workspace_id, 9, "event:replacement", "judgment:v2", replacement_statement,
        "evidence:guide", 10, supersedes_judgment_id="judgment:v1",
    )
    service.append(replacement, AGENT)
    with pg_engine.connect() as connection:
        current = connection.scalars(select(CreatorJudgment.proposal_id).where(
            CreatorJudgment.workspace_id == workspace_id,
            CreatorJudgment.status == "tim_confirmed",
            CreatorJudgment.superseded_at.is_(None),
        )).all()
        assert current == ["judgment:v1"]
    turn = _event(
        workspace_id, 10, "event:replacement-turn", "creator.conversation_turn_recorded", 11,
        turn_id="turn:confirm-v2", source_ref="source:conversation", source_message_ref="message:confirm-v2",
        source_role="user", actor="tim", authorship_basis="direct_unquoted_message", raw_text="确认替代判断",
        content_hash=content_hash("确认替代判断"), subject_refs=["route:tianlongshan"],
        interaction={
            "kind": "judgment_response", "proposal_id": "judgment:v2",
            "statement_hash": content_hash(replacement_statement), "response": "tim_confirmed",
        },
    )
    service.append(turn, REVIEWER)
    service.append(_event(
        workspace_id, 11, "event:replacement-decision", "creator.judgment_responded", 12,
        decision_id="decision:v2", proposal_id="judgment:v2", response_turn_ref="turn:confirm-v2",
        response="tim_confirmed", expected_statement_hash=content_hash(replacement_statement),
    ), REVIEWER)
    service.append(_event(
        workspace_id, 12, "event:contradiction-resolution", "creator.judgment_contradiction_resolved", 13,
        resolution_id="resolution:v1", contradiction_id="contradiction:v1", resolution="superseded",
        resolution_ref="judgment:v2", reason="Tim 已确认替代判断。",
    ), AGENT)
    with pg_engine.connect() as connection:
        rows = connection.execute(select(
            CreatorJudgment.proposal_id, CreatorJudgment.status, CreatorJudgment.superseded_at
        ).where(CreatorJudgment.workspace_id == workspace_id).order_by(CreatorJudgment.proposal_id)).all()
        assert rows[0].proposal_id == "judgment:v1" and rows[0].superseded_at is not None
        assert rows[1].proposal_id == "judgment:v2" and rows[1].status == "tim_confirmed" and rows[1].superseded_at is None
        contradiction = connection.execute(select(
            CreatorJudgmentContradiction.resolution, CreatorJudgmentContradiction.resolved_at
        ).where(CreatorJudgmentContradiction.workspace_id == workspace_id)).one()
        assert contradiction.resolution == "superseded" and contradiction.resolved_at is not None
    assert service.read_projection_records(workspace_id, 13, FULL)["records"] == service.read_records(workspace_id, FULL)


def test_exact_tim_rejection_never_creates_current_judgment(service, pg_engine):
    workspace_id = _workspace("creator-rejected")
    _start(service, workspace_id)
    _source_sequence(service, workspace_id)
    service.append(_event(
        workspace_id, 3, "event:evidence", "creator.evidence_recorded", 3,
        evidence_id="evidence:guide", source_ref="source:conversation", subject_ref="route:tianlongshan",
        raw_observation="待审核结构证据", observed_at="2026-08-01T00:00:00.000Z",
    ), AGENT)
    statement = "这条判断应被 Tim 拒绝。"
    service.append(_proposal_event(
        workspace_id, 4, "event:proposal", "judgment:reject", statement, "evidence:guide", 4,
    ), AGENT)
    service.append(_event(
        workspace_id, 5, "event:reject-turn", "creator.conversation_turn_recorded", 5,
        turn_id="turn:reject", source_ref="source:conversation", source_message_ref="message:reject",
        source_role="user", actor="tim", authorship_basis="direct_unquoted_message", raw_text="拒绝这条判断",
        content_hash=content_hash("拒绝这条判断"), subject_refs=["route:tianlongshan"],
        interaction={
            "kind": "judgment_response", "proposal_id": "judgment:reject",
            "statement_hash": content_hash(statement), "response": "rejected",
        },
    ), REVIEWER)
    service.append(_event(
        workspace_id, 6, "event:reject-decision", "creator.judgment_responded", 6,
        decision_id="decision:reject", proposal_id="judgment:reject", response_turn_ref="turn:reject",
        response="rejected", expected_statement_hash=content_hash(statement),
    ), REVIEWER)
    digest = service.read_projection_digest(workspace_id, FULL)
    assert digest["current_judgment_refs"] == []
    assert digest["pending_judgment_refs"] == []
    with pg_engine.connect() as connection:
        assert connection.scalar(select(CreatorJudgment.status).where(
            CreatorJudgment.workspace_id == workspace_id
        )) == "rejected"


def _compile_pg_records(records, tmp_path: Path, request: dict) -> dict:
    records_path = tmp_path / f"records-{uuid.uuid4().hex}.json"
    records_path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    root = Path(__file__).resolve().parents[1]
    output = subprocess.run(
        [
            "node", "--no-warnings", "--experimental-strip-types",
            str(root / "tests-ts/helpers/creator-context-records-child.ts"),
            str(records_path), json.dumps(request, ensure_ascii=False),
        ],
        cwd=root, capture_output=True, text=True, check=True,
    ).stdout
    return json.loads(output)


def test_pg_event_read_fails_closed_for_rights_revocation_and_review_due(service, tmp_path):
    review_workspace = _workspace("creator-review-due")
    _statement, review_decision = _append_exact_decision_loop(service, review_workspace)
    service.append(review_decision, REVIEWER)
    review_bundle = _compile_pg_records(service.read_records(review_workspace, FULL), tmp_path, {
        "task": "复核过期判断", "subject_refs": ["route:tianlongshan"],
        "as_of": "2028-01-01T00:00:00.000Z", "max_pending_turns": 20, "max_evidence": 30,
    })
    review_projection = service.read_projection_records(review_workspace, 7, FULL)["records"]
    assert review_projection == service.read_records(review_workspace, FULL)
    assert _compile_pg_records(review_projection, tmp_path, {
        "task": "复核过期判断", "subject_refs": ["route:tianlongshan"],
        "as_of": "2028-01-01T00:00:00.000Z", "max_pending_turns": 20, "max_evidence": 30,
    }) == review_bundle
    assert review_bundle["context"]["current_judgments"] == []
    assert any(item["reason"] == "review_due" for item in review_bundle["manifest"]["omissions"])

    revoked_workspace = _workspace("creator-rights-revoked")
    _statement, revoked_decision = _append_exact_decision_loop(service, revoked_workspace)
    service.append(revoked_decision, REVIEWER)
    service.append(_event(
        revoked_workspace, 7, "event:rights-revoked", "creator.rights_checked", 8,
        rights_check_id="rights:revoked", source_ref="source:conversation", decision="forbidden",
        policy_ref="policy:revoked", reason="来源权限已撤销。",
    ), FULL)
    revoked_bundle = _compile_pg_records(service.read_records(revoked_workspace, FULL), tmp_path, {
        "task": "撤权后不得加载原文", "subject_refs": ["route:tianlongshan"],
        "as_of": "2026-08-06T01:09:00.000Z", "max_pending_turns": 20, "max_evidence": 30,
    })
    revoked_projection = service.read_projection_records(revoked_workspace, 8, FULL)["records"]
    assert revoked_projection == service.read_records(revoked_workspace, FULL)
    assert _compile_pg_records(revoked_projection, tmp_path, {
        "task": "撤权后不得加载原文", "subject_refs": ["route:tianlongshan"],
        "as_of": "2026-08-06T01:09:00.000Z", "max_pending_turns": 20, "max_evidence": 30,
    }) == revoked_bundle
    assert revoked_bundle["context"]["current_judgments"] == []
    assert revoked_bundle["context"]["relevant_evidence"] == []
    assert any(item["reason"] == "rights_not_allowed" for item in revoked_bundle["manifest"]["omissions"])
    digest = service.read_projection_digest(revoked_workspace, FULL)
    assert digest["source_rights"] == [{
        "source_ref": "source:conversation", "source_event_revision": 2,
        "rights_decision": "forbidden", "rights_event_revision": 8,
    }]


def test_internal_router_binds_bearer_identity_and_never_accepts_body_principal():
    class FakeService:
        def read_records(self, workspace_id, principal):
            principal.require("context.read_private")
            return []

        def read_projection_records(self, workspace_id, expected_revision, principal):
            principal.require("context.read_private")
            return {
                "revision": expected_revision,
                "records": [],
                "digest": {
                    "revision": expected_revision,
                    "source_rights": [],
                    "current_judgment_refs": [],
                    "pending_judgment_refs": [],
                    "decision_refs": [],
                    "unresolved_contradiction_refs": [],
                },
            }

        def append(self, event, principal):
            principal.require("workspace.create")
            from app.creator_persistence.service import CreatorAppendReceipt
            return CreatorAppendReceipt(event["event_id"], 1, content_hash(event))

    def authenticate(token: str):
        if token != "valid-internal-token":
            raise CreatorAuthorizationError("invalid token")
        return FULL

    app = FastAPI()
    app.include_router(create_creator_internal_router(FakeService(), authenticate))
    client = TestClient(app)
    assert client.get("/internal/creator/workspaces/ws").status_code == 401
    assert client.get(
        "/internal/creator/workspaces/ws", headers={"Authorization": "Bearer wrong"}
    ).status_code == 403
    event = _event("ws", 0, "event:start", "creator.workspace_started", 0, mission="internal")
    response = client.post(
        "/internal/creator/workspaces/ws/events",
        headers={"Authorization": "Bearer valid-internal-token"},
        json={"event": event, "principal": {"principal_id": "forged"}},
    )
    assert response.status_code == 422
    projection = client.get(
        "/internal/creator/workspaces/ws/projection-records?expected_revision=0",
        headers={"Authorization": "Bearer valid-internal-token"},
    )
    assert projection.status_code == 200
    assert projection.json() == {
        "revision": 0,
        "records": [],
        "digest": {
            "revision": 0,
            "source_rights": [],
            "current_judgment_refs": [],
            "pending_judgment_refs": [],
            "decision_refs": [],
            "unresolved_contradiction_refs": [],
        },
    }


def test_postgres_records_match_jsonl_context_hash_for_tianlongshan(service, tmp_path):
    workspace_id = _workspace("creator-tianlongshan")
    statement, decision = _append_exact_decision_loop(service, workspace_id)
    service.append(decision, REVIEWER)
    records = service.read_records(workspace_id, FULL)
    records_path = tmp_path / "records.json"
    records_path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    jsonl_root = tmp_path / "jsonl"
    jsonl_root.mkdir()
    (jsonl_root / f"{workspace_id}.jsonl").write_text(
        "\n".join(canonical_json(record) for record in records) + "\n", encoding="utf-8"
    )
    request = {
        "task": "生成天龙山路线认知上下文", "subject_refs": ["route:tianlongshan"],
        "as_of": "2026-08-06T01:59:00.000Z", "max_pending_turns": 20, "max_evidence": 30,
    }
    root = Path(__file__).resolve().parents[1]
    records_helper = root / "tests-ts/helpers/creator-context-records-child.ts"
    jsonl_helper = root / "tests-ts/helpers/creator-replay-child.ts"
    projection_helper = root / "tests-ts/helpers/creator-projection-digest-child.ts"
    node_prefix = ["node", "--no-warnings", "--experimental-strip-types"]
    from_records = subprocess.run(
        [*node_prefix, str(records_helper), str(records_path), json.dumps(request, ensure_ascii=False)],
        cwd=root, capture_output=True, text=True, check=True,
    ).stdout
    from_jsonl = subprocess.run(
        [*node_prefix, str(jsonl_helper), str(jsonl_root), workspace_id, json.dumps(request, ensure_ascii=False)],
        cwd=root, capture_output=True, text=True, check=True,
    ).stdout
    assert from_records == from_jsonl
    bundle = json.loads(from_records)
    assert bundle["manifest"]["context_hash"].startswith("sha256:")
    assert bundle["context"]["current_judgments"][0]["statement"] == statement
    replay_digest = subprocess.run(
        [*node_prefix, str(projection_helper), str(records_path)],
        cwd=root, capture_output=True, text=True, check=True,
    ).stdout
    assert json.loads(replay_digest) == service.read_projection_digest(workspace_id, FULL)


def test_relational_projection_reconstructs_all_nine_v0_events_without_payload_json(service, tmp_path):
    workspace_id = _workspace("creator-projection-records")
    _statement, decision = _append_exact_decision_loop(service, workspace_id)
    service.append(decision, REVIEWER)
    service.append(_event(
        workspace_id, 7, "event:contradiction", "creator.judgment_contradiction_recorded", 8,
        contradiction_id="contradiction:v1", judgment_id="judgment:v1",
        contradicting_ref="evidence:guide", reason="需要复核骑友反馈与既有判断。",
    ), AGENT)
    service.append(_event(
        workspace_id, 8, "event:resolution", "creator.judgment_contradiction_resolved", 9,
        resolution_id="resolution:v1", contradiction_id="contradiction:v1",
        resolution="dismissed", resolution_ref="evidence:guide", reason="证据不足以推翻当前判断。",
    ), AGENT)

    event_truth = service.read_records(workspace_id, FULL)
    projection = service.read_projection_records(workspace_id, 9, FULL)
    assert projection["revision"] == 9
    assert projection["records"] == event_truth
    assert projection["digest"] == service.read_projection_digest(workspace_id, FULL)
    assert {record["event"]["type"] for record in projection["records"]} == set(CAPABILITY_BY_EVENT_TYPE)

    def authenticate_projection_test(token: str):
        if token != "projection-test-token":
            raise CreatorAuthorizationError("invalid token")
        return FULL

    app = FastAPI()
    app.include_router(create_creator_internal_router(service, authenticate_projection_test))
    response = TestClient(app).get(
        f"/internal/creator/workspaces/{workspace_id}/projection-records?expected_revision=9",
        headers={"Authorization": "Bearer projection-test-token"},
    )
    assert response.status_code == 200
    assert response.json() == projection
    stale_response = TestClient(app).get(
        f"/internal/creator/workspaces/{workspace_id}/projection-records?expected_revision=8",
        headers={"Authorization": "Bearer projection-test-token"},
    )
    assert stale_response.status_code == 409
    assert stale_response.json()["detail"]["code"] == "projection_revision_mismatch"

    request = {
        "task": "生成天龙山路线认知上下文",
        "subject_refs": ["route:tianlongshan"],
        "as_of": "2026-08-06T01:59:00.000Z",
        "max_pending_turns": 20,
        "max_evidence": 30,
    }
    assert _compile_pg_records(event_truth, tmp_path, request) == _compile_pg_records(
        projection["records"], tmp_path, request
    )
    with pytest.raises(CreatorProjectionRevisionMismatchError, match="expected 8, observed 9"):
        service.read_projection_records(workspace_id, 8, FULL)


def test_projection_tamper_diverges_while_append_only_event_truth_stays_exact(service, pg_engine):
    workspace_id = _workspace("creator-projection-tamper")
    _statement, decision = _append_exact_decision_loop(service, workspace_id)
    service.append(decision, REVIEWER)
    event_truth = service.read_records(workspace_id, FULL)
    assert service.read_projection_records(workspace_id, 7, FULL)["records"] == event_truth

    with pg_engine.begin() as connection:
        connection.execute(update(CreatorEvidenceItem).where(
            CreatorEvidenceItem.workspace_id == workspace_id,
            CreatorEvidenceItem.evidence_id == "evidence:guide",
        ).values(raw_observation="人工篡改的关系投影"))

    assert service.read_records(workspace_id, FULL) == event_truth
    projection = service.read_projection_records(workspace_id, 7, FULL)
    assert projection["records"] != event_truth
    assert projection["records"][3]["event"]["raw_observation"] == "人工篡改的关系投影"

    cache_workspace = _workspace("creator-projection-cache-tamper")
    _statement, cache_decision = _append_exact_decision_loop(service, cache_workspace)
    service.append(cache_decision, REVIEWER)
    cache_truth = service.read_records(cache_workspace, FULL)
    with pg_engine.begin() as connection:
        connection.execute(update(CreatorJudgment).where(
            CreatorJudgment.workspace_id == cache_workspace,
            CreatorJudgment.proposal_id == "judgment:v1",
        ).values(status="rejected"))
    cache_projection = service.read_projection_records(cache_workspace, 7, FULL)
    assert cache_projection["records"] == cache_truth
    assert cache_projection["digest"]["current_judgment_refs"] == []
