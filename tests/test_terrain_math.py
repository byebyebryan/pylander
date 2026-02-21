from __future__ import annotations

import pytest

from core.landing_sites import LandingSiteSurfaceModel, LandingSiteTerrainModifier, to_view
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
