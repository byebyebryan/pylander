from __future__ import annotations

import os
from pathlib import Path


def sanitize_token(value: str, *, fallback: str = "run") -> str:
    out: list[str] = []
    prev_us = False
    for ch in str(value).lower().strip():
        if ch.isalnum() or ch in ("-", "."):
            out.append(ch)
            prev_us = False
        elif not prev_us:
            out.append("_")
            prev_us = True
    token = "".join(out).strip("._")
    while "__" in token:
        token = token.replace("__", "_")
    return token or fallback


def output_path(path_value: str | None, *, repo_root: Path) -> Path | None:
    if not path_value:
        return None
    path = Path(str(path_value).strip())
    if not path.is_absolute():
        path = (repo_root / path).resolve()
    return path


def artifact_path(path_value: str | None, *, outputs_root: Path) -> Path | None:
    if not path_value:
        return None
    path = Path(str(path_value).strip())
    if path.is_absolute():
        return path.resolve()
    if path.parts and path.parts[0] == "outputs":
        return (outputs_root.parent / path).resolve()
    return (outputs_root / path).resolve()


def rel_to_outputs(path: Path | None, *, outputs_root: Path) -> str | None:
    if path is None:
        return None
    try:
        return path.resolve().relative_to(outputs_root).as_posix()
    except ValueError:
        return None


def href_from(base_dir: Path, target: Path | None) -> str | None:
    if target is None:
        return None
    return os.path.relpath(target, base_dir).replace(os.sep, "/")


def href_from_outputs(
    base_dir: Path, target_rel: str | None, *, outputs_root: Path
) -> str | None:
    if not target_rel:
        return None
    target = outputs_root / target_rel
    return href_from(base_dir, target)
