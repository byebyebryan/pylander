from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Any

if TYPE_CHECKING:
    from core.bot import Bot, Sensors
    from core.ecs import World
    from core.systems.sensor_update import SensorUpdateSystem
    from core.terrain import Terrain
    from bot_framework.bot_profiler import BotLoopProfiler
    from utils.tracepack import TraceRecorder


@dataclass
class BotLoopContext:
    ecs_world: World
    actor_bots: dict[str, Bot]
    sensor_update_system: SensorUpdateSystem
    profiler: BotLoopProfiler
    terrain: Terrain
    build_sensors: Callable[[Any, Any], "Sensors"]
    trace_recorder: TraceRecorder | None = None
