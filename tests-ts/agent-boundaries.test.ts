import assert from "node:assert/strict";
import test from "node:test";

import { createRiderCapabilityGate } from "../agent_runtime/consumer/capabilities.ts";
import { createCreatorCapabilityGate } from "../agent_runtime/creator/capabilities.ts";

test("creator and rider are separate deny-by-default capability surfaces", () => {
  const creator = createCreatorCapabilityGate();
  const rider = createRiderCapabilityGate();

  assert.equal(creator.allows("evidence.inspect_raw"), true);
  assert.equal(creator.allows("plan.generate"), false);
  assert.equal(creator.allows("world.publish"), false);
  assert.equal(rider.allows("plan.generate"), true);
  assert.equal(rider.allows("evidence.inspect_raw"), false);
  assert.equal(rider.allows("world_change.propose"), false);
  assert.equal(rider.allows("world.publish"), false);
  assert.throws(() => rider.require("evidence.inspect_raw"), /capability denied/);
});
