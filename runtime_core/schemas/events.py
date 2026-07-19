"""External event schemas accepted by the world state kernel."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EventSeverity(str, Enum):
    """Severity assigned by an external event producer."""

    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class Event(BaseModel):
    """Validated external event submitted to the world state kernel."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: UUID = Field(default_factory=uuid4)
    event_type: str = Field(min_length=1)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    severity: EventSeverity = EventSeverity.INFO
    deduplication_key: str = Field(min_length=1)

    @field_validator("timestamp")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        """Reject naive timestamps and normalize aware values to UTC."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value.astimezone(timezone.utc)

