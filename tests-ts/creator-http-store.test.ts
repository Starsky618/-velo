import assert from "node:assert/strict";
import test from "node:test";

import { createShadowRiderPrincipal } from "../agent_runtime/consumer/capabilities.ts";
import { CREATOR_CAPABILITIES, createTestCreatorPrincipal } from "../agent_runtime/creator/capabilities.ts";
import {
  CreatorHttpStoreProtocolError,
  HttpCreatorWorkspaceStore,
  type CreatorInternalApiCredential,
} from "../agent_runtime/creator/state/http-store.ts";
import type { CreatorEvent, CreatorStoredEvent } from "../agent_runtime/creator/state/types.ts";
import { contentHash } from "../agent_runtime/shared/canonical.ts";
import type { RuntimePrincipal } from "../agent_runtime/shared/capability-gate.ts";

const principal = createTestCreatorPrincipal();
const credential: CreatorInternalApiCredential = {
  bearer_token: "test-token.secret",
  principal,
};

const started: CreatorEvent = {
  schema_version: 1,
  type: "creator.workspace_started",
  event_id: "evt-start",
  workspace_id: "workspace-http",
  base_revision: 0,
  occurred_at: "2026-08-06T01:00:00.000Z",
  mission: "Persist Creator knowledge",
};

const source: CreatorEvent = {
  schema_version: 1,
  type: "creator.source_ingested",
  event_id: "evt-source",
  workspace_id: started.workspace_id,
  base_revision: 1,
  occurred_at: "2026-08-06T01:01:00.000Z",
  source_ref: "source:1",
  source_kind: "conversation",
  content_hash: "sha256:0000000000000000000000000000000000000000000000000000000000000001",
  immutable_ref: "conversation:1:revision:1",
  provenance_ref: "conversation:1",
};

const sourceProjectionDigest = {
  revision: 2,
  source_rights: [{
    source_ref: "source:1",
    source_event_revision: 2,
    rights_decision: null,
    rights_event_revision: null,
  }],
  current_judgment_refs: [],
  pending_judgment_refs: [],
  decision_refs: [],
  unresolved_contradiction_refs: [],
};

function stored(event: CreatorEvent, committedPrincipal: RuntimePrincipal = principal): CreatorStoredEvent {
  const capability = event.type === "creator.workspace_started" ? "workspace.create" : "source.ingest";
  return {
    event,
    committed_by: {
      principal_id: committedPrincipal.principal_id,
      product: "creator",
      environment: committedPrincipal.environment,
      capability,
    },
  };
}

function responseJson(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function makeStore(fetchImplementation: typeof globalThis.fetch, suppliedCredential: unknown = credential): HttpCreatorWorkspaceStore {
  return new HttpCreatorWorkspaceStore({
    base_url: "https://creator.internal/",
    credentials: async () => suppliedCredential as CreatorInternalApiCredential,
    fetch: fetchImplementation,
  });
}

test("HTTP Creator Store authenticates reads and replays exact stored events", async () => {
  let calls = 0;
  const fetchImplementation: typeof fetch = async (input, init) => {
    calls += 1;
    assert.equal(String(input), "https://creator.internal/internal/creator/workspaces/workspace-http");
    assert.equal(init?.method, "GET");
    assert.equal(new Headers(init?.headers).get("Authorization"), "Bearer test-token.secret");
    assert.equal(init?.body, undefined);
    return responseJson({ records: [stored(started)] });
  };
  const read = await makeStore(fetchImplementation).readAs(started.workspace_id, principal);
  assert.equal(calls, 1);
  assert.equal(read.view?.revision, 1);
  assert.deepEqual(read.events, [started]);
});

test("HTTP Creator Store reads an exact projection prefix at the requested revision", async () => {
  const fetchImplementation: typeof fetch = async (input, init) => {
    assert.equal(
      String(input),
      "https://creator.internal/internal/creator/workspaces/workspace-http/projection-records?expected_revision=2",
    );
    assert.equal(init?.method, "GET");
    assert.equal(new Headers(init?.headers).get("Authorization"), "Bearer test-token.secret");
    return responseJson({
      revision: 2,
      records: [stored(started), stored(source)],
      digest: sourceProjectionDigest,
    });
  };
  const projection = await makeStore(fetchImplementation).readProjectionRecordsAs(
    started.workspace_id,
    2,
    principal,
  );
  assert.equal(projection.revision, 2);
  assert.deepEqual(projection.records.map((record) => record.event.event_id), ["evt-start", "evt-source"]);
});

test("HTTP Creator Store fails closed for malformed or mismatched projection prefixes", async (t) => {
  await t.test("revision mismatch", async () => {
    await assert.rejects(
      () => makeStore(async () => responseJson({ revision: 1, records: [stored(started)], digest: sourceProjectionDigest }))
        .readProjectionRecordsAs(started.workspace_id, 2, principal),
      /revision does not match request/,
    );
  });
  await t.test("missing revision", async () => {
    await assert.rejects(
      () => makeStore(async () => responseJson({ revision: 2, records: [stored(started)], digest: sourceProjectionDigest }))
        .readProjectionRecordsAs(started.workspace_id, 2, principal),
      /do not cover the requested revision/,
    );
  });
  await t.test("non-contiguous base revision", async () => {
    const wrongBase = { ...source, base_revision: 0 };
    await assert.rejects(
      () => makeStore(async () => responseJson({
        revision: 2,
        records: [stored(started), stored(wrongBase)],
        digest: sourceProjectionDigest,
      })).readProjectionRecordsAs(started.workspace_id, 2, principal),
      /not the exact requested workspace prefix/,
    );
  });
  await t.test("unsafe revision rejected before transport", async () => {
    let calls = 0;
    await assert.rejects(
      () => makeStore(async () => { calls += 1; throw new Error("must not fetch"); })
        .readProjectionRecordsAs(started.workspace_id, Number.MAX_SAFE_INTEGER + 1, principal),
      /expectedRevision must be a non-negative safe integer/,
    );
    assert.equal(calls, 0);
  });
});

test("HTTP Creator Store rejects Rider, credential mismatch, and missing bearer token before transport", async (t) => {
  let calls = 0;
  const neverFetch: typeof fetch = async () => {
    calls += 1;
    throw new Error("must not fetch");
  };

  await t.test("Rider is denied", async () => {
    await assert.rejects(
      () => makeStore(neverFetch).readAs(started.workspace_id, createShadowRiderPrincipal()),
      /capability denied.*context\.read_private/,
    );
  });
  await t.test("caller must exactly match credential principal", async () => {
    const reordered: RuntimePrincipal = { ...principal, scopes: [...CREATOR_CAPABILITIES].reverse() };
    await assert.rejects(
      () => makeStore(neverFetch).readAs(started.workspace_id, reordered),
      /does not match authenticated principal/,
    );
  });
  await t.test("blank token fails closed", async () => {
    await assert.rejects(
      () => makeStore(neverFetch, { bearer_token: "", principal }).readAs(started.workspace_id, principal),
      /bearer token must be non-empty/,
    );
  });
  await t.test("unsafe workspace path is rejected before fetch", async () => {
    await assert.rejects(
      () => makeStore(neverFetch).readAs("workspace/http", principal),
      /workspaceId must use only safe/,
    );
  });
  await t.test("malformed principal Unicode is rejected before fetch", async () => {
    const malformed: RuntimePrincipal = { ...principal, principal_id: "bad\ud800principal" };
    await assert.rejects(
      () => makeStore(neverFetch, { bearer_token: "test-token.secret", principal: malformed })
        .readAs(started.workspace_id, malformed),
      /principal_id must contain only Unicode scalar/,
    );
  });
  await t.test("malformed scope Unicode is rejected before fetch", async () => {
    const malformed: RuntimePrincipal = { ...principal, scopes: [...principal.scopes, "bad\ud800scope"] };
    await assert.rejects(
      () => makeStore(neverFetch, { bearer_token: "test-token.secret", principal: malformed })
        .readAs(started.workspace_id, malformed),
      /scopes must contain only Unicode scalar/,
    );
  });
  assert.equal(calls, 0);
});

test("HTTP Creator Store POST body contains only the event and verifies receipt by re-reading", async () => {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  const fetchImplementation: typeof fetch = async (input, init) => {
    calls.push({ url: String(input), ...(init ? { init } : {}) });
    if (init?.method === "POST") {
      assert.deepEqual(JSON.parse(String(init.body)), { event: source });
      assert.equal(String(init.body).includes("test-token.secret"), false);
      assert.equal(String(init.body).includes(principal.principal_id), false);
      return responseJson({
        event_id: source.event_id,
        committed_revision: 2,
        payload_sha256: contentHash(source),
      });
    }
    return responseJson({ records: [stored(started), stored(source)] });
  };

  const view = await makeStore(fetchImplementation).appendAs(source, principal);
  assert.equal(view.revision, 2);
  assert.equal(calls.length, 2);
  assert.equal(calls[0]?.url, "https://creator.internal/internal/creator/workspaces/workspace-http/events");
  assert.equal(calls[0]?.init?.method, "POST");
  assert.equal(new Headers(calls[0]?.init?.headers).get("Authorization"), "Bearer test-token.secret");
  assert.equal(calls[1]?.init?.method, "GET");
});

test("HTTP Creator Store returns the receipt revision when another writer commits before re-read", async () => {
  const later: CreatorEvent = {
    ...source,
    event_id: "evt-source-later",
    base_revision: 2,
    occurred_at: "2026-08-06T01:02:00.000Z",
    source_ref: "source:later",
    content_hash: "sha256:0000000000000000000000000000000000000000000000000000000000000002",
    immutable_ref: "conversation:2:revision:1",
    provenance_ref: "conversation:2",
  };
  let call = 0;
  const fetchImplementation: typeof fetch = async () => {
    call += 1;
    return call === 1
      ? responseJson({ event_id: source.event_id, committed_revision: 2, payload_sha256: contentHash(source) })
      : responseJson({ records: [stored(started), stored(source), stored(later)] });
  };
  const committed = await makeStore(fetchImplementation).appendAs(source, principal);
  assert.equal(committed.revision, 2);
  assert.equal(committed.last_event_id, source.event_id);
});

test("HTTP Creator Store fails closed for malformed records and workspace mismatch", async (t) => {
  await t.test("invalid record receipt", async () => {
    const bad = { ...stored(started), committed_by: { ...stored(started).committed_by, capability: "source.ingest" } };
    await assert.rejects(
      () => makeStore(async () => responseJson({ records: [bad] })).readAs(started.workspace_id, principal),
      /invalid stored event.*capability does not match/,
    );
  });
  await t.test("different workspace", async () => {
    const other = { ...started, workspace_id: "workspace-other" };
    await assert.rejects(
      () => makeStore(async () => responseJson({ records: [stored(other)] })).readAs(started.workspace_id, principal),
      /workspace_id does not match request/,
    );
  });
  await t.test("unexpected response fields", async () => {
    await assert.rejects(
      () => makeStore(async () => responseJson({ records: [], principal })).readAs(started.workspace_id, principal),
      /unexpected fields/,
    );
  });
});

test("HTTP Creator Store rejects bad append receipts and inconsistent committed records", async (t) => {
  async function expectAppendRejected(receipt: unknown, records: CreatorStoredEvent[], pattern: RegExp): Promise<void> {
    let call = 0;
    const fetchImplementation: typeof fetch = async () => {
      call += 1;
      return call === 1 ? responseJson(receipt) : responseJson({ records });
    };
    await assert.rejects(() => makeStore(fetchImplementation).appendAs(source, principal), pattern);
  }

  await t.test("wrong receipt revision", async () => {
    await expectAppendRejected(
      { event_id: source.event_id, committed_revision: 3, payload_sha256: contentHash(source) },
      [stored(started), stored(source)],
      /receipt does not match submitted event/,
    );
  });
  await t.test("wrong receipt hash", async () => {
    await expectAppendRejected(
      { event_id: source.event_id, committed_revision: 2, payload_sha256: contentHash(started) },
      [stored(started), stored(source)],
      /receipt does not match submitted event/,
    );
  });
  await t.test("event absent after receipt", async () => {
    await expectAppendRejected(
      { event_id: source.event_id, committed_revision: 2, payload_sha256: contentHash(source) },
      [stored(started)],
      /not uniquely present after re-read/,
    );
  });
  await t.test("record receipt bound to another principal", async () => {
    const other: RuntimePrincipal = { ...principal, principal_id: "test:other-creator" };
    await expectAppendRejected(
      { event_id: source.event_id, committed_revision: 2, payload_sha256: contentHash(source) },
      [stored(started), stored(source, other)],
      /failed exact post-commit verification/,
    );
  });
});

test("HTTP Creator Store preserves transport failures for CreatorAgent read-after-error reconciliation", async () => {
  const networkFailure = new Error("connection reset after commit");
  await assert.rejects(
    () => makeStore(async () => { throw networkFailure; }).appendAs(source, principal),
    (error) => error === networkFailure,
  );
});

test("HTTP Creator Store rejects event families outside persistence v0 before transport", async () => {
  let calls = 0;
  const unsupported: CreatorEvent = {
    schema_version: 1,
    type: "creator.claim_proposed",
    event_id: "evt-claim",
    workspace_id: started.workspace_id,
    base_revision: 2,
    occurred_at: "2026-08-06T01:02:00.000Z",
    claim_id: "claim:1",
    subject_ref: "route:tianlongshan",
    predicate: "shape",
    proposed_value: "linear",
    temporality: "permanent",
    evidence_refs: ["evidence:1"],
  };
  await assert.rejects(
    () => makeStore(async () => { calls += 1; throw new Error("must not fetch"); }).appendAs(unsupported, principal),
    /outside persistence v0/,
  );
  assert.equal(calls, 0);
});

test("HTTP Creator Store rejects non-success status without trusting the response body", async () => {
  await assert.rejects(
    () => makeStore(async () => responseJson({ records: [stored(started)] }, 401)).readAs(started.workspace_id, principal),
    /GET failed with HTTP 401/,
  );
});
