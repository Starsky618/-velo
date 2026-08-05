import type { RuntimePrincipal } from "../../shared/capability-gate.ts";
import type { CreatorEvent, CreatorStoredEvent, CreatorView } from "./types.ts";

export interface CreatorWorkspaceRead {
  records: CreatorStoredEvent[];
  events: CreatorEvent[];
  view?: CreatorView;
}

/**
 * Runtime-facing persistence seam. Production may implement this through an
 * authenticated Domain Plane API; the TypeScript Agent must not learn SQL.
 */
export interface CreatorWorkspaceStore {
  readAs(workspaceId: string, principal: RuntimePrincipal): Promise<CreatorWorkspaceRead>;
  appendAs(event: CreatorEvent, principal: RuntimePrincipal): Promise<CreatorView>;
}
