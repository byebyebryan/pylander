from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Iterable

from app.selector import parse_selector, parse_seed_spec
from game.core.level_capabilities import (
    BenchmarkLevelPolicy,
    LevelBenchmarkProfile,
)
from game.core.selector_codec import render_selector
from bot_framework.scenarios import (
    expand_scenario_bindings as expand_selector_bindings,
    list_scenario_roots,
    resolve_scenario_binding as resolve_selector_binding,
    resolve_public_scenario_benchmark_profile as resolve_public_level_benchmark_profile,
)
from game.levels.registry import list_public_levels as list_gameplay_levels

DEFAULT_SEEDS = {
    "smoke": "0-1",
    "quick": "0-4",
    "full": "0-9",
    "focused": "0-9",
}

FOCUSED_SELECTOR_GROUPS: dict[str, tuple[str, ...]] = {
    "terminal": ("terminal",),
    "terminal_flight": ("terminal",),
    "plunge": ("plunge",),
    "terminal_plunge": ("terminal", "plunge"),
}


@dataclass(frozen=True)
class ResolvedSelectorPack:
    selectors: list[str]
    effective_level_policy: dict[str, BenchmarkLevelPolicy]
    included_levels: list[str]
    excluded_levels_effective: list[str]
    observe_only_levels_effective: list[str]


def _seed_spec_str(spec: str) -> str:
    seeds = parse_seed_spec(spec)
    if not seeds:
        raise ValueError(f"Seed spec '{spec}' produced no seeds")
    if len(seeds) == 1:
        return str(seeds[0])
    contiguous = seeds == list(range(seeds[0], seeds[-1] + 1))
    return (
        f"{seeds[0]}-{seeds[-1]}"
        if contiguous
        else ",".join(str(seed) for seed in seeds)
    )


def split_csv(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    for item in values:
        for token in str(item).split(","):
            normalized = token.strip()
            if normalized:
                out.append(normalized)
    return out


def _split_focused_selectors(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    for item in values:
        raw = str(item).strip()
        if not raw:
            continue
        # Preserve CSV seed specs for level:scenario:seed_csv selectors.
        if raw.count(":") >= 2:
            out.append(raw)
            continue
        out.extend(split_csv([raw]))
    return out


def _resolve_focused_selector_group(
    raw: str, *, known_levels: set[str]
) -> tuple[str, ...] | None:
    token = str(raw).strip().lower()
    if not token.startswith("@"):
        return None

    group_name = token[1:].strip()
    if not group_name:
        raise ValueError(
            "Empty focused selector group '@'. Expected a token such as @terminal"
        )

    levels = FOCUSED_SELECTOR_GROUPS.get(group_name)
    if levels is None:
        known = ", ".join(f"@{name}" for name in sorted(FOCUSED_SELECTOR_GROUPS))
        raise ValueError(
            f"Unknown focused selector group '@{group_name}'. Expected one of: {known}"
        )

    missing = sorted(
        level_name for level_name in levels if level_name not in known_levels
    )
    if missing:
        raise ValueError(
            f"Focused selector group '@{group_name}' references unknown levels: "
            f"{', '.join(missing)}"
        )
    return levels


def _load_level_profiles() -> dict[str, LevelBenchmarkProfile]:
    from game.levels.registry import load_level_class

    out: dict[str, LevelBenchmarkProfile] = {}
    for level_name in list_gameplay_levels():
        level_cls = load_level_class(level_name)
        out[level_name] = level_cls.benchmark_profile()
    for level_name in list_scenario_roots():
        out[level_name] = resolve_public_level_benchmark_profile(level_name)
    return out


def _parse_policy_override_levels(
    values: Iterable[str],
    *,
    known_levels: set[str],
    flag_name: str,
) -> set[str]:
    out: set[str] = set()
    for token in split_csv(values):
        if token not in known_levels:
            known = ", ".join(sorted(known_levels))
            raise ValueError(
                f"Unknown level '{token}' in {flag_name}. Expected one of: {known}"
            )
        out.add(token)
    return out


def _resolve_effective_policy(
    profiles: dict[str, LevelBenchmarkProfile],
    *,
    exclude_levels: set[str],
    observe_only_levels: set[str],
) -> dict[str, BenchmarkLevelPolicy]:
    overlap = sorted(exclude_levels & observe_only_levels)
    if overlap:
        raise ValueError(
            "Policy override conflict: levels cannot be both excluded and observe-only: "
            f"{', '.join(overlap)}"
        )

    out: dict[str, BenchmarkLevelPolicy] = {}
    for level_name, profile in profiles.items():
        if level_name in exclude_levels:
            out[level_name] = "excluded"
            continue
        if level_name in observe_only_levels:
            out[level_name] = "observe_only"
            continue
        out[level_name] = profile.policy
    return out


def _selector(
    level: str,
    scenario: str | None,
    seed_spec: str,
    *,
    eval_goal: str = "landing",
) -> str:
    return render_selector(
        level_name=level,
        scenario_name=scenario,
        goal=str(eval_goal or "landing").strip().lower() or "landing",
        seed_token=seed_spec,
    )


def _scenarios_for_mode(profile: LevelBenchmarkProfile, mode: str) -> tuple[str, ...]:
    if mode == "smoke":
        return profile.scenarios.smoke
    if mode == "quick":
        return profile.scenarios.quick
    if mode == "full":
        return profile.scenarios.full
    raise ValueError(f"Unsupported auto-selector mode '{mode}'")


def _build_auto_mode(
    *,
    mode: str,
    seed_spec: str,
    profiles: dict[str, LevelBenchmarkProfile],
    policy_by_level: dict[str, BenchmarkLevelPolicy],
) -> tuple[list[str], set[str]]:
    selectors: list[str] = []
    included: set[str] = set()
    for level_name in sorted(profiles):
        policy = policy_by_level[level_name]
        if policy == "excluded":
            continue
        scenarios = _scenarios_for_mode(profiles[level_name], mode)
        if not scenarios:
            raise ValueError(
                f"Level '{level_name}' has no {mode} scenarios under policy '{policy}'"
            )
        selectors.extend(
            _selector(level_name, scenario, seed_spec, eval_goal="landing")
            for scenario in scenarios
        )
        included.add(level_name)
    return selectors, included


def _build_focused_mode(
    *,
    seed_spec: str,
    selectors_raw: list[str],
    profiles: dict[str, LevelBenchmarkProfile],
    policy_by_level: dict[str, BenchmarkLevelPolicy],
) -> tuple[list[str], set[str]]:
    known_levels = set(profiles)
    selectors: list[str] = []
    included: set[str] = set()

    for raw in _split_focused_selectors(selectors_raw):
        group_levels = _resolve_focused_selector_group(raw, known_levels=known_levels)
        if group_levels is not None:
            for level_name in group_levels:
                profile = profiles[level_name]
                scenarios = profile.scenarios.full
                if scenarios:
                    selectors.extend(
                        _selector(level_name, scenario, seed_spec, eval_goal="landing")
                        for scenario in scenarios
                    )
                else:
                    selectors.append(
                        _selector(level_name, None, seed_spec, eval_goal="landing")
                    )
                included.add(level_name)
            continue

        parsed = parse_selector(raw, default_level=None, known_levels=known_levels)
        level_name = parsed.level_name
        profile = profiles[level_name]
        local_seed = _seed_spec_str((parsed.seed_token or seed_spec).strip())
        local_goal = str(parsed.goal or "landing").strip().lower() or "landing"

        if parsed.scenario_name:
            if "*" in parsed.scenario_path:
                bindings = expand_selector_bindings(
                    level_name,
                    scenario_path=parsed.scenario_path,
                    allow_wildcards=True,
                )
                full_scenarios = set(profile.scenarios.full)
                if not full_scenarios:
                    raise ValueError(
                        f"Selector '{raw}' specifies scenario '{parsed.scenario_name}', but "
                        f"level '{level_name}' has no benchmark scenarios"
                    )
                expanded_scenarios: list[str] = []
                for binding in bindings:
                    scenario_name = binding.scenario_name
                    if scenario_name is None or scenario_name not in full_scenarios:
                        known = ", ".join(profile.scenarios.full)
                        raise ValueError(
                            f"Unknown scenario '{parsed.scenario_name}' for level '{level_name}' "
                            f"in selector '{raw}'. Expected one of: {known}"
                        )
                    expanded_scenarios.append(scenario_name)
                selectors.extend(
                    _selector(
                        level_name,
                        scenario_name,
                        local_seed,
                        eval_goal=local_goal,
                    )
                    for scenario_name in expanded_scenarios
                )
                included.add(level_name)
                continue

            try:
                resolve_selector_binding(level_name, parsed.scenario_path)
            except ValueError as exc:
                known = ", ".join(profile.scenarios.full)
                raise ValueError(
                    f"Unknown scenario '{parsed.scenario_name}' for level '{level_name}' "
                    f"in selector '{raw}'. Expected one of: {known}"
                ) from exc
            selectors.append(
                _selector(
                    level_name,
                    parsed.scenario_name,
                    local_seed,
                    eval_goal=local_goal,
                )
            )
            included.add(level_name)
            continue

        selectors.append(_selector(level_name, None, local_seed, eval_goal=local_goal))
        included.add(level_name)

    _ = policy_by_level  # Explicit selectors win in focused mode.
    return selectors, included


def build_selectors(
    *,
    mode: str,
    seed_spec: str | None = None,
    focused_selectors: list[str] | None = None,
    exclude_levels: list[str] | None = None,
    observe_only_levels: list[str] | None = None,
) -> ResolvedSelectorPack:
    if mode not in DEFAULT_SEEDS:
        raise ValueError(f"Unsupported mode '{mode}'")

    resolved_seed = _seed_spec_str(seed_spec or DEFAULT_SEEDS[mode])
    profiles = _load_level_profiles()
    known_levels = set(profiles)
    excluded = _parse_policy_override_levels(
        exclude_levels or [],
        known_levels=known_levels,
        flag_name="--exclude-levels",
    )
    observe = _parse_policy_override_levels(
        observe_only_levels or [],
        known_levels=known_levels,
        flag_name="--observe-only-levels",
    )
    policy_by_level = _resolve_effective_policy(
        profiles,
        exclude_levels=excluded,
        observe_only_levels=observe,
    )

    if mode == "focused":
        local_focused = list(focused_selectors or [])
        if not local_focused:
            raise ValueError("--selectors is required for mode=focused")
        selectors, included = _build_focused_mode(
            seed_spec=resolved_seed,
            selectors_raw=local_focused,
            profiles=profiles,
            policy_by_level=policy_by_level,
        )
    else:
        selectors, included = _build_auto_mode(
            mode=mode,
            seed_spec=resolved_seed,
            profiles=profiles,
            policy_by_level=policy_by_level,
        )

    deduped: list[str] = []
    seen: set[str] = set()
    for selector in selectors:
        if selector in seen:
            continue
        seen.add(selector)
        deduped.append(selector)

    included_levels = sorted(included)
    excluded_levels_effective = sorted(
        level_name
        for level_name, policy in policy_by_level.items()
        if policy == "excluded"
    )
    observe_only_levels_effective = sorted(
        level_name
        for level_name, policy in policy_by_level.items()
        if policy == "observe_only"
    )

    return ResolvedSelectorPack(
        selectors=deduped,
        effective_level_policy=policy_by_level,
        included_levels=included_levels,
        excluded_levels_effective=excluded_levels_effective,
        observe_only_levels_effective=observe_only_levels_effective,
    )


def build_bench_command(
    *,
    selectors: list[str],
    bot: str = "pdg",
    json_path: str = "auto",
    trace_detail: str | None = None,
    bot_config_path: str | None = None,
    bot_profile_enabled: bool | None = None,
    bot_profile_interval_s: float | None = None,
    bot_profile_log_lines: bool | None = None,
) -> list[str]:
    if not selectors:
        raise ValueError("No selectors resolved")
    cmd = (
        ["uv", "run", "python", "main.py", "bench"]
        + selectors
        + [
            "--bot",
            bot,
            "--json",
            json_path,
        ]
    )
    if trace_detail:
        cmd += ["--trace-detail", str(trace_detail)]
    if bot_config_path:
        cmd += ["--bot-config", str(bot_config_path)]
    if bot_profile_enabled is not None:
        cmd += ["--bot-profile" if bot_profile_enabled else "--no-bot-profile"]
    if bot_profile_log_lines is not None:
        cmd += [
            "--bot-profile-logs" if bot_profile_log_lines else "--no-bot-profile-logs"
        ]
    if bot_profile_interval_s is not None:
        cmd += [
            "--bot-profile-interval-s",
            f"{max(0.25, float(bot_profile_interval_s)):.3f}",
        ]
    return cmd


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Build Pylander benchmark selector packs")
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
            "Focused selectors (level[:layer[:...]][:goal[:seed]]) or group aliases "
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
        help="Profiler report interval in seconds",
    )
    ap.add_argument(
        "--bot-profile-logs",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Enable periodic profiler logs in benchmark output (default: off)",
    )
    return ap


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(list(argv) if argv is not None else None)

    try:
        pack = build_selectors(
            mode=args.mode,
            seed_spec=args.seed_spec,
            focused_selectors=args.selectors,
            exclude_levels=args.exclude_levels,
            observe_only_levels=args.observe_only_levels,
        )
        cmd = build_bench_command(
            selectors=pack.selectors,
            bot=args.bot,
            json_path="auto",
            trace_detail=args.trace_detail,
            bot_config_path=args.bot_config,
            bot_profile_enabled=bool(args.bot_profile),
            bot_profile_interval_s=args.bot_profile_interval_s,
            bot_profile_log_lines=bool(args.bot_profile_logs),
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    print("# selectors")
    for selector in pack.selectors:
        print(selector)

    print("\n# policy")
    print(f"included_levels={','.join(pack.included_levels)}")
    print(f"excluded_levels_effective={','.join(pack.excluded_levels_effective)}")
    print(
        f"observe_only_levels_effective={','.join(pack.observe_only_levels_effective)}"
    )

    print("\n# command")
    print(" ".join(cmd))


__all__ = [
    "DEFAULT_SEEDS",
    "FOCUSED_SELECTOR_GROUPS",
    "ResolvedSelectorPack",
    "build_parser",
    "build_bench_command",
    "build_selectors",
    "main",
]


if __name__ == "__main__":
    main()
