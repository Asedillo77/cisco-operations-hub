import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from cisco_operations_hub.registry import build_registry
from cisco_operations_hub.server import create_server


def test_server_rejects_non_loopback_binding() -> None:
    with pytest.raises(ValueError, match="loopback"):
        create_server("0.0.0.0", 8765)


def test_tools_endpoint_and_csrf_protection() -> None:
    server = create_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        with urlopen(f"http://{host}:{port}/api/tools", timeout=2) as response:
            body = json.loads(response.read())
            assert len(body["tools"]) == 5

        request = Request(
            f"http://{host}:{port}/api/validate",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(HTTPError) as error:
            urlopen(request, timeout=2)
        assert error.value.code == 403
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_all_active_path_fields_offer_a_native_picker() -> None:
    for adapter in build_registry().values():
        description = adapter.describe()
        if not description.available:
            continue
        path_fields = [field for field in description.fields if field.kind == "path"]
        assert path_fields
        assert all(field.picker in {"file", "folder"} for field in path_fields)


def test_import_failure_returns_json_instead_of_dropping_request() -> None:
    class BrokenAdapter:
        def run(self, values: dict[str, object], *, apply: bool) -> None:
            raise ModuleNotFoundError("Missing runtime package: example")

    server = create_server("127.0.0.1", 0)
    server.registry["broken"] = BrokenAdapter()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    payload = json.dumps({"tool_id": "broken", "values": {}, "apply": False}).encode("utf-8")
    request = Request(
        f"http://{host}:{port}/api/run",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-CSRF-Token": server.csrf_token,
        },
        method="POST",
    )
    try:
        with pytest.raises(HTTPError) as error:
            urlopen(request, timeout=2)
        assert error.value.code == 400
        body = json.loads(error.value.read())
        assert body["error"] == "Missing runtime package: example"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
