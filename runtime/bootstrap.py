from __future__ import annotations

from dataclasses import dataclass

from core.systems.contact import ContactSystem
from core.systems.control_routing import ControlRoutingSystem
from core.systems.force_application import ForceApplicationSystem
from core.systems.landing_site_motion import LandingSiteMotionSystem
from core.systems.landing_site_projection import LandingSiteProjectionSystem
from core.systems.physics_sync import PhysicsSyncSystem
from core.systems.propulsion import PropulsionSystem
from core.systems.refuel import RefuelSystem
from core.systems.sensor_update import SensorUpdateSystem
from core.systems.scripted_control import ScriptedControlSystem
from core.systems.state_transition import StateTransitionSystem


@dataclass
class SystemsBundle:
    control_routing: ControlRoutingSystem
    state_transition: StateTransitionSystem
    scripted_control: ScriptedControlSystem
    landing_site_motion: LandingSiteMotionSystem
    landing_site_projection: LandingSiteProjectionSystem
    refuel: RefuelSystem
    propulsion: PropulsionSystem
    force_application: ForceApplicationSystem
    physics_sync: PhysicsSyncSystem
    contact: ContactSystem
    sensor_update: SensorUpdateSystem


def create_systems(ecs_world, *, terrain, sites, engine_adapter) -> SystemsBundle:
    bundle = SystemsBundle(
        control_routing=ControlRoutingSystem(),
        state_transition=StateTransitionSystem(),
        scripted_control=ScriptedControlSystem(),
        landing_site_motion=LandingSiteMotionSystem(),
        landing_site_projection=LandingSiteProjectionSystem(sites),
        refuel=RefuelSystem(sites),
        propulsion=PropulsionSystem(),
        force_application=ForceApplicationSystem(engine_adapter),
        physics_sync=PhysicsSyncSystem(engine_adapter),
        contact=ContactSystem(engine_adapter, sites),
        sensor_update=SensorUpdateSystem(terrain, sites),
    )

    for system in (
        bundle.control_routing,
        bundle.state_transition,
        bundle.scripted_control,
        bundle.landing_site_motion,
        bundle.landing_site_projection,
        bundle.refuel,
        bundle.propulsion,
        bundle.force_application,
        bundle.physics_sync,
        bundle.contact,
        bundle.sensor_update,
    ):
        system.world = ecs_world

    return bundle
