from __future__ import annotations

import json
import secrets
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .pickers import select_path
from .registry import build_registry

MAX_REQUEST_BYTES = 1_000_000
WEB_ROOT = Path(__file__).resolve().parent / "web"
if not WEB_ROOT.is_dir():
    WEB_ROOT = Path(__file__).resolve().parents[2] / "web"


class HubServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int]) -> None:
        super().__init__(address, HubHandler)
        self.csrf_token = secrets.token_urlsafe(32)
        self.registry = build_registry()


class HubHandler(BaseHTTPRequestHandler):
    server: HubServer

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
            self._send_text(html.replace("{{CSRF_TOKEN}}", self.server.csrf_token), "text/html")
            return
        if path == "/app.js":
            self._send_text((WEB_ROOT / "app.js").read_text(encoding="utf-8"), "text/javascript")
            return
        if path == "/styles.css":
            self._send_text((WEB_ROOT / "styles.css").read_text(encoding="utf-8"), "text/css")
            return
        if path == "/api/tools":
            tools = [adapter.describe().to_dict() for adapter in self.server.registry.values()]
            self._send_json({"tools": tools})
            return
        self._send_json({"error": "Not found."}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if self.headers.get("X-CSRF-Token") != self.server.csrf_token:
            self._send_json({"error": "Invalid request token."}, HTTPStatus.FORBIDDEN)
            return
        try:
            payload = self._read_json()
            tool_id = str(payload.get("tool_id", ""))
            adapter = self.server.registry.get(tool_id)
            if adapter is None:
                raise ValueError("Unknown tool.")
            path = urlparse(self.path).path
            if path == "/api/browse":
                field_name = str(payload.get("field_name", ""))
                field = next(
                    (item for item in adapter.describe().fields if item.name == field_name),
                    None,
                )
                if field is None:
                    raise ValueError("Unknown tool field.")
                self._send_json({"path": select_path(field)})
                return
            values = payload.get("values")
            if not isinstance(values, dict):
                raise ValueError("Tool values must be a JSON object.")
            if path == "/api/inventory-scope":
                inventory_scope = getattr(adapter, "inventory_scope", None)
                if inventory_scope is None:
                    raise ValueError("Inventory scope selection is unavailable for this tool.")
                self._send_json(inventory_scope(values))
                return
            if path == "/api/validate":
                self._send_json(adapter.validate(values).to_dict())
                return
            if path == "/api/run":
                apply = payload.get("apply", False)
                if not isinstance(apply, bool):
                    raise ValueError("Apply must be true or false.")
                self._send_json(adapter.run(values, apply=apply).to_dict())
                return
            self._send_json({"error": "Not found."}, HTTPStatus.NOT_FOUND)
        except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("Invalid request length.") from exc
        if length < 1 or length > MAX_REQUEST_BYTES:
            raise ValueError("Request body is empty or too large.")
        try:
            value = json.loads(self.rfile.read(length))
        except json.JSONDecodeError as exc:
            raise ValueError("Request body must be valid JSON.") from exc
        if not isinstance(value, dict):
            raise ValueError("Request body must be a JSON object.")
        return value

    def _send_json(self, value: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        self._send_bytes(json.dumps(value).encode("utf-8"), "application/json", status)

    def _send_text(self, value: str, content_type: str) -> None:
        self._send_bytes(value.encode("utf-8"), content_type, HTTPStatus.OK)

    def _send_bytes(self, value: bytes, content_type: str, status: HTTPStatus) -> None:
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(value)))
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'"
        )
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(value)

    def log_message(self, format: str, *args: object) -> None:
        return


def create_server(host: str = "127.0.0.1", port: int = 8765) -> HubServer:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("The operations hub may only bind to a loopback address.")
    return HubServer((host, port))
