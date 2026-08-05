import { canonicalJson } from "../../agent_runtime/shared/canonical.ts";
import { compileCreatorContext, type CreatorContextRequest } from "../../agent_runtime/creator/context/compiler.ts";
import { createTestCreatorPrincipal } from "../../agent_runtime/creator/capabilities.ts";
import { JsonlCreatorStore } from "../../agent_runtime/creator/state/engine.ts";

const [directory, workspaceId, requestJson] = process.argv.slice(2);
if (!directory || !workspaceId || !requestJson) throw new Error("expected directory, workspace id and Context request JSON");
const request = JSON.parse(requestJson) as CreatorContextRequest;
const store = new JsonlCreatorStore(directory, createTestCreatorPrincipal());
const view = (await store.read(workspaceId)).view;
if (!view) throw new Error(`workspace not found: ${workspaceId}`);
process.stdout.write(canonicalJson(compileCreatorContext(view, request)));
