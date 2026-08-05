import { readFile } from "node:fs/promises";

import { canonicalJson } from "../../agent_runtime/shared/canonical.ts";
import { creatorProjectionDigestFromView } from "../../agent_runtime/creator/context/projection-guard.ts";
import { replayCreatorWorkspace } from "../../agent_runtime/creator/state/engine.ts";
import type { CreatorStoredEvent } from "../../agent_runtime/creator/state/types.ts";

const [, , recordsPath] = process.argv;
if (!recordsPath) throw new Error("usage: creator-projection-digest-child <records.json>");

const records = JSON.parse(await readFile(recordsPath, "utf8")) as CreatorStoredEvent[];
const view = replayCreatorWorkspace(records);
process.stdout.write(canonicalJson(creatorProjectionDigestFromView(view)));
