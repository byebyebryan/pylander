from __future__ import annotations

from core.components import Radar, RefuelConfig, SensorReadings, Transform
from core.ecs import System
from core.sensor import get_proximity_contact, get_radar_contacts


class SensorUpdateSystem(System):
    """Compute and cache radar/proximity readings on entities."""

    def __init__(self, terrain, targets):
        super().__init__()
        self.terrain = terrain
        self.targets = targets

    def update(self, dt: float) -> None:
        _ = dt
        if not self.world:
            return

        for entity in self.world.get_entities_with(Transform, Radar, RefuelConfig, SensorReadings):
            trans = entity.get_component(Transform)
            radar = entity.get_component(Radar)
            cfg = entity.get_component(RefuelConfig)
            readings = entity.get_component(SensorReadings)
            if None in (trans, radar, cfg, readings):
                continue
            readings.radar_contacts = get_radar_contacts(
                trans.pos,
                self.targets,
                inner_range=radar.inner_range,
                outer_range=radar.outer_range,
            )
            readings.proximity = get_proximity_contact(
                trans.pos,
                self.terrain,
                range=cfg.proximity_sensor_range,
            )
