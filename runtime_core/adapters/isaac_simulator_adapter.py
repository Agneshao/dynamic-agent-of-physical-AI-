"""SimulatorAdapter for an Isaac process on the same DGX host."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Callable, Optional
from uuid import NAMESPACE_URL, UUID, uuid5

from runtime_core.ports.simulator import SimulatorAdapter
from runtime_core.schemas.commands import (
    Command,
    CommandStatus,
    CommandType,
    ExecutionReceipt,
    VerificationResult,
)
from runtime_core.schemas.evidence import Evidence, EvidenceFact, EvidenceKind
from runtime_core.schemas.isaac import (
    IsaacBridgeResultStatus,
    IsaacCommandRequest,
    IsaacCommandResult,
    IsaacEntityObservation,
)
from runtime_core.schemas.world_state import FrozenMachineState, FrozenPersonState

from .isaac_file_protocol import IsaacFileProtocol, IsaacFileProtocolError


CANONICAL_TO_ISAAC_ID: dict[str, str] = {
    "mower_1": "mower_01",
    "mower_2": "mower_02",
    "drone_1": "drone_01",
    "player_1": "player_01",
    "maintenance_1": "maintenance_01",
    "runtime": "runtime",
    "operator": "operator",
}
ISAAC_TO_CANONICAL_ID = {
    value: key for key, value in CANONICAL_TO_ISAAC_ID.items()
}
ISAAC_TO_CANONICAL_ID.update(
    {
        "Mower_01": "mower_1",
        "Mower_02": "mower_2",
        "Drone_01": "drone_1",
        "Player_01": "player_1",
        "Maintenance_01": "maintenance_1",
    }
)

_MACHINE_TYPES = {
    "mower_1": "mower",
    "mower_2": "mower",
    "drone_1": "drone",
}
_BATTERY_DEFAULTS = {"mower_1": 82.0, "mower_2": 76.0, "drone_1": 68.0}


class IsaacAdapterConfigurationError(ValueError):
    """Raised when a canonical Runtime ID has no explicit Isaac mapping."""


class IsaacSimulatorAdapter(SimulatorAdapter):
    """Dispatch versioned commands through the local append-only bridge."""

    def __init__(
        self,
        bridge_directory: Path | str,
        *,
        timeout_seconds: float = 10.0,
        poll_interval_seconds: float = 0.05,
        heartbeat_timeout_seconds: float = 3.0,
        clock: Optional[Callable[[], datetime]] = None,
        protocol: Optional[IsaacFileProtocol] = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        if heartbeat_timeout_seconds <= 0:
            raise ValueError("heartbeat_timeout_seconds must be positive")
        self._lock = RLock()
        self._protocol = protocol or IsaacFileProtocol(bridge_directory)
        self._timeout_seconds = timeout_seconds
        self._poll_interval_seconds = poll_interval_seconds
        self._heartbeat_timeout_seconds = heartbeat_timeout_seconds
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._results: dict[UUID, IsaacCommandResult] = {}
        self._receipts: dict[UUID, ExecutionReceipt] = {}
        self._evidence: dict[UUID, list[Evidence]] = {}

    @property
    def bridge_directory(self) -> Path:
        return self._protocol.paths.root

    def get_state(self) -> dict[str, object]:
        now = self._now()
        try:
            state = self._protocol.read_state()
        except IsaacFileProtocolError as exc:
            return {
                "connected": False,
                "connection_status": "INVALID_STATE",
                "error": str(exc),
                "bridge_directory": str(self.bridge_directory),
            }
        if state is None:
            return {
                "connected": False,
                "connection_status": "DISCONNECTED",
                "bridge_directory": str(self.bridge_directory),
                "entities": {},
            }
        heartbeat_age = max(0.0, (now - state.heartbeat_at).total_seconds())
        connected = state.isaac_running and heartbeat_age <= self._heartbeat_timeout_seconds
        entities = {}
        for observation in state.entities:
            canonical_id = ISAAC_TO_CANONICAL_ID.get(
                observation.isaac_entity_id, observation.isaac_entity_id
            )
            entities[canonical_id] = {
                **observation.model_dump(mode="json"),
                "canonical_id": canonical_id,
                "zone": _normalize_zone(observation.zone),
            }
        return {
            "connected": connected,
            "connection_status": "CONNECTED" if connected else "STALE_HEARTBEAT",
            "heartbeat_age_seconds": heartbeat_age,
            "bridge_directory": str(self.bridge_directory),
            "scenario_state": state.scenario_state,
            "organization_mode": state.organization_mode,
            "observed_plan_version": state.observed_plan_version,
            "pipeline_gate": state.pipeline_gate,
            "new_tasks_frozen": state.new_tasks_frozen,
            "entities": entities,
        }

    def execute_command(self, command: Command) -> ExecutionReceipt:
        with self._lock:
            previous = self._receipts.get(command.command_id)
            if previous is not None:
                return _copy_receipt(previous)
            timestamp = self._now()
            try:
                isaac_target_id = CANONICAL_TO_ISAAC_ID[command.target_id]
            except KeyError as exc:
                return self._failed_receipt(
                    command,
                    timestamp,
                    f"UNMAPPED_CANONICAL_TARGET: {command.target_id}",
                )
            action_id = uuid5(
                NAMESPACE_URL, f"golf-runtime-isaac:{command.idempotency_key}"
            )
            request = IsaacCommandRequest(
                action_id=action_id,
                command_id=command.command_id,
                idempotency_key=command.idempotency_key,
                command_type=command.command_type,
                canonical_target_id=command.target_id,
                isaac_target_id=isaac_target_id,
                base_world_version=command.world_version,
                base_org_version=command.org_version,
                issued_at=command.created_at,
                parameters={item.name: item.value for item in command.parameters},
            )
            try:
                result = self._protocol.latest_terminal_result(action_id)
                if result is None:
                    existing_ids = {item.action_id for item in self._protocol.list_requests()}
                    if action_id not in existing_ids:
                        self._protocol.append_request(request)
                    result = self._protocol.wait_for_terminal_result(
                        action_id,
                        timeout_seconds=self._timeout_seconds,
                        poll_interval_seconds=self._poll_interval_seconds,
                    )
            except (IsaacFileProtocolError, OSError, ValueError) as exc:
                return self._failed_receipt(
                    command,
                    timestamp,
                    f"ISAAC_BRIDGE_PROTOCOL_ERROR: {type(exc).__name__}: {exc}",
                )
            if result is None:
                receipt = ExecutionReceipt(
                    command_id=command.command_id,
                    status=CommandStatus.UNKNOWN,
                    message="ISAAC_BRIDGE_TIMEOUT",
                    executed_at=timestamp,
                )
                self._remember(command, receipt, None, isaac_target_id)
                return _copy_receipt(receipt)
            if result.command_id != command.command_id:
                return self._failed_receipt(
                    command,
                    timestamp,
                    "ISAAC_BRIDGE_COMMAND_ID_MISMATCH",
                )
            self._results[command.command_id] = result
            observed_machine, observed_person = _normalized_observation(command, result)
            status = (
                CommandStatus.EXECUTING
                if result.status == IsaacBridgeResultStatus.SUCCEEDED
                else CommandStatus.FAILED
            )
            receipt = ExecutionReceipt(
                command_id=command.command_id,
                status=status,
                message=result.message,
                observed_machine=observed_machine,
                observed_person=observed_person,
                new_tasks_frozen=result.new_tasks_frozen,
                executed_at=result.observed_at,
            )
            self._remember(command, receipt, result, isaac_target_id)
            return _copy_receipt(receipt)

    def verify_command(
        self, command: Command, receipt: ExecutionReceipt
    ) -> VerificationResult:
        with self._lock:
            result = self._results.get(command.command_id)
            if receipt.status == CommandStatus.UNKNOWN:
                status = CommandStatus.UNKNOWN
                message = receipt.message
            elif receipt.status == CommandStatus.FAILED or result is None:
                status = CommandStatus.FAILED
                message = receipt.message
            elif _matches_expected(command, receipt):
                status = CommandStatus.VERIFIED
                message = "Isaac observation matches expected command effect"
            else:
                status = CommandStatus.UNKNOWN
                message = "Isaac terminal result did not contain the expected effect"
            verification = VerificationResult(
                command_id=command.command_id,
                status=status,
                message=message,
                observed_machine=receipt.observed_machine,
                observed_person=receipt.observed_person,
                new_tasks_frozen=receipt.new_tasks_frozen,
                verified_at=(result.observed_at if result is not None else self._now()),
            )
            self._evidence.setdefault(command.command_id, []).append(
                Evidence(
                    command_id=command.command_id,
                    kind=EvidenceKind.ADAPTER_VERIFICATION,
                    source="isaac_simulator_adapter",
                    facts=(
                        EvidenceFact(name="status", value=status.value),
                        EvidenceFact(name="message", value=message),
                    ),
                    observed_at=verification.verified_at,
                )
            )
            return VerificationResult.model_validate(
                verification.model_dump(mode="python")
            )

    def collect_evidence(self, command: Command) -> list[Evidence]:
        with self._lock:
            return [
                Evidence.model_validate(item.model_dump(mode="python"))
                for item in self._evidence.get(command.command_id, ())
            ]

    def _failed_receipt(
        self, command: Command, timestamp: datetime, message: str
    ) -> ExecutionReceipt:
        receipt = ExecutionReceipt(
            command_id=command.command_id,
            status=CommandStatus.FAILED,
            message=message,
            executed_at=timestamp,
        )
        self._remember(command, receipt, None, CANONICAL_TO_ISAAC_ID.get(command.target_id))
        return _copy_receipt(receipt)

    def _remember(
        self,
        command: Command,
        receipt: ExecutionReceipt,
        result: Optional[IsaacCommandResult],
        isaac_target_id: Optional[str],
    ) -> None:
        self._receipts[command.command_id] = receipt
        facts = [
            EvidenceFact(name="status", value=receipt.status.value),
            EvidenceFact(name="message", value=receipt.message),
        ]
        if isaac_target_id is not None:
            facts.append(EvidenceFact(name="isaac_target_id", value=isaac_target_id))
        if result is not None:
            facts.append(EvidenceFact(name="bridge_status", value=result.status.value))
            if result.observation is not None and result.observation.position is not None:
                facts.append(
                    EvidenceFact(name="position", value=result.observation.position)
                )
        self._evidence.setdefault(command.command_id, []).append(
            Evidence(
                command_id=command.command_id,
                kind=EvidenceKind.ADAPTER_EXECUTION,
                source="isaac_simulator_adapter",
                facts=tuple(facts),
                observed_at=receipt.executed_at,
            )
        )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("IsaacSimulatorAdapter clock must be timezone-aware")
        return value.astimezone(timezone.utc)


def _normalized_observation(
    command: Command, result: IsaacCommandResult
) -> tuple[Optional[FrozenMachineState], Optional[FrozenPersonState]]:
    observation = result.observation
    if observation is None:
        return None, None
    timestamp = observation.observed_at
    canonical_id = command.target_id
    zone = _normalize_zone(observation.zone)
    if command.command_type in (CommandType.RETURN_TO_BASE, CommandType.RECALL_DRONE):
        zone = "maintenance_base"
    if canonical_id in _MACHINE_TYPES:
        return (
            FrozenMachineState(
                machine_id=canonical_id,
                machine_type=_MACHINE_TYPES[canonical_id],
                zone=zone,
                status=_expected_machine_status(command.command_type),
                battery_percent=(
                    observation.battery_percent
                    if observation.battery_percent is not None
                    else _BATTERY_DEFAULTS[canonical_id]
                ),
                last_updated_at=timestamp,
            ),
            None,
        )
    if canonical_id == "player_1":
        return (
            None,
            FrozenPersonState(
                person_id=canonical_id,
                role="player",
                zone=zone,
                status="alerted",
                last_updated_at=timestamp,
            ),
        )
    return None, None


def _expected_machine_status(command_type: CommandType) -> str:
    return {
        CommandType.PAUSE_MACHINE: "paused",
        CommandType.HOLD_POSITION: "holding",
        CommandType.RETURN_TO_BASE: "idle",
        CommandType.MOVE_TO_ZONE: "mowing",
        CommandType.RECALL_DRONE: "idle",
        CommandType.TRACK_PERSON: "tracking_person",
    }.get(command_type, "unknown")


def _matches_expected(command: Command, receipt: ExecutionReceipt) -> bool:
    if command.command_type == CommandType.FREEZE_NEW_TASKS:
        return receipt.new_tasks_frozen is True
    if command.command_type == CommandType.NOTIFY_OPERATOR:
        return receipt.status == CommandStatus.EXECUTING
    if command.command_type == CommandType.ALERT_PERSON:
        return receipt.observed_person is not None and receipt.observed_person.status == "alerted"
    machine = receipt.observed_machine
    if machine is None:
        return False
    return machine.status == _expected_machine_status(command.command_type)


def _normalize_zone(zone: Optional[str]) -> Optional[str]:
    if zone is None:
        return None
    normalized = str(zone).strip()
    if normalized.upper().startswith("ZONE_") and len(normalized) == 6:
        return "zone_" + normalized[-1].upper()
    return {
        "MOWER_BAY_01": "maintenance_base",
        "MOWER_BAY_02": "maintenance_base",
        "DRONE_PAD": "maintenance_base",
        "MAINTENANCE_WORKSHOP": "maintenance_base",
        "OPERATIONS_WAITING_POINT": "zone_D",
    }.get(normalized.upper(), normalized)


def _copy_receipt(receipt: ExecutionReceipt) -> ExecutionReceipt:
    return ExecutionReceipt.model_validate(receipt.model_dump(mode="python"))
