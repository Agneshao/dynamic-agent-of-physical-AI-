"""Immutable records describing atomic organization transitions."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from runtime_core.schemas.organization import OperatingMode, OrganizationState


class TransitionStatus(str, Enum):
    """Outcome of a ModeManager transition request."""

    APPLIED = "APPLIED"
    NO_OP_TRANSITION = "NO_OP_TRANSITION"


class OrganizationTransition(BaseModel):
    """Immutable audit-friendly description of one applied transition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    transition_id: UUID
    from_mode: OperatingMode
    to_mode: OperatingMode
    from_org_version: int = Field(ge=1)
    to_org_version: int = Field(ge=2)
    activated_roles: tuple[str, ...]
    suspended_roles: tuple[str, ...]
    triggered_by: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    timestamp: datetime

    @field_validator("timestamp")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value.astimezone(timezone.utc)


class OrganizationTransitionResult(BaseModel):
    """Successful applied or no-op transition response."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: TransitionStatus
    organization: OrganizationState
    transition: Optional[OrganizationTransition]
    audit_record_id: UUID

