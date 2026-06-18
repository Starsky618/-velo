# Route Cognition v1.1 Operationalization Plan

Generated: 2026-06-19

## 0. Grounding

The DB foundation is complete, but the product is not operationally complete.

Verified current facts:

- Final DB foundation head is `20260618_membership_formal`.
- `app/route_cognition/services/` currently contains only the segment eligibility writer path.
- `concept_nodes`, `route_collections`, concept candidates, concept formal links, and formal membership tables exist as DB/ORM foundations.
- No route cognition public API, admin UI, evidence public API, membership candidates, or `segment_submissions` are implemented.

This plan must not create schema, migrations, API routes, UI, or patches outside this document.

## 1. Internal Writer Services Needed First

Priority is not “what looks most complete in the schema.” Priority is “what lets a human create a tiny trusted Taiyuan/Xishan knowledge set without opening unsafe write paths.”

### P0: Shared Internal Write Guard

Before individual writers, every writer service must share the same internal write guard/helper. A future implementation can live at `app/route_cognition/services/write_guard.py`.

- Must run inside backend/internal code only.
- Must require an explicit `human_review` judgment where the target table requires it.
- Must reject direct agent formal writes.
- Must never write `evidence_items` as public content.
- Must never mutate `content/routes/**`, `guide.md`, or `route_guides.content_md`.
- No formal writer may bypass this guard.
- Must make the caller choose one of:
  - candidate proposal,
  - human acceptance/rejection,
  - manual curated formal write,
  - legacy import formal write.

This is a shared boundary, not a loose service convention. Each future writer may keep its own domain logic, but formal writes must pass through the same guard before touching DB rows.

Global formal write rule:

- No formal writer may create a formal row unless `accepted_judgment_run_id` points to a `human_review` judgment.

### P1: Concept Node Writer

Purpose: create and update a small, reviewed vocabulary of concepts such as landmarks, practice types, road conditions, safety risks, local terms, and training themes.

Why first:

- Concept candidates and formal concept links need stable `concept_nodes`.
- A small vocabulary avoids garbage concepts multiplying through candidates.

Rules:

- Default `visibility = private`.
- Default `publish_status = draft`.
- Published concepts require a source judgment.
- Imported concepts require `source_ref` or source judgment.
- `metadata_json` remains display/source supplement only; it must not contain relationship truth.

Suggested first use:

- Taiyuan/Xishan concepts only.
- A tiny hand-reviewed list: climbs, landmarks, local road names, safety risks, training themes.

### P2: Route Collection Writer

Purpose: create route-system containers such as Taiyuan Xishan, Jueweishan family, Tianlongshan corridor, or training theme packs.

Why second:

- Collections give the seed set a home.
- Collection memberships and collection concept links need stable `route_collections`.

Rules:

- Default `visibility = private`.
- Default `publish_status = draft`.
- No membership truth in `stats_json` or `metadata_json`.
- No route/segment membership writes inside this writer.

Suggested first use:

- 2-4 Taiyuan/Xishan collections only.

### P3: Concept Candidate Writer

Purpose: create typed candidate rows:

- `route_concept_candidates`
- `segment_concept_candidates`
- `collection_concept_candidates`

Why third:

- It lets algorithm/agent/human proposals enter a review queue without becoming formal truth.
- It preserves judgment/evidence summaries and missing/contradiction summaries before human acceptance.

Rules:

- Candidate writes may be proposed by algorithm/agent/human/imported sources.
- Candidates must point to `created_by_judgment_run_id` and `latest_judgment_run_id`.
- Segment candidates must target `route_cognition_segments.segment_id`, not raw `segments.id`.
- Route candidates must carry `route_book_id`, `route_version_id`, and frozen `route_line_hash`.
- The writer must copy frozen hash projections from current trusted sources, not accept arbitrary caller-supplied hashes.
- The candidate writer must not create `evidence_items` unless the evidence was actually used by a `judgment_run`.
- `evidence_items` are not generic research storage.

Suggested first use:

- Generate or manually enter a handful of route/segment/collection concept candidates for the seed set.

### P4: Concept Formal Link Promotion Writer

Purpose: promote accepted typed candidates into formal concept links:

- `route_concept_links`
- `segment_concept_links`
- `collection_concept_links`

Why fourth:

- Formal concept links must not be written directly by agents.
- The promotion writer is the gate where a human review turns a candidate into official route cognition truth.

Rules:

- `source_kind = candidate_accepted` only when the source candidate is accepted.
- Must use the wide formal-gate fields already enforced by DB.
- Must require `accepted_judgment_run_id` with `accepted_judgment_run_type = human_review`.
- Must reject mismatched route hash, segment hash, concept id, relation type, or target id.
- Must allow `manual_curated` / `legacy_import` only through a separate explicit reviewer path.
- Candidate acceptance and formal link creation must happen in one DB transaction.

Suggested first use:

- Promote only the best-reviewed candidates from the Taiyuan/Xishan seed set.

### P5: Route Segment Manual Writer

Purpose: write `route_segments` as a human-curated route composition / explanation layer.

Why fifth:

- Route composition is useful, but it is not required before concept vocabulary and candidate review work.
- It depends on route versions and whitelisted segments being trustworthy.

Rules:

- `route_segments` is not route geometry truth.
- `route_versions.reference_line_snapshot` remains route geometry truth.
- `route_books.reference_line` remains current version projection.
- The route segment writer must not update `route_books.reference_line`.
- The route segment writer must not update `route_versions.reference_line_snapshot`.
- `route_segments` remains composition overlay only.
- `segment_clip` must reference a whitelisted `route_cognition_segments.segment_id`.
- `segment_clip` must freeze `segment_geometry_hash`.
- `custom_geometry` is allowed only as reviewed component geometry, not as a hidden segment.
- Source kind is limited to `manual_curated` / `legacy_import`.

Suggested first use:

- Only 1-3 well-known Taiyuan/Xishan official routes.
- Do not decompose every route.

### P6: Collection Membership Manual Writer

Purpose: write reviewed collection memberships:

- `collection_routes`
- `collection_segments`

Why sixth:

- Collections can exist before memberships.
- Membership should come after the seed route/segment objects are trusted.

Rules:

- `collection_routes` references `route_collections` and `route_books`.
- `collection_segments` references `route_collections` and whitelisted route cognition segments.
- Source kind is limited to `manual_curated` / `legacy_import`.
- No membership candidates exist yet; do not simulate them in metadata.

Suggested first use:

- Put only the seed routes and a few landmark/risk/training segments into Taiyuan/Xishan collections.

## 2. Services That Must Remain Internal-Only

These services must not be public API yet:

- Concept node writer.
- Route collection writer.
- Concept candidate writer.
- Concept formal link promotion writer.
- Route segment manual writer.
- Collection membership manual writer.
- Segment eligibility writer.
- Judgment/evidence inspection helpers.

Hard boundaries:

- No public API yet.
- No agent direct formal writes.
- No evidence public API.
- No candidate public API.
- No unauthenticated route cognition reads until read-only publication rules are designed.
- No admin UI until internal services and reviewer workflows are proven on a tiny seed set.

## 3. Minimum Safe Seed Data Plan

Seed goal: create a tiny, trustworthy Taiyuan/Xishan working set that proves the workflow without flooding the DB.

Seed scope:

- Small Taiyuan/Xishan set only.
- No automatic backfill.
- No bulk import of all segments.
- No mass candidate generation.
- No public publishing by default.
- All seed objects and formal links remain private/draft or internal-only until separately approved for publication.

Recommended seed size:

- 5-10 `concept_nodes`.
- 2-4 `route_collections`.
- 3-6 route concept candidates.
- 3-6 segment concept candidates.
- 2-4 collection concept candidates.
- 1-3 promoted formal concept links per target type only after review.
- 1-3 route composition rows or small route composition examples.
- A handful of collection memberships.

Safe seed order:

1. Confirm the target route books and route versions.
2. Admit only needed segments into `route_cognition_segments` through the existing segment eligibility writer.
3. Create private/draft concept nodes.
4. Create private/draft route collections.
5. Create concept candidates with judgment summaries.
6. Review candidates with evidence/judgment context.
7. Promote only accepted candidates.
8. Add manual route composition and collection memberships.

Do not seed:

- All historical segments.
- All route books.
- All route guide claims.
- Any unreviewed agent output as formal truth.
- Relationship truth inside JSON blobs.

## 4. Reviewer / Admin Workflows Needed

No public/admin UI is implemented yet. The first workflow can be internal scripts or a protected internal tool, but it must follow the same product flow that a later admin UI will expose.

### Inspect Candidate

Reviewer must see:

- Target type: route / segment / collection.
- Target id and frozen hash projection where applicable.
- Concept node.
- Relation type.
- Candidate status.
- Created/latest/accepted judgment run ids.
- Latest confidence and confidence state.
- Evidence summary.
- Missing data summary.
- Contradiction summary.
- Reason summary.

Reviewer must not see:

- Raw chain-of-thought.
- Evidence as public content.
- Hidden write controls that bypass formal promotion.

### Inspect Judgment / Evidence

Reviewer must see:

- Judgment run type and status.
- Confidence state.
- Target route/segment if present.
- Evidence items actually used by the judgment.
- Research question/run trail if present.
- Missing data and contradiction summaries.

Reviewer must be able to answer:

- Why does this candidate exist?
- What evidence supports it?
- What is missing?
- What contradicts it?
- Is it safe to accept, reject, or mark inconclusive?

### Accept / Reject Candidate

Accept flow:

- Create or choose a `human_review` judgment run.
- Set candidate status to `accepted`.
- Set `accepted_by_judgment_run_id`.
- Set `reviewed_at`.
- Promote through the formal link promotion writer.

Reject flow:

- Create or choose a `human_review` judgment run.
- Set candidate status to `rejected`, `inconclusive`, `stale`, or `superseded`.
- Keep `accepted_by_judgment_run_id = NULL`.
- Do not create a formal link.

### Manual Curated / Legacy Import Formal Write

Manual curated formal write:

- Requires a human reviewer.
- Requires a human-review judgment.
- Must set `source_kind = manual_curated`.
- Must not point to a candidate.
- Must include a clear reason summary.

Legacy import formal write:

- Requires a human reviewer.
- Requires a human-review judgment.
- Must set `source_kind = legacy_import`.
- Must include `source_ref` or `reason_summary`.
- Must not create fake provenance.

## 5. Read-Only APIs That Can Be Introduced Safely Later

Read-only APIs should come after internal seed data has been reviewed. They should expose active, safe projections only.

### Route Concepts

Potential response:

- Route id / route version id.
- Active concept links.
- Concept name/type/summary.
- Relation type.
- Reason summary.

Do not expose:

- Candidate rows.
- Evidence raw content.
- Judgment internals.

### Segment Concepts

Potential response:

- Segment id.
- Active concept links.
- Concept name/type/summary.
- Relation type.
- Reason summary.

Do not expose:

- Raw `segments.id` if the segment is not in `route_cognition_segments`.
- Candidate rows.
- Evidence raw content.

### Collection Details

Potential response:

- Collection identity.
- Description and cover.
- Active collection concepts.
- Published stats projection.
- Safe map extent.

Do not expose:

- Metadata JSON as relationship truth.
- Internal source judgment ids unless explicitly designed for admin.

### Route Composition

Potential response:

- Ordered active `route_segments`.
- Component type.
- Segment reference when component is a segment clip.
- Custom geometry only as a safe display projection.

Do not imply:

- `route_segments` is the canonical route geometry.
- Route composition can replace `route_versions.reference_line_snapshot`.

### Collection Memberships

Potential response:

- Active collection routes.
- Active collection segments.
- Role, sequence, importance.
- Reason summary.

Do not expose:

- Membership draft/history by default.
- Evidence raw content.

## 6. Future Work

Future schema/product work, not part of the completed v1.1 DB foundation:

- `segment_submissions`.
- External search worker.
- Membership candidates:
  - `route_segment_candidates`
  - `collection_route_candidates`
  - `collection_segment_candidates`
- Route/segment spatial matching worker.
- Public UI.
- Admin UI.
- Personal private segments.
- `route_content_claims`.
- Embeddings / vector retrieval.
- Concept hierarchy.
- Concept aliases.
- Public concept pages.
- Public collection pages.
- Evidence public presentation policy.
- Bulk import/backfill strategy, if product later decides it is worth the risk.

## 7. Operating Principle

DB foundation complete does not mean product operationally complete.

The database now has the rooms, locks, and filing cabinets. The next product step is not more schema; it is a controlled internal workflow where a human can create a tiny trusted Taiyuan/Xishan knowledge set, inspect the evidence, accept or reject candidates, and only then expose safe read-only projections to users.
