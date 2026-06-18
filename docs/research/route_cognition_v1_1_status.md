# Route Cognition v1.1 Implementation Status

## Active batch

Batch 4: judgment ledger + external research loop

## Completed batches

- Batch 1: route_books + route_versions
  - migration: `migrations/versions/20260618_route_versions.py`
  - commit: pending / current workspace
  - notes:
    - `route_books` now carries `visibility`, `publish_status`, `updated_at`, `line_hash`, `elevation_profile`, and `current_version_id`.
    - `route_versions` is the geometry / navigation snapshot table.
    - Official route backfill is `public/published`; non-official route backfill is `private/draft`.
    - Route book creation and route guide import both create initial v1 route versions.

- Batch 2: route_guides provenance
  - migration: `migrations/versions/20260618_route_guides_provenance.py`
  - commit: pending / current workspace
  - notes:
    - `route_guides` now carries import provenance fields: `source_ref`, `content_hash`, `imported_at`, `source_route_version_id`, and `content_origin`.
    - `content_origin` is limited to `content_routes_import` and `legacy_import`.
    - `source_route_version_id` points to the current route version when a guide is bound to a route book.

- Batch 3: route export foundation
  - migration: `migrations/versions/20260618_route_exports.py`
  - commit: pending / current workspace
  - notes:
    - `route_export_jobs` records who requested which `route_version_id` in `gpx` / `tcx` format.
    - `route_export_artifacts` stores the backend-only `file_id` for generated export files.
    - Both tables bind `(route_version_id, route_book_id)` back to `route_versions` so exports cannot drift away from the actual route snapshot.
    - `route_share_links` is deferred because `unlisted` is not currently exposed as a user-facing sharing/download surface.

- Batch 4: judgment ledger + external research loop
  - migration: `migrations/versions/20260618_route_cognition_batch4.py`
  - commit: pending / current workspace
  - notes:
    - Added `judgment_runs`, `evidence_items`, `judgment_run_evidence`, `research_questions`, and `research_runs`.
    - Added `route_guides.source_judgment_run_id` as a nullable pointer to the source judgment run.
    - Evidence defaults to internal storage; user-facing APIs still do not read `evidence_items` directly.
    - Research starts from `research_questions`; there is no free-form external crawl worker in this batch.

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

## Open issues

- Candidate tables are not built yet.
- Formal relationship hard gate is not built yet.
- External search worker is not implemented.
- Evidence is internal-only storage for now; there is no user-facing evidence API.
- `route_share_links` decision when unlisted sharing/download opens.
- Actual GPX/TCX generation worker is deferred until the export pipeline batch.

## Superseded docs

- `docs/research/route_cognition_schema_FINAL.md`
