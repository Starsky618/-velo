import { canonicalJson } from "../../shared/canonical.ts";
import { compileCreatorContext, type CreatorContextRequest } from "../context/compiler.ts";
import type { CreatorView } from "../state/types.ts";

export interface CreatorReplayExpectation {
  current_judgment_refs: string[];
  forbidden_judgment_refs: string[];
  unresolved_contradiction_refs: string[];
}

export interface CreatorReplayEvalResult {
  verdict: "pass" | "fail";
  checks: Array<{ name: string; passed: boolean; detail: string }>;
}

/**
 * Context-compression eval: compare the in-process view with a cold replayed
 * view, then assert the exact current/forbidden judgment and contradiction set.
 */
export function evaluateCreatorContextReplay(
  liveView: CreatorView,
  replayedView: CreatorView,
  request: CreatorContextRequest,
  expectation: CreatorReplayExpectation,
): CreatorReplayEvalResult {
  const live = compileCreatorContext(liveView, request);
  const replayed = compileCreatorContext(replayedView, request);
  const current = new Set(replayed.manifest.included.judgment_refs);
  const unresolved = new Set(replayed.manifest.included.contradiction_refs);
  const checks = [
    {
      name: "cold_replay_is_identical",
      passed: canonicalJson(live) === canonicalJson(replayed),
      detail: `live=${live.manifest.context_hash};replayed=${replayed.manifest.context_hash}`,
    },
    {
      name: "expected_current_judgments",
      passed: expectation.current_judgment_refs.every((ref) => current.has(ref))
        && current.size === expectation.current_judgment_refs.length,
      detail: `current=${[...current].sort().join(",")}`,
    },
    {
      name: "forbidden_judgments_absent",
      passed: expectation.forbidden_judgment_refs.every((ref) => !current.has(ref)),
      detail: `forbidden=${expectation.forbidden_judgment_refs.join(",")}`,
    },
    {
      name: "unresolved_contradictions_match",
      passed: expectation.unresolved_contradiction_refs.every((ref) => unresolved.has(ref))
        && unresolved.size === expectation.unresolved_contradiction_refs.length,
      detail: `unresolved=${[...unresolved].sort().join(",")}`,
    },
  ];
  return { verdict: checks.every((check) => check.passed) ? "pass" : "fail", checks };
}
