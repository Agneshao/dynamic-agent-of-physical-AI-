"""Dependency-free HTTP server for the read-only runtime observability UI."""

from __future__ import annotations

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

from pydantic import ValidationError

from runtime_core.adapters.stepfun_model_router import (
    StepFunModelRouter,
    StepFunModelRouterError,
)
from runtime_core.demo.thunderstorm_demo import run_thunderstorm_demo
from runtime_core.ports.model_router import ModelRouterPort
from runtime_core.schemas.runtime_chat import RuntimeChatRequest
from runtime_core.trace.exporter import dump_runtime_trace_jsonl
from runtime_core.ui.chat_service import (
    RuntimeChatInvalidModelOutputError,
    RuntimeChatModelNotConfiguredError,
    RuntimeChatService,
)
from runtime_core.ui.projection import build_observability_view


STATIC_DIR = Path(__file__).with_name("static")


class ObservabilityRequestHandler(BaseHTTPRequestHandler):
    """Serve a precomputed, detached scenario projection and static assets."""

    scenario_payload: bytes = b"{}"
    trace_payload: bytes = b""
    chat_service = RuntimeChatService(None)

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        route = self.path.split("?", 1)[0]
        if route == "/api/scenario":
            self._send(self.scenario_payload, "application/json; charset=utf-8")
            return
        if route == "/runtime_trace.jsonl":
            self._send(self.trace_payload, "application/x-ndjson; charset=utf-8")
            return
        if route == "/api/model-status":
            self._send_json(
                {
                    "configured": self.chat_service.configured,
                    "model": self.chat_service.model_name,
                }
            )
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

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        route = self.path.split("?", 1)[0]
        if route != "/api/chat":
            self.send_error(501, "Unsupported method")
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json({"error": "INVALID_CONTENT_LENGTH"}, status=400)
            return
        if content_length <= 0 or content_length > 65_536:
            self._send_json({"error": "INVALID_REQUEST_SIZE"}, status=400)
            return
        try:
            raw = self.rfile.read(content_length)
            request = RuntimeChatRequest.model_validate_json(raw)
            reply = self.chat_service.reply(request)
        except (ValidationError, json.JSONDecodeError) as exc:
            self._send_json(
                {"error": "INVALID_CHAT_REQUEST", "message": str(exc)},
                status=400,
            )
            return
        except RuntimeChatModelNotConfiguredError:
            self._send_json(
                {"error": "MODEL_NOT_CONFIGURED", "model": self.chat_service.model_name},
                status=503,
            )
            return
        except (StepFunModelRouterError, RuntimeChatInvalidModelOutputError) as exc:
            self._send_json(
                {"error": "MODEL_REQUEST_FAILED", "message": str(exc)},
                status=502,
            )
            return
        self._send_json(
            {
                **reply.model_dump(mode="json"),
                "source": "STEPFUN",
                "model": self.chat_service.model_name,
            }
        )

    def log_message(self, format: str, *args: object) -> None:
        del format, args

    def _send_json(self, payload: object, *, status: int = 200) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self._send(body, "application/json; charset=utf-8", status=status)

    def _send(self, body: bytes, content_type: str, *, status: int = 200) -> None:
        self.send_response(status)
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
    model_router: Optional[ModelRouterPort] = None,
) -> ThreadingHTTPServer:
    """Create a server whose payload is isolated from all runtime writer objects."""
    result = run_thunderstorm_demo(audit_path=audit_path)
    view = build_observability_view(result)
    runtime_trace_payload = dump_runtime_trace_jsonl(result)
    payload = json.dumps(
        view.model_dump(mode="json"),
        separators=(",", ":"),
    ).encode("utf-8")
    resolved_model_router = model_router
    if resolved_model_router is None and os.environ.get("STEP_API_KEY"):
        resolved_model_router = StepFunModelRouter()
    runtime_chat_service = RuntimeChatService(resolved_model_router)

    class BoundHandler(ObservabilityRequestHandler):
        scenario_payload = payload
        trace_payload = runtime_trace_payload
        chat_service = runtime_chat_service

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
