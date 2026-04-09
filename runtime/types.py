from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.bot import Bot
    from core.ecs import World
    from core.systems.sensor_update import SensorUpdateSystem
    from core.terrain import Terrain
    from runtime.bot_profiler import BotLoopProfiler
    from utils.tracepack import TraceRecorder


@dataclass
class BotLoopContext:
    ecs_world: World
    actor_bots: dict[str, Bot]
    sensor_update_system: SensorUpdateSystem
    profiler: BotLoopProfiler
    terrain: Terrain
    trace_recorder: TraceRecorder | None = None
