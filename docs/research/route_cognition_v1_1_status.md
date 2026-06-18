# Route Cognition v1.1 Implementation Status

## Active batch

Batch 6: segment eligibility internal write workflow

- No new migration expected.
- No public API.
- No admin UI.
- No automatic backfill.
- Admission only through internal service.

## Completed batches

- Batch 1: route_books + route_versions
  - migration: `migrations/versions/20260618_route_versions.py`
  - commit: `f6814026` route versions batch 1
  - notes:
    - `route_books` now carries `visibility`, `publish_status`, `updated_at`, `line_hash`, `elevation_profile`, and `current_version_id`.
    - `route_versions` is the geometry / navigation snapshot table.
    - Official route backfill is `public/published`; non-official route backfill is `private/draft`.
    - Route book creation and route guide import both create initial v1 route versions.

- Batch 2: route_guides provenance
  - migration: `migrations/versions/20260618_route_guides_provenance.py`
  - commit: `a374217c` route cognition schema foundation
  - notes:
    - `route_guides` now carries import provenance fields: `source_ref`, `content_hash`, `imported_at`, `source_route_version_id`, and `content_origin`.
    - `content_origin` is limited to `content_routes_import` and `legacy_import`.
    - `source_route_version_id` points to the current route version when a guide is bound to a route book.

- Batch 3: route export foundation
  - migration: `migrations/versions/20260618_route_exports.py`
  - commit: `a374217c` route cognition schema foundation
  - notes:
    - `route_export_jobs` records who requested which `route_version_id` in `gpx` / `tcx` format.
    - `route_export_artifacts` stores the backend-only `file_id` for generated export files.
    - Both tables bind `(route_version_id, route_book_id)` back to `route_versions` so exports cannot drift away from the actual route snapshot.
    - `route_share_links` is deferred because `unlisted` is not currently exposed as a user-facing sharing/download surface.

- Batch 4: judgment ledger + external research loop
  - migration: `migrations/versions/20260618_route_cognition_batch4.py`
  - commit: `a374217c` route cognition schema foundation
  - notes:
    - Added `judgment_runs`, `evidence_items`, `judgment_run_evidence`, `research_questions`, and `research_runs`.
    - Added `route_guides.source_judgment_run_id` as a nullable pointer to the source judgment run.
    - Evidence defaults to internal storage; user-facing APIs still do not read `evidence_items` directly.
    - Research starts from `research_questions`; there is no free-form external crawl worker in this batch.

- Batch 5: segment geometry provenance + route cognition segment whitelist
  - migration: `migrations/versions/20260618_route_cognition_batch5.py`
  - commit: `b623b555` route cognition batch5 segment eligibility foundation
  - notes:
    - Added `segment_geometry_sources` for real segment geometry provenance.
    - Added `route_cognition_segments` as the 0..1 formal segment whitelist for route cognition.
    - `route_cognition_segments` is not a review queue; segments that are rejected, blocked, or still under review stay out of this table.
    - Existing `segments` are not backfilled into the whitelist automatically.
    - Existing `segments` do not receive fake geometry sources.
    - `legacy_reviewed` whitelist rows keep `primary_geometry_source_id` as `NULL` and do not create `segment_geometry_sources` rows.
    - `provenance_verified` whitelist rows must point to a matching `segment_geometry_sources` row with the same `segment_id` and `geometry_hash`.
    - Every whitelist row must point to a `judgment_runs` record; the future service/admin writer must choose an accepted same-segment judgment run.

## Accepted architecture decisions

- `route_books` is route identity.
- `route_versions` is geometry truth.
- `route_books.reference_line` is current version projection.
- `route_export_jobs` / `route_export_artifacts` reference `route_version_id`, not just `route_book_id`.
- Export artifact `file_id` is internal only; any future download must go through backend permission checks.
- v1 export formats are only `gpx` and `tcx`.
- FIT, platform sync, and course points remain future hooks.
- `route_guides.content_md` is an import-only read model.
- `content/routes/**/guide.md` is the user-facing content source.
- `judgment_runs` records structured judgment summaries, not full model chain-of-thought.
- `evidence_items` stores only evidence actually used by a judgment run; it is not a general knowledge store.
- `research_questions` is the required reason for future external research.
- `route_guides.source_judgment_run_id` is optional and is not backfilled automatically.
- Old segments enter later via `route_cognition_segments` with `legacy_reviewed`.
- `segment_geometry_sources` only records real provenance; there is no `legacy_existing` / `unknown` source type.
- `route_cognition_segments` is a whitelist subset of `segments`, not a one-to-one mirror.
- Future route / collection / concept links should target `route_cognition_segments.segment_id`, not raw `segments.id`.
- Future formal relationships must reference `route_cognition_segments.segment_id`; they must not bypass the whitelist through raw `segments.id`.
- Private personal segments and `segment_submissions` are not implemented in Batch 5.
- AI never writes formal relationships directly.
- Concept is a first-version target but not Batch 2.

## Batch 2 scope

- Add route_guides provenance fields.
- Update `scripts/import_route_guides.py`.
- Do not modify `content/routes/**` assets.

## Batch 2 must not do

- No CMS.
- No `route_content_claims`.
- No judgment / research / evidence tables.
- No concept tables.
- No candidate tables.
- No export tables.

## Batch 2 implementation notes

- `source_ref` comes from `content/routes/**/meta.json`.
- `content_hash` is the SHA-256 of `route_guides.content_md`.
- `imported_at` is only set by real imports; migration leaves old rows as `NULL`.
- `content_origin` starts with only `content_routes_import` and `legacy_import`.
- `source_route_version_id` points to the current route version when a guide is bound to a route book.
- `source_judgment_run_id` is deferred until judgment tables exist.

## Batch 3 scope

- Add `route_export_jobs`.
- Add `route_export_artifacts`.
- Add route export/download permission helpers.
- Do not expose direct public URLs for exported artifacts.

## Batch 3 must not do

- No `route_share_links` until unlisted sharing/download is explicitly opened.
- No FIT export enum/check.
- No platform OAuth or deep sync.
- No course points generation.
- No judgment / research / concept / candidate / segment provenance tables.
- No rewrite of `content/routes/**`.

## Batch 3 implementation notes

- Owners can export their own private/draft routes.
- Admins can export any route.
- Non-owner logged-in users can export `public/published` routes.
- Non-owner `unlisted` export requires a future share link with `can_export=True`; without that, it is denied.
- Export artifact download is restricted to admin or the job requester; route owners create their own export jobs if they need a file.

## Batch 4 scope

- Add a structured judgment ledger.
- Add evidence records that are tied to judgment runs.
- Add research questions and research runs as the foundation for external research.
- Add the optional `route_guides.source_judgment_run_id` provenance pointer.

## Batch 4 must not do

- No candidate tables.
- No formal relationship tables or hard gate.
- No concept tables.
- No route collection tables.
- No segment provenance tables.
- No CMS, pgvector, or `route_content_claims`.
- No external search worker.
- No user-facing evidence API.

## Batch 4 implementation notes

- `app/route_cognition/models.py` owns the five new ORM models.
- `migrations/env.py` imports `app.route_cognition.models` so Alembic sees the new tables.
- JSON fields use PostgreSQL JSONB in the real models and migration.
- Circular references from `research_questions` to `research_runs` / `evidence_items` are added after all tables exist.
- `evidence_items.fidelity_tier` convention: `1 = raw geometry / raw profile` (highest fidelity), `2 = structured metric`, `3 = image / screenshot`, `4 = UGC / web text`, `5 = model inference` (lowest fidelity).
- SQLite tests use explicit miniature tables for Batch 4 because SQLite does not support PostgreSQL JSONB/PostGIS in the same shape.

## Batch 4 acceptance SQL result

- `SELECT count(*) FROM judgment_runs;` -> `0`
- `SELECT count(*) FROM evidence_items;` -> `0`
- `SELECT count(*) FROM judgment_run_evidence;` -> `0`
- `SELECT count(*) FROM research_questions;` -> `0`
- `SELECT count(*) FROM research_runs;` -> `0`
- `SELECT evidence_type, count(*) FROM evidence_items GROUP BY evidence_type;` -> `[]`
- `SELECT display_policy, rights_status, count(*) FROM evidence_items GROUP BY display_policy, rights_status;` -> `[]`
- `SELECT status, count(*) FROM research_questions GROUP BY status;` -> `[]`
- `SELECT status, count(*) FROM research_runs GROUP BY status;` -> `[]`
- route/version mismatch query -> `0 rows`
- Note: results above were executed on an isolated empty verification database; real counts depend on the target database after migration.

## Batch 5 scope

- Add `segment_geometry_sources`.
- Add `route_cognition_segments`.
- Do not backfill old `segments`.
- Do not create fake provenance for old `segments`.
- Do not expose public APIs or admin UI.

## Batch 5 must not do

- No `segment_submissions`.
- No `route_collections`.
- No `route_segments` / `collection_segments` / `collection_routes`.
- No concept tables or formal relationship tables.
- No candidate tables.
- No external search worker.
- No user-facing evidence API.
- No rewrite of `content/routes/**`.
- No change to `route_guides.content_md`.
- No change to old `segments.reference_line` or `segment_efforts`.

## Batch 5 implementation notes

- `segment_geometry_sources.source_type` is limited to `activity_clip`, `gpx_upload`, `fit_upload`, and `admin_import`.
- `segment_geometry_sources.quality_status` is limited to `verified`, `needs_review`, `rejected`, and `deprecated`.
- `segment_geometry_sources.source_start_index` / `source_end_index` allow open-ended clips, but when both exist the start index must be strictly less than the end index.
- `segment_geometry_sources` requires a durable material pointer: `activity_clip` needs `source_content_hash`; `gpx_upload` / `fit_upload` / `admin_import` need at least one of `source_file_id`, `source_url`, or `source_content_hash`.
- `segment_geometry_sources.source_file_id` remains a string pointer without a foreign key until a real file table exists.
- `segment_geometry_sources.source_content_hash` remains nullable.
- `route_cognition_segments.review_basis` is limited to `provenance_verified` and `legacy_reviewed`.
- `route_cognition_segments.eligibility_status` is limited to `active`, `suspended`, and `deprecated`.
- `route_cognition_segments.reviewed_at` is required.
- `provenance_verified` requires `primary_geometry_source_id`.
- The database guarantees the source exists and has matching `segment_id` / `geometry_hash`; the future service/admin writer must choose a `segment_geometry_sources.quality_status = 'verified'` source before inserting `provenance_verified`.
- `legacy_reviewed` requires `primary_geometry_source_id IS NULL`.
- `(primary_geometry_source_id, segment_id)` references `segment_geometry_sources(id, segment_id)` without `ON DELETE SET NULL`.
- `(primary_geometry_source_id, segment_id, geometry_hash)` references `segment_geometry_sources(id, segment_id, geometry_hash)` without `ON DELETE SET NULL`.
- `UNIQUE(primary_geometry_source_id)` is retained so one geometry source cannot become the primary source for multiple whitelist rows.
- `accepted_judgment_run_id` references `judgment_runs.id` without `ON DELETE SET NULL`.

## Batch 5 acceptance SQL result

- `SELECT version_num FROM alembic_version;` -> `20260618_route_cognition_batch5`
- `SELECT count(*) FROM segment_geometry_sources;` -> `0`
- `SELECT count(*) FROM route_cognition_segments;` -> `0`
- `SELECT review_basis, eligibility_status, count(*) FROM route_cognition_segments GROUP BY review_basis, eligibility_status ORDER BY review_basis, eligibility_status;` -> `0 rows`
- `SELECT count(*) FROM route_cognition_segments WHERE review_basis = 'legacy_reviewed' AND primary_geometry_source_id IS NOT NULL;` -> `0`
- `SELECT count(*) FROM route_cognition_segments WHERE review_basis = 'provenance_verified' AND primary_geometry_source_id IS NULL;` -> `0`
- `SELECT count(*) FROM route_cognition_segments rcs JOIN segment_geometry_sources sgs ON rcs.primary_geometry_source_id = sgs.id WHERE rcs.primary_geometry_source_id IS NOT NULL AND rcs.segment_id <> sgs.segment_id;` -> `0`
- `SELECT count(*) FROM route_cognition_segments rcs LEFT JOIN judgment_runs jr ON rcs.accepted_judgment_run_id = jr.id WHERE jr.id IS NULL;` -> `0`
- automatic backfill check (`SELECT count(*) FROM route_cognition_segments;`) -> `0`
- Constraint definitions verified on isolated PostgreSQL:
  - `ck_route_cognition_segments_eligibility_status` -> `active` / `suspended` / `deprecated`
  - `ck_route_cognition_segments_required_review_fields` -> `reviewed_at IS NOT NULL`
  - `ck_segment_geometry_sources_quality_status` -> `verified` / `needs_review` / `rejected` / `deprecated`
  - `ck_segment_geometry_sources_index_order` -> `source_start_index < source_end_index`
  - `ck_segment_geometry_sources_material_pointer` -> durable material pointer required
  - `uq_segment_geometry_sources_id_segment_geometry_hash` -> `UNIQUE (id, segment_id, geometry_hash)`
  - `uq_route_cognition_segments_primary_source` -> `UNIQUE (primary_geometry_source_id)`
- FK delete actions on an isolated verification database:
  - `fk_route_cognition_segments_accepted_judgment` -> `NO ACTION`
  - `fk_route_cognition_segments_primary_source_geometry_hash` -> `NO ACTION`
  - `fk_route_cognition_segments_primary_source_segment` -> `NO ACTION`
  - `fk_route_cognition_segments_reviewed_by` -> `SET NULL`
  - `fk_route_cognition_segments_segment` -> `NO ACTION`
  - `fk_segment_geometry_sources_created_by` -> `SET NULL`
  - `fk_segment_geometry_sources_segment` -> `NO ACTION`
  - `fk_segment_geometry_sources_source_activity` -> `SET NULL`
- Note: results above were executed on an isolated temporary PostgreSQL database `velo_batch5_verify`; real counts depend on the target database after migration.

## Batch 6 scope

- Add an internal segment eligibility write workflow.
- Add `app/route_cognition/services/segment_eligibility.py`.
- Add deterministic segment geometry hash helper.
- Add focused service tests.
- Do not add a migration.
- Do not expose public APIs or admin UI.
- Do not automatically backfill old `segments`.

## Batch 6 must not do

- No `segment_submissions`.
- No `route_collections`.
- No `route_segments` / `collection_segments` / `collection_routes`.
- No concept tables or formal relationship tables.
- No candidate tables.
- No external search worker.
- No user-facing evidence API.
- No rewrite of `content/routes/**`.
- No change to `route_guides.content_md`.
- No change to old `segments.reference_line` or `segment_efforts`.

## Batch 6 implementation notes

- `admit_legacy_reviewed_segment` writes only `route_cognition_segments`; it does not create `segment_geometry_sources`.
- `admit_provenance_verified_segment` accepts only `segment_geometry_sources.quality_status = 'verified'`.
- Both admission paths require an accepted human review judgment run: `run_type = 'human_review'`, `status = 'succeeded'`, and `confidence_state IN ('human_accepted', 'stable')`.
- If `judgment_runs.segment_id` is set, it must match the target segment.
- Legacy admission computes a segment geometry hash from the existing `segments.reference_line`.
- Provenance admission copies `geometry_hash` and `normalization_version` from the verified source.
- Provenance admission also requires the source `geometry_hash` to match the current `segments.reference_line` hash.
- Existing or newly created provenance sources must satisfy the Batch 5 durable material pointer rule.
- `accepted_judgment_run_id` is the authoritative audit pointer; `review_note` is recommended context, not the source of truth.
- The service flushes changes but does not commit; callers own the transaction boundary.

## Open issues

- Candidate tables are not built yet.
- Formal relationship hard gate is not built yet.
- Segment submissions are not built yet.
- Route collection tables are not built yet.
- Concept tables are not built yet.
- External search worker is not implemented.
- Evidence is internal-only storage for now; there is no user-facing evidence API.
- `route_share_links` decision when unlisted sharing/download opens.
- Actual GPX/TCX generation worker is deferred until the export pipeline batch.
- `normalization_version` should eventually be tied to the canonical geometry hash helper version.
- Shared line hash helper should eventually move out of `app.route_book.service._line_hash` into a neutral utility.

## Superseded docs

- `docs/research/route_cognition_schema_FINAL.md`
