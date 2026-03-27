from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from utils.tracebundle import artifact_path, sanitize_token

_REPO_ROOT = Path(__file__).resolve().parents[1]


def git_rev_parse(ref: str) -> str:
    out = subprocess.check_output(
        ["git", "rev-parse", "--short", ref],
        cwd=_REPO_ROOT,
        text=True,
    )
    return out.strip()


def _git_output(args: list[str]) -> bytes:
    return subprocess.check_output(["git", *args], cwd=_REPO_ROOT)


def dirty_workspace_fingerprint() -> str | None:
    status = _git_output(["status", "--porcelain=v1", "--untracked-files=all"])
    if not status.strip():
        return None

    payload = bytearray()
    payload.extend(b"STATUS\n")
    payload.extend(status)
    payload.extend(b"\nDIFF_CACHED\n")
    payload.extend(
        _git_output(["diff", "--cached", "--no-ext-diff", "--binary", "HEAD"])
    )
    payload.extend(b"\nDIFF_WORKTREE\n")
    payload.extend(_git_output(["diff", "--no-ext-diff", "--binary", "HEAD"]))

    for raw_line in status.splitlines():
        line = raw_line.decode("utf-8", errors="replace")
        if not line.startswith("?? "):
            continue
        rel_path = line[3:]
        file_path = (_REPO_ROOT / rel_path).resolve()
        payload.extend(f"\nUNTRACKED:{rel_path}\n".encode("utf-8"))
        if file_path.is_file():
            try:
                payload.extend(file_path.read_bytes())
            except Exception:
                payload.extend(b"<unreadable>")

    return hashlib.sha1(bytes(payload)).hexdigest()[:10]


def workspace_key() -> str:
    head = git_rev_parse("HEAD")
    dirty = dirty_workspace_fingerprint()
    if not dirty:
        return head
    return f"{head}-dirty-{dirty}"


def selector_pack_stem(
    *,
    mode: str,
    selectors: list[str],
    bot: str,
    trace_detail: str,
    bot_config_path: str | None,
    bot_profile_enabled: bool,
    bot_profile_interval_s: float | None,
    bot_profile_log_lines: bool,
) -> str:
    level_tokens = sorted({s.split(":", 1)[0] for s in selectors if s.strip()})
    level_hint = "-".join(level_tokens[:3]) if level_tokens else "none"
    if len(level_tokens) > 3:
        level_hint += "-etc"
    digest_payload = json.dumps(
        {
            "mode": mode,
            "selectors": selectors,
            "bot": bot,
            "trace_detail": trace_detail,
            "bot_config_path": (None if not bot_config_path else str(bot_config_path)),
            "bot_profile_enabled": bool(bot_profile_enabled),
            "bot_profile_interval_s": (
                None
                if bot_profile_interval_s is None
                else round(float(bot_profile_interval_s), 6)
            ),
            "bot_profile_log_lines": bool(bot_profile_log_lines),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha1(digest_payload.encode("utf-8")).hexdigest()[:10]
    stem = f"{mode}_{level_hint}_n{len(selectors)}_{digest}"
    return sanitize_token(stem)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def tracepack_meta_path(json_path: Path) -> Path:
    name = json_path.name
    if name.endswith(".tracepack.json"):
        return json_path.with_name(name[: -len(".tracepack.json")] + ".meta.json")
    return json_path.with_name(f"{json_path.stem}.meta.json")


def _trace_entry_label(entry: dict[str, Any], *, index: int) -> str:
    selector = str(entry.get("run_key") or entry.get("selector") or "").strip()
    if selector:
        return selector
    level = str(entry.get("level") or "").strip()
    scenario = str(entry.get("scenario") or "").strip()
    seed = entry.get("seed")
    if level:
        scenario_part = f":{scenario}" if scenario else ""
        seed_part = f":{seed}" if seed is not None else ""
        return f"{level}{scenario_part}{seed_part}"
    return f"run_index[{index}]"


def validate_cached_tracepack_assets(
    json_path: Path,
    *,
    outputs_root: Path,
) -> str | None:
    try:
        payload = load_json(json_path)
    except Exception as exc:
        return f"invalid tracepack json ({type(exc).__name__}: {exc})"

    trace_root = artifact_path(
        str(payload.get("trace_root_path") or payload.get("trace_root_rel") or ""),
        outputs_root=outputs_root,
    )
    if trace_root is None:
        return "missing trace root metadata"
    if not trace_root.exists():
        return f"missing trace root directory: {trace_root}"

    entries = payload.get("run_index")
    if not isinstance(entries, list) or not entries:
        records = payload.get("records")
        if isinstance(records, list) and records:
            entries = records
        else:
            return "missing run trace index"

    for index, item in enumerate(entries):
        if not isinstance(item, dict):
            return f"invalid run trace entry at index {index}"
        label = _trace_entry_label(item, index=index)
        trace_path = artifact_path(
            str(item.get("trace_path") or item.get("trace_rel_path") or ""),
            outputs_root=outputs_root,
        )
        if trace_path is None:
            return f"missing trace path for {label}"
        if not trace_path.exists():
            return f"missing trace json for {label}: {trace_path}"

        preview_path_value = str(
            item.get("trace_preview_path") or item.get("trace_preview_rel_path") or ""
        ).strip()
        if preview_path_value:
            preview_path = artifact_path(
                preview_path_value,
                outputs_root=outputs_root,
            )
            if preview_path is None or not preview_path.exists():
                return f"missing preview png for {label}: {preview_path_value}"

    return None


def run_command(cmd: list[str], *, repo_root: Path | None = None) -> tuple[int, str]:
    print("# run")
    print(" ".join(cmd))
    proc = subprocess.run(
        cmd,
        cwd=(repo_root or _REPO_ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    output = str(proc.stdout or "")
    if output:
        print(output, end="" if output.endswith("\n") else "\n")
    return int(proc.returncode), output


def load_or_run(
    *,
    commit: str,
    stem: str,
    mode: str,
    selectors: list[str],
    bot: str,
    trace_detail: str,
    bot_config_path: str | None,
    bot_profile_enabled: bool,
    bot_profile_interval_s: float | None,
    bot_profile_log_lines: bool,
    results_root: Path,
    reuse: bool,
    allow_run: bool,
    command_builder: Callable[..., list[str]],
    repo_root: Path | None = None,
) -> tuple[Path, Path, bool]:
    out_dir = results_root / commit
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{stem}.tracepack.json"
    meta_path = out_dir / f"{stem}.meta.json"
    outputs_root = results_root.parent.resolve()

    expected_meta = {
        "mode": mode,
        "selectors": selectors,
        "bot": bot,
        "trace_detail": trace_detail,
        "bot_config_path": (None if not bot_config_path else str(bot_config_path)),
        "worker_mode": "default",
        "bot_profile_enabled": bool(bot_profile_enabled),
        "bot_profile_interval_s": (
            None if bot_profile_interval_s is None else float(bot_profile_interval_s)
        ),
        "bot_profile_log_lines": bool(bot_profile_log_lines),
    }
    cache_issue: str | None = None
    if reuse and json_path.exists() and meta_path.exists():
        try:
            existing = load_json(meta_path)
            if all(existing.get(k) == v for k, v in expected_meta.items()):
                cache_issue = validate_cached_tracepack_assets(
                    json_path,
                    outputs_root=outputs_root,
                )
                if cache_issue is None:
                    print(f"# cache hit: {json_path}")
                    return json_path, meta_path, True
                print(f"# cache stale: {cache_issue}")
        except Exception:
            pass

    if not allow_run:
        if cache_issue is not None:
            raise SystemExit(
                f"Incomplete cache for commit {commit}: {cache_issue}. "
                "Run this pack from that commit once to seed cache."
            )
        raise SystemExit(
            f"Missing cache for commit {commit}: {json_path.name}. "
            "Run this pack from that commit once to seed cache."
        )

    cmd = command_builder(
        selectors=selectors,
        bot=bot,
        bot_config_path=bot_config_path,
        json_path=str(json_path),
        trace_detail=trace_detail,
        bot_profile_enabled=bool(bot_profile_enabled),
        bot_profile_interval_s=bot_profile_interval_s,
        bot_profile_log_lines=bool(bot_profile_log_lines),
    )
    if repo_root is None:
        code, output = run_command(cmd)
    else:
        code, output = run_command(cmd, repo_root=repo_root)
    if code not in (0, 1):
        worker_error_markers = (
            "Batch workers unavailable",
            "refusing implicit sequential fallback",
        )
        if any(marker in output for marker in worker_error_markers):
            raise SystemExit(
                "Benchmark aborted: parallel workers are unavailable and sequential fallback is disabled.\n"
                "Please resolve process/worker support on this machine, then rerun."
            )
        raise SystemExit(f"Benchmark command failed with exit code {code}")
    if not json_path.exists():
        raise SystemExit(f"Expected benchmark JSON not found: {json_path}")
    cache_issue = validate_cached_tracepack_assets(
        json_path,
        outputs_root=outputs_root,
    )
    if cache_issue is not None:
        raise SystemExit(f"Benchmark produced incomplete tracepack: {cache_issue}")

    payload = {
        **expected_meta,
        "commit": commit,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "json_path": str(json_path),
        "bench_exit_code": int(code),
    }
    write_json(meta_path, payload)
    return json_path, meta_path, False


__all__ = [
    "git_rev_parse",
    "load_json",
    "load_or_run",
    "run_command",
    "selector_pack_stem",
    "validate_cached_tracepack_assets",
    "workspace_key",
    "write_json",
]
