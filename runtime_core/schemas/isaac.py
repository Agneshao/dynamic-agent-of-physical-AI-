"""Immutable contracts for the local Runtime-to-Isaac bridge."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

from .commands import CommandType
from .world_state import utc_now


ISAAC_BRIDGE_PROTOCOL_VERSION = "1.0"


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


class IsaacBridgeResultStatus(str, Enum):
    ACKNOWLEDGED = "ACKNOWLEDGED"
    IN_PROGRESS = "IN_PROGRESS"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"
    MALFORMED = "MALFORMED"

    @property
    def terminal(self) -> bool:
        return self in {
            self.SUCCEEDED,
            self.FAILED,
            self.REJECTED,
            self.MALFORMED,
        }


class IsaacEntityObservation(BaseModel):
    """One measured Isaac entity state before canonical normalization."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    isaac_entity_id: str = Field(min_length=1)
    entity_type: str = Field(min_length=1)
    status: str = Field(min_length=1)
    zone: Optional[str] = None
    position: Optional[tuple[float, float, float]] = None
    battery_percent: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    observed_at: datetime = Field(default_factory=utc_now)

    @field_validator("observed_at")
    @classmethod
    def require_aware_observed_at(cls, value: datetime) -> datetime:
        return _aware_utc(value, "observed_at")


class IsaacCommandRequest(BaseModel):
    """Append-only request written by the Runtime adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol_version: Literal["1.0"] = ISAAC_BRIDGE_PROTOCOL_VERSION
    action_id: UUID
    command_id: UUID
    idempotency_key: str = Field(min_length=1)
    command_type: CommandType
    canonical_target_id: str = Field(min_length=1)
    isaac_target_id: str = Field(min_length=1)
    base_world_version: int = Field(ge=0)
    base_org_version: int = Field(ge=1)
    issued_at: datetime = Field(default_factory=utc_now)
    parameters: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("issued_at")
    @classmethod
    def require_aware_issued_at(cls, value: datetime) -> datetime:
        return _aware_utc(value, "issued_at")


class IsaacCommandResult(BaseModel):
    """Acknowledgement, progress, or terminal result written by Isaac."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol_version: Literal["1.0"] = ISAAC_BRIDGE_PROTOCOL_VERSION
    action_id: UUID
    command_id: UUID
    status: IsaacBridgeResultStatus
    message: str = Field(min_length=1)
    observed_at: datetime = Field(default_factory=utc_now)
    observation: Optional[IsaacEntityObservation] = None
    new_tasks_frozen: Optional[bool] = None
    error_code: Optional[str] = None

    @field_validator("observed_at")
    @classmethod
    def require_aware_observed_at(cls, value: datetime) -> datetime:
        return _aware_utc(value, "observed_at")


class IsaacBridgeState(BaseModel):
    """Latest-state and heartbeat projection written atomically by Isaac."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol_version: Literal["1.0"] = ISAAC_BRIDGE_PROTOCOL_VERSION
    heartbeat_at: datetime = Field(default_factory=utc_now)
    isaac_running: bool = True
    scenario_state: str = Field(min_length=1)
    organization_mode: str = Field(min_length=1)
    observed_plan_version: int = Field(ge=0)
    pipeline_gate: str = Field(min_length=1)
    last_action_id: Optional[UUID] = None
    new_tasks_frozen: bool = False
    hazards: dict[str, dict[str, object]] = Field(default_factory=dict)
    entities: tuple[IsaacEntityObservation, ...] = ()

    @field_validator("heartbeat_at")
    @classmethod
    def require_aware_heartbeat_at(cls, value: datetime) -> datetime:
        return _aware_utc(value, "heartbeat_at")
