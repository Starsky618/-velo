import { mkdir, open } from "node:fs/promises";
import { dirname } from "node:path";

import { canonicalJson, contentHash } from "../../shared/canonical.ts";
import type { RuntimePrincipal } from "../../shared/capability-gate.ts";
import { withJsonlLock } from "../../shared/jsonl-lock.ts";
import { compileCreatorContext, type CreatorContextBundle, type CreatorContextRequest } from "./compiler.ts";
import { replayCreatorWorkspace } from "../state/engine.ts";
import type {
  CreatorProjectionDigest,
  CreatorProjectionRecordReader,
  CreatorWorkspaceRead,
} from "../state/store-port.ts";
import type { CreatorView } from "../state/types.ts";

export type CreatorContextDriftReason =
  | "projection_read_failed"
  | "projection_record_mismatch"
  | "projection_digest_mismatch"
  | "projection_replay_failed"
  | "context_mismatch";

export interface CreatorContextSafetyAlarm {
  schema_version: 1;
  alarm_id: string;
  detected_at: string;
  workspace_id: string;
  expected_revision: number;
  source_event_id_hash: string;
  request_hash: string;
  event_records_hash: string;
  projection_records_hash?: string;
  event_projection_digest_hash: string;
  database_projection_digest_hash?: string;
  event_context_hash: string;
  projection_context_hash?: string;
  reasons: CreatorContextDriftReason[];
}

export interface CreatorContextSafetyAlarmSink {
  append(alarm: CreatorContextSafetyAlarm): Promise<void>;
}

export interface CreatorContextCompilerPort {
  compile(
    read: CreatorWorkspaceRead,
    request: CreatorContextRequest,
    principal: RuntimePrincipal,
  ): Promise<CreatorContextBundle>;
}

export class EventTruthCreatorContextCompiler implements CreatorContextCompilerPort {
  async compile(
    read: CreatorWorkspaceRead,
    request: CreatorContextRequest,
    _principal: RuntimePrincipal,
  ): Promise<CreatorContextBundle> {
    if (!read.view) throw new Error("Creator Context compilation requires an existing workspace");
    return compileCreatorContext(read.view, request);
  }
}

export class CreatorContextDriftStopError extends Error {
  readonly alarm: CreatorContextSafetyAlarm;

  constructor(alarm: CreatorContextSafetyAlarm, cause?: unknown) {
    super("Creator Context projection drift stopped the run before model invocation", { cause });
    this.name = "CreatorContextDriftStopError";
    this.alarm = alarm;
  }
}

function alarmFor(
  read: CreatorWorkspaceRead,
  bundle: CreatorContextBundle,
  reasons: CreatorContextDriftReason[],
  detectedAt: string,
  hashes: {
    projection_records_hash?: string;
    database_projection_digest_hash?: string;
    projection_context_hash?: string;
  },
): CreatorContextSafetyAlarm {
  if (!read.view) throw new Error("Creator drift alarm requires an existing workspace");
  const core = {
    schema_version: 1 as const,
    workspace_id: read.view.workspace_id,
    expected_revision: read.view.revision,
    source_event_id_hash: contentHash(read.view.last_event_id),
    request_hash: bundle.manifest.request_hash,
    event_records_hash: contentHash(read.records),
    ...(hashes.projection_records_hash
      ? { projection_records_hash: hashes.projection_records_hash }
      : {}),
    event_projection_digest_hash: contentHash(creatorProjectionDigestFromView(read.view)),
    ...(hashes.database_projection_digest_hash
      ? { database_projection_digest_hash: hashes.database_projection_digest_hash }
      : {}),
    event_context_hash: bundle.manifest.context_hash,
    ...(hashes.projection_context_hash
      ? { projection_context_hash: hashes.projection_context_hash }
      : {}),
    reasons: [...new Set(reasons)].sort(),
  };
  return { ...core, alarm_id: contentHash(core), detected_at: detectedAt };
}

export function creatorProjectionDigestFromView(view: CreatorView): CreatorProjectionDigest {
  const latestRights = Object.values(view.rights_checks).reduce((bySource, check) => {
    const previous = bySource.get(check.source_ref);
    if (!previous || check.base_revision > previous.base_revision) bySource.set(check.source_ref, check);
    return bySource;
  }, new Map<string, (typeof view.rights_checks)[string]>());
  return {
    revision: view.revision,
    source_rights: Object.values(view.sources)
      .sort((left, right) => left.source_ref < right.source_ref ? -1 : left.source_ref > right.source_ref ? 1 : 0)
      .map((source) => {
        const rights = latestRights.get(source.source_ref);
        return {
          source_ref: source.source_ref,
          source_event_revision: source.base_revision + 1,
          rights_decision: rights?.decision ?? null,
          rights_event_revision: rights ? rights.base_revision + 1 : null,
        };
      }),
    current_judgment_refs: Object.values(view.judgments)
      .filter((judgment) => judgment.status === "tim_confirmed" && !judgment.superseded)
      .map((judgment) => judgment.id).sort(),
    pending_judgment_refs: Object.values(view.judgments)
      .filter((judgment) => judgment.status === "proposed" && !judgment.superseded)
      .map((judgment) => judgment.id).sort(),
    decision_refs: Object.keys(view.judgment_decisions).sort(),
    unresolved_contradiction_refs: Object.values(view.judgment_contradictions)
      .filter((contradiction) => !contradiction.resolved)
      .map((contradiction) => contradiction.id).sort(),
  };
}

export class ProjectionVerifiedCreatorContextCompiler implements CreatorContextCompilerPort {
  readonly #projectionReader: CreatorProjectionRecordReader;
  readonly #alarmSink: CreatorContextSafetyAlarmSink;
  readonly #clock: () => string;

  constructor(
    projectionReader: CreatorProjectionRecordReader,
    alarmSink: CreatorContextSafetyAlarmSink,
    clock: () => string = () => new Date().toISOString(),
  ) {
    this.#projectionReader = projectionReader;
    this.#alarmSink = alarmSink;
    this.#clock = clock;
  }

  async #stop(
    read: CreatorWorkspaceRead,
    bundle: CreatorContextBundle,
    reasons: CreatorContextDriftReason[],
    hashes: {
      projection_records_hash?: string;
      database_projection_digest_hash?: string;
      projection_context_hash?: string;
    } = {},
    cause?: unknown,
  ): Promise<never> {
    const alarm = alarmFor(
      read,
      bundle,
      reasons,
      this.#clock(),
      hashes,
    );
    try {
      await this.#alarmSink.append(alarm);
    } catch (alarmError) {
      throw new CreatorContextDriftStopError(alarm, alarmError);
    }
    throw new CreatorContextDriftStopError(alarm, cause);
  }

  async compile(
    read: CreatorWorkspaceRead,
    request: CreatorContextRequest,
    principal: RuntimePrincipal,
  ): Promise<CreatorContextBundle> {
    if (!read.view) throw new Error("Creator Context compilation requires an existing workspace");
    const eventBundle = compileCreatorContext(read.view, request);
    let projectionRead;
    try {
      projectionRead = await this.#projectionReader.readProjectionRecordsAs(
        read.view.workspace_id,
        read.view.revision,
        principal,
      );
    } catch (error) {
      return this.#stop(read, eventBundle, ["projection_read_failed"], {}, error);
    }

    const projectionRecordsHash = contentHash(projectionRead.records);
    const databaseProjectionDigestHash = contentHash(projectionRead.digest);
    const reasons: CreatorContextDriftReason[] = [];
    if (canonicalJson(projectionRead.records) !== canonicalJson(read.records)) {
      reasons.push("projection_record_mismatch");
    }
    if (canonicalJson(projectionRead.digest) !== canonicalJson(creatorProjectionDigestFromView(read.view))) {
      reasons.push("projection_digest_mismatch");
    }

    let projectionBundle: CreatorContextBundle;
    try {
      const projectionView = replayCreatorWorkspace(projectionRead.records);
      projectionBundle = compileCreatorContext(projectionView, request);
    } catch (error) {
      return this.#stop(
        read,
        eventBundle,
        [...reasons, "projection_replay_failed"],
        {
          projection_records_hash: projectionRecordsHash,
          database_projection_digest_hash: databaseProjectionDigestHash,
        },
        error,
      );
    }
    if (canonicalJson(projectionBundle) !== canonicalJson(eventBundle)) {
      reasons.push("context_mismatch");
    }
    if (reasons.length > 0) {
      return this.#stop(
        read,
        eventBundle,
        reasons,
        {
          projection_records_hash: projectionRecordsHash,
          database_projection_digest_hash: databaseProjectionDigestHash,
          projection_context_hash: projectionBundle.manifest.context_hash,
        },
      );
    }
    return eventBundle;
  }
}

export class JsonlCreatorContextSafetyAlarmSink implements CreatorContextSafetyAlarmSink {
  readonly path: string;

  constructor(path: string) {
    if (typeof path !== "string" || path.trim().length === 0) {
      throw new TypeError("Creator Context alarm path must be non-empty");
    }
    this.path = path;
  }

  async append(alarm: CreatorContextSafetyAlarm): Promise<void> {
    await mkdir(dirname(this.path), { recursive: true });
    await withJsonlLock(this.path, "Creator Context safety alarm stream", async () => {
      const file = await open(this.path, "a");
      try {
        await file.writeFile(`${canonicalJson(alarm)}\n`, "utf8");
        await file.sync();
      } finally {
        await file.close();
      }
    });
  }
}
