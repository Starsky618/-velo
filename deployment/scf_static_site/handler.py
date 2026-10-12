"""Read-only VELO static routing shared with the native SCF Web transport."""

import base64
import gzip
import hashlib
import re
from pathlib import Path
from urllib.parse import quote, unquote, urlencode

WEBSITE_ROOT = Path(__file__).resolve().parent / "website"
CANONICAL_ORIGIN = "https://weiluai.top"
MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/plain; charset=utf-8",
    ".xml": "application/xml; charset=utf-8",
    ".svg": "image/svg+xml",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ico": "image/x-icon",
    ".webp": "image/webp",
}
TEXT_SUFFIXES = {".html", ".css", ".js", ".json", ".txt", ".md", ".xml", ".svg"}
SECURITY_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": (
        "default-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob: https://tiles.openfreemap.org; "
        "font-src 'self'; script-src 'self'; worker-src 'self' blob:; "
        "connect-src 'self' https://tiles.openfreemap.org "
        "https://valhalla1.openstreetmap.de https://api.weiluai.top; "
        "object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'none'"
    ),
}


def _response(status, payload=b"", *, headers=None, binary=False, head=False):
    response_headers = {**SECURITY_HEADERS, **(headers or {})}
    if status != 304:
        response_headers["Content-Length"] = str(len(payload))
    return {
        "statusCode": status,
        "headers": response_headers,
        "isBase64Encoded": binary and not head and bool(payload),
        "body": "" if head else (
            base64.b64encode(payload).decode("ascii") if binary else payload.decode("utf-8")
        ),
    }


def _request_path(raw):
    if not isinstance(raw, str) or not raw.startswith("/") or raw.startswith("//"):
        raise ValueError("invalid path")
    if re.search(r"%(?![0-9a-fA-F]{2})", raw):
        raise ValueError("invalid encoding")
    path = unquote(raw, encoding="utf-8", errors="strict")
    # Do not normalize away traversal, accept backslashes, or decode twice.
    if any(ord(c) < 32 or ord(c) == 127 for c in path) or any(c in path for c in "\\%?#"):
        raise ValueError("invalid path")
    parts = path.split("/")[1:]
    if any(part.startswith(".") for part in parts) or "" in parts[:-1]:
        raise ValueError("hidden or ambiguous path")
    if parts[0].lower() in {"uploads", "backups"}:
        raise ValueError("private directory")
    return path


def _site_file(path):
    root = WEBSITE_ROOT
    if root.is_symlink():
        return None
    candidate = root
    for part in path.strip("/").split("/"):
        if part:
            candidate = candidate / part
            if candidate.is_symlink():
                return None
    try:
        candidate.resolve().relative_to(root.resolve())
        return candidate if candidate.is_file() else None
    except (OSError, ValueError, RuntimeError):
        return None


def _query_suffix(event):
    # Function URL supplies queryString as an object, not a raw URL string.
    query = event.get("queryString", {})
    if not isinstance(query, dict) or any(
        not isinstance(key, str) or not isinstance(value, str) for key, value in query.items()
    ):
        raise ValueError("invalid queryString")
    return "?" + urlencode(query) if query else ""


def _accepts_gzip(value):
    qualities = {}
    for item in value.lower().split(","):
        coding, *parameters = item.strip().split(";")
        quality = 1.0
        for parameter in parameters:
            if parameter.strip().startswith("q="):
                try:
                    quality = float(parameter.strip()[2:])
                except ValueError:
                    quality = 0.0
        qualities[coding] = quality
    return 0 < qualities.get("gzip", qualities.get("*", 0)) <= 1


def _serve_file(file, status, request_headers, head):
    payload = file.read_bytes()
    suffix = file.suffix.lower()
    binary = suffix not in TEXT_SUFFIXES
    headers = {"Content-Type": MIME_TYPES.get(suffix, "application/octet-stream")}
    if not binary:
        headers["Vary"] = "Accept-Encoding"
        if len(payload) >= 1024 and _accepts_gzip(request_headers.get("accept-encoding", "")):
            payload = gzip.compress(payload, compresslevel=6, mtime=0)
            headers["Content-Encoding"] = "gzip"
            binary = True
    etag = '"' + hashlib.sha256(payload).hexdigest() + '"'
    headers["ETag"] = etag
    validators = [value.strip().removeprefix("W/") for value in request_headers.get("if-none-match", "").split(",")]
    if status == 200 and (etag in validators or "*" in validators):
        return _response(304, headers=headers)
    return _response(status, payload, headers=headers, binary=binary, head=head)


def main_handler(event, context):
    """Transport-neutral routing; no API, database, or environment lookup."""
    if not isinstance(event, dict):
        return _response(400, b"Bad Request\n", headers={"Content-Type": "text/plain; charset=utf-8"})
    method = event.get("httpMethod")
    head = method == "HEAD"
    if not isinstance(method, str) or method not in {"GET", "HEAD"}:
        return _response(405, b"Method Not Allowed\n", headers={
            "Allow": "GET, HEAD", "Content-Type": "text/plain; charset=utf-8",
        })
    try:
        headers = event.get("headers", {})
        if not isinstance(headers, dict) or any(
            not isinstance(k, str) or not isinstance(v, str) for k, v in headers.items()
        ):
            raise ValueError("invalid headers")
        headers = {k.lower(): v for k, v in headers.items()}
        path = _request_path(event.get("path"))
        query = _query_suffix(event)
    except (ValueError, UnicodeError):
        return _response(400, b"Bad Request\n", headers={"Content-Type": "text/plain; charset=utf-8"}, head=head)

    url_path = quote(path, safe="/!$&'()*+,;=:@-._~")
    # Function URL identifies the original domain here and may omit Host.
    # Prefer its domain even when a different Host is also present.
    request_domain = headers.get("x-scf-request-domain", headers.get("host", ""))
    host = request_domain.lower().split(":", 1)[0].rstrip(".")
    if host == "www.weiluai.top":
        return _response(301, headers={"Location": CANONICAL_ORIGIN + url_path + query}, head=head)

    file = _site_file(path)
    if file and path.endswith("/"):
        file = None
    if not file:
        index = _site_file(path.rstrip("/") + "/index.html")
        if index:
            if not path.endswith("/"):
                return _response(308, headers={"Location": url_path + "/" + query}, head=head)
            file = index
    if file:
        return _serve_file(file, 200, headers, head)
    error_page = _site_file("/404.html")
    if error_page:
        return _serve_file(error_page, 404, headers, head)
    return _response(404, b"Not Found\n", headers={"Content-Type": "text/plain; charset=utf-8"}, head=head)
