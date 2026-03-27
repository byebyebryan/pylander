from __future__ import annotations

import os
import subprocess
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from app.benchmark_cache import load_or_run

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_git(args: list[str], *, repo_root: Path) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


@contextmanager
def temporary_worktree(commit: str, *, repo_root: Path = _REPO_ROOT) -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="pylander-bench-") as temp_root:
        worktree_path = Path(temp_root) / "repo"
        _run_git(["worktree", "add", "--detach", str(worktree_path), str(commit)], repo_root=repo_root)
        try:
            yield worktree_path
        finally:
            _run_git(["worktree", "remove", "--force", str(worktree_path)], repo_root=repo_root)
            _run_git(["worktree", "prune"], repo_root=repo_root)


def seed_cache_from_worktree(
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
    command_builder: Callable[..., list[str]],
    repo_root: Path = _REPO_ROOT,
) -> tuple[Path, Path, bool]:
    print(f"# seed baseline cache: {commit}")

    def _seed_command_builder(**kwargs: object) -> list[str]:
        cmd = list(command_builder(**kwargs))
        if os.environ.get("VIRTUAL_ENV") and cmd[:2] == ["uv", "run"]:
            return ["uv", "run", "--active", *cmd[2:]]
        return cmd

    with temporary_worktree(commit, repo_root=repo_root) as worktree_path:
        return load_or_run(
            commit=commit,
            stem=stem,
            mode=mode,
            selectors=selectors,
            bot=bot,
            trace_detail=trace_detail,
            bot_config_path=bot_config_path,
            bot_profile_enabled=bool(bot_profile_enabled),
            bot_profile_interval_s=bot_profile_interval_s,
            bot_profile_log_lines=bool(bot_profile_log_lines),
            results_root=results_root,
            reuse=True,
            allow_run=True,
            command_builder=_seed_command_builder,
            repo_root=worktree_path,
        )


__all__ = ["seed_cache_from_worktree", "temporary_worktree"]
