from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from typing import Type, TypeVar, Any

T = TypeVar("T")


class Entity:
    """A container for components with a unique ID."""

    def __init__(self, uid: str | None = None):
        self.uid = uid or str(uuid.uuid4())
        self.components: dict[Type, Any] = {}
        self.active = True

    def add_component(self, component: Any) -> None:
        self.components[type(component)] = component

    def get_component(self, component_type: Type[T]) -> T | None:
        return self.components.get(component_type)

    def has_component(self, component_type: Type) -> bool:
        return component_type in self.components

    def remove_component(self, component_type: Type) -> None:
        if component_type in self.components:
            del self.components[component_type]


class System(ABC):
    """Base class for systems that operate on entities with specific components."""

    def __init__(self):
        self.world: World | None = None

    @abstractmethod
    def update(self, dt: float):
        pass


class World:
    """Manages entities and systems."""

    def __init__(self):
        self.entities: list[Entity] = []
        self.systems: list[System] = []
        self._entity_map: dict[str, Entity] = {}

    def add_entity(self, entity: Entity) -> None:
        if entity.uid not in self._entity_map:
            self.entities.append(entity)
            self._entity_map[entity.uid] = entity

    def remove_entity(self, entity: Entity) -> None:
        if entity.uid in self._entity_map:
            self.entities.remove(entity)
            del self._entity_map[entity.uid]

    def add_system(self, system: System) -> None:
        system.world = self
        self.systems.append(system)

    def get_entities_with(self, *component_types: Type) -> list[Entity]:
        """Return all entities that have ALL of the specified component types."""
        result = []
        for entity in self.entities:
            if all(entity.has_component(ct) for ct in component_types):
                result.append(entity)
        return result

    def update(self, dt: float) -> None:
        for system in self.systems:
            system.update(dt)

    def get_entity_by_id(self, uid: str) -> Entity | None:
        return self._entity_map.get(uid)


def require_component(entity: Entity, component_type: Type[T]) -> T:
    """Get a required component, raising RuntimeError if absent."""
    comp = entity.get_component(component_type)
    if comp is None:
        raise RuntimeError(f"Entity {entity.uid} missing component {component_type.__name__}")
    return comp
