from __future__ import annotations

import core.terrain as _terrain
from core.components import CargoHold, Transform
from core.ecs import require_component
from core.level import Level
from core.maths import Vector2
from dataclasses import dataclass

from levels.common import PresetLevel, SiteSpec, get_mass
from levels.staged_eval import ZemStageEvalTracker

_SOURCE_PAD_X = 0.0


@dataclass(frozen=True)
class ClimbScenario:
    name: str
    terrain_kind: str
    target_dx: float
    target_dy: float


_SCENARIOS: tuple[ClimbScenario, ...] = (
    ClimbScenario(name="flat_low", terrain_kind="flat", target_dx=400.0, target_dy=200.0),
    ClimbScenario(name="flat_mid", terrain_kind="flat", target_dx=400.0, target_dy=400.0),
    ClimbScenario(name="flat_high", terrain_kind="flat", target_dx=400.0, target_dy=800.0),
    ClimbScenario(name="slope_low", terrain_kind="slope", target_dx=400.0, target_dy=200.0),
    ClimbScenario(name="slope_mid", terrain_kind="slope", target_dx=400.0, target_dy=400.0),
    ClimbScenario(name="slope_high", terrain_kind="slope", target_dx=400.0, target_dy=800.0),
)
_SCENARIO_BY_NAME = {item.name: item for item in _SCENARIOS}
_DEFAULT_SCENARIO = "flat_mid"
_QUICK_BENCHMARK_SCENARIOS: tuple[str, ...] = (
    "flat_mid",
    "slope_mid",
    "slope_high",
)
_CLIMB_EVAL_MODES: tuple[str, ...] = ("auto", "focused", "full")
_CLIMB_DEFAULT_EVAL_MODE = "full"


class ClimbLevel(PresetLevel):
    """Pad-to-pad climb transfer with uphill destination profiles and no obstacles."""

    default_bot_name = "zem_zev"
    dynamic_site_enabled = False

    site_specs = ()
    spawn_x = _SOURCE_PAD_X
    spawn_clearance = 0.0
    spawn_x_jitter = 0.0
    site_x_jitter = 0.0

    def __init__(self) -> None:
        super().__init__()
        self._eval_scenario_name = _DEFAULT_SCENARIO
        self._eval_mode_name = "auto"
        self._resolved_eval_mode = _CLIMB_DEFAULT_EVAL_MODE
        self._benchmark_random_mode = "sample"
        self._stage_eval = ZemStageEvalTracker(
            stage_prefix="climb",
            completion_gate_prefix="setup_gate",
        )

    @staticmethod
    def list_batch_scenarios() -> list[str]:
        return [item.name for item in _SCENARIOS]

    @staticmethod
    def list_quick_benchmark_scenarios() -> list[str]:
        return [name for name in _QUICK_BENCHMARK_SCENARIOS if name in _SCENARIO_BY_NAME]

    def set_eval_scenario(self, name: str) -> None:
        key = str(name).strip().lower()
        if key not in _SCENARIO_BY_NAME:
            known = ", ".join(sorted(_SCENARIO_BY_NAME))
            raise ValueError(f"Unknown climb scenario '{name}'. Expected one of: {known}")
        self._eval_scenario_name = key

    def set_eval_mode(self, name: str) -> None:
        key = str(name).strip().lower()
        if key not in _CLIMB_EVAL_MODES:
            known = ", ".join(_CLIMB_EVAL_MODES)
            raise ValueError(f"Unknown climb eval mode '{name}'. Expected one of: {known}")
        self._eval_mode_name = key

    def set_benchmark_mode(self, mode: str) -> None:
        key = str(mode or "sample").strip().lower()
        if key not in {"median", "sample"}:
            raise ValueError(f"Unknown benchmark mode '{mode}'. Expected one of: median, sample")
        self._benchmark_random_mode = key

    def scenario_has_randomized_fields(self, _name: str | None = None) -> bool:
        return False

    def _mode_for_run(self) -> str:
        if self._eval_mode_name == "auto":
            return _CLIMB_DEFAULT_EVAL_MODE
        return self._eval_mode_name

    def _resolve_zem_snapshot(self, game):
        return self._stage_eval.resolve_zem_snapshot(game)

    def _active_scenario(self) -> ClimbScenario:
        return _SCENARIO_BY_NAME[self._eval_scenario_name]

    @staticmethod
    def _scenario_slope(scenario: ClimbScenario) -> float:
        if scenario.terrain_kind != "slope":
            return 0.0
        return float(scenario.target_dy) / max(1e-6, float(scenario.target_dx))

    def _build_base_terrain(self, _seed: int):
        scenario = self._active_scenario()
        if scenario.terrain_kind == "flat":
            return _terrain.LodGridGenerator(lambda _x: 0.0)
        if scenario.terrain_kind == "slope":
            slope = self._scenario_slope(scenario)
            return _terrain.LodGridGenerator(lambda x: slope * x)
        raise ValueError(f"Unsupported climb terrain kind: {scenario.terrain_kind}")

    def setup(self, game, seed: int) -> None:
        self._resolved_eval_mode = self._mode_for_run()
        self._stage_eval.reset()

        scenario = self._active_scenario()
        dest_x = _SOURCE_PAD_X + float(scenario.target_dx)
        target_dy = float(scenario.target_dy)
        slope = self._scenario_slope(scenario)
        target_on_supports = scenario.terrain_kind == "flat"
        target_mode = "elevated_supports" if target_on_supports else "flush_flatten"
        self.site_specs = (
            SiteSpec(
                uid="climb_site_source",
                x=_SOURCE_PAD_X,
                size=110.0,
                award=100.0,
                fuel_price=8.0,
            ),
            SiteSpec(
                uid="climb_site_target",
                x=dest_x,
                size=110.0,
                award=100.0,
                fuel_price=8.0,
                terrain_mode=target_mode,
                terrain_bound=not target_on_supports,
                y_offset=target_dy if target_on_supports else 0.0,
                support_height=max(20.0, target_dy) if target_on_supports else 40.0,
            ),
        )
        super().setup(game, seed)

        actor = self.world.actors[0]
        cargo = actor.get_component(CargoHold)
        if cargo is not None:
            cargo.cargo_mass = 0.0
        engine = getattr(self, "engine", None)
        if engine is not None and hasattr(engine, "set_lander_mass"):
            engine.set_lander_mass(get_mass(actor), uid=actor.uid)

        self._stage_eval.seed_motion_state(actor)

        setattr(self, "scenario_name", scenario.name)
        setattr(
            self,
            "_scenario_params",
            {
                "terrain_kind": scenario.terrain_kind,
                "slope": slope,
                "dx": scenario.target_dx,
                "dy": scenario.target_dy,
                "target_mode": target_mode,
            },
        )
        target_site = self.sites.get_site("climb_site_target")
        if target_site is not None:
            setattr(self, "eval_target_pos", Vector2(target_site.x, target_site.y))

    def _resolve_landed_site_uid(self, landed_x: float) -> str | None:
        best_uid: str | None = None
        best_distance = float("inf")
        for spec in self.site_specs:
            half = 0.5 * float(spec.size)
            distance = abs(float(landed_x) - float(spec.x))
            if distance <= half + 1e-6:
                return spec.uid
            if distance < best_distance:
                best_distance = distance
                best_uid = spec.uid
        return best_uid

    def update(self, game, dt: float) -> None:
        _ = dt
        actor = self.world.actors[0]
        self._stage_eval.update_motion(actor)
        if self._stage_eval.phase_done:
            return
        snapshot = self._resolve_zem_snapshot(game)
        if isinstance(snapshot, dict):
            target_pos = getattr(self, "eval_target_pos", Vector2(0.0, 0.0))
            self._stage_eval.capture_snapshot(game, actor, target_pos, snapshot)

    def should_end(self, game) -> bool:
        if self._stage_eval.should_end_focused(self._resolved_eval_mode):
            return True
        return super().should_end(game)

    def end(self, game):
        result = super().end(game)
        result["eval_mode"] = self._resolved_eval_mode
        actor = self.world.actors[0]
        target_pos = getattr(self, "eval_target_pos", Vector2(0.0, 0.0))
        self._stage_eval.apply_result(
            result,
            eval_mode=self._resolved_eval_mode,
            eval_phase_name="zem_setup_gate",
            actor=actor,
            target_pos=target_pos,
        )

        state = str(result.get("state", "unknown"))
        landed_uid: str | None = None
        if state == "landed":
            trans = require_component(actor, Transform)
            landed_uid = self._resolve_landed_site_uid(float(trans.pos.x))

        climb_arrived = state == "landed" and landed_uid == "climb_site_target"
        result["climb_arrived"] = climb_arrived
        result["climb_landed_site_uid"] = landed_uid

        if self._resolved_eval_mode != "focused":
            result["success"] = climb_arrived
            if climb_arrived:
                result["failure_mode"] = "none"
            elif state == "landed":
                result["failure_mode"] = "wrong_pad"
            else:
                result["failure_mode"] = state
        return result


def create_level() -> Level:
    return ClimbLevel()
