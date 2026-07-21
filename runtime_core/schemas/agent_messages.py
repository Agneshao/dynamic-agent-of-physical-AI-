"""Immutable structured messages exchanged by synchronous logical agents."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Union
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .world_state import utc_now


class AgentMessageType(str, Enum):
    """Message types supported by the minimal synchronous team."""

    TASK_ASSIGNMENT = "TASK_ASSIGNMENT"
    SAFETY_REPORT = "SAFETY_REPORT"
    OPERATIONS_PLAN = "OPERATIONS_PLAN"
    NOTIFICATION_PLAN = "NOTIFICATION_PLAN"
    FINAL_PROPOSAL = "FINAL_PROPOSAL"
    ACKNOWLEDGEMENT = "ACKNOWLEDGEMENT"


AgentPayloadScalar = Union[str, int, float, bool, None]
AgentPayloadValue = Union[AgentPayloadScalar, tuple[AgentPayloadScalar, ...]]


class AgentPayloadField(BaseModel):
    """One stable JSON-safe payload field."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    value: AgentPayloadValue

    @field_validator("value")
    @classmethod
    def reject_non_finite_numbers(
        cls, value: AgentPayloadValue
    ) -> AgentPayloadValue:
        values = value if isinstance(value, tuple) else (value,)
        if any(isinstance(item, float) and not math.isfinite(item) for item in values):
            raise ValueError("agent payload values must contain only finite numbers")
        return value


class AgentMessage(BaseModel):
    """One version-bound message in a synchronous orchestration run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    message_id: UUID = Field(default_factory=uuid4)
    correlation_id: UUID
    incident_id: str = Field(min_length=1)
    message_type: AgentMessageType
    sender_role: str = Field(min_length=1)
    recipient_role: str = Field(min_length=1)
    world_version: int = Field(ge=0)
    org_version: int = Field(ge=1)
    objective: str = Field(min_length=1)
    payload: tuple[AgentPayloadField, ...] = ()
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("created_at")
    @classmethod
    def require_aware_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def require_unique_payload_names(self) -> AgentMessage:
        names = tuple(item.name for item in self.payload)
        if len(names) != len(set(names)):
            raise ValueError("agent payload field names must be unique")
        return self

    def get_payload(self, name: str) -> Optional[AgentPayloadField]:
        """Return one payload field without exposing a mutable container."""
        return next((item for item in self.payload if item.name == name), None)
