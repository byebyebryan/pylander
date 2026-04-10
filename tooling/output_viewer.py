from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SERVICE_NAME = "pylander_outputs_server"
HEALTH_PATH = "/__pylander_viewer_health__"


def normalize_base_url(value: str | None) -> str | None:
    if not value:
        return None
    base = str(value).strip().rstrip("/")
    if not base:
        return None
    return base


def bundle_url(base_url: str | None, rel_path: str) -> str | None:
    if not base_url:
        return None
    return f"{base_url}/{rel_path.lstrip('/')}"


def local_ip() -> str | None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        host = sock.getsockname()[0]
        return host or None
    except OSError:
        return None
    finally:
        sock.close()


def resolves_to_nonloopback(hostname: str) -> bool:
    try:
        addr = socket.gethostbyname(hostname)
    except OSError:
        return False
    return not addr.startswith("127.")


def discover_viewer_hostname() -> str:
    short_host = str(socket.gethostname() or "").strip()
    short_label = short_host.split(".", 1)[0]
    fqdn = str(socket.getfqdn() or "").strip()

    candidates: list[str] = []
    if short_label:
        candidates.append(f"{short_label}.lan")
    if fqdn and "." in fqdn and fqdn not in candidates:
        candidates.append(fqdn)
    if short_host and "." in short_host and short_host not in candidates:
        candidates.append(short_host)

    for candidate in candidates:
        if resolves_to_nonloopback(candidate):
            return candidate

    ip_addr = local_ip()
    if ip_addr:
        return ip_addr
    return short_label or "localhost"


def server_health(port: int) -> dict[str, Any] | None:
    health_url = f"http://127.0.0.1:{int(port)}{HEALTH_PATH}"
    try:
        with urllib.request.urlopen(health_url, timeout=0.75) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (
        OSError,
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
        ValueError,
    ):
        return None
    if not isinstance(payload, dict):
        return None
    if str(payload.get("service") or "") != SERVICE_NAME:
        return None
    return payload


def _server_root(payload: dict[str, Any] | None) -> Path | None:
    if not isinstance(payload, dict):
        return None
    token = str(payload.get("root") or "").strip()
    if not token:
        return None
    return Path(token).expanduser().resolve()


def _listener_pid_for_port(port: int) -> int | None:
    try:
        proc = subprocess.run(
            [
                "lsof",
                f"-tiTCP:{int(port)}",
                "-sTCP:LISTEN",
            ],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return None
    if int(proc.returncode) not in {0, 1}:
        return None
    for line in str(proc.stdout or "").splitlines():
        token = line.strip()
        if not token:
            continue
        try:
            return int(token)
        except ValueError:
            continue
    return None


def _stop_existing_server(root: Path, port: int) -> bool:
    state_path = (root / "viewer" / "server.json").resolve()
    payload: dict[str, Any] | None = None
    if state_path.exists():
        try:
            loaded = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            loaded = None
        if (
            isinstance(loaded, dict)
            and str(loaded.get("service") or "") == SERVICE_NAME
        ):
            payload = loaded
    pid = None if payload is None else payload.get("pid")
    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        pid_int = _listener_pid_for_port(port)
    if pid_int is None:
        return False

    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.kill(pid_int, sig)
        except ProcessLookupError:
            break
        except OSError:
            return False

        deadline = time.time() + 5.0
        while time.time() < deadline:
            if server_health(port) is None:
                return True
            time.sleep(0.1)

    return server_health(port) is None


def write_server_state(
    *,
    outputs_root: Path,
    status: str,
    port: int,
    bind_host: str,
    viewer_hostname: str,
    pid: int | None,
) -> Path:
    state_path = (outputs_root / "viewer" / "server.json").resolve()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "service": SERVICE_NAME,
        "status": status,
        "bind_host": bind_host,
        "port": int(port),
        "viewer_hostname": viewer_hostname,
        "viewer_base_url": f"http://{viewer_hostname}:{int(port)}",
        "pid": pid,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    state_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    return state_path


def default_server_command() -> list[str]:
    return [sys.executable, "-m", "tooling.serve_outputs"]


def ensure_outputs_server(
    *,
    outputs_root: Path,
    bind_host: str,
    port: int,
    viewer_hostname: str,
    repo_root: Path,
    server_script: Path | None = None,
) -> tuple[str, Path]:
    existing = server_health(port)
    desired_root = outputs_root.resolve()
    existing_root = _server_root(existing)
    if existing is not None and existing_root == desired_root:
        state_path = write_server_state(
            outputs_root=desired_root,
            status="running",
            port=port,
            bind_host=bind_host,
            viewer_hostname=viewer_hostname,
            pid=None,
        )
        return "reused", state_path
    if existing is not None and existing_root is not None:
        if not _stop_existing_server(existing_root, port):
            raise SystemExit(
                "Outputs server on "
                f"http://127.0.0.1:{int(port)}{HEALTH_PATH} serves "
                f"{existing_root}, not {desired_root}, and could not be replaced automatically."
            )
    state_path = write_server_state(
        outputs_root=desired_root,
        status="starting",
        port=port,
        bind_host=bind_host,
        viewer_hostname=viewer_hostname,
        pid=None,
    )

    log_path = (desired_root / "viewer" / "server.log").resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command = default_server_command()
    if server_script is not None:
        command = [sys.executable, str(server_script)]
    command.extend(
        [
            "--host",
            bind_host,
            "--port",
            str(int(port)),
            "--root",
            str(desired_root),
        ]
    )
    with log_path.open("ab") as log_fh:
        proc = subprocess.Popen(
            command,
            cwd=str(repo_root),
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    write_server_state(
        outputs_root=desired_root,
        status="starting",
        port=port,
        bind_host=bind_host,
        viewer_hostname=viewer_hostname,
        pid=proc.pid,
    )

    deadline = time.time() + 5.0
    while time.time() < deadline:
        if server_health(port) is not None:
            write_server_state(
                outputs_root=desired_root,
                status="running",
                port=port,
                bind_host=bind_host,
                viewer_hostname=viewer_hostname,
                pid=proc.pid,
            )
            return "started", state_path
        time.sleep(0.1)

    raise SystemExit(
        "Outputs server failed to become healthy on "
        f"http://127.0.0.1:{int(port)}{HEALTH_PATH}. "
        f"Check {log_path} for details."
    )


__all__ = [
    "HEALTH_PATH",
    "SERVICE_NAME",
    "bundle_url",
    "default_server_command",
    "discover_viewer_hostname",
    "ensure_outputs_server",
    "local_ip",
    "normalize_base_url",
    "resolves_to_nonloopback",
    "server_health",
    "write_server_state",
]
