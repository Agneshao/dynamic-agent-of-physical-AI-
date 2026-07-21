"""Validated person acknowledgement and shelter-arrival synchronization."""

from __future__ import annotations

from threading import RLock

from runtime_core.schemas.person_safety import (
    PersonSafetySignal,
    PersonSafetySignalType,
    PersonSafetyUpdateResult,
)
from runtime_core.schemas.world_state import PersonState
from runtime_core.world.state_kernel import PersonNotFoundError, WorldStateKernel


class DuplicatePersonSafetySignalError(RuntimeError):
    """Raised when one successfully applied safety signal is replayed."""


class PersonSafetyMonitor:
    """Translate authenticated safety observations into Kernel-owned person state."""

    def __init__(self, world_state_kernel: WorldStateKernel) -> None:
        self._lock = RLock()
        self._world_state_kernel = world_state_kernel
        self._processed_keys: set[str] = set()

    def apply(self, signal: PersonSafetySignal) -> PersonSafetyUpdateResult:
        with self._lock:
            if signal.deduplication_key in self._processed_keys:
                raise DuplicatePersonSafetySignalError(signal.deduplication_key)
            before = self._world_state_kernel.get_current_state()
            person = before.people.get(signal.person_id)
            if person is None:
                raise PersonNotFoundError(signal.person_id)
            previous_version = before.world_version
            if signal.signal_type == PersonSafetySignalType.ALERT_ACKNOWLEDGED:
                status = "evacuating"
                zone = person.zone
            else:
                status = "safe"
                zone = signal.shelter_zone
            updated = PersonState(
                person_id=person.person_id,
                role=person.role,
                zone=zone,
                status=status,
                last_updated_at=signal.timestamp,
            )
            committed = self._world_state_kernel.update_person(updated)
            self._processed_keys.add(signal.deduplication_key)
            return PersonSafetyUpdateResult(
                signal_id=signal.signal_id,
                incident_id=signal.incident_id,
                person_id=signal.person_id,
                previous_status=person.status,
                current_status=committed.people[signal.person_id].status,
                current_zone=committed.people[signal.person_id].zone,
                changed=committed.world_version > previous_version,
                previous_world_version=previous_version,
                current_world_version=committed.world_version,
            )
