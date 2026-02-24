from __future__ import annotations

import math

import pytest

import core.terrain as terrain
from core.landing_sites import (
    LandingSiteSurfaceModel,
    LandingSiteTerrainModifier,
    build_seeded_sites,
    to_view,
)
from core.maths import Range1D, Vector2


def _site(
    uid: str,
    x: float,
    y: float,
    mode: str,
    *,
    terrain_bound: bool = True,
):
    return to_view(
        uid=uid,
        x=x,
        y=y,
        size=100.0,
        vel=Vector2(0.0, 0.0),
        award=100.0,
        fuel_price=10.0,
        terrain_mode=mode,
        terrain_bound=terrain_bound,
        blend_margin=20.0,
        cut_depth=30.0,
        support_height=40.0,
        visited=False,
    )


def test_site_surface_model_get_sites_requires_range1d() -> None:
    model = LandingSiteSurfaceModel([_site("a", 0.0, 0.0, "flush_flatten")])
    span = Range1D.from_center(0.0, 20.0)
    out = model.get_sites(span)
    assert len(out) == 1

    with pytest.raises(AttributeError):
        model.get_sites(0.0)  # type: ignore[arg-type]


def test_flush_flatten_mode_flattens_terrain_patch() -> None:
    model = LandingSiteSurfaceModel([_site("a", 0.0, 10.0, "flush_flatten")])
    modifier = LandingSiteTerrainModifier(model)

    # Inside footprint: should snap to site y.
    y0 = modifier(Vector2(0.0, 50.0), 50.0, lod=0)
    assert y0 == 10.0

    # Far from footprint: unchanged.
    y_far = modifier(Vector2(500.0, 50.0), 50.0, lod=0)
    assert y_far == 50.0


def test_cut_in_mode_carves_below_base_terrain() -> None:
    model = LandingSiteSurfaceModel([_site("a", 0.0, 20.0, "cut_in")])
    modifier = LandingSiteTerrainModifier(model)

    y0 = modifier(Vector2(0.0, 80.0), 80.0, lod=0)
    assert y0 == 20.0


def test_elevated_supports_does_not_modify_terrain() -> None:
    model = LandingSiteSurfaceModel(
        [_site("a", 0.0, 120.0, "elevated_supports", terrain_bound=False)]
    )
    modifier = LandingSiteTerrainModifier(model)
    y0 = modifier(Vector2(0.0, 35.0), 35.0, lod=0)
    assert y0 == 35.0


def test_seeded_sites_generate_only_flush_or_elevated_modes() -> None:
    sites = build_seeded_sites(lambda _x: 0.0, seed=123, count_each_side=4)
    modes = {s.terrain_mode for s in sites}
    assert modes <= {"flush_flatten", "elevated_supports"}


def test_layered_terrain_generator_is_seed_deterministic() -> None:
    xs = [-2500.0, -1000.0, -128.0, 0.0, 333.0, 1900.0]
    gen_a = terrain.LayeredTerrainGenerator(seed=7)
    gen_b = terrain.LayeredTerrainGenerator(seed=7)
    gen_c = terrain.LayeredTerrainGenerator(seed=99)

    vals_a = [gen_a(x) for x in xs]
    vals_b = [gen_b(x) for x in xs]
    vals_c = [gen_c(x) for x in xs]

    assert vals_a == pytest.approx(vals_b)
    assert any(abs(a - c) > 1e-3 for a, c in zip(vals_a, vals_c))


def test_lod_grid_profile_aligns_to_stable_step() -> None:
    lod_terrain = terrain.LodGridGenerator(lambda x: 0.5 * x, base_resolution=8.0)
    profile = lod_terrain.profile(-13.0, 21.0, lod=1, step=20.0)

    xs = [x for x, _ in profile]
    assert xs[0] == pytest.approx(-20.0)
    assert xs[-1] == pytest.approx(40.0)
    for i in range(1, len(xs)):
        assert xs[i] - xs[i - 1] == pytest.approx(20.0)


def test_add_height_modifier_profile_matches_callable_samples() -> None:
    base = terrain.LodGridGenerator(lambda x: math.sin(x * 0.01) * 10.0, base_resolution=4.0)
    wrapped = terrain.AddHeightModifier(
        base,
        lambda pos, y, _lod: y + 5.0 + 0.001 * pos.x,
    )

    profile = wrapped.profile(-50.0, 50.0, lod=0, step=6.0)
    for x, y in profile:
        assert y == pytest.approx(wrapped(x, lod=0))


def test_sample_terrain_height_supports_lod_and_non_lod_callables() -> None:
    class _WithLod:
        def __call__(self, x: float, lod: int = 0) -> float:
            return x + (2.0 * lod)

    class _NoLod:
        def __call__(self, x: float) -> float:
            return x - 3.0

    assert terrain.sample_terrain_height(_WithLod(), 5.0, lod=2) == pytest.approx(9.0)
    assert terrain.sample_terrain_height(_NoLod(), 5.0, lod=2) == pytest.approx(2.0)


def test_terrain_resolution_and_slope_helpers_match_expected_values() -> None:
    def line(x: float) -> float:
        return (0.75 * x) + 10.0

    lod_terrain = terrain.LodGridGenerator(line, base_resolution=4.0)

    assert terrain.terrain_resolution(lod_terrain, lod=0) == pytest.approx(4.0)
    assert terrain.terrain_resolution(lod_terrain, lod=2) == pytest.approx(16.0)
    assert terrain.terrain_resolution(line, lod=0) == pytest.approx(2.0)
    assert terrain.estimate_terrain_slope(lod_terrain, 128.0, lod=0) == pytest.approx(0.75)


def test_pick_lod_for_world_step_prefers_closest_resolution() -> None:
    lod_terrain = terrain.LodGridGenerator(lambda x: x, base_resolution=4.0)
    assert terrain.pick_lod_for_world_step(lod_terrain, 5.0) == 0
    assert terrain.pick_lod_for_world_step(lod_terrain, 9.0) == 1
    assert terrain.pick_lod_for_world_step(lod_terrain, 35.0) == 3


def test_sample_ballistic_trajectory_stops_on_terrain_hit() -> None:
    traj = terrain.sample_ballistic_trajectory(
        lambda _x: 0.0,
        x=0.0,
        y=120.0,
        vx=15.0,
        vy_up=0.0,
        max_distance=2000.0,
        segment_length=14.0,
    )
    assert traj.hit
    assert traj.termination == "terrain_hit"
    assert traj.hit_x is not None
    assert traj.hit_y is not None
    assert abs(traj.hit_y) <= 0.5
    assert len(traj.points) >= 2
    assert traj.distance > 0.0


def test_sample_ballistic_trajectory_stops_at_max_distance() -> None:
    traj = terrain.sample_ballistic_trajectory(
        lambda _x: -1e9,
        x=0.0,
        y=120.0,
        vx=10.0,
        vy_up=0.0,
        max_distance=140.0,
        segment_length=18.0,
    )
    assert not traj.hit
    assert traj.termination == "max_distance"
    assert traj.distance == pytest.approx(140.0)
    assert len(traj.points) >= 2


def test_sample_ballistic_trajectory_handles_low_horizontal_speed() -> None:
    traj = terrain.sample_ballistic_trajectory(
        lambda _x: -1e9,
        x=0.0,
        y=10.0,
        vx=0.01,
        vy_up=20.0,
        max_distance=200.0,
        segment_length=8.0,
    )
    assert len(traj.points) >= 3
    assert all(math.isfinite(px) and math.isfinite(py) for px, py in traj.points)
    assert traj.distance > 0.0


def test_sample_ballistic_trajectory_refines_impact_point() -> None:
    def terrain_line(xx: float) -> float:
        return 0.2 * xx

    traj = terrain.sample_ballistic_trajectory(
        terrain_line,
        x=0.0,
        y=80.0,
        vx=22.0,
        vy_up=0.0,
        max_distance=2000.0,
        segment_length=60.0,
    )
    assert traj.hit
    assert traj.hit_x is not None
    assert traj.hit_y is not None
    terrain_y = terrain_line(traj.hit_x)
    assert abs(traj.hit_y - terrain_y) <= 0.75
