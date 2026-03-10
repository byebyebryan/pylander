from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

from core.bot import BotAction


class FlightStage(str, Enum):
    TAKEOFF = "takeoff"
    SETUP = "setup"
    COAST = "coast"
    FLARE = "flare"
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
        return StageTickResult(next_stage=FlightStage.SETUP)


class PDGSetupController(StageController):
    def __init__(self) -> None:
        super().__init__(FlightStage.SETUP)

    def update(self, bot, ctx) -> StageTickResult:
        if ctx.suggested_stage != self.stage:
            return StageTickResult(next_stage=ctx.suggested_stage)
        return StageTickResult(action=bot._run_pdg_stage(ctx=ctx, stage=self.stage))


class BallisticCoastController(StageController):
    def __init__(self) -> None:
        super().__init__(FlightStage.COAST)

    def update(self, bot, ctx) -> StageTickResult:
        if ctx.suggested_stage != self.stage:
            return StageTickResult(next_stage=ctx.suggested_stage)
        flare_gate = bot._evaluate_flare_gate(
            dt=ctx.dt,
            passive=ctx.passive,
            dx=ctx.dx,
            dy=ctx.dy,
            alt=ctx.alt,
            max_thrust_accel=ctx.max_thrust_accel,
            min_thrust_accel=ctx.min_thrust_accel,
            nominal_thrust_accel=ctx.nominal_thrust_accel,
            thrust_ramp_up=ctx.ramp_up,
        )
        if flare_gate is not None:
            bot._finalize_flare_entry(
                passive=ctx.passive,
                alt=ctx.alt,
                projected_dx=float(ctx.projection.projected_dx),
                mode=flare_gate.mode,
                horizon_s=flare_gate.burn_time_s,
                terminal_speed=None,
                peak_accel_ratio=None,
                od_excess_s=None,
                latest_safe_margin_s=flare_gate.latest_safe_margin_s,
                required_accel_ratio=flare_gate.required_accel_ratio,
            )
            return StageTickResult(next_stage=FlightStage.FLARE)

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


class PDGFlareController(StageController):
    def __init__(self) -> None:
        super().__init__(FlightStage.FLARE)

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
    "PDGFlareController",
    "PDGSetupController",
    "StageController",
    "StageTickResult",
    "TakeoffBootstrapController",
    "TouchdownBrakeController",
]
