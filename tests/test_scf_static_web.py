"""Real local HTTP checks for SCF's native Web transport, with no cloud calls."""

import base64
import contextlib
import gzip
import http.client
import importlib.util
import io
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
DEPLOYMENT = ROOT / "deployment/scf_static_site"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


handler = load("scf_native_routing", DEPLOYMENT / "handler.py")
handler.WEBSITE_ROOT = ROOT / "website"
with patch.dict("sys.modules", {"handler": handler}):
    web = load("scf_native_http", DEPLOYMENT / "http_server.py")


class NativeHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = web.StaticHTTPServer(("127.0.0.1", 0), web.StaticRequestHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def request(self, path, method="GET", headers=None, body=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            connection.request(method, path, body=body, headers={"Host": "weiluai.top", **(headers or {})})
            response = connection.getresponse()
            payload = response.read()
            values = response.headers
            if response.status == 304:
                self.assertIsNone(values.get("Content-Length"))
                self.assertEqual(payload, b"")
            elif method != "HEAD":
                self.assertEqual(int(values["Content-Length"]), len(payload))
            if values.get("Content-Type"):
                self.assertEqual(len(values.get_all("Content-Type")), 1)
            self.assertIsNone(values.get("Content-Disposition"))
            self.assertIsNone(values.get("Transfer-Encoding"))
            self.assertEqual(values.get("Connection"), "close")
            return response.status, values, payload
        finally:
            connection.close()

    def test_pages_and_binary_assets_return_actual_source_bytes(self):
        targets = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/company/": ("company/index.html", "text/html; charset=utf-8"),
            "/privacy/garmin/": ("privacy/garmin/index.html", "text/html; charset=utf-8"),
            "/en/": ("en/index.html", "text/html; charset=utf-8"),
            "/assets/huangcai.png": ("assets/huangcai.png", "image/png"),
            "/assets/tianlong.jpg": ("assets/tianlong.jpg", "image/jpeg"),
            "/assets/velo-editorial.woff": ("assets/velo-editorial.woff", "font/woff"),
        }
        for path, (source, mime) in targets.items():
            with self.subTest(path=path):
                status, headers, payload = self.request(path)
                self.assertEqual(status, 200)
                self.assertEqual(headers["Content-Type"], mime)
                self.assertEqual(payload, (ROOT / "website" / source).read_bytes())
                self.assertNotEqual(payload, base64.b64encode((ROOT / "website" / source).read_bytes()))

    def test_gzip_is_real_compressed_bytes_and_revalidates(self):
        for path, source in [("/", "index.html"), ("/data/segments.json", "data/segments.json")]:
            status, headers, payload = self.request(path, headers={"Accept-Encoding": "gzip"})
            self.assertEqual(status, 200)
            self.assertEqual(headers["Content-Encoding"], "gzip")
            self.assertEqual(payload[:2], b"\x1f\x8b")
            self.assertEqual(gzip.decompress(payload), (ROOT / "website" / source).read_bytes())
            self.assertEqual(headers["Vary"], "Accept-Encoding")
            status, _, payload = self.request(path, headers={"Accept-Encoding": "gzip", "If-None-Match": headers["ETag"]})
            self.assertEqual(status, 304)
            self.assertEqual(payload, b"")

    def test_head_keeps_get_length_without_body(self):
        for path in ["/", "/assets/huangcai.png", "/missing"]:
            for accept in ["identity", "gzip"]:
                get_status, get_headers, _ = self.request(path, headers={"Accept-Encoding": accept})
                status, headers, payload = self.request(path, "HEAD", {"Accept-Encoding": accept})
                self.assertEqual(status, get_status)
                self.assertEqual(headers["Content-Length"], get_headers["Content-Length"])
                self.assertEqual(headers["ETag"], get_headers["ETag"])
                self.assertEqual(payload, b"")

    def test_etag_304_has_no_body_or_content_length(self):
        _, headers, _ = self.request("/")
        for method in ["GET", "HEAD"]:
            status, _, payload = self.request("/", method, {"If-None-Match": headers["ETag"]})
            self.assertEqual(status, 304)
            self.assertEqual(payload, b"")

    def test_original_404_and_no_private_package_files(self):
        for path in ["/missing", "/assets/", "/handler.py", "/http_server.py", "/scf_bootstrap", "/deployment-manifest.json"]:
            status, _, payload = self.request(path)
            self.assertEqual(status, 404)
            self.assertEqual(payload, (ROOT / "website/404.html").read_bytes())

    def test_non_get_head_is_405_including_unknown_methods_and_post_body(self):
        for method in ["POST", "PUT", "DELETE", "PATCH", "OPTIONS", "TRACE", "CONNECT", "BREW"]:
            status, headers, payload = self.request("/", method, body=b"request body is ignored")
            self.assertEqual(status, 405)
            self.assertEqual(headers["Allow"], "GET, HEAD")
            self.assertEqual(payload, b"Method Not Allowed\n")

    def test_domain_and_redirect_preserve_original_query(self):
        query = "tag=a&tag=b&blank=&next=%2fen%2f+%20"
        status, headers, _ = self.request("/privacy/garmin/?" + query, headers={"Host": "www.weiluai.top"})
        self.assertEqual(status, 301)
        self.assertEqual(headers["Location"], "https://weiluai.top/privacy/garmin/?" + query)
        status, headers, _ = self.request("/company?" + query)
        self.assertEqual(status, 308)
        self.assertEqual(headers["Location"], "/company/?" + query)
        status, headers, _ = self.request("/company/?" + query, headers={"Host": "internal.scf", "X-SCF-Request-Domain": "www.weiluai.top"})
        self.assertEqual(status, 301)
        self.assertEqual(headers["Location"], "https://weiluai.top/company/?" + query)

    def test_original_path_blocks_traversal_hidden_uploads_and_double_slash(self):
        for path in ["/../.env", "/.git/config", "/assets/.env", "/uploads/private.gpx", "/%2e%2e/uploads/private.gpx", "/%252e%252e%252f.env", "//evil.example/", "/assets//file", "/%00", "/%0d%0aX-Test:evil"]:
            with self.subTest(path=path):
                status, _, payload = self.request(path)
                self.assertEqual(status, 400)
                self.assertEqual(payload, b"Bad Request\n")

    def test_http_contents_and_exception_values_are_not_logged(self):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            self.request("/?secret=do-not-log", headers={"X-SCF-Secret-Key": "secret-value"})
            with patch.object(web, "main_handler", side_effect=RuntimeError("secret-value")):
                status, _, payload = self.request("/")
                self.assertEqual(status, 500)
                self.assertEqual(payload, b"Internal Server Error\n")
        self.assertEqual(output.getvalue() + errors.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
