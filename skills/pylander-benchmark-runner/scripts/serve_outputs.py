from __future__ import annotations

import argparse
import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SERVICE_NAME = "pylander_outputs_server"
_HEALTH_PATH = "/__pylander_viewer_health__"


class _NoCacheHandler(SimpleHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] == _HEALTH_PATH:
            root = str(Path(getattr(self, "directory", ".")).resolve())
            payload = {
                "service": _SERVICE_NAME,
                "root": root,
            }
            body = json.dumps(payload, sort_keys=True).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()


def main() -> None:
    ap = argparse.ArgumentParser(description="Serve the local outputs directory over HTTP")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--root", default=str((_REPO_ROOT / "outputs").resolve()))
    args = ap.parse_args()

    root = Path(args.root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)

    handler = partial(_NoCacheHandler, directory=str(root))
    server = ThreadingHTTPServer((str(args.host), int(args.port)), handler)
    print(f"Serving {root} at http://{args.host}:{int(args.port)}/")
    print(f"Health check: http://127.0.0.1:{int(args.port)}{_HEALTH_PATH}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
