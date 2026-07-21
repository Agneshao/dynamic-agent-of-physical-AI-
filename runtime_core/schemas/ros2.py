"""Transport-neutral schemas at the ROS2 integration boundary."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .world_state import FrozenMachineState, FrozenPersonState, utc_now


class Ros2MessageEnvelope(BaseModel):
    """Authenticated ROS2 message metadata plus its structured payload."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    topic: str = Field(min_length=1)
    source_node: str = Field(min_length=1)
    sequence: int = Field(ge=0)
    payload: dict[str, Any]
    observed_at: datetime = Field(default_factory=utc_now)

    @field_validator("observed_at")
    @classmethod
    def require_aware_observed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        return value.astimezone(timezone.utc)


class Ros2SensorIngestResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: UUID
    event_type: str
    topic: str
    deduplication_key: str
    previous_world_version: int = Field(ge=0)
    current_world_version: int = Field(ge=0)
    changed: bool


class Ros2CommandResponse(BaseModel):
    """Normalized response returned by a concrete ROS2 command transport."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    accepted: bool
    acknowledged: bool = True
    message: str = Field(min_length=1)
    observed_machine: Optional[FrozenMachineState] = None
    observed_person: Optional[FrozenPersonState] = None
    new_tasks_frozen: Optional[bool] = None
    observed_at: datetime = Field(default_factory=utc_now)

    @field_validator("observed_at")
    @classmethod
    def require_aware_observed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        return value.astimezone(timezone.utc)
