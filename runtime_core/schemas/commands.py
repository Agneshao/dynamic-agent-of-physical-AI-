"""Immutable schemas for version-bound runtime commands and results."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .evidence import Evidence
from .proposals import ProposalParameter
from .world_state import FrozenMachineState, FrozenPersonState, utc_now


class CommandType(str, Enum):
    """Commands supported by the stage 2C mock runtime."""

    PAUSE_MACHINE = "pause_machine"
    HOLD_POSITION = "hold_position"
    RETURN_TO_BASE = "return_to_base"
    MOVE_TO_ZONE = "move_to_zone"
    RECALL_DRONE = "recall_drone"
    FREEZE_NEW_TASKS = "freeze_new_tasks"
    NOTIFY_OPERATOR = "notify_operator"
    ALERT_PERSON = "alert_person"
    TRACK_PERSON = "track_person"


class CommandStatus(str, Enum):
    """Command definition and execution lifecycle statuses."""

    CREATED = "CREATED"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


def _normalize_aware_datetime(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


class Command(BaseModel):
    """A frozen command bound to one incident and runtime version pair."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    command_id: UUID = Field(default_factory=uuid4)
    incident_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    command_type: CommandType
    target_id: str = Field(min_length=1)
    parameters: tuple[ProposalParameter, ...] = ()
    source: str = Field(min_length=1)
    world_version: int = Field(ge=0)
    org_version: int = Field(ge=1)
    status: CommandStatus = CommandStatus.CREATED
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("created_at")
    @classmethod
    def require_aware_created_at(cls, value: datetime) -> datetime:
        return _normalize_aware_datetime(value, "created_at")

    @field_validator("status")
    @classmethod
    def require_created_status(cls, value: CommandStatus) -> CommandStatus:
        if value != CommandStatus.CREATED:
            raise ValueError("Command.status must remain CREATED")
        return value

    @model_validator(mode="after")
    def validate_idempotency_and_parameters(self) -> Command:
        expected_key = (
            f"{self.incident_id}:{self.command_type.value}:{self.target_id}"
        )
        if self.idempotency_key != expected_key:
            raise ValueError(f"idempotency_key must equal {expected_key}")
        names = tuple(parameter.name for parameter in self.parameters)
        if len(names) != len(set(names)):
            raise ValueError("command parameter names must be unique")
        return self

    def get_parameter(self, name: str) -> Optional[ProposalParameter]:
        """Return one parameter by name without exposing a mutable container."""
        return next((item for item in self.parameters if item.name == name), None)


class ExecutionReceipt(BaseModel):
    """Mock adapter acknowledgement before runtime synchronization."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    command_id: UUID
    status: CommandStatus
    message: str = Field(min_length=1)
    observed_machine: Optional[FrozenMachineState] = None
    observed_person: Optional[FrozenPersonState] = None
    new_tasks_frozen: Optional[bool] = None
    executed_at: datetime = Field(default_factory=utc_now)

    @field_validator("executed_at")
    @classmethod
    def require_aware_executed_at(cls, value: datetime) -> datetime:
        return _normalize_aware_datetime(value, "executed_at")

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: CommandStatus) -> CommandStatus:
        if value not in (
            CommandStatus.EXECUTING,
            CommandStatus.FAILED,
            CommandStatus.UNKNOWN,
        ):
            raise ValueError("receipt status must be EXECUTING, FAILED, or UNKNOWN")
        return value


class VerificationResult(BaseModel):
    """Adapter-side verification of an observed command effect."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    command_id: UUID
    status: CommandStatus
    message: str = Field(min_length=1)
    observed_machine: Optional[FrozenMachineState] = None
    observed_person: Optional[FrozenPersonState] = None
    new_tasks_frozen: Optional[bool] = None
    verified_at: datetime = Field(default_factory=utc_now)

    @field_validator("verified_at")
    @classmethod
    def require_aware_verified_at(cls, value: datetime) -> datetime:
        return _normalize_aware_datetime(value, "verified_at")

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: CommandStatus) -> CommandStatus:
        if value not in (
            CommandStatus.VERIFIED,
            CommandStatus.FAILED,
            CommandStatus.UNKNOWN,
        ):
            raise ValueError("verification status must be VERIFIED, FAILED, or UNKNOWN")
        return value


class CommandResult(BaseModel):
    """Immutable runtime result after adapter execution and optional sync."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    command_id: UUID
    status: CommandStatus
    message: str = Field(min_length=1)
    evidence: tuple[Evidence, ...] = ()
    executed_at: datetime = Field(default_factory=utc_now)

    @field_validator("executed_at")
    @classmethod
    def require_aware_executed_at(cls, value: datetime) -> datetime:
        return _normalize_aware_datetime(value, "executed_at")

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: CommandStatus) -> CommandStatus:
        if value not in (
            CommandStatus.VERIFIED,
            CommandStatus.FAILED,
            CommandStatus.UNKNOWN,
        ):
            raise ValueError("result status must be VERIFIED, FAILED, or UNKNOWN")
        return value
