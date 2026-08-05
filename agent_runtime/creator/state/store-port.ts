import type { RuntimePrincipal } from "../../shared/capability-gate.ts";
import type { CreatorEvent, CreatorView } from "./types.ts";

/**
 * Runtime-facing persistence seam. Production may implement this through an
 * authenticated Domain Plane API; the TypeScript Agent must not learn SQL.
 */
export interface CreatorWorkspaceStore {
  read(workspaceId: string): Promise<{ events: CreatorEvent[]; view?: CreatorView }>;
  appendAs(event: CreatorEvent, principal: RuntimePrincipal): Promise<CreatorView>;
}
