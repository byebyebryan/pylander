from __future__ import annotations

from dataclasses import dataclass

from game.core.systems.contact import ContactSystem
from game.core.systems.control_routing import ControlRoutingSystem
from game.core.systems.force_application import ForceApplicationSystem
from game.core.systems.landing_site_motion import LandingSiteMotionSystem
from game.core.systems.landing_site_projection import LandingSiteProjectionSystem
from game.core.systems.physics_sync import PhysicsSyncSystem
from game.core.systems.propulsion import PropulsionSystem
from game.core.systems.refuel import RefuelSystem
from game.core.systems.sensor_update import SensorUpdateSystem
from game.core.systems.scripted_control import ScriptedControlSystem
from game.core.systems.state_transition import StateTransitionSystem


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


def create_systems(ecs_world, *, terrain, sites, engine) -> SystemsBundle:
    bundle = SystemsBundle(
        control_routing=ControlRoutingSystem(),
        state_transition=StateTransitionSystem(),
        scripted_control=ScriptedControlSystem(),
        landing_site_motion=LandingSiteMotionSystem(),
        landing_site_projection=LandingSiteProjectionSystem(sites),
        refuel=RefuelSystem(sites),
        propulsion=PropulsionSystem(),
        force_application=ForceApplicationSystem(engine),
        physics_sync=PhysicsSyncSystem(engine),
        contact=ContactSystem(engine, sites),
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
