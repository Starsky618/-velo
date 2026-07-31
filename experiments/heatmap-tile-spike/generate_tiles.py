from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.request import Request, urlopen

DEFAULT_API = "http://127.0.0.1:18001"
DEFAULT_MAP_CENTER = {"longitude": 112.5562942, "latitude": 37.8505264}


def request_bytes(url: str, token: str | None = None, body: dict | None = None) -> bytes:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    encoded = json.dumps(body).encode() if body is not None else None
    with urlopen(Request(url, data=encoded, headers=headers), timeout=90) as response:
        return response.read()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate every raster tile touched by the QA user's raw tracks"
    )
    parser.add_argument("--api", default=DEFAULT_API)
    parser.add_argument("--min-zoom", type=int, default=11)
    parser.add_argument("--max-zoom", type=int, default=18)
    parser.add_argument(
        "--generate-max-zoom",
        type=int,
        default=15,
        help="eagerly persist this zoom and below; higher zooms use parent fallback + lazy detail",
    )
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--max-tiles", type=int, default=100_000)
    parser.add_argument(
        "--manifest-only",
        action="store_true",
        help="print the track-driven tile counts without downloading PNG files",
    )
    args = parser.parse_args()
    if not args.min_zoom <= args.generate_max_zoom <= args.max_zoom:
        raise SystemExit("--generate-max-zoom must be inside min/max zoom")

    root = Path(__file__).resolve().parent

    login = json.loads(request_bytes(
        f"{args.api}/api/user/login",
        body={"code": "heatmap-tile-spike"},
    ))
    token = login["token"]
    manifest_payload = json.loads(request_bytes(
        f"{args.api}/api/user/me/heatmap/tiles/manifest"
        f"?min_zoom={args.min_zoom}&max_zoom={args.max_zoom}",
        token=token,
    ))
    tile_count = int(manifest_payload["tile_count"])
    if tile_count > args.max_tiles:
        raise SystemExit(
            f"manifest contains {tile_count} tiles, above --max-tiles={args.max_tiles}"
        )
    center = manifest_payload.get("center") or DEFAULT_MAP_CENTER
    cache_version = str(manifest_payload["cache_version"])
    tile_root = root / "tiles" / cache_version
    tile_root.mkdir(parents=True, exist_ok=True)

    jobs: list[tuple[int, int, int, Path]] = []
    for zoom_text, coordinates in manifest_payload["tiles"].items():
        zoom = int(zoom_text)
        if zoom > args.generate_max_zoom:
            continue
        for x, y in coordinates:
            output = tile_root / str(zoom) / str(x) / f"{y}.png"
            jobs.append((zoom, int(x), int(y), output))

    if args.manifest_only:
        print(json.dumps({
            "tile_count": len(jobs),
            "tile_counts": {
                zoom: len(coordinates)
                for zoom, coordinates in manifest_payload["tiles"].items()
            },
            "generation": manifest_payload["generation"],
            "cache_version": cache_version,
        }, ensure_ascii=False), flush=True)
        return

    def download(job: tuple[int, int, int, Path]) -> Path:
        zoom, x, y, output = job
        if output.is_file():
            return output
        output.parent.mkdir(parents=True, exist_ok=True)
        payload = request_bytes(
            f"{args.api}/api/user/me/heatmap/tiles/{zoom}/{x}/{y}.png?color=red&v=spike",
            token=token,
        )
        output.write_bytes(payload)
        return output

    completed = 0
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = [executor.submit(download, job) for job in jobs]
        for future in as_completed(futures):
            future.result()
            completed += 1
            if completed % 20 == 0 or completed == len(jobs):
                print(f"generated {completed}/{len(jobs)} tiles", flush=True)

    manifest = {
        "center": center,
        "initial_zoom": 13,
        "min_zoom": args.min_zoom,
        "max_zoom": args.max_zoom,
        "fallback_max_zoom": args.generate_max_zoom,
        "tile_count": len(jobs),
        "full_tile_count": tile_count,
        "generated_tile_counts": {
            zoom: len(coordinates)
            for zoom, coordinates in manifest_payload["tiles"].items()
            if int(zoom) <= args.generate_max_zoom
        },
        "full_tile_counts": {
            zoom: len(coordinates)
            for zoom, coordinates in manifest_payload["tiles"].items()
        },
        "generation": manifest_payload["generation"],
        "cache_version": cache_version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
