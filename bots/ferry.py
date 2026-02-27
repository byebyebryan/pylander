"""Pad-to-pad ferry bot: upright liftoff, then launch/coast/flare stack."""

from __future__ import annotations

from bots.launch import LaunchBot
from core.bot import ActiveSensors, Bot, BotAction, PassiveSensors, VehicleInfo
from core.sensor import RadarContact

_FERRY_BEHAVIORS = ("ferry",)
_TAKEOFF_SAFE_ALTITUDE = 100.0
_TAKEOFF_THRUST_TARGET = 0.9


class FerryBot(Bot):
    def __init__(self, behavior: str = "ferry") -> None:
        super().__init__()
        self._delegate = LaunchBot(behavior="launch")
        self._behavior = "ferry"
        self._source_site_uid: str | None = None
        self._destination_site_uid: str | None = None
        self._pad_clear = False
        self._arrived = False
        self.set_behavior(behavior)

    @property
    def behavior(self) -> str:
        return self._behavior

    def set_vehicle_info(self, info: VehicleInfo) -> None:
        super().set_vehicle_info(info)
        self._delegate.set_vehicle_info(info)

    def set_behavior(self, behavior: str) -> None:
        key = str(behavior).strip().lower()
        if key not in _FERRY_BEHAVIORS:
            known = ", ".join(_FERRY_BEHAVIORS)
            raise ValueError(f"Unknown ferry behavior '{behavior}'. Expected one of: {known}")
        self._behavior = "ferry"
        self._source_site_uid = None
        self._destination_site_uid = None
        self._pad_clear = False
        self._arrived = False
        self.set_pinned_target_uid(None)
        self._delegate.set_pinned_target_uid(None)
        self._delegate.set_behavior("launch")

    def _takeoff_thrust(self) -> float:
        max_thrust = 1.6
        if self.vehicle_info is not None:
            max_thrust = max(0.0, float(self.vehicle_info.max_thrust))
        return max(0.0, min(max_thrust, _TAKEOFF_THRUST_TARGET))

    def _choose_destination_contact(
        self,
        passive: PassiveSensors,
    ) -> RadarContact | None:
        contacts = passive.radar_contacts or []
        if not contacts:
            return None
        if passive.state == "landed":
            landed_uid = contacts[0].uid
            if (
                self._destination_site_uid is not None
                and landed_uid is not None
                and landed_uid == self._destination_site_uid
            ):
                return contacts[0]
            self._source_site_uid = landed_uid
            self._destination_site_uid = None
            self._arrived = False
        if self._destination_site_uid is not None:
            for contact in contacts:
                if contact.uid == self._destination_site_uid:
                    return contact
        if self._source_site_uid is not None:
            for contact in contacts:
                if contact.uid is not None and contact.uid != self._source_site_uid:
                    self._destination_site_uid = contact.uid
                    return contact
        fallback = max(contacts, key=lambda contact: abs(float(contact.rel_x)))
        if fallback.uid is not None and fallback.uid != self._source_site_uid:
            self._destination_site_uid = fallback.uid
        return fallback

    def _is_landed_on_destination(self, passive: PassiveSensors) -> bool:
        if passive.state != "landed":
            return False
        if self._destination_site_uid is None:
            return False
        contacts = passive.radar_contacts or []
        if not contacts:
            return False
        landed_uid = contacts[0].uid
        if landed_uid is not None:
            return landed_uid == self._destination_site_uid
        return any(contact.uid == self._destination_site_uid for contact in contacts)

    def _handoff_to_launch_action(self) -> BotAction:
        action = BotAction(
            target_thrust=self._takeoff_thrust(),
            target_angle=0.0,
            refuel=False,
            status="ferry:handoff_launch",
            handoff_to=self._delegate,
            active_bot="launch",
            stage="handoff",
        )
        self.status = action.status
        return action

    def update(
        self,
        dt: float,
        passive: PassiveSensors,
        active: ActiveSensors,
    ) -> BotAction:
        if self._arrived and passive.state == "landed":
            if self._is_landed_on_destination(passive):
                action = BotAction(
                    target_thrust=0.0,
                    target_angle=0.0,
                    refuel=False,
                    status="ferry:arrived",
                )
                self.status = action.status
                return action
            # If we're landed somewhere else, clear the arrival latch and
            # continue normal target/launch flow.
            self._arrived = False

        if passive.state in ("crashed", "out_of_fuel"):
            action = BotAction(
                target_thrust=0.0,
                target_angle=float(passive.angle),
                refuel=False,
                status=f"ferry:{passive.state}",
            )
            self.status = action.status
            return action

        _ = self._choose_destination_contact(passive)
        pinned_uid = self._destination_site_uid
        self.set_pinned_target_uid(pinned_uid)
        self._delegate.set_pinned_target_uid(pinned_uid)
        if self._is_landed_on_destination(passive):
            self._arrived = True
            action = BotAction(
                target_thrust=0.0,
                target_angle=0.0,
                refuel=False,
                status="ferry:arrived",
            )
            self.status = action.status
            return action
        if passive.state in ("landed", "flying"):
            if passive.state == "landed":
                self._delegate.set_behavior("launch")
                self._pad_clear = False
                action = BotAction(
                    target_thrust=self._takeoff_thrust(),
                    target_angle=0.0,
                    refuel=False,
                    status="ferry:takeoff_upright",
                )
                self.status = action.status
                return action

            if not self._pad_clear:
                altitude = float(passive.altitude)
                if altitude <= _TAKEOFF_SAFE_ALTITUDE:
                    action = BotAction(
                        target_thrust=self._takeoff_thrust(),
                        target_angle=0.0,
                        refuel=False,
                        status="ferry:clear_pad",
                    )
                    self.status = action.status
                    return action
                # Hand off once clear of the departure pad.
                self._delegate.set_behavior("launch")
                self._pad_clear = True
                return self._handoff_to_launch_action()
            return self._handoff_to_launch_action()
        action = BotAction(
            target_thrust=0.0,
            target_angle=float(passive.angle),
            refuel=False,
            status="ferry:idle",
        )
        self.status = action.status
        return action

    def get_headless_stats(self) -> str:
        delegate_stats = self._delegate.get_headless_stats()
        if not delegate_stats:
            return "ferry"
        return f"ferry {delegate_stats}"


def list_behavior_names() -> tuple[str, ...]:
    return _FERRY_BEHAVIORS


def create_bot() -> Bot:
    return FerryBot()
