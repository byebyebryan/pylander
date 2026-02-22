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
