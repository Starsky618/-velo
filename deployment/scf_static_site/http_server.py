"""Native HTTP transport for the read-only VELO SCF Web function."""

import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from urllib.parse import parse_qsl

from handler import main_handler


class StaticHTTPServer(ThreadingHTTPServer):
    # Bound per-instance memory even when multiple HTTP connections reach one instance.
    daemon_threads = True
    request_queue_size = 8

    def __init__(self, *args, **kwargs):
        self._slots = threading.BoundedSemaphore(2)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        self._slots.acquire()
        try:
            super().process_request(request, client_address)
        except Exception:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()

    def handle_error(self, request, client_address):
        # Do not log HTTP contents, platform headers, or exception values.
        return


class StaticRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    timeout = 5

    def log_message(self, format, *args):
        return

    def __getattr__(self, name):
        # Let the shared handler return 405 for every parsed non-GET/HEAD method.
        if name.startswith("do_"):
            return self._respond
        raise AttributeError(name)

    def _plain_error(self, status, message):
        payload = message.encode("ascii")
        self.send_response_only(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def _respond(self):
        # No request body is needed. Closing prevents unread POST/pipeline bytes reuse.
        self.close_connection = True
        try:
            # BaseHTTPRequestHandler normalizes leading // in self.path; keep the original target.
            request_target = self.requestline.split()[1]
            path, separator, raw_query = request_target.partition("?")
            if any(ord(character) < 33 or ord(character) > 126 for character in request_target):
                raise ValueError("invalid request target")
            if any(len(self.headers.get_all(name, [])) > 1 for name in ("Host", "X-SCF-Request-Domain")):
                raise ValueError("ambiguous request domain")
            query = dict(parse_qsl(raw_query, keep_blank_values=True, errors="strict", max_num_fields=1000))
        except (ValueError, UnicodeError):
            self._plain_error(400, "Bad Request\n")
            return
        try:
            response = main_handler({
                "httpMethod": self.command, "path": path,
                "headers": dict(self.headers.items()), "queryString": query, "body": "",
            }, None)
            status = response["statusCode"]
            headers = dict(response["headers"])
            # Keep repeated parameters, ordering, blank values and original URL encoding.
            if status in {301, 308} and separator:
                headers["Location"] = headers["Location"].partition("?")[0] + "?" + raw_query
            body = response["body"]
            payload = base64.b64decode(body, validate=True) if response["isBase64Encoded"] else body.encode("utf-8")
            if any("\r" in str(value) or "\n" in str(value) for value in headers.values()):
                raise ValueError("invalid response header")
            if status == 304:
                payload = b""
                headers.pop("Content-Length", None)
            elif self.command != "HEAD":
                # The wire length belongs to decoded bytes, never the Base64 envelope.
                headers["Content-Length"] = str(len(payload))
        except Exception:
            self._plain_error(500, "Internal Server Error\n")
            return
        self.send_response_only(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD" and status != 304:
            self.wfile.write(payload)


def main():
    with StaticHTTPServer(("0.0.0.0", 9000), StaticRequestHandler) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
