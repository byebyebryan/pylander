from __future__ import annotations

import argparse
from collections.abc import Sequence
import hashlib
import json
from pathlib import Path
from typing import Any

from app.benchmark_cache import (
    git_rev_parse,
    load_json,
    load_or_run,
    selector_pack_stem,
    write_json,
)
from app.benchmark_context import (
    build_auto_intent,
    build_inspect_payload,
    default_missing_baseline_policy,
    load_intent,
)
from app.benchmark_compare import print_compare
from app.benchmark_seed import seed_cache_from_worktree
from app.selector_pack import (
    ResolvedSelectorPack,
    build_bench_command,
    build_selectors,
)
from utils.tracebundle import sanitize_token

_REPO_ROOT = Path(__file__).resolve().parents[1]
_MISSING_CACHE_PREFIXES = ("Missing cache for commit", "Incomplete cache for commit")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Run cached Pylander benchmarks with optional baseline compare"
    )
    ap.add_argument(
        "--mode", choices=("smoke", "quick", "full", "focused"), default=None
    )
    ap.add_argument(
        "--seed-spec", default=None, help="Override default seed range, e.g. 0-9"
    )
    ap.add_argument(
        "--selectors",
        nargs="*",
        default=[],
        help=(
            "Focused selectors or group aliases "
            "(@terminal, @terminal_flight, @plunge, @terminal_plunge)"
        ),
    )
    ap.add_argument(
        "--exclude-levels",
        nargs="*",
        default=[],
        help="Levels to exclude from auto packs (csv or repeated)",
    )
    ap.add_argument(
        "--observe-only-levels",
        nargs="*",
        default=[],
        help="Levels to keep as observation-only (csv or repeated)",
    )
    ap.add_argument("--bot", default="pdg")
    ap.add_argument(
        "--trace-detail", choices=("report", "replay", "debug"), default="report"
    )
    ap.add_argument("--bot-config", default=None)
    ap.add_argument(
        "--bot-profile",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable bot compute profiling in benchmark runs (default: on)",
    )
    ap.add_argument(
        "--bot-profile-interval-s",
        type=float,
        default=None,
        help="Profiler report interval in seconds (when profiler logs are enabled)",
    )
    ap.add_argument(
        "--bot-profile-logs",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Enable periodic profiler logs in benchmark output (default: off)",
    )
    ap.add_argument(
        "--baseline-ref",
        default="auto",
        help="Git ref to compare against, 'auto' for inferred baseline, or 'none' to disable compare",
    )
    ap.add_argument(
        "--missing-baseline",
        choices=("skip", "seed", "error"),
        default=None,
        help="Behavior when the baseline cache is missing: skip compare, seed from a temp worktree, or fail",
    )
    ap.add_argument("--results-dir", default="outputs/benchmarks")
    ap.add_argument(
        "--intent-json",
        default=None,
        help="Optional existing intent sidecar describing the planned benchmark run",
    )
    ap.add_argument(
        "--goal-summary",
        default=None,
        help="Optional short summary recorded in an auto-generated intent sidecar",
    )
    ap.add_argument(
        "--context-note",
        action="append",
        default=[],
        help="Optional additional context line recorded in an auto-generated intent sidecar",
    )
    ap.add_argument(
        "--no-reuse",
        action="store_true",
        help="Ignore cache and rerun current commit pack",
    )
    ap.add_argument("--crash-detail-limit", type=int, default=8)
    return ap


def _normalize_baseline_ref(value: str | None) -> str | None:
    token = str(value or "").strip()
    if not token or token.lower() == "none":
        return None
    return token


def _resolve_inputs(
    args: argparse.Namespace,
    *,
    repo_root: Path,
) -> tuple[ResolvedSelectorPack, dict[str, Any], Path, str | None, str, Path]:
    results_root = (repo_root / args.results_dir).resolve()
    intent_path_raw = str(args.intent_json or "").strip()
    if intent_path_raw:
        intent_path = Path(intent_path_raw).expanduser()
        if not intent_path.is_absolute():
            intent_path = (repo_root / intent_path).resolve()
        if not intent_path.exists():
            raise SystemExit(f"Intent JSON not found: {intent_path}")
        intent_payload = load_intent(intent_path)
        repo_context = dict(intent_payload.get("repo_context") or {})
        run_plan = dict(intent_payload.get("run_plan") or {})
        baseline_plan = dict(intent_payload.get("baseline_plan") or {})
        outputs = dict(intent_payload.get("outputs") or {})
        configured_results_root = str(outputs.get("results_root") or "").strip()
        if configured_results_root:
            results_root = Path(configured_results_root).expanduser().resolve()
        mode = str(run_plan.get("mode") or "").strip()
        if not mode:
            raise SystemExit(f"Intent JSON missing run_plan.mode: {intent_path}")
        try:
            pack = build_selectors(
                mode=mode,
                seed_spec=run_plan.get("seed_spec"),
                focused_selectors=list(run_plan.get("selectors") or []),
                exclude_levels=list(run_plan.get("exclude_levels") or []),
                observe_only_levels=list(run_plan.get("observe_only_levels") or []),
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        current_commit = str(
            outputs.get("candidate_commit")
            or repo_context.get("workspace_key")
            or git_rev_parse("HEAD")
        )
        baseline_ref = _normalize_baseline_ref(baseline_plan.get("requested_ref"))
        baseline_commit = (
            str(baseline_plan.get("resolved_ref") or "").strip() or None
            if baseline_ref == "auto"
            else git_rev_parse(str(baseline_ref))
            if baseline_ref is not None
            else None
        )
        return pack, intent_payload, intent_path, baseline_commit, current_commit, results_root

    if not args.mode:
        raise SystemExit("--mode is required unless --intent-json is provided")
    try:
        pack = build_selectors(
            mode=args.mode,
            seed_spec=args.seed_spec,
            focused_selectors=args.selectors,
            exclude_levels=args.exclude_levels,
            observe_only_levels=args.observe_only_levels,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    inspect_payload = build_inspect_payload(
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
    intent_payload, intent_path = build_auto_intent(
        inspect_payload=inspect_payload,
        pack=pack,
        mode=args.mode,
        seed_spec=args.seed_spec,
        bot=str(args.bot),
        trace_detail=str(args.trace_detail),
        bot_config_path=args.bot_config,
        bot_profile_enabled=bool(args.bot_profile),
        bot_profile_interval_s=args.bot_profile_interval_s,
        bot_profile_log_lines=bool(args.bot_profile_logs),
        baseline_ref=_normalize_baseline_ref(args.baseline_ref),
        missing_baseline_policy=args.missing_baseline,
        results_root=results_root,
        goal_summary=args.goal_summary,
        context_notes=list(args.context_note or []),
    )
    write_json(intent_path, intent_payload)
    baseline_plan = dict(intent_payload.get("baseline_plan") or {})
    baseline_ref = _normalize_baseline_ref(baseline_plan.get("requested_ref"))
    baseline_commit = (
        str(baseline_plan.get("resolved_ref") or "").strip() or None
        if baseline_ref == "auto"
        else git_rev_parse(str(baseline_ref))
        if baseline_ref is not None
        else None
    )
    current_commit = str(
        dict(intent_payload.get("repo_context") or {}).get("workspace_key")
        or git_rev_parse("HEAD")
    )
    return pack, intent_payload, intent_path, baseline_commit, current_commit, results_root


def _effective_missing_baseline_policy(
    args: argparse.Namespace, intent_payload: dict[str, Any]
) -> str:
    baseline_plan = dict(intent_payload.get("baseline_plan") or {})
    token = str(
        args.missing_baseline
        or baseline_plan.get("missing_baseline_policy")
        or default_missing_baseline_policy(
            requested_ref=baseline_plan.get("requested_ref")
        )
    ).strip()
    if token not in {"skip", "seed", "error"}:
        return "skip"
    return token


def _record_missing_baseline(
    *,
    intent_payload: dict[str, Any],
    intent_path: Path,
    baseline_commit: str,
    message: str,
) -> None:
    assumptions = [
        str(item).strip()
        for item in intent_payload.get("assumptions") or []
        if str(item).strip()
    ]
    note = (
        "Missing baseline compare was skipped because the resolved baseline cache "
        f"({baseline_commit}) is not available locally."
    )
    if note not in assumptions:
        assumptions.append(note)
        intent_payload["assumptions"] = assumptions
        write_json(intent_path, intent_payload)
    print(message)
    print(
        "\n# baseline\n"
        f"commit={baseline_commit}\n"
        "status=missing_cache\n"
        f"message={message}"
    )


def _load_baseline_artifacts(
    *,
    args: argparse.Namespace,
    intent_payload: dict[str, Any],
    intent_path: Path,
    pack: ResolvedSelectorPack,
    baseline_commit: str,
    current_commit: str,
    results_root: Path,
    stem: str,
    bot_profile_interval_s: float | None,
) -> tuple[Path, Path, bool] | None:
    run_plan = dict(intent_payload.get("run_plan") or {})
    policy = _effective_missing_baseline_policy(args, intent_payload)
    try:
        return load_or_run(
            commit=baseline_commit,
            stem=stem,
            mode=str(run_plan.get("mode") or args.mode),
            selectors=pack.selectors,
            bot=str(run_plan.get("bot") or args.bot),
            trace_detail=str(run_plan.get("trace_detail") or args.trace_detail),
            bot_config_path=run_plan.get("bot_config_path") or args.bot_config,
            bot_profile_enabled=bool(
                run_plan.get("bot_profile_enabled", bool(args.bot_profile))
            ),
            bot_profile_interval_s=bot_profile_interval_s,
            bot_profile_log_lines=bool(
                run_plan.get("bot_profile_log_lines", bool(args.bot_profile_logs))
            ),
            results_root=results_root,
            reuse=True,
            allow_run=(baseline_commit == current_commit),
            command_builder=build_bench_command,
        )
    except SystemExit as exc:
        message = str(exc)
        if not message.startswith(_MISSING_CACHE_PREFIXES):
            raise
        if policy == "seed":
            return seed_cache_from_worktree(
                commit=baseline_commit,
                stem=stem,
                mode=str(run_plan.get("mode") or args.mode),
                selectors=pack.selectors,
                bot=str(run_plan.get("bot") or args.bot),
                trace_detail=str(run_plan.get("trace_detail") or args.trace_detail),
                bot_config_path=run_plan.get("bot_config_path") or args.bot_config,
                bot_profile_enabled=bool(
                    run_plan.get("bot_profile_enabled", bool(args.bot_profile))
                ),
                bot_profile_interval_s=bot_profile_interval_s,
                bot_profile_log_lines=bool(
                    run_plan.get("bot_profile_log_lines", bool(args.bot_profile_logs))
                ),
                results_root=results_root,
                command_builder=build_bench_command,
                repo_root=_REPO_ROOT,
            )
        if policy == "skip":
            _record_missing_baseline(
                intent_payload=intent_payload,
                intent_path=intent_path,
                baseline_commit=baseline_commit,
                message=message,
            )
            return None
        raise


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(list(argv) if argv is not None else None)

    pack, intent_payload, intent_path, baseline_commit, current_commit, results_root = (
        _resolve_inputs(args, repo_root=_REPO_ROOT)
    )
    run_plan = dict(intent_payload.get("run_plan") or {})
    bot_profile_interval_s = (
        None
        if run_plan.get("bot_profile_interval_s") is None
        else max(0.25, float(run_plan["bot_profile_interval_s"]))
    )
    stem = selector_pack_stem(
        mode=str(run_plan.get("mode") or args.mode),
        selectors=pack.selectors,
        bot=str(run_plan.get("bot") or args.bot),
        trace_detail=str(run_plan.get("trace_detail") or args.trace_detail),
        bot_config_path=run_plan.get("bot_config_path") or args.bot_config,
        bot_profile_enabled=bool(
            run_plan.get("bot_profile_enabled", bool(args.bot_profile))
        ),
        bot_profile_interval_s=bot_profile_interval_s,
        bot_profile_log_lines=bool(
            run_plan.get("bot_profile_log_lines", bool(args.bot_profile_logs))
        ),
    )

    cand_json, cand_meta, cand_cached = load_or_run(
        commit=current_commit,
        stem=stem,
        mode=str(run_plan.get("mode") or args.mode),
        selectors=pack.selectors,
        bot=str(run_plan.get("bot") or args.bot),
        trace_detail=str(run_plan.get("trace_detail") or args.trace_detail),
        bot_config_path=run_plan.get("bot_config_path") or args.bot_config,
        bot_profile_enabled=bool(
            run_plan.get("bot_profile_enabled", bool(args.bot_profile))
        ),
        bot_profile_interval_s=bot_profile_interval_s,
        bot_profile_log_lines=bool(
            run_plan.get("bot_profile_log_lines", bool(args.bot_profile_logs))
        ),
        results_root=results_root,
        reuse=not args.no_reuse,
        allow_run=True,
        command_builder=build_bench_command,
    )
    print(f"\n# intent\njson={intent_path}")
    print(
        f"\n# candidate\ncommit={current_commit}\njson={cand_json}\nmeta={cand_meta}\ncached={cand_cached}"
    )
    print(
        "\n# policy\n"
        f"included_levels={','.join(pack.included_levels)}\n"
        f"excluded_levels_effective={','.join(pack.excluded_levels_effective)}\n"
        f"observe_only_levels_effective={','.join(pack.observe_only_levels_effective)}"
    )

    if not baseline_commit:
        return

    baseline_artifacts = _load_baseline_artifacts(
        args=args,
        intent_payload=intent_payload,
        intent_path=intent_path,
        pack=pack,
        baseline_commit=baseline_commit,
        current_commit=current_commit,
        results_root=results_root,
        stem=stem,
        bot_profile_interval_s=bot_profile_interval_s,
    )
    if baseline_artifacts is None:
        return
    base_json, base_meta, base_cached = baseline_artifacts
    print(
        f"\n# baseline\ncommit={baseline_commit}\njson={base_json}\nmeta={base_meta}\ncached={base_cached}"
    )

    candidate_payload = load_json(cand_json)
    baseline_payload = load_json(base_json)
    compare = print_compare(
        baseline_commit=baseline_commit,
        candidate_commit=current_commit,
        baseline_payload=baseline_payload,
        candidate_payload=candidate_payload,
        level_policy=pack.effective_level_policy,
        bot=str(run_plan.get("bot") or args.bot),
        crash_detail_limit=max(0, int(args.crash_detail_limit)),
    )
    compare["baseline_json_path"] = str(base_json.resolve())
    compare["candidate_json_path"] = str(cand_json.resolve())
    policy_digest_payload = json.dumps(
        {
            "policy": pack.effective_level_policy,
            "excluded": pack.excluded_levels_effective,
            "observe_only": pack.observe_only_levels_effective,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    policy_digest = hashlib.sha1(policy_digest_payload.encode("utf-8")).hexdigest()[:8]
    compare_token = sanitize_token(f"compare_vs_{baseline_commit}_{policy_digest}")
    compare_path = cand_json.with_name(f"{cand_json.stem}.{compare_token}.json")
    write_json(compare_path, compare)
    print(f"\n# compare_report\njson={compare_path}")


__all__ = ["build_parser", "main"]


if __name__ == "__main__":
    main()
