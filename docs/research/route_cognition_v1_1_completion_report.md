# Route Cognition v1.1 Completion Report

Generated: 2026-06-19

## 1. Final Alembic Head

- Final Alembic head: `20260618_membership_formal`.
- Verified command: `python3 -m alembic heads`.
- Final migration chain tail:
  - `20260618_concept_nodes`
  - `20260618_concept_rel_candidates`
  - `20260618_concept_formal_links`
  - `20260618_membership_formal`

## 2. Commits From Batch 1 Through Step D

Implementation and ledger commits in the v1.1 DB foundation chain:

| Scope | Commit | Message |
|---|---:|---|
| Batch 1 | `f6814026` | `feat(route-books): add route versions batch 1` |
| Batch 2-4 | `a374217c` | `Add route cognition schema foundation` |
| Pre-Batch 5 ledger | `cb254cea` | `Mark route cognition pre-Batch5 planning state` |
| Batch 5 | `b623b555` | `route cognition batch5 segment eligibility foundation` |
| Batch 6 draft/foundation | `1b7c92c9` | `route cognition batch6 segment admission workflow` |
| Batch 6 final fix | `8451e289` | `route cognition batch6 segment eligibility workflow` |
| Batch 7 | `d3c520fe` | `route cognition batch7 route collections foundation` |
| Step A | `288aa69a` | `route cognition v1.1 concept nodes foundation` |
| Step B | `c8693241` | `route cognition v1.1 concept relationship candidates` |
| Status ledger cleanup | `37662ea7` | `route cognition v1.1 status ledger cleanup` |
| Step C | `ae475a0c` | `route cognition v1.1 concept formal links` |
| Step D | `2d29baa1` | `route cognition v1.1 membership formal tables` |

## 3. Tables Added By v1.1

Route identity / versioning:

- `route_versions`

Route export foundation:

- `route_export_jobs`
- `route_export_artifacts`

Judgment / evidence / research ledger:

- `judgment_runs`
- `evidence_items`
- `judgment_run_evidence`
- `research_questions`
- `research_runs`

Segment eligibility foundation:

- `segment_geometry_sources`
- `route_cognition_segments`

Collection / concept foundations:

- `route_collections`
- `concept_nodes`

Typed concept relationship candidate tables:

- `route_concept_candidates`
- `segment_concept_candidates`
- `collection_concept_candidates`

Concept formal relationship tables:

- `route_concept_links`
- `segment_concept_links`
- `collection_concept_links`

Route and collection formal membership tables:

- `route_segments`
- `collection_routes`
- `collection_segments`

Existing tables altered by v1.1:

- `route_books`: route versioning fields and publication-state constraints.
- `route_guides`: provenance fields and optional source judgment pointer.
- `judgment_runs`: `UNIQUE(id, run_type)` for human-review hard gates.
- Step B candidate tables: wide formal-gate unique constraints added in Step C.
- `route_cognition_segments`: `UNIQUE(segment_id, geometry_hash)` added in Step D.

## 4. Core Invariants Enforced By DB

Route identity and geometry truth:

- `route_books` is route identity.
- `route_versions` is geometry / navigation snapshot truth.
- `route_books.reference_line` remains the current-version projection.
- `route_versions` has route-book scoped version uniqueness and a composite `UNIQUE(id, route_book_id)` anchor.

Route guide projection:

- `route_guides.content_md` is an import/read model, not an agent-edit surface.
- `route_guides.content_origin` is enum-checked.
- `route_guides.source_route_version_id` binds guide provenance back to a route version when available.

Export foundation:

- Export jobs and artifacts bind `(route_version_id, route_book_id)` to `route_versions(id, route_book_id)`.
- Export format is limited to `gpx` / `tcx`.
- v1 route export does not enable course points.

Judgment and evidence:

- `judgment_runs.run_type`, `status`, and `confidence_state` are enum-checked.
- `judgment_runs.confidence` is bounded to `[0, 1]` when present.
- `evidence_items.fidelity_tier` is bounded to `1..5`.
- Evidence is tied to judgment runs and is not a public knowledge table.

Segment eligibility:

- `segment_geometry_sources.source_type` and `quality_status` are enum-checked.
- `segment_geometry_sources.source_start_index < source_end_index` when both are present.
- `segment_geometry_sources` requires a durable material pointer.
- `route_cognition_segments` is a whitelist over `segments`, not a review queue.
- `route_cognition_segments.eligibility_status` is limited to `active`, `suspended`, `deprecated`.
- `route_cognition_segments.reviewed_at` is required.
- `legacy_reviewed` rows must not point to `segment_geometry_sources`.
- `provenance_verified` rows must point to a source with matching `segment_id` / `geometry_hash`.
- Step D adds `UNIQUE(segment_id, geometry_hash)` on `route_cognition_segments`.

Collections and concepts:

- `route_collections` is a route system / regional topic container, not a concept node.
- `concept_nodes` is the semantic concept object table.
- Public collection/concept rows must be published.
- Published collection/concept rows require a source judgment.
- Imported collection/concept rows require source provenance.
- Slugs are scoped by city for collections and by scope/type for concepts.
- Collection/concept geometry is SRID 4326 with explicit valid geometry checks.

Typed concept candidates:

- Candidate tables are typed, not generic polymorphic tables.
- There is no `entity_type` / `entity_id` universal candidate table.
- Candidate status includes proposed/review/accepted/rejected/stale/inconclusive states.
- Accepted candidates require `accepted_by_judgment_run_id` and `reviewed_at`.
- Non-accepted candidates must not carry `accepted_by_judgment_run_id`.
- Open-candidate partial unique indexes block duplicate proposed/needs-review rows while allowing rejected history.

Concept formal links:

- Formal link status is limited to `active`, `deprecated`, `superseded`.
- Formal links require `(accepted_judgment_run_id, accepted_judgment_run_type)`.
- `accepted_judgment_run_type` is DB-locked to `human_review`.
- Candidate-accepted formal links use wide composite FKs back to the matching accepted candidate.
- Manual/legacy formal links must not point to source candidates.
- Segment concept links target `route_cognition_segments.segment_id`, not raw `segments.id`.

Membership formal tables:

- `route_segments` is a composition overlay / explanation layer, not route geometry truth.
- `route_versions.reference_line_snapshot` remains route geometry truth.
- `route_segments.segment_clip` requires `segment_id`, `segment_geometry_hash`, `component_geometry`, and `component_geometry_hash`.
- `route_segments.custom_geometry` requires component geometry but must not carry a segment id/hash.
- `route_segments` only allows valid LINESTRING / MULTILINESTRING component geometry.
- `start_fraction < end_fraction` is enforced for segment clips.
- `route_segments.segment_id` and `collection_segments.segment_id` target `route_cognition_segments.segment_id`.
- `route_segments` and `collection_segments` freeze segment hash through `(segment_id, segment_geometry_hash)`.
- Membership `source_kind` is limited to `manual_curated` / `legacy_import`.
- Membership rows require a human-review judgment.
- Active membership partial unique indexes prevent duplicate active rows while allowing deprecated history.

## 5. Explicitly Completed Scope

Completed:

- Route versioning foundation.
- Route guide provenance.
- Route export job/artifact foundation.
- Judgment ledger, evidence ledger, and research-loop tables.
- Segment geometry provenance and route cognition segment whitelist.
- Internal segment eligibility write workflow.
- Route collection foundation.
- Concept node foundation.
- Typed concept relationship candidate tables.
- Concept formal relationship tables.
- Route and collection formal membership tables.

## 6. Explicitly Not Implemented / Future Work

Not implemented in v1.1 DB foundation:

- Membership candidate tables:
  - `route_segment_candidates`
  - `collection_route_candidates`
  - `collection_segment_candidates`
- Other route/segment/collection candidate families beyond Step B concept relationship candidates.
- `segment_submissions`.
- Public route cognition API.
- Admin UI.
- External search worker.
- User-facing concept pages.
- User-facing evidence pages.
- Concept hierarchy.
- Concept alias table.
- Public collection pages backed by the new schema.
- Promotion workflow from membership candidates to membership formal tables.
- Service/admin writers for all formal relationship and membership tables.
- Automatic backfill into route cognition whitelist, concept links, or membership tables.

## 7. Known Operational Gaps

- No public/admin UI.
- No `segment_submissions`.
- No external search worker.
- No membership candidates.
- No user-facing concept pages.
- No user-facing evidence API.
- No production writer workflow for formal concept links or membership tables yet.
- No automatic backfill of historical routes/segments into cognition tables.
- `route_segments` can explain composition, but the live product still needs future code before users can see or edit that explanation.

## 8. Final Validation Summary

Latest focused Step D pytest:

```bash
pytest tests/test_route_cognition_membership_formal_tables.py -q
```

Result:

- `25 passed, 7 warnings`

Latest regression pytest:

```bash
pytest tests/test_route_cognition_concept_formal_links.py \
       tests/test_route_cognition_concept_relationship_candidates.py \
       tests/test_route_cognition_concept_nodes.py \
       tests/test_route_cognition_batch7.py \
       tests/test_route_cognition_batch4.py \
       tests/test_route_cognition_batch5.py \
       tests/test_route_cognition_segment_eligibility_service.py \
       tests/test_route_guides_api.py \
       tests/test_route_export_foundation.py \
       tests/test_route_cognition_membership_formal_tables.py -q
```

Result:

- `274 passed, 26 warnings`

Latest PostgreSQL migration round-trip:

```bash
alembic upgrade head
alembic downgrade -1
alembic upgrade head
```

Result on temporary PostGIS PostgreSQL:

- Upgrade to head succeeded.
- Downgrade from `20260618_membership_formal` to `20260618_concept_formal_links` succeeded.
- Upgrade back to `20260618_membership_formal` succeeded.
- Final `alembic_version`: `20260618_membership_formal`.
- `route_segments` count: `0`.
- `collection_routes` count: `0`.
- `collection_segments` count: `0`.

Forbidden scope checks:

- Step D commit `2d29baa1` changed only:
  - `app/route_cognition/models.py`
  - `docs/research/route_cognition_v1_1_status.md`
  - `migrations/versions/20260618_membership_formal.py`
  - `tests/test_route_cognition_membership_formal_tables.py`
- No `route_segment_candidates`, `collection_route_candidates`, `collection_segment_candidates`, or `segment_submissions` table definitions exist in `app/` or `migrations/versions/`.
- Grep hits for forbidden names are limited to tests/documentation that assert those items are not implemented, plus pre-existing route-book routers unrelated to Step D.
- No `content/routes/**`, `guide.md`, or `route_guides.content_md` content was changed by Step D.

## 9. Completion Statement

route cognition v1.1 DB foundation is complete.
