import { readFile } from "node:fs/promises";

import { canonicalJson } from "../../agent_runtime/shared/canonical.ts";
import { compileCreatorContext, type CreatorContextRequest } from "../../agent_runtime/creator/context/compiler.ts";
import { replayCreatorWorkspace } from "../../agent_runtime/creator/state/engine.ts";
import type { CreatorStoredEvent } from "../../agent_runtime/creator/state/types.ts";

const [, , recordsPath, requestJson] = process.argv;
if (!recordsPath || !requestJson) throw new Error("usage: creator-context-records-child <records.json> <request-json>");

const records = JSON.parse(await readFile(recordsPath, "utf8")) as CreatorStoredEvent[];
const request = JSON.parse(requestJson) as CreatorContextRequest;
process.stdout.write(canonicalJson(compileCreatorContext(replayCreatorWorkspace(records), request)));
