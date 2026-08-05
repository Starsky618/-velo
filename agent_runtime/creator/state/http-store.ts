import { creatorCapabilityForEventType, createCreatorCapabilityGate } from "../capabilities.ts";
import { canonicalJson, contentHash } from "../../shared/canonical.ts";
import type { RuntimePrincipal } from "../../shared/capability-gate.ts";
import { replayCreatorWorkspace, validateCreatorEvent, validateCreatorStoredEvent } from "./engine.ts";
import type { CreatorWorkspaceRead, CreatorWorkspaceStore } from "./store-port.ts";
import type { CreatorEvent, CreatorStoredEvent, CreatorView } from "./types.ts";

export interface CreatorInternalApiCredential {
  bearer_token: string;
  principal: RuntimePrincipal;
}

export const CREATOR_PERSISTENCE_V0_EVENT_TYPES = [
  "creator.workspace_started",
  "creator.source_ingested",
  "creator.conversation_turn_recorded",
  "creator.rights_checked",
  "creator.evidence_recorded",
  "creator.judgment_proposed",
  "creator.judgment_responded",
  "creator.judgment_contradiction_recorded",
  "creator.judgment_contradiction_resolved",
] as const;

export type CreatorPersistenceV0Event = Extract<
  CreatorEvent,
  { type: (typeof CREATOR_PERSISTENCE_V0_EVENT_TYPES)[number] }
>;

export function isCreatorPersistenceV0Event(event: CreatorEvent): event is CreatorPersistenceV0Event {
  return (CREATOR_PERSISTENCE_V0_EVENT_TYPES as readonly string[]).includes(event.type);
}

export type CreatorInternalApiCredentialProvider = () => Promise<CreatorInternalApiCredential>;

export interface CreatorHttpStoreOptions {
  base_url: string;
  credentials: CreatorInternalApiCredentialProvider;
  fetch?: typeof globalThis.fetch;
}

export class CreatorHttpStoreProtocolError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "CreatorHttpStoreProtocolError";
  }
}

interface CreatorAppendReceipt {
  event_id: string;
  committed_revision: number;
  payload_sha256: string;
}

function assertPlainRecord(value: unknown, label: string): asserts value is Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new CreatorHttpStoreProtocolError(`${label} must be an object`);
  }
}

function assertExactKeys(record: Record<string, unknown>, keys: readonly string[], label: string): void {
  const actual = Object.keys(record).sort();
  const expected = [...keys].sort();
  if (canonicalJson(actual) !== canonicalJson(expected)) {
    throw new CreatorHttpStoreProtocolError(`${label} has unexpected fields`);
  }
}

function containsUnpairedSurrogate(value: string): boolean {
  for (let index = 0; index < value.length; index += 1) {
    const unit = value.charCodeAt(index);
    if (unit >= 0xd800 && unit <= 0xdbff) {
      const next = value.charCodeAt(index + 1);
      if (!(next >= 0xdc00 && next <= 0xdfff)) return true;
      index += 1;
    } else if (unit >= 0xdc00 && unit <= 0xdfff) {
      return true;
    }
  }
  return false;
}

function validateRuntimePrincipal(value: unknown, label: string): asserts value is RuntimePrincipal {
  assertPlainRecord(value, label);
  assertExactKeys(value, ["principal_id", "product", "environment", "scopes"], label);
  if (typeof value.principal_id !== "string" || value.principal_id.trim().length === 0) {
    throw new CreatorHttpStoreProtocolError(`${label}.principal_id must be a non-empty string`);
  }
  if (containsUnpairedSurrogate(value.principal_id)) {
    throw new CreatorHttpStoreProtocolError(`${label}.principal_id must contain only Unicode scalar values`);
  }
  if (value.product !== "creator" && value.product !== "rider") {
    throw new CreatorHttpStoreProtocolError(`${label}.product is invalid`);
  }
  if (value.environment !== "test" && value.environment !== "shadow" && value.environment !== "production") {
    throw new CreatorHttpStoreProtocolError(`${label}.environment is invalid`);
  }
  if (!Array.isArray(value.scopes) || value.scopes.some((scope) => typeof scope !== "string" || scope.length === 0)) {
    throw new CreatorHttpStoreProtocolError(`${label}.scopes must contain only non-empty strings`);
  }
  if (value.scopes.some((scope) => containsUnpairedSurrogate(scope))) {
    throw new CreatorHttpStoreProtocolError(`${label}.scopes must contain only Unicode scalar values`);
  }
}

function validateCredential(value: unknown): asserts value is CreatorInternalApiCredential {
  assertPlainRecord(value, "Creator internal API credential");
  assertExactKeys(value, ["bearer_token", "principal"], "Creator internal API credential");
  if (typeof value.bearer_token !== "string" || !/^[\x21-\x7e]+$/.test(value.bearer_token)) {
    throw new CreatorHttpStoreProtocolError("Creator internal API bearer token must be non-empty visible ASCII without whitespace");
  }
  validateRuntimePrincipal(value.principal, "Creator internal API credential principal");
  if (value.principal.product !== "creator") {
    throw new CreatorHttpStoreProtocolError("Creator internal API credential principal must be a Creator principal");
  }
}

function requireMatchingPrincipal(caller: RuntimePrincipal, authenticated: RuntimePrincipal): void {
  validateRuntimePrincipal(caller, "Creator store caller principal");
  if (canonicalJson(caller) !== canonicalJson(authenticated)) {
    throw new CreatorHttpStoreProtocolError("Creator store caller principal does not match authenticated principal");
  }
}

function validateReadResponse(value: unknown): CreatorStoredEvent[] {
  assertPlainRecord(value, "Creator workspace read response");
  assertExactKeys(value, ["records"], "Creator workspace read response");
  if (!Array.isArray(value.records)) {
    throw new CreatorHttpStoreProtocolError("Creator workspace read response records must be an array");
  }
  for (const record of value.records) {
    try {
      validateCreatorStoredEvent(record);
    } catch (error) {
      throw new CreatorHttpStoreProtocolError(
        `Creator workspace read response contains an invalid stored event: ${error instanceof Error ? error.message : String(error)}`,
      );
    }
  }
  return value.records;
}

function validateAppendReceipt(value: unknown): CreatorAppendReceipt {
  assertPlainRecord(value, "Creator append receipt");
  assertExactKeys(value, ["event_id", "committed_revision", "payload_sha256"], "Creator append receipt");
  if (typeof value.event_id !== "string" || value.event_id.length === 0) {
    throw new CreatorHttpStoreProtocolError("Creator append receipt event_id must be a non-empty string");
  }
  if (!Number.isSafeInteger(value.committed_revision) || (value.committed_revision as number) < 1) {
    throw new CreatorHttpStoreProtocolError("Creator append receipt committed_revision must be a positive integer");
  }
  if (typeof value.payload_sha256 !== "string" || !/^sha256:[0-9a-f]{64}$/.test(value.payload_sha256)) {
    throw new CreatorHttpStoreProtocolError("Creator append receipt payload_sha256 must be a sha256 content hash");
  }
  return value as unknown as CreatorAppendReceipt;
}

export class HttpCreatorWorkspaceStore implements CreatorWorkspaceStore {
  readonly #baseUrl: string;
  readonly #credentials: CreatorInternalApiCredentialProvider;
  readonly #fetch: typeof globalThis.fetch;

  constructor(options: CreatorHttpStoreOptions) {
    if (typeof options.base_url !== "string" || options.base_url.trim().length === 0) {
      throw new TypeError("Creator internal API base_url must be a non-empty string");
    }
    this.#baseUrl = options.base_url.replace(/\/+$/, "");
    this.#credentials = options.credentials;
    this.#fetch = options.fetch ?? globalThis.fetch;
    if (typeof this.#fetch !== "function") throw new TypeError("Creator HTTP Store requires fetch");
  }

  async #credentialFor(caller: RuntimePrincipal, capability: string): Promise<CreatorInternalApiCredential> {
    const credential: unknown = await this.#credentials();
    validateCredential(credential);
    requireMatchingPrincipal(caller, credential.principal);
    createCreatorCapabilityGate(credential.principal).require(capability);
    return credential;
  }

  async #requestJson(
    method: "GET" | "POST",
    path: string,
    credential: CreatorInternalApiCredential,
    body?: unknown,
  ): Promise<unknown> {
    const response = await this.#fetch(`${this.#baseUrl}${path}`, {
      method,
      headers: {
        Accept: "application/json",
        Authorization: `Bearer ${credential.bearer_token}`,
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      },
      ...(body === undefined ? {} : { body: canonicalJson(body) }),
    });
    if (!response.ok) {
      throw new Error(`Creator internal API ${method} failed with HTTP ${response.status}`);
    }
    return response.json() as Promise<unknown>;
  }

  async readAs(workspaceId: string, principal: RuntimePrincipal): Promise<CreatorWorkspaceRead> {
    if (typeof workspaceId !== "string" || !/^[a-zA-Z0-9._-]+$/.test(workspaceId)) {
      throw new TypeError("workspaceId must use only safe alphanumeric, dot, underscore or hyphen characters");
    }
    createCreatorCapabilityGate(principal).require("context.read_private");
    const credential = await this.#credentialFor(principal, "context.read_private");
    const raw = await this.#requestJson(
      "GET",
      `/internal/creator/workspaces/${encodeURIComponent(workspaceId)}`,
      credential,
    );
    const records = validateReadResponse(raw);
    const events = records.map((record) => record.event);
    if (records.length === 0) return { records, events };
    let view: CreatorView;
    try {
      view = replayCreatorWorkspace(records);
    } catch (error) {
      throw new CreatorHttpStoreProtocolError(
        `Creator workspace read response cannot be replayed: ${error instanceof Error ? error.message : String(error)}`,
      );
    }
    if (view.workspace_id !== workspaceId) {
      throw new CreatorHttpStoreProtocolError("Creator workspace read response workspace_id does not match request");
    }
    return { records, events, view };
  }

  async appendAs(event: CreatorEvent, principal: RuntimePrincipal): Promise<CreatorView> {
    validateCreatorEvent(event);
    if (!isCreatorPersistenceV0Event(event)) {
      throw new CreatorHttpStoreProtocolError(`Creator event type is outside persistence v0: ${event.type}`);
    }
    const capability = creatorCapabilityForEventType(event.type);
    const gate = createCreatorCapabilityGate(principal);
    gate.require("context.read_private");
    gate.require(capability);
    const credential = await this.#credentialFor(principal, capability);
    createCreatorCapabilityGate(credential.principal).require("context.read_private");
    const rawReceipt = await this.#requestJson(
      "POST",
      `/internal/creator/workspaces/${encodeURIComponent(event.workspace_id)}/events`,
      credential,
      { event },
    );
    const receipt = validateAppendReceipt(rawReceipt);
    const expectedRevision = event.base_revision + 1;
    const expectedHash = contentHash(event);
    if (receipt.event_id !== event.event_id
      || receipt.committed_revision !== expectedRevision
      || receipt.payload_sha256 !== expectedHash) {
      throw new CreatorHttpStoreProtocolError("Creator append receipt does not match submitted event");
    }

    const persisted = await this.readAs(event.workspace_id, principal);
    const matches = persisted.records
      .map((record, index) => ({ record, revision: index + 1 }))
      .filter(({ record }) => record.event.event_id === event.event_id);
    if (matches.length !== 1) {
      throw new CreatorHttpStoreProtocolError("Creator append receipt event is not uniquely present after re-read");
    }
    const match = matches[0]!;
    if (match.revision !== receipt.committed_revision
      || canonicalJson(match.record.event) !== canonicalJson(event)
      || contentHash(match.record.event) !== receipt.payload_sha256
      || match.record.committed_by.principal_id !== credential.principal.principal_id
      || match.record.committed_by.product !== credential.principal.product
      || match.record.committed_by.environment !== credential.principal.environment
      || match.record.committed_by.capability !== capability) {
      throw new CreatorHttpStoreProtocolError("Creator append receipt event failed exact post-commit verification");
    }
    if (!persisted.view || persisted.view.revision < receipt.committed_revision) {
      throw new CreatorHttpStoreProtocolError("Creator append receipt revision is absent after re-read");
    }
    let committedView: CreatorView;
    try {
      committedView = replayCreatorWorkspace(persisted.records.slice(0, receipt.committed_revision));
    } catch (error) {
      throw new CreatorHttpStoreProtocolError(
        `Creator append receipt prefix cannot be replayed: ${error instanceof Error ? error.message : String(error)}`,
      );
    }
    if (committedView.revision !== receipt.committed_revision || committedView.last_event_id !== event.event_id) {
      throw new CreatorHttpStoreProtocolError("Creator append receipt does not identify the exact committed prefix");
    }
    return committedView;
  }
}
