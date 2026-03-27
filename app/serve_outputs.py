from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from app.output_viewer import HEALTH_PATH, SERVICE_NAME

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SERVICE_NAME = SERVICE_NAME
_HEALTH_PATH = HEALTH_PATH


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


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Serve the local outputs directory over HTTP"
    )
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--root", default=str((_REPO_ROOT / "outputs").resolve()))
    return ap


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(list(argv) if argv is not None else None)

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


__all__ = ["_HEALTH_PATH", "_NoCacheHandler", "_SERVICE_NAME", "build_parser", "main"]


if __name__ == "__main__":
    main()
