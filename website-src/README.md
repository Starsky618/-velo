# VELO public website source

This is the user-approved landing page from local preview commit 5af70a3.

Build with Node 22+: `npm ci && npm run build` from this directory. Vite writes hashed client assets into `../website/`, and `prerender.mjs` renders the React page to its root HTML for crawlable content. The browser hydrates that markup. Existing company/privacy/English/404/verification pages remain untouched. Images, the map style and public source catalog are retained in `../website/assets/` and `../website/data/`; only build output is public, source and QA are not.

Production Caddy permits same-origin scripts, blob WebGL workers, inline runtime styles, and map connections/images to tiles.openfreemap.org and valhalla1.openstreetmap.de, plus the VELO API for its public GLO-30 preview. It keeps the current standalone website root, denied uploads, true unknown-path 404, and www redirect. No SPA catch-all is used. The bounded public elevation endpoint is documented in the release note.

The map has 121 complete public Strava records with 55 display representatives; full origins remain searchable. The all-day trip is an explicit 76.7km illustrative out-and-back with GPX/HTML export. The exact user-provided TYY7 introduction and seven photos are retained without additional notes in that chapter. Paid access is introduced through the user-confirmed community contact; this brochure does not implement payment or live AI planning.

The intended complete 清徐夜骑线 and whole 汾河 cycleway mappings remain pending; the available river entry explicitly says 南段. Do not replace missing source data with legacy GPX. Other design decisions and current proof: docs/website-release-20260911.md.

Hand drawing supports retaining the raw line, optional OSM bicycle routing in this web demo, the existing GLO-30 elevation factory, and GPX with point-aligned height. Products use Tencent for road snapping; the web demo explicitly names OSM. The typography is local Noto Sans SC regular and medium, with OFL license retained.
