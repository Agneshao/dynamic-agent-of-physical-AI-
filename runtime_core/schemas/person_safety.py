"""Person-alert acknowledgement and shelter-arrival schemas."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .world_state import utc_now


class PersonSafetySignalType(str, Enum):
    ALERT_ACKNOWLEDGED = "ALERT_ACKNOWLEDGED"
    SHELTER_ARRIVAL_VERIFIED = "SHELTER_ARRIVAL_VERIFIED"


class PersonSafetySignal(BaseModel):
    """One authenticated external observation about a person's safety progress."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    signal_id: UUID = Field(default_factory=uuid4)
    incident_id: str = Field(min_length=1)
    person_id: str = Field(min_length=1)
    signal_type: PersonSafetySignalType
    source: str = Field(min_length=1)
    deduplication_key: str = Field(min_length=1)
    shelter_zone: Optional[str] = None
    timestamp: datetime = Field(default_factory=utc_now)

    @field_validator("timestamp")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def require_expected_key_and_shelter(self) -> PersonSafetySignal:
        expected = f"{self.incident_id}:{self.signal_type.value}:{self.person_id}"
        if self.deduplication_key != expected:
            raise ValueError(f"deduplication_key must equal {expected}")
        if (
            self.signal_type == PersonSafetySignalType.SHELTER_ARRIVAL_VERIFIED
            and not self.shelter_zone
        ):
            raise ValueError("shelter arrival requires shelter_zone")
        return self


class PersonSafetyUpdateResult(BaseModel):
    """Immutable result of applying one person-safety observation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    signal_id: UUID
    incident_id: str
    person_id: str
    previous_status: str
    current_status: str
    current_zone: Optional[str]
    changed: bool
    previous_world_version: int = Field(ge=0)
    current_world_version: int = Field(ge=0)
