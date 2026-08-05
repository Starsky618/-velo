import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { createTestCreatorPrincipal, creatorCapabilityForEventType } from "../agent_runtime/creator/capabilities.ts";
import {
  CreatorContextDriftStopError,
  JsonlCreatorContextSafetyAlarmSink,
  ProjectionVerifiedCreatorContextCompiler,
  creatorProjectionDigestFromView,
  type CreatorContextSafetyAlarm,
  type CreatorContextSafetyAlarmSink,
} from "../agent_runtime/creator/context/projection-guard.ts";
import { CreatorAgentV0 } from "../agent_runtime/creator/runtime/agent-v0.ts";
import type { CreatorDecisionModel } from "../agent_runtime/creator/runtime/model.ts";
import { replayCreatorWorkspace } from "../agent_runtime/creator/state/engine.ts";
import type {
  CreatorProjectionRead,
  CreatorProjectionRecordReader,
  CreatorWorkspaceRead,
  CreatorWorkspaceStore,
} from "../agent_runtime/creator/state/store-port.ts";
import type { CreatorEvent, CreatorStoredEvent, CreatorView } from "../agent_runtime/creator/state/types.ts";
import { canonicalJson, contentHash } from "../agent_runtime/shared/canonical.ts";
import type { RuntimePrincipal } from "../agent_runtime/shared/capability-gate.ts";

const principal = createTestCreatorPrincipal();
const privateObservation = "天龙山私密骑友反馈：雨后弯心有碎石。";

const events: CreatorEvent[] = [
  {
    schema_version: 1,
    event_id: "event:start",
    workspace_id: "creator-projection-shadow",
    base_revision: 0,
    occurred_at: "2026-08-06T01:00:00.000Z",
    type: "creator.workspace_started",
    mission: "保留 Tim 判断并阻止漂移 Context",
  },
  {
    schema_version: 1,
    event_id: "event:source",
    workspace_id: "creator-projection-shadow",
    base_revision: 1,
    occurred_at: "2026-08-06T01:01:00.000Z",
    type: "creator.source_ingested",
    source_ref: "source:rider-report",
    source_kind: "rider_report",
    content_hash: contentHash(privateObservation),
    immutable_ref: "rider-report:revision:1",
    provenance_ref: "rider:test:reviewed",
  },
  {
    schema_version: 1,
    event_id: "event:rights",
    workspace_id: "creator-projection-shadow",
    base_revision: 2,
    occurred_at: "2026-08-06T01:02:00.000Z",
    type: "creator.rights_checked",
    rights_check_id: "rights:rider-report:v1",
    source_ref: "source:rider-report",
    decision: "allowed",
    policy_ref: "policy:creator-private-v1",
    reason: "骑友授权仅供 Creator 内部判断。",
  },
  {
    schema_version: 1,
    event_id: "event:evidence",
    workspace_id: "creator-projection-shadow",
    base_revision: 3,
    occurred_at: "2026-08-06T01:03:00.000Z",
    type: "creator.evidence_recorded",
    evidence_id: "evidence:tianlongshan:gravel",
    source_ref: "source:rider-report",
    subject_ref: "route:tianlongshan",
    raw_observation: privateObservation,
    observed_at: "2026-08-06T01:03:00.000Z",
  },
];

function stored(event: CreatorEvent): CreatorStoredEvent {
  return {
    event: structuredClone(event),
    committed_by: {
      principal_id: principal.principal_id,
      product: "creator",
      environment: principal.environment,
      capability: creatorCapabilityForEventType(event.type),
    },
  };
}

function workspaceRead(): CreatorWorkspaceRead {
  const records = events.map(stored);
  return { records, events: records.map((record) => record.event), view: replayCreatorWorkspace(records) };
}

function projectionRead(records: CreatorStoredEvent[], read: CreatorWorkspaceRead): CreatorProjectionRead {
  return {
    revision: records.length,
    records,
    digest: creatorProjectionDigestFromView(read.view!),
  };
}

class StaticStore implements CreatorWorkspaceStore, CreatorProjectionRecordReader {
  readonly read: CreatorWorkspaceRead;
  readonly projection: CreatorProjectionRead | Error;

  constructor(read: CreatorWorkspaceRead, projection: CreatorProjectionRead | Error) {
    this.read = read;
    this.projection = projection;
  }

  async readAs(_workspaceId: string, _principal: RuntimePrincipal): Promise<CreatorWorkspaceRead> {
    return structuredClone(this.read);
  }

  async appendAs(_event: CreatorEvent, _principal: RuntimePrincipal): Promise<CreatorView> {
    throw new Error("no_action test must not append");
  }

  async readProjectionRecordsAs(
    _workspaceId: string,
    _expectedRevision: number,
    _principal: RuntimePrincipal,
  ): Promise<CreatorProjectionRead> {
    if (this.projection instanceof Error) throw this.projection;
    return structuredClone(this.projection);
  }
}

class MemoryAlarmSink implements CreatorContextSafetyAlarmSink {
  readonly alarms: CreatorContextSafetyAlarm[] = [];

  async append(alarm: CreatorContextSafetyAlarm): Promise<void> {
    this.alarms.push(structuredClone(alarm));
  }
}

class CountingNoActionModel implements CreatorDecisionModel {
  readonly model_ref = "shadow:projection-guard-test";
  calls = 0;

  async decide() {
    this.calls += 1;
    return { type: "no_action" as const, reason: "Projection parity verified." };
  }
}

function runRequest() {
  return {
    workspace_id: "creator-projection-shadow",
    event_id: "event:agent-run",
    occurred_at: "2026-08-06T01:04:00.000Z",
    task: "判断天龙山路线认知是否足够",
    subject_refs: ["route:tianlongshan"],
    max_pending_turns: 20,
    max_evidence: 30,
  };
}

test("Projection-verified Context invokes the model only after exact record and bundle parity", async () => {
  const read = workspaceRead();
  const sink = new MemoryAlarmSink();
  const model = new CountingNoActionModel();
  const compiler = new ProjectionVerifiedCreatorContextCompiler(
    sink,
    () => "2026-08-06T01:04:00.000Z",
  );
  const store = new StaticStore(read, projectionRead(structuredClone(read.records), read));
  const result = await new CreatorAgentV0(store, principal, model, compiler).run(runRequest());
  assert.equal(result.commit_status, "no_action");
  assert.equal(model.calls, 1);
  assert.deepEqual(sink.alarms, []);
});

test("Projection drift writes a privacy-safe alarm and stops before model invocation", async () => {
  const read = workspaceRead();
  const tampered = structuredClone(read.records);
  const evidence = tampered[3]!.event;
  assert.equal(evidence.type, "creator.evidence_recorded");
  if (evidence.type === "creator.evidence_recorded") evidence.raw_observation = "被篡改的投影内容";
  const sink = new MemoryAlarmSink();
  const model = new CountingNoActionModel();
  const compiler = new ProjectionVerifiedCreatorContextCompiler(
    sink,
    () => "2026-08-06T01:04:00.000Z",
  );
  const store = new StaticStore(read, projectionRead(tampered, read));
  await assert.rejects(
    () => new CreatorAgentV0(store, principal, model, compiler).run(runRequest()),
    (error) => {
      assert.ok(error instanceof CreatorContextDriftStopError);
      assert.deepEqual(error.alarm.reasons, ["context_mismatch", "projection_record_mismatch"]);
      return true;
    },
  );
  assert.equal(model.calls, 0);
  assert.equal(sink.alarms.length, 1);
  const encoded = canonicalJson(sink.alarms[0]);
  assert.equal(encoded.includes(privateObservation), false);
  assert.equal(encoded.includes("被篡改的投影内容"), false);
  assert.match(sink.alarms[0]!.alarm_id, /^sha256:[0-9a-f]{64}$/);
});

test("Current projection cache drift stops even when reconstructed event records still match", async () => {
  const read = workspaceRead();
  const projection = projectionRead(structuredClone(read.records), read);
  projection.digest.pending_judgment_refs = ["judgment:forged-cache"];
  const sink = new MemoryAlarmSink();
  const model = new CountingNoActionModel();
  const compiler = new ProjectionVerifiedCreatorContextCompiler(
    sink,
    () => "2026-08-06T01:04:00.000Z",
  );
  const store = new StaticStore(read, projection);
  await assert.rejects(
    () => new CreatorAgentV0(store, principal, model, compiler).run(runRequest()),
    (error) => error instanceof CreatorContextDriftStopError
      && canonicalJson(error.alarm.reasons) === canonicalJson(["projection_digest_mismatch"]),
  );
  assert.equal(model.calls, 0);
  assert.notEqual(
    sink.alarms[0]!.event_projection_digest_hash,
    sink.alarms[0]!.database_projection_digest_hash,
  );
});

test("Projection read and replay failures both fail closed before the model", async (t) => {
  const read = workspaceRead();
  await t.test("read failure", async () => {
    const sink = new MemoryAlarmSink();
    const model = new CountingNoActionModel();
    const compiler = new ProjectionVerifiedCreatorContextCompiler(
      sink,
      () => "2026-08-06T01:04:00.000Z",
    );
    const store = new StaticStore(read, new Error("revision changed"));
    await assert.rejects(
      () => new CreatorAgentV0(store, principal, model, compiler).run(runRequest()),
      (error) => error instanceof CreatorContextDriftStopError
        && error.alarm.reasons[0] === "projection_read_failed",
    );
    assert.equal(model.calls, 0);
  });

  await t.test("replay failure after a rights projection is tampered", async () => {
    const tampered = structuredClone(read.records);
    const rights = tampered[2]!.event;
    assert.equal(rights.type, "creator.rights_checked");
    if (rights.type === "creator.rights_checked") rights.decision = "forbidden";
    const sink = new MemoryAlarmSink();
    const model = new CountingNoActionModel();
    const compiler = new ProjectionVerifiedCreatorContextCompiler(
      sink,
      () => "2026-08-06T01:04:00.000Z",
    );
    const store = new StaticStore(read, projectionRead(tampered, read));
    await assert.rejects(
      () => new CreatorAgentV0(store, principal, model, compiler).run(runRequest()),
      (error) => error instanceof CreatorContextDriftStopError
        && canonicalJson(error.alarm.reasons)
          === canonicalJson(["projection_record_mismatch", "projection_replay_failed"]),
    );
    assert.equal(model.calls, 0);
  });
});

test("Projection revision mismatch is checked again by the guard before model invocation", async () => {
  const read = workspaceRead();
  const projection = projectionRead(structuredClone(read.records), read);
  projection.revision = 999;
  const sink = new MemoryAlarmSink();
  const model = new CountingNoActionModel();
  const compiler = new ProjectionVerifiedCreatorContextCompiler(
    sink,
    () => "2026-08-06T01:04:00.000Z",
  );
  const store = new StaticStore(read, projection);
  await assert.rejects(
    () => new CreatorAgentV0(store, principal, model, compiler).run(runRequest()),
    (error) => error instanceof CreatorContextDriftStopError
      && canonicalJson(error.alarm.reasons) === canonicalJson(["projection_revision_mismatch"]),
  );
  assert.equal(model.calls, 0);
  assert.equal(sink.alarms.length, 1);
});

test("Projection-verified compiler refuses a store without the projection read capability", async () => {
  const read = workspaceRead();
  const sink = new MemoryAlarmSink();
  const model = new CountingNoActionModel();
  const compiler = new ProjectionVerifiedCreatorContextCompiler(
    sink,
    () => "2026-08-06T01:04:00.000Z",
  );
  const eventOnlyStore: CreatorWorkspaceStore = {
    readAs: async () => structuredClone(read),
    appendAs: async () => { throw new Error("no_action test must not append"); },
  };
  await assert.rejects(
    () => new CreatorAgentV0(eventOnlyStore, principal, model, compiler).run(runRequest()),
    (error) => error instanceof CreatorContextDriftStopError
      && canonicalJson(error.alarm.reasons) === canonicalJson(["projection_read_failed"]),
  );
  assert.equal(model.calls, 0);
});

test("Alarm persistence failure also keeps Context closed", async () => {
  const read = workspaceRead();
  const tampered = structuredClone(read.records);
  const evidence = tampered[3]!.event;
  if (evidence.type === "creator.evidence_recorded") evidence.raw_observation = "tampered";
  const model = new CountingNoActionModel();
  const compiler = new ProjectionVerifiedCreatorContextCompiler(
    { append: async () => { throw new Error("disk full"); } },
    () => "2026-08-06T01:04:00.000Z",
  );
  const store = new StaticStore(read, projectionRead(tampered, read));
  await assert.rejects(
    () => new CreatorAgentV0(store, principal, model, compiler).run(runRequest()),
    CreatorContextDriftStopError,
  );
  assert.equal(model.calls, 0);
});

test("JSONL alarm sink appends canonical records without storing private Context", async () => {
  const directory = await mkdtemp(join(tmpdir(), "creator-context-alarm-"));
  try {
    const path = join(directory, "alarms.jsonl");
    const sink = new JsonlCreatorContextSafetyAlarmSink(path);
    const read = workspaceRead();
    const bundleHash = contentHash({ safe: true });
    const alarm: CreatorContextSafetyAlarm = {
      schema_version: 1,
      alarm_id: bundleHash,
      detected_at: "2026-08-06T01:04:00.000Z",
      workspace_id: read.view!.workspace_id,
      expected_revision: read.view!.revision,
      source_event_id_hash: contentHash(read.view!.last_event_id),
      request_hash: bundleHash,
      event_records_hash: contentHash(read.records),
      event_projection_digest_hash: contentHash(creatorProjectionDigestFromView(read.view!)),
      event_context_hash: bundleHash,
      reasons: ["projection_read_failed"],
    };
    await sink.append(alarm);
    await sink.append(alarm);
    const lines = (await readFile(path, "utf8")).trim().split("\n");
    assert.deepEqual(lines, [canonicalJson(alarm), canonicalJson(alarm)]);
    assert.equal(lines.join("\n").includes(privateObservation), false);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});
