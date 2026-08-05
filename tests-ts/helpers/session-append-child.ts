import { JsonlSessionStore } from "../../agent_runtime/consumer/session/engine.ts";
import type { RiderSessionEvent } from "../../agent_runtime/consumer/session/types.ts";

const [directory, eventJson] = process.argv.slice(2);
if (!directory || !eventJson) throw new Error("expected directory and Session event JSON");
const event = JSON.parse(eventJson) as RiderSessionEvent;
const view = await new JsonlSessionStore(directory).append(event);
process.stdout.write(String(view.revision));
