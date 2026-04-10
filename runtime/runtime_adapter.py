"""Bot runtime integration adapter: narrows the engine↔bot runtime boundary.

Phase 2 extracts the bot/no-bot selection branching from LanderGame into a
dedicated adapter object so the constructor depends on the interface rather
than concrete bootstrap functions.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from core.bot import Bot, BotEvalDecision
    from core.ecs import World
    from runtime.bootstrap import SystemsBundle
    from runtime.bot_profiler import BotLoopProfiler
    from runtime.game_bootstrap import BotRuntimeBootstrap, TraceRuntimeBootstrap
    from core.physics import PhysicsEngine


@dataclass(frozen=True)
class EvalHooks:
    prime_boost_cutoff_for_primary_bot: Callable[[Any, dict[str, Bot]], None]
    track_plot_events: Callable[..., None]
    print_headless_stats: Callable[..., None]
    resolve_headless_bot_eval_decision: Callable[..., BotEvalDecision | None]
    merge_bot_snapshots_into_result: Callable[..., None]
    apply_bot_eval_to_result: Callable[..., None]


def build_default_eval_hooks() -> EvalHooks:
    from bot_framework.eval.boost_cutoff import prime_boost_cutoff_for_primary_bot
    from bot_framework.eval.headless_stats import print_headless_stats
    from bot_framework.eval.plot_events import track_plot_events
    from bot_framework.eval.result_pipeline import (
        apply_bot_eval_to_result,
        merge_bot_snapshots_into_result,
        resolve_headless_bot_eval_decision,
    )

    return EvalHooks(
        prime_boost_cutoff_for_primary_bot=prime_boost_cutoff_for_primary_bot,
        track_plot_events=track_plot_events,
        print_headless_stats=print_headless_stats,
        resolve_headless_bot_eval_decision=resolve_headless_bot_eval_decision,
        merge_bot_snapshots_into_result=merge_bot_snapshots_into_result,
        apply_bot_eval_to_result=apply_bot_eval_to_result,
    )


def build_noop_eval_hooks() -> EvalHooks:
    def noop_prime(level, actor_bots):
        pass

    def noop_track_plot_events(**kwargs):
        pass

    def noop_print_headless_stats(**kwargs):
        pass

    def noop_resolve_headless_bot_eval_decision(**kwargs):
        return None

    def noop_merge_bot_snapshots_into_result(**kwargs):
        pass

    def noop_apply_bot_eval_to_result(result, eval_goal, **kwargs):
        result["eval_goal"] = eval_goal
        result["eval_early_end"] = False

    return EvalHooks(
        prime_boost_cutoff_for_primary_bot=noop_prime,
        track_plot_events=noop_track_plot_events,
        print_headless_stats=noop_print_headless_stats,
        resolve_headless_bot_eval_decision=noop_resolve_headless_bot_eval_decision,
        merge_bot_snapshots_into_result=noop_merge_bot_snapshots_into_result,
        apply_bot_eval_to_result=noop_apply_bot_eval_to_result,
    )


class BotRuntimeAdapter(ABC):
    """Protocol for bot runtime wiring.

    Adapters handle the selection of bot-runtime bootstrap, trace-runtime
    bootstrap, and eval hooks so LanderGame does not branch on bot presence.
    """

    @abstractmethod
    def resolve(
        self,
        *,
        level: Any,
        actors: list[Any],
        ecs_world: World,
        world_bots: Any,
        primary_bot: Bot | None,
        active_uid: str,
        active_uid_getter: Callable[[], str],
        systems: SystemsBundle,
        profiler: BotLoopProfiler,
        terrain: Any,
        engine: PhysicsEngine,
        seed: int,
        headless: bool,
        eval_goal: str,
    ) -> tuple[
        BotRuntimeBootstrap,
        TraceRuntimeBootstrap,
        EvalHooks,
        set[tuple[str, str]],
    ]:
        """Resolve all bot-runtime dependencies.

        Returns (bot_runtime, trace_runtime, eval_hooks, plot_events_seen).
        """
        raise NotImplementedError


class FullBotRuntimeAdapter(BotRuntimeAdapter):
    def resolve(
        self,
        *,
        level: Any,
        actors: list[Any],
        ecs_world: World,
        world_bots: Any,
        primary_bot: Bot | None,
        active_uid: str,
        active_uid_getter: Callable[[], str],
        systems: SystemsBundle,
        profiler: BotLoopProfiler,
        terrain: Any,
        engine: PhysicsEngine,
        seed: int,
        headless: bool,
        eval_goal: str,
    ) -> tuple[
        BotRuntimeBootstrap,
        TraceRuntimeBootstrap,
        EvalHooks,
        set[tuple[str, str]],
    ]:
        from runtime.game_bootstrap import (
            bootstrap_bot_runtime,
            bootstrap_trace_runtime,
        )

        bot_runtime = bootstrap_bot_runtime(
            level=level,
            actors=actors,
            ecs_world=ecs_world,
            world_bots=world_bots,
            primary_bot=primary_bot,
            active_uid=active_uid,
            systems=systems,
            profiler=profiler,
            terrain=terrain,
            engine=engine,
        )
        trace_runtime = bootstrap_trace_runtime(
            terrain=terrain,
            ecs_world=ecs_world,
            actor_bots=bot_runtime.actor_bots,
            active_uid_getter=active_uid_getter,
            headless=headless,
            level=level,
            seed=seed,
        )
        plot_events_seen = trace_runtime.events_seen

        eval_hooks = build_default_eval_hooks()

        return bot_runtime, trace_runtime, eval_hooks, plot_events_seen


class NoBotRuntimeAdapter(BotRuntimeAdapter):
    def resolve(
        self,
        *,
        level: Any,
        actors: list[Any],
        ecs_world: World,
        world_bots: Any,
        primary_bot: Bot | None,
        active_uid: str,
        active_uid_getter: Callable[[], str],
        systems: SystemsBundle,
        profiler: BotLoopProfiler,
        terrain: Any,
        engine: PhysicsEngine,
        seed: int,
        headless: bool,
        eval_goal: str,
    ) -> tuple[
        BotRuntimeBootstrap,
        TraceRuntimeBootstrap,
        EvalHooks,
        set[tuple[str, str]],
    ]:
        from runtime.game_bootstrap import (
            bootstrap_empty_bot_runtime,
            bootstrap_null_trace_runtime,
        )

        bot_runtime = bootstrap_empty_bot_runtime(
            level=level,
            actors=actors,
            ecs_world=ecs_world,
            world_bots=world_bots,
            primary_bot=primary_bot,
            active_uid=active_uid,
            systems=systems,
            profiler=profiler,
            terrain=terrain,
            engine=engine,
        )
        trace_runtime = bootstrap_null_trace_runtime(
            terrain=terrain,
            ecs_world=ecs_world,
            actor_bots=bot_runtime.actor_bots,
            active_uid_getter=active_uid_getter,
            headless=headless,
            level=level,
            seed=seed,
        )
        plot_events_seen = trace_runtime.events_seen
        eval_hooks = build_noop_eval_hooks()
        return bot_runtime, trace_runtime, eval_hooks, plot_events_seen


def make_runtime_adapter(bot: Bot | None, headless: bool) -> BotRuntimeAdapter:
    """Factory that returns the appropriate runtime adapter based on bot presence.

    This is the single entry point for runtime adapter selection, keeping the
    branching logic out of LanderGame.__init__.
    """
    if headless and bot is None:
        raise ValueError("Headless mode requires a bot")
    if bot is None:
        return NoBotRuntimeAdapter()
    return FullBotRuntimeAdapter()


__all__ = [
    "BotRuntimeAdapter",
    "EvalHooks",
    "FullBotRuntimeAdapter",
    "NoBotRuntimeAdapter",
    "build_default_eval_hooks",
    "build_noop_eval_hooks",
    "make_runtime_adapter",
]
