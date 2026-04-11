from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bot_framework.benchmark_cache import (
    git_rev_parse,
    load_json,
    selector_pack_stem,
    tracepack_meta_path,
    workspace_key,
    write_json,
)
from bot_framework.selector_pack import ResolvedSelectorPack, build_selectors

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SKIPPABLE_AREAS = {"benchmark_tooling", "docs", "skills", "tests"}
_BENCHMARK_TOOLING_FILES = {
    "bot_framework/bench.py",
    "bot_framework/benchmark_cache.py",
    "bot_framework/benchmark_compare.py",
    "tooling/output_viewer.py",
    "tooling/plot_pack.py",
    "bot_framework/run_cached_benchmark.py",
    "bot_framework/selector_pack.py",
    "tooling/serve_outputs.py",
    "tooling/trace_bundle.py",
    "tooling/tracebundle.py",
    "tooling/traceviewer.py",
}
_DOC_FILES = {"AGENTS.md", "README.md"}


def _git_text(args: list[str]) -> str:
    return subprocess.check_output(["git", *args], cwd=_REPO_ROOT, text=True).strip()


def _git_lines(args: list[str]) -> list[str]:
    text = _git_text(args)
    return [line.strip() for line in text.splitlines() if line.strip()]


def classify_path(path_value: str) -> str:
    path = str(path_value).strip().replace("\\", "/")
    if not path:
        return "other_code"
    if path in _DOC_FILES or path.startswith("docs/"):
        return "docs"
    if path.startswith(".agents/skills/"):
        return "skills"
    if path.startswith("tests/"):
        return "tests"
    if path in _BENCHMARK_TOOLING_FILES or path.startswith("bot_framework/benchmark_"):
        return "benchmark_tooling"
    if path.startswith("bots/"):
        return "bot_logic"
    if path.startswith("levels/"):
        return "level_logic"
    if path.startswith("core/") or path.startswith("runtime/"):
        return "core_runtime"
    if path in {"main.py", "game.py"}:
        return "core_runtime"
    if path.startswith("app/") or path.startswith("bot_framework/"):
        return "app_runtime"
    return "other_code"


def classify_paths(paths: Iterable[str]) -> list[str]:
    return sorted({classify_path(path) for path in paths if str(path).strip()})


def is_skippable_area_set(areas: Iterable[str]) -> bool:
    normalized = {str(area).strip() for area in areas if str(area).strip()}
    return bool(normalized) and normalized.issubset(_SKIPPABLE_AREAS)


def current_changed_files() -> list[str]:
    changed = set(_git_lines(["diff", "--cached", "--name-only", "HEAD"]))
    changed.update(_git_lines(["diff", "--name-only", "HEAD"]))
    changed.update(_git_lines(["ls-files", "--others", "--exclude-standard"]))
    return sorted(path for path in changed if path)


def _commit_subject(commit: str) -> str:
    return _git_text(["show", "-s", "--format=%s", commit])


def commit_changed_files(commit: str) -> list[str]:
    return _git_lines(
        [
            "show",
            "--pretty=format:",
            "--first-parent",
            "--name-only",
            "--diff-filter=ACDMRTUXB",
            commit,
        ]
    )


def first_parent_commits(start_ref: str, *, limit: int = 12) -> list[str]:
    if not str(start_ref).strip():
        return []
    try:
        return _git_lines(
            [
                "rev-list",
                "--first-parent",
                f"--max-count={max(1, int(limit))}",
                start_ref,
            ]
        )
    except subprocess.CalledProcessError:
        return []


def _safe_parent_ref(ref: str) -> str | None:
    try:
        return _git_text(["rev-parse", f"{ref}^"])
    except subprocess.CalledProcessError:
        return None


def resolve_auto_baseline(*, dirty: bool, limit: int = 24) -> dict[str, Any]:
    start_ref = "HEAD" if dirty else _safe_parent_ref("HEAD")
    inspected: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    resolved: dict[str, Any] | None = None

    for commit in first_parent_commits(str(start_ref or ""), limit=limit):
        short_commit = git_rev_parse(commit)
        files = commit_changed_files(commit)
        areas = classify_paths(files)
        skippable = is_skippable_area_set(areas)
        entry = {
            "commit": short_commit,
            "subject": _commit_subject(commit),
            "changed_files": files,
            "touched_areas": areas,
            "skip_candidate": bool(skippable),
            "skip_reason": (
                "changed files are limited to docs, skills, tests, or benchmark tooling"
                if skippable
                else "commit touches likely behavior-affecting code"
            ),
        }
        inspected.append(entry)
        if skippable:
            skipped.append(entry)
            continue
        resolved = entry
        break

    return {
        "strategy": "auto",
        "start_ref": ("HEAD" if dirty else "HEAD^"),
        "resolved_commit": (None if resolved is None else resolved["commit"]),
        "resolved_subject": (None if resolved is None else resolved["subject"]),
        "skipped_commits": skipped,
        "inspected_commits": inspected,
    }


def intent_sidecar_path(candidate_json_path: Path) -> Path:
    return candidate_json_path.with_name(f"{candidate_json_path.stem}.intent.json")


def analysis_sidecar_path(candidate_json_path: Path) -> Path:
    return candidate_json_path.with_name(f"{candidate_json_path.stem}.analysis.json")


def inspect_sidecar_path(candidate_json_path: Path) -> Path:
    return candidate_json_path.with_name(f"{candidate_json_path.stem}.inspect.json")


def compare_sidecar_candidates(candidate_json_path: Path) -> list[Path]:
    pattern = f"{candidate_json_path.stem}.compare_vs_*.json"
    return sorted(candidate_json_path.parent.glob(pattern))


def discover_compare_path(candidate_json_path: Path) -> Path | None:
    matches = compare_sidecar_candidates(candidate_json_path)
    if len(matches) == 1:
        return matches[0]
    return None


def default_missing_baseline_policy(*, requested_ref: str | None) -> str:
    token = str(requested_ref or "").strip()
    if not token or token == "none":
        return "skip"
    if token == "auto":
        return "skip"
    return "error"


def build_pack_preview(
    *,
    mode: str,
    seed_spec: str | None,
    selectors: list[str],
    exclude_levels: list[str],
    observe_only_levels: list[str],
    bot: str,
    trace_detail: str,
    bot_config_path: str | None,
    bot_profile_enabled: bool,
    bot_profile_interval_s: float | None,
    bot_profile_log_lines: bool,
    results_root: Path,
    current_commit: str,
    baseline_commit: str | None,
) -> dict[str, Any]:
    pack: ResolvedSelectorPack = build_selectors(
        mode=mode,
        seed_spec=seed_spec,
        focused_selectors=selectors,
        exclude_levels=exclude_levels,
        observe_only_levels=observe_only_levels,
    )
    stem = selector_pack_stem(
        mode=mode,
        selectors=pack.selectors,
        bot=bot,
        trace_detail=trace_detail,
        bot_config_path=bot_config_path,
        bot_profile_enabled=bool(bot_profile_enabled),
        bot_profile_interval_s=bot_profile_interval_s,
        bot_profile_log_lines=bool(bot_profile_log_lines),
    )
    candidate_json = (
        results_root / current_commit / f"{stem}.tracepack.json"
    ).resolve()
    candidate_meta = tracepack_meta_path(candidate_json)
    candidate_inspect = inspect_sidecar_path(candidate_json)
    preview: dict[str, Any] = {
        "mode": mode,
        "seed_spec": seed_spec,
        "selectors": pack.selectors,
        "policy": {
            "included_levels": pack.included_levels,
            "excluded_levels_effective": pack.excluded_levels_effective,
            "observe_only_levels_effective": pack.observe_only_levels_effective,
        },
        "stem": stem,
        "candidate_json": str(candidate_json),
        "candidate_meta": str(candidate_meta),
        "candidate_intent": str(intent_sidecar_path(candidate_json)),
        "candidate_analysis": str(analysis_sidecar_path(candidate_json)),
        "candidate_inspect": str(candidate_inspect),
        "candidate_cache_exists": bool(
            candidate_json.exists() and candidate_meta.exists()
        ),
    }
    if baseline_commit:
        baseline_json = (
            results_root / baseline_commit / f"{stem}.tracepack.json"
        ).resolve()
        baseline_meta = tracepack_meta_path(baseline_json)
        preview["baseline_json"] = str(baseline_json)
        preview["baseline_meta"] = str(baseline_meta)
        preview["baseline_cache_exists"] = bool(
            baseline_json.exists() and baseline_meta.exists()
        )
    return preview


def build_inspect_payload(
    *,
    mode: str | None,
    seed_spec: str | None,
    selectors: list[str],
    exclude_levels: list[str],
    observe_only_levels: list[str],
    bot: str,
    trace_detail: str,
    bot_config_path: str | None,
    bot_profile_enabled: bool,
    bot_profile_interval_s: float | None,
    bot_profile_log_lines: bool,
    baseline_ref: str | None,
    results_root: Path,
) -> dict[str, Any]:
    head_commit = git_rev_parse("HEAD")
    current_key = workspace_key()
    dirty = current_key != head_commit
    changed_files = current_changed_files()
    touched_areas = classify_paths(changed_files)
    auto_baseline = resolve_auto_baseline(dirty=dirty)

    requested_ref = None if baseline_ref in {None, "", "none"} else str(baseline_ref)
    explicit_commit = None
    if requested_ref and requested_ref != "auto":
        explicit_commit = git_rev_parse(requested_ref)

    payload: dict[str, Any] = {
        "schema": "pylander.benchmark.inspect.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "repo_context": {
            "repo_root": str(_REPO_ROOT),
            "head_commit": head_commit,
            "workspace_key": current_key,
            "dirty": dirty,
            "changed_files": changed_files,
            "touched_areas": touched_areas,
        },
        "baseline": {
            "requested_ref": requested_ref,
            "explicit_commit": explicit_commit,
            "auto": auto_baseline,
        },
        "recent_first_parent": auto_baseline.get("inspected_commits") or [],
    }

    if mode:
        selected_baseline = (
            explicit_commit
            if explicit_commit is not None
            else auto_baseline.get("resolved_commit")
            if requested_ref == "auto"
            else None
        )
        payload["pack_preview"] = build_pack_preview(
            mode=mode,
            seed_spec=seed_spec,
            selectors=selectors,
            exclude_levels=exclude_levels,
            observe_only_levels=observe_only_levels,
            bot=bot,
            trace_detail=trace_detail,
            bot_config_path=bot_config_path,
            bot_profile_enabled=bool(bot_profile_enabled),
            bot_profile_interval_s=bot_profile_interval_s,
            bot_profile_log_lines=bool(bot_profile_log_lines),
            results_root=results_root,
            current_commit=current_key,
            baseline_commit=selected_baseline,
        )
    return payload


def build_auto_intent(
    *,
    inspect_payload: dict[str, Any],
    pack: ResolvedSelectorPack,
    mode: str,
    seed_spec: str | None,
    bot: str,
    trace_detail: str,
    bot_config_path: str | None,
    bot_profile_enabled: bool,
    bot_profile_interval_s: float | None,
    bot_profile_log_lines: bool,
    baseline_ref: str | None,
    missing_baseline_policy: str,
    results_root: Path,
    goal_summary: str | None = None,
    context_notes: list[str] | None = None,
) -> tuple[dict[str, Any], Path]:
    repo_context = dict(inspect_payload.get("repo_context") or {})
    baseline_payload = dict(inspect_payload.get("baseline") or {})
    current_key = str(repo_context.get("workspace_key") or git_rev_parse("HEAD"))
    requested_ref = None if baseline_ref in {None, "", "none"} else str(baseline_ref)
    resolved_missing_baseline_policy = str(
        missing_baseline_policy
        or default_missing_baseline_policy(requested_ref=requested_ref)
    )
    explicit_commit = baseline_payload.get("explicit_commit")
    auto_payload = dict(baseline_payload.get("auto") or {})
    resolved_commit = (
        explicit_commit
        if requested_ref and requested_ref != "auto"
        else auto_payload.get("resolved_commit")
        if requested_ref == "auto"
        else None
    )
    bot_profile_interval_s = (
        None
        if bot_profile_interval_s is None
        else max(0.25, float(bot_profile_interval_s))
    )
    stem = selector_pack_stem(
        mode=mode,
        selectors=pack.selectors,
        bot=bot,
        trace_detail=trace_detail,
        bot_config_path=bot_config_path,
        bot_profile_enabled=bool(bot_profile_enabled),
        bot_profile_interval_s=bot_profile_interval_s,
        bot_profile_log_lines=bool(bot_profile_log_lines),
    )
    candidate_json = (results_root / current_key / f"{stem}.tracepack.json").resolve()
    sidecar_path = intent_sidecar_path(candidate_json)
    notes = [str(item).strip() for item in (context_notes or []) if str(item).strip()]
    request_source = "explicit"
    if notes:
        request_source = "mixed"
    if requested_ref == "auto":
        request_source = "mixed" if request_source == "explicit" else request_source
    summary = (
        str(goal_summary).strip()
        if str(goal_summary or "").strip()
        else (
            f"Focused benchmark for {', '.join(pack.selectors[:3])}"
            if mode == "focused"
            else f"{mode.title()} benchmark run for {bot}"
        )
    )
    assumptions: list[str] = []
    if requested_ref == "auto" and resolved_commit is None:
        assumptions.append(
            "No auto baseline commit was resolved; compare output will be omitted."
        )
    if not notes:
        assumptions.append(
            "Conversation context was not provided explicitly; intent is based on CLI inputs and repo state only."
        )
    payload = {
        "schema": "pylander.benchmark.intent.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "request_source": request_source,
        "goal_summary": summary,
        "conversation_context": notes,
        "repo_context": repo_context,
        "run_plan": {
            "mode": mode,
            "seed_spec": seed_spec,
            "selectors": pack.selectors,
            "exclude_levels": pack.excluded_levels_effective,
            "observe_only_levels": pack.observe_only_levels_effective,
            "bot": bot,
            "trace_detail": trace_detail,
            "bot_config_path": bot_config_path,
            "bot_profile_enabled": bool(bot_profile_enabled),
            "bot_profile_interval_s": bot_profile_interval_s,
            "bot_profile_log_lines": bool(bot_profile_log_lines),
        },
        "baseline_plan": {
            "strategy": (
                "explicit"
                if requested_ref and requested_ref != "auto"
                else "auto"
                if requested_ref == "auto"
                else "none"
            ),
            "requested_ref": requested_ref,
            "missing_baseline_policy": resolved_missing_baseline_policy,
            "resolved_ref": resolved_commit,
            "skipped_commits": list(auto_payload.get("skipped_commits") or []),
        },
        "outputs": {
            "results_root": str(results_root.resolve()),
            "candidate_commit": current_key,
            "stem": stem,
            "candidate_json": str(candidate_json),
            "intent_json": str(sidecar_path),
        },
        "assumptions": assumptions,
    }
    return payload, sidecar_path


def load_intent(path: Path) -> dict[str, Any]:
    return load_json(path)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Inspect benchmark context, baseline candidates, and cache paths"
    )
    ap.add_argument(
        "--mode", choices=("smoke", "quick", "full", "focused"), default=None
    )
    ap.add_argument("--seed-spec", default=None)
    ap.add_argument("--selectors", nargs="*", default=[])
    ap.add_argument("--exclude-levels", nargs="*", default=[])
    ap.add_argument("--observe-only-levels", nargs="*", default=[])
    ap.add_argument("--bot", default="pdg")
    ap.add_argument(
        "--trace-detail", choices=("report", "replay", "debug"), default="report"
    )
    ap.add_argument("--bot-config", default=None)
    ap.add_argument(
        "--bot-profile", action=argparse.BooleanOptionalAction, default=True
    )
    ap.add_argument("--bot-profile-interval-s", type=float, default=None)
    ap.add_argument(
        "--bot-profile-logs", action=argparse.BooleanOptionalAction, default=False
    )
    ap.add_argument("--baseline-ref", default="auto")
    ap.add_argument("--results-dir", default="outputs/benchmarks")
    ap.add_argument(
        "--output-json",
        default=None,
        help="Optional path to write inspect JSON. Use 'auto' with a resolved pack preview.",
    )
    return ap


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    results_root = (_REPO_ROOT / args.results_dir).resolve()
    try:
        payload = build_inspect_payload(
            mode=args.mode,
            seed_spec=args.seed_spec,
            selectors=list(args.selectors or []),
            exclude_levels=list(args.exclude_levels or []),
            observe_only_levels=list(args.observe_only_levels or []),
            bot=str(args.bot),
            trace_detail=str(args.trace_detail),
            bot_config_path=args.bot_config,
            bot_profile_enabled=bool(args.bot_profile),
            bot_profile_interval_s=args.bot_profile_interval_s,
            bot_profile_log_lines=bool(args.bot_profile_logs),
            baseline_ref=args.baseline_ref,
            results_root=results_root,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    output_json = str(args.output_json or "").strip()
    if output_json:
        if output_json == "auto":
            pack_preview = dict(payload.get("pack_preview") or {})
            candidate_json = str(pack_preview.get("candidate_json") or "").strip()
            if not candidate_json:
                raise SystemExit(
                    "--output-json auto requires a resolved pack preview (--mode ...)"
                )
            output_path = inspect_sidecar_path(Path(candidate_json))
        else:
            output_path = Path(output_json).expanduser().resolve()
        write_json(output_path, payload)
        print("# inspect")
        print(f"json={output_path}")
        return

    print(json.dumps(payload, indent=2, sort_keys=True))


__all__ = [
    "analysis_sidecar_path",
    "build_auto_intent",
    "build_inspect_payload",
    "build_pack_preview",
    "build_parser",
    "classify_path",
    "classify_paths",
    "commit_changed_files",
    "compare_sidecar_candidates",
    "current_changed_files",
    "discover_compare_path",
    "default_missing_baseline_policy",
    "intent_sidecar_path",
    "inspect_sidecar_path",
    "is_skippable_area_set",
    "load_intent",
    "main",
    "resolve_auto_baseline",
]


if __name__ == "__main__":
    main()
