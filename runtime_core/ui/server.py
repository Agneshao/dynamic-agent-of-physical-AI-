"""Dependency-free HTTP server for the read-only runtime observability UI."""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

from runtime_core.demo.thunderstorm_demo import run_thunderstorm_demo
from runtime_core.ui.projection import build_observability_view


STATIC_DIR = Path(__file__).with_name("static")


class ObservabilityRequestHandler(BaseHTTPRequestHandler):
    """Serve a precomputed, detached scenario projection and static assets."""

    scenario_payload: bytes = b"{}"

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        route = self.path.split("?", 1)[0]
        if route == "/api/scenario":
            self._send(self.scenario_payload, "application/json; charset=utf-8")
            return
        assets = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/index.html": ("index.html", "text/html; charset=utf-8"),
            "/styles.css": ("styles.css", "text/css; charset=utf-8"),
            "/app.js": ("app.js", "text/javascript; charset=utf-8"),
            "/scenario.js": ("scenario.js", "text/javascript; charset=utf-8"),
        }
        asset = assets.get(route)
        if asset is None:
            self.send_error(404)
            return
        filename, content_type = asset
        self._send((STATIC_DIR / filename).read_bytes(), content_type)

    def log_message(self, format: str, *args: object) -> None:
        del format, args

    def _send(self, body: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)


def create_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    audit_path: Optional[Path] = None,
) -> ThreadingHTTPServer:
    """Create a server whose payload is isolated from all runtime writer objects."""
    result = run_thunderstorm_demo(audit_path=audit_path)
    view = build_observability_view(result)
    payload = json.dumps(
        view.model_dump(mode="json"),
        separators=(",", ":"),
    ).encode("utf-8")

    class BoundHandler(ObservabilityRequestHandler):
        scenario_payload = payload

    return ThreadingHTTPServer((host, port), BoundHandler)


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the runtime observability UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = create_server(host=args.host, port=args.port)
    print(f"Runtime observability UI: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
