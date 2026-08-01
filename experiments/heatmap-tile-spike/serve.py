from __future__ import annotations

import argparse
from collections import OrderedDict
from io import BytesIO
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import importlib
import json
import os
from pathlib import Path
import re
import ssl
import sys
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from PIL import Image, ImageFilter


_TILE_PATH = re.compile(
    r"^/(fallback-tiles|live-tiles)/([A-Za-z0-9_-]+)/"
    r"(\d+)/(\d+)/(\d+)\.png$"
)
_FALLBACK_CACHE_MAX_ITEMS = 512


def parse_tile_path(path: str) -> tuple[str, str, int, int, int] | None:
    match = _TILE_PATH.fullmatch(urlsplit(path).path)
    if match is None:
        return None
    kind, version, zoom_text, x_text, y_text = match.groups()
    zoom, x, y = int(zoom_text), int(x_text), int(y_text)
    if not 0 <= zoom <= 22:
        return None
    tile_count = 1 << zoom
    if not (0 <= x < tile_count and 0 <= y < tile_count):
        return None
    return kind, version, zoom, x, y


def tile_path(root: Path, version: str, zoom: int, x: int, y: int) -> Path:
    return root / "tiles" / version / str(zoom) / str(x) / f"{y}.png"


def render_parent_fallback(
    root: Path,
    version: str,
    zoom: int,
    x: int,
    y: int,
    *,
    min_zoom: int,
) -> bytes | None:
    """裁切最近的已生成父瓦片，让高倍率等待细节时始终保留旧红线。"""
    for parent_zoom in range(zoom, min_zoom - 1, -1):
        delta = zoom - parent_zoom
        scale = 1 << delta
        parent_x = x // scale
        parent_y = y // scale
        candidate = tile_path(root, version, parent_zoom, parent_x, parent_y)
        if not candidate.is_file():
            continue
        payload = candidate.read_bytes()
        if delta == 0:
            return payload
        with Image.open(BytesIO(payload)) as source:
            rgba = source.convert("RGBA")
            width, height = rgba.size
            relative_x = x - parent_x * scale
            relative_y = y - parent_y * scale
            left = relative_x * width / scale
            upper = relative_y * height / scale
            right = (relative_x + 1) * width / scale
            lower = (relative_y + 1) * height / scale
            cropped = rgba.crop((left, upper, right, lower)).resize(
                (width, height),
                Image.Resampling.BILINEAR,
            )
            # 直接放大父瓦片会把 3px 红线放成 12–24px 色块。对 alpha 做等比例
            # 腐蚀，只把它当“细节未到前的稳定占位线”，真实子瓦片随后叠在上面。
            # BILINEAR 会在两侧再产生约半个父像素的软边，按 4 倍而不是
            # 原始 3px 线宽收缩，最终占位线保持在约 3–6px。
            erosion_size = 4 * (scale - 1) + 1
            if erosion_size % 2 == 0:
                erosion_size += 1
            if erosion_size > 1:
                cropped.putalpha(
                    cropped.getchannel("A").filter(
                        ImageFilter.MinFilter(erosion_size)
                    )
                )
        output = BytesIO()
        cropped.save(output, format="PNG", optimize=True)
        return output.getvalue()
    return None


def local_qa_token(api: str) -> str:
    request = Request(
        f"{api.rstrip('/')}/api/user/login",
        data=json.dumps({"code": "heatmap-tile-spike"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=15) as response:
        return str(json.loads(response.read())["token"])


def fetch_live_tile(api: str, token: str, zoom: int, x: int, y: int) -> bytes:
    request = Request(
        f"{api.rstrip('/')}/api/user/me/heatmap/tiles/{zoom}/{x}/{y}.png"
        "?color=red&v=spike",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urlopen(request, timeout=90) as response:
        return response.read()


def load_tencent_key(config_root: Path) -> str:
    original_cwd = Path.cwd()
    original_path = list(sys.path)
    try:
        os.chdir(config_root)
        sys.path.insert(0, str(config_root))
        sys.modules.pop("app.config", None)
        sys.modules.pop("app", None)
        settings = importlib.import_module("app.config").settings
        return str(settings.TENCENT_MAP_KEY or "")
    finally:
        os.chdir(original_cwd)
        sys.path[:] = original_path


def handler_for(
    root: Path,
    tencent_key: str,
    *,
    api: str | None = None,
    api_token: str | None = None,
):
    fallback_cache: OrderedDict[tuple[str, int, int, int], bytes] = OrderedDict()
    fallback_cache_lock = Lock()
    tile_locks: dict[Path, Lock] = {}
    tile_locks_guard = Lock()

    def cached_fallback(version: str, zoom: int, x: int, y: int) -> bytes | None:
        key = (version, zoom, x, y)
        with fallback_cache_lock:
            payload = fallback_cache.get(key)
            if payload is not None:
                fallback_cache.move_to_end(key)
                return payload
        payload = render_parent_fallback(
            root,
            version,
            zoom,
            x,
            y,
            min_zoom=0,
        )
        if payload is None:
            return None
        with fallback_cache_lock:
            fallback_cache[key] = payload
            fallback_cache.move_to_end(key)
            while len(fallback_cache) > _FALLBACK_CACHE_MAX_ITEMS:
                fallback_cache.popitem(last=False)
        return payload

    class SpikeHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(root), **kwargs)

        def do_GET(self):
            clean_path = urlsplit(self.path).path
            if clean_path in ("/", "/index.html"):
                source = (root / "index.html").read_text(encoding="utf-8")
                script_url = (
                    "https://map.qq.com/api/gljs?v=1.exp&key=" + tencent_key
                )
                source = source.replace(
                    "<!-- TENCENT_MAP_SCRIPT -->",
                    '<script src=' + json.dumps(script_url) + '></script>',
                )
                payload = source.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(payload)
                return
            tile_request = parse_tile_path(self.path)
            if tile_request is not None:
                kind, version, zoom, x, y = tile_request
                if kind == "fallback-tiles":
                    payload = cached_fallback(version, zoom, x, y)
                else:
                    candidate = tile_path(root, version, zoom, x, y)
                    payload = candidate.read_bytes() if candidate.is_file() else None
                    if payload is None and api is not None and api_token is not None:
                        with tile_locks_guard:
                            tile_lock = tile_locks.setdefault(candidate, Lock())
                        with tile_lock:
                            if candidate.is_file():
                                payload = candidate.read_bytes()
                            else:
                                try:
                                    payload = fetch_live_tile(
                                        api, api_token, zoom, x, y
                                    )
                                    candidate.parent.mkdir(parents=True, exist_ok=True)
                                    temporary = candidate.with_suffix(".png.part")
                                    temporary.write_bytes(payload)
                                    os.replace(temporary, candidate)
                                except (HTTPError, URLError, TimeoutError, OSError):
                                    payload = None
                if payload is None:
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                try:
                    self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError):
                    # 地图快速移动时会主动取消上一帧瓦片；不是服务端失败。
                    pass
                return
            if self.path.startswith("/tiles/"):
                candidate = (root / self.path.lstrip("/").split("?", 1)[0]).resolve()
                if not candidate.is_file() or root not in candidate.parents:
                    # 透明 200 会让地图把仍可用的父级瓦片替换成“成功加载的空图”。
                    # 明确 404，生产层才能保留父瓦片或记录预生成遗漏。
                    self.send_error(404, "heatmap tile was not pre-generated")
                    return
            super().do_GET()

        def log_message(self, format, *args):
            if not (
                self.path.startswith("/tiles/")
                or self.path.startswith("/fallback-tiles/")
                or self.path.startswith("/live-tiles/")
            ):
                super().log_message(format, *args)

    return SpikeHandler


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the disposable heatmap tile spike")
    parser.add_argument("--config-root", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument(
        "--api",
        help="optional local QA API used to lazily fill high-zoom detail tiles",
    )
    parser.add_argument("--certfile", type=Path)
    parser.add_argument("--keyfile", type=Path)
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    key = load_tencent_key(args.config_root.resolve())
    if not key:
        raise SystemExit("TENCENT_MAP_KEY is not configured in the selected config root")
    api_token = local_qa_token(args.api) if args.api else None
    server = ThreadingHTTPServer(
        (args.host, args.port),
        handler_for(root, key, api=args.api, api_token=api_token),
    )
    scheme = "http"
    if args.certfile or args.keyfile:
        if not args.certfile or not args.keyfile:
            raise SystemExit("--certfile and --keyfile must be provided together")
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(args.certfile, args.keyfile)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        scheme = "https"
    print(f"heatmap tile spike: {scheme}://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
