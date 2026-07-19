"""Minimal immutable human approval decision schema."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .world_state import utc_now


class ApprovalDecision(BaseModel):
    """One final approval decision for a specific proposal."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    approval_id: UUID = Field(default_factory=uuid4)
    proposal_id: UUID
    approved: bool
    approved_by: str = Field(min_length=1)
    timestamp: datetime = Field(default_factory=utc_now)
    reason: str = Field(min_length=1)

    @field_validator("timestamp")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value.astimezone(timezone.utc)


def approve_proposal(
    proposal_id: UUID,
    *,
    approved: bool,
    approved_by: str,
    reason: str,
) -> ApprovalDecision:
    """Create a frozen decision without introducing an approval subsystem."""
    return ApprovalDecision(
        proposal_id=proposal_id,
        approved=approved,
        approved_by=approved_by,
        reason=reason,
    )
