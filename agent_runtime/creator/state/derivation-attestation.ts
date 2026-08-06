import { createPrivateKey, createPublicKey, sign, verify, type KeyObject } from "node:crypto";

import { canonicalJson, contentHash } from "../../shared/canonical.ts";
import type { RuntimePrincipal } from "../../shared/capability-gate.ts";
import { creatorCapabilityForEvent } from "../capabilities.ts";
import { applyCreatorEvent, replayCreatorWorkspace, validateCreatorAppendEvent } from "./engine.ts";
import type { CreatorEvent, CreatorStoredEvent } from "./types.ts";

export const CREATOR_DERIVATION_ATTESTATION_VERSION = 1 as const;
export const CREATOR_DERIVED_EVENT_TYPES = [
  "creator.turn_interpretation_proposed",
  "creator.behavior_calibration_recorded",
  "creator.judgment_promotion_proposed",
] as const;

export interface CreatorDerivationAttestationCore {
  schema_version: typeof CREATOR_DERIVATION_ATTESTATION_VERSION;
  algorithm: "ed25519";
  key_id: string;
  workspace_id: string;
  event_id: string;
  base_revision: number;
  event_payload_hash: string;
  prior_records_hash: string;
  principal_id: string;
  principal_environment: RuntimePrincipal["environment"];
  authorized_capability: string;
}

export interface CreatorDerivationAttestation extends CreatorDerivationAttestationCore {
  signature: string;
}

export interface CreatorDerivationAttestor {
  attest(
    event: CreatorEvent,
    priorRecords: readonly CreatorStoredEvent[],
    principal: RuntimePrincipal,
  ): CreatorDerivationAttestation;
}

export interface CreatorDerivationKeyPolicy {
  allowed_principal_ids: string[];
  allowed_environments: RuntimePrincipal["environment"][];
  allowed_capabilities: string[];
}

export function creatorEventRequiresDerivationAttestation(event: CreatorEvent): boolean {
  return (CREATOR_DERIVED_EVENT_TYPES as readonly string[]).includes(event.type)
    || event.type === "creator.task_state_changed"
    || (event.type === "creator.judgment_proposed" && event.schema_version === 2);
}

function requireEd25519PrivateKey(value: string): KeyObject {
  if (typeof value !== "string" || value.trim() === "") {
    throw new TypeError("Creator derivation attestation private key must be non-empty PEM");
  }
  const key = createPrivateKey(value);
  if (key.asymmetricKeyType !== "ed25519") throw new TypeError("Creator derivation attestation requires an Ed25519 private key");
  return key;
}

/**
 * Signs only after the TypeScript reducer accepts the exact event against the
 * exact prior event prefix. PostgreSQL verifies the signature before append,
 * so a bearer credential alone cannot forge a model-derived state change.
 */
export class CreatorEd25519DerivationAttestor implements CreatorDerivationAttestor {
  readonly #keyId: string;
  readonly #privateKey: KeyObject;
  readonly #policy: CreatorDerivationKeyPolicy;

  constructor(keyId: string, privateKeyPem: string, policy: CreatorDerivationKeyPolicy) {
    if (typeof keyId !== "string" || keyId.trim() === "") throw new TypeError("Creator derivation key_id must be non-empty");
    if (!policy || !Array.isArray(policy.allowed_principal_ids) || policy.allowed_principal_ids.length === 0
      || !Array.isArray(policy.allowed_environments) || policy.allowed_environments.length === 0
      || !Array.isArray(policy.allowed_capabilities) || policy.allowed_capabilities.length === 0
      || [...policy.allowed_principal_ids, ...policy.allowed_environments, ...policy.allowed_capabilities]
        .some((item) => typeof item !== "string" || item.trim() === "")) {
      throw new TypeError("Creator derivation key policy must explicitly scope principals, environments and capabilities");
    }
    this.#keyId = keyId;
    this.#privateKey = requireEd25519PrivateKey(privateKeyPem);
    this.#policy = structuredClone(policy);
  }

  attest(
    event: CreatorEvent,
    priorRecords: readonly CreatorStoredEvent[],
    principal: RuntimePrincipal,
  ): CreatorDerivationAttestation {
    validateCreatorAppendEvent(event);
    if (!creatorEventRequiresDerivationAttestation(event)) {
      throw new Error(`Creator event does not require derivation attestation: ${event.type}`);
    }
    if (priorRecords.length !== event.base_revision) {
      throw new Error("Creator derivation attestation requires the exact prior revision prefix");
    }
    const priorView = priorRecords.length === 0 ? undefined : replayCreatorWorkspace(priorRecords);
    applyCreatorEvent(priorView, event, principal);
    const capability = creatorCapabilityForEvent(event);
    if (!this.#policy.allowed_principal_ids.includes(principal.principal_id)
      || !this.#policy.allowed_environments.includes(principal.environment)
      || !this.#policy.allowed_capabilities.includes(capability)) {
      throw new Error("Creator derivation signing key is not authorized for this principal, environment and capability");
    }
    const core: CreatorDerivationAttestationCore = {
      schema_version: CREATOR_DERIVATION_ATTESTATION_VERSION,
      algorithm: "ed25519",
      key_id: this.#keyId,
      workspace_id: event.workspace_id,
      event_id: event.event_id,
      base_revision: event.base_revision,
      event_payload_hash: contentHash(event),
      prior_records_hash: contentHash(priorRecords),
      principal_id: principal.principal_id,
      principal_environment: principal.environment,
      authorized_capability: capability,
    };
    return {
      ...core,
      signature: `ed25519:${sign(null, Buffer.from(canonicalJson(core)), this.#privateKey).toString("base64url")}`,
    };
  }
}

/** Test/support helper: verification needs only a public key and cannot mint reducer proofs. */
export function verifyCreatorEd25519DerivationAttestation(
  attestation: CreatorDerivationAttestation,
  publicKeyPem: string,
): boolean {
  const publicKey = createPublicKey(publicKeyPem);
  if (publicKey.asymmetricKeyType !== "ed25519") throw new TypeError("Creator derivation verification requires an Ed25519 public key");
  const { signature, ...core } = attestation;
  if (!signature.startsWith("ed25519:")) return false;
  try {
    return verify(null, Buffer.from(canonicalJson(core)), publicKey, Buffer.from(signature.slice(8), "base64url"));
  } catch {
    return false;
  }
}
