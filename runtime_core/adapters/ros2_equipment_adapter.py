"""SimulatorAdapter backed by an injected ROS2 command transport."""

from __future__ import annotations

from datetime import datetime, timezone
from threading import RLock
from typing import Protocol
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
from runtime_core.schemas.ros2 import Ros2CommandResponse


class Ros2CommandTransportPort(Protocol):
    """Small surface implemented by an rclpy Action/Service client."""

    def execute(
        self,
        *,
        topic: str,
        payload: dict[str, object],
        timeout_seconds: float,
    ) -> Ros2CommandResponse:
        ...


class Ros2EquipmentAdapter(SimulatorAdapter):
    """Publish Commands through ROS2 and verify returned physical observations."""

    def __init__(
        self,
        transport: Ros2CommandTransportPort,
        *,
        timeout_seconds: float = 5.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._lock = RLock()
        self._transport = transport
        self._timeout_seconds = timeout_seconds
        self._responses: dict[UUID, Ros2CommandResponse] = {}
        self._receipts: dict[UUID, ExecutionReceipt] = {}
        self._evidence: dict[UUID, list[Evidence]] = {}

    def get_state(self) -> dict[str, object]:
        with self._lock:
            return {
                str(command_id): response.model_dump(mode="json")
                for command_id, response in self._responses.items()
            }

    def execute_command(self, command: Command) -> ExecutionReceipt:
        with self._lock:
            previous = self._receipts.get(command.command_id)
            if previous is not None:
                return ExecutionReceipt.model_validate(
                    previous.model_dump(mode="python")
                )
            topic = f"/golf/commands/{command.target_id}/{command.command_type.value}"
            response = self._transport.execute(
                topic=topic,
                payload=command.model_dump(mode="json"),
                timeout_seconds=self._timeout_seconds,
            )
            self._responses[command.command_id] = response
            status = (
                CommandStatus.EXECUTING
                if response.accepted and response.acknowledged
                else CommandStatus.UNKNOWN
                if response.accepted
                else CommandStatus.FAILED
            )
            receipt = ExecutionReceipt(
                command_id=command.command_id,
                status=status,
                message=response.message,
                observed_machine=response.observed_machine,
                observed_person=response.observed_person,
                new_tasks_frozen=response.new_tasks_frozen,
                executed_at=response.observed_at,
            )
            self._receipts[command.command_id] = receipt
            self._append_evidence(
                command,
                EvidenceKind.ADAPTER_EXECUTION,
                "ros2_equipment_adapter",
                response.observed_at,
                (
                    EvidenceFact(name="topic", value=topic),
                    EvidenceFact(name="accepted", value=response.accepted),
                    EvidenceFact(name="acknowledged", value=response.acknowledged),
                ),
            )
            return ExecutionReceipt.model_validate(receipt.model_dump(mode="python"))

    def verify_command(
        self,
        command: Command,
        receipt: ExecutionReceipt,
    ) -> VerificationResult:
        with self._lock:
            response = self._responses.get(command.command_id)
            if response is None:
                return VerificationResult(
                    command_id=command.command_id,
                    status=CommandStatus.UNKNOWN,
                    message="ROS2 response unavailable",
                )
            verified = receipt.status == CommandStatus.EXECUTING and _matches_expected(
                command, response
            )
            status = (
                CommandStatus.VERIFIED
                if verified
                else CommandStatus.FAILED
                if receipt.status == CommandStatus.FAILED
                else CommandStatus.UNKNOWN
            )
            message = (
                "ROS2 observation matches expected command effect"
                if verified
                else "ROS2 command effect could not be verified"
            )
            result = VerificationResult(
                command_id=command.command_id,
                status=status,
                message=message,
                observed_machine=response.observed_machine,
                observed_person=response.observed_person,
                new_tasks_frozen=response.new_tasks_frozen,
                verified_at=response.observed_at,
            )
            self._append_evidence(
                command,
                EvidenceKind.ADAPTER_VERIFICATION,
                "ros2_equipment_adapter",
                response.observed_at,
                (
                    EvidenceFact(name="status", value=status.value),
                    EvidenceFact(name="message", value=message),
                ),
            )
            return VerificationResult.model_validate(result.model_dump(mode="python"))

    def collect_evidence(self, command: Command) -> list[Evidence]:
        with self._lock:
            return [
                Evidence.model_validate(item.model_dump(mode="python"))
                for item in self._evidence.get(command.command_id, ())
            ]

    def _append_evidence(
        self,
        command: Command,
        kind: EvidenceKind,
        source: str,
        observed_at: datetime,
        facts: tuple[EvidenceFact, ...],
    ) -> None:
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            observed_at = datetime.now(timezone.utc)
        self._evidence.setdefault(command.command_id, []).append(
            Evidence(
                command_id=command.command_id,
                kind=kind,
                source=source,
                facts=facts,
                observed_at=observed_at,
            )
        )


def _matches_expected(command: Command, response: Ros2CommandResponse) -> bool:
    machine = response.observed_machine
    person = response.observed_person
    if command.command_type == CommandType.FREEZE_NEW_TASKS:
        return response.new_tasks_frozen is True
    if command.command_type == CommandType.NOTIFY_OPERATOR:
        return response.accepted and response.acknowledged
    if command.command_type == CommandType.ALERT_PERSON:
        return person is not None and person.status == "alerted"
    if machine is None:
        return False
    if command.command_type == CommandType.PAUSE_MACHINE:
        return machine.status == "paused"
    if command.command_type == CommandType.HOLD_POSITION:
        return machine.status == "holding"
    if command.command_type in (CommandType.RETURN_TO_BASE, CommandType.RECALL_DRONE):
        return machine.status == "idle" and machine.zone == "maintenance_base"
    if command.command_type == CommandType.TRACK_PERSON:
        return machine.machine_type == "drone" and machine.status == "tracking_person"
    return False
