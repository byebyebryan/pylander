"""Shared base class for pad-to-pad boost-transfer levels."""

from __future__ import annotations

from dataclasses import dataclass

from core.components import CargoHold, Transform
from core.ecs import require_component
from core.eval_goals import EVAL_GOAL_BOOST_CUTOFF, EVAL_GOAL_LANDING
from core.maths import Vector2
from levels.common_world import (
    PresetLevel,
    SiteSpec,
    apply_transfer_result,
    get_mass,
    resolve_landed_site_uid,
)
from levels.common_scenarios import ScenarioCatalogMixin

SOURCE_PAD_X = 0.0
SOURCE_SITE_UID = "transfer_source"
TARGET_SITE_UID = "transfer_target"


@dataclass(frozen=True)
class BoostWeightTier:
    key: str
    cargo_mass: float
    cargo_fraction: float


BOOST_WEIGHT_TIERS: tuple[BoostWeightTier, ...] = (
    BoostWeightTier(key="empty", cargo_mass=0.0, cargo_fraction=0.0),
    BoostWeightTier(key="half", cargo_mass=3000.0, cargo_fraction=0.5),
    BoostWeightTier(key="full", cargo_mass=6000.0, cargo_fraction=1.0),
)


def build_boost_weight_params(scenario) -> dict[str, float | str]:  # noqa: ANN001
    return {
        "weight_tier": str(getattr(scenario, "weight_tier", "") or ""),
        "cargo_mass": float(getattr(scenario, "cargo_mass", 0.0) or 0.0),
        "cargo_fraction": float(getattr(scenario, "cargo_fraction", 0.0) or 0.0),
    }


class BoostTransferLevel(ScenarioCatalogMixin, PresetLevel):
    """Base for pad-to-pad boost-transfer levels.

    Subclasses must override:
    - ``_build_base_terrain(seed)`` — terrain generator
    - ``_resolve_dest_x(scenario, rng)`` — target pad X position
    - ``_build_scenario_params(scenario, dest_x)`` — dict for ``_scenario_params``
    """

    default_bot_name = "pdg"
    dynamic_site_enabled = False
    _supported_eval_goals = (EVAL_GOAL_LANDING, EVAL_GOAL_BOOST_CUTOFF)

    site_specs = ()
    spawn_x = SOURCE_PAD_X
    spawn_clearance = 0.0
    spawn_x_jitter = 0.0
    site_x_jitter = 0.0

    def __init__(self) -> None:
        super().__init__()
        self._init_scenario_catalog()
        self._benchmark_random_mode = "sample"

    def set_benchmark_mode(self, mode: str) -> None:
        key = str(mode or "sample").strip().lower()
        if key not in {"median", "sample"}:
            raise ValueError(
                f"Unknown benchmark mode '{mode}'. Expected one of: median, sample"
            )
        self._benchmark_random_mode = key

    # -- hooks for subclasses -------------------------------------------------

    def _resolve_dest_x(self, scenario, rng) -> float:  # noqa: ANN001
        """Return the target-pad X coordinate given the active scenario."""
        raise NotImplementedError

    def _build_scenario_params(self, scenario, dest_x: float) -> dict:  # noqa: ANN001
        """Return the dict stored as ``_scenario_params``."""
        raise NotImplementedError

    # -- shared world setup / end ---------------------------------------------

    def setup(self, game, seed: int) -> None:
        scenario = self._active_scenario()
        import random as _random

        scenario_seed_key = str(
            getattr(scenario, "sample_key", scenario.name) or scenario.name
        )
        scenario_name_hash = sum(ord(ch) for ch in scenario_seed_key)
        rng = _random.Random(seed ^ (scenario_name_hash << 1))

        dest_x = self._resolve_dest_x(scenario, rng)
        setattr(self, "_sampled_dest_x", float(dest_x))
        self.site_specs = (
            SiteSpec(
                uid=SOURCE_SITE_UID,
                x=SOURCE_PAD_X,
                size=110.0,
                award=100.0,
                fuel_price=8.0,
            ),
            SiteSpec(
                uid=TARGET_SITE_UID,
                x=dest_x,
                size=110.0,
                award=100.0,
                fuel_price=8.0,
            ),
        )
        super().setup(game, seed)
        if self.world is None:
            raise RuntimeError("BoostTransferLevel world was not initialized")

        actor = self.world.actors[0]
        cargo = actor.get_component(CargoHold)
        if cargo is not None:
            cargo_mass = max(0.0, float(getattr(scenario, "cargo_mass", 0.0) or 0.0))
            cargo.cargo_mass = min(cargo_mass, float(cargo.max_cargo_mass))
        engine = self.engine
        set_lander_mass = getattr(engine, "set_lander_mass", None)
        if callable(set_lander_mass):
            set_lander_mass(get_mass(actor), uid=actor.uid)

        self.set_runtime_identity(scenario_name=scenario.name)
        setattr(self, "_scenario_params", self._build_scenario_params(scenario, dest_x))

        if self.sites is None:
            raise RuntimeError("BoostTransferLevel sites were not initialized")
        dest_site = self.sites.get_site(TARGET_SITE_UID)
        if dest_site is not None:
            self.set_runtime_identity(eval_target_pos=Vector2(dest_site.x, dest_site.y))

    def _resolve_landed_site_uid(self, landed_x: float) -> str | None:
        return resolve_landed_site_uid(self.site_specs, landed_x)

    def end(self, game):
        result = super().end(game)
        state = str(result.get("state", "unknown"))
        landed_uid: str | None = None
        if state == "landed":
            if self.world is None:
                raise RuntimeError("BoostTransferLevel world was not initialized")
            actor = self.world.actors[0]
            trans = require_component(actor, Transform)
            landed_uid = self._resolve_landed_site_uid(float(trans.pos.x))
        return apply_transfer_result(
            result,
            state=state,
            landed_uid=landed_uid,
            source_uid=SOURCE_SITE_UID,
            target_uid=TARGET_SITE_UID,
        )
