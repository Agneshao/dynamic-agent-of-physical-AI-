"""Pre-authorized person alert and drone tracking for critical incidents."""

from __future__ import annotations

from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field

from runtime_core.execution.simple_executor import SimpleExecutor
from runtime_core.organization.mode_manager import ModeManager
from runtime_core.schemas.commands import Command, CommandResult, CommandType
from runtime_core.schemas.events import EventSeverity
from runtime_core.schemas.proposals import ProposalParameter
from runtime_core.schemas.world_state import WorldSnapshot
from runtime_core.world.state_kernel import WorldStateKernel


class HumanSafetyFastPathResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    incident_id: str = Field(min_length=1)
    source_snapshot_id: UUID
    exposed_people: tuple[str, ...]
    commands: tuple[Command, ...]
    command_results: tuple[CommandResult, ...]


class HumanSafetyFastPath:
    """Alert exposed people and retain a drone for monitoring before planning."""

    def __init__(
        self,
        executor: SimpleExecutor,
        world_state_kernel: WorldStateKernel,
        mode_manager: ModeManager,
    ) -> None:
        self._executor = executor
        self._world_state_kernel = world_state_kernel
        self._mode_manager = mode_manager

    def execute(
        self,
        snapshot: WorldSnapshot,
        *,
        incident_id: str,
        severity: EventSeverity = EventSeverity.CRITICAL,
        shelter_zone: str = "clubhouse",
    ) -> HumanSafetyFastPathResult:
        if not incident_id:
            raise ValueError("incident_id must not be empty")
        if not shelter_zone:
            raise ValueError("shelter_zone must not be empty")
        exposed_people = tuple(
            person.person_id
            for person in snapshot.state.people
            if person.zone is not None
            and person.status not in ("safe", "sheltered")
        )
        if severity != EventSeverity.CRITICAL or not exposed_people:
            return HumanSafetyFastPathResult(
                incident_id=incident_id,
                source_snapshot_id=snapshot.snapshot_id,
                exposed_people=exposed_people,
                commands=(),
                command_results=(),
            )

        actions: list[tuple[CommandType, str, tuple[ProposalParameter, ...]]] = []
        for person_id in exposed_people:
            actions.append(
                (
                    CommandType.ALERT_PERSON,
                    person_id,
                    (
                        ProposalParameter(name="shelter_zone", value=shelter_zone),
                        ProposalParameter(
                            name="message",
                            value="Critical weather: move to shelter immediately.",
                        ),
                    ),
                )
            )
        drone = next(
            (
                machine
                for machine in snapshot.state.machines
                if machine.machine_type == "drone"
            ),
            None,
        )
        if drone is not None:
            actions.append(
                (
                    CommandType.TRACK_PERSON,
                    drone.machine_id,
                    (
                        ProposalParameter(name="person_id", value=exposed_people[0]),
                        ProposalParameter(name="until", value="shelter_arrival_verified"),
                    ),
                )
            )

        commands: list[Command] = []
        results: list[CommandResult] = []
        for command_type, target_id, parameters in actions:
            organization = self._mode_manager.get_current_organization()
            idempotency_key = f"{incident_id}:{command_type.value}:{target_id}"
            command = Command(
                command_id=uuid5(NAMESPACE_URL, idempotency_key),
                incident_id=incident_id,
                idempotency_key=idempotency_key,
                command_type=command_type,
                target_id=target_id,
                parameters=parameters,
                source="human_safety_fast_path",
                world_version=self._world_state_kernel.get_world_version(),
                org_version=organization.org_version,
            )
            commands.append(command)
            results.append(self._executor.execute(command))
        return HumanSafetyFastPathResult(
            incident_id=incident_id,
            source_snapshot_id=snapshot.snapshot_id,
            exposed_people=exposed_people,
            commands=tuple(commands),
            command_results=tuple(results),
        )
