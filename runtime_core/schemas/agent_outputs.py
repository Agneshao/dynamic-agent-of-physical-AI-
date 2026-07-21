"""Frozen context views and departmental emergency-agent outputs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .agent_messages import AgentMessageType, AgentPayloadField
from .organization import OperatingMode
from .proposals import Proposal, ProposalAction
from .world_state import (
    FrozenMachineState,
    FrozenPersonState,
    FrozenRouteState,
    FrozenTaskState,
    FrozenWeatherState,
    FrozenZoneState,
)


class AgentContextView(BaseModel):
    """A projected immutable view built from RoleProfile visibility settings."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    visible_fields: tuple[str, ...]
    world_version: int = Field(ge=0)
    org_version: int = Field(ge=1)
    people: Optional[tuple[FrozenPersonState, ...]] = None
    machines: Optional[tuple[FrozenMachineState, ...]] = None
    zones: Optional[tuple[FrozenZoneState, ...]] = None
    tasks: Optional[tuple[FrozenTaskState, ...]] = None
    routes: Optional[tuple[FrozenRouteState, ...]] = None
    weather: Optional[FrozenWeatherState] = None
    new_tasks_frozen: Optional[bool] = None
    incident_id: Optional[str] = None
    operator_target: Optional[str] = None
    current_mode: Optional[OperatingMode] = None


class SafetyReport(BaseModel):
    """Structured safety analysis for one incident and version pair."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    incident_id: str = Field(min_length=1)
    world_version: int = Field(ge=0)
    org_version: int = Field(ge=1)
    occupied_zones: tuple[str, ...]
    unsafe_machines: tuple[str, ...]
    required_holds: tuple[str, ...]
    risk_summary: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)


class OperationsPlan(BaseModel):
    """Structured equipment actions derived from current safety evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    incident_id: str = Field(min_length=1)
    world_version: int = Field(ge=0)
    org_version: int = Field(ge=1)
    recommended_actions: tuple[ProposalAction, ...]
    operational_summary: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)


class NotificationPlan(BaseModel):
    """Structured recipients and message category for an incident."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    incident_id: str = Field(min_length=1)
    world_version: int = Field(ge=0)
    org_version: int = Field(ge=1)
    recipients: tuple[str, ...]
    message_category: str = Field(min_length=1)
    notification_summary: str = Field(min_length=1)


class AgentInteractionRecord(BaseModel):
    """One immutable, version-bound message visible to observability clients."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: int = Field(ge=1)
    message_id: UUID
    correlation_id: UUID
    incident_id: str = Field(min_length=1)
    sender_role: str = Field(min_length=1)
    recipient_role: str = Field(min_length=1)
    message_type: AgentMessageType
    world_version: int = Field(ge=0)
    org_version: int = Field(ge=1)
    objective: str = Field(min_length=1)
    payload: tuple[AgentPayloadField, ...] = ()
    output_type: Optional[str] = None
    output_summary: Optional[str] = None
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def require_aware_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value.astimezone(timezone.utc)


class EmergencyTeamResult(BaseModel):
    """Read-only result of one synchronous emergency-team deliberation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    incident_id: str = Field(min_length=1)
    selected_roles: tuple[str, ...]
    interactions: tuple[AgentInteractionRecord, ...]
    safety_report: SafetyReport
    operations_plan: OperationsPlan
    notification_plan: NotificationPlan
    proposal: Proposal
