from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.selector import parse_selector  # noqa: E402
from core.level_capabilities import (  # noqa: E402
    BenchmarkLevelPolicy,
    LevelBenchmarkProfile,
    resolve_level_benchmark_profile,
)
from levels import create_level, list_available_levels  # noqa: E402


DEFAULT_SEEDS = {
    "smoke": "0-1",
    "quick": "0-4",
    "full": "0-9",
    "focused": "0-9",
}


@dataclass(frozen=True)
class ResolvedSelectorPack:
    selectors: list[str]
    effective_level_policy: dict[str, BenchmarkLevelPolicy]
    included_levels: list[str]
    excluded_levels_effective: list[str]
    observe_only_levels_effective: list[str]


def _parse_seed_spec(spec: str) -> list[int]:
    vals: list[int] = []
    for token in (p.strip() for p in spec.split(",")):
        if not token:
            continue
        if "-" in token:
            left, right = token.split("-", 1)
            start = int(left.strip())
            end = int(right.strip())
            step = 1 if end >= start else -1
            vals.extend(range(start, end + step, step))
        else:
            vals.append(int(token))
    out: list[int] = []
    seen: set[int] = set()
    for v in vals:
        if v in seen:
            continue
        seen.add(v)
        out.append(v)
    return out


def _seed_spec_str(spec: str) -> str:
    seeds = _parse_seed_spec(spec)
    if not seeds:
        raise ValueError(f"Seed spec '{spec}' produced no seeds")
    if len(seeds) == 1:
        return str(seeds[0])
    contiguous = seeds == list(range(seeds[0], seeds[-1] + 1))
    return f"{seeds[0]}-{seeds[-1]}" if contiguous else ",".join(str(s) for s in seeds)


def _split_csv(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    for item in values:
        for token in str(item).split(","):
            t = token.strip()
            if t:
                out.append(t)
    return out


def _split_focused_selectors(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    for item in values:
        raw = str(item).strip()
        if not raw:
            continue
        # Preserve CSV seed specs for level:scenario:seed_csv selectors.
        # Example: launch:mid:0,1 must stay a single selector.
        if raw.count(":") >= 2:
            out.append(raw)
            continue
        out.extend(_split_csv([raw]))
    return out


def _load_level_profiles() -> dict[str, LevelBenchmarkProfile]:
    out: dict[str, LevelBenchmarkProfile] = {}
    for level_name in sorted(list_available_levels()):
        level = create_level(level_name)
        out[level_name] = resolve_level_benchmark_profile(level, level_name)
    return out


def _parse_policy_override_levels(
    values: Iterable[str],
    *,
    known_levels: set[str],
    flag_name: str,
) -> set[str]:
    out: set[str] = set()
    for token in _split_csv(values):
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


def _selector(level: str, scenario: str | None, seed_spec: str) -> str:
    if scenario:
        return f"{level}:{scenario}:{seed_spec}"
    return f"{level}::{seed_spec}"


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
        selectors.extend(_selector(level_name, scenario, seed_spec) for scenario in scenarios)
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
        parsed = parse_selector(raw, default_level=None, known_levels=known_levels)
        level_name = parsed.level_name
        profile = profiles[level_name]
        local_seed = _seed_spec_str((parsed.seed_token or seed_spec).strip())

        if parsed.scenario_name:
            full_scenarios = set(profile.scenarios.full)
            if not full_scenarios:
                raise ValueError(
                    f"Selector '{raw}' specifies scenario '{parsed.scenario_name}', but "
                    f"level '{level_name}' has no benchmark scenarios"
                )
            if parsed.scenario_name not in full_scenarios:
                known = ", ".join(profile.scenarios.full)
                raise ValueError(
                    f"Unknown scenario '{parsed.scenario_name}' for level '{level_name}' in "
                    f"selector '{raw}'. Expected one of: {known}"
                )
            selectors.append(_selector(level_name, parsed.scenario_name, local_seed))
            included.add(level_name)
            continue

        scenarios = profile.scenarios.full
        if scenarios:
            selectors.extend(_selector(level_name, scenario, local_seed) for scenario in scenarios)
        else:
            selectors.append(_selector(level_name, None, local_seed))
        included.add(level_name)

    _ = policy_by_level  # Explicit selectors win in focused mode; policy is used for reporting only.
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
        level_name for level_name, policy in policy_by_level.items() if policy == "excluded"
    )
    observe_only_levels_effective = sorted(
        level_name for level_name, policy in policy_by_level.items() if policy == "observe_only"
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
    bot: str = "zem_zev",
    workers: int | None = None,
    eval_mode: str = "auto",
    json_path: str = "auto",
    csv_path: str = "auto",
) -> list[str]:
    if not selectors:
        raise ValueError("No selectors resolved")
    cmd = (
        ["uv", "run", "python", "main.py", "bench"]
        + selectors
        + [
            "--bot",
            bot,
            "--eval-mode",
            eval_mode,
            "--json",
            json_path,
            "--csv",
            csv_path,
        ]
    )
    if workers is not None:
        cmd += ["--workers", str(max(1, int(workers)))]
    return cmd


def main() -> None:
    ap = argparse.ArgumentParser(description="Build Pylander benchmark selector packs")
    ap.add_argument("--mode", choices=("smoke", "quick", "full", "focused"), required=True)
    ap.add_argument("--seed-spec", default=None, help="Override default seed range, e.g. 0-9")
    ap.add_argument("--selectors", nargs="*", default=[], help="Focused selectors (level[:scenario[:seed]])")
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
    ap.add_argument("--bot", default="zem_zev")
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--eval-mode", default="auto", choices=("auto", "focused", "full"))
    args = ap.parse_args()

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
            workers=args.workers,
            eval_mode=args.eval_mode,
            json_path="auto",
            csv_path="auto",
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    print("# selectors")
    for s in pack.selectors:
        print(s)

    print("\n# policy")
    print(f"included_levels={','.join(pack.included_levels)}")
    print(f"excluded_levels_effective={','.join(pack.excluded_levels_effective)}")
    print(f"observe_only_levels_effective={','.join(pack.observe_only_levels_effective)}")

    print("\n# command")
    print(" ".join(cmd))


if __name__ == "__main__":
    main()
