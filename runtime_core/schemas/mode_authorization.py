"""Human authorization contracts for entering emergency operating mode."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .organization import OperatingMode
from .world_state import utc_now


class EmergencyModeAuthorizationDecision(BaseModel):
    """One immutable human decision for a specific emergency incident."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    authorization_id: UUID = Field(default_factory=uuid4)
    incident_id: str = Field(min_length=1, max_length=128)
    target_mode: OperatingMode = OperatingMode.EMERGENCY
    approved: bool
    authorized_by: str = Field(min_length=1, max_length=128)
    authorization_method: Literal["HUMAN_OPERATOR"] = "HUMAN_OPERATOR"
    reason: str = Field(min_length=1, max_length=1000)
    timestamp: datetime = Field(default_factory=utc_now)

    @field_validator("timestamp")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def require_emergency_target(self) -> EmergencyModeAuthorizationDecision:
        if self.target_mode != OperatingMode.EMERGENCY:
            raise ValueError("emergency authorization target_mode must be EMERGENCY")
        return self
