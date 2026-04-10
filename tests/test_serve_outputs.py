from __future__ import annotations

import json
import threading
import urllib.request
from functools import partial
from http.server import ThreadingHTTPServer

import tooling.serve_outputs as serve_outputs


def test_health_endpoint_reports_service_and_root(tmp_path) -> None:
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
