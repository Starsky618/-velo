import { readFile } from "node:fs/promises";

import { canonicalJson } from "../../agent_runtime/shared/canonical.ts";
import { replayCreatorWorkspace } from "../../agent_runtime/creator/state/engine.ts";
import type { CreatorStoredEvent } from "../../agent_runtime/creator/state/types.ts";

const [, , recordsPath] = process.argv;
if (!recordsPath) throw new Error("usage: creator-projection-digest-child <records.json>");

const records = JSON.parse(await readFile(recordsPath, "utf8")) as CreatorStoredEvent[];
const view = replayCreatorWorkspace(records);
const latestRights = Object.values(view.rights_checks).reduce((bySource, check) => {
  bySource.set(check.source_ref, check);
  return bySource;
}, new Map<string, (typeof view.rights_checks)[string]>());
const digest = {
  revision: view.revision,
  source_rights: Object.values(view.sources).sort((left, right) => left.source_ref.localeCompare(right.source_ref)).map((source) => {
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
process.stdout.write(canonicalJson(digest));
