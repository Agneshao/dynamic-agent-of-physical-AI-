"""Authoritative operating mode and organization state schemas."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .world_state import utc_now


class OperatingMode(str, Enum):
    """The single authoritative runtime operating mode."""

    NORMAL = "NORMAL"
    WATCH = "WATCH"
    EMERGENCY = "EMERGENCY"
    RECOVERY = "RECOVERY"


class OrganizationState(BaseModel):
    """Validated organization state exclusively owned by ModeManager."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    org_version: int = Field(ge=1)
    mode: OperatingMode
    registered_roles: tuple[str, ...]
    active_roles: tuple[str, ...]
    suspended_roles: tuple[str, ...]
    reporting_graph: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    permission_profile: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    activated_at: datetime = Field(default_factory=utc_now)
    transition_id: UUID
    reason: str = Field(min_length=1)

    @field_validator("activated_at")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("activated_at must be timezone-aware")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_role_partition(self) -> OrganizationState:
        registered = set(self.registered_roles)
        active = set(self.active_roles)
        suspended = set(self.suspended_roles)
        if len(registered) != len(self.registered_roles):
            raise ValueError("registered_roles must not contain duplicates")
        if len(active) != len(self.active_roles):
            raise ValueError("active_roles must not contain duplicates")
        if len(suspended) != len(self.suspended_roles):
            raise ValueError("suspended_roles must not contain duplicates")
        if active & suspended:
            raise ValueError("active_roles and suspended_roles must not overlap")
        if active | suspended != registered:
            raise ValueError(
                "active_roles and suspended_roles must partition registered_roles"
            )
        return self
