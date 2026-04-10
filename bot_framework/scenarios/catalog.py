from __future__ import annotations

from dataclasses import dataclass
import re
from typing import cast

from game.core.eval_goals import KNOWN_EVAL_GOAL_SET
from game.core.level_capabilities import (
    BenchmarkLevelPolicy,
    BenchmarkScenarioSets,
    LevelBenchmarkProfile,
)

_BENCHMARK_MODES = frozenset({"smoke", "quick", "full"})
_SCENARIO_ROOTS: tuple[str, ...] = (
    "boost",
    "terrain",
    "terminal",
    "plunge",
)


def list_scenario_roots() -> list[str]:
    return list(_SCENARIO_ROOTS)


_SEED_TOKEN_RE = re.compile(
    r"^-?\d+(?:\s*-\s*-?\d+)?(?:\s*,\s*-?\d+(?:\s*-\s*-?\d+)?)*$"
)


@dataclass(frozen=True)
class ScenarioLeaf:
    root: str
    path: tuple[str, ...]
    runtime_level_name: str
    runtime_scenario_name: str | None
    policy: str = "normal"
    benchmark_modes: frozenset[str] = frozenset()


@dataclass(frozen=True)
class ScenarioBinding:
    level_name: str
    path: tuple[str, ...]
    runtime_level_name: str
    runtime_scenario_name: str | None

    @property
    def scenario_name(self) -> str | None:
        return join_selector_path(self.path)


def join_selector_path(path: tuple[str, ...] | list[str] | None) -> str | None:
    if not path:
        return None
    tokens = [str(token).strip().lower() for token in path if str(token).strip()]
    return ":".join(tokens) if tokens else None


def split_selector_path(scenario_name: str | None) -> tuple[str, ...]:
    token = str(scenario_name or "").strip().lower()
    if not token:
        return ()
    return tuple(part.strip().lower() for part in token.split(":") if part.strip())


def resolve_public_scenario_benchmark_profile(level_name: str) -> LevelBenchmarkProfile:
    root = _normalize_root(level_name)
    policy = cast(BenchmarkLevelPolicy, _root_policy(root))
    if policy == "excluded":
        return LevelBenchmarkProfile(
            policy="excluded",
            scenarios=BenchmarkScenarioSets(smoke=(), quick=(), full=()),
        )
    return LevelBenchmarkProfile(
        policy=policy,
        scenarios=BenchmarkScenarioSets(
            smoke=_scenario_names_for_mode(root, "smoke"),
            quick=_scenario_names_for_mode(root, "quick"),
            full=_scenario_names_for_mode(root, "full"),
        ),
    )


def resolve_scenario_binding(
    level_name: str,
    scenario_path: tuple[str, ...] | list[str] | None = None,
) -> ScenarioBinding:
    bindings = expand_scenario_bindings(
        level_name,
        scenario_path=scenario_path,
        allow_wildcards=False,
    )
    if len(bindings) != 1:
        raise ValueError(
            f"Selector '{level_name}' resolved to {len(bindings)} bindings; expected one"
        )
    return bindings[0]


def expand_scenario_bindings(
    level_name: str,
    *,
    scenario_path: tuple[str, ...] | list[str] | None = None,
    allow_wildcards: bool,
) -> list[ScenarioBinding]:
    root = _normalize_root(level_name)
    raw_tokens = tuple(str(token).strip().lower() for token in (scenario_path or ()))
    if any(not token for token in raw_tokens):
        raise ValueError(f"Invalid selector path for '{root}': empty selector token")

    bindings = _expand_path(
        root, raw_tokens, prefix=(), allow_wildcards=allow_wildcards
    )
    if not bindings:
        raise ValueError(f"Selector '{root}' resolved no scenarios")
    return bindings


def scenario_children(
    level_name: str, path: tuple[str, ...] | list[str] | None = None
) -> tuple[str, ...]:
    root = _normalize_root(level_name)
    return _child_tokens(
        root, tuple(str(token).strip().lower() for token in (path or ()))
    )


def scenario_default_path(level_name: str) -> tuple[str, ...]:
    return resolve_scenario_binding(level_name).path


def selector_path_looks_like_seed(token: str) -> bool:
    value = str(token or "").strip()
    return bool(value and _SEED_TOKEN_RE.fullmatch(value))


def selector_token_is_reserved(token: str) -> bool:
    key = str(token or "").strip().lower()
    if not key:
        return True
    return (
        key == "*" or key in KNOWN_EVAL_GOAL_SET or selector_path_looks_like_seed(key)
    )


def _normalize_root(level_name: str) -> str:
    root = str(level_name or "").strip().lower()
    if root not in _ROOT_TO_LEAVES:
        known = ", ".join(_SCENARIO_ROOTS)
        raise ValueError(
            f"Unknown scenario root '{level_name}'. Expected one of: {known}"
        )
    return root


def _root_policy(root: str) -> str:
    policies = {leaf.policy for leaf in _ROOT_TO_LEAVES[root]}
    if len(policies) != 1:
        raise ValueError(
            f"Scenario root '{root}' mixes benchmark policies: {sorted(policies)}"
        )
    return next(iter(policies))


def _scenario_names_for_mode(root: str, mode: str) -> tuple[str, ...]:
    if mode not in _BENCHMARK_MODES:
        raise ValueError(f"Unsupported benchmark mode '{mode}'")
    out: list[str] = []
    seen: set[str] = set()
    for leaf in _ROOT_TO_LEAVES[root]:
        if mode not in leaf.benchmark_modes:
            continue
        scenario_name = join_selector_path(leaf.path)
        if scenario_name is None or scenario_name in seen:
            continue
        seen.add(scenario_name)
        out.append(scenario_name)
    return tuple(out)


def _find_exact_leaf(root: str, prefix: tuple[str, ...]) -> ScenarioLeaf | None:
    for leaf in _ROOT_TO_LEAVES[root]:
        if leaf.path == prefix:
            return leaf
    return None


def _child_tokens(root: str, prefix: tuple[str, ...]) -> tuple[str, ...]:
    children: list[str] = []
    seen: set[str] = set()
    prefix_len = len(prefix)
    for leaf in _ROOT_TO_LEAVES[root]:
        if len(leaf.path) <= prefix_len or leaf.path[:prefix_len] != prefix:
            continue
        token = leaf.path[prefix_len]
        if token in seen:
            continue
        seen.add(token)
        children.append(token)
    return tuple(children)


def _default_child(root: str, prefix: tuple[str, ...]) -> str | None:
    return _DEFAULT_CHILD_BY_PREFIX.get((root, *prefix))


def _binding_from_leaf(leaf: ScenarioLeaf) -> ScenarioBinding:
    return ScenarioBinding(
        level_name=leaf.root,
        path=leaf.path,
        runtime_level_name=leaf.runtime_level_name,
        runtime_scenario_name=leaf.runtime_scenario_name,
    )


def _expand_path(
    root: str,
    tokens: tuple[str, ...],
    *,
    prefix: tuple[str, ...],
    allow_wildcards: bool,
) -> list[ScenarioBinding]:
    children = _child_tokens(root, prefix)
    exact_leaf = _find_exact_leaf(root, prefix)

    if not children:
        if exact_leaf is None:
            raise ValueError(
                f"Selector '{root}' stopped at invalid path '{join_selector_path(prefix) or root}'"
            )
        if tokens:
            extra = ":".join(tokens)
            selector = ":".join([root, *prefix, extra])
            raise ValueError(
                f"Invalid selector '{selector}'. '{join_selector_path(prefix) or root}' is a leaf selector"
            )
        return [_binding_from_leaf(exact_leaf)]

    if not tokens:
        default_child = _default_child(root, prefix)
        if default_child is None:
            selector = ":".join([root, *prefix])
            raise ValueError(f"Selector '{selector}' is missing a default child")
        return _expand_path(
            root,
            (),
            prefix=(*prefix, default_child),
            allow_wildcards=allow_wildcards,
        )

    token = tokens[0]
    if token == "*":
        if not allow_wildcards:
            selector = ":".join([root, *prefix, "*"])
            raise ValueError(
                f"Wildcard selectors are only supported in bench-style expansion, not '{selector}'"
            )
        out: list[ScenarioBinding] = []
        for child in children:
            out.extend(
                _expand_path(
                    root,
                    tokens[1:],
                    prefix=(*prefix, child),
                    allow_wildcards=allow_wildcards,
                )
            )
        return out

    if token not in children:
        selector = ":".join([root, *prefix, token])
        expected = ", ".join(children)
        raise ValueError(
            f"Unknown selector token '{token}' in '{selector}'. Expected one of: {expected}"
        )

    return _expand_path(
        root,
        tokens[1:],
        prefix=(*prefix, token),
        allow_wildcards=allow_wildcards,
    )


def _make_leaf(
    *,
    root: str,
    path: tuple[str, ...],
    runtime_scenario_name: str | None = None,
    policy: str = "normal",
    benchmark_modes: frozenset[str] | None = None,
) -> ScenarioLeaf:
    scenario_name = (
        str(runtime_scenario_name).strip().lower()
        if runtime_scenario_name is not None
        else join_selector_path(path)
    )
    return ScenarioLeaf(
        root=root,
        path=path,
        runtime_level_name=root,
        runtime_scenario_name=scenario_name,
        policy=policy,
        benchmark_modes=frozenset(benchmark_modes or ()),
    )


def _build_leaves() -> tuple[ScenarioLeaf, ...]:
    from bot_framework.scenarios.terrain_catalog import (
        TERRAIN_QUICK_SCENARIOS,
        TERRAIN_SCENARIOS,
        TERRAIN_SMOKE_SCENARIOS,
    )

    leaves: list[ScenarioLeaf] = []

    boost_families = (
        ("flat", ("near", "mid", "far"), {"mid"}, {"mid"}),
        (
            "downhill",
            ("low", "mid", "mid_long", "high"),
            {"low", "mid", "high"},
            {"mid"},
        ),
        (
            "climb",
            ("low", "mid", "mid_long", "high"),
            {"low", "mid", "high"},
            {"mid"},
        ),
    )
    weight_tiers = ("empty", "half", "full")
    for family, route_tiers, quick_routes, smoke_routes in boost_families:
        for route_tier in route_tiers:
            for weight_tier in weight_tiers:
                benchmark_modes = {"full"}
                if weight_tier == "half" and route_tier in quick_routes:
                    benchmark_modes.add("quick")
                if weight_tier == "half" and route_tier in smoke_routes:
                    benchmark_modes.add("smoke")
                leaves.append(
                    _make_leaf(
                        root="boost",
                        path=(family, route_tier, weight_tier),
                        benchmark_modes=frozenset(benchmark_modes),
                    )
                )

    for scenario in TERRAIN_SCENARIOS:
        scenario_path = split_selector_path(scenario.name)
        benchmark_modes = {"full"}
        if scenario.name in TERRAIN_QUICK_SCENARIOS:
            benchmark_modes.add("quick")
        if scenario.name in TERRAIN_SMOKE_SCENARIOS:
            benchmark_modes.add("smoke")
        leaves.append(
            _make_leaf(
                root="terrain",
                path=scenario_path,
                runtime_scenario_name=scenario.name,
                policy="observe_only",
                benchmark_modes=frozenset(benchmark_modes),
            )
        )

    for profile in ("shallower", "shallow", "mid", "steep", "steeper"):
        benchmark_modes = {"full"}
        if profile in {"shallow", "mid", "steep"}:
            benchmark_modes.add("quick")
        if profile == "mid":
            benchmark_modes.add("smoke")
        leaves.append(
            _make_leaf(
                root="terminal",
                path=("normal", profile),
                benchmark_modes=frozenset(benchmark_modes),
            )
        )

    for profile in ("shallower", "shallow", "mid", "steep", "steeper"):
        for tier in ("tight", "wide"):
            benchmark_modes = {"full"}
            if (profile, tier) in {
                ("shallow", "tight"),
                ("mid", "wide"),
                ("steep", "wide"),
            }:
                benchmark_modes.add("quick")
            if (profile, tier) == ("mid", "wide"):
                benchmark_modes.add("smoke")
            leaves.append(
                _make_leaf(
                    root="terminal",
                    path=("error", profile, tier),
                    benchmark_modes=frozenset(benchmark_modes),
                )
            )

    for altitude in ("low", "mid", "high"):
        for weight_tier in ("empty", "half", "full"):
            benchmark_modes = {"full"}
            if weight_tier == "half":
                benchmark_modes.add("quick")
                if altitude == "mid":
                    benchmark_modes.add("smoke")
            leaves.append(
                _make_leaf(
                    root="plunge",
                    path=(altitude, weight_tier),
                    benchmark_modes=frozenset(benchmark_modes),
                )
            )
    return tuple(leaves)


def _build_default_child_map() -> dict[tuple[str, ...], str]:
    out: dict[tuple[str, ...], str] = {
        ("boost",): "flat",
        ("terrain",): "reactive",
        ("terminal",): "normal",
        ("plunge",): "mid",
    }
    for family in ("flat", "downhill", "climb"):
        out[("boost", family)] = "mid"
    out[("terrain", "reactive")] = "terminal_backstop"
    for route in ("near", "mid", "far"):
        out[("boost", "flat", route)] = "half"
    for route in ("low", "mid", "mid_long", "high"):
        out[("boost", "downhill", route)] = "half"
        out[("boost", "climb", route)] = "half"
    for route in ("low", "mid", "high"):
        out[("plunge", route)] = "half"
    out[("terminal", "normal")] = "mid"
    out[("terminal", "error")] = "mid"
    for profile in ("shallower", "shallow", "mid", "steep", "steeper"):
        out[("terminal", "error", profile)] = "tight"
    return out


def _validate_catalog() -> None:
    for leaf in _LEAVES:
        if leaf.policy not in {"normal", "observe_only", "excluded"}:
            raise ValueError(
                f"Scenario leaf '{leaf.root}:{join_selector_path(leaf.path) or ''}' "
                f"has invalid policy '{leaf.policy}'"
            )
        if any(selector_token_is_reserved(token) for token in leaf.path):
            raise ValueError(
                f"Scenario leaf '{leaf.root}:{join_selector_path(leaf.path) or ''}' "
                "uses a reserved token"
            )
        if len(set(leaf.path)) != len(leaf.path):
            raise ValueError(
                f"Scenario leaf '{leaf.root}:{join_selector_path(leaf.path) or ''}' "
                "repeats a token on one canonical path"
            )
        invalid_modes = set(leaf.benchmark_modes) - _BENCHMARK_MODES
        if invalid_modes:
            raise ValueError(
                f"Scenario leaf '{leaf.root}:{join_selector_path(leaf.path) or ''}' "
                f"has invalid benchmark modes: {sorted(invalid_modes)}"
            )

    seen_leafs: set[tuple[str, tuple[str, ...]]] = set()
    for leaf in _LEAVES:
        key = (leaf.root, leaf.path)
        if key in seen_leafs:
            raise ValueError(
                f"Duplicate scenario leaf '{leaf.root}:{join_selector_path(leaf.path) or ''}'"
            )
        seen_leafs.add(key)

    for root in _SCENARIO_ROOTS:
        root_leaves = _ROOT_TO_LEAVES.get(root, ())
        if not root_leaves:
            raise ValueError(f"Scenario root '{root}' has no leaf bindings")

        prefixes: set[tuple[str, ...]] = {()}
        for leaf in root_leaves:
            for idx in range(1, len(leaf.path)):
                prefixes.add(leaf.path[:idx])

        for prefix in prefixes:
            children = _child_tokens(root, prefix)
            if not children:
                continue
            default_child = _default_child(root, prefix)
            selector = ":".join([root, *prefix])
            if default_child is None:
                raise ValueError(
                    f"Selector node '{selector}' is missing a default child"
                )
            if default_child not in children:
                expected = ", ".join(children)
                raise ValueError(
                    f"Selector node '{selector}' has invalid default '{default_child}'. "
                    f"Expected one of: {expected}"
                )


_LEAVES = _build_leaves()
_ROOT_TO_LEAVES: dict[str, tuple[ScenarioLeaf, ...]] = {
    root: tuple(leaf for leaf in _LEAVES if leaf.root == root)
    for root in _SCENARIO_ROOTS
}
_DEFAULT_CHILD_BY_PREFIX = _build_default_child_map()

_validate_catalog()
