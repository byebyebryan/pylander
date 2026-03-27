from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from app.benchmark_cache import (
    git_rev_parse,
    load_json,
    load_or_run,
    selector_pack_stem,
    workspace_key,
    write_json,
)
from app.benchmark_compare import print_compare
from app.selector_pack import (
    ResolvedSelectorPack,
    build_bench_command,
    build_selectors,
)
from utils.tracebundle import sanitize_token

_REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Run cached Pylander benchmarks with optional baseline compare"
    )
    ap.add_argument(
        "--mode", choices=("smoke", "quick", "full", "focused"), required=True
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
        "--baseline-ref", default=None, help="Git ref to compare against (e.g. main)"
    )
    ap.add_argument("--results-dir", default="outputs/benchmarks")
    ap.add_argument(
        "--no-reuse",
        action="store_true",
        help="Ignore cache and rerun current commit pack",
    )
    ap.add_argument("--crash-detail-limit", type=int, default=8)
    args = ap.parse_args()

    try:
        pack: ResolvedSelectorPack = build_selectors(
            mode=args.mode,
            seed_spec=args.seed_spec,
            focused_selectors=args.selectors,
            exclude_levels=args.exclude_levels,
            observe_only_levels=args.observe_only_levels,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    current_commit = workspace_key()
    baseline_commit = git_rev_parse(args.baseline_ref) if args.baseline_ref else None
    bot_profile_interval_s = (
        None
        if args.bot_profile_interval_s is None
        else max(0.25, float(args.bot_profile_interval_s))
    )
    stem = selector_pack_stem(
        mode=args.mode,
        selectors=pack.selectors,
        bot=args.bot,
        trace_detail=args.trace_detail,
        bot_config_path=args.bot_config,
        bot_profile_enabled=bool(args.bot_profile),
        bot_profile_interval_s=bot_profile_interval_s,
        bot_profile_log_lines=bool(args.bot_profile_logs),
    )
    results_root = (_REPO_ROOT / args.results_dir).resolve()

    cand_json, cand_meta, cand_cached = load_or_run(
        commit=current_commit,
        stem=stem,
        mode=args.mode,
        selectors=pack.selectors,
        bot=args.bot,
        trace_detail=args.trace_detail,
        bot_config_path=args.bot_config,
        bot_profile_enabled=bool(args.bot_profile),
        bot_profile_interval_s=bot_profile_interval_s,
        bot_profile_log_lines=bool(args.bot_profile_logs),
        results_root=results_root,
        reuse=not args.no_reuse,
        allow_run=True,
        command_builder=build_bench_command,
    )
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

    base_json, base_meta, base_cached = load_or_run(
        commit=baseline_commit,
        stem=stem,
        mode=args.mode,
        selectors=pack.selectors,
        bot=args.bot,
        trace_detail=args.trace_detail,
        bot_config_path=args.bot_config,
        bot_profile_enabled=bool(args.bot_profile),
        bot_profile_interval_s=bot_profile_interval_s,
        bot_profile_log_lines=bool(args.bot_profile_logs),
        results_root=results_root,
        reuse=True,
        allow_run=(baseline_commit == current_commit),
        command_builder=build_bench_command,
    )
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
        bot=args.bot,
        crash_detail_limit=max(0, int(args.crash_detail_limit)),
    )
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


__all__ = ["main"]


if __name__ == "__main__":
    main()
