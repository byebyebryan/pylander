from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
    Any,
    Generic,
    Literal,
    Mapping,
    TypeGuard,
    TypeVar,
    cast,
)

import core.terrain as _terrain
from core.components import (
    ActorControlRole,
    ActorProfile,
    CargoHold,
    Engine,
    PhysicsState,
    LandingSite as LandingSiteComponent,
    LandingSiteEconomy,
    LanderGeometry,
    PlayerControlled,
    PlayerSelectable,
    Transform,
)
from core.ecs import Entity
from core.landing_sites import (
    LandingSiteSurfaceModel,
    LandingSiteTerrainModifier,
    to_view,
)
from core.level import Level, LevelWorld
from core.level_capabilities import (
    BenchmarkLevelPolicy,
    BenchmarkScenarioSets,
    LevelBenchmarkProfile,
)
from core.maths import Vector2
from core.bot import BoostCutoffMetrics
from core.config import GRAVITY_MAG
from core.eval_goals import EVAL_GOAL_LANDING
from landers import create_lander
from core.ecs import require_component
from levels.common_world import (
    EndResultMixin,
    build_level_physics_engine,
    compute_spawn_pos,
    get_mass,
)

if TYPE_CHECKING:
    from core.physics import PhysicsEngine


BenchmarkRandomMode = Literal["median", "sample"]


@dataclass(frozen=True)
class SampleRange:
    low: float
    high: float

    def __post_init__(self) -> None:
        lo = float(self.low)
        hi = float(self.high)
        if hi < lo:
            raise ValueError(f"Invalid SampleRange: high({hi}) < low({lo})")

    def median(self) -> float:
        return 0.5 * (float(self.low) + float(self.high))

    def sample(self, rng: random.Random) -> float:
        return rng.uniform(float(self.low), float(self.high))


SampleValue = float | SampleRange
ScenarioT = TypeVar("ScenarioT")


def is_ranged_value(value: object) -> TypeGuard[SampleRange]:
    return isinstance(value, SampleRange)


def has_randomized_values(values: list[SampleValue] | tuple[SampleValue, ...]) -> bool:
    return any(is_ranged_value(v) for v in values)


def resolve_sample_value(
    value: SampleValue,
    *,
    mode: BenchmarkRandomMode,
    rng: random.Random,
) -> float:
    if not is_ranged_value(value):
        return float(cast(float, value))
    if mode == "median":
        return value.median()
    return value.sample(rng)


@dataclass(frozen=True)
class ScenarioLevelSpec:
    name: str
    start_x: float
    target_x: float
    spawn_clearance: float
    terrain_kind: str
    start_x_jitter: float = 0.0
    target_x_jitter: float = 0.0
    slope: float = 0.0
    terrain_base: float = 0.0
    terrain_amplitude: float = 2200.0
    terrain_frequency: float = 0.00025
    terrain_octaves: int = 5
    target_mode: str = "flush_flatten"
    target_offset_y: float = 0.0
    target_size: float = 100.0
    cargo_mass: float | None = None


class ScenarioCatalogMixin(Generic[ScenarioT]):
    """Shared scenario catalog plumbing for named scenario levels."""

    _scenario_by_name: Mapping[str, ScenarioT] = {}
    _default_scenario_name: str = ""
    _smoke_benchmark_scenarios: tuple[str, ...] = ()
    _quick_benchmark_scenarios: tuple[str, ...] = ()
    _benchmark_policy: BenchmarkLevelPolicy = "normal"
    _supported_eval_goals: tuple[str, ...] = (EVAL_GOAL_LANDING,)

    def _init_scenario_catalog(self) -> None:
        default_name = str(type(self)._default_scenario_name).strip()
        if not default_name:
            raise ValueError(
                f"{type(self).__name__} must define _default_scenario_name"
            )
        self._eval_scenario_name = default_name

    @classmethod
    def _scenario_catalog_name(cls) -> str:
        type_name = cls.__name__
        if type_name.endswith("Level"):
            type_name = type_name[:-5]
        return type_name.lower() or "level"

    def _scenario_names(self) -> tuple[str, ...]:
        return tuple(str(name) for name in type(self)._scenario_by_name)

    def _active_scenario(self) -> ScenarioT:
        return type(self)._scenario_by_name[self._eval_scenario_name]

    def supported_eval_goals(self) -> tuple[str, ...]:
        return tuple(str(goal) for goal in type(self)._supported_eval_goals)

    def list_batch_scenarios(self) -> list[str]:
        return list(self._scenario_names())

    def list_quick_benchmark_scenarios(self) -> list[str]:
        scenario_by_name = type(self)._scenario_by_name
        return [
            name
            for name in type(self)._quick_benchmark_scenarios
            if name in scenario_by_name
        ]

    def benchmark_profile(self) -> LevelBenchmarkProfile:
        scenario_by_name = type(self)._scenario_by_name
        full = self._scenario_names()
        quick = tuple(
            name
            for name in type(self)._quick_benchmark_scenarios
            if name in scenario_by_name
        )
        smoke = tuple(
            name
            for name in type(self)._smoke_benchmark_scenarios
            if name in scenario_by_name
        )
        return LevelBenchmarkProfile(
            policy=type(self)._benchmark_policy,
            scenarios=BenchmarkScenarioSets(smoke=smoke, quick=quick, full=full),
        )

    def set_eval_scenario(self, name: str) -> None:
        key = str(name).strip().lower()
        scenario_by_name = type(self)._scenario_by_name
        if key not in scenario_by_name:
            known = ", ".join(sorted(scenario_by_name))
            label = type(self)._scenario_catalog_name()
            raise ValueError(
                f"Unknown {label} scenario '{name}'. Expected one of: {known}"
            )
        self._eval_scenario_name = key


def validate_scenario_recoverability(
    actor,
    *,
    scenario_name: str,
    spawn_clearance: float,
    initial_vy_up: float,
) -> None:
    """Fail fast for scenarios that cannot physically arrest descent in time."""
    engine = require_component(actor, Engine)

    total_mass = max(0.5, get_mass(actor))
    max_up_acc = (
        float(engine.max_power) * float(engine.max_thrust) / total_mass
    ) - GRAVITY_MAG
    if max_up_acc <= 1e-6:
        raise ValueError(
            f"Scenario '{scenario_name}' is unrecoverable: no upward acceleration"
        )

    downward_speed = max(0.0, -float(initial_vy_up))
    stop_distance = (downward_speed * downward_speed) / (2.0 * max_up_acc)
    safety_margin = max(8.0, float(spawn_clearance) * 0.18)
    usable_altitude = max(0.0, float(spawn_clearance) - safety_margin)

    if stop_distance > usable_altitude:
        raise ValueError(
            f"Scenario '{scenario_name}' is unrecoverable: "
            f"stop_distance={stop_distance:.2f} usable_altitude={usable_altitude:.2f}"
        )


def sync_engine_pose_velocity(
    engine: PhysicsEngine,
    pos: Any,
    rotation: float,
    vx: float,
    vy: float,
    uid: str,
    *,
    clear_velocity: bool = False,
) -> None:
    """Teleport + velocity sync on a physics engine."""
    engine.teleport(
        Vector2(pos),
        angle=rotation,
        clear_velocity=clear_velocity,
        uid=uid,
    )
    engine.set_velocity(Vector2(vx, vy), uid=uid)


def angle_from_velocity(vx: float, vy_up: float, *, opposite: bool = False) -> float:
    """Return the heading angle (radians) implied by a velocity vector."""
    vel_x = -float(vx) if opposite else float(vx)
    vel_y = -float(vy_up) if opposite else float(vy_up)
    if abs(vel_x) <= 1e-6 and abs(vel_y) <= 1e-6:
        return 0.0
    return math.atan2(vel_x, vel_y)


def build_boost_cutoff_metrics_from_state(
    *,
    x: float,
    y: float,
    vx: float,
    vy_up: float,
    altitude: float,
    target_x: float,
    target_y: float,
) -> BoostCutoffMetrics:
    dx = float(target_x) - float(x)
    dy = float(target_y) - float(y)
    vy_pos = max(0.0, float(vy_up))
    apex_y = float(y)
    if GRAVITY_MAG > 1e-6:
        apex_y += (vy_pos * vy_pos) / (2.0 * GRAVITY_MAG)
    projected_apex_over_target = apex_y - float(target_y)

    has_target_y_solution = True
    projected_impact_dx: float | None = None
    projected_impact_angle_deg: float | None = None
    t_cross: float | None = None

    if GRAVITY_MAG <= 1e-6:
        if abs(float(vy_up)) > 1e-6:
            t_cross = dy / float(vy_up)
        elif abs(dy) <= 1e-6:
            t_cross = 0.0
        else:
            has_target_y_solution = False
    else:
        disc = (float(vy_up) * float(vy_up)) - (2.0 * GRAVITY_MAG * dy)
        if disc < 0.0:
            has_target_y_solution = False
        else:
            sqrt_disc = math.sqrt(max(0.0, disc))
            roots = sorted(
                (
                    (float(vy_up) - sqrt_disc) / GRAVITY_MAG,
                    (float(vy_up) + sqrt_disc) / GRAVITY_MAG,
                )
            )
            positive = [value for value in roots if value >= 0.0]
            if positive:
                if dy >= 0.0 and len(positive) >= 2:
                    t_cross = positive[-1]
                else:
                    future = [value for value in positive if value > 1e-4]
                    t_cross = future[0] if future else positive[0]
            else:
                has_target_y_solution = False

    if has_target_y_solution and t_cross is not None:
        projected_impact_dx = dx - (float(vx) * float(t_cross))
        vy_down = abs(float(vy_up) - (GRAVITY_MAG * max(0.0, float(t_cross))))
        projected_impact_angle_deg = math.degrees(math.atan2(vy_down, abs(float(vx))))

    return BoostCutoffMetrics(
        time_s=0.0,
        altitude=max(0.0, float(altitude)),
        x=float(x),
        y=float(y),
        vx=float(vx),
        vy_up=float(vy_up),
        projected_apex_y=apex_y,
        projected_apex_over_target=projected_apex_over_target,
        has_target_y_solution=has_target_y_solution,
        projected_dx=projected_impact_dx,
        projected_impact_dx=projected_impact_dx,
        projected_impact_angle_deg=projected_impact_angle_deg,
        burn_duration_s=0.0,
        burn_fuel_used=0.0,
        burn_avg_thrust_level=0.0,
    )


def prime_boost_cutoff_for_primary_bot(level, game) -> None:
    world = getattr(level, "world", None)
    if world is None or not getattr(world, "actors", None):
        return
    actor = world.actors[0]
    bot = getattr(game, "actor_bots", {}).get(actor.uid)
    if bot is None:
        return

    target_pos = level.ensure_runtime_context().eval_target_pos
    if not isinstance(target_pos, Vector2):
        return
    resolved_target_pos = cast(Any, target_pos)

    trans = require_component(actor, Transform)
    phys = require_component(actor, PhysicsState)
    altitude = float(trans.pos.y) - float(level.terrain(float(trans.pos.x), lod=0))
    bot.prime_boost_cutoff(
        build_boost_cutoff_metrics_from_state(
            x=float(trans.pos.x),
            y=float(trans.pos.y),
            vx=float(phys.vel.x),
            vy_up=float(phys.vel.y),
            altitude=altitude,
            target_x=float(resolved_target_pos.x),
            target_y=float(resolved_target_pos.y),
        )
    )


def make_flat_scenario_spec(
    *,
    name: str,
    start_dx: float,
    start_dy: float,
    cargo_mass: float,
) -> ScenarioLevelSpec:
    """Build a ScenarioLevelSpec for flat-terrain terminal-flight scenarios."""
    return ScenarioLevelSpec(
        name=name,
        start_x=start_dx,
        target_x=0.0,
        spawn_clearance=start_dy,
        terrain_kind="flat",
        target_mode="flush_flatten",
        target_offset_y=0.0,
        target_size=110.0,
        cargo_mass=cargo_mass,
    )


def scenario_seed(seed: int, name: str) -> int:
    """Derive a deterministic hash from a seed and scenario name."""
    return seed ^ (sum(ord(ch) for ch in name) << 1)


def _build_base_terrain(seed: int, spec: ScenarioLevelSpec):
    if spec.terrain_kind == "flat":
        return _terrain.LodGridGenerator(lambda _x: spec.terrain_base)
    if spec.terrain_kind == "slope":
        return _terrain.LodGridGenerator(lambda x: spec.terrain_base + spec.slope * x)
    if spec.terrain_kind == "complex":
        simplex = _terrain.SimplexNoiseGenerator(
            seed=seed,
            octaves=spec.terrain_octaves,
            amplitude=spec.terrain_amplitude,
            frequency=spec.terrain_frequency,
            persistence=0.30,
            lacunarity=3.0,
        )
        return _terrain.LodGridGenerator(simplex, base_resolution=8.0)
    raise ValueError(f"Unsupported terrain kind: {spec.terrain_kind}")


class ScenarioLevel(EndResultMixin, Level):
    """Single-scenario level with deterministic world setup and optional default bot."""

    scenario: ScenarioLevelSpec | None = None
    default_bot_name: str | None = None
    _benchmark_random_mode: BenchmarkRandomMode = "sample"

    def set_benchmark_mode(self, mode: str) -> None:
        key = str(mode or "sample").strip().lower()
        if key not in {"median", "sample"}:
            raise ValueError(
                f"Unknown benchmark mode '{mode}'. Expected one of: median, sample"
            )
        self._benchmark_random_mode = "median" if key == "median" else "sample"

    def scenario_has_randomized_fields(self, _name: str | None = None) -> bool:
        return False

    def _resolve_sample_value(self, value: SampleValue, rng: random.Random) -> float:
        return resolve_sample_value(
            value,
            mode=self._benchmark_random_mode,
            rng=rng,
        )

    def _set_scenario_params(self, params: dict[str, float | int | str | bool]) -> None:
        setattr(self, "_scenario_params", dict(params))

    def setup(self, game, seed: int) -> None:
        _ = game
        spec = self.scenario
        if spec is None:
            raise ValueError(f"{type(self).__name__} must define `scenario`")
        self._set_scenario_params({})

        rng = random.Random(seed)
        base_terrain = _build_base_terrain(seed, spec)

        target_x = spec.target_x
        if spec.target_x_jitter > 0.0:
            target_x += rng.uniform(-spec.target_x_jitter, spec.target_x_jitter)
        target_ground_y = base_terrain(target_x, lod=0)
        target_y = target_ground_y + spec.target_offset_y
        target_terrain_bound = spec.target_mode != "elevated_supports"

        site_uid = "eval_site_primary"
        site_view = to_view(
            uid=site_uid,
            x=target_x,
            y=target_y,
            size=spec.target_size,
            vel=Vector2(0.0, 0.0),
            award=200.0,
            fuel_price=10.0,
            terrain_mode=spec.target_mode,
            terrain_bound=target_terrain_bound,
            blend_margin=20.0,
            cut_depth=20.0,
            support_height=max(20.0, target_y - target_ground_y),
            visited=False,
        )
        site_model = LandingSiteSurfaceModel([site_view])
        terrain = _terrain.AddHeightModifier(
            base_terrain,
            LandingSiteTerrainModifier(site_model),
        )

        site_entity = Entity(uid=site_uid)
        site_entity.add_component(Transform(pos=Vector2(target_x, target_y)))
        site_entity.add_component(
            LandingSiteComponent(
                size=spec.target_size,
                terrain_mode=spec.target_mode,
                terrain_bound=target_terrain_bound,
                blend_margin=20.0,
                cut_depth=20.0,
                support_height=max(20.0, target_y - target_ground_y),
            )
        )
        site_entity.add_component(
            LandingSiteEconomy(award=200.0, fuel_price=10.0, visited=False)
        )

        lander_name = getattr(self, "lander_name", "classic")
        lander = create_lander(lander_name)
        if spec.cargo_mass is not None:
            cargo = lander.get_component(CargoHold)
            if cargo is not None:
                cargo.cargo_mass = max(
                    0.0,
                    min(float(spec.cargo_mass), float(cargo.max_cargo_mass)),
                )
        lander.add_component(ActorProfile(kind="lander", name="player"))
        lander.add_component(ActorControlRole(role="human"))
        lander.add_component(PlayerSelectable(order=0))
        lander.add_component(PlayerControlled(active=True))

        trans = require_component(lander, Transform)
        geo = require_component(lander, LanderGeometry)
        start_x = spec.start_x
        if spec.start_x_jitter > 0.0:
            start_x += rng.uniform(-spec.start_x_jitter, spec.start_x_jitter)
        start_pos = compute_spawn_pos(
            terrain,
            start_x,
            geo,
            clearance=spec.spawn_clearance,
        )
        lander.start_pos = Vector2(start_pos)
        trans.pos = Vector2(start_pos)

        landing_site_colliders = None
        if not target_terrain_bound or spec.target_mode == "elevated_supports":
            landing_site_colliders = [(target_x, target_y, spec.target_size)]
        engine = build_level_physics_engine(
            terrain,
            geo=geo,
            mass=get_mass(lander),
            uid=lander.uid,
            start_pos=start_pos,
            start_angle=trans.rotation,
            landing_site_colliders=landing_site_colliders,
        )

        self.world = LevelWorld(
            terrain=terrain,
            sites=site_model,
            actors=[lander],
            primary_actor_uid=lander.uid,
            site_entities=[site_entity],
            lander=lander,
            extra_entities=[],
        )
        self.engine = engine
        self.set_runtime_identity(
            scenario_name=spec.name,
            eval_target_pos=Vector2(target_x, target_y),
        )
