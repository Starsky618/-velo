import type { RuntimePrincipal } from "../../shared/capability-gate.ts";
import type { CreatorEvent, CreatorStoredEvent, CreatorView } from "./types.ts";

export interface CreatorWorkspaceRead {
  records: CreatorStoredEvent[];
  events: CreatorEvent[];
  view?: CreatorView;
}

export interface CreatorProjectionRead {
  revision: number;
  records: CreatorStoredEvent[];
  digest: CreatorProjectionDigest;
}

export interface CreatorProjectionDigest {
  revision: number;
  source_rights: Array<{
    source_ref: string;
    source_event_revision: number;
    rights_decision: "allowed" | "forbidden" | "needs_review" | null;
    rights_event_revision: number | null;
  }>;
  current_judgment_refs: string[];
  pending_judgment_refs: string[];
  decision_refs: string[];
  unresolved_contradiction_refs: string[];
}

/** Independent relational projection read used only for pre-model drift checks. */
export interface CreatorProjectionRecordReader {
  readProjectionRecordsAs(
    workspaceId: string,
    expectedRevision: number,
    principal: RuntimePrincipal,
  ): Promise<CreatorProjectionRead>;
}

/**
 * Runtime-facing persistence seam. Production may implement this through an
 * authenticated Domain Plane API; the TypeScript Agent must not learn SQL.
 */
export interface CreatorWorkspaceStore {
  readAs(workspaceId: string, principal: RuntimePrincipal): Promise<CreatorWorkspaceRead>;
  appendAs(event: CreatorEvent, principal: RuntimePrincipal): Promise<CreatorView>;
}
