"""Deterministic in-memory implementation of the existing simulator port."""

from __future__ import annotations

from datetime import datetime, timezone
from threading import RLock
from typing import Callable, Optional
from uuid import UUID

from runtime_core.ports.simulator import SimulatorAdapter
from runtime_core.schemas.commands import (
    Command,
    CommandStatus,
    CommandType,
    ExecutionReceipt,
    VerificationResult,
)
from runtime_core.schemas.evidence import Evidence, EvidenceFact, EvidenceKind
from runtime_core.schemas.world_state import FrozenMachineState


class MockSimulatorAdapter(SimulatorAdapter):
    """Model external device state without owning authoritative runtime state."""

    def __init__(
        self,
        *,
        fail_command_types: tuple[CommandType, ...] = (),
        no_response_command_types: tuple[CommandType, ...] = (),
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self._lock = RLock()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        timestamp = self._now_locked()
        self._machines: dict[str, FrozenMachineState] = {
            "mower_1": FrozenMachineState(
                machine_id="mower_1",
                machine_type="mower",
                zone="zone_B",
                status="mowing",
                battery_percent=82.0,
                last_updated_at=timestamp,
            ),
            "mower_2": FrozenMachineState(
                machine_id="mower_2",
                machine_type="mower",
                zone="zone_D",
                status="mowing",
                battery_percent=76.0,
                last_updated_at=timestamp,
            ),
            "drone_1": FrozenMachineState(
                machine_id="drone_1",
                machine_type="drone",
                zone="zone_C",
                status="patrolling",
                battery_percent=68.0,
                last_updated_at=timestamp,
            ),
        }
        self._locations: dict[str, dict[str, object]] = {
            "zone_A": {"available": True, "occupied_by_people": ()},
            "zone_B": {"available": True, "occupied_by_people": ("player_1",)},
            "zone_C": {"available": True, "occupied_by_people": ()},
            "zone_D": {"available": True, "occupied_by_people": ()},
            "maintenance_base": {"available": True, "occupied_by_people": ()},
        }
        self._new_tasks_frozen = False
        self._notifications: list[str] = []
        self._fail_command_types = frozenset(fail_command_types)
        self._no_response_command_types = frozenset(no_response_command_types)
        self._receipts: dict[UUID, ExecutionReceipt] = {}
        self._evidence: dict[UUID, list[Evidence]] = {}
        self._execution_counts: dict[str, int] = {}

    def get_state(self) -> dict[str, object]:
        """Return a detached snapshot of the external simulated state."""
        with self._lock:
            return {
                "machines": {
                    machine_id: machine.model_dump(mode="json")
                    for machine_id, machine in self._machines.items()
                },
                "locations": {
                    location_id: {
                        "available": details["available"],
                        "occupied_by_people": tuple(details["occupied_by_people"]),
                    }
                    for location_id, details in self._locations.items()
                },
                "new_tasks_frozen": self._new_tasks_frozen,
                "notifications": tuple(self._notifications),
            }

    def execute_command(self, command: Command) -> ExecutionReceipt:
        """Apply one command to external state and return an acknowledgement."""
        with self._lock:
            previous = self._receipts.get(command.command_id)
            if previous is not None:
                return self._copy_receipt(previous)

            timestamp = self._now_locked()
            if command.command_type in self._fail_command_types:
                receipt = ExecutionReceipt(
                    command_id=command.command_id,
                    status=CommandStatus.FAILED,
                    message="mock adapter configured failure",
                    executed_at=timestamp,
                )
                self._record_execution_locked(command, receipt, executed=False)
                return self._copy_receipt(receipt)

            try:
                observed_machine, frozen = self._apply_command_locked(command, timestamp)
            except ValueError as exc:
                receipt = ExecutionReceipt(
                    command_id=command.command_id,
                    status=CommandStatus.FAILED,
                    message=str(exc),
                    executed_at=timestamp,
                )
                self._record_execution_locked(command, receipt, executed=False)
                return self._copy_receipt(receipt)

            no_response = command.command_type in self._no_response_command_types
            receipt = ExecutionReceipt(
                command_id=command.command_id,
                status=(CommandStatus.UNKNOWN if no_response else CommandStatus.EXECUTING),
                message=(
                    "mock adapter executed command without acknowledgement"
                    if no_response
                    else "mock adapter executed command"
                ),
                observed_machine=observed_machine,
                new_tasks_frozen=frozen,
                executed_at=timestamp,
            )
            self._record_execution_locked(command, receipt, executed=True)
            return self._copy_receipt(receipt)

    def verify_command(
        self,
        command: Command,
        receipt: ExecutionReceipt,
    ) -> VerificationResult:
        """Verify the current external state against the command effect."""
        with self._lock:
            timestamp = self._now_locked()
            if receipt.status == CommandStatus.UNKNOWN:
                result = VerificationResult(
                    command_id=command.command_id,
                    status=CommandStatus.UNKNOWN,
                    message="adapter acknowledgement unavailable",
                    observed_machine=receipt.observed_machine,
                    new_tasks_frozen=receipt.new_tasks_frozen,
                    verified_at=timestamp,
                )
            elif receipt.status == CommandStatus.FAILED:
                result = VerificationResult(
                    command_id=command.command_id,
                    status=CommandStatus.FAILED,
                    message=receipt.message,
                    verified_at=timestamp,
                )
            else:
                observed_machine, frozen = self._observed_effect_locked(command)
                result = VerificationResult(
                    command_id=command.command_id,
                    status=CommandStatus.VERIFIED,
                    message="mock adapter state verified",
                    observed_machine=observed_machine,
                    new_tasks_frozen=frozen,
                    verified_at=timestamp,
                )
            self._evidence.setdefault(command.command_id, []).append(
                Evidence(
                    command_id=command.command_id,
                    kind=EvidenceKind.ADAPTER_VERIFICATION,
                    source="mock_simulator_adapter",
                    facts=(
                        EvidenceFact(name="status", value=result.status.value),
                        EvidenceFact(name="message", value=result.message),
                    ),
                    observed_at=timestamp,
                )
            )
            return VerificationResult.model_validate(result.model_dump(mode="python"))

    def collect_evidence(self, command: Command) -> list[Evidence]:
        """Return detached evidence copies for one command."""
        with self._lock:
            return [
                Evidence.model_validate(item.model_dump(mode="python"))
                for item in self._evidence.get(command.command_id, ())
            ]

    def get_execution_count(self, idempotency_key: str) -> int:
        """Return how often external execution was attempted for a logical key."""
        with self._lock:
            return self._execution_counts.get(idempotency_key, 0)

    def _apply_command_locked(
        self, command: Command, timestamp: datetime
    ) -> tuple[Optional[FrozenMachineState], Optional[bool]]:
        if command.command_type == CommandType.FREEZE_NEW_TASKS:
            if command.target_id != "runtime":
                raise ValueError("freeze_new_tasks target must be runtime")
            self._new_tasks_frozen = True
            return None, True
        if command.command_type == CommandType.NOTIFY_OPERATOR:
            parameter = command.get_parameter("message")
            message = str(parameter.value) if parameter else "operator notification"
            self._notifications.append(message)
            return None, None

        machine = self._machines.get(command.target_id)
        if machine is None:
            raise ValueError(f"unknown machine: {command.target_id}")
        if command.command_type == CommandType.RECALL_DRONE and machine.machine_type != "drone":
            raise ValueError("recall_drone requires a drone target")

        status = machine.status
        zone = machine.zone
        if command.command_type == CommandType.PAUSE_MACHINE:
            status = "paused"
        elif command.command_type == CommandType.HOLD_POSITION:
            status = "holding"
        elif command.command_type in (
            CommandType.RETURN_TO_BASE,
            CommandType.RECALL_DRONE,
        ):
            status = "idle"
            zone = "maintenance_base"
        else:
            raise ValueError(f"unsupported command type: {command.command_type.value}")

        updated = FrozenMachineState(
            machine_id=machine.machine_id,
            machine_type=machine.machine_type,
            zone=zone,
            status=status,
            battery_percent=machine.battery_percent,
            last_updated_at=(
                machine.last_updated_at
                if status == machine.status and zone == machine.zone
                else timestamp
            ),
        )
        self._machines[command.target_id] = updated
        return updated, None

    def _observed_effect_locked(
        self, command: Command
    ) -> tuple[Optional[FrozenMachineState], Optional[bool]]:
        if command.command_type == CommandType.FREEZE_NEW_TASKS:
            return None, self._new_tasks_frozen
        if command.command_type == CommandType.NOTIFY_OPERATOR:
            return None, None
        machine = self._machines.get(command.target_id)
        if machine is None:
            raise ValueError(f"unknown machine: {command.target_id}")
        return machine, None

    def _record_execution_locked(
        self,
        command: Command,
        receipt: ExecutionReceipt,
        *,
        executed: bool,
    ) -> None:
        self._receipts[command.command_id] = receipt
        self._execution_counts[command.idempotency_key] = (
            self._execution_counts.get(command.idempotency_key, 0) + 1
        )
        self._evidence.setdefault(command.command_id, []).append(
            Evidence(
                command_id=command.command_id,
                kind=EvidenceKind.ADAPTER_EXECUTION,
                source="mock_simulator_adapter",
                facts=(
                    EvidenceFact(name="executed", value=executed),
                    EvidenceFact(name="status", value=receipt.status.value),
                    EvidenceFact(name="message", value=receipt.message),
                ),
                observed_at=receipt.executed_at,
            )
        )

    def _now_locked(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("MockSimulatorAdapter clock must be timezone-aware")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _copy_receipt(receipt: ExecutionReceipt) -> ExecutionReceipt:
        return ExecutionReceipt.model_validate(receipt.model_dump(mode="python"))
