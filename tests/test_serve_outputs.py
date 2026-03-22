from __future__ import annotations

import importlib.util
import json
import threading
import urllib.request
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _script(rel: str) -> Path:
    return (REPO_ROOT / rel).resolve()


serve_outputs = _load_module(
    "serve_outputs_script",
    _script("skills/pylander-benchmark-runner/scripts/serve_outputs.py"),
)


def test_health_endpoint_reports_service_and_root(tmp_path: Path) -> None:
    handler = partial(serve_outputs._NoCacheHandler, directory=str(tmp_path))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}{serve_outputs._HEALTH_PATH}",
            timeout=2.0,
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
        assert payload["service"] == serve_outputs._SERVICE_NAME
        assert payload["root"] == str(tmp_path.resolve())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)
