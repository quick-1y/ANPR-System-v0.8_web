from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, Tuple


STATIC_DIR = Path(__file__).resolve().parent / "static"


def build_runtime_config(core_base_url: str, video_base_url: str, events_base_url: str) -> Dict[str, str]:
    return {
        "core_base_url": core_base_url.rstrip("/"),
        "video_base_url": video_base_url.rstrip("/"),
        "events_base_url": events_base_url.rstrip("/"),
    }


def resolve_proxy_target(path: str, runtime_config: Dict[str, str]) -> Tuple[str, str] | None:
    parsed = urllib.parse.urlsplit(path)
    clean_path = parsed.path.rstrip("/") or "/"
    query = f"?{parsed.query}" if parsed.query else ""

    if clean_path.startswith("/api/proxy/core"):
        suffix = clean_path.removeprefix("/api/proxy/core")
        return runtime_config["core_base_url"], suffix + query
    if clean_path.startswith("/api/proxy/video"):
        suffix = clean_path.removeprefix("/api/proxy/video")
        return runtime_config["video_base_url"], suffix + query
    if clean_path.startswith("/api/proxy/events"):
        suffix = clean_path.removeprefix("/api/proxy/events")
        return runtime_config["events_base_url"], suffix + query
    return None


class WebUIRequestHandler(SimpleHTTPRequestHandler):
    runtime_config: Dict[str, str] = {}

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/api/config":
            payload = json.dumps(self.runtime_config, ensure_ascii=False).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if self.path.startswith("/api/proxy/"):
            self._proxy_request("GET")
            return

        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        if self.path.startswith("/api/proxy/"):
            self._proxy_request("POST")
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

    def _proxy_request(self, method: str) -> None:
        target = resolve_proxy_target(self.path, self.runtime_config)
        if not target:
            self._send_json({"error": "proxy_target_not_found"}, status=HTTPStatus.NOT_FOUND)
            return

        base_url, suffix = target
        target_url = f"{base_url}{suffix}"
        data = None
        if method in {"POST", "PUT", "PATCH"}:
            content_len = int(self.headers.get("Content-Length", "0") or 0)
            data = self.rfile.read(content_len) if content_len > 0 else None

        headers = {"Content-Type": self.headers.get("Content-Type", "application/json")}
        request = urllib.request.Request(url=target_url, data=data, headers=headers, method=method)

        try:
            with urllib.request.urlopen(request, timeout=5.0) as response:
                payload = response.read() or b"{}"
                self.send_response(int(response.getcode() or 200))
                self.send_header("Content-Type", response.headers.get("Content-Type", "application/json; charset=utf-8"))
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
        except urllib.error.HTTPError as exc:
            payload = exc.read() or b'{"error":"upstream_http_error"}'
            self.send_response(int(exc.code))
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except Exception:
            self._send_json({"error": "upstream_unreachable"}, status=HTTPStatus.BAD_GATEWAY)

    def _send_json(self, payload: Dict[str, object], status: int = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


def run_server(
    host: str = "127.0.0.1",
    port: int = 8110,
    core_base_url: str = "http://127.0.0.1:8080/api/v1",
    video_base_url: str = "http://127.0.0.1:8090/api/v1",
    events_base_url: str = "http://127.0.0.1:8100/api/v1",
) -> None:
    runtime_config = build_runtime_config(core_base_url, video_base_url, events_base_url)

    class ConfiguredHandler(WebUIRequestHandler):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    ConfiguredHandler.runtime_config = runtime_config
    server = ThreadingHTTPServer((host, port), ConfiguredHandler)
    print(f"Web UI listening on http://{host}:{port}")
    server.serve_forever()
