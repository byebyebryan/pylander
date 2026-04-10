from __future__ import annotations

import json
import signal
from pathlib import Path

import tooling.output_viewer as output_viewer


def test_ensure_outputs_server_restarts_when_existing_root_differs(
    monkeypatch,
    tmp_path: Path,
) -> None:
    desired_root = (tmp_path / "desired_outputs").resolve()
    stale_root = (tmp_path / "stale_outputs").resolve()
    stale_state_path = stale_root / "viewer" / "server.json"
    stale_state_path.parent.mkdir(parents=True, exist_ok=True)
    stale_state_path.write_text(
        json.dumps(
            {
                "service": output_viewer.SERVICE_NAME,
                "pid": 12345,
            }
        ),
        encoding="utf-8",
    )

    health_payloads = iter(
        (
            {"service": output_viewer.SERVICE_NAME, "root": str(stale_root)},
            None,
            {"service": output_viewer.SERVICE_NAME, "root": str(desired_root)},
        )
    )

    def _fake_server_health(_port: int):
        try:
            return next(health_payloads)
        except StopIteration:
            return {"service": output_viewer.SERVICE_NAME, "root": str(desired_root)}

    kill_calls: list[tuple[int, signal.Signals]] = []

    class _FakeProc:
        pid = 67890

    monkeypatch.setattr(output_viewer, "server_health", _fake_server_health)
    monkeypatch.setattr(
        output_viewer.os, "kill", lambda pid, sig: kill_calls.append((pid, sig))
    )
    monkeypatch.setattr(
        output_viewer.subprocess, "Popen", lambda *args, **kwargs: _FakeProc()
    )
    monkeypatch.setattr(output_viewer.time, "sleep", lambda _secs: None)

    status, state_path = output_viewer.ensure_outputs_server(
        outputs_root=desired_root,
        bind_host="0.0.0.0",
        port=8765,
        viewer_hostname="starship.lan",
        repo_root=tmp_path,
    )

    assert status == "started"
    assert state_path == (desired_root / "viewer" / "server.json").resolve()
    assert kill_calls == [(12345, signal.SIGTERM)]
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload["status"] == "running"
    assert payload["pid"] == 67890


def test_stop_existing_server_falls_back_to_listener_pid_when_state_pid_missing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    root = (tmp_path / "outputs").resolve()
    state_path = root / "viewer" / "server.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "service": output_viewer.SERVICE_NAME,
                "pid": None,
            }
        ),
        encoding="utf-8",
    )

    health_payloads = iter((None,))
    kill_calls: list[tuple[int, signal.Signals]] = []

    monkeypatch.setattr(
        output_viewer,
        "server_health",
        lambda _port: next(health_payloads, None),
    )
    monkeypatch.setattr(output_viewer, "_listener_pid_for_port", lambda _port: 54321)
    monkeypatch.setattr(
        output_viewer.os, "kill", lambda pid, sig: kill_calls.append((pid, sig))
    )
    monkeypatch.setattr(output_viewer.time, "sleep", lambda _secs: None)

    assert output_viewer._stop_existing_server(root, 8765) is True
    assert kill_calls == [(54321, signal.SIGTERM)]
