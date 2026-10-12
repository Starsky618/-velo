"""Standalone static-function tests; no business DB or service fixtures required."""

import base64
import gzip
import hashlib
import http.client
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import select
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DEPLOYMENT = ROOT / "deployment/scf_static_site"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


handler = load_module("scf_static_handler", DEPLOYMENT / "handler.py")
builder = load_module("scf_static_build", DEPLOYMENT / "build.py")


def event(path="/", method="GET", headers=None, query=None):
    # Official Function URL shape: no API Gateway/AWS-only fields.
    return {"httpMethod": method, "path": path, "headers": {"x-scf-request-domain": "weiluai.top"} if headers is None else headers, "queryString": query or {}, "body": ""}


def body_bytes(response):
    body = response["body"]
    return base64.b64decode(body, validate=True) if response["isBase64Encoded"] else body.encode("utf-8")


class StaticFunctionTests(unittest.TestCase):
    def setUp(self):
        self.root_patch = patch.object(handler, "WEBSITE_ROOT", ROOT / "website")
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    def test_real_bilingual_pages_and_icp_are_unchanged(self):
        for path in ["/", "/en/", "/company/", "/en/company/", "/privacy/", "/en/privacy/", "/privacy/garmin/", "/en/privacy/garmin/"]:
            with self.subTest(path=path):
                response = handler.main_handler(event(path), None)
                self.assertEqual(response["statusCode"], 200)
                self.assertEqual(body_bytes(response), (ROOT / "website" / path.lstrip("/") / "index.html").read_bytes())
                self.assertIn("湘ICP备2026023052号-1", response["body"])
                self.assertEqual(response["headers"]["Content-Type"], "text/html; charset=utf-8")
                self.assertFalse(response["isBase64Encoded"])

    def test_every_real_asset_returns_exact_bytes_and_valid_envelope(self):
        for file in sorted((ROOT / "website").rglob("*")):
            if not file.is_file():
                continue
            with self.subTest(file=file):
                response = handler.main_handler(event("/" + file.relative_to(ROOT / "website").as_posix()), None)
                self.assertEqual(response["statusCode"], 200)
                self.assertEqual(body_bytes(response), file.read_bytes())
                self.assertEqual(set(response), {"statusCode", "headers", "body", "isBase64Encoded"})
                self.assertEqual(int(response["headers"]["Content-Length"]), file.stat().st_size)
                self.assertLess(len(json.dumps(response).encode()), 6_000_000)

    def test_binary_images_and_fonts_have_correct_mime_and_base64(self):
        for path, mime in [("/assets/huangcai.png", "image/png"), ("/assets/tianlong.jpg", "image/jpeg"), ("/assets/velo-editorial.woff", "font/woff")]:
            response = handler.main_handler(event(path), None)
            self.assertEqual(response["headers"]["Content-Type"], mime)
            self.assertTrue(response["isBase64Encoded"])

    def test_head_has_get_headers_without_body(self):
        for path in ["/", "/assets/huangcai.png", "/missing"]:
            for accept in ["identity", "gzip"]:
                request_headers = {"Accept-Encoding": accept}
                get = handler.main_handler(event(path, headers=request_headers), None)
                head = handler.main_handler(event(path, "HEAD", request_headers), None)
                self.assertEqual(head["statusCode"], get["statusCode"])
                self.assertEqual(head["headers"], get["headers"])
                self.assertEqual(head["body"], "")
                self.assertFalse(head["isBase64Encoded"])

    def test_www_redirect_preserves_path_and_query_values(self):
        for domain_header in ["X-Scf-Request-Domain", "Host"]:
            for method in ["GET", "HEAD"]:
                with self.subTest(domain_header=domain_header, method=method):
                    response = handler.main_handler(event(
                        "/privacy/garmin/", method=method,
                        headers={domain_header: "WWW.WEILUAI.TOP.:443"},
                        query={"from": "a b", "next": "/en/?a=b&c=1"},
                    ), None)
                    self.assertEqual(response["statusCode"], 301)
                    destination = urlsplit(response["headers"]["Location"])
                    self.assertEqual((destination.scheme, destination.netloc, destination.path), ("https", "weiluai.top", "/privacy/garmin/"))
                    self.assertEqual(parse_qs(destination.query), {"from": ["a b"], "next": ["/en/?a=b&c=1"]})
                    self.assertEqual(response["body"], "")

    def test_scf_domain_takes_precedence_over_host(self):
        cases = [
            ("www.weiluai.top", "weiluai.top", 301),
            ("weiluai.top", "www.weiluai.top", 200),
            ("123-example.ap-guangzhou.tencentscf.com", "www.weiluai.top", 200),
            ("www.weiluai.top.attacker.example", "www.weiluai.top", 200),
            ("", "www.weiluai.top", 200),
        ]
        for scf_domain, host, status in cases:
            with self.subTest(scf_domain=scf_domain, host=host):
                response = handler.main_handler(event(headers={
                    "x-scf-request-domain": scf_domain, "host": host,
                }), None)
                self.assertEqual(response["statusCode"], status)
                if status == 301:
                    self.assertEqual(response["headers"]["Location"], "https://weiluai.top/")
                else:
                    self.assertNotIn("Location", response["headers"])

    def test_www_redirect_is_not_triggered_by_forwarded_host_or_suffix(self):
        for headers in [
            {"x-scf-request-domain": "weiluai.top", "x-forwarded-host": "www.weiluai.top"},
            {"x-scf-request-domain": "www.weiluai.top.attacker.example"},
            {"host": "www.weiluai.top.attacker.example"},
            {"x-forwarded-host": "www.weiluai.top"},
            {},
        ]:
            self.assertEqual(handler.main_handler(event(headers=headers), None)["statusCode"], 200)

    def test_directory_canonical_redirect_and_index(self):
        for path in ["/company", "/privacy/garmin", "/en"]:
            response = handler.main_handler(event(path, query={"v": "1"}), None)
            self.assertEqual(response["statusCode"], 308)
            self.assertEqual(response["headers"]["Location"], path + "/?v=1")
            self.assertEqual(handler.main_handler(event(path + "/"), None)["statusCode"], 200)

    def test_missing_or_nonindexed_directory_uses_actual_404(self):
        expected = (ROOT / "website/404.html").read_bytes()
        for path in ["/not-found", "/assets/", "/robots.txt/", "/handler.py", "/deployment-manifest.json", "/api/health"]:
            response = handler.main_handler(event(path), None)
            self.assertEqual(response["statusCode"], 404, path)
            self.assertEqual(body_bytes(response), expected)

    def test_non_get_head_methods_are_405_on_both_hosts(self):
        for method in ["POST", "PUT", "DELETE", "PATCH", "OPTIONS", "TRACE", "get", None]:
            for host in ["weiluai.top", "www.weiluai.top"]:
                response = handler.main_handler(event(method=method, headers={"x-scf-request-domain": host}), None)
                self.assertEqual(response["statusCode"], 405)
                self.assertEqual(response["headers"]["Allow"], "GET, HEAD")

    def test_etag_revalidation_including_weak_lists_and_head(self):
        first = handler.main_handler(event(), None)
        etag = first["headers"]["ETag"]
        self.assertEqual(first["headers"]["Cache-Control"], "no-cache")
        for validator in [etag, "W/" + etag, '"different", W/' + etag, "*"]:
            for method in ["GET", "HEAD"]:
                response = handler.main_handler(event(method=method, headers={"If-None-Match": validator}), None)
                self.assertEqual(response["statusCode"], 304)
                self.assertEqual(response["body"], "")
                self.assertNotIn("Content-Length", response["headers"])
                self.assertEqual(response["headers"]["ETag"], etag)
        self.assertEqual(handler.main_handler(event(headers={"If-None-Match": '"stale"'}), None)["statusCode"], 200)

    def test_404_does_not_turn_into_304(self):
        etag = handler.main_handler(event("/missing"), None)["headers"]["ETag"]
        self.assertEqual(handler.main_handler(event("/missing", headers={"If-None-Match": etag}), None)["statusCode"], 404)

    def test_gzip_bytes_and_cache_variant(self):
        plain = handler.main_handler(event("/data/segments.json"), None)
        compressed = handler.main_handler(event("/data/segments.json", headers={"accept-encoding": "br, gzip;q=0.8"}), None)
        self.assertTrue(compressed["isBase64Encoded"])
        self.assertEqual(compressed["headers"]["Content-Encoding"], "gzip")
        self.assertEqual(gzip.decompress(body_bytes(compressed)), body_bytes(plain))
        self.assertLess(len(body_bytes(compressed)), len(body_bytes(plain)))
        self.assertEqual(compressed["headers"]["Vary"], "Accept-Encoding")
        self.assertNotEqual(compressed["headers"]["ETag"], plain["headers"]["ETag"])
        conditional = handler.main_handler(event("/data/segments.json", headers={"accept-encoding": "gzip", "if-none-match": compressed["headers"]["ETag"]}), None)
        self.assertEqual(conditional["statusCode"], 304)

    def test_disabled_gzip_is_respected(self):
        for value in ["br", "gzip;q=0", "*;q=1, gzip;q=0", "gzip;q=bad"]:
            response = handler.main_handler(event(headers={"accept-encoding": value}), None)
            self.assertNotIn("Content-Encoding", response["headers"])

    def test_safety_headers_match_existing_caddy_contract(self):
        caddy = (ROOT / "Caddyfile").read_text()
        for name, value in handler.main_handler(event(), None)["headers"].items():
            if name in handler.SECURITY_HEADERS:
                self.assertIn(f'{name} "{value}"', caddy)

    def test_traversal_hidden_and_malformed_paths_cannot_read_files(self):
        paths = ["/../.env", "/../uploads/activity.gpx", "/%2e%2e/uploads/activity.gpx", "/%252e%252e%252fuploads/a", "/.git/config", "/assets/.env", "/assets/../../Caddyfile", "/uploads/a", "/backups/a", "/assets\\..\\.env", "/%5c..%5c.env", "/%00", "/%0d%0aLocation:evil", "/%ff", "/%gg", "/%", "//evil.example/", "/assets//file", "index.html", "https://evil/", "/?x=y", "/#fragment"]
        for path in paths:
            with self.subTest(path=path):
                response = handler.main_handler(event(path), None)
                self.assertEqual(response["statusCode"], 400)
                self.assertEqual(response["body"], "Bad Request\n")

    def test_symlink_file_directory_and_root_are_not_served(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "website"
            root.mkdir()
            private = Path(temp) / "uploads"
            private.mkdir()
            (private / "secret.txt").write_text("PRIVATE")
            (root / "leak.txt").symlink_to(private / "secret.txt")
            (root / "leak").symlink_to(private, target_is_directory=True)
            (root / ".secret").write_text("PRIVATE")
            with patch.object(handler, "WEBSITE_ROOT", root):
                for path in ["/leak.txt", "/leak/secret.txt", "/.secret"]:
                    response = handler.main_handler(event(path), None)
                    self.assertIn(response["statusCode"], {400, 404})
                    self.assertNotIn("PRIVATE", response["body"])
            alias = Path(temp) / "alias"
            alias.symlink_to(private, target_is_directory=True)
            with patch.object(handler, "WEBSITE_ROOT", alias):
                self.assertEqual(handler.main_handler(event("/secret.txt"), None)["statusCode"], 404)

    def test_invalid_event_shape_does_not_fall_back_to_another_protocol(self):
        for malformed in [None, [], {}, {"requestContext": {"http": {"method": "GET"}}, "rawPath": "/"}, {"httpMethod": [], "path": "/"}, {"httpMethod": "GET", "path": "/", "headers": []}, {"httpMethod": "GET", "path": "/", "queryString": "x=1"}]:
            response = handler.main_handler(malformed, None)
            self.assertIn(response["statusCode"], {400, 405})


class ImmutableBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.repo = Path(cls.temp.name) / "repo"
        cls.repo.mkdir()
        cls.git("init", "-q")
        # Copy the exact tracked site from this checkout's commit, never its dirty files.
        cls.baseline = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"]).decode().strip()
        names = subprocess.check_output(["git", "-C", str(ROOT), "ls-tree", "-rz", "--name-only", cls.baseline, "--", "website"])
        for raw in names.split(b"\0"):
            if raw:
                name = raw.decode()
                target = cls.repo / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(subprocess.check_output(["git", "-C", str(ROOT), "show", cls.baseline + ":" + name]))
        for source_path, archive_name in builder.CODE_SOURCES.items():
            target = cls.repo / source_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((DEPLOYMENT / archive_name).read_bytes())
            target.chmod(0o755 if source_path == builder.BOOTSTRAP_SOURCE else 0o644)
        (cls.repo / ".env").write_text("PRIVATE_TEST=secret")
        (cls.repo / "uploads").mkdir()
        (cls.repo / "uploads/private.gpx").write_text("PRIVATE_TEST")
        cls.git("add", "--", "website", *builder.CODE_SOURCES, ".env", "uploads")
        cls.git("-c", "user.name=SCF Local Test", "-c", "user.email=scf-test@example.invalid", "commit", "-qm", "Isolated test fixture; not a release")
        cls.revision = cls.git("rev-parse", "HEAD").decode().strip()
        cls.package = Path(cls.temp.name) / "first.zip"
        cls.report = builder.build(cls.repo, cls.revision, cls.package)

    @classmethod
    def git(cls, *args):
        return subprocess.check_output(["git", "-C", str(cls.repo), *args], stderr=subprocess.PIPE)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_artifact_is_byte_reproducible_despite_dirty_worktree(self):
        (self.repo / "website/index.html").write_text("DIRTY WEBSITE")
        (self.repo / builder.HANDLER_SOURCE).write_text("DIRTY HANDLER")
        (self.repo / "website/untracked.txt").write_text("UNTRACKED")
        second = Path(self.temp.name) / "second.zip"
        builder.build(self.repo, self.revision, second)
        self.assertEqual(self.package.read_bytes(), second.read_bytes())

    def test_manifest_hashes_and_package_allowlist(self):
        with zipfile.ZipFile(self.package) as archive:
            self.assertEqual(archive.testzip(), None)
            names = set(archive.namelist())
            self.assertTrue(all(name in {*builder.CODE_SOURCES.values(), "deployment-manifest.json"} or name.startswith("website/") for name in names))
            self.assertFalse(any(".env" in name or "uploads" in name or ".git" in name for name in names))
            manifest = json.loads(archive.read("deployment-manifest.json"))
            self.assertEqual(manifest["source_revision"], self.revision)
            self.assertEqual({row["path"] for row in manifest["files"]}, names - {"deployment-manifest.json"})
            for row in manifest["files"]:
                self.assertEqual(hashlib.sha256(archive.read(row["path"])).hexdigest(), row["sha256"])
                self.assertEqual(len(archive.read(row["path"])), row["bytes"])
                self.assertEqual(archive.read(row["path"]), self.git("show", self.revision + ":" + row["source_path"]))
                self.assertEqual(row["mode"], "0755" if row["path"] == "scf_bootstrap" else "0644")
            for info in archive.infolist():
                self.assertEqual(info.date_time, (1980, 1, 1, 0, 0, 0))
                self.assertEqual(info.compress_type, zipfile.ZIP_STORED)
                self.assertEqual((info.external_attr >> 16) & 0o777, 0o755 if info.filename == "scf_bootstrap" else 0o644)
            self.assertEqual(manifest["function_type"], "Web")
            self.assertEqual(manifest["entry_point"], "scf_bootstrap")
            self.assertEqual(manifest["listen_address"], "0.0.0.0:9000")
            bootstrap = archive.read("scf_bootstrap")
            self.assertTrue(bootstrap.startswith(b"#!/bin/bash\n"))
            self.assertTrue(bootstrap.endswith(b"\n"))
            self.assertNotIn(b"\r", bootstrap)
            self.assertIn(b"exec /var/lang/python310/bin/python3.10 -B -u /var/user/http_server.py", bootstrap)
        sidecar = json.loads(self.package.with_suffix(".zip.manifest.json").read_text())
        self.assertEqual(sidecar["zip_sha256"], hashlib.sha256(self.package.read_bytes()).hexdigest())
        self.assertLess(sidecar["zip_bytes"], builder.MAX_ZIP_BYTES)
        self.assertLess(sidecar["unpacked_bytes"], builder.MAX_UNPACKED_BYTES)
        self.assertLess(sidecar["largest_response"]["bytes_upper_bound"], builder.MAX_RESPONSE_BYTES)

    def test_unpacked_package_serves_all_assets_without_repo_or_dependencies(self):
        unpacked = Path(self.temp.name) / "unpacked"
        with zipfile.ZipFile(self.package) as archive:
            archive.extractall(unpacked)
        packaged = load_module("packaged_scf_handler", unpacked / "handler.py")
        self.assertEqual(packaged.WEBSITE_ROOT, (unpacked / "website").resolve())
        for row in self.report["files"]:
            if not row["path"].startswith("website/"):
                continue
            response = packaged.main_handler(event("/" + row["path"][len("website/"):]), None)
            self.assertEqual(response["statusCode"], 200)
            self.assertEqual(hashlib.sha256(body_bytes(response)).hexdigest(), row["sha256"])
        self.assertEqual(packaged.main_handler(event("/../.env"), None)["statusCode"], 400)
        self.assertEqual(packaged.main_handler(event("/deployment-manifest.json"), None)["statusCode"], 404)

    def test_unpacked_package_runs_native_http_without_repository_imports(self):
        unpacked = Path(self.temp.name) / "unpacked-http"
        with zipfile.ZipFile(self.package) as archive:
            archive.extractall(unpacked)
        script = (
            "from http_server import StaticHTTPServer, StaticRequestHandler; "
            "server = StaticHTTPServer(('127.0.0.1', 0), StaticRequestHandler); "
            "print(server.server_port, flush=True); server.serve_forever()"
        )
        process = subprocess.Popen([sys.executable, "-B", "-c", script], cwd=unpacked, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            ready, _, _ = select.select([process.stdout], [], [], 5)
            self.assertTrue(ready, "packaged HTTP server did not start")
            port = int(process.stdout.readline().strip())
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            try:
                connection.request("GET", "/assets/huangcai.png")
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers.get_all("Content-Type"), ["image/png"])
                self.assertEqual(response.read(), (unpacked / "website/assets/huangcai.png").read_bytes())
            finally:
                connection.close()
        finally:
            process.terminate()
            process.communicate(timeout=5)

    def test_requires_explicit_commit_and_refuses_existing_output(self):
        for revision in ["HEAD", self.revision[:12], "--all", "$(touch /tmp/no)"]:
            with self.assertRaises(ValueError):
                builder.build(self.repo, revision, Path(self.temp.name) / "invalid.zip")
        with self.assertRaises(ValueError):
            builder.build(self.repo, self.revision, self.package)

    def test_rejects_oversized_response(self):
        with patch.object(builder, "MAX_RESPONSE_BYTES", 100):
            with self.assertRaisesRegex(ValueError, "response exceeds"):
                builder.build(self.repo, self.revision, Path(self.temp.name) / "too-large.zip")

    def test_rejects_tracked_symlinks_and_hidden_assets(self):
        # Use a separate fixture branch so other tests keep the original commit.
        for filename, content, mode, pattern in [
            ("website/link.txt", b"../.env", "120000", "symlink"),
            ("website/.secret", b"secret", "100644", "non-public"),
            (builder.BOOTSTRAP_SOURCE, b"#!/bin/bash\n", "100644", "executable mode"),
        ]:
            object_id = subprocess.check_output(["git", "-C", str(self.repo), "hash-object", "-w", "--stdin"], input=content).decode().strip()
            with tempfile.TemporaryDirectory() as index_temp:
                environ = {**os.environ, "GIT_INDEX_FILE": str(Path(index_temp) / "index")}
                subprocess.run(["git", "-C", str(self.repo), "read-tree", self.revision], env=environ, check=True)
                subprocess.run(["git", "-C", str(self.repo), "update-index", "--add", "--cacheinfo", mode + "," + object_id + "," + filename], env=environ, check=True)
                tree = subprocess.check_output(["git", "-C", str(self.repo), "write-tree"], env=environ).decode().strip()
                commit = subprocess.check_output(["git", "-C", str(self.repo), "-c", "user.name=SCF Test", "-c", "user.email=scf-test@example.invalid", "commit-tree", tree, "-m", "Unsafe isolated test fixture"]).decode().strip()
            with self.assertRaisesRegex(ValueError, pattern):
                builder.build(self.repo, commit, Path(self.temp.name) / "unsafe.zip")


if __name__ == "__main__":
    unittest.main()
