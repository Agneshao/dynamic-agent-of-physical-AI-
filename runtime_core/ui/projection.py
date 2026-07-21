"""Detached UI projection over immutable runtime results."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

from runtime_core.demo.thunderstorm_demo import ThunderstormDemoResult
from runtime_core.schemas.agent_outputs import AgentInteractionRecord
from runtime_core.schemas.commands import Command, CommandResult
from runtime_core.schemas.world_state import FrozenMachineState


class ObservabilityLayer(str, Enum):
    ORGANIZATION = "ORGANIZATION"
    AGENT = "AGENT"
    EXECUTION = "EXECUTION"
    STATE = "STATE"


UiScalar = Union[str, int, float, bool, None]
UiValue = Union[UiScalar, tuple[UiScalar, ...]]


class UiFact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    value: UiValue


class ObservabilityEvent(BaseModel):
    """One event placed into exactly one architectural layer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: int = Field(ge=1)
    layer: ObservabilityLayer
    kind: str = Field(min_length=1)
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    status: str = Field(min_length=1)
    world_version: int = Field(ge=0)
    org_version: int = Field(ge=1)
    sender: Optional[str] = None
    recipient: Optional[str] = None
    facts: tuple[UiFact, ...] = ()
    timestamp: datetime

    @field_validator("timestamp")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value.astimezone(timezone.utc)


class MachineChange(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    machine_id: str
    machine_type: str
    initial_status: str
    final_status: str
    initial_zone: Optional[str]
    final_zone: Optional[str]
    battery_percent: float
    changed: bool


class ObservabilityView(BaseModel):
    """JSON-safe, immutable UI input with no references to runtime writers."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    incident_id: str
    generated_at: datetime
    layers: tuple[ObservabilityLayer, ...]
    initial_mode: str
    final_mode: str
    initial_world_version: int
    final_world_version: int
    initial_org_version: int
    final_org_version: int
    active_roles: tuple[str, ...]
    suspended_roles: tuple[str, ...]
    events: tuple[ObservabilityEvent, ...]
    interactions: tuple[AgentInteractionRecord, ...]
    machine_changes: tuple[MachineChange, ...]
    final_weather: tuple[UiFact, ...]
    new_tasks_frozen: bool
    audit_record_count: int

    @field_validator("generated_at")
    @classmethod
    def require_aware_generated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")
        return value.astimezone(timezone.utc)


def build_observability_view(result: ThunderstormDemoResult) -> ObservabilityView:
    """Project a completed scenario without retaining mutable service objects."""
    incident_id = result.organization_plan.incident_id
    events: list[ObservabilityEvent] = []
    sequence = 1

    events.append(
        ObservabilityEvent(
            sequence=sequence,
            layer=ObservabilityLayer.STATE,
            kind="WEATHER_CHANGE",
            title="Thunderstorm detected",
            summary="Weather telemetry crossed the critical safety threshold.",
            status="CRITICAL",
            world_version=result.initial_world_version + 1,
            org_version=result.initial_org_version,
            sender="weather_source",
            recipient="world_state_kernel",
            facts=(
                UiFact(name="condition", value="thunderstorm"),
                UiFact(name="lightning_distance_km", value=2.5),
                UiFact(name="wind_speed_mps", value=18.0),
            ),
            timestamp=result.final_world_state.weather.updated_at,
        )
    )
    sequence += 1
    for command, command_result in zip(
        result.fast_path_commands, result.fast_path_results
    ):
        events.append(
            _command_event(
                sequence=sequence,
                command=command,
                command_result=command_result,
                title="Emergency fast path",
                sender="emergency_fast_path",
            )
        )
        sequence += 1
    for command, command_result in zip(
        result.human_safety_commands, result.human_safety_results
    ):
        events.append(
            _command_event(
                sequence=sequence,
                command=command,
                command_result=command_result,
                title="Human safety fast path",
                sender="human_safety_fast_path",
            )
        )
        sequence += 1

    events.append(
        ObservabilityEvent(
            sequence=sequence,
            layer=ObservabilityLayer.ORGANIZATION,
            kind="ORGANIZATION_PLAN",
            title="Minimum organization selected",
            summary=result.organization_plan.reason,
            status="RECOMMENDED",
            world_version=result.stale_submission_world_version,
            org_version=result.initial_org_version,
            sender="minimal_organization_selector",
            recipient="mode_manager",
            facts=(
                UiFact(
                    name="required_capabilities",
                    value=result.organization_plan.required_capabilities,
                ),
                UiFact(
                    name="selected_roles",
                    value=result.organization_plan.selected_roles,
                ),
            ),
            timestamp=result.final_organization.activated_at,
        )
    )
    sequence += 1
    events.append(
        ObservabilityEvent(
            sequence=sequence,
            layer=ObservabilityLayer.ORGANIZATION,
            kind="MODE_TRANSITION",
            title="Emergency organization activated",
            summary=(
                f"{result.initial_mode.value} changed to {result.final_mode.value}; "
                "ModeManager published the audited organization state."
            ),
            status="APPLIED",
            world_version=result.stale_submission_world_version,
            org_version=result.final_org_version,
            sender="mode_manager",
            recipient="organization_state",
            facts=(
                UiFact(name="active_roles", value=result.final_organization.active_roles),
                UiFact(
                    name="suspended_role_count",
                    value=len(result.final_organization.suspended_roles),
                ),
            ),
            timestamp=result.final_organization.activated_at,
        )
    )
    sequence += 1
    events.append(
        ObservabilityEvent(
            sequence=sequence,
            layer=ObservabilityLayer.EXECUTION,
            kind="PROPOSAL_SUBMISSION",
            title="Old proposal submitted",
            summary="The NORMAL organization proposal entered the version gate.",
            status="SUBMITTED",
            world_version=result.stale_submission_world_version,
            org_version=result.final_org_version,
            sender="normal_operations_stub",
            recipient="proposal_board",
            facts=(
                UiFact(name="proposal_world_version", value=result.normal_proposal.world_version),
                UiFact(name="proposal_org_version", value=result.normal_proposal.org_version),
                UiFact(name="current_world_version", value=result.stale_submission_world_version),
                UiFact(name="current_org_version", value=result.final_org_version),
            ),
            timestamp=result.stale_proposal_result.timestamp,
        )
    )
    sequence += 1
    events.append(
        ObservabilityEvent(
            sequence=sequence,
            layer=ObservabilityLayer.EXECUTION,
            kind="STALE_PROPOSAL_REJECTED",
            title="Old proposal rejected",
            summary=result.stale_proposal_result.message,
            status=result.stale_proposal_result.status.value,
            world_version=result.stale_proposal_result.checked_world_version,
            org_version=result.stale_proposal_result.checked_org_version,
            sender="proposal_board",
            recipient="normal_operations_stub",
            facts=(
                UiFact(
                    name="rejection_code",
                    value=result.stale_proposal_result.rejection_code.value,
                ),
            ),
            timestamp=result.stale_proposal_result.timestamp,
        )
    )
    sequence += 1

    interactions = (
        result.emergency_team_result.interactions
        if result.emergency_team_result is not None
        else ()
    )
    for interaction in interactions:
        events.append(
            ObservabilityEvent(
                sequence=sequence,
                layer=ObservabilityLayer.AGENT,
                kind=interaction.message_type.value,
                title=interaction.message_type.value.replace("_", " ").title(),
                summary=interaction.output_summary or interaction.objective,
                status="DELIVERED",
                world_version=interaction.world_version,
                org_version=interaction.org_version,
                sender=interaction.sender_role,
                recipient=interaction.recipient_role,
                facts=tuple(
                    UiFact(name=item.name, value=item.value)
                    for item in interaction.payload
                ),
                timestamp=interaction.created_at,
            )
        )
        sequence += 1

    events.extend(
        (
            ObservabilityEvent(
                sequence=sequence,
                layer=ObservabilityLayer.EXECUTION,
                kind="PROPOSAL_ADMISSION",
                title="Emergency proposal admitted",
                summary=result.emergency_proposal_result.message,
                status=result.emergency_proposal_result.status.value,
                world_version=result.emergency_proposal_result.checked_world_version,
                org_version=result.emergency_proposal_result.checked_org_version,
                sender="incident_commander",
                recipient="proposal_board",
                facts=(
                    UiFact(
                        name="proposal_id",
                        value=str(result.emergency_proposal.proposal_id),
                    ),
                    UiFact(name="action_count", value=len(result.emergency_proposal.actions)),
                ),
                timestamp=result.emergency_proposal_result.timestamp,
            ),
            ObservabilityEvent(
                sequence=sequence + 1,
                layer=ObservabilityLayer.EXECUTION,
                kind="HUMAN_APPROVAL",
                title="Operator approval",
                summary=result.approval_decision.reason,
                status="APPROVED" if result.approval_decision.approved else "REJECTED",
                world_version=result.emergency_proposal.world_version,
                org_version=result.emergency_proposal.org_version,
                sender=result.approval_decision.approved_by,
                recipient="simple_executor",
                timestamp=result.approval_decision.timestamp,
            ),
        )
    )
    sequence += 2
    command_by_id = {command.command_id: command for command in _proposal_commands(result)}
    for action, command_result in zip(
        result.emergency_proposal.actions, result.command_results
    ):
        command = command_by_id.get(command_result.command_id)
        facts = (
            UiFact(name="action_type", value=action.action_type),
            UiFact(name="target_id", value=action.target_id),
            UiFact(name="evidence_count", value=len(command_result.evidence)),
        )
        events.append(
            ObservabilityEvent(
                sequence=sequence,
                layer=ObservabilityLayer.EXECUTION,
                kind="COMMAND_RESULT",
                title=f"Execute {action.action_type.replace('_', ' ')}",
                summary=command_result.message,
                status=command_result.status.value,
                world_version=(
                    command.world_version if command is not None else result.final_world_version
                ),
                org_version=result.final_org_version,
                sender="simple_executor",
                recipient=action.target_id,
                facts=facts,
                timestamp=command_result.executed_at,
            )
        )
        sequence += 1

    return ObservabilityView(
        incident_id=incident_id,
        generated_at=datetime.now(timezone.utc),
        layers=tuple(ObservabilityLayer),
        initial_mode=result.initial_mode.value,
        final_mode=result.final_mode.value,
        initial_world_version=result.initial_world_version,
        final_world_version=result.final_world_version,
        initial_org_version=result.initial_org_version,
        final_org_version=result.final_org_version,
        active_roles=result.final_organization.active_roles,
        suspended_roles=result.final_organization.suspended_roles,
        events=tuple(events),
        interactions=interactions,
        machine_changes=_machine_changes(result),
        final_weather=(
            UiFact(name="condition", value=result.final_world_state.weather.condition),
            UiFact(
                name="lightning_distance_km",
                value=result.final_world_state.weather.lightning_distance_km,
            ),
            UiFact(name="wind_speed_mps", value=result.final_world_state.weather.wind_speed_mps),
            UiFact(
                name="precipitation_level",
                value=result.final_world_state.weather.precipitation_level,
            ),
        ),
        new_tasks_frozen=result.final_world_state.new_tasks_frozen,
        audit_record_count=len(result.audit_records),
    )


def _command_event(
    *,
    sequence: int,
    command: Command,
    command_result: CommandResult,
    title: str,
    sender: str,
) -> ObservabilityEvent:
    return ObservabilityEvent(
        sequence=sequence,
        layer=ObservabilityLayer.EXECUTION,
        kind="FAST_PATH_COMMAND",
        title=title,
        summary=f"{command.command_type.value} on {command.target_id}: {command_result.message}",
        status=command_result.status.value,
        world_version=command.world_version,
        org_version=command.org_version,
        sender=sender,
        recipient="simple_executor",
        facts=(
            UiFact(name="command_type", value=command.command_type.value),
            UiFact(name="target_id", value=command.target_id),
            UiFact(name="idempotency_key", value=command.idempotency_key),
            UiFact(name="evidence_count", value=len(command_result.evidence)),
        ),
        timestamp=command_result.executed_at,
    )


def _machine_changes(result: ThunderstormDemoResult) -> tuple[MachineChange, ...]:
    initial_by_id = {
        machine.machine_id: machine for machine in result.initial_world_state.machines
    }
    changes = []
    for final in result.final_world_state.machines:
        initial = initial_by_id[final.machine_id]
        changes.append(_machine_change(initial, final))
    return tuple(changes)


def _machine_change(
    initial: FrozenMachineState,
    final: FrozenMachineState,
) -> MachineChange:
    return MachineChange(
        machine_id=final.machine_id,
        machine_type=final.machine_type,
        initial_status=initial.status,
        final_status=final.status,
        initial_zone=initial.zone,
        final_zone=final.zone,
        battery_percent=final.battery_percent,
        changed=initial.status != final.status or initial.zone != final.zone,
    )


def _proposal_commands(result: ThunderstormDemoResult) -> tuple[Command, ...]:
    """No Commands are retained by the demo; return an empty lookup helper."""
    del result
    return ()
