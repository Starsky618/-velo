# Personal heatmap raster-tile spike

This disposable spike tests a layered personal-heatmap delivery path: render
versioned PNG tiles in Tencent's WebGL map instead of feeding thousands of
dynamic polylines into the Mini Program native map.

## Local proof

- Corpus: the raw-track manifest contains 43,594 occupied tiles across zoom
  11-18. The eager base is only the 3,351 zoom 11-15 tiles; zoom 16-18 keeps a
  cropped parent tile visible while its real detail tile is fetched and
  persisted. Generated `tiles/` and `manifest.json` are ignored.
- Consistency: artifact paths include the heatmap cache version, so a new
  activity generation cannot silently reuse the previous corpus.
- Browser: 390 x 780 drag/zoom checks kept frame intervals around 16.7 ms P50
  and 17.6 ms P95 during 12 rapid cross-region/zoom changes, with no frames
  over 34 ms. A forced detail-layer failure still retained the red parent
  route instead of showing a blank or a successful transparent tile.
- WeChat Developer Tools: `urlCheck=false` bypassed the business-domain check,
  but the simulator rejected both plain HTTP and a self-signed local HTTPS
  certificate before the H5 page executed.

The three display layers are intentionally distinct:

1. the authenticated backend builds a track-driven manifest from continuous
   raw `Trackpoint` segments;
2. zoom 11-15 is eagerly generated as the always-available red base;
3. zoom 16-18 first overzooms the nearest parent and then overlays/persists the
   real raw-track child tile without clearing the base during the request.

Run the local browser proof from the repository root:

```sh
python3 experiments/heatmap-tile-spike/generate_tiles.py \
  --generate-max-zoom 15
python3 experiments/heatmap-tile-spike/serve.py \
  --config-root /Users/macbookair/Desktop/velo \
  --api http://127.0.0.1:18001
```

Open <http://127.0.0.1:18080>. The Tencent browser key is injected at runtime
from the selected VELO config root and is not written into this directory.

## Acceptance boundary

This is not yet the production cold-tile store. The local filesystem stands in
for private object storage, and the local server stands in for its HTTPS/CDN
origin. Before production integration, put the same versioned artifacts on a
registered HTTPS QA domain, keep owner authorization at the delivery edge, and
verify continuous pan/zoom on a real WeChat device. Do not treat browser proof
or a successful `/health` response as WeChat acceptance.
