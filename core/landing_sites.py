from __future__ import annotations

import random
from dataclasses import dataclass, field

from core.maths import Range1D, Vector2


@dataclass
class LandingSiteSeed:
    uid: str
    x: float
    y: float
    size: float
    award: float
    fuel_price: float
    terrain_mode: str
    terrain_bound: bool
    blend_margin: float = 20.0
    cut_depth: float = 30.0
    support_height: float = 40.0
    velocity: Vector2 = field(default_factory=lambda: Vector2(0.0, 0.0))
    parent_uid: str | None = None
    local_offset: Vector2 = field(default_factory=lambda: Vector2(0.0, 0.0))


@dataclass
class LandingSiteView:
    uid: str
    x: float
    y: float
    size: float
    vel: Vector2
    award: float
    fuel_price: float
    terrain_mode: str
    terrain_bound: bool
    blend_margin: float
    cut_depth: float
    support_height: float
    visited: bool

    @property
    def info(self) -> dict:
        return {
            "award": 0.0 if self.visited else self.award,
            "fuel_price": self.fuel_price,
        }


class LandingSiteSurfaceModel:
    """Read-model for landing-site queries used by systems and UI."""

    def __init__(self, initial_sites: list[LandingSiteView] | None = None):
        self._sites: dict[str, LandingSiteView] = {}
        if initial_sites:
            self.update_from_views(initial_sites)

    def update_from_views(self, sites: list[LandingSiteView]) -> None:
        self._sites = {s.uid: s for s in sites}

    def get_sites(self, span: Range1D) -> list[LandingSiteView]:
        center_x = (span.min + span.max) * 0.5
        half_span = span.span * 0.5
        out: list[LandingSiteView] = []
        for site in self._sites.values():
            if (
                site.x - site.size / 2.0 - half_span
                <= center_x
                <= site.x + site.size / 2.0 + half_span
            ):
                out.append(site)
        out.sort(key=lambda s: abs(s.x - center_x))
        return out

    def get_site(self, uid: str) -> LandingSiteView | None:
        return self._sites.get(uid)

    def consume_award(self, uid: str) -> float:
        site = self._sites.get(uid)
        if site is None or site.visited or site.award == 0.0:
            return 0.0
        self._sites[uid] = LandingSiteView(
            uid=site.uid,
            x=site.x,
            y=site.y,
            size=site.size,
            vel=Vector2(site.vel),
            award=site.award,
            fuel_price=site.fuel_price,
            terrain_mode=site.terrain_mode,
            terrain_bound=site.terrain_bound,
            blend_margin=site.blend_margin,
            cut_depth=site.cut_depth,
            support_height=site.support_height,
            visited=True,
        )
        return site.award


class LandingSiteTerrainModifier:
    """Terrain modifier derived from landing-site projections."""

    def __init__(self, sites: LandingSiteSurfaceModel):
        self.sites = sites

    def __call__(self, pos: Vector2, y: float, lod: int = 0) -> float:
        out_y = y
        margin = 80.0 * (2**lod)
        nearby = self.sites.get_sites(Range1D.from_center(pos.x, margin))
        for site in nearby:
            if not site.terrain_bound:
                continue
            if site.terrain_mode == "elevated_supports":
                continue
            out_y = self._apply_site_mode(out_y, pos.x, site, lod)
        return out_y

    def _apply_site_mode(
        self, current_y: float, world_x: float, site: LandingSiteView, lod: int
    ) -> float:
        half = site.size * 0.5
        dx = abs(world_x - site.x)
        blend = max(0.0, site.blend_margin * (2**lod))
        if dx > half + blend:
            return current_y

        target_y = site.y
        if site.terrain_mode == "cut_in":
            target_y = min(site.y, current_y - max(0.0, site.cut_depth))
        elif site.terrain_mode == "flush_flatten":
            target_y = site.y

        if dx <= half or blend <= 1e-6:
            return target_y

        t = (dx - half) / blend
        t = max(0.0, min(1.0, t))
        return target_y * (1.0 - t) + current_y * t


def build_seeded_sites(height_at, seed: int, count_each_side: int = 8) -> list[LandingSiteSeed]:
    """Generate deterministic terrain-independent site seeds around origin."""
    rng = random.Random(seed)

    def _make_site(idx: int, x: float) -> LandingSiteSeed:
        size = rng.uniform(50.0, 100.0)
        fuel_price = round(rng.uniform(5.0, 15.0) * 2.0) / 2.0
        award = rng.uniform(100.0, 500.0)
        roll = rng.random()
        if roll < 0.55:
            mode = "flush_flatten"
            y = height_at(x) + rng.uniform(-40.0, 40.0)
            terrain_bound = True
        elif roll < 0.8:
            mode = "cut_in"
            y = height_at(x) - rng.uniform(20.0, 80.0)
            terrain_bound = True
        else:
            mode = "elevated_supports"
            y = height_at(x) + rng.uniform(60.0, 180.0)
            terrain_bound = False
        return LandingSiteSeed(
            uid=f"site_{idx}",
            x=x,
            y=y,
            size=size,
            award=award,
            fuel_price=fuel_price,
            terrain_mode=mode,
            terrain_bound=terrain_bound,
            blend_margin=20.0,
            cut_depth=30.0,
            support_height=max(20.0, y - height_at(x)),
            velocity=Vector2(0.0, 0.0),
            parent_uid=None,
            local_offset=Vector2(0.0, 0.0),
        )

    sites: list[LandingSiteSeed] = []
    x_right = rng.uniform(400.0, 1200.0)
    x_left = -rng.uniform(400.0, 1200.0)
    idx = 0
    for _ in range(count_each_side):
        idx += 1
        sites.append(_make_site(idx, x_right))
        x_right += rng.uniform(1000.0, 3000.0)
    for _ in range(count_each_side):
        idx += 1
        sites.append(_make_site(idx, x_left))
        x_left -= rng.uniform(1000.0, 3000.0)

    # Add one moving elevated platform to prove decoupled behavior.
    moving_x = rng.uniform(-600.0, 600.0)
    moving_y = height_at(moving_x) + 140.0
    sites.append(
        LandingSiteSeed(
            uid="site_moving_1",
            x=moving_x,
            y=moving_y,
            size=110.0,
            award=300.0,
            fuel_price=11.0,
            terrain_mode="elevated_supports",
            terrain_bound=False,
            blend_margin=20.0,
            cut_depth=30.0,
            support_height=max(20.0, moving_y - height_at(moving_x)),
            velocity=Vector2(35.0, 0.0),
            parent_uid=None,
            local_offset=Vector2(0.0, 0.0),
        )
    )
    return sites


def to_view(
    *,
    uid: str,
    x: float,
    y: float,
    size: float,
    vel: Vector2,
    award: float,
    fuel_price: float,
    terrain_mode: str,
    terrain_bound: bool,
    blend_margin: float,
    cut_depth: float,
    support_height: float,
    visited: bool,
) -> LandingSiteView:
    return LandingSiteView(
        uid=uid,
        x=x,
        y=y,
        size=size,
        vel=Vector2(vel),
        award=award,
        fuel_price=fuel_price,
        terrain_mode=terrain_mode,
        terrain_bound=terrain_bound,
        blend_margin=blend_margin,
        cut_depth=cut_depth,
        support_height=support_height,
        visited=visited,
    )
