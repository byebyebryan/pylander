from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected object JSON at {path}")
    return payload


def write_json(path: str | Path, payload: dict[str, Any]) -> Path:
    out = Path(path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return out


def run_command(cmd: list[str], *, cwd: str | Path) -> tuple[int, str]:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return int(proc.returncode), str(proc.stdout or "")


def parse_compare_report_path(output: str) -> str | None:
    lines = output.splitlines()
    for idx, line in enumerate(lines):
        if line.strip() != "# compare_report":
            continue
        for j in range(idx + 1, min(idx + 6, len(lines))):
            m = re.match(r"^json=(.+)$", lines[j].strip())
            if m:
                return m.group(1).strip()
    return None


def parse_section_json_path(output: str, section_header: str) -> str | None:
    marker = f"# {section_header.strip()}"
    lines = output.splitlines()
    for idx, line in enumerate(lines):
        if line.strip() != marker:
            continue
        for j in range(idx + 1, min(idx + 12, len(lines))):
            m = re.match(r"^json=(.+)$", lines[j].strip())
            if m:
                return m.group(1).strip()
    return None


def parse_seed_spec(spec: str) -> list[int]:
    out: list[int] = []
    for token in (p.strip() for p in str(spec).split(",")):
        if not token:
            continue
        if "-" in token:
            left, right = token.split("-", 1)
            start = int(left.strip())
            end = int(right.strip())
            step = 1 if end >= start else -1
            out.extend(range(start, end + step, step))
        else:
            out.append(int(token))
    deduped: list[int] = []
    seen: set[int] = set()
    for value in out:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)
