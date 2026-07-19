"""Minimal versioned command executor and runtime synchronization boundary."""

from __future__ import annotations

from datetime import datetime, timezone
from threading import RLock
from typing import Callable, Optional
from uuid import UUID

from runtime_core.organization.mode_manager import ModeManager
from runtime_core.ports.simulator import SimulatorAdapter
from runtime_core.schemas.commands import (
    Command,
    CommandResult,
    CommandStatus,
    VerificationResult,
)
from runtime_core.schemas.evidence import Evidence, EvidenceFact, EvidenceKind
from runtime_core.schemas.world_state import MachineState
from runtime_core.world.state_kernel import WorldStateKernel


class SimpleExecutor:
    """Execute one command and synchronize verified effects into WorldState."""

    def __init__(
        self,
        world_state_kernel: WorldStateKernel,
        mode_manager: ModeManager,
        adapter: SimulatorAdapter,
        *,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self._lock = RLock()
        self._world_state_kernel = world_state_kernel
        self._mode_manager = mode_manager
        self._adapter = adapter
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._results_by_command_id: dict[UUID, CommandResult] = {}
        self._results_by_idempotency_key: dict[str, CommandResult] = {}

    def execute(self, command: Command) -> CommandResult:
        """Run version check, idempotency, adapter verification, and sync."""
        with self._lock:
            current_world_version = self._world_state_kernel.get_world_version()
            organization = self._mode_manager.get_current_organization()
            timestamp = self._now_locked()
            if command.world_version != current_world_version:
                return self._terminal_result(
                    command,
                    CommandStatus.FAILED,
                    "STALE_WORLD_VERSION",
                    timestamp,
                )
            if command.org_version != organization.org_version:
                return self._terminal_result(
                    command,
                    CommandStatus.FAILED,
                    "STALE_ORGANIZATION_VERSION",
                    timestamp,
                )

            previous = self._results_by_idempotency_key.get(command.idempotency_key)
            if previous is not None:
                return self._copy_result(previous)
            previous = self._results_by_command_id.get(command.command_id)
            if previous is not None:
                return self._copy_result(previous)

            receipt = self._adapter.execute_command(command)
            verification = self._adapter.verify_command(command, receipt)
            evidence = tuple(self._adapter.collect_evidence(command))
            if verification.status != CommandStatus.VERIFIED:
                status = (
                    CommandStatus.FAILED
                    if verification.status == CommandStatus.FAILED
                    else CommandStatus.UNKNOWN
                )
                result = CommandResult(
                    command_id=command.command_id,
                    status=status,
                    message=verification.message,
                    evidence=evidence,
                    executed_at=receipt.executed_at,
                )
                self._remember_locked(command, result)
                return self._copy_result(result)

            try:
                changed = self._sync_verified_effect_locked(verification)
            except Exception as exc:
                sync_evidence = Evidence(
                    command_id=command.command_id,
                    kind=EvidenceKind.KERNEL_SYNC_FAILED,
                    source="simple_executor",
                    facts=(
                        EvidenceFact(name="adapter_status", value="VERIFIED"),
                        EvidenceFact(name="kernel_sync_error", value=str(exc)),
                    ),
                    observed_at=timestamp,
                )
                result = CommandResult(
                    command_id=command.command_id,
                    status=CommandStatus.UNKNOWN,
                    message=(
                        "ADAPTER_EXECUTED_KERNEL_SYNC_FAILED: "
                        f"{type(exc).__name__}: {exc}"
                    ),
                    evidence=evidence + (sync_evidence,),
                    executed_at=receipt.executed_at,
                )
                self._remember_locked(command, result)
                return self._copy_result(result)

            sync_evidence = Evidence(
                command_id=command.command_id,
                kind=EvidenceKind.KERNEL_SYNC,
                source="simple_executor",
                facts=(
                    EvidenceFact(name="runtime_state_changed", value=changed),
                    EvidenceFact(
                        name="world_version",
                        value=self._world_state_kernel.get_world_version(),
                    ),
                ),
                observed_at=timestamp,
            )
            result = CommandResult(
                command_id=command.command_id,
                status=CommandStatus.VERIFIED,
                message="adapter effect verified and synchronized",
                evidence=evidence + (sync_evidence,),
                executed_at=receipt.executed_at,
            )
            self._remember_locked(command, result)
            return self._copy_result(result)

    def _sync_verified_effect_locked(
        self, verification: VerificationResult
    ) -> bool:
        before_version = self._world_state_kernel.get_world_version()
        if verification.observed_machine is not None:
            self._world_state_kernel.update_machine(
                MachineState.model_validate(
                    verification.observed_machine.model_dump(mode="python")
                )
            )
        elif verification.new_tasks_frozen is not None:
            self._world_state_kernel.update_new_tasks_frozen(
                verification.new_tasks_frozen
            )
        return self._world_state_kernel.get_world_version() > before_version

    def _remember_locked(self, command: Command, result: CommandResult) -> None:
        self._results_by_command_id[command.command_id] = result
        self._results_by_idempotency_key[command.idempotency_key] = result

    @staticmethod
    def _terminal_result(
        command: Command,
        status: CommandStatus,
        message: str,
        timestamp: datetime,
    ) -> CommandResult:
        return CommandResult(
            command_id=command.command_id,
            status=status,
            message=message,
            executed_at=timestamp,
        )

    def _now_locked(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("SimpleExecutor clock must be timezone-aware")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _copy_result(result: CommandResult) -> CommandResult:
        return CommandResult.model_validate(result.model_dump(mode="python"))
