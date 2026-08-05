import assert from "node:assert/strict";
import test from "node:test";

import { createRiderCapabilityGate, createShadowRiderPrincipal } from "../agent_runtime/consumer/capabilities.ts";
import { createCreatorCapabilityGate, createTestCreatorPrincipal } from "../agent_runtime/creator/capabilities.ts";

test("creator and rider are separate deny-by-default capability surfaces", () => {
  const creator = createCreatorCapabilityGate(createTestCreatorPrincipal());
  const rider = createRiderCapabilityGate(createShadowRiderPrincipal());

  assert.equal(creator.allows("evidence.inspect_raw"), true);
  assert.equal(creator.allows("plan.generate"), false);
  assert.equal(creator.allows("world.publish"), false);
  assert.equal(rider.allows("plan.generate"), true);
  assert.equal(rider.allows("evidence.inspect_raw"), false);
  assert.equal(rider.allows("world_change.propose"), false);
  assert.equal(rider.allows("world.publish"), false);
  assert.throws(() => rider.require("evidence.inspect_raw"), /capability denied/);
  assert.equal(createRiderCapabilityGate(createTestCreatorPrincipal()).allows("plan.generate"), false);
  assert.equal(createCreatorCapabilityGate(createShadowRiderPrincipal()).allows("evidence.inspect_raw"), false);
});
