"""Deterministic thunderstorm safety commands with no planner dependency."""

from __future__ import annotations

from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field

from runtime_core.execution.simple_executor import SimpleExecutor
from runtime_core.organization.mode_manager import ModeManager
from runtime_core.schemas.commands import Command, CommandResult, CommandType
from runtime_core.schemas.events import EventSeverity
from runtime_core.schemas.world_state import WorldSnapshot
from runtime_core.world.state_kernel import WorldStateKernel


class FastPathResult(BaseModel):
    """Immutable command and result set produced for one incident."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    incident_id: str = Field(min_length=1)
    source_snapshot_id: UUID
    commands: tuple[Command, ...]
    command_results: tuple[CommandResult, ...]


class EmergencyFastPath:
    """Execute fixed critical-weather actions only through SimpleExecutor."""

    _ACTIONS: tuple[tuple[CommandType, str], ...] = (
        (CommandType.PAUSE_MACHINE, "mower_1"),
        (CommandType.PAUSE_MACHINE, "mower_2"),
        (CommandType.FREEZE_NEW_TASKS, "runtime"),
        (CommandType.RECALL_DRONE, "drone_1"),
    )

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
    ) -> FastPathResult:
        """Execute the fixed critical-weather response for one incident."""
        if not incident_id:
            raise ValueError("incident_id must not be empty")
        if severity != EventSeverity.CRITICAL:
            return FastPathResult(
                incident_id=incident_id,
                source_snapshot_id=snapshot.snapshot_id,
                commands=(),
                command_results=(),
            )

        commands: list[Command] = []
        results: list[CommandResult] = []
        for command_type, target_id in self._ACTIONS:
            organization = self._mode_manager.get_current_organization()
            idempotency_key = f"{incident_id}:{command_type.value}:{target_id}"
            command = Command(
                command_id=uuid5(NAMESPACE_URL, idempotency_key),
                incident_id=incident_id,
                idempotency_key=idempotency_key,
                command_type=command_type,
                target_id=target_id,
                source="emergency_fast_path",
                world_version=self._world_state_kernel.get_world_version(),
                org_version=organization.org_version,
            )
            commands.append(command)
            results.append(self._executor.execute(command))
        return FastPathResult(
            incident_id=incident_id,
            source_snapshot_id=snapshot.snapshot_id,
            commands=tuple(commands),
            command_results=tuple(results),
        )
