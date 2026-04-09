from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

from core.bot import BotAction


class FlightStage(str, Enum):
    TAKEOFF = "takeoff"
    BOOST = "boost"
    COAST = "coast"
    TERMINAL = "terminal"
    TOUCHDOWN = "touchdown"


@dataclass(frozen=True)
class StageTickResult:
    action: BotAction | None = None
    next_stage: FlightStage | None = None


class StageController(ABC):
    def __init__(self, stage: FlightStage) -> None:
        self.stage = stage

    def enter(self, bot, ctx) -> None:
        _ = bot, ctx

    def exit(self, bot, ctx) -> None:
        _ = bot, ctx

    @abstractmethod
    def update(self, bot, ctx) -> StageTickResult:
        raise NotImplementedError


class TakeoffBootstrapController(StageController):
    def __init__(self) -> None:
        super().__init__(FlightStage.TAKEOFF)

    def update(self, bot, ctx) -> StageTickResult:
        if ctx.passive.state == "landed" or ctx.alt < bot._cfg.launch_takeoff_clear_altitude:
            summary = "departing pad" if ctx.passive.state == "landed" else "clearing pad"
            action = BotAction(
                bot._takeoff_thrust(ctx.max_throttle),
                0.0,
                False,
                status=f"pdg {self.stage.value}",
            )
            bot._set_display_state(mode="takeoff", phase=self.stage.value, summary=summary)
            return StageTickResult(action=action)
        return StageTickResult(next_stage=FlightStage.BOOST)


class PDGBoostController(StageController):
    def __init__(self) -> None:
        super().__init__(FlightStage.BOOST)

    def update(self, bot, ctx) -> StageTickResult:
        return bot._run_boost_controller(ctx=ctx)


class BallisticCoastController(StageController):
    def __init__(self) -> None:
        super().__init__(FlightStage.COAST)

    def update(self, bot, ctx) -> StageTickResult:
        if ctx.suggested_stage != self.stage:
            return StageTickResult(next_stage=ctx.suggested_stage)
        terminal_gate = bot._evaluate_terminal_gate(
            dt=ctx.dt,
            passive=ctx.passive,
            dx=ctx.dx,
            projected_dx=float(ctx.projection.projected_dx),
            dy=ctx.dy,
            alt=ctx.alt,
            max_thrust_accel=ctx.max_thrust_accel,
            min_thrust_accel=ctx.min_thrust_accel,
            nominal_thrust_accel=ctx.nominal_thrust_accel,
            thrust_ramp_up=ctx.ramp_up,
        )
        if terminal_gate is not None:
            bot._finalize_terminal_entry(
                passive=ctx.passive,
                dx=ctx.dx,
                alt=ctx.alt,
                projected_dx=float(ctx.projection.projected_dx),
                mode=terminal_gate.mode,
                horizon_s=terminal_gate.burn_time_s,
                terminal_speed=None,
                peak_accel_ratio=None,
                od_excess_s=None,
                latest_safe_margin_s=terminal_gate.latest_safe_margin_s,
                required_accel_ratio=terminal_gate.required_accel_ratio,
            )
            return StageTickResult(next_stage=FlightStage.TERMINAL)

        action = bot._command_passive_coast(
            dt=ctx.dt,
            passive=ctx.passive,
        )
        action.status = (
            f"pdg passive/{self.stage.value} "
            f"dx={bot._stable(ctx.dx, 1):.1f} pdx={bot._stable(float(ctx.projection.projected_dx), 1):.1f}"
        )
        bot._set_display_state(
            mode="passive",
            phase=self.stage.value,
            summary=(
                f"dx={bot._stable(ctx.dx, 1):.1f} "
                f"pdx={bot._stable(float(ctx.projection.projected_dx), 1):.1f}"
            ),
        )
        return StageTickResult(action=action)


class PDGTerminalController(StageController):
    def __init__(self) -> None:
        super().__init__(FlightStage.TERMINAL)

    def update(self, bot, ctx) -> StageTickResult:
        if ctx.suggested_stage == FlightStage.TOUCHDOWN:
            return StageTickResult(next_stage=FlightStage.TOUCHDOWN)
        return StageTickResult(action=bot._run_pdg_stage(ctx=ctx, stage=self.stage))


class TouchdownBrakeController(StageController):
    def __init__(self) -> None:
        super().__init__(FlightStage.TOUCHDOWN)

    def update(self, bot, ctx) -> StageTickResult:
        return StageTickResult(action=bot._run_pdg_stage(ctx=ctx, stage=self.stage))


__all__ = [
    "BallisticCoastController",
    "FlightStage",
    "PDGTerminalController",
    "PDGBoostController",
    "StageController",
    "StageTickResult",
    "TakeoffBootstrapController",
    "TouchdownBrakeController",
]
