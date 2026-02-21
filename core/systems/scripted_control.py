from __future__ import annotations

from core.components import (
    ActorControlRole,
    ControlIntent,
    Engine,
    KinematicMotion,
    ScriptController,
    ScriptFrame,
    Transform,
)
from core.ecs import Entity, System


class ScriptedControlSystem(System):
    """Advance scripted frames and project them into actor state/components."""

    def update(self, dt: float) -> None:
        if not self.world:
            return
        for entity in self.world.get_entities_with(ScriptController, ActorControlRole):
            script = entity.get_component(ScriptController)
            role = entity.get_component(ActorControlRole)
            if script is None or role is None:
                continue
            if role.role != "script" or not script.enabled:
                continue
            self._advance(entity, script, dt)

    def _advance(self, entity: Entity, script: ScriptController, dt: float) -> None:
        if not script.frames:
            return

        frame = script.frames[min(script.frame_index, len(script.frames) - 1)]
        self._apply_frame(entity, frame)

        script.frame_elapsed += max(0.0, dt)
        while script.frame_elapsed >= max(frame.duration, 1e-6):
            script.frame_elapsed -= max(frame.duration, 1e-6)
            next_index = script.frame_index + 1
            if next_index >= len(script.frames):
                if not script.loop:
                    script.frame_index = len(script.frames) - 1
                    script.frame_elapsed = max(frame.duration, 1e-6)
                    return
                next_index = 0
            script.frame_index = next_index
            frame = script.frames[script.frame_index]
            self._apply_frame(entity, frame)

    @staticmethod
    def _apply_frame(entity: Entity, frame: ScriptFrame) -> None:
        intent = entity.get_component(ControlIntent)
        engine = entity.get_component(Engine)
        motion = entity.get_component(KinematicMotion)
        trans = entity.get_component(Transform)

        if intent is not None:
            intent.refuel_requested = bool(frame.refuel)
            intent.target_thrust = frame.target_thrust
            intent.target_angle = frame.target_angle

        if engine is not None:
            if frame.target_thrust is not None:
                engine.target_thrust = max(0.0, min(1.0, frame.target_thrust))
            if frame.target_angle is not None:
                engine.target_angle = frame.target_angle

        if frame.velocity is not None:
            if motion is not None:
                motion.velocity = frame.velocity
            elif trans is not None:
                trans.pos += frame.velocity
