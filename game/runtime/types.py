from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Any

from game.runtime.profiler import BotProfiler

if TYPE_CHECKING:
    from game.core.bot import Bot, Sensors
    from game.core.ecs import World
    from game.core.systems.sensor_update import SensorUpdateSystem
    from game.core.terrain import Terrain
    from tooling.tracepack import TraceRecorder


@dataclass
class BotLoopContext:
    ecs_world: World
    actor_bots: dict[str, Bot]
    sensor_update_system: SensorUpdateSystem
    profiler: BotProfiler
    terrain: Terrain
    build_sensors: Callable[[Any, Any], "Sensors"]
    trace_recorder: TraceRecorder | None = None
