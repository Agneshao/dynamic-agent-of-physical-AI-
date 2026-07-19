"""Thread-safe single writer for the mutable world state."""

from __future__ import annotations

from threading import RLock
from typing import Any, Type

from pydantic import ValidationError

from runtime_core.schemas.events import Event
from runtime_core.schemas.world_state import (
    MachineState,
    PersonState,
    ResourceReservationState,
    RouteState,
    TaskState,
    WeatherState,
    WorldState,
    ZoneState,
    utc_now,
)

from .version_manager import VersionManager


class WorldStateError(RuntimeError):
    """Base class for world state kernel errors."""


class InvalidWorldUpdateError(WorldStateError):
    """Raised when a candidate state fails full schema validation."""


class DuplicateEventError(WorldStateError):
    """Raised when an already committed deduplication key is received."""


class UnsupportedEventTypeError(WorldStateError):
    """Raised when the kernel has no deterministic handler for an event type."""


class MachineNotFoundError(WorldStateError):
    """Raised when a machine update targets an unknown machine."""


class PersonNotFoundError(WorldStateError):
    """Raised when a person update targets an unknown person."""


class ZoneNotFoundError(WorldStateError):
    """Raised when a zone update targets an unknown zone."""


class TaskNotFoundError(WorldStateError):
    """Raised when a task update targets an unknown task."""


class RouteNotFoundError(WorldStateError):
    """Raised when a route update targets an unknown route."""


class ResourceReservationNotFoundError(WorldStateError):
    """Raised when a reservation update targets an unknown reservation."""


class WorldStateKernel:
    """Own and atomically mutate the runtime's authoritative world state."""

    def __init__(self, initial_state: WorldState | None = None) -> None:
        validated = WorldState.model_validate(
            (initial_state or WorldState()).model_dump(mode="python")
        )
        self._lock = RLock()
        self._state = validated
        self._version_manager = VersionManager(validated.world_version)
        self._processed_deduplication_keys: set[str] = set()

    def get_current_state(self) -> WorldState:
        """Return a deep validated copy, never the internal state object."""
        with self._lock:
            return self._copy_state_locked()

    def get_world_version(self) -> int:
        """Return the currently committed world version."""
        with self._lock:
            return self._version_manager.world_version

    def update_machine(self, machine: MachineState) -> WorldState:
        """Replace an existing machine and increment version only on real change."""
        with self._lock:
            return self._update_mapping_item_locked(
                mapping_name="machines",
                entity_id=machine.machine_id,
                entity=machine,
                missing_error=MachineNotFoundError,
            )

    def update_person(self, person: PersonState) -> WorldState:
        """Replace an existing person and increment version only on real change."""
        with self._lock:
            return self._update_mapping_item_locked(
                mapping_name="people",
                entity_id=person.person_id,
                entity=person,
                missing_error=PersonNotFoundError,
            )

    def update_zone(self, zone: ZoneState) -> WorldState:
        """Replace an existing zone and increment version only on real change."""
        with self._lock:
            return self._update_mapping_item_locked(
                mapping_name="zones",
                entity_id=zone.zone_id,
                entity=zone,
                missing_error=ZoneNotFoundError,
            )

    def update_weather(self, weather: WeatherState) -> WorldState:
        """Replace weather state and increment version only on real change."""
        with self._lock:
            if self._state.weather == weather:
                return self._copy_state_locked()
            candidate = self._state.model_dump(mode="python")
            candidate["weather"] = weather.model_dump(mode="python")
            return self._commit_candidate_locked(candidate)

    def update_new_tasks_frozen(self, frozen: bool) -> WorldState:
        """Set the authoritative task-admission freeze flag on real change."""
        with self._lock:
            if self._state.new_tasks_frozen == frozen:
                return self._copy_state_locked()
            candidate = self._state.model_dump(mode="python")
            candidate["new_tasks_frozen"] = frozen
            return self._commit_candidate_locked(candidate)

    def apply_event(self, event: Event) -> WorldState:
        """Apply one supported event atomically and record its key after commit."""
        with self._lock:
            if event.deduplication_key in self._processed_deduplication_keys:
                raise DuplicateEventError(event.deduplication_key)

            previous_version = self._version_manager.world_version
            result = self._dispatch_event_locked(event)
            if self._version_manager.world_version > previous_version:
                self._processed_deduplication_keys.add(event.deduplication_key)
            return result

    def _dispatch_event_locked(self, event: Event) -> WorldState:
        event_handlers = {
            "machine.updated": (MachineState, "machines", "machine_id", MachineNotFoundError),
            "person.updated": (PersonState, "people", "person_id", PersonNotFoundError),
            "zone.updated": (ZoneState, "zones", "zone_id", ZoneNotFoundError),
            "task.updated": (TaskState, "tasks", "task_id", TaskNotFoundError),
            "route.updated": (RouteState, "routes", "route_id", RouteNotFoundError),
            "resource_reservation.updated": (
                ResourceReservationState,
                "resource_reservations",
                "reservation_id",
                ResourceReservationNotFoundError,
            ),
        }
        if event.event_type == "weather.updated":
            weather = WeatherState.model_validate(event.payload)
            if self._state.weather == weather:
                return self._copy_state_locked()
            candidate = self._state.model_dump(mode="python")
            candidate["weather"] = weather.model_dump(mode="python")
            return self._commit_candidate_locked(candidate)

        handler = event_handlers.get(event.event_type)
        if handler is None:
            raise UnsupportedEventTypeError(event.event_type)

        model_type, mapping_name, id_field, missing_error = handler
        entity = model_type.model_validate(event.payload)
        entity_id = getattr(entity, id_field)
        return self._update_mapping_item_locked(
            mapping_name=mapping_name,
            entity_id=entity_id,
            entity=entity,
            missing_error=missing_error,
        )

    def _update_mapping_item_locked(
        self,
        *,
        mapping_name: str,
        entity_id: str,
        entity: Any,
        missing_error: Type[WorldStateError],
    ) -> WorldState:
        current_mapping = getattr(self._state, mapping_name)
        if entity_id not in current_mapping:
            raise missing_error(entity_id)
        if current_mapping[entity_id] == entity:
            return self._copy_state_locked()

        candidate = self._state.model_dump(mode="python")
        candidate_mapping = dict(candidate[mapping_name])
        candidate_mapping[entity_id] = entity.model_dump(mode="python")
        candidate[mapping_name] = candidate_mapping
        return self._commit_candidate_locked(candidate)

    def _commit_candidate_locked(self, candidate: dict[str, Any]) -> WorldState:
        next_version = self._version_manager.next_world_version()
        candidate["world_version"] = next_version
        candidate["timestamp"] = utc_now()
        try:
            validated = WorldState.model_validate(candidate)
        except ValidationError as exc:
            raise InvalidWorldUpdateError("candidate world state failed validation") from exc

        self._version_manager.commit_world_version(next_version)
        self._state = validated
        return self._copy_state_locked()

    def _copy_state_locked(self) -> WorldState:
        return WorldState.model_validate(self._state.model_dump(mode="python"))
