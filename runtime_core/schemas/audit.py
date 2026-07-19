"""Schemas for append-only runtime audit records."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator


class AuditRecordType(str, Enum):
    """Audit event types used by organization and proposal control planes."""

    ORGANIZATION_TRANSITION = "ORGANIZATION_TRANSITION"
    ORGANIZATION_TRANSITION_REJECTED = "ORGANIZATION_TRANSITION_REJECTED"
    ORGANIZATION_TRANSITION_NO_OP = "ORGANIZATION_TRANSITION_NO_OP"
    PROPOSAL_ACCEPTED = "PROPOSAL_ACCEPTED"
    PROPOSAL_REJECTED = "PROPOSAL_REJECTED"
    PROPOSAL_INVALIDATED = "PROPOSAL_INVALIDATED"


class AuditRecord(BaseModel):
    """One immutable, checksummed JSONL audit record."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    record_id: UUID
    record_type: AuditRecordType
    timestamp: datetime
    actor: str = Field(min_length=1)
    world_version: int = Field(ge=0)
    org_version: int = Field(ge=1)
    payload: dict[str, JsonValue]
    checksum: str = Field(min_length=64, max_length=64)

    @field_validator("timestamp")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value.astimezone(timezone.utc)

