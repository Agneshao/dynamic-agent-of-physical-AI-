"""Runtime-owned live control service for the operator HTTP boundary."""

from __future__ import annotations

from runtime_core.adapters.isaac_simulator_adapter import IsaacSimulatorAdapter
from runtime_core.schemas.commands import Command
from runtime_core.schemas.isaac_control import (
    IsaacControlCommandRequest,
    IsaacControlCommandResponse,
)
from runtime_core.schemas.proposals import ProposalParameter


class IsaacControlNotConfiguredError(RuntimeError):
    """Raised when the UI server has no live Isaac adapter."""


class IsaacControlDisconnectedError(RuntimeError):
    """Raised when the bridge heartbeat is missing or stale."""


class IsaacControlService:
    """Validate explicit operator commands and execute them through the adapter."""

    def __init__(self, adapter: IsaacSimulatorAdapter | None) -> None:
        self._adapter = adapter

    @property
    def configured(self) -> bool:
        return self._adapter is not None

    def state(self) -> dict[str, object]:
        if self._adapter is None:
            return {
                "configured": False,
                "connected": False,
                "connection_status": "NOT_CONFIGURED",
                "entities": {},
            }
        return {"configured": True, **self._adapter.get_state()}

    def execute(
        self, request: IsaacControlCommandRequest
    ) -> IsaacControlCommandResponse:
        if self._adapter is None:
            raise IsaacControlNotConfiguredError("Isaac adapter is not configured")
        state = self._adapter.get_state()
        if not state.get("connected"):
            raise IsaacControlDisconnectedError(
                "Isaac bridge is not connected: "
                + str(state.get("connection_status", "UNKNOWN"))
            )
        parameters = ()
        if request.target_zone is not None:
            speed_mps = 8.0 if request.command_type.value == "inspect_zone" else 4.0
            parameters = (
                ProposalParameter(name="target_zone", value=request.target_zone),
                ProposalParameter(name="speed_mps", value=speed_mps),
            )
        command_incident_id = f"{request.incident_id}:{request.request_id}"
        command = Command(
            incident_id=command_incident_id,
            idempotency_key=(
                f"{command_incident_id}:{request.command_type.value}:"
                f"{request.target_id}"
            ),
            command_type=request.command_type,
            target_id=request.target_id,
            parameters=parameters,
            source=f"operator:{request.operator_id}",
            world_version=request.world_version,
            org_version=request.org_version,
        )
        receipt = self._adapter.execute_command(command)
        verification = self._adapter.verify_command(command, receipt)
        return IsaacControlCommandResponse(
            request_id=request.request_id,
            command_id=command.command_id,
            status=verification.status,
            message=verification.message,
            observed_machine=verification.observed_machine,
            observed_person=verification.observed_person,
            state=self.state(),
        )
